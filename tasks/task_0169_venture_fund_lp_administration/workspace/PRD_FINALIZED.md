# Venture Fund / LP Administration API — Product Requirements Document

## 1. Introduction

This document specifies the back-office administration platform that a venture-capital firm uses to run the full economic lifecycle of its funds and their limited-partner (LP) relationships. The system is, at its heart, a double-sided ledger: every dollar an LP commits, has called against it, funds, or receives back must reconcile against the fund's aggregate position at every moment. Around that ledger sit the workflows that general partners and their administrators perform daily — forming a fund, accepting commitments, issuing capital calls and watching them settle or default, marking the portfolio, accruing management fees net of side-letter discounts and portfolio fee offsets, declaring distributions through a multi-tier waterfall, and recycling recallable proceeds back into unfunded capacity.

The platform serves four distinct constituencies whose interests deliberately do not overlap. General-partner operators drive the fund forward and own the capital-call and distribution decisions. Back-office accountants fund and default individual allocations, mark valuations, accrue fees, and pay distributions. Limited partners read their own statements and fund their own draws. Compliance staff manage side letters and LP onboarding and hold read access for audit. Because the same underlying numbers feed an LP's K-1 tax statement, the fund's reported NAV, and the GP's carried interest, the correctness of every derived figure is a contractual obligation, not a convenience — a mis-rounded fee or a mis-sequenced waterfall tier is a real economic error. The remainder of this document fixes the precise contract for each computed field, each state transition, and each guard that protects the ledger from drifting out of balance.

All monetary amounts in this system are represented as integer cents; the API never accepts or emits fractional cents. Rates are expressed in basis points (one basis point is one hundredth of one percent), so a value of `2000` denotes twenty percent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs. If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `FundManager`, `FundAdministrator`, `LimitedPartnerUser`, and `ComplianceOfficer`.

A `FundManager` is the GP-side fund operator who forms funds, runs capital calls, declares and recalls distributions, and manages the investment portfolio. A `FundAdministrator` is the back-office accountant who funds and defaults allocations, accrues fees, marks valuations, and pays distributions. A `ComplianceOfficer` manages side letters and LP onboarding and holds read access for audit. For these three roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it, but it never compares it to any entity's `id`.

A `LimitedPartnerUser`, by contrast, is entity-backed: when `X-User-Role` is `LimitedPartnerUser`, the `X-User-ID` value is the `id` of the acting `LimitedPartner`. Ownership checks on any resource that references a `LimitedPartner` compare the resource's LP foreign key to `X-User-ID`. Concretely, when a `LimitedPartnerUser` requests a commitment's statement or funds a capital-call allocation, the system resolves the targeted `Commitment` (directly, or through the allocation's `commitment_id`) and confirms that the commitment's `lp_id` equals the caller's `X-User-ID`. If it does not, the request is rejected with `ERR_NOT_COMMITMENT_OWNER` (HTTP 403). This ownership check is distinct from the role check: a caller may hold the correct role yet still be acting on a commitment that is not theirs.

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

List endpoints accept two pagination controls, `limit` and `offset`. The `limit` parameter defaults to `10`, may be no smaller than `1`, and may be no larger than `100`. The `offset` parameter defaults to `0` and may be no smaller than `0`. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400). List responses surface `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, where `total_count` is the number of records matching the query before the page window is applied and `has_more` indicates whether records remain beyond the current window. Unless a specific endpoint states otherwise, lists are returned sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix and is assigned by the server on creation; client-supplied identifiers are never honored. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, set once at creation and never altered.

All entities in this system are mutable ledger objects, and every entity additionally carries an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation to the resource; the `version` field begins at `1` on creation and increments by one each time the resource is mutated. These two fields are the basis for the optimistic-concurrency mechanism described in §2.7 and for the staleness checks woven through the distribution and capital-call workflows.

### 2.5. The Cent-Ledger Discipline and Rounding

Because the platform reconciles every figure against fund-level aggregates, the order and method of rounding are part of the contract, not an implementation detail. Wherever a calculation in this document calls for rounding, it means **round half up** to the nearest integer cent: a fractional remainder of exactly one half always rounds away from zero to the next whole cent. All stored monetary fields are integer cents.

When a single amount must be split across several recipients — a capital call across participating commitments, or an LP distribution share across commitments — the system uses the **largest-remainder method** so that the parts sum exactly to the whole and no cent is created or lost. Each recipient first receives the floor of its exact pro-rata share. The cents left over (the original amount minus the sum of those floors) are then handed out one cent at a time to the recipients with the largest fractional remainders of their exact shares. When two recipients have identical fractional remainders, the tie is broken by the recipient commitment's `created_at` in ascending order — never by `id`. This discipline guarantees that allocations reconcile to the cent against the amount being split.

### 2.6. Ledger Reconciliation and Derived Fields

Several fields are not written directly by clients but are continuously reconciled from their children, and the system recomputes them within the same request that changes their inputs. A `Fund` exposes four such totals. `total_committed_cents` is the sum of `committed_cents` across every `Commitment` on the fund whose `status` is `ACTIVE` or `DEFAULTED`. `total_called_cents` is the sum of `called_amount_cents` across the fund's capital calls whose `status` is `ISSUED`, `SETTLED`, or `PARTIALLY_DEFAULTED`. `total_distributed_cents` is the sum of `gross_amount_cents` across the fund's distribution events whose `status` is `DECLARED` or `PAID`. `recycled_to_date_cents` is the sum of `recycled_amount_cents` across the fund's distribution events whose `status` is `RECALLED`.

A `Commitment` likewise carries derived totals. Its `drawn_cents` is the sum of `paid_amount_cents` over its capital-call allocations whose `status` is `PAID`, reduced by any recycling restorations applied to that commitment. Its `distributed_cents` is the sum of `amount_cents` over its distribution allocations whose parent `DistributionEvent` has `status` `DECLARED` or `PAID`. Its `unfunded_cents` is `committed_cents` minus `drawn_cents`, floored at zero — the remaining callable capital. A `CapitalCall` carries `funded_amount_cents`, the sum of `paid_amount_cents` across its allocations whose `status` is `PAID`. A `LimitedPartner` carries `default_strike_count`, the count of that LP's capital-call allocations (across all of its commitments) whose `status` is `DEFAULTED`. An `Investment` carries `current_mark_cents`, taken from the latest `FINAL` valuation mark on that investment and equal to `cost_basis_cents` until the first `FINAL` mark exists. Whenever any of these inputs changes, the derived field is recomputed in the same request, and the owning resource's `updated_at` and `version` advance accordingly.

### 2.7. Optimistic Concurrency on Fund Version

Two write operations — issuing a capital call and declaring a distribution event — depend on the fund's cumulative ledger position and therefore guard against acting on a stale view of the fund. Each such request must include a non-optional field, `expected_fund_version`, carrying the `version` of the target `Fund` that the client last observed.

When a `FundManager` issues a capital call, the request must carry `expected_fund_version` matching the target fund's current `version`. If the fund's `version` has advanced since the client last read it — because another call was issued, a commitment was accepted, or a distribution was declared, each of which bumps the fund — the issuance is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), forcing the client to refresh before it mis-sequences the call. The same rule governs declaring a distribution event: that request, too, must carry `expected_fund_version` equal to the fund's current `version`, and a mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), because the waterfall split is computed against the fund's called and distributed totals and a stale view would price the tiers against outdated figures. Endpoints other than capital-call issuance and distribution declaration do not take a version field.

### 2.8. Path Resolution, References, and Request Validation

The platform validates a request in a fixed precedence so that the error a client receives is always the most fundamental one. Authentication (§2.1) is checked first, then role permission, then — for `LimitedPartnerUser` ownership operations — that `X-User-ID` matches the targeted commitment's `lp_id`. Next, every resource named in the path is resolved, together with every foreign key referenced in the body that is *not* governed by the referential-integrity rule of the following paragraph; this resolution proceeds left-to-right, and if any such resource does not exist, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). The body foreign keys of the three creation endpoints named in the following paragraph are the sole exception: a reference there that does not exist yields `ERR_INVALID_REFERENCE` (HTTP 422) instead, exactly as that paragraph specifies, and never `ERR_RESOURCE_NOT_FOUND`. Only then is the request body checked for the presence of required fields, correct types, and valid enum members, with a violation yielding `ERR_INVALID_REQUEST` (HTTP 400). A numeric input that is present and well-typed but outside its declared range — for example a `carry_rate_bps` above `5000`, an `ownership_pct_bps` above `10000`, or any negative cents amount — is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422). For any operation that drives a state machine, the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409).

Referential integrity beyond mere existence is enforced for the creation endpoints that knit entities together. When a commitment is created it must reference a `Fund` and a `LimitedPartner` that both exist; when an investment is created it must reference a `Fund` and a `PortfolioCompany`; when a side letter is created it must reference a `Fund` and a `LimitedPartner`. A reference that points at a non-existent or incompatible parent is rejected with `ERR_INVALID_REFERENCE` (HTTP 422). This ordering means a state-machine violation never masks a missing resource, and a range violation never masks a malformed body.

## 3. Business Logic & Workflows

### 3.1. Forming and Steering a Fund

A `FundManager` begins by creating a `Fund`, supplying its `name`, `vintage_year`, and `target_size_cents`, together with the economic terms that govern every downstream computation: the annual management-fee rate `mgmt_fee_rate_bps` on committed capital, the GP carried-interest rate `carry_rate_bps` charged on profit above the preferred return, and the LP preferred (hurdle) return rate `pref_rate_bps` per annum. Three further terms are optional at creation and carry defaults when omitted: `gp_catchup_rate_bps`, the GP's catch-up share applied in the waterfall and defaulting to `10000` (a full one-hundred-percent catch-up); `recycling_cap_pct_bps`, the ceiling on recyclable distributions expressed as basis points of total committed capital and defaulting to `0`; and `fee_offset_pct_bps`, the share of portfolio-company fees that offsets LP management fees and defaulting to `0`. A `target_size_cents` of zero or more is accepted. The newly created fund begins in `FORMING` status with `version` `1`.

A fund advances through its lifecycle on the manager's command. Activation moves the fund from `FORMING` to `INVESTING`, but only once at least one `Commitment` on the fund has reached `ACTIVE` status; an attempt to activate a fund with no accepted commitment is rejected with `ERR_COMMITMENT_NOT_ACCEPTED` (HTTP 409). Beginning the harvest period moves a fund from `INVESTING` to `HARVESTING`. Each of these two transitions increments the fund's `version` by one. Winding down moves the fund from `HARVESTING` to `WOUND_DOWN`, which is terminal, and it is the most heavily guarded transition: it is permitted only when no `CapitalCall` on the fund is still in `ISSUED` status and no `Investment` on the fund is still `ACTIVE`. If either condition fails — an outstanding issued call or a still-active investment — the wind-down is blocked with `ERR_WIND_DOWN_BLOCKED` (HTTP 409). When wind-down does succeed, every `Commitment` on the fund still in `ACTIVE` status is cascaded to `CLOSED`, and the fund's `version` increments by one.

Beyond its stored terms, a fund answers two computed reads. One returns the fund's current economic snapshot — its NAV in cents alongside `total_called_cents`, `total_distributed_cents`, and `recycled_to_date_cents`. The fund NAV is the sum of `current_mark_cents` across the fund's investments whose `status` is `ACTIVE` or `IMPAIRED`. Funds may also be listed and filtered by `status`.

### 3.2. Onboarding Limited Partners and Their Commitments

A `LimitedPartner` record is created by a `FundAdministrator` or a `ComplianceOfficer` and captures the investor's `legal_name`, its `lp_type` classification — one of `INDIVIDUAL`, `INSTITUTION`, `FUND_OF_FUNDS`, or `SOVEREIGN` — and the `tax_id_last4` digits printed on the K-1. The optional `is_tax_exempt` flag defaults to `false` and later governs the UBTI flag on tax statements. The LP's `default_strike_count` is maintained by the system and starts at zero.

A `Commitment` ties one LP to one fund and is created by a `FundManager` or `FundAdministrator` with a payload naming the `fund_id`, the `lp_id`, and the `committed_cents` the LP pledges, which must be at least `1` cent. A commitment is born in `PENDING` status. Accepting it — an action reserved to the `FundManager` — moves it from `PENDING` to `ACTIVE`, but only while the owning fund is in `FORMING` or `INVESTING` status; acceptance recomputes the fund's `total_committed_cents`. A commitment exposes its running ledger through `drawn_cents`, `distributed_cents`, and `unfunded_cents`, all derived as described in §2.6, and may be read individually or listed and filtered by `fund_id`, `lp_id`, or `status`.

An `ACTIVE` commitment may be declared in default by the `FundManager`, moving it from `ACTIVE` to `DEFAULTED`. This is permitted only when the owning LP has reached the strike limit — that is, when the LP's `default_strike_count` is at least one (the system tolerates no missed draws before default becomes available). Declaring the default cascades: every `CapitalCallAllocation` on that commitment still in `PENDING` status is moved to `DEFAULTED`, and each affected parent `CapitalCall` is re-evaluated and may move from `ISSUED` to `PARTIALLY_DEFAULTED` as described in §3.3.

### 3.3. Capital Calls, Allocation, Funding, and Default

When a `FundManager` issues a capital call against a fund, the request names the `fund_id`, the drawdown `purpose` — one of `INVESTMENT`, `MANAGEMENT_FEE`, or `EXPENSE` — the aggregate `called_amount_cents` requested (at least `1` cent), the `due_date` by which allocations must be funded, and the `expected_fund_version` that anchors the optimistic-concurrency check of §2.7. The `due_date` must be a valid date that is not in the past; a `due_date` that is already past, like any malformed period, is rejected with `ERR_INVALID_PERIOD` (HTTP 422). On issuance the call is assigned the next monotonic `call_number` for that fund (1, 2, 3, and so on), enters `ISSUED` status, and the fund's `version` increments by one.

Issuance splits the requested amount across the fund's participating commitments. A commitment participates when its `status` is `ACTIVE`, its `unfunded_cents` is greater than zero, and its LP is not excused from this call's `purpose` by an executed side letter (see §3.6). The aggregate `called_amount_cents` must not exceed the sum of `unfunded_cents` across those participating commitments; if it does, the call is rejected with `ERR_CALL_EXCEEDS_UNFUNDED` (HTTP 422). If filtering for participation leaves no eligible commitment at all, the call is rejected with `ERR_NO_PARTICIPATING_COMMITMENTS` (HTTP 422). Given a valid participant set, each participating commitment's exact share is the `called_amount_cents` multiplied by that commitment's `unfunded_cents` and divided by the total participating `unfunded_cents`. Each commitment first receives the floor of its exact share as its `allocated_amount_cents`; the leftover cents — the called amount minus the sum of those floors — are then distributed one cent each to the commitments with the largest fractional remainders, ties broken by the commitment's `created_at` in ascending order, exactly as the cent-ledger discipline of §2.5 prescribes. No commitment is ever allocated more than its own `unfunded_cents`. Each resulting `CapitalCallAllocation` records its `capital_call_id`, its `commitment_id`, the computed `allocated_amount_cents`, a `paid_amount_cents` that starts at `0`, and a `status` of `PENDING`.

Funding an allocation is shared between a `FundAdministrator` and the owning `LimitedPartnerUser`, and moves the allocation from `PENDING` to `PAID`. Funding is all-or-nothing: the supplied `paid_amount_cents` must equal the allocation's `allocated_amount_cents`, and any other value — partial funding — is rejected with `ERR_PARTIAL_FUNDING_NOT_ALLOWED` (HTTP 422). On a successful funding the allocation's `paid_amount_cents` is set to its `allocated_amount_cents`, the owning commitment's `drawn_cents` is recomputed, and the parent call may settle: once every allocation of an `ISSUED` call has reached `PAID` or `WAIVED`, the call bubbles up from `ISSUED` to `SETTLED` and its `funded_amount_cents` is recomputed. A call sitting in `PARTIALLY_DEFAULTED` settles by the same rule once every one of its non-`DEFAULTED` allocations is `PAID` or `WAIVED`, moving from `PARTIALLY_DEFAULTED` to `SETTLED`.

Defaulting an allocation is reserved to the `FundAdministrator` and moves the allocation from `PENDING` to `DEFAULTED`. Doing so recomputes the owning LP's `default_strike_count` and re-evaluates the parent call. If, after the default, at least one allocation of the call is `DEFAULTED` while at least one other remains `PAID` or `PENDING`, the call moves from `ISSUED` to `PARTIALLY_DEFAULTED`. If instead every allocation of the call is now `DEFAULTED`, the call moves from `ISSUED` to `DEFAULTED`. The same `ISSUED → PARTIALLY_DEFAULTED` transition is what the commitment-default cascade of §3.2 triggers when it flips pending allocations to `DEFAULTED`.

A `FundManager` may cancel a call that is still `ISSUED` provided none of its allocations has yet been `PAID`; cancellation moves the call from `ISSUED` to `CANCELLED` and cascades every one of its allocations to `WAIVED`. Allocations may be read individually, listed and filtered by `commitment_id`, `capital_call_id`, or `status`, and a call's allocations may be listed as a sub-resource of the call.

### 3.4. Marking the Portfolio and Realizing Investments

A `FundManager` records a `PortfolioCompany` with its `name` and `sector`; the company starts as a `PROSPECT`. When the manager records an `Investment` — naming the `fund_id`, the `portfolio_company_id`, the `cost_basis_cents` deployed (at least `1` cent), and the fully-diluted `ownership_pct_bps` (between `1` and `10000`) — the investment is created `ACTIVE`, its `realized_proceeds_cents` initialized to `0`, and the company moves from `PROSPECT` to `HELD`. Investments may be read with their `current_mark_cents` and listed or filtered by `fund_id`, `portfolio_company_id`, or `status`.

Valuations flow through a review cycle owned by the `FundAdministrator`. A draft mark is created against an investment with its `investment_id`, an `as_of_date`, a proposed `fair_value_cents` (zero or more), and a `methodology` of `LAST_ROUND`, `DCF`, `COMPARABLES`, or `WRITE_OFF`; it begins in `DRAFT` status. The `as_of_date` may not be after the moment of the request; a future-dated mark is rejected with `ERR_INVALID_PERIOD` (HTTP 422). Finalizing a draft moves it from `DRAFT` to `FINAL` and is permitted only while the owning `Investment` is `ACTIVE`. Before a mark may be finalized, its `as_of_date` must be strictly later than the `as_of_date` of the investment's current `FINAL` mark; an equal or earlier date collides and is rejected with `ERR_MARK_DATE_CONFLICT` (HTTP 409), which prevents a back-dated mark from superseding a newer one. Finalization cascades: any prior mark on the same investment still in `FINAL` status is moved to `SUPERSEDED`, and the investment's `current_mark_cents` is recomputed from the newly final mark. If the finalized mark's `methodology` is `WRITE_OFF`, the cascade reaches further — the owning `Investment` moves to `IMPAIRED` and the owning `PortfolioCompany` moves to `WRITTEN_OFF`. Marks may be read or listed and filtered by `investment_id` or `status`.

Realizing an investment is the `FundManager`'s act of crystallizing an exit. It moves the investment from `ACTIVE` to `REALIZED`, records the supplied `realized_proceeds_cents`, and moves the owning company from `HELD` to `EXITED`. Realization is the gate for distributions: a distribution may only draw on the proceeds of a realized investment, as §3.5 makes precise.

### 3.5. Distributions, the Waterfall, and Clawback

Declaring a distribution is a `FundManager` operation that names the `fund_id`, the `source_investment_id` whose proceeds are being returned, the `gross_amount_cents` to distribute (at least `1` cent), the `distribution_type` — `RETURN_OF_CAPITAL`, `CAPITAL_GAIN`, or `INCOME` — an optional `recyclable` flag defaulting to `false`, and the `expected_fund_version` for the optimistic-concurrency guard of §2.7. The source investment must be in `REALIZED` status; declaring against an unrealized investment is rejected with `ERR_SOURCE_NOT_REALIZED` (HTTP 422). The `gross_amount_cents` must not exceed the realized proceeds still available on the source investment — that is, its `realized_proceeds_cents` less the amounts already distributed from it; an over-draw is rejected with `ERR_DISTRIBUTION_EXCEEDS_PROCEEDS` (HTTP 422). A successful declaration creates the event in `DECLARED` status and increments the fund's `version` by one.

On declaration the system runs the four-tier American-style waterfall against the fund's cumulative economics, evaluating the tiers strictly in order, each tier consuming from a running remainder that begins at the event's `gross_amount_cents`. Let the fund's paid-in capital be its `total_called_cents` and the prior distributions be its `total_distributed_cents` as they stand before this event. The accrued preferred return is the paid-in capital multiplied by `pref_rate_bps`, divided by `10000`, multiplied by the number of preferred years elapsed (a simple, non-compounding accrual where the preferred years are derived from the fund's `vintage_year` through to the event date), rounded half up to whole cents.

The first tier returns capital: the return-of-capital due is the paid-in capital minus prior distributions, floored at zero, and tier one pays the lesser of the remaining amount and that figure, then reduces the remainder. The second tier pays the preferred return: the preferred due is the accrued preferred minus any prior gains already returned to LPs (that is, minus the amount by which prior distributions exceeded paid-in capital, floored at zero), floored at zero; tier two pays the lesser of the remainder and that figure, then reduces the remainder. The third tier is the GP catch-up. Its target is tier two multiplied by `carry_rate_bps`, divided by the quantity `10000` minus `carry_rate_bps`, rounded half up; the catch-up actually taken is that target multiplied by `gp_catchup_rate_bps`, divided by `10000`, rounded half up, but never more than the remainder, and the remainder is reduced by what is taken. The fourth tier splits whatever remains: the GP carry portion is the remainder multiplied by `carry_rate_bps`, divided by `10000`, rounded half up, and the LP portion is the remainder minus that GP portion. Each tier's rounding is applied as that tier is computed. The event's `lp_share_cents` is the sum of tier one, tier two, and the LP portion of tier four; its `gp_carry_cents` is the sum of the tier-three catch-up and the GP portion of tier four.

A clawback adjustment applies when, after this event, the LPs' cumulative receipts still fall short of the cumulative preferred floor. The cumulative LP receipts including this event are compared against the accrued preferred; if the receipts are below the preferred floor, the shortfall is the accrued preferred minus those cumulative LP receipts. The event's `gp_carry_cents` is reduced by that shortfall, floored at zero, the clawed-back amount is added to the event's `lp_share_cents`, and every `DistributionAllocation` of this event has its `clawback_flag` set to true. When no shortfall exists, `clawback_flag` remains false on every allocation.

Having computed the LP share, the system splits `lp_share_cents` across commitments pro-rata by paid-in capital. The eligible commitments are those whose `status` is `ACTIVE` or `DEFAULTED` and whose `drawn_cents` is greater than zero; if that set is empty the split has no recipients and the declaration is rejected with `ERR_NO_PARTICIPATING_COMMITMENTS` (HTTP 422). Each eligible commitment's exact share is `lp_share_cents` multiplied by that commitment's `drawn_cents` divided by the total eligible `drawn_cents`; each receives the floor of its exact share as the allocation's `amount_cents`, and the leftover cents are handed out one cent at a time to the largest fractional remainders, ties broken by the commitment's `created_at` ascending — the same largest-remainder discipline of §2.5. Each `DistributionAllocation` records its `distribution_event_id`, its `commitment_id`, the computed `amount_cents`, and its `clawback_flag`.

Paying a declared distribution is a `FundAdministrator` action, permitted only once every allocation of the event has been assigned an amount (the event was split). Payment moves the event from `DECLARED` to `PAID`, recomputes `distributed_cents` on each commitment named by an allocation, and recomputes the fund's `total_distributed_cents`. A `FundManager` may instead reverse a still-`DECLARED` event, moving it from `DECLARED` to `REVERSED` and zeroing the `amount_cents` on all of its allocations; because the event never reached `PAID`, no commitment's `distributed_cents` drifts. Distribution events and their allocations may be read individually and listed — events by `fund_id`, `source_investment_id`, or `status`, and allocations by `commitment_id` or `distribution_event_id`.

### 3.6. Recycling: Recalling Distributions into Unfunded Capacity

Recycling lets a fund recall a previously paid distribution back into its LPs' unfunded capacity, so the same capital can be deployed again. A `FundManager` recalls an event, moving it from `PAID` to `RECALLED`, but only when the event's `recyclable` flag is true and the recall stays within the fund's recycling cap. The cap, in cents, is the fund's `recycling_cap_pct_bps` multiplied by its `total_committed_cents`, divided by `10000`, rounded half up; the remaining headroom is that cap minus the fund's `recycled_to_date_cents`, floored at zero. The amount actually recallable is the lesser of the event's `lp_share_cents` and that headroom. If the recallable amount is not positive — that is, the headroom is already exhausted so that the recycled-to-date plus this recall would breach the cap — the recall is rejected with `ERR_RECYCLING_CAP_EXCEEDED` (HTTP 422). When the recall proceeds, the event's `recycled_amount_cents` is set to the recallable amount.

The recalled capital is restored to commitments in proportion to what each received from this very event. For each `DistributionAllocation` of the event, that commitment's restoration share is the recallable amount multiplied by the allocation's `amount_cents`, divided by the event's `lp_share_cents`, rounded half up, but never more than the commitment's current `drawn_cents` (a commitment's drawn capital is never pushed below zero). Each affected commitment's `drawn_cents` is reduced by its restoration share, which correspondingly restores its `unfunded_cents`, and the fund's `recycled_to_date_cents` is recomputed to reflect the recall.

### 3.7. Side Letters, MFN Precedence, and Excused Purposes

A `ComplianceOfficer` negotiates `SideLetter` terms that bend the standard fund economics for a particular LP. A side letter names the `fund_id` and the `lp_id` it covers, an `mfn_rank` (its most-favored-nation rank, at least `1`, where a lower rank takes precedence when terms conflict), an optional `fee_discount_bps` reduction to that LP's management fee (defaulting to `0`), and an optional `excused_purposes` array listing the `CapitalCall.purpose` values from which the LP is excused from funding (defaulting to the empty list). A side letter starts as `PROPOSED`. The `mfn_rank` must be unique on the fund among side letters that are `PROPOSED` or `EXECUTED`; a collision is rejected with `ERR_MFN_RANK_TAKEN` (HTTP 409). Executing a side letter moves it from `PROPOSED` to `EXECUTED`, which is the point at which its terms take effect — only an `EXECUTED` side letter excuses an LP from a call's purpose or discounts that LP's fee. A side letter that is retired moves to the `TERMINATED` state, at which point its terms no longer apply. Side letters may be read or listed and filtered by `fund_id`, `lp_id`, or `status`.

The excused-purpose term feeds directly into capital-call allocation. When an LP holds an `EXECUTED` side letter whose `excused_purposes` contains the call's `purpose`, that LP's commitment is dropped from the participant set entirely, and its would-be share is redistributed pro-rata among the remaining commitments rather than being left unfunded — so the full `called_amount_cents` is still raised from the non-excused participants.

### 3.8. Management Fees, Offsets, and LP Statements

A `FundAdministrator` accrues a management fee for a period by supplying the `period_start` and `period_end` that bound it. The period is half-open — inclusive of the start and exclusive of the end — and `period_end` must be strictly after `period_start`, failing which the request is rejected with `ERR_INVALID_PERIOD` (HTTP 422). A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409). The accrual is created in `ACCRUED` status.

The gross fee is computed per commitment and then summed, and the order matters: the rounding is applied to each commitment's contribution before the contributions are added together, never sum-then-round. The day count is the whole number of days between `period_start` and `period_end` over the half-open interval. For each `Commitment` on the fund whose `status` is `ACTIVE`, its effective rate in basis points is the fund's `mgmt_fee_rate_bps` minus that LP's side-letter discount (the `fee_discount_bps` from the LP's executed side letter on the fund), floored at zero. That commitment's contribution is its `committed_cents` multiplied by the effective rate, divided by `10000`, multiplied by the day count, divided by `365` days per year, rounded half up to whole cents. The accrual's `gross_fee_cents` is the sum of those per-commitment rounded contributions.

The fee offset is a variant applied on the same accrual. A `MANAGEMENT_FEE` capital call qualifies for this accrual when its `due_date` falls within the half-open accrual interval — that is, when `period_start` ≤ `due_date` < `period_end` (the call's `due_date` is the temporal anchor used to decide whether it falls in the accrual period; a `CapitalCall` carries no separate `period` field). When the fund's `fee_offset_pct_bps` is greater than zero and the fund has at least one such qualifying `MANAGEMENT_FEE` call, the offset is the lesser of the gross fee and the following figure: the sum of `called_amount_cents` across those qualifying `MANAGEMENT_FEE` calls, multiplied by the fund's `fee_offset_pct_bps`, divided by `10000`, rounded half up. That figure is stored as `offset_applied_cents`. The `net_fee_cents` is then the `gross_fee_cents` minus `offset_applied_cents`, floored at zero. Absent the offset — when `fee_offset_pct_bps` is zero or no qualifying management-fee call exists — `offset_applied_cents` is `0` and `net_fee_cents` equals `gross_fee_cents`. An accrual begins in `ACCRUED` status and may subsequently be billed (moving to `INVOICED`), settled (moving to `PAID`), or unwound (moving to `REVERSED`); only a non-`REVERSED` accrual counts toward the period-overlap guard above. Fee accruals may be read individually and listed as a sub-resource of the fund, filtered by `status`.

Finally, an LP-facing statement renders the K-1 and performance figures for a single commitment, and the owning `LimitedPartnerUser` may read only its own. The statement reports paid-in capital as the commitment's `drawn_cents` and `distributed_cents` directly. The commitment's share of fund NAV is the fund NAV multiplied by the commitment's `committed_cents` divided by the fund's `total_committed_cents`, rounded half up — where fund NAV is the sum of `current_mark_cents` across the fund's investments that are `ACTIVE` or `IMPAIRED`. The distributions-to-paid-in ratio (`dpi_bps`) is the distributed amount multiplied by `10000` divided by paid-in capital, and the total-value-to-paid-in ratio (`tvpi_bps`) is the distributed amount plus NAV, multiplied by `10000`, divided by paid-in capital; both ratios are integer basis points and both are zero when paid-in capital is zero. The K-1 line items sum the LP's distribution-allocation amounts on `PAID` events by type: the return-of-capital line totals the allocations from `RETURN_OF_CAPITAL` events, the capital-gain line totals those from `CAPITAL_GAIN` events, and the income line totals those from `INCOME` events. The UBTI flag on the statement is true exactly when the LP's `is_tax_exempt` is true and its income line is greater than zero.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; reads, list queries, and state-transition or computation operations that modify or inspect an existing resource return HTTP 200. The summary below gives the HTTP contract only; the request payloads, computed fields, and side effects for each operation are specified in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/funds` | Create a fund. | FundManager |
| GET | `/funds/{id}` | Read a fund with computed totals. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/funds` | List funds (paginated). | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/funds/{id}/activate` | Move a fund from FORMING to INVESTING. | FundManager |
| POST | `/funds/{id}/begin-harvest` | Move a fund from INVESTING to HARVESTING. | FundManager |
| POST | `/funds/{id}/wind-down` | Move a fund from HARVESTING to WOUND_DOWN; cascade-close active commitments. | FundManager |
| GET | `/funds/{id}/nav` | Computed read of fund NAV and cumulative totals. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/limited-partners` | Create an LP record. | FundAdministrator, ComplianceOfficer |
| GET | `/limited-partners/{id}` | Read an LP. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/commitments` | Create a commitment linking an LP to a fund. | FundManager, FundAdministrator |
| GET | `/commitments/{id}` | Read a commitment with computed ledger fields. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/commitments` | List/filter commitments. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/commitments/{id}/accept` | Accept a commitment (PENDING to ACTIVE). | FundManager |
| POST | `/commitments/{id}/declare-default` | Declare an active commitment defaulted. | FundManager |
| GET | `/commitments/{id}/statement` | Computed LP statement / K-1 figures. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/capital-calls` | Issue a capital call (OCC on the fund). | FundManager |
| GET | `/capital-calls/{id}` | Read a capital call. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/capital-calls` | List/filter capital calls. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/capital-calls/{id}/cancel` | Cancel an issued call with no paid allocations. | FundManager |
| GET | `/capital-calls/{id}/allocations` | List allocations of a call. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/capital-call-allocations/{id}` | Read an allocation. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/capital-call-allocations` | List/filter allocations. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/capital-call-allocations/{id}/fund` | Fund an allocation in full. | FundAdministrator, LimitedPartnerUser |
| POST | `/capital-call-allocations/{id}/default` | Mark an allocation defaulted. | FundAdministrator |
| POST | `/portfolio-companies` | Create a portfolio company. | FundManager |
| GET | `/portfolio-companies/{id}` | Read a portfolio company. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/investments` | Record an investment into a portfolio company. | FundManager |
| GET | `/investments/{id}` | Read an investment with current mark. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/investments` | List/filter investments. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/investments/{id}/realize` | Realize an investment with cash proceeds. | FundManager |
| POST | `/valuation-marks` | Create a draft valuation mark. | FundAdministrator |
| GET | `/valuation-marks/{id}` | Read a valuation mark. | FundManager, FundAdministrator, ComplianceOfficer |
| GET | `/valuation-marks` | List/filter valuation marks. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/valuation-marks/{id}/finalize` | Finalize a draft mark and supersede prior finals. | FundAdministrator |
| POST | `/funds/{id}/fee-accruals` | Accrue a management fee for a period. | FundAdministrator |
| GET | `/funds/{id}/fee-accruals` | List fee accruals of a fund. | FundManager, FundAdministrator, ComplianceOfficer |
| GET | `/fee-accruals/{id}` | Read a fee accrual. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/distribution-events` | Declare a distribution (OCC on the fund). | FundManager |
| GET | `/distribution-events/{id}` | Read a distribution event with waterfall results. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/distribution-events` | List/filter distribution events. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/distribution-events/{id}/pay` | Pay a declared distribution. | FundAdministrator |
| POST | `/distribution-events/{id}/recall` | Recall a paid recyclable distribution. | FundManager |
| POST | `/distribution-events/{id}/reverse` | Reverse a declared distribution. | FundManager |
| GET | `/distribution-allocations/{id}` | Read a distribution allocation. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| GET | `/distribution-allocations` | List/filter distribution allocations. | FundManager, FundAdministrator, ComplianceOfficer, LimitedPartnerUser |
| POST | `/side-letters` | Create a side letter granting LP-specific terms. | ComplianceOfficer |
| GET | `/side-letters/{id}` | Read a side letter. | FundManager, FundAdministrator, ComplianceOfficer |
| GET | `/side-letters` | List/filter side letters. | FundManager, FundAdministrator, ComplianceOfficer |
| POST | `/side-letters/{id}/execute` | Execute a proposed side letter. | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_COMMITMENT_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_FEE_PERIOD_OVERLAP` | 409 |
| `ERR_MARK_DATE_CONFLICT` | 409 |
| `ERR_MFN_RANK_TAKEN` | 409 |
| `ERR_PARTIAL_FUNDING_NOT_ALLOWED` | 422 |
| `ERR_CALL_EXCEEDS_UNFUNDED` | 422 |
| `ERR_DISTRIBUTION_EXCEEDS_PROCEEDS` | 422 |
| `ERR_RECYCLING_CAP_EXCEEDED` | 422 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_SOURCE_NOT_REALIZED` | 422 |
| `ERR_COMMITMENT_NOT_ACCEPTED` | 409 |
| `ERR_NO_PARTICIPATING_COMMITMENTS` | 422 |
| `ERR_WIND_DOWN_BLOCKED` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |

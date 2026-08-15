# Community Foundation Funds API — Product Requirements Document

## 1. Introduction

A community foundation operates as a steward of charitable capital: it establishes funds on behalf of donors, accepts gifts ranging from wire transfers to parcels of real property, invests balances in commingled pools, vets the organizations that receive grants, and reports annually to the families and committees who entrusted it with those assets. This document specifies the API through which foundation staff, fund advisors, scholarship applicants, and committee members perform that work. The system covers fund establishment under formal agreement terms (donor-advised, designated, and scholarship funds), contribution acceptance including complex non-cash assets, investment pool allocation with unit-based accounting, grant recommendation review with grantee due diligence, spending policy and administrative fee assessment, advisor succession with inactivity and dormancy handling, scholarship committee scoring and award disbursement, and annual statement generation with impact reporting.

Two concerns dominate the design. The first is fiduciary: every dollar is accounted for on a fund-level cash ledger that is credited when gifts are accepted or liquidated and debited when grants, awards, and administrative fees are paid, and every investment position is expressed in pool units whose price derives from a marked-to-market net asset value. The second is governance: grant approval and payment are separated across distinct officers, expenditure-responsibility acknowledgements are collected where the tax code demands them, advisor succession follows the executed agreement rather than ad-hoc intervention, and dormant balances are swept according to a published policy. All time-dependent behavior in the system is driven by a controllable logical clock rather than wall-clock time, so that inactivity thresholds, clearance expirations, and application windows are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. The system recognizes nine roles: `FoundationAdmin`, `GiftOfficer`, `ComplianceOfficer`, `FinanceOfficer`, `ProgramOfficer`, `InvestmentManager`, `Advisor`, `Applicant`, and `CommitteeMember`. A request missing either header, or carrying a role name outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The interpretation of `X-User-ID` depends on the role. When `X-User-Role` is `FoundationAdmin`, `GiftOfficer`, `ComplianceOfficer`, `FinanceOfficer`, `ProgramOfficer`, or `InvestmentManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as the claiming officer or the approving officer recorded on a grant — but does not compare it to any entity's `id`. Segregation-of-duties checks compare these opaque identifiers against each other, never against entity rows.

When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting `FundAdvisor`; ownership checks on any resource that references a `FundAdvisor` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `ScholarshipApplication`; ownership checks on award responses compare the application's `id` to `X-User-ID`. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting `CommitteeMember`, and self-service actions such as recusal compare the member row's `id` to `X-User-ID`.

Role duties in brief: a `FoundationAdmin` establishes funds, drafts and executes agreements, invites and revokes advisors, activates and closes funds, generates and delivers annual statements, and controls the logical clock. A `GiftOfficer` records pledges, documents asset lots, and accepts, declines, and liquidates contributions. A `ComplianceOfficer` registers grantees, runs due diligence, and claims, approves, returns, denies, and cancels grants — with the constraint that the approving officer is never the officer who claimed the review. A `FinanceOfficer` disburses approved grants and accepted awards, records market value snapshots, runs spending policy, assesses fees, and shares unitization bookkeeping with the `InvestmentManager`, who owns the investment pool lifecycle. A `ProgramOfficer` runs scholarship programs and committees. An `Advisor` recommends grants on donor-advised funds and reads fund statements. An `Applicant` submits scholarship applications and answers award offers. A `CommitteeMember` scores applications and may recuse themselves.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100 — a value outside the bounds is clamped to the nearest bound rather than rejected, and an unparseable `limit` or `offset` falls back to its default. The `offset` parameter specifies how many items to skip and defaults to 0, with negative values clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on an identical creation timestamp broken by insertion order, earliest inserted first.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources — funds, agreements, advisors, contributions, pools, pool holdings, grantees, grant recommendations, scholarship programs, committee members, applications, and awards — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource, including modifications performed as side effects of operations on other resources.

Ledger-style records are the exception. An asset lot, a unitization event, a disbursement, a spending policy run, a market value snapshot, a fee assessment, a score entry, and an annual statement each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these record types. Two later in-place writes exist — an asset lot's `gross_proceeds` is recorded on the lot at liquidation, and an annual statement's status advances from `GENERATED` to `DELIVERED` on delivery — but neither maintains `updated_at` or `version`, and no endpoint otherwise mutates these records in place after creation.

### 2.5. The Logical Clock and Scheduled State Evaluation

The server keeps a logical clock that is decoupled from wall-clock time. Before any client call, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `FoundationAdmin` advances it through an administrative capability that accepts a target instant, supplied as `to_iso8601`, and answers with the resulting `current_utc`. Every timestamp the server assigns — gift dates, agreement execution stamps, activity markers, clearance stamps — is read from this clock.

Advancing the clock is never a no-op for state: each advance evaluates time-based automatic transitions across the whole foundation. A donor-advised fund whose inactivity has reached its trigger lapses from `ACTIVE` to `INACTIVE`, and an already-inactive fund whose inactivity has reached the deeper dormancy threshold lapses to `DORMANT`. A cleared grantee whose clearance has aged a full twelve months lapses from `CLEARED` to `EXPIRED`. Section 3 specifies each of these transitions and its consequences.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. Each identifier in the path is confirmed to exist before the next is examined, and the request is rejected with a 404 carrying `ERR_NOT_FOUND` at the first identifier that does not resolve. The canonical orderings are fund before contribution before lot, pool before unitization event, and program before application before score entry; a request naming a contribution under a nonexistent fund therefore fails on the fund before the contribution is ever consulted.

Identifiers carried in the request body are checked immediately after path existence. A creation payload that references a `fund_id`, `grantee_id`, advisor id, `member_id`, `application_id`, or a list of `winner_application_ids` that does not correspond to an existing resource is rejected with a 404 carrying `ERR_REFERENCE_NOT_FOUND`.

### 2.7. Monetary and Unit Precision

All dollar amounts in the system — balances, fees, grant amounts, proceeds, allowances — are handled with decimal arithmetic and stored and returned at exactly 2 decimal places, using round-half-up whenever a computed value must be rounded. Pool units and pool unit prices are carried at 4 decimal places, likewise rounded half-up. Monetary and unit values appear in response bodies as JSON numbers, not strings.

Several calculations round at more than one step (an average followed by a rate multiplication, an annual fee followed by a quarterly division, a per-lot fee followed by a sum). Wherever §3 describes such a calculation, the stated rounding order is normative: rounding in a different order yields different cents and is non-conformant.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to the `version` of a parent entity, and no other endpoint accepts a version field:

- Creating a grant recommendation requires the request to carry `expected_fund_version`, holding the target fund's `version` as the client last observed it. A fund's version advances whenever its ledger or derived fields change — a fee assessment, a disbursement, a contribution acceptance, and even another grant creation all move it — so a client whose read is behind the server's state is proposing against a `spendable_balance` it has not seen. If `expected_fund_version` does not match the fund's current `version`, the creation is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412).
- Recording a `BUY_IN` or `REDEMPTION` unitization event requires the request to carry `expected_pool_version` matching the target pool's current `version`, because the unit price is a function of `nav` and `units_outstanding` that a prior mutation may have changed. A mismatch is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412). `MARK_TO_MARKET` events are exempt from this requirement — they reprice the pool rather than transact at a previously observed price — and do not carry the expected-version field.
- Creating an agreement for a fund that already has an `EXECUTED` agreement is an amendment, and the request must carry `expected_fund_version` matching the fund's current `version`; a mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412). The first agreement created on a fund — one drafted while no executed agreement exists — does not require the field, since no incumbent terms are being superseded.

### 2.9. Validation Order of Evaluation

When several checks could reject the same request, they are evaluated in a fixed order, and the earliest failing check determines the error returned. The order is: (1) presence and validity of the user context headers, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) role permission on the endpoint, failing with `ERR_FORBIDDEN`; (3) existence of path identifiers, left to right, failing with `ERR_NOT_FOUND`; (4) existence of request-body references, failing with `ERR_REFERENCE_NOT_FOUND`; (5) legality of the target resource's state for the requested transition, failing with `ERR_INVALID_STATE` or the more specific state error named in §3; (6) optimistic concurrency where §2.8 requires it, failing with `ERR_STALE_FUND_VERSION` or `ERR_STALE_POOL_VERSION`; (7) time-window rules, failing with `ERR_OUTSIDE_WINDOW`; (8) cross-reference coherence between referenced entities and their parents, failing with `ERR_CROSS_REFERENCE_MISMATCH`; (9) segregation-of-duties rules; (10) compliance gates such as grantee clearance, expenditure-responsibility acknowledgement, and the revision ceiling; (11) uniqueness constraints, failing with `ERR_UNIQUENESS_VIOLATION`; (12) field domain constraints such as ranges and formats, failing with `ERR_FIELD_CONSTRAINT`; (13) fiscal capacity checks against balances and holdings; (14) history sufficiency for spending policy, failing with `ERR_INSUFFICIENT_HISTORY`; (15) the one-score-per-member rule, failing with `ERR_DUPLICATE_SCORE`; and (16) the grant revision limit, failing with `ERR_REVISION_LIMIT_REACHED`. Where §3 assigns an endpoint a more specific error than the category error listed here, the specific error takes precedence as the returned code while the ordering is unchanged.

### 2.10. Ledger Integrity and Cross-Entity Consistency

Every fund carries a spendable cash ledger, `cash_balance`, which starts at 0.00. It is credited when a contribution is accepted (cash gifts) or liquidated (non-cash gifts) and when a redemption pays out of a pool; it is debited when a grant or scholarship award is disbursed, when a buy-in moves cash into a pool, and when a quarterly administrative fee is assessed. Invested value is tracked separately: `invested_units` aggregates the pool units the fund holds, and `invested_market_value` is the sum over the fund's pool holdings of `units_held` multiplied by the pool's current `unit_price`, recomputed on every unitization event that touches the fund. A fund's `total_market_value` is its `cash_balance` plus its `invested_market_value`, expressed at 2 decimal places.

State changes propagate across entity boundaries so the hierarchy stays consistent. Liquidating a gift or disbursing a grant refreshes the fund's activity timestamp and can wake an inactive fund; executing an amendment supersedes the incumbent agreement and rebinds the fund's derived terms; recording an advisor deceased can cascade through a named successor all the way back to fund reactivation. Each such mutation — including writes to derived fields performed as side effects of an operation on a different resource — refreshes the mutated resource's `updated_at` and increments its `version`. Fund mutations in particular bump the fund's `version`, which is what the optimistic-concurrency rules of §2.8 key on: fund activation and closure, agreement execution, contribution acceptance and liquidation, unitization events, grant creation and disbursement, award disbursement, spending policy runs, and fee assessments all advance the fund's `version`.

## 3. Business Logic & Workflows

### 3.1. Establishing Funds and Governing Agreements

A `FoundationAdmin` establishes a fund by supplying its `fund_name`, its `fund_type` — one of `DONOR_ADVISED`, `DESIGNATED`, or `SCHOLARSHIP` — and the `endowed` flag, which marks the fund as a permanent endowment restricted to spending-policy outlays when true and as fully expendable when false. The new fund begins in `PENDING_AGREEMENT` with `cash_balance` at 0.00 and `invested_units` at 0.0000. Fund names are unique across the foundation; a duplicate `fund_name` is rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409). Staff and external parties can review the fund register through the fund list, which accepts optional `fund_type` and `status` filters, and can fetch a single fund by its `fundId`; reading a fund refreshes its computed fields, including `inactivity_months`, `invested_market_value`, `total_market_value`, and `spendable_balance`.

No fund activates on paperwork alone. The `FoundationAdmin` drafts a fund agreement carrying the economic terms: `spending_rate_pct`, an annual spending rate expressed as a decimal percent between 0.00 and 20.00; `spending_formula`, either `AVERAGE_12Q` for a trailing twelve quarter-end average or `FIXED_3YR` for a trailing three fiscal-year-end average; and `fee_tier_schedule`, either `STANDARD` for the marginal three-tier schedule or `FLAT` for a single flat rate. Optional terms include `successor_advisor_id`, naming the advisor who inherits a donor-advised fund on inactivity or death (null when unset), `inactivity_trigger_months` defaulting to 36, `dormancy_trigger_months` defaulting to 24, and `min_initial_contribution` defaulting to 10000.00 dollars, which must be zero or greater. Every agreement receives an `agreement_version_no` — 1 for the fund's first agreement, incremented by one for each subsequent agreement created on the fund, whether or not earlier drafts were ever executed — and begins in `DRAFT`. A self-reference is forbidden: the advisor row named as `successor_advisor_id` must not be the fund's own `PRIMARY` advisor row, and such a nomination is rejected with `ERR_UNIQUENESS_VIOLATION`. Agreements for a fund are listed under the fund, a single agreement is fetched by `agreementId`, and a foundation-wide agreement register can be filtered by `fund_id` or by `successor_advisor_id` to find every agreement naming a particular successor.

Execution is the act that gives an agreement force, and it enforces two checks in order. First, no other agreement for the same fund may already be `EXECUTED` outside the amendment path — executing a second draft while an executed agreement exists, where the new draft was not created as an amendment against the fund's then-current version, is rejected with `ERR_AGREEMENT_ALREADY_EXECUTED` (HTTP 409). Second, `successor_advisor_id`, when set, must reference an advisor serving the same fund; a successor drawn from another fund's roster is rejected with `ERR_SUCCESSOR_NOT_ON_FUND` (HTTP 422). A successful execution stamps `executed_at` from the logical clock and moves the agreement from `DRAFT` to `EXECUTED`. When the fund already had an executed agreement — the amendment case, in which the newer draft was created against the fund's current version as described in §2.8 — the incumbent agreement automatically transitions from `EXECUTED` to `SUPERSEDED`, and fund behavior derived from agreement terms (the spending allowance basis and the fee schedule) rebinds to the newly executed agreement. An `EXECUTED` agreement may later be terminated by a `FoundationAdmin`, but only once its fund has reached `CLOSED`; terminating earlier is rejected with `ERR_FUND_NOT_CLOSED` (HTTP 409).

Activation turns a paper fund into an operating one and enforces its two preconditions in order. The fund must first hold an `EXECUTED` agreement — activating without one fails with `ERR_AGREEMENT_NOT_EXECUTED` (HTTP 409) — and it must then have received at least one accepted contribution whose `net_proceeds` is greater than or equal to the agreement's `min_initial_contribution`, failing which the activation is rejected with `ERR_MIN_INITIAL_CONTRIBUTION` (HTTP 422). Because gift acceptance is permitted while a fund is still `PENDING_AGREEMENT` (see §3.3), the seed gift normally lands before activation is attempted. Activation moves the fund from `PENDING_AGREEMENT` to `ACTIVE`, stamps both `inception_date` and `last_activity_at` from the logical clock, and advances the fund's `version`.

Closure runs in the opposite direction and comes in two shapes. Closing an `ACTIVE` fund requires, in order: a zeroed ledger, meaning `cash_balance` is exactly 0.00 and `invested_units` is exactly 0.0000, failing which the close is rejected with `ERR_FUND_NOT_EMPTY` (HTTP 409); no grant recommendation of the fund resting in any of `DRAFT`, `SUBMITTED`, `COMPLIANCE_REVIEW`, `RETURNED`, or `APPROVED`, failing which the close is rejected with `ERR_PENDING_GRANTS` (HTTP 409); and no scholarship program of the fund in `SETUP`, `OPEN`, `SCORING`, or `AWARDED`, failing which the close is rejected with `ERR_PROGRAM_OPEN` (HTTP 409). Closing a `DORMANT` fund is narrower: only the empty-ledger check applies, because the dormancy transition has already resolved the fund's pending grant work. Either path lands the fund in `CLOSED`, which is terminal.

### 3.2. Fund Advisors, Succession, and the Inactivity Policy

Donor-advised funds revolve around their advisors. A `FoundationAdmin` invites an advisor to a fund by providing `advisor_name`, a contact `email`, and an `advisor_kind` of `PRIMARY` or `SUCCESSOR`; the invitation creates the advisor row in `INVITED` status. Advisor email addresses are unique across all advisors foundation-wide, and a duplicate is rejected with `ERR_UNIQUENESS_VIOLATION`. Advisors are listed per fund or foundation-wide filtered by `fund_id`, and a single advisor is fetched by `advisorId`.

Acceptance is strictly self-service: the acting advisor's `X-User-ID` must equal the invited advisor row's `id`, and an acceptance attempted under any other identity is rejected with `ERR_NOT_THE_INVITED_ADVISOR` (HTTP 403). A successful acceptance moves the advisor from `INVITED` to `ACTIVE` and stamps `activated_at`. Resignation follows the same self-service rule and error; it moves an `ACTIVE` advisor to `RESIGNED` and is deliberately not qualifying activity — the fund's `last_activity_at` is left unchanged, so a resignation cannot reset the inactivity clock. A `FoundationAdmin` may instead revoke a pending invitation, moving an `INVITED` advisor to `REVOKED`; revocation also reaches into paperwork, nulling `successor_advisor_id` on any `DRAFT` agreement that named the revoked advisor.

Recording an advisor deceased is the most far-reaching advisor operation, and it cascades in three hops. In the first hop, a `FoundationAdmin` records the advisor as `DECEASED`; only an `ACTIVE` advisor can be recorded deceased, and the attempt against an advisor in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). In the second hop, if the fund's `EXECUTED` agreement names a `successor_advisor_id` whose status is `INVITED`, that successor auto-transitions from `INVITED` to `ACTIVE` without any acceptance call — the executed agreement itself is the authorization. In the third hop, the successor's auto-activation counts as an advisor succession event on the fund: it refreshes the fund's `last_activity_at`, and if the fund was `INACTIVE` it immediately auto-transitions back to `ACTIVE` per the fund lifecycle. `RESIGNED`, `DECEASED`, and `REVOKED` are all terminal for the advisor row.

The inactivity policy is what makes succession matter. A fund's `inactivity_months` is the number of whole calendar months between `last_activity_at` and the current logical clock — and is null until `last_activity_at` is first stamped at activation: take the difference in calendar years multiplied by twelve, add the difference in calendar months, and subtract one when the day-of-month of the clock is earlier than the day-of-month of `last_activity_at`. Qualifying activity — acceptance of a contribution on the fund, liquidation of a non-cash gift, disbursement of a grant or award on the fund, or a successor auto-activation — resets the baseline by refreshing `last_activity_at`. When a clock advance pushes a `DONOR_ADVISED` fund's `inactivity_months` to at least the executed agreement's `inactivity_trigger_months` (thirty-six months by default), the fund lapses from `ACTIVE` to `INACTIVE`. A single clock advance moves a fund at most one step along this ladder: a fund that lapses to `INACTIVE` on an advance is evaluated for dormancy only on a subsequent advance, even if its inactivity already exceeds the deeper threshold. Only donor-advised funds carry this behavior; `DESIGNATED` and `SCHOLARSHIP` funds do not inactivate.

An `INACTIVE` fund that receives qualifying activity — a contribution acceptance or liquidation on the fund, a grant or award disbursement on the fund, or a successor auto-activation — returns to `ACTIVE` automatically, with `last_activity_at` refreshed to the current logical clock. If no activity arrives and a clock advance pushes `inactivity_months` to at least the sum of the agreement's `inactivity_trigger_months` and `dormancy_trigger_months` (sixty months under the defaults of thirty-six and twenty-four), the fund lapses from `INACTIVE` to `DORMANT`. Dormancy has teeth: every grant recommendation of the fund sitting in `DRAFT`, `SUBMITTED`, or `RETURNED` is denied in cascade with `decided_at` set, whether or not the fund has a successor waiting — grants already under compliance review are untouched by the cascade — and, separately, if the fund has no successor advisor (an advisor row of the fund whose `advisor_kind` is `SUCCESSOR`) in `ACTIVE` or `INVITED` status, its entire `cash_balance` is swept to the foundation's unrestricted fund by internal transfer, a cash-ledger movement only, which mints no disbursement record, since disbursement rows of source kind `GRANT` exist only where an actual grant was paid. From `DORMANT`, the only way out is closure under the empty-ledger rule of §3.1.

### 3.3. Gift Acceptance: Contributions, Asset Lots, and Liquidation

A `GiftOfficer` records a pledged contribution with the receiving `fund_id`, the `donor_name`, the `asset_kind` — one of `CASH`, `PUBLICLY_TRADED`, `RESTRICTED_STOCK`, or `REAL_PROPERTY` — and the donor-declared fair market `declared_value`, which must be greater than zero and is carried at 2 decimal places; violations of the amount rules are rejected with `ERR_FIELD_CONSTRAINT` (HTTP 422). The pledge begins with `acceptance_status` of `PLEDGED`. Contributions carry a second, parallel status dimension, `liquidation_status`: a cash pledge starts at `NOT_REQUIRED`, while any non-cash pledge starts at `PENDING_LIQUIDATION`. The two dimensions evolve independently — a contribution is fully settled only when it is both `ACCEPTED` and `LIQUIDATED`, or closed out as `DECLINED`. Contributions are listed with optional `fund_id` and `acceptance_status` filters and fetched singly by `contributionId`.

Non-cash gifts are documented lot by lot. Against a pledged contribution, the `GiftOfficer` adds asset lots, each with a `description` (a ticker, a parcel identifier, and the like), a `quantity` of units or shares greater than zero and carried at 2 decimal places, an `appraised_value` in dollars greater than zero at 2 decimal places, and an optional `liquidation_fee_pct` for the lot class that defaults to 1.50 when omitted, is carried at 2 decimal places, and must be zero or greater. Each lot is its own ledger record carrying `id` and `created_at` only; lots are listed under their contribution, queried foundation-wide by `contribution_id`, or fetched singly by `lotId`.

Acceptance is permitted while the fund is `PENDING_AGREEMENT` or `ACTIVE`; an acceptance attempted against a fund in any other state is rejected with `ERR_FUND_NOT_ACCEPTING` (HTTP 409). The acceptance stamps `gift_date` from the logical clock; because the stamp is read from the clock itself it can never fall in the future, and acceptance performs no window check. What happens next depends on the asset kind. For a `CASH` gift, `net_proceeds` equals `declared_value`, the fund's `cash_balance` is credited immediately, the contribution's `liquidation_status` moves straight to `LIQUIDATED`, and the fund's `last_activity_at` is refreshed. For any non-cash kind, acceptance leaves `liquidation_status` at `PENDING_LIQUIDATION` and no cash moves yet — the gift has been taken in, but its value is not spendable until liquidation completes. Either way the acceptance advances the fund's `version`. A `GiftOfficer` may instead decline a pledge, which moves `acceptance_status` to `DECLINED` and records the supplied `decline_reason`; the reason is required — a decline attempted without one is rejected with `ERR_FIELD_CONSTRAINT` (HTTP 422) — and the field is null on any contribution that was never declined.

Liquidation converts a pending non-cash gift into spendable cash. The `GiftOfficer` submits the actual sale results as `lot_proceeds` — either an object mapping each lot's `id` to its gross figure, or a list of entries each carrying `lot_id` and `gross_proceeds` — recording a `gross_proceeds` figure, zero or greater at 2 decimal places, for every asset lot of the contribution; if any lot is missing its `gross_proceeds`, the liquidation is rejected with `ERR_LOT_PROCEEDS_MISSING` (HTTP 422). The waterfall then runs per lot, processing the lots in order of creation, earliest `created_at` first, with ties broken by higher `appraised_value` first. For each lot, the lot fee is the lot's `gross_proceeds` multiplied by its `liquidation_fee_pct` and divided by one hundred, rounded half-up to two decimal places; the lot's net is then its `gross_proceeds` minus that fee minus a flat brokerage charge of 75.00 dollars per lot, and if that net would be negative it is floored at zero, so a lot's fee never exceeds its proceeds. The contribution's `net_proceeds` is the sum of the per-lot nets, rounded half-up to two decimal places. The per-lot-then-sum order is normative: summing gross proceeds first and applying the fee afterward is non-conformant. Completion moves the contribution to `LIQUIDATED`, credits the fund's `cash_balance` with the `net_proceeds`, refreshes the fund's `last_activity_at`, advances the fund's `version`, and — if the fund was `INACTIVE` — returns it to `ACTIVE` automatically.

### 3.4. Investment Pools and Unitization Accounting

Pooled investing is managed by an `InvestmentManager`, who creates each pool with a unique `pool_name`, a `pool_kind` of `CONSERVATIVE`, `BALANCED`, or `GROWTH`, and seed figures `initial_nav` and `initial_units`. The seed units must be greater than zero — a pool with no units has no defined price — and a non-positive seed is rejected with `ERR_FIELD_CONSTRAINT`; the seed `initial_nav` must be zero or greater, a negative one likewise failing with `ERR_FIELD_CONSTRAINT`. The pool opens in `OPEN` status with `nav` and `units_outstanding` seeded from those inputs. A pool's `unit_price` is its `nav` divided by its `units_outstanding`, rounded half-up to four decimal places, and is defined only while `units_outstanding` is greater than zero. Pools are listed, fetched by `poolId`, suspended, reopened, and terminated. Suspension moves an `OPEN` pool to `SUSPENDED` and blocks transactional events, reopening returns a `SUSPENDED` pool to `OPEN`, and termination — permitted only when `units_outstanding` is exactly 0.0000, failing which the request is rejected with `ERR_POOL_NOT_EMPTY` (HTTP 409) — moves an `OPEN` pool to `TERMINATED`, which is terminal.

All movement in and out of pools is booked as unitization events by an `InvestmentManager` or `FinanceOfficer`. Each event names its `event_kind` — `BUY_IN`, `REDEMPTION`, or `MARK_TO_MARKET` — and its target pool; a `fund_id` is required for `BUY_IN` and `REDEMPTION` and is null for a market reprice. Transactional events (`BUY_IN` and `REDEMPTION`) are accepted only while the pool is `OPEN`; against a `SUSPENDED` or `TERMINATED` pool they are rejected with `ERR_POOL_NOT_OPEN` (HTTP 409), and both carry the `expected_pool_version` guard of §2.8. Every executed event snapshots `unit_price_applied`, the pool's unit price at the instant of execution, and records `units_delta`, the signed count of units minted or burned, at 4 decimal places. Each event record also carries `cash_amount`, `units_amount`, and `new_nav`, each populated only on the event kind that uses it — buy-ins, redemptions, and repricings respectively — and null on events of the other kinds.

A buy-in moves fund cash into the pool. The `cash_amount` must be greater than zero, failing with `ERR_FIELD_CONSTRAINT`, and a buy-in attempted while the pool's unit price is undefined — zero units outstanding — is rejected with `ERR_INVALID_STATE` (HTTP 409). The fund's `cash_balance` must be at least the `cash_amount` being invested, failing which the event is rejected with `ERR_INSUFFICIENT_CASH` (HTTP 422). The minted unit count is `cash_amount` divided by the current `unit_price`, rounded half-up to four decimal places; those units are added to the pool's `units_outstanding`, the cash is added to the pool's `nav`, the fund's `cash_balance` is debited by `cash_amount`, and the fund's holding row for the pool is created or increased by the minted units.

A redemption runs the same machinery in reverse, keyed on units rather than dollars. The `units_amount` to redeem, carried at 4 decimal places, must be greater than zero — failing with `ERR_FIELD_CONSTRAINT` — and must not exceed the fund's `units_held` in that pool, failing which the event is rejected with `ERR_INSUFFICIENT_CASH`. The payout is `units_amount` multiplied by the current `unit_price`, rounded half-up to two decimal places; the redeemed units are subtracted from `units_outstanding`, the payout is subtracted from `nav`, the fund's `cash_balance` is credited with the payout, and the fund's holding is decreased by the redeemed units. A pool holding row exists only while its `units_held` is greater than zero, so a full redemption retires the row. Holdings are listed per fund, filtered foundation-wide by `fund_id` or `pool_id`, and fetched singly by `holdingId`.

A mark-to-market reprices the pool without moving units: the pool's `nav` is replaced outright by the supplied `new_nav` — zero or greater, at 2 decimal places — `units_outstanding` is unchanged, the `unit_price` is recomputed from the new figures, the event's `units_delta` is 0.0000, and its `unit_price_applied` snapshots the pool's unit price after the reprice. Being non-transactional, a mark-to-market is accepted against a pool in any status, including `SUSPENDED` or `TERMINATED`. Because the price moved, every fund holding that pool has its `invested_market_value` recomputed — and `total_market_value` follows, being cash plus invested value. Both transactional directions advance the pool's `version` and the involved fund's `version`, and the fund's computed investment fields are refreshed on every event that touches it. The event ledger is listed per pool, filtered foundation-wide by `pool_id` or `fund_id`, and individual events are fetched by `eventId`.

### 3.5. Market Value History, Spending Policy, and Administrative Fees

Endowed funds spend from policy, not from impulse, and the policy machinery rests on recorded history. A `FinanceOfficer` records market value snapshots for a fund, each with a `snapshot_kind` of `QUARTER_END` or `FISCAL_YEAR_END`, an `effective_date` fixing the date the value is effective, and the fund's `market_value` at that date — zero or greater, at 2 decimal places. Snapshots are listed per fund with an optional `snapshot_kind` filter, queried foundation-wide by `fund_id`, and fetched singly by `snapshotId`.

Once a year per fund, the `FinanceOfficer` runs the spending policy for a `fiscal_year` such as 2026. The run copies `formula_used` from the fund's currently `EXECUTED` agreement — a fund without an `EXECUTED` agreement cannot run its policy, and the attempt is rejected with `ERR_AGREEMENT_NOT_EXECUTED` (HTTP 409) — and builds its averaging window from the fund's snapshots of the matching kind whose `effective_date` falls on or before the run date, ordered from most recent to oldest, with ties on the same `effective_date` broken by earlier `created_at` first. Under `AVERAGE_12Q`, the window is the twelve most recent `QUARTER_END` snapshots, and if fewer than twelve exist the run is rejected with `ERR_INSUFFICIENT_HISTORY` (HTTP 422); `base_value` is the sum of those twelve `market_value` figures divided by twelve, rounded half-up to two decimal places. Under `FIXED_3YR`, the same construction draws the three most recent `FISCAL_YEAR_END` snapshots and requires all three, dividing their sum by three; the same fund, rate, and date generally yield a different allowance under the two formulas. The run's `allowance_granted` is then `base_value` multiplied by the agreement's `spending_rate_pct` and divided by one hundred, rounded half-up to two decimal places. The rounding order is pinned: the average is rounded to cents first, and only then is the rate multiplication performed and rounded. The run persists the exact inputs it used as `market_values_used` — the twelve or three figures that entered the average — and on the fund it sets `current_spending_allowance` to the granted amount and resets `allowance_used` to 0.00. A fund's `current_spending_allowance` is 0.00 until its first run. Each run is unique per fund per fiscal year. Runs are listed per fund, queried by `fund_id`, and fetched by `runId`.

What the allowance means at decision time is expressed by `spendable_balance`. For an endowed fund, the remaining allowance is the greater of zero and the difference between `current_spending_allowance` and `allowance_used`, and `spendable_balance` is the smaller of `cash_balance` and that remaining allowance, at 2 decimal places. For a non-endowed fund, `spendable_balance` is simply `cash_balance` — the fully expendable fund spends whatever cash it holds. Grant approval enforces this figure, as §3.6 describes, and `allowance_used` accumulates grants and awards disbursed against the current fiscal year's allowance until the next spending policy run resets it.

The foundation charges its administrative fee quarterly. A `FinanceOfficer` assesses a fund by supplying the `quarter_end_date` the fee is based on and the `quarter_end_balance` — the fund's `total_market_value` at quarter end, zero or greater at 2 decimal places — which serves as the fee base. The assessment copies `schedule_used` from the fund's `EXECUTED` agreement — a fund without one is rejected with `ERR_AGREEMENT_NOT_EXECUTED` (HTTP 409) — and computes `annual_fee` from the balance. Under the `STANDARD` schedule, the fee is marginal across three tiers: the portion of the balance up to 250,000.00 dollars is charged at 1.00 percent, the portion above 250,000.00 dollars and up to 1,000,000.00 dollars — at most 750,000.00 dollars of it — is charged at 0.60 percent, and any portion above 1,000,000.00 dollars is charged at 0.30 percent; the three tier amounts are summed and the total rounded half-up to two decimal places. Under the `FLAT` schedule, `annual_fee` is the whole balance multiplied by 0.75 percent, rounded half-up to two decimal places. Either way, `quarterly_fee` is the `annual_fee` divided by four and rounded half-up to two decimal places — the annual figure is rounded first and only then divided, and dividing before rounding is non-conformant. The `quarterly_fee` is debited from the fund's `cash_balance`, and an assessment that would drive the cash balance below zero is rejected with `ERR_INSUFFICIENT_CASH`. Fee assessments are listed per fund, queried by `fund_id`, and fetched by `feeId`.

### 3.6. Grantee Due Diligence and the Grant Lifecycle

Grantmaking begins with the recipient. A `ComplianceOfficer` registers each grantee organization with its `legal_name`, its nine-digit `tax_id` in employer-identification-number format, and its `irs_subsection` — `C3_501` for a public charity, `C3_PRIVATE_FOUNDATION`, `GOVERNMENT`, or `OTHER`. Legal names and tax identifiers are each unique; a malformed or duplicated registration is rejected with `ERR_FIELD_CONSTRAINT` or `ERR_UNIQUENESS_VIOLATION` respectively. Registration computes `expenditure_responsibility_required`, which is true whenever the subsection is neither `C3_501` nor `GOVERNMENT`, and starts the grantee at `due_diligence_status` `UNVETTED`. Grantees are listed with an optional `due_diligence_status` filter and fetched by `granteeId`.

Due diligence proceeds under the `ComplianceOfficer`'s hand. Beginning review moves a grantee from `UNVETTED` to `IN_REVIEW`; the same begin-review action also reopens an `EXPIRED` or `REJECTED_DD` grantee into `IN_REVIEW`. Clearing moves the grantee from `IN_REVIEW` to `CLEARED` and stamps `cleared_at` from the logical clock; rejecting moves it to `REJECTED_DD`. Clearance is perishable: when a clock advance carries the current time to twelve months or more past `cleared_at`, the grantee lapses automatically from `CLEARED` to `EXPIRED`, and an expired grantee must pass through review again before it can receive anything.

A grant recommendation is created by an `Advisor` or a `FoundationAdmin` with the granting `fund_id`, the recipient `grantee_id`, the `amount` in dollars, a free-text charitable `purpose`, and — for donor-advised funds — the `recommended_by_advisor_id` of the recommending advisor. The field is required on grants from `DONOR_ADVISED` funds and forbidden on grants from `DESIGNATED` or `SCHOLARSHIP` funds, which are staff-initiated. Every creation carries the `expected_fund_version` guard of §2.8, because the fund's version moves with its ledger. Grant amounts observe a floor of 250.00 dollars, enforced as a field constraint at creation with `ERR_FIELD_CONSTRAINT` and re-checked at submission with the more specific error below. A new recommendation starts in `DRAFT` with `revision_count` at 0 — and, because creating it touches the fund's pipeline, it advances the fund's `version`. Grants are listed with `fund_id`, `grantee_id`, `recommended_by_advisor_id`, and `status` filters and fetched by `grantId`.

Submission moves a recommendation from `DRAFT` to `SUBMITTED` — or, after a return, from `RETURNED` back to `SUBMITTED` — and enforces four checks in order. The fund must be `ACTIVE`, failing with `ERR_FUND_NOT_ACTIVE_FOR_GRANTS` (HTTP 409). Authorization then depends on fund type: on a `DONOR_ADVISED` fund, `recommended_by_advisor_id` must reference an `ACTIVE` advisor of that fund and the acting `X-User-ID` must equal it, failing with `ERR_ADVISOR_NOT_AUTHORIZED` (HTTP 403); on a `DESIGNATED` or `SCHOLARSHIP` fund the actor is a `FoundationAdmin` and `recommended_by_advisor_id` is null, with violations of either condition likewise failing with `ERR_ADVISOR_NOT_AUTHORIZED` (HTTP 403). The `amount` must be at least 250.00 dollars, failing with `ERR_GRANT_BELOW_MINIMUM` (HTTP 422). And `revision_count` must still be below 3, failing with `ERR_REVISION_LIMIT_REACHED` (HTTP 422). A successful submission stamps `submitted_at`; resubmission from `RETURNED` refreshes it.

Compliance review is claimed, not assigned: a `ComplianceOfficer` claims a `SUBMITTED` grant, moving it to `COMPLIANCE_REVIEW` and recording the claiming officer's identity on the grant. Approval is then the densest gate in the system, and its four checks are evaluated in order so that an early failure is never masked by a later one. First, segregation of duties: the approving officer's `X-User-ID` must differ from the `X-User-ID` that claimed the review, failing with `ERR_SOD_SELF_APPROVAL` (HTTP 403). Second, the grantee's `due_diligence_status` must be `CLEARED` at the decision instant — a grantee sitting in `UNVETTED`, `IN_REVIEW`, `REJECTED_DD`, or `EXPIRED` fails with `ERR_GRANTEE_NOT_CLEARED` (HTTP 422), which is how the twelve-month freshness window bites. Third, when the grantee's `expenditure_responsibility_required` is true, the approval payload must carry `include_er_acknowledgement` set to true, failing with `ERR_ER_ACK_REQUIRED` (HTTP 422). Fourth, the `amount` must not exceed the fund's `spendable_balance` at the decision instant — the allowance-aware figure of §3.5 — failing with `ERR_EXCEEDS_SPENDABLE` (HTTP 422). Approval moves the grant to `APPROVED`, stamps `decided_at`, and records the approving officer's identity for the downstream segregation check.

A compliance officer who cannot approve has three exits. Returning the grant moves it from `COMPLIANCE_REVIEW` to `RETURNED` and increments `revision_count`; when that increment brings the count to 3, the grant immediately auto-transitions from `RETURNED` to `DENIED` with `decided_at` set, closing the revision loop — and since a `DENIED` grant is terminal, no further submission is possible from it. Denying outright moves the grant to `DENIED` with `decided_at` set. And an `APPROVED` grant may still be cancelled, moving it to `CANCELLED`, when circumstances change before payment.

Payment belongs to finance, not compliance. A `FinanceOfficer` disburses an `APPROVED` grant under two checks in order: the disbursing officer's `X-User-ID` must differ from the approving officer's recorded identity, failing with `ERR_SOD_SELF_DISBURSE` (HTTP 403), and the `amount` must not exceed the fund's `cash_balance`, failing with `ERR_INSUFFICIENT_CASH`. Disbursement debits the fund's `cash_balance` by the grant amount, adds the amount to the fund's `allowance_used` on endowed funds, refreshes the fund's `last_activity_at` — waking an `INACTIVE` fund back to `ACTIVE` — and creates a disbursement record with `source_kind` `GRANT`, the `grant_id` populated, the `fund_id` denormalized from the grant for statement sweeps, and the disbursed `amount` copied from the grant at creation. The grant lands in `DISBURSED`, terminal, and the fund's `version` advances. Each grant's payment trail is listed as a sub-resource of the grant itself.

### 3.7. Scholarship Programs, Committees, Scoring, and Awards

Scholarship work begins with a program. A `ProgramOfficer` creates a program on a fund whose `fund_type` is `SCHOLARSHIP` — programs may not be established on donor-advised or designated funds, and the attempt is rejected with `ERR_FIELD_CONSTRAINT` (HTTP 422) — supplying a unique `program_name`, the `application_open` and `application_close` timestamps (the close must fall strictly after the open), the fixed per-winner `award_amount` of at least 500.00 dollars, and the `max_awards` ceiling of at least 1; range violations are rejected with `ERR_FIELD_CONSTRAINT`. A new program sits in `SETUP` with `committee_size` at 0. Its `quorum_threshold` is one more than half the committee size rounded down — a strict majority — and is recomputed on every enrollment change. Programs are listed per fund, filtered foundation-wide by `fund_id`, and fetched by `programId`.

The committee gives the program its judgment. A `ProgramOfficer` seats members with `member_name` and `email`, unique per program; seating is permitted only while the program is in `SETUP` or `OPEN`, and a seating attempted later is rejected with `ERR_PROGRAM_LOCKED` (HTTP 409) — on this endpoint the per-program email-uniqueness check is evaluated before the program-state check, ahead of the global ordering of §2.9. Each seating adds a `SEATED` member and increments `committee_size`, recomputing `quorum_threshold`. Members are listed per program or filtered by `program_id`, and fetched by `memberId`. Two exits exist. A member recuses themselves — the acting `X-User-ID` must equal the member row's `id`, failing with `ERR_NOT_THE_MEMBER` (HTTP 403) — moving from `SEATED` to `RECUSED`; recusal decrements `committee_size` and recomputes the quorum, and score entries the member already submitted remain valid. A `ProgramOfficer` removes a member, moving them to `REMOVED` with the same size and quorum consequences, but only while the program is in `SETUP` or `OPEN`; once the program has moved on, removal is rejected with `ERR_PROGRAM_LOCKED` (HTTP 409).

Opening the program enforces three checks in order: the committee must number at least 3 seated members, failing with `ERR_COMMITTEE_TOO_SMALL` (HTTP 422); the application window must be well-formed, with `application_close` after `application_open`; and the current logical clock must not yet have reached `application_close`, failing with `ERR_OUTSIDE_WINDOW`. Opening moves the program from `SETUP` to `OPEN`. A program still in `SETUP` may instead be cancelled outright, landing in `CANCELLED`.

Applications arrive from applicants themselves. An `Applicant` submits with `applicant_name` and `applicant_email`, unique per program, and the submission is accepted only inside the window — the logical clock at or after `application_open` and strictly before `application_close` — failing with `ERR_OUTSIDE_WINDOW`; the window is the only gate, and the program's own status is not consulted at submission. The application is created in `SUBMITTED` status, and its `id` thereafter serves as the applicant's own `X-User-ID`. Applications are listed per program with an optional `status` filter, filtered foundation-wide by `program_id`, and fetched by `applicationId`.

Closing the application window requires the logical clock to have reached `application_close` — closing early is rejected with `ERR_OUTSIDE_WINDOW` — and at least one application on the books, failing with `ERR_NO_APPLICATIONS` (HTTP 422). The program moves from `OPEN` to `SCORING`, and every `SUBMITTED` application cascades to `UNDER_SCORING`.

Scoring is individual and final. A `CommitteeMember` scores an application by submitting their own `member_id` — a `member_id` other than the acting member's own is rejected with `ERR_NOT_THE_MEMBER` (HTTP 403) — and only while the application is `UNDER_SCORING`, failing otherwise with `ERR_INVALID_STATE`, together with four integer components — `academic`, `financial_need`, `essay`, and `interview` — each between 0 and 100 inclusive, failing which the entry is rejected with `ERR_FIELD_CONSTRAINT`. The scoring member must be seated on the program that owns the application; a member of a different program's committee is rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422), and a second score from the same member on the same application is rejected with `ERR_DUPLICATE_SCORE` (HTTP 409). Each entry's `weighted_score` is forty percent of `academic`, thirty percent of `financial_need`, twenty percent of `essay`, and ten percent of `interview`, summed and rounded half-up to two decimal places. The application's `final_score` is then maintained continuously: once the number of score entries whose member held `SEATED` status at the time of scoring reaches the program's `quorum_threshold`, `final_score` becomes the mean of those entries' `weighted_score` values, rounded half-up to two decimal places; before quorum it remains null. Scores are listed per application, filtered by `application_id` or `member_id`, and fetched by `scoreId`.

Winner selection is a single decisive act by the `ProgramOfficer`, who submits the chosen `winner_application_ids`. Its checks run in order: at least one application must carry a non-null `final_score` — quorum met somewhere — failing with `ERR_QUORUM_NOT_MET` (HTTP 422); the slate's length must not exceed `max_awards`, failing with `ERR_TOO_MANY_WINNERS` (HTTP 422); every named winner must itself carry a `final_score`, failing with `ERR_UNSCORED_WINNER` (HTTP 422); and every named winner must belong to this program, failing with `ERR_CROSS_REFERENCE_MISMATCH`. Finally, at the fund level, the program's maximum potential outlay — `max_awards` multiplied by `award_amount` — must not exceed the fund's `cash_balance`, failing with `ERR_INSUFFICIENT_CASH`. Selection moves each winner to `SELECTED` and every other `UNDER_SCORING` application to `NOT_SELECTED`, creates one scholarship award per winner in `OFFERED` status with its `amount` copied from the program's `award_amount` and its `program_id` and `fund_id` denormalized from the application and program, answers with the created `award_ids` and a `selected_count`, and moves the program to `AWARDED`. Awards are listed per program, filtered by `application_id`, `program_id`, or `fund_id`, and fetched by `awardId`.

Each offer is answered by the applicant. Acceptance or declination is strictly self-service — the acting `X-User-ID` must equal the application's contact identity, failing with `ERR_NOT_THE_APPLICANT` (HTTP 403). Acceptance moves the award from `OFFERED` to `ACCEPTED` and cascades the application to `ACCEPTED_AWARD`; declination moves the award to `DECLINED` and the application to `DECLINED_AWARD`. Declining never auto-closes the program: even when every award has reached a terminal state, the program remains `AWARDED` until the `ProgramOfficer` closes it, and closing is permitted only when no award of the program remains in `OFFERED` or `ACCEPTED`, failing with `ERR_AWARDS_PENDING` (HTTP 409). Payment of an `ACCEPTED` award is a `FinanceOfficer` action requiring the `amount` to fit within the fund's `cash_balance`, failing with `ERR_INSUFFICIENT_CASH`, and the fund to be `ACTIVE`, failing with `ERR_FUND_NOT_ACTIVE_FOR_GRANTS`; it debits the fund's cash, adds the amount to `allowance_used` on endowed funds, refreshes `last_activity_at`, creates a disbursement record with `source_kind` `SCHOLARSHIP_AWARD` and the `award_id` populated, and moves the award to `DISBURSED`. Should enrollment verification or another condition fail after acceptance, the `ProgramOfficer` forfeits the award, moving it from `ACCEPTED` to `FORFEITED`. `DISBURSED`, `DECLINED`, and `FORFEITED` are all terminal.

### 3.8. Annual Statements and Impact Reporting

Once per fund per fiscal year, a `FoundationAdmin` generates the annual statement by naming its `fiscal_year`; the pair of fund and fiscal year is unique, and a duplicate generation is rejected with `ERR_UNIQUENESS_VIOLATION`. Generation computes the roll-forward across the fiscal year window, which runs from January 1 through December 31 of the named year, inclusive. The `opening_value` is the fund's total market value at fiscal-year open, taken from the fund's most recent snapshot of either kind whose `effective_date` falls on or before January 1 of the fiscal year — ties on the same `effective_date` broken by earlier `created_at` first, as in the spending-policy window — otherwise carried from the closing figure of the most recent prior fiscal year's statement, and otherwise zero. The `contributions_total` is the sum of `net_proceeds` over the fund's contributions that are `ACCEPTED` and `LIQUIDATED` with `gift_date` inside the fiscal year. The `grants_total` is the sum of `amount` over the fund's disbursement records created inside the fiscal year — grants and scholarship awards alike. The `fees_total` is the sum of `quarterly_fee` over the fund's fee assessments whose `quarter_end_date` falls inside the fiscal year. The `investment_gain_loss` captures reprice effects: for each `MARK_TO_MARKET` unitization event in the fiscal year touching a pool the fund holds, the fund's `units_held` at the instant of the event is multiplied by the change in that pool's unit price — the price after the event minus the price before — and the products are summed; the figure may be negative. The `closing_value` is then the opening value plus contributions minus grants minus fees plus the investment gain or loss, and every component is carried at 2 decimal places with round-half-up. A generated statement begins in `GENERATED`; the `FoundationAdmin` later marks it `DELIVERED`, which is terminal. Statements are listed per fund, queried foundation-wide by `fund_id`, and fetched by `statementId`; fund advisors read their funds' statements.

Impact reporting rides on the disbursement ledger rather than the statement. The foundation lists a fund's disbursements — grants and awards in one feed, filterable by `source_kind` — or queries the ledger foundation-wide by `grant_id`, `award_id`, or `fund_id`, and fetches any single record by `disbursementId`. Each disbursement's `amount` is the figure copied from its source grant or award at creation, so the feed reconciles exactly against the statements' `grants_total`.

## 4. Endpoint Definitions

Operations that create a new resource — a fund, agreement, advisor, contribution, asset lot, pool, unitization event, grantee, grant recommendation, snapshot, spending policy run, fee assessment, annual statement, scholarship program, committee member, application, or score entry — return `201 Created`. Operations that read resources or modify an existing resource's state (activations, closures, executions, acceptances, approvals, disbursements, and the like) return `200 OK`. Request payloads and side effects for each operation are specified in §3; this table is the address map.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; evaluates time-based auto-transitions | FoundationAdmin |
| POST | `/funds` | Establish a fund | FoundationAdmin |
| GET | `/funds` | List funds with optional filters | Any authenticated role |
| GET | `/funds/{fundId}` | Get fund detail with computed fields refreshed | Any authenticated role |
| POST | `/funds/{fundId}/activate` | Activate a fund once its agreement is executed and the minimum initial contribution is accepted | FoundationAdmin |
| POST | `/funds/{fundId}/close` | Close an emptied fund | FoundationAdmin |
| POST | `/funds/{fundId}/agreements` | Create an agreement (first or amendment; amendments carry OCC on the fund) | FoundationAdmin |
| GET | `/funds/{fundId}/agreements` | List agreements for a fund | FoundationAdmin, ComplianceOfficer, FinanceOfficer |
| GET | `/agreements/{agreementId}` | Get an agreement | FoundationAdmin, ComplianceOfficer, FinanceOfficer |
| POST | `/agreements/{agreementId}/execute` | Execute a DRAFT agreement | FoundationAdmin |
| POST | `/agreements/{agreementId}/terminate` | Terminate an EXECUTED agreement (fund must be CLOSED) | FoundationAdmin |
| POST | `/funds/{fundId}/advisors` | Invite an advisor to a fund | FoundationAdmin |
| GET | `/funds/{fundId}/advisors` | List advisors for a fund | FoundationAdmin, ComplianceOfficer, Advisor |
| GET | `/advisors/{advisorId}` | Get an advisor | FoundationAdmin, ComplianceOfficer, Advisor |
| POST | `/advisors/{advisorId}/accept` | Advisor accepts invitation (self only) | Advisor |
| POST | `/advisors/{advisorId}/resign` | Advisor resigns (self only) | Advisor |
| POST | `/advisors/{advisorId}/revoke` | Revoke an invitation | FoundationAdmin |
| POST | `/advisors/{advisorId}/record-deceased` | Record advisor deceased; triggers the succession cascade | FoundationAdmin |
| POST | `/contributions` | Record a pledged contribution | GiftOfficer |
| GET | `/contributions` | List contributions, filterable by fund | FoundationAdmin, GiftOfficer, FinanceOfficer |
| GET | `/contributions/{contributionId}` | Get a contribution | FoundationAdmin, GiftOfficer, FinanceOfficer |
| POST | `/contributions/{contributionId}/lots` | Add an asset lot to a non-cash contribution | GiftOfficer |
| GET | `/contributions/{contributionId}/lots` | List lots of a contribution | FoundationAdmin, GiftOfficer, FinanceOfficer |
| POST | `/contributions/{contributionId}/accept` | Accept a pledge | GiftOfficer |
| POST | `/contributions/{contributionId}/decline` | Decline a pledge | GiftOfficer |
| POST | `/contributions/{contributionId}/liquidate` | Record liquidation of all lots; computes net proceeds and credits cash | GiftOfficer |
| POST | `/pools` | Create an investment pool | InvestmentManager |
| GET | `/pools` | List pools | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/pools/{poolId}` | Get a pool | FoundationAdmin, InvestmentManager, FinanceOfficer |
| POST | `/pools/{poolId}/suspend` | Suspend a pool (blocks buy-in and redemption) | InvestmentManager |
| POST | `/pools/{poolId}/reopen` | Reopen a suspended pool | InvestmentManager |
| POST | `/pools/{poolId}/terminate` | Terminate an empty pool | InvestmentManager |
| POST | `/pools/{poolId}/unitization-events` | Record a buy-in, redemption, or mark-to-market (transactional events carry OCC on the pool) | InvestmentManager, FinanceOfficer |
| GET | `/pools/{poolId}/unitization-events` | List events of a pool | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/funds/{fundId}/pool-holdings` | List a fund's pool holdings | FoundationAdmin, InvestmentManager, FinanceOfficer |
| POST | `/grantees` | Register a grantee organization | ComplianceOfficer |
| GET | `/grantees` | List grantees | FoundationAdmin, ComplianceOfficer, Advisor |
| GET | `/grantees/{granteeId}` | Get a grantee | FoundationAdmin, ComplianceOfficer, Advisor |
| POST | `/grantees/{granteeId}/begin-review` | Move a grantee to IN_REVIEW | ComplianceOfficer |
| POST | `/grantees/{granteeId}/clear` | Clear a grantee (starts the twelve-month freshness window) | ComplianceOfficer |
| POST | `/grantees/{granteeId}/reject` | Reject a grantee in due diligence | ComplianceOfficer |
| POST | `/grants` | Create a grant recommendation (OCC on the fund) | Advisor, FoundationAdmin |
| GET | `/grants` | List grants, filterable | FoundationAdmin, ComplianceOfficer, FinanceOfficer, Advisor |
| GET | `/grants/{grantId}` | Get a grant | FoundationAdmin, ComplianceOfficer, FinanceOfficer, Advisor |
| POST | `/grants/{grantId}/submit` | Submit from DRAFT or RETURNED | Advisor, FoundationAdmin |
| POST | `/grants/{grantId}/claim-review` | Compliance claims the grant for review | ComplianceOfficer |
| POST | `/grants/{grantId}/approve` | Approve a grant (approver differs from claimer) | ComplianceOfficer |
| POST | `/grants/{grantId}/return` | Return a grant for revision; the third return auto-denies | ComplianceOfficer |
| POST | `/grants/{grantId}/deny` | Deny a grant | ComplianceOfficer |
| POST | `/grants/{grantId}/cancel` | Cancel an approved grant | ComplianceOfficer |
| POST | `/grants/{grantId}/disburse` | Disburse an approved grant (disburser differs from approver) | FinanceOfficer |
| POST | `/funds/{fundId}/market-value-snapshots` | Record a quarter-end or fiscal-year-end market value | FinanceOfficer |
| GET | `/funds/{fundId}/market-value-snapshots` | List snapshots for a fund | FoundationAdmin, FinanceOfficer |
| POST | `/funds/{fundId}/spending-policy-runs` | Run the annual spending policy for a fiscal year | FinanceOfficer |
| GET | `/funds/{fundId}/spending-policy-runs` | List spending policy runs | FoundationAdmin, FinanceOfficer |
| POST | `/funds/{fundId}/fee-assessments` | Assess the quarterly administrative fee | FinanceOfficer |
| GET | `/funds/{fundId}/fee-assessments` | List fee assessments | FoundationAdmin, FinanceOfficer |
| POST | `/funds/{fundId}/annual-statements` | Generate the annual statement for a fiscal year | FoundationAdmin |
| GET | `/funds/{fundId}/annual-statements` | List annual statements | FoundationAdmin, FinanceOfficer, Advisor |
| GET | `/statements/{statementId}` | Get a statement | FoundationAdmin, FinanceOfficer, Advisor |
| POST | `/statements/{statementId}/deliver` | Mark a statement delivered | FoundationAdmin |
| GET | `/funds/{fundId}/disbursements` | List disbursements (grants and awards) for a fund — impact reporting feed | FoundationAdmin, FinanceOfficer |
| POST | `/funds/{fundId}/scholarship-programs` | Create a scholarship program on a SCHOLARSHIP fund | ProgramOfficer |
| GET | `/funds/{fundId}/scholarship-programs` | List programs for a fund | FoundationAdmin, ProgramOfficer, Applicant, CommitteeMember |
| GET | `/programs/{programId}` | Get a program | FoundationAdmin, ProgramOfficer, Applicant, CommitteeMember |
| POST | `/programs/{programId}/open` | Open a program for applications | ProgramOfficer |
| POST | `/programs/{programId}/close-applications` | Close the application window; applications move to scoring | ProgramOfficer |
| POST | `/programs/{programId}/select-winners` | Select winners; creates awards and rejects non-winners | ProgramOfficer |
| POST | `/programs/{programId}/close` | Close a program once all awards are terminal | ProgramOfficer |
| POST | `/programs/{programId}/cancel` | Cancel a program still in SETUP | ProgramOfficer |
| POST | `/programs/{programId}/committee-members` | Seat a committee member | ProgramOfficer |
| GET | `/programs/{programId}/committee-members` | List committee members | FoundationAdmin, ProgramOfficer, CommitteeMember |
| POST | `/committee-members/{memberId}/recuse` | Member recuses self | CommitteeMember |
| POST | `/committee-members/{memberId}/remove` | Remove a member while the program is in SETUP or OPEN | ProgramOfficer |
| POST | `/programs/{programId}/applications` | Submit an application inside the window | Applicant |
| GET | `/programs/{programId}/applications` | List applications | FoundationAdmin, ProgramOfficer, CommitteeMember |
| GET | `/applications/{applicationId}` | Get an application | FoundationAdmin, ProgramOfficer, CommitteeMember, Applicant |
| POST | `/applications/{applicationId}/scores` | Committee member scores an application (one score per member) | CommitteeMember |
| GET | `/applications/{applicationId}/scores` | List score entries for an application | FoundationAdmin, ProgramOfficer |
| GET | `/programs/{programId}/awards` | List awards of a program | FoundationAdmin, ProgramOfficer, FinanceOfficer, Applicant |
| GET | `/awards/{awardId}` | Get an award | FoundationAdmin, ProgramOfficer, FinanceOfficer, Applicant |
| POST | `/awards/{awardId}/accept` | Applicant accepts an award | Applicant |
| POST | `/awards/{awardId}/decline` | Applicant declines an award | Applicant |
| POST | `/awards/{awardId}/disburse` | Disburse an accepted award | FinanceOfficer |
| POST | `/awards/{awardId}/forfeit` | Forfeit an accepted award | ProgramOfficer |
| GET | `/agreements` | Filtered list of agreements (by fund or named successor advisor) | FoundationAdmin, ComplianceOfficer, FinanceOfficer |
| GET | `/advisors` | Filtered list of advisors (by fund) | FoundationAdmin, ComplianceOfficer |
| GET | `/lots/{lotId}` | Get an asset lot | FoundationAdmin, GiftOfficer, FinanceOfficer |
| GET | `/lots` | Filtered list of asset lots (by contribution) | FoundationAdmin, GiftOfficer, FinanceOfficer |
| GET | `/pool-holdings/{holdingId}` | Get a pool holding | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/pool-holdings` | Filtered list of pool holdings (by fund or pool) | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/unitization-events/{eventId}` | Get a unitization event | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/unitization-events` | Filtered list of unitization events (by pool or fund) | FoundationAdmin, InvestmentManager, FinanceOfficer |
| GET | `/disbursements/{disbursementId}` | Get a disbursement | FoundationAdmin, FinanceOfficer |
| GET | `/disbursements` | Filtered list of disbursements (by grant, award, or fund) | FoundationAdmin, FinanceOfficer |
| GET | `/spending-policy-runs/{runId}` | Get a spending policy run | FoundationAdmin, FinanceOfficer |
| GET | `/spending-policy-runs` | Filtered list of spending policy runs (by fund) | FoundationAdmin, FinanceOfficer |
| GET | `/market-value-snapshots/{snapshotId}` | Get a market value snapshot | FoundationAdmin, FinanceOfficer |
| GET | `/market-value-snapshots` | Filtered list of snapshots (by fund) | FoundationAdmin, FinanceOfficer |
| GET | `/fee-assessments/{feeId}` | Get a fee assessment | FoundationAdmin, FinanceOfficer |
| GET | `/fee-assessments` | Filtered list of fee assessments (by fund) | FoundationAdmin, FinanceOfficer |
| GET | `/programs` | Filtered list of scholarship programs (by fund) | FoundationAdmin, ProgramOfficer |
| GET | `/committee-members/{memberId}` | Get a committee member | FoundationAdmin, ProgramOfficer, CommitteeMember |
| GET | `/committee-members` | Filtered list of committee members (by program) | FoundationAdmin, ProgramOfficer |
| GET | `/applications` | Filtered list of scholarship applications (by program) | FoundationAdmin, ProgramOfficer |
| GET | `/scores/{scoreId}` | Get a score entry | FoundationAdmin, ProgramOfficer |
| GET | `/scores` | Filtered list of score entries (by application or member) | FoundationAdmin, ProgramOfficer |
| GET | `/awards` | Filtered list of scholarship awards (by application, program, or fund) | FoundationAdmin, ProgramOfficer, FinanceOfficer |
| GET | `/statements` | Filtered list of annual statements (by fund) | FoundationAdmin, FinanceOfficer |
| GET | `/grants/{grantId}/disbursements` | Disbursements of a grant | FoundationAdmin, FinanceOfficer, ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_FUND_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POOL_VERSION` | 412 Precondition Failed |
| `ERR_AGREEMENT_NOT_EXECUTED` | 409 Conflict |
| `ERR_AGREEMENT_ALREADY_EXECUTED` | 409 Conflict |
| `ERR_MIN_INITIAL_CONTRIBUTION` | 422 Unprocessable Entity |
| `ERR_FUND_NOT_ACCEPTING` | 409 Conflict |
| `ERR_FUND_NOT_ACTIVE_FOR_GRANTS` | 409 Conflict |
| `ERR_FUND_NOT_EMPTY` | 409 Conflict |
| `ERR_PENDING_GRANTS` | 409 Conflict |
| `ERR_PROGRAM_OPEN` | 409 Conflict |
| `ERR_FUND_NOT_CLOSED` | 409 Conflict |
| `ERR_SUCCESSOR_NOT_ON_FUND` | 422 Unprocessable Entity |
| `ERR_NOT_THE_INVITED_ADVISOR` | 403 Forbidden |
| `ERR_ADVISOR_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_GRANT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_GRANTEE_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_ER_ACK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXCEEDS_SPENDABLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CASH` | 422 Unprocessable Entity |
| `ERR_SOD_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SOD_SELF_DISBURSE` | 403 Forbidden |
| `ERR_REVISION_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_COMMITTEE_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_NO_APPLICATIONS` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TOO_MANY_WINNERS` | 422 Unprocessable Entity |
| `ERR_UNSCORED_WINNER` | 422 Unprocessable Entity |
| `ERR_AWARDS_PENDING` | 409 Conflict |
| `ERR_PROGRAM_LOCKED` | 409 Conflict |
| `ERR_NOT_THE_APPLICANT` | 403 Forbidden |
| `ERR_NOT_THE_MEMBER` | 403 Forbidden |
| `ERR_POOL_NOT_OPEN` | 409 Conflict |
| `ERR_POOL_NOT_EMPTY` | 409 Conflict |
| `ERR_INSUFFICIENT_HISTORY` | 422 Unprocessable Entity |
| `ERR_LOT_PROCEEDS_MISSING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SCORE` | 409 Conflict |
| `ERR_UNIQUENESS_VIOLATION` | 409 Conflict |
| `ERR_FIELD_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 Unprocessable Entity |

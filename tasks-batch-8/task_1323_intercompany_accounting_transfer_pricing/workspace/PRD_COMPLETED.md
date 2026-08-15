# Intercompany Transfer Pricing API — Product Requirements Document

## 1. Introduction

Multinational groups live and die by the quality of their intercompany accounting. Every cross-border charge between group entities — goods, services, royalties, financing, cost sharing — must be priced under a defensible transfer pricing policy, recorded symmetrically in both ledgers, eliminated on consolidation, trued up against benchmarked arm's-length ranges at year end, documented in master and local files, and defended before tax authorities that increasingly demand country-by-country transparency. When any link in that chain is weak, the group faces double taxation, penalties, and audit exposure across every jurisdiction it touches.

This document specifies the Intercompany Transfer Pricing API, the system of record for a group tax department's transfer pricing operations. It governs the inventory of intercompany agreements and their pricing policies, the booking and matching of intercompany transactions, automatic elimination at fiscal-year close, cost-plus markup administration with year-end true-up runs, benchmarking studies and comparables refreshes, documentation package preparation and filing, audit defense files and advance pricing agreements, and the treasury cash pool that nets and settles intercompany balances. All resources are mounted under the `/tp` prefix.

The design reflects three regulatory realities. First, segregation of duties: the analyst who prepares a pricing decision may never be the manager who approves it. Second, evidence pinning: the moment an agreement is activated, the benchmarking study and arm's-length range supporting it are frozen onto the agreement so that later study refreshes cannot silently rewrite history. Third, a logical clock: fiscal years close on dates the operator controls, and interest accrues day by day against that clock rather than against wall time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled precisely as follows: `GroupTaxAdmin`, `TaxAnalyst`, `TaxManager`, `TransferPricingLead`, and `TreasuryManager`. Each write endpoint admits a specific subset of these roles (enumerated in §4); a caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All read endpoints are shared: every one of the five roles may call any GET operation.

`GroupTaxAdmin` is the group tax operations owner, responsible for fiscal years, legal entities, and the logical clock. `TaxAnalyst` is the preparer: it drafts agreements, books and matches transactions, drafts true-up runs, benchmarking studies, and documentation packages. `TaxManager` is the reviewer and approver: it activates and terminates agreements, approves amendments and true-ups, and approves and files documentation — and it never approves work submitted by itself. `TransferPricingLead` is the transfer pricing specialist: it approves and refreshes benchmarking studies and owns audit defense files and APA negotiations. `TreasuryManager` operates the cash pool lifecycle: pool creation, sweeps, netting, and settlement.

For every one of these five roles — `GroupTaxAdmin`, `TaxAnalyst`, `TaxManager`, `TransferPricingLead`, and `TreasuryManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where an action is attributable to a person (for example as `created_by_user_id` on an agreement, `matched_by_user_id` on a transaction, or `submitted_by_user_id` on a documentation package) and compares it against such stored identifiers when enforcing segregation of duties, but it never compares `X-User-ID` to any entity's `id`.

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

Endpoints that return lists of resources are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — values outside that range are clamped to the nearer bound rather than rejected. `offset` sets the number of items skipped and defaults to 0, with negative values clamped to 0. A `limit` or `offset` that does not parse as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Each filter query parameter a listing accepts restricts the result to resources whose named field exactly equals the supplied value.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in this API — fiscal years, legal entities, agreements, transactions, true-up runs, benchmarking studies, documentation packages, audit cases, and cash pools — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every change to the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource. Cascading side effects that mutate another resource also increment that resource's `version` by 1 and refresh its `updated_at`; a cascade that would merely re-set a flag to the value it already holds performs no write and leaves that resource's `version` and `updated_at` untouched.

### 2.5. The Logical Clock

The server maintains a logical clock that governs all business time. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `GroupTaxAdmin` may advance the clock by supplying a target instant `to_iso8601`; the response reports the resulting `current_utc`. The clock is monotonic: an attempt to set it backwards is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every timestamp the business logic stamps onto a resource — `closed_at` on a fiscal year, `filed_at` on a documentation package, `opened_at_utc` and `netting_at_utc` on a cash pool — is read from this logical clock, as are the date-window and day-count computations described in §3. Instants read from the logical clock are rendered as ISO 8601 UTC with three fractional digits, except that the fractional part is omitted entirely when it is exactly zero.

### 2.6. Monetary Precision, Basis Points, and Rounding

All monetary amounts are integer cents; all margins, markups, and range boundaries are integer basis points (one basis point is one hundredth of a percent, so 10000 basis points make one whole unit). Every computed monetary or basis-point value is rounded half-up to a whole integer at each computation step where a rule states a rounding — no banker's rounding, no truncation. Percentile ranks and day counts are whole numbers as defined by their respective rules in §3. The country-by-country threshold test is a pure integer comparison in whole euros and involves no rounding at all.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

Refreshing a benchmarking study requires the request to carry `expected_study_version`, the `version` of the study as the client last observed it. If the study's current `version` on the server differs from the supplied value — because another writer has advanced it since the client last read the study — the refresh is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because refresh creates a new `DRAFT` successor study; a refresh based on an unobserved version would fork two competing successor lines.

Posting sweep movements against a cash pool requires the request to carry `expected_cash_pool_version`, the pool's `version` as the client last observed it. A mismatch with the pool's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because sweep amounts are computed from observed position balances and a stale expectation would net against positions the client never saw. In the validation sequence of §2.8, the optimistic-concurrency check is evaluated immediately after state legality (step 4) and before every later category. The expected-version field is mandatory on both endpoints: a request that omits it, or carries it as a non-integer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) at the body-shape step.

Endpoints other than these two do not take a version field; clients must not supply one.

### 2.8. Validation Order and Error Precedence

Every request is validated against a fixed sequence of check categories, and the first failing check determines the error returned — a caller always sees the earliest applicable failure, not a later one. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role must be admitted by the endpoint, else `ERR_FORBIDDEN_FOR_ROLE`.
3. **Existence** — every identifier must resolve: path identifiers first, validated left to right, then body-supplied foreign keys in their declared order; the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404).
4. **State legality** — the target resource must be in a state from which the requested transition or operation is defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Acting on a terminal resource falls under this check as well.
5. **Segregation of duties** — where an approval or activation is guarded, the acting `X-User-ID` must differ from the stored creator, submitter, or amendment starter, else `ERR_SEGREGATION_OF_DUTIES`.
6. **Entity referential integrity** — referenced legal entities must be `ACTIVE` where required, and an agreement's provider and recipient must be distinct, else `ERR_ENTITY_INACTIVE` or `ERR_SAME_LEGAL_ENTITY`; within this step the provider–recipient distinctness check runs first, and a provider's active status is checked before a recipient's.
7. **Temporal rules** — agreement effective-period overlap, APA covered-year disjointness, and the in-effect window at activation, surfacing `ERR_AGREEMENT_PERIOD_OVERLAP`, `ERR_APA_YEAR_OVERLAP`, or `ERR_AGREEMENT_NOT_IN_EFFECT`.
8. **Structural business constraints** — benchmark freshness, match tolerance, zero-sum sweeps, non-empty defense files, document finality, APA locks, duplicate guards, and blocking transactions or true-up runs.
9. **Fiscal-calendar obligations** — the year must be `CLOSING` for true-up approval and posting, must not be `CLOSED` for booking or filing, and country-by-country filing presence and obligation are enforced at close and at filing.
10. **Request-body shape** — required fields present, enum values valid, amounts positive where required, and the structural rules of each resource.

Body shape is deliberately the lowest priority: when a request violates both a business rule and a shape rule and the offending field is parseable, the business error is surfaced first. A body so malformed that it cannot be parsed at all short-circuits as `ERR_INVALID_REQUEST` before the state check at step 4.

### 2.9. Resource Existence and Identifier Validation

The resource topology is flat: resources reference one another by foreign keys rather than by nested URL ownership. Wherever an identifier appears — in a path variable or in a request-body foreign key such as an `agreement_id` or `fiscal_year_id` — the server must resolve it, in the order given by step 3 of §2.8, and reject the request with `ERR_NOT_FOUND` on the first identifier that does not correspond to an existing resource. Only after every identifier resolves does the server evaluate state, segregation, and business rules. The existence check applies to identifiers supplied as non-empty strings; a body-supplied foreign key that is missing or not a string is left for the request-body shape check (step 10) rather than reported as `ERR_NOT_FOUND`.

### 2.10. Segregation of Duties

Preparer and approver are always different people. Five operations enforce this by comparing the acting `X-User-ID` against a stored user identifier on the target resource: activating an agreement compares against the agreement's `created_by_user_id`; approving an amendment compares against `amendment_started_by_user_id`; approving a true-up run compares against the run's `created_by_user_id`; approving a benchmarking study compares against the study's `created_by_user_id`; and approving a documentation package compares against `submitted_by_user_id`. In each case, an approver whose `X-User-ID` equals the stored identifier is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Fiscal Years, Legal Entities, and the Country-by-Country Threshold

A `GroupTaxAdmin` opens the fiscal calendar by creating a **FiscalYear** with a `year_index` (the calendar year number, such as 2026) and `group_revenue_eur`, the consolidated group revenue in whole euros — the prior-year figure used for the country-by-country threshold test. The `year_index` is unique across all fiscal years; a duplicate is rejected with `ERR_INVALID_REQUEST`. At creation the server computes `cbc_required`: it is true when `group_revenue_eur` is at least 750000000, and the boundary is inclusive — exactly 750000000 yields true while 749999999 yields false. A new fiscal year starts `OPEN` with `consolidated_intercompany_net_cents` at 0 and `closed_at` null.

Legal entities are the counterparties of every intercompany flow. A `GroupTaxAdmin` creates each **LegalEntity** with a `name`, an ISO 3166-1 alpha-2 `country_code`, and an ISO 4217 `functional_currency` (the two codes are stored as supplied; the server does not validate them against the ISO registries); it begins `ACTIVE`. Deactivation moves an entity from `ACTIVE` to `INACTIVE` and is blocked with `ERR_ENTITY_HAS_ACTIVE_AGREEMENTS` whenever any agreement in `ACTIVE` or `UNDER_AMENDMENT` references the entity as provider or recipient — agreements still in `DRAFT` do not block deactivation.

Year-end close is a two-phase ceremony. Beginning the closing moves the year `OPEN → CLOSING` and triggers automatic elimination: every transaction of the year whose `elimination_status` is `MATCHED` transitions to `ELIMINATED`, each booking a consolidation plug (see §3.4), and the year's `consolidated_intercompany_net_cents` is recomputed — it remains 0 by construction. Closing the year (`CLOSING → CLOSED`) is gated by three preconditions evaluated in the precedence order of §2.8: no transaction of the year may have an `elimination_status` other than `ELIMINATED` (`ERR_YEAR_HAS_OPEN_TRANSACTIONS`); no true-up run of the year may be in a status other than `POSTED` (`ERR_YEAR_HAS_OPEN_TRUE_UPS`); and if `cbc_required` is true, a documentation package of `doc_type` `CBC_REPORT` in status `FILED` must exist for the year (`ERR_CBC_FILING_MISSING`). On close the server stamps `closed_at` from the logical clock and fires a two-link staleness cascade: every benchmarking study in `CURRENT` whose `vintage_year` is less than or equal to the closing `year_index` minus 2 transitions to `STALE`, and every agreement pinned to one of those newly stale studies has its `pricing_review_required` flag set to true. Each mutation in this ceremony increments the owning resource's `version` by 1.

### 3.2. Benchmarking Studies and the Arm's-Length Range

A benchmarking study is the evidence base for a pricing policy. A `TaxAnalyst` drafts one by supplying a `transaction_type` (one of `GOODS`, `SERVICES`, `IP_ROYALTY`, `FINANCING`, `COST_SHARING`), a geographic `region` label, a `vintage_year` marking the data vintage, and `comparables_bp`, a list of comparable margins in basis points. The list must contain at least five entries; fewer is rejected with `ERR_INVALID_REQUEST`. The study starts in `DRAFT` with its `created_by_user_id` recorded, its quartile fields `p25_bp`, `median_bp`, and `p75_bp` null, and `supersedes_study_id` null.

Approval by a `TransferPricingLead` moves the study `DRAFT → CURRENT` and computes the interquartile range by the nearest-rank method: the comparables are sorted ascending; with `n` entries, the rank of the p-th percentile is the smallest integer greater than or equal to p multiplied by `n` and divided by 100, counting positions from 1; `p25_bp`, `median_bp`, and `p75_bp` are the sorted values at the ranks for 25, 50, and 75 respectively. For example, five comparables of 300, 400, 500, 600, and 700 give ranks 2, 3, and 4, hence `p25_bp` 400, `median_bp` 500, and `p75_bp` 600. Approval is segregation-guarded against the study's `created_by_user_id`. If the approved draft carries a `supersedes_study_id`, the referenced study — whether `CURRENT` or `STALE` — transitions to `SUPERSEDED` in the same operation.

Comparables age. A study in `CURRENT` becomes `STALE` automatically during fiscal-year close when its `vintage_year` is less than or equal to the closing year's `year_index` minus 2, as described in §3.1; agreements pinned to it are flagged for pricing review. To refresh the evidence, a `TransferPricingLead` requests a refresh on a `CURRENT` or `STALE` study, supplying a new `comparables_bp` list and the OCC field `expected_study_version` per §2.7. Refresh is not a state transition of the old study: it creates a new `DRAFT` study that inherits the refreshed study's `transaction_type`, `region`, and `vintage_year`, records the refreshing user as its `created_by_user_id`, and carries a `supersedes_study_id` pointing at the refreshed study, and it increments the refreshed study's `version` by 1 as the OCC witness. The new draft then travels its own approval path; only when it is approved does the parent study move to `SUPERSEDED`. The studies listing supports optional filters `supersedes_study_id`, `status`, and `transaction_type`, so a reviewer can trace an entire supersession lineage.

### 3.3. The Intercompany Agreement Lifecycle

The **IntercompanyAgreement** is the system's pricing contract between two group entities. A `TaxAnalyst` drafts one with a `provider_entity_id` (the selling or providing entity) and a `recipient_entity_id` (the buyer), a `transaction_type` from the same five-value enumeration used by studies, a `pricing_method` of `COST_PLUS`, `TNMM`, `RESALE_MINUS`, or `CUP`, a `true_up_method` of `TO_MEDIAN` or `TO_RANGE_EDGE` naming the arm's-length target the year-end true-up adjusts to, and a half-open effective window from `effective_from` (inclusive) to `effective_to` (exclusive). The server does not require `effective_from` to precede `effective_to`; an empty or inverted window is stored as supplied and simply never satisfies the in-effect test at activation. The provider and recipient must differ (`ERR_SAME_LEGAL_ENTITY`), both entities must be `ACTIVE` (`ERR_ENTITY_INACTIVE`), and the effective window must not overlap — under half-open semantics where one window ending exactly when another begins is adjacency, not overlap — any other agreement with the same provider, recipient, and transaction type in `DRAFT`, `ACTIVE`, or `UNDER_AMENDMENT` (`ERR_AGREEMENT_PERIOD_OVERLAP`). When `pricing_method` is `COST_PLUS`, two further inputs are mandatory: `markup_bp`, the applied markup in basis points, and `benchmarking_study_id`, the supporting study. The new agreement is `DRAFT`, records its `created_by_user_id`, starts with `amendments_count` at 0, and leaves `pinned_study_id`, the pinned range snapshot, the pending amendment fields, `pricing_review_required`, and `apa_locked` at their empty defaults.

Activation by a `TaxManager` moves the agreement `DRAFT → ACTIVE` and is the most heavily guarded transition in the system. In the precedence order of §2.8: the activator must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); both counterparties must still be `ACTIVE` (`ERR_ENTITY_INACTIVE`); the logical clock's date must fall inside the half-open window from `effective_from` to `effective_to` (`ERR_AGREEMENT_NOT_IN_EFFECT`); no other agreement with the same provider, recipient, and transaction type in `ACTIVE` or `UNDER_AMENDMENT` may overlap the window (`ERR_AGREEMENT_PERIOD_OVERLAP`); and the referenced `benchmarking_study_id` must resolve to a study in `CURRENT` (`ERR_STALE_BENCHMARK`). An agreement drafted without a `benchmarking_study_id` — permitted for the non-`COST_PLUS` methods — skips this check entirely and activates with all four pinned fields left null. Activation then pins the evidence: `pinned_study_id` is set to the referenced study and `pinned_p25_bp`, `pinned_median_bp`, and `pinned_p75_bp` are copied from it, freezing the arm's-length range that later true-up runs will test against.

Amendment is a cyclic detour out of and back into `ACTIVE`. A `TaxAnalyst` starts an amendment (`ACTIVE → UNDER_AMENDMENT`) by supplying `new_markup_bp` and optionally `new_benchmarking_study_id`; the server stores them as `pending_markup_bp` and `pending_study_id` and records `amendment_started_by_user_id`. Starting an amendment is refused with `ERR_APA_LOCKED` while `apa_locked` is true. Approval by a `TaxManager` (`UNDER_AMENDMENT → ACTIVE`) requires the approver to differ from `amendment_started_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`) and, when `pending_study_id` is set, requires that study to be `CURRENT` (`ERR_STALE_BENCHMARK`). Approval applies `pending_markup_bp` to `markup_bp`, and when a replacement study was proposed it also points the agreement's `benchmarking_study_id` at that study and re-pins the study and range snapshot from it; it then clears the pending fields, adds 1 to `amendments_count`, and resets `pricing_review_required` to false — because the approved amendment is precisely the expected response to a review flag. Alternatively, a `TaxAnalyst` may discard the amendment (`UNDER_AMENDMENT → ACTIVE`), which clears `pending_markup_bp`, `pending_study_id`, and `amendment_started_by_user_id` while leaving the markup and pins untouched; further amendment cycles remain allowed after either path.

Termination by a `TaxManager` (`ACTIVE → TERMINATED`) is refused with `ERR_APA_LOCKED` while an APA lock covers the agreement, and with `ERR_AGREEMENT_HAS_OPEN_TRANSACTIONS` while any transaction of the agreement has an `elimination_status` other than `ELIMINATED`. `TERMINATED` is terminal. The agreements listing accepts optional filters `provider_entity_id`, `recipient_entity_id`, `pinned_study_id`, `benchmarking_study_id`, and `status`.

### 3.4. Booking, Matching, and Eliminating Intercompany Transactions

Transactions are booked by a `TaxAnalyst` against an agreement and a fiscal year, carrying `agreement_id`, `fiscal_year_id`, the provider's `cost_base_cents` (the denominator of the cost-plus margin), the `provider_revenue_cents` the provider booked as revenue (the intercompany invoice price), and the `recipient_cost_cents` the recipient booked as cost. All three amounts are mandatory integers: `cost_base_cents` must be at least 1, while `provider_revenue_cents` and `recipient_cost_cents` must be at least 0; violations are `ERR_INVALID_REQUEST`. Booking is only permitted against an agreement in `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and never against a `CLOSED` fiscal year (`ERR_BOOKS_CLOSED`).

At booking the server derives two figures from the agreement's then-current `markup_bp`. The provisional arm's-length price, `provisional_al_price_cents`, is the cost base multiplied by the markup factor — that is, `cost_base_cents` multiplied by the sum of 10000 and `markup_bp`, divided by 10000 — rounded half-up to whole cents. The realized margin, `margin_bp`, is the excess of `provider_revenue_cents` over `cost_base_cents`, multiplied by 10000 and divided by `cost_base_cents`, rounded half-up. For the special case of a zero cost base — which arises only on system-created true-up adjustment entries — both figures are defined as 0. When the agreement carries no `markup_bp` — permitted for the non-`COST_PLUS` methods — the derivation proceeds with a markup of 0.

Every transaction carries two independent state dimensions. The elimination dimension runs `UNMATCHED → MATCHED → ELIMINATED`; the settlement dimension runs `UNSETTLED → NETTED → SETTLED`. A new booking starts `UNMATCHED` and `UNSETTLED`, with `origin_run_id` null and `is_true_up_adjustment` false.

Matching is the analyst's reconciliation act: a `TaxAnalyst` matches a transaction when the two sides' booked amounts agree within a tolerance of 100 cents — the absolute difference between `provider_revenue_cents` and `recipient_cost_cents` must be at most 100, otherwise the match is rejected with `ERR_ELIMINATION_MISMATCH`. Matching records `matched_by_user_id` and advances only the elimination dimension; the settlement dimension is untouched, and conversely netting (§3.8) operates on `MATCHED` transactions that have not yet been eliminated — the dimensions evolve independently.

Elimination is always systemic, never manual. During the begin-closing ceremony every `MATCHED` transaction of the year moves to `ELIMINATED`, and each elimination books a consolidation plug equal to `provider_revenue_cents` minus `recipient_cost_cents`, so the year's `consolidated_intercompany_net_cents` — the running sum over eliminated transactions of provider revenue minus recipient cost minus the plug — increases by exactly zero with each entry. Eliminations are processed in chronological order of transaction creation, ascending, and the invariant that `consolidated_intercompany_net_cents` equals 0 holds after every elimination batch. The transactions listing accepts optional filters `agreement_id`, `fiscal_year_id`, `origin_run_id`, `elimination_status`, and `settlement_status`.

### 3.5. Year-End True-Up Runs

When the booked margin drifts outside the pinned arm's-length range, the group trues up. A `TaxAnalyst` creates a **TrueUpRun** for an `agreement_id` and `fiscal_year_id`; it starts `DRAFT` with `created_by_user_id` recorded and `actual_margin_bp`, `true_up_amount_cents`, `adjustment_transaction_id`, and `approved_by_user_id` null.

Computation (`DRAFT → COMPUTED`) requires at least one transaction for the agreement and year with an `elimination_status` of `MATCHED` or `ELIMINATED`; an empty input set is rejected with `ERR_NO_ELIMINATED_TRANSACTIONS`. The tested set is exactly those `MATCHED` and `ELIMINATED` transactions — `UNMATCHED` bookings are excluded. The run aggregates the set's total cost base and total booked provider revenue, then derives the `actual_margin_bp`: the excess of total booked revenue over total cost base, multiplied by 10000, divided by the total cost base, rounded half-up. A zero total cost base — possible only when the tested set consists solely of true-up adjustment entries — yields an `actual_margin_bp` of 0, mirroring the zero-cost-base rule of §3.4. If the agreement carries no pinned range — because it was activated without a benchmarking study — the computation records the `actual_margin_bp` and sets `true_up_amount_cents` to 0; otherwise the margin is tested against the agreement's pinned range formed by `pinned_p25_bp` and `pinned_p75_bp`, with `pinned_median_bp` as the midpoint. Range membership is inclusive: when the actual margin lies at or between the pinned P25 and P75, the `true_up_amount_cents` is 0 and no adjustment is needed. Outside the range, the target margin depends on the agreement's `true_up_method`: under `TO_MEDIAN` the target is the pinned median; under `TO_RANGE_EDGE` the target is whichever of the pinned P25 or P75 is closer to the actual margin, with an exact tie resolving to the lower edge — the range-edge variant deliberately produces a smaller adjustment than the median variant for the same data. The target price is then the total cost base multiplied by the sum of 10000 and the target margin, divided by 10000, rounded half-up to whole cents, and the `true_up_amount_cents` is that target price minus the total booked revenue — a signed figure where a positive amount means the recipient owes the provider.

A computed run may be sent back for rework: recomputation (`COMPUTED → DRAFT`) resets `actual_margin_bp` and `true_up_amount_cents` to null so computation can run again, forming a deliberate cyclic loop. Approval by a `TaxManager` (`COMPUTED → APPROVED`) requires the fiscal year to be `CLOSING` (`ERR_YEAR_NOT_CLOSING`) and the approver to differ from the run's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); it records `approved_by_user_id`. Posting by a `TaxManager` (`APPROVED → POSTED`) again requires the year to be `CLOSING` and fires a three-link cascade. First, when the `true_up_amount_cents` is not 0, the server creates an adjustment transaction for the same agreement and year with `cost_base_cents` of 0, both `provider_revenue_cents` and `recipient_cost_cents` equal to the true-up amount, `origin_run_id` pointing at the run, `is_true_up_adjustment` true, `elimination_status` `MATCHED`, and `settlement_status` `UNSETTLED`, and records its identifier as the run's `adjustment_transaction_id`; when the amount is 0 no adjustment is created, the field stays null, and the remaining two links are skipped as well — no elimination occurs and no cash-pool positions are upserted or modified. Second, the adjustment is immediately auto-eliminated to `ELIMINATED` with a plug of 0. Third, if a cash pool exists for the fiscal year in status `OPEN`, the provider entity's position `pending_cents` is increased by the true-up amount and the recipient entity's position `pending_cents` is decreased by the same amount, with positions upserted per entity as needed. The true-up runs listing accepts optional filters `agreement_id`, `fiscal_year_id`, `adjustment_transaction_id`, and `status`.

### 3.6. Documentation Packages and Filing Obligations

Transfer pricing documentation is produced per fiscal year. A `TaxAnalyst` creates a **DocPackage** with a `fiscal_year_id` and a `doc_type` of `MASTER_FILE`, `LOCAL_FILE`, or `CBC_REPORT`. A `LOCAL_FILE` must name the `entity_id` it documents, and that entity must be `ACTIVE`; `MASTER_FILE` and `CBC_REPORT` packages must not carry an `entity_id` at all — violations of either structural rule are `ERR_INVALID_REQUEST`. At most one `CBC_REPORT` package may exist per fiscal year; a second is rejected with `ERR_DUPLICATE_CBC_REPORT`. A new package is `DRAFT`, with `submitted_by_user_id`, `approved_by_user_id`, and `filed_at` empty.

The package then walks a three-step review chain. Submission by a `TaxAnalyst` (`DRAFT → SUBMITTED`) records `submitted_by_user_id`. Approval by a `TaxManager` (`SUBMITTED → APPROVED`) is segregation-guarded against the submitter (`ERR_SEGREGATION_OF_DUTIES`) and records `approved_by_user_id`. Filing by a `TaxManager` (`APPROVED → FILED`) enforces three obligations: the fiscal year must not be `CLOSED` (`ERR_BOOKS_CLOSED`); a `CBC_REPORT` may only be filed for a year whose `cbc_required` is true (`ERR_CBC_NOT_REQUIRED`); and a `LOCAL_FILE` may not be filed while any `ACTIVE` agreement of its entity carries `pricing_review_required` true (`ERR_STALE_BENCHMARK`) — the group must refresh and re-approve stale pricing evidence before it attests a local file. Filing stamps `filed_at` from the logical clock; `FILED` is terminal. The packages listing accepts optional filters `fiscal_year_id`, `entity_id`, `doc_type`, and `status`.

### 3.7. Audit Defense Files and Advance Pricing Agreements

When a tax authority opens an examination, a `TransferPricingLead` opens an **AuditCase** naming the audited `entity_id` (which must be `ACTIVE`), a `case_type` of `AUDIT` or `APA`, and the `authority_country` as an ISO country code. An APA case additionally requires `covered_year_indexes`, a non-empty list of the integer year indexes the arrangement covers; an `AUDIT` case may carry an optional list of integer year indexes that plays no role in any rule. The `authority_country` is recorded as supplied, without ISO-registry validation. The covered years must be disjoint from the covered years of every other APA case for the same entity whose status is `OPENED`, `ACTIVE_PREP`, `SUBMITTED_TO_AUTHORITY`, or `CLOSED_AGREED` — an agreed APA therefore keeps blocking its covered years — and an intersection is rejected with `ERR_APA_YEAR_OVERLAP`. The case opens in `OPENED` with an empty `defense_doc_ids` list.

The defense file is assembled by attaching documentation packages. Each attachment names a `doc_package_id` and requires the package to be `APPROVED` or `FILED` (`ERR_DOC_NOT_FINAL`); the identifier is appended to `defense_doc_ids` in order. The first successful attachment automatically advances the case `OPENED → ACTIVE_PREP`; subsequent attachments are self-transitions within `ACTIVE_PREP`. When the file is ready, the lead submits the response to the authority, moving the case from either `OPENED` or `ACTIVE_PREP` to `SUBMITTED_TO_AUTHORITY`; submitting with an empty defense file is rejected with `ERR_DEFENSE_FILE_EMPTY` — a business error, raised even from `OPENED`, since the submission transition itself is defined from both states.

Resolution is defined only from `SUBMITTED_TO_AUTHORITY` — invoking it from any other status is `ERR_INVALID_STATE_TRANSITION` — and branches on `case_type`. Resolving an `AUDIT` case lands in `CLOSED_RESOLVED`. Resolving an `APA` case lands in `CLOSED_AGREED` and locks the covered pricing: every agreement whose provider or recipient is the case entity, whose status is `ACTIVE` or `UNDER_AMENDMENT`, and whose effective window covers the first of January of at least one year in `covered_year_indexes` — that is, `effective_from` on or before that January 1 and `effective_to` after it — has its `apa_locked` flag set to true for the APA term. While `apa_locked` is true, starting an amendment or terminating the agreement is refused with `ERR_APA_LOCKED`, as described in §3.3. Both terminal states close the case. The audit cases listing accepts optional filters `entity_id`, `case_type`, and `status`.

### 3.8. Cash Pooling: Sweeps, Netting, and Settlement

The treasury cash pool nets intercompany balances and prices the internal funding. A `TreasuryManager` creates the **CashPool** for a `fiscal_year_id` with an `interest_method` of `AVERAGE_BALANCE` or `CLOSING_BALANCE` and a flat `admin_fee_cents` — a mandatory integer of at least 0 — to be allocated pro-rata at netting. At most one pool may exist per fiscal year (`ERR_DUPLICATE_CASH_POOL`). The pool opens in `OPEN` with an empty `positions` array and `opened_at_utc` stamped from the logical clock — the day-count epoch for interest — while `netting_at_utc` stays null until netting begins.

While the pool is `OPEN`, the treasury posts sweep movements. Each sweep request carries a `movements` list — every element naming an `entity_id` and a signed integer amount in cents carried in `amount_cents` (the alias `amount` is also accepted) — plus the OCC field `expected_cash_pool_version` per §2.7. The amounts within one sweep request must sum to zero across entities (`ERR_POOL_NOT_ZERO_SUM`). Each movement upserts the entity's position object — which carries `entity_id`, `balance_cents`, `accrued_balance_day_cents`, `pending_cents`, `interest_cents`, `fee_cents`, and a `status` that mirrors the pool's phase (`OPEN` when the position is created, `NETTING` once netting begins, `SETTLED` at settlement) — adding the amount to the position's `balance_cents` and accruing balance-days: under the average-balance convention, each sweep adds the position's balance immediately before the sweep multiplied by the whole days elapsed since the previous event, measured on the logical clock.

Beginning the netting (`OPEN → NETTING`) stamps `netting_at_utc` and settles four accounts in one atomic ceremony. First, the final balance-day epoch accrues: under `AVERAGE_BALANCE`, the current balance multiplied by the whole days from the pool's opening or the last sweep — whichever is later — to `netting_at_utc` is added to each position's `accrued_balance_day_cents`. Second, interest is computed per position at a per-diem spread of 85 basis points per annum — that is, 85 divided by 10000 and by 365 per cent-day. Under `AVERAGE_BALANCE` the interest base is the position's accumulated `accrued_balance_day_cents`, so the intra-period timing of sweeps changes the result; under `CLOSING_BALANCE` the base is the position's `balance_cents` multiplied by the whole days from `opened_at_utc` to `netting_at_utc`, ignoring intra-period timing entirely and yielding different cents for identical sweeps. Interest is computed on the balances as they stand before any folding, so a position first created by the transaction fold below accrues no balance-days and carries `interest_cents` 0. Each position's `interest_cents` is the base multiplied by the spread, rounded half-up, signed with the balance — lenders positive, borrowers negative — so the interest across positions sums to zero by symmetry of the base signs. Third, each position's `pending_cents` is folded into `balance_cents` and reset to 0, and every transaction of the pool's fiscal year that is still `UNSETTLED` with an `elimination_status` of `MATCHED` or `ELIMINATED` transitions to `NETTED` in chronological order of transaction creation, adding its `provider_revenue_cents` to the provider entity's balance and subtracting its `recipient_cost_cents` from the recipient entity's balance. Fourth, the administration fee is allocated: the fee base is the sum of the absolute balances across all positions after pending amounts and transaction netting have been folded in; walking positions in order of their entity's `created_at` ascending, each position's `fee_cents` is the `admin_fee_cents` multiplied by the position's absolute balance and divided by the fee base, rounded half-up per position first; the residual — the fee minus the sum of the rounded per-position amounts, which may be positive or negative — is assigned to the position with the largest absolute balance, with ties broken by the entity's `created_at` ascending, never by entity identifier. If the fee base is 0 because every position balance is 0, each position's `fee_cents` is set to 0 and the entire `admin_fee_cents` is assigned to the first position in that entity-`created_at` order. This pinned order — round per position, then sum, then residual — is the only accepted sequence; summing first and rounding once is a rejected alternative. At every step the positions remain zero-sum in aggregate: sweeps are zero-sum validated, pending accruals are symmetric, and transaction folds are symmetric.

Settlement by a `TreasuryManager` (`NETTING → SETTLED`) requires the sum of all positions' `balance_cents` to be exactly 0 after folding (`ERR_POOL_NOT_ZERO_SUM`). On success every position's `status` becomes `SETTLED` and every `NETTED` transaction of the year becomes `SETTLED`, ending both the pool lifecycle and the settlement dimension of its transactions. The pools listing accepts an optional `fiscal_year_id` filter.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource — including all state transitions and the clock-setting capability — return `200 OK`. The refresh of a benchmarking study returns `201 Created` because it creates the successor `DRAFT` study.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tp/_clock/set_current_utc` | Advance the server's logical clock | GroupTaxAdmin |
| POST | `/tp/fiscal_years` | Create a fiscal year; computes the CbC obligation | GroupTaxAdmin |
| GET | `/tp/fiscal_years/{fiscalYearId}` | Get a fiscal year | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/fiscal_years/{fiscalYearId}/begin_closing` | Begin closing; auto-eliminates matched transactions | GroupTaxAdmin |
| POST | `/tp/fiscal_years/{fiscalYearId}/close` | Close the year; cascades study staleness and review flags | GroupTaxAdmin |
| POST | `/tp/legal_entities` | Create a legal entity | GroupTaxAdmin |
| GET | `/tp/legal_entities/{legalEntityId}` | Get a legal entity | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/legal_entities/{legalEntityId}/deactivate` | Deactivate an entity not bound to live agreements | GroupTaxAdmin |
| POST | `/tp/agreements` | Create a draft intercompany agreement | TaxAnalyst |
| GET | `/tp/agreements/{agreementId}` | Get an agreement | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/agreements` | List agreements with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/agreements/{agreementId}/activate` | Activate a draft agreement and pin its study | TaxManager |
| POST | `/tp/agreements/{agreementId}/start_amendment` | Open an amendment cycle on an active agreement | TaxAnalyst |
| POST | `/tp/agreements/{agreementId}/approve_amendment` | Approve and apply a pending amendment | TaxManager |
| POST | `/tp/agreements/{agreementId}/discard_amendment` | Discard a pending amendment without applying it | TaxAnalyst |
| POST | `/tp/agreements/{agreementId}/terminate` | Terminate an active agreement | TaxManager |
| POST | `/tp/transactions` | Book an intercompany transaction | TaxAnalyst |
| GET | `/tp/transactions/{transactionId}` | Get a transaction | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/transactions` | List transactions with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/transactions/{transactionId}/match` | Match a transaction within the booking tolerance | TaxAnalyst |
| POST | `/tp/true_up_runs` | Create a draft true-up run | TaxAnalyst |
| GET | `/tp/true_up_runs/{trueUpRunId}` | Get a true-up run | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/true_up_runs` | List true-up runs with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/true_up_runs/{trueUpRunId}/compute` | Compute the tested margin and true-up amount | TaxAnalyst |
| POST | `/tp/true_up_runs/{trueUpRunId}/recompute` | Reset a computed run back to draft | TaxAnalyst |
| POST | `/tp/true_up_runs/{trueUpRunId}/approve` | Approve a computed true-up run | TaxManager |
| POST | `/tp/true_up_runs/{trueUpRunId}/post` | Post the run; creates and eliminates the adjustment | TaxManager |
| POST | `/tp/benchmarking_studies` | Create a draft benchmarking study | TaxAnalyst |
| GET | `/tp/benchmarking_studies/{benchmarkingStudyId}` | Get a benchmarking study | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/benchmarking_studies` | List benchmarking studies with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/benchmarking_studies/{benchmarkingStudyId}/approve` | Approve a study; computes the interquartile range | TransferPricingLead |
| POST | `/tp/benchmarking_studies/{benchmarkingStudyId}/refresh` | Create a successor draft study (OCC-guarded) | TransferPricingLead |
| POST | `/tp/doc_packages` | Create a draft documentation package | TaxAnalyst |
| GET | `/tp/doc_packages/{docPackageId}` | Get a documentation package | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/doc_packages` | List documentation packages with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/doc_packages/{docPackageId}/submit` | Submit a package for review | TaxAnalyst |
| POST | `/tp/doc_packages/{docPackageId}/approve` | Approve a submitted package | TaxManager |
| POST | `/tp/doc_packages/{docPackageId}/file` | File an approved package | TaxManager |
| POST | `/tp/audit_cases` | Open an audit or APA case | TransferPricingLead |
| GET | `/tp/audit_cases/{auditCaseId}` | Get an audit case | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/audit_cases` | List audit cases with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/audit_cases/{auditCaseId}/attach_doc` | Attach a final documentation package to the defense file | TransferPricingLead |
| POST | `/tp/audit_cases/{auditCaseId}/submit_response` | Submit the defense response to the authority | TransferPricingLead |
| POST | `/tp/audit_cases/{auditCaseId}/resolve` | Resolve the case; APA resolution locks covered pricing | TransferPricingLead |
| POST | `/tp/cash_pools` | Create the cash pool for a fiscal year | TreasuryManager |
| GET | `/tp/cash_pools/{cashPoolId}` | Get a cash pool including its positions | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| GET | `/tp/cash_pools` | List cash pools with optional filters | GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager |
| POST | `/tp/cash_pools/{cashPoolId}/sweeps` | Post zero-sum sweep movements (OCC-guarded) | TreasuryManager |
| POST | `/tp/cash_pools/{cashPoolId}/begin_netting` | Begin netting; computes interest, fees, and folds | TreasuryManager |
| POST | `/tp/cash_pools/{cashPoolId}/settle` | Settle the pool and its netted transactions | TreasuryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_ENTITY_INACTIVE` | 409 Conflict |
| `ERR_SAME_LEGAL_ENTITY` | 409 Conflict |
| `ERR_ENTITY_HAS_ACTIVE_AGREEMENTS` | 409 Conflict |
| `ERR_AGREEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_EFFECT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_HAS_OPEN_TRANSACTIONS` | 409 Conflict |
| `ERR_APA_LOCKED` | 409 Conflict |
| `ERR_STALE_BENCHMARK` | 409 Conflict |
| `ERR_ELIMINATION_MISMATCH` | 409 Conflict |
| `ERR_NO_ELIMINATED_TRANSACTIONS` | 409 Conflict |
| `ERR_YEAR_NOT_CLOSING` | 409 Conflict |
| `ERR_YEAR_HAS_OPEN_TRANSACTIONS` | 409 Conflict |
| `ERR_YEAR_HAS_OPEN_TRUE_UPS` | 409 Conflict |
| `ERR_BOOKS_CLOSED` | 409 Conflict |
| `ERR_CBC_NOT_REQUIRED` | 409 Conflict |
| `ERR_CBC_FILING_MISSING` | 409 Conflict |
| `ERR_DUPLICATE_CBC_REPORT` | 409 Conflict |
| `ERR_DOC_NOT_FINAL` | 409 Conflict |
| `ERR_DEFENSE_FILE_EMPTY` | 409 Conflict |
| `ERR_APA_YEAR_OVERLAP` | 409 Conflict |
| `ERR_POOL_NOT_ZERO_SUM` | 409 Conflict |
| `ERR_DUPLICATE_CASH_POOL` | 409 Conflict |

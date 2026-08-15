# Deposit Pricing Governance API — Product Requirements Document

## 1. Introduction

Retail deposit pricing is a governance discipline before it is a mathematical one. A bank's pricing committee designs tiered rate structures per product and market, watches competitor rate scans to keep its repricing cadence honest, runs promotional offers with explicit rollover treatment, and grants off-sheet exception rates only inside a documented authority ladder. Every rate change must deploy cleanly across the branch, online, mobile, and call-center channels, and customers must receive disclosures within regulated lead times — above all when a change moves against them. Behind the scenes, treasury's cost-of-funds curve anchors margin analysis, relationship bundles reward qualified households, and grandfathered term accounts must survive sheet turnover until someone deliberately migrates them.

This document specifies the API that operates that entire lifecycle. It covers how deposit products and rate sheets are drafted, reviewed, scheduled, activated, and retired; how competitor intelligence and funding curves feed the margin gate; how accounts are opened, priced, repriced, enrolled in promotions, and credited interest under a logical clock; how exception pricing requests move through a segregation-of-duties review; and how bundle enrollments and migration batches reprice whole customer populations. The audience is the engineering team building the service. Every rule below is contractual: thresholds, boundary inclusivity, evaluation orders, and error identifiers are stated exactly once in prose and summarized in the tables at the end.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: identity, envelopes, pagination, time, resource shape, arithmetic, concurrency, addressing, disclosure discipline, and the order in which validations fire.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's capacity. A request missing either header, or presenting an `X-User-Role` value outside the declared role set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly seven roles. A `PricingAnalyst` drafts rate sheets, uploads and analyzes competitor scans, manages repricing cycles, creates and publishes promotional offers, and schedules and activates rate changes. A `PricingCommittee` member approves or returns rate sheets, retires sheets, decides exception requests of any authority tier, and is the sole authority for committee-tier exceptions and revocations. A `TreasuryOfficer` publishes funding curves. A `BranchBanker` opens and services accounts, adjusts balances, posts interest, enrolls accounts in promotions, creates and resubmits exception requests, applies approved exceptions, and decides branch-tier exceptions. A `ComplianceOfficer` resolves disclosure notices. A `ChannelOperator` executes rate deployments to the delivery channels. An `OperationsAdmin` manages products, relationship bundles and enrollments, migration batches, and the logical clock.

For every one of these seven roles — `PricingAnalyst`, `PricingCommittee`, `TreasuryOfficer`, `BranchBanker`, `ComplianceOfficer`, `ChannelOperator`, and `OperationsAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` and `decided_by_user_id` on an exception request, where segregation of duties is enforced) but never compares it against any entity's `id`.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10, accepts a minimum of 1, and is bounded above by 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

Paginated list responses include four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Time Sweep

All temporal semantics in the system derive from a server-held logical clock, never from the host's wall clock. At server startup the clock reads exactly `2026-08-01T00:00:00Z`; there is no wall-clock fallback at any point. An `OperationsAdmin` advances it through the clock-set capability (`POST /_clock/set_current_utc`), whose request body carries `to_iso8601` and whose response echoes the new logical instant as `current_utc`. Throughout this document the phrase "logical today" means the calendar date of the logical clock in UTC, and every window check, deadline, lateness flag, cadence evaluation, and sweep below reads that date.

Advancing the clock runs a time sweep, processed day by day in date order so that balance and rate changes apply from the day they take effect. Each elapsed day applies six steps, in this order:

1. Daily interest accrual: every account whose lifecycle is not `CLOSED` accrues that day's interest into `unposted_accrual_milli` (see §3.5).
2. Promotional-offer activation and expiry: offers in `SCHEDULED` whose `enrollment_start` has been reached become `ACTIVE`; offers whose `enrollment_end` has passed — whether still `SCHEDULED` or already `ACTIVE` — become `EXPIRED`.
3. Per-account promo rollover for accounts whose `promo_end_date` has passed, including `RENEW_THEN_SHEET` extension (see §3.5).
4. Applied exceptions whose `exception_end_date` has passed expire, and their accounts revert to sheet pricing (see §3.6).
5. `PROMO_EXPIRY` notices are created for accounts whose `promo_end_date` is exactly thirty days in the future (see §2.9).
6. Exception requests that were approved but never applied expire once logical today is more than thirty days past the decision date (see §3.6).

### 2.5. Common Resource Properties

All thirteen resources in the system — DepositProduct, RateSheet, CompetitorRateScan, RepricingCycle, PromotionalOffer, ExceptionPricingRequest, DepositAccount, FundingCurve, RelationshipBundle, CustomerBundleEnrollment, DisclosureNotice, RateDeployment, and MigrationBatch — share one set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): starts at 1 on creation and increments by exactly one on every mutation. State transitions, cascade-driven repricing, sweep-driven changes, and explicit edits all count as mutations — none of them is exempt.

Because cascades bump versions (a sheet activation, for instance, bumps the version of every account it reprices), a client holding a version read before the cascade is holding a stale version afterward; §2.7 defines how the two guarded writes exploit that fact.

### 2.6. Rate, Balance, and Accrual Arithmetic

Rates are always integer basis points. Balances and projected balances are always integer cents. Accrued-but-unposted interest is tracked in integer milli-cents (thousandths of a cent). Wherever a computed rate or benchmark is not naturally a whole number, the system rounds half up to the nearest whole basis point unless a rule states otherwise.

Daily accrual is the exception to rounding policy: each day's accrual is floored (rounded down) to a whole milli-cent, never rounded to cents. The accumulated milli-cents are converted to cents exactly once, at posting time, using round half up. The server never rounds each day's accrual to cents before summing — summing first and rounding once at posting is the pinned behavior, because per-day rounding to cents yields a different posted total.

Date fields (`effective_date`, `enrollment_start`, and the like) are ISO 8601 calendar-date strings. Timestamp fields (`sent_at`, `deployed_at`, and the envelope's `api_request_timestamp`) are ISO 8601 UTC datetimes with three fractional digits.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints carry an optimistic-concurrency guard, each keyed to the version of the resource being modified:

- Editing a DRAFT rate sheet (`PATCH /rate-sheets/{id}`) requires the non-optional field `expected_sheet_version`, carrying the sheet `version` the client last observed. If the sheet's current `version` has advanced past that value, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite sheet edits it has not observed.
- Adjusting an account balance (`PATCH /deposit-accounts/{id}`) requires the non-optional field `expected_account_version`, carrying the account `version` the client last observed. If the account's current `version` has advanced — including through cascade-driven repricing from sheet activation, migration execution, or bundle changes — the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412).

Both edits remain legitimate writes under product semantics; the guard exists purely to detect that the writer's view of the resource is stale. No endpoint other than these two accepts a version field.

### 2.8. Product–Market Addressing and Sheet Lineage

The resource topology is flat: every resource is addressed by a single identifier in its URL path, and there are no nested paths. A path identifier that does not correspond to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in request bodies are validated after path existence, each mapping to its own HTTP 422 error: a missing `product_id` reference yields `ERR_PRODUCT_NOT_FOUND`, a missing `sheet_id` yields `ERR_SHEET_NOT_FOUND`, a missing `account_id` yields `ERR_ACCOUNT_NOT_FOUND`, a missing `promo_offer_id` yields `ERR_PROMO_NOT_FOUND`, and a missing `bundle_id` yields `ERR_BUNDLE_NOT_FOUND`.

The organizing axis of the pricing domain is the product–market pair: a `product_id` together with a `market_code` (a free-form market string such as `US-WEST` or `US-EAST`; there is no Market entity). Rate sheets are versioned per pair: `sheet_version` starts at 1 for the first sheet of a pair and increments by one for each subsequent sheet created for the same pair. Two uniqueness invariants hold per pair at all times: at most one sheet in `DRAFT` (a second attempt fails with `ERR_DRAFT_SHEET_EXISTS`), and at most one sheet in `EFFECTIVE` (activation atomically supersedes the incumbent, so the invariant is never violated even momentarily). Sheets form a lineage through `supersedes_sheet_id`, which points at the sheet a given sheet replaced.

A sheet prices accounts over a half-open effective window that begins on `effective_date` (inclusive) and ends on `end_date` (exclusive). An omitted `end_date` defaults to `9999-12-31`, meaning open-ended. Two windows that merely touch — one sheet's `effective_date` equal to another's `end_date` — are adjacent, not overlapping, and adjacency is always permitted.

Channels are enumerated exactly as `BRANCH`, `ONLINE`, `MOBILE`, and `CALL_CENTER`. Wherever the system creates one row per channel (deployments and sheet-level notices at scheduling time), it creates them in this fixed order, and filtered list reads of those rows return them in creation order.

### 2.9. Disclosure Notice Discipline

Customer-facing disclosure is modeled as DisclosureNotice rows, each with a `sheet_id`, an optional `account_id`, a `channel`, a `notice_type`, a `required_by_date`, a `sent_at` timestamp, an `is_late` flag, and a `status` of `PENDING`, `SENT`, or `WAIVED`. Three notice types exist:

- `PRE_CHANGE` — sheet-level notices (their `account_id` is null), created one per channel when a sheet is scheduled. The required date is the sheet's `effective_date` minus its `disclosure_lead_days`, so a sheet scheduled with a thirty-day lead must be disclosed no later than thirty days before it takes effect.
- `RATE_CHANGE_ADVERSE` — account-level notices created whenever a repricing event (sheet activation, exception expiry, promo rollover, or migration) lowers an account's rate by ten basis points or more. The notice rides the account's home `channel`, and its required date is five days after the triggering date.
- `PROMO_EXPIRY` — account-level notices created by the time sweep thirty days before an enrolled account's `promo_end_date`; the required date is `promo_end_date` minus thirty days.

The `is_late` flag is true when the notice was sent on a date after its `required_by_date`, and also — read as a computed property — when the notice is still `PENDING` and logical today has already passed the required date.

A `ComplianceOfficer` resolves a pending notice through the notice-resolution capability: action `SEND` moves `PENDING` to `SENT`, stamps `sent_at` with the current logical instant, and fixes `is_late` from the sent date; action `WAIVE` moves `PENDING` to `WAIVED` and requires a `reason` (its absence is rejected with `ERR_INVALID_REQUEST`). Resolving a notice that is already `SENT` or `WAIVED` is rejected with `ERR_NOTICE_ALREADY_RESOLVED`. Notices can be listed with filters on `sheet_id`, `account_id`, `status`, and `channel`.

### 2.10. Validation Order of Evaluation

Every request is evaluated against a fixed ladder of checks; the first failure stops evaluation and determines the error response. The ladder, from first to last:

1. Authentication: the identity headers are present and the role is declared (`ERR_UNAUTHENTICATED`, 401).
2. Role authorization: the role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. Request schema: required fields present, types and enum values valid, dates well-formed (`ERR_INVALID_REQUEST`, 400).
4. Path existence: the resource named in the path exists (`ERR_NOT_FOUND`, 404).
5. Body foreign keys: every referenced `product_id`, `sheet_id`, `account_id`, `promo_offer_id`, and `bundle_id` exists (the corresponding 422 error from §2.8).
6. From-state validity: the target resource is in a state from which the requested transition exists — sheets surface `ERR_SHEET_INVALID_STATE`, offers `ERR_PROMO_INVALID_STATE`, exception requests `ERR_EXCEPTION_INVALID_STATE`, accounts `ERR_ACCOUNT_INVALID_STATE`, migration batches `ERR_MIGRATION_INVALID_STATE`, enrollments `ERR_ENROLLMENT_INVALID_STATE`, scans `ERR_SCAN_INVALID_STATE`, deployments `ERR_DEPLOYMENT_INVALID_STATE`, and notice re-resolution `ERR_NOTICE_ALREADY_RESOLVED` (all 409).
7. Concurrency: on the two guarded writes of §2.7, the expected version matches (`ERR_STALE_VERSION`, 412).
8. Business rules, in the endpoint-specific order given below.

Because the ladder is ordered, a request that fails both schema and concurrency surfaces `ERR_INVALID_REQUEST`, not `ERR_STALE_VERSION`; a request that fails both state and a business gate surfaces the state error.

Where several business rules guard one endpoint, they fire in this relative order:

- Rate sheet creation: the one-draft-per-pair rule (`ERR_DRAFT_SHEET_EXISTS`) first, then tier structure (`ERR_TIER_STRUCTURE_INVALID`), then the per-tier rate cap (`ERR_RATE_CAP_EXCEEDED`).
- Sheet submission: tier structure revalidation first, then the presence of an operative funding curve covering the product tenor (`ERR_NO_FUNDING_CURVE`), then the margin floor (`ERR_MARGIN_BELOW_FLOOR`).
- Sheet activation: the disclosure gate (`ERR_DISCLOSURE_LEAD_TIME_UNMET`) first — so a late or unsent disclosure surfaces rather than being masked by a later gate — then deployment completeness (`ERR_DEPLOYMENT_INCOMPLETE`), then the future-effective-date check (`ERR_FUTURE_EFFECTIVE_DATE`).
- Offer publication: enrollment-window sanity (`enrollment_start` not later than `enrollment_end`, else `ERR_INVALID_REQUEST`) first, then the closed-window overlap check (`ERR_PROMO_WINDOW_OVERLAP`).
- Promo enrollment: enrollability (`ERR_PROMO_NOT_ENROLLABLE`) first, then the minimum opening balance (`ERR_PROMO_MIN_BALANCE_UNMET`).
- Exception creation: the product's exception permission (`ERR_INVALID_REQUEST`) first, then documentation completeness (`ERR_EXCEPTION_DOCS_MISSING`), then baseline-sheet effectiveness (`ERR_BASELINE_SHEET_NOT_EFFECTIVE`), then the delta ceiling (`ERR_EXCEPTION_DELTA_EXCEEDS_MAX`).
- Exception decision: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) first, then — for approvals — baseline-sheet effectiveness (`ERR_BASELINE_SHEET_NOT_EFFECTIVE`), then authority-tier permission (`ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`). Decline and return decisions enforce segregation alone.
- Exception resubmission: documentation completeness first, then the delta ceiling.
- Migration execution: batch and source-sheet state (`ERR_MIGRATION_INVALID_STATE`) first, then target-sheet effectiveness (`ERR_MIGRATION_TARGET_NOT_EFFECTIVE`), then the shared product-and-market check (`ERR_INVALID_REQUEST`).

## 3. Business Logic & Workflows

### 3.1. Product Configuration and Rate Sheet Drafting

Everything begins with the product catalogue. An `OperationsAdmin` creates a DepositProduct carrying a `product_code` that is unique across all products (codes such as `SAV-STD` or `CD-12M`), a `product_class` of `SAVINGS`, `MONEY_MARKET`, `CD`, or `INTEREST_CHECKING`, and a `term_months` that defines the product's relationship to rate change: zero means a variable-rate, non-term product, while a positive value is a contractual term whose accounts lock their rate at open and turn `GRANDFATHERED` when their sheet is later superseded. The product's `tier_application` — `MARGINAL` or `WHOLE_BALANCE` — selects which tiered-rate variant (§3.5) prices its accounts. The `rate_cap_bp` is the absolute internal ceiling for the product: no tier rate, promo rate, or stacked effective rate may exceed it. Two booleans complete the product: `allows_promos` gates promotional enrollment, and `allows_exceptions` gates exception pricing. Products can be listed with a `product_class` filter.

With a product in place, a `PricingAnalyst` drafts a RateSheet for a product–market pair, supplying the pair's `product_id` and `market_code`, the `effective_date`, an optional `end_date` (defaulting to `9999-12-31` for an open-ended window), the `disclosure_lead_days` that will drive pre-change disclosure deadlines, a `margin_floor_bp` (zero disables the submit-time margin check entirely), an optional `source_scan_id` linking the competitor scan that motivated the sheet, and the `tiers` array. Each tier row carries `tier_index`, `lower_bound_cents` (inclusive), `upper_bound_cents` (exclusive, with `-1` marking the unbounded final tier), `rate_bp`, and `projected_balance_cents`.

Tier structure is validated strictly: the rows must tile the balance axis contiguously from zero — the first lower bound is zero, each tier's lower bound equals the previous tier's upper bound, rates ascend without gaps or overlaps, `tier_index` values run 0 through n−1, and the final tier is unbounded. Any violation is rejected with `ERR_TIER_STRUCTURE_INVALID`. Independently, every tier's `rate_bp` must be at most the product's `rate_cap_bp`, on pain of `ERR_RATE_CAP_EXCEEDED`. And because only one `DRAFT` may exist per product–market pair, drafting a second is rejected with `ERR_DRAFT_SHEET_EXISTS`.

A created sheet is born in `DRAFT` status. The server assigns its `sheet_version` as the next sequence number for the pair, and computes `total_projected_balance_cents` as the sum of the tiers' `projected_balance_cents`, recomputing it on creation and on every subsequent edit. If the pair has no RepricingCycle yet, creating the sheet auto-creates one with a default cadence of thirty days. Sheets may be listed filtered by `product_id`, `market_code`, `status`, `supersedes_sheet_id`, or `source_scan_id`.

While a sheet remains `DRAFT`, the analyst may edit it — subject to the optimistic-concurrency guard of §2.7 via `expected_sheet_version`. An edit may change `disclosure_lead_days`, `margin_floor_bp`, `effective_date`, or `end_date`; when `tiers` are provided they replace the existing array wholesale and are revalidated against both the structural rules and the rate cap. Editing a sheet that has left `DRAFT` is rejected with `ERR_SHEET_INVALID_STATE`. Every accepted edit bumps the sheet's `version` by one and refreshes `updated_at`.

### 3.2. Committee Review, Scheduling, Activation, and Retirement

Submission by a `PricingAnalyst` moves a sheet from `DRAFT` to `COMMITTEE_REVIEW` and fires the sheet's fiscal gate. The tiers are revalidated — they must be non-empty and structurally valid, else `ERR_TIER_STRUCTURE_INVALID`. When the sheet's `margin_floor_bp` is greater than zero, the server computes the forward-looking margin (§3.4): an operative funding curve covering the product's tenor must exist (`ERR_NO_FUNDING_CURVE`), and the margin must be at least the floor — equality passes — else submission is rejected with `ERR_MARGIN_BELOW_FLOOR`. These checks fire in the order given in §2.10, and a successful submission bumps the sheet's version.

Committee review is a `PricingCommittee` prerogative expressed through a `decision` (with an optional `reason`). A decision of `APPROVE` moves `COMMITTEE_REVIEW` to `APPROVED`. A decision of `RETURN` is the committee's universal send-back: from `COMMITTEE_REVIEW` the sheet returns to `DRAFT`; from `APPROVED` it returns to `COMMITTEE_REVIEW`; and from `SCHEDULED` it falls back to `APPROVED`, in which case the server deletes the sheet's `PENDING` and `FAILED` deployment rows and its `PENDING` disclosure notices, unwinding the scheduling artifacts. A decision attempted on a sheet in any other state is rejected with `ERR_SHEET_INVALID_STATE`.

Scheduling, again by a `PricingAnalyst`, moves `APPROVED` to `SCHEDULED` and guards the product–market calendar. The sheet's half-open window must not overlap any other sheet for the same pair that is in `SCHEDULED` — unconditionally. It may overlap the incumbent `EFFECTIVE` sheet only in chronological succession, that is, when the new sheet's `effective_date` is strictly later than the incumbent's; the incumbent is then superseded and truncated at activation. Adjacency — the new `effective_date` landing exactly on another sheet's `end_date` — is always allowed. Any other overlap is rejected with `ERR_EFFECTIVE_WINDOW_OVERLAP`. Upon scheduling, the server creates four RateDeployment rows — one per channel in the fixed order `BRANCH`, `ONLINE`, `MOBILE`, `CALL_CENTER`, all in `PENDING` — and four sheet-level `PRE_CHANGE` DisclosureNotice rows in the same channel order, each with a `required_by_date` of `effective_date` minus `disclosure_lead_days`.

Channel execution belongs to the `ChannelOperator`. A deployment execution with action `DEPLOY` moves a deployment from `PENDING` or `FAILED` to `DEPLOYED` and stamps `deployed_at`; action `MARK_FAILED` moves `PENDING` to `FAILED`. Marking a `DEPLOYED` row failed, or deploying a `RETIRED` row, is rejected with `ERR_DEPLOYMENT_INVALID_STATE`. Deployments may be listed with filters on `sheet_id`, `channel`, and `status`, and return in creation order.

Activation by a `PricingAnalyst` moves `SCHEDULED` to `EFFECTIVE` and is the system's serialization point — the moment pricing truth changes for an entire product–market pair. Three gates guard it, evaluated in this order: the disclosure gate requires every `PRE_CHANGE` notice for the sheet to be `SENT` and not late, or `WAIVED` (else `ERR_DISCLOSURE_LEAD_TIME_UNMET`); the deployment gate requires all four channel deployments to be `DEPLOYED` (else `ERR_DEPLOYMENT_INCOMPLETE`); and the date gate requires logical today to be on or after the sheet's `effective_date` (else `ERR_FUTURE_EFFECTIVE_DATE`).

Once the gates pass, activation runs a seven-link cascade:

1. The new sheet's `supersedes_sheet_id` is set to the prior `EFFECTIVE` sheet for the pair (remaining null when this is the pair's first activation); the prior sheet transitions `EFFECTIVE → SUPERSEDED`, and its `end_date` is truncated to the new sheet's `effective_date`, closing its window.
2. Every `DEPLOYED` deployment belonging to the superseded sheet transitions to `RETIRED`.
3. Every account priced on the superseded sheet whose lifecycle is not `CLOSED` is re-priced by product kind: accounts of variable-rate products (`term_months` equal to zero) are re-pointed — `sheet_id` set to the new sheet, `base_rate_bp` and `current_rate_bp` recomputed, version bumped — while accounts of term products keep their `sheet_id` and their frozen rate, flipping `rate_source` to `GRANDFATHERED` with a version bump. `CLOSED` accounts are never re-pointed. Accounts priced on any other sheet — including a sheet of another product in the same market — are not affected by the activation in any way: an account turns `GRANDFATHERED` only when the sheet it is priced on is itself the one being superseded.
4. Each repriced account whose rate dropped by ten basis points or more receives an account-level `RATE_CHANGE_ADVERSE` notice on its home channel, due five days after the activation date.
5. Exception requests priced against the superseded sheet that sit in `UNDER_REVIEW` or `RETURNED` move to `REBASE_REQUIRED`.
6. The pair's RepricingCycle records `last_reviewed_at` as the activation date and recomputes `next_review_due`.
7. If the activated sheet names a `source_scan_id` and that scan is `ANALYZED`, the scan transitions to `ACTIONED`.

Retirement is a `PricingCommittee` action available from `DRAFT`, `EFFECTIVE`, or `SUPERSEDED`, guarded by a single precondition: no DepositAccount may reference the sheet under any `rate_source` — attempting to retire a sheet with accounts still attached is rejected with `ERR_SHEET_INVALID_STATE`. A `SUPERSEDED` sheet may also retire itself without human action: when a migration batch drains the last `GRANDFATHERED` account off it (§3.7), the sheet transitions to `RETIRED` automatically. `RETIRED` is terminal for every path into it. Each of these transitions, like all sheet mutations, increments the sheet's `version` by one.

### 3.3. Competitor Intelligence and Repricing Cadence

Market intelligence enters the system as CompetitorRateScan uploads. A `PricingAnalyst` submits a scan with its `market_code`, the `scan_date` on which the data was collected, a `source_name` labeling the data vendor, and an `entries` array whose rows each carry `competitor_name`, `product_class`, `rate_bp`, and `tier_balance_cents`; the entries array may legitimately be empty. A scan is born `SUBMITTED`.

Analysis, again by a `PricingAnalyst`, moves the scan from `SUBMITTED` to `ANALYZED` — requesting analysis in any other state is rejected with `ERR_SCAN_INVALID_STATE` — and computes two benchmark rates. The benchmarks are computed for the scan's dominant product class: the class whose entries carry the largest total `tier_balance_cents`, with ties broken by product class in the fixed order `CD`, then `INTEREST_CHECKING`, then `MONEY_MARKET`, then `SAVINGS` — deterministic, never identifier-based. The official benchmark, stored as `benchmark_weighted_bp`, weights each competitor entry's rate by its tier balance: the sum, over the class's entries, of each `rate_bp` multiplied by its `tier_balance_cents`, divided by the sum of the `tier_balance_cents`, rounded half up to a whole basis point. The reference benchmark, stored as `benchmark_simple_bp`, is the unweighted mean: the sum of the entries' rates divided by the number of entries, rounded half up; it diverges from the weighted figure whenever competitor balances are unequal. When no entries match, both fields remain null. A scan's final transition, `ANALYZED → ACTIONED`, is performed by the system when a rate sheet naming the scan as its `source_scan_id` is activated (§3.2). Scans may be listed filtered by `market_code` and `status`.

Repricing discipline is tracked per product–market pair by a RepricingCycle. A `PricingAnalyst` creates or replaces a pair's cycle by submitting `product_id`, `market_code`, and `cadence_days`; the pair key is unique, so posting a cycle for a pair that already has one replaces that pair's cadence configuration. The cycle's `last_reviewed_at` records the date of the last sheet activation for the pair and stays null until the first activation. `next_review_due` is computed as `last_reviewed_at` plus `cadence_days`, and is null while the pair has never activated. The cycle's `status` is computed on read: `OVERDUE` once `last_reviewed_at` is set and logical today reaches `next_review_due` — the due date itself already counts as overdue, an inclusive boundary — and `CURRENT` in every other case, including never-activated pairs. Recall from §3.1 that drafting a pair's first sheet auto-creates its cycle at a thirty-day default cadence, and from §3.2 that activation advances the cycle. Cycles may be listed filtered by `product_id`, `market_code`, and `status`.

### 3.4. Funding Curves and Margin Analysis

Treasury supplies the cost-of-funds view. A `TreasuryOfficer` publishes a FundingCurve with a `curve_date` and a `points` array whose rows pair `tenor_months` with `cost_bp`; the points must include a tenor of zero months and must ascend by tenor. The operative curve at any moment is the latest published curve whose `curve_date` is on or before logical today; when no curve satisfies that, cost of funds cannot be computed and dependent operations fail with `ERR_NO_FUNDING_CURVE`.

The funding cost for a product is read at the product's `term_months` tenor. An exact tenor match on a curve point yields that point's `cost_bp` with no interpolation — a variable-rate product (tenor zero) therefore prices its funding at the zero-tenor point. Otherwise the cost is linearly interpolated between the two bracketing points: the lower point's cost, plus the fraction of the tenor distance between the two points' tenors that the product's tenor represents, multiplied by the difference between the two points' costs, with the result rounded half up to a whole basis point. A tenor beyond the curve's maximum point is rejected with `ERR_NO_FUNDING_CURVE`.

Margin analysis is a computed read on a sheet, available to `PricingAnalyst`, `PricingCommittee`, and `TreasuryOfficer`, with two variants selected by the `variant` query parameter. The default, `FORWARD_LOOKING`, works from the sheet itself: `weighted_rate_bp` is the sum over tiers of each tier's `rate_bp` multiplied by its `projected_balance_cents`, divided by the sum of the projected balances, rounded half up to a whole basis point; `funding_cost_bp` comes from the operative curve at the product's tenor; and `margin_bp` is the weighted rate minus the funding cost. The response carries `variant`, `weighted_rate_bp`, `funding_cost_bp`, `margin_bp`, the sheet's `margin_floor_bp`, and `passes_floor`, which is true when the margin is at least the floor. Because it uses projected balances, the forward-looking variant is computable before any account exists — but if the sheet's projected balances sum to zero, the read fails with `ERR_MARGIN_NOT_COMPUTABLE`. The `REALIZED_BOOK` variant instead weights reality: the `OPEN` accounts of the sheet's product and market whose `rate_source` is `SHEET`, `PROMO`, or `EXCEPTION`, each contributing its `balance_cents` at its `current_rate_bp`. With no qualifying account, the variant fails with `ERR_MARGIN_NOT_COMPUTABLE`. The submit gate of §3.2 always evaluates the forward-looking variant.

### 3.5. Account Servicing, Promotions, and Interest

A `BranchBanker` opens a DepositAccount by supplying the external `customer_ref` (an opaque core-banking reference; there is no Customer entity), the `product_id` and `market_code` placing the account on a product–market pair, the `opening_balance_cents` that becomes the account's `balance_cents`, and the account's home `channel`. At open, the account's `sheet_id` is resolved to the unique `EFFECTIVE` sheet for the pair — uniqueness holds because activation atomically supersedes the incumbent — and when no effective sheet exists the open fails with `ERR_SHEET_NOT_FOUND`. Pricing is computed immediately: `base_rate_bp` from the sheet's tiers at the opening balance, the bundle bonus evaluated per §3.7, and `current_rate_bp` stacked and capped. The account is born with `lifecycle` `OPEN` and `rate_source` `SHEET`; `opened_at` records the logical date of opening, `last_accrual_date` initializes to the opened date, and both `unposted_accrual_milli` and `posted_interest_cents` start at zero.

The tiered rate of a balance against a sheet's tiers follows two product-selected variants. Tiers are half-open intervals: each covers balances from its `lower_bound_cents` up to but not including its `upper_bound_cents`, so a balance landing exactly on a boundary belongs to the tier whose lower bound equals it. Under `MARGINAL`, each tier's rate applies only to the slice of the balance inside that tier, and the blended rate is the sum over tiers of slice size multiplied by tier rate, divided by the balance, rounded half up to a whole basis point. Under `WHOLE_BALANCE`, the rate of the single tier containing the balance applies to the entire balance. A zero balance yields a rate of zero basis points. This same tiered machinery drives the account's `base_rate_bp`, rate quotes, and exception baselines.

An account's effective rate is evaluated in a fixed order whenever its sheet, balance, `rate_source`, bundle enrollment, or exception state changes. First, the base: `SHEET` accounts take the tiered rate over the current sheet's tiers; `PROMO` accounts take the offer's `promo_rate_bp`; `EXCEPTION` accounts take `exception_rate_bp`, the approved requested rate; `GRANDFATHERED` accounts keep their frozen `current_rate_bp` and skip recomputation entirely. Second, the bundle bonus: `bonus_bp` applies only when `rate_source` is `SHEET` and a qualifying `ENROLLED` enrollment exists for the customer (§3.7) — the bonus never stacks on `PROMO` or `EXCEPTION` rates, and is otherwise zero. Third, the cap: `current_rate_bp` is the lesser of the product's `rate_cap_bp` and the base plus bonus. `base_rate_bp`, `bundle_bonus_bp`, and `current_rate_bp` are stored on the account, and a rate-quote read exposes the full breakdown — `account_id`, `rate_source`, `base_rate_bp`, `bundle_bonus_bp`, `exception_rate_bp`, `cap_applied` (whether the cap clamped the stack), and `current_rate_bp`.

Balance adjustments are the second OCC-guarded write (§2.7): the request carries `expected_account_version` and the new `balance_cents`. Adjustments are allowed on `OPEN` and `FROZEN` accounts and are blocked on `CLOSED` ones with `ERR_ACCOUNT_INVALID_STATE`. A successful adjustment recomputes the account's tier base and current rate, refreshes `qualifying_balance_cents` on the customer's `ENROLLED` bundle enrollments, and bumps the account version.

Lifecycle actions are driven through the account-action capability with an `action` value: `FREEZE` moves `OPEN → FROZEN`, `UNFREEZE` moves `FROZEN → OPEN`, and `CLOSE` moves `OPEN` or `FROZEN` to the terminal `CLOSED`. Closing does not post final interest automatically, and a `CLOSED` account drops out of the combined relationship balance (§3.7). Any incompatible combination — closing a `CLOSED` account, freezing a frozen one, or attempting a promo enrollment on a `FROZEN` or non-`SHEET` account — is rejected with `ERR_ACCOUNT_INVALID_STATE`.

Promotional offers are drafted by a `PricingAnalyst` with the pair's `product_id` and `market_code`, the `promo_rate_bp` (bounded by the product's `rate_cap_bp`, else `ERR_RATE_CAP_EXCEEDED`), the `promo_term_days` an enrolled account keeps the rate before rollover, the enrollment window `enrollment_start` through `enrollment_end` — a closed interval, both bounds inclusive — an optional `min_opening_balance_cents` defaulting to zero, and the `rollover_treatment`, either `ROLL_TO_SHEET` or `RENEW_THEN_SHEET`. Publishing moves `DRAFT → SCHEDULED` after two checks: `enrollment_start` must not fall after `enrollment_end` (else `ERR_INVALID_REQUEST`), and the closed window must not intersect any `SCHEDULED` or `ACTIVE` offer for the same pair — because the interval is closed, offers that merely touch on a boundary date still conflict (else `ERR_PROMO_WINDOW_OVERLAP`). From there the clock takes over: `SCHEDULED → ACTIVE` when logical today reaches `enrollment_start`, and `SCHEDULED` or `ACTIVE → EXPIRED` once today passes `enrollment_end`. An analyst may also close an `ACTIVE` offer, moving it to `CLOSED`: enrollment stops immediately, but accounts already on the promo keep their rate until their own `promo_end_date`. Offer actions from incompatible states — closing a `DRAFT`, publishing an `ACTIVE` — are rejected with `ERR_PROMO_INVALID_STATE`. Offers may be listed filtered by `product_id`, `market_code`, and `status`.

A `BranchBanker` enrolls an account through the account-action capability with action `ENROLL_PROMO` and the target `promo_offer_id`. The gates fire in order: the account's lifecycle must be `OPEN` (else `ERR_ACCOUNT_INVALID_STATE`); the product must allow promotions (else `ERR_INVALID_REQUEST`); the offer must be `ACTIVE`, logical today must lie inside the closed enrollment window, and the offer's product and market must match the account's (else `ERR_PROMO_NOT_ENROLLABLE`); and the account's `balance_cents` must be at least the offer's `min_opening_balance_cents` (else `ERR_PROMO_MIN_BALANCE_UNMET`). On success the account's `rate_source` becomes `PROMO`, `promo_offer_id` is recorded, `promo_end_date` is set to the enrollment date plus the offer's `promo_term_days`, the rate is recomputed, and the version bumps.

Rollover is a sweep affair. When logical today passes an account's `promo_end_date`, the offer's `rollover_treatment` decides: under `RENEW_THEN_SHEET` with the offer still `ACTIVE`, the account's `promo_end_date` extends by another `promo_term_days` and the account stays on `PROMO` with no transition; under `ROLL_TO_SHEET` — or under `RENEW_THEN_SHEET` when the offer is no longer active — the account returns to `SHEET`, its promo fields clear, the rate recomputes from the sheet, and the version bumps. A rollover that drops the rate by ten basis points or more raises a `RATE_CHANGE_ADVERSE` notice due five days later. Separately, thirty days before `promo_end_date` the sweep creates the account's `PROMO_EXPIRY` notice.

Interest accrues daily and posts on demand. Each elapsed day of the clock sweep, every account whose lifecycle is not `CLOSED` accrues the whole milli-cents obtained by multiplying its posted `balance_cents` by its `current_rate_bp` and dividing by 3,650 — a division floored to whole milli-cents, reflecting a 365-day year and the basis-point denominator — and that amount accumulates into `unposted_accrual_milli`. Posting, invoked by a `BranchBanker` through the interest-posting capability, converts the accumulated accrual to cents exactly once: `unposted_accrual_milli` divided by one thousand and rounded half up yields the posted delta, which is added to `posted_interest_cents`; the accrual then resets to zero and `last_accrual_date` becomes logical today. Posting when nothing has accrued is a no-op that posts a delta of zero; posting on a `CLOSED` account is rejected with `ERR_ACCOUNT_INVALID_STATE`. The posting operation returns the updated account with a 201 status, since a posting record is created. Accounts may be listed filtered by `customer_ref`, `product_id`, `market_code`, `sheet_id`, `rate_source`, `lifecycle`, `promo_offer_id`, or `exception_request_id`.

### 3.6. Exception Pricing: Requests, Decisions, and Expiry

Exception pricing lets a banker move a single account off the published sheet under a documented authority ladder. A `BranchBanker` creates an ExceptionPricingRequest by naming the `account_id`, the baseline `sheet_id` the request is priced against, the `requested_rate_bp`, the `term_days` the exception will last once applied, and an optional `justification_doc_ref`. At creation the server snapshots `baseline_rate_bp` — the tiered rate for the account's balance on the named sheet at that moment — computes `delta_bp` as the requested rate minus the baseline, and derives the `authority_tier`: `BRANCH` when the delta is at most twenty-five basis points, `COMMITTEE` when the delta lies between twenty-six and seventy-five inclusive; a delta above seventy-five basis points is rejected at creation with `ERR_EXCEPTION_DELTA_EXCEEDS_MAX`. Creation enforces, in the order of §2.10: the product must allow exceptions (else `ERR_INVALID_REQUEST`); a `justification_doc_ref` is mandatory whenever the computed tier is `COMMITTEE` (else `ERR_EXCEPTION_DOCS_MISSING`); the baseline sheet must be `EFFECTIVE` (else `ERR_BASELINE_SHEET_NOT_EFFECTIVE`); and the delta ceiling. The request is born `UNDER_REVIEW`, with `submitted_by_user_id` recorded from the `X-User-ID` header for segregation of duties.

Decisions are expressed through a `decision` value and are segregated: the deciding operator's `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. An `APPROVE` decision moves `UNDER_REVIEW → APPROVED` and adds two further gates — the baseline sheet must still be `EFFECTIVE` (else `ERR_BASELINE_SHEET_NOT_EFFECTIVE`), and the actor must hold the tier's authority: `BRANCH`-tier requests may be approved by a `BranchBanker` or the `PricingCommittee`, while `COMMITTEE`-tier requests are the committee's alone, with violations rejected as `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`. Approval records `decided_by_user_id`. A `DECLINE` decision moves `UNDER_REVIEW → DECLINED`, and a `RETURN` decision moves `UNDER_REVIEW → RETURNED`; both enforce segregation alone, and both record the decider. Any decision attempted from a state other than `UNDER_REVIEW` — other than revocation, below — is rejected with `ERR_EXCEPTION_INVALID_STATE`.

Resubmission belongs to the original submitting banker alone, and is available from both `RETURNED` and `REBASE_REQUIRED`, moving the request back to `UNDER_REVIEW`. The banker may supply a new `requested_rate_bp`, `term_days`, or `justification_doc_ref`. In both cases the server re-snapshots `baseline_rate_bp` from the pair's current `EFFECTIVE` sheet and recomputes `delta_bp` and `authority_tier`; for a `RETURNED` request the `sheet_id` is additionally re-pointed to that current effective sheet. The documentation rule and the delta ceiling re-apply on resubmit exactly as at creation. The `REBASE_REQUIRED` state itself is not banker-chosen: it is where pending requests land when activation supersedes their baseline sheet underneath them (§3.2).

Application, by a `BranchBanker`, moves `APPROVED → APPLIED` under three preconditions: the baseline sheet is still `EFFECTIVE` (else `ERR_BASELINE_SHEET_NOT_EFFECTIVE`); the account's lifecycle is `OPEN` and its `rate_source` is `SHEET` (else `ERR_ACCOUNT_INVALID_STATE`); and the product allows exceptions (else `ERR_INVALID_REQUEST`). Applying stamps the account: `rate_source` becomes `EXCEPTION`, `exception_request_id` is set, `exception_end_date` becomes the application date plus `term_days`, `exception_rate_bp` takes the `requested_rate_bp`, the current rate is recomputed, and the account's version bumps.

Revocation is the committee's compensation lever: a `REVOKE` decision moves `APPLIED → REVOKED` and restores the account to sheet-derived pricing — `rate_source` back to `SHEET`; `exception_request_id`, `exception_end_date`, and `exception_rate_bp` cleared to null; the current rate recomputed from the sheet's tiers plus any bundle bonus; the account version bumped.

Two expiries run on the clock. An `APPLIED` exception expires — `APPLIED → EXPIRED` — once logical today passes `exception_end_date`; the account reverts to `SHEET` with its exception fields cleared and version bumped, and if the reversion drops the rate by ten basis points or more, a `RATE_CHANGE_ADVERSE` notice is raised with a required date five days out. Separately, an `APPROVED` request that is never applied expires — `APPROVED → EXPIRED` — once logical today is more than thirty days past the decision date. `DECLINED`, `REVOKED`, and `EXPIRED` are terminal. Exception requests may be listed filtered by `account_id`, `sheet_id`, and `status`.

### 3.7. Relationship Bundles and Grandfathered-Rate Migration

Relationship pricing rewards customers who consolidate balances. An `OperationsAdmin` defines a RelationshipBundle with a unique `bundle_code`, a `bonus_bp` to add to eligible rates, a `min_combined_balance_cents` qualification threshold, the `required_product_classes` a customer's combined balance is measured across, and the `eligible_product_classes` the bonus actually applies to.

The combined relationship balance for a customer and bundle is the sum of `balance_cents` over that customer's accounts whose lifecycle is `OPEN` and whose product class is among the bundle's `required_product_classes` — a customer holding no open balances in the required classes simply sums to zero. The sum reads posted balances only: `unposted_accrual_milli` and `posted_interest_cents` never feed it, which keeps the evaluation order acyclic even though rates, bonuses, balances, and accruals all interrelate.

Enrolling a customer — the `OperationsAdmin` supplies `bundle_id` and `customer_ref` — creates a CustomerBundleEnrollment in `ENROLLED` status and computes `qualifying_balance_cents` from the combined relationship balance at that moment. When the qualifying balance reaches the bundle's `min_combined_balance_cents`, the bonus is applied to the customer's eligible accounts: every `OPEN` account of that customer whose product class is in `eligible_product_classes` takes `bundle_bonus_bp`, recomputes its `current_rate_bp`, and bumps its version. When the balance falls short, the bonus stays zero.

Enrollment transitions are driven with an `action`. `SUSPEND` moves `ENROLLED → SUSPENDED` and strips the bonus: all eligible `OPEN` accounts of the customer have `bundle_bonus_bp` zeroed, rates recomputed, and versions bumped. `REINSTATE` moves `SUSPENDED → ENROLLED`, recomputes `qualifying_balance_cents`, and re-applies the bonus to eligible `OPEN` accounts only when the refreshed balance reaches the minimum — otherwise the bonus remains zero. `EXIT` moves either `ENROLLED` or `SUSPENDED` to the terminal `EXITED`: from `ENROLLED` the bonus is removed from eligible `OPEN` accounts with recomputation and version bumps; from `SUSPENDED` there is no bonus left to remove, so nothing else changes. A transition attempted from an incompatible state — suspending an `EXITED` enrollment, say — is rejected with `ERR_ENROLLMENT_INVALID_STATE`. Enrollments may be listed filtered by `bundle_id`, `customer_ref`, and `status`. Recall from §3.5 that the bundle bonus attaches only to accounts whose `rate_source` is `SHEET`; it never stacks on promo or exception rates.

Migration closes the loop on grandfathering. An `OperationsAdmin` plans a MigrationBatch by naming a `source_sheet_id`, expected to be `SUPERSEDED`, and a `target_sheet_id`, expected to be `EFFECTIVE`; the batch is born `PLANNED`. Executing the batch with action `EXECUTE` enforces, in order: the batch is `PLANNED` and the source sheet is `SUPERSEDED` (else `ERR_MIGRATION_INVALID_STATE`); the target sheet is `EFFECTIVE` (else `ERR_MIGRATION_TARGET_NOT_EFFECTIVE`); and source and target share the same product and market (else `ERR_INVALID_REQUEST`). The execution cascade then walks every account with `sheet_id` on the source sheet and `rate_source` `GRANDFATHERED`: accounts whose lifecycle is not `CLOSED` move to `SHEET` pricing on the target sheet — `sheet_id` re-pointed, base and current rates recomputed, version bumped — while `CLOSED` accounts are skipped and tallied in `skipped_count`. `migrated_count` records how many accounts moved. Each migrated account whose rate drops by ten basis points or more receives a `RATE_CHANGE_ADVERSE` notice due five days after execution. And when the cascade leaves no `GRANDFATHERED` accounts on the source sheet, the source sheet retires itself to `RETIRED` automatically — the machine's answer to grandfathered-sheet attrition. A batch may instead be aborted, action `ABORT` moving `PLANNED → ABORTED` with no account effects; `COMPLETED` and `ABORTED` are both terminal. Batches may be listed filtered by `source_sheet_id`, `target_sheet_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource — products, rate sheets, competitor scans, repricing cycles, promotional offers, exception requests, deposit accounts, interest posting records, funding curves, bundles, enrollments, and migration batches — return `201 Created`. Operations that modify an existing resource in place, drive a state transition, perform a computed read, or advance the logical clock return `200 OK`. The table below is a summary only; request fields, preconditions, side effects, and error behavior are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/deposit-products` | Create a deposit product | OperationsAdmin |
| GET | `/deposit-products` | List products | OperationsAdmin, PricingAnalyst, PricingCommittee, BranchBanker |
| POST | `/rate-sheets` | Create a DRAFT rate sheet with embedded tiers | PricingAnalyst |
| GET | `/rate-sheets` | List rate sheets with filters | PricingAnalyst, PricingCommittee, BranchBanker, ComplianceOfficer |
| GET | `/rate-sheets/{id}` | Get one rate sheet | PricingAnalyst, PricingCommittee, BranchBanker, ComplianceOfficer |
| PATCH | `/rate-sheets/{id}` | Edit a DRAFT sheet (OCC-guarded); tiers replaced wholesale when provided | PricingAnalyst |
| POST | `/rate-sheets/{id}/submit` | Submit a draft for committee review (margin gate) | PricingAnalyst |
| POST | `/rate-sheets/{id}/review-decision` | Committee `APPROVE` or `RETURN` | PricingCommittee |
| POST | `/rate-sheets/{id}/schedule` | Schedule an approved sheet; creates deployments and pre-change notices | PricingAnalyst |
| POST | `/rate-sheets/{id}/activate` | Activate a scheduled sheet; runs the supersession and repricing cascade | PricingAnalyst |
| POST | `/rate-sheets/{id}/retire` | Retire a sheet once no accounts reference it | PricingCommittee |
| GET | `/rate-sheets/{id}/margin-analysis` | Computed margin read; `FORWARD_LOOKING` default, `REALIZED_BOOK` via `variant` | PricingAnalyst, PricingCommittee, TreasuryOfficer |
| GET | `/rate-deployments` | List deployment rows | PricingAnalyst, ChannelOperator, ComplianceOfficer |
| GET | `/rate-deployments/{id}` | Get one deployment | PricingAnalyst, ChannelOperator, ComplianceOfficer |
| POST | `/rate-deployments/{id}/execution` | `DEPLOY` or `MARK_FAILED` a deployment | ChannelOperator |
| POST | `/competitor-rate-scans` | Upload a competitor rate scan with embedded entries | PricingAnalyst |
| GET | `/competitor-rate-scans` | List scans | PricingAnalyst, PricingCommittee |
| GET | `/competitor-rate-scans/{id}` | Get one scan | PricingAnalyst, PricingCommittee |
| POST | `/competitor-rate-scans/{id}/analyze` | Compute and store both benchmark variants | PricingAnalyst |
| POST | `/repricing-cycles` | Create or replace the cadence for a product–market pair | PricingAnalyst |
| GET | `/repricing-cycles` | List cycles with computed `CURRENT` / `OVERDUE` status | PricingAnalyst, PricingCommittee |
| GET | `/repricing-cycles/{id}` | Get one cycle | PricingAnalyst, PricingCommittee |
| POST | `/promotional-offers` | Create a DRAFT promotional offer | PricingAnalyst |
| GET | `/promotional-offers` | List offers | PricingAnalyst, PricingCommittee, BranchBanker |
| GET | `/promotional-offers/{id}` | Get one offer | PricingAnalyst, PricingCommittee, BranchBanker |
| POST | `/promotional-offers/{id}/publish` | Publish an offer (closed-window overlap check) | PricingAnalyst |
| POST | `/promotional-offers/{id}/close` | Close an active offer to new enrollments | PricingAnalyst |
| POST | `/exception-pricing-requests` | Request an off-sheet rate; snapshots baseline, delta, and authority tier | BranchBanker |
| GET | `/exception-pricing-requests` | List exception requests | BranchBanker, PricingCommittee, ComplianceOfficer |
| GET | `/exception-pricing-requests/{id}` | Get one exception request | BranchBanker, PricingCommittee, ComplianceOfficer |
| POST | `/exception-pricing-requests/{id}/decision` | `APPROVE`, `DECLINE`, or `RETURN` from `UNDER_REVIEW`; `REVOKE` from `APPLIED` | BranchBanker, PricingCommittee |
| POST | `/exception-pricing-requests/{id}/resubmit` | Resubmit a `RETURNED` or `REBASE_REQUIRED` request with a re-snapshotted baseline | BranchBanker |
| POST | `/exception-pricing-requests/{id}/apply` | Apply an approved exception to the account | BranchBanker |
| POST | `/deposit-accounts` | Open an account on the pair's effective sheet | BranchBanker |
| GET | `/deposit-accounts` | List accounts with filters | BranchBanker, PricingAnalyst, PricingCommittee |
| GET | `/deposit-accounts/{id}` | Get one account | BranchBanker, PricingAnalyst, PricingCommittee |
| PATCH | `/deposit-accounts/{id}` | Adjust balance (OCC-guarded); recomputes rates | BranchBanker |
| POST | `/deposit-accounts/{id}/actions` | `FREEZE`, `UNFREEZE`, `CLOSE`, or `ENROLL_PROMO` | BranchBanker |
| POST | `/deposit-accounts/{id}/interest-postings` | Post accrued interest (sum-then-round) | BranchBanker |
| GET | `/deposit-accounts/{id}/rate-quote` | Computed effective-rate breakdown | BranchBanker, PricingAnalyst |
| POST | `/funding-curves` | Publish a funding curve | TreasuryOfficer |
| GET | `/funding-curves` | List funding curves | TreasuryOfficer, PricingAnalyst, PricingCommittee |
| POST | `/relationship-bundles` | Create a relationship pricing bundle | OperationsAdmin |
| GET | `/relationship-bundles` | List bundles | OperationsAdmin, PricingAnalyst, BranchBanker |
| POST | `/bundle-enrollments` | Enroll a customer; computes the qualifying balance and applies the bonus | OperationsAdmin |
| GET | `/bundle-enrollments` | List enrollments | OperationsAdmin, BranchBanker |
| GET | `/bundle-enrollments/{id}` | Get one enrollment | OperationsAdmin, BranchBanker |
| POST | `/bundle-enrollments/{id}/transition` | `SUSPEND`, `REINSTATE`, or `EXIT` an enrollment | OperationsAdmin |
| GET | `/disclosure-notices` | List notices | ComplianceOfficer, PricingAnalyst |
| GET | `/disclosure-notices/{id}` | Get one notice | ComplianceOfficer, PricingAnalyst |
| POST | `/disclosure-notices/{id}/resolution` | `SEND` or `WAIVE` a pending notice | ComplianceOfficer |
| POST | `/migration-batches` | Plan a grandfathered-rate migration | OperationsAdmin |
| GET | `/migration-batches` | List migration batches | OperationsAdmin, PricingAnalyst |
| GET | `/migration-batches/{id}` | Get one migration batch | OperationsAdmin, PricingAnalyst |
| POST | `/migration-batches/{id}/execution` | `EXECUTE` (migrate and cascade) or `ABORT` | OperationsAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock; advancing it runs the daily time sweep | OperationsAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined where each rule lives in §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SHEET_INVALID_STATE` | 409 Conflict |
| `ERR_PROMO_INVALID_STATE` | 409 Conflict |
| `ERR_EXCEPTION_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_INVALID_STATE` | 409 Conflict |
| `ERR_MIGRATION_INVALID_STATE` | 409 Conflict |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SCAN_INVALID_STATE` | 409 Conflict |
| `ERR_DEPLOYMENT_INVALID_STATE` | 409 Conflict |
| `ERR_NOTICE_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_DRAFT_SHEET_EXISTS` | 409 Conflict |
| `ERR_EFFECTIVE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DISCLOSURE_LEAD_TIME_UNMET` | 409 Conflict |
| `ERR_DEPLOYMENT_INCOMPLETE` | 409 Conflict |
| `ERR_FUTURE_EFFECTIVE_DATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCT_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_SHEET_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_PROMO_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_BUNDLE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_TIER_STRUCTURE_INVALID` | 422 Unprocessable Entity |
| `ERR_RATE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MARGIN_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_MARGIN_NOT_COMPUTABLE` | 422 Unprocessable Entity |
| `ERR_PROMO_NOT_ENROLLABLE` | 422 Unprocessable Entity |
| `ERR_PROMO_MIN_BALANCE_UNMET` | 422 Unprocessable Entity |
| `ERR_EXCEPTION_DELTA_EXCEEDS_MAX` | 422 Unprocessable Entity |
| `ERR_EXCEPTION_DOCS_MISSING` | 422 Unprocessable Entity |
| `ERR_BASELINE_SHEET_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_MIGRATION_TARGET_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_NO_FUNDING_CURVE` | 422 Unprocessable Entity |

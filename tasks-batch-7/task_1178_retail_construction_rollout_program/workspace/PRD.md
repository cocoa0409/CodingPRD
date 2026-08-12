# Retail Construction Rollout API — Product Requirements Document

## 1. Introduction

A national retailer executing a multi-market store rollout behaves like its own general contractor: dozens of sites move through design, permitting, construction, and grand opening on a phased schedule, and every delay or overrun compounds across the portfolio. This document specifies the Retail Construction Rollout API, the system of record with which the rollout organization plans the site list and phased schedule, manages prototype drawings and jurisdiction variances, tracks permits municipality by municipality, runs GC bidding and award per market, sequences fixture, IT, and signage vendors against site readiness, controls budget variance and change orders, and protects each committed grand-opening date.

All endpoints are mounted under `/rollout`. Work is strictly segregated across eight operator roles, from the `ProgramDirector` who owns the budget envelope to the `GCVendor` who bids on packages. Because the program's financial posture, its construction schedule, and its opening-date commitments all derive from one another, the API reconciles derived state immediately on every change: a single award, approval, or vendor completion can rewrite site budgets, program contingency, readiness, and opening forecasts in one request. Section 2 fixes the system-wide contracts; Section 3 walks the business workflows in rollout order.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The API recognizes exactly eight roles, spelled as follows: `ProgramDirector`, `DesignManager`, `PermitCoordinator`, `ProcurementLead`, `GCVendor`, `SiteSuperintendent`, `OperationsLead`, and `FinanceController`.

A request with a missing or unrecognized header or role is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`. Read endpoints — every list and get — are shared by all eight roles; write endpoints are restricted per the endpoint table in §4.

Identity semantics differ by role. When `X-User-Role` is `GCVendor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on any resource that references a `Contractor` compare the resource's `contractor_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_IDENTITY`. When `X-User-Role` is `ProgramDirector`, `DesignManager`, `PermitCoordinator`, `ProcurementLead`, `SiteSuperintendent`, `OperationsLead`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may still record it — notably as `proposed_by_user_id` on a change order at proposal time — and later compare it against that recorded value, as cancellation ownership and segregation-of-duties checks do, but it never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in this API — rollout programs, markets, municipality profiles, sites, drawing sets, permits, contractors, bid packages, bids, vendor mobilizations, change orders, punch items, turnovers, and opening commitments — carries four system-managed properties:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every mutation.

A mutation is any change to a resource's stored state, including the recomputation of derived fields triggered by a cascade that originated on another resource. When a change order is approved, for example, the owning site's `version` increments even though the request targeted the change order, because the site's budget buckets changed; the same convention applies to automatic transitions such as a site's advance from `IN_BUILD` to `PUNCH`.

### 2.5. The Logical Clock and the Time-Based Sweep

All time-dependent rules in this API read a single logical clock; the wall clock is never consulted. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and before any clock-setting call it continues to read exactly that instant. A `ProgramDirector` may advance the clock by supplying `to_iso8601`; the call returns the new `current_utc`. Wherever this document says "current date" or "today", it means the calendar date of this logical clock.

Advancing the clock does not by itself mutate any resource. Clock-driven transitions are applied only through an admin-only sweep capability, which does two things in one pass: every `ISSUED` permit whose `expires_on` is on or before the current date moves to `EXPIRED`, and every non-terminal opening commitment has its opening-date forecast recomputed as specified in §3.8. The sweep reports what it changed through two lists in its response, `expired_permit_ids` and `recomputed_commitment_ids`.

### 2.6. Units, Precision, and Rounding

Financial and schedule arithmetic follow fixed precision rules so that every implementation reproduces identical numbers:

- All monetary amounts are integer cents; fractional cents never appear in requests or responses.
- Variance ratios and change-order tier percentages are integer basis points, produced by rounding half up where rounding is prescribed.
- A bid's `evaluation_score` is a number with exactly two decimal places, rounded half up.
- Durations and date arithmetic are expressed in whole days; where a conservative vendor duration is padded, the padded duration is rounded half up to a whole day.
- Permit fees are rounded half up to whole cents per permit before any summation; summing unrounded per-permit amounts and rounding once at the end is forbidden.
- Change-order tier classification is an exact rational comparison performed with no rounding at all.

### 2.7. Optimistic Concurrency Control

Three write operations require the client to supply `expected_site_version`, carrying the `version` of the target site as the client last observed it: the site update operation, change-order approval, and turnover acceptance. If the supplied value does not equal the site's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. The client's view of the site's budget allocation, committed opening date, or punch posture is then stale relative to the server's record, and proceeding would overwrite changes the client never observed. Endpoints not named above do not accept any version field.

### 2.8. Hierarchical Consistency and Automatic Reconciliation

The rollout model is a web of derived state: program budget totals roll up from sites, site readiness derives from vendor completions, and opening forecasts derive from permits, vendor schedules, and budget posture. Whenever an underlying fact changes, the server reconciles every dependent aggregate immediately, within the same request, so clients never observe a stale derived value. Removed sites drop out of all program-level aggregates, so the program rollup always reflects the live portfolio.

Several transitions are automatic rather than client-driven. A site moves from `IN_BUILD` to `PUNCH` when its last outstanding vendor type completes; a market moves from `BIDDING` to `AWARDED` when one of its packages is awarded; an opening commitment's `protection_posture` migrates among `PROTECTED`, `WATCH`, `AT_RISK`, and `BREACHED` purely by recalculation; and every such posture moves to `MET` the moment its site opens. Each automatic reconciliation mutates the affected resources, refreshing `updated_at` and incrementing `version` per §2.4.

### 2.9. Nested Resource Retrieval and Existence Checking

Where an endpoint path contains resource identifiers, the server validates them for existence sequentially from left to right, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Identifiers supplied in request bodies that reference other resources — `program_id`, `market_id`, `site_id`, `drawing_set_id`, `bid_package_id`, and `contractor_id` — are likewise validated, and an unknown reference is rejected with `ERR_NOT_FOUND`.

### 2.10. Validation Evaluation Order

A single request can violate several rules at once. The server evaluates checks in a fixed order, and the first failing check determines which error the client receives:

1. Authentication — both headers present and the role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization — the role is permitted for this endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Identity ownership — where an endpoint acts on caller-owned resources, such as bid submission and withdrawal or change-order cancellation (`ERR_FORBIDDEN_IDENTITY`).
4. Existence — path identifiers left to right, then body-referenced identifiers (`ERR_NOT_FOUND`).
5. State guards — the target resource is in a from-state that allows the operation, terminal states reject all further transitions, and domain state gates hold (`ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_MARKET_NOT_BIDDING`, `ERR_MARKET_NOT_AWARDED`, `ERR_BID_PACKAGE_NOT_OPEN`, `ERR_CONTRACTOR_NOT_PREQUALIFIED`, `ERR_SITE_NOT_IN_BUILD`, `ERR_TURNOVER_ALREADY_REQUESTED`, `ERR_ACTIVE_SITES_REMAIN`, `ERR_TURNOVER_NOT_ACCEPTED`).
6. Optimistic concurrency — `expected_site_version` matches the site's current `version` (`ERR_STALE_VERSION`).
7. Compliance gates — segregation of duties and change-order tier authority (`ERR_SEGREGATION_OF_DUTIES`, `ERR_CO_TIER_ROLE_REQUIRED`).
8. Cross-entity reference gates — municipality profile presence, drawing approval and revision currency, vendor predecessor completion, BUILDING permit issuance (`ERR_MUNICIPALITY_PROFILE_MISSING`, `ERR_DRAWING_NOT_APPROVED`, `ERR_DRAWING_SUPERSEDED`, `ERR_VENDOR_PREDECESSOR_INCOMPLETE`, `ERR_PERMIT_NOT_ISSUED`).
9. Temporal gates — bid windows, vendor window feasibility and overlap, permit expiry, opening-date locks (`ERR_BID_WINDOW_NOT_OPEN`, `ERR_BID_WINDOW_CLOSED`, `ERR_BID_WINDOW_STILL_OPEN`, `ERR_SCHEDULE_INFEASIBLE`, `ERR_PERMIT_EXPIRED`, `ERR_VENDOR_WINDOW_OVERLAP`, `ERR_OPEN_DATE_LOCKED`, `ERR_OPENING_LOCK_ENGAGED`).
10. Uniqueness and capacity — duplicate permit types, duplicate bids, market crew-day capacity, active vendors on a site being removed, punch critical mass, punch waiver severity, outstanding punch items at acceptance, responsive bids at award (`ERR_DUPLICATE_PERMIT_TYPE`, `ERR_DUPLICATE_BID`, `ERR_MARKET_CAPACITY_FULL`, `ERR_ACTIVE_VENDOR_ON_SITE`, `ERR_PUNCH_CRITICAL_OPEN`, `ERR_PUNCH_NOT_WAIVABLE`, `ERR_PUNCH_ITEMS_OUTSTANDING`, `ERR_NO_RESPONSIVE_BIDS`).
11. Fiscal headroom — the budget-headroom check on change-order approval (`ERR_BUDGET_HEADROOM_EXCEEDED`).
12. Request shape — missing or malformed fields, enum values outside their declared range, numeric range violations such as an out-of-range technical score (`ERR_INVALID_REQUEST`).

A change-order approval that would fail both the stale-version check and the headroom check is therefore rejected with `ERR_STALE_VERSION`, because optimistic concurrency (step 6) is evaluated before fiscal headroom (step 11).

## 3. Business Logic & Workflows

### 3.1. Building the Program: Budget Envelope, Markets, and the Site List

A `ProgramDirector` opens a rollout program by supplying its `name`, its `fiscal_year`, the `total_budget_cents` available to the whole program, and the `contingency_pool_cents` carved out of that total to absorb overruns. A new program starts in `SETUP` with its computed aggregates zeroed: `committed_cents`, `actuals_cents`, and `contingency_reserved_cents` all read 0, `contingency_free_cents` equals the full pool, and `budget_posture` reads `WITHIN_PLAN`. Activating the program moves it from `SETUP` to `ACTIVE`, and only an `ACTIVE` program supports downstream work. Completing the program moves it from `ACTIVE` to `COMPLETE` and is allowed only when every site of the program has reached `OPEN` or `REMOVED`; the attempt is rejected with `ERR_ACTIVE_SITES_REMAIN` while any site is still mid-flight.

Within a program the director registers markets — metropolitan areas — each with a `name`, a two-letter `state_code`, and `max_concurrent_vendor_crews`, the per-day cap on vendor crews working across all of the market's sites. A market begins `REGISTERED`. Opening bidding moves it from `REGISTERED` to `BIDDING` and requires the parent program to be `ACTIVE`, failing with `ERR_PROGRAM_NOT_ACTIVE` otherwise. The market later moves from `BIDDING` to `AWARDED` automatically when one of its bid packages is awarded (§3.4).

Sites join the program through the director, who supplies the `program_id` and `market_id`, the site's `municipality_code`, its street `address`, its gross `square_footage` (the permit fee basis), the phased schedule wave number `phase_wave`, the planned budget envelope `budget_allocation_cents`, and the committed grand-opening date `target_open_date`. A new site starts `LISTED` with `readiness_posture` `ROUGH` and `base_contract_cents` 0, and exactly one `OpeningCommitment` is auto-created alongside it, its `committed_open_on` mirroring `target_open_date` and its posture reading `PROTECTED` (§3.8).

While a site is young its plan data can still move. The site update operation — restricted to the `ProgramDirector` — accepts changes to `target_open_date`, `budget_allocation_cents`, and `phase_wave`, and it always requires `expected_site_version` per §2.7. The grand-opening date locks as soon as the site leaves `LISTED` or `DESIGN`: from `PERMITTING` onward, changing `target_open_date` is rejected with `ERR_OPEN_DATE_LOCKED` unless the request carries a `director_override_reason`. Any accepted date change synchronizes the commitment's `committed_open_on` and recomputes the forecast and protection posture, and every accepted update increments the site's `version`.

A site that must leave the program can be removed from any state except `OPEN`. Removal is refused while a vendor crew is physically on site — any mobilization in `ON_SITE` triggers `ERR_ACTIVE_VENDOR_ON_SITE`. Removal cascades: every `PROPOSED` change order on the site moves to `REJECTED`, a `REQUESTED` turnover moves to `SUPERSEDED`, the site drops out of all program budget aggregates, and the site's `version` increments. When the removed site was in `LISTED`, `IN_BUILD`, `PUNCH`, or `TURNOVER`, its not-yet-started mobilizations in `PLANNED` or `SCHEDULED` are additionally cancelled to `CANCELLED`; removal from `DESIGN`, `PERMITTING`, or `MOBILIZED` performs no such cancellation, because no crew windows should exist that early.

List endpoints support filtering throughout this subsection: programs filter by `status`; markets by `program_id` and `status`; sites by `program_id`, `market_id`, `status`, and `phase_wave`.

### 3.2. Prototype Drawings and Jurisdiction Variances

The `DesignManager` owns the drawing pipeline. Each drawing set captures the prototype adapted to one jurisdiction, created with the `program_id`, the `jurisdiction_code` of the municipality it applies to, and optional `variance_notes`. Revision numbering is automatic per program-and-jurisdiction pair: the `revision` of a new set is one more than the highest existing revision for that pair, and its `review_round` starts at 1. A new set is a `DRAFT`.

Submitting moves a set from `DRAFT` to `SUBMITTED`, where two outcomes exist. Approval moves it to `APPROVED` and enforces single-currency of approved drawings: any other `APPROVED` set for the same program and jurisdiction moves to `SUPERSEDED`, and the newly approved set's `supersedes_set_id` is pinned to the superseded set's `id`, or left null when nothing was superseded. Rejection moves the set to `REJECTED` and records the supplied `rejection_reason`. A rejected set is not dead: revising returns it from `REJECTED` to `DRAFT` and increments `review_round` by 1, starting another trip through the review loop.

Site design work rides on this pipeline. Advancing design moves a site from `LISTED` to `DESIGN`. Submitting the design moves it from `DESIGN` to `PERMITTING`, and that step is gated on drawings: an `APPROVED` drawing set must exist whose program matches the site's program and whose `jurisdiction_code` matches the site's `municipality_code`; without one the transition is rejected with `ERR_DRAWING_NOT_APPROVED`. Both transitions increment the site's `version`.

Drawing sets list with filters on `program_id`, `jurisdiction_code`, `status`, and `supersedes_set_id`.

### 3.3. Permitting by Municipality

Permit timing and fees differ per municipality, so the `PermitCoordinator` first registers a profile per municipality: the unique `municipality_code` that sites reference, the `statutory_review_days` the statute allows (the optimistic forecast basis), the `observed_avg_review_days` actually experienced (the conservative forecast basis), the `permit_validity_days` an issued permit stays alive, and the fee schedule — a flat `fee_base_cents` per application plus `fee_per_sqft_cents`, a rate in cents per 100 square feet of site area.

A permit application is created against a site by supplying the `site_id`, the `permit_type` — one of `BUILDING`, `ELECTRICAL`, `SIGNAGE`, or `HEALTH` — and the `drawing_set_id` pinning the exact drawing revision being filed. The permit copies its `municipality_code` from the site at creation, starts at `round_number` 1 in `DRAFT`, and its `fee_cents` reads 0 until filing. Two creation-time guards apply: a municipality profile must exist for the site's `municipality_code`, failing with `ERR_MUNICIPALITY_PROFILE_MISSING` otherwise; and a site may hold only one non-terminal permit of each type, so an existing permit of the same type in `DRAFT`, `FILED`, `UNDER_REVIEW`, or `ISSUED` causes rejection with `ERR_DUPLICATE_PERMIT_TYPE`.

Filing moves a permit from `DRAFT` to `FILED`. The pinned drawing set must still be `APPROVED` and must be the latest approved revision for its program-and-jurisdiction pair; filing against a superseded or otherwise stale revision is rejected with `ERR_DRAWING_SUPERSEDED`. Filing computes the current-round fee as the profile's flat base fee plus the site's `square_footage` multiplied by `fee_per_sqft_cents` and divided by 100, that product rounded half up to whole cents before being added to the base. The fee is debited into the site's `permit_fees_paid_cents` ledger, `filed_at` is stamped from the clock, and `review_due_on` is set to the filing date plus `statutory_review_days`.

The review itself walks `FILED` to `UNDER_REVIEW` to `ISSUED`. Starting review performs the first step; issuing performs the second, stamping `issued_at` from the clock and setting `expires_on` to the issue date plus `permit_validity_days`. A permit counts as expired when the current date is on or after `expires_on`, and the time-based sweep of §2.5 moves such `ISSUED` permits to `EXPIRED`. A municipality can instead reject the application — the move from `UNDER_REVIEW` to `REJECTED` records the `rejection_reason`.

Refiling is the cyclic resubmission loop: a `REJECTED` permit returns to `FILED` against the request's `drawing_set_id`, which must again identify the latest `APPROVED` revision for the site's program and municipality, failing with `ERR_DRAWING_SUPERSEDED` otherwise. Refiling increments `round_number`, re-pins the drawing to the supplied set, charges half of the base fee formula rounded half up to whole cents, debits the ledger a second time, and restamps `filed_at` and `review_due_on`. Withdrawing — allowed from `FILED` or `UNDER_REVIEW` — moves the permit to `WITHDRAWN` and credits the full current-round fee back out of `permit_fees_paid_cents`. The ledger's rounding order is pinned: each permit's fee is rounded to whole cents first and only then summed, so a ledger built by summing unrounded amounts and rounding once is wrong.

Permitting gates the site's construction start. Marking a site permitted moves it from `PERMITTING` to `MOBILIZED` and inspects the site's `BUILDING` permit with the latest `created_at`, whatever its status. If that permit is `EXPIRED`, or is `ISSUED` but its `expires_on` is on or before the current date, the transition is rejected with `ERR_PERMIT_EXPIRED`. Otherwise that latest `BUILDING` permit must exist and be `ISSUED`; when there is none, or the latest sits in any other status, the rejection is `ERR_PERMIT_NOT_ISSUED`. A successful transition increments the site's `version`.

Permits list with filters on `site_id`, `drawing_set_id`, `status`, and `permit_type`; municipality profiles filter by `municipality_code`.

### 3.4. GC Bidding and Award per Market

Procurement runs per market and per wave. The `ProcurementLead` first registers general contractors: each contractor carries a `legal_name`, a unique `license_no`, and its `license_state`, and starts `PREQUALIFIED`. Suspension moves a contractor from `PREQUALIFIED` to `SUSPENDED`, and suspended contractors cannot bid.

A bid package bundles one wave of one market. It is created with the `market_id`, the `phase_wave` it covers, a `scope_description`, the bidding window `bid_open_at` and `bid_close_at`, the `evaluation_mode` — `LOWEST_PRICE` or `BEST_VALUE` — and `max_duration_days`, the responsiveness cap on promised build durations. A package starts `DRAFT`. Opening it moves `DRAFT` to `OPEN` and requires the market to be `BIDDING`, failing with `ERR_MARKET_NOT_BIDDING` otherwise, and the clock to have reached `bid_open_at`, failing with `ERR_BID_WINDOW_NOT_OPEN` otherwise. Closing moves `OPEN` to `CLOSED` and requires the clock to have reached `bid_close_at` (`ERR_BID_WINDOW_STILL_OPEN`).

While a package is `OPEN`, a `GCVendor` submits bids with the `bid_package_id`, their own `contractor_id`, a per-store `amount_cents`, a promised per-store `duration_days`, and a `tech_score` between 0 and 100 inclusive, with out-of-range scores failing as `ERR_INVALID_REQUEST`. The `contractor_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN_IDENTITY`); the contractor must be `PREQUALIFIED` (`ERR_CONTRACTOR_NOT_PREQUALIFIED`); the package must be `OPEN` (`ERR_BID_PACKAGE_NOT_OPEN`); a submission at or after `bid_close_at` is refused with `ERR_BID_WINDOW_CLOSED` even if the package was never formally closed; and a contractor may hold only one `SUBMITTED` bid per package (`ERR_DUPLICATE_BID`). An accepted submission is stamped with `submitted_at` from the clock and lands in `SUBMITTED`. The server computes `is_responsive` on each bid: the amount must be positive, and the duration must be positive and no greater than the package's `max_duration_days`. A bidder may withdraw — moving the bid from `SUBMITTED` to `WITHDRAWN` — only their own bid (`ERR_FORBIDDEN_IDENTITY`) and only while the package is not yet `AWARDED` (`ERR_INVALID_STATE` once it is).

Awarding a closed package requires at least one responsive `SUBMITTED` bid, failing with `ERR_NO_RESPONSIVE_BIDS` otherwise. Under `LOWEST_PRICE`, candidates rank by ascending `amount_cents`, ties breaking toward the shorter `duration_days` and then the earlier `submitted_at`, and every bid's `evaluation_score` stays null. Under `BEST_VALUE`, each candidate's `evaluation_score` combines a price component — the lowest candidate amount divided by this bid's amount, multiplied by 100, weighted at 70% — with a technical component — the bid's `tech_score` weighted at 30% — the sum rounded half up to two decimal places; candidates rank by descending score, ties breaking toward the lower amount and then the earlier submission, so a higher-priced bid with a superior technical score can win.

The award cascade is wide. The winning bid moves to `AWARDED` and the package's `awarded_bid_id` is pinned to it; every other `SUBMITTED` bid moves to `REJECTED`; the package moves to `AWARDED`; the market moves from `BIDDING` to `AWARDED`; every site whose `market_id` and `phase_wave` match the package and which is not yet `OPEN` or `REMOVED` has its `base_contract_cents` set to the winning per-store amount; and site budget variances, the program budget rollup, and the affected sites' opening forecasts are all recomputed per §3.6 and §3.8.

Bids list with filters on `bid_package_id`, `contractor_id`, and `status`; packages filter by `market_id` and `status`; contractors filter by `status`.

### 3.5. Vendor Sequencing and Site Readiness

With a GC awarded, execution begins. Starting the build moves a site from `MOBILIZED` to `IN_BUILD` and requires the site's market to be `AWARDED`, failing with `ERR_MARKET_NOT_AWARDED` otherwise; the site's `version` increments. From that point the `SiteSuperintendent` choreographs three vendor types — `FIXTURE`, `IT`, and `SIGNAGE` — through mobilization windows on the site.

A mobilization is planned with the `site_id`, the `vendor_type`, the `vendor_name`, and a planned window running from `planned_start_on` up to but excluding `planned_end_on`; it starts `PLANNED`. Scheduling — moving from `PLANNED` to `SCHEDULED` — runs five checks. The site must be in `IN_BUILD` or `PUNCH` (`ERR_SITE_NOT_IN_BUILD`). The predecessor chain must be satisfied: an `IT` mobilization requires a `COMPLETE` `FIXTURE` mobilization on the site, a `SIGNAGE` mobilization requires a `COMPLETE` `IT` mobilization, and `FIXTURE` has no predecessor (`ERR_VENDOR_PREDECESSOR_INCOMPLETE`). The window must be feasible, with `planned_start_on` earlier than `planned_end_on` and the end still in the future relative to the current date (`ERR_SCHEDULE_INFEASIBLE`). The window must not overlap any other mobilization on the same site in `PLANNED`, `SCHEDULED`, or `ON_SITE` under half-open semantics — two windows that merely touch, one ending exactly when the next begins, do not conflict (`ERR_VENDOR_WINDOW_OVERLAP`). Finally comes market crew-day capacity: for every day of the window, the count of other mobilizations across all sites of the same market in `SCHEDULED` or `ON_SITE` whose windows also cover that day must be strictly below the market's `max_concurrent_vendor_crews` — a day may land exactly at capacity but never above it (`ERR_MARKET_CAPACITY_FULL`).

Arrival moves a mobilization from `SCHEDULED` to `ON_SITE`, allowed once the current date reaches `planned_start_on` (`ERR_SCHEDULE_INFEASIBLE` before then), and stamps `actual_start_on` with the current date. Completion moves it from `ON_SITE` to `COMPLETE`, stamps `actual_end_on`, and recomputes the site's `readiness_posture`: a completed `FIXTURE` mobilization yields `FIXTURE_SET`, a completed `IT` yields `IT_LIVE`, and a completed `SIGNAGE` yields `SIGNAGE_HUNG`. When every vendor type holds a `COMPLETE` mobilization, the site automatically advances from `IN_BUILD` to `PUNCH` — readiness reads `SIGNAGE_HUNG`, the opening forecast is recomputed, and the site's `version` increments. Cancelling from `PLANNED` or `SCHEDULED` moves the mobilization to `CANCELLED` and releases its market crew-day usage for every day of the window.

Mobilizations list with filters on `site_id`, `vendor_type`, and `status`.

### 3.6. Change Orders and Budget Variance Control

Change orders are the fiscal pressure valve of the build. A `SiteSuperintendent` proposes one with the `site_id`, a `description`, a signed `amount_cents` — negative amounts are credits — and a `cost_category` of `SCOPE`, `SCHEDULE`, `CODE_COMPLIANCE`, or `OWNER_REQUEST`. Proposal requires the site to be in its building phase with an awarded market behind it, failing with `ERR_MARKET_NOT_AWARDED` while the market is not `AWARDED`. The proposal lands in `PROPOSED`, records the caller's `X-User-ID` as `proposed_by_user_id`, and immediately adds `amount_cents` to the site's `proposed_co_cents` bucket.

Each proposal is tiered by size relative to the site's contract: the absolute amount, multiplied by 10000 and divided by `base_contract_cents`, compared exactly with no rounding — a guarantee made safe because proposal only happens after an award has set a positive base contract. A ratio of at most 200 basis points classifies `STANDARD`, at most 500 classifies `ELEVATED`, and anything larger classifies `CRITICAL`; the computed `tier` is stored on the change order.

Approval is the most heavily gated operation in the API. A `FinanceController` or `ProgramDirector` approves, optionally attaching an `approval_note`, and the checks run in the global order of §2.10: the site must not be `OPEN` or `REMOVED` (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` for a terminal site); `expected_site_version` must match the site's current `version` (`ERR_STALE_VERSION`, per §2.7); tier authority requires a `FinanceController` for `STANDARD` and `ELEVATED` orders but a `ProgramDirector` for `CRITICAL` ones (`ERR_CO_TIER_ROLE_REQUIRED`); the approver's `X-User-ID` must differ from `proposed_by_user_id`, enforcing segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); a `SCHEDULE`-category order may not be approved while the site's opening commitment sits in `AT_RISK` or `BREACHED` — the opening lock (`ERR_OPENING_LOCK_ENGAGED`); and finally the fiscal check — a credit always passes, but a positive amount must fit the site's headroom, with `committed_cents` plus `amount_cents` not exceeding `budget_allocation_cents` (`ERR_BUDGET_HEADROOM_EXCEEDED`).

An approved order moves to `APPROVED` and rewrites the site's ledger: `amount_cents` leaves `proposed_co_cents` and enters `approved_co_cents`; `committed_cents` — always `base_contract_cents` plus the sum of `APPROVED` change-order amounts — is recomputed; the site's `version` increments; both variance ratios and the site `budget_posture` re-derive; the program rollup recomputes; and the opening forecast recomputes with its provisional-ratio slip factor (§3.8). Rejection by a `FinanceController` or `ProgramDirector` records the `rejection_reason`, moves the order to `REJECTED`, removes the amount from `proposed_co_cents`, recomputes the provisional ratio, and increments the site's `version`. Cancellation by the proposing superintendent — only the recorded proposer may cancel (`ERR_FORBIDDEN_IDENTITY`) — performs the same bucket compensation and lands at `CANCELLED`. Rescission by a `FinanceController`, accompanied by a `rescind_reason`, moves an `APPROVED` order to `RESCINDED` as the exact compensation of approval: the site must not be `OPEN` or `REMOVED` (`ERR_INVALID_STATE`), the amount leaves `approved_co_cents`, `committed_cents` recomputes, the site's `version` increments, and variance ratios, postures, the program rollup, and the opening forecast all re-derive.

Two variance ratios track each site in basis points. While `base_contract_cents` is 0, both read 0. Otherwise the final ratio, `variance_ratio_final_bp`, is `committed_cents` minus `base_contract_cents`, multiplied by 10000, divided by `base_contract_cents`, and rounded half up; the provisional ratio, `variance_ratio_provisional_bp`, applies the same formula to `committed_cents` plus `proposed_co_cents`, so identical data yields a higher provisional figure whenever a `PROPOSED` order exists. The site's `budget_posture` keys off the final ratio: at most 500 basis points reads `WITHIN`, at most 1500 reads `WATCH`, and beyond that `OVERRUN`.

The program rollup aggregates over all sites of the program not in `REMOVED`. The program's `committed_cents` and `actuals_cents` are the plain sums over those sites. The contingency reserve works per site: a site's overrun is its `committed_cents` minus its `base_contract_cents`, floored at zero; the reserve charges one quarter of that overrun for `WATCH` sites and the whole overrun for `OVERRUN` sites, each term rounded half up to whole cents before summation into `contingency_reserved_cents`. The program's `contingency_free_cents` is the pool minus the reserve, and its `budget_posture` reads `OVERRUN` when the free amount is negative, else `GUARDED` when twice the reserve exceeds the pool, else `WITHIN_PLAN`.

Change orders list with filters on `site_id`, `status`, and `tier`.

### 3.7. Punch List, Turnover, and Store Opening

Once a site reaches `PUNCH`, the superintendent logs deficiencies as punch items with the `site_id`, a `description`, and a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`; creation is only meaningful while the site is in `PUNCH` or `TURNOVER`. Each item starts `OPEN` with `reopen_count` 0, and the site maintains two live counts over its items: `punch_open_critical_count`, the `CRITICAL` items sitting in `OPEN` or `RESOLVED`, and `punch_open_total_count`, all items in `OPEN` or `RESOLVED` — a resolved item still counts as open until verified.

Resolving moves an item from `OPEN` to `RESOLVED` and leaves both counts unchanged. Verification by an `OperationsLead` moves `RESOLVED` to `VERIFIED` and recomputes the counts. Failed verification sends the item back from `RESOLVED` to `OPEN`, takes a `failure_note`, increments `reopen_count` by 1, and recomputes the counts — the rework loop can cycle as many times as needed. Waiver moves an item from `OPEN` or `RESOLVED` to `WAIVED` and recomputes the counts, but only `MAJOR` and `MINOR` items are waivable; waiving a `CRITICAL` item is rejected with `ERR_PUNCH_NOT_WAIVABLE`.

When the list is clear enough, the superintendent requests turnover with just the `site_id`. The site must be in `PUNCH` (`ERR_INVALID_STATE` otherwise), `punch_open_critical_count` must be zero (`ERR_PUNCH_CRITICAL_OPEN`), and no other turnover may already sit `REQUESTED` for the site (`ERR_TURNOVER_ALREADY_REQUESTED`). The request lands `REQUESTED`, pins a `readiness_snapshot` capturing the site's `readiness_posture`, `punch_open_critical_count`, `punch_open_total_count`, and `forecast_open_on` at that instant, and automatically moves the site from `PUNCH` to `TURNOVER`, incrementing its `version`.

Acceptance is the operations lead's decision and requires `expected_site_version` per §2.7, a mismatch failing with `ERR_STALE_VERSION`. The punch gate demands every `CRITICAL` and `MAJOR` item be `VERIFIED`, and either every `MINOR` item be `VERIFIED` or `WAIVED`, or the request flag `waive_open_minor` be set true — anything short is rejected with `ERR_PUNCH_ITEMS_OUTSTANDING`. When acceptance proceeds with `waive_open_minor`, remaining `MINOR` items in `OPEN` or `RESOLVED` are swept to `WAIVED`. Acceptance is also the final reconciliation: the site's `actuals_cents` is set equal to its `committed_cents`, program actuals recompute, and the site's `version` increments. Rejection, carrying a `rejection_reason`, moves the turnover to `REJECTED` and automatically reverts the site from `TURNOVER` back to `PUNCH` for another round of work.

Opening the store moves the site from `TURNOVER` to `OPEN` and requires an `ACCEPTED` turnover to exist (`ERR_TURNOVER_NOT_ACCEPTED` otherwise); the site's opening commitment moves to `MET` and the site's `version` increments.

Punch items list with filters on `site_id`, `status`, and `severity`; turnovers filter by `site_id` and `status`.

### 3.8. Grand-Opening Date Protection

Every site carries exactly one `OpeningCommitment`, auto-created with the site as described in §3.1. Its `committed_open_on` mirrors the site's `target_open_date`, and its computed fields are `forecast_open_on` — the conservative forecast — `forecast_optimistic_on`, `slip_days`, and `protection_posture`. Commitments list with filters on `site_id` and `protection_posture`.

The forecast evaluation order is pinned, because budget posture and the forecast reference each other. First the site's variance ratios and `budget_posture` are computed from the current change-order buckets (§3.6). Then a slip factor derives from the provisional ratio: 0 basis points when that ratio is at most 500, 500 when it is at most 1500, and 1500 beyond that. Then the forecast dates are computed, and only then is `protection_posture` derived. The change-order opening lock of §3.6 reads the stored posture from the previous evaluation; it never feeds back within a single evaluation.

The permit block measures outstanding reviews over permits in `FILED` or `UNDER_REVIEW`. The optimistic block uses each permit's `review_due_on`, taking the days from today until that date, floored at zero. The conservative block instead dates each permit from its filing date plus the municipality's `observed_avg_review_days`, again floored at zero. Each block is the maximum across the set, or zero when no such permit exists.

The vendor chain walks the three types in fixed order — `FIXTURE`, then `IT`, then `SIGNAGE` — skipping any type that already holds a `COMPLETE` mobilization. For each incomplete type the forecast uses its non-terminal mobilization — one in `PLANNED`, `SCHEDULED`, or `ON_SITE`, choosing the earliest-created when several exist; a required type with no scheduled work contributes zero days, because the forecast prices only scheduled work. A running cursor accumulates time across the chain. Optimistically, each window starts at the later of the cursor and its `planned_start_on` and lasts its planned length. Conservatively, the planned length is padded by the slip factor — multiplied by one plus the slip factor divided by 10000 — and rounded half up to whole days. For a mobilization already `ON_SITE`, both variants count only the remaining planned time from the later of the cursor and today through `planned_end_on`, floored at zero.

The conservative forecast `forecast_open_on` is today plus the conservative permit block plus the conservative vendor chain plus a fixed ten-day punch buffer; `forecast_optimistic_on` combines the optimistic block and chain with the same buffer. `slip_days` is the number of days by which the conservative forecast passes `committed_open_on`, floored at zero.

The protection posture derives last. A site in `OPEN` reads `MET`. Before that, a current date on or after `committed_open_on` while the site has not opened reads `BREACHED`. Otherwise the slip decides: zero slip is `PROTECTED`, one to seven days is `WATCH`, eight to twenty-one days is `AT_RISK`, and twenty-two days or more is `BREACHED`. These transitions are pure recalculation — posture migrates in both directions as inputs change — and after the director moves a breached commitment's date later through the override of §3.1, recalculation can return `BREACHED` to `PROTECTED`, `WATCH`, or `AT_RISK` by the same slip bands. Every posture moves to `MET` the moment its site opens.

Recomputation fires on vendor completion, on permit filing and issuance, on change-order approval and rescission, on the automatic advance to `PUNCH`, on site open-date changes, on the time-based sweep, and — on demand — through a `ProgramDirector`-initiated recalculation of any single commitment.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. All other operations — reads, state transitions, updates, the clock and sweep capabilities — return `200 OK`. All paths are mounted under `/rollout`. The table below summarizes only the HTTP contract; request payloads, computed fields, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rollout/_clock/set_current_utc` | Set the logical clock | ProgramDirector |
| POST | `/rollout/_sweeps/time-based` | Apply clock-driven permit expiry and forecast recomputation | ProgramDirector |
| POST | `/rollout/programs` | Create a rollout program | ProgramDirector |
| GET | `/rollout/programs` | List programs | Any |
| GET | `/rollout/programs/{programId}` | Get a program with its computed budget rollup | Any |
| POST | `/rollout/programs/{programId}/activate` | Activate a program (`SETUP` → `ACTIVE`) | ProgramDirector |
| POST | `/rollout/programs/{programId}/complete` | Complete a program once all sites are terminal | ProgramDirector |
| POST | `/rollout/markets` | Create a market in a program | ProgramDirector |
| GET | `/rollout/markets` | List markets | Any |
| GET | `/rollout/markets/{marketId}` | Get a market | Any |
| POST | `/rollout/markets/{marketId}/open-bidding` | Open bidding on a market (`REGISTERED` → `BIDDING`) | ProcurementLead |
| POST | `/rollout/municipality-profiles` | Create a municipality fee/review profile | PermitCoordinator |
| GET | `/rollout/municipality-profiles` | List municipality profiles | Any |
| POST | `/rollout/sites` | Create a site and its opening commitment | ProgramDirector |
| GET | `/rollout/sites` | List sites | Any |
| GET | `/rollout/sites/{siteId}` | Get a site | Any |
| PATCH | `/rollout/sites/{siteId}` | Update mutable site fields with optimistic concurrency | ProgramDirector |
| POST | `/rollout/sites/{siteId}/advance-design` | Advance a site from `LISTED` to `DESIGN` | DesignManager |
| POST | `/rollout/sites/{siteId}/submit-design` | Move a site from `DESIGN` to `PERMITTING` | DesignManager |
| POST | `/rollout/sites/{siteId}/mark-permitted` | Move a site from `PERMITTING` to `MOBILIZED` | PermitCoordinator |
| POST | `/rollout/sites/{siteId}/start-build` | Move a site from `MOBILIZED` to `IN_BUILD` | SiteSuperintendent |
| POST | `/rollout/sites/{siteId}/open` | Open the store (`TURNOVER` → `OPEN`) | OperationsLead |
| POST | `/rollout/sites/{siteId}/remove` | Remove a site from the program | ProgramDirector |
| POST | `/rollout/drawing-sets` | Create a drawing set with auto-assigned revision | DesignManager |
| GET | `/rollout/drawing-sets` | List drawing sets | Any |
| GET | `/rollout/drawing-sets/{drawingSetId}` | Get a drawing set | Any |
| POST | `/rollout/drawing-sets/{drawingSetId}/submit` | Submit a drawing set for review | DesignManager |
| POST | `/rollout/drawing-sets/{drawingSetId}/approve` | Approve; supersede the prior approved revision | DesignManager |
| POST | `/rollout/drawing-sets/{drawingSetId}/reject` | Reject a submitted drawing set | DesignManager |
| POST | `/rollout/drawing-sets/{drawingSetId}/revise` | Return a rejected set to `DRAFT` | DesignManager |
| POST | `/rollout/permits` | Create a permit application pinning a drawing revision | PermitCoordinator |
| GET | `/rollout/permits` | List permits | Any |
| GET | `/rollout/permits/{permitId}` | Get a permit | Any |
| POST | `/rollout/permits/{permitId}/file` | File; compute and debit the filing fee | PermitCoordinator |
| POST | `/rollout/permits/{permitId}/start-review` | Move from `FILED` to `UNDER_REVIEW` | PermitCoordinator |
| POST | `/rollout/permits/{permitId}/issue` | Issue; set the validity window | PermitCoordinator |
| POST | `/rollout/permits/{permitId}/reject` | Reject an application under review | PermitCoordinator |
| POST | `/rollout/permits/{permitId}/refile` | Refile at half fee with a re-pinned drawing | PermitCoordinator |
| POST | `/rollout/permits/{permitId}/withdraw` | Withdraw; refund the current-round fee | PermitCoordinator |
| POST | `/rollout/contractors` | Register a prequalified GC | ProcurementLead |
| GET | `/rollout/contractors` | List contractors | Any |
| GET | `/rollout/contractors/{contractorId}` | Get a contractor | Any |
| POST | `/rollout/contractors/{contractorId}/suspend` | Suspend a contractor | ProcurementLead |
| POST | `/rollout/bid-packages` | Create a per-market per-wave bid package | ProcurementLead |
| GET | `/rollout/bid-packages` | List bid packages | Any |
| GET | `/rollout/bid-packages/{bidPackageId}` | Get a bid package | Any |
| POST | `/rollout/bid-packages/{bidPackageId}/open` | Open the bidding window | ProcurementLead |
| POST | `/rollout/bid-packages/{bidPackageId}/close` | Close the bidding window | ProcurementLead |
| POST | `/rollout/bid-packages/{bidPackageId}/award` | Award; set base contracts on matching wave sites | ProcurementLead |
| POST | `/rollout/bids` | Submit a bid | GCVendor |
| GET | `/rollout/bids` | List bids | Any |
| GET | `/rollout/bids/{bidId}` | Get a bid | Any |
| POST | `/rollout/bids/{bidId}/withdraw` | Withdraw an own bid before award | GCVendor |
| POST | `/rollout/vendor-mobilizations` | Plan a vendor mobilization window | SiteSuperintendent |
| GET | `/rollout/vendor-mobilizations` | List vendor mobilizations | Any |
| GET | `/rollout/vendor-mobilizations/{mobilizationId}` | Get a vendor mobilization | Any |
| POST | `/rollout/vendor-mobilizations/{mobilizationId}/schedule` | Schedule; enforce predecessor, overlap, and capacity rules | SiteSuperintendent |
| POST | `/rollout/vendor-mobilizations/{mobilizationId}/arrive` | Mark the crew on site | SiteSuperintendent |
| POST | `/rollout/vendor-mobilizations/{mobilizationId}/complete` | Complete; recompute readiness and forecast | SiteSuperintendent |
| POST | `/rollout/vendor-mobilizations/{mobilizationId}/cancel` | Cancel; release crew-day usage | SiteSuperintendent |
| POST | `/rollout/change-orders` | Propose a change order | SiteSuperintendent |
| GET | `/rollout/change-orders` | List change orders | Any |
| GET | `/rollout/change-orders/{changeOrderId}` | Get a change order | Any |
| POST | `/rollout/change-orders/{changeOrderId}/approve` | Approve under tier, segregation, concurrency, lock, and headroom gates | FinanceController, ProgramDirector |
| POST | `/rollout/change-orders/{changeOrderId}/reject` | Reject a proposed change order | FinanceController, ProgramDirector |
| POST | `/rollout/change-orders/{changeOrderId}/rescind` | Rescind an approved change order | FinanceController |
| POST | `/rollout/change-orders/{changeOrderId}/cancel` | Cancel an own proposal | SiteSuperintendent |
| POST | `/rollout/punch-items` | Create a punch item | SiteSuperintendent |
| GET | `/rollout/punch-items` | List punch items | Any |
| GET | `/rollout/punch-items/{punchItemId}` | Get a punch item | Any |
| POST | `/rollout/punch-items/{punchItemId}/resolve` | Mark an item resolved | SiteSuperintendent |
| POST | `/rollout/punch-items/{punchItemId}/verify` | Verify a resolution | OperationsLead |
| POST | `/rollout/punch-items/{punchItemId}/fail-verification` | Fail verification; reopen the item | OperationsLead |
| POST | `/rollout/punch-items/{punchItemId}/waive` | Waive a `MAJOR` or `MINOR` item | OperationsLead |
| POST | `/rollout/turnovers` | Request turnover to operations | SiteSuperintendent |
| GET | `/rollout/turnovers` | List turnovers | Any |
| GET | `/rollout/turnovers/{turnoverId}` | Get a turnover | Any |
| POST | `/rollout/turnovers/{turnoverId}/accept` | Accept; finalize actuals | OperationsLead |
| POST | `/rollout/turnovers/{turnoverId}/reject` | Reject; the site reverts to `PUNCH` | OperationsLead |
| GET | `/rollout/opening-commitments` | List opening commitments | Any |
| GET | `/rollout/opening-commitments/{commitmentId}` | Get an opening commitment | Any |
| POST | `/rollout/opening-commitments/{commitmentId}/recalculate` | Force recomputation of forecast and posture | ProgramDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_IDENTITY` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CO_TIER_ROLE_REQUIRED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACTIVE_SITES_REMAIN` | 409 Conflict |
| `ERR_MARKET_NOT_BIDDING` | 409 Conflict |
| `ERR_MARKET_NOT_AWARDED` | 409 Conflict |
| `ERR_CONTRACTOR_NOT_PREQUALIFIED` | 409 Conflict |
| `ERR_DUPLICATE_BID` | 409 Conflict |
| `ERR_BID_PACKAGE_NOT_OPEN` | 409 Conflict |
| `ERR_BID_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_BID_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BID_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_NO_RESPONSIVE_BIDS` | 409 Conflict |
| `ERR_DRAWING_NOT_APPROVED` | 409 Conflict |
| `ERR_DRAWING_SUPERSEDED` | 409 Conflict |
| `ERR_MUNICIPALITY_PROFILE_MISSING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PERMIT_TYPE` | 409 Conflict |
| `ERR_PERMIT_NOT_ISSUED` | 409 Conflict |
| `ERR_PERMIT_EXPIRED` | 409 Conflict |
| `ERR_SITE_NOT_IN_BUILD` | 409 Conflict |
| `ERR_SCHEDULE_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_VENDOR_PREDECESSOR_INCOMPLETE` | 409 Conflict |
| `ERR_VENDOR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MARKET_CAPACITY_FULL` | 409 Conflict |
| `ERR_ACTIVE_VENDOR_ON_SITE` | 409 Conflict |
| `ERR_BUDGET_HEADROOM_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OPENING_LOCK_ENGAGED` | 409 Conflict |
| `ERR_OPEN_DATE_LOCKED` | 409 Conflict |
| `ERR_PUNCH_CRITICAL_OPEN` | 409 Conflict |
| `ERR_PUNCH_NOT_WAIVABLE` | 422 Unprocessable Entity |
| `ERR_PUNCH_ITEMS_OUTSTANDING` | 409 Conflict |
| `ERR_TURNOVER_ALREADY_REQUESTED` | 409 Conflict |
| `ERR_TURNOVER_NOT_ACCEPTED` | 409 Conflict |

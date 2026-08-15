# Industrial Property Leasing & Build-to-Suit API — Product Requirements Document

## 1. Introduction

Industrial development deals are long, multi-party affairs: a tenant-side broker arrives with a space requirement defined in physical terms — clear height, dock doors, power, truck-court depth — and the developer must screen inventory, walk the candidate sites, negotiate letter-of-intent economics, verify environmental and zoning posture, convert construction budgets into rent for build-to-suit product, manage delivery against a contractual schedule, and settle broker commissions months later when rent finally commences. Each step involves a different desk on the developer side, and a deal can stall or unwind at any one of them. This document specifies the REST API that an industrial developer operates to run that pipeline end to end, from requirement intake through lease execution, delivery, and commission settlement.

The platform serves five desks. A tenant-side representative drives intake, tours, LOI submissions, and expansion-option exercise; the developer's leasing lead manages inventory, counters, acceptances, option grants, and commission administration; a construction lead prices build-to-suit plans and tracks delivery milestones; a final approver executes leases, approves pricing, and controls the system's logical clock; a compliance officer clears or flags environmental and zoning-use reviews. Because negotiations iterate, the LOI lifecycle is explicitly cyclic; because delivery dates slip, rent commencement and abatement are computed from actual milestone outcomes rather than contract dates; and because two parties alternate writes on the same negotiation document, the API guards that document with optimistic concurrency. All endpoints are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting operator, and `X-User-Role` declares their role. A request missing either header, or presenting a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403); the same code is returned when a representative-scoped ownership check fails, so callers cannot distinguish the two failure modes.

Five roles exist, spelled exactly as follows:

- `TenantRep` — the tenant-side broker: owns requirement intake and withdrawal, requests and completes and cancels their own tours, creates and submits and withdraws LOIs, and exercises or releases expansion options riding on their deals.
- `LeasingManager` — the developer-side leasing lead: registers sites, confirms and cancels tours, counters, accepts, and rejects LOIs, grants expansion options, and administers commission invoices (issue, pay, dispute).
- `ProjectManager` — the developer-side construction lead: prices and revises build-to-suit plans and creates and completes delivery milestones.
- `AssetManager` — the developer-side final approver: executes accepted LOIs, approves build-to-suit pricing, and operates the logical clock.
- `ComplianceOfficer` — the environmental and zoning-use verifier: opens, begins, and resolves compliance reviews.

All five roles use opaque operator identifiers. When `X-User-Role` is `TenantRep`, `X-User-ID` is an opaque identifier not tied to any persisted entity's `id`; the server records it as `tenant_rep_id` on each `TenantRequirement` and each `Tour` the representative creates, and ownership checks on those resources compare the resource's `tenant_rep_id` field to `X-User-ID`. When `X-User-Role` is `LeasingManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it to an entity's `id`. The same holds individually for `ProjectManager`, for `AssetManager`, and for `ComplianceOfficer`: each presents an opaque `X-User-ID` that the server does not match against any stored entity identifier.

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

List endpoints accept two query parameters: `limit`, which defaults to 10 with a minimum of 1 and a maximum of 100, and `offset`, which defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Results are sorted by `created_at` ascending. Filters documented with each list in §3 are conjunctive and combine freely with pagination.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system — tenant requirements, sites, tours, LOIs, build-to-suit plans, delivery milestones, expansion options, compliance reviews, and commission invoices — carries four common properties; no entity in this system omits any of them. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation, including mutations caused by cascades originating on another entity. `version` is an integer that increments by one on every mutation of the resource, again including cascaded mutations.

### 2.5. The Logical Clock

Time-dependent rules — tour completion eligibility, expansion-option exercise windows, and option expiry — are evaluated against a logical clock, never the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. An `AssetManager`-only test-driving capability moves the clock forward: the request carries `to_iso8601`, and the response reports the new `current_utc`. Workflows that read time always read this clock.

### 2.6. Optimistic Concurrency Control on the Negotiation Document

Two writes on the LOI are version-gated: submitting an LOI (both the initial submission and any resubmission after a counter) and countering an LOI. Each such request must carry `expected_loi_version`, the value of the LOI's `version` that the client last observed. If the LOI's current `version` does not equal `expected_loi_version` — because the other side of the negotiation has legitimately advanced the document since the client read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the LOI before acting again. No other endpoint accepts a version field. Every successful submit or counter itself increments the LOI's `version` by one (and advances `negotiation_round`), so a client's observed version goes stale the moment the counterparty acts.

### 2.7. Monetary Precision, Rounding, and Remainder Pinning

All monetary amounts and per-square-foot rates are carried at 2 decimal places, rounded half up. `yield_on_cost` is the single exception, rendered at 4 decimal places, also rounded half up. `abatement_days` is a whole-day count with no rounding. Two rounding-order rules are pinned and may not be reordered. First, aggregate rent is summed from unrounded yearly amounts and rounded exactly once, to cents. Second, the tiered broker commission rounds each tier to cents before the tiers are summed — never the reverse — and every division remainder is pinned in a fixed direction: the half-cent remainder of the side split lands on the `LANDLORD_REP` invoice, and the remainder of the installment split lands on the second installment, as detailed in §3.7.

### 2.8. Validation Order and Failure Precedence

When several checks could fail on the same request, the earliest applicable check in the following global order determines the rejection; later failures are masked by earlier ones.

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the five declared roles, on every endpoint — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The acting role must be listed for the endpoint — otherwise `ERR_FORBIDDEN` (403).
3. **Representative ownership.** On representative-scoped writes — withdrawing a requirement, submitting or withdrawing an LOI, completing a tour, a `TenantRep` cancelling a tour, exercising or releasing an expansion option — `X-User-ID` must equal the owning record's `tenant_rep_id` — otherwise `ERR_FORBIDDEN` (403).
4. **Existence.** Every identifier in the URL path and every foreign-key identifier in the request body (`requirement_id`, `site_id`, `plan_id`, `loi_id`, `land_site_id`) must resolve to an existing record, validated left to right with path identifiers before body identifiers — otherwise `ERR_NOT_FOUND` (404).
5. **Request shape.** Required fields must be present with correct types on every creation and action call — otherwise `ERR_INVALID_REQUEST` (400).
6. **Enum membership.** Enum-typed inputs — `use_type`, `parcel_type`, `pricing_method`, `milestone_type`, `review_type`, `outcome`, `commission_basis` — must carry a declared member — otherwise `ERR_INVALID_ENUM` (400).
7. **Range sanity.** A tour's `end_at` must be strictly after `start_at`; an option's `window_close_date` must be strictly after `window_open_date`; a requirement's `min_sf` must not exceed `max_sf` — otherwise `ERR_INVALID_TIME_RANGE` (422).
8. **State-machine legality.** The requested transition must be declared from the entity's current status; terminal states accept no further transitions — otherwise `ERR_INVALID_STATE` (409).
9. **Stale-version check.** On the two version-gated LOI writes, `expected_loi_version` must equal the LOI's current `version` — otherwise `ERR_STALE_VERSION` (412).
10. **Site-status gates.** Where a workflow requires the referenced site to be `LISTED` (LOI creation, LOI acceptance, option grant, option exercise) or to be `LISTED` or `RESERVED` (tour confirmation), it must be — otherwise `ERR_SITE_NOT_LISTED` (409).
11. **Compliance gates.** Lease execution and option exercise require specific `CLEARED` reviews — otherwise `ERR_COMPLIANCE_NOT_CLEARED` (409).
12. **LOI-creation battery, in this fixed order.** Hard physical minimums (`ERR_HARD_MINIMUMS_NOT_MET`, 422), then the completed-tour requirement (`ERR_NO_COMPLETED_TOUR`, 409), then the no-open-LOI uniqueness rule (`ERR_LOI_ALREADY_OPEN`, 409), then the `leased_sf` size-band rule (`ERR_SF_OUT_OF_RANGE`, 422), then site availability (`ERR_INSUFFICIENT_SF`, 422).
13. **Tour scheduling.** The buffered site-schedule check runs before the representative-calendar check — `ERR_TOUR_SITE_CONFLICT` (409) surfaces ahead of `ERR_REP_CALENDAR_CONFLICT` (409).
14. **Uniqueness of child records.** A duplicate `milestone_type` on a plan (or a milestone create against a plan in a disallowed status) fails with `ERR_DUPLICATE_MILESTONE` (409); a duplicate review triple fails with `ERR_DUPLICATE_REVIEW` (409). These two sit at the same precedence tier on their respective endpoints.
15. **Temporal gates.** Option not-yet-open (`ERR_OPTION_WINDOW_NOT_OPEN`, 409) is checked before option expired (`ERR_OPTION_WINDOW_EXPIRED`, 409); a tour completed before its window ends fails `ERR_TOUR_NOT_CONCLUDED` (409); an installment-2 payment before the due flag fails `ERR_INSTALLMENT_NOT_DUE` (409).
16. **Fiscal gates.** The free-rent cap at submission (`ERR_FREE_RENT_OVER_CAP`, 422), the net-effective floor at acceptance (`ERR_NER_BELOW_FLOOR`, 422), and the conversion-overrun cap at plan approval (`ERR_RENT_CONVERSION_OVER_RUN`, 422).

The trigger conditions themselves are defined with their workflows in §3; this section fixes only precedence.

### 2.9. Cross-Entity Cascade Architecture

State changes propagate across entities within the same request, and every side effect is visible in that request's response — the consistency model is immediate, with no deferred settlement. Three multi-link cascades pin the architecture. First, accepting an LOI moves its site from `LISTED` to `RESERVED` and adds the leased square footage to the site's `reserved_sf`; that site transition, in turn, rejects every competing `SUBMITTED` or `COUNTERED` LOI on the same site — the rejections are caused by the site transition, not by the accept call directly. Second, executing an LOI moves the site from `RESERVED` to `COMMITTED`, and that commitment cancels every `REQUESTED` or `CONFIRMED` tour at the site that serves a different requirement. Third, delivering a build-to-suit plan writes rent commencement and delay abatement onto its LOI and moves the site from `COMMITTED` to `LEASED`; the site reaching `LEASED` then flips `installment_2_due` to true on every commission invoice of the linked LOI.

Compensating cascades run in the reverse direction. Withdrawing an `ACCEPTED` LOI releases the reservation — the site returns from `RESERVED` to `LISTED` and the LOI's square footage leaves `reserved_sf` — and releases every `GRANTED` expansion option riding on that LOI. Withdrawing a requirement cancels its open tours and withdraws its open LOIs in one motion. Full preconditions live with each workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Requirement Intake and Site Inventory

An engagement opens when a `TenantRep` registers a tenant requirement. The intake payload names the prospective tenant (`tenant_name`), the use (`use_type`, one of `DISTRIBUTION`, `MANUFACTURING`, `COLD_STORAGE`, or `R_AND_D`), the acceptable size band (`min_sf` and `max_sf`), and the four physical minimums that drive screening: `min_clear_height_ft`, `min_dock_doors`, `min_power_amps`, and `min_yard_depth_ft`. The representative also records `target_submarket`, a free-text label scoping the market survey, and `required_delivery_date`, the date by which the tenant needs occupancy. `min_sf` must be greater than zero and no greater than `max_sf`; a size band that violates this is rejected with `ERR_INVALID_TIME_RANGE` (422). The creating representative's header is stamped into `tenant_rep_id`, which becomes the ownership token for every later rep-scoped write on the record, and the requirement begins life `ACTIVE`.

A requirement ends in one of two terminal states. It becomes `SATISFIED` only by system action, at the moment a linked LOI is executed; and it becomes `WITHDRAWN` when the owning representative withdraws it — ownership here means `X-User-ID` equals the requirement's `tenant_rep_id`, failing which the call is `ERR_FORBIDDEN`. Withdrawal cascades in the same request: every tour of that requirement in `REQUESTED` or `CONFIRMED` status moves to `CANCELLED`, and every LOI raised against it in `DRAFT`, `SUBMITTED`, or `COUNTERED` status moves to `WITHDRAWN`. Any role may fetch a single requirement by its identifier.

On the other side of the market, a `LeasingManager` registers each building or land parcel in the developer's inventory. Registration captures `site_name`, the `submarket` label used for survey filtering, the `parcel_type` (`EXISTING` for a standing building, `LAND_BANK` for banked land held for expansion or build-to-suit), and `total_sf`, the total rentable square footage, which must be greater than zero and is immutable after registration. Physical attributes follow: `clear_height_ft` and `dock_doors` (both zero on raw land), `power_amps`, and `yard_depth_ft`. Compliance posture is declared up front through `zoning_designation` (a code such as M-1, M-2, or I-2) and `environmental_phase` (one of `PHASE_I_COMPLETE`, `PHASE_II_REQUIRED`, or `REMEDIATED`). Finally, `asking_rate_psf` records the annual NNN asking rate per square foot — the anchor from which match floors, negotiation floors, and market-comp pricing are all derived. A newly registered site starts `LISTED` with `reserved_sf` at zero; `available_sf` is read-only and always equals `total_sf` minus `reserved_sf`, recomputed whenever `reserved_sf` changes.

The site's lifecycle is a four-stage conveyor with one release valve: `LISTED` → `RESERVED` when an LOI acceptance (or an option exercise, for a land parcel) reserves square footage; `RESERVED` → `COMMITTED` when the reserving LOI is executed; `COMMITTED` → `LEASED` when the linked build-to-suit plan is delivered; and `RESERVED` → `LISTED` as the compensating release when the reserving deal is withdrawn before execution. `LEASED` is terminal. The market-survey list supports filtering by `submarket`, `status`, and `parcel_type`, with standard pagination, and any role may fetch a single site.

### 3.2. Market Survey, Site Matching, and Tour Coordination

Before anyone drives a tour, either a `TenantRep` or a `LeasingManager` may run a stateless match evaluation over a requirement/site pair by supplying `requirement_id` and `site_id`. Both records must exist, otherwise `ERR_NOT_FOUND`; a site in any status may be scored. The evaluation persists nothing — it is a screening read — and returns `requirement_id`, `site_id`, the computed `match_score`, and the boolean `hard_minimums_met`.

The score weights four physical attributes: clear height at 30%, dock doors at 30%, power at 20%, and yard depth at 20%. Each attribute contributes its weight multiplied by the ratio of the site's measurement to the requirement's corresponding minimum — that ratio capped at 1.25 — with the capped ratio then divided by 1.25 and the result multiplied by 100. `match_score` is the sum of the four contributions, rounded half-up to two decimal places. A site that exactly meets every minimum therefore scores 80, and the cap means a site at or beyond 125% of every minimum scores the full 100. `hard_minimums_met` is true only when all five conditions hold: the site's `clear_height_ft` is at least `min_clear_height_ft`, its `dock_doors` at least `min_dock_doors`, its `power_amps` at least `min_power_amps`, its `yard_depth_ft` at least `min_yard_depth_ft`, and its `total_sf` at least `min_sf`. The upper bound of the tenant's size band is deliberately not tested here; it is enforced later through the `leased_sf` range at LOI creation.

Once a candidate survives screening, the representative requests a tour by naming `site_id` and `requirement_id` with a window from `start_at` to `end_at`; the end must be strictly after the start, otherwise `ERR_INVALID_TIME_RANGE`. The representative's header is stamped into `tenant_rep_id`, and the tour begins `REQUESTED`. Two scheduling guards apply, the site schedule checked before the representative's calendar. The site guard rejects the request with `ERR_TOUR_SITE_CONFLICT` (409) when any non-`CANCELLED` tour at the same site has a buffered window — thirty minutes of padding on each side, running from thirty minutes before its `start_at` to thirty minutes after its `end_at` — that intersects the new tour's half-open window from `start_at` up to but not including `end_at`. The calendar guard then rejects with `ERR_REP_CALENDAR_CONFLICT` (409) when any non-`CANCELLED` tour belonging to the same `tenant_rep_id` has a plain, unpadded half-open window intersecting the new one; back-to-back tours that merely touch at an endpoint do not intersect and are allowed.

A requested tour moves `REQUESTED` → `CONFIRMED` when a `LeasingManager` confirms it — allowed only while the tour's site is `LISTED` or `RESERVED`, otherwise `ERR_SITE_NOT_LISTED`. The owning representative then marks the confirmed tour `CONFIRMED` → `COMPLETED`, but only once the logical clock has reached the tour's `end_at`; an earlier attempt fails with `ERR_TOUR_NOT_CONCLUDED` (409), and a completion attempted by anyone other than the owning representative fails ownership with `ERR_FORBIDDEN`. Cancellation moves a `REQUESTED` or `CONFIRMED` tour to `CANCELLED` and is available to the owning representative or to any `LeasingManager`; the system also cancels tours itself, both on requirement withdrawal and when a site is committed to a different requirement. `COMPLETED` and `CANCELLED` are terminal. The tour list supports filtering by `site_id`, `requirement_id`, `tenant_rep_id`, and `status`, and any role may fetch one tour.

### 3.3. LOI Economics and the Negotiation Cycle

With at least one completed tour on the books, a `TenantRep` opens a letter of intent by naming `requirement_id` and `site_id` and stating economics: `term_years` (the lease term in whole years, from 1 to 30), `leased_sf`, `base_rate_psf` (the year-one annual NNN base rent per square foot), `ti_allowance_psf` (a one-time tenant-improvement allowance per square foot), `free_rent_months` (months of abated year-one base rent), `escalation_pct` (the annual escalation expressed as a decimal such as 0.03, first applied in year two), and optionally `commission_basis` (`GROSS_AGGREGATE` or `NET_EFFECTIVE`, defaulting to `GROSS_AGGREGATE` when omitted). Creation is gated by a six-check battery evaluated in this exact order: the site must be `LISTED` (`ERR_SITE_NOT_LISTED`); the site must satisfy all five hard minimums defined in §3.2 (`ERR_HARD_MINIMUMS_NOT_MET`, 422); at least one `COMPLETED` tour must exist for the requirement/site pair (`ERR_NO_COMPLETED_TOUR`, 409); no other LOI for the same pair may be open — that is, in `DRAFT`, `SUBMITTED`, `COUNTERED`, or `ACCEPTED` (`ERR_LOI_ALREADY_OPEN`, 409); `leased_sf` must lie within the requirement's band from `min_sf` to `max_sf`, inclusive at both ends (`ERR_SF_OUT_OF_RANGE`, 422); and the site's `available_sf` must be at least `leased_sf` (`ERR_INSUFFICIENT_SF`, 422). A created LOI starts `DRAFT` with `negotiation_round` at zero, and both derived economics are computed immediately at the stated terms.

The two derived economics follow pinned formulas. `aggregate_rent_total` is the total base rent over the term: year one contributes `base_rate_psf` multiplied by `leased_sf`, and each subsequent year contributes that same year-one amount grown at the annual rate `escalation_pct`, compounding once per elapsed year — year two carries one growth application, year three carries two, and so on through `term_years`. The yearly amounts are summed unrounded, and the sum is rounded half-up exactly once, to cents. `net_effective_rent_psf` nets the two concessions out of that aggregate: the free-rent credit equals `free_rent_months` multiplied by one month of year-one base rent (a month being `base_rate_psf` multiplied by `leased_sf`, divided by twelve), rounded half-up to cents; the improvement credit equals the lesser of `ti_allowance_psf` and a fifty-dollar-per-square-foot cap, multiplied by `leased_sf`, rounded half-up to cents. Both credits are subtracted from `aggregate_rent_total`, and the difference is divided by the product of `term_years` and `leased_sf`, rounded half-up to cents. Both figures recompute whenever the effective terms change.

Negotiation is a cycle between the two desks. The owning representative submits from `DRAFT` (`DRAFT` → `SUBMITTED`) carrying `expected_loi_version` and, optionally, revisions to `base_rate_psf`, `ti_allowance_psf`, `free_rent_months`, `escalation_pct`, `term_years`, or `leased_sf`. The checks fire in precedence order: the representative must own the linked requirement (`ERR_FORBIDDEN`); the LOI must be in the expected state (`ERR_INVALID_STATE`); the version must match (`ERR_STALE_VERSION`, 412); and the effective `free_rent_months` — after applying any revision in the same call — may not exceed twelve (`ERR_FREE_RENT_OVER_CAP`, 422). A successful submission increments `negotiation_round` and `version` by one each and recomputes both derived economics at the effective terms. The `LeasingManager` answers with a counter (`SUBMITTED` → `COUNTERED`), which carries `expected_loi_version` plus a full replacement economics payload of `base_rate_psf`, `ti_allowance_psf`, `free_rent_months`, and `escalation_pct`; those four values replace the standing terms outright, round and version each increment, and the economics recompute at the countered terms. The tenant may then resubmit (`COUNTERED` → `SUBMITTED`) under exactly the same rules as the initial submission, optionally revising terms, and the two sides may trade rounds indefinitely.

Acceptance is the `LeasingManager`'s move from either `SUBMITTED` or `COUNTERED`, and it evaluates four preconditions in order: the transition must be legal from the current state (`ERR_INVALID_STATE`); the LOI's site must still be `LISTED` (`ERR_SITE_NOT_LISTED`); the site's `available_sf` must be at least `leased_sf` (`ERR_INSUFFICIENT_SF`); and the standing `net_effective_rent_psf` must be at least sixty percent of the site's `asking_rate_psf`, the floor computed by multiplying the asking rate by 0.60 and rounding half-up to cents (`ERR_NER_BELOW_FLOOR`, 422). On acceptance the cascade fires: the site moves `LISTED` → `RESERVED` with `leased_sf` added to `reserved_sf` and `available_sf` recomputed — link one — and that site transition rejects every other LOI on the same site sitting in `SUBMITTED` or `COUNTERED`, moving them to `REJECTED` — link two, caused by the site transition rather than the accept call itself.

The unwind paths are equally explicit. A `LeasingManager` rejects a `SUBMITTED` or `COUNTERED` LOI, moving it to terminal `REJECTED`. The owning representative withdraws from `DRAFT`, `SUBMITTED`, or `COUNTERED` into terminal `WITHDRAWN` with no site effect, since nothing is reserved yet. Withdrawing from `ACCEPTED` — the tenant walking away before execution — performs the compensating release: the site moves `RESERVED` → `LISTED` with the LOI's `leased_sf` removed from `reserved_sf`, and every expansion option still `GRANTED` on that LOI moves to `RELEASED`. `EXECUTED`, `REJECTED`, and `WITHDRAWN` are all terminal. The LOI list supports filtering by `requirement_id`, `site_id`, and `status`, and any role may fetch one LOI.

### 3.4. Environmental and Zoning-Use Verification

Compliance work runs on its own track, owned by the `ComplianceOfficer`. Opening a review requires `site_id`, `requirement_id`, a `review_type` of `ENVIRONMENTAL` or `ZONING_USE`, and an optional `findings` narrative. Uniqueness is enforced per triple: a second review with the same `site_id`, `requirement_id`, and `review_type` is rejected with `ERR_DUPLICATE_REVIEW` (409). New reviews begin `PENDING`.

The review lifecycle contains a deliberate remediation loop. Beginning a review moves `PENDING` → `IN_REVIEW`. Resolution takes an `outcome` of `CLEARED` or `FLAGGED`: from `IN_REVIEW`, a `CLEARED` outcome lands in terminal `CLEARED`, while a `FLAGGED` outcome lands in `FLAGGED`; either way, when the resolution payload carries `findings`, the stored narrative is replaced by it. A flagged review is not dead — after remediation the officer may begin it again, `FLAGGED` → `IN_REVIEW`, and resolve it afresh, looping as many times as needed. Review lists filter by `site_id`, `requirement_id`, `review_type`, and `status`, and any role may fetch one review.

Two downstream gates consume these verdicts, and both are stated here so the compliance desk can see the full blast radius of its decisions. Executing an LOI demands two separate `CLEARED` reviews for the LOI's site-and-requirement pair — one `ENVIRONMENTAL` and one `ZONING_USE` — and a missing or non-cleared review on either axis rejects the execution with `ERR_COMPLIANCE_NOT_CLEARED` (409). Exercising an expansion option demands a `CLEARED` `ZONING_USE` review pairing the option's land parcel with the linked LOI's requirement, failing with the same error otherwise.

### 3.5. Lease Execution, Build-to-Suit Pricing, and Delivery

Execution is the `AssetManager`'s signature on an `ACCEPTED` LOI, gated first by state (`ERR_INVALID_STATE`) and then by the twin compliance gates of §3.4 (`ERR_COMPLIANCE_NOT_CLEARED`). A successful execution does five things in one request: the LOI moves `ACCEPTED` → `EXECUTED`; the site moves `RESERVED` → `COMMITTED`, and that commitment cancels every `REQUESTED` or `CONFIRMED` tour at the site serving a different requirement; the requirement moves `ACTIVE` → `SATISFIED`; a build-to-suit plan is auto-created one-to-one with its `loi_id` pointing back to the executed LOI, starting in `SCHEMATIC`; and two commission invoices are auto-created in a fixed order — `TENANT_REP` first, `LANDLORD_REP` second — each starting `ACCRUED` with amounts computed per §3.7 at the LOI's final terms and each carrying `commission_basis` copied from the LOI.

Pricing the plan is the `ProjectManager`'s job, submitted with `hard_cost_total` (the construction budget), `soft_cost_total` (architecture, permits, legal), a `pricing_method` of `YIELD_ON_COST` or `MARKET_COMP`, and optionally `contingency_pct`, which defaults to 0.05. The cost-to-rent conversion breaks the circular dependency between cost, rent, and commission with a pinned two-pass evaluation. In pass one, the base cost is the sum of `hard_cost_total` and `soft_cost_total`, grown by `contingency_pct`; `provisional_base_rate_psf` is that base cost multiplied by the eight-percent target yield and divided by the linked LOI's `leased_sf`, rounded half-up to cents; a provisional aggregate rent is then computed with the aggregate formula of §3.3 at that provisional rate over the LOI's `leased_sf`, `term_years`, and `escalation_pct`; and `commission_cost_estimate` is four percent of the provisional aggregate, rounded half-up to cents. In pass two, `total_project_cost` is the base cost plus `commission_cost_estimate`, and the final rent depends on the variant. Under `YIELD_ON_COST`, `converted_base_rate_psf` is `total_project_cost` multiplied by the eight-percent target yield and divided by `leased_sf`, rounded half-up to cents. Under `MARKET_COMP`, `converted_base_rate_psf` is the greater of the linked site's `asking_rate_psf` and the yield-on-cost rate grown by a five-percent market markup and rounded half-up to cents — identical cost inputs produce a different, and never below-market, rent. Finally, `yield_on_cost` is `converted_base_rate_psf` multiplied by `leased_sf` and divided by `total_project_cost`, rounded half-up to four decimal places. A successful pricing moves the plan `SCHEMATIC` → `PRICED` and writes all five computed fields.

Design iteration is expected: sending a priced plan back to schematic work moves it `PRICED` → `SCHEMATIC`, and the computed pricing fields from the last run are retained until the next pricing overwrites them. Approval is the `AssetManager`'s second signature, allowed from `PRICED` only when `converted_base_rate_psf` is no more than one hundred ten percent of the linked LOI's `base_rate_psf` — the cap computed by multiplying the LOI's base rate by 1.10 and rounding half-up to cents — with an overrun rejected as `ERR_RENT_CONVERSION_OVER_RUN` (422). Approval moves the plan `PRICED` → `APPROVED`, with one shortcut: if every milestone on the plan — and at least one must exist — is already `COMPLETE` at the moment of approval, the plan continues straight through `APPROVED` → `DELIVERED` inside the same request, firing the delivery cascades below.

The delivery schedule is tracked as milestones on the plan. The `ProjectManager` adds one with `plan_id`, a `milestone_type` of `PERMITS`, `SHELL`, `TI`, or `SUBSTANTIAL_COMPLETION`, and a contractual `planned_date`; the plan must be in `SCHEMATIC`, `PRICED`, or `APPROVED`, and each `milestone_type` may appear only once per plan — a wrong plan status or a repeated type is rejected alike with `ERR_DUPLICATE_MILESTONE` (409). Milestones begin `PENDING`. Completing one records the payload's `actual_date` as the milestone's `actual_date` and moves it `PENDING` → `COMPLETE`; completion is accepted while the plan is in `SCHEMATIC`, `PRICED`, or `APPROVED`. When a completion clears the last `PENDING` milestone of an `APPROVED` plan, the plan bubbles up `APPROVED` → `DELIVERED` within the same request.

Delivery settles the schedule against reality. At `DELIVERED`, the linked LOI's `rent_commencement_date` — null until this moment — is set to the `actual_date` of the plan's `SUBSTANTIAL_COMPLETION` milestone, and its `abatement_days` is set to the extra free-rent days owed for late delivery: the whole-day difference between that milestone's `actual_date` and its `planned_date`, reduced by a thirty-day grace and floored at zero. Exactly thirty days late yields zero abatement days; thirty-one days late yields one. The site then moves `COMMITTED` → `LEASED`, and that transition flips `installment_2_due` to true on every commission invoice of the linked LOI — the third and final cascade link. `DELIVERED` is terminal for the plan, and `LEASED` is terminal for the site. Plan lists filter by `loi_id` (at most one plan ever exists per LOI) and `status`; milestone lists filter by `plan_id`, `milestone_type`, and `status`; any role may fetch either resource.

### 3.6. Expansion Options and Land Banking

Deals often carry a growth kicker. A `LeasingManager` grants an expansion option by naming `loi_id`, `land_site_id`, `option_sf`, and the exercise window from `window_open_date` to `window_close_date`. The linked LOI must be `ACCEPTED` or `EXECUTED`; an LOI in any other status fails the state check with `ERR_INVALID_STATE`. The land parcel must be a `LAND_BANK` site — banked land, not a standing building — currently `LISTED` (`ERR_SITE_NOT_LISTED`), with `available_sf` at least `option_sf` (`ERR_INSUFFICIENT_SF`); and `window_close_date` must be strictly after `window_open_date` (`ERR_INVALID_TIME_RANGE`). Both window bounds are inclusive at exercise time. A granted option begins `GRANTED`.

Exercise belongs to the tenant side — the acting `TenantRep` must own the requirement of the linked LOI, failing which `ERR_FORBIDDEN`. The exercise checks fire in precedence order: the option must be `GRANTED` (`ERR_INVALID_STATE`); the land parcel must still be `LISTED` (`ERR_SITE_NOT_LISTED`); the zoning gate of §3.4 must hold for the parcel and the LOI's requirement (`ERR_COMPLIANCE_NOT_CLEARED`); the parcel's `available_sf` must be at least `option_sf` (`ERR_INSUFFICIENT_SF`); the logical clock must have reached `window_open_date` (`ERR_OPTION_WINDOW_NOT_OPEN`, 409); and the clock must not have passed `window_close_date`, which is inclusive — an attempt after the close flips the option itself to `EXPIRED` and the call fails with `ERR_OPTION_WINDOW_EXPIRED` (409). The not-open check is always evaluated before the expiry check. A successful exercise moves the option `GRANTED` → `EXERCISED` and reserves the land: the parcel moves `LISTED` → `RESERVED` with `option_sf` added to its `reserved_sf` and `available_sf` recomputed.

Release is the clean exit: the owning representative moves a `GRANTED` option to `RELEASED`, and the system applies the same transition when the linked `ACCEPTED` LOI is withdrawn before execution. `EXERCISED`, `EXPIRED`, and `RELEASED` are all terminal. Option lists filter by `loi_id`, `land_site_id`, and `status`, and any role may fetch one option.

### 3.7. Broker Commissions and Installment Settlement

Commission amounts are computed exactly once, at execution, from the LOI's final terms, and they never recompute afterward. Each of the two auto-created invoices copies `commission_basis` from the LOI and records the basis it ran over as `commission_basis_amount`: under `GROSS_AGGREGATE` the basis is the LOI's `aggregate_rent_total`, while under `NET_EFFECTIVE` it is `net_effective_rent_psf` multiplied by `term_years` and by `leased_sf`, rounded half-up to cents — identical LOI terms therefore produce a smaller basis, and a smaller commission, under `NET_EFFECTIVE`, because the free-rent and improvement credits reduce it. A tiered schedule runs over the basis: tier one is five percent of the basis up to a five-hundred-thousand-dollar cap, rounded half-up to cents; tier two is three percent of whatever basis exceeds that cap — zero when it does not — rounded half-up to cents; and the combined commission is the sum of the two rounded tiers, tiers always rounded before summing, never after. The tenant-side invoice's `total_commission` is one half of the combined amount, rounded half-up to cents; the landlord-side invoice's `total_commission` is the combined amount minus the tenant side, pinning any half-cent remainder to `LANDLORD_REP`.

Each invoice splits its `total_commission` into two installments with the remainder pinned forward: `installment_1_amount` is one half of `total_commission`, rounded half-up to cents, and falls due at lease execution; `installment_2_amount` is `total_commission` minus `installment_1_amount` and falls due only at rent commencement, an event signaled on the invoice by `installment_2_due`. Both invoices begin `ACCRUED` with `installment_1_paid`, `installment_2_paid`, and `installment_2_due` all false.

Administration sits with the `LeasingManager`. Issuing moves an `ACCRUED` invoice to `INVOICED`. Payments carry `installment_number`: paying installment 1 on an `INVOICED` invoice sets `installment_1_paid` and moves it to `PARTIALLY_PAID`; installment 2 is accepted only from `PARTIALLY_PAID` — attempting it before installment 1 has landed fails the state check with `ERR_INVALID_STATE` — and only once `installment_2_due` is true, otherwise `ERR_INSTALLMENT_NOT_DUE` (409); a successful installment-2 payment sets `installment_2_paid` and moves the invoice to terminal `PAID`. An `INVOICED` invoice may instead be disputed with a `reason`, which is recorded as `dispute_reason` while the invoice sits in `DISPUTED`; re-issuing a disputed invoice returns it `DISPUTED` → `INVOICED`, clears `dispute_reason` to null, and leaves every amount unchanged, so the dispute loop may repeat. Invoice lists filter by `loi_id`, `broker_side`, and `status`, and any role may fetch one invoice.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Calls that create a new resource return 201 Created; every other successful call — single fetches, lists, state transitions, the stateless match evaluation, and the clock operation — returns 200 OK. "All roles" in the table means the five roles enumerated in §2.1. Request bodies, response payloads, and side effects are defined by the workflows of §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | /api/tenant-requirements | Register a tenant requirement (clear height / dock / power / yard / size band) | TenantRep |
| GET | /api/tenant-requirements/{id} | Fetch one requirement | All roles |
| POST | /api/tenant-requirements/{id}/withdraw | Withdraw a requirement; cascades to open LOIs and tours | TenantRep |
| POST | /api/match-evaluations | Stateless site-match scoring for a requirement/site pair; persists nothing | TenantRep, LeasingManager |
| POST | /api/sites | Register a building or land-bank parcel in inventory | LeasingManager |
| GET | /api/sites | Market-survey list with filters and pagination | All roles |
| GET | /api/sites/{id} | Fetch one site | All roles |
| POST | /api/tours | Request a tour window at a site for a requirement | TenantRep |
| GET | /api/tours | List/filter tours | All roles |
| GET | /api/tours/{id} | Fetch one tour | All roles |
| POST | /api/tours/{id}/confirm | Confirm a requested tour | LeasingManager |
| POST | /api/tours/{id}/complete | Mark a confirmed tour completed once its window has passed | TenantRep |
| POST | /api/tours/{id}/cancel | Cancel a requested or confirmed tour | TenantRep, LeasingManager |
| POST | /api/lois | Open an LOI (rate / TI / free rent / escalation) on a toured, qualifying site | TenantRep |
| GET | /api/lois | List/filter LOIs | All roles |
| GET | /api/lois/{id} | Fetch one LOI | All roles |
| POST | /api/lois/{id}/submit | Submit from DRAFT or resubmit after a counter, optionally revising economics | TenantRep |
| POST | /api/lois/{id}/counter | Counter with revised economics | LeasingManager |
| POST | /api/lois/{id}/accept | Accept standing terms; reserves the site and rejects competing LOIs | LeasingManager |
| POST | /api/lois/{id}/reject | Reject a submitted or countered LOI | LeasingManager |
| POST | /api/lois/{id}/withdraw | Withdraw an LOI; from ACCEPTED releases the reservation and GRANTED options | TenantRep |
| POST | /api/lois/{id}/execute | Execute an accepted LOI after environmental and zoning clearance | AssetManager |
| GET | /api/bts-plans | List/filter build-to-suit plans | All roles |
| GET | /api/bts-plans/{id} | Fetch one build-to-suit plan | All roles |
| POST | /api/bts-plans/{id}/price | Run the cost-to-rent conversion under the chosen pricing method | ProjectManager |
| POST | /api/bts-plans/{id}/revise | Send a priced plan back to schematic design | ProjectManager |
| POST | /api/bts-plans/{id}/approve | Approve pricing if the converted rent stays within the overrun cap | AssetManager |
| POST | /api/delivery-milestones | Add a delivery milestone (permits / shell / TI / substantial completion) to a plan | ProjectManager |
| GET | /api/delivery-milestones | List/filter milestones | All roles |
| GET | /api/delivery-milestones/{id} | Fetch one milestone | All roles |
| POST | /api/delivery-milestones/{id}/complete | Complete a milestone with its actual date; may bubble the plan to DELIVERED | ProjectManager |
| POST | /api/expansion-options | Grant an expansion option over a land-bank parcel, riding on an ACCEPTED or EXECUTED LOI | LeasingManager |
| GET | /api/expansion-options | List/filter expansion options | All roles |
| GET | /api/expansion-options/{id} | Fetch one expansion option | All roles |
| POST | /api/expansion-options/{id}/exercise | Exercise the option inside its window after zoning clearance | TenantRep |
| POST | /api/expansion-options/{id}/release | Release a granted option | TenantRep |
| POST | /api/compliance-reviews | Open an environmental or zoning-use verification for a site/requirement pair | ComplianceOfficer |
| GET | /api/compliance-reviews | List/filter compliance reviews | All roles |
| GET | /api/compliance-reviews/{id} | Fetch one compliance review | All roles |
| POST | /api/compliance-reviews/{id}/begin | Begin (or re-begin after FLAGGED) a review | ComplianceOfficer |
| POST | /api/compliance-reviews/{id}/resolve | Clear or flag an in-review compliance review | ComplianceOfficer |
| GET | /api/commission-invoices | List/filter commission invoices | All roles |
| GET | /api/commission-invoices/{id} | Fetch one commission invoice | All roles |
| POST | /api/commission-invoices/{id}/issue | Issue (or re-issue after dispute) an invoice | LeasingManager |
| POST | /api/commission-invoices/{id}/pay | Pay installment 1 (at execution) or installment 2 (after rent commencement) | LeasingManager |
| POST | /api/commission-invoices/{id}/dispute | Dispute an issued invoice | LeasingManager |
| POST | /api/_clock/set_current_utc | Move the logical clock used by tour completion, option windows, and option expiry | AssetManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined with their workflows in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|----------|-----------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SITE_NOT_LISTED | 409 |
| ERR_COMPLIANCE_NOT_CLEARED | 409 |
| ERR_HARD_MINIMUMS_NOT_MET | 422 |
| ERR_NO_COMPLETED_TOUR | 409 |
| ERR_LOI_ALREADY_OPEN | 409 |
| ERR_SF_OUT_OF_RANGE | 422 |
| ERR_INSUFFICIENT_SF | 422 |
| ERR_TOUR_SITE_CONFLICT | 409 |
| ERR_REP_CALENDAR_CONFLICT | 409 |
| ERR_DUPLICATE_MILESTONE | 409 |
| ERR_DUPLICATE_REVIEW | 409 |
| ERR_OPTION_WINDOW_NOT_OPEN | 409 |
| ERR_OPTION_WINDOW_EXPIRED | 409 |
| ERR_TOUR_NOT_CONCLUDED | 409 |
| ERR_INSTALLMENT_NOT_DUE | 409 |
| ERR_FREE_RENT_OVER_CAP | 422 |
| ERR_NER_BELOW_FLOOR | 422 |
| ERR_RENT_CONVERSION_OVER_RUN | 422 |

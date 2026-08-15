# Comic Convention Exhibitor Management API — Product Requirements Document

## 1. Introduction

Behind every successful fan convention sits a year of unglamorous administration: a fixed inventory of booths and artist tables that must be priced, juried, and allocated; returning exhibitors who expect priority treatment for their loyalty; freight that must be marshalled through a handful of dock doors in tight windows; and a sales-tax compliance obligation that follows every transaction on the show floor. When these concerns live in spreadsheets and email threads, the failure modes are familiar — double-promised corner booths, waitlisted artists who never learn a space opened up, dock congestion on load-in morning, and exhibitors who arrive without a verified permit.

This document specifies an API for running a Comic-Con style convention's exhibitor and Artist Alley program end to end. It covers booth and table inventory with demand-tiered pricing, exhibitor applications across renewal and open channels, jury scoring with category quotas, floor placement with neighbor-placement requests, badge allocation for exhibitor staff, load-in and load-out freight scheduling, on-site policy enforcement built on a strike-point standing system, cancellation refunds, and sales-tax estimation and settlement. Four kinds of operators use the system — the show director, on-site operations staff, jury members, and the exhibitors themselves — each seeing exactly the slice of the program their role requires.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes five roles: `ShowDirector`, `OperationsStaff`, `JuryMember`, `Exhibitor`, and `Anonymous`. A request missing either header, or carrying a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is not on the target operation's role list is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting Exhibitor — the identifier returned by exhibitor self-registration. Ownership checks on any resource that references an Exhibitor compare the resource's foreign-key field to `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`.
- When `X-User-Role` is `ShowDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reporter_user_id` on an issue ticket the director files) but does not compare it to any entity's `id`.
- When `X-User-Role` is `OperationsStaff`, `X-User-ID` is likewise an opaque operator identifier; it is recorded as `reporter_user_id` on issue tickets the staff member reports and is never compared to any entity's `id`.
- When `X-User-Role` is `JuryMember`, `X-User-ID` is an opaque juror identifier recorded as `juror_user_id` on each score the juror posts; it is matched against an application's barred-juror list and against that juror's prior scores, but never against an entity's `id`.
- When `X-User-Role` is `Anonymous`, the caller is unregistered; the only operation open to this role is exhibitor self-registration.

The `Exhibitor` role acts exclusively on its own resources: its own applications, staff records, freight bookings, sales reports, neighbor requests, and its own exhibitor record. List endpoints enforce this scoping themselves — an exhibitor listing applications is coerced to its own `exhibitor_id` filter, neighbor-request listings show only requests where the exhibitor is requester or target, staff, freight, and sales listings return only the exhibitor's own records, and reading an exhibitor record other than one's own is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order; resources that share the same creation timestamp are ordered by their `id` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, including mutations performed as steps of a system-driven cascade.

Two resources are immutable after creation and carry only `id` and `created_at`: the JuryScore and the DockDoor. Both `updated_at` and `version` are absent on those two resources, and no operation modifies them once created.

### 2.5. The Logical Clock

All time-dependent behavior in the system — submission windows, offer expiry, freight windows, phase gates, and every operations sweep — reads a single logical clock rather than the wall clock. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z: a fixed startup default, never the current wall-clock time. A director-only, test-driving capability sets the clock to a supplied `to_iso8601` instant; any ISO 8601 UTC instant is accepted, with no monotonicity constraint, and the response reports the resulting `current_utc`. Wherever this document says "the current time" or "the clock", it means this logical clock.

### 2.6. Money, Scores, and Rounding

All monetary amounts are represented as integer cents; floating-point money never appears in requests, responses, or storage. The convention's tax rate is carried in basis points as `sales_tax_rate_bp` — a value of 875 means an 8.75 percent rate. Wherever a computation produces a fractional cent or a fractional score, the system rounds half up, and the exact points where rounding occurs are pinned per calculation in Section 3: each per-space price, the combined invoice total, the deposit, each juror's `weighted_total`, the per-day tax estimate, each sales line's tax, and the cancellation refund are the only rounding points in the system. Jury-derived numbers — `weighted_total` and `jury_composite_score` — are the only non-integer values the API exposes, and both always carry exactly two decimal places, rounded half up.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control. Revising an application requires the request to carry `expected_application_version`, holding the application `version` the client last observed; if the application's current `version` has since advanced — because an earlier accepted write already bumped it — the revision is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), since the client's edits were authored against a stale snapshot and the newer revision supersedes them. Updating a convention's configuration likewise requires `expected_convention_version`; a mismatch with the convention's current `version` is rejected with `ERR_STALE_CONVENTION_VERSION` (HTTP 412), preventing the request from silently overwriting configuration the client never saw. No other endpoint accepts a version field.

### 2.8. Validation Priority Order

A single request can fail several checks at once. Which rejection it receives is decided by a fixed priority order; the priority position, not the numeric HTTP status, decides which error surfaces when several checks fail. From first to last:

1. Authentication — the headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED`.
2. Role authorization — the caller's role appears in the endpoint's role list; otherwise `ERR_FORBIDDEN_ROLE`.
3. Existence — every identifier in the path, validated left to right, and every foreign-key field in the body must resolve to an existing resource; otherwise `ERR_NOT_FOUND`.
4. Ownership scope — exhibitor requests must target their own resources; otherwise `ERR_FORBIDDEN_OWNERSHIP`.
5. State preconditions — the target resource must be in a from-state that permits the requested transition (`ERR_INVALID_TRANSITION`), and the OCC version fields must match the current versions (`ERR_STALE_APPLICATION_VERSION`, `ERR_STALE_CONVENTION_VERSION`).
6. Temporal gates — submission and renewal windows, the offer-expiry window, freight phase gating, the freight check-in slot window, sales-report phase gating, and the advance-phase clock gates: `ERR_APPLICATION_WINDOW_CLOSED`, `ERR_OFFER_EXPIRED`, `ERR_FREIGHT_WRONG_PHASE`, `ERR_INVALID_TIME_WINDOW`, `ERR_PHASE_PRECONDITION`.
7. Compliance and duty gates — juror conflict of interest, resolver-versus-reporter segregation, exhibitor standing, permit verification, the badge compliance hold, and exemption eligibility: `ERR_JURY_CONFLICT_OF_INTEREST`, `ERR_DUTY_SEGREGATION`, `ERR_EXHIBITOR_SUSPENDED`, `ERR_PERMIT_NOT_VERIFIED`, `ERR_COMPLIANCE_HOLD`, `ERR_EXEMPTION_NOT_ALLOWED`.
8. Referential integrity — an application's category matches its exhibitor's category, the category is offered in the convention, the neighbor target holds a live application, staff registration is permitted, and freight or sales activity targets a placed application: `ERR_CATEGORY_MISMATCH`, `ERR_CATEGORY_NOT_OFFERED`, `ERR_NEIGHBOR_TARGET_NOT_APPLIED`, `ERR_NEIGHBOR_SELF_TARGET`, `ERR_APPLICATION_NOT_PLACED`, `ERR_STAFF_NOT_ALLOWED_YET`.
9. Constraint satisfaction — uniqueness rules, the category-zone map, kind matching, jury quorum and score thresholds, quota caps, the quota-floor adjustment rule, the extra-badge cap, dock-door window containment and overlap, and empty sales lines: `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_JURY_SCORE`, `ERR_DUPLICATE_NEIGHBOR_REQUEST`, `ERR_DUPLICATE_SPACE_CODE`, `ERR_CATEGORY_ZONE_VIOLATION`, `ERR_SPACE_KIND_MISMATCH`, `ERR_JURY_QUORUM_NOT_MET`, `ERR_SCORE_BELOW_THRESHOLD`, `ERR_CATEGORY_QUOTA_FULL`, `ERR_WAITLIST_FULL`, `ERR_QUOTA_BELOW_ACCEPTED`, `ERR_BADGE_EXTRA_LIMIT`, `ERR_DOOR_WINDOW_OUTSIDE_SLOT`, `ERR_DOOR_WINDOW_CONFLICT`, `ERR_SALES_REPORT_EMPTY`.
10. Money and capacity last — the deposit exact match, the remaining badge allocation, load-slot pallet capacity, and space availability: `ERR_DEPOSIT_MISMATCH`, `ERR_BADGE_ALLOCATION_EXHAUSTED`, `ERR_SLOT_CAPACITY_EXCEEDED`, `ERR_SPACE_NOT_AVAILABLE`.

Independent of this ordering, a body that is malformed — a missing required field, a wrong-typed value, an unknown enum value, or an integer outside its declared range, such as a `requested_space_count` or `pallet_count` below one, or a jury criterion outside zero to one hundred — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Derived Counters and Cascading Consistency

The system is immediately consistent: every mutation commits atomically within its request, and every derived number is recomputed synchronously rather than by a background job. Counters such as a quota's `accepted_count` and `waitlisted_count`, a load slot's `reserved_pallets`, and an application's `included_badges`, `balance_due_cents`, and `jury_composite_score` are maintained by the same operations that move their inputs. An exhibitor's `standing` is not an independently stored fact; it is derived from `strike_points` and recomputed after every guilty resolution, and a single resolution can move an exhibitor across several bands at once. Whenever any operation — client-driven or system-driven — touches a resource, that resource's `updated_at` refreshes and its `version` increments, including every step of a cascade. Cascades are the norm at the end of an exhibitor's participation: declining an offer, cancelling, offer expiry, and eviction each release placements, free spaces, revoke badges, cancel freight bookings, decrement quota counters, moot neighbor requests, and fire the waitlist promotion sweep, as detailed in Section 3.

## 3. Business Logic & Workflows

### 3.1. Laying Out the Show: Conventions, Quotas, and Floor Inventory

Every program begins with a `ShowDirector` creating the Convention. The creation payload carries the show's display `name`, the instants the show opens and closes (`starts_at` and `ends_at`, both UTC — the first selling day is the calendar date of `starts_at`), the application timeline (`renewal_open_at`, `application_open_at`, and `application_close_at`), the `early_bird_deadline`, whether sales-tax permits are required (`tax_permit_required`), and the tax rate (`sales_tax_rate_bp`). Two collections travel with the same payload: `category_quotas`, each entry naming a `category` with its `max_accepted` and `max_waitlisted` caps, and `dock_doors`, each entry naming a `door_code`. Creating the convention cascade-creates one CategoryQuota per `category_quotas` entry and one DockDoor per `dock_doors` entry, and each door's `door_code` must be unique within the convention. The optional `deposit_window_days` sets how many days an accepted exhibitor has to accept its offer and defaults to 14 when omitted. A new convention's `phase` opens at `SETUP`, with an `ops_run_count` of zero.

Each category — one of `ARTIST_ALLEY`, `DEALER`, `PUBLISHER`, `STUDIO`, or `NONPROFIT`, unique within a convention — is governed by its quota row. The quota's `accepted_count` tracks how many applications of that convention and category currently hold `JURIED_ACCEPTED`, `CONTRACTED`, or `PLACED` status, and its `waitlisted_count` tracks those holding `JURIED_WAITLISTED`; both start at zero and move with jury decisions, promotions, withdrawals, cancellations, and evictions. The director may later adjust a quota's `max_accepted` or `max_waitlisted`, but lowering `max_accepted` below the live `accepted_count` is rejected with `ERR_QUOTA_BELOW_ACCEPTED`.

Floor inventory is then built unit by unit. Each SpaceUnit is created with its `convention_id`, a human-readable `space_code` unique within the convention (a duplicate code is rejected with `ERR_DUPLICATE_SPACE_CODE`), a `block` letter, a numeric `unit_number` giving its position within the block, a `hall` (`MAIN`, `ARTIST_ALLEY_HALL`, or `SMALL_PRESS`), a physical `kind` (`BOOTH_10X10`, `BOOTH_10X20`, `CORNER_BOOTH`, `ENDCAP`, `FEATURED_ISLAND`, `ARTIST_TABLE`, or `NONPROFIT_TABLE`), and its tier-one `base_price_cents`. New units start `AVAILABLE`. Adjacency is a geometric fact of the floor plan: two spaces are adjacent exactly when they share the same `block` and their `unit_number` values differ by exactly one. Each unit also carries a system-maintained `current_application_id` pointing at the application currently holding it — null while the unit is `AVAILABLE`.

Convention configuration may be revised while the show takes shape. Such updates are OCC-guarded per §2.7 and may touch any of `name`, the timeline instants, `early_bird_deadline`, `deposit_window_days`, `tax_permit_required`, and `sales_tax_rate_bp`; a successful update bumps the convention's `version`. Quotas and dock doors, once cascade-created, are listed and read through their own collection endpoints, and quotas may be filtered by `convention_id` or `category`, space units by `convention_id`, `status`, `kind`, or `hall`, and dock doors by `convention_id` or `door_code`.

The convention moves through eight phases in a fixed march — `SETUP` → `APPLICATIONS_OPEN` → `JURY_REVIEW` → `PLACEMENT` → `LOGISTICS` → `LIVE` → `LOAD_OUT` → `CLOSED` — and the director advances it exactly one step per call; `CLOSED` is terminal. Each step has its own gate, and a failed gate is rejected with `ERR_PHASE_PRECONDITION`:

- `SETUP` → `APPLICATIONS_OPEN` requires at least one CategoryQuota and at least one SpaceUnit to exist for the convention.
- `APPLICATIONS_OPEN` → `JURY_REVIEW` requires the clock to be at or after `application_close_at`.
- `JURY_REVIEW` → `PLACEMENT` requires that no application of the convention remains in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_REVISION`.
- `PLACEMENT` → `LOGISTICS` requires that no placement of the convention remains `TENTATIVE`.
- `LOGISTICS` → `LIVE` requires the clock to be at or after `starts_at`.
- `LIVE` → `LOAD_OUT` requires the clock to be at or after `ends_at`.
- `LOAD_OUT` → `CLOSED` requires that no freight booking of the convention remains in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`, and that no issue ticket remains `OPEN`, `TRIAGED`, or `ESCALATED`.

Every successful advance increments the convention's `version`. Separately from phase advancement, the director can fire an operations checkpoint that runs four maintenance sweeps in a fixed order — offer expiry first, then permit expiry, then freight, then load slots — and increments `ops_run_count` by one. The rules of each sweep live with their workflows below (§3.5 and §3.8).

### 3.2. Exhibitors: Registration, Standing, and Renewal Priority

Exhibitors self-register; registration is the system's only unauthenticated operation. A registrant supplies a `legal_name`, a primary selling `category` drawn from the same five-value enumeration the quotas use, and optionally `prior_years_completed` and `prior_on_time_payments`, both defaulting to zero. The new exhibitor starts with `strike_points` at zero and `standing` at `GOOD`, and its `renewal_priority_score` is computed immediately. The returned `id` becomes that exhibitor's `X-User-ID` for every later call, and an exhibitor may read only its own record.

The `renewal_priority_score` rewards tenure and reliability: ten points for each completed prior year, plus three points for each prior on-time payment, minus eight points for each strike point, with the result floored at zero when the arithmetic would go negative. It is recomputed on every change to `strike_points`, and the waitlist promotion sweep uses it as a tie-break (§3.4).

Standing derives from strike points in bands that are inclusive at their lower edge: fewer than three points is `GOOD`; at least three but fewer than five is `PROBATION`; at least five but fewer than seven is `SUSPENDED`; seven or more is `EVICTED`. Because points arrive one to three at a time, a resolution can skip bands — an exhibitor sitting at two points who is assigned four more lands directly in `SUSPENDED`. Entering `EVICTED` fires the eviction cascade described in §3.9. Renewal-channel eligibility, exercised at application submission (§3.3), requires at least one completed prior year and `GOOD` standing.

### 3.3. Applying for Space: Channels, Windows, and the Revision Loop

An exhibitor begins by drafting an Application with a `convention_id`, a `category`, a `channel`, the `requested_space_kinds` it will accept, a `requested_space_count`, its `estimated_daily_sales_cents`, and an optional `conflicted_juror_user_ids` list defaulting to empty. The application's `category` must equal the exhibitor's registered category (`ERR_CATEGORY_MISMATCH`), the requested-kinds list must be non-empty, and the requested count must be at least one. The draft's `exhibitor_id` is set from the caller's `X-User-ID`. New drafts hold status `DRAFT`, and their `permit_status` opens at `PENDING` when the convention requires permits and `NOT_REQUIRED` otherwise. While an application is in `DRAFT` — or later in `NEEDS_REVISION` — the exhibitor may revise its `requested_space_kinds`, `requested_space_count`, `estimated_daily_sales_cents`, `conflicted_juror_user_ids`, and `channel`; revisions are OCC-guarded per §2.7, and a stale `expected_application_version` is rejected with `ERR_STALE_APPLICATION_VERSION`. The `provisional_quote_cents` and `tax_estimate_cents` remain null while the application is a draft.

Submitting moves `DRAFT` → `SUBMITTED` and is possible only while the convention is in `APPLICATIONS_OPEN` (`ERR_INVALID_TRANSITION` otherwise). The submission window depends on the `channel`. A `RENEWAL` submission is accepted from `renewal_open_at` until strictly before `application_close_at`, and only from exhibitors with at least one completed prior year and `GOOD` standing (`ERR_RENEWAL_NOT_ELIGIBLE`); an `OPEN` submission is accepted from `application_open_at` until strictly before `application_close_at`. Submitting outside the applicable window — including at or after `application_close_at` — is rejected with `ERR_APPLICATION_WINDOW_CLOSED`. Two further gates apply to every submission: a CategoryQuota row must exist for the convention and the requested category (`ERR_CATEGORY_NOT_OFFERED`), and the exhibitor must not already hold another application in the same convention in a live status — anything other than `WITHDRAWN`, `JURIED_REJECTED`, `DECLINED`, or `CANCELLED` (`ERR_DUPLICATE_APPLICATION`).

A successful submission stamps `submitted_at` with the current clock, computes the `provisional_quote_cents` and the `tax_estimate_cents`, and increments the application's `version`. The provisional quote prices the request hypothetically: each of the `requested_space_count` spaces is priced at the cheapest `AVAILABLE` unit among the requested kinds — the lowest `base_price_cents` per requested kind — and any requested kind with no `AVAILABLE` unit at all is priced at that kind's floor: 95,000 cents for `BOOTH_10X10`, 175,000 for `BOOTH_10X20`, 140,000 for `CORNER_BOOTH`, 160,000 for `ENDCAP`, 400,000 for `FEATURED_ISLAND`, 27,500 for `ARTIST_TABLE`, and 15,000 for `NONPROFIT_TABLE`. The demand-tier multiplier comes from the sold count at submit time.

Both the provisional quote and the later final invoice share one pricing ladder. At pricing time the system counts the convention's sold spaces — units in `RESERVED` or `ASSIGNED` status. Fewer than twenty sold spaces keeps pricing in tier one, where each space prices at its `base_price_cents`; at least twenty but fewer than forty-five sold spaces moves pricing to tier two, multiplying each base price by 1.20; forty-five or more moves it to tier three, multiplying by 1.45. Each per-space price is rounded half-up to a whole cent, and the rounded prices sum to a pre-discount subtotal. A multi-space discount reads off that pre-discount subtotal — never off the discounted value: a subtotal of at least 300,000 cents earns ten percent off; at least 150,000 cents but below 300,000 earns five percent; anything lower earns none. When the application's `submitted_at` falls on or before the convention's `early_bird_deadline`, a further ten percent early-bird deduction applies. The total is the subtotal reduced by the discount percentage and the early-bird percentage combined, with a single round-half-up to the nearest cent after both deductions are combined.

The tax estimate is forward-looking guidance for the exhibitor. The show's selling days are counted inclusively from the calendar date of `starts_at` through the calendar date of `ends_at`. The per-day tax is the application's `estimated_daily_sales_cents` multiplied by `sales_tax_rate_bp` and divided by ten thousand, rounded half-up to the nearest cent; the `tax_estimate_cents` is that rounded per-day figure multiplied by the number of selling days. Rounding per day before multiplying is pinned, so the estimate can disagree with the per-line settlement computed after the show (§3.9).

The jury may send an application back for changes: a director's revision request moves `UNDER_REVIEW` → `NEEDS_REVISION`, and resubmission returns `NEEDS_REVISION` → `SUBMITTED`. Resubmission is allowed in two phases — during `APPLICATIONS_OPEN` every draft-submission check applies, and `ERR_APPLICATION_WINDOW_CLOSED` can only surface in this phase; during `JURY_REVIEW` the window checks are waived while the quota and duplicate checks still apply. Resubmission restamps `submitted_at` and recomputes the provisional quote and tax estimate, and the `UNDER_REVIEW` → `NEEDS_REVISION` → `SUBMITTED` loop may repeat without bound.

Withdrawal is the exhibitor's exit from any pre-contract state: from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_REVISION`, or `JURIED_WAITLISTED` the application moves to `WITHDRAWN`, and every `PENDING` neighbor request involving that exhibitor becomes `MOOT`. Withdrawing from `JURIED_WAITLISTED` additionally decrements the category quota's `waitlisted_count`. `WITHDRAWN` is terminal.

### 3.4. The Jury: Scoring, Quorum, and the Director's Decision

Scoring opens only while the convention is in `JURY_REVIEW` (`ERR_PHASE_PRECONDITION`), and only against applications in `SUBMITTED` or `UNDER_REVIEW` (`ERR_INVALID_TRANSITION`). A `JuryMember` posts a score by naming the `application_id` and four criteria — `originality`, `craft`, `category_fit`, and `professionalism` — each an integer from 0 to 100 inclusive (anything outside that range is `ERR_INVALID_REQUEST`). The posting juror's `X-User-ID` is recorded as the score's `juror_user_id`. Two guards protect the panel's integrity: a juror whose identifier appears in the application's `conflicted_juror_user_ids` may not score it (`ERR_JURY_CONFLICT_OF_INTEREST`), and a juror who has already scored the application may not score it again (`ERR_DUPLICATE_JURY_SCORE`). Scores are immutable once created, and they may be listed filtered by `application_id` or `juror_user_id`.

The very first score posted for an application moves it automatically from `SUBMITTED` to `UNDER_REVIEW`. Each score's `weighted_total` is 35 percent of `originality` plus 25 percent of `craft` plus 25 percent of `category_fit` plus 15 percent of `professionalism`, rounded half-up to two decimal places. The application's `jury_composite_score` is the mean of the `weighted_total` values across its distinct-juror scores, itself rounded half-up to two decimal places — the per-juror rounding happens before the mean is taken — and it stays null until the first score exists.

Decisions belong to the `ShowDirector` and are taken from `UNDER_REVIEW` by supplying a `decision` of `ACCEPTED`, `WAITLISTED`, or `REJECTED`. Every decision first requires a quorum: at least three scores from distinct `juror_user_id` values must exist, or the attempt is rejected with `ERR_JURY_QUORUM_NOT_MET`. Beyond quorum, the score bands and quota caps gate the outcome. An acceptance requires a `jury_composite_score` of at least 70.00 (`ERR_SCORE_BELOW_THRESHOLD`) and room in the category — the quota's `accepted_count` still below `max_accepted` (`ERR_CATEGORY_QUOTA_FULL`). A waitlisting requires a composite of at least 50.00 (`ERR_SCORE_BELOW_THRESHOLD`) and the quota's `waitlisted_count` below `max_waitlisted` (`ERR_WAITLIST_FULL`). A rejection carries no score floor. In band terms: at 70.00 or above, acceptance is permitted; at least 50.00 but below 70.00, only waitlisting or rejection remain; below 50.00, only rejection is possible.

A decision stamps `decided_at` with the current clock. Acceptance moves the application to `JURIED_ACCEPTED` and increments the quota's `accepted_count`; waitlisting moves it to `JURIED_WAITLISTED` and increments `waitlisted_count`. Rejection moves it to the terminal `JURIED_REJECTED` and additionally turns every `PENDING` neighbor request in which this application's exhibitor is requester or target to `MOOT`.

The waitlist is not a dead end. Whenever a category's `accepted_count` decreases — an exhibitor declines, cancels, lets its offer expire, or is evicted — and the count is then below `max_accepted`, a promotion sweep fires for that convention and category. The sweep considers the category's `JURIED_WAITLISTED` applications, ordered by `jury_composite_score` descending, then by the exhibitor's `renewal_priority_score` descending, then by the application's `created_at` ascending, and promotes exactly one to `JURIED_ACCEPTED`, restamping its `decided_at` and shifting the counters: `waitlisted_count` down by one, `accepted_count` up by one. When no waitlisted candidate exists, the sweep is a silent no-op.

### 3.5. Permits, Deposits, and the Path to Contract

An application's `permit_status` is a second, parallel dimension that evolves independently of its jury status. Exhibitors of a permit-requiring convention submit their state sales-tax permit by supplying a `permit_number` and a `permit_expires_at`, moving `PENDING` → `SUBMITTED`; a permit the director has rejected may be resubmitted the same way, so `SUBMITTED` → `REJECTED` → `SUBMITTED` may repeat. The director verifies a submitted permit (`SUBMITTED` → `VERIFIED`) or rejects it (`SUBMITTED` → `REJECTED`). An exhibitor whose category is `NONPROFIT` may instead claim exemption, moving `PENDING` → `EXEMPT`; any other category is rejected with `ERR_EXEMPTION_NOT_ALLOWED`. Permits can also go stale: the run-ops permit sweep moves a `VERIFIED` permit whose `permit_expires_at` lies before the current clock to `EXPIRED`.

An offer is accepted from `JURIED_ACCEPTED`, and acceptance is a gated financial act. The exhibitor must act within the deposit window — the clock must be on or before `decided_at` plus `deposit_window_days` days, or the attempt is rejected with `ERR_OFFER_EXPIRED`. The exhibitor's `standing` must be `GOOD` or `PROBATION` (`ERR_EXHIBITOR_SUSPENDED`). When the convention's `tax_permit_required` is true, the `permit_status` must be `VERIFIED` or `EXEMPT` (`ERR_PERMIT_NOT_VERIFIED`). At least one `TENTATIVE` placement must already exist for the application (`ERR_INVALID_TRANSITION`). Consistent with the global validation order, a request failing several of these surfaces the out-of-state rejection before the window check, the window check before the standing and permit gates, and the deposit comparison last of all.

Acceptance computes the final invoice. The final variant of the pricing ladder (§3.3) runs over the spaces actually held for the application — the convention's `RESERVED` units whose `current_application_id` is this application — with the space count taken from those units and the demand-tier multiplier read from the sold count at accept time; identical application inputs can therefore price differently from the provisional quote. The `deposit_cents` is one quarter of the `final_invoice_cents`, rounded half-up to the nearest cent, and the request's `deposit_cents` must equal that computed figure exactly (`ERR_DEPOSIT_MISMATCH`). On success the application becomes `CONTRACTED`: the invoice and deposit are persisted, `amount_paid_cents` is set to the deposit, and `balance_due_cents` opens at the invoice minus the amount paid plus any `badge_fees_cents` (zero at this point, since badge extras only become purchasable after placement).

An exhibitor may instead decline the offer: `JURIED_ACCEPTED` → `DECLINED`, terminal. Declining decrements the quota's `accepted_count` and then fires the promotion sweep for the category, releases every `TENTATIVE` placement of the application with its spaces returning `RESERVED` → `AVAILABLE`, and turns every `PENDING` neighbor request involving the exhibitor to `MOOT`. Offers also die of old age: the run-ops offer sweep declines any `JURIED_ACCEPTED` application whose `decided_at` plus `deposit_window_days` days lies strictly before the current clock, recording `OFFER_EXPIRED` as the reason in a system note and running the same release-and-promotion cascade.

### 3.6. Floor Placement and Neighbor Relations

With an accepted (or contracted) application in hand, the `ShowDirector` offers concrete spaces by creating placements naming an `application_id` and a `space_unit_id`. The target application must be `JURIED_ACCEPTED` or `CONTRACTED`. The offered unit must be `AVAILABLE` (`ERR_SPACE_NOT_AVAILABLE`), its `kind` must appear among the application's `requested_space_kinds` (`ERR_SPACE_KIND_MISMATCH`), and the combination of the application's `category`, the unit's `kind`, and the unit's `hall` must satisfy the convention's category-zone map — each category is confined to defined zones of the floor, and an out-of-zone offer is rejected with `ERR_CATEGORY_ZONE_VIOLATION`. A successful offer creates the placement `TENTATIVE` and moves the unit `AVAILABLE` → `RESERVED` with its `current_application_id` set to the application. Placements may be listed filtered by `application_id`, `space_unit_id`, or `status`.

Confirming a placement is the moment a space becomes real. The director confirms a `TENTATIVE` placement only while the convention is in `PLACEMENT` (`ERR_PHASE_PRECONDITION`) and the application is `CONTRACTED` or `PLACED` (`ERR_INVALID_TRANSITION`; `PLACED` is allowed so a multi-space exhibitor can confirm its remaining spaces one by one). Confirmation moves the placement `TENTATIVE` → `CONFIRMED`, the unit `RESERVED` → `ASSIGNED`, and the application `CONTRACTED` → `PLACED` — an already `PLACED` application stays `PLACED`. The application's `included_badges` is then recomputed over all of its `ASSIGNED` spaces (§3.7), its `balance_due_cents` is recomputed, and the neighbor-request evaluation sweep runs for the convention. A `TENTATIVE` placement may instead be released, returning the placement to `RELEASED` and the unit to `AVAILABLE`; releases also happen automatically when the holding application is declined, expired, cancelled, or evicted, and a `CONFIRMED` placement is released the same way when its application is cancelled or evicted, returning its `ASSIGNED` unit to `AVAILABLE` and clearing `current_application_id`.

Exhibitors express seating preferences through neighbor requests. An exhibitor creates one with a `convention_id`, a `target_exhibitor_id`, and a `kind` of `ADJACENT_TO` or `AWAY_FROM`; the `requester_exhibitor_id` is set from the caller's `X-User-ID`. Targeting oneself is rejected with `ERR_NEIGHBOR_SELF_TARGET`; the target — like the requester — must hold a live application in the convention (`ERR_NEIGHBOR_TARGET_NOT_APPLIED`); and a duplicate `PENDING` request for the same requester, target, and kind is rejected with `ERR_DUPLICATE_NEIGHBOR_REQUEST`. New requests are `PENDING`, and the requester may withdraw one (`PENDING` → `WITHDRAWN`); anyone else attempting the withdrawal is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

Requests are adjudicated by geography, not negotiation. During each placement-confirm sweep, a `PENDING` request is evaluated once both the requester and the target hold at least one `CONFIRMED` placement in the convention after that confirm. An `ADJACENT_TO` request is `HONORED` when at least one requester space is adjacent to at least one target space — same `block`, `unit_number` differing by exactly one — and an `AWAY_FROM` request is `HONORED` when no requester space is adjacent to any target space. When both parties hold confirmed placements but the kind's predicate is false, the request is `DECLINED`. And whenever either party's application reaches `WITHDRAWN`, `JURIED_REJECTED`, `DECLINED`, or `CANCELLED`, every still-`PENDING` request between them becomes `MOOT`. `HONORED`, `DECLINED`, `WITHDRAWN`, and `MOOT` are all terminal. Listings can be filtered by `convention_id`, `requester_exhibitor_id`, `target_exhibitor_id`, or `status`, with exhibitor visibility scoped per §2.1.

### 3.7. Staff Badges and On-Site Allocation

Once contracted, an exhibitor registers the people who will staff its space: each staff record carries the `convention_id`, the staffer's `full_name` for the badge, and an optional duty `role_label` such as cashier or artist, with the `exhibitor_id` set from the caller's `X-User-ID`. Registration requires the exhibitor's application in that convention to be `CONTRACTED` or `PLACED` (`ERR_STAFF_NOT_ALLOWED_YET`), and each new staff member starts with `badge_status` `NONE`. Staff listings filter by `exhibitor_id`, `convention_id`, or `badge_status`.

Badge entitlement follows the space. Each `ASSIGNED` unit contributes a per-kind allotment — four badges for a `BOOTH_10X10`, six for a `BOOTH_10X20`, six for a `CORNER_BOOTH`, eight for an `ENDCAP`, twelve for a `FEATURED_ISLAND`, two for an `ARTIST_TABLE`, and two for a `NONPROFIT_TABLE` — and the application's `included_badges` is the sum of those allotments over its `ASSIGNED` units, recomputed at every placement confirmation. `RESERVED` units contribute nothing. Beyond the included allotment, a `PLACED` exhibitor may purchase extra badges by specifying a `quantity`; the purchase is capped so that `purchased_extra_badges` plus the requested quantity may not exceed `included_badges` (`ERR_BADGE_EXTRA_LIMIT`). Each extra badge costs 7,500 cents, added to `badge_fees_cents`, and the `balance_due_cents` is recomputed to include the new fees.

Issuing a badge moves a staff member `NONE` → `ISSUED` and may be performed by the exhibitor or by `OperationsStaff`. Issuance is double-gated, compliance first and allocation second. The compliance gate requires the exhibitor's `standing` to be neither `SUSPENDED` nor `EVICTED` and no unresolved `CRITICAL` issue — one in `OPEN`, `TRIAGED`, or `ESCALATED` — to exist for that exhibitor in that convention (`ERR_COMPLIANCE_HOLD`). The allocation gate requires the number of currently `ISSUED` badges for the exhibitor in the convention to be below `included_badges` plus `purchased_extra_badges` (`ERR_BADGE_ALLOCATION_EXHAUSTED`). Issuance additionally requires the exhibitor's application to be `PLACED` (`ERR_INVALID_TRANSITION`) and the convention to be in `LOGISTICS` or `LIVE` (`ERR_PHASE_PRECONDITION`).

Revoking a badge moves `ISSUED` → `REVOKED` and is available to `OperationsStaff` and the `ShowDirector`; revocation frees one unit of allocation, dropping the derived issued count by one. Badges are also revoked automatically — without any desk action — when the exhibitor's application is cancelled or the exhibitor is evicted (§3.9).

### 3.8. Freight: Marshalling Windows, Dock Doors, and Bookings

Load-in and load-out run through marshalling windows. The director creates each load slot with its `convention_id`, a `direction` of `INBOUND` or `OUTBOUND`, a `starts_at` opening the window inclusively, an `ends_at` closing it exclusively — the end must be strictly after the start (`ERR_INVALID_TIME_WINDOW`) — and a `pallet_capacity` bounding the aggregate pallets the window can absorb. A slot opens `OPEN` with `reserved_pallets` at zero; slots list with `convention_id`, `direction`, or `status` filters. The `reserved_pallets` counter sums the `pallet_count` of the slot's bookings in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status only. When a booking pushes the counter to exactly `pallet_capacity` the slot turns `FULL`; when a cancellation or completion later drops it below capacity the slot returns to `OPEN`; and the run-ops slot sweep moves any `OPEN` or `FULL` slot whose `ends_at` has passed to `CLOSED`, which is terminal.

An exhibitor books freight by naming an `application_id`, a `load_slot_id`, a `dock_door_id`, a door occupation window (`door_starts_at` and `door_ends_at`), and a `pallet_count` of at least one; the booking's `exhibitor_id` is denormalized from the application for ownership checks. Creation is gated in the global validation order. The slot must be `OPEN` (`ERR_INVALID_TRANSITION`) before any clock reasoning happens. The phase gate follows: `INBOUND` slots accept bookings only during `LOGISTICS`, `OUTBOUND` slots only during `LOAD_OUT` (`ERR_FREIGHT_WRONG_PHASE`). The application must be `PLACED` (`ERR_APPLICATION_NOT_PLACED`). The door window must lie inside the slot window — `door_starts_at` no earlier than the slot's `starts_at` and `door_ends_at` no later than the slot's `ends_at` (`ERR_DOOR_WINDOW_OUTSIDE_SLOT`) — and must not collide with another active booking of the same door under the buffer rule. Only then is capacity checked: the slot's `reserved_pallets` plus the new `pallet_count` may not exceed `pallet_capacity` (`ERR_SLOT_CAPACITY_EXCEEDED`).

The buffer rule keeps dock doors turning over cleanly. Every active booking — one in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` — occupies its door for a half-open interval padded by fifteen minutes on both sides. A new window conflicts with an existing booking of the same door whenever the new `door_starts_at` falls before the existing window's end plus fifteen minutes and the existing window's start falls before the new `door_ends_at` plus fifteen minutes; a conflict is rejected with `ERR_DOOR_WINDOW_CONFLICT`. Because the inequality is strict, a new window beginning exactly at the existing window's end plus fifteen minutes is accepted.

Bookings have their own small lifecycle. `OperationsStaff` (or the director) confirms a `REQUESTED` booking (`REQUESTED` → `CONFIRMED`). Check-in is the operations desk's alone and moves `CONFIRMED` → `CHECKED_IN` only while the clock is at or after the slot's `starts_at` and strictly before its `ends_at` (`ERR_INVALID_TIME_WINDOW`). The exhibitor, operations, or the director may cancel a booking still in `REQUESTED` or `CONFIRMED`; cancellation releases its pallets, dropping the slot's `reserved_pallets` by the booking's `pallet_count` and returning a `FULL` slot to `OPEN` when the count falls below capacity. Two run-ops freight sweeps close bookings out: a `CONFIRMED` booking whose slot's `ends_at` has passed without check-in becomes `NO_SHOW` and releases nothing — the no-show held its capacity to the end — while a `CHECKED_IN` booking past its slot's end becomes `COMPLETED` and releases its pallets in the usual way. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal, and bookings list with `application_id`, `exhibitor_id`, `load_slot_id`, `dock_door_id`, or `status` filters.

### 3.9. Enforcement, Departure, and Settlement

On-site policy enforcement runs on issue tickets. `OperationsStaff` and the `ShowDirector` report incidents by naming the `convention_id`, the subject `exhibitor_id`, a `category` of `ENCROACHMENT`, `NOISE`, `PROHIBITED_ITEM`, `COPYRIGHT`, or `CONDUCT`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`; the reporter's `X-User-ID` is recorded as `reporter_user_id`, and the ticket opens `OPEN`. The director then works the queue: triage moves `OPEN` → `TRIAGED`, escalation moves `OPEN` or `TRIAGED` → `ESCALATED`, and resolution is possible from any of `OPEN`, `TRIAGED`, or `ESCALATED`. Tickets list with `convention_id`, `exhibitor_id`, `status`, or `severity` filters.

Resolution records an `outcome` of `GUILTY` or `UNFOUNDED` and moves the ticket to the terminal `RESOLVED`. Segregation of duties is enforced at this step: the resolving director's `X-User-ID` must differ from the ticket's `reporter_user_id` (`ERR_DUTY_SEGREGATION`), so no one adjudicates their own complaint. An `UNFOUNDED` resolution applies nothing. A `GUILTY` one sets the ticket's `strike_points_applied` to the severity's point value — one for `MINOR`, two for `MAJOR`, three for `CRITICAL` — and adds those points to the exhibitor's `strike_points`. The exhibitor's `standing` is then recomputed against the bands of §3.2, the `renewal_priority_score` is recomputed with the new point total, and crossing into `EVICTED` fires the eviction cascade.

Eviction is the system's heaviest hammer. When an exhibitor's `standing` becomes `EVICTED`, every application of that exhibitor in `JURIED_ACCEPTED`, `CONTRACTED`, or `PLACED` is cancelled with `cancellation_reason` `EVICTION` and a `refund_cents` of zero. Each cancelled application then unwinds in full: its `TENTATIVE` and `CONFIRMED` placements are released and their spaces return to `AVAILABLE` with `current_application_id` cleared; its `ISSUED` staff badges are revoked; its `REQUESTED` and `CONFIRMED` freight bookings are cancelled, releasing their pallets from the load slots and returning any `FULL` slot to `OPEN` when the count drops below capacity; the category quota's `accepted_count` is decremented; and the promotion sweep runs for each affected category. Every `PENDING` neighbor request involving the exhibitor becomes `MOOT`, and the exhibitor's `renewal_priority_score` is recomputed.

Ordinary departure uses the same unwind with kinder money. An exhibitor — or the director acting on the convention's behalf — may cancel a `CONTRACTED` or `PLACED` application; the `cancellation_reason` records `EXHIBITOR` or `DIRECTOR` according to the actor. The refund follows the calendar: cancelling on or before the instant exactly sixty days before the show's `starts_at` refunds the full `amount_paid_cents`; after that instant but on or before the instant exactly thirty days before `starts_at`, half; later than that, nothing. The `refund_cents` is the `amount_paid_cents` multiplied by the applicable fraction, rounded half-up to the nearest cent, and eviction-driven cancellations bypass this rule entirely with a refund of zero. Alongside the refund, the full release cascade runs exactly as in eviction — placements released, spaces freed, badges revoked, freight cancelled with pallet release, `accepted_count` decremented, the promotion sweep fired, neighbor requests mooted — and `CANCELLED` is terminal.

After the doors open, money reporting closes the loop. An exhibitor drafts a sales report for a `PLACED` application (`ERR_APPLICATION_NOT_PLACED`) by supplying the `application_id` and a `lines` array — one entry per sales batch, each carrying a `sale_date` and a `gross_cents`; an empty `lines` array is rejected with `ERR_SALES_REPORT_EMPTY`, as is an attempt to submit one. The draft holds status `DRAFT` with a null `tax_settlement_cents`, the `exhibitor_id` denormalized from the application, and reports list with `application_id`, `exhibitor_id`, or `status` filters. Submitting — allowed once the convention is `LIVE`, in `LOAD_OUT`, or `CLOSED` (`ERR_PHASE_PRECONDITION`) — moves the report to the terminal `SUBMITTED` and settles the tax: each line's tax is its `gross_cents` multiplied by `sales_tax_rate_bp` and divided by ten thousand, rounded half-up to the nearest cent, and the `tax_settlement_cents` is the sum of those per-line amounts. Because the settlement rounds per line before summing while the estimate (§3.3) rounds per day before multiplying, the two figures can legitimately disagree for the same underlying sales.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. All other successful operations — reads, updates, and every state-transition action — return `200 OK`. Request payloads, response bodies, and side effects are defined by the workflows of Section 3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ShowDirector |
| POST | `/conventions` | Create a convention with its category quotas and dock doors | ShowDirector |
| GET | `/conventions/{conventionId}` | Read a convention | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| PUT | `/conventions/{conventionId}` | Update convention configuration (OCC-guarded) | ShowDirector |
| POST | `/conventions/{conventionId}/advance-phase` | Advance the convention exactly one phase | ShowDirector |
| POST | `/conventions/{conventionId}/run-ops` | Run the operations checkpoint sweeps | ShowDirector |
| GET | `/category-quotas` | List category quotas | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| GET | `/category-quotas/{categoryQuotaId}` | Read one category quota | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| PATCH | `/category-quotas/{categoryQuotaId}` | Adjust quota caps | ShowDirector |
| POST | `/space-units` | Create one booth or table inventory unit | ShowDirector |
| GET | `/space-units` | List space units with filters | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| GET | `/space-units/{spaceUnitId}` | Read one space unit | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| POST | `/exhibitors` | Self-register an exhibitor or artist | Anonymous |
| GET | `/exhibitors/{exhibitorId}` | Read an exhibitor (Exhibitor role: own record only) | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/applications` | Create an application draft for the authenticated exhibitor | Exhibitor |
| GET | `/applications` | List applications (Exhibitor role: own only) | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| GET | `/applications/{applicationId}` | Read one application (Exhibitor role: own only) | ShowDirector, OperationsStaff, JuryMember, Exhibitor |
| PATCH | `/applications/{applicationId}` | Revise an application while DRAFT or NEEDS_REVISION (OCC-guarded) | Exhibitor |
| POST | `/applications/{applicationId}/submit` | Submit or resubmit an application | Exhibitor |
| POST | `/applications/{applicationId}/withdraw` | Withdraw from a pre-contract state | Exhibitor |
| POST | `/applications/{applicationId}/request-revision` | Send the application back for changes | ShowDirector |
| POST | `/applications/{applicationId}/decide` | Jury decision: accept, waitlist, or reject | ShowDirector |
| POST | `/applications/{applicationId}/accept-offer` | Accept an offer, computing the invoice and collecting the deposit | Exhibitor |
| POST | `/applications/{applicationId}/decline` | Decline an accepted offer | Exhibitor |
| POST | `/applications/{applicationId}/cancel` | Cancel a contracted or placed application | Exhibitor, ShowDirector |
| POST | `/applications/{applicationId}/badge-extras` | Purchase extra badges beyond the included allotment | Exhibitor |
| POST | `/applications/{applicationId}/submit-permit` | Submit sales-tax permit details | Exhibitor |
| POST | `/applications/{applicationId}/verify-permit` | Verify a submitted permit | ShowDirector |
| POST | `/applications/{applicationId}/reject-permit` | Reject a submitted permit | ShowDirector |
| POST | `/applications/{applicationId}/claim-exemption` | Claim sales-tax exemption (nonprofit only) | Exhibitor |
| POST | `/jury-scores` | Post an immutable jury score | JuryMember |
| GET | `/jury-scores` | List jury scores | ShowDirector, JuryMember |
| GET | `/jury-scores/{juryScoreId}` | Read one jury score | ShowDirector, JuryMember |
| POST | `/placements` | Offer a specific space to an application | ShowDirector |
| GET | `/placements` | List placements | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/placements/{placementId}` | Read one placement | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/placements/{placementId}/confirm` | Confirm a tentative placement | ShowDirector |
| POST | `/placements/{placementId}/release` | Release a tentative placement back to inventory | ShowDirector |
| POST | `/neighbor-requests` | Request adjacency to or separation from another exhibitor | Exhibitor |
| GET | `/neighbor-requests` | List neighbor requests (scoped for Exhibitor) | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/neighbor-requests/{neighborRequestId}` | Read one neighbor request | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/neighbor-requests/{neighborRequestId}/withdraw` | Withdraw a pending neighbor request | Exhibitor |
| POST | `/staff-members` | Register a staff member | Exhibitor |
| GET | `/staff-members` | List staff members (Exhibitor role: own only) | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/staff-members/{staffMemberId}` | Read one staff member | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/staff-members/{staffMemberId}/issue-badge` | Issue a staff badge | Exhibitor, OperationsStaff |
| POST | `/staff-members/{staffMemberId}/revoke-badge` | Revoke an issued badge | OperationsStaff, ShowDirector |
| POST | `/load-slots` | Create a load-in or load-out marshalling window | ShowDirector |
| GET | `/load-slots` | List load slots | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/load-slots/{loadSlotId}` | Read one load slot | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/dock-doors` | List dock doors | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/dock-doors/{dockDoorId}` | Read one dock door | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/freight-bookings` | Book freight on a slot and dock door | Exhibitor |
| GET | `/freight-bookings` | List freight bookings (Exhibitor role: own only) | ShowDirector, OperationsStaff, Exhibitor |
| GET | `/freight-bookings/{freightBookingId}` | Read one freight booking | ShowDirector, OperationsStaff, Exhibitor |
| POST | `/freight-bookings/{freightBookingId}/confirm` | Confirm a requested booking | OperationsStaff, ShowDirector |
| POST | `/freight-bookings/{freightBookingId}/cancel` | Cancel a requested or confirmed booking | Exhibitor, OperationsStaff, ShowDirector |
| POST | `/freight-bookings/{freightBookingId}/check-in` | Check in a confirmed booking inside the slot window | OperationsStaff |
| POST | `/issue-tickets` | Report an on-site policy issue against an exhibitor | OperationsStaff, ShowDirector |
| GET | `/issue-tickets` | List issue tickets | ShowDirector, OperationsStaff |
| GET | `/issue-tickets/{issueTicketId}` | Read one issue ticket | ShowDirector, OperationsStaff |
| POST | `/issue-tickets/{issueTicketId}/triage` | Mark an open issue under investigation | ShowDirector |
| POST | `/issue-tickets/{issueTicketId}/escalate` | Escalate an open or triaged issue | ShowDirector |
| POST | `/issue-tickets/{issueTicketId}/resolve` | Resolve an issue with an outcome | ShowDirector |
| POST | `/sales-reports` | Create a draft sales report | Exhibitor |
| GET | `/sales-reports` | List sales reports (Exhibitor role: own only) | ShowDirector, Exhibitor |
| GET | `/sales-reports/{salesReportId}` | Read one sales report | ShowDirector, Exhibitor |
| POST | `/sales-reports/{salesReportId}/submit` | Submit the report and settle its tax | Exhibitor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONVENTION_VERSION` | 412 Precondition Failed |
| `ERR_APPLICATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RENEWAL_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_CATEGORY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CATEGORY_NOT_OFFERED` | 422 Unprocessable Entity |
| `ERR_CATEGORY_QUOTA_FULL` | 422 Unprocessable Entity |
| `ERR_WAITLIST_FULL` | 422 Unprocessable Entity |
| `ERR_JURY_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_JURY_CONFLICT_OF_INTEREST` | 403 Forbidden |
| `ERR_DUPLICATE_JURY_SCORE` | 409 Conflict |
| `ERR_PERMIT_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_EXEMPTION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_EXHIBITOR_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SPACE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SPACE_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CATEGORY_ZONE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NEIGHBOR_SELF_TARGET` | 422 Unprocessable Entity |
| `ERR_NEIGHBOR_TARGET_NOT_APPLIED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_NEIGHBOR_REQUEST` | 409 Conflict |
| `ERR_DUPLICATE_SPACE_CODE` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD` | 422 Unprocessable Entity |
| `ERR_BADGE_ALLOCATION_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_BADGE_EXTRA_LIMIT` | 422 Unprocessable Entity |
| `ERR_APPLICATION_NOT_PLACED` | 422 Unprocessable Entity |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DOOR_WINDOW_OUTSIDE_SLOT` | 422 Unprocessable Entity |
| `ERR_DOOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_FREIGHT_WRONG_PHASE` | 422 Unprocessable Entity |
| `ERR_PHASE_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_DUTY_SEGREGATION` | 403 Forbidden |
| `ERR_QUOTA_BELOW_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_SALES_REPORT_EMPTY` | 422 Unprocessable Entity |
| `ERR_STAFF_NOT_ALLOWED_YET` | 422 Unprocessable Entity |

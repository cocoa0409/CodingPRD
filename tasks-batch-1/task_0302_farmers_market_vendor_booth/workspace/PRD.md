# Farmers Market & Vendor Booth Management API — Product Requirements Document

## 1. Introduction

Running a seasonal farmers market means juggling a finite pool of physical booths against a fluctuating roster of vendors, each of whom must clear a paperwork gauntlet — applications, product-category approval, and health permits — before they can ever set up a stall. This API is the system of record for that whole operation. It governs how vendors apply and are vetted, how the limited booths on the market map are competed for and allocated (either for a full season or for a single market day), how attendance is tracked day by day, how the token and voucher program is reconciled against vendor self-reported sales, and how commission is ultimately disbursed to the market.

Two financial truths sit at the heart of the system, and they deliberately diverge. The market accrues commission on what vendors *say* they sold, but it only finalizes commission on what it can *verify* through redeemed tokens; and the fee a vendor pays depends on whether they took a booth for the season or for one day, prorated and refunded under rules that change with the weather. The platform must hold both an occupancy ledger and a voucher-cash ledger consistent on every mutation, promote waitlisted vendors the instant a booth frees up, and unwind an entire day's commitments — assignments, attendance, sales, and voucher liability — when a market day is cancelled for weather. The sections that follow specify the contracts, the cross-cutting principles, and the per-lifecycle business rules that make this behaviour deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, principles, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `MarketAdmin`, `MarketManager`, and `Vendor`. A request that omits either header, or that carries an `X-User-Role` value that is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but is not permitted to perform the requested operation — or a `Vendor` attempting to act on a resource it does not own — is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles map to identity differently. `MarketAdmin` is the market operator: it configures markets, booths, and market days, verifies permits, reviews applications, manages the assignment lifecycle, and opens, closes, or cancels days. When `X-User-Role` is `MarketAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `MarketManager` is the financial operator: it issues voucher batches, reconciles redemptions, and disputes or reconciles sales reports and the commission they carry, but it cannot configure the map or review applications. When `X-User-Role` is `MarketManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity's `id`. `Vendor` is the market participant. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's vendor foreign key to `X-User-ID`. Concretely, a vendor owns its own applications, permits, booth assignments, check-ins, sales reports, and voucher redemptions, and may only resubmit, cancel, submit, or otherwise act on those rows where the chain of references leads back to its own `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list results are sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Versioning, and Common Properties

Every primary resource in the system — markets, vendors, permits, applications, booths, market days, booth assignments, check-ins, sales reports, voucher batches, and voucher redemptions — carries a system-managed `id` that is a UUID with no type prefix. Each also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recording when the row was first created. Because every entity in this domain is a mutable, server-managed record, each additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every change, and a `version` integer that begins at 1 on creation and increments by exactly 1 on every mutation. The `version` field is the basis for the optimistic concurrency check described in §2.8. Recomputation of a derived field — for example refreshing a market's ledger totals — is itself a mutation: it refreshes `updated_at` and increments `version` on the resource whose derived field changed.

### 2.5. Hierarchical Consistency and Automatic State Propagation

The entities in this system are linked by foreign keys rather than nested URL paths, but their states remain tightly coupled, and the server propagates changes across those links automatically without an explicit client request on the dependent resource. When a vendor's first application is approved, the owning vendor is promoted from `PROSPECT` to `ACTIVE` and the vendor's `version` is bumped alongside the application's. When a season assignment reserves or releases a booth, the booth's `status` and `season_holder_assignment_id` are updated and the booth's `version` is incremented. Whenever a booth assignment enters or leaves the occupancy set, or a voucher redemption is reconciled or reversed, the owning market's ledger fields are recomputed and the market's `version` is incremented. The cancellation of a market day is the deepest of these cascades and is specified in full in §3. In every case the rule is the same: each automatic mutation independently refreshes the affected resource's `updated_at` and increments its `version`, so a client that holds a stale view can detect the drift.

### 2.6. Nested Reference Resolution and Existence Ordering

Although the URL topology is flat — each entity lives at its own top-level collection and parent links travel in the request body — a request still references resources both by the identifier in its path and by the foreign keys in its body. The server validates every path-referenced resource for existence within the market scope before it evaluates business rules, and where a path contains more than one identifier it resolves them left to right, rejecting the first one that does not resolve with `ERR_NOT_FOUND`. Body foreign keys that point at non-existent rows are likewise treated as not-found. This ordering guarantees that a request against a missing resource fails cleanly before any state or fiscal logic runs.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are integer counts of cents and are stored and returned as integers. Wherever a calculation multiplies or divides cents — fee proration, commission on a basis-point rate, voucher reimbursement — the result is taken to integer cents using the round-half-up method, except where a calculation explicitly specifies a floor (the season weather-refund proration described in §3 floors its per-day share). Basis-point rates use a denominator of 10000, so a rate of `commission_bps` applied to an amount means that amount multiplied by `commission_bps` and divided by 10000, rounded half up to whole cents.

### 2.8. Optimistic Concurrency on Season Booth Allocation

Requesting a `SEASON` booth assignment is the one write in this system that is guarded by optimistic concurrency, because two vendors can both legitimately see a booth as `OPEN` and both try to take it for the season. To allocate a season booth, the create request must carry `expected_booth_version`, a non-optional field for `SEASON` requests that holds the `version` of the target booth the client last observed. If that value does not match the booth's current `version` — for instance because another writer has already reserved a season assignment on the booth, taking it from `OPEN` to `SEASON_HELD` and advancing the booth's `version` — the create is rejected with `ERR_STALE_BOOTH_VERSION` at HTTP 412. This prevents a client from overwriting an allocation it never observed; the rejection is framed entirely in terms of the stale version the client supplied, not the timing of the two requests. Daily booth-assignment creates and every other write in the system do not take a version field and are not subject to this check.

### 2.9. The Two Market Ledgers and Derived-Field Reconciliation

Each market maintains three computed totals that are reconciled on every triggering mutation, and they must never be conflated. The **occupancy-fee ledger**, `total_fees_collected_cents`, is the sum over every booth assignment currently in `RESERVED` or `ACTIVE` status of that assignment's `fee_charged_cents` less its `fee_refunded_cents`; assignments in `REQUESTED`, `WAITLISTED`, `CANCELLED`, or `COMPLETED` contribute nothing. To break the apparent circularity between an assignment's own fee fields and this market total, the order of evaluation is pinned: the assignment's `fee_charged_cents` and `fee_refunded_cents` are locked first, in isolation, and only then is the market aggregate recomputed from the now-final per-row values. The **reconciled-revenue ledger**, `total_commission_accrued_cents`, is the sum of `commission_cents` across every sales report under the market that has reached `RECONCILED` status. The **voucher-cash ledger**, `voucher_liability_cents`, is the market's `voucher_face_value_cents` multiplied by the total tokens redeemed across all reconciled redemptions (capped per batch by issuance, as §3 details), less the cash already reimbursed to vendors. A market also exposes `booth_count`, the number of booths created under it. All four computed fields are recomputed atomically inside the request that triggers the change.

### 2.10. Permit and Category Gating

Two gates stand between an approved vendor and a booth. The first is the **health-permit gate**, captured per vendor by the computed boolean `permit_ok`. A vendor's `permit_ok` is true in either of two cases: the product category on the vendor's approved application is not one of `DAIRY`, `MEAT`, or `PREPARED_FOOD` (so no health permit is needed at all), or the vendor holds at least one permit whose `permit_type` is `HEALTH`, whose `status` is `VERIFIED`, and whose `expiry_date` is on or after the date of the assignment window under test. This flag is recomputed whenever a permit is verified or expires, and it is re-evaluated at assignment time against the relevant window date. The second is the **category gate**: a booth's `allowed_categories` array, when non-empty, must contain the approved `product_category` of the vendor requesting it. These gates and the error codes they raise are detailed alongside the assignment workflow in §3.

### 2.11. Validation Ordering

When a single endpoint is subject to several checks, they are evaluated in a fixed priority order so that the same bad request always produces the same error. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization, including vendor ownership (`ERR_FORBIDDEN_ROLE`); then existence of every path-referenced resource within the market scope (`ERR_NOT_FOUND`); then structural validation of the request body — required fields present and well-typed, enum values legal, and numeric bounds satisfied such as `gross_sales_cents` being at least 0 and `token_count` being greater than 0 (`ERR_INVALID_REQUEST`); then business referential integrity such as the daily-versus-season `market_day_id` rule and the redemption-batch day match (`ERR_REFERENTIAL_MISMATCH`); then the state-legality check that the target is in a state from which the transition is permitted (`ERR_INVALID_STATE`); then temporal-window checks (`ERR_OUTSIDE_WINDOW`); then the permit-safety gate (`ERR_PERMIT_NOT_VERIFIED`); then the category gate (`ERR_CATEGORY_NOT_ALLOWED`); then the booth-occupancy hard rejection (`ERR_BOOTH_OCCUPIED`); then the voucher fiscal cap (`ERR_TOKEN_OVERDRAW`); then the stale-booth-version check (`ERR_STALE_BOOTH_VERSION`); and finally uniqueness (`ERR_DUPLICATE`). An earlier failure short-circuits and masks any later one, so for example a request that is both unauthenticated and malformed surfaces `ERR_UNAUTHENTICATED`, not `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Market and Its Map

The lifecycle begins when a `MarketAdmin` creates a market. The creating payload supplies the market's `name`, its season window as a `season_start_date` and `season_end_date` pair (each a `YYYY-MM-DD` date, with the end falling on or after the start), and the market's fiscal policy: a `season_fee_cents`, a `daily_fee_cents`, a `commission_bps` commission rate, and a `voucher_face_value_cents` cash value for one redeemed token. The season end date may equal the start date but may not precede it; the two fee amounts and the face value must each be strictly greater than 0; and `commission_bps` must lie between 0 and 10000 inclusive. A violation of any of these bounds — an end date earlier than the start, a fee or face value at or below zero, or a basis-point rate outside the 0-to-10000 range — is rejected with `ERR_VALIDATION_BOUNDS`. A freshly created market starts with `booth_count` at 0 and every ledger field (`total_commission_accrued_cents`, `total_fees_collected_cents`, `voucher_liability_cents`) at 0.

Against that market the admin lays out the physical map. Creating a booth supplies the owning `market_id`, a `label` that must be unique within the market (for example `A-12`), a `grid_row` and `grid_col` that each must be at least 0, a `size_class` that is one of `SINGLE`, `DOUBLE`, or `CORNER`, and an `allowed_categories` array naming which product categories the booth may host — an empty array meaning all categories are welcome. A new booth comes up with `status` `OPEN` and a null `season_holder_assignment_id`, and its creation increments the market's `booth_count`. A booth's `status` is one of `OPEN`, `SEASON_HELD`, or `OUT_OF_SERVICE`: it reads `SEASON_HELD` while a season assignment in `RESERVED` or `ACTIVE` holds it, and `OUT_OF_SERVICE` when an admin has taken it down. The admin can flip a booth between service states by supplying an `out_of_service` boolean; the booth toggles between `OUT_OF_SERVICE` and `OPEN`, but only when it is not currently `SEASON_HELD`. Attempting a duplicate `label` within the same market is rejected with `ERR_DUPLICATE`.

The admin also schedules the market's operating days. Creating a market day supplies the `market_id` and a `market_date` (`YYYY-MM-DD`) that must fall within the season window — on or after `season_start_date` and on or before `season_end_date`, inclusive — and that must be unique within the market. A date outside the season window is rejected with `ERR_OUTSIDE_WINDOW`, and a duplicate date within the market is rejected with `ERR_DUPLICATE`. A market day is born `SCHEDULED`, with `attendance_count` at 0 and `opened_at` null; it carries a `cancellation_reason` (one of `WEATHER`, `SAFETY`, or `LOW_TURNOUT`) only once cancelled, and a computed `daily_fee_refundable` flag described in §3.6.

### 3.2. Vendor Onboarding: Registration, Permits, and Applications

A vendor enters the system through registration, performed either by a `MarketAdmin` or by the vendor itself. Registration supplies the `market_id` the vendor belongs to, a `legal_name`, and a `contact_email` that must be unique within the market; a duplicate email under the same market is rejected with `ERR_DUPLICATE`. A new vendor starts in `PROSPECT` status, with `no_show_strikes` at 0 and `permit_ok` false. A vendor's `status` is either `PROSPECT` or `ACTIVE`; it flips to `ACTIVE` the moment the vendor's first application is approved, and there is no path back to `PROSPECT`.

Before approval, a vendor may file permits and applications. Submitting a permit supplies the owning `vendor_id`, a `permit_type` (one of `HEALTH`, `FIRE`, `COTTAGE_FOOD`, or `RESALE`), a `permit_number` from the issuing authority, an `issue_date`, and an `expiry_date` (each `YYYY-MM-DD`), where the expiry must be strictly after the issue date — an expiry on or before the issue date is rejected with `ERR_VALIDATION_BOUNDS`. A submitted permit begins `PENDING` with a null `verified_at`. The four permit states are `PENDING`, `VERIFIED`, `REJECTED`, and `EXPIRED`. A `MarketAdmin` adjudicates a pending permit by supplying a `decision` of either `VERIFY` or `REJECT`: a `VERIFY` moves the permit to `VERIFIED`, stamps `verified_at` with the current UTC time, and recomputes the owning vendor's `permit_ok`; a `REJECT` moves it to `REJECTED`.

Filing an application supplies the applicant's `vendor_id` and a `product_category`, one of `PRODUCE`, `DAIRY`, `MEAT`, `BAKED_GOODS`, `PREPARED_FOOD`, `CRAFTS`, or `FLOWERS`. On creation the system computes `requires_health_permit`, which is true exactly when the chosen category is one of `DAIRY`, `MEAT`, or `PREPARED_FOOD`; this pins which categories will gate approval on a verified health permit. The application is born `SUBMITTED` with a null `review_note`. Its `status` progresses through `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, and `REJECTED`. A `MarketAdmin` moves a submitted application into review, advancing it from `SUBMITTED` to `UNDER_REVIEW`; this is legal only while the application is `SUBMITTED`, and it bumps the application's `version`.

From `UNDER_REVIEW`, the admin either approves or rejects. Approval requires the application to be `UNDER_REVIEW`, and where `requires_health_permit` is true it additionally requires the applicant vendor to hold at least one permit whose `permit_type` is `HEALTH`, whose `status` is `VERIFIED`, and whose `expiry_date` is on or after the market's `season_start_date`; approving a health-gated application without such a permit is rejected with `ERR_NO_HEALTH_PERMIT`. A successful approval moves the application to `APPROVED`, sets its `review_note` from the request, promotes the owning vendor from `PROSPECT` to `ACTIVE` if it was still `PROSPECT`, and increments both the application's and the vendor's `version` by 1. Rejection, legal only from `UNDER_REVIEW`, moves the application to `REJECTED`, records the supplied `review_note`, and bumps the application's `version`. A rejected application is not a dead end: the owning vendor — and only the vendor that owns it, verified by matching the application's `vendor_id` against `X-User-ID` — may resubmit it, which is legal only from `REJECTED`, returns it to `SUBMITTED`, clears `review_note` back to null, and increments `version`, opening a fresh review pass.

### 3.3. Competing for a Booth: Reservation, Waitlist, and Promotion

A booth assignment is how a vendor lays claim to a stall. A request is created by a `MarketAdmin` or by the vendor, supplying the `market_id`, the `booth_id` of the requested booth, the `vendor_id` of the requesting vendor, and an `assignment_type` of either `SEASON` or `DAILY`. A `DAILY` request must additionally carry the `market_day_id` of the day it covers, while a `SEASON` request must omit it; supplying a `market_day_id` on a season request, or omitting it on a daily request, is rejected with `ERR_REFERENTIAL_MISMATCH`. A season request must also carry `expected_booth_version` as described in §2.8. The request may optionally carry an `allow_waitlist` flag, whose role is described below. Every assignment is born in `REQUESTED` status and is immediately evaluated by the system, which synchronously drives it onward; its `status` is one of `REQUESTED`, `WAITLISTED`, `RESERVED`, `ACTIVE`, `COMPLETED`, or `CANCELLED`.

For the request to advance at all, the vendor must be `ACTIVE` and the vendor's `permit_ok` must be true, evaluated against the assignment window — `season_start_date` for a season request, the day's `market_date` for a daily request. A vendor whose `permit_ok` is false at that window is rejected with `ERR_PERMIT_NOT_VERIFIED`. The booth's `allowed_categories`, if non-empty, must contain the vendor's approved `product_category`, failing which the request is rejected with `ERR_CATEGORY_NOT_ALLOWED`. The booth must also be free for the requested window: for a season request, the booth must be `OPEN` with no overlapping season or daily occupation across the season window; for a daily request, no `RESERVED` or `ACTIVE` assignment of either type may occupy the booth on that market day.

When the slot is free and all gates pass, the assignment moves from `REQUESTED` straight to `RESERVED`. Reservation locks `fee_charged_cents` by the fee calculation in §3.4. For a season reservation it additionally sets the booth's `status` to `SEASON_HELD`, records the booth's `season_holder_assignment_id` as this assignment, and increments the booth's `version`. In all reservations the market's `total_fees_collected_cents` is recomputed and the market's `version` is incremented. When instead the slot is already occupied by a `RESERVED` or `ACTIVE` assignment, the request takes the waitlist path: it moves from `REQUESTED` to `WAITLISTED`, its `waitlist_rank` is computed as one more than the count of existing waitlisted assignments on the same booth (and, for a daily request, the same market day), and its `fee_charged_cents` stays 0 while it waits. The `allow_waitlist` flag governs this fork: it defaults to allowing the waitlist, but when a client explicitly sets it to false and the slot is occupied, no waitlist row is created and the request is instead rejected outright with `ERR_BOOTH_OCCUPIED`.

A waitlisted assignment is the system's queue of standby vendors. Its `waitlist_rank` is its 1-based position among the waitlisted assignments on the same booth — and, for daily assignments, the same market day — ordered by `created_at` ascending, so the earliest waitlister ranks first; because creation timestamps are unique per row no tie-break is needed. Promotion always selects the row whose `waitlist_rank` is 1. A waitlisted assignment advances to `RESERVED` either automatically, when the assignment that was holding its slot is completed or cancelled and frees it, or on an explicit promotion by a `MarketAdmin`. Promotion is legal only when the slot is now free, when this assignment's `waitlist_rank` is 1, and when the vendor's `permit_ok` is still true at promotion time; an attempt to promote an assignment whose `waitlist_rank` is not 1, or whose slot is still occupied, is rejected with `ERR_WAITLIST_NOT_HEAD`. A promotion locks `fee_charged_cents`, for a season assignment sets the booth's `status` to `SEASON_HELD` and `season_holder_assignment_id` and bumps the booth's `version`, re-ranks the remaining waitlisted assignments by decrementing each survivor's `waitlist_rank` by 1, and recomputes the market's `total_fees_collected_cents` while incrementing the market's `version`.

A reserved assignment is activated either by a `MarketAdmin` or by the system on the first check-in to a daily assignment, advancing it from `RESERVED` to `ACTIVE`; activation is legal only from `RESERVED`, and for a daily assignment only while the market day is `OPEN` (not `CANCELLED` or `CLOSED`). Activation bumps the assignment's `version`. Completing an assignment — done by a `MarketAdmin`, or by the system when the season ends or a daily market day closes — is legal from either `RESERVED` or `ACTIVE` and moves it to `COMPLETED`. For a season assignment, completion frees the booth: it sets the booth's `status` back to `OPEN`, clears `season_holder_assignment_id`, and increments the booth's `version`. Completion then promotes the rank-1 waitlisted assignment on the freed slot to `RESERVED`, which itself runs the waitlist-to-reserved transition and so recomputes the market's `total_fees_collected_cents`. Because the occupancy ledger counts only `RESERVED` and `ACTIVE` rows, completing the holder drops its locked fee from the total and the promotion of the next waitlister re-adds an identical fee, leaving the ledger invariant across the complete-and-promote pair.

Cancellation is the broadest exit. An assignment may be cancelled from `REQUESTED`, `WAITLISTED`, `RESERVED`, or `ACTIVE` — by a `MarketAdmin`, by the owning vendor (a vendor cancel requires that the acting vendor owns the assignment), or by the system when a daily market day is cancelled for weather — moving it to `CANCELLED`. If the cancelled assignment was a season assignment in `RESERVED` or `ACTIVE`, cancellation frees the booth exactly as completion does: it sets the booth back to `OPEN`, clears `season_holder_assignment_id`, and increments the booth's `version`. If it was in `RESERVED` or `ACTIVE`, cancellation also promotes the rank-1 waitlisted assignment on the freed slot to `RESERVED`, cascading into the waitlist-to-reserved transition that recomputes the market's `total_fees_collected_cents`. If instead it was merely `WAITLISTED`, cancellation re-ranks the remaining waitlisted assignments, decrementing each higher rank by 1. And when the cancellation is the consequence of a weather day cancellation, it sets `fee_refunded_cents` by the refund calculation in §3.6, recomputes the market's `total_fees_collected_cents`, and increments the market's `version`. Any attempt to drive an assignment through a transition illegal from its current state is rejected with `ERR_INVALID_STATE`.

### 3.4. Pricing a Booth: The Season-versus-Daily Fee

The fee an assignment owes is locked at the moment it becomes `RESERVED`, whether that happens directly or through promotion, and it depends on two things: the booth's size and the assignment type. Each booth size carries a multiplier expressed in hundredths to keep the arithmetic in integers — a `SINGLE` booth uses 100, a `DOUBLE` booth uses 180, and a `CORNER` booth uses 150, the corner's premium reflecting its prized map position. The base rate is drawn from the market according to the assignment type: a `SEASON` assignment uses the market's `season_fee_cents` as its base, one flat charge covering every market day in the season window; a `DAILY` assignment uses the market's `daily_fee_cents` as its base, charged for the single day. In both variants the locked `fee_charged_cents` is the base multiplied by the size multiplier, divided by 100, and rounded half up to whole cents. Because a daily assignment is charged per day, taking N separate daily assignments on a booth across a full season costs N times the daily fee, which in general diverges from the single season charge for the same booth.

### 3.5. Market Day Operations: Attendance, Check-In, and Day Close

A market day moves through `SCHEDULED`, `OPEN`, `CLOSED`, and `CANCELLED`. A `MarketAdmin` opens a scheduled day, advancing it from `SCHEDULED` to `OPEN` and stamping `opened_at`; this is legal only from `SCHEDULED`. Attendance is tracked through check-ins. A check-in is created by a `MarketAdmin` or the vendor and supplies the `market_id`, the `booth_assignment_id` of the assignment being attended, and the `market_day_id` of the day attended; it is born `EXPECTED`, with a null `arrived_at`. A check-in's `status` is `EXPECTED`, `PRESENT`, or `NO_SHOW`. Marking a check-in as arrived — by a `MarketAdmin` or the vendor — advances it from `EXPECTED` to `PRESENT`, stamps `arrived_at`, recomputes the day's `attendance_count`, and bumps the check-in's `version`; if the linked assignment is `RESERVED` it cascades that assignment to `ACTIVE`. Arrival is legal only when the check-in is `EXPECTED` and the market day is `OPEN`; arriving on a `SCHEDULED`, `CLOSED`, or `CANCELLED` day is rejected with `ERR_OUTSIDE_WINDOW`, and an arrival attempted from a status other than `EXPECTED` falls foul of the state check. The day's `attendance_count` is the count of check-ins in `PRESENT` status for that day.

Closing an open day, performed by a `MarketAdmin`, is legal only from `OPEN` and advances it to `CLOSED`. Closing runs three cascades atomically: every check-in for the day still in `EXPECTED` becomes `NO_SHOW`, which recomputes and increments the owning vendor's `no_show_strikes` and bumps each check-in's `version`; every daily booth assignment on the day in `RESERVED` or `ACTIVE` is completed to `COMPLETED`; and every voucher batch for the day in `ISSUED` status is closed to `CLOSED`. The day's `version` is incremented. A vendor's `no_show_strikes` is the running count of that vendor's `NO_SHOW` check-ins and drives waitlist demotion considerations.

### 3.6. Weather Cancellation: The Master Cascade and Fee Refunds

Cancelling a market day, done by a `MarketAdmin` from either `SCHEDULED` or `OPEN`, requires a `cancellation_reason` to be supplied and moves the day to `CANCELLED`; a missing reason makes the request malformed. On cancellation the system sets `daily_fee_refundable` to true exactly when the `cancellation_reason` is `WEATHER`, and false for `SAFETY` or `LOW_TURNOUT`. The cancellation then unwinds the day in a layered cascade. First, every daily booth assignment on the day that is in `REQUESTED`, `WAITLISTED`, `RESERVED`, or `ACTIVE` is cancelled to `CANCELLED`. Where the reason is `WEATHER`, each such cancelled assignment has its `fee_refunded_cents` set by the refund rule below and, if it was holding a booth, frees that booth's slot; freeing a slot then recomputes the parent market's `total_fees_collected_cents`. Check-ins for a cancelled day are not swept to `NO_SHOW`; instead they are voided — their `status` is left as-is but they are excluded from the day's `attendance_count`. Every voucher redemption for the day that is `RECONCILED` or `SUBMITTED` is reversed to `REVERSED`, which resets each redemption's `reimbursed_cents` to 0 and recomputes the market's `voucher_liability_cents`. Every voucher batch for the day is closed to `CLOSED`. Finally the day's `version` is incremented. This is the master cascade of the system: the day flows down to its booth assignments and onward to the booth and market fee ledger, and in parallel down to its voucher redemptions and onward to the market voucher ledger.

The weather refund is the only path that rebates a fee. When a `WEATHER` cancellation cancels an assignment, a daily assignment receives a full rebate — its `fee_refunded_cents` equals its `fee_charged_cents`. A season assignment, by contrast, is not rebated its whole season fee for a single lost day; it is rebated only one day's prorated share. That share is computed by counting the market days under the market that are not `CANCELLED` at the moment of cancellation, taking that count or 1 if it would be zero, dividing the assignment's `fee_charged_cents` by it, and flooring the quotient to whole cents. For any cancellation reason other than `WEATHER`, `fee_refunded_cents` stays 0, since `SAFETY` and `LOW_TURNOUT` cancellations are non-refundable; outside a weather cancellation an assignment's `fee_refunded_cents` is 0 by default.

### 3.7. Tokens and Vouchers: Issuance, Redemption, and Reconciliation

The token program runs in parallel with attendance. A `MarketManager` issues a voucher batch for a day by supplying the `market_id`, the `market_day_id` the tokens are issued for, and a `tokens_issued` count that must be greater than 0. A batch is born `ISSUED` with `tokens_redeemed` at 0; its `status` is either `ISSUED` or `CLOSED`, closing when its day closes or is cancelled. A batch's `tokens_redeemed` is the sum of `token_count` across the reconciled redemptions drawn from it, capped so it never exceeds `tokens_issued`.

A redemption is how a vendor claims cash for tokens taken. Submitted by a `MarketManager` or the vendor, it supplies the `market_id`, the `voucher_batch_id` the tokens came from, the redeeming `vendor_id`, the `market_day_id` of the redemption, and a `token_count` greater than 0. The redemption's `market_day_id` must equal the batch's `market_day_id`, failing which the request is rejected with `ERR_REFERENTIAL_MISMATCH`. A redemption is born `SUBMITTED` with `reimbursed_cents` at 0; its `status` is `SUBMITTED`, `RECONCILED`, or `REVERSED`. A `MarketManager` reconciles a submitted redemption, advancing it from `SUBMITTED` to `RECONCILED`. Reconciliation is legal only when the redemption is `SUBMITTED` and the owning market day is `OPEN` or `CLOSED` but not `CANCELLED` — a reconcile against a cancelled day is rejected with `ERR_DAY_NOT_OPEN`. It is further capped fiscally: the running total of `RECONCILED` `token_count` for the batch, plus this redemption's `token_count`, must not exceed the batch's `tokens_issued`; a reconcile that would push the batch's reconciled total above its issuance is rejected with `ERR_TOKEN_OVERDRAW`. A successful reconcile locks `reimbursed_cents` as this redemption's `token_count` multiplied by the market's `voucher_face_value_cents`, then recomputes the batch's `tokens_redeemed` and the market's `voucher_liability_cents` and increments the market's `version`.

The market's `voucher_liability_cents` is reconciled from all batches under the market: for each batch, its `tokens_redeemed` is the lesser of its `tokens_issued` and the sum of `token_count` across that batch's reconciled redemptions; the market liability is then the market's `voucher_face_value_cents` multiplied by the total of `tokens_redeemed` summed over every batch under the market, less the cash already reimbursed to vendors to date. On an ordinary day the disbursement lags redemption so the liability is positive; when redemptions are reversed the summed term drops and the liability is recomputed downward. A redemption is reversed — from either `SUBMITTED` or `RECONCILED` — only by the system when the owning market day is cancelled; reversal resets `reimbursed_cents` to 0 and recomputes the batch's `tokens_redeemed` and the market's `voucher_liability_cents`, returning the voucher cash ledger to its pre-redemption value.

### 3.8. Sales Reporting and the Two Commission Bases

A sales report captures what a vendor sold on an attended day, and it is the bridge between self-reported revenue and verified commission. A report is created by a `MarketAdmin` or the vendor against a specific attendance, supplying the `market_id`, the `check_in_id` it covers (one report per check-in; a second report for the same check-in is rejected with `ERR_DUPLICATE`), a `gross_sales_cents` figure that must be at least 0, and a `tokens_accepted` count that must be at least 0. The report is born `DRAFT` with `commission_cents` at 0; its `status` is `DRAFT`, `SUBMITTED`, `RECONCILED`, or `DISPUTED`. The vendor that owns the report submits it, advancing it from `DRAFT` to `SUBMITTED`, optionally supplying corrected `gross_sales_cents` and `tokens_accepted` figures on submit. Submission is legal only when the report is `DRAFT` (or `DISPUTED`, per the dispute loop below), when the linked check-in is `PRESENT` — only attended days may report sales, and a submit whose check-in is not `PRESENT` is rejected with `ERR_SALES_NOT_PRESENT` — and when the acting vendor owns the report, traced through the check-in to the assignment's `vendor_id`. Submission computes the provisional `commission_cents` and bumps the report's `version`.

The **provisional commission**, computed at submission, is taken on the vendor's full self-reported gross: it is `gross_sales_cents` multiplied by the market's `commission_bps` and divided by 10000, rounded half up to whole cents. A `MarketManager` may dispute a submitted report, advancing it from `SUBMITTED` to `DISPUTED`; a dispute is legal only from `SUBMITTED`, flags the report without changing `commission_cents`, and bumps the `version`. A disputed report is returned to the manager's queue when the owning vendor resubmits it with corrected figures, advancing it from `DISPUTED` back to `SUBMITTED`, recomputing the provisional `commission_cents`, and bumping the `version`; submitted and disputed thus cycle until the manager reconciles.

The **final commission**, computed when a `MarketManager` reconciles a submitted report from `SUBMITTED` to `RECONCILED`, is taken on a token-reconciled basis and generally differs from the provisional figure because it cannot exceed it. Reconciliation is legal only when the report is `SUBMITTED` and when every voucher redemption for the same vendor and market day has itself reached `RECONCILED`. On reconcile the system first sets `reconciled_token_count` to the lesser of the report's `tokens_accepted` and the sum of `token_count` across the reconciled redemptions attributed to that vendor and that market day. It then derives the token-backed sales as that `reconciled_token_count` multiplied by the market's `voucher_face_value_cents`, takes the verified sales as the lesser of `gross_sales_cents` and those token-backed sales, and sets the final `commission_cents` to the verified sales multiplied by `commission_bps` and divided by 10000, rounded half up to whole cents. Because the verified amount never exceeds the gross, the final commission is at most the provisional one. Reconciliation then recomputes the market's `total_commission_accrued_cents` — the sum of `commission_cents` over every reconciled report under the market — and increments the market's `version`.

### 3.9. Deterministic Time Control

To make date-window and permit-expiry behaviour testable, an admin-only test-driving capability advances the server's notion of the current UTC instant to a supplied `to_iso8601` value. Setting the clock forward sweeps permits: any permit that was `VERIFIED` whose `expiry_date` now falls before the current date transitions to `EXPIRED`, and the owning vendor's `permit_ok` is recomputed to reflect the lost permit. This is how a once-valid health permit silently lapses and re-gates a vendor's future assignments.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, including the lifecycle and reconciliation actions, return `200 OK`. List and fetch operations return `200 OK`. Request bodies, query parameters, and side effects for each endpoint are specified in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/markets` | Create a market with season window and fee/commission/voucher policy | MarketAdmin |
| GET | `/markets/{market_id}` | Get a market including computed ledger fields | MarketAdmin, MarketManager, Vendor |
| POST | `/vendors` | Register a vendor under a market | MarketAdmin, Vendor |
| GET | `/vendors/{vendor_id}` | Get a vendor including computed permit_ok and no_show_strikes | MarketAdmin, MarketManager, Vendor |
| GET | `/vendors` | List vendors (filterable by market_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/permits` | Submit a permit for verification | MarketAdmin, Vendor |
| GET | `/permits/{permit_id}` | Get a permit | MarketAdmin, MarketManager, Vendor |
| GET | `/permits` | List permits (filterable by vendor_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/permits/{permit_id}/verify` | Verify or reject a submitted permit | MarketAdmin |
| POST | `/applications` | Submit an application with a product category | MarketAdmin, Vendor |
| GET | `/applications/{application_id}` | Get an application | MarketAdmin, MarketManager, Vendor |
| GET | `/applications` | List applications (filterable by vendor_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/applications/{application_id}/start-review` | Move an application into review | MarketAdmin |
| POST | `/applications/{application_id}/approve` | Approve an application (health-permit gated when required) | MarketAdmin |
| POST | `/applications/{application_id}/reject` | Reject an application under review | MarketAdmin |
| POST | `/applications/{application_id}/resubmit` | Resubmit a rejected application | Vendor |
| POST | `/booths` | Create a booth on the market map | MarketAdmin |
| GET | `/booths/{booth_id}` | Get a booth including computed status and season holder | MarketAdmin, MarketManager, Vendor |
| GET | `/booths` | List booths (filterable by market_id, season_holder_assignment_id, status, size_class) | MarketAdmin, MarketManager, Vendor |
| POST | `/booths/{booth_id}/set-service` | Set a booth out of service or back open | MarketAdmin |
| POST | `/market-days` | Schedule a market day within the season window | MarketAdmin |
| GET | `/market-days/{market_day_id}` | Get a market day including attendance_count | MarketAdmin, MarketManager, Vendor |
| GET | `/market-days` | List market days (filterable by market_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/market-days/{market_day_id}/open` | Open a scheduled market day | MarketAdmin |
| POST | `/market-days/{market_day_id}/close` | Close an open market day (no-show sweep, daily completion, batch close) | MarketAdmin |
| POST | `/market-days/{market_day_id}/cancel` | Cancel a market day with a reason | MarketAdmin |
| POST | `/booth-assignments` | Request a booth assignment (auto-reserve or auto-waitlist) | MarketAdmin, Vendor |
| GET | `/booth-assignments/{assignment_id}` | Get a booth assignment including fee and waitlist_rank | MarketAdmin, MarketManager, Vendor |
| GET | `/booth-assignments` | List assignments (filterable by market_id, booth_id, vendor_id, market_day_id, status, assignment_type) | MarketAdmin, MarketManager, Vendor |
| POST | `/booth-assignments/{assignment_id}/activate` | Activate a reserved assignment | MarketAdmin |
| POST | `/booth-assignments/{assignment_id}/complete` | Complete an assignment; free booth and promote rank-1 waitlister | MarketAdmin |
| POST | `/booth-assignments/{assignment_id}/cancel` | Cancel an assignment; free booth, promote and re-rank waitlist | MarketAdmin, Vendor |
| POST | `/booth-assignments/{assignment_id}/promote` | Promote the rank-1 waitlisted assignment to reserved | MarketAdmin |
| POST | `/check-ins` | Create an expected check-in for an assignment on a day | MarketAdmin, Vendor |
| GET | `/check-ins/{check_in_id}` | Get a check-in | MarketAdmin, MarketManager, Vendor |
| GET | `/check-ins` | List check-ins (filterable by market_id, booth_assignment_id, market_day_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/check-ins/{check_in_id}/arrive` | Mark a check-in present; activates a reserved assignment | MarketAdmin, Vendor |
| POST | `/sales-reports` | Create a draft sales report for a check-in | MarketAdmin, Vendor |
| GET | `/sales-reports/{sales_report_id}` | Get a sales report including commission and reconciled token count | MarketAdmin, MarketManager, Vendor |
| GET | `/sales-reports` | List sales reports (filterable by market_id, check_in_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/sales-reports/{sales_report_id}/submit` | Submit or re-submit a sales report; provisional commission | Vendor |
| POST | `/sales-reports/{sales_report_id}/dispute` | Dispute a submitted sales report | MarketManager |
| POST | `/sales-reports/{sales_report_id}/reconcile` | Reconcile a submitted report; final commission | MarketManager |
| POST | `/voucher-batches` | Issue a batch of tokens for a market day | MarketManager |
| GET | `/voucher-batches/{voucher_batch_id}` | Get a voucher batch including tokens redeemed | MarketAdmin, MarketManager, Vendor |
| GET | `/voucher-batches` | List voucher batches (filterable by market_id, market_day_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/voucher-redemptions` | Submit tokens from a batch for redemption | MarketManager, Vendor |
| GET | `/voucher-redemptions/{redemption_id}` | Get a voucher redemption including reimbursed amount | MarketAdmin, MarketManager, Vendor |
| GET | `/voucher-redemptions` | List redemptions (filterable by market_id, voucher_batch_id, vendor_id, market_day_id, status) | MarketAdmin, MarketManager, Vendor |
| POST | `/voucher-redemptions/{redemption_id}/reconcile` | Reconcile a submitted redemption; lock reimbursement | MarketManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | MarketAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REFERENTIAL_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_OUTSIDE_WINDOW` | 409 |
| `ERR_PERMIT_NOT_VERIFIED` | 409 |
| `ERR_CATEGORY_NOT_ALLOWED` | 409 |
| `ERR_BOOTH_OCCUPIED` | 409 |
| `ERR_TOKEN_OVERDRAW` | 409 |
| `ERR_STALE_BOOTH_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_NO_HEALTH_PERMIT` | 409 |
| `ERR_WAITLIST_NOT_HEAD` | 409 |
| `ERR_DAY_NOT_OPEN` | 409 |
| `ERR_VALIDATION_BOUNDS` | 422 |
| `ERR_SALES_NOT_PRESENT` | 409 |

# Holiday Market API — Product Requirements Document

## 1. Introduction

Downtown holiday markets operate on a compressed calendar: a few weeks of vendor applications, a jury cycle, booth assignment, a short public season punctuated by weather events, and then teardown and settlement. Operators juggle category balance (nobody wants a market that is all candle sellers), premium chalet versus standard booth inventory, temporary structure permits, propane heat safety, shared cashless point-of-sale, and end-of-season renewal offers — all against a fixed public calendar that cannot slip.

This document specifies the Holiday Market API, a multi-tenant seasonal retail platform that manages the full lifecycle from vendor recruitment through next-season renewal. The system coordinates six distinct roles — market operators, vendors, jury members, a jury chair, utility crews, and finance officers — across a seasonal market that progresses through `SETUP`, `OPEN`, `WEATHER_ALERT`, `CLOSED_SEASON`, and `CANCELLED` postures. Every booth commitment, every dollar of shared-POS fee, every heating surcharge, and every renewal discount is computed by deterministic rules described here.

The API is organized around a small number of long-lived aggregates (Markets, Vendors) and a larger set of child resources (Applications, Booths, Assignments, Permits, Utility Hookups, POS Devices, Sales Settlements, Programming Slots, Load Slots, Weather Events, Renewal Offers). A logical clock endpoint exists for test-driving; it accepts `to_iso8601` as the target instant. Before any call to it, the server's logical clock reads exactly `2026-08-01T00:00:00Z` and does not fall back to real wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All requests must carry two HTTP headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role not listed below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes six roles, spelled exactly as follows:

- `MarketOperator` — market staff responsible for overall market operations, booth assignment, permits, POS, programming, load slots, weather, and the ops checkpoint.
- `VendorRole` — a vendor. When `X-User-Role` is `VendorRole`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's `vendor_id` foreign-key field to `X-User-ID`, and a failed ownership check is rejected with `ERR_UNAUTHORIZED` (HTTP 403). In particular, a `VendorRole` caller retrieving a specific application through the nested `/markets/{marketId}/applications/{applicationId}` URL must own it — the application's `vendor_id` must equal `X-User-ID`. The vendor is addressable by `vendorId` in top-level vendor URLs.
- `JuryMember` — scores vendor applications. When `X-User-Role` is `JuryMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as the `juror_id` inside each `jury_scores` entry but does not compare it to any entity's `id`.
- `JuryChair` — decides application outcomes after quorum. When `X-User-Role` is `JuryChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not recorded on any resource.
- `UtilityCrew` — installs, energizes, and decommissions utility hookups. When `X-User-Role` is `UtilityCrew`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `FinanceOfficer` — reconciles and pays settlements. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and has a maximum of 100. `offset` defaults to 0. The `meta` envelope on list responses carries `limit`, `offset`, `total_count`, and `has_more`. All list results are sorted by `created_at` ascending unless otherwise stated.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix, rendered in the canonical hyphenated 8-4-4-4-12 string form (for example `3f6b8d2e-7a1c-4e5b-9c0d-1e2f3a4b5c6d`). Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set at creation and never modified. Every resource carries `updated_at`, also an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation. Every resource carries `version`, an integer that starts at 1 and increments by 1 on every mutation. All entities in this domain carry the full common field set; there are no reduced-field entities. Values supplied by the client for any of these common fields (`id`, `created_at`, `updated_at`, `version`) in a create or update request are ignored; the server always mints and maintains them itself.

### 2.5. Monetary Precision and Rounding

All monetary amounts are represented as integer cents (e.g., `base_rent_cents`, `total_fee_cents`, `gross_card_cents`, `pos_fee_cents`, `net_payable_cents`). Calculations that produce fractional cents round half-up to whole cents, applied once at the end of the calculation — never per-component. The sole exception is the shared-POS fee, which uses floor (round down) semantics, also to whole cents, with no float rounding.

Percentages used in fee configuration are expressed in basis points: a value of 250 means 2.50 percent. The `renewal_score` is the only non-integer computed value; it is rounded half-up to two decimal places.

### 2.6. Derived Posture and the Ops Checkpoint

A market's `posture` is not written directly by any endpoint other than the explicit transitions; it is a derived aggregate computed from a small set of flags and timestamps. The derivation order is pinned: if the market has been cancelled, `posture` is `CANCELLED`; otherwise if the current UTC instant is at or past `closes_at`, `posture` is `CLOSED_SEASON`; otherwise if any `WeatherEvent` within the past 6 hours has `triggers_alert` true, `posture` is `WEATHER_ALERT`; otherwise if the market has been opened, `posture` is `OPEN`; otherwise `posture` is `SETUP`. This posture gates all child operations.

The `run_ops` checkpoint advances the market's `run_ops_index` by 1 and executes a fixed sequence of expiry and transition steps. Operators invoke it explicitly; the system never runs it spontaneously.

### 2.7. Optimistic Concurrency Control

Two write endpoints require optimistic concurrency control. The first is the market open transition: a request to transition a market from `SETUP` to `OPEN` must carry `expected_market_version`, an integer equal to the `Market.version` the client last observed. If the market's current `version` does not match `expected_market_version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing an operator working from a stale market snapshot from re-opening after another operator has already transitioned the market forward.

The second is the application decide transition: a request to decide a `VendorApplication` must carry `expected_application_version`, an integer equal to the `VendorApplication.version` the `JuryChair` last observed. If the application's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A second sequential decide carries a stale `expected_application_version` and is rejected, even though each individual call sees valid preconditions. No other endpoint takes a version field.

### 2.8. Nested Resource Retrieval

For nested URLs, path parameters are validated left-to-right. The server first resolves the market identified by `marketId`, then the child resource within that market — whether `applicationId`, `assignmentId`, `boothId`, `permitId`, `hookupId`, `posDeviceId`, `settlementId`, `slotId`, `loadSlotId`, `weatherEventId`, or `offerId`. If any path-templated resource does not exist — or exists but is scoped to a different market than the one named — the request is rejected with `ERR_NOT_FOUND` (HTTP 404). This applies uniformly: an application under market A addressed through market B's URL is a 404, not a 403.

### 2.9. Validation Ordering

When multiple validation rules apply to a single request, they are evaluated in a fixed priority order. Authentication and role authorization come first (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`). Existence of path-templated resources follows (`ERR_NOT_FOUND`). Then optimistic concurrency (`ERR_STALE_VERSION`). Then market posture (`ERR_POSTURE_FORBIDDEN`). Then entity state validity (`ERR_INVALID_STATE`). Then permit requirements (`ERR_PERMIT_REQUIRED`). Then the application window (`ERR_APPLICATION_WINDOW_CLOSED`). Then slot conflicts (`ERR_SLOT_CONFLICT`). Then category cap (`ERR_CATEGORY_CAP_REACHED`). Then jury quorum (`ERR_JURY_QUORUM_NOT_MET`). Then booth availability (`ERR_BOOTH_UNAVAILABLE`). Then renewal booth availability (`ERR_BOOTH_NO_LONGER_AVAILABLE`). Then settlement uniqueness (`ERR_DUPLICATE_SETTLEMENT`). Then settlement amount validity (`ERR_INVALID_SETTLEMENT_AMOUNTS`). Then payment satisfaction (`ERR_PAYMENT_NOT_SATISFIED`). A request that fails an earlier check never surfaces a later one.

## 3. Business Logic & Workflows

### 3.1. Market Setup and Booth Inventory

A `MarketOperator` creates a market by supplying `name`, `season_code` (a unique per-market string such as `WINTER-2026`), `opens_at` and `closes_at` (the public opening and closing instants, with `closes_at` strictly after `opens_at`), `application_opens_at` and `application_closes_at` (the vendor application window), `jury_quorum` (default 3, the minimum number of jury scores required before an application can be decided), `category_caps` (a map from category code — `FOOD_BEVERAGE`, `CRAFT`, `APPAREL`, `HOME_GOODS`, or `EXPERIENCE` — to maximum accepted vendor count), `chalet_count` and `standard_booth_count` (premium chalet and standard booth inventory), and optionally `shared_pos_enabled` (default true), `shared_pos_fee_bps` (default 250), and `weather_alert_threshold_wind_mph` (default 35). A newly created market starts in `SETUP` posture with `run_ops_index` 0, `total_accepted_vendors` 0, and `total_booths_committed` 0.

Booths are created under a market with a `booth_code` (human-readable, unique per market, e.g. `CH-01` or `STD-A12`), `booth_type` (`STANDARD` or `CHALET`), `zone` (`NORTH`, `SOUTH`, `EAST`, or `WEST`), `square_feet`, and `has_power` (default false, whether the booth supports a utility hookup). A booth starts in `AVAILABLE` status and transitions through `RESERVED`, `OCCUPIED`, or `OFFLINE` as assignments and operations proceed.

### 3.2. Vendor Registration and Application Lifecycle

A `MarketOperator` registers a vendor with `legal_name`, `contact_email` (unique), and `category` (one of the five category codes). A vendor starts in `PROSPECT` status with `no_show_strikes` 0, `lifetime_gross_sales_cents` 0, and `renewal_score` 0.

A vendor (acting as `VendorRole`) creates an application under a market in `DRAFT` status by supplying `vendor_id` (the owning market is recorded as `market_id` by the server), `requested_booth_type` (`STANDARD` or `CHALET`), optionally `requested_pos` (default false) and `heating_requested` (default false, meaningful only when `requested_booth_type` is `CHALET`). The application starts with `jury_scores` empty and `jury_average` null.

Submission transitions the application from `DRAFT` to `SUBMITTED`. Submission is only accepted while the market is in `SETUP` posture and the current UTC instant is between `application_opens_at` and `application_closes_at` inclusive; otherwise it is rejected with `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 409). A vendor may also withdraw from `DRAFT` or `SUBMITTED` at any time, transitioning the application to `WITHDRAWN`.

### 3.3. Jury Scoring and Decision

Once an application is `SUBMITTED`, a `JuryMember` may submit a score by providing `score_0_100` (an integer from 0 to 100). The first score transitions the application from `SUBMITTED` to `UNDER_JURY`, appends `{juror_id, score_0_100}` to `jury_scores`, and recomputes `jury_average` as the mean of all scores. Subsequent scores by other jury members keep the application in `UNDER_JURY`, append to `jury_scores`, and recompute `jury_average`. The system enforces two constraints on scoring: an application may hold at most 5 scores, and a juror who has already scored a given application cannot score it again — a duplicate-juror attempt is rejected with `ERR_JURY_QUORUM_NOT_MET` (HTTP 409).

When at least `jury_quorum` scores have been recorded, a `JuryChair` may decide the application by providing `decision` (one of `ACCEPTED`, `REJECTED`, or `WAITLISTED`) and `expected_application_version`. The decide endpoint is subject to optimistic concurrency control: a stale `expected_application_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). If fewer than `jury_quorum` scores exist, any decide attempt is rejected with `ERR_JURY_QUORUM_NOT_MET` (HTTP 409).

The three decision outcomes have distinct preconditions. An `ACCEPTED` decision requires that `jury_average` is at least 60, and that the number of already-accepted applications in the vendor's `category` is strictly below `category_caps[category]`; if the cap is reached, the attempt is rejected with `ERR_CATEGORY_CAP_REACHED` (HTTP 409). A `REJECTED` decision requires that `jury_average` is below 60. A `WAITLISTED` decision requires that `jury_average` is at least 60 but the category cap has been reached. On any decide, `decided_at` is set to the current UTC instant. On `ACCEPTED`, the market's `total_accepted_vendors` increments by 1, and if the vendor's `status` is currently `PROSPECT`, it transitions to `APPROVED`.

### 3.4. Booth Assignment and Fee Computation

A `MarketOperator` creates a booth assignment by providing `booth_id` and `application_id`. The assignment starts in `PENDING_PAYMENT` status. At creation, the system computes three monetary fields. `base_rent_cents` is derived from a two-dimensional lookup: a base rate in cents determined by `booth_type` crossed with `zone`, multiplied by a season tier. The season tier depends on how many days separate the assignment's `created_at` from the market's `opens_at`: if the assignment is created at least 45 days before opening, the multiplier is 0.85 (early bird); if created 7 days or fewer before opening, the multiplier is 1.20 (late commit); otherwise the multiplier is 1.00. The final `base_rent_cents` is the base rate times the multiplier, rounded half-up to whole cents, with rounding applied once at the end. `heating_surcharge_cents` is 45000 (a $450.00 flat charge) when the application has `heating_requested` true and the booth is a `CHALET`; otherwise it is 0. `total_fee_cents` is the sum of `base_rent_cents` and `heating_surcharge_cents`, exact in whole cents with no additional rounding step.

Activation transitions the assignment from `PENDING_PAYMENT` to `ACTIVE`. Activation requires that the linked application is `ACCEPTED`, that no other `ACTIVE` assignment exists on the same booth, and that the market's `posture` is `SETUP` or `OPEN`. If the application is not `ACCEPTED`, the attempt is rejected with `ERR_PAYMENT_NOT_SATISFIED` (HTTP 409). If the booth is not `AVAILABLE`, the attempt is rejected with `ERR_BOOTH_UNAVAILABLE` (HTTP 409). On activation, the booth's `status` transitions to `RESERVED` and the market's `total_booths_committed` increments by 1.

An `ACTIVE` assignment may be released by an operator, which transitions it to `RELEASED`, returns the booth to `AVAILABLE`, and decrements `total_booths_committed` by 1. Manual release requires that all `SalesSettlement` records for the assignment are in `RECONCILED` or `PAID` status. An `ACTIVE` assignment may also be forfeited by an operator providing a `reason` of `NO_SHOW`, `PERMIT_REVOKED`, or `OPERATOR_EJECTION`. Forfeiture transitions the assignment to `FORFEITED`, returns the booth to `AVAILABLE`, decrements `total_booths_committed` by 1, and — only when `reason` is `NO_SHOW` — increments the vendor's `no_show_strikes` by 1.

### 3.5. Permits, Utility Hookups, and Safety Gating

Permits are issued by a `MarketOperator` for a specific assignment by supplying `assignment_id`, `permit_type` (`TEMP_STRUCTURE`, `FOOD_SERVICE`, `PROPANE_HEAT`, or `GENERATOR`), `issued_by` (an authority identifier such as the city fire department), `issued_at`, and `expires_at` (strictly after `issued_at`). A permit starts in `ACTIVE` status and may transition to `EXPIRED` (automatically during `run_ops` when the current UTC instant is at or past `expires_at`) or `REVOKED` (by operator action). Both transitions carry the same side effect: if the permit is a `TEMP_STRUCTURE` permit and a booth assignment is linked, the assignment transitions to `FORFEITED` with reason `PERMIT_REVOKED`.

Utility hookups are requested by `UtilityCrew` for a booth by providing `booth_id` and `hookup_type` (`ELECTRIC_15A`, `ELECTRIC_30A`, `WATER`, or `PROPANE`). A hookup starts in `REQUESTED` status with `amps_drawn` 0. Installation transitions it to `INSTALLED`; installation requires the market to be in `SETUP` posture, and for `ELECTRIC_15A` or `ELECTRIC_30A` the booth's `has_power` must be true — otherwise rejected with `ERR_BOOTH_UNAVAILABLE` (HTTP 409). Energizing transitions an `INSTALLED` hookup to `ENERGIZED`; energizing requires the market to be in `SETUP` or `OPEN` posture, and for `PROPANE` hookups it additionally requires an `ACTIVE` `PROPANE_HEAT` permit for the same booth's `ACTIVE` assignment — otherwise rejected with `ERR_PERMIT_REQUIRED` (HTTP 409). Decommissioning transitions an `ENERGIZED` hookup to `DECOMMISSIONED`; it is permitted when the market is in `WEATHER_ALERT` or `CLOSED_SEASON` posture, or when the linked assignment is `RELEASED` or `FORFEITED`.

### 3.6. Shared POS and Daily Settlement

A `MarketOperator` provisions a POS device for an assignment by providing `assignment_id` and `device_code` (unique per market). The device starts in `PROVISIONED` status. Activation transitions it to `ACTIVE` and requires the linked assignment to be `ACTIVE`, the market's `shared_pos_enabled` to be true (otherwise rejected with `ERR_NO_SHARED_POS`, HTTP 409), and the market's `posture` to be `OPEN` (otherwise rejected with `ERR_POSTURE_FORBIDDEN`, HTTP 409).

A device in `ACTIVE` may be suspended (transitioning to `SUSPENDED`) either manually by an operator or automatically when the market enters `WEATHER_ALERT`. A `SUSPENDED` device may be re-activated (transitioning back to `ACTIVE`) either manually or automatically when the market returns from `WEATHER_ALERT` to `OPEN`; re-activation requires the market's `posture` to be `OPEN`. A device in `ACTIVE` or `SUSPENDED` may be returned (transitioning to `RETURNED`), but only if no `DRAFT` or `SUBMITTED` sales settlement exists for the assignment — otherwise rejected with `ERR_DEVICE_HAS_OPEN_SETTLEMENTS` (HTTP 409).

A vendor creates a sales settlement for an assignment and a `business_date` (an ISO-8601 calendar date in `YYYY-MM-DD` format) by supplying `assignment_id`, `business_date`, `gross_card_cents`, `gross_cash_cents`, and optionally `refund_cents` (default 0). At creation, the system computes `pos_fee_cents` and `net_payable_cents` and sets the status to `DRAFT`. The POS fee is computed as follows: when the market's `shared_pos_enabled` is true and an `ACTIVE` POS device exists for the assignment, `pos_fee_cents` is the floor of `gross_card_cents` multiplied by `shared_pos_fee_bps` divided by 10000; otherwise `pos_fee_cents` is 0. `net_payable_cents` is `gross_card_cents` plus `gross_cash_cents` minus `refund_cents` minus `pos_fee_cents`. The system validates that `gross_card_cents` and `gross_cash_cents` are non-negative, that `refund_cents` does not exceed the sum of the two gross fields, and that all amounts are integer cents; violations are rejected with `ERR_INVALID_SETTLEMENT_AMOUNTS` (HTTP 422).

A vendor may update a `DRAFT` settlement's `gross_card_cents`, `gross_cash_cents`, or `refund_cents`; the system recomputes `pos_fee_cents` and `net_payable_cents` on each update.

Submission transitions the settlement from `DRAFT` to `SUBMITTED`. Submission requires the market's `posture` to be `OPEN` or `WEATHER_ALERT` and requires that no other `SUBMITTED` settlement exists for the same `assignment_id` and `business_date` — a duplicate is rejected with `ERR_DUPLICATE_SETTLEMENT` (HTTP 409). On submission, the vendor's `lifetime_gross_sales_cents` increases by `gross_card_cents` plus `gross_cash_cents` minus `refund_cents`.

A `FinanceOfficer` reconciles a `SUBMITTED` settlement, transitioning it to `RECONCILED`. Reconciliation requires the market's `posture` to be `OPEN`, `WEATHER_ALERT`, or `CLOSED_SEASON`. On reconciliation, the vendor's `renewal_score` is recomputed. A `FinanceOfficer` may also dispute a `SUBMITTED` settlement (transitioning it to `DISPUTED`) or pay a `RECONCILED` settlement (transitioning it to `PAID`).

The market-level end-of-day reconciliation report uses a different POS-fee aggregation: the floor is applied to the sum of `gross_card_cents` across all settlements for the day, which can differ from the sum of per-row floors by up to (number of rows minus one) cents. The per-row floor is authoritative for the `DRAFT` and `SUBMITTED` settlement rows themselves.

### 3.7. Programming, Load Slots, and Weather

A `MarketOperator` schedules a programming slot by providing `title`, `slot_kind` (`MUSIC`, `DEMO`, `SANTA_PHOTOS`, `WORKSHOP`, or `PARADE`), `starts_at`, `ends_at` (strictly after `starts_at`), and optionally `vendor_id`. The slot starts in `SCHEDULED` status. The system rejects any programming slot whose interval overlaps an existing slot of the same kind on the same market and vendor, or whose `starts_at` is not before `ends_at`, with `ERR_SLOT_CONFLICT` (HTTP 409).

A `SCHEDULED` slot transitions to `LIVE` automatically when the current UTC instant reaches `starts_at` and the market is `OPEN`. A `LIVE` slot transitions to `COMPLETED` automatically when the current UTC instant reaches `ends_at` and the market is `OPEN`. An operator may cancel a `SCHEDULED` slot at any time, transitioning it to `CANCELLED`. When the market enters `WEATHER_ALERT`, any `SCHEDULED` slot of kind `PARADE` is automatically cancelled, and any `LIVE` slot regardless of kind is automatically cancelled.

Load slots reserve a loading window for an assignment. An operator creates one by providing `assignment_id`, `direction` (`LOAD_IN` or `LOAD_OUT`), `starts_at`, and `ends_at`. The slot starts in `RESERVED` status. The same slot-conflict rules apply: overlapping intervals on the same market and booth key are rejected with `ERR_SLOT_CONFLICT` (HTTP 409). A vendor checks in to a reserved slot between 30 minutes before `starts_at` and `ends_at`, transitioning it to `CHECKED_IN`. A vendor completes a checked-in slot at or before 60 minutes after `ends_at`, transitioning it to `COMPLETED`. During `run_ops`, any slot still in `RESERVED` whose `ends_at` has passed transitions to `NO_SHOW`, the vendor's `no_show_strikes` increments by 1, and the vendor's `renewal_score` is recomputed.

Weather events are recorded by a `MarketOperator` with `observed_at`, `wind_mph`, `temp_f`, `precipitation` (`NONE`, `RAIN`, `SNOW`, or `ICE`), and `source` (`NWS`, `ON_SITE_SENSOR`, or `OPERATOR`). The system computes `triggers_alert` as true when `wind_mph` is at or above the market's `weather_alert_threshold_wind_mph` or when `precipitation` is `ICE`; otherwise false. When a new weather event has `triggers_alert` true and the market's `posture` is `OPEN`, the market automatically transitions to `WEATHER_ALERT`, all `ACTIVE` POS devices on the market transition to `SUSPENDED`, and `Market.version` increments by 1. When the market is in `WEATHER_ALERT` and no weather event with `observed_at` in the past 6 hours has `triggers_alert` true — the window is the inclusive interval from 6 hours ago up to the current instant, so an event whose `observed_at` lies in the future does not count — an operator may clear the alert, transitioning the market back to `OPEN`, re-activating all `SUSPENDED` POS devices to `ACTIVE`, and incrementing `Market.version` by 1.

### 3.8. Market Open, Cancel, and Season Close

Opening a market transitions it from `SETUP` to `OPEN`. The request must carry `expected_market_version` matching the market's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Opening requires the current UTC instant to be at or after 7 days before `opens_at`, at least one `ACTIVE` booth assignment to exist, and no weather event with `observed_at` in the past 6 hours (the same inclusive window as §3.7) with `triggers_alert` true. On opening, the market's `posture` becomes `OPEN` and `Market.version` increments by 1.

Cancelling a market is only permitted from `SETUP`. Cancellation transitions the market to `CANCELLED`, all applications in `DRAFT`, `SUBMITTED`, `UNDER_JURY`, or `WAITLISTED` to `WITHDRAWN`, and all assignments in `PENDING_PAYMENT` or `ACTIVE` to `FORFEITED`. `Market.version` increments by 1.

Season close is automatic: when the market is `OPEN` and the current UTC instant reaches `closes_at`, the market transitions to `CLOSED_SEASON`. Every `ACTIVE` booth assignment transitions to `RELEASED` and its booth returns to `AVAILABLE`. Every `ACTIVE` POS device transitions to `RETURNED`. Every `SUBMITTED` sales settlement transitions to `RECONCILED`. `Market.version` increments by 1.

### 3.9. The Ops Checkpoint

The ops checkpoint is the market's periodic housekeeping pass. Invoking it increments `run_ops_index` by 1 and then executes five steps in pinned order. First, any booth assignment still in `PENDING_PAYMENT` that has been in that state for at least 3 ops runs transitions to `FORFEITED` and the vendor's `no_show_strikes` increments by 1. Second, any `ACTIVE` permit whose `expires_at` is at or before the current UTC instant transitions to `EXPIRED`, which may cascade a linked `TEMP_STRUCTURE` assignment to `FORFEITED`. Third, any `EXTENDED` renewal offer whose `offer_expires_at` is at or before the current UTC instant transitions to `EXPIRED`. Fourth, any `RESERVED` load slot whose `ends_at` has passed transitions to `NO_SHOW`, with the vendor's `no_show_strikes` incrementing by 1 and `renewal_score` recomputed. Fifth, if the market is `OPEN` and the current UTC instant is at or past `closes_at`, the market transitions to `CLOSED_SEASON` with all cascades described in §3.8.

### 3.10. Renewal Offers

A `MarketOperator` extends a renewal offer to a vendor for the next season's market by providing `vendor_id`, `prior_assignment_id`, `offered_booth_id`, and `offer_expires_at`. The offer starts in `EXTENDED` status. At creation, the system computes `discount_pct` from the vendor's `renewal_score` band: a score of 80 or above yields 20 percent; 60 to 79 yields 15 percent; 40 to 59 yields 10 percent; 20 to 39 yields 5 percent; below 20 yields 0 percent.

The vendor's `renewal_score` is a composite value between 0 and 100, recomputed whenever a settlement is reconciled, a load slot goes `NO_SHOW`, or an assignment is forfeited with reason `NO_SHOW`. The score is the sum of three components. The sales component is the lesser of 50 and the vendor's `lifetime_gross_sales_cents` divided by 200000 (so $100,000 in lifetime gross sales yields the full 50 points). The reliability component is the greater of 0 and 30 minus 10 times the vendor's `no_show_strikes`. The jury component is the vendor's most recent `jury_average` divided by 100 and multiplied by 20, or 0 if no jury average exists. The final `renewal_score` is rounded half-up to two decimal places.

A vendor accepts a renewal offer before `offer_expires_at`, provided the offered booth is still `AVAILABLE`; if the booth has since been reserved or occupied, the acceptance is rejected with `ERR_BOOTH_NO_LONGER_AVAILABLE` (HTTP 409). On acceptance, the offered booth transitions to `RESERVED`, a new `VendorApplication` is auto-created for the vendor in the new market with status `ACCEPTED` (skipping jury), and a new `BoothAssignment` is auto-created for the new application and offered booth with status `PENDING_PAYMENT`. A vendor may also decline an `EXTENDED` offer, transitioning it to `DECLINED`. During `run_ops`, any `EXTENDED` offer whose `offer_expires_at` has passed transitions to `EXPIRED` with no booth reservation made.

## 4. Endpoint Definitions

All endpoints are mounted under the `/markets` prefix unless otherwise noted. New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200. Authentication, authorization, existence, state, and business validations are applied in the priority order described in §2.9.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | `/markets` | Create a new Market (in SETUP posture) | `MarketOperator` |
| GET | `/markets/{marketId}` | Get a specific Market | `MarketOperator`, `VendorRole`, `JuryMember`, `JuryChair`, `UtilityCrew`, `FinanceOfficer` |
| GET | `/markets` | List markets (paginated, filterable by `season_code`, `posture`) | `MarketOperator`, `VendorRole`, `JuryMember`, `JuryChair`, `UtilityCrew`, `FinanceOfficer` |
| POST | `/markets/{marketId}/open_market` | Transition Market SETUP → OPEN (OCC via `expected_market_version`) | `MarketOperator` |
| POST | `/markets/{marketId}/clear_weather_alert` | Transition Market WEATHER_ALERT → OPEN | `MarketOperator` |
| POST | `/markets/{marketId}/cancel` | Cancel a Market (SETUP only) | `MarketOperator` |
| POST | `/markets/{marketId}/run_ops` | Advance the ops checkpoint | `MarketOperator` |
| POST | `/vendors` | Register a Vendor | `MarketOperator` |
| GET | `/vendors/{vendorId}` | Get a specific Vendor | `MarketOperator`, `VendorRole`, `JuryChair`, `FinanceOfficer` |
| GET | `/vendors` | List vendors (paginated; filterable by `category`, `status`) | `MarketOperator`, `JuryChair`, `FinanceOfficer` |
| POST | `/markets/{marketId}/applications` | Create a VendorApplication in DRAFT | `VendorRole` |
| GET | `/markets/{marketId}/applications/{applicationId}` | Get a specific application | `MarketOperator`, `VendorRole`, `JuryMember`, `JuryChair` |
| GET | `/markets/{marketId}/applications` | List applications for a market (filterable by `status`, `category`) | `MarketOperator`, `JuryMember`, `JuryChair` |
| POST | `/markets/{marketId}/applications/{applicationId}/submit` | Vendor submits their application (DRAFT → SUBMITTED) | `VendorRole` |
| POST | `/markets/{marketId}/applications/{applicationId}/score` | JuryMember submits a score (0-100) for the application | `JuryMember` |
| POST | `/markets/{marketId}/applications/{applicationId}/decide` | JuryChair decides ACCEPTED / REJECTED / WAITLISTED (OCC via `expected_application_version`) | `JuryChair` |
| POST | `/markets/{marketId}/applications/{applicationId}/withdraw` | Vendor withdraws their application | `VendorRole` |
| POST | `/markets/{marketId}/booths` | Create a Booth | `MarketOperator` |
| GET | `/markets/{marketId}/booths/{boothId}` | Get a Booth | `MarketOperator`, `VendorRole`, `JuryChair`, `UtilityCrew` |
| GET | `/markets/{marketId}/booths` | List booths for a market (filterable by `status`, `booth_type`, `zone`) | `MarketOperator`, `VendorRole`, `JuryChair`, `UtilityCrew` |
| POST | `/markets/{marketId}/assignments` | Create a BoothAssignment (PENDING_PAYMENT) | `MarketOperator` |
| GET | `/markets/{marketId}/assignments/{assignmentId}` | Get a specific BoothAssignment | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/{marketId}/assignments` | List assignments (filterable by `status`, `booth_id`, `application_id`) | `MarketOperator`, `FinanceOfficer` |
| POST | `/markets/{marketId}/assignments/{assignmentId}/activate` | Transition BoothAssignment PENDING_PAYMENT → ACTIVE | `MarketOperator` |
| POST | `/markets/{marketId}/assignments/{assignmentId}/release` | Operator releases an ACTIVE BoothAssignment | `MarketOperator` |
| POST | `/markets/{marketId}/assignments/{assignmentId}/forfeit` | Operator forfeits an ACTIVE BoothAssignment with a `reason` | `MarketOperator` |
| POST | `/markets/{marketId}/permits` | Issue a Permit for an assignment | `MarketOperator` |
| GET | `/markets/{marketId}/permits/{permitId}` | Get a Permit | `MarketOperator`, `VendorRole`, `UtilityCrew` |
| GET | `/markets/{marketId}/permits` | List permits (filterable by `status`, `permit_type`, `assignment_id`) | `MarketOperator`, `UtilityCrew` |
| POST | `/markets/{marketId}/permits/{permitId}/revoke` | Revoke an ACTIVE Permit | `MarketOperator` |
| POST | `/markets/{marketId}/hookups` | Request a UtilityHookup | `UtilityCrew` |
| GET | `/markets/{marketId}/hookups/{hookupId}` | Get a UtilityHookup | `MarketOperator`, `UtilityCrew` |
| GET | `/markets/{marketId}/hookups` | List hookups (filterable by `status`, `hookup_type`, `booth_id`) | `MarketOperator`, `UtilityCrew` |
| POST | `/markets/{marketId}/hookups/{hookupId}/install` | Mark hookup INSTALLED | `UtilityCrew` |
| POST | `/markets/{marketId}/hookups/{hookupId}/energize` | Mark hookup ENERGIZED (permit-gated for some types) | `UtilityCrew` |
| POST | `/markets/{marketId}/hookups/{hookupId}/decommission` | Mark hookup DECOMMISSIONED | `UtilityCrew` |
| POST | `/markets/{marketId}/pos_devices` | Provision a PosDevice | `MarketOperator` |
| GET | `/markets/{marketId}/pos_devices/{posDeviceId}` | Get a PosDevice | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/{marketId}/pos_devices` | List POS devices (filterable by `status`, `assignment_id`) | `MarketOperator`, `FinanceOfficer` |
| POST | `/markets/{marketId}/pos_devices/{posDeviceId}/activate` | PROVISIONED/SUSPENDED → ACTIVE | `MarketOperator` |
| POST | `/markets/{marketId}/pos_devices/{posDeviceId}/suspend` | ACTIVE → SUSPENDED | `MarketOperator` |
| POST | `/markets/{marketId}/pos_devices/{posDeviceId}/return_device` | ACTIVE/SUSPENDED → RETURNED | `MarketOperator` |
| POST | `/markets/{marketId}/settlements` | Vendor creates a DRAFT SalesSettlement for an assignment and date | `VendorRole` |
| GET | `/markets/{marketId}/settlements/{settlementId}` | Get a SalesSettlement | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/{marketId}/settlements` | List settlements (filterable by `status`, `assignment_id`, `business_date`) | `MarketOperator`, `FinanceOfficer` |
| PUT | `/markets/{marketId}/settlements/{settlementId}` | Update a DRAFT settlement's amounts | `VendorRole` |
| POST | `/markets/{marketId}/settlements/{settlementId}/submit` | DRAFT → SUBMITTED | `VendorRole` |
| POST | `/markets/{marketId}/settlements/{settlementId}/reconcile` | SUBMITTED → RECONCILED | `FinanceOfficer` |
| POST | `/markets/{marketId}/settlements/{settlementId}/dispute` | SUBMITTED → DISPUTED | `FinanceOfficer` |
| POST | `/markets/{marketId}/settlements/{settlementId}/pay` | RECONCILED → PAID | `FinanceOfficer` |
| POST | `/markets/{marketId}/programming` | Schedule a ProgrammingSlot | `MarketOperator` |
| GET | `/markets/{marketId}/programming/{slotId}` | Get a ProgrammingSlot | `MarketOperator`, `VendorRole` |
| GET | `/markets/{marketId}/programming` | List programming (filterable by `status`, `slot_kind`, `vendor_id`) | `MarketOperator`, `VendorRole` |
| POST | `/markets/{marketId}/programming/{slotId}/cancel` | Cancel a SCHEDULED slot | `MarketOperator` |
| POST | `/markets/{marketId}/load_slots` | Reserve a LoadSlot for an assignment | `MarketOperator` |
| GET | `/markets/{marketId}/load_slots/{loadSlotId}` | Get a LoadSlot | `MarketOperator`, `VendorRole` |
| GET | `/markets/{marketId}/load_slots` | List load slots (filterable by `status`, `assignment_id`, `direction`) | `MarketOperator`, `VendorRole` |
| POST | `/markets/{marketId}/load_slots/{loadSlotId}/check_in` | Vendor checks in to a load slot | `VendorRole` |
| POST | `/markets/{marketId}/load_slots/{loadSlotId}/complete` | Vendor completes a load slot | `VendorRole` |
| POST | `/markets/{marketId}/weather_events` | Record a WeatherEvent; may flip market posture to WEATHER_ALERT | `MarketOperator` |
| GET | `/markets/{marketId}/weather_events/{weatherEventId}` | Get a WeatherEvent | `MarketOperator`, `VendorRole`, `UtilityCrew` |
| GET | `/markets/{marketId}/weather_events` | List weather events (filterable by `triggers_alert`, `source`) | `MarketOperator`, `UtilityCrew` |
| POST | `/markets/{marketId}/renewal_offers` | Extend a RenewalOffer to a vendor for the NEXT season's market | `MarketOperator` |
| GET | `/markets/{marketId}/renewal_offers/{offerId}` | Get a RenewalOffer | `MarketOperator`, `VendorRole` |
| GET | `/markets/{marketId}/renewal_offers` | List renewal offers (filterable by `status`, `vendor_id`) | `MarketOperator`, `VendorRole` |
| POST | `/markets/{marketId}/renewal_offers/{offerId}/accept` | Vendor accepts a RenewalOffer | `VendorRole` |
| POST | `/markets/{marketId}/renewal_offers/{offerId}/decline` | Vendor declines a RenewalOffer | `VendorRole` |
| GET | `/markets/applications` | List all applications across markets | `MarketOperator`, `JuryMember`, `JuryChair` |
| GET | `/markets/booths` | List all booths across markets | `MarketOperator`, `VendorRole`, `JuryChair`, `UtilityCrew` |
| GET | `/markets/assignments` | List all assignments across markets | `MarketOperator`, `FinanceOfficer` |
| GET | `/markets/permits` | List all permits across markets | `MarketOperator`, `UtilityCrew` |
| GET | `/markets/hookups` | List all hookups across markets | `MarketOperator`, `UtilityCrew` |
| GET | `/markets/pos_devices` | List all POS devices across markets | `MarketOperator`, `FinanceOfficer` |
| GET | `/markets/settlements` | List all settlements across markets | `MarketOperator`, `FinanceOfficer` |
| GET | `/markets/programming` | List all programming slots across markets | `MarketOperator`, `VendorRole` |
| GET | `/markets/load_slots` | List all load slots across markets | `MarketOperator`, `VendorRole` |
| GET | `/markets/weather_events` | List all weather events across markets | `MarketOperator`, `UtilityCrew` |
| GET | `/markets/renewal_offers` | List all renewal offers across markets | `MarketOperator`, `VendorRole` |
| GET | `/markets/applications/{applicationId}` | Get a specific application by id (top-level) | `MarketOperator`, `VendorRole`, `JuryMember`, `JuryChair` |
| GET | `/markets/booths/{boothId}` | Get a specific booth by id (top-level) | `MarketOperator`, `VendorRole`, `JuryChair`, `UtilityCrew` |
| GET | `/markets/assignments/{assignmentId}` | Get a specific assignment by id (top-level) | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/permits/{permitId}` | Get a specific permit by id (top-level) | `MarketOperator`, `VendorRole`, `UtilityCrew` |
| GET | `/markets/hookups/{hookupId}` | Get a specific hookup by id (top-level) | `MarketOperator`, `UtilityCrew` |
| GET | `/markets/pos_devices/{posDeviceId}` | Get a specific POS device by id (top-level) | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/settlements/{settlementId}` | Get a specific settlement by id (top-level) | `MarketOperator`, `VendorRole`, `FinanceOfficer` |
| GET | `/markets/programming/{slotId}` | Get a specific programming slot by id (top-level) | `MarketOperator`, `VendorRole` |
| GET | `/markets/load_slots/{loadSlotId}` | Get a specific load slot by id (top-level) | `MarketOperator`, `VendorRole` |
| GET | `/markets/weather_events/{weatherEventId}` | Get a specific weather event by id (top-level) | `MarketOperator`, `VendorRole`, `UtilityCrew` |
| GET | `/markets/renewal_offers/{offerId}` | Get a specific renewal offer by id (top-level) | `MarketOperator`, `VendorRole` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to the supplied ISO-8601 UTC instant | `MarketOperator` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POSTURE_FORBIDDEN` | 409 |
| `ERR_PERMIT_REQUIRED` | 409 |
| `ERR_APPLICATION_WINDOW_CLOSED` | 409 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_CATEGORY_CAP_REACHED` | 409 |
| `ERR_JURY_QUORUM_NOT_MET` | 409 |
| `ERR_BOOTH_UNAVAILABLE` | 409 |
| `ERR_BOOTH_NO_LONGER_AVAILABLE` | 409 |
| `ERR_DUPLICATE_SETTLEMENT` | 409 |
| `ERR_INVALID_SETTLEMENT_AMOUNTS` | 422 |
| `ERR_PAYMENT_NOT_SATISFIED` | 409 |
| `ERR_NO_SHARED_POS` | 409 |
| `ERR_DEVICE_HAS_OPEN_SETTLEMENTS` | 409 |

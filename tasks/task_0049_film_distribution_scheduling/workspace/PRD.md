# Film Distribution Scheduling API — Product Requirements Document

## 1. Introduction

Theatrical film distribution sits at the intersection of three operational worlds that rarely speak the same language: distributors who plan release windows months in advance and need to enforce minimum exposure per region, cinema operators who treat screens as a scarce minute-by-minute resource that must be packed efficiently around cleaning crews and peak-hour audience patterns, and a ticketing platform whose buyer behavior — including bulk-buying anomalies — can move millions of cents of pre-sale revenue overnight. Today these workflows are stitched together with spreadsheets, email, and overnight batch reconciliations, which means a cancelled show on Friday night surfaces as a contested settlement entry the following Wednesday and a bulk-buyer abusing a promo code is detected only after the receipts have already been split.

This document specifies a single REST API, mounted under the `/films` namespace and rooted at the platform domain, that consolidates these workflows into one immediate-consistency system. The API governs the full life of a release — film registration, regional rollout, automatic showtime arrangement against screen operating constraints, real-time pre-sale tracking with anomaly interception, distributor/cinema/platform revenue allocation with refund-induced reversals, and the inbound event channel by which the ticketing platform, the payment processor, and the cinema-management upstream feed authoritative state. Every state-changing action is auditable, every settlement is append-only, and every cascade from a single distributor decision (delisting a film, for example) is fully reified across the schedule, the ticket book, the ledger, and the notification archive.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than `GET /_meta/health` must carry two HTTP headers: `X-User-ID` and `X-User-Role`. Either header missing or empty produces a 401 response with `error_id` `ERR_AUTH_HEADERS_MISSING`. If both headers are present but the role is not authorized for the endpoint, the response is 403 with `ERR_ROLE_FORBIDDEN`.

There are six roles, listed here with their exact spelling and the binding between `X-User-ID` and the system's persisted entities:

- `PlatformAdmin` — the platform operator who manages distributors and runs the test-harness endpoints. `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditLog`) but does not compare it to any entity's `id`.
- `DistributorOps` — a distributor user who runs film lifecycle actions. When `X-User-Role` is `DistributorOps`, `X-User-ID` is the `id` of the acting `Distributor`; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`.
- `CinemaOps` — a cinema operator who manages cinemas, screens, and showtimes and may refund or exchange tickets. When `X-User-Role` is `CinemaOps`, `X-User-ID` is the `id` of the acting `Cinema`; ownership checks on any resource that references a `Cinema` compare the resource's foreign-key field to `X-User-ID`.
- `TicketingPlatform` — the upstream ticketing platform that purchases tickets, refunds and exchanges them, and posts external sync events. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditLog` but performs no entity match against it.
- `FinanceOps` — the finance operator who manages the settlement ledger. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditLog` but performs no entity match against it.
- `Auditor` — a strictly read-only role with access to every `GET` endpoint. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

Every list endpoint accepts two query-string controls: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside that closed-closed range are rejected as `ERR_BAD_REQUEST`. `offset` defaults to 0 and must be at least 0. The default sort order on every list endpoint is `created_at` ascending — the oldest row appears first — and this order is stable across page boundaries. The response `meta` block carries the request's `limit` and `offset` echoed back, along with `total_count` (the total number of rows that match the active filter, before pagination) and `has_more` (true when `offset + limit < total_count`, false otherwise).

### 2.4. Common Resource Properties

Every persisted entity exposes an `id` that is a server-minted UUID with no type prefix and no client-supplied content. Most entities — `Distributor`, `Film`, `Cinema`, `Screen`, `Showtime`, `Ticket` — also carry the full set of common audit fields: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer starting at 1 that increments by exactly one on every successful mutation of the row. `created_at` is fixed at creation and never moves. `updated_at` is refreshed on every successful mutation to the server clock at the time the mutation commits.

Five entities are append-only ledgers or archives and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent on them: `Settlement`, `ScheduleAdjustment`, `AnomalyAlert`, `ExternalEvent`, and `AuditLog`. For `Settlement`, `created_at` is additionally immutable from the moment the row is written, and the same immutability holds for `ScheduleAdjustment.archived_at`, `ScheduleAdjustment.created_at`, `AnomalyAlert.created_at`, `ExternalEvent.created_at`, and `AuditLog.created_at`.

### 2.5. Nested Resource Retrieval and Path Validation

URL path parameters are validated strictly from left to right. For `/cinemas/{cinema_id}/screens` and `/screens/{screen_id}/showtimes`, the parent resource must be looked up first; if the parent is missing the response is 404 `ERR_NOT_FOUND` and no deeper checks run. Once parents resolve, any foreign-key field carried in the request body (`film_id`, `screen_id`, `distributor_id`, `showtime_id`, `exchanged_to_showtime_id`, `parent_settlement_id`) must resolve to an existing row; otherwise the response is 404 `ERR_REFERENCED_ENTITY_NOT_FOUND`. These two existence checks always precede any state, format, or business-rule check.

### 2.6. Optimistic Concurrency Control

Mutating endpoints — every action endpoint that transitions state, and every refund/exchange/cancel/post — accept an optional `version` field in the request body. If `version` is supplied and does not match the current `version` on the target row, the request is rejected with `ERR_VERSION_CONFLICT` (409); if `version` is omitted, the check is skipped and the mutation applies optimistically to whatever row state the server currently holds. Repeating the same action twice with the same `version` against a target whose `version` has already advanced past it (because the first call succeeded) is rejected with `ERR_DUPLICATE_OPERATION` (409); this is how settlement post, ticket refund, and ticket exchange become idempotent under retry. On every successful mutation, the server increments `version` by one and refreshes `updated_at`.

### 2.7. Precision, Rounding, and Money Arithmetic

All monetary amounts are stored and transmitted as integer cents — there are no fractional cents anywhere in the system. Time-of-day fields are stored as integer minute-of-day values in the closed range 0 to 1439 unless explicitly noted otherwise (operating-hours end allows 1440 as the exclusive next-day boundary). Rates expressed in basis points (`default_split_ratio_bps`, `attendance_rate_bps`, `LOW_ATTENDANCE_THRESHOLD_BPS`, `PLATFORM_COMMISSION_BPS`, `TAX_BPS`, `PROMO_DISTRIBUTOR_BPS_OVERRIDE`) are integers from 0 to 10000, where 10000 represents 100 percent. Every rounding step in the settlement waterfall uses round-half-up to the nearest integer cent. The attendance computation that gates low-attendance cancellation deliberately uses floor (integer) division on basis points, so the boundary is pinned exactly. All boundary comparisons throughout the spec are exact: where the prose says "at least" or "no less than", the comparison is inclusive on both sides; where it says "strictly less than" or "below", the boundary value itself does not qualify.

### 2.8. Cascade Consistency and Append-Only Ledger Discipline

When a film is delisted, when a film is shelved, and when a showtime is cancelled, mutations propagate down the entity tree in a fixed order. Whenever a mutation propagates, every touched mutable entity has its `version` incremented and its `updated_at` refreshed at the same logical instant the parent's change commits, so a reader that observes the parent's new state will also observe the children's new state. Settlement, by contrast, is append-only: a `POSTING` row that needs to be undone is never edited or deleted in place; instead a sibling `REVERSAL` row is appended that points back at the original via `parent_settlement_id`. The `POSTING` row's `status` only transitions to `REVERSED` once the sum of compensating `REVERSAL` rows referencing it brings its net contribution to zero. `ScheduleAdjustment`, `AnomalyAlert`, `ExternalEvent`, and `AuditLog` are likewise append-only — they are never updated after the row is written, with the single exception that `ExternalEvent.applied` flips from false to true once the inbound event handler has run.

### 2.9. Validation Priority Order

When multiple validation conditions could fail on a single request, exactly one error is returned, and the choice follows a fixed priority order. From highest to lowest priority: authentication header presence (`ERR_AUTH_HEADERS_MISSING`), role authorization (`ERR_ROLE_FORBIDDEN`), URL-path existence (`ERR_NOT_FOUND`), request-body foreign-key existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`), state-machine transition admissibility (`ERR_INVALID_STATE`), cross-entity film-not-released (`ERR_FILM_NOT_RELEASED`), cross-entity showtime-not-completed (`ERR_SHOWTIME_NOT_COMPLETED`), pre-sale anomaly safety (`ERR_PRESALE_ANOMALY_DETECTED`), format matching (`ERR_SCREEN_FORMAT_MISMATCH`), region strategy and tier cap (`ERR_REGION_STRATEGY_VIOLATION`), screen time conflict (`ERR_SCREEN_TIME_CONFLICT`), operating hours (`ERR_OUTSIDE_OPERATING_HOURS`), competing-film peak coordination (`ERR_COMPETING_FILM_CONFLICT`), seat capacity (`ERR_SEAT_CAPACITY_EXCEEDED`), per-buyer hard cap (`ERR_PER_BUYER_LIMIT_EXCEEDED`), distributor weekly minimum (`ERR_MIN_SHOW_COUNT_BREACH`), duplicate-operation idempotency (`ERR_DUPLICATE_OPERATION`), and finally optimistic-concurrency `version` mismatch (`ERR_VERSION_CONFLICT`). The malformed-body error `ERR_BAD_REQUEST` short-circuits everything below the auth checks and is returned whenever a request body fails type-level parsing — missing required fields, wrong types, out-of-range integers, or unknown enum values.

A consequence worth calling out: the pre-sale anomaly check sits above the per-buyer hard cap. When a single ticket purchase would simultaneously breach the rolling-window or cumulative anomaly threshold and the per-buyer hard cap, the response is `ERR_PRESALE_ANOMALY_DETECTED` and an `AnomalyAlert` is recorded; the per-buyer-cap rejection is suppressed in that case.

### 2.10. Server Clock and the Sweep

The system relies on a server clock for all release-window comparisons, pre-sale gating, in-progress and completed transitions, and the rolling 60-minute anomaly window. In test mode the clock can be advanced — but never rewound — by submitting an ISO 8601 instant as `to_timestamp`. An attempt to set the clock to an instant at or before the current clock fails with `ERR_CLOCK_REGRESS` (422). A separate sweep capability scans all `Showtime` rows and applies the system-actor transitions on `sale_status` and `lifecycle_status` whose time preconditions are now satisfied, plus an `AuditLog` entry per sweep run. The same time-driven sale-status transition can also fire lazily on a ticket-purchase attempt that arrives after `presale_opens_at` has passed but before any explicit sweep has run.

## 3. Business Logic & Workflows

### 3.1. Distributor Onboarding and Film Registration

A new distributor is created with `name`, `contact_email`, the integer `default_split_ratio_bps` that will govern how net revenue is shared between distributor and cinema on every settlement, and `min_show_count_per_week` that pins the minimum number of weekly showings any cinema must run for any film carrying this distributor's label. The created row starts at `status` `ACTIVE`; an `INACTIVE` distributor cannot have a `PLANNED` film promoted out of plan.

Films are registered by `DistributorOps` against an active distributor. The request supplies a `title`, the foreign key `distributor_id`, a positive integer `duration_minutes`, a `rating` chosen from `G`, `PG`, `PG13`, `R`, or `NC17`, a `format` chosen from `2D`, `3D`, or `IMAX`, and a `release_date` that is the earliest moment the title may be sold publicly. A film released in multiple formats is registered as separate `Film` rows, one per format — there is no multi-format `Film`. The `region_strategy` object on each film names the set of `allowed_regions` (region codes that match a cinema's `region_code`) and a per-tier cap map `tier_caps` keyed by `TIER_1`, `TIER_2`, and `TIER_3` that limits how many cinemas in each tier may simultaneously host this film. On creation, the new `Film` row starts at `status` `PLANNED` with `shelved_reason` absent.

### 3.2. The Film Release Lifecycle

A `Film` follows a four-state lifecycle: `PLANNED`, `RELEASED`, `SHELVED`, and the terminal `DELISTED`. Promotion from `PLANNED` to `RELEASED` is initiated by `DistributorOps` and is allowed only once the server clock has reached `release_date` and the parent `Distributor.status` is `ACTIVE`; if the clock is still earlier than `release_date` the transition is rejected with `ERR_INVALID_STATE`. On a successful release, `status` flips to `RELEASED`, any previously recorded `shelved_reason` is cleared, `updated_at` is refreshed, and an `AuditLog` row is emitted with `action` `FILM_RELEASE`.

Shelving — `RELEASED → SHELVED` — is a soft pause invoked by `DistributorOps` with a free-text `reason` that the server records on the film's `shelved_reason`. A film may only be shelved while it has at least one `Showtime` whose `lifecycle_status` is either `SCHEDULED` or `IN_PROGRESS`; without active downstream demand the shelve action is rejected with `ERR_INVALID_STATE`. On a successful shelve, every future showtime for the film whose `lifecycle_status` is `SCHEDULED` has its `sale_status` flipped from `PRESALE` or `ON_SALE` to `CLOSED` (so new ticket purchases are blocked), while `lifecycle_status` itself remains `SCHEDULED`. An `AuditLog` row with `action` `FILM_SHELVE` is emitted.

The reverse transition `SHELVED → RELEASED` re-uses the release action and again requires that `release_date` has been reached. On a successful re-release, `shelved_reason` is cleared, and every showtime that was closed purely because of the shelving — those still in `lifecycle_status` `SCHEDULED` — reopens its `sale_status` according to the same `presale_opens_at` rule used at creation time: showtimes whose `presale_opens_at` has already passed move directly to `ON_SALE`, while those whose `presale_opens_at` is still in the future return to `PRESALE`. An `AuditLog` row with `action` `FILM_RELEASE` is emitted on re-release as well.

Delisting is the terminal step and may be invoked from `PLANNED`, `RELEASED`, or `SHELVED`. There are no business preconditions on delisting itself — a distributor may pull a title at any time before, during, or after release. The delist cascade fires in four hops in this order. First, every `Showtime` belonging to the film whose `lifecycle_status` is `SCHEDULED` is force-cancelled — `lifecycle_status` becomes `CANCELLED`, `sale_status` becomes `CLOSED`, and `cancel_reason` is set to `INCIDENT` (a delist never uses `NEW_FILM_INSERTION` as its cancel reason). Second, every `VALID` `Ticket` on those cancelled showtimes has its `status` set to `REFUNDED` and `refunded_at` set to the server clock. Third, for each refunded ticket whose original `POSTING` `Settlement` row is in `status` `POSTED`, a compensating `REVERSAL` row is appended with `kind` `REVERSAL` and `parent_settlement_id` pointing at the original `POSTING`. Fourth, one `ScheduleAdjustment` row is archived per cancelled showtime with `adjustment_type` `CANCEL`, `reason` `INCIDENT`, the snapshot `affected_ticket_ids` list populated, and `notifications_dispatched` set to the count of ticket-holder notifications emitted. An `AuditLog` row with `action` `FILM_DELIST` finalizes the cascade.

### 3.3. Cinema, Screen, and Operating Constraints

`CinemaOps` registers a `Cinema` with `name`, a `region_code`, a `tier` chosen from `TIER_1`, `TIER_2`, or `TIER_3`, and the cinema-wide peak window defined by `peak_window_start_minute` and `peak_window_end_minute`. The peak window is half-open on the right — `peak_window_start_minute` is inclusive and `peak_window_end_minute` is exclusive — and both are minute-of-day values in the closed range 0 through 1439. The default peak window runs from minute 1080 (6:00 PM) to minute 1380 (11:00 PM).

Each cinema hosts one or more `Screen` rows. A screen carries a human-readable `label`, the array `supported_formats` listing which of `2D`, `3D`, and `IMAX` it can project, an `operating_start_minute` (inclusive) and `operating_end_minute` (exclusive) bounding when the screen can run, a `cleaning_interval_minutes` between consecutive shows that defaults to 15, a `trailer_minutes` count defaulting to 10, an `ad_minutes` count defaulting to 5, and a positive integer `seat_capacity`. `operating_end_minute` must be strictly greater than `operating_start_minute` and may take the value 1440 to indicate the end of the operating day; show finishing exactly at `operating_end_minute` is allowed.

### 3.4. Automatic Showtime Arrangement

`CinemaOps` schedules a showtime against a specific screen by supplying the `film_id`, an integer `start_minute` (the minute-of-day at which the ad block begins), a `business_date` carrying the calendar date the screening belongs to as a midnight ISO 8601 timestamp, the per-seat `ticket_price_cents`, and the `presale_opens_at` instant. The cinema's `cinema_id` is denormalised onto the showtime from the parent screen, and the film's `distributor_id` is denormalised at creation time so subsequent revenue-split and competing-film queries do not need to re-join the film. New showtimes are born with `lifecycle_status` `SCHEDULED` and `sale_status` `PRESALE`; `tickets_sold_count`, `tickets_refunded_count`, `gross_box_office_cents` start at zero, and `anomaly_flag` starts false. An `AuditLog` row with `action` `SHOWTIME_CREATE` is emitted on successful creation.

Before the row is written, the server pins two derived integers using a fixed combinatorial rule. The base length of the show block is the film's `duration_minutes` plus the screen's `trailer_minutes` plus the screen's `ad_minutes`. To that base, a format-specific setup overhead is added: 5 minutes for `IMAX`, 3 minutes for `3D`, and 0 minutes for `2D`. The resulting sum is stored on the showtime as `block_minutes`. The derived `end_minute` is exactly `start_minute` plus `block_minutes`; cleaning time is deliberately not part of `block_minutes` because cleaning is enforced separately as adjacency, not as occupied minutes.

Five admissibility checks are evaluated on every showtime creation, in the order listed (this is the relative priority among them): first the film's format must appear in the screen's `supported_formats` array, or the response is `ERR_SCREEN_FORMAT_MISMATCH` (422). Second, the region strategy must admit this cinema — the cinema's `region_code` must be present in the film's `region_strategy.allowed_regions`, and the count of cinemas in this cinema's tier that already host this film in a state of `SCHEDULED` or later must be strictly less than `region_strategy.tier_caps` for this tier; either failure returns `ERR_REGION_STRATEGY_VIOLATION` (422). Third, the proposed run must not conflict on the screen: for every other showtime on the same screen and same `business_date` whose `lifecycle_status` is not `CANCELLED`, the half-open interval starting at the other show's `start_minute` and running through that show's `end_minute` plus the screen's `cleaning_interval_minutes` (the cleaning buffer is attached to the right side of the earlier showtime) must not overlap with the proposed half-open interval `[start_minute, end_minute)`; any overlap returns `ERR_SCREEN_TIME_CONFLICT` (409). Fourth, the proposed run must fit inside operating hours: `start_minute` must be at least `operating_start_minute`, and `end_minute` must be no greater than `operating_end_minute` — note the right boundary is inclusive on the show's end, so a film that finishes exactly at `operating_end_minute` is admitted, while a film that finishes one minute later is rejected with `ERR_OUTSIDE_OPERATING_HOURS` (422). Fifth, competing-film coordination caps the cinema's peak density: counting only point-membership of `start_minute` against the cinema's closed-closed peak window inclusion (a show's `start_minute` is in the peak window if it lies between `peak_window_start_minute` and `peak_window_end_minute` inclusive on both ends, despite the half-open semantics used for the peak window definition elsewhere), at most one showtime per `distributor_id` per `business_date` is permitted to start inside that window for the cinema; the second start in the window from the same distributor is rejected with `ERR_COMPETING_FILM_CONFLICT` (409).

Two scheduling calls that race to create overlapping showtimes on the same screen serialize first-writer-wins on the `(screen_id, business_date, start_minute)` tuple; the loser receives `ERR_SCREEN_TIME_CONFLICT`.

### 3.5. Pre-Sale Opening and Anomaly Interception

A new showtime sits in `sale_status` `PRESALE` until the server clock crosses `presale_opens_at`, at which point the system actor transitions `sale_status` to `ON_SALE` — provided the parent `Film.status` is `RELEASED`. If the film is not yet `RELEASED` when the clock crosses `presale_opens_at`, the transition is suppressed and any ticket purchase attempt fails with `ERR_FILM_NOT_RELEASED`. The transition can fire one of two ways: explicitly during a sweep run, or lazily on the first ticket-purchase attempt that arrives after `presale_opens_at` and finds the showtime still in `PRESALE`. A purchase attempt arriving before `presale_opens_at` is rejected with `ERR_PRESALE_NOT_OPEN`.

`TicketingPlatform` purchases a ticket against a specific showtime by supplying the `buyer_external_id`, a non-negative integer `paid_amount_cents`, and optionally a `promo_code`. The server stamps `purchased_at` to the current clock, mints the ticket `id`, and writes the row with `status` `VALID`. Two hard fiscal limits guard every purchase. First, the total count of `VALID` tickets on the showtime must not equal the screen's `seat_capacity` at the moment of insert — strictly inclusive on the boundary so the (seat_capacity)-th sale succeeds and the (seat_capacity + 1)-th sale is rejected with `ERR_SEAT_CAPACITY_EXCEEDED`. Two simultaneous purchases racing for the last seat serialize first-writer-wins on the `tickets_sold_count` increment and the loser receives `ERR_SEAT_CAPACITY_EXCEEDED`. Second, the count of `VALID` tickets for the same `showtime_id` and same `buyer_external_id` must remain strictly less than the per-buyer hard cap of 20 tickets — the 20th sale to a single buyer is admitted, the 21st is rejected with `ERR_PER_BUYER_LIMIT_EXCEEDED`.

Pre-sale anomaly detection runs on every purchase before the row is persisted. Two parallel rules evaluate against the same `Tickets` input domain filtered by `showtime_id`, `buyer_external_id`, and `status` `VALID`. The rolling-window rule counts the number of such tickets whose `purchased_at` lies within the last 60 minutes inclusive of the current server clock; if this count would reach 10 or more with the proposed ticket included, the rule trips with `rule` `ROLLING_WINDOW`. The cumulative rule counts the total number of such tickets without any time bound; if this count would reach 30 or more with the proposed ticket included, the rule trips with `rule` `CUMULATIVE`. When either rule trips, the proposed ticket is not persisted (no `Ticket` row is written, `tickets_sold_count` is not incremented, and `gross_box_office_cents` is unchanged), an `AnomalyAlert` is appended with the `showtime_id`, `buyer_external_id`, the `rule` that fired, and the `triggering_count` that breached the threshold, and the response is `ERR_PRESALE_ANOMALY_DETECTED`. The showtime's `anomaly_flag` is set to true on the first trip. The two rules apply at the same priority level, with rolling-window evaluated before cumulative; when both would trip simultaneously, the `AnomalyAlert.rule` recorded is `ROLLING_WINDOW`. As noted in §2.9, the anomaly check sits above the per-buyer cap — when both fire on the same request, the response is `ERR_PRESALE_ANOMALY_DETECTED`.

After a successful purchase, `tickets_sold_count` and `gross_box_office_cents` on the showtime are recomputed: `tickets_sold_count` is the count of tickets on this showtime whose `status` is `VALID`, `tickets_refunded_count` is the count whose `status` is `REFUNDED` or `EXCHANGED`, and `gross_box_office_cents` is the sum of `paid_amount_cents` over the tickets whose `status` is `VALID`.

### 3.6. Showtime Execution and Closure

Once a showtime is in `lifecycle_status` `SCHEDULED` and the server clock reaches `business_date` plus `start_minute`, the system actor transitions it to `IN_PROGRESS` and simultaneously closes sales by setting `sale_status` to `CLOSED`; this transition requires `Film.status` to be `RELEASED`. When the clock further reaches `business_date` plus `end_minute`, the system actor transitions `lifecycle_status` from `IN_PROGRESS` to `COMPLETED`, which unblocks the downstream settlement post. Both transitions are observable as side effects of running the sweep capability and produce no `AuditLog` rows of their own (the sweep itself emits a `SWEEP_RUN` audit entry).

When a showtime transitions to `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, its `sale_status` becomes `CLOSED` as a paired side effect. Any subsequent ticket purchase against the showtime is rejected with `ERR_SHOWTIME_NOT_ON_SALE`. A purchase that raced against a cancel and committed first is included in the cascade refund; a purchase that arrives after the cancel commits sees `sale_status` as `CLOSED` and is rejected — this is how the cancel-versus-purchase race is serialized.

### 3.7. Show Adjustment by Cinema Cancellation

`CinemaOps` cancels a `SCHEDULED` showtime by supplying a `cancel_reason` chosen from `LOW_ATTENDANCE`, `NEW_FILM_INSERTION`, and `INCIDENT`, an optional `exchange_to_showtime_id` (which is supplied as the request-body key `exchange_to_showtime_id` whose value names the replacement showtime; if supplied, every affected ticket is exchanged rather than refunded onto that target instead of refunded), and the standard `version` field. A cancel is only admitted when `lifecycle_status` is `SCHEDULED` — cancelling an `IN_PROGRESS` or already-`CANCELLED` show fails with `ERR_INVALID_STATE`.

`LOW_ATTENDANCE` carries a fiscal precondition. The maximum possible revenue for the showtime is `seat_capacity` multiplied by `ticket_price_cents`. The attendance rate, expressed in basis points, is `gross_box_office_cents` multiplied by 10000 and then divided by the maximum possible revenue using integer (floor) division; the resulting `attendance_rate_bps` must be strictly less than 1500 (15.00 percent) for the `LOW_ATTENDANCE` cancellation to be admitted. Boundary precision matters here: a showtime whose `attendance_rate_bps` computes to exactly 1500 does not qualify, and the cancel attempt is rejected with `ERR_INVALID_STATE`. `NEW_FILM_INSERTION` and `INCIDENT` have no fiscal precondition.

A separate gating check runs at cancel time against the distributor weekly minimum. For the ISO-week (in the form `'YYYY-Www'`, e.g. `'2026-W19'`) containing the cancelled showtime's `business_date`, the server counts every other showtime on the same `cinema_id` whose film carries the same `distributor_id` and whose `lifecycle_status` is in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` (cancelled showtimes are excluded from the count, and the showtime currently being cancelled is also excluded). If that count would fall strictly below the distributor's `min_show_count_per_week` after the cancel, the cancel is rejected with `ERR_MIN_SHOW_COUNT_BREACH` — unless `cancel_reason` is `INCIDENT`, which acts as a force-majeure override that bypasses this check. `LOW_ATTENDANCE` and `NEW_FILM_INSERTION` do not bypass it. This breach check sits above the duplicate-operation idempotency check in priority order, so a retry of the same cancel against a showtime that was already cancelled but still violates the minimum returns `ERR_MIN_SHOW_COUNT_BREACH` rather than `ERR_DUPLICATE_OPERATION`.

The cascade on a successful cancel fires in this order. The showtime's `lifecycle_status` becomes `CANCELLED`, its `sale_status` becomes `CLOSED`, and its `cancel_reason` is stored. Every `VALID` `Ticket` on the showtime has its `status` set to `REFUNDED` (or `EXCHANGED` with `exchanged_to_showtime_id` populated to the supplied target, if `exchange_to_showtime_id` was provided in the request) and `refunded_at` set to the current clock; in the `EXCHANGED` path a new child `Ticket` is also created on the destination showtime carrying the original `paid_amount_cents` and `promo_code`. For each refunded or exchanged ticket whose original `POSTING` `Settlement` was in `status` `POSTED`, a `REVERSAL` row is appended with `kind` `REVERSAL` and `parent_settlement_id` pointing at the original. One `ScheduleAdjustment` row is archived with `adjustment_type` `CANCEL`, `reason` matching the supplied `cancel_reason`, the snapshot `affected_ticket_ids` populated, `notifications_dispatched` set to the count of holder notifications emitted, and `archived_at` stamped to the current clock alongside the row's `created_at`. An `AuditLog` row with `action` `SHOWTIME_CANCEL` finalizes the operation. When `NEW_FILM_INSERTION` is used and a replacement showtime is created in the freed slot as a follow-up scheduling call, that creation produces an additional `ScheduleAdjustment` row with `adjustment_type` `INSERTION`. Exchange paths additionally produce an `EXCHANGE_TARGET` `ScheduleAdjustment` row tagged with the destination showtime's `id`.

### 3.8. Ticket Compensation: Refund and Exchange

Outside of a showtime cancel, individual `VALID` tickets may be refunded or exchanged by `TicketingPlatform` or `CinemaOps`. A refund supplies the standard `version` field; the original `Ticket.status` becomes `REFUNDED`, `refunded_at` is stamped to the current clock, the parent showtime's `gross_box_office_cents` is recomputed, and if the showtime's `POSTING` `Settlement` is already in `status` `POSTED`, a compensating `REVERSAL` row is appended with `parent_settlement_id` pointing at it; when the running sum of `REVERSAL` rows under that `POSTING` brings its net to zero, the `POSTING` row's `status` advances to `REVERSED`. An `AuditLog` row with `action` `TICKET_REFUND` is emitted. A refund against a ticket that is already `REFUNDED`, already `EXCHANGED`, or whose showtime has moved beyond the refund grace window is rejected with `ERR_TICKET_NOT_REFUNDABLE`.

An exchange takes `version` plus the request-body field `exchanged_to_showtime_id` naming the destination showtime. The destination must be in `lifecycle_status` `SCHEDULED`, its `sale_status` must be in `PRESALE` or `ON_SALE`, and its format and per-seat price must be compatible with the original; otherwise the response is `ERR_EXCHANGE_TARGET_INVALID`. On a successful exchange, the original ticket's `status` is set to `EXCHANGED`, `refunded_at` is stamped, and `exchanged_to_showtime_id` is recorded on the original row; a new child ticket is created on the destination carrying forward `paid_amount_cents` and `promo_code`. If the original ticket's `POSTING` `Settlement` is `POSTED`, a `REVERSAL` row is appended in the same way as a refund. An `AuditLog` row with `action` `TICKET_EXCHANGE` is emitted. Retrying the same refund or exchange action with the same `version` against a target whose `version` has already advanced past it is rejected with `ERR_DUPLICATE_OPERATION`.

### 3.9. Revenue Split, Settlement Posting, and Reversal

Settlement is the append-only ledger that records how each completed showtime's gross box-office is divided among the ticketing platform, the tax authority, the distributor, and the cinema. `FinanceOps` creates a draft posting against a showtime by supplying the `showtime_id` and the `cycle_label` (an ISO-week identifier such as `'2026-W19'`). The resulting `Settlement` row is born with `kind` `POSTING` and `status` `DRAFT`, and the split numbers are computed at creation time from the showtime's current set of `VALID` tickets. The draft can only be promoted from `DRAFT` to `POSTED` by an explicit post action that supplies the standard `version` field; the post is admitted only when the parent showtime's `lifecycle_status` is `COMPLETED` — otherwise the response is `ERR_SHOWTIME_NOT_COMPLETED`. An `AuditLog` row with `action` `SETTLEMENT_POST` is emitted on a successful post.

The split itself is computed in a fixed, non-reorderable sequence of seven steps. Step one: for each `VALID` ticket in the evaluation set, compute that ticket's contribution to the platform commission as the ticket's `paid_amount_cents` multiplied by `PLATFORM_COMMISSION_BPS` (800 basis points, or 8 percent) divided by 10000, rounded half-up to the nearest integer cent. Step two: sum every ticket's `paid_amount_cents` to produce the source `gross_cents`. Step three: sum the per-ticket commissions from step one to produce `platform_commission_cents` — this is round-then-sum, not sum-then-round, and that ordering matters when the ticket count is large. Step four: compute `net_after_platform` as `gross_cents` minus `platform_commission_cents`. Step five: compute `tax_cents` as `net_after_platform` multiplied by `TAX_BPS` (600 basis points, or 6 percent) divided by 10000, rounded half-up once at this single point. Step six: compute the effective distributor share in basis points — if any ticket in the evaluation set carries a non-empty `promo_code`, the effective share is `PROMO_DISTRIBUTOR_BPS_OVERRIDE` (5000 basis points, or 50/50), otherwise it is the distributor's `default_split_ratio_bps`; then `distributor_amount_cents` is `net_after_tax` (which is `net_after_platform` minus `tax_cents`) multiplied by the effective bps divided by 10000, rounded half-up. Step seven: `cinema_amount_cents` is the waterfall remainder, equal to `net_after_tax` minus `distributor_amount_cents`. The invariant the engine guarantees is that `distributor_amount_cents` plus `cinema_amount_cents` plus `tax_cents` plus `platform_commission_cents` equals `gross_cents` exactly, with no fractional residue.

The same formula has two variants. The posting variant runs at `POSTING` creation time over the full set of `VALID` tickets present on the showtime at that instant; `platform_commission_cents` is the sum of per-ticket rounded values and `gross_cents` reflects every current `VALID` ticket. The reversal variant runs when a single ticket is refunded or exchanged and the parent `POSTING` is in `status` `POSTED`: the evaluation set is exactly that one ticket, `gross_cents` enters the ledger as the negative of the refunded ticket's `paid_amount_cents`, and `platform_commission_cents` is computed on that single ticket — so a reversal subtracts exactly that ticket's rounded share of the platform commission rather than recomputing a fresh slice of a hypothetical net total. Because per-ticket rounding occurs before the sum and because promo eligibility is re-evaluated on the reduced set when a non-promo ticket is reversed away from a promo-bearing showtime, the provisional posting numbers and the final (posting net of reversals) numbers can differ — this is the intended behavior, not an arithmetic bug.

A settlement post that races against a ticket refund for the same showtime is serialized by optimistic concurrency on the showtime's `version`; one of the two operations wins and the other receives `ERR_VERSION_CONFLICT` (409) and is expected to retry against the new state. The same `ERR_VERSION_CONFLICT` (409) is the loser for any race on `Film` mutations — release, shelve, or delist racing each other or a competing edit on the same film row also serialize first-writer-wins on `Film.version`, and the loser receives `ERR_VERSION_CONFLICT`. A duplicate post action — same `settlement_id`, same `version` — repeated after the first succeeded is rejected with `ERR_DUPLICATE_OPERATION`.

The `POSTING` row's `status` only transitions to `REVERSED` when the system detects that the sum across all `REVERSAL` rows referencing this `POSTING` (each carrying its share as a negative `gross_cents`) plus this `POSTING`'s `gross_cents` equals zero. When that condition holds, the system actor sets the `POSTING`'s `status` to `REVERSED` and emits an `AuditLog` row with `action` `SETTLEMENT_REVERSE`. `REVERSAL` rows themselves are born in `status` `POSTED` (they are immutable ledger entries) and never further transition.

### 3.10. Inbound Event Synchronization and Operational Observability

External upstream systems push events into the API through a single inbound event channel. Each inbound event carries a `kind` of `TICKETING_PLATFORM`, `PAYMENT`, or `CINEMA_MGMT`, plus a free-form `payload` object whose shape is documented per upstream system. The server persists the event with `applied` false, runs its handler, and flips `applied` to true once the handler completes; this two-step persistence is the only field on `ExternalEvent` that is ever mutated after creation.

Every state-changing action on `Film`, `Showtime`, `Ticket`, and `Settlement`, plus every clock advance and every sweep run, appends an `AuditLog` row. The row records the acting `actor_role` and `actor_id` (the values of `X-User-Role` and `X-User-ID` at the time), the `action` enum that names the change (one of `FILM_RELEASE`, `FILM_SHELVE`, `FILM_DELIST`, `SHOWTIME_CREATE`, `SHOWTIME_CANCEL`, `SETTLEMENT_POST`, `SETTLEMENT_REVERSE`, `TICKET_REFUND`, `TICKET_EXCHANGE`, `CLOCK_ADVANCE`, or `SWEEP_RUN`), the `target_entity` name and `target_id` of the mutated row, and a `payload_snapshot` of the relevant fields after the action. Read-only listings of audit entries support filtering by `action`, `target_entity`, and `target_id`. Similarly, `AnomalyAlert` listings filter by `showtime_id`, `buyer_external_id`, and `rule`; `ScheduleAdjustment` listings filter by `showtime_id`, `reason`, and `adjustment_type`; `Settlement` listings filter by `cycle_label`, `showtime_id`, `kind`, and `status`; and `Showtime` listings filter by `cinema_id`, `film_id`, `business_date`, `lifecycle_status`, and `sale_status`.

## 4. Endpoint Definitions

Endpoint creation calls return HTTP 201 with the created resource in the envelope's `data`. Endpoint read calls, list calls, and action calls that mutate an existing resource return HTTP 200. Validation, state, and business-rule failures use the error codes catalogued in §5 with their nominal HTTP status. The table below names every endpoint, its HTTP contract, a one-line description, and the roles authorized to call it; request and response shapes are reconstructed from the narrative in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/distributors` | Create distributor (starts ACTIVE) | `PlatformAdmin` |
| GET | `/distributors/{distributor_id}` | Read distributor | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/films` | Create film (defaults to PLANNED) | `DistributorOps` |
| GET | `/films/{film_id}` | Read film | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/films/{film_id}/release` | Promote film PLANNED→RELEASED or SHELVED→RELEASED | `DistributorOps` |
| POST | `/films/{film_id}/shelve` | Transition film RELEASED→SHELVED | `DistributorOps` |
| POST | `/films/{film_id}/delist` | Transition film to DELISTED with cascade | `DistributorOps` |
| POST | `/cinemas` | Create cinema | `CinemaOps` |
| GET | `/cinemas/{cinema_id}` | Read cinema | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/cinemas/{cinema_id}/screens` | Create screen under cinema | `CinemaOps` |
| GET | `/screens/{screen_id}` | Read screen | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/screens/{screen_id}/showtimes` | Schedule a new showtime on a screen | `CinemaOps` |
| GET | `/showtimes/{showtime_id}` | Read showtime with computed aggregates | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| GET | `/showtimes` | List showtimes with filters | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/showtimes/{showtime_id}/cancel` | Cancel a SCHEDULED showtime with cascade | `CinemaOps` |
| POST | `/showtimes/{showtime_id}/tickets` | Purchase a ticket | `TicketingPlatform` |
| GET | `/tickets/{ticket_id}` | Read ticket | `PlatformAdmin`, `TicketingPlatform`, `CinemaOps`, `FinanceOps`, `Auditor` |
| POST | `/tickets/{ticket_id}/refund` | Refund a VALID ticket | `TicketingPlatform`, `CinemaOps` |
| POST | `/tickets/{ticket_id}/exchange` | Exchange a VALID ticket onto a new showtime | `TicketingPlatform`, `CinemaOps` |
| POST | `/settlements` | Create DRAFT POSTING settlement for a completed showtime | `FinanceOps` |
| POST | `/settlements/{settlement_id}/post` | Transition settlement DRAFT→POSTED | `FinanceOps` |
| GET | `/settlements/{settlement_id}` | Read settlement | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| GET | `/settlements` | List settlements with filters | `PlatformAdmin`, `DistributorOps`, `CinemaOps`, `FinanceOps`, `Auditor` |
| GET | `/anomaly-alerts` | List anomaly alerts with filters | `PlatformAdmin`, `CinemaOps`, `FinanceOps`, `Auditor` |
| GET | `/schedule-adjustments` | List archived schedule adjustments | `PlatformAdmin`, `CinemaOps`, `FinanceOps`, `Auditor` |
| GET | `/audit-logs` | List audit log entries | `PlatformAdmin`, `Auditor` |
| POST | `/_clock/advance` | Test harness — advance server clock to a given ISO 8601 instant | `PlatformAdmin` |
| POST | `/_sweep/run` | Test harness — run system sweep | `PlatformAdmin` |
| POST | `/_events/external` | Test harness — accept an inbound event | `PlatformAdmin`, `TicketingPlatform` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_HEADERS_MISSING` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FILM_NOT_RELEASED` | 409 |
| `ERR_SHOWTIME_NOT_COMPLETED` | 409 |
| `ERR_SHOWTIME_NOT_ON_SALE` | 409 |
| `ERR_PRESALE_ANOMALY_DETECTED` | 409 |
| `ERR_SCREEN_FORMAT_MISMATCH` | 422 |
| `ERR_REGION_STRATEGY_VIOLATION` | 422 |
| `ERR_SCREEN_TIME_CONFLICT` | 409 |
| `ERR_OUTSIDE_OPERATING_HOURS` | 422 |
| `ERR_COMPETING_FILM_CONFLICT` | 409 |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 409 |
| `ERR_PER_BUYER_LIMIT_EXCEEDED` | 409 |
| `ERR_MIN_SHOW_COUNT_BREACH` | 409 |
| `ERR_DUPLICATE_OPERATION` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_CLOCK_REGRESS` | 422 |
| `ERR_PRESALE_NOT_OPEN` | 409 |
| `ERR_TICKET_NOT_REFUNDABLE` | 409 |
| `ERR_EXCHANGE_TARGET_INVALID` | 422 |

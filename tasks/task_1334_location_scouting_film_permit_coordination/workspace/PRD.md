# Location Film Permits API — Product Requirements Document

## 1. Introduction

Film productions live or die by their locations, and every day spent on a street, in a house, or on a sidewalk is a negotiated, permitted, insured, and auditable event. A location manager must scout a site and assemble a photo package, negotiate a day rate with the property owner, file a permit application with the governing jurisdiction inside its lead-time window, notify the neighborhood within a mandated radius, present insurance certificates that satisfy the jurisdiction's liability floor, post a restoration deposit, staff police or fire monitors when lanes close, and then survive the shoot day itself — complaints, overtime, no-show officers and all. The film office on the other side of the counter reviews packages, opens and decides permit applications, verifies insurance, confirms monitor staffing, and settles damage claims against the deposit after the final walkthrough.

This document specifies the Location Film Permits API, the system of record for that entire lifecycle. It governs a production from `PREP` through its first ready shoot day (which flips the production to `ACTIVE`) to final wrap, and it coordinates the interests of three parties — the production-side location manager, the jurisdiction film office, and the property owner's representative — under segregation of duties: the party that proposes a day rate is never the party that counters it, and the party that films a location is never the party that settles the damage claim against it. Because permit work is deadline-driven, the API runs on a server-side logical clock rather than wall-clock time; lead-time arithmetic, notification adequacy, closure windows, certificate lapse, complaint escalation, and permit expiry are all evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly three roles: `LocationManager`, `FilmOffice`, and `OwnerRep`. A request whose `X-User-Role` header is missing or does not name one of these three roles, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role and are normative. When `X-User-Role` is `LocationManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `FilmOffice`: `X-User-ID` is an opaque staff identifier with no entity backing. When `X-User-Role` is `OwnerRep`, `X-User-ID` is the `id` of the acting `LocationOwner`; ownership checks on any resource that references a `LocationOwner` compare the resource's foreign-key field to `X-User-ID`.

A `LocationManager` is the production-side operator: they create productions, register owners and locations, book locations, assemble scout packages, negotiate owner agreements, file and amend permit applications, request street closures, record notifications, present insurance certificates, fund deposit accounts, author walkthrough reports, assign monitors, plan and run shoot days, and wrap or cancel the production. A `FilmOffice` operator is the jurisdiction's staff: they configure and suspend jurisdictions, review scout packages, start review on and decide permit applications, approve street closures, acknowledge notifications, verify or reject insurance certificates, settle deposit accounts, confirm, release, check in, and mark no-show monitors, shut down shoot days, and drive the logical clock and the operations sweep. An `OwnerRep` is the property owner's representative: they counter proposals, accept proposed agreements, dispute post-shoot walkthrough reports, and file complaints. Complaint filing is shared across all three roles; agreement acceptance and walk-away are shared between `LocationManager` and `OwnerRep` with the acting role determined by which side of the table is currently holding the offer; complaint resolution is shared between `LocationManager` (from `ACKNOWLEDGED`) and `FilmOffice` (from `ESCALATED`). All three roles share read access on every GET endpoint.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — Production, Jurisdiction, Location, LocationOwner, LocationBooking, ScoutPackage, OwnerAgreement, PermitApplication, StreetClosure, NotificationRecord, InsuranceCertificate, DepositAccount, WalkthroughReport, MonitorAssignment, ShootDay, and Complaint — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including mutations driven by cascades that originate on a different resource.

Because every entity in this system carries the full common set, any state change — whether client-initiated or fired automatically by a cascade or the operations sweep — advances `version` and refreshes `updated_at` on the mutated resource.

### 2.5. The Logical Clock and the Operations Sweep

Time in this system is a server-maintained logical clock, never wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit adjustment it continues to read that default; it never silently falls back to real time. A `FilmOffice` operator may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the current time as `now`. Server-stamped fields throughout the system — a permit application's `submitted_at`, a notification's `posted_at`, a complaint's `filed_at` — are all taken from this clock.

A second `FilmOffice` capability, the operations sweep, advances the system epoch in one call and returns the number of mutated records as `swept`. The sweep is the mechanism behind every time-triggered transition in the system: it expires `ISSUED` permit applications whose `shoot_end_date` has passed without any shoot day reaching `IN_PROGRESS` (moving them to `EXPIRED` and cancelling their still-`REQUESTED` or `APPROVED` street closures), lapses `VERIFIED` insurance certificates whose `expiry_date` has passed (to `LAPSED`), escalates `OPEN` complaints whose response deadline has passed (to `ESCALATED`, firing the shut-down cascade when the complaint is `CRITICAL` against an in-progress day), moves an `APPROVED` street closure to `ACTIVE` when the clock reaches its `closure_start` and on to `COMPLETED` when the clock reaches its `closure_end`, and moves a `READY` shoot day to `IN_PROGRESS` when the clock reaches its `shoot_date`.

### 2.6. Optimistic Concurrency Control

Two write operations in this API consume derived state that other writers advance, and both are protected by mandatory optimistic concurrency control. Endpoints not listed here do not take a version field.

First, creating a permit application — most critically an amendment whose `amendment_of_id` supersedes an existing application — mutates the parent Production as part of the supersede cascade: the Production's `version` advances. A create request must therefore carry `expected_production_version` holding the client's last observed `version` of the Production. If that value does not match the Production's current `version` — because another writer has advanced the Production since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's view of which applications are live is stale.

Second, marking a shoot day ready consumes derived state — `monitors_confirmed`, deposit posture, certificate status — that other writers advance. The mark-ready request must carry `expected_shoot_day_version` holding the client's last observed `version` of the ShootDay. A mismatch against the day's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the day and re-check the entire gate set before retrying.

### 2.7. Nested Resource Retrieval and Validation Order

Most production-scoped resources live under a nested path such as `/productions/{id}/shoot-days/{rid}`. The system validates path identifiers sequentially, left to right: the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier — parent `{id}` or child `{rid}` — that does not exist or does not belong to the enclosing production's scope, before any business rule is evaluated. Cross-scope read aliases exist so that a permit application and a shoot day are also retrievable directly by their own identifier, without naming the production.

Requests across the API are checked in a fixed precedence order: authentication of the headers first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence and production-scope of every path identifier (`ERR_NOT_FOUND`), then the optimistic-concurrency version check where the endpoint requires one (`ERR_STALE_VERSION`), then whether the target resource's current state permits the requested transition at all (`ERR_INVALID_STATE`), then the business-rule checks specific to the operation (insurance sufficiency, lead time, notification adequacy, agreement chain, interval conflicts, caps, thresholds, funding, signatures, and the rest), and finally payload well-formedness — required fields present and well-typed, enum values valid, dates parseable — as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Integer Money and Pinned Rounding

All monetary quantities in this system are integer cents: fee components, day rates, liability limits, deposit amounts, claim awards. There are no fractional cents anywhere, and no decimal rounding modes apply. Where a calculation involves division, the rounding discipline is pinned per calculation in §3: the permit fee performs a single floor at its final multiplication step with no intermediate rounding, and the deposit requirement performs a single floor at its final division step with no intermediate rounding. Basis-point multipliers are divided by ten thousand. Counts (monitors, photos, business days, calendar days) and distances in feet are integers throughout.

### 2.9. Interval Semantics: Bookings Are Closed, Closures Are Half-Open

Two different interval disciplines coexist in this system, and confusing them is the classic source of off-by-one conflicts. A location booking occupies a **closed** interval: both `booking_start_date` and `booking_end_date` are included, and the owner's mandated buffer extends that interval on both sides. Touching counts as conflict — two bookings whose buffered closed intervals so much as share a single calendar date are in conflict. A street closure, by contrast, occupies a **half-open** interval `[closure_start, closure_end)`: a second closure that starts at exactly the moment a first closure ends does not overlap it. The notification and insurance windows (coverage effective and expiry dates, permit shoot windows) are again inclusive closed date ranges.

### 2.10. Hierarchical Consistency and Cascading Side Effects

The system maintains alignment between parents and children automatically. Every production-scoped child resource — bookings, scout packages, agreements, applications, closures, notifications, certificates, deposit accounts, walkthrough reports, monitor assignments, shoot days, and complaints — carries a system-assigned `production_id` binding it to its parent production. When an `OwnerAgreement` reaches `EXECUTED`, the Location it covers transitions from `SCOUTING` to `AGREEMENT_EXECUTED` without a separate client call, and the required amount of any deposit account already open for that location is recomputed. When a permit application is superseded or a shoot day is shut down, dependent street closures, shoot days, and monitor assignments are resolved in cascade — the full chains are specified in §3. Each cascade step independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`. System-initiated transitions never require a client request on the specific resource they mutate; the client observes them on the next read or sweep.

## 3. Business Logic & Workflows

### 3.1. Setting the Stage: Jurisdictions, Owners, and Locations

Before any production work begins, a `FilmOffice` operator configures each **Jurisdiction** in which filming may occur. A jurisdiction carries a unique `code` (values such as `LA-CITY`, `LA-COUNTY`, or `PASADENA`), a human-readable `name`, and the full regulatory parameter set: `lead_time_business_days` (the minimum number of business days that must lie between permit submission and the earliest shoot day), `notification_lead_calendar_days` (the minimum calendar days before the earliest shoot day by which neighborhood notification must be posted), `notification_radius_ft` (the required canvass radius around the location), the fee fields `base_fee_cents`, `per_day_fee_cents`, and `per_lane_fee_cents`, the large-cast trigger pair `large_cast_threshold` and `large_cast_multiplier_bps` (a basis-point multiplier, so that 12500 means the subtotal is scaled by 1.25), the insurance floor `min_liability_limit_cents`, the `police_monitor_lane_threshold` (lane-closure counts at or above this value force police staffing), and an optional `holidays` array of ISO `YYYY-MM-DD` dates that defaults to an empty list and is excluded from business-day counting. A jurisdiction is created `ACTIVE`; the film office may later suspend it, moving it to `SUSPENDED`, after which new permit submissions into it are rejected with `ERR_JURISDICTION_SUSPENDED` and no new bookings may be taken at locations within it.

A `LocationManager` registers each **LocationOwner** with a `legal_name`, a `contact_email` that must be unique across all owners, and a `default_day_rate_cents` that anchors the first negotiation round. The manager then registers each **Location** with a `name` and street `address`, a `jurisdiction_id` selecting the governing jurisdiction, an `owner_id` naming the legal owner who must sign the eventual agreement, and three owner-imposed constraints that follow the location through every later workflow: `deposit_floor_cents` (the minimum restoration deposit the owner will accept), `buffer_days` (rest days that must separate any two bookings at this location), and `max_shoot_hours_per_day` (the cap on shoot hours per day). A new location starts in `SCOUTING` status; it transitions to `AGREEMENT_EXECUTED` automatically the first time an owner agreement for it is executed, and a `LocationManager` may retire it from either status, moving it to `RETIRED` and removing it from new bookings. Agreements on a retired location can no longer be executed.

### 3.2. Scouting and the Owner Agreement Negotiation

With a production created — a `LocationManager` opens it with a `title`, the `production_company` legal entity name, the `cast_size` (total cast and crew headcount on the largest shoot day, which drives both the large-cast fee tier and monitor staffing), and the `umbrella_liability_limit_cents` the production carries, starting in `PREP` with `version` 1 — the manager assembles a **ScoutPackage** for each candidate location. The package records the `location_id`, a `photo_count`, a surveyor-rated `coverage_score_pct` between 0 and 100 inclusive, and the `scout_date` of the physical scout. Submission is allowed only while the production is in `PREP`, and a package with a `photo_count` below 6 is rejected at submission with `ERR_PACKAGE_INCOMPLETE`; a successful submission moves the package from `DRAFT` to `SUBMITTED`. The film office then reviews the submitted package with a `decision` of `ACCEPT` or `REJECT`, moving it to `ACCEPTED` or `REJECTED` respectively. An `ACCEPTED` package for the production-location pair is the mandatory gateway to negotiation.

The **OwnerAgreement** is a cyclic negotiation between the `LocationManager` and the `OwnerRep`. Opening one records the `location_id` and the shoot window `shoot_start_date` through `shoot_end_date` (the end date inclusive), initializes `round_count` to 0, and optionally accepts a `max_rounds` cap that defaults to 5. The manager makes the first proposal, supplying a `proposed_day_rate_cents` that must be greater than zero; the first proposal is rejected with `ERR_SCOUT_NOT_ACCEPTED` unless an `ACCEPTED` scout package exists for the same production and location. Each proposal increments `round_count` by one, replaces the standing `proposed_day_rate_cents` with the payload rate, and moves the agreement to `PROPOSED`. The owner representative counters from `PROPOSED`, supplying their own `proposed_day_rate_cents`, which replaces the standing rate and moves the agreement to `COUNTERED` without incrementing the round count; the manager re-proposes from `COUNTERED`, incrementing `round_count` again. Both proposing and countering are rejected with `ERR_NEGOTIATION_EXHAUSTED` when the action would push `round_count` beyond `max_rounds`.

Either side may close the deal, but only the side facing the offer: the `OwnerRep` accepts a `PROPOSED` agreement, and the `LocationManager` accepts a `COUNTERED` one. Acceptance requires the location not to be `RETIRED`; it locks `agreed_day_rate_cents` to the standing `proposed_day_rate_cents`, moves the agreement to `EXECUTED`, cascades the location to `AGREEMENT_EXECUTED`, and triggers a recomputation of `required_amount_cents` on any deposit account already open for that location. Either side may instead walk away — the manager from `PROPOSED`, the owner representative from `COUNTERED` — collapsing the negotiation to `COLLAPSED`. `EXECUTED` and `COLLAPSED` are terminal.

### 3.3. Location Bookings and the Owner's Buffer

A **LocationBooking** reserves a location's calendar for the production. The manager creates one by naming the `location_id` and the inclusive `booking_start_date` and `booking_end_date`; a booking that passes the buffer rule is born `CONFIRMED`. The buffer rule enforces the owner's rest days: the new booking's closed interval, widened on both sides by the location's `buffer_days` — that is, from `buffer_days` before `booking_start_date` through `buffer_days` after `booking_end_date`, both ends included — must not intersect any other `CONFIRMED` booking's own closed `booking_start_date`-to-`booking_end_date` interval at the same location. Because both intervals are closed, mere adjacency is already a conflict: if the widened interval so much as shares one calendar date with an existing confirmed booking, creation is rejected with `ERR_BOOKING_BUFFER_CONFLICT` (HTTP 409). Note the deliberate contrast with street closures in §3.6, where exact adjacency is permitted.

Releasing a booking is a `LocationManager` action that moves it to `RELEASED` and frees its interval for future buffer checks. The release is refused with `ERR_INVALID_STATE` while any shoot day at that location stands in `PLANNED`, `READY`, or `IN_PROGRESS` — a booking cannot be pulled out from under a live shooting schedule.

### 3.4. The Permit Application: Drafting, Submission, Lead Time, and Fees

A **PermitApplication** is created within a production by a `LocationManager` supplying the `location_id`, the requested `shoot_start_date` and inclusive `shoot_end_date`, the number of `closed_lanes` requested (defaulting to 0), and the planned `shoot_hours_per_day`. The request must also carry `expected_production_version` per the concurrency rule in §2.6, and may optionally carry `amendment_of_id`, the self-referential link that turns the new application into an amendment superseding an existing one. On creation the application is born `DRAFT`, its `jurisdiction_id` is copied from the location and pinned there for the life of the application, and the parent Production's `version` increments by one. When `amendment_of_id` is set and the referenced application is `ISSUED` or `CONDITIONALLY_APPROVED`, the supersede cascade fires: the referenced application moves to `SUPERSEDED`; for a superseded `ISSUED` application, its street closures still in `REQUESTED` or `APPROVED` are cancelled, and its shoot days in `PLANNED` or `READY` are cancelled — and each such shoot-day cancellation in turn releases that day's `ASSIGNED` or `CONFIRMED` monitor assignments to `RELEASED`. From `CONDITIONALLY_APPROVED` the supersede moves only the application itself.

Submission is the moment the regulatory arithmetic happens. A `LocationManager` may submit while the production is in `PREP` or `ACTIVE`, but five gates stand in front: the location must be in `AGREEMENT_EXECUTED` (else `ERR_AGREEMENT_NOT_EXECUTED`); the jurisdiction must be `ACTIVE` (else `ERR_JURISDICTION_SUSPENDED`); an `EXECUTED` owner agreement whose window covers the requested `shoot_start_date` through `shoot_end_date` must exist for the production and location (else `ERR_AGREEMENT_NOT_EXECUTED`); and `shoot_hours_per_day` must not exceed the location's `max_shoot_hours_per_day` (else `ERR_HOURS_EXCEED_LOCATION_CAP`). On a passing submission the server stamps `submitted_at` from the logical clock and computes two stored facts. First, `business_days_available`: the count of dates strictly after the submission date and on or before `shoot_start_date` — the submission date itself is excluded, the shoot date is included if it qualifies — that fall on neither a Saturday nor a Sunday nor any date in the pinned jurisdiction's `holidays`. Second, `lead_time_satisfied`: true exactly when `business_days_available` is at least the jurisdiction's `lead_time_business_days`. The application lands in `SUBMITTED` either way; a short lead time does not block submission, it blocks review.

The submission also prices the application into `fee_cents`, and the fee is recomputed on any amendment that changes the shoot days, the lanes, or the cast tier. The pricing model counts the days in the window, builds a subtotal, and applies one multiplier. The subtotal is the jurisdiction's `base_fee_cents`, plus the day count times `per_day_fee_cents`, plus the day count times `closed_lanes` times `per_lane_fee_cents`. If the production's `cast_size` is strictly greater than the jurisdiction's `large_cast_threshold`, the fee is the subtotal multiplied by `large_cast_multiplier_bps` and divided by ten thousand, with a single floor applied at that final multiplication and no intermediate rounding; otherwise the fee is the subtotal unchanged. The evaluation order is pinned: days first, then subtotal, then the single terminal floor. Two variants of the day count exist, and they answer different questions. For budgeting, a draft application displays an estimate under the calendar-day model, in which the day count is simply the number of calendar dates in the `shoot_start_date`-to-`shoot_end_date` window, both dates included. The authoritative fee computed at submission uses the business-day model: the day count includes only dates of the same window that are business days under the same weekend-and-holiday rule as the lead-time count, so a window spanning a weekend yields a strictly smaller authoritative fee than the displayed calendar-day estimate for the same inputs.

### 3.5. Review, Insurance, Notification, and Issuance

The film office opens review by moving a `SUBMITTED` application to `UNDER_REVIEW`, and this transition carries the lead-time gate: review may not start unless `lead_time_satisfied` is true, otherwise the request fails with `ERR_LEAD_TIME_SHORT`. From `UNDER_REVIEW` the film office decides the application with a `decision` of `ISSUE`, `APPROVE_WITH_CONDITIONS`, or `DENY`. Denial is always available and moves the application to `DENIED`, from review or from conditional approval alike. Conditional approval moves it to `CONDITIONALLY_APPROVED` with no further precondition.

Issuance is where the safety documents bite. Deciding `ISSUE` directly from `UNDER_REVIEW` requires a `VERIFIED` insurance certificate for the production and the pinned jurisdiction whose inclusive coverage window from `effective_date` through `expiry_date` spans the entire requested shoot window; without one the decision is rejected with `ERR_INSURANCE_INSUFFICIENT`. Deciding `ISSUE` from `CONDITIONALLY_APPROVED` requires that same certificate and additionally an `ACKED` notification record attached to this application, else `ERR_NOTIFICATION_DEFICIENT`.

An **InsuranceCertificate** is presented by a `LocationManager` with a `jurisdiction_id` naming the jurisdiction it is presented to, the `insurer_name`, the certificate's `umbrella_limit_cents`, an `indemnity_clause_ref`, and the inclusive `effective_date` and `expiry_date` of coverage; it starts as `PRESENTED`. The film office verifies it against three checks: the limit must be at least the jurisdiction's `min_liability_limit_cents` (a shortfall fails with `ERR_INSURANCE_INSUFFICIENT`), the indemnity clause reference must be non-empty (an empty one fails with `ERR_INDEMNITY_MISSING`), and the expiry date must not precede the effective date. A verified certificate moves to `VERIFIED`; the film office may instead reject a presented certificate outright to `REJECTED`. When the logical clock passes a verified certificate's `expiry_date`, the operations sweep lapses it to `LAPSED`. Lapse is not retroactive: an already-`ISSUED` permit whose shoot window is not fully in the past keeps its status, but creating any new shoot day under it is blocked with `ERR_INSURANCE_INSUFFICIENT` until fresh coverage is verified.

A **NotificationRecord** documents the legally required neighborhood canvass. The manager records one against a specific `permit_application_id`, reporting the `households_reached` and the `radius_ft_used` actually canvassed. The server stamps `posted_at` from the logical clock and computes two facts at creation: `calendar_days_before_shoot`, the whole calendar days between the posting date and the application's `shoot_start_date`, and `notification_adequate`, true exactly when `calendar_days_before_shoot` is at least the pinned jurisdiction's `notification_lead_calendar_days` **and** `radius_ft_used` is at least its `notification_radius_ft`. Both comparisons are inclusive at the boundary: a posting made exactly the required number of days ahead at exactly the required radius is adequate. An adequate record is born `POSTED`; an inadequate one is born directly `DEFICIENT` with no review step. The film office acknowledges a `POSTED` record, moving it to `ACKED` — but only when `notification_adequate` is true, otherwise `ERR_NOTIFICATION_DEFICIENT`.

Once issued, a permit is the live authorization for shoot days and street closures, but it is not immortal. The operations sweep moves an `ISSUED` application to `EXPIRED` when the logical clock passes its `shoot_end_date` and no shoot day under it ever reached `IN_PROGRESS`, cancelling any of its closures still in `REQUESTED` or `APPROVED`. A `LocationManager` may withdraw an application while it is in `DRAFT` or `SUBMITTED`, moving it to `WITHDRAWN`. And an amendment supersedes an `ISSUED` or `CONDITIONALLY_APPROVED` application as described in §3.4. For the purposes of the production wrap gate in §3.9, an application counts as resolved once it has left every one of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, and `CONDITIONALLY_APPROVED` — `ISSUED`, `DENIED`, `SUPERSEDED`, `EXPIRED`, and `WITHDRAWN` all clear the gate.

### 3.6. Street Closures

When a permit involves lane closures, the manager requests a **StreetClosure** against it, naming the `permit_application_id`, a normalized `street_segment` identifier such as `MAIN-ST-100-BLOCK`, and the window `closure_start` to `closure_end`. The request is born `REQUESTED`. Film-office approval is gated twice: the backing permit application must be `ISSUED` (else `ERR_PERMIT_NOT_ISSUED`), and no other `APPROVED` or `ACTIVE` closure on the same `street_segment` may intersect the requested window (else `ERR_CLOSURE_OVERLAP`, HTTP 409). The overlap test uses half-open interval semantics — the window includes `closure_start` and excludes `closure_end` — so a closure starting at the exact instant another ends does not collide with it, in deliberate contrast to the closed-interval booking buffer of §3.3. A `LocationManager` may cancel a closure while it is `REQUESTED` or `APPROVED`, moving it to `CANCELLED`.

From `APPROVED` the closure's life is clock-driven: the operations sweep moves it to `ACTIVE` when the clock reaches `closure_start`, and to `COMPLETED` when the clock reaches `closure_end`. Two cascades can interrupt that life: a shut-down shoot day cancels its day's `APPROVED` or `ACTIVE` closures (§3.8), and a superseded or expired permit cancels its `REQUESTED` or `APPROVED` closures (§3.4, §3.5). Either way, cancellation frees the interval on the street segment for future approvals.

### 3.7. Deposits, Walkthroughs, and Settlement

The **DepositAccount** holds the production's restoration and damage money for one location; there is exactly one account per production-location pair, so opening a second for the same pair is refused. The manager opens it by naming the `location_id`, and the server computes `required_amount_cents` at that moment: if an `EXECUTED` owner agreement exists for the location the risk-based formula below applies, otherwise the required amount is the location's `deposit_floor_cents` alone. The risk-based amount multiplies the agreed day rate by the number of calendar dates in the agreement window and then takes half: specifically, multiply `agreed_day_rate_cents` by the shoot-day count, multiply that product by 50, and divide by 100 with a single floor applied at that final division — the rounding order is pinned, and reordering it changes the answer whenever the rate is odd. A rate of 99999 cents over 3 days illustrates the point: the pinned order yields 149998 cents (299997 times 50, divided by 100 and floored), whereas flooring the half-rate first would yield 149997. The required amount is the larger of the location's `deposit_floor_cents` and this risk amount; when the two are exactly equal, the required amount is simply that common value with no tie-break surcharge. The account is born `OPEN` with `held_amount_cents`, `claimed_amount_cents`, and `released_amount_cents` all at 0.

The manager pays into the account with an `amount_cents` that is added to `held_amount_cents`; the moment the held amount reaches or exceeds the required amount, the account moves automatically to `FUNDED`. That funded posture is one of the readiness gates in §3.8.

Two **WalkthroughReport** kinds bookend the shoot. A `PRE` report, created with `kind` set to `PRE`, documents the location's condition before the first shoot day; a POST report, with `kind` set to POST, documents it afterward and opens the settlement. Either is created by the manager with the `location_id` and may carry `damage_item_count`, `damage_claim_cents`, and the two signature flags `signed_by_owner` and `signed_by_manager`, which default to 0, 0, false, and false respectively. A draft report becomes `SIGNED` only when both signature flags are true, otherwise the signing is rejected with `ERR_SIGNATURE_MISSING`. For a `PRE` report there is an additional uniqueness rule: no other `SIGNED` `PRE` report may already exist for the location, or the signing fails with `ERR_DUPLICATE_PRE_WALKTHROUGH`. When a POST report is signed, the deposit account for the production and location moves to `SETTLING`. The owner representative may instead dispute a POST report — only POST reports are disputable — moving it to `DISPUTED`, which likewise pushes the deposit account to `SETTLING`; a disputed report can be re-signed by the manager once both signature flags are again true, returning it to `SIGNED`.

Settlement itself belongs to the film office and runs as a waterfall. The settle call supplies an explicit `awarded_claim_cents` — the award is a film-office judgment, not a derived value. Settlement is blocked while the location's POST report stands `DISPUTED` (the attempt fails with `ERR_WALKTHROUGH_DISPUTED`), and an award larger than the account's un-released balance — `held_amount_cents` minus `released_amount_cents` — is rejected with `ERR_CLAIM_EXCEEDS_DEPOSIT`. On a passing settle, claims are paid first and the remainder released: `claimed_amount_cents` increases by the award, and `released_amount_cents` increases by whatever of the held balance remains after the award, so that afterward the held amount equals the claimed amount plus the released amount exactly. The account closes to `CLOSED`, the POST walkthrough report moves automatically to `FINAL`, and the location's `PRE` report — if not already final — moves to `FINAL` when the POST report becomes signed.

### 3.8. Shoot Days: Staffing, the Readiness Gate, Execution, and Compliance

A **ShootDay** is planned by a `LocationManager` against a permit, supplying the `permit_application_id`, the `location_id`, the `shoot_date`, and `planned_hours`. Creation requires only that the referenced permit not be in a terminal state — a terminal permit fails with `ERR_PERMIT_NOT_ISSUED`, while the full issued-permit gate applies later at readiness, not at creation. The `shoot_date` must lie within the permit's inclusive `shoot_start_date`-to-`shoot_end_date` window, and `planned_hours` must not exceed the location's `max_shoot_hours_per_day`, else `ERR_HOURS_EXCEED_LOCATION_CAP`. If the permit's certificate has since lapsed and its shoot window is not fully past, creation is blocked with `ERR_INSURANCE_INSUFFICIENT`. A new shoot day is born `PLANNED`, and the server computes its `monitors_required` immediately (recomputing on any permit amendment that changes lanes or hours): the base is `shoot_hours_per_day` divided by 8 and rounded up to a whole number; one extra monitor is added when the permit's `closed_lanes` reaches or exceeds the jurisdiction's `police_monitor_lane_threshold`; and one further extra is added when the production's `cast_size` is strictly greater than the `large_cast_threshold`. When the lane trigger fires, at least one of the assignments counted toward coverage must be of `monitor_type` `POLICE`, or the readiness gate fails even when the numeric count is met.

**MonitorAssignment** staffing is shared between the parties. The manager assigns an officer to a day with the `shoot_day_id`, a `monitor_type` of `POLICE`, `FIRE`, or `FILM_OFFICER`, the `officer_badge`, and `hours_booked`; one officer may hold at most one non-released assignment per shoot day, so a duplicate `officer_badge` on the same day is refused. The film office confirms an assignment while the day is `PLANNED` or `READY`, moving it from `ASSIGNED` to `CONFIRMED` and recomputing the day's `monitors_confirmed` — the count of that day's assignments standing in `CONFIRMED`. Release by the film office frees the officer: an `ASSIGNED` assignment releases freely, but a `CONFIRMED` one cannot be released while its day is `IN_PROGRESS` (the attempt fails with `ERR_DAY_IN_PROGRESS`). On the shoot day itself, while the day is `IN_PROGRESS`, the film office records officer presence through check-in, which sets the assignment's `checked_in` flag to true without leaving `CONFIRMED`. A confirmed assignment whose officer never checks in becomes `NO_SHOW` — recorded automatically when the day completes, or explicitly by the film office at any point; a `NO_SHOW` no longer counts toward `monitors_confirmed`, both counters and the day's compliance are recomputed, and a no-show that drops confirmed coverage below required forces the day's `compliance_status` to `VIOLATION`.

Marking a day ready is the single most gated transition in the system, and the request must carry `expected_shoot_day_version` per §2.6. A `LocationManager` may move a `PLANNED` day to `READY` only when every one of the following holds: the backing permit is `ISSUED` (else `ERR_PERMIT_NOT_ISSUED`); an `ACKED` notification exists for that permit (else `ERR_NOTIFICATION_DEFICIENT`); a `VERIFIED` certificate covers the `shoot_date` (else `ERR_INSURANCE_INSUFFICIENT`); the location's deposit account is `FUNDED` (else `ERR_DEPOSIT_NOT_FUNDED`); a `SIGNED` `PRE` walkthrough exists for the location (else `ERR_PRE_WALKTHROUGH_MISSING`); `monitors_confirmed` is at least `monitors_required` with the police-type requirement satisfied when the lane threshold fired (else `ERR_MONITOR_SHORTFALL`); and, when the permit's `closed_lanes` is greater than zero, the `APPROVED` street closures needed for the day's lanes exist (else `ERR_CLOSURE_MISSING`). Success sets the day `READY`, increments its `version`, and — if the production was still in `PREP` — flips the production to `ACTIVE`. The operations sweep then moves a `READY` day to `IN_PROGRESS` on its `shoot_date`.

Completion is the manager's accounting of the day: it requires `actual_hours`, which must not exceed the location's `max_shoot_hours_per_day` (else `ERR_HOURS_EXCEED_LOCATION_CAP`), and it records `overtime_minutes` as the excess of actual over planned hours, in minutes, floored at zero — a day that runs short records zero overtime. Completion recomputes `compliance_status` and sweeps every still-unchecked `CONFIRMED` assignment into `NO_SHOW`. The compliance score itself accumulates violation points: any overtime adds one point; confirmed monitor coverage below required adds one; each counted `HIGH` or `CRITICAL` complaint against the day adds two points; each counted `MEDIUM` complaint adds one. Two or more points mean `VIOLATION`, exactly one means `DEGRADED`, zero means `COMPLIANT` — so two `MEDIUM` complaints already tip a day into `VIOLATION`. Which complaints count depends on the variant. The strict variant, the authoritative one persisted on the shoot day and used for wrap gating, counts every complaint against the day including `RESOLVED` ones — resolving a complaint never erases the compliance fact. The lenient display variant, used only for the film-office dashboard projection and never persisted, counts only complaints in `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`; under it a resolved `HIGH` complaint drops the projection from `VIOLATION` to `COMPLIANT` while the persisted strict value stays `VIOLATION`. Compliance is recomputed at completion, at every no-show, and at every `CRITICAL` complaint.

Two endings interrupt a day. A manager may cancel a `PLANNED` or `READY` day, moving it to `CANCELLED` and releasing its `ASSIGNED` and `CONFIRMED` monitor assignments. And a `CRITICAL` complaint filed against an `IN_PROGRESS` day shuts the day down automatically — the film office may also shut an in-progress day down explicitly — moving it to `SHUT_DOWN` and cancelling its day's `APPROVED` or `ACTIVE` street closures, which frees those street-segment intervals; the production itself remains `ACTIVE`.

### 3.9. Complaints, Escalation, and Production Wrap

Anyone at the table may file a **Complaint** against a shoot day — `FilmOffice`, `LocationManager`, and `OwnerRep` alike — naming the `shoot_day_id`, a `category` of `NOISE`, `PARKING`, `PROPERTY_DAMAGE`, `HOURS_VIOLATION`, or `OTHER`, and a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`. The server stamps `filed_at` from the logical clock and sets `response_due_at` exactly 24 hours later; the complaint opens as `OPEN`. Filing a `CRITICAL` complaint against an `IN_PROGRESS` day fires the shut-down cascade of §3.8 immediately, and every filing recomputes the day's `compliance_status`. The manager acknowledges an open complaint, moving it to `ACKNOWLEDGED`. Resolution requires a non-empty `resolution_note` (an empty one fails with `ERR_INVALID_REQUEST`): the manager resolves from `ACKNOWLEDGED`, while an escalated complaint is reserved for the film office to resolve from `ESCALATED`. Escalation itself is automatic: when the operations sweep finds an `OPEN` complaint whose `response_due_at` has passed, it moves the complaint to `ESCALATED`, and if the complaint is `CRITICAL` against an in-progress day the sweep fires the shut-down cascade there as well. The `resolution_note` defaults to empty on creation.

Cancellation and wrap close the production's own lifecycle. While the production is in `PREP` and no shoot day has yet reached `READY` or beyond (otherwise `ERR_INVALID_STATE`), the manager may cancel the production, moving it to `CANCELLED`; the cancellation withdraws every application still in `DRAFT` or `SUBMITTED` to `WITHDRAWN` and collapses every agreement still in `PROPOSED` or `COUNTERED` to `COLLAPSED`. Wrapping is the `ACTIVE`-to-`WRAPPED` transition, and its three preconditions are evaluated in a fixed order: first, every permit application must have left `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, and `CONDITIONALLY_APPROVED` — a failure here is reported as `ERR_APPLICATIONS_OPEN`; second, every deposit account must be `CLOSED` — reported as `ERR_DEPOSITS_OPEN`; and last, no complaint may remain in `OPEN` or `ACKNOWLEDGED` — reported as `ERR_COMPLAINTS_OPEN`. The ordering matters operationally: a wrap attempt against a production with both open applications and open deposits surfaces `ERR_APPLICATIONS_OPEN`, not `ERR_DEPOSITS_OPEN`.

## 4. Endpoint Definitions

Operations that create a new resource — a production, jurisdiction, owner, location, or any child resource added to a production's collection — return `201 Created`. Operations that modify, transition, or act upon an existing resource return `200 OK`. The table below is the complete HTTP contract; request payloads, derived fields, and side effects for each operation are specified in §2 and §3, and cross-scope list endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus the filters named in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock (startup default exactly 2026-08-01T00:00:00Z) | FilmOffice |
| POST | `/_ops/sweep` | Advance the system epoch: expire permits, lapse certificates, escalate complaints, activate/complete closures, start ready shoot days | FilmOffice |
| POST | `/jurisdictions` | Create a jurisdiction (film-office configuration) | FilmOffice |
| GET | `/jurisdictions/{id}` | Get a jurisdiction | FilmOffice, LocationManager, OwnerRep |
| GET | `/jurisdictions` | List jurisdictions (filterable by `code`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/jurisdictions/{id}/suspend` | Suspend a jurisdiction (blocks new permits and bookings) | FilmOffice |
| POST | `/owners` | Register a location owner | LocationManager |
| GET | `/owners/{id}` | Get an owner | FilmOffice, LocationManager, OwnerRep |
| GET | `/owners` | List owners (paginated) | FilmOffice, LocationManager, OwnerRep |
| POST | `/locations` | Register a location | LocationManager |
| GET | `/locations/{id}` | Get a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations` | List locations (filterable by `jurisdiction_id`, `owner_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/locations/{id}/retire` | Retire a location | LocationManager |
| GET | `/permit-applications/{id}` | Get a permit application by id (cross-scope alias of the nested read) | FilmOffice, LocationManager, OwnerRep |
| GET | `/shoot-days/{id}` | Get a shoot day by id (cross-scope alias of the nested read) | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/location-bookings` | List bookings at a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/scout-packages` | List scout packages for a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/owner-agreements` | List owner agreements for a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/permit-applications` | List permit applications for a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/jurisdictions/{id}/permit-applications` | List permit applications pinned to a jurisdiction | FilmOffice, LocationManager, OwnerRep |
| GET | `/permit-applications/{id}/amendments` | List applications whose `amendment_of_id` references this application | FilmOffice, LocationManager, OwnerRep |
| GET | `/permit-applications/{id}/street-closures` | List street closures backed by a permit application | FilmOffice, LocationManager, OwnerRep |
| GET | `/permit-applications/{id}/notifications` | List notifications attached to a permit application | FilmOffice, LocationManager, OwnerRep |
| GET | `/jurisdictions/{id}/insurance-certificates` | List insurance certificates presented to a jurisdiction | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/deposit-accounts` | List deposit accounts for a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/walkthrough-reports` | List walkthrough reports for a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/shoot-days/{id}/monitor-assignments` | List monitor assignments staffing a shoot day | FilmOffice, LocationManager, OwnerRep |
| GET | `/permit-applications/{id}/shoot-days` | List shoot days backed by a permit application | FilmOffice, LocationManager, OwnerRep |
| GET | `/locations/{id}/shoot-days` | List shoot days at a location | FilmOffice, LocationManager, OwnerRep |
| GET | `/shoot-days/{id}/complaints` | List complaints filed against a shoot day | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions` | Create a production | LocationManager |
| GET | `/productions/{id}` | Get a production | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/wrap` | Wrap a production (ordered gates: applications, deposits, complaints) | LocationManager |
| POST | `/productions/{id}/cancel` | Cancel a production still in PREP | LocationManager |
| POST | `/productions/{id}/location-bookings` | Create a CONFIRMED location booking; enforces the closed-interval buffer rule | LocationManager |
| GET | `/productions/{id}/location-bookings` | List bookings (filterable by `location_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/location-bookings/{rid}/release` | Release a confirmed booking | LocationManager |
| POST | `/productions/{id}/scout-packages` | Create a scout package for a location | LocationManager |
| GET | `/productions/{id}/scout-packages` | List scout packages (filterable by `location_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/scout-packages/{rid}` | Get a scout package | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/scout-packages/{rid}/submit` | Submit a scout package (photo floor applies) | LocationManager |
| POST | `/productions/{id}/scout-packages/{rid}/review` | Film office reviews a submitted package (`decision` ACCEPT or REJECT) | FilmOffice |
| POST | `/productions/{id}/owner-agreements` | Open an owner agreement negotiation | LocationManager |
| GET | `/productions/{id}/owner-agreements` | List agreements (filterable by `location_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/owner-agreements/{rid}` | Get an agreement | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/owner-agreements/{rid}/propose` | Propose (or re-propose after a counter) a day rate | LocationManager |
| POST | `/productions/{id}/owner-agreements/{rid}/counter` | Owner counters the proposal | OwnerRep |
| POST | `/productions/{id}/owner-agreements/{rid}/accept` | Accept the standing rate (OwnerRep accepts PROPOSED; LocationManager accepts COUNTERED) | LocationManager, OwnerRep |
| POST | `/productions/{id}/owner-agreements/{rid}/walk-away` | Collapse the negotiation | LocationManager, OwnerRep |
| POST | `/productions/{id}/permit-applications` | Create a permit application (optionally an amendment via `amendment_of_id`). OCC: `expected_production_version` required | LocationManager |
| GET | `/productions/{id}/permit-applications` | List permit applications (filterable by `location_id`, `jurisdiction_id`, `status`, `amendment_of_id`) | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/permit-applications/{rid}` | Get a permit application | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/permit-applications/{rid}/submit` | Submit an application; computes lead time and fee | LocationManager |
| POST | `/productions/{id}/permit-applications/{rid}/start-review` | Film office opens review (lead-time gate) | FilmOffice |
| POST | `/productions/{id}/permit-applications/{rid}/decide` | Film office decides (`decision` ISSUE, APPROVE_WITH_CONDITIONS, or DENY) | FilmOffice |
| POST | `/productions/{id}/permit-applications/{rid}/withdraw` | Withdraw a DRAFT or SUBMITTED application | LocationManager |
| POST | `/productions/{id}/street-closures` | Request a street closure against a permit | LocationManager |
| GET | `/productions/{id}/street-closures` | List street closures (filterable by `permit_application_id`, `street_segment`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/street-closures/{rid}/approve` | Approve a closure (overlap + permit gates) | FilmOffice |
| POST | `/productions/{id}/street-closures/{rid}/cancel` | Cancel a REQUESTED or APPROVED closure | LocationManager |
| POST | `/productions/{id}/notifications` | Record a posted neighborhood notification | LocationManager |
| GET | `/productions/{id}/notifications` | List notifications (filterable by `permit_application_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/notifications/{rid}/acknowledge` | Film office acknowledges an adequate notification | FilmOffice |
| POST | `/productions/{id}/insurance-certificates` | Present an insurance certificate to a jurisdiction | LocationManager |
| GET | `/productions/{id}/insurance-certificates` | List certificates (filterable by `jurisdiction_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/insurance-certificates/{rid}/verify` | Verify a certificate (limit, indemnity, window checks) | FilmOffice |
| POST | `/productions/{id}/insurance-certificates/{rid}/reject` | Reject a certificate | FilmOffice |
| POST | `/productions/{id}/deposit-accounts` | Open a deposit account for a location (unique per production+location) | LocationManager |
| GET | `/productions/{id}/deposit-accounts` | List deposit accounts (filterable by `location_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/deposit-accounts/{rid}` | Get a deposit account | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/deposit-accounts/{rid}/deposit` | Pay funds into the deposit account (`amount_cents`) | LocationManager |
| POST | `/productions/{id}/deposit-accounts/{rid}/settle` | Film office settles the account: award a claim (`awarded_claim_cents`), release the remainder, close | FilmOffice |
| POST | `/productions/{id}/walkthrough-reports` | Create a PRE or POST walkthrough report | LocationManager |
| GET | `/productions/{id}/walkthrough-reports` | List walkthrough reports (filterable by `location_id`, `kind`, `status`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/walkthrough-reports/{rid}/sign` | Sign a report (both signature flags must already be true) | LocationManager |
| POST | `/productions/{id}/walkthrough-reports/{rid}/dispute` | Owner disputes a POST report | OwnerRep |
| POST | `/productions/{id}/monitor-assignments` | Assign a monitor/officer to a shoot day | LocationManager |
| GET | `/productions/{id}/monitor-assignments` | List monitor assignments (filterable by `shoot_day_id`, `status`, `monitor_type`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/monitor-assignments/{rid}/confirm` | Film office confirms an assignment | FilmOffice |
| POST | `/productions/{id}/monitor-assignments/{rid}/release` | Release an assignment | FilmOffice |
| POST | `/productions/{id}/monitor-assignments/{rid}/mark-no-show` | Record a no-show on a confirmed assignment | FilmOffice |
| POST | `/productions/{id}/monitor-assignments/{rid}/check-in` | Record officer check-in on the shoot day (requires the day IN_PROGRESS) | FilmOffice |
| POST | `/productions/{id}/shoot-days` | Plan a shoot day under a non-terminal permit | LocationManager |
| GET | `/productions/{id}/shoot-days` | List shoot days (filterable by `permit_application_id`, `location_id`, `status`) | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/shoot-days/{rid}` | Get a shoot day | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/shoot-days/{rid}/mark-ready` | Gate check + transition to READY. OCC: `expected_shoot_day_version` required | LocationManager |
| POST | `/productions/{id}/shoot-days/{rid}/complete` | Complete an IN_PROGRESS day with `actual_hours` | LocationManager |
| POST | `/productions/{id}/shoot-days/{rid}/cancel` | Cancel a PLANNED or READY day | LocationManager |
| POST | `/productions/{id}/shoot-days/{rid}/shut-down` | Film office shuts down an IN_PROGRESS day | FilmOffice |
| POST | `/productions/{id}/complaints` | File a complaint against a shoot day | FilmOffice, LocationManager, OwnerRep |
| GET | `/productions/{id}/complaints` | List complaints (filterable by `shoot_day_id`, `status`, `severity`) | FilmOffice, LocationManager, OwnerRep |
| POST | `/productions/{id}/complaints/{rid}/acknowledge` | Location manager acknowledges a complaint | LocationManager |
| POST | `/productions/{id}/complaints/{rid}/resolve` | Resolve a complaint (LocationManager from ACKNOWLEDGED; FilmOffice from ESCALATED) | LocationManager, FilmOffice |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; the table below is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PACKAGE_INCOMPLETE` | 422 |
| `ERR_SCOUT_NOT_ACCEPTED` | 422 |
| `ERR_NEGOTIATION_EXHAUSTED` | 422 |
| `ERR_AGREEMENT_NOT_EXECUTED` | 422 |
| `ERR_JURISDICTION_SUSPENDED` | 422 |
| `ERR_LEAD_TIME_SHORT` | 422 |
| `ERR_NOTIFICATION_DEFICIENT` | 422 |
| `ERR_INSURANCE_INSUFFICIENT` | 422 |
| `ERR_INDEMNITY_MISSING` | 422 |
| `ERR_PERMIT_NOT_ISSUED` | 422 |
| `ERR_CLOSURE_OVERLAP` | 409 |
| `ERR_BOOKING_BUFFER_CONFLICT` | 409 |
| `ERR_HOURS_EXCEED_LOCATION_CAP` | 422 |
| `ERR_MONITOR_SHORTFALL` | 422 |
| `ERR_DEPOSIT_NOT_FUNDED` | 422 |
| `ERR_CLAIM_EXCEEDS_DEPOSIT` | 422 |
| `ERR_WALKTHROUGH_DISPUTED` | 422 |
| `ERR_SIGNATURE_MISSING` | 422 |
| `ERR_PRE_WALKTHROUGH_MISSING` | 422 |
| `ERR_DUPLICATE_PRE_WALKTHROUGH` | 422 |
| `ERR_DAY_IN_PROGRESS` | 409 |
| `ERR_CLOSURE_MISSING` | 422 |
| `ERR_APPLICATIONS_OPEN` | 409 |
| `ERR_DEPOSITS_OPEN` | 409 |
| `ERR_COMPLAINTS_OPEN` | 409 |

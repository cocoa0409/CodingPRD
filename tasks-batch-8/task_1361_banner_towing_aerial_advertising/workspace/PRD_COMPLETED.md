# Banner Towing & Aerial Advertising API — Product Requirements Document

## 1. Introduction

A coastal banner-tow operator sells the sky by the hour. Clients — concert promoters, real-estate developers, political campaigns, local restaurants — buy advertising campaigns made up of individual tow flights over defined routes: beach segments on a summer Saturday, stadium airspace during a game, festival grounds, parade corridors. Every one of those flights must clear a stack of regulatory, meteorological, mechanical, and financial gates before an aircraft ever lifts a banner off the tow field, and every one of them must be documented afterward well enough to survive a client dispute. This document specifies the API that runs that operation end to end: campaign booking, per-date FAA airspace approvals, banner fabrication and message revision, same-day weather go/no-go calls, flight-hour billing with make-good credits for weather cancellations, stadium TFR compliance, proof-of-flight documentation, and the seasonal aircraft-hour quotas that keep the fleet from being oversold.

The system serves seven distinct operator roles with strict segregation of duties — the person who grants an airspace approval may not later vouch for flights flown under it, and only the pilot assigned to a slot may file its flight log. Aircraft and pilot selection is automated through scoring selectors that balance hours across the fleet; billing runs monthly per campaign with a pinned rounding order and a tiered volume discount; and all scarce-resource consumption (seasonal aircraft hours, banner fabrication starts, campaign booking) is protected by optimistic concurrency control. All resources are mounted under the `/btaa` URL prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly seven roles: `PlatformAdmin`, `Client`, `Dispatcher`, `Pilot`, `GroundCrewLead`, `ComplianceOfficer`, and `FinanceOfficer`. A request whose `X-User-Role` header is missing or names a value outside this declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-ID` header is missing — or, for entity-backed roles, does not identify a valid persisted entity — is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, a request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two of the seven roles are entity-backed. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED_OWNER` (HTTP 403). When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot`; ownership checks on any resource that references a `Pilot` compare the resource's foreign-key field to `X-User-ID`, with the same `ERR_UNAUTHORIZED_OWNER` rejection on mismatch. The remaining five roles are opaque: when `X-User-Role` is `PlatformAdmin`, `Dispatcher`, `GroundCrewLead`, `ComplianceOfficer`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the granting officer on an `AirspaceApproval`, used later by the segregation-of-duties rule) but does not compare it to any entity's `id`.

On the system-wide filtered listings, entity-backed callers see only their own resources: a `Client` listing banners, banner revisions, flight slots, flight logs, or make-good credits sees only those belonging to its own campaigns, and a `Pilot` listing weather assessments or flight logs sees only records on which they are named. The same ownership rule governs single-record retrieval of a `WeatherAssessment` or `FlightLog` by a `Pilot`, except that an assessment naming no assessing pilot is readable by any pilot.

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

Requests that match no route — or that use an unsupported method on a matched route — are rejected with `ERR_NOT_FOUND` (HTTP 404) in the same envelope; an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500), likewise in the standard error envelope.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range of one through one hundred, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; filters apply to the full collection before pagination, `total_count` counts the filtered set, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order; records that share a `created_at` — common while the logical clock stands still — are ordered by insertion sequence. Most collections additionally support exact-match filters named after the resource's own fields — for example the aircraft collection of a base accepts an optional `status` filter, the route collection of a base accepts `kind` and `status`, the seasonal-capacity collection accepts `month_yyyy_mm`, and the invoice collection of a campaign accepts `status` and `period_yyyy_mm`. The per-collection filters are introduced alongside each resource in §3.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` records the creation instant as an ISO 8601 UTC timestamp with three fractional digits; `updated_at` carries the same format and is refreshed on every mutation. `version` is a system-managed integer that starts at one on creation and increments by exactly one on every modification of the resource, including modifications caused by cascades from other resources.

Two resources are immutable evidentiary records and break this pattern deliberately: a `WeatherAssessment` and a `ProofOfFlight` each carry `id` and `created_at` only. Neither has `updated_at` and neither has `version`; once created, they are never modified.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in this document — booking lead times, scheduling cutoffs, TFR overlap evaluation, approval-window containment, and credit expiry all read the logical clock, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z` and does not fall back to wall-clock time at any point. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied instant: the request carries `to_iso8601`, an ISO 8601 UTC timestamp, and the response echoes the supplied value verbatim as the `current_utc` field. Every server-stamped timestamp — `created_at`, `updated_at`, the envelope's `api_request_timestamp`, `assessed_at_utc`, `filed_at_utc`, `submitted_at_utc`, and `cancelled_at_utc` — reads the same logical clock.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the URL path. The existence of each path identifier is confirmed in sequence, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — a request addressed to a slot under a non-existent campaign fails on the campaign before the slot is ever consulted. The same discipline applies to identifiers supplied in the request body: a payload that references a `banner_id`, `route_id`, `airspace_approval_id`, or `supersedes_slot_id` that does not exist is rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.7. The Validation Pipeline and Its Fixed Order

Every request passes through a single validation pipeline whose stages run in a fixed priority order, and a failure at any stage short-circuits the rest. Authentication comes first — the role-header check, then the identity-header check, then the per-endpoint role permission check. Existence checks follow: path-template identifiers are resolved left to right, then body-referenced foreign keys. State checks come next: the from-state check rejects any transition the resource's current state does not permit with `ERR_INVALID_STATE` (HTTP 409). Terminal states permit no outgoing transitions at all, so a request against a terminal resource surfaces this same from-state error; no separate terminal-state error is ever emitted. Domain business rules run after state checks, in the priority order given in the relevant §3 workflows, and the optimistic-concurrency version comparison runs last of all, after every business rule has passed.

Malformed payloads are caught by two general-purpose rejections. An enum field whose value is outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400). A missing required field, a wrong-typed value, or an out-of-range scalar — for example a `planned_duration_hours` outside the integer range of one through eight, or an approval whose `window_end_utc` is not strictly later than its `window_start_utc` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Fields outside a payload's declared set are ignored rather than rejected.

### 2.8. Seasonal Capacity Accounting

Each base operates under a per-month aircraft-hour quota recorded on a `SeasonalCapacity` resource keyed by `month_yyyy_mm`, a calendar-month identifier in `YYYY-MM` form, together with the total `aircraft_hour_quota` the base may fly that month. The committed figure, `hours_committed`, is the sum of `planned_duration_hours` over every flight slot for that base and month — a slot's month being the calendar month of its `date_local` — whose status is `BOOKED`, `SCHEDULED`, `WEATHER_HOLD`, or `FLOWN`; slots in any of the cancelled states contribute nothing. The derived `hours_remaining` is the quota minus the committed hours. Both figures are recomputed on every transition that moves a slot into or out of the contributing set — booking consumes from the pool, and every cancellation of any flavor releases the slot's planned hours back to it. All capacity figures are integer hours. Creating a `SeasonalCapacity` enforces no uniqueness on the base-and-month pair; if duplicates exist, the earliest-created record is the operative one for booking and accounting.

### 2.9. Money, Hours, and Precision

All monetary amounts are integer cents; there is no decimal money anywhere in the system. Wherever a calculation produces a fractional cent, the value is rounded half-up to a whole cent at the pinned rounding points named in §3 — per flight line before summation, and again after the volume discount is applied to the summed subtotal. Invoice totals never go below zero.

Flight time is tracked in hobbs hours. A flight log's billable duration is its shutdown reading minus its engine-start reading, rounded half-up to the nearest tenth of an hour. Seasonal utilization is reckoned against the active season, which runs from May 1 through September 30: a flight counts as in-season when the calendar month of its slot's `date_local` falls between May and September inclusive, and only flight time logged within that window accrues toward an aircraft's or pilot's season totals.

### 2.10. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a scarce or contended parent resource. Campaign booking requires the request to carry `expected_campaign_version` holding the campaign's current `version`; if another writer has advanced the campaign's version since the client last read it — for example by adding a flight slot — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). Flight-slot creation requires `expected_seasonal_capacity_version` holding the current `version` of the `SeasonalCapacity` for the target base and month; if another writer has consumed quota the caller believed was available, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Banner fabrication requires `expected_banner_version` holding the banner's current `version`; if a revision was promoted in the meantime, forcing the banner back to draft and advancing its version, the fabrication start is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these three accepts a version field.

### 2.11. Hierarchical Consistency and Automatic Cascades

The system maintains alignment between parent and child resources without waiting for explicit client requests. When the last open item under a parent resolves, or when a parent's state change strands its children, the server transitions the affected resources automatically: a campaign moves itself to `IN_FLIGHT` when its first slot is scheduled and to `COMPLETE` when every slot is terminal and every invoice settled; revoking an airspace approval cancels every slot still depending on it; suspending a pilot or grounding an aircraft strips their future assignments; promoting a banner revision demotes a fabricated banner back to draft. Every resource touched by such a cascade — not just the one named in the request — has its `version` incremented by one and its `updated_at` refreshed, and every computed counter on an affected parent is recomputed at the same moment. A parent whose recomputed counters come back unchanged is not modified: its `version` and `updated_at` stand.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Operation: Bases, Fleet, Routes, and Quotas

Operations begin with a `PlatformAdmin` registering a **Base** — a coastal operating location identified by a unique `code` such as an airfield identifier, plus a human-readable `name`. A base is born with `status` `ACTIVE` and may later be `CLOSED`. Against a base, the platform registers the fleet: each **Aircraft** is created with a system-wide unique `tail_number`, a `model` of `CITABRIA`, `SUPER_CUB`, or `PAWNEE`, a rated `max_tow_weight_lbs`, and a published `hourly_rate_cents` billed per hobbs hour. New aircraft start `ACTIVE` with `season_hours_flown` at zero. Pilots are registered at a base the same way, each with a `full_name`, a unique FAA `certificate_number`, and a `tow_endorsement_level` of `TRAINEE`, `STANDARD`, or `STADIUM_QUALIFIED`; a new pilot is `ACTIVE` with `season_hours_flown` and `season_pickup_failure_count` both at zero. The aircraft collection at a base can be listed with an optional `status` filter, as can the pilot collection, and individual records are retrievable by their `id`.

Routes describe where banners get towed. A **Route** carries a unique `code`, a `kind` of `BEACH`, `STADIUM`, `FESTIVAL`, or `PARADE`, the `base_id` of the base it launches from, a `length_nm` in nautical miles, and a `min_banner_length_ft` — the minimum physical banner length the route requires for visibility. Routes are born `ACTIVE` and may be `RETIRED`; the per-base route listing accepts `kind` and `status` filters. `length_nm` may be any number, while `min_banner_length_ft`, `max_tow_weight_lbs`, and `hourly_rate_cents` must be integers. Finally, the platform declares each base's monthly capacity by creating a `SeasonalCapacity` with a `month_yyyy_mm` and an `aircraft_hour_quota`; the record starts with `hours_committed` at zero and derives `hours_remaining` per §2.8. Uniqueness of the base `code`, aircraft `tail_number`, pilot `certificate_number`, and route `code` is descriptive rather than enforced — the server accepts duplicate values without rejection.

Fleet and crew availability is actively managed over the season. A `GroundCrewLead` (or the platform) can ground an aircraft, moving it from `ACTIVE` to `MAINTENANCE`; the moment that happens, every `SCHEDULED` slot assigned to that aircraft reverts to `BOOKED` with its `assigned_aircraft_id` cleared, and the selector will re-pick an aircraft when those slots are scheduled again. Returning the aircraft flips it back to `ACTIVE`. A `PlatformAdmin` may retire an aircraft — a terminal `RETIRED` state — but only when no `SCHEDULED` slots are assigned to it. Pilots follow a parallel lifecycle: a `PlatformAdmin` may reinstate a `SUSPENDED` pilot back to `ACTIVE`, but only while the pilot's `season_pickup_failure_count` is below three, and may deactivate a pilot to the terminal `INACTIVE` state only when the pilot holds no `SCHEDULED` slots. Every one of these lifecycle transitions validates its from-state and rejects any other with `ERR_INVALID_STATE` (HTTP 409): grounding requires `ACTIVE`, returning to service requires `MAINTENANCE`, retiring requires `ACTIVE` — an aircraft in maintenance cannot be retired — reinstating requires `SUSPENDED`, and deactivating requires `ACTIVE`; the no-`SCHEDULED`-slots preconditions and the reinstatement failure-count limit likewise surface `ERR_INVALID_STATE`. Each of these transitions increments the aircraft's or pilot's `version` by one.

### 3.2. Clients and Campaigns

A `PlatformAdmin` onboards each advertising **Client** with a `legal_name` and a `billing_email`; the record starts with `credit_hold` false and `outstanding_balance_cents` at zero. A `FinanceOfficer` may later set or clear the hold through the credit-hold capability, whose request carries a boolean `credit_hold` field and which updates `credit_hold` and bumps the client's `version`. A client under a credit hold cannot start new work: creating a campaign while `credit_hold` is true is rejected with `ERR_CLIENT_CREDIT_HOLD` (HTTP 402) — the check applies to `PlatformAdmin` callers as well and fires before the ownership comparison, both of them before the campaign payload itself is validated — and the same hold blocks campaign booking with the same error.

A **Campaign** is created under a client with a display `name`, records its owner in `client_id`, and starts in `DRAFT` with all counters at zero. Its `status` walks through `BOOKED`, `IN_FLIGHT`, and the terminal `COMPLETE` or `CANCELLED`. Booking a campaign is the client's act of committing: it requires at least one child slot already in `BOOKED` status — a booking attempt with none fails with `ERR_INVALID_STATE` (HTTP 409) — and requires `expected_campaign_version` per §2.10, and on success the campaign moves from `DRAFT` to `BOOKED` with its `version` incremented. Its checks fire in a fixed order: the from-state check (`DRAFT` only), the at-least-one-`BOOKED`-slot requirement, the credit-hold check, the ownership check, and finally the version comparison. The campaign then advances on its own — the moment its first child slot reaches `SCHEDULED`, the campaign moves from `BOOKED` to `IN_FLIGHT` automatically, and once every child slot sits in a terminal state (`FLOWN`, `CANCELLED_CLIENT`, `CANCELLED_WEATHER`, or `CANCELLED_TFR`) and every invoice issued for the campaign is `PAID` or `VOID` — a condition satisfied vacuously when no invoice has been issued for the campaign — the campaign completes itself to `COMPLETE`. Completion is evaluated only while the campaign is `IN_FLIGHT`; a `BOOKED` campaign whose slots all reach terminal states remains `BOOKED`.

Cancellation is possible from each non-terminal state, with escalating strictness. From `DRAFT`, cancellation requires that no child slot be in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` — otherwise the request fails with `ERR_CAMPAIGN_HAS_OPEN_SLOTS` — and cascades any `DRAFT` slots to `CANCELLED_CLIENT`. From `BOOKED`, the precondition relaxes to forbid only `SCHEDULED` and `WEATHER_HOLD` slots, and the cascade sweeps child slots in `DRAFT` or `BOOKED` to `CANCELLED_CLIENT`, with each cancelled slot accruing a penalty under the weather-cancellation penalty rule of §3.8 and releasing its month of committed seasonal capacity. From `IN_FLIGHT`, the same precondition and the same cascade apply. Only the campaign-owning client may cancel a campaign; anyone else is turned away with `ERR_UNAUTHORIZED_OWNER`, and the ownership check runs after the open-slot precondition.

Three counters keep the campaign's posture visible at a glance: `booked_flight_count` tallies child slots in `BOOKED` or `SCHEDULED`; `flown_flight_count` tallies slots in `FLOWN`; `cancelled_weather_count` tallies slots in `CANCELLED_WEATHER`. A fourth figure, `unapplied_make_good_cents`, sums the `remaining_cents` of the campaign's make-good credits whose status is `OPEN`. Each is recomputed whenever the underlying set changes. A client's campaigns can be listed with a `status` filter, and a per-campaign billing preview (§3.8) is available to the platform, the finance office, and the client.

### 3.3. Banners and Message Revisions

Every campaign fabricates at least one physical **Banner**, created under the campaign with an `artwork_hash` identifying the print-ready artwork file, the current `text_message`, and the physical `banner_length_ft` and `banner_weight_lbs`, both integers. A banner starts in `DRAFT`, and its `current_revision_id` — the pointer to its latest active revision — starts unset. A campaign's banners can be listed with a `status` filter, and a system-wide banner listing supports `current_revision_id` and `status` filters for reverse lookup of which banner a revision currently drives.

Message changes flow through **BannerRevision** records proposed under a banner with a `proposed_text` and a `proposed_artwork_hash`. Each revision receives a `revision_seq` that increases monotonically within its banner, starting at one, and a computed `supersedes_revision_id` pointing at the previous active revision it replaces — empty for the first revision. A revision is born `PROPOSED`, and a revision may be proposed against a banner in any status. Approval is the client's prerogative, and only the campaign-owning client may approve or reject — a `GroundCrewLead` who proposed the artwork cannot approve it, and a non-owning caller is rejected with `ERR_UNAUTHORIZED_OWNER`. Rejection moves the revision to `REJECTED` and ends its story. Approval moves it to `APPROVED`, and the system immediately and automatically promotes it to `ACTIVE`, performing its effects in a pinned order: first the prior `ACTIVE` revision on the same banner becomes `SUPERSEDED`; second, if the banner's status is `IN_FABRICATION` or `READY`, it is forced back to `DRAFT`; third, the banner's `current_revision_id` is updated to the newly active revision, and the banner's `text_message` and `artwork_hash` take on the approved revision's proposed values. The pinned order guarantees the banner never even briefly references a superseded revision as its current one, and both the banner's and the revision's `version` increment. The revision collection of a banner supports a `status` filter; a system-wide revision listing supports `supersedes_revision_id`, `banner_id`, and `status` filters.

Fabrication is the ground crew's domain. A `GroundCrewLead` starts fabrication, moving a banner from `DRAFT` to `IN_FABRICATION`, but only when an active revision exists — otherwise the request fails with `ERR_NO_ACTIVE_REVISION` — and only when the banner's `banner_length_ft` is at least the `min_banner_length_ft` of every route referenced by the parent campaign's slots in `BOOKED`, `SCHEDULED`, `WEATHER_HOLD`, or `FLOWN` status, else `ERR_BANNER_TOO_SHORT` (HTTP 409). The request must carry `expected_banner_version` per §2.10, because a revision promoted since the fabricator last read the banner will have forced it back to `DRAFT` and advanced its version, and printing from a stale revision is exactly the failure this guard exists to prevent. When printing completes, marking the banner ready moves it from `IN_FABRICATION` to `READY`. Retirement from `READY` to the terminal `RETIRED` is permitted only when no flight slot in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` still references the banner; a banner in use cannot be retired and the attempt fails with `ERR_BANNER_IN_USE`. Any later revision promotion — whether the banner sits `IN_FABRICATION` or `READY` — knocks it back to `DRAFT` automatically and updates its `current_revision_id`, so a fabricated banner always reflects the message the client most recently approved.

### 3.4. Airspace Approvals and Stadium TFR Compliance

No flight launches without a per-date **AirspaceApproval** for its route. A `Dispatcher` (or the platform) requests one by supplying the `date_local` service date in `YYYY-MM-DD` form, the approved `window_start_utc`, and the `window_end_utc`, which must fall strictly after the start; the request may also carry `stadium_tfr_waiver`, a boolean that defaults to false and is true only when the FAA has granted a TFR waiver for that window — the flag is accepted on routes of any kind but consulted only for `STADIUM` routes. The approval is born `PENDING`. A `ComplianceOfficer` then dispositions it: granting moves it to `GRANTED`, denying moves it to `DENIED`, and both are terminal. Revocation is the dangerous sibling — a `GRANTED` approval moved to `REVOKED` cascades immediately: every flight slot referencing that approval that is still in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` is cancelled to `CANCELLED_TFR`, and each cancelled slot releases its planned hours back to its month of seasonal capacity. The per-route approval listing supports `status` and `date_local` filters.

Stadium routes live inside Temporary Flight Restrictions. A **TFRRestriction** is published by a `ComplianceOfficer` (or the platform) with the `route_id` it covers, a `starts_utc`, an `ends_utc` strictly after the start, and a free-text `reason` carrying the stadium event code; it is born `PUBLISHED` and can later be cancelled to `CANCELLED`, which is terminal. Overlap between a slot and a TFR is computed on half-open intervals: the slot occupies the span from its `planned_start_utc` up to but not including its start plus its `planned_duration_hours`, and the TFR occupies the span from `starts_utc` up to but not including `ends_utc`. The two overlap when the slot's start falls before the TFR's end and the slot's end falls after the TFR's start; merely touching — a slot ending exactly when a TFR begins — does not count as overlap. When a slot on a `STADIUM` route overlaps any `PUBLISHED` TFR, the booking is rejected with `ERR_TFR_BLOCKS_SLOT` (HTTP 409) unless the slot's airspace approval carries `stadium_tfr_waiver` as true. A route's TFR collection supports a `status` filter.

### 3.5. Booking Flight Slots Against Seasonal Capacity

The **FlightSlot** is where everything converges: a concrete date, route, banner, and planned duration competing for scarce aircraft hours. A slot is nominally born in `DRAFT`, but the creation call is itself the booking — a client (or a dispatcher on the client's behalf) creates and books in one step, so a successful request lands the slot directly in `BOOKED` status. The payload names the `route_id`, the `airspace_approval_id` covering the date, the `banner_id` to be towed, the `date_local` service date, the `planned_start_utc` takeoff instant, and the `planned_duration_hours` as an integer from one to eight; it must also carry `expected_seasonal_capacity_version` per §2.10, and may optionally carry `supersedes_slot_id` when the slot is a make-good replacement for a weather-cancelled predecessor. The slot's `date_local` must equal the approval's `date_local`.

Booking enforces a battery of checks in a fixed order, and the order matters because it decides which rejection a multiply-invalid request surfaces. For the state-check stage of the §2.7 pipeline, creating a flight slot is treated as a transition on the parent campaign: the campaign must be in `DRAFT`, `BOOKED`, or `IN_FLIGHT`, and a creation request against a terminal campaign (`COMPLETE` or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409) before any business rule runs. Payload field validation — required fields, types, and the `planned_duration_hours` range — runs after the campaign path identifier resolves and before the body-referenced foreign keys of §2.6 are resolved. After the generic pipeline of §2.7, the business rules fire in this sequence: first the TFR check of §3.4, then confirmation that the airspace approval is `GRANTED` and covers the slot — a non-granted, date-mismatched, or different-route approval fails with `ERR_AIRSPACE_NOT_APPROVED` (HTTP 409) — then banner readiness, which requires the banner to be `READY` with its `current_revision_id` set and long enough for the route, failing as `ERR_BANNER_NOT_READY` (HTTP 409); the banner is not required to belong to the parent campaign. Next the make-good source check: a `supersedes_slot_id` must name a slot in `CANCELLED_WEATHER` whose credit is still `OPEN` or `PARTIALLY_APPLIED`, failing as `ERR_INVALID_MAKE_GOOD_SOURCE` (HTTP 409); the source slot is not required to belong to the same campaign. The aircraft selector of the following paragraph runs at this point, an empty candidate set failing as `ERR_NO_ELIGIBLE_AIRCRAFT` (HTTP 409). Then the double-booking check — no two slots for the same aircraft may overlap in time on the same half-open interval basis as §3.4 — is applied to exactly the one aircraft the selector returned, with no fallback to a lower-ranked candidate, counting only slots in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` as occupying an aircraft, and failing as `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409). The pilot selector runs next, an empty candidate set failing as `ERR_NO_ELIGIBLE_PILOT` (HTTP 409); no overlap constraint applies to pilots. The two temporal checks follow: the `planned_start_utc` must be at least twenty-four hours in the future at booking time, failing as `ERR_BOOKING_TOO_SOON` (HTTP 409), and the planned window from `planned_start_utc` through its duration must lie entirely inside the approval window — inclusive at both ends, so the planned start may coincide with `window_start_utc` and the planned end with `window_end_utc` — failing as `ERR_OUTSIDE_APPROVAL_WINDOW` (HTTP 409). Capacity is checked next: the `hours_remaining` of the target base-and-month `SeasonalCapacity` must be at least the slot's `planned_duration_hours`, failing as `ERR_SEASONAL_CAPACITY_EXCEEDED` (HTTP 409), and a base-and-month with no `SeasonalCapacity` record at all fails the same way. The client-ownership check runs after the capacity check — a `Client` caller must own the parent campaign — and finally the stale-version comparison of §2.10 runs.

Twice during booking the system drafts resources on the client's behalf. The **aircraft selector** filters the fleet to aircraft homed at the route's base, `ACTIVE`, rated with a `max_tow_weight_lbs` at least the banner's `banner_weight_lbs`, and able to absorb the slot without their `season_hours_flown` plus the planned duration exceeding the hard cap of six hundred season hours. Survivors are ranked by a score of season hours flown multiplied by one hundred plus the aircraft's `hourly_rate_cents` divided by one thousand — lower wins, preferring to spread hours across the fleet and breaking value ties toward the cheaper rate — and exact ties break by earliest `created_at` and then by insertion sequence, never by identifier. An empty candidate set fails the booking with `ERR_NO_ELIGIBLE_AIRCRAFT` (HTTP 409). The **pilot selector** runs after the aircraft selector with the same shape: pilots homed at the route's base, `ACTIVE`, with a `season_pickup_failure_count` below three, holding `STADIUM_QUALIFIED` endorsement whenever the route's `kind` is `STADIUM`, and able to absorb the slot without exceeding the pilot hard cap of five hundred season hours. The pilot score is season hours flown times one hundred minus an endorsement bonus — endorsement rank times fifty, where `TRAINEE` ranks zero, `STANDARD` ranks one, and `STADIUM_QUALIFIED` ranks two — again lower wins, ties broken by earliest `created_at` and then by insertion sequence, and an empty set fails with `ERR_NO_ELIGIBLE_PILOT` (HTTP 409). The winners are written to the slot as `assigned_aircraft_id` and `assigned_pilot_id`.

A successful booking consumes capacity immediately: the month's `hours_committed` increases by the planned duration and the capacity record's `version` increments, the campaign's `booked_flight_count` is recomputed, and the campaign's own `version` advances by one — which is precisely why the campaign-booking OCC guard of §2.10 exists. The slot's `weather_hold_count` starts at zero, and `consumed_make_good_credit_id` stays unset until invoice time. A campaign's slot collection can be filtered by `status` and `date_local`; a system-wide slot listing supports `route_id`, `airspace_approval_id`, `banner_id`, `assigned_aircraft_id`, `assigned_pilot_id`, `supersedes_slot_id`, `consumed_make_good_credit_id`, `campaign_id`, `status`, and `date_local` filters.

### 3.6. Flight-Day Operations: Scheduling, Weather Calls, and the Flight Log

Scheduling is the dispatcher's commitment that a booked slot will actually launch. Moving a slot from `BOOKED` to `SCHEDULED` requires the request to arrive at least two hours before `planned_start_utc` — anything closer is rejected with `ERR_TOO_LATE_TO_SCHEDULE` (HTTP 409) — and requires the assigned aircraft and assigned pilot both to be `ACTIVE`: the aircraft is checked first and a non-`ACTIVE` aircraft fails with `ERR_INVALID_STATE` (HTTP 409), a suspended pilot fails with `ERR_PILOT_SUSPENDED` (HTTP 409), and a pilot in any other non-`ACTIVE` state fails with `ERR_INVALID_STATE` (HTTP 409). When a prior cascade cleared an assignment, the §3.5 selectors re-pick at scheduling time and their empty-set errors surface here as well. The first scheduling under a `BOOKED` campaign pushes the campaign itself into `IN_FLIGHT` automatically, per §2.11.

On the day of flight, weather calls are recorded as immutable **WeatherAssessment** records against the slot, each carrying the reported `ceiling_ft` in feet above ground, `visibility_sm` in statute miles, and `wind_kts` surface wind — `ceiling_ft` and `wind_kts` must be integers, while `visibility_sm` may be any number. Assessments are accepted only for a slot in `SCHEDULED` or `WEATHER_HOLD`; any other slot state fails with `ERR_INVALID_STATE` (HTTP 409). The server stamps `assessed_at_utc` and records the assessing pilot in the `assessed_by_pilot_id` field — the calling pilot when a `Pilot` files the assessment, and the slot's assigned pilot when a `Dispatcher` or `PlatformAdmin` does — then derives the `verdict` from fixed VFR minima: visibility below 3.0 statute miles, or a ceiling below 1,000 feet, or surface wind above 25 knots yields `NO_GO`; failing that, visibility below 5.0 statute miles, or a ceiling below 1,500 feet, or wind above 18 knots yields `MARGINAL`; anything better yields `GO`. A `GO` or `MARGINAL` verdict leaves the slot's state untouched — marginal weather is logged for the record but never moves the slot. A `NO_GO` verdict drives the state machine: the slot moves from `SCHEDULED` to `WEATHER_HOLD` and its `weather_hold_count` increments by one, except when the increment would bring the count to two or more, in which case the slot is cancelled outright to `CANCELLED_WEATHER`. The same rule fires from `WEATHER_HOLD` itself — a further `NO_GO` against a held slot cancels it. Cancellation by weather is never billed; instead the system creates a **MakeGoodCredit** whose `original_cents` equals the source slot's `planned_duration_hours` multiplied by the assigned aircraft's `hourly_rate_cents`, whose `expires_on_local` falls exactly thirty days after the source slot's `date_local`, and whose `remaining_cents` starts equal to that original value with the credit in `OPEN` status. The cancelled slot's planned hours release back to seasonal capacity, and the campaign's `cancelled_weather_count` is recomputed. A slot's assessments can be listed in order, a system-wide listing supports `assessed_by_pilot_id` and `slot_id` filters, and any single assessment is retrievable by `id`.

A held slot is not dead. The dispatcher can reschedule from `WEATHER_HOLD` back to `SCHEDULED` by supplying a new `planned_start_utc`, provided the new start still falls inside the approval window — failing as `ERR_OUTSIDE_APPROVAL_WINDOW` (HTTP 409) — and the slot's `weather_hold_count` is below two; a slot that has already held twice fails with `ERR_INVALID_STATE` (HTTP 409) and must be cancelled to `CANCELLED_WEATHER` instead of rescheduled.

After the flight, the assigned pilot — and only the assigned pilot — files the **FlightLog**; anyone else is rejected with `ERR_UNAUTHORIZED_OWNER` (HTTP 403). Filing carries `hobbs_out` from engine start, `hobbs_in` from shutdown, the `pickup_technique` of `GROUND_PICKUP` or `AERIAL_PICKUP`, the `pickup_outcome` of `CLEAN`, `RETRIED`, or `FAILED`, and free-text `tow_field_notes`. Four guards fire in a fixed order: first the endorsement check — an `AERIAL_PICKUP` technique filed by a `TRAINEE` pilot is rejected with `ERR_PICKUP_TECHNIQUE_NOT_ENDORSED` (HTTP 409); then the hobbs sanity check — `hobbs_in` must be strictly greater than `hobbs_out`, else `ERR_INVALID_HOBBS` (HTTP 422); then the assigned-pilot ownership check; then segregation of duties — a `ComplianceOfficer` who granted the airspace approval under which the slot flew may not file its flight log, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful filing transitions the slot from `SCHEDULED` to `FLOWN`, stamps `filed_at_utc`, and copies the slot's `assigned_aircraft_id` and `assigned_pilot_id` onto the log as its `aircraft_id` and `pilot_id`. The log's `hobbs_hours` — the difference between the two readings, rounded to the nearest tenth of an hour — accrues to both the aircraft's and the pilot's `season_hours_flown` when the flight falls within the May-to-September season, and the campaign's `flown_flight_count` is recomputed.

Pickup failures carry a career consequence. A log filed with `pickup_outcome` `FAILED` increments the pilot's `season_pickup_failure_count` by one; when that count reaches three — exactly three suspends, two does not — the pilot is automatically suspended to `SUSPENDED`, and every `SCHEDULED` slot assigned to that pilot reverts to `BOOKED` with its `assigned_pilot_id` cleared for re-selection. The filing touches three versioned resources at once: the slot, the aircraft, and the pilot each increment their `version` by one. A client may also walk away from a slot before it flies: cancelling from `BOOKED` or `SCHEDULED` moves the slot to `CANCELLED_CLIENT`, releases its committed seasonal hours, records the cancellation instant as `cancelled_at_utc` for the penalty computation of §3.8, and is restricted to the campaign-owning client under the same `ERR_UNAUTHORIZED_OWNER` rule. Slots can also die without anyone's request: the approval-revocation cascade of §3.4 moves `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` slots to `CANCELLED_TFR`, releasing capacity the same way. A slot's flight logs — at most one — are listable per slot, and a system-wide log listing supports `aircraft_id`, `pilot_id`, and `slot_id` filters.

### 3.7. Proof of Flight Documentation

Every flown slot owes the client evidence. The assigned pilot submits a **ProofOfFlight** bundle containing the `gps_track_digest` — a SHA-256 of the GPS track file — the `photo_hash` of the banner-in-flight photograph, and a `pilot_attestation` boolean affirming the flight occurred as logged. The server stamps `submitted_at_utc` and creates the bundle with `finalized` false. Proof can only be submitted for a slot in `FLOWN` status; submitting against a slot in any other state is rejected with `ERR_SLOT_NOT_FLOWN` (HTTP 409), and as with the flight log, only the assigned pilot may submit — anyone else draws `ERR_UNAUTHORIZED_OWNER`. A slot accepts only one bundle: a second submission fails with `ERR_INVALID_STATE` (HTTP 409). A `ComplianceOfficer` then reviews and finalizes the bundle, setting `finalized` to true; finalization carries no from-state check, so finalizing an already-finalized bundle succeeds without further effect. An invoice line for a flight is not considered final until its proof bundle is on file, and a slot's proof — at most one — is retrievable per slot by the platform, compliance, finance, the client, and the pilot.

### 3.8. Monthly Billing, Make-Good Credits, and Settlement

Billing runs monthly per campaign. A `FinanceOfficer` issues an **Invoice** by naming the `period_yyyy_mm` billing period — issuance requires no particular campaign state, permits multiple invoices for the same period, and tolerates an invoice whose figures are all zero — and the system computes four figures in a pinned order. First the flight subtotal: every `FLOWN` slot whose flight log's `filed_at_utc` falls inside the period contributes a line, processed in order of `filed_at_utc` ascending with ties broken by the log's `created_at` ascending; each line is the log's `hobbs_hours` multiplied by the assigned aircraft's `hourly_rate_cents`, rounded half-up to a whole cent before any summation. A tiered volume discount then applies across the whole invoice, not per line: when the period's total hobbs hours are twenty or fewer the discount is zero percent; above twenty and up to fifty hours the discount is five percent; above fifty hours it is ten percent. The `flight_subtotal_cents` is the sum of the per-line amounts, multiplied by one minus the discount fraction, rounded half-up to a whole cent — the discount factor itself is never rounded, and the per-line rounding strictly precedes the discount rounding.

Second, penalties: for every slot cancelled by the client whose recorded `cancelled_at_utc` falls inside the period, the penalty is a fraction of the slot's planned value — its `planned_duration_hours` times the aircraft's `hourly_rate_cents` — and the fraction depends on notice, the span between the recorded `cancelled_at_utc` and the `planned_start_utc`. Notice of at least seventy-two hours incurs no penalty, and the boundary is inclusive: exactly seventy-two hours means zero. Notice of at least twenty-four hours but under seventy-two incurs twenty-five percent of the planned value, rounded half-up per slot, with the twenty-four-hour boundary also inclusive. Notice under twenty-four hours incurs fifty percent, rounded the same way. The `cancellation_penalty_cents` is the sum of these per-slot penalties.

Third, make-good credits apply as a waterfall. The eligible set is the campaign's credits in `OPEN` or `PARTIALLY_APPLIED` status whose `expires_on_local` falls on or after the period's end date — the last calendar day of the period month — ordered by earliest expiry first and, among equal expiries, by earliest `created_at`. Starting from the available pool of `flight_subtotal_cents` plus `cancellation_penalty_cents`, each credit in order applies the smaller of its `remaining_cents` and the pool not yet covered by previously applied credits; the applied amount accumulates into `make_good_applied_cents`, the credit's `remaining_cents` decreases by the same amount, and the credit lands in `FULLY_APPLIED` when its remainder reaches zero or `PARTIALLY_APPLIED` otherwise. A credit partially consumed moves from `OPEN` to `PARTIALLY_APPLIED` the same way. The consuming slot — the earliest-created slot of the campaign whose `supersedes_slot_id` names the credit's source slot and which has not already recorded a credit — records it in `consumed_make_good_credit_id`. All credit arithmetic is exact integer cents with no rounding. Finally, `total_cents` is the available pool minus the applied credits, floored at zero, and `balance_due_cents` opens equal to `total_cents` at issuance, to be decremented later by payment applications which are out of scope for this version. The invoice is born `ISSUED`, the client's `outstanding_balance_cents` — the sum of `balance_due_cents` across all non-`PAID` invoices — is recomputed, and the campaign's `unapplied_make_good_cents` reflects whatever the waterfall left behind.

Clients and finance can preview all of this before committing: the billing preview takes the period as the `period_yyyy_mm` query parameter — a missing or malformed period fails with `ERR_INVALID_REQUEST` (HTTP 400) — and returns the same four figures — `flight_subtotal_cents`, `cancellation_penalty_cents`, `make_good_applied_cents`, and `total_cents` — but computed provisionally, counting slots still in `BOOKED` or `SCHEDULED` at their `planned_duration_hours`, keyed to the period by the slot's `date_local` month, alongside the actual `hobbs_hours` of `FLOWN` slots keyed by the log's `filed_at_utc` month, with the same tiered volume discount applied over the combined provisional hours, and never including penalties or credit applications — so `cancellation_penalty_cents` and `make_good_applied_cents` are always zero in a preview and `total_cents` equals the preview subtotal. The final invoice, by contrast, counts only `FLOWN` slots and includes both penalties and credits.

Settlement closes the loop. Marking an invoice paid moves it from `ISSUED` to `PAID` and recomputes the client's outstanding balance. Voiding an invoice is the compensating action: the invoice moves to `VOID`, every make-good credit that was applied to it reverts — its `remaining_cents` restored and its status returning to `OPEN` or `PARTIALLY_APPLIED` as the restored remainder warrants — and the outstanding balance is recomputed again. A campaign's invoices can be listed with `status` and `period_yyyy_mm` filters, and its credits with a `status` filter; a system-wide credit listing supports `source_slot_id`, `campaign_id`, and `status` filters, and each credit carries its `source_slot_id` back to the weather-cancelled slot that created it.

Credits do not live forever. A `PlatformAdmin` runs the periodic ops checkpoint for a base — the named base must exist, but the sweep itself is global across all bases — which sweeps every credit still `OPEN` or `PARTIALLY_APPLIED` whose `expires_on_local` has fallen before the current local date and flips it to `EXPIRED`, recomputing each affected campaign's `unapplied_make_good_cents`. The checkpoint reports how many credits it expired in the `expired_credit_count` field and lists their identifiers in the `expired_credit_ids` field in ascending `created_at` order.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below is a navigational summary only — request payloads, computed fields, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/btaa/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/btaa/bases` | Create a Base | PlatformAdmin |
| GET | `/btaa/bases/{id}` | Get a Base | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer |
| POST | `/btaa/bases/{id}/aircraft` | Register an Aircraft at a Base | PlatformAdmin |
| GET | `/btaa/bases/{id}/aircraft` | List Aircraft at a Base | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer, Client |
| GET | `/btaa/aircraft/{id}` | Get an Aircraft | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer |
| POST | `/btaa/aircraft/{id}/ground` | Ground an Aircraft (cascades scheduled slots to booked) | GroundCrewLead, PlatformAdmin |
| POST | `/btaa/aircraft/{id}/return_to_service` | Return an Aircraft to service | GroundCrewLead, PlatformAdmin |
| POST | `/btaa/aircraft/{id}/retire` | Retire an Aircraft (terminal) | PlatformAdmin |
| POST | `/btaa/bases/{id}/pilots` | Register a Pilot at a Base | PlatformAdmin |
| GET | `/btaa/bases/{id}/pilots` | List Pilots at a Base | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer |
| GET | `/btaa/pilots/{id}` | Get a Pilot | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer, Pilot |
| POST | `/btaa/pilots/{id}/reinstate` | Reinstate a suspended Pilot | PlatformAdmin |
| POST | `/btaa/pilots/{id}/deactivate` | Deactivate a Pilot (terminal) | PlatformAdmin |
| POST | `/btaa/routes` | Create a Route | PlatformAdmin |
| GET | `/btaa/routes/{id}` | Get a Route | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer, Client, Pilot |
| GET | `/btaa/bases/{id}/routes` | List Routes homed at a Base | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, FinanceOfficer, Client, Pilot |
| POST | `/btaa/clients` | Create a Client | PlatformAdmin |
| GET | `/btaa/clients/{id}` | Get a Client | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| POST | `/btaa/clients/{id}/set_credit_hold` | Set or clear a Client's credit hold | FinanceOfficer |
| POST | `/btaa/clients/{id}/campaigns` | Create a Campaign under a Client | Client, PlatformAdmin |
| GET | `/btaa/clients/{id}/campaigns` | List Campaigns for a Client | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Dispatcher, Client |
| GET | `/btaa/campaigns/{id}` | Get a Campaign | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Dispatcher, Client, Pilot, GroundCrewLead |
| POST | `/btaa/campaigns/{id}/book` | Book a Campaign (OCC on campaign version) | Client |
| POST | `/btaa/campaigns/{id}/cancel` | Cancel a Campaign (cascades non-terminal slots) | Client |
| GET | `/btaa/campaigns/{id}/billing_preview` | Provisional billing preview for a period | PlatformAdmin, FinanceOfficer, Client |
| POST | `/btaa/campaigns/{id}/banners` | Create a Banner for a Campaign | Client, PlatformAdmin |
| GET | `/btaa/campaigns/{id}/banners` | List Banners for a Campaign | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/banners/{id}` | Get a Banner | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client, Pilot |
| POST | `/btaa/banners/{id}/fabricate` | Start Banner fabrication (OCC on banner version) | GroundCrewLead |
| POST | `/btaa/banners/{id}/mark_ready` | Mark a Banner ready | GroundCrewLead |
| POST | `/btaa/banners/{id}/retire` | Retire a Banner (terminal) | GroundCrewLead |
| POST | `/btaa/banners/{id}/revisions` | Propose a BannerRevision | Client, GroundCrewLead |
| GET | `/btaa/banners/{id}/revisions` | List BannerRevisions for a Banner | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client |
| GET | `/btaa/banner_revisions/{id}` | Get a BannerRevision | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client |
| POST | `/btaa/banner_revisions/{id}/approve` | Approve a BannerRevision (auto-activates; supersedes prior) | Client |
| POST | `/btaa/banner_revisions/{id}/reject` | Reject a BannerRevision | Client |
| POST | `/btaa/routes/{id}/airspace_approvals` | Request an AirspaceApproval for a route and date | Dispatcher, PlatformAdmin |
| GET | `/btaa/routes/{id}/airspace_approvals` | List AirspaceApprovals for a Route | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/airspace_approvals/{id}` | Get an AirspaceApproval | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| POST | `/btaa/airspace_approvals/{id}/grant` | Grant an AirspaceApproval | ComplianceOfficer |
| POST | `/btaa/airspace_approvals/{id}/deny` | Deny an AirspaceApproval | ComplianceOfficer |
| POST | `/btaa/airspace_approvals/{id}/revoke` | Revoke an AirspaceApproval (cascades slots to cancelled-TFR) | ComplianceOfficer |
| POST | `/btaa/tfr_restrictions` | Publish a TFRRestriction | ComplianceOfficer, PlatformAdmin |
| GET | `/btaa/routes/{id}/tfr_restrictions` | List TFRs for a Route | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/tfr_restrictions/{id}` | Get a TFRRestriction | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| POST | `/btaa/tfr_restrictions/{id}/cancel` | Cancel a TFRRestriction | ComplianceOfficer |
| POST | `/btaa/bases/{id}/seasonal_capacities` | Define a monthly aircraft-hour quota for a Base | PlatformAdmin |
| GET | `/btaa/bases/{id}/seasonal_capacities` | List SeasonalCapacities for a Base | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client |
| GET | `/btaa/seasonal_capacities/{id}` | Get a SeasonalCapacity | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client |
| POST | `/btaa/campaigns/{id}/flight_slots` | Create and book a FlightSlot (OCC on seasonal capacity; selectors assign aircraft and pilot) | Client, Dispatcher |
| GET | `/btaa/campaigns/{id}/flight_slots` | List FlightSlots for a Campaign | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot, GroundCrewLead |
| GET | `/btaa/flight_slots/{id}` | Get a FlightSlot | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot, GroundCrewLead |
| POST | `/btaa/flight_slots/{id}/schedule` | Schedule a booked FlightSlot | Dispatcher |
| POST | `/btaa/flight_slots/{id}/weather_assessments` | Record a WeatherAssessment (NO_GO drives hold or cancellation) | Pilot, Dispatcher, PlatformAdmin |
| POST | `/btaa/flight_slots/{id}/reschedule_after_hold` | Reschedule a slot out of weather hold | Dispatcher |
| POST | `/btaa/flight_slots/{id}/flight_log` | Pilot files the FlightLog; slot becomes flown | Pilot |
| POST | `/btaa/flight_slots/{id}/cancel_by_client` | Client cancels a booked or scheduled slot (penalty accrues) | Client |
| GET | `/btaa/flight_slots/{id}/weather_assessments` | List WeatherAssessments for a FlightSlot | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/flight_slots/{id}/flight_logs` | List FlightLogs for a FlightSlot | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/flight_slots/{id}/proof_of_flight` | List ProofOfFlight bundles for a FlightSlot | PlatformAdmin, ComplianceOfficer, Client, Pilot, FinanceOfficer |
| POST | `/btaa/flight_slots/{id}/proof_of_flight` | Submit ProofOfFlight for a flown slot | Pilot |
| POST | `/btaa/proof_of_flight/{id}/finalize` | Finalize a ProofOfFlight bundle | ComplianceOfficer |
| GET | `/btaa/campaigns/{id}/make_good_credits` | List MakeGoodCredits for a Campaign | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| GET | `/btaa/make_good_credits/{id}` | Get a MakeGoodCredit | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| POST | `/btaa/campaigns/{id}/invoices` | Issue an Invoice for a period | FinanceOfficer |
| GET | `/btaa/campaigns/{id}/invoices` | List Invoices for a Campaign | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| GET | `/btaa/invoices/{id}` | Get an Invoice | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| POST | `/btaa/invoices/{id}/mark_paid` | Mark an Invoice paid | FinanceOfficer |
| POST | `/btaa/invoices/{id}/void` | Void an Invoice (restores applied credits) | FinanceOfficer |
| GET | `/btaa/weather_assessments/{id}` | Get a WeatherAssessment by id | PlatformAdmin, Dispatcher, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/flight_logs/{id}` | Get a FlightLog by id | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/banners` | Filtered list of Banners | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client |
| GET | `/btaa/banner_revisions` | Filtered list of BannerRevisions | PlatformAdmin, Dispatcher, GroundCrewLead, ComplianceOfficer, Client |
| GET | `/btaa/flight_slots` | Filtered list of FlightSlots | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot, GroundCrewLead |
| GET | `/btaa/weather_assessments` | Filtered list of WeatherAssessments | PlatformAdmin, Dispatcher, ComplianceOfficer, Pilot |
| GET | `/btaa/flight_logs` | Filtered list of FlightLogs | PlatformAdmin, Dispatcher, FinanceOfficer, ComplianceOfficer, Client, Pilot |
| GET | `/btaa/make_good_credits` | Filtered list of MakeGoodCredits | PlatformAdmin, FinanceOfficer, ComplianceOfficer, Client |
| POST | `/btaa/bases/{id}/run_ops` | Ops checkpoint: expire stale MakeGoodCredits | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_UNAUTHORIZED_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_HOBBS` | 422 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_TFR_BLOCKS_SLOT` | 409 |
| `ERR_AIRSPACE_NOT_APPROVED` | 409 |
| `ERR_OUTSIDE_APPROVAL_WINDOW` | 409 |
| `ERR_BOOKING_TOO_SOON` | 409 |
| `ERR_TOO_LATE_TO_SCHEDULE` | 409 |
| `ERR_SEASONAL_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_ELIGIBLE_AIRCRAFT` | 409 |
| `ERR_NO_ELIGIBLE_PILOT` | 409 |
| `ERR_AIRCRAFT_DOUBLE_BOOKED` | 409 |
| `ERR_BANNER_NOT_READY` | 409 |
| `ERR_BANNER_TOO_SHORT` | 409 |
| `ERR_BANNER_IN_USE` | 409 |
| `ERR_NO_ACTIVE_REVISION` | 409 |
| `ERR_INVALID_MAKE_GOOD_SOURCE` | 409 |
| `ERR_CAMPAIGN_HAS_OPEN_SLOTS` | 409 |
| `ERR_CLIENT_CREDIT_HOLD` | 402 |
| `ERR_PICKUP_TECHNIQUE_NOT_ENDORSED` | 409 |
| `ERR_PILOT_SUSPENDED` | 409 |
| `ERR_SLOT_NOT_FLOWN` | 409 |
| `ERR_INTERNAL` | 500 |

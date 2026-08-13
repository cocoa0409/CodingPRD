# Real Estate Media API — Product Requirements Document

## 1. Introduction

A real estate listing lives or dies by its imagery, and producing that imagery is an orchestration problem: a shoot must be booked against a market's rate card, the property must be certified ready before a crew rolls, a photographer with the right equipment package — and, for aerial work, the right certification — must be matched to a time window that respects travel buffers and daily capacity, weather must be allowed to move a shoot without punishing the client, and the finished photos and virtual tour must be delivered, revised under a quality guarantee, licensed, and published. This document specifies the Real Estate Media API, the system of record a real-estate media company uses to run that pipeline end to end.

The API governs the full lifecycle of a shoot booking: from a client agent's first draft through property-readiness attestation, coordinator assignment, airspace authorization for drone work, the shoot itself, editing and delivery against a turnaround deadline, client revisions, and final acceptance — the atomic event that computes the invoice, activates the media license, and publishes the hosted virtual tour. Markets define pricing multipliers, turnaround standards, twilight slots, travel buffers, and weather-credit policy. Photographers carry equipment packages, drone certification, and per-day capacity limits. A set of automatic transitions keeps dependent entities — add-ons, authorizations, asset bundles, revisions, tours, and licenses — consistent as bookings are submitted, assigned, rescheduled, delivered, or cancelled.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The platform recognizes exactly four roles: `ClientAgent`, `Photographer`, `Coordinator`, and `OpsAdmin`. A request with a missing header, or an `X-User-Role` value outside that set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is simply not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ClientAgent`, `X-User-ID` is the `id` of the acting `ClientAgent`; ownership checks on any resource that references a ClientAgent — above all a booking's `client_agent_id` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `Photographer`, `X-User-ID` is the `id` of the acting `Photographer`; assignment-scoped checks compare a booking's `assigned_photographer_id` to `X-User-ID`, again raising `ERR_FORBIDDEN` on mismatch. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the same is true when `X-User-Role` is `OpsAdmin`: the server may record such identifiers but never compares them to any entity's `id`.

In broad strokes: a ClientAgent books shoots, attests property readiness, requests revisions, and accepts delivery; a Photographer shoots assigned bookings, delivers edited bundles, and claims revisions; a Coordinator assigns and unassigns photographers, confirms bookings, and resubmits airspace authorizations; an OpsAdmin operates the platform itself — markets, photographer and agent registration, airspace decisions, tour and license governance, and the logical clock. Section 4 gives the authoritative per-endpoint role list.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how much of the collection remains unread.

### 2.4. Markets, Rate Cards, and Monetary Precision

A **Market** is the pricing and policy root for everything booked within it. Each market is registered with a `market_code` — unique across all markets, two to twelve characters of uppercase alphanumerics and dashes (for example `ATX` or `DEN`) — plus a human-readable `display_name`. Four numeric policies ride on the market: `pricing_multiplier_bps`, a pricing multiplier expressed in basis points and constrained to the range 5000 through 30000, where 10000 means exactly the base rate card and a value such as 12500 applies a 1.25x uplift; `standard_turnaround_hours`, the base editing turnaround in whole hours, constrained to 12 through 120; `twilight_slot_minutes`, the length of one twilight shoot slot, defaulting to 60 and constrained to 30 through 120 in multiples of 15; and `travel_buffer_minutes`, the minimum gap between back-to-back shoots for one photographer, defaulting to 45 and constrained to 0 through 180. A fifth policy, `weather_reschedule_credit_bps`, controls the credit granted on a weather reschedule as basis points of the booking's locked quote; it defaults to 1000 and may range from 0 to 5000. Every market carries a `status` of `ACTIVE` or `SUSPENDED`, and new markets start `ACTIVE`.

All money in the system is carried as integer cents. Monetary calculations round half-up to whole cents, and multi-line calculations round each line individually before summing — never the reverse. Durations are whole minutes; deadlines are computed to whole-second precision over ISO 8601 instants. Because every money line is multiplied by the market factor before its line-level rounding, a market whose multiplier differs from 10000 reprices every line of a quote, not just the base.

An OpsAdmin may reconfigure a market's `pricing_multiplier_bps`, `standard_turnaround_hours`, `twilight_slot_minutes`, `travel_buffer_minutes`, or `weather_reschedule_credit_bps`, and may flip its `status` between `ACTIVE` and `SUSPENDED`, through the market-update capability; each such update increments the market's `version`. Suspending a market blocks new booking submissions for that market — a submission into a `SUSPENDED` market fails with `ERR_MARKET_SUSPENDED` — while bookings already in flight are entirely unaffected.

### 2.5. Common Resource Properties and Audit Fields

Every primary resource — markets, photographers, client agents, bookings, checklist items, add-ons, airspace authorizations, asset bundles, revision requests, virtual tours, and license grants — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including server-side cascades that touch it.

The three-fractional-digit form is reserved for `api_request_timestamp`, `created_at`, and `updated_at`. Every other datetime value the API emits — `scheduled_start_utc`, `scheduled_end_utc`, `delivery_due_utc`, `delivered_at_utc`, `revision_window_closes_utc`, `checked_at_utc`, `window_start_utc`, `window_end_utc`, `decided_at_utc`, `published_at_utc`, `activated_at_utc`, `old_start_utc`, `new_start_utc`, and the clock endpoint's `now_utc` — is rendered as an ISO 8601 UTC instant at whole-second precision, with no fractional digits (for example `2026-08-10T14:00:00Z`).

The one exception is the **RescheduleEvent**, which is an immutable, append-only history record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent, since a reschedule event is never modified after it is written.

### 2.6. Optimistic Concurrency Control

Two write operations on a booking are guarded by optimistic concurrency control, and both use the same mechanism. A `PATCH /shoot-bookings/{id}` request — the mutable-fields update — must carry `expected_booking_version`, holding the booking `version` value the client last observed. A `POST /shoot-bookings/{id}/reschedule` request must likewise carry `expected_booking_version`. On either endpoint, if the supplied value no longer equals the booking's current `version` — because another write has legitimately advanced the version since the client last read the resource, for instance a submission that locked the quote, or an add-on activation that recomputed the scheduled window — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the booking before retrying. Endpoints not named here do not accept a version field at all.

### 2.7. Photographer Scheduling Invariants

Photographer calendars obey two hard invariants, evaluated whenever a booking is assigned, whenever a booking is rescheduled onto a photographer's new window, and whenever a twilight upgrade is activated.

The first invariant is temporal separation. For a candidate window, the server widens both ends by the market's `travel_buffer_minutes` and tests the widened interval against every other booking assigned to that photographer in `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED` state. Because the intersection test treats the widened intervals as open, adjacency is permitted when the gap between two shoots is at least the travel buffer — a gap exactly equal to the buffer is allowed, while anything shorter is a conflict rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (HTTP 409).

Twilight work is stricter. A twilight booking occupies exactly one slot running from its slot start for the market's `twilight_slot_minutes`, and twilight slots are exclusive per photographer per evening: two twilight bookings for the same photographer in the same market on the same evening always conflict, regardless of the buffer, because the overlap test for twilight work is applied to the raw slot interval before any buffer expansion.

The second invariant is daily capacity. Each photographer maintains `committed_minutes_by_day`, a map from UTC calendar date (in `YYYY-MM-DD` form) to the total committed, non-cancelled shoot minutes for that day, recomputed on every assignment change. Adding a booking's window to a photographer's day must not push that day's total over the photographer's `max_shoot_minutes_per_day`; a total exactly equal to the cap is permitted, and only a strictly greater total is rejected with `ERR_DAY_CAPACITY_EXCEEDED` (HTTP 409).

### 2.8. Validation Precedence

Malformed requests — a missing required field, an invalid enum value, or otherwise malformed input — fail fast with `ERR_INVALID_REQUEST` (HTTP 400) before any business validation begins. Beyond that, when a single request could fail several checks, the server evaluates them in a fixed precedence order and reports only the first applicable failure; an earlier tier masks every later tier. The order is:

1. **User context** — missing or invalid `X-User-ID` / `X-User-Role` headers fail with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — a role not permitted for the endpoint fails with `ERR_UNAUTHORIZED_ROLE` (403).
3. **Existence** — unknown path identifiers or a broken parent chain fail with `ERR_NOT_FOUND` (404).
4. **State legality** — the target entity is not in a state that permits the operation, reported as the operation's specific state error (for example `ERR_BOOKING_NOT_IN_DRAFT`) or, generically, `ERR_INVALID_STATE` (409).
5. **Temporal rules** — lead-time, quarter-hour alignment, shoot-window, cancellation-cutoff, and revision-window checks, typified by `ERR_SLOT_TOO_SOON` (422).
6. **Airspace-safety rules** — drone certification, authorization attempt caps, lapsed authorization windows, and the unbranded-tier rule, typified by `ERR_DRONE_CERT_REQUIRED` (422).
7. **Resource constraints** — overlap, day-capacity, equipment-match, duplicate-drone, reschedule-cap, revision-cap, and readiness-completeness checks, typified by `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (409).
8. **Cross-entity referential gates** — open revisions at acceptance, quality and tour-asset gates at delivery, and open commitments at photographer deactivation, typified by `ERR_OPEN_REVISIONS_EXIST` (409).
9. **Fiscal sanity** — invoice invariants at acceptance, reported as `ERR_INVOICE_INCONSISTENT` (422).

A request that fails at tier one is never reported as a tier-seven conflict, even when both conditions happen to hold.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. For a path such as `/shoot-bookings/{id}/addons/{addonId}`, the server first confirms that `{id}` identifies an existing booking and only then looks up `{addonId}` beneath it; the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, or when a child resource exists but does not belong to the named parent. The same left-to-right rule applies to checklist items, airspace authorizations, asset bundles, and revision requests nested under a booking, and to bookings nested under a photographer or client agent: the parent chain — add-on to booking, authorization to booking, revision to booking, bundle to booking, booking to market — must chain correctly before any business rule is evaluated.

### 2.10. The Logical Clock

All time-dependent behavior in the system reads from a single logical clock, not from wall-clock time. Before any clock-setting call is made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock. An OpsAdmin may advance it through an admin-only, test-driving capability that accepts a target instant as `to_iso8601` and answers with the resulting `now_utc`.

Advancing the clock is what drives the system's automatic transitions: bookings still sitting in `DRAFT`, `AWAITING_READINESS`, or `READY` when the clock reaches their scheduled start expire on the spot; an approved airspace authorization whose window end passes before the shoot is marked complete lapses; and a revision window that closes with a revision still open resolves that revision as too late. Sections 3.5, 3.7, and 3.9 describe each of these cascades where they live.

## 3. Business Logic & Workflows

### 3.1. Booking Intake and the Provisional Quote

Before any booking exists, the platform's back office registers its participants. An OpsAdmin registers each client agent with the `brokerage_name` they belong to, a `full_name`, a contact `email` that must be unique across all client agents, and the `home_market_id` of their home market; every agent starts with a prepaid `credit_balance_cents` of zero, which is where weather credits and refunds accrue over the agent's lifetime. The agent directory can be listed and filtered by `home_market_id`. Photographer registration works the same way and is described in §3.3.

A `ClientAgent` begins an order by creating a booking with a client-facing `order_ref` — unique across all bookings — the `market_id` of the market where the property sits, the `property_address`, the contracted `equipment_package` of `STANDARD`, `PREMIUM`, or `LUXURY`, a `photo_count` of contracted edited photos between 10 and 100, and a committed `scheduled_start_utc` that must land on a quarter-hour boundary; a start that is not aligned to a quarter hour is rejected with `ERR_INVALID_SLOT_ALIGNMENT`. Optional intent flags ride along: `wants_virtual_tour` defaults to false; `tour_variant` of `BRANDED` or `UNBRANDED` defaults to null and is required exactly when `wants_virtual_tour` is true — omitting it then is an `ERR_INVALID_REQUEST` — and note that choosing `UNBRANDED` carries a licensing obligation that is only enforced later, at acceptance, not at creation or delivery; `license_tier` of `MLS_COMPLIANT`, `STANDARD_MARKETING`, or `EXTENDED` defaults to `MLS_COMPLIANT` and remains upgradeable until delivery acceptance; and `is_twilight` defaults to false. The server stamps the booking's `client_agent_id` from the caller's `X-User-ID`, so an agent's bookings are always attributable to the account that created them. The booking is born in `DRAFT`, and the server immediately computes its `shoot_duration_minutes` and `scheduled_end_utc`.

The shoot-duration rule works as follows. The base length depends on the package: sixty minutes for `STANDARD`, ninety for `PREMIUM`, and one hundred twenty for `LUXURY`. Each package includes a photo allotment — twenty-five, forty, and sixty photos respectively — and every started group of five photos beyond the allotment adds ten minutes, so a partial group still contributes the full ten. A twilight booking ignores this arithmetic entirely: its duration is simply the market's `twilight_slot_minutes`, occupying exactly one twilight slot. The booking's `scheduled_end_utc` is the scheduled start plus the shoot duration plus any add-on minutes, and it is recomputed whenever the package, photo count, start, or add-on set changes.

While the booking remains in `DRAFT`, the owning agent may revise its mutable fields — `equipment_package`, `photo_count`, `wants_virtual_tour`, `tour_variant`, `license_tier`, and `scheduled_start_utc` — through the OCC-guarded update described in §2.6; attempting that update in any later state fails with `ERR_INVALID_STATE`, and changing the package, photo count, or start recomputes `scheduled_end_utc`.

Submission is the first irreversible step. The owning agent submits the booking, which requires it to still be in `DRAFT` (otherwise `ERR_BOOKING_NOT_IN_DRAFT`), requires the caller to own the booking (otherwise `ERR_FORBIDDEN`), requires the market to be `ACTIVE` (otherwise `ERR_MARKET_SUSPENDED`), and requires the scheduled start to be no sooner than twenty-four hours from now (otherwise `ERR_SLOT_TOO_SOON`). Submission locks the booking's `provisional_quote_cents` and spawns the property-readiness checklist: five items keyed `DECLUTTER_MAIN`, `UTILITIES_ON`, `PETS_SECURED`, `ACCESS_CODES`, and `EXTERIOR_CLEAR`, every one created with `required` true and `checked` false. The booking moves to `AWAITING_READINESS` and its `version` increments.

The locked quote is computed line by line, and the order of operations is pinned: each money line is computed in isolation and rounded half-up to whole cents, and only then are the lines summed. The base line multiplies the package's base rate — 15000 cents for `STANDARD`, 25000 for `PREMIUM`, 40000 for `LUXURY` — by the market's `pricing_multiplier_bps` divided by ten thousand. The overage line multiplies the number of contracted photos beyond the package's included allotment (never below zero) by 300 cents per photo and by the market factor. When the order includes a virtual tour, a tour line multiplies the variant's tour rate — 12000 cents for `BRANDED`, 14000 for `UNBRANDED` — by the market factor; otherwise the tour line is zero. A twilight booking adds a twilight premium of twenty-five percent (2500 basis points) of the base line, computed after the market multiplier has been applied to that line; non-twilight bookings carry a zero twilight line. Each add-on already `ACTIVE` at submit time contributes its resolved `price_cents` as its own individually rounded line. When those add-on lines together reach or exceed 50000 cents, a volume discount of ten percent of the add-on lines (1000 basis points), rounded half-up, is subtracted — and the discount never touches the base, overage, tour, or twilight lines. The quote is the sum of base, overage, tour, and twilight lines, plus the add-on lines, minus the volume discount. Once the booking leaves `DRAFT`, the quote is locked and is not recomputed, even if the booking later regresses to `DRAFT`.

One clock-driven guard applies here: if the logical clock reaches `scheduled_start_utc` while the booking is still in `DRAFT`, the booking expires to `EXPIRED` and its checklist items freeze. The same expiry applies from `AWAITING_READINESS` and from `READY`: a booking that has not progressed past readiness by its own start time expires automatically. The full bookings listing can be filtered by `market_id`, `state`, `client_agent_id`, or `assigned_photographer_id`.

### 3.2. Property Readiness and the Checklist Gate

Readiness is attested item by item. Each checklist item carries an `item_key`, a `required` flag that defaults to true, a `checked` flag that defaults to false, a `booking_id` tying it to its booking, and a server-stamped `checked_at_utc` that is set the moment `checked` flips from false to true and cleared back to null when readiness is reset. The owning agent checks or unchecks an item by patching its `checked` flag; every such patch re-evaluates the readiness aggregate.

The aggregate rule is an exact equality, not a threshold: when the number of checked required items equals the total number of required items on the booking, readiness is complete, and a booking sitting in `AWAITING_READINESS` advances automatically to `READY`, incrementing its `version`. Regression runs the other way with equal force. If a required item that was checked is flipped back to unchecked while the booking is `AWAITING_READINESS`, the booking regresses to `DRAFT`; if a checked required item is unchecked while the booking is `READY`, it likewise regresses to `DRAFT`. In both regressions the locked `provisional_quote_cents` is left untouched — the quote is not recomputed — so a booking that re-submits carries the pricing it locked the first time.

Checklist items remain client-editable while the booking is in `DRAFT`, `AWAITING_READINESS`, `READY`, `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`, precisely so that readiness can be re-attested after a reschedule wipes it. Once the booking reaches `SHOT` or any later state, the items are frozen, and any further patch is rejected with `ERR_CHECKLIST_ITEM_IMMUTABLE` (HTTP 409).

### 3.3. Assignment: Matching Photographer to Booking

An OpsAdmin registers each photographer with their home `market_id`, a `full_name`, an `email` unique across all photographers, and a non-empty `equipment_packages` list drawn from `STANDARD`, `PREMIUM`, and `LUXURY`. Two operational knobs complete the profile: `drone_certified`, defaulting to false, records whether the photographer holds the Part 107 certification required for any drone add-on, and `max_shoot_minutes_per_day`, defaulting to 480 and constrained to 60 through 720, caps the committed shoot minutes the photographer may carry per UTC calendar day. New photographers start `ACTIVE`, begin with an empty `committed_minutes_by_day` map, and the profile's `equipment_packages`, `drone_certified`, and `max_shoot_minutes_per_day` can be updated later by an OpsAdmin. Photographer listings can be filtered by `market_id` and `status`, and a reverse listing exposes the bookings assigned to a photographer, filterable by `state`.

Once a booking reaches `READY`, a `Coordinator` assigns a photographer by supplying a `photographer_id`. Assignment enforces six gates, in the precedence order of §2.8: the booking must be `READY` (otherwise `ERR_BOOKING_NOT_READY`); the photographer must be `ACTIVE` and belong to the booking's market (otherwise `ERR_PHOTOGRAPHER_NOT_ELIGIBLE`); the photographer's `equipment_packages` must contain the booking's `equipment_package` (otherwise `ERR_EQUIPMENT_MISMATCH`); if any `ACTIVE` drone add-on — `DRONE_STILLS` or `DRONE_VIDEO` — rides on the booking, the photographer must be drone certified (otherwise `ERR_DRONE_CERT_REQUIRED`); the candidate window must pass the travel-buffer overlap rule of §2.7 (otherwise `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`); and the day-capacity rule of §2.7 must admit the new minutes (otherwise `ERR_DAY_CAPACITY_EXCEEDED`).

A successful assignment sets the booking's `assigned_photographer_id`, adds the shoot's minutes to the photographer's `committed_minutes_by_day` entry for the scheduled day, and increments both the booking's `version` and the photographer's `version`. One wrinkle matters: when an `ACTIVE` drone add-on exists at assign time, the booking does not rest in `ASSIGNED` — it passes immediately through into `AUTHORIZATION_PENDING`, and the server mints an `AirspaceAuthorization` in `PENDING` with `attempt_number` 1 whose window covers the booking's scheduled window, as detailed in §3.5.

Assignment is revocable. A Coordinator's unassignment requires the booking to be `ASSIGNED` or `AUTHORIZATION_PENDING` (otherwise `ERR_BOOKING_NOT_ASSIGNED`), and it is refused while any airspace authorization on the booking sits in `APPROVED` — an approved authorization must first be obviated by a reschedule, or the unassignment fails with `ERR_AUTHORIZATION_STILL_VALID`. The approved-authorization refusal is evaluated before the state-legality check: since an `APPROVED` authorization normally means the booking has already advanced to `CONFIRMED`, a request that violates both rules is reported as `ERR_AUTHORIZATION_STILL_VALID`, not `ERR_BOOKING_NOT_ASSIGNED`. Unassignment releases the photographer: the committed minutes for the day are decremented by the released window, `assigned_photographer_id` returns to null, any `PENDING` or `REJECTED` authorization on the booking is cancelled, the booking falls back to `READY` (from either `ASSIGNED` or `AUTHORIZATION_PENDING`, with the same release cascade), and again both entities' versions increment.

Confirmation is the Coordinator's final scheduling act. Confirming a booking requires it to be `ASSIGNED` and requires that no `ACTIVE` drone add-on exist on it; attempting to confirm around an unresolved drone authorization fails with `ERR_AUTHORIZATION_PENDING`, because drone work must route through `AUTHORIZATION_PENDING` and reach `CONFIRMED` only when every authorization is approved. A booking sits in `AUTHORIZATION_PENDING` precisely while a drone authorization is unresolved, so confirming a booking in that state fails with `ERR_AUTHORIZATION_PENDING` rather than `ERR_BOOKING_NOT_ASSIGNED`; confirming from any other non-`ASSIGNED` state fails with `ERR_BOOKING_NOT_ASSIGNED`. A clean confirmation moves the booking `ASSIGNED` → `CONFIRMED` and increments its `version`.

A photographer's own lifecycle is guarded by their commitments. An OpsAdmin may deactivate a photographer — moving `status` from `ACTIVE` to `INACTIVE` — only while that photographer holds zero bookings in `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`; any open commitment blocks the change with `ERR_PHOTOGRAPHER_HAS_OPEN_COMMITMENTS` (HTTP 409). Reactivation back to `ACTIVE` is unrestricted, and an `INACTIVE` photographer refuses new assignments through the eligibility gate above.

### 3.4. Add-Ons: Twilight, Drone, Rush, and Staging

Five add-on kinds exist: `TWILIGHT_UPGRADE`, `DRONE_STILLS`, `DRONE_VIDEO`, `RUSH_EDIT`, and `VIRTUAL_STAGING`. The owning agent attaches an add-on by `kind` while the booking is in any pre-terminal state from `DRAFT` through `CONFIRMED`; in any later state the request fails with `ERR_BOOKING_NOT_CANCELLABLE`. An add-on is created in `PENDING` and activates automatically once its price resolves, and activation resolves two numbers from the rate card. The `price_cents` is 20000 cents for `DRONE_STILLS`, 35000 for `DRONE_VIDEO`, 15000 for `RUSH_EDIT`, and 10000 for `VIRTUAL_STAGING`, each multiplied by the market factor and rounded half-up to whole cents; `TWILIGHT_UPGRADE` is priced at zero, because the twilight premium is captured inside the quote itself and the add-on row exists purely for scheduling. The `extra_minutes` extend the scheduled window by thirty minutes for `DRONE_STILLS`, forty-five for `DRONE_VIDEO`, and zero for `RUSH_EDIT`, `VIRTUAL_STAGING`, and `TWILIGHT_UPGRADE`, and every activation recomputes the booking's `scheduled_end_utc` accordingly.

Two kinds carry their own admission rules. A `TWILIGHT_UPGRADE` requires the booking's `is_twilight` flag to be false at creation — a booking already flagged twilight rejects the upgrade with `ERR_TWILIGHT_CONFLICT` (HTTP 409) — and the market's twilight slot must be free for the photographer under the exclusivity rule of §2.7, or the request fails with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`. On activation the upgrade sets `is_twilight` to true and re-bases the scheduled window onto the market's twilight slot. A drone add-on requires that the booking not already carry another `ACTIVE` drone add-on; a second one is refused with `ERR_DUPLICATE_DRONE_ADDON` (HTTP 409). Activating a drone add-on while the booking is `ASSIGNED` or `CONFIRMED` triggers the airspace-authorization flow of §3.5: a `PENDING` authorization is minted for the scheduled window, and a `CONFIRMED` booking regresses to `AUTHORIZATION_PENDING` until the authorization resolves.

Add-ons can be withdrawn before the shoot. Cancelling an add-on requires it to be `ACTIVE` (otherwise `ERR_ADDON_NOT_CANCELLABLE`) and requires the booking to be not yet `SHOT` (otherwise `ERR_BOOKING_NOT_RESCHEDULABLE`). Cancellation recomputes `scheduled_end_utc` without the add-on's `extra_minutes`; cancelling a drone add-on cancels its linked airspace authorization, and if the booking was waiting in `AUTHORIZATION_PENDING` with no pending authorization left, it returns to `CONFIRMED`; cancelling a `TWILIGHT_UPGRADE` clears the booking's `is_twilight` flag. An add-on can also die by policy rather than by client action: when its airspace authorization exhausts the attempt cap of §3.5, the add-on moves from `ACTIVE` to `REFUSED`, and its price is credited back against the provisional quote at invoice time. Finally, a booking cancellation cascades — every non-terminal add-on, whether `PENDING` or `ACTIVE`, moves to `CANCELLED`.

### 3.5. Airspace Authorization for Drone Work

Every drone add-on requires an airspace authorization before the booking may be confirmed. An authorization is created in `PENDING` with `attempt_number` 1, its `window_start_utc` and `window_end_utc` copied from the booking's `scheduled_start_utc` and `scheduled_end_utc` at submission time, its `addon_id` identifying the drone add-on it covers, and its `decided_at_utc` null until a decision lands. While any authorization is unresolved, the booking waits in `AUTHORIZATION_PENDING` — or in `ASSIGNED`, when the §3.9 reschedule cascade landed it there with a fresh `PENDING` authorization outstanding, in which case the drone gate is re-applied at confirmation time. When no authorization covering a still-`ACTIVE` drone add-on remains `PENDING` or unresolved-`REJECTED`, the booking advances automatically to `CONFIRMED` from either holding state, incrementing its `version`; a booking that has never carried an airspace authorization is unaffected by this rule.

An OpsAdmin decides each pending authorization from the operations console. Approval requires the authorization to be `PENDING` (otherwise `ERR_AUTHORIZATION_NOT_PENDING`) and requires its `window_end_utc` to still lie in the future — approving into a lapsed window fails with `ERR_AUTHORIZATION_WINDOW_LAPSED` (HTTP 422). Approval stamps `decided_at_utc`, and when it clears the last pending authorization on a booking waiting in `AUTHORIZATION_PENDING`, the booking auto-advances to `CONFIRMED`. Rejection likewise requires `PENDING` (otherwise `ERR_AUTHORIZATION_NOT_PENDING`) and stamps `decided_at_utc`; the booking stays in its current holding state awaiting a resubmission — `AUTHORIZATION_PENDING`, or `ASSIGNED` when the rejection follows a §3.9 reschedule — with one terminal caveat: if the rejected authorization had already reached `attempt_number` 3, the covered drone add-on moves to `REFUSED`, and if no drone add-on remains `ACTIVE` on the booking, the booking advances to `CONFIRMED` without it.

Resubmission belongs to the Coordinator. It requires the authorization to be `REJECTED` (otherwise `ERR_AUTHORIZATION_NOT_REJECTED`), requires `attempt_number` to still be below the hard cap of 3 (otherwise `ERR_AUTHORIZATION_ATTEMPTS_EXHAUSTED`), and requires the booking to still be waiting in `AUTHORIZATION_PENDING` (otherwise `ERR_BOOKING_NOT_RESCHEDULABLE`). A resubmission increments `attempt_number` by one, re-stamps the window from the booking's current scheduled window, clears `decided_at_utc` back to null, and returns the authorization to `PENDING`.

Authorizations also move without any console decision. A `PENDING` authorization is cancelled by cascade when its booking is cancelled, when the assignment is revoked, or when the covered drone add-on is cancelled. An `APPROVED` authorization expires — moving to `EXPIRED` — when a booking reschedule moves the scheduled window out from under it, or when the logical clock reaches its `window_end_utc` while the booking has not yet been marked shot. Whenever an authorization expires but the booking still needs the drone add-on, a replacement `PENDING` authorization is created following the reschedule cascade of §3.9: its `attempt_number` is one greater than the maximum prior attempt for that add-on, capped at 3, and if that cap would be exceeded the drone add-on is instead moved to `REFUSED` and the booking proceeds without it. For operational reachability, authorizations are listed both per booking and through a global operations queue filterable by `booking_id`, `addon_id`, and `state`.

### 3.6. Shoot Day and the Delivery Pipeline

When the scheduled window arrives, the assigned photographer marks the shoot complete. Marking requires the booking to be `CONFIRMED` (otherwise `ERR_BOOKING_NOT_CONFIRMED`), requires the caller's `X-User-ID` to equal the booking's `assigned_photographer_id` (otherwise `ERR_FORBIDDEN`), and requires the current moment to fall inside the shoot window — no earlier than two hours before `scheduled_start_utc` and no later than twenty-four hours after `scheduled_end_utc` (otherwise `ERR_OUTSIDE_SHOOT_WINDOW`, HTTP 422). Marking the shoot creates the booking's first `AssetBundle` in `EDITING` with `round_number` 1, computes `delivery_due_utc` by the turnaround rule below, and walks the booking from `CONFIRMED` to `SHOT` and then automatically on to `IN_EDIT`, incrementing the booking's `version`.

The turnaround rule derives the delivery deadline from the market's `standard_turnaround_hours`. An `ACTIVE` `RUSH_EDIT` add-on halves that figure, rounding up to a whole hour; an `ACTIVE` `VIRTUAL_STAGING` add-on adds twelve hours. Weather history then stretches the result: each consumed weather reschedule adds twenty-four hours of slack, but only the first two weather reschedules count — a booking with three weather reschedules receives forty-eight hours of extension, not seventy-two. The resulting `delivery_due_utc` is the mark-shot instant plus the adjusted hours, computed to whole-second precision, and it is re-derived by the same rule if a weather reschedule lands and the shoot is later marked again.

Delivery is the photographer's act of handing over the edited bundle, supplying the `photo_asset_count` of edited photos and, when the booking wants a virtual tour, the `tour_asset_url` of the rendered tour. Delivery requires the booking to be `IN_EDIT` or `REVISION_REQUESTED` (otherwise `ERR_BOOKING_NOT_IN_EDIT`), and again requires the caller to be the assigned photographer (otherwise `ERR_FORBIDDEN`). Two quality gates guard it: the bundle's `photo_asset_count` must meet or exceed the booking's contracted `photo_count` — the quality guarantee — or the delivery is rejected with `ERR_QUALITY_GUARANTEE_SHORTFALL` (HTTP 422); and when `wants_virtual_tour` is true, a non-null `tour_asset_url` is mandatory, or the delivery fails with `ERR_TOUR_ASSET_MISSING` (HTTP 422).

A successful first delivery moves the bundle from `EDITING` to `DELIVERED`, stamping `delivered_at_utc` on both the bundle and the booking, and opens the revision window: `revision_window_closes_utc` is set to exactly seventy-two hours after the delivery instant. First delivery also spawns the booking's post-delivery entourage: a `VirtualTour` in `HOSTED` state, but only when the booking wants a tour — its `variant` copied from the booking's `tour_variant` and its public `hosted_url` minted at creation — and a `LicenseGrant` in `DORMANT` state awaiting acceptance. Every booking carries at most one tour and at most one license. The booking moves to `DELIVERED` and its `version` increments.

### 3.7. Revisions Under the Quality Guarantee

The quality guarantee grants the client two free revision rounds, with two further paid rounds beyond them. While the booking is `DELIVERED`, the owning agent opens a revision round with a payload naming the `bundle_id` being revised and free-form `notes` describing the requested changes. Opening a round requires the booking to be `DELIVERED` (otherwise `ERR_BOOKING_NOT_DELIVERED`), requires the caller to own the booking (otherwise `ERR_FORBIDDEN`), requires the current moment to fall strictly before `revision_window_closes_utc` — a request at or after that instant is too late and fails with `ERR_REVISION_WINDOW_CLOSED` (HTTP 422) — and requires `revisions_used` to still be below the hard cap of four consumed rounds, that is two free plus two paid (otherwise `ERR_REVISION_LIMIT_REACHED`, HTTP 409).

Pricing is decided at the moment the round opens. While `revisions_used` is still below the free quota of two, the new `RevisionRequest` is stamped `is_free` true with `fee_cents` zero; from the third round onward `is_free` is false and `fee_cents` resolves to 7500 cents multiplied by the market factor, rounded half-up to whole cents. The request is created in `OPEN`, the booking's `revisions_used` increments by one, the booking moves from `DELIVERED` to `REVISION_REQUESTED`, and the booking's `version` increments.

The assigned photographer claims an `OPEN` revision to signal work is underway; claiming requires the revision to be `OPEN` (otherwise `ERR_REVISION_NOT_OPEN`) and requires the caller to be the booking's assigned photographer (otherwise `ERR_FORBIDDEN`), moving the revision to `IN_PROGRESS`. An OpsAdmin may instead dismiss an `OPEN` revision outright, moving it to `REJECTED_EXHAUSTED`. And if the revision window closes while a revision still sits `OPEN`, the system resolves it as `REJECTED_LATE`.

Redelivery closes the loop. The photographer delivers the revised bundle under exactly the delivery gates of §3.6 — the booking must be `REVISION_REQUESTED`, the quality guarantee and tour-asset gates apply unchanged, and every `OPEN` or `IN_PROGRESS` revision on the current bundle must be addressed by the new bundle. Redelivery moves the prior bundle from `DELIVERED` to `SUPERSEDED`, creates a fresh bundle whose `round_number` is one greater than its predecessor's, delivers that new bundle, and resolves the prior bundle's revisions to `RESOLVED`. Crucially, redelivery does not extend `revision_window_closes_utc`: the window is fixed from the first delivery, so late rounds can never be bought back by re-delivering. The booking returns to `DELIVERED` with its `version` incremented. For operational reachability, revisions are listed per booking and through a global list filterable by `booking_id`, `bundle_id`, and `state`.

### 3.8. Acceptance, Invoicing, Licensing, and Tour Hosting

Acceptance is the client agent's sign-off and the booking's financial settlement. It requires the booking to be `DELIVERED` (otherwise `ERR_BOOKING_NOT_DELIVERED`) and the caller to own it (otherwise `ERR_FORBIDDEN`); it is blocked while any revision on the booking sits in `OPEN` or `IN_PROGRESS` (otherwise `ERR_OPEN_REVISIONS_EXIST`, HTTP 409); and it carries the deferred tour gate: if the booking's `tour_variant` is `UNBRANDED`, its `license_tier` must be `MLS_COMPLIANT` at this moment, or acceptance fails with `ERR_UNBRANDED_REQUIRES_MLS_TIER` (HTTP 422). This tier check is enforced here — at acceptance — and not at creation or delivery. Per §2.8's precedence, the state-legality check fires before the open-revision gate: because opening a revision moves the booking out of `DELIVERED` into `REVISION_REQUESTED`, an acceptance attempted while a revision is open is reported as `ERR_BOOKING_NOT_DELIVERED`; `ERR_OPEN_REVISIONS_EXIST` is the report when the booking still sits in `DELIVERED` with an `OPEN` or `IN_PROGRESS` revision outstanding.

Acceptance computes `final_invoice_cents` in a pinned evaluation order. The locked `provisional_quote_cents` is taken as the stable base; its line decomposition is not recomputed, even though it already reflects the add-ons and volume discount priced at submit time. The add-on set is then re-delta'd: the sum of `price_cents` over the add-ons `ACTIVE` at acceptance is compared against the add-on total baked into the locked quote, and the difference — positive or negative — is applied, which keeps the locked base stable while letting the add-on set drift between submit and acceptance. If a `RUSH_EDIT` add-on is `ACTIVE` and the delivery landed after `delivery_due_utc`, the rush fee is refunded in full: the entire `RUSH_EDIT` add-on price is subtracted as a rush discount. The `fee_cents` of every paid revision that reached `RESOLVED` are added. When delivery was late, a late penalty of fifteen percent of the provisional quote (1500 basis points), rounded half-up to whole cents, is subtracted; an on-time delivery carries neither the late penalty nor the rush refund, and a late rush delivery deliberately receives both reliefs. The accumulated `weather_credit_cents` — never more than thirty percent of the provisional quote — is subtracted. Finally, the license fee resolved at activation is added. The invoice is the resulting total floored at zero: if the arithmetic ever produces a negative figure, the invoice is zero. Should the computation violate any of these fiscal invariants — the zero floor, the weather-credit cap, or license-tier consistency — the acceptance is rejected with `ERR_INVOICE_INCONSISTENT` (HTTP 422).

In the same atomic transaction, the booking's `LicenseGrant` moves from `DORMANT` to `ACTIVE`: `activated_at_utc` is stamped, the grant's `tier` is copied from the booking's `license_tier`, and its `fee_cents` resolves from the tier and tour variant — zero cents for `MLS_COMPLIANT`, 5000 for `STANDARD_MARKETING`, and 15000 for `EXTENDED`, plus a 4000-cent unbranded surcharge when the booking's `tour_variant` is `UNBRANDED`. The unbranded-tier rule above is what guarantees an `UNBRANDED` tour never activates under a non-MLS tier. When the booking has a tour, the tour moves from `HOSTED` to `PUBLISHED` in the same transaction, stamping `published_at_utc`; the tour may publish only if the license activates alongside it — acceptance is atomic, and a license that cannot activate fails the whole acceptance with `ERR_LICENSE_NOT_ACTIVE`. The latest delivered bundle moves from `DELIVERED` to `FINALIZED`. The accumulated weather credit, having been deducted from the invoice, is then zeroed off the booking's `weather_credit_cents`; the agent's prepaid `credit_balance_cents` ledger is the standing destination where weather credits and refunds accrue. The booking reaches `ACCEPTED`, terminal, with its `version` incremented.

Governance continues after acceptance. An OpsAdmin may suspend a published tour — requiring it to be `PUBLISHED`, otherwise `ERR_TOUR_NOT_PUBLISHED` — moving it to `SUSPENDED`, and may later resume a suspended tour, which requires the tour to be `SUSPENDED` (otherwise `ERR_TOUR_NOT_SUSPENDED`) and additionally requires the booking to be `ACCEPTED` with its license `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`). Unpublishing moves a tour from `PUBLISHED` or `SUSPENDED` to the terminal `UNPUBLISHED`; invoking it in any other state fails with `ERR_TOUR_NOT_PUBLISHED`.

The license has its own parallel controls. Suspending a license requires it to be `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`) and moves it to `SUSPENDED`; if the tour is `PUBLISHED` at that moment, the tour cascades to `SUSPENDED` with it. Reinstating requires the license to be `SUSPENDED` (otherwise `ERR_LICENSE_NOT_SUSPENDED`) and returns it to `ACTIVE` — but the tour is deliberately not auto-resumed and stays `SUSPENDED` until separately resumed. Revocation moves a license from `ACTIVE` or `SUSPENDED` to the terminal `REVOKED` — attempting it in any other state fails with `ERR_LICENSE_NOT_ACTIVE` — and sends the tour to `UNPUBLISHED` if it is not already there.

### 3.9. Rescheduling, Weather Credits, and Cancellation

Life happens to shoots, and the reschedule action is the client's pressure valve. The owning agent reschedules by supplying the OCC guard `expected_booking_version` described in §2.6, a `kind` of `WEATHER` or `CLIENT`, a replacement `new_start_utc`, and a `reason_code`. The booking must be in `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED` (otherwise `ERR_BOOKING_NOT_RESCHEDULABLE`), and its `reschedule_count` must still be below the hard cap of three consumed reschedules. The replacement start must be no sooner than twenty-four hours from now (otherwise `ERR_SLOT_TOO_SOON`) and must land on a quarter-hour boundary (otherwise `ERR_INVALID_SLOT_ALIGNMENT`). The reason code must match the kind: `PRECIPITATION`, `WIND`, or `LOW_LIGHT` for `WEATHER`, and `SELLER_DELAY`, `ACCESS_ISSUE`, or `STAGING_DELAY` for `CLIENT`; any mismatch fails with `ERR_INVALID_REASON_CODE` (HTTP 422).

An in-cap reschedule appends an immutable `RescheduleEvent` — recording its `kind`, the booking's previous start in `old_start_utc`, the replacement in `new_start_utc`, the `reason_code`, and the `credit_applied_cents` actually credited by the event — and increments `reschedule_count` by one. For a `WEATHER` event, the weather-credit rule runs: the raw credit is the market's `weather_reschedule_credit_bps`, in basis points, applied to the locked `provisional_quote_cents` and rounded half-up to whole cents; accumulation is capped at thirty percent of the quote (3000 basis points, rounded half-up); the booking's `weather_credit_cents` becomes the smaller of the old accumulation plus the raw credit and the cap; and the event's `credit_applied_cents` records only the marginal amount this event actually contributed, so an event that lands on the cap may credit a partial amount or none at all. `CLIENT` events always record zero.

The rest of the cascade keeps the booking coherent. The booking's `scheduled_start_utc` moves to the new instant, `scheduled_end_utc` is recomputed, and `delivery_due_utc` is cleared to be recomputed at the next mark-shot. Every checklist item is reset — `checked` false, `checked_at_utc` null — because property readiness must be re-attested; the booking lands in `ASSIGNED` — a `CONFIRMED` booking drops back to `ASSIGNED`, and one waiting on airspace approval leaves `AUTHORIZATION_PENDING` — with the readiness gate re-checked at confirmation. The landing state is `ASSIGNED` whenever the assignment survives, even when the authorization cascade below mints a fresh `PENDING` authorization for a still-`ACTIVE` drone add-on: the booking does not re-enter `AUTHORIZATION_PENDING` at reschedule time, and the drone-authorization gate is instead re-applied when the booking is next confirmed (§3.3). The assigned photographer is re-validated against the new window under the overlap and day-capacity rules of §2.7; if the photographer no longer fits, the assignment is forfeited — `assigned_photographer_id` returns to null, the committed minutes are released, and the booking falls back to `READY`. Every `APPROVED` authorization whose window no longer matches the new window moves to `EXPIRED`, and a replacement `PENDING` authorization is minted per §3.5 with `attempt_number` one above the maximum prior attempt, capped at three; if that cap would be exceeded, the drone add-on moves to `REFUSED` and the booking proceeds without it. For a booking rescheduled out of `AUTHORIZATION_PENDING`, pending authorizations are cancelled and re-created on the new window. Each reschedule increments the booking's `version`, and the append-only reschedule history can be listed per booking and filtered by `kind`.

At the cap, the two kinds diverge sharply. A `CLIENT` reschedule attempted with `reschedule_count` already at three is refused with `ERR_RESCHEDULE_CAP_EXCEEDED` (HTTP 409). A `WEATHER` reschedule at the cap instead succeeds and cancels the shoot: the booking moves to `CANCELLED_WEATHER` with the same release cascade as a client cancellation, no per-event weather credit accrues, and a final weather-cancellation credit equal to one weather-credit application is granted into the agent's `credit_balance_cents`.

Plain cancellation remains available throughout the pre-shoot states. The owning agent may cancel from `DRAFT`, `AWAITING_READINESS`, `READY`, `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`; from any other state the attempt fails with `ERR_BOOKING_NOT_CANCELLABLE`. Cancelling a `CONFIRMED` booking carries one extra guard: the current moment must fall more than twelve hours before the scheduled start, or the request fails with `ERR_INSIDE_CANCELLATION_CUTOFF` (HTTP 422). Every cancellation runs the same release cascade — all non-terminal add-ons move to `CANCELLED`, all airspace authorizations move to `CANCELLED`, the assigned photographer's committed minutes are released and `assigned_photographer_id` returns to null when an assignment existed — and the booking lands in `CANCELLED_BY_CLIENT` with its `version` incremented. Together with `ACCEPTED`, `CANCELLED_WEATHER`, and clock-driven `EXPIRED`, these are the four terminal states in which a booking's story ends.

## 4. Endpoint Definitions

Status codes follow a simple rule: operations that create a new stand-alone resource — registering a market, a photographer, or a client agent, creating a booking, attaching an add-on, or opening a revision request — answer `201 Created`. Everything else, including state-transition actions, modifications, and reads, answers `200 OK`. Request payloads, response shapes, and side effects are defined by the workflows in §3; this table is the address map, not the specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | OpsAdmin |
| POST | `/markets` | Create a Market | OpsAdmin |
| GET | `/markets` | List Markets | All roles |
| GET | `/markets/{marketId}` | Get a Market | All roles |
| PATCH | `/markets/{marketId}` | Update market configuration or suspend/reactivate | OpsAdmin |
| POST | `/photographers` | Create a Photographer | OpsAdmin |
| GET | `/photographers` | List Photographers (filterable by market) | All roles |
| GET | `/photographers/{photographerId}` | Get a Photographer | All roles |
| PATCH | `/photographers/{photographerId}` | Update photographer profile or status | OpsAdmin |
| GET | `/photographers/{photographerId}/shoot-bookings` | List bookings assigned to a photographer | Coordinator, OpsAdmin, Photographer |
| POST | `/client-agents` | Register a ClientAgent | OpsAdmin |
| GET | `/client-agents` | List ClientAgents | Coordinator, OpsAdmin |
| GET | `/client-agents/{clientAgentId}` | Get a ClientAgent | ClientAgent, Coordinator, OpsAdmin |
| GET | `/client-agents/{clientAgentId}/shoot-bookings` | List bookings belonging to an agent | ClientAgent, Coordinator, OpsAdmin |
| POST | `/shoot-bookings` | Create a ShootBooking in DRAFT | ClientAgent |
| GET | `/shoot-bookings` | List ShootBookings | All roles |
| GET | `/shoot-bookings/{id}` | Get a ShootBooking | All roles |
| PATCH | `/shoot-bookings/{id}` | Update mutable fields while DRAFT (OCC-guarded) | ClientAgent |
| POST | `/shoot-bookings/{id}/submit` | Submit booking (DRAFT → AWAITING_READINESS), locking the quote and spawning the checklist | ClientAgent |
| POST | `/shoot-bookings/{id}/cancel` | Client cancel | ClientAgent |
| POST | `/shoot-bookings/{id}/assign` | Coordinator assigns a photographer (READY → ASSIGNED) | Coordinator |
| POST | `/shoot-bookings/{id}/unassign` | Coordinator revokes an assignment (ASSIGNED/AUTHORIZATION_PENDING → READY) | Coordinator |
| POST | `/shoot-bookings/{id}/confirm` | Confirm an ASSIGNED booking with no drone add-ons (ASSIGNED → CONFIRMED) | Coordinator |
| POST | `/shoot-bookings/{id}/mark-shot` | Assigned photographer marks the shoot complete (CONFIRMED → SHOT → IN_EDIT) | Photographer |
| POST | `/shoot-bookings/{id}/deliver` | Deliver or re-deliver the asset bundle | Photographer |
| POST | `/shoot-bookings/{id}/accept` | Client accepts delivery (DELIVERED → ACCEPTED) | ClientAgent |
| POST | `/shoot-bookings/{id}/reschedule` | Weather or client reschedule (OCC-guarded) | ClientAgent |
| GET | `/shoot-bookings/{id}/checklist-items` | List checklist items for a booking | All roles |
| PATCH | `/shoot-bookings/{id}/checklist-items/{itemId}` | Check or uncheck a checklist item | ClientAgent |
| POST | `/shoot-bookings/{id}/addons` | Attach an add-on (auto-activates after pricing) | ClientAgent |
| GET | `/shoot-bookings/{id}/addons` | List add-ons for a booking | All roles |
| GET | `/shoot-bookings/{id}/addons/{addonId}` | Get an add-on | All roles |
| POST | `/shoot-bookings/{id}/addons/{addonId}/cancel` | Cancel an ACTIVE add-on | ClientAgent |
| GET | `/airspace-authorizations` | Global list of airspace authorizations (ops queue) | Coordinator, OpsAdmin |
| GET | `/airspace-authorizations/{authId}` | Get a single airspace authorization by id | Coordinator, OpsAdmin |
| GET | `/shoot-bookings/{id}/airspace-authorizations` | List authorizations for a booking | All roles |
| GET | `/shoot-bookings/{id}/airspace-authorizations/{authId}` | Get an authorization | All roles |
| POST | `/shoot-bookings/{id}/airspace-authorizations/{authId}/approve` | Ops approve a pending authorization | OpsAdmin |
| POST | `/shoot-bookings/{id}/airspace-authorizations/{authId}/reject` | Ops reject a pending authorization | OpsAdmin |
| POST | `/shoot-bookings/{id}/airspace-authorizations/{authId}/resubmit` | Coordinator resubmits a rejected authorization | Coordinator |
| GET | `/shoot-bookings/{id}/asset-bundles` | List bundles for a booking | All roles |
| GET | `/shoot-bookings/{id}/asset-bundles/{bundleId}` | Get a bundle | All roles |
| GET | `/revisions` | Global list of revision requests | Coordinator, OpsAdmin |
| GET | `/revisions/{revisionId}` | Get a single revision request by id | Coordinator, OpsAdmin |
| POST | `/shoot-bookings/{id}/revisions` | Open a revision request | ClientAgent |
| GET | `/shoot-bookings/{id}/revisions` | List revisions for a booking | All roles |
| GET | `/shoot-bookings/{id}/revisions/{revisionId}` | Get a revision | All roles |
| POST | `/shoot-bookings/{id}/revisions/{revisionId}/claim` | Photographer claims an OPEN revision (OPEN → IN_PROGRESS) | Photographer |
| POST | `/shoot-bookings/{id}/revisions/{revisionId}/dismiss` | Ops dismiss an OPEN revision (OPEN → REJECTED_EXHAUSTED) | OpsAdmin |
| GET | `/shoot-bookings/{id}/virtual-tour` | Get the virtual tour for a booking (0 or 1) | All roles |
| POST | `/shoot-bookings/{id}/virtual-tour/suspend` | Ops suspend a published tour | OpsAdmin |
| POST | `/shoot-bookings/{id}/virtual-tour/resume` | Ops resume a suspended tour (requires license ACTIVE) | OpsAdmin |
| POST | `/shoot-bookings/{id}/virtual-tour/unpublish` | Ops unpublish a tour | OpsAdmin |
| GET | `/shoot-bookings/{id}/license` | Get the license grant for a booking (0 or 1) | All roles |
| POST | `/shoot-bookings/{id}/license/suspend` | Ops suspend a license (cascades to the tour) | OpsAdmin |
| POST | `/shoot-bookings/{id}/license/reinstate` | Ops reinstate a suspended license | OpsAdmin |
| POST | `/shoot-bookings/{id}/license/revoke` | Ops revoke a license | OpsAdmin |
| GET | `/shoot-bookings/{id}/reschedule-events` | List reschedule history for a booking (append-only) | All roles |

## 5. Error Code Catalogue

The catalogue below is the complete set of machine-readable error identifiers. Trigger conditions are specified where each rule lives, in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_BOOKING_NOT_READY` | 409 Conflict |
| `ERR_BOOKING_NOT_ASSIGNED` | 409 Conflict |
| `ERR_BOOKING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_BOOKING_NOT_IN_EDIT` | 409 Conflict |
| `ERR_BOOKING_NOT_DELIVERED` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_BOOKING_NOT_RESCHEDULABLE` | 409 Conflict |
| `ERR_MARKET_SUSPENDED` | 409 Conflict |
| `ERR_SLOT_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_INVALID_SLOT_ALIGNMENT` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SHOOT_WINDOW` | 422 Unprocessable Entity |
| `ERR_INSIDE_CANCELLATION_CUTOFF` | 422 Unprocessable Entity |
| `ERR_PHOTOGRAPHER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DRONE_CERT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DAY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PHOTOGRAPHER_HAS_OPEN_COMMITMENTS` | 409 Conflict |
| `ERR_DUPLICATE_DRONE_ADDON` | 409 Conflict |
| `ERR_TWILIGHT_CONFLICT` | 409 Conflict |
| `ERR_ADDON_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_AUTHORIZATION_PENDING` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_PENDING` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_REJECTED` | 409 Conflict |
| `ERR_AUTHORIZATION_ATTEMPTS_EXHAUSTED` | 409 Conflict |
| `ERR_AUTHORIZATION_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_STILL_VALID` | 409 Conflict |
| `ERR_RESCHEDULE_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_REASON_CODE` | 422 Unprocessable Entity |
| `ERR_QUALITY_GUARANTEE_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_TOUR_ASSET_MISSING` | 422 Unprocessable Entity |
| `ERR_REVISION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_REVISION_NOT_OPEN` | 409 Conflict |
| `ERR_OPEN_REVISIONS_EXIST` | 409 Conflict |
| `ERR_UNBRANDED_REQUIRES_MLS_TIER` | 422 Unprocessable Entity |
| `ERR_TOUR_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TOUR_NOT_SUSPENDED` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LICENSE_NOT_SUSPENDED` | 409 Conflict |
| `ERR_INVOICE_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_CHECKLIST_ITEM_IMMUTABLE` | 409 Conflict |

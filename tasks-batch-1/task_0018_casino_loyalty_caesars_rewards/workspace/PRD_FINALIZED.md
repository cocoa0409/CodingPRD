# Casino Loyalty Caesars Rewards API — Product Requirements Document

## 1. Introduction

Caesars Rewards is the universal loyalty program that ties a guest's play and stay activity across every Caesars-operated property — Las Vegas Strip flagships, regional casinos, and international destinations — into a single membership record. A guest who earns Tier Credits at one property must immediately enjoy the same standing, the same comped room economics, and the same host relationship at every other property; conversely, a regulatory or self-exclusion action taken at any property must propagate instantly to all the others. The system this document specifies is the backbone of that promise: a single source of truth for member tier, host assignment, comp-room pricing, responsible-gambling status, velocity surveillance, and the annual rollover that begins each loyalty year.

Beyond pure rewards bookkeeping, the platform is the casino's first line of operational compliance. Self-exclusion requests must take effect the moment they are filed, and they must reach into every pending host assignment and every open comp-room reservation that the excluded member holds. Velocity monitoring must catch high-rate play within a rolling one-hour window and brake further comp-room privileges before they accrue. Comp-room pricing must remain reproducible: the rate a member sees at booking time is the rate the casino expects, with the only legitimate movement being a tier promotion that occurs between booking and check-in. Three operator roles — member services, loyalty management, and compliance — divide the work so that no single individual can both originate and approve a host engagement, and an audit-grade error catalogue captures every refusal.

This document treats the loyalty engine as a behavioural specification first and a REST contract second. Sections 2 and 3 describe how the system behaves, what it accepts, and what it refuses; section 4 names the endpoints that drive those behaviours, and section 5 catalogues the error identifiers cited throughout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the call is being made. A request that omits either header (or supplies a blank value) is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. A request whose `X-User-Role` is not in the set of roles authorised for the target endpoint is rejected with `ERR_UNAUTHORIZED` and HTTP 403.

The system recognises exactly four role names, spelled exactly as follows: `Member`, `MemberServices`, `LoyaltyManager`, and `ComplianceOfficer`.

The `Member` role is entity-backed. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` row, and any ownership check on a resource that references a member (the booking the member is trying to cancel, the self-exclusion the member is trying to reinstate) compares the resource's `member_id` field to `X-User-ID`. The other three roles — `MemberServices`, `LoyaltyManager`, and `ComplianceOfficer` — are opaque operator identifiers not tied to any persisted entity row. The server may record an opaque operator identifier on a row (for example, on a `HostAssignment` it persists the creator's identifier as `assigned_by_user_id` and the approver's identifier as `approved_by_user_id`) but it does not compare those identifiers to any entity's `id`.

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

All list endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). The four pagination fields exposed in `meta` are `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true when more rows exist beyond the returned page and false otherwise. Lists are sorted by `created_at` ascending unless an endpoint section explicitly states otherwise.

### 2.4. Common Resource Properties

Most entities in the catalogue — `Member`, `Property`, `Host`, `GamingSession`, `CompRoomBooking`, `HostAssignment`, and `AnnualResetRun` — share a common set of system-managed properties on top of their domain fields. Every such resource carries an `id` (a server-minted UUID with no type prefix), a `created_at` and `updated_at` (each ISO 8601 UTC with three fractional digits of millisecond precision), and a `version` (an integer that starts at 1 on creation and is incremented by exactly one on every mutation that changes the row). `updated_at` is refreshed to the current server time on every such mutation. Two entities deliberately do not carry the full common set: `SelfExclusion` and `VelocityAlert` are append-only audit-style rows. They carry `id` and `created_at` only; they do not expose `updated_at` and they do not expose `version`.

Path-segment ids are validated strictly left to right. For a nested path of the shape `/parents/{parent_id}/children/{child_id}`, the server first verifies that `parent_id` resolves to an existing parent row, and only then that `child_id` resolves to a child whose `parent_id` matches; either failure surfaces as `ERR_NOT_FOUND` (HTTP 404). Body-level foreign keys (`member_id`, `host_id`, `property_id`, and so on) are checked under the same `ERR_NOT_FOUND` discipline.

### 2.5. Optimistic Concurrency Control

Two creation endpoints are guarded by Optimistic Concurrency Control on the `Member` parent. A `POST` to create a `HostAssignment` and a `POST` to create a `CompRoomBooking` each take `expected_member_version` as a non-optional input field, which the caller must populate with the `version` value the caller last observed on the target `Member`. The server compares this value against the current `Member.version` at the instant the request is processed; if it does not match — because, for example, an intervening self-exclusion has just transitioned the member to `EXCLUDED` and cascaded revokes onto prior assignments and bookings, advancing the member's `version`, or because a velocity-monitoring tick has just driven the member to `SUSPENDED` and bumped the same counter — the request is rejected with `ERR_STALE_MEMBER_VERSION` and HTTP 412. The rule is purely a stale-version rejection on the parent: the caller is overwriting a member state it has not observed, and the create cannot be allowed to slip past whatever gate moved the version. The endpoints that manually clear velocity (`POST /members/{id}/clear-velocity`) also take `expected_member_version` for the same reason. No other endpoint takes a version field.

### 2.6. Hierarchical Consistency and Cascades

A single state transition often propagates further than the entity it was issued against. When a `Member` transitions on the responsible-gambling dimension from `NOT_EXCLUDED` to `EXCLUDED`, the server, in the same operation, transitions every `HostAssignment` for that member whose current status is in `PENDING_APPROVAL` or `ACTIVE` to `REVOKED`, and transitions every `CompRoomBooking` for that member whose current status is in `PENDING` or `CONFIRMED` to `CANCELLED`; if any of the revoked assignments was the active one, the member's `assigned_host_id` is set to null. When a `Member` transitions on the velocity dimension into `SUSPENDED` (from either `NORMAL` or `FLAGGED`), the server transitions every `CompRoomBooking` for that member whose current status is in `PENDING` or `CONFIRMED` to `CANCELLED`. Every entity touched by these cascades has its `updated_at` refreshed and its `version` incremented by one.

The three dimensions of `Member` state — `tier_status`, `exclusion_status`, and `velocity_status` — are independent and evolve in parallel. A member who is `DIAMOND` on tier and `SUSPENDED` on velocity is a single member with two simultaneously valid state values, and the velocity dimension's gating effect on new bookings does not erase the member's earned tier.

### 2.7. Numerical Precision and Rounding

Two distinct precision regimes apply. Tier-Credit accrual produces a per-session credit value rounded half-up to two decimal places before being added to the member's year-to-date and lifetime running totals; the rounding happens once per session, never on the running total. Comp-room rate computation works entirely in integer USD cents and applies round-half-up at each multiplication step (the discount multiplication first, the market-segment multiplication second). Velocity-window aggregation is a straight integer sum of cents and is exact.

### 2.8. Universal Loyalty and Property Independence

The loyalty record is universal. A member's `home_property_id` records where they enrolled, but their tier standing, their self-exclusion posture, and their velocity status apply at every property in the network. A `GamingSession` recorded at one property contributes to the same `tier_credits_ytd` and `tier_credits_lifetime` totals that a `CompRoomBooking` at any other property is priced against. A member cannot escape a self-exclusion or a velocity suspension by switching properties.

### 2.9. Segregation of Duties on Host Engagements

A single `LoyaltyManager` `X-User-ID` may not both create and approve (or create and reject) the same `HostAssignment`. The creator's identifier is captured at create-time as `assigned_by_user_id`; the approver or rejecter's identifier must differ from that value, and the approver's identifier is captured as `approved_by_user_id` on success. A violation is rejected with `ERR_SOD_VIOLATION` and HTTP 422.

### 2.10. Validation Order

When multiple validations could fire on the same request, the server evaluates them in a fixed priority order so the surfaced `error_id` is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`, HTTP 401), then role authorisation (`ERR_UNAUTHORIZED`, HTTP 403), then existence of every path-segment id and body foreign-key id resolved strictly left to right (`ERR_NOT_FOUND`, HTTP 404), then state-machine eligibility of the target resource (`ERR_INVALID_STATE`, HTTP 409), then the OCC version check on `Member.version` where applicable (`ERR_STALE_MEMBER_VERSION`, HTTP 412), and only then the business-safety, business-referential, business-constraint, business-temporal, and business-fiscal rules described in §3. Within the business band, exclusion gating (`ERR_MEMBER_EXCLUDED`) is checked before velocity gating (`ERR_MEMBER_VELOCITY_SUSPENDED`), which is checked before the regulator-minimum-period check on self-exclusion (`ERR_EXCLUSION_PERIOD_TOO_SHORT`), then segregation-of-duties (`ERR_SOD_VIOLATION`), then the single-active-host constraint (`ERR_ACTIVE_HOST_EXISTS`), then tier eligibility for comp (`ERR_TIER_INELIGIBLE_FOR_COMP`), then the reset-due / not-yet-due temporal checks (`ERR_RESET_NOT_DUE`, `ERR_RESET_ALREADY_DUE`), then the time-interval checks on sessions and bookings (`ERR_SESSION_INVALID_TIMES`, `ERR_BOOKING_INVALID_DATES`), then the uniqueness checks (`ERR_EMAIL_TAKEN`, `ERR_RESET_YEAR_TAKEN`), then the interval-overlap checks (`ERR_SESSION_OVERLAP`, `ERR_BOOKING_OVERLAP`), and finally the regulatory single-session cap (`ERR_SESSION_LOSS_OVER_CAP`).

### 2.11. Test-Driving the Clock

Several rules turn on the server's current UTC clock — the reset-due check, the elapsed-self-exclusion check, the booking check-in time check. For deterministic testing, a `ComplianceOfficer` capability sets the server's logical `current_utc` to a supplied `to_iso8601` instant; the clock then sticks at that value until the next such call.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding and the Three Parallel State Dimensions

A new member enters the system through a `MemberServices` registration, which carries the prospective member's `full_name`, their `email`, and the `home_property_id` of the property at which they are enrolling. The `email` must be unique across all existing `Member` rows under case-insensitive comparison and must not exceed 254 characters; a collision is rejected with `ERR_EMAIL_TAKEN`. On success, the row is created with `tier_status` `GOLD`, `tier_credits_ytd` zero, `tier_credits_lifetime` zero, `exclusion_status` `NOT_EXCLUDED`, `velocity_status` `NORMAL`, `assigned_host_id` null, and `version` 1. From this point forward the member evolves along three parallel dimensions: `tier_status`, which advances through `GOLD`, `PLATINUM`, `DIAMOND`, and `SEVEN_STARS` as the member accumulates Tier Credits and resets back to `GOLD` at year-end; `exclusion_status`, which can move from `NOT_EXCLUDED` to `EXCLUDED` and from there to `REINSTATED` and back to `EXCLUDED` again; and `velocity_status`, which can move from `NORMAL` to `FLAGGED` and from either of those to `SUSPENDED`, with the suspended state cleared back to `NORMAL` only by compliance intervention.

Members and their adjacent reference data are queryable through paginated list endpoints. The member-listing endpoint accepts the optional filters `home_property_id`, `tier_status`, `exclusion_status`, `velocity_status`, and `assigned_host_id`, alongside the pagination parameters. A reverse-reachability query exposes the members whose `home_property_id` matches a given property's id.

### 3.2. Property and Host Setup

A `Property` is provisioned by a `ComplianceOfficer` carrying the property's `name`, its `market_segment` (one of `VEGAS_STRIP`, `REGIONAL`, or `INTERNATIONAL`), and its `base_room_rate_cents` (a non-negative integer representing the standard nightly room rate in USD cents before any loyalty discount). The property is created in `status` `OPEN`. The property-listing endpoint accepts the optional filters `market_segment` and `status`.

A `Host` is also provisioned by a `ComplianceOfficer` carrying the host's `employee_email` (unique across all hosts, case-insensitive) and the `home_property_id` of the property that employs them; the host is created in `status` `ACTIVE`. The host-listing endpoint accepts `home_property_id` and `status` filters, allowing both reverse-reachability lookups (which hosts belong to this property) and operational filtering.

### 3.3. Recording Gaming Sessions and the Tier-Credit Accrual Engine

A `MemberServices` operator records a completed gaming session by submitting a payload that names the `member_id` and `property_id` along with the session's `started_at` and `ended_at` timestamps, the `game_type` (`SLOTS`, `TABLE_GAMES`, or `POKER`), and the `theoretical_loss_cents` — the property's theoretical loss expressed in USD cents. The submission is refused if the member is excluded (`ERR_MEMBER_EXCLUDED`), if `ended_at` is not strictly greater than `started_at` (`ERR_SESSION_INVALID_TIMES`), if `theoretical_loss_cents` exceeds one hundred million cents — the regulatory single-session reporting cap of one million US dollars — in which case the response is `ERR_SESSION_LOSS_OVER_CAP`, or if the half-open interval from `started_at` (inclusive) to `ended_at` (exclusive) truly overlaps an existing `RECORDED` session for the same member on the same property — touching at an endpoint is allowed, true overlap is rejected with `ERR_SESSION_OVERLAP`.

On a successful submission the session is created in `status` `RECORDED` and the tier-credit accrual engine fires. The engine first converts the theoretical loss into base credits by dividing `theoretical_loss_cents` by one hundred — a session on slots earning one Tier Credit per dollar of theoretical loss. For `TABLE_GAMES` the base figure is multiplied by two, and for `POKER` by one and a half; slots take a game-type multiplier of one. The result is then multiplied by a tier-driven coefficient that depends on the member's `tier_status` *as it stood the moment the request began*, before any tier promotion that this same session might trigger: `GOLD` carries a coefficient of one, `PLATINUM` of one and one-quarter, `DIAMOND` of one and one-half, and `SEVEN_STARS` of two. The final value is rounded half-up to two decimal places — this rounding is done per session, before the value is added to any running total — and stored on the session as `tier_credits_earned`. The same value is then added to the member's `tier_credits_ytd` (year-to-date) and to the member's `tier_credits_lifetime` (which never resets).

After accrual, the tier-promotion state machine runs against the updated `tier_credits_ytd`. A member who is not excluded promotes from `GOLD` to `PLATINUM` when `tier_credits_ytd` reaches at least fifteen thousand, from `PLATINUM` to `DIAMOND` when it reaches at least seventy-five thousand, and from `DIAMOND` to `SEVEN_STARS` when it reaches at least one hundred and fifty thousand. Each promotion refreshes the member's `updated_at` and increments the member's `version`. A member whose `exclusion_status` is `EXCLUDED` does not promote even if their session-driven totals would otherwise have crossed a threshold.

### 3.4. Velocity Monitoring

After the accrual settles, the velocity-monitoring routine runs on the same recorded session. It looks back one hour — exactly three thousand six hundred seconds — from the just-recorded session's `ended_at` and computes the sum of `theoretical_loss_cents` across every `GamingSession` for this member whose `status` is `RECORDED` and whose `ended_at` falls in the window that is open on the left (strictly greater than `window_start`) and closed on the right (less than or equal to `window_end`). The boundary on the upper threshold matters: a total that is greater than or equal to one and a half million cents (fifteen thousand US dollars) creates a `VelocityAlert` with `severity` `SUSPENDED`, and a total that is greater than or equal to five hundred thousand cents (five thousand US dollars) but below the suspend threshold creates a `VelocityAlert` with `severity` `FLAGGED`. A total of exactly five hundred thousand cents trips `FLAGGED`, not `NORMAL`. The alert row records its `window_start`, `window_end`, the computed `total_theoretical_loss_cents`, and `severity`; it carries `id` and `created_at` but no `updated_at` or `version` (it is audit-immutable). 

The `VelocityAlert` then drives the member's `velocity_status` machine. From `NORMAL`, a `FLAGGED` alert advances the member to `FLAGGED`. From either `NORMAL` or `FLAGGED`, a `SUSPENDED` alert advances the member to `SUSPENDED` and, in the same operation, cancels every `CompRoomBooking` for that member whose current status is in `PENDING` or `CONFIRMED` — the suspension simultaneously protects the casino's compliance posture and clears the member's outstanding comp pipeline. Each transition increments the member's `version`. This is the depth-three cascade that originates from a single session record: gaming session creation → velocity alert → member velocity transition → booking cancellations.

A `ComplianceOfficer` may manually clear the member out of `SUSPENDED` back to `NORMAL` through the velocity-clear capability, which takes `expected_member_version`. The clear is permitted only if the member is currently `SUSPENDED` and the member's most recent `VelocityAlert.window_end` lies strictly more than twenty-four hours before the server's current UTC clock; otherwise the request is refused on state grounds. `VelocityAlert` rows are inspectable individually and through a paginated list filterable by `member_id` and `severity`.

### 3.5. Host Assignments and the Two-Person Approval Discipline

A `LoyaltyManager` initiates a host engagement by submitting a payload that carries the `member_id`, the `host_id`, and the `expected_member_version` for the OCC check on the member. The submission is refused if the member is excluded (`ERR_MEMBER_EXCLUDED`) or if the supplied member version no longer matches the member's current `version` (`ERR_STALE_MEMBER_VERSION`); the OCC check is exactly the gate that catches a stale operator who is unaware that the member has just self-excluded and seen their pending assignments revoked. On success the assignment is created in `status` `PENDING_APPROVAL` with `assigned_by_user_id` set to the creator's `X-User-ID`, `approved_by_user_id` null, and `version` 1; the member's `version` is incremented to mark the new pending engagement.

A second `LoyaltyManager` then resolves the assignment. Approving the assignment requires that the approver's `X-User-ID` differs from the creator's `assigned_by_user_id` (segregation of duties — same-operator approval is refused with `ERR_SOD_VIOLATION`), that the assignment is still in `PENDING_APPROVAL`, that the member's `exclusion_status` is not `EXCLUDED`, that the host's `status` is `ACTIVE`, and that no other `HostAssignment` for the same member is currently `ACTIVE` (a member may have at most one active host at a time — a duplicate is refused with `ERR_ACTIVE_HOST_EXISTS`). On approval, the assignment transitions `PENDING_APPROVAL → ACTIVE`, the approver's `X-User-ID` is captured as `approved_by_user_id`, and the member's `assigned_host_id` is set to this assignment's `host_id`; both the assignment's `version` and the member's `version` are incremented. Rejecting the assignment shares the segregation-of-duties precondition and the pending-state precondition; it transitions the assignment `PENDING_APPROVAL → REJECTED` and increments only the assignment's `version`.

An `ACTIVE` assignment can later be revoked, either by a `LoyaltyManager` or a `ComplianceOfficer`, transitioning the assignment `ACTIVE → REVOKED` and, because this was the member's active assignment, clearing `assigned_host_id` back to null and incrementing the member's `version`. The same `ACTIVE → REVOKED` transition also fires as the depth-two cascade from a self-exclusion (see §3.7); a `PENDING_APPROVAL → REVOKED` cascade likewise occurs in the same scenario for assignments that had not yet been approved. Host assignments are inspectable individually and through a paginated list filterable by `member_id`, `host_id`, and `status`.

### 3.6. Comp-Room Bookings and the Provisional / Final Rate

A `LoyaltyManager` creates a comp-room booking by submitting a payload that carries the `member_id`, the `property_id`, the `check_in` and `check_out` timestamps, and the `expected_member_version` for the OCC check. The booking is refused if the member is excluded (`ERR_MEMBER_EXCLUDED`), if the member is velocity-suspended (`ERR_MEMBER_VELOCITY_SUSPENDED`), if `check_out` is not strictly greater than `check_in` (`ERR_BOOKING_INVALID_DATES`), if the supplied member version is stale (`ERR_STALE_MEMBER_VERSION`), or if the half-open interval from `check_in` (inclusive) to `check_out` (exclusive) intersects with other non-terminal bookings (`PENDING`, `CONFIRMED`, or `CHECKED_IN`) at the same property such that the aggregate count of overlapping bookings at any point of intersection would exceed the property's occupancy cap of twenty — that aggregate-capacity overlap is refused with `ERR_BOOKING_OVERLAP` (this is distinct from the binary touching-vs-overlap rule on gaming sessions; here the rejection is about exceeding capacity across the interval intersection).

On creation, the server derives `nights` as the difference between `check_out` and `check_in` measured in seconds, divided by 86,400, and rounded up to the nearest whole number. It then runs the provisional variant of the comp-room rate calculation and stores the result in `provisional_rate_cents`, computing `total_charge_cents` as `nights` multiplied by `provisional_rate_cents`. The booking is created in `status` `PENDING` with `version` 1 and `final_rate_cents` null; the member's `version` is incremented.

The provisional rate begins from the property's `base_room_rate_cents` and applies, in order, two multipliers. The first is the tier-driven comp discount, which represents the fraction of the base rate that the casino is waiving: ten one-hundredths for `GOLD`, forty one-hundredths for `PLATINUM`, seventy one-hundredths for `DIAMOND`, and the full base rate for `SEVEN_STARS`. The server multiplies the base rate by one minus that fraction and rounds the result half-up to whole cents. The second multiplier is the market-segment band — one and two-tenths for `VEGAS_STRIP`, one for `REGIONAL`, and one and one-tenth for `INTERNATIONAL` — applied to the post-discount cent value and again rounded half-up to whole cents. Both rounding steps are performed at the multiplication, not deferred to the end. The provisional rate is computed using the member's `tier_status` at the instant of booking creation.

A second `LoyaltyManager` action confirms the booking, transitioning it `PENDING → CONFIRMED`. Confirmation is refused unless the member is not excluded (`ERR_MEMBER_EXCLUDED`), the member is not velocity-suspended (`ERR_MEMBER_VELOCITY_SUSPENDED`), and the member's `tier_status` is currently in the set `PLATINUM`, `DIAMOND`, or `SEVEN_STARS` — `GOLD` members are not eligible for comp rooms, and the refusal is `ERR_TIER_INELIGIBLE_FOR_COMP`. A confirmed booking may be reverted back to `PENDING` (transitioning `CONFIRMED → PENDING`) provided the server's current UTC clock is still strictly before the booking's `check_in`.

Check-in transitions the booking `CONFIRMED → CHECKED_IN`, but only once the server's current UTC clock is at or past the booking's `check_in`, and only if the member is not excluded and not velocity-suspended. At check-in the server recomputes the same rate formula in its final variant: same base rate (re-read from the property), same discount-then-market sequence of multiplications, same per-step round-half-up, but using the member's `tier_status` at the moment of check-in. The result is stored as `final_rate_cents`, and `total_charge_cents` is overwritten as `nights` multiplied by `final_rate_cents`. The two rates differ when, between booking creation and check-in, the member's tier has changed — typically a promotion driven by intervening play; that is the legitimate source of rate drift, and it is by design.

Check-out transitions the booking `CHECKED_IN → COMPLETED` once the server's current UTC clock is at or past the booking's `check_out`. Cancellation transitions the booking from either `PENDING` or `CONFIRMED` to `CANCELLED` and may be initiated by a `LoyaltyManager`, by the member themselves on their own bookings, or by the system as a cascade from a member self-exclusion or a velocity suspension. The bookings list is filterable by `member_id`, `property_id`, and `status`.

### 3.7. Self-Exclusion and the Two-Level Cascade

A `Member` self-excludes by submitting a payload that carries their `member_id`, the `exclusion_until` date marking the earliest eligible reinstatement instant, and a free-text `reason`. The server stamps `requested_at` with the current UTC clock. The submission is refused if the member already has an `ACTIVE` `SelfExclusion` row (state precondition: at most one active exclusion at a time) or if the duration from `requested_at` to `exclusion_until` is less than three hundred and sixty-five days — the regulator-mandated minimum self-exclusion period, refused with `ERR_EXCLUSION_PERIOD_TOO_SHORT`. The `SelfExclusion` row is created in `status` `ACTIVE` and carries `id` and `created_at` only (no `updated_at`, no `version`).

The self-exclusion is the deepest cascade in the system. In the same operation, the server transitions the member's `exclusion_status` from `NOT_EXCLUDED` (or `REINSTATED`, on a repeat self-exclusion) to `EXCLUDED`; transitions every `HostAssignment` for this member whose current status is in `PENDING_APPROVAL` or `ACTIVE` to `REVOKED`; transitions every `CompRoomBooking` for this member whose current status is in `PENDING` or `CONFIRMED` to `CANCELLED`; and, if any of the revoked assignments was the active one, nulls out `assigned_host_id`. The member's `updated_at` is refreshed and the member's `version` is incremented. Each touched assignment and each touched booking likewise has its `updated_at` refreshed and its `version` incremented. This is the depth-three cascade that ties responsible-gambling enforcement to operational state: self-exclusion → member exclusion-status transition → assignment and booking transitions → `assigned_host_id` null-out.

Reinstatement is initiated by the same `Member` once the exclusion period has elapsed: the request is accepted only when the corresponding `SelfExclusion` is in `status` `ACTIVE` and the server's current UTC clock has reached or surpassed `exclusion_until`. On success, the `SelfExclusion` transitions `ACTIVE → REINSTATED`, the member's `exclusion_status` transitions `EXCLUDED → REINSTATED`, and the member's `version` is incremented. From `REINSTATED` the member may self-exclude again under the same minimum-period rule, cycling the exclusion-status dimension back to `EXCLUDED`. The self-exclusion list is filterable by `member_id` and `status`.

### 3.8. The Annual Reset

The loyalty year is closed by an `AnnualResetRun`. A `ComplianceOfficer` schedules the run by submitting `reset_year` (an integer of at least 2020) and `scheduled_for` (the ISO 8601 UTC instant at which the run becomes executable). `reset_year` must be unique across `SCHEDULED` rows — a duplicate scheduling is refused with `ERR_RESET_YEAR_TAKEN`. The run is created in `status` `SCHEDULED` and may take either of two terminal transitions.

Cancelling a scheduled run is permitted only while the server's current UTC clock remains strictly before `scheduled_for`; an attempt to cancel after that point fails with `ERR_RESET_ALREADY_DUE`. On success the run transitions `SCHEDULED → CANCELLED` and its `version` is incremented.

Executing the run is permitted only once the server's current UTC clock has reached or surpassed `scheduled_for`; an earlier attempt fails with `ERR_RESET_NOT_DUE`. The run is additionally refused if another `SCHEDULED` run exists for the same `reset_year` (an `ERR_INVALID_STATE` state issue). On execution, the server captures `tier_credits_lifetime_invariant_before_cents` as the sum of `tier_credits_lifetime` across every `Member`, expressed in integer cents (each member's `tier_credits_lifetime` Tier-Credit value is multiplied by one hundred and the cross-member total is then rounded half-up to a whole integer — the `_cents` suffix is load-bearing); then, for every member whose `exclusion_status` is not `EXCLUDED`, resets `tier_credits_ytd` to zero and sets `tier_status` to `GOLD` (every such member's `version` is incremented); counts those members into `members_reset_count`; captures `tier_credits_lifetime_invariant_after_cents` as the post-reset sum of `tier_credits_lifetime` under the same Tier-Credits-times-one-hundred integer-cents convention; transitions the run `SCHEDULED → EXECUTED`; and increments the run's `version`. Both invariant fields are integer counts of cents (not the Tier-Credit values themselves). Lifetime totals are never reset — the before-and-after invariant exists precisely so that the system can prove this — and excluded members are deliberately left out of the reset, preserving their state for post-reinstatement audit.

### 3.9. State Transition Reference

Each transition described above can be reached from the endpoint table in §4 by joining the state pair below with the role and capability description that drives it:

- `Member.tier_status`: `GOLD → PLATINUM`, `PLATINUM → DIAMOND`, `DIAMOND → SEVEN_STARS` on session-driven accrual; `PLATINUM → GOLD`, `DIAMOND → GOLD`, `SEVEN_STARS → GOLD` on annual-reset execution.
- `Member.exclusion_status`: `NOT_EXCLUDED → EXCLUDED` and `REINSTATED → EXCLUDED` on self-exclusion creation; `EXCLUDED → REINSTATED` on self-exclusion reinstatement.
- `Member.velocity_status`: `NORMAL → FLAGGED`, `FLAGGED → SUSPENDED`, and `NORMAL → SUSPENDED` driven by velocity alerts on session record; `SUSPENDED → NORMAL` on compliance velocity-clear.
- `CompRoomBooking`: `PENDING → CONFIRMED`, `CONFIRMED → CHECKED_IN`, `CHECKED_IN → COMPLETED`, `PENDING → CANCELLED`, `CONFIRMED → CANCELLED`, `CONFIRMED → PENDING`.
- `HostAssignment`: `PENDING_APPROVAL → ACTIVE`, `PENDING_APPROVAL → REJECTED`, `ACTIVE → REVOKED`, `PENDING_APPROVAL → REVOKED` (cascade).
- `SelfExclusion`: `ACTIVE → REINSTATED`.
- `AnnualResetRun`: `SCHEDULED → EXECUTED`, `SCHEDULED → CANCELLED`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the newly created row in `data`; endpoints that modify an existing resource (including state transitions) return HTTP 200 with the updated row. All read endpoints return HTTP 200. Request bodies, response bodies, and side effects for each endpoint are described in §3 — the table below is a directory, not a contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /members | Register a new universal-loyalty member. | MemberServices |
| GET | /members/{id} | Fetch a member by id. | MemberServices, LoyaltyManager, ComplianceOfficer, Member |
| GET | /members | List members with optional filters. | MemberServices, LoyaltyManager, ComplianceOfficer |
| POST | /members/{id}/clear-velocity | Manually clear a velocity SUSPENDED status (OCC-gated). | ComplianceOfficer |
| POST | /properties | Register a property. | ComplianceOfficer |
| GET | /properties/{id} | Fetch a property. | MemberServices, LoyaltyManager, ComplianceOfficer |
| GET | /properties | List properties. | MemberServices, LoyaltyManager, ComplianceOfficer |
| GET | /properties/{id}/members | List the members whose home property is {id}. | MemberServices, LoyaltyManager, ComplianceOfficer |
| POST | /hosts | Register a host. | ComplianceOfficer |
| GET | /hosts/{id} | Fetch a host. | LoyaltyManager, ComplianceOfficer |
| GET | /hosts | List hosts. | LoyaltyManager, ComplianceOfficer |
| POST | /host-assignments | Create a host assignment in PENDING_APPROVAL (OCC-gated). | LoyaltyManager |
| POST | /host-assignments/{id}/approve | Approve a pending assignment (different operator). | LoyaltyManager |
| POST | /host-assignments/{id}/reject | Reject a pending assignment (different operator). | LoyaltyManager |
| POST | /host-assignments/{id}/revoke | Revoke an active assignment. | LoyaltyManager, ComplianceOfficer |
| GET | /host-assignments/{id} | Fetch a host assignment. | LoyaltyManager, ComplianceOfficer |
| GET | /host-assignments | List host assignments. | LoyaltyManager, ComplianceOfficer |
| POST | /gaming-sessions | Record a session; triggers accrual and velocity monitoring. | MemberServices |
| GET | /gaming-sessions/{id} | Fetch a session. | MemberServices, LoyaltyManager, ComplianceOfficer |
| GET | /gaming-sessions | List sessions. | MemberServices, LoyaltyManager, ComplianceOfficer |
| POST | /comp-room-bookings | Create a comp-room booking; provisional rate computed (OCC-gated). | LoyaltyManager |
| POST | /comp-room-bookings/{id}/confirm | Confirm a pending booking. | LoyaltyManager |
| POST | /comp-room-bookings/{id}/check-in | Check in a confirmed booking; final rate computed. | LoyaltyManager |
| POST | /comp-room-bookings/{id}/check-out | Check out from a checked-in booking. | LoyaltyManager |
| POST | /comp-room-bookings/{id}/cancel | Cancel a non-checked-in booking. | LoyaltyManager, Member |
| POST | /comp-room-bookings/{id}/revert-to-pending | Revert a confirmed booking back to PENDING. | LoyaltyManager |
| GET | /comp-room-bookings/{id} | Fetch a booking. | LoyaltyManager, MemberServices, Member |
| GET | /comp-room-bookings | List bookings. | LoyaltyManager, MemberServices, ComplianceOfficer |
| POST | /self-exclusions | Self-exclude; cascades revokes and cancellations. | Member |
| POST | /self-exclusions/{id}/reinstate | Reinstate after the exclusion period has elapsed. | Member |
| GET | /self-exclusions/{id} | Fetch a self-exclusion. | Member, ComplianceOfficer |
| GET | /self-exclusions | List self-exclusions. | ComplianceOfficer, Member |
| GET | /velocity-alerts/{id} | Fetch a velocity alert. | ComplianceOfficer |
| GET | /velocity-alerts | List velocity alerts. | ComplianceOfficer |
| POST | /annual-reset-runs | Schedule an annual reset for a reset_year. | ComplianceOfficer |
| POST | /annual-reset-runs/{id}/execute | Execute a due reset. | ComplianceOfficer |
| POST | /annual-reset-runs/{id}/cancel | Cancel a not-yet-due reset. | ComplianceOfficer |
| GET | /annual-reset-runs/{id} | Fetch a reset run. | ComplianceOfficer |
| GET | /annual-reset-runs | List reset runs. | ComplianceOfficer |
| POST | /_clock/set_current_utc | Test-driving: pin the server's current UTC clock. | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_MEMBER_VERSION | 412 |
| ERR_MEMBER_EXCLUDED | 422 |
| ERR_MEMBER_VELOCITY_SUSPENDED | 422 |
| ERR_EXCLUSION_PERIOD_TOO_SHORT | 422 |
| ERR_SOD_VIOLATION | 422 |
| ERR_ACTIVE_HOST_EXISTS | 422 |
| ERR_TIER_INELIGIBLE_FOR_COMP | 422 |
| ERR_RESET_NOT_DUE | 422 |
| ERR_RESET_ALREADY_DUE | 422 |
| ERR_SESSION_INVALID_TIMES | 422 |
| ERR_BOOKING_INVALID_DATES | 422 |
| ERR_EMAIL_TAKEN | 409 |
| ERR_RESET_YEAR_TAKEN | 409 |
| ERR_SESSION_OVERLAP | 409 |
| ERR_BOOKING_OVERLAP | 409 |
| ERR_SESSION_LOSS_OVER_CAP | 422 |

# Wind Tunnel API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Wind Tunnel API, the operational backbone of an indoor skydiving venue modelled on the iFLY experience. The business sells packaged flight time — minutes of body flight inside a vertical wind tunnel — and must coordinate a surprising amount of moving machinery to deliver each flyer safely into the air: tunnels that need maintenance windows and weight ceilings, certified instructors whose time must not be double-booked, waivers that expire, health and weight declarations that gate the door, and a pricing engine that treats a walk-in customer differently from someone who reserved a party of five a week in advance.

The system is built around a small set of peer resources linked by foreign keys rather than nested ownership. A flyer registers as a Member, signs a Waiver, optionally enrols in a Membership, and purchases a Booking against a published PackageProduct. Front-desk staff schedule Sessions on a Tunnel, assign an Instructor to each, and then place individual Flights — one flyer flying a slice of a booking's minute pool — into a session's seats. Once a session runs, instructors check flyers in, complete or abort their flights, and close the session, at which point the venue reconciles reflight credits, add-on charges, and instructor seniority in a single sweep.

Two themes recur throughout and deserve emphasis up front. First, **money and minutes conserve**: refunds return exactly what was taken, reflight credits granted provisionally are trued up at session close, and seat counts and minute pools always reconcile against their parents. Second, **safety and scheduling are non-negotiable gates**: an unstaffed session cannot start, a tunnel under maintenance cannot run flights, an overweight or unwaivered flyer cannot check in, and an instructor cannot be in two overlapping sessions at once. The remainder of this document defines these rules precisely.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelopes, and cross-cutting principles that apply across the entire API. Business-process detail lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Flyer`, `Instructor`, `FrontDesk`, and `Manager`.

Two of these roles are **entity-backed**, meaning the identity in `X-User-ID` corresponds to a persisted resource:

- When `X-User-Role` is `Flyer`, `X-User-ID` is the `id` of the acting `Member`. The server records `X-User-ID` but does not compare it to any resource's `member_id`; access is gated by role alone, so a `Flyer` may act on any member's record, waivers, bookings, flights, and coaching, not only their own.
- When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`. The server records `X-User-ID` but does not compare it to any resource's `instructor_id`; access is gated by role alone.

The other two roles are **opaque operator identifiers** not tied to any persisted entity:

- When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque front-of-house operator identifier. The server may record it but does not compare it to any entity's `id`. `FrontDesk` handles walk-in bookings, session scheduling and staffing, add-ons, and check-in.
- When `X-User-Role` is `Manager`, `X-User-ID` is an opaque administrative operator identifier, likewise not matched against any entity's `id`. `Manager` owns the catalog (tunnels, instructors, packages), tunnel maintenance, memberships, and the logical clock, and may read all resources.

Role authorization for each endpoint is enumerated in the Section 4 table, and authorization is decided solely by `X-User-Role` against that table with no per-resource ownership comparison. `Manager` may read every resource; `FrontDesk` has broad operational reach; `Flyer` and `Instructor` are constrained to the operations their role permits.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 or above 100 is clamped into that range rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is not a valid integer is rejected with `ERR_VALIDATION` (400).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every top-level resource carries a system-managed `id`: a server-minted UUID with no type prefix. The full set of resources — `Tunnel`, `Instructor`, `Member`, `Membership`, `PackageProduct`, `Booking`, `Session`, `Flight`, `Waiver`, and `CoachingBooking` — additionally carries three timestamps and a counter: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that begins at its initial value and increments by one on every mutation of the resource. `created_at` is fixed at creation; `updated_at` is refreshed on every change; `version` supports optimistic concurrency (see Section 2.6). Whenever a computed field on a resource changes — a member's `wallet_cents`, a booking's `minutes_remaining`, a session's `seats_taken` — that mutation refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. Cross-Resource Consistency and Cascading Side Effects

Many operations touch more than one resource, and the system applies every downstream effect atomically as part of the triggering request. When a session closes, when a flight aborts, or when a booking or session is cancelled, the changes ripple across bookings, members, instructors, flights, and coaching records. Each affected resource independently has its `updated_at` refreshed and its `version` incremented. The precise cascades — which counters move, which statuses flip, and in what order — are described in the workflow narratives of Section 3; this subsection establishes only that they are immediate, complete, and reconciled within the same request that triggers them.

Two conservation invariants hold at all times. For any booking, `minutes_remaining` plus the minutes consumed by its active flights always equals `minutes_included`; every refund exactly restores what a flight consumed. For any session, `seats_taken` plus `seats_available` always equals `capacity`; every seat released exactly offsets a seat taken. Reflight credits obey a similar conservation rule across a member's lifetime counters, detailed in Section 3.7.

### 2.6. Optimistic Concurrency Control on Instructor Assignment

Assigning or reassigning a session's instructor is the one operation guarded by optimistic concurrency control. The assign-instructor request must carry `expected_session_version`, a non-optional field holding the `version` of the target `Session` that the client last observed. The server compares `expected_session_version` against the session's current `version`. If they match, the assignment proceeds and the session's `version` increments by one. If they do not match — because a prior assignment already advanced the session's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made.

This rule makes a stale-view assignment deterministically detectable: two strictly sequential assign calls that both carry the version observed before the first call will see the first succeed and the second rejected with `ERR_STALE_VERSION`, because the first call advanced the session's `version` out from under the second. No endpoint other than instructor assignment takes a version field; all other mutations proceed without an OCC check.

### 2.7. The Logical Clock and Waiver Validity

The system runs on a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly moved it stays at that default — it never falls back to real wall-clock time. An administrative test-driving capability lets an operator advance the clock to a supplied `to_iso8601` instant; the response reports the new clock as `current_utc`. Moving the clock re-evaluates time-sensitive state, most importantly waiver expiry, on the next read.

Waiver validity is entirely a function of this clock. When a waiver is signed, `signed_at` is stamped from the current clock and `expires_at` is set to ninety days after `signed_at`. A waiver reads as `SIGNED` while the current clock is at or before `expires_at`, and is treated as `EXPIRED` once the current clock passes `expires_at`. This expiry is what the check-in safety gate consults.

### 2.8. Resource Retrieval and Reverse-Reachability Filters

The topology is flat: every resource is a top-level collection reached directly, and relationships are expressed through foreign-key fields rather than nested URL ownership. A single-resource retrieval validates the identifier in its path and returns `404` with the resource-specific not-found error (for example `ERR_SESSION_NOT_FOUND`) when it does not resolve. For any request that carries several identifiers — a path id together with foreign keys in the body — existence is validated left-to-right in the order given in Section 2.10, and the first identifier that fails to resolve determines which not-found error is returned.

List endpoints support **reverse-reachability filtering**: rather than walking a nested path, a caller narrows a collection by the foreign keys and status of interest. Waivers may be filtered by `member_id` and `status`; memberships by `member_id` and `status`; bookings by `member_id`, `package_id`, and `status`; sessions by `tunnel_id`, `instructor_id`, and `op_status`; flights by `booking_id`, `session_id`, `member_id`, and `status`; and coaching bookings by `flight_id`, `instructor_id`, and `status`. All such filters combine with the `limit` and `offset` pagination parameters.

### 2.9. Money, Minutes, and Rounding Precision

All monetary amounts are stored and returned as integer **cents** — `base_price_cents`, `total_price_cents`, `wallet_cents`, `refunded_cents`, `outstanding_addon_cents`, `video_charge_cents`, `charge_cents`, and the statement totals are all whole-cent integers. Wherever a price computation produces a fractional cent, the result is rounded to a whole number of cents using the **round-half-up** convention (a half-cent rounds up). Two pricing rules make the placement of that rounding significant, and both are specified exactly in Section 3: booking price applies a **single final rounding** after all multipliers are combined, while the add-on statement rounds **each line item independently before summing**. Flight minutes, reflight credits, seat counts, and party sizes are all integers; no minute value is ever fractional and none is ever allowed to go negative.

### 2.10. Validation Order and Precedence

When several validations could apply to one request, they are evaluated in a fixed priority order, and the first failure determines the error returned. Lower-priority checks are never reached once a higher-priority check fails.

1. **Authentication** — `X-User-Role` and `X-User-ID` must be present and recognized, else `ERR_UNAUTHENTICATED` (401). This is checked first on every request.
2. **Authorization** — the authenticated role must be permitted for the operation per Section 2.1 and the Section 4 table, else `ERR_FORBIDDEN` (403).
3. **Existence** — all referenced resources must exist, validated left-to-right: the path id first, then body foreign keys in the order `member_id`, `package_id`, `tunnel_id`, `instructor_id`, `booking_id`, `session_id`, `flight_id`. The first unresolved identifier yields the corresponding `ERR_*_NOT_FOUND` (404).
4. **State** — the target resource must be in a valid state for the requested transition (session operational or staffing axis, flight status, or booking status), else `ERR_INVALID_STATE` (409).
5. **Configuration and eligibility gates** — a package requiring returning experience demands a returning member (`ERR_EXPERIENCE_NOT_ELIGIBLE`), a session start demands an operational tunnel (`ERR_TUNNEL_NOT_OPERATIONAL`), and a flight create or session start demands a staffed session (`ERR_SESSION_NOT_STAFFED`), all at 409. These apply to booking creation, flight creation, and session start.
6. **Check-in safety gates** — a valid signed waiver and a within-limit weight, else `ERR_WAIVER_INVALID` or `ERR_WEIGHT_LIMIT_EXCEEDED` (422). These apply to check-in.
7. **Temporal gates** — a valid session window, a tunnel free with its turnaround buffer, and an instructor free over the interval, yielding `ERR_INVALID_SESSION_WINDOW` (422), `ERR_SESSION_TIME_CONFLICT` (409), or `ERR_INSTRUCTOR_TIME_CONFLICT` (409). These apply to session creation and instructor assignment.
8. **Structural constraints** — a party size of at least one and at least one available seat, else `ERR_INVALID_PARTY_SIZE` or `ERR_SESSION_FULL` (422). These apply to booking creation and flight creation respectively.
9. **Fiscal sufficiency** — a booking must retain enough minutes for a new flight, else `ERR_INSUFFICIENT_MINUTES` (422). This applies to flight creation.

Malformed bodies — a missing required field, a wrong type, or an invalid enum value — are rejected with `ERR_VALIDATION` (400).

## 3. Business Logic & Workflows

### 3.1. The Catalog: Tunnels, Instructors, and Packages

A `Manager` establishes the venue's fixed assets. A tunnel is created with a `name`, a `max_weight_kg` ceiling that every flyer's weight is checked against at check-in, a `default_capacity` that seeds new sessions when they omit an explicit seat count, and a `turnaround_minutes` buffer that the scheduler enforces as the mandatory gap between two sessions on that same tunnel. A new tunnel begins with its `status` set to `OPERATIONAL`. A manager may later toggle that status through a maintenance capability that accepts a `mode` of either `OPERATIONAL` or `MAINTENANCE` and writes it to `status`; a tunnel in `MAINTENANCE` cannot host a session start.

Instructors are likewise created by a `Manager` with a `name` and a `cert_level` of `L1`, `L2`, or `L3`. Every new instructor starts with `tier` at `JUNIOR`, `sessions_completed` at 0, and `status` at `ACTIVE`; an optional `status` of `ACTIVE` or `OFF` may be supplied at creation and defaults to `ACTIVE`. The `sessions_completed` counter tracks how many sessions this instructor has closed; each session close increments it by one, and once it reaches two or more the instructor's `tier` upgrades from `JUNIOR` to `SENIOR`. That upgrade threshold — two completed sessions — is the sole driver of seniority.

Packages are the sellable products, created by a `Manager` with a `name`, the `included_minutes` of flight time granted per flyer, a `base_price_cents` base price per flyer before any adjustment, and a `min_experience` gate. A package whose `min_experience` is `RETURNING` may only be booked for a member whose experience is `RETURNING`; a package whose `min_experience` is `FIRST_TIME` is open to anyone. Packages carry an `active` flag, defaulting to true, indicating whether they can currently be booked; the server records this flag but does not gate booking creation on it, so a booking may still be created against an inactive package.

### 3.2. Flyers, Waivers, and Memberships

A flyer joins the system as a `Member`, self-registered by a `Flyer` or created by `FrontDesk`, providing a `name`, a `weight_kg`, an `experience_status` that defaults to `FIRST_TIME` (the alternative being `RETURNING`), and an optional list of `health_flags` describing declared health conditions, which defaults to an empty list. A newly registered member starts with every counter and balance at zero — `reflight_credit_minutes`, `total_credits_minted`, `total_credits_consumed`, `wallet_cents`, `confirmed_booking_count`, and `outstanding_addon_cents` are all 0 — and a `membership_tier` of `NONE`.

Before flying, a member must sign a `Waiver`, which records the `member_id` of the signer, the `weight_kg_declared` on the form, and a `health_ok` boolean by which the flyer certifies they carry no disqualifying health condition; a member declaring non-empty health conditions relies on this certification. The waiver's `signed_at`, `expires_at`, and `status` follow the logical-clock rules of Section 2.7. A member's flying eligibility at the door depends on holding a `SIGNED`, unexpired waiver.

Memberships confer a standing discount. `FrontDesk` or `Manager` enrols a member by supplying the `member_id` and a `tier` of `STANDARD` or `PRO`. The membership's `discount_pct` is a computed rate — 0.10 (ten percent) for `STANDARD` and 0.15 (fifteen percent) for `PRO` — and its `status` begins `ACTIVE`. While a membership is `ACTIVE`, the owning member's computed `membership_tier` mirrors the membership's tier; the discount applies to booking prices and to add-on charges alike. Cancelling a membership sets its `status` to `CANCELLED` and resets the member's `membership_tier` to `NONE`, so a member with no active membership carries a tier of `NONE` and receives no discount.

### 3.3. Booking a Package: Walk-In and Reservation Pricing

A `Flyer` or `FrontDesk` operator creates a `Booking` by naming the `member_id`, the `package_id`, a `booking_type` of either `WALK_IN` or `RESERVATION`, a `party_size` of at least one flyer, and — for reservations — a `lead_days` count of advance days that defaults to 0 and is ignored entirely for walk-ins. A party size below one is rejected with `ERR_INVALID_PARTY_SIZE`. If the package's `min_experience` is `RETURNING` while the member is `FIRST_TIME`, the booking is rejected with `ERR_EXPERIENCE_NOT_ELIGIBLE`.

On creation the booking's minute pool is fixed: `minutes_included` is the `party_size` multiplied by the package's `included_minutes`, and `minutes_remaining` starts equal to `minutes_included`. The booking's `status` starts `CONFIRMED`, its `refunded_cents` starts 0, and the owning member's `confirmed_booking_count` increases by one. The four booking statuses are `CONFIRMED`, `EXHAUSTED`, `CANCELLED`, and `COMPLETED`.

The booking's `total_price_cents` is computed in a pinned order, entirely in integer cents:

1. Start from the package's `base_price_cents` as the per-flyer amount.
2. Choose a party multiplier by size: exactly 1.00 for a party of one or two, 0.95 for a party of three or four, and 0.90 for a party of five or more.
3. Form the subtotal as the per-flyer base price multiplied by the `party_size` and then by that party multiplier.
4. Apply the type-specific adjustment. For a `WALK_IN`, multiply the subtotal by 1.20 — a twenty-percent walk-in surcharge — and disregard `lead_days` completely. For a `RESERVATION`, apply a lead-time discount instead: no discount when `lead_days` is fewer than 3, a five-percent discount (multiply by 0.95) when `lead_days` is at least 3 but fewer than 7, and a ten-percent discount (multiply by 0.90) when `lead_days` is 7 or more. A reservation carries no surcharge.
5. Apply the member discount by multiplying by one minus the member's rate: 0.00 for `NONE`, 0.10 for `STANDARD`, 0.15 for `PRO`.
6. Round the single final product to a whole number of cents using round-half-up. Only this one rounding occurs; the intermediate products are not rounded.

### 3.4. Scheduling Sessions and Staffing Instructors

`FrontDesk` or `Manager` schedules a `Session` on a tunnel by supplying the `tunnel_id`, a `start_utc`, an `end_utc`, and an optional `capacity` that defaults to the tunnel's `default_capacity` when omitted. The window is validated first: `end_utc` must be strictly later than `start_utc` and the duration must be at least fifteen minutes, or the request is rejected with `ERR_INVALID_SESSION_WINDOW`. The scheduler then checks the tunnel's calendar — the new session may neither overlap another session on the same tunnel nor fall within that tunnel's `turnaround_minutes` buffer of one; a violation yields `ERR_SESSION_TIME_CONFLICT`. Sessions whose `op_status` is `CANCELLED` are excluded from this check. A new session begins with `op_status` at `OPEN`, `staffing_status` at `UNSTAFFED`, `instructor_id` null, `seats_taken` at 0, and `seats_available` equal to its capacity.

A session evolves along two independent axes. The **operational axis** `op_status` moves through `OPEN`, `RUNNING`, `CLOSED`, and `CANCELLED`; the **staffing axis** `staffing_status` is either `UNSTAFFED` or `STAFFED`, and evolves independently of the operational axis on the same row.

Staffing is where the concurrency control of Section 2.6 lives. `FrontDesk` or `Manager` assigns an instructor by supplying the `instructor_id` and the `expected_session_version`. The assignment first requires that `expected_session_version` match the session's current `version`, failing with `ERR_STALE_VERSION` otherwise. It then requires that the chosen instructor have no other non-cancelled session overlapping the half-open interval from `start_utc` to `end_utc` — sessions that merely abut are allowed — failing with `ERR_INSTRUCTOR_TIME_CONFLICT` otherwise. On success the session's `instructor_id` is set, `staffing_status` becomes `STAFFED`, and `version` increments by one. Reassigning an already-staffed session is legitimate: a fresh assignment supersedes the prior one, running the same version check and the same conflict check against the new instructor, again setting `instructor_id` and again incrementing `version`. Because each successful assignment advances `version`, a second assign call carrying a now-stale `expected_session_version` is rejected with `ERR_STALE_VERSION`.

Starting a session, done by an `Instructor` or `FrontDesk`, advances `op_status` from `OPEN` to `RUNNING`. It requires that the session already be `STAFFED`, failing with `ERR_SESSION_NOT_STAFFED`, and that the underlying tunnel's `status` be `OPERATIONAL`, failing with `ERR_TUNNEL_NOT_OPERATIONAL`.

### 3.5. Placing Flights and the Minute Pool

A `Flight` places one flyer into one session seat, consuming minutes from a booking. A `Flyer` or `FrontDesk` operator creates it with the `booking_id` whose pool it draws from, the `session_id` it flies in, the `member_id` of the flyer (validated only for existence; the server does not require it to match the booking's member), and the `scheduled_minutes` reserved for the slot. Creation first requires the session's `op_status` to be `OPEN` or `RUNNING` and the booking's `status` to be `CONFIRMED` or `EXHAUSTED`, else `ERR_INVALID_STATE`; it then requires the session to be `STAFFED` (else `ERR_SESSION_NOT_STAFFED`) and to have at least one open seat (else `ERR_SESSION_FULL`), and requires the booking to hold enough minutes — its `minutes_remaining` must be at least the requested `scheduled_minutes`, else `ERR_INSUFFICIENT_MINUTES`.

Consuming minutes and taking a seat are the two immediate effects of creation. The booking's `minutes_remaining` is its `minutes_included` less the sum of `scheduled_minutes` across all of its flights in the `SCHEDULED`, `CHECKED_IN`, or `FLOWN` states; it is never permitted to go negative, which is why a create that would drive it below zero is rejected outright. If consuming these minutes drives `minutes_remaining` to exactly zero, the booking transitions `CONFIRMED → EXHAUSTED`, and that transition decrements the member's `confirmed_booking_count` by one. Correspondingly, the session's `seats_taken` is the count of its flights in `SCHEDULED`, `CHECKED_IN`, or `FLOWN`, and `seats_available` is `capacity` minus `seats_taken`, never negative. A new flight begins with `status` `SCHEDULED`, `minutes_charged` 0, `flown_minutes` 0, `reflight_credit_granted` 0, `video_addon_purchased` false, and `video_charge_cents` 0.

A flight's `status` follows a branching path: `SCHEDULED`, then `CHECKED_IN`, then a fork into one of the terminal outcomes `FLOWN`, `ABORTED`, `NO_SHOW`, or `CANCELLED`.

### 3.6. Running a Session: Check-In, Completion, Abort, and No-Show

An `Instructor` or `FrontDesk` operator checks a flyer in, advancing the flight `SCHEDULED → CHECKED_IN`. Check-in requires the session's `op_status` to be `OPEN` or `RUNNING`, else `ERR_INVALID_STATE`. It then applies the two safety gates: the member must hold a waiver whose `status` is `SIGNED` with the current clock at or before its `expires_at`, else `ERR_WAIVER_INVALID`; and the member's `weight_kg` must not exceed the tunnel's `max_weight_kg`, where a weight strictly greater than the ceiling is rejected with `ERR_WEIGHT_LIMIT_EXCEEDED` while a weight exactly at the ceiling passes.

From `CHECKED_IN`, an `Instructor` resolves the flight one of three ways, and each session-running action requires `op_status` to be `RUNNING`:

- **Completion** advances `CHECKED_IN → FLOWN`, requiring `op_status` `RUNNING` else `ERR_INVALID_STATE`. It sets the flight's `minutes_charged` to its `scheduled_minutes`; the booking's minutes stay consumed with no refund.
- **Abort** advances `CHECKED_IN → ABORTED`, requiring `op_status` `RUNNING` else `ERR_INVALID_STATE`. The instructor supplies the actual `flown_minutes` reached before the abort. Abort triggers a three-hop cascade: the flight's `scheduled_minutes` are refunded to the booking, so `minutes_remaining` increases by that amount; if the booking had been `EXHAUSTED` this refund flips it `EXHAUSTED → CONFIRMED`; and that flip increments the member's `confirmed_booking_count` by one. Abort also records the supplied `flown_minutes` on the flight and sets its `minutes_charged` to 0, and grants a provisional reflight credit as described in Section 3.7.

A flyer who does not appear is marked as a no-show by `FrontDesk` or `Instructor`, moving the flight from `SCHEDULED` or `CHECKED_IN` to `NO_SHOW`. Unlike an abort or a cancellation, a no-show **forfeits** the minutes — there is no refund to the booking — but the seat is released, so the session's `seats_taken` decrements. The system also produces no-shows automatically at session close, described next.

Closing a session, performed by an `Instructor` or `FrontDesk`, advances `op_status` `RUNNING → CLOSED` and runs a reconciliation sweep. The assigned instructor's `sessions_completed` increases by one, and if it then stands at two or more, the instructor's `tier` upgrades to `SENIOR`. Every flight still `SCHEDULED` or `CHECKED_IN` at close becomes `NO_SHOW` with its minutes forfeited and no refund. Every `FLOWN` flight has its `minutes_charged` finalized to its `scheduled_minutes`. Every `ABORTED` flight has its reflight credit reconciled from provisional to final (Section 3.7). And every coaching booking still `REQUESTED` on the closed session's flights is marked `DELIVERED`.

### 3.7. Reflight Credit: Provisional Grant and Final Reconciliation

Reflight credit compensates a flyer whose flight was cut short. It is tracked per member as `reflight_credit_minutes`, the current balance, and audited across the member's lifetime by `total_credits_minted`, the running total of credit minutes ever granted at their final values, and `total_credits_consumed`, the running total of credit minutes ever spent on discounted reflights. The valuation runs in two variants.

At the moment of **abort**, the credit is granted **provisionally** at the full slot: the flight's `reflight_credit_granted` is set to its `scheduled_minutes`, the member's `reflight_credit_minutes` increases by that same `scheduled_minutes`, and `total_credits_minted` increases by it as well. This deliberately over-grants, crediting the whole booked slot regardless of how many minutes were actually flown.

At **session close**, each aborted flight's credit is reconciled to its **final** value: the credit that should stand is the flight's `scheduled_minutes` less the `flown_minutes` recorded at abort — that is, only the unflown remainder. The reconciliation computes the delta between the final value and the provisional value already granted, a quantity that is zero or negative, and applies that delta to both the member's `reflight_credit_minutes` and `total_credits_minted`, and writes the final value into the flight's `reflight_credit_granted`. In effect the over-grant from abort is wound back so that the member ultimately holds credit only for the minutes they did not fly.

### 3.8. Add-Ons: Video and Coaching Statements

Two add-ons attach to a flight and accrue to the member's `outstanding_addon_cents`. Both apply the member's discount rate — 0.00 for `NONE`, 0.10 for `STANDARD`, 0.15 for `PRO` — and both round each line independently.

A `Flyer` or `FrontDesk` operator purchases the **video add-on** for a flight, setting its `video_addon_purchased` to true. The flight's `video_charge_cents` is computed as 3335 cents multiplied by one minus the member's discount rate, rounded half-up to a whole cent.

**Coaching** is booked by a `Flyer` or `FrontDesk` operator against a flight, naming the `flight_id`, the coaching `instructor_id`, and the `minutes` purchased. A coaching booking begins with `status` `REQUESTED` (its other statuses being `DELIVERED` and `CANCELLED`). Its `charge_cents` is computed as 1245 cents per minute multiplied by the purchased `minutes`, then by one minus the member's discount rate, rounded half-up to a whole cent.

The member's `outstanding_addon_cents` is the sum of these per-line charges: the sum of each video flight's rounded line plus the sum of each non-cancelled coaching booking's rounded line. Because each line is rounded before summation, this total can differ from rounding a raw sum, and the per-line rounding is authoritative. The member's statement view exposes this as `statement_total_cents`, decomposed into `video_charges_cents` and `coaching_charges_cents`. When a coaching booking is cancelled — which happens automatically when its flight is cancelled or marked no-show — its status becomes `CANCELLED` and the member's `outstanding_addon_cents` is reduced by that coaching's `charge_cents`, the statement being recomputed accordingly.

### 3.9. Cancellations, Refunds, and Freed Capacity

Cancellation appears at three levels, each restoring what it can.

A scheduled `Flight` may be cancelled by `FrontDesk` or a `Flyer`, moving it `SCHEDULED → CANCELLED`. The flight's `scheduled_minutes` are refunded to its booking, raising `minutes_remaining`, and the session seat is released, decrementing `seats_taken`. If the refund raises a booking's `minutes_remaining` above zero from an `EXHAUSTED` state, the booking flips `EXHAUSTED → CONFIRMED` and the member's `confirmed_booking_count` increases by one.

A `Booking` may be cancelled by a `Flyer` or `FrontDesk` only while its `status` is `CONFIRMED` or `EXHAUSTED` (otherwise `ERR_INVALID_STATE`), and provided no flight on it is currently `FLOWN`; a booking with a flown flight is rejected with `ERR_BOOKING_HAS_FLOWN_FLIGHT`. Cancellation transitions every `SCHEDULED` or `CHECKED_IN` flight on the booking to `CANCELLED`, refunds the booking's `total_price_cents` to the member's `wallet_cents`, records that same amount in the booking's `refunded_cents`, and sets the booking `status` to `CANCELLED`; if the booking had been `CONFIRMED`, the member's `confirmed_booking_count` decreases by one.

A `Session` may be cancelled by `FrontDesk` or `Manager` from either `OPEN` or `RUNNING`, moving `op_status` to `CANCELLED`. Every non-terminal flight on it — those `SCHEDULED` or `CHECKED_IN` — becomes `CANCELLED` with its `scheduled_minutes` refunded to its booking, and the session's `seats_taken` is recomputed against the freed seats; as with any minute refund, a refund that lifts a booking out of `EXHAUSTED` flips it back to `CONFIRMED` and re-increments the member's `confirmed_booking_count`.

## 4. Endpoint Definitions

Creating a new, standalone resource returns `201 Created`. Operations that modify or transition an existing resource, including retrievals and lifecycle actions, return `200 OK`. All request payloads, response bodies, and side effects for these endpoints are specified in the narratives of Section 3; the table below lists only the routes, their purpose, and the roles permitted to call them.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tunnels` | Create a tunnel | Manager |
| GET | `/tunnels/{id}` | Get a tunnel | Manager, FrontDesk |
| POST | `/tunnels/{id}/maintenance` | Toggle tunnel maintenance mode | Manager |
| POST | `/instructors` | Create an instructor | Manager |
| GET | `/instructors/{id}` | Get an instructor | Manager, FrontDesk |
| POST | `/members` | Register a flyer | Flyer, FrontDesk |
| GET | `/members/{id}` | Get a member | Flyer, FrontDesk, Manager |
| GET | `/members/{id}/statement` | Get a member's add-on statement | Flyer, FrontDesk, Manager |
| POST | `/waivers` | Sign a waiver | Flyer, FrontDesk |
| GET | `/waivers/{id}` | Get a waiver | Flyer, FrontDesk, Manager |
| GET | `/waivers` | List waivers | Flyer, FrontDesk, Manager |
| POST | `/memberships` | Enroll a membership | FrontDesk, Manager |
| GET | `/memberships/{id}` | Get a membership | Flyer, FrontDesk, Manager |
| GET | `/memberships` | List memberships | FrontDesk, Manager |
| POST | `/memberships/{id}/cancel` | Cancel a membership | FrontDesk, Manager |
| POST | `/packages` | Create a package product | Manager |
| GET | `/packages/{id}` | Get a package | Flyer, FrontDesk, Manager |
| POST | `/bookings` | Create a booking | Flyer, FrontDesk |
| GET | `/bookings/{id}` | Get a booking | Flyer, FrontDesk, Manager |
| GET | `/bookings` | List bookings | Flyer, FrontDesk, Manager |
| POST | `/bookings/{id}/cancel` | Cancel a booking and refund to wallet | Flyer, FrontDesk |
| POST | `/sessions` | Schedule a session on a tunnel | FrontDesk, Manager |
| GET | `/sessions/{id}` | Get a session | Flyer, FrontDesk, Manager, Instructor |
| GET | `/sessions` | List sessions | Flyer, FrontDesk, Manager, Instructor |
| POST | `/sessions/{id}/assign-instructor` | Assign or reassign the session instructor (OCC guarded) | FrontDesk, Manager |
| POST | `/sessions/{id}/start` | Start a session | Instructor, FrontDesk |
| POST | `/sessions/{id}/close` | Close a session | Instructor, FrontDesk |
| POST | `/sessions/{id}/cancel` | Cancel a session | FrontDesk, Manager |
| POST | `/flights` | Schedule a flyer into a session slot | Flyer, FrontDesk |
| GET | `/flights/{id}` | Get a flight | Flyer, FrontDesk, Manager, Instructor |
| GET | `/flights` | List flights | Flyer, FrontDesk, Manager, Instructor |
| POST | `/flights/{id}/check-in` | Check a flyer in | Instructor, FrontDesk |
| POST | `/flights/{id}/complete` | Mark a flight flown | Instructor |
| POST | `/flights/{id}/abort` | Abort a flight mid-session | Instructor |
| POST | `/flights/{id}/no-show` | Mark a flyer no-show | FrontDesk, Instructor |
| POST | `/flights/{id}/cancel` | Cancel a scheduled flight | FrontDesk, Flyer |
| POST | `/flights/{id}/video` | Purchase the video add-on for a flight | FrontDesk, Flyer |
| POST | `/coaching-bookings` | Add coaching to a flight | FrontDesk, Flyer |
| GET | `/coaching-bookings/{id}` | Get a coaching booking | Flyer, FrontDesk, Manager, Instructor |
| GET | `/coaching-bookings` | List coaching bookings | Flyer, FrontDesk, Manager, Instructor |
| POST | `/_clock/set_current_utc` | Set the logical clock | Manager, FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_TUNNEL_NOT_FOUND` | 404 Not Found |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_COACHING_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TUNNEL_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_SESSION_NOT_STAFFED` | 409 Conflict |
| `ERR_EXPERIENCE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_WAIVER_INVALID` | 422 Unprocessable Entity |
| `ERR_WEIGHT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_SESSION_WINDOW` | 422 Unprocessable Entity |
| `ERR_SESSION_TIME_CONFLICT` | 409 Conflict |
| `ERR_INSTRUCTOR_TIME_CONFLICT` | 409 Conflict |
| `ERR_SESSION_FULL` | 422 Unprocessable Entity |
| `ERR_INVALID_PARTY_SIZE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_MINUTES` | 422 Unprocessable Entity |
| `ERR_BOOKING_HAS_FLOWN_FLIGHT` | 409 Conflict |

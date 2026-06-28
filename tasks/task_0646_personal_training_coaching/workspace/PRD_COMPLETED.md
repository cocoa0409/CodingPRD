# Personal Training & Coaching API — Product Requirements Document

## 1. Introduction

This document specifies the Personal Training & Online Coaching platform, a system that allows independent coaches to run their entire client relationship through a single API. Coaches onboard prospective trainees through a structured intake and assessment, enroll them into either an in-person session-pack arrangement or an online monthly subscription, deliver workout programs and nutrition (macro) plans, and track progress through periodic check-ins that capture weight, photos, and adherence to habits.

The platform is built around two financial models that behave very differently. A **session pack** is a prepaid bundle of in-person training sessions that is consumed booking by booking, with no-show and late-cancellation fees that erode the client's prepaid value, and refunds owed back when the relationship ends with seats unused. An **online subscription** is a recurring monthly arrangement that is prorated when ended mid-cycle. Layered on top of both is a calendar and booking engine that protects the coach's time with buffer rules, prevents a client from being double-booked, and suspends a client's ability to book after repeated no-shows.

Because session balances, strike counts, macro targets, and adherence scores are all derived from underlying events, the system computes them deterministically and keeps them immediately consistent. The narrative below first establishes the cross-cutting rules every endpoint obeys, then walks the major workflows where those rules combine.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH` (HTTP 401). The system recognizes exactly three roles, spelled precisely as `PlatformAdmin`, `Trainer`, and `Client`. When a caller presents a syntactically valid role but is not permitted to perform the requested operation — or is an ownership-bound role attempting to act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server does not compare it to any entity's `id`; the `PlatformAdmin` is an operational actor who registers trainers, drives the logical clock, and performs cross-tenant reads.

When `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer`. Ownership checks on any resource that references a trainer compare the resource's `trainer_id` to `X-User-ID`: a trainer may act only on clients, engagements, session packs, bookings, programs, macro plans, check-ins, habit logs, and messages whose owning engagement (or client) carries that trainer's identifier; and on the `Trainer` resource itself a trainer may read only its own record (its `id` must equal `X-User-ID`), any other being rejected with `ERR_FORBIDDEN_ROLE`.

When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`. Ownership checks compare the resource's `client_id` — directly, or indirectly through the `client_id` of the engagement the resource belongs to — against `X-User-ID`. A client may act only on its own intake, its own engagements, and the bookings, check-ins, habit logs, and messages scoped to those engagements.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by `created_at` in ascending order, with ties (which the logical clock makes common) broken by ascending creation order so that records minted earlier sort first. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system are mutable, system-tracked entities — the `Trainer`, `Client`, `Engagement`, `SessionPack`, `Booking`, `ProgramAssignment`, `MacroPlan`, and `CheckIn`. Each carries a server-minted `id` formatted as a UUID with no type prefix, used for identity only. Each also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits stamped from the logical clock (not wall-clock time), and a `version` integer. `created_at` is fixed at creation; `updated_at` is refreshed on every mutation; and `version` starts at the initial value and increments by one on each mutation, supporting the concurrency control described in §2.7.

Two entities are append-only event records and are deliberately leaner: the `HabitLog` and the `Message`. Each of these carries only an `id` (a UUID, no prefix) and a `created_at` timestamp (likewise stamped from the logical clock). They have no `updated_at` and no `version` field, because they are never modified after they are written.

The system runs on a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-04-01T00:00:00Z`, and it never falls back to real time; before any clock-setting call it reads precisely this default. An administrative test-driving capability advances the clock to a supplied instant, passed as a `to_iso8601` value in the request body; on success it returns the resulting clock as a single `current_utc` field (the supplied instant, normalized to an ISO 8601 UTC timestamp with three fractional digits). All time-sensitive rules — no-show routing, completion gating, subscription proration, and age derivation for nutrition math — read this logical clock as "now."

### 2.5. Nested Resource Retrieval and Existence Ordering

Several paths address a resource that lives under a parent — session packs, macro plans, and check-ins under an engagement, for example. When a path carries more than one identifier, the system validates them left to right and rejects on the first identifier that does not resolve. A request that names a missing client fails with `ERR_CLIENT_NOT_FOUND` before any nested engagement, booking, or check-in is consulted; a request under a missing engagement fails with `ERR_ENGAGEMENT_NOT_FOUND` before its children are examined. The remaining not-found codes follow the same pattern for their resource types: `ERR_BOOKING_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_MACROPLAN_NOT_FOUND`, `ERR_PACK_NOT_FOUND`, and `ERR_TRAINER_NOT_FOUND`. Foreign-key identifiers supplied in a request body — a `trainer_id`, `client_id`, `engagement_id`, `session_pack_id`, or `program_assignment_id` that names a non-existent record — are likewise rejected with the corresponding not-found code.

### 2.6. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or malformed header (`ERR_MISSING_AUTH`) is detected before anything else. Authorization is second: a forbidden role or an ownership violation (`ERR_FORBIDDEN_ROLE`) is detected next. Third, the existence of every path identifier is checked left to right (the 404 family above). Fourth, the existence of every foreign-key identifier carried in the body is checked. Fifth, the request body itself is validated for well-formedness — required fields present, enum values within range, numeric fields that must be positive (`total_sessions`, `price_cents`, `weight_kg`, `planned_workouts_per_week`, `habit_checks_target`) strictly greater than zero, and the interval guards that `end_utc` is strictly after `start_utc` and `window_end_utc` is strictly after `window_start_utc` — with any breach raising `ERR_INVALID_REQUEST` (HTTP 422). Only after these five gates pass does the system evaluate the state, business-referential, safety, temporal, seat-availability, and concurrency rules that the workflow sections describe; within a single endpoint those later checks are themselves ordered, and where ordering matters the relevant workflow subsection states it explicitly.

### 2.7. Optimistic Concurrency Control

Two creation operations guard against acting on a stale view of a parent record, and both express that guard as a mandatory version field in the request body.

When booking a session against a session pack, the request must carry `expected_session_pack_version` holding the `version` of the target `SessionPack` as the client last observed it. If the pack's current `version` has advanced since then — for example because another writer already committed the last remaining seat and legitimately depleted the pack — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the writer cannot commit a seat against a stale view of `sessions_remaining`. This field is required for bookings that commit a pack seat; bookings on an online-subscription engagement carry no pack and therefore no version field.

When creating an engagement, the request must carry `expected_client_version` holding the `version` of the target `Client` as last observed. If the client's current `version` has advanced — for example because the client was re-assessed or returned to draft after the writer read it, making the writer's view of `intake_status` stale — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two takes a version field.

### 2.8. Money, Counts, and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a money calculation produces a fractional cent — the per-session value of a pack, a no-show fee, a subscription refund, an invoice line, or tax — the result is rounded to a whole cent using the round-half-up convention (a value exactly halfway between two cents rounds upward). Session counts, strike counts, calorie targets, macro grams, and adherence scores are likewise whole integers; the rounding rule for any derived integer is the same round-half-up. The wallet balance owed back to a client, `wallet_credit_cents`, accumulates refunds and credits and is never allowed to go negative.

### 2.9. Cascades, Recomputation, and Threshold Triggers

Several operations mutate more than one entity in a single call, and the system keeps all of them immediately consistent. When a pack seat is committed or released, the pack's seat counts and lifecycle status are recomputed; when a pack depletes, its parent engagement is paused; when a booking becomes a no-show or late cancellation, the client's strike count and booking privilege are recomputed; and when a check-in is assessed, the client's latest weight and any provisional macro targets are recomputed. Each such reconciliation that touches a versioned entity refreshes that entity's `updated_at` and increments its `version`; the one exception is the client recomputations — the strike-and-privilege recompute and the latest-weight recompute refresh `updated_at` and increment `version` only when the recomputed value actually changes, leaving the client untouched (no version bump) when the recomputation yields the same values. The precise direction and triggers of each cascade are described in the workflow that drives it, in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Trainers and the Client Intake Lifecycle

A coaching relationship begins with a `Trainer`, registered by the `PlatformAdmin` with a `full_name`, a unique `email`, and an optional `timezone` (defaulting to `UTC` and used only to display booking windows — every stored instant is UTC regardless). A registered trainer begins with `status` of `ACTIVE`; the alternative `status` value is `DEACTIVATED`.

A trainer onboards a prospective trainee by creating a `Client` record, supplying the `trainer_id` of the owning coach, the client's `full_name`, a unique `email`, the client's `sex` (either `MALE` or `FEMALE`, which selects the metabolic constant used later for nutrition math), the `birth_year` (an integer, from which age is derived as the logical clock's current year minus the birth year), and the `height_cm` (a number that must be strictly greater than zero, else `ERR_INVALID_REQUEST`). A freshly created client starts with `intake_status` of `DRAFT`, a `no_show_strikes` count of 0, and a `booking_privilege` of `ALLOWED`.

Intake then moves through a small, revisable cycle. The client submits their own intake for review, which advances `intake_status` from `DRAFT` to `SUBMITTED`; this is permitted only while the record is in `DRAFT`, and an attempt from any other state is rejected with `ERR_INVALID_STATE`. The trainer reviewing a submission may either accept it or send it back. Accepting it advances `intake_status` from `SUBMITTED` to `ASSESSED`, which is the gate that enables engagement creation for this client; this transition requires the record to be in `SUBMITTED` and otherwise raises `ERR_INTAKE_NOT_SUBMITTED`. Sending it back returns `intake_status` from `SUBMITTED` to `DRAFT` for further revision and likewise requires the `SUBMITTED` state, raising `ERR_INVALID_STATE` otherwise. The submit-then-return loop may repeat as many times as needed, since the intake forms a `SUBMITTED` ↔ `DRAFT` cycle until the trainer is satisfied. Two computed read-back fields on the client — `latest_weight_kg`, described in §3.6, and the strike and privilege fields, described in §3.4 — are surfaced whenever a client is fetched.

### 3.2. Engagements: Enrollment and the Active/Paused/Ended Lifecycle

Once a client is `ASSESSED`, the trainer enrolls them by creating an `Engagement`. The request names the `client_id` and the `billing_model`, and carries the `expected_client_version` for the concurrency guard of §2.7. The `billing_model` is either `SESSION_PACK` or `ONLINE_SUBSCRIPTION` and is fixed for the life of the engagement — it can never be changed after creation. Creation requires the named client to be in `intake_status` `ASSESSED`; if it is not, the request is rejected with `ERR_INTAKE_NOT_ASSESSED`. On success the engagement is born with `status` of `ACTIVE`, its `trainer_id` copied from the client's coaching trainer, a `wallet_credit_cents` balance of 0, and a `pause_reason` of `NONE`; this creation also increments the client's `version` by one. For an `ONLINE_SUBSCRIPTION`, the request additionally supplies `monthly_fee_cents` (a positive integer) and `cycle_start_utc` (a valid ISO 8601 instant) — either missing or malformed raising `ERR_INVALID_REQUEST` — from which the system stores the current billing cycle as the thirty-day window beginning at `cycle_start_utc`.

An engagement's life plays out across three states: `ACTIVE`, `PAUSED`, and the terminal `ENDED`. A trainer may manually pause an active engagement; doing so moves `status` from `ACTIVE` to `PAUSED` and sets `pause_reason` to `MANUAL`. The system itself may pause an engagement when a session pack depletes, in which case `pause_reason` is set to `PACK_DEPLETED` (see §3.3). Either way, pausing requires the engagement to be `ACTIVE` and otherwise raises `ERR_INVALID_STATE`, and while an engagement is `PAUSED` no new bookings may be created against it.

Resuming reverses the pause, moving `status` from `PAUSED` back to `ACTIVE` and resetting `pause_reason` to `NONE`. Resume requires the engagement to be `PAUSED`, raising `ERR_INVALID_STATE` otherwise. There is one extra guard: if the engagement was paused specifically because its pack depleted — that is, `pause_reason` is `PACK_DEPLETED` — it can only resume when the engagement has an `ACTIVE` session pack with at least one seat remaining; otherwise the resume is rejected with `ERR_NO_SESSIONS_REMAINING`. This pause-and-resume forms a deliberate `ACTIVE` ↔ `PAUSED` cycle.

Ending an engagement is the terminal act and may be invoked from either `ACTIVE` or `PAUSED`. The end operation drives a coordinated cascade. First, every booking still in `BOOKED` for this engagement is cancelled — transitioning to `CANCELLED` with no fee — and each such cancellation releases its pack seat. Second, for a `SESSION_PACK` engagement, each `ACTIVE` session pack that still has seats remaining refunds the value of those remaining seats into the engagement's `wallet_credit_cents` and is then marked `REFUNDED` (the settlement arithmetic is in §3.3). Third, for an `ONLINE_SUBSCRIPTION` engagement, the mid-cycle proration refund (§3.7) is added to `wallet_credit_cents`. Fourth, any `MacroPlan` still in `PROVISIONAL` is moved to `LOCKED`, freezing its numbers. Fifth, any `ProgramAssignment` in `DRAFT` or `PUBLISHED` is moved to `ARCHIVED`. Finally the engagement's `status` becomes `ENDED`.

### 3.3. Session Packs: Purchase, Seat Accounting, and Refund Settlement

For a `SESSION_PACK` engagement, the trainer purchases a `SessionPack` by supplying `total_sessions` (the number of sessions bought, which must be greater than zero) and `price_cents` (the total amount paid, also greater than zero). At creation the system records the pack's `per_session_value_cents` as the price divided by the number of sessions, rounded half-up to a whole cent; this per-session value is what drives both no-show fees and end-of-engagement refunds. A new pack starts with `status` of `ACTIVE`, a `sessions_committed` count of 0, and `sessions_remaining` equal to `total_sessions`.

Seat accounting is computed, not stored ad hoc. The committed-seat count, `sessions_committed`, is the number of this pack's bookings whose status is one of `BOOKED`, `COMPLETED`, `NO_SHOW`, or `LATE_CANCELLED`; bookings that ended up `RESCHEDULED` or `CANCELLED` do not occupy a seat. The available count, `sessions_remaining`, is `total_sessions` minus `sessions_committed`, and new bookings are gated when it reaches zero. While the pack is live (in `ACTIVE` or `DEPLETED`), this forward-looking count treats a plain `BOOKED` seat as committed, because that seat is being held for a future session.

A pack's lifecycle status reacts to seat movement. When a committing booking drives `sessions_remaining` to zero, the pack moves from `ACTIVE` to `DEPLETED`, and that depletion bubbles up to pause the parent engagement: the engagement moves `ACTIVE` → `PAUSED` with `pause_reason` set to `PACK_DEPLETED`. Conversely, when a previously committed booking is cancelled and frees a seat so that `sessions_remaining` becomes greater than zero again, a `DEPLETED` pack returns to `ACTIVE`. A pack therefore cycles `ACTIVE` ↔ `DEPLETED` as seats are committed and freed. The only terminal status is `REFUNDED`, reached when an engagement ends while the pack still holds seats.

The refund computed at engagement end uses a **settled** view that differs from the live committed view. At settlement only seats that were truly consumed — those in `COMPLETED`, `NO_SHOW`, or `LATE_CANCELLED` — count against the pack; any seat still merely `BOOKED` is treated as unused and refunded. The refund added to `wallet_credit_cents` is the number of unused seats (the pack's `total_sessions` minus the count of truly consumed seats) multiplied by `per_session_value_cents`. Because outstanding `BOOKED` seats are refunded rather than counted as committed, this settled refund deliberately diverges from the live `sessions_remaining` figure whenever such seats exist, and the pack then moves to `REFUNDED`.

Before any pack is bought, a trainer may price a prospective purchase without persisting anything, by submitting a set of `line_items` for an invoice quote; `line_items` must be a non-empty array, and each line is an object carrying a `list_price_cents` (a non-negative integer list price) and a `discount_pct` (the per-line discount fraction, a number in the inclusive range 0 to 1), with any breach of these shapes raising `ERR_INVALID_REQUEST`. The total is built in a pinned order: first each line's net is computed as its `list_price_cents` multiplied by one minus that line's `discount_pct`, rounded half-up to a whole cent; then those rounded line nets are summed to produce `subtotal_cents`; then tax is computed as the subtotal multiplied by the tax rate of 8.75 percent (0.0875), again rounded half-up to a whole cent, yielding `tax_cents`; and finally `invoice_total_cents` is the subtotal plus the tax. Rounding each line before summing — rather than summing raw amounts and rounding once at the end — is required, because the two orders genuinely diverge: three lines each listing 201 cents at a 50 percent discount round to 101 per line and sum to a subtotal of 303 (not 302), giving a total of 330 (not 328). The quote response returns `subtotal_cents`, `tax_cents`, and `invoice_total_cents` and stores nothing.

### 3.4. Booking a Session: Calendars, Buffers, and Booking Privilege

A session is reserved by creating a `Booking` against an engagement. The core request names the `engagement_id`, a `start_utc`, and an `end_utc` (which must be strictly after the start). For a `SESSION_PACK` engagement the request also names the `session_pack_id` of the pack to draw from and carries the `expected_session_pack_version` concurrency guard; for an `ONLINE_SUBSCRIPTION` engagement the `session_pack_id` must be omitted entirely. On success the booking is created with `status` of `BOOKED`, its `trainer_id` copied from the engagement, a `rescheduled_from_booking_id` of null (set only when the booking is the product of a reschedule, per §3.5), and a `fee_charged_cents` of 0. For a `SESSION_PACK` booking the pack's `sessions_committed` is incremented, the pack's `version` is incremented by one, and if that commit drives `sessions_remaining` to zero the pack depletes and the engagement is paused as described in §3.3.

Booking creation passes through a sequence of business guards, each with its own rejection. The engagement must be `ACTIVE`; a booking attempt against a paused or ended engagement is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`. The billing model and pack must fit: a `SESSION_PACK` booking must reference a `session_pack_id` belonging to that same engagement (of any pack lifecycle status), and an `ONLINE_SUBSCRIPTION` booking must omit `session_pack_id`; a violation of this billing-model fit or pack ownership — independent of whether seats remain — is rejected with `ERR_PACK_MODEL_MISMATCH`. The acting client must currently be allowed to book: if the client's `booking_privilege` is `SUSPENDED`, the create is rejected with `ERR_BOOKING_PRIVILEGE_SUSPENDED`. Two calendar-geometry checks then apply (detailed below). Finally, for a `SESSION_PACK` booking the referenced pack must have `sessions_remaining` greater than zero — regardless of whether its status reads `ACTIVE` or `DEPLETED` — and a booking attempted against a pack with no seats left is rejected with `ERR_NO_SESSIONS_REMAINING`; the `expected_session_pack_version` concurrency guard of §2.7 is the last gate.

The two calendar checks use deliberately different geometry. The **trainer calendar** check treats the proposed interval as half-open from `start_utc` up to but not including `end_utc`, and compares it against every live booking on the same trainer (those in `BOOKED` or `COMPLETED`), but it pads each existing booking by a fifteen-minute buffer (900 seconds) on both ends. The proposed session is rejected with `ERR_BOOKING_OVERLAP` if it intrudes into any padded interval — equivalently, two of a trainer's sessions must be separated by a gap of at least the buffer, so back-to-back sessions, including ones that merely touch end-to-start, are rejected. The **client calendar** check compares the same proposed half-open interval against every live booking (in `BOOKED` or `COMPLETED`) of the same client across all of that client's engagements, but with strict half-open semantics and no buffer at all: an overlap is a true interval intersection, so a session that begins exactly when another ends is permitted. A client double-booking is rejected with `ERR_CLIENT_DOUBLE_BOOKED`. Both checks apply equally to creating a booking and to rescheduling one.

No-show discipline protects the trainer's calendar. A client's `no_show_strikes` is the count of that client's bookings, across all of their engagements, that ended in either `NO_SHOW` or `LATE_CANCELLED`. Whenever a booking enters one of those two states, the count is recomputed; the moment it reaches three or more, the client's `booking_privilege` flips to `SUSPENDED` (it is `ALLOWED` while the count stays below three). Note the boundary: a client sitting at two strikes is still `ALLOWED`, and the third strike is what suspends them. Suspension is what the booking-privilege gate above enforces.

### 3.5. Completing, Cancelling, Rescheduling, and No-Show Handling

Each booking advances out of `BOOKED` along exactly one path, and several of those paths depend on the logical clock relative to the booking's window. A booking is **completed** by the trainer, moving `status` from `BOOKED` to `COMPLETED`; this requires the booking to be `BOOKED` (otherwise `ERR_INVALID_STATE`) and requires that the logical clock has reached or passed the booking's `start_utc` (otherwise `ERR_SESSION_NOT_STARTED`). A completed booking keeps its pack seat committed, since the session genuinely happened.

A booking is **cancelled** by either the client or the trainer, and the timing decides the outcome. If the cancellation arrives at least twenty-four hours before the session starts — that is, the gap from the logical clock to `start_utc` is at least 86,400 seconds — the booking moves to `CANCELLED` free of charge: for a `SESSION_PACK` booking its seat is released (the committed count drops by one), a `DEPLETED` pack returns to `ACTIVE`, and `fee_charged_cents` stays 0. If instead the cancellation arrives within that twenty-four-hour window — the gap is strictly less than 86,400 seconds — the booking is routed to `LATE_CANCELLED` instead: the seat stays committed (the session is treated as consumed), and a fee is charged. For a `SESSION_PACK` engagement the `fee_charged_cents` is the pack's `per_session_value_cents` multiplied by the no-show fee rate of 50 percent (0.50), rounded half-up to a whole cent; for an `ONLINE_SUBSCRIPTION` engagement the fee is 0. A late cancellation counts as a strike, so the client's `no_show_strikes` is recomputed and, if it now reaches three or more, the `booking_privilege` flips to `SUSPENDED`. Cancelling requires the booking to be `BOOKED`, otherwise `ERR_INVALID_STATE`.

A booking is **marked as a no-show** by the trainer when the client failed to attend. This moves `status` from `BOOKED` to `NO_SHOW`, requires the booking to be `BOOKED` (otherwise `ERR_INVALID_STATE`), and requires that the logical clock has reached or passed the booking's `end_utc` (otherwise `ERR_SESSION_NOT_ENDED`). The seat stays committed, and the fee follows the same rule as a late cancellation: `per_session_value_cents` times the 50 percent rate rounded half-up for a `SESSION_PACK` booking, and 0 for an `ONLINE_SUBSCRIPTION`. A no-show also counts as a strike, recomputing `no_show_strikes` and suspending the client's `booking_privilege` if it reaches three or more.

A booking is **rescheduled** by either the client or the trainer to a new time. Rescheduling requires the booking to be `BOOKED` (otherwise `ERR_INVALID_STATE`) and, like a free cancellation, requires that the move is made at least twenty-four hours ahead — the gap from the logical clock to the original `start_utc` must be at least 86,400 seconds, or the request is rejected with `ERR_RESCHEDULE_TOO_LATE`. The new `start_utc` and `end_utc` supplied in the request must clear both calendar checks of §3.4: the trainer buffer geometry (else `ERR_BOOKING_OVERLAP`) and the client half-open geometry (else `ERR_CLIENT_DOUBLE_BOOKED`). A successful reschedule creates a new booking in `BOOKED` whose `rescheduled_from_booking_id` points back to the original booking's `id`, reusing the very same pack seat so there is no net change to the pack's committed count, while the original booking moves to the terminal `RESCHEDULED` state, having handed its seat to the successor; because it creates a new booking resource, the response is `201 Created` and its body is the newly created successor booking.

### 3.6. Check-Ins, Adherence Scoring, and Progress

Progress is captured through periodic check-ins. A check-in is submitted against an engagement with a `measured_at` instant, a body `weight_kg` (greater than zero), an optional set of progress `photo_urls` (defaulting to an empty list), and the adherence window it summarizes, bounded by an inclusive `window_start_utc` and an exclusive `window_end_utc` (which must be strictly after the start). On submission the check-in is created with `status` of `SUBMITTED` and its `adherence_score` is computed over the window.

The `adherence_score` is a single integer from 0 to 100 that blends three behaviors logged during the window, all read from the engagement's habit logs (§3.8) joined to its published program. The window is half-open, from `window_start_utc` up to but not including `window_end_utc`, and its length in whole days, `window_days`, is the window's duration divided by one day and rounded up to the next whole day. The number of planned workouts for the window is the program's `planned_workouts_per_week` multiplied by the window length in days divided by seven, kept at full precision without early rounding. The workout ratio is the count of `WORKOUT_COMPLETED` logs in the window divided by that planned-workout figure, capped at 1. The nutrition ratio is the number of distinct UTC calendar dates on which a `NUTRITION_LOGGED` event occurred in the window divided by `window_days`, capped at 1. The habit ratio is the count of `HABIT_CHECK` logs in the window divided by the program's `habit_checks_target`, capped at 1. These three ratios are kept at full precision and combined with weights of 0.50 for workouts, 0.30 for nutrition, and 0.20 for habits; the weighted blend is multiplied by 100 and rounded half-up to a single integer exactly once at the very end. This round-once discipline — never rounding the individual ratios before weighting — is required for the score to match.

A check-in moves through a revision cycle before it is finalized. The trainer may request a revision, moving `status` from `SUBMITTED` to `REVISION_REQUESTED`; this requires the check-in to be `SUBMITTED`, otherwise `ERR_INVALID_STATE`. The client then resubmits, optionally supplying a corrected `weight_kg` and updated `photo_urls`, which moves `status` from `REVISION_REQUESTED` back to `SUBMITTED` and recomputes the `adherence_score` over the window; this requires the check-in to be `REVISION_REQUESTED`, otherwise `ERR_INVALID_STATE`. The request-and-resubmit pair forms a `SUBMITTED` ↔ `REVISION_REQUESTED` cycle that may repeat. Finally the trainer assesses the check-in, moving `status` from `SUBMITTED` to the terminal `ASSESSED`; this requires the check-in to be `SUBMITTED`, otherwise `ERR_INVALID_STATE`.

Assessing a check-in is the event that updates the client's progress picture. The client's `latest_weight_kg` is recomputed as the `weight_kg` of the most recent check-in that has reached `ASSESSED` or later, where "most recent" means latest by `measured_at` with ties broken by the earlier `created_at`; this value is null until the first such check-in. If a `PROVISIONAL` macro plan exists for the engagement, assessing also recomputes that plan's targets from the new weight, as described next.

### 3.7. Programs, Macro Plans, and Subscription Proration

A `ProgramAssignment` is the workout plan delivered inside an engagement. The trainer creates one with a `title`, a `planned_workouts_per_week` (the planned workout count per seven-day window, greater than zero, used as the workout denominator in adherence scoring), and a `habit_checks_target` (the target habit completions per check-in window, greater than zero, used as the habit denominator). A new program starts in `status` `DRAFT`. Publishing it moves `status` from `DRAFT` to `PUBLISHED`, which requires the program to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and the parent engagement to be `ACTIVE` (otherwise `ERR_ENGAGEMENT_NOT_ACTIVE`); creating a program likewise requires the parent engagement to be `ACTIVE`. Only once a program is `PUBLISHED` may habit logs reference it. A program may be archived from either `DRAFT` or `PUBLISHED`, moving `status` to the terminal `ARCHIVED`, whether by the trainer's explicit request or by the engagement-end cascade of §3.2.

A `MacroPlan` is the nutrition target set, of which there is at most one per engagement. The trainer creates it with a `goal` and an `activity_level`. The `goal` is one of `FAT_LOSS`, `MAINTENANCE`, or `MUSCLE_GAIN`, and the `activity_level` is one of `SEDENTARY`, `MODERATE`, or `ACTIVE`. Creation requires that the client already has a non-null `latest_weight_kg` (that is, at least one assessed check-in carrying a weight) and that no macro plan — provisional or locked — already exists for the engagement; a violation of either condition is rejected with `ERR_NO_WEIGHT_FOR_MACROS`. On creation the system captures `snapshot_weight_kg` from the client's current `latest_weight_kg` and computes the targets, starting the plan in `status` `PROVISIONAL`.

The macro computation runs in a pinned four-step order. First, the basal metabolic rate is derived from the snapshot weight, the client's `height_cm`, and the age computed as the logical clock's current year minus the client's `birth_year`: for a `MALE` client it is ten times the weight in kilograms, plus 6.25 times the height in centimeters, minus five times the age, plus five; for a `FEMALE` client it is the same expression but minus 161 at the end instead of plus five. Second, total daily energy expenditure is the basal rate multiplied by the activity multiplier — 1.2 for `SEDENTARY`, 1.55 for `MODERATE`, or 1.725 for `ACTIVE`. Third, `target_calories` is derived from the goal and the total daily expenditure: for `FAT_LOSS` it is the expenditure reduced by 20 percent (multiplied by 0.80), for `MAINTENANCE` it is the expenditure unchanged, and for `MUSCLE_GAIN` it is the expenditure increased by 10 percent (multiplied by 1.10), with the result rounded half-up to a whole calorie. Fourth, the macro grams are split from `target_calories` using the goal's fractions and the energy density of each macronutrient: protein and carbohydrate each yield four calories per gram and fat yields nine. For `FAT_LOSS` the protein, carbohydrate, and fat fractions of calories are 0.40, 0.30, and 0.30; for `MAINTENANCE` they are 0.30, 0.40, and 0.30; for `MUSCLE_GAIN` they are 0.30, 0.45, and 0.25. Thus `protein_g` is the target calories times the protein fraction divided by four, `carb_g` is the target calories times the carbohydrate fraction divided by four, and `fat_g` is the target calories times the fat fraction divided by nine — each rounded half-up to a whole gram.

While the plan is `PROVISIONAL`, these numbers are an estimate that is recomputed from the client's `latest_weight_kg` every time a check-in is assessed, so the same plan yields different targets as the client's weight changes. Locking the plan moves `status` from `PROVISIONAL` to the terminal `LOCKED`, which requires the plan to be `PROVISIONAL` (otherwise `ERR_INVALID_STATE`) and freezes `target_calories`, `protein_g`, `carb_g`, and `fat_g` so that later check-ins no longer recompute them. Because of this, a locked plan and a provisional plan that started from identical inputs can diverge after a subsequent check-in. A provisional plan is also locked automatically by the engagement-end cascade.

For an `ONLINE_SUBSCRIPTION` engagement, ending mid-cycle produces a prorated refund. The cycle length is the whole number of days in the stored billing window, which is always thirty for a monthly cycle. The elapsed days are the time from the cycle start to the logical clock, divided by one day and rounded down to a whole day. The remaining days are the cycle length minus the elapsed days, clamped to the range from zero up to the full cycle length. The refund in cents is `monthly_fee_cents` multiplied by the remaining days divided by the cycle length, rounded half-up to a whole cent, and that amount is added to the engagement's `wallet_credit_cents` as part of the end cascade.

### 3.8. Habit Logs and Messaging

Throughout an engagement, workouts and habits are recorded as append-only `HabitLog` events. Each log names the `engagement_id` it belongs to, the `program_assignment_id` it is logged against, a `kind`, and the `logged_at` instant at which the workout or habit occurred. The `kind` is one of `WORKOUT_COMPLETED`, `NUTRITION_LOGGED`, or `HABIT_CHECK`, and it is this classification that the adherence score of §3.6 bins into its three ratios according to where `logged_at` falls among the check-in windows. A habit log may only be written against a program that is currently `PUBLISHED` within the same engagement; an attempt to log against a program that is not published is rejected with `ERR_PROGRAM_NOT_PUBLISHED`. Logs are never modified once written.

The engagement also carries a message thread. A `Message` is an append-only record naming the `engagement_id` and a non-empty `body`; its `sender_role` is set by the system from the caller's role to either `TRAINER` or `CLIENT`, never supplied by the client. Like habit logs, messages are write-once event records.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. State-changing operations on an existing resource, list reads, single-resource reads, the invoice quote, and the clock-setting capability return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an explicit UTC instant | PlatformAdmin |
| POST | `/trainers` | Register a trainer | PlatformAdmin |
| GET | `/trainers/{trainerId}` | Get a trainer | PlatformAdmin, Trainer |
| POST | `/clients` | Create a client intake record | Trainer |
| GET | `/clients/{clientId}` | Get a client | Trainer, Client |
| GET | `/clients` | List clients; filter by `trainer_id` | Trainer, PlatformAdmin |
| POST | `/clients/{clientId}/submit-intake` | Client submits intake for assessment | Client |
| POST | `/clients/{clientId}/assess` | Trainer marks intake assessed | Trainer |
| POST | `/clients/{clientId}/return-intake` | Trainer returns intake for revision | Trainer |
| POST | `/engagements` | Create an engagement for an assessed client | Trainer |
| GET | `/engagements/{engagementId}` | Get an engagement | Trainer, Client |
| GET | `/engagements` | List engagements; filter by `client_id` or `trainer_id` | Trainer, Client, PlatformAdmin |
| POST | `/engagements/{engagementId}/pause` | Manually pause an engagement | Trainer |
| POST | `/engagements/{engagementId}/resume` | Resume a paused engagement | Trainer |
| POST | `/engagements/{engagementId}/end` | End an engagement and run the settlement cascade | Trainer |
| POST | `/engagements/{engagementId}/session-packs` | Purchase a session pack | Trainer |
| GET | `/engagements/{id}/session-packs` | List session packs for an engagement | Trainer, Client |
| GET | `/session-packs/{packId}` | Get a session pack | Trainer, Client |
| POST | `/engagements/{engagementId}/session-packs/invoice` | Compute a session-pack purchase invoice | Trainer |
| POST | `/bookings` | Book a session | Trainer, Client |
| GET | `/bookings/{bookingId}` | Get a booking | Trainer, Client |
| GET | `/bookings` | List bookings; filter by `engagement_id`, `session_pack_id`, `trainer_id`, or `rescheduled_from_booking_id` | Trainer, Client, PlatformAdmin |
| POST | `/bookings/{bookingId}/cancel` | Cancel a booking | Trainer, Client |
| POST | `/bookings/{bookingId}/complete` | Mark a booking completed | Trainer |
| POST | `/bookings/{bookingId}/mark-no-show` | Mark a booking as a no-show | Trainer |
| POST | `/bookings/{bookingId}/reschedule` | Reschedule a booking | Trainer, Client |
| POST | `/program-assignments` | Create a program assignment | Trainer |
| GET | `/program-assignments/{programId}` | Get a program assignment | Trainer, Client |
| GET | `/program-assignments` | List program assignments; filter by `engagement_id` | Trainer, Client, PlatformAdmin |
| POST | `/program-assignments/{programId}/publish` | Publish a program | Trainer |
| POST | `/program-assignments/{programId}/archive` | Archive a program | Trainer |
| POST | `/engagements/{engagementId}/macro-plans` | Create a macro plan | Trainer |
| GET | `/macro-plans/{macroPlanId}` | Get a macro plan | Trainer, Client |
| GET | `/engagements/{id}/macro-plans` | List macro plans for an engagement | Trainer, Client |
| POST | `/macro-plans/{macroPlanId}/lock` | Lock a macro plan | Trainer |
| POST | `/engagements/{engagementId}/check-ins` | Submit a check-in | Client, Trainer |
| GET | `/check-ins/{checkInId}` | Get a check-in | Trainer, Client |
| GET | `/engagements/{id}/check-ins` | List check-ins for an engagement | Trainer, Client |
| POST | `/check-ins/{checkInId}/request-revision` | Request a check-in revision | Trainer |
| POST | `/check-ins/{checkInId}/resubmit` | Resubmit a revised check-in | Client |
| POST | `/check-ins/{checkInId}/assess` | Assess a check-in | Trainer |
| POST | `/habit-logs` | Log a workout/nutrition/habit event | Client, Trainer |
| GET | `/habit-logs/{habitLogId}` | Get a habit log | Trainer, Client |
| GET | `/habit-logs` | List habit logs; filter by `engagement_id` or `program_assignment_id` | Trainer, Client |
| POST | `/messages` | Post a message into an engagement thread | Trainer, Client |
| GET | `/messages/{messageId}` | Get a message | Trainer, Client |
| GET | `/messages` | List messages; filter by `engagement_id` | Trainer, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_TRAINER_NOT_FOUND` | 404 Not Found |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PACK_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_MACROPLAN_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKIN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INTAKE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_INTAKE_NOT_ASSESSED` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PACK_MODEL_MISMATCH` | 409 Conflict |
| `ERR_NO_SESSIONS_REMAINING` | 409 Conflict |
| `ERR_NO_WEIGHT_FOR_MACROS` | 409 Conflict |
| `ERR_BOOKING_PRIVILEGE_SUSPENDED` | 403 Forbidden |
| `ERR_BOOKING_OVERLAP` | 409 Conflict |
| `ERR_CLIENT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RESCHEDULE_TOO_LATE` | 409 Conflict |
| `ERR_SESSION_NOT_STARTED` | 409 Conflict |
| `ERR_SESSION_NOT_ENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

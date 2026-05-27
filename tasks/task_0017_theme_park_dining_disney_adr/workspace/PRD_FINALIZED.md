# Theme Park Dining ADR API — Product Requirements Document

## 1. Introduction

Theme-park guests have, for years, had to juggle three independent realities when they sit down for a table-service meal: a 60-day-ahead reservation window that opens at sunrise resort-time and clears within minutes, a prepaid Dining Plan whose credit balance moves in lockstep with every booking action, and a same-day park admission whose status governs whether the guest can even walk into the restaurant they booked. When any one of those realities drifts out of sync — a credit double-debited at the kitchen door, an allergy ticket lost between request and seating, a Lightning Lane add-on still charged after the underlying booking was already cancelled — the in-park guest experience collapses and the cast member at the podium absorbs the failure. This document specifies the platform that holds the three realities in a single consistent model.

The product is a reservation-of-record system covering the full life of a dining commitment: the guest registers a park session for the day, books a 30-minute seating slot inside the rolling 60-day window, holds Dining Plan credits provisionally at booking and finalises them at check-in, optionally attaches an allergy meal request that the kitchen acknowledges and prepares, optionally buys a Lightning Lane add-on whose price is computed at the moment of allocation, and is either seated and completed or marked no-show with the consequent fee assessment and credit release. Three role classes — the end-user Guest, the Restaurant cast member, and the back-office PlatformAdmin — share the same surface but operate on disjoint sets of state transitions. The platform's job is to keep credit movement, capacity allocation, allergy lifecycle, no-show accounting, and add-on redemption mutually consistent under operator-driven clock advances and concurrent edits.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request MUST carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, identifying the role the caller is acting under. Three roles are recognised, spelt exactly as follows: `Guest`, `Restaurant`, and `PlatformAdmin`. A request that omits either header — or carries an empty/whitespace-only `X-User-ID`, or carries an `X-User-Role` value not exactly in that set of three — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that carries valid headers but whose role is not authorised for the called endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same code is returned when the role is generally authorised but the caller is not the owner of the resource being touched. For the `GET /v1/restaurants/{id}` endpoint specifically, a caller acting as `Restaurant` may only read the restaurant row whose `id` equals `X-User-ID`; any other id is `ERR_FORBIDDEN`.

Role identity binds to persisted entities in two of the three cases. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any resource that references a `Guest` (directly via `guest_id`, or transitively through `Reservation.guest_id`) compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Restaurant`, `X-User-ID` is the `id` of the acting `Restaurant`; ownership checks on a `Reservation` or its child `AllergyMeal` compare `Reservation.restaurant_id` to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server records it for audit purposes but never compares it to any entity's `id`, and a `PlatformAdmin` may act on resources irrespective of guest or restaurant ownership.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 20 cryptographically random characters drawn from uppercase ASCII letters and decimal digits (total length 24).
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

All list endpoints accept two query parameters, `limit` and `offset`, and return the four pagination fields (`limit`, `offset`, `total_count`, `has_more`) inside the `meta` envelope. The `limit` parameter defaults to 10 when omitted, has a minimum value of 1, and is capped at a maximum of 100; the `offset` parameter defaults to 0 and has no upper bound beyond what the underlying result set imposes. A `limit` or `offset` value that is not an integer, or a `limit` outside `[1, 100]`, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list endpoint returns results sorted by `created_at` in ascending order — the oldest qualifying resource appears first — and this ordering is stable across paginated calls. `has_more` is `true` iff `offset + len(returned_items) < total_count`.

### 2.4. Common Resource Properties

Most resources in this system — `Guest`, `Restaurant`, `ParkSession`, `DiningPlan`, `Reservation`, `AllergyMeal`, and `LightningLaneAddOn` — carry the same four system-managed fields. The `id` is a server-minted UUID emitted as a string with no entity-type prefix; clients never supply it on create. The `created_at` timestamp is set at insertion time, the `updated_at` timestamp is refreshed on every mutation that the server commits to the resource, and both timestamps follow ISO 8601 UTC form with three fractional digits. The `version` field is an integer that begins at 1 on creation and is incremented by exactly 1 on every server-committed mutation; it is the value compared against `expected_reservation_version` for the two Optimistic Concurrency Control endpoints described in §2.7.

Two entities are exceptions to this convention: `NoShowFeeAssessment` and `CreditLedgerEntry`. Both are append-only audit records — once written, they are never amended — and therefore carry only `id` and `created_at`. They have no `updated_at` and no `version` field at all; clients that expect those keys on these two entities will find them absent from every response. The `NoShowFeeAssessment` also carries a separate `assessed_at` timestamp (described in §3.5), and every `CreditLedgerEntry` carries a `posted_at` timestamp that captures the exact UTC instant at which the underlying reservation transition committed.

### 2.5. Time, Time Zones, and the Test-Drivable Clock

Every datetime field stored or returned by this API is in UTC and is serialised in ISO 8601 form with three fractional digits and a trailing `Z`. The resort, however, runs on `America/New_York` local wall-clock time for two purposes only: the daily 06:00 opening of the rolling 60-day booking window, and the projection used to evaluate a restaurant's `opening_local_time`, `closing_local_time`, visit-date arithmetic, and slot-grid alignment. The resort timezone offset varies across DST boundaries, so the UTC instant of "06:00 resort time, 60 days before visit" shifts across the year — the implementation must compute the wall-clock first and convert, not vice versa. A guest's own `home_timezone` is captured for client-side UI only and never enters any window, capacity, or eligibility computation.

Because window arithmetic, no-show assessment, and Lightning Lane expiry all depend on "current UTC time", the platform exposes an operator-only capability that overrides the wall clock for an entire deployment. After a `PlatformAdmin` advances the clock, all subsequent time-based logic — 60-day window opening, no-show grace expiry, Lightning Lane redemption window, every `_ops` sweep — reads from this virtual instant rather than the host wall clock.

### 2.6. Hierarchical Consistency and Cascade Semantics

Many of the workflows in §3 involve a state transition on one entity that fans out into mutations on others. Whenever such a cascade fires, every affected entity's `updated_at` advances to the same instant as the originating transition and — for entities that carry one — its `version` is incremented by 1. Cascades that release or move credits append the appropriate `CreditLedgerEntry` rows on the same commit boundary. The platform's consistency model is immediate: a caller that observes the originating entity in its post-transition state will, on any subsequent read of a cascaded entity, observe that entity in its post-cascade state as well. There is no eventual-consistency window between an originating transition and its derived effects.

### 2.7. Optimistic Concurrency Control

Two endpoints in this API mutate a `Reservation` (or, in the Lightning Lane allocation case, depend on the `Reservation`'s exact current state) and therefore require the client to prove it is acting on a version of the parent resource it has actually observed. Both endpoints take a non-optional input field `expected_reservation_version` of integer type, which must equal the parent `Reservation`'s current `version`. If it does not, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state changes.

The first such endpoint is the reservation cancellation operation. The hazard it guards is the race in which a client reads a `Reservation` at `version` N, but in the meantime a no-show sweep or a restaurant-side cascade has already advanced the reservation into a terminal state; the client's stale-view cancel must not silently overwrite that newer terminal state, and the platform rejects it with `ERR_STALE_VERSION` (HTTP 412). The second is the Lightning Lane add-on allocation operation, which depends on the `Reservation` still being in `CONFIRMED`; if any other writer has bumped the reservation's `version` since the client's last read, allocation is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the reservation before retrying. Endpoints that are not listed in this section never take `expected_reservation_version`; supplying it is silently ignored on those endpoints, and omitting it on the two listed endpoints is treated as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Validation Priority and Precision

When a single request can fail more than one rule, validation is ordered: authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_FORBIDDEN`), then resolution of any path-templated resource ids left-to-right (`ERR_NOT_FOUND`), then resolution of body-referenced foreign keys such as `guest_id`, `restaurant_id`, `park_session_id`, `dining_plan_id`, and `reservation_id` (`ERR_FK_NOT_FOUND`), then the target resource's current-state compatibility with the requested transition (`ERR_INVALID_STATE`), then the OCC check on `expected_reservation_version` where applicable (`ERR_STALE_VERSION`). Only after all six gates pass does the platform evaluate domain rules — guest-suspension first (`ERR_GUEST_SUSPENDED`), then allergen-shape validation, then temporal rules in the order window-open / past-date / restaurant hours / slot-grid alignment, then capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), then guest-side double-booking (`ERR_GUEST_DOUBLE_BOOKING`), then park-session referential consistency (`ERR_PARK_SESSION_MISMATCH`), then fiscal rules (insufficient credits, plan coverage), then the add-on uniqueness and party-size feasibility constraints. The lower the priority number on a rule, the earlier it fires; the first failing rule is the one whose `error_id` and HTTP status the caller sees.

All monetary amounts in this system are stored and returned as integer cents — there are no fractional-cent fields anywhere in the entity model. Where a computation produces a decimal intermediate (the per-seat multiplication in the no-show fee and the per-seat park-multiplier scaling in the Lightning Lane fee), rounding to integer cents is by the round-half-up rule, and it is applied exactly once at the per-seat boundary. Dining Plan credit movement is integer-only: there is no rounding step at all on `credits_held`, `credits_debited`, or the `credits_delta` on a `CreditLedgerEntry`.

### 2.9. Nested Resource Retrieval

URL paths in §4 are flat — every resource has a single-level path of the form `/v1/<collection>/{id}` or `/v1/<collection>/{id}/<action>`. The `{id}` slot is always validated first: a path id that does not resolve to an existing row yields `ERR_NOT_FOUND` (HTTP 404) before any body or precondition is inspected.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Guests, Restaurants, and Dining Plans

A guest record is created by a `PlatformAdmin` from an `email` (lowercase, RFC 5322 form, and unique across the `Guest` table — the platform accepts `email` matching the regex `^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$` and additionally requires `email == email.lower()`; any malformed value, any uppercase character, a non-string, a missing required field, or a duplicate email are all rejected with `ERR_INVALID_REQUEST` (HTTP 400)), a `full_name` for display, and an IANA `home_timezone` that the platform stores for the guest's UI but never uses in any window computation. New guests open in `ACTIVE` `status` with `no_show_strike_count` set to 0; both fields are system-managed thereafter. A guest's `status` flips to `SUSPENDED` only as a side effect of accumulating no-shows (see §3.5), and once suspended the guest is barred from creating new reservations or Lightning Lane add-ons — those attempts return `ERR_GUEST_SUSPENDED` even when every other validation would have passed.

A `PlatformAdmin` provisions each dining venue with a display `name`, the owning `park_code` (one of `MAGIC_KINGDOM`, `EPCOT`, `ANIMAL_KINGDOM`, `HOLLYWOOD_STUDIOS`), a `capacity_per_slot` between 1 and 400 inclusive, a `slot_minutes` length that is exactly 30 (no other value is supported in v1; if the field is supplied it must equal 30, and if omitted the server defaults it to 30 — any other value yields `ERR_INVALID_REQUEST`), an `is_character_dining` boolean that defaults to false and drives both Lightning Lane pricing uplift and the no-show fee surcharge, a `dining_plan_credit_cost` between 1 and 3 inclusive that is the number of Table-Service credits debited per seat, a non-negative `no_show_base_fee_cents` per seat, and an `opening_local_time` and `closing_local_time` pair in `HH:MM` 24-hour resort wall-clock notation. The closing time is the exclusive upper bound for a slot's start: a slot may start at 21:30 if closing is 22:00, but not at 22:00. `closing_local_time` MUST be strictly later than `opening_local_time` (compared as `(HH, MM)` tuples); otherwise the request is rejected with `ERR_INVALID_REQUEST`. Any malformed `HH:MM`, out-of-range numeric field, wrong type, missing required field, or invalid `park_code` is `ERR_INVALID_REQUEST`.

A `DiningPlan` is issued by a `PlatformAdmin` for a specific `guest_id` at a chosen `tier` (one of `STANDARD`, `PLUS`, `DELUXE`) with a non-negative `table_service_credits_initial` count and a validity interval `[valid_from, valid_until)` — the `valid_from` instant is inclusive UTC, `valid_until` is exclusive UTC. `valid_until` MUST be strictly greater than `valid_from`; otherwise the request is rejected with `ERR_INVALID_REQUEST`. On creation the plan's `table_service_credits_remaining` is set equal to `table_service_credits_initial`, `table_service_credits_held` starts at 0, and the plan opens in `ACTIVE` `status`. A guest is expected to have at most one `ACTIVE` plan at a time; the plan's status transitions to `EXPIRED` or `REVOKED` are administrative.

### 3.2. The Park Session: One per Guest, per Visit Date

Every act of dining at a Disney restaurant is anchored to a `ParkSession`, which represents a single guest's visit to a single park on a single calendar date. A guest (or a `PlatformAdmin` acting on the guest's behalf) creates a session by submitting `guest_id`, `park_code`, and a `visit_date` in `YYYY-MM-DD` form interpreted in the resort timezone. The new session opens in `NOT_STARTED` `status` with both `activated_at` and `closed_at` null. When the guest taps into the park at the front gate, the session is advanced from `NOT_STARTED` to `ACTIVE` and the server stamps `activated_at` with the commit instant; this transition is only permitted when the resort-projected current date equals the session's `visit_date`. The reverse path is `ACTIVE` to `CLOSED`, taken either explicitly by the guest or by an end-of-day operator, with `closed_at` stamped on commit.

Cancelling a session is a separate path and only available from `NOT_STARTED` — any other current status yields `ERR_INVALID_STATE`. When a guest cancels a `NOT_STARTED` session, the platform sets the session's `status` to the literal value `CANCELLED` (this is the fourth permissible `ParkSession.status` value, alongside `NOT_STARTED`, `ACTIVE`, and `CLOSED`), stamps `closed_at`, bumps the session's `version`, and then runs a two-hop cascade. The first hop walks every `Reservation` whose `park_session_id` points at this session and whose `status` is in `PENDING` or `CONFIRMED`, flipping each to `CANCELLED`; for any reservation that was in `CONFIRMED` at the moment of cascade, the plan-credit release fires exactly as it would on a direct cancel — `Reservation.credits_held` is subtracted from the plan's `table_service_credits_held`, `Reservation.credits_held` is zeroed, and a `CreditLedgerEntry` of `entry_type` `RELEASE` is appended with a negative `credits_delta`. The second hop is triggered by the first hop's reservation status changes, not by the original session cancel: for every reservation that was just cascade-cancelled, if a `LightningLaneAddOn` exists for it with `status` in `REQUESTED` or `ALLOCATED`, that add-on's `status` flips to `CANCELLED` as well. The two-hop ordering matters for `updated_at` and `version` bookkeeping: the reservation row is bumped first, then the add-on row.

### 3.3. Booking a Reservation Inside the 60-Day Window

The act of booking is the creation of a `PENDING` `Reservation` and carries six caller-supplied fields: `guest_id`, `restaurant_id`, `park_session_id`, `dining_plan_id`, `slot_start_utc`, and `party_size` (an integer between 1 and 12 inclusive; any non-integer or out-of-range value is rejected with `ERR_INVALID_REQUEST`, as is a `slot_start_utc` that cannot be parsed as ISO 8601). The platform computes `slot_end_utc` as `slot_start_utc` plus the restaurant's `slot_minutes` (always exactly 30 minutes in v1) and stores it serialised in the §2.5 three-fractional-digit `Z` form; this end is the exclusive upper bound of the slot. Booking applies a long ordered list of domain checks.

The booking window opens, for each calendar `visit_date`, exactly 60 days before that date, at 06:00:00 in the resort timezone. To compute the opening instant the platform takes 06:00 local resort time on the visit date, subtracts 60 calendar days, and converts the result to UTC — because the resort observes DST, the UTC instant of window-open drifts across the year. A booking attempt before that instant is rejected with `ERR_OUTSIDE_BOOKING_WINDOW`; a booking whose `visit_date` (or whose slot) is already in the past relative to the current resort-time date is rejected with `ERR_PAST_DINING_DATE`. The slot start, projected back to resort wall-clock, must fall in the half-open interval from the restaurant's `opening_local_time` (inclusive) up to its `closing_local_time` (exclusive); outside that range the request is rejected with `ERR_SLOT_OUTSIDE_HOURS`. The slot start must additionally land on a 30-minute grid measured from `opening_local_time` — if opening is 11:00 a 13:30 start is on grid and a 13:15 start is not, the latter producing `ERR_SLOT_MISALIGNED`. The `slot_start_utc` instant must also carry zero seconds and zero microseconds (i.e., it lands on an exact minute boundary); a non-zero seconds/microseconds component also produces `ERR_SLOT_MISALIGNED`.

Slot capacity is enforced by summing the `party_size` of every other reservation at the same restaurant whose `[slot_start_utc, slot_end_utc)` half-open interval overlaps the candidate's interval and whose `status` is in `PENDING`, `CONFIRMED`, `CHECKED_IN`, or `SEATED`; if that sum plus the candidate's `party_size` exceeds the restaurant's `capacity_per_slot`, the booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`. The guest is also blocked from overlapping themselves: if the same guest already has a non-terminal reservation (one in `PENDING`, `CONFIRMED`, `CHECKED_IN`, or `SEATED`) whose interval, padded by 60 minutes on each side, overlaps the candidate's `[slot_start_utc, slot_end_utc)` interval, the request is rejected with `ERR_GUEST_DOUBLE_BOOKING` — this padded one-dining-slot-per-60-minute rule applies across all four parks, not per-park.

The supplied `park_session_id` must be in `NOT_STARTED` or `ACTIVE` `status`, must share the same `park_code` as the chosen restaurant, and its `visit_date` must equal the resort-projected calendar date of `slot_start_utc`; any mismatch yields `ERR_PARK_SESSION_MISMATCH`. The supplied `dining_plan_id` is recorded on the reservation but is not credit-checked at booking — credit-checking happens at confirmation (§3.4). On success the platform persists the reservation with `status` `PENDING`, `credits_held` 0, `credits_debited` 0, and `confirmed_at`, `checked_in_at`, and `no_show_assessed_at` all null.

### 3.4. Confirmation, Credit Holding, and Patching Party Size

A `PENDING` reservation becomes a real commitment when the guest confirms it, advancing the reservation from `PENDING` to `CONFIRMED`. Confirmation requires the reservation to still be in `PENDING`, the underlying `ParkSession` to be in `NOT_STARTED` or `ACTIVE`, and the booking `Guest` to still be in `ACTIVE` status. The `DiningPlan` must additionally be in `ACTIVE` status and must cover the slot — its `valid_from` must be at or before `slot_start_utc` and `slot_start_utc` must be strictly before `valid_until`; coverage failure raises `ERR_PLAN_NOT_COVERING`. The plan must also have enough free credits: the difference between its `table_service_credits_remaining` and its current `table_service_credits_held` must be at least the restaurant's `dining_plan_credit_cost` multiplied by the reservation's `party_size`. If the plan is short, confirmation fails with `ERR_INSUFFICIENT_CREDITS`.

On a successful commit, the platform sets `Reservation.credits_held` to the restaurant's `dining_plan_credit_cost` multiplied by the reservation's current `party_size`, increases the plan's `table_service_credits_held` by exactly that amount, appends a `CreditLedgerEntry` with `entry_type` `HOLD` and a positive `credits_delta` equal to the held quantity (the convention is that a positive `credits_delta` on `HOLD` or `DEBIT` decreases the plan's `table_service_credits_remaining` or its free pool, and a negative `credits_delta` on `RELEASE` or `REFUND` increases it), and stamps `confirmed_at` with `now()`. The credit movement is integer-only — there is no rounding.

After confirmation, a guest may still adjust the head-count by submitting a new `party_size` against either a `PENDING` or a `CONFIRMED` reservation. The patch re-validates two things: the new `party_size` must not cause the slot to exceed `capacity_per_slot` after accounting for the seats already counted by this reservation, and on a `CONFIRMED` reservation the implied credit-hold delta must not deplete the plan's `(table_service_credits_remaining - table_service_credits_held)` budget. Either failure produces `ERR_PARTY_SIZE_PATCH_INFEASIBLE`. On a successful patch of a `CONFIRMED` reservation, the platform recomputes `credits_held` per the provisional credit calculation, adjusts the plan's `table_service_credits_held` by the signed delta, and appends a corresponding `CreditLedgerEntry` of `entry_type` `HOLD` (positive delta) or `RELEASE` (negative delta). A patch on a `PENDING` reservation moves no credits because there are none held yet.

A confirmed reservation can be cancelled by the guest at any time before two hours prior to `slot_start_utc`: the rule is that the current UTC time must be strictly earlier than `slot_start_utc` minus two hours. Inside that two-hour window the cancel path from `CONFIRMED` is no longer available and the request is rejected with `ERR_INVALID_STATE`. Cancellation from `CONFIRMED` requires `expected_reservation_version`, runs the OCC check, reverses the hold (decrement the plan's `table_service_credits_held` by `Reservation.credits_held`, zero `Reservation.credits_held`, append a `CreditLedgerEntry` of `entry_type` `RELEASE` with a `credits_delta` equal to the negated released quantity), and cascades any `LightningLaneAddOn` for this reservation that is in `REQUESTED` or `ALLOCATED` to `CANCELLED`. Cancellation from `PENDING` is also OCC-guarded with `expected_reservation_version`, but moves no credits because none are held; it simply flips `status` to `CANCELLED` (and, harmlessly, runs the same LL-add-on cascade — though a PENDING reservation cannot carry an attached add-on, so the cascade is a no-op in practice). On either cancel path, the ordering between the `expected_reservation_version` precondition and the current-state check follows the §2.8 ladder: state compatibility (`ERR_INVALID_STATE`) is evaluated before the OCC check (`ERR_STALE_VERSION`). A non-integer `expected_reservation_version` is `ERR_INVALID_REQUEST`.

### 3.5. Check-In, Seating, Completion, and the No-Show Path

When the guest arrives at the restaurant, check-in advances the reservation from `CONFIRMED` to `CHECKED_IN`. The check-in window is `[slot_start_utc - 15 minutes, slot_end_utc]` measured in UTC — fifteen minutes of pre-slot grace, then the full slot itself — and the underlying `ParkSession` must be in `ACTIVE` `status`. A check-in attempt before the window (`now < slot_start_utc - 15min`), after the window (`now > slot_end_utc`), or with a `ParkSession` not in `ACTIVE`, is rejected with `ERR_INVALID_STATE`. On commit, the platform finalises credits: `Reservation.credits_debited` is set to the restaurant's `dining_plan_credit_cost` multiplied by the reservation's `party_size` at the moment of check-in, the plan's `table_service_credits_held` is decreased by the reservation's `credits_held`, the plan's `table_service_credits_remaining` is decreased by `credits_debited`, a `CreditLedgerEntry` of `entry_type` `DEBIT` is appended with a positive `credits_delta` equal to `credits_debited`, and `checked_in_at` is stamped. The two variants of the dining-plan credit calculation — provisional at confirm time and final at check-in time — use the same per-seat formula but differ in which `party_size` they capture: provisional uses the value at the instant of confirmation, final uses the value at the instant of check-in. If a party-size patch (§3.4) reduced the head-count between confirm and check-in, `credits_debited` will be less than `credits_held`, and the difference is exactly what the final-variant `CreditLedgerEntry` records as the actual finalised amount.

Seating is a restaurant-side action that takes a `CHECKED_IN` reservation to `SEATED`. If an `AllergyMeal` exists for this reservation and that meal is in `REQUESTED` `status`, the seat transition auto-advances the meal to `ACKNOWLEDGED` (this is the first hop of the allergy-meal cascade chain). Completion takes the reservation from `SEATED` to `COMPLETED` and runs two further cascades on commit: if an `AllergyMeal` exists and is in `PREPARED`, it auto-advances to `SERVED` (the second hop of the allergy cascade chain), and if a `LightningLaneAddOn` exists and is in `ALLOCATED` with the current time still at or before its `redemption_window_end_utc`, the add-on flips to `REDEEMED`.

If the slot end passes and the guest still has not checked in, the reservation enters the no-show path — either through an operator-driven sweep that walks every `CONFIRMED` reservation whose `slot_end_utc` is now strictly earlier than the current UTC time and transitions it to `NO_SHOW`, or through a manual restaurant-or-admin mark-no-show on a specific reservation that requires the same precondition (the slot's full grace must have elapsed; `current_utc > slot_end_utc`). Either path runs the same cascade, in this order: the platform increments the booking `Guest.no_show_strike_count` by 1, and if the post-increment count is at or above 5 the guest's `status` flips to `SUSPENDED`; it creates a `NoShowFeeAssessment` (described below); it decreases the plan's `table_service_credits_held` by the reservation's `credits_held` and appends a `CreditLedgerEntry` of `entry_type` `RELEASE` with a negative `credits_delta` equal to the released quantity (no-show releases the hold but does not debit the plan); if an `AllergyMeal` exists for the reservation and is in `REQUESTED` or `ACKNOWLEDGED`, the meal flips to `DECLINED` with `declined_reason` set to the literal string `RESERVATION_NO_SHOW`; finally `Reservation.credits_held` is zeroed and `no_show_assessed_at` is stamped with `now()`. The `NoShowFeeAssessment.assessed_at` is the same UTC instant as `Reservation.no_show_assessed_at`.

The no-show fee itself is computed at the moment of the `NO_SHOW` transition and stored on the assessment row. The inputs are the restaurant's `no_show_base_fee_cents`, the restaurant's `is_character_dining` flag, the reservation's `party_size`, and the guest's `no_show_strike_count` (with this no-show already counted — i.e., the count after the just-described increment). The platform first computes a per-seat character surcharge: 1000 cents if the restaurant is character dining, 0 otherwise. It adds this surcharge to the base per-seat fee to obtain a per-seat-pre-multiplier amount. It then selects a repeat-offender multiplier on a tiered scale: if the post-increment strike count is 1, the multiplier is 1.0; if it is 2 or 3, the multiplier is 1.075; if it is 4 or greater, the multiplier is 1.250. The platform multiplies the per-seat-pre-multiplier amount by the multiplier — this can produce a fractional-cent decimal — and rounds that single per-seat figure to integer cents using the round-half-up rule. That rounded per-seat amount is then multiplied by the integer `party_size`, with no further rounding, to obtain `total_amount_cents`. The order matters: rounding happens once per seat and the multiplication by `party_size` is pure integer arithmetic. The assessment additionally persists `base_amount_cents` equal to the per-seat base times `party_size`, `character_surcharge_cents` equal to the per-seat surcharge times `party_size`, the chosen `repeat_offender_multiplier` stored verbatim as a JSON number (the tier-1 value MAY be emitted as `1.0`, tier-2 as `1.075`, tier-3 as `1.25`/`1.250`; any JSON-numeric form whose decimal value equals the tier constant is acceptable), and `total_amount_cents` as computed above. The assessment's `assessed_at` field carries the same UTC instant as the reservation's `no_show_assessed_at`. Every assessment also carries its denormalised `reservation_id` and `guest_id`, the latter copied at write time from the reservation for query convenience.

### 3.6. Allergy Meals and Their Revert Loop

An `AllergyMeal` attaches to exactly one reservation: when a guest creates one, the request carries `reservation_id`, a non-empty `allergen_codes` array whose every entry must be one of `PEANUT`, `TREE_NUT`, `GLUTEN`, `DAIRY`, `EGG`, `SHELLFISH`, or `SOY`, and an optional `notes` free-text instruction for the chef that defaults to the empty string. A `notes` value supplied with a non-string type is rejected with `ERR_INVALID_REQUEST`. A non-list `allergen_codes`, an empty array, or any unrecognised allergen value yields `ERR_INVALID_ALLERGEN`. Only one allergy meal may exist per reservation; attempting to create a second one returns `ERR_ADDON_ALREADY_EXISTS` (the same uniqueness rule applies to Lightning Lane add-ons, see §3.7). The new meal opens in `REQUESTED` `status` with `declined_reason` null.

The meal's lifecycle is restaurant-driven from that point. The kitchen acknowledges the request, advancing `REQUESTED` to `ACKNOWLEDGED`, but this action is only valid when the underlying reservation is in `CONFIRMED`, `CHECKED_IN`, or `SEATED`. Acknowledge also fires implicitly as a cascade hop when the restaurant seats the reservation (a `CHECKED_IN`-to-`SEATED` transition will auto-acknowledge an attached meal that is still in `REQUESTED`). From `ACKNOWLEDGED` the kitchen advances to `PREPARED`, valid only while the reservation is in `SEATED`. From `PREPARED` the kitchen advances to `SERVED`, valid while the reservation is in `SEATED` or `COMPLETED`; `SERVED` also fires implicitly as the cascade hop on a `SEATED`-to-`COMPLETED` transition. The kitchen may also bounce an acknowledged meal back to `REQUESTED` — the revert loop, valid only while the reservation is in `CONFIRMED` or `CHECKED_IN` — when allergens need amending. A direct `REQUESTED`-to-`DECLINED` transition is available when the kitchen cannot accommodate the request at all; this transition requires a non-empty `reason` field in the request body (a missing, non-string, or blank `reason` is `ERR_INVALID_REQUEST`), which the platform stores on the meal's `declined_reason`. The decline transition is valid from `REQUESTED` regardless of the parent reservation's current status (no `Reservation.status` constraint is applied). Finally, a no-show on the parent reservation force-declines any meal in `REQUESTED` or `ACKNOWLEDGED` with `declined_reason` set to `RESERVATION_NO_SHOW` (see §3.5).

### 3.7. Lightning Lane Add-Ons, Pricing, and the Redemption Window

A guest may attach a `LightningLaneAddOn` to a `CONFIRMED` reservation. Creation requires `reservation_id` and a `tier` enumerator of `SINGLE_PASS` or `MULTI_PASS`; the new add-on opens in `REQUESTED` `status` with `fee_cents` 0, `allocated_at` null, and `redemption_window_end_utc` null. Only one add-on per reservation is allowed (`ERR_ADDON_ALREADY_EXISTS` on the second attempt). A guest whose `status` is `SUSPENDED` is barred from creating add-ons (`ERR_GUEST_SUSPENDED`).

The guest then allocates the add-on, advancing it from `REQUESTED` to `ALLOCATED`. Allocation requires the underlying reservation to still be in `CONFIRMED` and is OCC-guarded by `expected_reservation_version` (see §2.7); a mismatch yields `ERR_STALE_VERSION` (HTTP 412). State-compatibility checks (the add-on must be in `REQUESTED`, the parent reservation in `CONFIRMED`) are evaluated before the OCC check per the §2.8 ladder — a mismatched add-on or reservation status yields `ERR_INVALID_STATE` regardless of the version supplied. A non-integer `expected_reservation_version` is `ERR_INVALID_REQUEST`. On commit, the platform computes the fee, stamps `allocated_at` with the commit instant, sets `redemption_window_end_utc` to the reservation's `slot_end_utc` plus sixty minutes, bumps the add-on's `version`, AND additionally bumps the parent `Reservation`'s `version` (allocation is treated as a write affecting both rows, so any concurrent OCC-guarded caller observing the reservation between the read and a retry must re-fetch).

The fee calculation takes four inputs: the restaurant's `is_character_dining` flag, the restaurant's `park_code`, the add-on's `tier`, and the reservation's `party_size` at the moment of allocation. The platform looks up a per-tier base in integer cents — `SINGLE_PASS` is 1500 cents, `MULTI_PASS` is 2500 cents — and adds a per-seat character uplift of 500 cents when the restaurant is character dining, 0 otherwise. The sum is multiplied by a park-specific decimal multiplier: 1.175 at `MAGIC_KINGDOM`, 1.075 at `EPCOT`, 1.000 at `ANIMAL_KINGDOM`, and 1.100 at `HOLLYWOOD_STUDIOS`. This product is a per-seat decimal that may carry sub-cent fractions; the platform rounds it to integer cents using the round-half-up rule. That single per-seat rounded amount is then multiplied by the integer `party_size`, with no further rounding, to give the `fee_cents` stored on the add-on. As with the no-show calculation, the rounding must happen once at the per-seat boundary — rounding after the party-size multiply diverges by up to (party_size − 1) cents per booking and is the wrong order.

Once allocated, the add-on can be redeemed either explicitly through a manual redeem action (valid while the add-on is in `ALLOCATED` and the current UTC time is at or before `redemption_window_end_utc`) or implicitly as the cascade hop on the reservation's `SEATED`-to-`COMPLETED` transition. A manual redeem attempt on an add-on whose status is anything other than `ALLOCATED`, or whose `redemption_window_end_utc` has strictly passed, is rejected with `ERR_INVALID_STATE`. If neither path runs and `redemption_window_end_utc` passes while the add-on is still in `ALLOCATED`, an operator-driven expiry sweep transitions the add-on from `ALLOCATED` to `EXPIRED`. The guest may also cancel an add-on while it is still in `REQUESTED` — any cancel attempt on an add-on in any other status is rejected with `ERR_INVALID_STATE`. Once it has reached `ALLOCATED`, the cancellation path of choice is to cancel the parent reservation, which cascades the add-on to `CANCELLED` along with releasing the credit hold (see §3.4 and §3.2). The `SEATED`-to-`COMPLETED` cascade hop only flips an `ALLOCATED` add-on to `REDEEMED` when the current UTC time is still at or before `redemption_window_end_utc`; if the window has already passed, the add-on stays in `ALLOCATED` (the operator expiry sweep is the only path that produces `EXPIRED`).

### 3.8. Operator Capabilities: Clock and Sweeps

Three operator-only capabilities round out the surface. The clock-set capability accepts a single field `to_iso8601` and overwrites the platform's virtual current UTC for the entire deployment; every time-based gate in the system — window opening, slot-grid alignment, two-hour cancel cutoff, fifteen-minute check-in grace, no-show grace, Lightning Lane expiry window — reads from this virtual clock thereafter. The supplied `to_iso8601` value is normalised into the canonical §2.5 three-fractional-digit `Z` form before storage; the endpoint returns a `data` object of shape `{"current_utc": "<normalised ISO 8601 UTC>"}`. A `to_iso8601` value that cannot be parsed is `ERR_INVALID_REQUEST`. The no-show sweep capability walks every `Reservation` in `CONFIRMED` whose `slot_end_utc` is now strictly earlier than the current UTC time and runs the full `CONFIRMED`-to-`NO_SHOW` cascade on each (see §3.5), returning a `swept_count` integer and a `swept_reservation_ids` string array. The Lightning Lane expiry sweep capability walks every `LightningLaneAddOn` in `ALLOCATED` whose `redemption_window_end_utc` is now strictly earlier than the current UTC time and runs the `ALLOCATED`-to-`EXPIRED` transition on each, returning `expired_count` and `expired_addon_ids`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Endpoints that create a new persisted resource return HTTP 201 (Created); endpoints that modify or transition an existing resource, and all read endpoints, return HTTP 200 (OK). Every endpoint sits behind the §2.1 authentication and authorisation chain; the "Authorized Role(s)" column lists every role that may invoke the endpoint, subject to the ownership rules in §2.1 and §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /v1/guests | Register a guest account | PlatformAdmin |
| GET | /v1/guests/{id} | Get a guest by id | PlatformAdmin, Guest |
| POST | /v1/restaurants | Register a restaurant | PlatformAdmin |
| GET | /v1/restaurants/{id} | Get a restaurant | PlatformAdmin, Guest, Restaurant |
| GET | /v1/restaurants | List restaurants (filterable by park) | PlatformAdmin, Guest, Restaurant |
| POST | /v1/park-sessions | Create a park session for a guest on a visit date | Guest, PlatformAdmin |
| GET | /v1/park-sessions/{id} | Get a park session | PlatformAdmin, Guest |
| GET | /v1/park-sessions | List park sessions (filterable by guest) | PlatformAdmin, Guest |
| POST | /v1/park-sessions/{id}/activate | Tap-into-park transition NOT_STARTED → ACTIVE | Guest |
| POST | /v1/park-sessions/{id}/close | Close transition ACTIVE → CLOSED | Guest |
| POST | /v1/park-sessions/{id}/cancel | Cancel a NOT_STARTED session and cascade-cancel its reservations | Guest |
| POST | /v1/dining-plans | Issue a dining plan for a guest | PlatformAdmin |
| GET | /v1/dining-plans/{id} | Get a dining plan | PlatformAdmin, Guest |
| GET | /v1/dining-plans | List dining plans (filterable by guest) | PlatformAdmin, Guest |
| POST | /v1/reservations | Create a PENDING reservation | Guest |
| GET | /v1/reservations/{id} | Get a reservation | PlatformAdmin, Guest, Restaurant |
| GET | /v1/reservations | List reservations (filterable by guest, restaurant, park session, dining plan, status) | PlatformAdmin, Guest, Restaurant |
| POST | /v1/reservations/{id}/confirm | Confirm transition PENDING → CONFIRMED; holds plan credits | Guest |
| POST | /v1/reservations/{id}/cancel | Cancel transition from PENDING or CONFIRMED; OCC-guarded | Guest |
| POST | /v1/reservations/{id}/check-in | Check-in transition CONFIRMED → CHECKED_IN; finalises credit debit | Guest |
| POST | /v1/reservations/{id}/seat | Seat transition CHECKED_IN → SEATED | Restaurant |
| POST | /v1/reservations/{id}/complete | Complete transition SEATED → COMPLETED; cascades dependents | Restaurant |
| POST | /v1/reservations/{id}/mark-no-show | Manual CONFIRMED → NO_SHOW; same cascade as ops sweep | Restaurant, PlatformAdmin |
| POST | /v1/reservations/{id}/party-size | Patch party_size on a PENDING or CONFIRMED reservation | Guest |
| POST | /v1/allergy-meals | Attach an allergy meal request to a reservation | Guest |
| GET | /v1/allergy-meals/{id} | Get an allergy meal | PlatformAdmin, Guest, Restaurant |
| GET | /v1/allergy-meals | List allergy meals (filterable by reservation) | PlatformAdmin, Guest, Restaurant |
| POST | /v1/allergy-meals/{id}/acknowledge | REQUESTED → ACKNOWLEDGED | Restaurant |
| POST | /v1/allergy-meals/{id}/prepare | ACKNOWLEDGED → PREPARED | Restaurant |
| POST | /v1/allergy-meals/{id}/serve | PREPARED → SERVED | Restaurant |
| POST | /v1/allergy-meals/{id}/revert-to-requested | ACKNOWLEDGED → REQUESTED (revert loop) | Restaurant |
| POST | /v1/allergy-meals/{id}/decline | REQUESTED → DECLINED with reason | Restaurant |
| POST | /v1/lightning-lane-addons | Request a Lightning Lane add-on for a reservation | Guest |
| GET | /v1/lightning-lane-addons/{id} | Get an add-on | PlatformAdmin, Guest |
| GET | /v1/lightning-lane-addons | List add-ons (filterable by reservation) | PlatformAdmin, Guest |
| POST | /v1/lightning-lane-addons/{id}/allocate | REQUESTED → ALLOCATED; computes fee; OCC-guarded on reservation version | Guest |
| POST | /v1/lightning-lane-addons/{id}/redeem | ALLOCATED → REDEEMED (manual; auto on reservation complete) | Guest, Restaurant |
| POST | /v1/lightning-lane-addons/{id}/cancel | REQUESTED → CANCELLED | Guest |
| GET | /v1/no-show-fee-assessments/{id} | Get a single no-show fee assessment | PlatformAdmin, Guest |
| GET | /v1/no-show-fee-assessments | List no-show fee assessments (filterable by guest or reservation) | PlatformAdmin, Guest |
| GET | /v1/credit-ledger-entries/{id} | Get a single credit ledger entry | PlatformAdmin, Guest |
| GET | /v1/credit-ledger-entries | List credit ledger entries (filterable by dining plan or reservation) | PlatformAdmin, Guest |
| POST | /v1/_clock/set_current_utc | Set the platform's virtual current UTC for testing | PlatformAdmin |
| POST | /v1/_ops/no-show-sweep | Run the no-show sweep across CONFIRMED reservations | PlatformAdmin |
| POST | /v1/_ops/lightning-lane-expiry-sweep | Expire ALLOCATED add-ons whose redemption window has passed | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_GUEST_SUSPENDED | 403 |
| ERR_INVALID_ALLERGEN | 422 |
| ERR_OUTSIDE_BOOKING_WINDOW | 422 |
| ERR_PAST_DINING_DATE | 422 |
| ERR_SLOT_OUTSIDE_HOURS | 422 |
| ERR_SLOT_MISALIGNED | 422 |
| ERR_SLOT_CAPACITY_EXCEEDED | 409 |
| ERR_GUEST_DOUBLE_BOOKING | 409 |
| ERR_PARK_SESSION_MISMATCH | 409 |
| ERR_INSUFFICIENT_CREDITS | 422 |
| ERR_PLAN_NOT_COVERING | 409 |
| ERR_ADDON_ALREADY_EXISTS | 409 |
| ERR_PARTY_SIZE_PATCH_INFEASIBLE | 422 |
| ERR_INVALID_REQUEST | 400 |

# Dog Walking & Pet Boarding API — Product Requirements Document

## 1. Introduction

The Dog Walking & Pet Boarding Platform is a two-sided marketplace where pet owners book dog walks, daycare, and overnight boarding with vetted independent sitters. Owners need to know that the person entering their home and handling their pet has passed a background check, that the price they were quoted is the price they pay, and that something covers them when an incident happens on a walk. Sitters need a predictable payout pipeline, a calendar that does not double-book them, and a tier system that rewards consistent, claim-free work rather than punishing them for one off-day.

This document defines the REST API that supports the full marketplace lifecycle: account onboarding for owners and sitters, background-check disposition, pet and emergency-contact records, the Meet & Greet vetting step, recurring and one-off bookings, key handoff and GPS tracking during service, the rating-and-payout settlement at completion, and the insurance-claim workflow when something goes wrong. Several flows are deeply interconnected — a single background-check flag can cascade through a sitter's calendar and refund a handful of owners; a paid insurance claim can quietly demote a sitter's tier and reprice every upcoming booking on their calendar. The specification is written from a product-manager perspective and is the single contract between the platform team and any client integrator.

All endpoints described below are mounted under the `/api/v1` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the two public registration endpoints (owner registration and sitter registration) must carry two headers:

- `X-User-ID` — identifies the caller.
- `X-User-Role` — identifies the caller's role.

If either header is missing or empty on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is present but is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are defined:

- **`Anonymous`** — the unauthenticated caller. This role exists only to invoke the two public registration endpoints (owner registration and sitter registration). `X-User-ID` for an `Anonymous` caller is an opaque, unverified identifier; the server does not associate it with any persisted entity.
- **`Owner`** — a pet owner who books services. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` row; ownership checks on any resource that references an `Owner` (a `Pet`, an `EmergencyContact`, a `MeetAndGreet`, a `Booking`, an `InsuranceClaim`) compare that resource's `owner_id` to `X-User-ID`.
- **`Sitter`** — the service provider. When `X-User-Role` is `Sitter`, `X-User-ID` is the `id` of the acting `Sitter` row; ownership checks on a `Booking`, a `KeyHandoff`, a `GpsTrack`, or a `MeetAndGreet` reference the resource's `sitter_id` against `X-User-ID`.
- **`PlatformAdmin`** — the operations role responsible for background-check dispositions, sitter lifecycle administration, the no-show timer on Meet & Greets, and the test-driving clock. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.
- **`ClaimsAdjuster`** — the insurance role that reviews, approves, denies, reverts, and pays insurance claims. `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

The §4 endpoint table lists the authorized role(s) for every operation.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100; `offset` defaults to 0 and must be a non-negative integer. List results are ordered by `created_at` in ascending order, so older records appear first and the same `offset` returns the same page across repeated requests. The pagination block in `meta` exposes the four pagination fields `limit`, `offset`, `total_count` (the total number of records that satisfy the request's filters, irrespective of pagination), and `has_more` (a boolean that is true exactly when `offset + limit < total_count`).

### 2.4. Common Resource Properties

Every persisted resource carries an `id`, which is a server-minted UUID. The `id` is the raw UUID string with no entity-type prefix, and the server is the sole authority for generating it. The `created_at` timestamp is set at creation time and is an ISO 8601 UTC timestamp with three fractional digits; it never changes after the row is created.

Most resources also carry an `updated_at` timestamp (refreshed on any state-changing write) and an integer `version` field that starts at 1 on creation and increments by exactly 1 on every mutation that changes the row. These two fields are present on `Owner`, `Sitter`, `BackgroundCheck`, `Pet`, `EmergencyContact`, `MeetAndGreet`, `Booking`, `KeyHandoff`, and `InsuranceClaim`. One entity is intentionally append-only: `GpsTrack` rows are written once and never modified, so `GpsTrack` carries only `id` and `created_at` — both `updated_at` and `version` are absent.

### 2.5. Hierarchical Consistency and Cascading Side Effects

The platform's most consequential write paths cross entity boundaries. Two named cascades govern the platform's behaviour and are referenced by name throughout §3:

- **Cascade #1 — Background-check flag.** Flagging a pending background check propagates through the sitter onboarding state to active bookings to owner wallets, four layers deep: the flagged `BackgroundCheck` row records the adjuster-supplied `flagged_reason`; the sitter is suspended; every booking on that sitter's calendar that is not yet underway is auto-cancelled with `cancellation_reason` `AUTO_SITTER_SUSPENDED`; and every affected owner's wallet credit is refilled by the full cancelled `booking_quote_cents` (the previously-applied wallet credit is restored on top of the booking principal).
- **Cascade #2 — Insurance claim paid.** Paying out an approved insurance claim increments the sitter's `claim_count`, which recomputes the sitter's tier; if the tier drops, every upcoming booking on that sitter's calendar (those still in `REQUESTED` or `CONFIRMED` status) is re-quoted at the new tier and any provisional payout is adjusted by the delta; if the sitter's `claim_count` crosses the value 2 while the sitter is `ACTIVE`, the sitter is also moved to `SUSPENDED` for safety review.

Whenever a cascade touches a row, that row's `version` increments by 1 and its `updated_at` is refreshed. Cascade-induced version bumps are indistinguishable from explicit writes from the client's perspective — they are the source of stale-version conditions that §2.6 catches.

### 2.6. Optimistic Concurrency Control

Cancelling a confirmed booking is the only operation that takes an explicit optimistic-concurrency token. The cancel request body must include `expected_booking_version` carrying the client's last observed `version` of the target booking. If that value does not match the booking's current `version` at the moment the server processes the request, the cancel is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection is not about two requests racing in real time — it catches the case where a cascade has silently advanced `Booking.version` between the client's last read and this cancel (for example, Cascade #1 auto-cancelling the booking already, or Cascade #2 re-quoting it after a tier drop). A request that does not carry `expected_booking_version` is also rejected when the booking is in the `CONFIRMED` state; cancelling a booking from the `REQUESTED` state does not require the field, because no cascade can have changed it. No other endpoint takes a version field.

### 2.7. Path Resolution and Foreign-Key Validation

Every endpoint with a path parameter resolves the path left-to-right against the entity hierarchy in the URL. The path `/bookings/{id}` first looks up the booking by its `id`; if no row exists, the response is `ERR_NOT_FOUND` (HTTP 404). The same principle applies to every other `{id}` segment across the API. Foreign keys passed in a `POST` request body — `owner_id`, `sitter_id`, `pet_id`, `booking_id` — are validated against their parent tables; a non-existent reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). Request bodies that violate the basic shape contract — missing a required field, supplying the wrong type, an enum value outside the declared set, or a negative integer where a non-negative integer is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Validation Priority Order

When more than one validation rule could fire for a single request, the server evaluates them in a fixed priority order so that error responses are deterministic. The order is, from highest priority to lowest: (1) authentication header presence (`ERR_UNAUTHENTICATED`), (2) role authorization (`ERR_FORBIDDEN`), (3) path entity existence (`ERR_NOT_FOUND`), (4) request-body foreign-key existence (`ERR_FK_NOT_FOUND`), (5) state-machine precondition (`ERR_INVALID_STATE`), (6) optimistic-concurrency token (`ERR_STALE_VERSION`), (7) sitter background-check clearance (`ERR_SITTER_NOT_CLEARED`), (8) Meet & Greet completion + sitter availability (`ERR_MEET_AND_GREET_REQUIRED`), (9) pet-owner referential consistency (`ERR_PET_OWNER_MISMATCH`), (10) sitter calendar overlap (`ERR_SITTER_TIME_CONFLICT`), (11) pet calendar overlap (`ERR_PET_TIME_CONFLICT`), (12) primary emergency contact uniqueness (`ERR_PRIMARY_CONTACT_EXISTS`), (13) per-sitter background-check uniqueness (`ERR_BG_CHECK_EXISTS`), (14) per-booking key-handoff uniqueness (`ERR_KEY_HANDOFF_EXISTS`), (15) wallet credit sufficiency (`ERR_WALLET_INSUFFICIENT`), (16) insurance approved-amount bounds (`ERR_INVALID_APPROVED_AMOUNT`), (17) GPS-track booking-status guard (`ERR_GPS_BOOKING_NOT_IN_PROGRESS`), (18) request-body shape (`ERR_INVALID_REQUEST`). The first rule to fire is the one whose `error_id` is returned; lower-priority rules do not run.

### 2.9. Monetary Precision and Rounding

All money on the platform is denominated in integer cents — no floating-point currency anywhere. Wherever a calculation introduces a non-integer intermediate (a tier multiplier, a time-of-day factor, a recurring discount, a platform-fee percentage), the result is rounded to the nearest cent with the half-up convention (a value ending in exactly 0.5 rounds away from zero). The `booking_quote` formula performs three named rounding operations and the `sitter_payout` formula performs one; the exact rounding points are described in §3 alongside the formulas they govern.

### 2.10. Time Semantics and the Test-Driving Clock

Every timestamp on the platform is ISO 8601 in UTC with three fractional digits of precision. Several state transitions are time-gated — a booking cannot start before its scheduled `start_at`, a Meet & Greet cannot be marked no-show until enough time has elapsed since its `scheduled_at`, a sitter cannot complete a booking until its `end_at` has passed. To make these transitions exercisable deterministically, the platform exposes an admin-only test-driving capability that pins the server's notion of "now" to a supplied instant; the request body carries the target instant as `to_iso8601`. After the call, every subsequent read of the server clock returns the pinned value until the capability is invoked again. This capability is restricted to the `PlatformAdmin` role.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Owners, Sitters, Pets, and Emergency Contacts

A prospective pet owner self-registers by submitting `email`, `full_name`, and `phone` to the owner registration endpoint. The submitted `email` must be unique across owners and non-empty, the `phone` is captured in E.164 form, and the new `Owner` row starts with `wallet_credit_cents` of 0. The `wallet_credit_cents` field is the refund-credit balance: it is debited when applied to a booking and credited back when a booking is cancelled with a wallet refund destination, and it must never go negative.

After registration, an owner records the pets they want serviced. Each `Pet` row carries the owning `owner_id`, a `name`, a `species` (one of `DOG` or `CAT`), a strictly positive `weight_kg`, and free-text `medical_notes` (defaulting to the empty string). The owner also records emergency contacts. Each `EmergencyContact` has its own `owner_id`, a `full_name` and `phone` for the contact, a `relationship` label drawn from `SPOUSE`, `PARENT`, `FRIEND`, `VET`, `NEIGHBOR`, or `OTHER`, and an integer `priority` between 1 and 3 (1 is primary, 2 is secondary, 3 is tertiary). At most one emergency contact per owner may have `priority` of 1; attempting to create a second primary contact for the same owner is rejected with `ERR_PRIMARY_CONTACT_EXISTS`.

A prospective sitter self-registers symmetrically — `email`, `full_name`, `phone` — and the new `Sitter` row is created in the `APPLIED` status with `tier` `BRONZE`, `tier_score` 10, and zero counters for `total_completed_bookings`, `total_rating_sum`, `total_rating_count`, `claim_count`, and `pending_payout_cents`. `suspended_at` is null. The sitter cannot yet be booked.

### 3.2. Background Check Disposition and the Sitter Onboarding State Machine

Onboarding a sitter to bookable status runs through a single background-check entity per sitter. A `PlatformAdmin` operator creates the `BackgroundCheck` row by supplying the `sitter_id` and the `provider` (one of `CHECKR`, `ACCURATE`, or `FIRST_ADVANTAGE`); the check is created in `PENDING` status. Creating the row also advances the sitter from `APPLIED` to `BG_CHECK_PENDING` and bumps the sitter's `version`. Exactly one background check may exist per sitter; a second create attempt is rejected with `ERR_BG_CHECK_EXISTS`, and a create attempt is only valid when the sitter is in `APPLIED` and no prior `BackgroundCheck` exists.

The check resolves in one of two ways. The cleared disposition advances the `BackgroundCheck` from `PENDING` to `CLEARED`, stamps `cleared_at` with the current server clock, and as a side effect advances the associated sitter from `BG_CHECK_PENDING` to `ACTIVE` (bumping `Sitter.version`). The flagged disposition is more consequential: it requires a non-empty `flagged_reason`, advances the `BackgroundCheck` from `PENDING` to `FLAGGED`, records the supplied `flagged_reason` on the row, and originates Cascade #1. Cascade #1 propagates as follows: the sitter (whether currently `BG_CHECK_PENDING` or `ACTIVE`) is moved to `SUSPENDED`, `Sitter.suspended_at` is stamped with the current clock, and `Sitter.version` increments. Every `Booking` whose `sitter_id` is this sitter and whose `status` is one of `REQUESTED`, `CONFIRMED`, or `KEY_RECEIVED` is auto-cancelled — its `status` is set to `CANCELLED`, its `cancellation_reason` is set to the literal string `AUTO_SITTER_SUSPENDED`, and its `version` is bumped. For each such auto-cancelled booking, the owner's `wallet_credit_cents` is increased by the booking's `booking_quote_cents` minus its `wallet_credit_applied_cents` (the refund of the unpaid principal) and then increased again by `wallet_credit_applied_cents` (the restoration of the credit that had been applied) — the net effect is that the owner's wallet is credited by the full `booking_quote_cents`, and `Owner.version` increments. For every `CONFIRMED` booking caught in the cascade, the sitter's `pending_payout_cents` is reduced by that booking's `provisional_sitter_payout_cents` because the reservation no longer holds.

A `PlatformAdmin` may also reinstate a suspended sitter back to `ACTIVE`, which is the only cyclic edge in the sitter state machine: reinstating clears `Sitter.suspended_at` to null and bumps `Sitter.version`. The sitter state machine also has two paths to its terminal `DEACTIVATED` state: deactivation from `ACTIVE` is allowed only when the sitter has no booking with `status` in `REQUESTED`, `CONFIRMED`, `KEY_RECEIVED`, or `IN_PROGRESS`, while deactivation from `SUSPENDED` is unconditional. Both bump `Sitter.version`. Triggering a state transition on a sitter that is not in the prescribed source state is rejected with `ERR_INVALID_STATE`.

### 3.3. Meet & Greet: The Required Vetting Step

Before an owner can book a sitter, the platform requires a successful in-person Meet & Greet between the owner, the pet, and the sitter for that specific combination. An owner schedules a Meet & Greet by submitting `owner_id`, `sitter_id`, `pet_id`, `scheduled_at`, and optional `notes`. At creation, the chosen sitter must have a `CLEARED` background check — otherwise the request is rejected with `ERR_SITTER_NOT_CLEARED`. The new `MeetAndGreet` is created in `SCHEDULED` status with `decided_at` null and the supplied `notes` (defaulting to the empty string when omitted).

A scheduled Meet & Greet has four possible terminal dispositions and the deciding endpoint stamps the row's `decided_at` with the server clock and bumps the row's `version` on every transition. The owner may approve the Meet & Greet, transitioning `SCHEDULED → COMPLETED_APPROVED`; this transition is only valid when the Meet & Greet's `scheduled_at` is at or before the current server clock and the chosen sitter's `status` is `ACTIVE`. Approval optionally records `notes` on the deciding transition. The owner may decline the Meet & Greet (`SCHEDULED → COMPLETED_DECLINED`), and the owner may cancel a scheduled Meet & Greet outright (`SCHEDULED → CANCELLED`); both decline and cancel may carry `notes`. Only a `PlatformAdmin` may mark a no-show, transitioning `SCHEDULED → NO_SHOW`, and the operation is gated on the server clock being at least 60 minutes past the Meet & Greet's `scheduled_at`. Any attempt to transition from a non-`SCHEDULED` source state is rejected with `ERR_INVALID_STATE`.

### 3.4. Booking Creation and the Quote Calculation

With at least one `COMPLETED_APPROVED` Meet & Greet on file for the (owner, sitter, pet) tuple, the owner may create a booking. The request body carries `owner_id`, `sitter_id`, `pet_id`, the `service_type` (one of `WALK_30MIN`, `WALK_60MIN`, `BOARDING_OVERNIGHT`, or `DAYCARE`), the `time_of_day` bucket (one of `STANDARD`, `PEAK`, or `OVERNIGHT`), an optional `recurring_cadence` (one of `NONE`, `WEEKLY`, or `BIWEEKLY`, defaulting to `NONE`), the half-open service window as `start_at` (inclusive) and `end_at` (exclusive, with `end_at` strictly after `start_at`), an optional `emergency_surcharge_cents` (a non-negative integer defaulting to 0), and an optional `wallet_credit_applied_cents` to draw down on the owner's refund balance. Creation rejection precedence: if the Meet & Greet prerequisite is unmet or the sitter is not `ACTIVE`, the response is `ERR_MEET_AND_GREET_REQUIRED`; if the supplied `pet_id`'s owner does not match the supplied `owner_id`, the response is `ERR_PET_OWNER_MISMATCH` — an owner cannot book another owner's pet. Two calendar checks then run. The sitter calendar check rejects with `ERR_SITTER_TIME_CONFLICT` when any existing booking for the same sitter that is not in `COMPLETED`, `CANCELLED`, `REJECTED`, or `EMERGENCY_TERMINATED` has a half-open interval running from its `start_at` through its `end_at` plus 30 minutes of trailing travel buffer that overlaps the proposed half-open interval from `start_at` to `end_at`. The pet calendar check rejects with `ERR_PET_TIME_CONFLICT` when any existing booking for the same pet that is not in those four terminal states has a closed interval from its `start_at` to its `end_at` that inclusively intersects the proposed closed `[start_at, end_at]` — the pet must be in at most one active booking at any instant, with no buffer. The two overlap rules are deliberately different: sitter overlap is half-open and adds 30 minutes of travel time on the trailing edge, while pet overlap is closed-inclusive and uses no buffer.

The wallet credit guard, `ERR_WALLET_INSUFFICIENT`, fires when the supplied `wallet_credit_applied_cents` exceeds either the owner's current `wallet_credit_cents` (cannot apply more credit than the balance) or the just-computed `booking_quote_cents` (cannot apply more credit than the quote itself).

The quote is the booking's `booking_quote_cents` and is produced by the `booking_quote` calculation, which uses four constant tables — a base-rate-by-service table, a tier multiplier, a time-of-day factor, and a recurring-cadence discount — and three named rounding operations. The base rate, in cents, is `2000` for `WALK_30MIN`, `3500` for `WALK_60MIN`, `8000` for `BOARDING_OVERNIGHT`, and `5000` for `DAYCARE`. The tier multiplier is `1.00` for `BRONZE`, `1.15` for `SILVER`, and `1.30` for `GOLD`, snapshotted from the sitter's current `tier` at compute time. The time-of-day factor is `1.00` for `STANDARD`, `1.20` for `PEAK`, and `1.30` for `OVERNIGHT`. The recurring discount is `0.00` for `NONE`, `0.10` for `WEEKLY`, and `0.05` for `BIWEEKLY` — note that `BIWEEKLY` carries a smaller discount than `WEEKLY` because every-other-week recurrence is less valuable to the platform than weekly recurrence. The calculation proceeds in this exact order: first, the base rate in cents is multiplied by the tier multiplier and rounded half-up to the nearest cent to produce the first intermediate; second, that intermediate is multiplied by the time-of-day factor and rounded half-up to the nearest cent to produce the second intermediate; third, the discount amount in cents is the second intermediate multiplied by the recurring discount rate and rounded half-up to the nearest cent; finally, the booking's `booking_quote_cents` is the second intermediate minus the discount amount, plus the caller-supplied `emergency_surcharge_cents`. The three rounding points are essential — applying a single round at the end yields different integer cents than the pinned three-round sequence.

On a successful create, the booking is persisted with `status` `REQUESTED`, `booking_quote_cents` set to the computed quote, `provisional_sitter_payout_cents` and `final_sitter_payout_cents` initialised to 0, `tip_cents` and `incident_deduction_cents` initialised to 0, `owner_rating` initialised to null, and `cancellation_reason` initialised to null. When `wallet_credit_applied_cents` is greater than zero, the owner's `wallet_credit_cents` is debited by that amount and `Owner.version` is incremented.

### 3.5. The Booking Lifecycle, Key Handoff, and Live Service

A newly created booking sits in `REQUESTED` awaiting the sitter's decision. The sitter has two terminal first moves and one accepting move. Rejecting a booking advances it from `REQUESTED` to `REJECTED`, records the supplied `reason` as the booking's `cancellation_reason`, and restores the previously-applied wallet credit to the owner — `Owner.wallet_credit_cents` is increased by `Booking.wallet_credit_applied_cents` and `Owner.version` is bumped. Cancelling from the requested side (by the owner) follows the same compensation path: `cancellation_reason` is the supplied `reason`, the previously-applied wallet credit is restored, and `Owner.version` increments; this cancellation requires no version field because no cascade can have advanced the booking yet.

Confirming the booking advances it from `REQUESTED` to `CONFIRMED` and is only allowed when the sitter's `status` is `ACTIVE`, the sitter's background check is `CLEARED`, a `COMPLETED_APPROVED` Meet & Greet exists for the (owner, sitter, pet) tuple, and the booking's `start_at` is still in the future relative to the server clock; the same `ERR_SITTER_NOT_CLEARED` and `ERR_MEET_AND_GREET_REQUIRED` guards that protect Meet & Greet creation and Booking creation are re-checked at confirmation, and `ERR_INVALID_STATE` covers the start-time and source-state checks. Confirming also computes the booking's `provisional_sitter_payout_cents` via the provisional variant of the `sitter_payout` calculation (described below) and accumulates it into the sitter's `pending_payout_cents`, bumping `Sitter.version`.

A booking in `CONFIRMED` may still be cancelled by the owner, but this is the optimistic-concurrency path. The cancel request must carry `reason` and `expected_booking_version` matching the booking's current `version`; on a mismatch the response is `ERR_STALE_VERSION` (HTTP 412). On a successful confirmed-side cancel the booking's `status` becomes `CANCELLED`, `cancellation_reason` is recorded, `Booking.version` increments, the sitter's `pending_payout_cents` is decreased by the booking's `provisional_sitter_payout_cents` (reservation reversed) and `Sitter.version` bumps, and the owner is made whole: `Owner.wallet_credit_cents` is increased by `booking_quote_cents` minus `wallet_credit_applied_cents` (the principal refund as wallet credit) and then by `wallet_credit_applied_cents` (the previously-applied credit restored), so the net effect is that the owner's wallet is credited by the full `booking_quote_cents`. `Owner.version` increments.

Between confirmation and service start, the parties arrange physical access to the home. The owner creates exactly one key-handoff record per booking: the request carries the `booking_id`, the `method` (one of `LOCKBOX`, `IN_PERSON`, or `SMART_LOCK`), and an optional `lockbox_code` (used only when `method` is `LOCKBOX`; null otherwise). The new `KeyHandoff` is created in `PENDING` status with `received_at` null. The `status` field on `KeyHandoff` is drawn from the set `PENDING`, `RECEIVED`, `RETURNED`, and `LOST`. A second handoff create for the same booking is rejected with `ERR_KEY_HANDOFF_EXISTS`. When the sitter arrives to collect the key, marking the handoff received advances the `KeyHandoff` from `PENDING` to `RECEIVED`, stamps the handoff's `received_at` with the server clock, and in the same call advances the booking from `CONFIRMED` to `KEY_RECEIVED`. Both rows have their `version` bumped.

Starting the service is gated on the server clock having reached the booking's `start_at`: the sitter call advances the booking from `KEY_RECEIVED` to `IN_PROGRESS` only when `system_clock` is at or after `start_at`. During an `IN_PROGRESS` booking, the sitter may append GPS samples one at a time; each sample carries the `booking_id`, a `latitude` between -90 and 90 in decimal degrees, a `longitude` between -180 and 180 in decimal degrees, and the `recorded_at` instant of the sample. A GPS write is rejected with `ERR_GPS_BOOKING_NOT_IN_PROGRESS` (HTTP 409) when the named booking's `status` is anything other than `IN_PROGRESS`. GPS-track rows are append-only — once written they are never modified — so they carry only `id` and `created_at`, no `updated_at` and no `version`.

### 3.6. Completion, Settlement, and the Sitter Payout Calculation

The sitter completes the service only after `system_clock` reaches the booking's `end_at`; the call advances the booking from `IN_PROGRESS` to `COMPLETED`, flips the existing key handoff from `RECEIVED` to `RETURNED` (and bumps `KeyHandoff.version`), and accepts three optional inputs on the body: a non-negative `tip_cents`, a non-negative `incident_deduction_cents` (used when a late return or other minor issue justifies a reduction), and an `owner_rating` between 1 and 5 inclusive (or null when the owner declined to rate). The booking row records these inputs, computes the final variant of `sitter_payout` to set `final_sitter_payout_cents`, and increments `Booking.version`.

Settlement on the sitter is the most arithmetically dense moment in the system. The sitter's `pending_payout_cents` is decreased by the booking's `provisional_sitter_payout_cents` (releasing the reservation) and then increased by the booking's `final_sitter_payout_cents` (the released, completed payout — kept in the same accumulator for invariant tracking even though it is conceptually out of the pending bucket). The sitter's `total_completed_bookings` increases by 1. When `owner_rating` is not null, the rating is folded into the sitter's running average by adding it to `total_rating_sum` and incrementing `total_rating_count` by 1; when `owner_rating` is null, the rating counters are untouched. The change to any of the four counters that feed the tier score (`total_completed_bookings`, `total_rating_sum`, `total_rating_count`, `claim_count`) triggers a `sitter_tier_score` recompute. `Sitter.version` is bumped at the end.

The `sitter_payout` calculation has two variants. Both share the platform-fee derivation: `platform_fee_cents` is the booking's `booking_quote_cents` multiplied by the platform-fee rate of `0.15` and rounded half-up to the nearest cent. The provisional variant — fired at confirmation, when tip and incident inputs are not yet known — sets `provisional_sitter_payout_cents` to `booking_quote_cents` minus `platform_fee_cents`. The final variant — fired at completion — adds `tip_cents`, subtracts `incident_deduction_cents`, and floors the result at zero: `final_sitter_payout_cents` is the maximum of zero and the quantity (`booking_quote_cents` minus `platform_fee_cents`) plus `tip_cents` minus `incident_deduction_cents`. The two variants may diverge in either direction — a generous tip raises the final payout above the provisional, while a significant incident deduction may drop it below, possibly to zero. The single rounding point is on `platform_fee_cents`; the rest of the arithmetic is integer-only.

If service goes wrong mid-stream, the sitter emergency-terminates the booking, advancing it from `IN_PROGRESS` to `EMERGENCY_TERMINATED` with a supplied `reason` recorded as `cancellation_reason`. Emergency termination explicitly pays out nothing: `final_sitter_payout_cents` is set to 0, and the sitter's `pending_payout_cents` is decreased by `provisional_sitter_payout_cents` to reverse the reservation. `Booking.version` and `Sitter.version` are bumped.

### 3.7. The Sitter Tier Calculation

The `sitter_tier_score` calculation recomputes the sitter's `tier_score` and derived `tier` whenever any of the sitter's running counters change — that is, on the side effects of booking completion and on the side effects of insurance-claim payout. The calculation has three named constants for component weights and an additive base — the rating weight is `0.5`, the bookings weight is `0.3`, and the additive base is `10` — plus a claim-penalty schedule with a per-claim penalty of `15` capped at a cumulative `45`, a bookings-count cap of `40`, and two tier thresholds: `40` (the minimum score to reach `SILVER`) and `70` (the minimum score to reach `GOLD`).

The rating component is derived as follows. When `total_rating_count` is zero, the rating component is the neutral default of `60` (representing roughly a 3-star average on the 0-to-100 scale used here). Otherwise, the floating-point average rating is `total_rating_sum` divided by `total_rating_count`, that average is multiplied by `20` to project the 1-to-5 rating into the 0-to-100 score range, and the result is rounded half-up to an integer — this is the first pinned round. The bookings component is the minimum of the sitter's `total_completed_bookings` and the bookings cap of `40` (so additional completions beyond 40 stop adding to the score). The claim penalty is the minimum of `claim_count` times `15` and the cap of `45` (so a fourth or fifth paid claim does not deepen the penalty beyond a third claim's contribution).

The components are combined as follows. The weighted sum is the rating component times the rating weight (`0.5`), plus the bookings component times the bookings weight (`0.3`), plus the additive base of `10`. The weighted sum is rounded half-up to an integer — this is the second pinned round. The penalty is then subtracted, and the final `tier_score` is the maximum of zero and that difference. The order matters: rating component is rounded before being weighted, the weighted sum is rounded before the penalty is subtracted, and applying a single round at the very end produces a different integer than the two-round sequence specified here. The derived `tier` is `GOLD` when `tier_score` is at least `70`, `SILVER` when `tier_score` is at least `40` and below `70`, and `BRONZE` otherwise. A `PlatformAdmin` may also force an idempotent recompute on a sitter directly; the recompute call only bumps `Sitter.version` when the recomputation actually changes `tier_score` or `tier`.

### 3.8. Insurance Claims, the Claim Payout Calculation, and Cascade #2

When an incident occurs on a booking, the owner files an insurance claim against that booking. The claim filing requires the `booking_id` and a strictly positive `claim_amount_cents`, with optional `adjuster_notes` at intake. The targeted booking's `status` must be `IN_PROGRESS`, `COMPLETED`, or `EMERGENCY_TERMINATED` — claims filed against bookings in any other status are rejected with `ERR_INVALID_STATE`. The new `InsuranceClaim` is created in `SUBMITTED` status with two pinned snapshots: `sitter_id_snapshot` is copied from the booking's `sitter_id`, and `sitter_tier_snapshot` is copied from the current `tier` of that sitter. These snapshots are pinned at submit time so that later cascades that change the sitter's tier do not retroactively change the claim's deductible bracket. The claim's `provisional_payout_cents` is computed via the provisional variant of `claim_payout`. `approved_amount_cents` is null, `final_payout_cents` is 0, `adjuster_notes` defaults to the empty string when omitted at intake, and `denied_reason` is null.

The `claim_payout` calculation uses a tier-keyed deductible table — `10000` cents for `BRONZE`, `5000` cents for `SILVER`, `2500` cents for `GOLD` — and a single platform-wide maximum payout of `500000` cents. The provisional variant uses the owner-declared `claim_amount_cents`; the final variant uses the adjuster-set `approved_amount_cents`. In both variants the formula is the same: first take the minimum of the relevant amount and the maximum payout of `500000` (so a runaway claim is capped at the platform limit), then subtract the tier-specific deductible from the constants table (keyed on `sitter_tier_snapshot`, not the current `Sitter.tier`), then take the maximum of zero and that difference. Because adjusters may only reduce the owner-declared amount and never increase it, the final claim payout is always less than or equal to the provisional payout. All arithmetic is on integer cents — no rounding is required.

A `ClaimsAdjuster` walks the claim through review. Starting review advances `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW`, the adjuster may approve, deny, or — only after approval — revert. Approval advances `UNDER_REVIEW → APPROVED`, requires the request body to carry `approved_amount_cents` strictly greater than zero and at most the claim's `claim_amount_cents` (otherwise `ERR_INVALID_APPROVED_AMOUNT`), records `approved_amount_cents` on the row, optionally records `adjuster_notes`, and computes the final variant of `claim_payout` into `final_payout_cents`. Reverting an approved claim advances `APPROVED → UNDER_REVIEW`, clears `approved_amount_cents` back to null, and resets `final_payout_cents` to 0 — this is the cyclic edge on the insurance-claim state machine. Denial advances `UNDER_REVIEW → DENIED` and requires a non-empty `denied_reason`, which is recorded on the row alongside any supplied `adjuster_notes`. The owner may also withdraw a still-submitted claim, advancing `SUBMITTED → WITHDRAWN`; later states cannot be withdrawn.

Paying out an approved claim is the operation that originates Cascade #2: it advances `APPROVED → PAID` and then propagates as follows. The sitter identified by the pinned `sitter_id_snapshot` has their `claim_count` incremented by 1 and `Sitter.version` bumped; the increment triggers a `sitter_tier_score` recompute. If the recompute drops the sitter's `tier` (the new computed tier is strictly worse than the existing one — `GOLD` to `SILVER` or `BRONZE`, or `SILVER` to `BRONZE`), every booking on that sitter's calendar whose `status` is `REQUESTED` or `CONFIRMED` has its `booking_quote_cents` recomputed via the `booking_quote` formula using the new (worse) tier, and for any `CONFIRMED` such booking the `provisional_sitter_payout_cents` is also recomputed via the provisional `sitter_payout`; the sitter's `pending_payout_cents` is adjusted by the delta on each re-quoted confirmed booking, and each such booking's `version` increments. Finally, if the increment of `claim_count` causes it to cross the value 2 (i.e. `claim_count` becomes greater than or equal to 2) while the sitter's `status` is `ACTIVE`, the sitter is moved to `SUSPENDED` per the sitter state machine, `Sitter.suspended_at` is stamped, and `Sitter.version` bumps again. Cascade #2 is the second source of stale-version conditions on `Booking`: a confirmed-side cancel that races the cascade will catch the silent `version` bump and surface `ERR_STALE_VERSION`.

Any attempt to drive the insurance-claim state machine from a non-permitted source state is rejected with `ERR_INVALID_STATE`. The two cleared safety bands — `ERR_SITTER_NOT_CLEARED` (priority 7) and `ERR_MEET_AND_GREET_REQUIRED` (priority 8) — apply at both Meet & Greet creation and Booking confirmation in the case of the former, and at both Booking creation and Booking confirmation in the case of the latter; the second-pass check at confirmation guards against the sitter being suspended between booking creation and the sitter's confirmation moment.

## 4. Endpoint Definitions

Every endpoint described in §3 is listed below. The platform follows two status-code conventions across the table: an endpoint that brings a wholly new resource into existence returns `201 Created`, while an endpoint that modifies, transitions, or retrieves an existing resource returns `200 OK`. Error responses use the HTTP status codes listed in §5. The table is intentionally minimal — it does not enumerate request or response bodies. Refer back to §3 for the inputs each endpoint accepts and the side effects it produces.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/v1/owners/register` | Create a new Owner account. | `Anonymous` |
| GET | `/api/v1/owners/{id}` | Retrieve an Owner by id. | `Owner`, `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/owners` | List Owners with pagination. | `PlatformAdmin` |
| POST | `/api/v1/sitters/register` | Create a new Sitter account in `APPLIED` state. | `Anonymous` |
| GET | `/api/v1/sitters/{id}` | Retrieve a Sitter by id. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/sitters` | List Sitters with optional `status` and `tier` filters. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| POST | `/api/v1/sitters/{id}/reinstate` | Move a `SUSPENDED` Sitter back to `ACTIVE`. | `PlatformAdmin` |
| POST | `/api/v1/sitters/{id}/deactivate` | Move an `ACTIVE` or `SUSPENDED` Sitter to terminal `DEACTIVATED`. | `PlatformAdmin` |
| POST | `/api/v1/sitters/{id}/recompute-tier` | Force an idempotent tier-score recompute. | `PlatformAdmin` |
| POST | `/api/v1/background-checks` | Create a BackgroundCheck for a Sitter (advances Sitter `APPLIED` → `BG_CHECK_PENDING`). | `PlatformAdmin` |
| GET | `/api/v1/background-checks/{id}` | Retrieve a BackgroundCheck by id. | `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/background-checks` | List BackgroundChecks, optionally filtered by `sitter_id` and `status`. | `PlatformAdmin`, `ClaimsAdjuster` |
| POST | `/api/v1/background-checks/{id}/clear` | Disposition a `PENDING` BackgroundCheck as `CLEARED`. | `PlatformAdmin` |
| POST | `/api/v1/background-checks/{id}/flag` | Disposition a `PENDING` BackgroundCheck as `FLAGGED` (originates Cascade #1). | `PlatformAdmin` |
| POST | `/api/v1/pets` | Create a Pet for an Owner. | `Owner` |
| GET | `/api/v1/pets/{id}` | Retrieve a Pet by id. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/pets` | List Pets, optionally filtered by `owner_id`. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| POST | `/api/v1/emergency-contacts` | Create an EmergencyContact for an Owner. | `Owner` |
| GET | `/api/v1/emergency-contacts/{id}` | Retrieve an EmergencyContact by id. | `Owner`, `PlatformAdmin` |
| GET | `/api/v1/emergency-contacts` | List EmergencyContacts filtered by `owner_id`. | `Owner`, `PlatformAdmin` |
| POST | `/api/v1/meet-and-greets` | Schedule a Meet & Greet between Owner+Pet and Sitter. | `Owner` |
| GET | `/api/v1/meet-and-greets/{id}` | Retrieve a MeetAndGreet by id. | `Owner`, `Sitter`, `PlatformAdmin` |
| GET | `/api/v1/meet-and-greets` | List MeetAndGreets filtered by any/all of `owner_id`, `sitter_id`, `pet_id`, `status`. | `Owner`, `Sitter`, `PlatformAdmin` |
| POST | `/api/v1/meet-and-greets/{id}/approve` | Mark a `SCHEDULED` MeetAndGreet `COMPLETED_APPROVED`. | `Owner` |
| POST | `/api/v1/meet-and-greets/{id}/decline` | Mark a `SCHEDULED` MeetAndGreet `COMPLETED_DECLINED`. | `Owner` |
| POST | `/api/v1/meet-and-greets/{id}/mark-no-show` | Mark a `SCHEDULED` MeetAndGreet as `NO_SHOW` (admin-only; requires 60+ minutes since `scheduled_at`). | `PlatformAdmin` |
| POST | `/api/v1/meet-and-greets/{id}/cancel` | Cancel a `SCHEDULED` MeetAndGreet. | `Owner` |
| POST | `/api/v1/bookings` | Create a Booking (`REQUESTED`) and compute `booking_quote_cents`. | `Owner` |
| GET | `/api/v1/bookings/{id}` | Retrieve a Booking by id. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/bookings` | List Bookings filtered by any/all of `owner_id`, `sitter_id`, `pet_id`, `status`. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| POST | `/api/v1/bookings/{id}/confirm` | Sitter confirms a `REQUESTED` Booking. | `Sitter` |
| POST | `/api/v1/bookings/{id}/reject` | Sitter rejects a `REQUESTED` Booking. | `Sitter` |
| POST | `/api/v1/bookings/{id}/cancel` | Cancel a Booking; valid from `REQUESTED` (no OCC) or `CONFIRMED` (OCC required via `expected_booking_version`). | `Owner` |
| POST | `/api/v1/bookings/{id}/start` | Sitter starts the booked service (`KEY_RECEIVED` → `IN_PROGRESS`). | `Sitter` |
| POST | `/api/v1/bookings/{id}/complete` | Sitter completes the service (`IN_PROGRESS` → `COMPLETED`) with optional tip / rating / incident inputs. | `Sitter` |
| POST | `/api/v1/bookings/{id}/emergency-terminate` | Sitter terminates an `IN_PROGRESS` Booking due to emergency (no payout, no rating). | `Sitter` |
| POST | `/api/v1/key-handoffs` | Create a KeyHandoff for a `CONFIRMED` Booking. | `Owner` |
| GET | `/api/v1/key-handoffs/{id}` | Retrieve a KeyHandoff by id. | `Owner`, `Sitter`, `PlatformAdmin` |
| GET | `/api/v1/key-handoffs` | List KeyHandoffs filtered by `booking_id` and `status`. | `Owner`, `Sitter`, `PlatformAdmin` |
| POST | `/api/v1/key-handoffs/{id}/receive` | Sitter marks the handoff `RECEIVED` (advances Booking `CONFIRMED` → `KEY_RECEIVED`). | `Sitter` |
| POST | `/api/v1/gps-tracks` | Append a GPS sample to an `IN_PROGRESS` Booking. | `Sitter` |
| GET | `/api/v1/gps-tracks/{id}` | Retrieve a single GpsTrack sample by id. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| GET | `/api/v1/gps-tracks` | List GpsTracks filtered by `booking_id`. | `Owner`, `Sitter`, `PlatformAdmin`, `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims` | File an InsuranceClaim against an `IN_PROGRESS` / `COMPLETED` / `EMERGENCY_TERMINATED` Booking. | `Owner` |
| GET | `/api/v1/insurance-claims/{id}` | Retrieve an InsuranceClaim by id. | `Owner`, `ClaimsAdjuster`, `PlatformAdmin` |
| GET | `/api/v1/insurance-claims` | List InsuranceClaims filtered by `booking_id`, `sitter_id_snapshot`, `status`. | `Owner`, `ClaimsAdjuster`, `PlatformAdmin` |
| POST | `/api/v1/insurance-claims/{id}/start-review` | ClaimsAdjuster begins review (`SUBMITTED` → `UNDER_REVIEW`). | `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims/{id}/approve` | ClaimsAdjuster approves the claim (`UNDER_REVIEW` → `APPROVED`) with `approved_amount_cents`. | `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims/{id}/revert` | ClaimsAdjuster reverts an `APPROVED` claim back to `UNDER_REVIEW`. | `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims/{id}/pay` | ClaimsAdjuster marks an `APPROVED` claim `PAID` (originates Cascade #2). | `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims/{id}/deny` | ClaimsAdjuster denies a claim (`UNDER_REVIEW` → `DENIED`). | `ClaimsAdjuster` |
| POST | `/api/v1/insurance-claims/{id}/withdraw` | Owner withdraws a `SUBMITTED` claim. | `Owner` |
| POST | `/api/v1/_clock/set_current_utc` | Test-driving endpoint: pin the server's `system_clock` to a supplied ISO 8601 UTC instant via the `to_iso8601` body field. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SITTER_NOT_CLEARED` | 422 |
| `ERR_MEET_AND_GREET_REQUIRED` | 422 |
| `ERR_PET_OWNER_MISMATCH` | 422 |
| `ERR_SITTER_TIME_CONFLICT` | 409 |
| `ERR_PET_TIME_CONFLICT` | 409 |
| `ERR_PRIMARY_CONTACT_EXISTS` | 409 |
| `ERR_BG_CHECK_EXISTS` | 409 |
| `ERR_KEY_HANDOFF_EXISTS` | 409 |
| `ERR_WALLET_INSUFFICIENT` | 422 |
| `ERR_INVALID_APPROVED_AMOUNT` | 422 |
| `ERR_GPS_BOOKING_NOT_IN_PROGRESS` | 409 |
| `ERR_INVALID_REQUEST` | 400 |

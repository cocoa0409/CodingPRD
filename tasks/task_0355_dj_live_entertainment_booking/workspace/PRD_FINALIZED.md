# Dj Live Entertainment Booking API — Product Requirements Document

## 1. Introduction

Booking a DJ or a live act for an event is a coordination problem disguised as a sales transaction. A studio juggles a roster of performers with different genres and rate cards, a catalogue of packages bundling sound, lighting, staging, and effects equipment, a patchwork of travel zones with their own surge pricing, and clients who haggle over contracts, change their minds, and occasionally need a substitute act when their first choice falls through. This API is the system of record that keeps all of that consistent: it tracks the lifecycle of a booking from the first inquiry through the signed contract, the captured deposit, the night of the performance, and the final settlement, while continuously recomputing what is owed.

The platform serves four distinct audiences. Studio administrators stand up the reference data — travel zones, packages, equipment line items, performers, and the test-driving clock. Booking agents drive the day-to-day lifecycle of each engagement, arranging holds, contracts, payments, and backup performers. Performers manage their own unavailability and decide whether to accept the backup slots offered to them. Clients sign contracts, pay deposits and balances, curate their song requests and do-not-play lists, and may cancel an event they no longer want. Because money, calendars, and roster availability all move together, the system favours immediate consistency: every state change that touches a quote, a deposit threshold, a performer's availability, or a payment ledger is applied and reflected atomically within the request that triggers it.

This document specifies the global contract that every endpoint shares, the cross-cutting principles that govern money and time, and the detailed business workflows that an implementer must reproduce exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the four recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The four roles are spelled exactly `StudioAdmin`, `BookingAgent`, `Performer`, and `Client`. When a recognised role calls an endpoint it is not permitted to use, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When a caller is permitted to use an endpoint in general but is not the owner of the specific resource it targets, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The two operator roles are not tied to any stored entity. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is an opaque operator identifier not bound to any persisted record; the server treats it purely as the acting administrator and never compares it to an entity `id`. When `X-User-Role` is `BookingAgent`, `X-User-ID` is likewise an opaque operator identifier not bound to any persisted record; it identifies the acting agent but is never matched against an entity `id`.

The two participant roles are entity-backed. When `X-User-Role` is `Performer`, `X-User-ID` is the `id` of the acting `Performer`; any ownership check on a resource that references a performer compares that resource's performer foreign key to `X-User-ID`. Concretely, accepting or declining a backup offer requires that `X-User-ID` equal the `candidate_performer_id` recorded on that backup assignment, and a performer may only file blackout windows against their own performer record. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; any ownership check on a resource that references a client compares that resource's client foreign key to `X-User-ID`. A client may only sign or decline a contract, request a revision, add a song entry, pay, capture, or cancel on a booking whose `client_id` equals `X-User-ID`; signing another client's contract, for example, is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and has a minimum of 0. A request whose `limit` falls below 1 or above 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422); on list endpoints this bounds check is the only validation that fires, so it never competes with the business validations described elsewhere. Results are ordered by `created_at` ascending. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object, where `total_count` is the count of all matching rows before the page window is applied and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Common Resource Properties

Most resources share a common envelope of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix — rendered in the canonical 36-character lowercase hyphenated form (`8-4-4-4-12` hex digits), not a dash-stripped 32-character hex string, and never carrying any leading `entity_` style prefix. The `id` is the only field affected by this; the `api_request_id` carried in response metadata is unrelated and keeps its `req_` prefix as described in §2.2. Every resource also carries a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Resources that can be mutated after creation also carry an `updated_at` timestamp in the same format and an integer `version` that begins at 1 and increments by exactly 1 on every mutation. The following entities carry the full set — `id`, `created_at`, `updated_at`, and `version`: `Performer`, `TravelZone`, `PackageOffering`, `EquipmentItem`, `Booking`, `Client`, `PaymentRecord`, `SongRequest`, `ContractDocument`, and `BackupAssignment`. The `BlackoutWindow` entity is the sole exception: it is immutable once created and therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

Whenever a mutation occurs — whether triggered directly by the caller or applied as a cascade from another operation — the affected resource's `updated_at` is refreshed and its `version` is incremented by 1. A single business action that mutates several resources increments the `version` of each one it touches.

### 2.5. Money, Precision, and Rounding

All monetary amounts are stored and exchanged as integer cents; there are no fractional cents. Several computations involve basis points, where 10000 basis points represents a factor of 1.0. Wherever a basis-point factor or a percentage is multiplied into a cent amount, the intermediate product is divided by 10000 and the result is rounded half up to the nearest whole cent. This half-up rounding applies to the travel-fee surge multiplication, the deposit calculation, and the cancellation-fee calculation. Pure additions of integer cents — for instance, summing equipment line fees or adding overtime onto a quote — are exact and require no rounding. Where a calculation pins an evaluation order, that order is part of the contract and must be honoured.

### 2.6. Nested Resource Retrieval and Referential Integrity

Many resources are reached through nested paths — equipment under a package, blackouts and song requests and payments and contracts and backup assignments under their parent. Path-referenced resources are validated left to right: the leftmost identifier in the path is resolved first, and the first one that does not resolve to an existing row yields `ERR_NOT_FOUND` (HTTP 404). Separately, when a create request carries foreign-key references in its body — such as `client_id`, `performer_id`, `package_id`, `event_zone_id`, `booking_id`, or `candidate_performer_id` — each such reference must resolve to an existing row; if any does not, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency on the Booking Aggregate

Two booking operations are guarded by optimistic concurrency control because each can be invalidated by a concurrent change to the same booking. Issuing or re-issuing a contract requires the caller to supply `expected_booking_version` in the request body, carrying the `version` of the booking the caller last observed. If `expected_booking_version` does not equal the booking's current `version`, the request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412). This protects against the case where a prior issue-contract on the same booking has already created a new contract revision and advanced the booking's `version`, so that a second issue request built on the older view would otherwise clobber it.

Promoting a backup performer likewise requires `expected_booking_version` in the request body, and a mismatch with the booking's current `version` is rejected with the same `ERR_STALE_BOOKING_VERSION` (HTTP 412). This captures the situation where another agent has already promoted a different backup — legitimately reassigning the active performer and expiring the peer backups, and thereby advancing the booking's `version` — leaving the current caller's view stale. No other endpoint accepts or requires a version field.

### 2.8. Validation Ordering

When several validations could apply to a single request, they are evaluated in a fixed priority order so that the failure surfaced is deterministic. Authentication is checked first: the presence and validity of the auth headers (`ERR_UNAUTHENTICATED`). Next, role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`), then, for ownership-scoped operations, the resource-ownership check (`ERR_NOT_RESOURCE_OWNER`). After authorization comes existence: path-referenced resources (`ERR_NOT_FOUND`), then body foreign-key references (`ERR_REFERENCED_ENTITY_NOT_FOUND`). Next is generic request well-formedness — required fields present, correct types, valid enum values, integers within their declared bounds (`ERR_INVALID_REQUEST`). Only after a request is known to be authentic, authorized, owned, referentially sound, and well-formed do the domain-specific business rules run: package-active checks, state-transition legality (`ERR_INVALID_STATE`), the booking-version concurrency check (`ERR_STALE_BOOKING_VERSION`), and then the temporal, capacity, backup, and fiscal rules. In short, the earlier a rule sits in the order above, the earlier it wins when more than one would otherwise fire. The relative precedence among these is reinforced in the workflow narratives that follow, where each rule is described next to the operation it guards.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Catalogue: Zones, Packages, Equipment, and the Clock

Before any booking can be priced, a `StudioAdmin` populates the reference data. A travel zone is created with a `zone_code` (which must be present and unique across all travel zones), a human-readable `name`, a `base_travel_fee_cents` charged as a flat fee when a performer leaves their home zone for this zone, a `per_mile_fee_cents` surcharge added per road mile, and an optional `surge_multiplier_bps`. The surge multiplier is expressed in basis points, where 10000 means a factor of 1.0 (no surge); it defaults to 10000 and may never be set below 10000. All of `base_travel_fee_cents`, `per_mile_fee_cents` must be zero or greater.

A package offering is created with a `name` (required, non-empty), a `tier` that is one of `BASIC`, `STANDARD`, or `PREMIUM`, a `flat_package_fee_cents` charged on top of the performer's set rate, and an `included_set_minutes` value that defines how long a set runs before overtime applies. Included set minutes must be at least 30. The package also carries a `deposit_pct_bps`, the required deposit expressed as a fraction of the grand total in basis points (2500 means 25%); it defaults to 2500 and must be between 0 and 10000 inclusive. A package's `status` begins `ACTIVE` on creation. An administrator may retire a package, transitioning its `status` to `RETIRED`; a `RETIRED` package can no longer back a new booking.

Equipment line items hang off a package. Each is created against a package and carries that package's identity in its `package_id`, a `category` that is one of `SOUND`, `LIGHTING`, `STAGING`, or `FX`, a `label` describing the gear, a `unit_fee_cents` (zero or greater) added to any booking that selects the package, and a `requires_power_circuits` count of dedicated 20-amp circuits the item draws, which defaults to 1 and must be zero or greater.

Because the entire system reasons about time — events in the future, lead times before cancellation, blackout windows — the server keeps a logical clock. An administrator-only test-driving capability sets that clock to a supplied `now_utc` instant, and all subsequent time comparisons use the clock's value. This is how event-in-the-future checks, lead-day computations, and blackout overlaps are exercised deterministically.

### 3.2. The Performer Roster, Availability, and Blackouts

A performer is registered by a `StudioAdmin` with a `stage_name` (required, non-empty), an `act_type` that is one of `DJ`, `BAND`, `SOLO_MUSICIAN`, `EMCEE`, or `DUO`, a `genre` that is one of `HOUSE`, `HIP_HOP`, `TOP_40`, `JAZZ`, `ROCK`, `COUNTRY`, `LATIN`, `CLASSICAL`, or `MULTI_GENRE`, and a `home_zone_id` naming the travel zone the performer is based in — travel fees are always computed relative to this home zone. Pricing is captured by `base_set_rate_cents`, the quoted fee for the performer's standard set, and `overtime_rate_cents_per_15min`, the charge for each started 15-minute block performed beyond the contracted length; both must be zero or greater.

Three fields on a performer are system-maintained. The `availability_status` begins `AVAILABLE` and is one of `AVAILABLE`, `ON_HOLD`, `BOOKED`, or `INACTIVE`. It moves to `ON_HOLD` when the performer is placed on a hold, to `BOOKED` once a booking confirms or a set starts, back to `AVAILABLE` when a booking completes or cancels, and an administrator may force it to `INACTIVE` by deactivating the performer, removing them from the bookable roster. The `reliability_score` starts at 100 and is decremented by performer-caused events described later; it is floored at 0 and never exceeds 100. The `lifetime_completed_sets` counter starts at 0 and counts the bookings the performer drove all the way to a performed set.

Performers (and administrators on their behalf) record unavailability as blackout windows. A blackout window names the `performer_id` it applies to, an inclusive `start_utc`, and an exclusive `end_utc`, with an optional free-text `reason` such as a vacation or recording session; the end instant must be strictly later than the start instant. A new blackout window may not overlap an existing window of the same performer under half-open semantics — that is, two windows overlap when the start of one is strictly before the end of the other and the start of that other is strictly before the end of the first. An overlapping window is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409). Blackout windows are immutable: once written they are never updated, which is why they carry no version.

### 3.3. From Inquiry to Hold: Pricing the Event

Before a booking can name a client, that client must be registered — by either a `StudioAdmin` or a `BookingAgent` — with a `full_name` (required, non-empty), an `email` (required and unique across all clients), and an optional `phone`. A client also carries a system-maintained `store_credit_cents` balance, described in the cancellation narrative.

A `BookingAgent` opens an engagement by creating a booking inquiry, supplying the `client_id`, the `performer_id` to be booked, the `package_id` to bundle, the `event_zone_id` where the event will be held, the `event_start_utc` set-start timestamp, the `event_miles_from_home` road-mile distance from the performer's home zone to the venue (zero or greater), and optionally a `contracted_set_minutes`. If `contracted_set_minutes` is omitted, it defaults to the chosen package's `included_set_minutes`; if supplied, it must be at least the package's `included_set_minutes`, otherwise the create is rejected with `ERR_SET_TOO_SHORT` (HTTP 422). The selected package must be `ACTIVE` at create time; referencing a `RETIRED` package is rejected with `ERR_PACKAGE_RETIRED` (HTTP 409). The `event_start_utc` must be strictly after the current clock; an event at or before the present is rejected with `ERR_EVENT_IN_PAST` (HTTP 422). A freshly created booking enters the `INQUIRY` state with its `active_performer_id` unset.

Placing the booking on hold is where the money is first computed. A hold is only legal from `INQUIRY`. The booked performer's `availability_status` must be either `AVAILABLE` or `ON_HOLD` for the hold to proceed. The event's start instant must not fall inside any blackout window of that performer — that is, the start must not lie at or after a window's `start_utc` and strictly before its `end_utc`; a violation is rejected with `ERR_PERFORMER_BLACKED_OUT` (HTTP 409). The booking's set window must also not collide with another non-terminal booking of the same active performer under the booking-versus-booking overlap rule; a collision is rejected with `ERR_PERFORMER_DOUBLE_BOOKED` (HTTP 409). When all of these pass, the hold computes the provisional grand total (described in 3.4), derives the required deposit, sets `balance_due_cents` to the quote total minus whatever has already been paid, records `active_performer_id` as the originally booked `performer_id`, moves the performer's `availability_status` to `ON_HOLD`, and transitions the booking from `INQUIRY` to `HOLD`.

### 3.4. The Quote: Set Rate, Package, Equipment, and Travel

The provisional grand total, stored on the booking as `quote_total_cents`, is assembled at the moment of the hold from four components in a pinned order. First, the performer's `base_set_rate_cents` is taken as the set rate. Second, the package's `flat_package_fee_cents` is added. Third, the equipment fee is computed as the sum of `unit_fee_cents` across every equipment line item whose `package_id` matches the booking's package — this sum is evaluated before travel is added. Fourth, the travel fee is added.

The travel fee is governed by the performer's home zone. If the event zone equals the performer's home zone — that is, `event_zone_id` equals the performer's `home_zone_id` — the travel fee is exactly 0 regardless of mileage or any surge multiplier; this home-zone waiver short-circuits the entire travel computation. Otherwise, the raw travel amount is the event zone's `base_travel_fee_cents` plus its `per_mile_fee_cents` multiplied by `event_miles_from_home`. That raw amount is then multiplied by the event zone's `surge_multiplier_bps`, divided by 10000, and rounded half up to whole cents to yield the travel fee. The quote total is the exact integer sum of the set rate, the package fee, the equipment fee, and this travel fee. Overtime is deliberately excluded from the quote — it is realized only when the set is actually performed.

The required deposit is computed at the same hold step. It equals the quote total multiplied by the package's `deposit_pct_bps`, divided by 10000, and rounded half up to whole cents, and is stored as `deposit_required_cents`.

### 3.5. Contracts: Issuing, Signing, Revising, and the Negotiation Loop

Once a booking is on hold, the agent issues a contract. Issuing requires that the booking be in `HOLD` and that no deposit has yet been captured (no captured `DEPOSIT` payment exists for the booking), and the request must carry an `expected_booking_version` matching the booking's current `version`. Issuing from `HOLD` creates a `ContractDocument` at `revision` 1 with `status` `ISSUED`, snapshots the current quote into the contract's `quoted_total_cents`, and moves the booking from `HOLD` to `CONTRACT_SENT`. Each contract document records the `booking_id` it covers.

From `CONTRACT_SENT`, two client actions diverge. The client may sign the issued contract: signing requires the contract's `status` to be `ISSUED`, the owning booking to be in `CONTRACT_SENT`, and the acting client to own the booking, after which the contract's `status` becomes `SIGNED`. Alternatively, the client may decline the issued contract directly, moving its `status` to `DECLINED`; declining unlocks no deposit path. The client may instead request a revision, which is legal only when the booking is in `CONTRACT_SENT` and the current contract is `ISSUED`. Requesting a revision moves the booking from `CONTRACT_SENT` to `NEGOTIATING` and cascades the current contract's `status` to `DECLINED`.

From `NEGOTIATING`, the agent re-issues a contract to close the loop. Re-issuing carries an `expected_booking_version` matching the booking's current `version`, supersedes any still-`ISSUED` contract on the booking by moving its `status` to `SUPERSEDED`, creates a fresh `ContractDocument` whose `revision` is one greater than the highest revision yet seen on the booking, with `status` `ISSUED` and `quoted_total_cents` snapshotting the current quote, and returns the booking to `CONTRACT_SENT`. This `CONTRACT_SENT → NEGOTIATING → CONTRACT_SENT` cycle may repeat as many times as the client and agent need. A contract reaches one of three terminal states — `SIGNED`, `DECLINED`, or `SUPERSEDED` — and never leaves them.

### 3.6. Payments: Authorizing, Capturing, Voiding, and the Deposit Threshold

Payments evolve along two independent dimensions. A payment is authorized against a booking by supplying the `booking_id`, a `kind` that is one of `DEPOSIT`, `BALANCE`, or `ADJUSTMENT`, a strictly positive `amount_cents`, and an optional `refund_destination` that is either `ORIGINAL` or `STORE_CREDIT` (defaulting to `ORIGINAL`) and governs where a later refund of this payment is routed. A new payment record begins with a `capture_status` of `AUTHORIZED` and a `settlement_status` of `UNSETTLED`.

The `capture_status` dimension moves a payment from `AUTHORIZED` to either `CAPTURED` or `VOID`. Capturing is legal only while the payment is `AUTHORIZED` and the owning booking is neither `CANCELLED` nor `SETTLED`; the captured amount must not exceed the booking's outstanding `balance_due_cents`, and an over-capture is rejected with `ERR_OVERPAYMENT` (HTTP 409). A capture recomputes the booking's `amount_paid_cents` — the sum of captured payment amounts minus the sum of refunded amounts — and its `balance_due_cents`. Voiding is legal only while a payment is still `AUTHORIZED`; attempting to void a payment that is already `CAPTURED` or `VOID` is rejected with `ERR_PAYMENT_NOT_VOIDABLE` (HTTP 409).

Capturing a deposit can confirm a booking. When a `DEPOSIT` payment is captured against a booking that is in `CONTRACT_SENT` with a `SIGNED` contract, and the cumulative captured deposit amount for the booking reaches or exceeds `deposit_required_cents`, the system automatically advances the booking from `CONTRACT_SENT` to `CONFIRMED`. Confirmation sets the booking's `active_performer_id` to the booked `performer_id` and moves that performer's `availability_status` to `BOOKED`; any standing backup offers remain on standby rather than being expired.

The `settlement_status` dimension evolves independently of capture. A captured payment stays `UNSETTLED` until either a cancellation routes it to `REFUNDED` or a settlement marks it `SETTLED`; a captured payment can therefore be `UNSETTLED` and only later become `REFUNDED`.

### 3.7. The Night Of: Starting, Completing, and Overtime

When the event arrives, the agent starts the set, which is legal only from `CONFIRMED` and only once the current clock has reached or passed the booking's `event_start_utc`. Starting the set moves the booking from `CONFIRMED` to `PERFORMING`; the active performer's `availability_status` remains `BOOKED`.

Completing the set supplies the realized duration as `actual_set_minutes`, which must be present and zero or greater; completion is legal only from `PERFORMING`. Completing computes the overtime charge, derives the final total, recomputes the balance, transitions the active performer's `availability_status` back to `AVAILABLE`, increments that performer's `lifetime_completed_sets` by 1, and moves the booking from `PERFORMING` to `PERFORMED`. The overtime computation works from the contracted length: the extra minutes are the actual minutes performed minus the contracted minutes, but never less than zero. Those extra minutes are billed per started 15-minute block — the number of blocks is the extra minutes divided by 15 and rounded up to the next whole block, so zero extra minutes bill zero blocks, exactly the contracted length bills zero blocks, and a single minute over the contracted length bills one full block. The overtime charge, stored as `overtime_cents`, is the number of blocks multiplied by the performer's `overtime_rate_cents_per_15min`. The final grand total, stored as `final_total_cents`, is the quote total plus the overtime charge, and the `balance_due_cents` is recomputed as that final total minus `amount_paid_cents`.

### 3.8. Settlement

A performed booking is settled by the agent. Settlement is legal only from `PERFORMED` and only when the booking's `balance_due_cents` is zero or below — the final balance must be fully covered by captured payments; attempting to settle with a positive outstanding balance is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 409). Settling marks every captured payment on the booking that is still `UNSETTLED` as `SETTLED`, and moves the booking from `PERFORMED` to its terminal `SETTLED` state.

### 3.9. Cancellation, Fees, and Refunds

A booking may be cancelled from `HOLD`, `CONTRACT_SENT`, `NEGOTIATING`, or `CONFIRMED`, by either the booking agent or the owning client. Cancelling computes a cancellation fee, refunds what is refundable, and unwinds the engagement's side relationships. The cancellation fee is a fraction of the booking's quote total, with the fraction set by how much lead time remains before the event. The lead time in whole days is the difference between the event start and the current clock, expressed in whole UTC days by taking the total seconds between them and dividing by 86400 with the fractional part discarded. When the lead time is 30 days or more, the fee is 10% of the quote total; when it is at least 14 days but fewer than 30, the fee is 25%; when it is at least 7 days but fewer than 14, the fee is 50%; and when it is fewer than 7 days — including an event that has already passed — the fee is 100%. A booking that is in `CONFIRMED` at the moment of cancellation carries an additional surcharge of 10 percentage points added to whichever lead-time tier applies, with the combined fee capped at 100% of the quote total. The resulting cancellation fee in cents is the quote total multiplied by the applicable fraction in basis points, divided by 10000, and rounded half up to whole cents; it is stored as `cancellation_fee_cents`.

The refund follows the fee. For each captured payment, the refundable portion is the booking's `amount_paid_cents` reduced by the `cancellation_fee_cents`, and that refund is routed according to the payment's `refund_destination`: a routed refund moves the payment's `settlement_status` to `REFUNDED`, and when the destination is `STORE_CREDIT` the refundable portion is added to the owning client's `store_credit_cents` balance. The cancellation also unwinds related records: any still-`ISSUED` or `SIGNED` contract on the booking moves to `DECLINED`, any backup assignment still in `OFFERED` or `ACCEPTED` moves to `EXPIRED`, and the current active performer's `availability_status` returns to `AVAILABLE`. The booking itself moves to its terminal `CANCELLED` state.

### 3.10. Song Requests and the Do-Not-Play List

A client or agent curates the music for a booking by adding song entries. Each entry names the booking it belongs to via `booking_id`, a `title` (required, non-empty), an optional `artist`, and a `list_type` that is either `REQUEST` (a song the client wants played) or `DO_NOT_PLAY` (a song to avoid). A `REQUEST` entry also carries a `priority` integer, where a lower number means play earlier; it defaults to 100, must be at least 1, and is ignored for do-not-play entries. A song entry's `status` begins `ACCEPTED`. However, if a newly created `REQUEST` collides with an existing `DO_NOT_PLAY` entry on the same booking — meaning the two share the same title and artist when both are compared case-insensitively — the new request is recorded with `status` `CONFLICTED` instead of `ACCEPTED`. A song entry never leaves the state it is created in; `CONFLICTED` is terminal.

### 3.11. Backup Performers: Offering, Accepting, Declining, and Promotion

Because acts fall through, a booking can stockpile fallback performers. The agent offers a backup slot to a candidate by supplying the booking's `booking_id`, the `candidate_performer_id`, and an operator-assigned `rank` (at least 1) that orders the fallbacks — a lower rank is tried first. A candidate may not be the booking's current active performer; offering the active performer as their own backup is rejected with `ERR_BACKUP_IS_PRIMARY` (HTTP 409). A new backup assignment begins in `OFFERED`.

The offered performer responds. Accepting is legal only while the assignment is `OFFERED`, only by the candidate performer themselves, and only while that performer's `availability_status` is `AVAILABLE` or `ON_HOLD`; acceptance moves the assignment to `ACCEPTED`. Declining is legal only while the assignment is `OFFERED` and only by the candidate; declining moves the assignment to `DECLINED` and decrements that performer's `reliability_score` by 5, floored at 0. A declined slot returns to the pool, and the agent may offer the next-ranked candidate, so the offer-and-decline pattern can cycle through fallbacks.

Promotion swaps in a backup. The agent promotes a backup by supplying the targeted `backup_assignment_id` and an `expected_booking_version`. Promotion is legal only when the targeted assignment is `ACCEPTED` and the owning booking is in `CONFIRMED` or `PERFORMING`. Among the accepted backups, only one is eligible: the system selects the eligible candidate by sorting the booking's accepted assignments first by `rank` ascending, breaking ties by the candidate performer's `reliability_score` descending, and breaking any remaining tie by the assignment's `created_at` ascending — never by `id`. If the assignment the caller targeted is not that lowest-rank eligible one, the request is rejected with `ERR_NOT_LOWEST_RANK_BACKUP` (HTTP 409); if the booking has no accepted backup at all, it is rejected with `ERR_NO_ELIGIBLE_BACKUP` (HTTP 409). A successful promotion moves the targeted assignment to `PROMOTED`, reassigns the booking's `active_performer_id` to the candidate, returns the former active performer's `availability_status` to `AVAILABLE` while decrementing that performer's `reliability_score` by 10 (floored at 0), moves the new performer's `availability_status` to `BOOKED`, and expires every other `OFFERED` or `ACCEPTED` backup assignment on the booking by moving it to `EXPIRED`. A backup assignment's terminal states are `DECLINED`, `PROMOTED`, and `EXPIRED`.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; reads, list retrievals, and operations that modify or transition an existing resource return HTTP 200. The table below lists only the method, path, a short description, and the authorized roles; request bodies, response payloads, and side effects are specified in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/travel-zones` | Create a travel zone | StudioAdmin |
| GET | `/travel-zones/{id}` | Read a travel zone | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/packages` | Create a package offering | StudioAdmin |
| GET | `/packages/{id}` | Read a package | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/packages/{id}/retire` | Retire a package so it can no longer back new bookings | StudioAdmin |
| POST | `/packages/{id}/equipment` | Add an equipment line item to a package | StudioAdmin |
| GET | `/packages/{id}/equipment` | List equipment items for a package | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/performers` | Create a performer / act | StudioAdmin |
| GET | `/performers/{id}` | Read a performer | StudioAdmin, BookingAgent, Performer, Client |
| GET | `/performers` | List performers, filterable by home zone, act type, and availability | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/performers/{id}/deactivate` | Mark a performer INACTIVE | StudioAdmin |
| POST | `/performers/{id}/blackouts` | Create an unavailability window for a performer | StudioAdmin, Performer |
| GET | `/performers/{id}/blackouts` | List blackout windows for a performer | StudioAdmin, BookingAgent, Performer |
| POST | `/clients` | Register a client | StudioAdmin, BookingAgent |
| GET | `/clients/{id}` | Read a client | StudioAdmin, BookingAgent, Client |
| POST | `/bookings` | Create a booking inquiry | BookingAgent |
| GET | `/bookings/{id}` | Read a booking with all computed totals | StudioAdmin, BookingAgent, Performer, Client |
| GET | `/bookings` | List bookings with filters | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/bookings/{id}/hold` | Place a hold; compute quote and deposit, hold the performer | BookingAgent |
| POST | `/bookings/{id}/issue-contract` | Issue or re-issue a contract document | BookingAgent |
| POST | `/bookings/{id}/request-revision` | Request a contract revision, moving to NEGOTIATING | Client |
| POST | `/bookings/{id}/start-set` | Mark the set as started | BookingAgent |
| POST | `/bookings/{id}/complete-set` | Complete the set, supplying actual minutes | BookingAgent |
| POST | `/bookings/{id}/settle` | Settle a fully-paid performed booking | BookingAgent |
| POST | `/bookings/{id}/cancel` | Cancel a booking; compute fee, refund, revert relationships | BookingAgent, Client |
| POST | `/bookings/{id}/promote-backup` | Promote the lowest-rank accepted backup to active performer | BookingAgent |
| GET | `/contracts/{id}` | Read a contract document | StudioAdmin, BookingAgent, Client |
| GET | `/bookings/{id}/contracts` | List contract documents for a booking | StudioAdmin, BookingAgent, Client |
| POST | `/contracts/{id}/sign` | Client signs an issued contract | Client |
| POST | `/contracts/{id}/decline` | Client declines an issued contract | Client |
| POST | `/payments` | Authorize a payment against a booking | BookingAgent, Client |
| GET | `/payments/{id}` | Read a payment record | StudioAdmin, BookingAgent, Client |
| GET | `/bookings/{id}/payments` | List payment records for a booking | StudioAdmin, BookingAgent, Client |
| POST | `/payments/{id}/capture` | Capture an authorized payment; may auto-confirm the booking | BookingAgent, Client |
| POST | `/payments/{id}/void` | Void an authorized payment | BookingAgent |
| POST | `/bookings/{id}/song-requests` | Add a song request or do-not-play entry | Client, BookingAgent |
| GET | `/bookings/{id}/song-requests` | List song requests for a booking | StudioAdmin, BookingAgent, Performer, Client |
| GET | `/song-requests/{id}` | Read a single song request | StudioAdmin, BookingAgent, Performer, Client |
| POST | `/bookings/{id}/backup-assignments` | Offer a backup slot to a candidate performer | BookingAgent |
| GET | `/bookings/{id}/backup-assignments` | List backup assignments for a booking | StudioAdmin, BookingAgent, Performer |
| GET | `/backup-assignments/{id}` | Read a single backup assignment | StudioAdmin, BookingAgent, Performer |
| POST | `/backup-assignments/{id}/accept` | Candidate performer accepts a backup offer | Performer |
| POST | `/backup-assignments/{id}/decline` | Candidate performer declines a backup offer | Performer |
| GET | `/backup-assignments` | List backup assignments filterable by candidate and booking | StudioAdmin, BookingAgent, Performer |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | StudioAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PACKAGE_RETIRED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_BOOKING_VERSION` | 412 |
| `ERR_EVENT_IN_PAST` | 422 |
| `ERR_PERFORMER_BLACKED_OUT` | 409 |
| `ERR_PERFORMER_DOUBLE_BOOKED` | 409 |
| `ERR_BLACKOUT_OVERLAP` | 409 |
| `ERR_SET_TOO_SHORT` | 422 |
| `ERR_NOT_LOWEST_RANK_BACKUP` | 409 |
| `ERR_NO_ELIGIBLE_BACKUP` | 409 |
| `ERR_BACKUP_IS_PRIMARY` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_PAYMENT_NOT_VOIDABLE` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |

# P2P Gear Rental API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the P2P Gear Rental API, a peer-to-peer marketplace where individual owners list physical equipment — cameras, drones, power tools, and similar gear — for short-term rental by other users. The platform sits between two peers on every transaction: an owner who lists an item and controls its rental lifecycle, and a renter who requests, pays for, and returns the item. Around that core exchange the system layers identity verification, dynamic day-by-day pricing, security deposits, damage-and-loss claims with platform-backed coverage, owner payouts net of commission, and a reputation system that rewards reliable behavior and penalizes late returns and upheld claims.

The business problem the API solves is trust and money movement between strangers. Every rental exposes an owner to the risk that expensive gear is damaged or never returned, and exposes a renter to the risk of unfair charges. The system mediates this by holding a refundable security deposit against each booking, by pricing rentals transparently through a reproducible pricing engine, by requiring photographic condition evidence at both pickup and return, and by adjudicating claims through a neutral platform operator. Because owners re-price and re-stock their listings while renters are quoting against them, and because multiple claims can draw on a single deposit, the API is built around optimistic concurrency control and carefully ordered, cascading side effects so that no party ever settles against stale figures.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Domain workflows in Section 3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request other than new-user registration must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When a caller is authenticated but not permitted to perform the requested operation — either because their role is not authorized for it, or because they are an ownership-scoped user acting on a resource they do not own — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes four roles: `Anonymous`, `Renter`, `Owner`, and `Platform`.

- `Anonymous` is the unauthenticated caller. Its only capability is registering a new user; registration is the single endpoint that does not require the authentication headers.
- `Renter` is a user acting as a renter of gear. This role is **entity-backed**: when `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `User`. Ownership checks on any resource that references a renter compare that resource's owning foreign key to `X-User-ID` — for a booking, the check compares `renter_id` to `X-User-ID`.
- `Owner` is a user acting as an owner of listings. This role is likewise **entity-backed**: when `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `User`. Ownership checks compare the owning foreign key of the target resource to `X-User-ID` — for a listing, its `owner_id`; for a booking-scoped owner action, the `owner_id` of the listing the booking references; for a handoff appointment, its `owner_id`.
- `Platform` is the operational operator responsible for verification decisions, claim review and resolution, payout release, and clock/ops control. This role is **opaque**: when `X-User-Role` is `Platform`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `decided_by` on a `VerificationRecord`, `reviewed_by` and `resolved_by` on a `Claim` — but never compares it to any entity's `id`.

A single human may act as both an owner and a renter at different times by presenting the appropriate `X-User-Role`; the underlying `User` `id` is the same.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` outside the inclusive 1–100 range, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_INVALID_REQUEST` (values are never silently clamped).

Unless a specific endpoint states otherwise, all list responses are sorted by the resource's `created_at` timestamp in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the number of items matching the query before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by 1 on every mutation, used for optimistic concurrency control.

The `User`, `VerificationRecord`, `Listing`, `Booking`, `HandoffAppointment`, `Deposit`, `Claim`, and `Payout` resources all carry the full set including `updated_at` and `version`. Two resources are append-only evidence records and therefore carry **only** `id` and `created_at`; they have no `updated_at` and no `version`: the `ConditionReport` and the `Rating`. Any statement below about bumping a resource's `version` or `updated_at` applies only to the versioned resources.

Whenever a workflow mutates a resource — whether by direct client action or by an automatic server-driven cascade — the mutated resource's `updated_at` is refreshed and its `version` is incremented. This applies equally to derived-field updates: when the platform recomputes a `Booking`'s pricing on an approved extension, or captures from a `Deposit`, the touched resource's `version` advances.

### 2.5. Monetary Precision and Rounding Conventions

All monetary amounts in the system are stored and exchanged as integer counts of cents; there are no fractional-cent values in stored fields. Where a calculation multiplies a cent amount by a basis-point rate (a fraction expressed in ten-thousandths, so 10000 basis points equals a factor of 1.0), the intermediate product is rounded to whole cents using the **round half up** method — a value whose fractional part is exactly one half rounds away from zero to the next whole cent.

The precise point at which rounding is applied matters and differs by calculation; each pricing rule in Section 3 states its own rounding order explicitly. Where a rule specifies rounding "per day" or "per unit" before summing, implementers must round each component first and then add — summing raw components and rounding once at the end is a different and incorrect order that will produce off-by-a-cent discrepancies.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC), because in each case a client is acting on a parent resource that another actor may have advanced since the client last read it.

The first guard protects booking creation against a stale listing. A renter quotes a rental price and availability against a specific `Listing`, capturing that listing's `version` at read time, and must submit it as `expected_listing_version` when creating the booking. If the owner has since re-priced, changed the demand multiplier, adjusted quantity, or a prior booking has advanced the listing, the listing's `version` will no longer equal the submitted `expected_listing_version`; the create is then rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412), forcing the renter to re-fetch a fresh quote before committing. The same `expected_listing_version` token guards a direct listing edit: an owner updating a listing's mutable fields must submit `expected_listing_version`, and a mismatch with the listing's current `version` is likewise rejected with `ERR_STALE_LISTING_VERSION`.

The second guard protects claim resolution against a stale deposit. Several claims — for example a `DAMAGE` claim and a `LOSS` claim — may draw on the same booking `Deposit`. When the platform resolves a claim, it must submit `expected_deposit_version` carrying the `version` of the `Deposit` it last read. If another claim has already captured from that deposit in the meantime, the deposit's `version` will have advanced and the resolve is rejected with `ERR_STALE_DEPOSIT_VERSION` (HTTP 412), so the resolver re-reads the remaining held balance before capturing. Both `expected_listing_version` and `expected_deposit_version` are required, non-optional inputs on the operations that take them; endpoints not named here take no version field.

### 2.7. Validation Precedence

When more than one validation could reject a request, the checks are evaluated in a fixed order of precedence, and the first failing check determines the error returned. This ordering is stable across the API and is as follows, from highest precedence to lowest:

1. Authentication — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — role permitted for the operation and, for entity-backed ownership operations, `X-User-ID` matches the owning foreign key, else `ERR_FORBIDDEN` (403).
3. Existence — every path- or body-referenced resource exists, validated left-to-right, else `ERR_NOT_FOUND` (404).
4. State legality — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
5. Referenced-entity state — a required sibling entity is in its required state; for example a booking create or approve requires the listing to be `ACTIVE`, else `ERR_LISTING_NOT_ACTIVE` (409).
6. Renter verification — booking create and pickup require the acting renter to be verified, else `ERR_RENTER_NOT_VERIFIED` (409).
7. Claim settlement gate — payout release requires no unresolved claim on the booking, else `ERR_CLAIM_UNRESOLVED` (409).
8. Availability — the requested rental or extension window does not collide with too many overlapping bookings, else `ERR_LISTING_UNAVAILABLE` (409).
9. Handoff calendar — a scheduled handoff slot plus its buffer does not collide with another on the owner's calendar, else `ERR_HANDOFF_SLOT_CONFLICT` (409).
10. Trust gate — a high-value booking requires sufficient renter trust, else `ERR_TRUST_TOO_LOW` (422).
11. Condition evidence — pickup and return require matching-phase condition photos, else `ERR_CONDITION_PHOTOS_REQUIRED` (422).
12. Stale-version (OCC) — the submitted expected version matches the parent's current `version`, else `ERR_STALE_LISTING_VERSION` or `ERR_STALE_DEPOSIT_VERSION` (412).
13. Award legality — a claim resolution award is within the claimed amount and, for a partial award, strictly inside its bounds, else `ERR_INVALID_AWARD` (422).
14. Request well-formedness — body field types, enums, and ranges are valid, else `ERR_INVALID_REQUEST` (400).
15. Email uniqueness — a registration email is not already in use, else `ERR_DUPLICATE_EMAIL` (409).
16. Extension window — an extension's proposed end is strictly after the current end, else `ERR_EXTENSION_WINDOW_INVALID` (422).
17. Handoff completion — pickup and return require a completed handoff of the matching type, else `ERR_HANDOFF_MISSING` (409).
18. Rating eligibility — a rating requires a completed booking and a participant author, else `ERR_RATING_NOT_ALLOWED` (409).

Only the checks that actually apply to a given endpoint participate; the relative order among those that do apply is the order above.

### 2.8. Nested Resource Retrieval and Filtered Collections

The API uses a flat resource topology: children carry foreign keys and are reached either through single-segment sub-resource reads (a booking's deposit, a booking's payout, a booking's claims, a booking's handoffs, a booking's condition reports, a booking's ratings) or through filtered list endpoints, never through deep multi-segment identifier chains. When a path contains identifiers, each is validated left-to-right, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any deeper work is attempted.

The booking list supports filtering by `listing_id`, by `renter_id`, and by `status`, in addition to the standard `limit` and `offset` pagination parameters. Sub-resource reads such as a booking's deposit or payout return an array of zero or one element, reflecting that at most one such resource exists per booking.

### 2.9. The Logical Clock and System Sweeps

The system operates on a **logical clock** rather than real wall-clock time, so that time-dependent behavior is deterministic and test-drivable. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it reports precisely this default and never the host's real time. A `Platform` operator may advance the clock by supplying a `to_iso8601` instant; the response reports the new `current_utc`. All timestamps that the system stamps from "now" — a verification's `valid_from`, a booking's `actual_return_at`, late-return detection — read the logical clock.

A `Platform`-driven operational sweep detects overdue rentals: it scans every booking currently in the in-progress state whose window has ended before the logical clock and marks each one late, accruing penalties as described in Section 3.6. The sweep responds with `marked_late_count` and the list of affected `booking_ids`.

### 2.10. Deposit Conservation Invariant

Each security `Deposit` is a small ledger whose three balances — `held_cents`, `captured_cents`, and `released_cents` — always sum to `original_amount_cents`. This conservation invariant holds at every point in the deposit's life: money only moves between the three buckets, it is never created or destroyed. Capturing funds for an adjudicated claim moves cents from `held_cents` into `captured_cents`; returning funds to the renter moves cents from `held_cents` into `released_cents`. The deposit's `status` reflects which buckets are populated: `HELD` while everything is still held, `PARTIALLY_CAPTURED` once some but not all held funds have been captured, `CAPTURED` once all originally-held funds have been captured, and `RELEASED` once the held balance has been returned with nothing captured. Every mutation of a deposit's balances increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Accounts and Identity Verification

Anyone may register as a `User` by supplying an `email`, a `full_name`, and a `phone`. The `email` must be unique across all users; a duplicate registration is rejected with `ERR_DUPLICATE_EMAIL`. A newly registered user starts with `verification_status` of `UNVERIFIED`, a `trust_score` of 300, a null `avg_rating`, and zeroed `rating_count`, `late_return_count`, `upheld_claim_count`, and `total_earnings_cents`. These latter fields are all computed reflections of the user's activity — `avg_rating` and `rating_count` derive from ratings left about the user, `late_return_count` and `upheld_claim_count` from their conduct as a renter, and `total_earnings_cents` from released payouts where they were the owner. A user profile can be fetched at any time to read these computed values.

Before a user can rent gear they must verify their identity. A `Renter` or `Owner` submits a verification for themselves — the acting `X-User-ID` must equal the `user_id` being verified — providing a `document_type`, one of `PASSPORT`, `DRIVERS_LICENSE`, or `NATIONAL_ID`, together with an opaque `document_ref` pointing at the uploaded document. Submitting a verification creates a `VerificationRecord` in `PENDING` state and sets the user's `verification_status` to `PENDING`. A user's verification records can be listed, filtered by `user_id` and returned in ascending `created_at` order per Section 2.3.

A `Platform` operator then adjudicates the pending record with a `decision`. On an approve decision, the record transitions from `PENDING` to `APPROVED`: its `valid_from` is set to the current logical clock, its `valid_until` is set to `valid_from` plus 365 days (the verification validity period), the operator's identifier is stored in `decided_by`, and the user's `verification_status` becomes `VERIFIED`. On a reject decision, the record transitions from `PENDING` to `REJECTED`, a `reject_reason` must be supplied, `decided_by` is recorded, and the user's `verification_status` becomes `REJECTED`. A decision may only be applied to a record that is still `PENDING`; otherwise the transition is rejected as an illegal state change.

### 3.2. Listings and the Dynamic Pricing Engine

An `Owner` creates a gear `Listing` by supplying the `owner_id`, a `title`, a free-text `category`, a `declared_value_cents` (the owner-declared replacement value, which must be greater than zero and caps total coverage on a loss claim), a `base_daily_rate_cents` (greater than zero), and a `deposit_cents` (the fixed per-booking security deposit, zero or greater). Two further fields are optional: `quantity`, the number of identical units available, which defaults to 1 and must be at least 1, and `demand_multiplier_bps`, the dynamic demand multiplier in basis points, which defaults to 10000 (a factor of 1.0) and must be at least 5000 and at most 30000. A listing is created in `DRAFT` and also carries a computed `active_booking_count`, the number of its bookings in an availability-consuming state.

A listing becomes rentable when its owner activates it, moving `DRAFT` to `ACTIVE`; the owner may later suspend it, moving `ACTIVE` to `SUSPENDED` (which blocks new bookings but leaves existing bookings untouched), and re-activate it, moving `SUSPENDED` back to `ACTIVE`. Every activation and suspension requires the acting owner to own the listing. An owner may also edit a listing's mutable pricing and availability fields — `base_daily_rate_cents`, `demand_multiplier_bps`, `declared_value_cents`, `deposit_cents`, and `quantity` — in any of the `DRAFT`, `ACTIVE`, or `SUSPENDED` states. Such an edit is OCC-guarded on `expected_listing_version` as described in Section 2.6 and increments the listing's `version`; because it advances the version, an edit is precisely the write that makes a renter's previously-fetched listing version stale.

The heart of listing economics is the **dynamic daily pricing** rule, which produces the rental subtotal for a window. First, `billable_days` is computed as the number of whole days in the half-open interval from `start_date` up to but not including `end_date` — equivalently, the number of nights in the window. A single duration-discount tier is then chosen for the whole window: if `billable_days` is at least 28, the discount is 2500 basis points; otherwise if `billable_days` is at least 7, the discount is 1000 basis points; otherwise there is no duration discount. The subtotal is then built one day at a time, iterating over each date in the window from `start_date` up to but not including `end_date`. For each such day, start from the `base_daily_rate_cents` multiplied by `demand_multiplier_bps` divided by 10000. If that day falls on a Saturday or Sunday, multiply the running figure by 10000 plus the weekend surcharge of 2000 basis points, all divided by 10000 (that is, increase it by twenty percent). Next multiply by 10000 minus the chosen duration discount, divided by 10000. Round that day's figure to whole cents using round half up, and add the rounded day charge to `rental_subtotal_cents`. Rounding happens per day before summing; the accumulated `rental_subtotal_cents` is the sum of the individually rounded day charges, never a single rounding of a raw total. This same computation drives the request-time price, the recomputed price after an approved extension, and the read-only quote.

A renter (or owner) may fetch a live quote for a booking's window, which returns `billable_days`, `rental_subtotal_cents`, `renter_service_fee_cents`, `provisional_total_cents`, and the listing's `deposit_cents` without mutating anything.

### 3.3. Requesting a Booking

A verified `Renter` requests a rental by creating a `Booking` against a listing, supplying the `listing_id`, their own `renter_id`, the `start_date` and `end_date` of the desired window, and the `expected_listing_version` they quoted against. The window is half-open on the interval from `start_date` to `end_date`, and `end_date` must be strictly after `start_date`. Several conditions must all hold for the request to succeed. The listing must exist and be `ACTIVE`, or the request is rejected with `ERR_LISTING_NOT_ACTIVE`. The submitted `expected_listing_version` must match the listing's current `version` under the OCC rule of Section 2.6. The acting renter's `verification_status` must be `VERIFIED`, or the request is rejected with `ERR_RENTER_NOT_VERIFIED`. The window must not collide with availability: counting the listing's other bookings that overlap the requested interval and sit in an availability-consuming state (`REQUESTED`, `APPROVED`, `ACTIVE`, `EXTENSION_REQUESTED`, or `LATE`), that count must be strictly less than the listing's `quantity`, otherwise the request is rejected with `ERR_LISTING_UNAVAILABLE`. Because the interval is half-open, a booking that ends exactly when another begins does not overlap — adjacency is allowed.

A trust gate applies to expensive gear. If the listing's `declared_value_cents` is greater than 100000 cents, the renter's `trust_score` must be at least 300; a renter below that threshold is rejected with `ERR_TRUST_TOO_LOW`.

When all conditions pass, the booking is created in `REQUESTED` status and priced immediately. The system computes `billable_days` and `rental_subtotal_cents` via the dynamic daily pricing rule of Section 3.2, then derives the renter service fee and provisional total via the **booking settlement charge** rule in its provisional form: `renter_service_fee_cents` is the `rental_subtotal_cents` multiplied by 1200 basis points divided by 10000 (twelve percent), rounded to whole cents using round half up on the summed subtotal, and `provisional_total_cents` is `rental_subtotal_cents` plus `renter_service_fee_cents`. The provisional form carries no late fee. Creating the booking also increments the listing's `active_booking_count` by 1 and increments the listing's `version` by 1 — the latter being another write that renders any concurrently-held listing version stale.

A renter may withdraw a booking that is still `REQUESTED` by cancelling it, which transitions it to `CANCELLED` and decrements the listing's `active_booking_count` by 1. Cancellation requires the acting renter to own the booking.

### 3.4. Approval, Handoff Scheduling, and Condition Evidence

The owner of the listing decides the fate of a `REQUESTED` booking. Approving it transitions the booking `REQUESTED → APPROVED` and, as a cascade, creates the security `Deposit` for the booking: its `original_amount_cents` is snapshotted from the listing's `deposit_cents` at approval, its `held_cents` is set equal to that original amount, its `captured_cents` and `released_cents` start at 0, and its `status` is `HELD`. Approval requires the acting owner to own the listing, the booking to be `REQUESTED`, and the listing to still be `ACTIVE`. Declining instead transitions the booking `REQUESTED → DECLINED` and decrements the listing's `active_booking_count` by 1, releasing the availability unit that the request had held. A renter who no longer wants an already-approved booking may cancel it while it is `APPROVED`, transitioning `APPROVED → CANCELLED`: this decrements the listing's `active_booking_count` by 1 and releases the deposit in full — the held balance moves into `released_cents`, `held_cents` becomes 0, and the deposit's `status` becomes `RELEASED`, preserving the conservation invariant. Whenever a booking is declined or cancelled, any still-`SCHEDULED` handoff appointments for that booking are cascaded to `CANCELLED` and the owner's calendar slots are freed.

Physical exchange of the item is arranged through `HandoffAppointment` records, which the owner schedules on their own calendar. Each appointment is created with a `booking_id`, the owner's `owner_id`, a `type` of either `PICKUP` or `RETURN`, and a `slot_start` and `slot_end` (the latter strictly after the former). A pickup handoff may be scheduled while the booking is `APPROVED`; a return handoff while the booking is in progress or overdue. The appointment occupies the interval from `slot_start` to `slot_end` inclusive, extended by a mandatory buffer of 60 minutes on each side. The buffer is applied only to the appointment being scheduled; its buffered, closed interval is tested for intersection against the raw (unbuffered) `slot_start`–`slot_end` of each existing still-`SCHEDULED` handoff on the same owner's calendar, and any such intersection rejects the request with `ERR_HANDOFF_SLOT_CONFLICT`. A new appointment starts in `SCHEDULED`; the owner later marks it `COMPLETED`, moving `SCHEDULED → COMPLETED`, which is what unblocks the corresponding pickup or return. An owner may list their own handoff appointments, and a booking's handoffs may be listed, filtered by `booking_id` and returned in ascending `created_at` order per Section 2.3.

Condition evidence is captured as append-only `ConditionReport` records. Either the owner or the renter records one against a `booking_id` with a `phase` of `PICKUP` or `RETURN`, a non-empty `photo_urls` list carrying at least one photo URL, a `recorded_by` value of `OWNER` or `RENTER`, and optional free-text `notes`. An empty photo set is rejected with `ERR_CONDITION_PHOTOS_REQUIRED`. A booking's condition reports may be listed, filtered by `booking_id` and returned in ascending `created_at` order per Section 2.3.

### 3.5. Pickup, Active Rental, and Extensions

The owner marks an approved item as picked up, transitioning the booking `APPROVED → ACTIVE`. Pickup is heavily gated: the acting owner must own the listing, the booking must be `APPROVED`, the renter's `verification_status` must still be `VERIFIED` (or `ERR_RENTER_NOT_VERIFIED`), a `PICKUP` handoff appointment for the booking must already be `COMPLETED` (or `ERR_HANDOFF_MISSING`), and a `PICKUP` condition report with at least one photo must exist (or `ERR_CONDITION_PHOTOS_REQUIRED`). Once in `ACTIVE`, the item is out on rental.

While a booking is `ACTIVE`, the renter may ask to keep the item longer by requesting an extension, supplying a `new_end_date`. This transitions the booking `ACTIVE → EXTENSION_REQUESTED` and records the proposed end in `extension_requested_end_date` without yet changing the window. The request requires the acting renter to own the booking, the booking to be `ACTIVE`, and the `new_end_date` to be strictly after the current `end_date` (otherwise `ERR_EXTENSION_WINDOW_INVALID`). Availability is re-checked over just the extension interval, from the current `end_date` up to but not including `new_end_date`: the count of other bookings overlapping that interval in an availability-consuming state (`REQUESTED`, `APPROVED`, `ACTIVE`, `EXTENSION_REQUESTED`, `LATE`) must be strictly less than the listing's `quantity`, or the request is rejected with `ERR_LISTING_UNAVAILABLE`.

The owner then decides the pending extension with a `decision`. On approve, the booking transitions `EXTENSION_REQUESTED → ACTIVE`: the `end_date` is set to `extension_requested_end_date`, that field is cleared back to null, and `billable_days`, `rental_subtotal_cents`, `renter_service_fee_cents`, and `provisional_total_cents` are recomputed over the new, longer window using the dynamic daily pricing and provisional settlement rules. This approval also increments the listing's `version` by 1. On decline, the booking also returns `EXTENSION_REQUESTED → ACTIVE` but the `extension_requested_end_date` is simply cleared and the window and pricing are left unchanged. Because approval returns the booking to `ACTIVE`, a renter may request a further extension afterward — the extension cycle may repeat.

### 3.6. Late Returns, Return Settlement, and Payout Creation

When the logical clock passes a booking's `end_date` while it is still `ACTIVE`, the Platform-driven late-return sweep marks it late, transitioning `ACTIVE → LATE`. On that transition the system sets `late_days` to the number of whole days between the booking's `end_date` and the current logical clock, accrues the late fee, increments the renter's `late_return_count` by 1, and recomputes the renter's `trust_score`. The **late fee accrual** rule computes a per-day penalty as the listing's `base_daily_rate_cents` multiplied by 15000 basis points divided by 10000 (one hundred fifty percent of the base daily rate), rounded to whole cents using round half up exactly once; `late_fee_cents` is then that rounded per-day penalty multiplied by `late_days`. The penalty is rounded per late day and then multiplied — summing raw penalties and rounding once is the wrong order.

The owner closes out the rental by marking the item returned, transitioning the booking from either `ACTIVE` or `LATE` to `RETURNED`. Return requires the acting owner to own the listing, the booking to be `ACTIVE` or `LATE`, a `COMPLETED` `RETURN` handoff appointment to exist (or `ERR_HANDOFF_MISSING`), and a `RETURN` condition report with at least one photo to exist (or `ERR_CONDITION_PHOTOS_REQUIRED`). On return, `actual_return_at` is stamped from the logical clock, and the **final** form of the booking settlement charge is computed: `final_total_cents` is `rental_subtotal_cents` plus `renter_service_fee_cents` plus `late_fee_cents`. The final total therefore adds the accrued late fee and, if the window was extended, reflects the re-priced subtotal, so it can exceed the provisional total captured at booking. Return also decrements the listing's `active_booking_count` by 1.

Return additionally creates the owner's `Payout` as a cascade, with `status` `PENDING`. The **owner payout** rule sets `gross_earnings_cents` from a snapshot of the booking's `rental_subtotal_cents` at return — the renter service fee is retained by the platform and is not paid to the owner. `owner_commission_cents` is `gross_earnings_cents` multiplied by 1500 basis points divided by 10000 (fifteen percent), rounded to whole cents using round half up. `damage_reimbursement_cents` starts at 0 for a freshly created payout. `net_payout_cents` is `gross_earnings_cents` minus `owner_commission_cents` plus `damage_reimbursement_cents`. The payout records the `booking_id` and the owner's `owner_id`.

### 3.7. Damage and Loss Claims

After a booking has reached `RETURNED` (or `LATE`, or `COMPLETED`), and provided a deposit exists for it, the listing owner may open a `Claim` for damage or loss. The claim carries the `booking_id`, a `claim_type` of `DAMAGE` (repairable) or `LOSS` (item not returned), a `claimed_amount_cents` greater than zero, and a free-text `description`. Opening a claim creates it in `OPEN` status and computes the provisional form of the **deposit settlement** rule: `provisional_capture_cents` is the smaller of `claimed_amount_cents` and the deposit's current `held_cents`. As a cross-entity cascade, if the booking's `Payout` is currently `PENDING`, opening the claim freezes it by moving the payout `PENDING → HELD`, so no owner money is released while a claim is live. A booking's claims may be listed, filtered by `booking_id` and returned in ascending `created_at` order per Section 2.3.

A `Platform` operator reviews an open claim, moving it `OPEN → UNDER_REVIEW` and recording the operator in `reviewed_by`. The operator then resolves the claim with a `decision`, and the resolve is OCC-guarded on `expected_deposit_version` per Section 2.6. There are three resolution branches, and each is fully specified:

- **Approve** transitions `UNDER_REVIEW → APPROVED`. The `approved_amount_cents` is set to the full `claimed_amount_cents`.
- **Partial** transitions `UNDER_REVIEW → PARTIALLY_APPROVED`. The resolve payload supplies an `approved_amount_cents` that must be strictly greater than 0 and strictly less than `claimed_amount_cents`; a value outside those bounds is rejected with `ERR_INVALID_AWARD`. That payload amount becomes the claim's `approved_amount_cents`.
- **Deny** transitions `UNDER_REVIEW → DENIED`. The `approved_amount_cents`, `deposit_capture_cents`, and `coverage_paid_cents` are all set to 0 and the deposit is left untouched.

For an approved or partially-approved claim, the final deposit settlement is computed identically with the branch's award: `deposit_capture_cents` is the smaller of `approved_amount_cents` and the deposit's current `held_cents`. The platform-backed coverage beyond the deposit, `coverage_paid_cents`, is the award minus the deposit capture — that is `approved_amount_cents` minus `deposit_capture_cents` — but no more than the listing's `declared_value_cents` minus the deposit's `original_amount_cents`, and never below 0; the coverage is the larger of 0 and the smaller of those two quantities. More generally, no resolution may award more than the claimed amount, and no capture may exceed the currently held balance; a violation is `ERR_INVALID_AWARD`.

An approved or partial resolution then drives a cascade. It captures `deposit_capture_cents` from the deposit: those cents move out of `held_cents` and into `captured_cents`, and the deposit's `version` increments. When the capture equals the entire held balance the deposit moves to `CAPTURED`; when it consumes only part of the held balance the deposit moves to `PARTIALLY_CAPTURED`, and a later capture of the remaining held balance moves it on to `CAPTURED`. The booking's payout is then updated: `damage_reimbursement_cents` accumulates the sum, over the booking's resolved (approved or partially-approved) claims, of each claim's `deposit_capture_cents` plus `coverage_paid_cents`, and `net_payout_cents` is recomputed accordingly. Finally the renter's `upheld_claim_count` is incremented by 1 and their `trust_score` is recomputed. A deny resolution performs none of these captures; instead, if it was the last unresolved claim on the booking — no claim remains `OPEN` or `UNDER_REVIEW` — and the payout is currently `HELD`, the payout is unfrozen back to `PENDING`.

### 3.8. Owner Payout Release and Booking Completion

Once every claim on a booking has been adjudicated, the owner's earnings can be released. Releasing the payout requires that the booking's `Payout` be `PENDING` or `HELD` and that no `Claim` on the booking remain `OPEN` or `UNDER_REVIEW`; an attempt while any claim is still unresolved is rejected with `ERR_CLAIM_UNRESOLVED`. Release may be performed by the `Platform` or by the `Owner`. It moves the payout to `RELEASED` and, as a cascade, transitions the booking `RETURNED → COMPLETED` — the terminal booking state, reachable only after all claims are settled. Release also settles the deposit remainder: whatever is still in `held_cents` moves into `released_cents` and `held_cents` becomes 0, so the deposit ends `RELEASED` when nothing was ever captured, or `CAPTURED` with its remainder released when some funds were captured, always preserving the conservation invariant. On release, the owner's `total_earnings_cents` is increased by the payout's `net_payout_cents`.

### 3.9. Ratings and the Trust Score

After a booking is `COMPLETED`, the two participants may rate each other. A rating is authored against a `booking_id` by a `rater_id` (which must equal `X-User-ID`) about a `ratee_id`, with a `direction` of `RENTER_TO_OWNER` or `OWNER_TO_RENTER`, an integer `score` from 1 to 5, and an optional free-text `comment`. A rating is only allowed when the booking is `COMPLETED` and the author is a participant — the booking's renter or the listing's owner; otherwise it is rejected with `ERR_RATING_NOT_ALLOWED`. Ratings are append-only. A booking's ratings may be listed, filtered by `booking_id` and returned in ascending `created_at` order per Section 2.3, and a user's ratings — those they authored via `rater_id` or received via `ratee_id` — may be listed as well in that same ascending `created_at` order. Creating a rating recomputes the ratee's `avg_rating` (the mean of the `score` values of ratings about them, or null when they have none), their `rating_count`, and their `trust_score`.

The **trust score** is a weighted reputation figure recomputed on rating creation, on late-return detection, and on an upheld (approved or partially-approved) claim. It begins from a base of 300. A rating term is added: when the user has at least one rating, the term is 40 points per star times the quantity `avg_rating` minus 3.0, rounded to the nearest whole number using round half up; when the user has no ratings the rating term is 0. From that running figure, subtract 25 points for each late return the user has as a renter (`late_return_count`) and subtract 40 points for each upheld claim against them as a renter (`upheld_claim_count`). The result is then clamped to the integer range 0 to 500 — values below 0 become 0 and values above 500 become 500 — and stored as `trust_score`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource, and read operations, return `200 OK`. Request and response bodies, and the side effects each operation triggers, are specified by the workflow narratives in Section 3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/users` | Register a new user | Anonymous |
| GET | `/users/{id}` | Fetch a user profile including computed trust and counters | Renter, Owner, Platform |
| POST | `/users/{id}/verifications` | Submit an ID verification for self | Renter, Owner |
| GET | `/users/{id}/verifications` | List a user's verification records | Renter, Owner, Platform |
| POST | `/verifications/{id}/decide` | Approve or reject a pending verification | Platform |
| POST | `/listings` | Create a gear listing (starts DRAFT) | Owner |
| GET | `/listings/{id}` | Fetch a listing | Renter, Owner, Platform |
| GET | `/users/{id}/listings` | List an owner's listings | Renter, Owner, Platform |
| PATCH | `/listings/{id}` | Update mutable listing pricing/availability fields (OCC) | Owner |
| POST | `/listings/{id}/activate` | Move a listing DRAFT/SUSPENDED to ACTIVE | Owner |
| POST | `/listings/{id}/suspend` | Move a listing ACTIVE to SUSPENDED | Owner |
| POST | `/bookings` | Create a rental request (OCC on listing version) | Renter |
| GET | `/bookings/{id}` | Fetch a booking with computed pricing/settlement | Renter, Owner, Platform |
| GET | `/bookings` | List bookings, filterable by listing, renter, or status | Renter, Owner, Platform |
| GET | `/bookings/{id}/quote` | Current dynamic-pricing quote for the booking window | Renter, Owner |
| POST | `/bookings/{id}/approve` | Owner approves a request; creates the deposit hold | Owner |
| POST | `/bookings/{id}/decline` | Owner declines a request; releases availability | Owner |
| POST | `/bookings/{id}/cancel` | Renter cancels a REQUESTED or APPROVED booking | Renter |
| POST | `/bookings/{id}/pickup` | Owner marks the item picked up | Owner |
| POST | `/bookings/{id}/return` | Owner marks the item returned; finalizes and pays out | Owner |
| POST | `/bookings/{id}/extensions` | Renter requests to extend the rental window | Renter |
| POST | `/bookings/{id}/extension-decision` | Owner approves or declines a pending extension | Owner |
| POST | `/bookings/{id}/handoffs` | Owner schedules a pickup or return handoff | Owner |
| GET | `/bookings/{id}/handoffs` | List a booking's handoffs | Renter, Owner, Platform |
| GET | `/users/{id}/handoffs` | List an owner's handoff appointments | Owner, Platform |
| POST | `/handoffs/{id}/complete` | Owner marks a scheduled handoff completed | Owner |
| POST | `/bookings/{id}/condition-reports` | Record pickup or return condition photos | Owner, Renter |
| GET | `/bookings/{id}/condition-reports` | List a booking's condition reports | Renter, Owner, Platform |
| POST | `/bookings/{id}/claims` | Owner opens a damage/loss claim; freezes the payout | Owner |
| GET | `/bookings/{id}/claims` | List a booking's claims | Renter, Owner, Platform |
| POST | `/claims/{id}/review` | Platform moves a claim OPEN to UNDER_REVIEW | Platform |
| POST | `/claims/{id}/resolve` | Platform adjudicates a claim (OCC on deposit version) | Platform |
| GET | `/bookings/{id}/deposit` | Fetch the booking's deposit ledger | Renter, Owner, Platform |
| POST | `/payouts/{id}/release` | Release the owner payout; completes the booking | Platform, Owner |
| GET | `/bookings/{id}/payout` | Fetch the booking's payout | Renter, Owner, Platform |
| GET | `/users/{id}/payouts` | List an owner's payouts | Owner, Platform |
| POST | `/bookings/{id}/ratings` | Leave a rating for the counterparty | Renter, Owner |
| GET | `/bookings/{id}/ratings` | List a booking's ratings | Renter, Owner, Platform |
| GET | `/users/{id}/ratings` | List ratings authored by or about a user | Renter, Owner, Platform |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical clock | Platform |
| POST | `/_ops/detect-late-returns` | System sweep: mark overdue ACTIVE bookings LATE | Platform |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_RENTER_NOT_VERIFIED` | 409 |
| `ERR_LISTING_UNAVAILABLE` | 409 |
| `ERR_HANDOFF_SLOT_CONFLICT` | 409 |
| `ERR_HANDOFF_MISSING` | 409 |
| `ERR_CONDITION_PHOTOS_REQUIRED` | 422 |
| `ERR_EXTENSION_WINDOW_INVALID` | 422 |
| `ERR_TRUST_TOO_LOW` | 422 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_STALE_DEPOSIT_VERSION` | 412 |
| `ERR_INVALID_AWARD` | 422 |
| `ERR_CLAIM_UNRESOLVED` | 409 |
| `ERR_RATING_NOT_ALLOWED` | 409 |

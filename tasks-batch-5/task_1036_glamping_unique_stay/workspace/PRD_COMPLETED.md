# Glamping & Unique-Stay Booking API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Glamping & Unique-Stay Booking API, a marketplace platform in the spirit of Hipcamp that connects independent land hosts with travellers seeking distinctive overnight experiences — yurts, cabins, treehouses, geodesic domes, and refurbished airstreams. The platform's central challenge is reconciling three moving surfaces at once: a calendar of availability that must never be double-booked, a seasonal pricing engine whose rates the host may revise at any moment, and a two-sided ledger that has to split every dollar cleanly between guest refunds, host earnings, and platform fees.

Around that core, the system also governs the regulatory path a listing must walk before it can accept guests (land-use permits filed with local authorities and reviewed by an operational reviewer), the amenity and experience add-ons a host can attach to a stay, and the post-stay concerns of reviews and guest-host messaging. Because pricing and availability are read by a guest before they commit and can change underneath them, the platform leans on optimistic concurrency and on a strict separation between the price a guest is *quoted* and the price that is ultimately *locked*. Every workflow below is written so that money is conserved at each terminal outcome and so that no participant can act on a stale view of a listing.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that hold across every endpoint. Domain-specific workflow logic lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `Host`, `Guest`, `PermitReviewer`, and `PlatformAdmin`.

- When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`; ownership checks on any resource that references a `Host` compare that resource's owning-host linkage to `X-User-ID`. A host owns its listings and everything filed beneath them — permits, seasonal rates, add-ons, and experience slots — as well as the host-side lifecycle of bookings made against its own listings.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any resource that references a `Guest` compare the resource's `guest_id` to `X-User-ID`. A guest owns the bookings it creates and the reviews it writes.
- When `X-User-Role` is `PermitReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. This role is the only one authorized to decide permits.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. Platform administrators onboard hosts and guests, control the logical clock, and may read any resource.

When an `entity_backed` principal (a `Host` or a `Guest`) attempts an ownership-guarded mutation on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This is distinct from `ERR_FORBIDDEN`: the role is capable of the operation in general, but not on this particular resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a common set of system-managed fields. Every `Host`, `Guest`, `Listing`, `Permit`, `SeasonalRate`, `AddOn`, `ExperienceSlot`, `Booking`, and `Payout` includes:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that begins at 1 and increments by one on every mutation of the resource. It underpins the optimistic concurrency mechanism described in §2.7.

Two resources are deliberately lighter. A `Review` and a `Message` are append-only and immutable once written; each carries only an `id` and a `created_at`. Neither an `updated_at` nor a `version` field is present on a `Review` or a `Message`, and they are never mutated after creation.

Whenever a computed field on a resource changes as a downstream consequence of some other action — for example when a host's `pending_payout_cents` moves because one of its payouts settled, or when a listing's `reserved_nights_count` changes because a booking was confirmed or released — that change is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. The Logical Clock and Temporal Gating

Because check-in eligibility and cancellation refund tiers both depend on "today," the platform runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly moved it stays at that value and never falls back to the host machine's real time. A platform administrator advances it by supplying a target instant in the `to_iso8601` field; the supplied instant becomes the new "now" that governs the days-before-check-in computation and the check-in date gate. All date comparisons in this specification — window coverage, check-in eligibility, refund tiers — are evaluated against this logical clock.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer counts of cents. Wherever a calculation multiplies a cents amount by a rate or a percentage — a fee, a discount, a refund fraction — the product is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger magnitude). The precise point at which rounding is applied matters and is specified per calculation in Section 3; as a rule, sums are accumulated first and the rate is applied to the sum, then the result is rounded once, rather than rounding each term individually.

### 2.7. Optimistic Concurrency on Listings

A guest quotes a prospective stay against a particular snapshot of a listing — its availability and its seasonal pricing surface at the moment of reading. That surface can shift underneath the guest: accepting another booking on the listing bumps the listing's `version`, and publishing or repricing a seasonal rate window bumps it as well. To stop a guest from committing against a projection it can no longer trust, a booking-request write must carry `expected_listing_version` as a mandatory field.

Specifically, a booking-request write against a listing requires `expected_listing_version` to equal the target listing's current `version`. If another writer has advanced the listing's `version` since the guest last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the guest must re-read the listing and re-quote before trying again. This optimistic-concurrency check guards only the booking-request write; no other endpoint accepts or requires a version field, and endpoints not named here do not perform a version comparison.

### 2.8. Cascading State Propagation

A single operation on a parent resource frequently forces state changes on its children, and those changes cascade further into the ledger. Three propagation patterns recur throughout Section 3, and each is a first-class part of the contract:

- **Suspension propagation.** When a listing leaves `LISTED` for `SUSPENDED` — whether a host suspends it directly or the system suspends it because the listing's permit was rejected — every booking on that listing still sitting in `REQUESTED` is moved to `DECLINED`. No payout was ever scheduled for a `REQUESTED` booking, so nothing is released on the ledger.
- **Rejection propagation.** When a reviewer rejects a permit, and the listing that permit belongs to is currently `LISTED`, the listing is driven to `SUSPENDED`, which in turn triggers the suspension propagation above.
- **Delist propagation.** Delisting is terminal and unwinds live commitments. Each of these cascades and the exact ledger arithmetic they carry are specified in §3.2 and §3.8.

Every reconciliation that touches a parent or sibling resource independently refreshes that resource's `updated_at` and increments its `version`, per §2.4.

### 2.9. Nested Resource Retrieval and the Order of Validation

Many paths address a resource nested beneath a parent — a listing's permits, an add-on's slots, a booking's messages. Path identifiers are validated left to right, and the first identifier that names a non-existent resource produces `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier or body content is examined.

More broadly, every request is validated in a fixed priority order, and the first failing check determines the error returned:

1. Authentication of the headers first — a missing header or unknown role yields `ERR_UNAUTHENTICATED`.
2. Then role authorization for the operation — `ERR_FORBIDDEN` when the role may not perform it.
3. Then resource ownership for `entity_backed` principals — `ERR_NOT_RESOURCE_OWNER` when a host or guest acts on something it does not own.
4. Then existence of every path- and body-referenced resource — `ERR_NOT_FOUND`.
5. Then body well-formedness — required fields present, enum values legal, integers within range, `rating` between 1 and 5 inclusive, dates parseable, and `check_out` strictly after `check_in` — any breach yields `ERR_VALIDATION` (HTTP 400).
6. Then the target's state admits the requested transition — a generic mismatch yields `ERR_INVALID_STATE` (HTTP 400).
7. Then endpoint-specific state and business rules, described in Section 3.

This ordering means, for example, that a caller who is both unauthenticated and pointing at a missing resource always sees the authentication error first. Where an endpoint layers several business checks, the per-endpoint ordering is called out in the workflow narrative that owns it.

### 2.10. The Money-Conservation Principle

Every booking is a self-contained ledger, and the platform guarantees that money is conserved at each terminal outcome. What the guest is on the hook for at confirmation time — the locked `final_total_cents` — always equals the sum of three disjoint parts: whatever is refunded to the guest's wallet, whatever the host ultimately earns, and whatever the platform retains as revenue. On a clean completion the guest refund is zero, the host earns the settled payout, and the platform keeps the guest fee plus the host fee. On a cancellation the guest refund is the computed refund amount, the host earns its retained share, and the platform keeps the guest fee plus the host fee assessed on the host's retained portion. The guest-facing service fee is platform revenue and is never returned to a guest under any circumstance.

The host's running ledger reflects this. A host's `pending_payout_cents` is the total `estimated_amount_cents` across that host's payouts still in `SCHEDULED` status — a conserved projection of money owed. A host's `paid_out_cents` is the total `final_amount_cents` across that host's payouts that have settled to `PAID` or `PARTIAL`. A host's `completed_stays_count` is the number of that host's bookings that have reached `COMPLETED`. A guest's `wallet_credit_cents` accumulates the refunds it receives from cancellations. A listing's `reserved_nights_count` is the total `nights` across that listing's bookings currently in `CONFIRMED` or `CHECKED_IN` — a conserved occupancy quantity that rises on confirmation and falls on release.

## 3. Business Logic & Workflows

### 3.1. Onboarding Hosts and Guests

The two human parties enter the system through a platform administrator. Onboarding a host records a `display_name` and a contact `email`, and optionally a `payout_method`, which is one of `BANK` or `PAYPAL` and defaults to `BANK` when omitted. A freshly created host starts with an empty ledger: `pending_payout_cents`, `paid_out_cents`, and `completed_stays_count` all begin at 0. Onboarding a guest likewise records a `display_name` and an `email`; a new guest begins with `wallet_credit_cents` of 0. Both hosts and guests are readable by the `Host`, `Guest`, and `PlatformAdmin` roles (a `PermitReviewer` requesting either is rejected with `ERR_FORBIDDEN`), and the host record deliberately exposes its payout ledger fields so a host can watch earnings accrue.

### 3.2. Building a Listing and Clearing the Permit Gate

A host creates a listing whose `status` field begins at `DRAFT`. Creation captures the owning `host_id`, a `title`, a `site_type` — one of `YURT`, `CABIN`, `TREEHOUSE`, `DOME`, or `AIRSTREAM` — and a `max_guests` value of at least 1. Several economics fields are set here too: `min_nights` (the default floor on stay length, at least 1, defaulting to 1 when omitted), `base_nightly_rate_cents` as reference metadata (a required field with no default, at least 0), a flat per-stay `cleaning_fee_cents` (at least 0, defaulting to 0), and a `cancellation_policy` of `FLEXIBLE`, `MODERATE`, or `STRICT`, defaulting to `MODERATE`. Note that `base_nightly_rate_cents` is metadata only; actual pricing always comes from seasonal rate windows (§3.3), and a stay night not covered by any window is refused. A new listing's `reserved_nights_count` is 0 and its `version` is 1.

Before a listing can host anyone, it must clear a land-use permit. A host files a permit against the listing, recording the `listing_id`, a `permit_type` of `CAMPING`, `STRUCTURE`, or `SPECIAL_USE`, the issuing `authority_name`, and an optional `valid_until` expiry (an ISO 8601 instant, or null for a perpetual permit). A newly filed permit is in `DRAFT`, with `review_notes` null until a decision is rendered.

Submitting a permit moves it from `DRAFT` to `SUBMITTED`. As a side effect, if the parent listing was still in `DRAFT`, that submission advances the listing from `DRAFT` to `PENDING_PERMIT`. A permit reviewer then renders a decision by supplying an `outcome` of either `APPROVE` or `REJECT`, together with optional `review_notes`. An `APPROVE` outcome moves the permit from `SUBMITTED` to `APPROVED` and stores the supplied notes; the decision is only valid while the permit is in `SUBMITTED`, and any decision attempted on a permit not in `SUBMITTED` is rejected with `ERR_PERMIT_ALREADY_DECIDED` (HTTP 400). A `REJECT` outcome moves the permit from `SUBMITTED` to `REJECTED`, stores the notes, and cascades: if the listing was `LISTED`, it is driven to `SUSPENDED`, and that suspension in turn declines every `REQUESTED` booking on the listing (§2.8). A rejected permit is not the end of the road — a host may revise and resubmit, which moves the permit from `REJECTED` back to `SUBMITTED` and clears `review_notes` to null.

With an `APPROVED` permit and at least one seasonal rate on the books, a host publishes the listing, transitioning it from `PENDING_PERMIT` to `LISTED`. Publication has two gates beyond the state check: the listing's permit must be `APPROVED`, else the request is rejected with `ERR_PERMIT_NOT_APPROVED` (HTTP 400), and at least one `SeasonalRate` must exist on the listing, else the request is rejected with `ERR_INVALID_STATE` (HTTP 400). A host may suspend a `LISTED` listing, moving it to `SUSPENDED` and declining its `REQUESTED` bookings as above. Reinstating a `SUSPENDED` listing returns it to `LISTED`, but only when the listing's permit is still `APPROVED` — otherwise the reinstatement is likewise rejected with `ERR_PERMIT_NOT_APPROVED`. Finally, a host may delist a listing from any non-terminal status (`DRAFT`, `PENDING_PERMIT`, `LISTED`, or `SUSPENDED`), driving it to the terminal `DELISTED` state; delisting is refused only if the listing is already `DELISTED`. The ledger consequences of delisting live bookings are detailed in §3.8.

### 3.3. Seasonal Rates and Pricing Windows

Pricing is expressed as a set of non-overlapping date windows on a listing. A host adds a seasonal rate by supplying the `listing_id`, a `start_date` (inclusive), an `end_date` (exclusive), a `nightly_rate_cents` value of at least 0, and an optional `min_nights_override`. A night dated D is covered by a window when its date falls on or after `start_date` and strictly before `end_date`; the half-open convention means adjacent windows may abut at a shared boundary without overlapping. A new window that would overlap an existing window on the same listing is rejected with `ERR_RATE_OVERLAP` (HTTP 409). Adding a seasonal rate increments the parent listing's `version` by 1, since it changes the pricing surface guests quote against.

A host may reprice an existing window, changing its `nightly_rate_cents` and/or its `min_nights_override` without moving its dates; repricing also increments the parent listing's `version` by 1. The `min_nights_override`, when set on the window that contains a booking's `check_in` date, supersedes the listing's `min_nights` as the effective minimum stay length for that booking; when unset, the listing's `min_nights` applies.

### 3.4. Amenities, Experiences, and Their Slots

A host enriches a listing with add-ons. Each add-on records the parent `listing_id`, a display `name`, a `category` of either `AMENITY` or `EXPERIENCE`, a `pricing_unit` of `PER_STAY`, `PER_NIGHT`, or `PER_GUEST`, and a `price_cents` of at least 0. A new add-on is `ACTIVE`; an add-on may later be `RETIRED`, and a `RETIRED` add-on cannot be attached to new bookings.

An `EXPERIENCE` add-on — a guided hike, a sunrise paddle — runs on specific dates with limited capacity, modelled as experience slots. A host creates a slot under an add-on with the `add_on_id`, a `slot_date`, and a `max_participants` capacity of at least 1. Each slot tracks `reserved_participants`, which starts at 0 and is defined as the sum of `participant_count` across every add-on line that references this slot on bookings currently in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status. Because that set excludes declined and cancelled bookings, releasing a booking recomputes the affected slots' `reserved_participants` downward.

### 3.5. Requesting a Stay and Quoting the Price

A guest initiates a stay by requesting a booking against a listing. The request carries the `listing_id`, the guest's own `guest_id`, a `check_in` date (inclusive), a `check_out` date (exclusive), a `guest_count` of at least 1, and the `expected_listing_version` demanded by the optimistic-concurrency rule of §2.7. The booking is created in `REQUESTED` with `payment_status` of `PENDING`, its `add_ons` array empty, and the listing's current `cleaning_fee_cents` captured onto the booking as `cleaning_fee_snapshot_cents`. The occupancy interval is the half-open range from `check_in` up to but not including `check_out`, and `nights` is the whole number of days between them. Creating the request increments the listing's `version` by 1.

Several gates guard the request, evaluated in this order: the listing must currently be `LISTED`, else `ERR_LISTING_NOT_LISTED` (HTTP 400); every night of the stay must be covered by a seasonal rate window, else `ERR_NO_RATE_FOR_DATES` (HTTP 400); the stay must be at least the effective minimum nights — the covering window's `min_nights_override` if the `check_in` window sets one, otherwise the listing's `min_nights` — else `ERR_MIN_NIGHTS_NOT_MET` (HTTP 400); the `guest_count` must not exceed the listing's `max_guests`, else `ERR_MAX_GUESTS_EXCEEDED` (HTTP 400); and finally, as the last gate, `expected_listing_version` must match the listing's current `version`, else `ERR_STALE_VERSION` (HTTP 412).

At request time the system computes a provisional guest total and stores it as `quoted_total_cents`, using the rates and add-on prices then in effect. The computation proceeds as follows. For each night in the stay, the nightly rate is the `nightly_rate_cents` of the seasonal window covering that night's date; the nightly subtotal is the sum of those per-night rates. A length-of-stay discount is then selected as the single most favourable applicable tier: a monthly discount of 28 percent applies when the stay is 28 nights or longer, otherwise a weekly discount of 10 percent applies when the stay is 7 nights or longer, otherwise no discount applies. The discounted nightly amount is the nightly subtotal multiplied by one minus the chosen discount fraction, with that product rounded once, half-up, to a whole cent — the discount is applied to the summed subtotal, never to each night individually.

Add-on lines are then priced. Each line's contribution to the add-ons subtotal is its `line_total_cents`, computed from the add-on's `pricing_unit`: a `PER_STAY` line contributes its `price_cents` once; a `PER_NIGHT` line contributes `price_cents` multiplied by `nights`; a `PER_GUEST` line contributes `price_cents` multiplied by `guest_count`. The stay subtotal is the discounted nightly amount plus the add-ons subtotal plus `cleaning_fee_snapshot_cents`. A guest service fee of 12 percent is applied to that subtotal — computed on the summed subtotal and then rounded once, half-up — and `quoted_total_cents` is the subtotal plus that guest fee.

A guest may attach amenity and experience lines to a still-`REQUESTED` booking before the host acts. Attaching supplies the `add_on_id`, and for an experience, the `experience_slot_id` and a `participant_count` (which defaults to 1 when omitted). Each attached line records the `add_on_id`, the `experience_slot_id` (null for amenity lines), the `participant_count`, a `unit_price_snapshot_cents` capturing the add-on's `price_cents` at attach time, and the resulting `line_total_cents`; attaching re-computes `quoted_total_cents`. Attachment enforces a chain of referential and capacity rules: the add-on must belong to the booking's listing and be `ACTIVE`, else `ERR_ADDON_NOT_OFFERED` (HTTP 400); a referenced experience slot must belong to the referenced add-on, else `ERR_ADDON_LISTING_MISMATCH` (HTTP 400); an `EXPERIENCE` line must reference an `experience_slot_id` and an `AMENITY` line must not, else `ERR_EXPERIENCE_SLOT_REQUIRED` (HTTP 400); the slot's `slot_date` must fall within the booking's stay interval from `check_in` up to but not including `check_out`, else `ERR_SLOT_DATE_OUT_OF_RANGE` (HTTP 400); and the slot's `reserved_participants` plus the new `participant_count` must not exceed the slot's `max_participants`, else `ERR_SLOT_CAPACITY_EXCEEDED` (HTTP 409).

### 3.6. Host Review: Accepting, Declining, and Locking the Price

A host reviews inbound requests. Declining a `REQUESTED` booking moves it to `DECLINED` and releases any experience-slot participants it was holding, so the affected slots' `reserved_participants` fall accordingly.

Accepting a `REQUESTED` booking moves it to `CONFIRMED` and is the decisive commitment. Acceptance is gated: the listing must still be `LISTED`, else `ERR_LISTING_NOT_LISTED`, and the requested interval from `check_in` up to but not including `check_out` must not overlap any booking on the listing already in `CONFIRMED` or `CHECKED_IN`, else `ERR_DATES_UNAVAILABLE` (HTTP 409). On acceptance the guest total is re-computed and locked as `final_total_cents`, using exactly the same formula as the request-time quote but evaluated against the seasonal rates and add-on prices in effect at accept time. Consequently `final_total_cents` diverges from `quoted_total_cents` precisely when the host changed a covering window's `nightly_rate_cents` or an add-on's `price_cents` between request and accept; until acceptance, `final_total_cents` is null.

Acceptance also schedules the host's earnings. A `Payout` is created in `SCHEDULED` status carrying an `estimated_amount_cents`, the host's projected net assuming the stay completes. That projection works from the same locked components: take the discounted nightly amount plus the add-ons subtotal — this stay-and-add-ons figure deliberately excludes the cleaning fee and the guest service fee — multiply it by the 3 percent host fee and round once, half-up, to get the host fee; then `estimated_amount_cents` is the discounted nightly amount plus the add-ons subtotal plus `cleaning_fee_snapshot_cents` minus that host fee. In effect the host keeps the full cleaning fee, while the platform takes its 12 percent guest fee from the guest and its 3 percent host fee from the host's stay-and-add-ons revenue. When the payout is scheduled, the host's `pending_payout_cents` rises by `estimated_amount_cents`, and the listing's `reserved_nights_count` rises by the booking's `nights`.

### 3.7. The Stay: Check-in, Completion, and Settlement

Once confirmed, a stay proceeds along the calendar. A host checks a guest in, moving the booking from `CONFIRMED` to `CHECKED_IN`, but only once the logical clock's date has reached the `check_in` date; an attempt before then is rejected with `ERR_CHECKIN_TOO_EARLY` (HTTP 400).

Completing a `CHECKED_IN` booking moves it to `COMPLETED` and settles the ledger cleanly. The booking's `payment_status` advances from `PENDING` to `PAID`. The scheduled payout moves from `SCHEDULED` to `PAID`, and its `final_amount_cents` is set equal to its `estimated_amount_cents` — a clean completion pays the full projected estimate. The host's ledger then reconciles: `pending_payout_cents` falls by that `estimated_amount_cents`, `paid_out_cents` rises by the settled `final_amount_cents`, and `completed_stays_count` increases by 1. The payout for a booking is retrievable on its own via `GET /bookings/{id}/payout`, which returns an array-typed envelope (with pagination `meta`) holding that single payout, or an empty array when none exists; a booking has either zero or one payout.

### 3.8. Cancellations, Refunds, and Delisting

A guest may cancel a booking that is in `CONFIRMED` or `CHECKED_IN`; a cancellation attempt on a booking in any other status is rejected with `ERR_BOOKING_NOT_CANCELLABLE` (HTTP 400). Cancellation splits the locked money three ways, and the split turns on how far ahead of check-in the cancellation lands.

The refundable base is the discounted nightly amount plus the add-ons subtotal plus `cleaning_fee_snapshot_cents` — everything the guest paid except the guest service fee, which is platform revenue and never refundable. The days-before figure is the whole number of days from the logical clock's current date to the booking's `check_in` date. The refund fraction is then chosen by the listing's `cancellation_policy`:

- Under `FLEXIBLE`, the full base is refunded when the cancellation is at least 1 day before check-in, and nothing is refunded otherwise.
- Under `MODERATE`, the full base is refunded when the cancellation is at least 7 days before check-in; a half refund applies when it is at least 1 day before check-in but fewer than 7; and nothing is refunded otherwise.
- Under `STRICT`, a half refund applies when the cancellation is at least 14 days before check-in, and nothing is refunded otherwise.

The `refund_amount_cents` is the refundable base multiplied by the chosen fraction, rounded once, half-up. The guest's `wallet_credit_cents` rises by that refund. The booking's `payment_status` becomes `REFUNDED` when the refund equals the full refundable base, or `PARTIALLY_REFUNDED` when the refund is greater than zero but less than the full base; when the refund is zero it is left unchanged at `PENDING`.

The host's cancellation payout is computed from what remains after the guest's refund. The host's retained gross is the refundable base minus `refund_amount_cents`; the host fee on that retained portion is the retained gross multiplied by the 3 percent host fee, rounded once, half-up; and the host's cancellation earning is the retained gross minus that fee. The scheduled payout settles to `VOIDED` with `final_amount_cents` of 0 when the host's cancellation earning is 0, or to `PARTIAL` with `final_amount_cents` equal to that earning otherwise. The host's `pending_payout_cents` falls by the original `estimated_amount_cents`, and `paid_out_cents` rises by the payout's settled `final_amount_cents`. The listing's `reserved_nights_count` falls by the booking's `nights`.

Delisting a listing is a host-fault event that unwinds every live booking on it. Only bookings on the listing in `CONFIRMED` or `CHECKED_IN` are unwound; any booking still in `REQUESTED` is left untouched (delisting does not decline it). Each booking on the listing in `CONFIRMED` or `CHECKED_IN` is moved to `CANCELLED` with a full refund — the refund fraction is forced to the full base regardless of the listing's `cancellation_policy`, so the host retains nothing. For each such cancelled booking, its scheduled payout is `VOIDED` with `final_amount_cents` of 0; the host's `pending_payout_cents` is decremented by that payout's `estimated_amount_cents`; the booking's `refund_amount_cents` is credited to the guest's `wallet_credit_cents`; the booking's `payment_status` becomes `REFUNDED`; and the listing's `reserved_nights_count` is decremented by that booking's `nights`. Across all of these outcomes — completion, cancellation, and delist — the per-booking money-conservation identity of §2.10 holds.

### 3.9. Reviews and Messaging

After a stay concludes, a guest may leave one review. A review is permitted only when the booking has reached `COMPLETED`; an attempt against a booking in any other status is rejected with `ERR_REVIEW_NOT_ALLOWED` (HTTP 400). A review captures the `booking_id`, an integer `rating` from 1 to 5 inclusive, and an optional free-text `comment`. Only one review may exist per booking; a second attempt is rejected with `ERR_DUPLICATE_REVIEW` (HTTP 409). Reviews are append-only and immutable.

Throughout a booking's life, the host and guest parties may exchange messages scoped to that booking. A message records the `booking_id`, a `sender_role` of either `HOST` or `GUEST`, the message `body`, and a `sender_id` taken from the acting principal's `X-User-ID` — identity only, never a business input. Messages are append-only and immutable, and a booking's thread is readable by either party and by platform staff.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state-transition action, add-on attachment, and the clock control — return `200 OK`. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/hosts` | Onboard a host | PlatformAdmin |
| GET | `/hosts/{id}` | Get a host, including payout ledger fields | Host, Guest, PlatformAdmin |
| POST | `/guests` | Onboard a guest | PlatformAdmin |
| GET | `/guests/{id}` | Get a guest, including wallet credit | Guest, Host, PlatformAdmin |
| POST | `/listings` | Create a listing (DRAFT) | Host |
| GET | `/listings/{id}` | Get a listing | Host, Guest, PlatformAdmin |
| GET | `/listings` | List/filter listings | Host, Guest, PlatformAdmin |
| POST | `/listings/{id}/publish` | Publish a listing | Host |
| POST | `/listings/{id}/suspend` | Suspend a listing | Host, PlatformAdmin |
| POST | `/listings/{id}/reinstate` | Reinstate a suspended listing | Host |
| POST | `/listings/{id}/delist` | Permanently delist a listing | Host |
| POST | `/listings/{id}/permits` | File a land-use permit for a listing | Host |
| GET | `/listings/{id}/permits` | List a listing's permits | Host, Guest, PlatformAdmin |
| POST | `/permits/{id}/submit` | Submit or resubmit a permit | Host |
| POST | `/permits/{id}/decision` | Approve or reject a submitted permit | PermitReviewer |
| POST | `/listings/{id}/seasonal-rates` | Add a seasonal rate window | Host |
| GET | `/listings/{id}/seasonal-rates` | List a listing's seasonal rates | Host, Guest, PlatformAdmin |
| PATCH | `/seasonal-rates/{id}` | Reprice a seasonal-rate window | Host |
| POST | `/listings/{id}/add-ons` | Create an amenity/experience add-on | Host |
| GET | `/listings/{id}/add-ons` | List a listing's add-ons | Host, Guest, PlatformAdmin |
| GET | `/add-ons/{id}` | Get an add-on | Host, Guest, PlatformAdmin |
| POST | `/add-ons/{id}/slots` | Create an experience slot | Host |
| GET | `/add-ons/{id}/slots` | List an add-on's slots | Host, Guest, PlatformAdmin |
| POST | `/listings/{id}/bookings` | Request a booking (REQUESTED) | Guest |
| GET | `/bookings/{id}` | Get a booking | Host, Guest, PlatformAdmin |
| GET | `/bookings` | List/filter bookings | Host, Guest, PlatformAdmin |
| POST | `/bookings/{id}/add-ons` | Attach an amenity/experience line | Guest |
| POST | `/bookings/{id}/accept` | Accept a booking | Host |
| POST | `/bookings/{id}/decline` | Decline a booking | Host |
| POST | `/bookings/{id}/check-in` | Check a guest in | Host |
| POST | `/bookings/{id}/complete` | Complete a stay | Host |
| POST | `/bookings/{id}/cancel` | Cancel a booking | Guest |
| GET | `/bookings/{id}/payout` | Get the payout for a booking | Host, PlatformAdmin |
| POST | `/bookings/{id}/reviews` | Review a completed stay | Guest |
| GET | `/bookings/{id}/reviews` | List a booking's reviews | Host, Guest, PlatformAdmin |
| POST | `/bookings/{id}/messages` | Post a message to a booking thread | Host, Guest |
| GET | `/bookings/{id}/messages` | List a booking thread | Host, Guest, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 400 |
| `ERR_PERMIT_ALREADY_DECIDED` | 400 |
| `ERR_BOOKING_NOT_CANCELLABLE` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LISTING_NOT_LISTED` | 400 |
| `ERR_PERMIT_NOT_APPROVED` | 400 |
| `ERR_NO_RATE_FOR_DATES` | 400 |
| `ERR_RATE_OVERLAP` | 409 |
| `ERR_DATES_UNAVAILABLE` | 409 |
| `ERR_MIN_NIGHTS_NOT_MET` | 400 |
| `ERR_MAX_GUESTS_EXCEEDED` | 400 |
| `ERR_ADDON_NOT_OFFERED` | 400 |
| `ERR_ADDON_LISTING_MISMATCH` | 400 |
| `ERR_EXPERIENCE_SLOT_REQUIRED` | 400 |
| `ERR_SLOT_DATE_OUT_OF_RANGE` | 400 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_CHECKIN_TOO_EARLY` | 400 |
| `ERR_REVIEW_NOT_ALLOWED` | 400 |
| `ERR_DUPLICATE_REVIEW` | 409 |

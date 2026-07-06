# Wedding-Officiant & Ceremony Service API — Product Requirements Document

## 1. Introduction

Planning a wedding ceremony means coordinating a surprising number of moving parts against a single immovable date: the right officiant must be legally certified for the venue's state, able to perform the couple's chosen style, and free of any conflicting engagement; the ceremony script must be drafted, reviewed, and approved; a rehearsal must be booked without colliding with another party at the same venue; a marriage license must be filed, signed, and returned to the registry inside a legally binding window; and the money — deposits, gratuities, refunds — must reconcile to the cent. This API is the system of record for a wedding-officiant and ceremony service that manages all of these concerns end to end.

The platform is operated by a coordinator staff who curate a roster of officiants and the packages, venues, and pricing that couples select from. Couples submit their intake details, request a booking, place a date hold against an officiant, pay a deposit to confirm, customize their ceremony, schedule a rehearsal, and file their marriage license. Because every one of these steps is time-sensitive and legally consequential, the system relies on a controllable logical clock, scheduled expiry sweeps, optimistic concurrency on officiant availability, and a set of cascading reconciliations that keep bookings, scripts, rehearsals, holds, and licenses consistent whenever an officiant is suspended or a booking is cancelled.

This document specifies the complete external contract: the resource model, the state machines that govern each entity's lifecycle, the pricing and settlement calculations, the ordered validation rules, the REST endpoints, and the catalogue of error codes. It is written for the engineer implementing the service and is intended to be read as the single authoritative specification.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `Coordinator`, `Couple`, and `Officiant`.

- A `Coordinator` is the platform operator. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for auditing but never compares it to any entity's `id`; coordinators are not subject to ownership checks.
- A `Couple` is a client. When `X-User-Role` is `Couple`, `X-User-ID` is the `id` of the acting `Couple`. Ownership checks on any resource that references a couple compare the resource's `couple_id` (directly on a booking, or through the booking a child resource belongs to) against `X-User-ID`; a couple may act only on its own bookings and their child records.
- An `Officiant` is the assigned (or backup) officiant. When `X-User-Role` is `Officiant`, `X-User-ID` is the `id` of the acting `Officiant`. Ownership checks compare the target resource's `officiant_id` — or, where applicable, the booking's `backup_officiant_id` — against `X-User-ID`; an officiant may act only where they are the assigned primary or backup.

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

List endpoints are paginated through the `limit` and `offset` query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list responses are sorted by the resource's `created_at` timestamp in ascending order, with ties on identical `created_at` values broken by ascending creation order (the sequence in which the resources were created); because the logical clock is fixed until explicitly moved, many resources share the same `created_at` and this creation-order tiebreak is what fixes their relative position. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `has_more` is `true` exactly when `offset` plus the number of items returned on the page is strictly less than `total_count`.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — officiants, couples, packages, venues, bookings, date holds, ceremony scripts, rehearsals, marriage licenses, and reviews — carries the same four system-managed fields. `id` is a server-minted UUID, generated with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was created. `updated_at` is the ISO 8601 UTC timestamp of the resource's most recent modification. `version` is an integer that begins at 1 at creation and increments by one on every mutation of the resource, including mutations to its computed fields.

Whenever the server changes a resource — whether from a direct client request or from an automatic reconciliation triggered elsewhere — it refreshes that resource's `updated_at` and increments its `version`. This is especially important for the officiant: placing, releasing, or expiring a date hold adjusts the officiant's `active_hold_count` and therefore increments the officiant's `version`, even though no client edited the officiant directly.

### 2.5. The Logical Clock and Scheduled Expiry

All time-sensitive rules in this system are evaluated against a **logical clock** rather than wall-clock time, so that date holds, license validity, and return deadlines can be exercised deterministically. At server startup the logical clock reads exactly `2026-03-01T00:00:00Z`; until it is explicitly set, every time comparison uses this default (never the real wall clock). A coordinator may set the clock to any supplied ISO 8601 instant through the `to_iso8601` field, moving it forward or backward. Every server-stamped timestamp is likewise read from this logical clock rather than the real wall clock: each resource's `created_at` and `updated_at`, a date hold's `expires_at`, a marriage license's `signed_at`, `return_deadline`, and `recorded_at`, and every response envelope's `api_request_timestamp` are all derived from the current logical clock value.

Two lifecycle events are driven not by a client acting on a resource but by the passage of the logical clock, and they are realized only when a coordinator runs the scheduled expiry sweep:

- Any date hold still in `HELD` whose `expires_at` instant is at or before the current clock is moved to `EXPIRED`. Expiring the hold releases the officiant's slot (the officiant's `active_hold_count` decreases by one and its `version` increments), and if the hold's booking is still in `HOLD`, that booking moves to `EXPIRED`.
- Any marriage license still in `FILED` whose `expiry_date` is at or before the current clock is moved to `EXPIRED`.

### 2.6. Monetary Amounts, Precision, and Rounding

All monetary values are integer cents. Where a calculation multiplies a cent amount by a rate or fraction (gratuity, deposit percentage, refund percentage, goodwill), the result is rounded to a whole number of cents using the **round-half-up** rule: a fractional cent of exactly one half rounds up to the next whole cent. The individual line items produced while quoting a booking are already whole cents and are not rounded further at that stage.

Computed reputation ratings are the exception to the cents convention: `displayed_rating` and `internal_rating` are decimal numbers rounded to two decimal places, also round-half-up, and are `null` when there are no qualifying reviews.

### 2.7. Optimistic Concurrency on Officiant Availability

Placing a date hold is guarded by optimistic concurrency control on the parent officiant. A place-hold request must carry `expected_officiant_version`, which is the `version` of the officiant that the client last observed. Before the hold is created, the server compares `expected_officiant_version` against the officiant's current `version`. If another writer has advanced the officiant's version since the client read it — for example, another hold placement, or a release or expiry that adjusted the officiant's `active_hold_count` — the value is stale and the request is rejected with `ERR_STALE_OFFICIANT_VERSION` (HTTP 412). Because two different holds may reserve entirely non-overlapping dates, such a second placement could otherwise legitimately succeed; the stale version is the only thing that distinguishes it, so this is genuinely a create-with-supersede case resolved by concurrency control on the parent version rather than by any state precondition. Place-hold is the only operation that takes `expected_officiant_version`; no other endpoint requires a version field.

### 2.8. Cascading Reconciliation and Hierarchical Consistency

Two chains of automatic reconciliation keep the resource graph consistent. Each step in a chain independently mutates the affected resource and therefore refreshes its `updated_at` and increments its `version`.

**Officiant suspension (the suspension cascade).** When an officiant is suspended, every booking the suspended officiant serves must be re-opened for reassignment. For each booking in which the suspended officiant is the primary assignee (`officiant_id`) and whose status is `CONFIRMED` or `BACKUP_CONFIRMED`, that booking moves to `BACKUP_PENDING`; additionally, for each booking in which the suspended officiant is the backup (`backup_officiant_id`) and whose status is `BACKUP_CONFIRMED`, that booking also moves to `BACKUP_PENDING`. Each such booking transition then propagates: if the booking's ceremony script is `APPROVED`, it reverts to `CHANGES_REQUESTED` (the incoming officiant must re-approve it); and that script reversion in turn propagates: if the booking's rehearsal is `CONFIRMED`, it reverts to `SCHEDULED`, unlocking the timeline pending the new officiant's re-approval.

**Booking cancellation (the cancellation cascade).** When a booking is cancelled, its active date hold — one that is still `HELD` or `CONFIRMED` — is moved to `RELEASED`. Releasing the hold decrements the officiant's `active_hold_count` by one and increments the officiant's `version`. For cancellations of a booking that had progressed to `CONFIRMED`, `BACKUP_PENDING`, or `BACKUP_CONFIRMED`, the cancellation additionally cancels the booking's rehearsal if it is `SCHEDULED` or `CONFIRMED` (moving it to `CANCELLED`) and voids the booking's marriage license if it is `NOT_FILED`, `FILED`, or `SIGNED` (moving it to `VOIDED`).

### 2.9. Interval Conflict Detection for Officiants and Venues

The system detects two kinds of scheduling conflict, and the two use deliberately different interval semantics.

**Officiant double-booking** protects an officiant from two overlapping engagements and is checked against the officiant's existing date holds that are `HELD` or `CONFIRMED`. Each window is padded on both sides by the officiant's travel buffer — `travel_buffer_minutes` converted to seconds — and the windows are treated as **closed** intervals. Concretely, the candidate window runs from the ceremony start minus the buffer to the ceremony end plus the buffer, and each existing hold's window runs from its `hold_start` minus the buffer to its `hold_end` plus the buffer. A conflict exists when the candidate window's start is at or before an existing window's end and that existing window's start is at or before the candidate window's end. Because the intervals are closed, windows that merely touch at an endpoint do collide. A conflict is rejected with `ERR_OFFICIANT_DOUBLE_BOOKED`.

**Venue double-booking** protects a rehearsal venue and is checked against existing rehearsals at the same venue that are `SCHEDULED` or `CONFIRMED`. Here the windows carry no buffer and are treated as **half-open** intervals `[start, end)`. A conflict exists when the candidate rehearsal's start is strictly before an existing rehearsal's end and that existing rehearsal's start is strictly before the candidate's end. Because the intervals are half-open, back-to-back rehearsals where one ends exactly when the next begins do not collide. A conflict is rejected with `ERR_VENUE_UNAVAILABLE`.

### 2.10. Referential Resolution and Validation Order

For every request, checks are applied in a fixed precedence so that the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`). Authorization of the role, including entity-backed ownership for couples and officiants, comes next (`ERR_UNAUTHORIZED`). The system then confirms that every resource referenced by the request — whether named in the URL path or by a foreign key in the body — actually exists, resolving references left to right in the order officiant, couple, package, venue, booking, hold, script, rehearsal, license, review, and returning the corresponding not-found error for the first missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`. Once existence is established, the body's shape is validated (`ERR_VALIDATION`): required fields present, enum values within their allowed sets, `rating` an integer from 1 through 5, `ceremony_end` strictly after `ceremony_start`, and `expiry_date` strictly after `issued_date`. Only after all of that does the system evaluate state and business rules.

State and business rules are themselves ordered. As a general rule, a transition is first checked against the target resource's current state; a request to perform a transition that is not legal from the current state is rejected with `ERR_INVALID_STATE`. Two operations carry dedicated, more specific state gates that take the place of this generic check: confirming a booking requires it to be in `HOLD` and reports `ERR_BOOKING_NOT_HOLD` instead, and this dedicated state gate is evaluated before the fiscal deposit check on the same request; placing a date hold requires the booking to be in `INQUIRY` and reports `ERR_INVALID_STATE` from its own dedicated gate. The remaining per-operation orderings — availability, certification, style, concurrency, overlap, capacity, cross-entity state, temporal, and fiscal checks — are described alongside the workflows they guard in Section 3, and each such workflow states the order in which its checks fire.

## 3. Business Logic & Workflows

### 3.1. The Roster and Reference Data

The coordinator seeds the platform with the officiants, packages, and venues that couples will choose from, and couples (or a coordinator acting for them) create intake records.

**Officiants.** Registering an officiant records their `full_name` and `email`, the set of ceremony `styles` they offer, their faith `denomination`, and the `certified_jurisdictions` in which they are legally permitted to solemnize. The `styles` array is non-empty and each element is one of `RELIGIOUS`, `SECULAR`, `INTERFAITH`, or `SPIRITUAL`. The `denomination` is exactly one of `CHRISTIAN`, `JEWISH`, `MUSLIM`, `HINDU`, `BUDDHIST`, `NONDENOMINATIONAL`, or `CIVIL`. Each element of `certified_jurisdictions` is a two-letter state code, and the array is non-empty. Two operational tuning fields may be supplied or defaulted: `travel_buffer_minutes`, the buffer applied on both sides of a ceremony window during double-booking checks, is a non-negative integer that defaults to 180; and `max_active_holds`, the ceiling on how many non-terminal date holds the officiant may hold at once, is an integer of at least 1 that defaults to 5. A newly registered officiant begins in status `PENDING_REVIEW` with `active_hold_count` at 0, `escrow_balance_cents` at 0, `displayed_rating` and `internal_rating` at `null`, and `published_review_count` at 0. The roster can be browsed with filters for `style`, `denomination`, `jurisdiction`, and `status`.

An officiant's status is one of `PENDING_REVIEW`, `ACTIVE`, or `SUSPENDED`, and only a coordinator changes it, supplying the target through `to_state`. A pending officiant is approved by moving `PENDING_REVIEW → ACTIVE`; an active officiant is suspended by moving `ACTIVE → SUSPENDED`; and a suspended officiant is reinstated by moving `SUSPENDED → ACTIVE`. Any of these requested from the wrong current state is rejected with `ERR_INVALID_STATE`. Suspension triggers the suspension cascade described in Section 2.8, re-opening the suspended officiant's confirmed bookings for reassignment and reverting their approved scripts and confirmed rehearsals.

**Couples.** A couple intake record captures `partner_one_name`, `partner_two_name`, `email`, and `phone`. On creation its money-tracking fields start at zero: `paid_total_cents` (the sum of deposits captured across the couple's bookings) and `refund_credit_cents` (the sum of refunds and credits returned on the couple's cancelled bookings).

**Packages.** A package carries a display `name`, a `tier` that is one of `ESSENTIAL`, `CLASSIC`, or `PREMIUM`, a `base_price_cents` that must be greater than zero, and a `deposit_pct` that is greater than zero and at most 1. The `deposit_pct` is the fraction of a booking's grand total captured as the deposit at confirmation.

**Venues.** A venue records a `name`, a street `address`, and a `jurisdiction`, which is the two-letter state code where the venue sits. The venue's jurisdiction is what drives an officiant's certification requirement and the marriage-license jurisdiction requirement for any booking held there.

### 3.2. Creating a Booking and Quoting the Price

A couple, or a coordinator on their behalf, opens a booking by naming the participants and the ceremony: the assigned `officiant_id`, the client `couple_id`, the selected `package_id`, and the ceremony `venue_id`, together with the ceremony window `ceremony_start` and `ceremony_end` (`ceremony_end` must be strictly after `ceremony_start`), the one-way `travel_distance_km` from the officiant's base to the venue (a non-negative number), the `required_style` the couple wants (one of `RELIGIOUS`, `SECULAR`, `INTERFAITH`, or `SPIRITUAL`), and an optional list of `addon_codes` that defaults to an empty list. Each add-on code is one of `UNITY_CANDLE`, `HANDFASTING`, `LIVESTREAM`, `SAND_CEREMONY`, `PREMIUM_SCRIPT`, or `BILINGUAL_CEREMONY`. A booking is created in status `INQUIRY`. Its `backup_officiant_id` is `null` until a backup is assigned later, and its settlement fields start empty: `refund_issued_cents` and `forfeit_retained_cents` are both 0 and `cancel_initiator` and `cancel_reason` are both `null` until the booking is cancelled.

At creation the system computes the full price quote and records it on the booking. First it captures `days_until_ceremony_at_quote`, the whole number of days from the current clock to `ceremony_start`, computed as the floor of the difference in seconds divided by the number of seconds in a day. Then it builds the line items:

- The base fee is the package's `base_price_cents`.
- The travel surcharge, stored as `quoted_travel_cents`, is a tiered function of `travel_distance_km` across four contiguous bands: a distance of at most 25 kilometers adds nothing; a distance greater than 25 and up to and including 75 kilometers adds 15000 cents; a distance greater than 75 and up to and including 150 kilometers adds 30000 cents; and any distance greater than 150 kilometers adds 45000 cents.
- The rush surcharge, stored as `quoted_rush_cents`, is 25000 cents when `days_until_ceremony_at_quote` is strictly fewer than 30 days, and 0 otherwise.
- The interfaith surcharge, stored as `quoted_interfaith_cents`, is 20000 cents when `required_style` is exactly `INTERFAITH`, and 0 otherwise.
- The add-ons total, stored as `quoted_addons_cents`, is the sum of the per-code prices of the selected `addon_codes`: `UNITY_CANDLE` is 5000, `HANDFASTING` is 8000, `LIVESTREAM` is 12000, `SAND_CEREMONY` is 4000, `PREMIUM_SCRIPT` is 5025, and `BILINGUAL_CEREMONY` is 8025 cents.

The `quoted_subtotal_cents` is the sum of the base fee, the travel surcharge, the rush surcharge, the interfaith surcharge, and the add-ons total. All of these amounts are whole cents and are not rounded at this stage.

Gratuity is then computed line by line. The gratuity applies at a rate of 18 percent to each individual line item — the base fee, the travel surcharge, the rush surcharge, the interfaith surcharge, and each selected add-on taken separately — with each of those per-line amounts rounded half-up to a whole cent, and the rounded amounts summed to produce `quoted_gratuity_cents`. The gratuity must be computed this way, per line and then summed; it must not be computed by taking 18 percent of the combined subtotal, because rounding each line independently can differ from rounding the total by a cent. The grand total, `quoted_total_cents`, is `quoted_subtotal_cents` plus `quoted_gratuity_cents`. Finally, `deposit_due_cents` is the grand total multiplied by the package's `deposit_pct`, rounded half-up to a whole cent. Until the booking is confirmed, `deposit_captured_cents` is 0.

### 3.3. Date Holds, Availability, and Confirmation

Before a couple can commit, they place a **date hold** to reserve the officiant's calendar. A place-hold request names only the `booking_id` and carries the `expected_officiant_version` for the concurrency check described in Section 2.7. Placing the hold advances the booking from `INQUIRY` to `HOLD` and creates a `DateHold` in status `HELD`, copying the officiant onto the hold as `officiant_id` and copying the ceremony window onto the hold as `hold_start` and `hold_end`. The hold's `expires_at` is set to its `created_at` plus the hold time-to-live (a fixed number of days, `HOLD_TTL_DAYS`, which is 14), after which the hold auto-expires during the scheduled sweep. Placing the hold increments the officiant's `active_hold_count` by one and increments the officiant's `version` by one.

Placing a hold runs a specific ordered gauntlet of checks after existence and body validation. First the booking must be in `INQUIRY`; if not, the request is rejected with `ERR_INVALID_STATE`. Next the assigned officiant must be `ACTIVE`; an officiant that is `PENDING_REVIEW` or `SUSPENDED` yields `ERR_OFFICIANT_UNAVAILABLE`. Then the officiant must be certified for the venue's jurisdiction — the venue's `jurisdiction` must appear among the officiant's `certified_jurisdictions` — otherwise `ERR_OFFICIANT_NOT_CERTIFIED`. Then the booking's `required_style` must be one of the officiant's offered `styles`, otherwise `ERR_STYLE_MISMATCH`. Then the concurrency check compares `expected_officiant_version` against the officiant's current `version`, rejecting a mismatch with `ERR_STALE_OFFICIANT_VERSION`. Then the officiant double-booking check (closed, travel-buffered intervals as defined in Section 2.9) rejects any overlap with the officiant's existing `HELD` or `CONFIRMED` holds using `ERR_OFFICIANT_DOUBLE_BOOKED`. Finally, capacity is enforced: if the officiant's `active_hold_count` is already at or above `max_active_holds`, the request is rejected with `ERR_CAPACITY_EXCEEDED`. The officiant's `active_hold_count` is always kept equal to the number of that officiant's date holds in `HELD` or `CONFIRMED`; placing a hold adds one, and releasing or expiring a hold subtracts one, so placing and then releasing a hold returns the count to its prior value.

Confirming a booking captures the deposit and advances it from `HOLD` to `CONFIRMED`. The couple supplies `deposit_amount_cents`, the amount they are paying. Confirmation is checked in order: the booking must be in `HOLD`, and if it is not the request is rejected with `ERR_BOOKING_NOT_HOLD` — this state gate is evaluated before the deposit check on the same request; the assigned officiant must still be `ACTIVE`, otherwise `ERR_OFFICIANT_UNAVAILABLE`; the booking's date hold must not yet have expired, meaning the current clock must be strictly before the hold's `expires_at`, otherwise `ERR_HOLD_EXPIRED`; and finally `deposit_amount_cents` must be at least `deposit_due_cents`, otherwise `ERR_DEPOSIT_INSUFFICIENT`. On success the booking's `deposit_captured_cents` is set equal to `deposit_due_cents`, the couple's `paid_total_cents` increases by the captured deposit, the officiant's `escrow_balance_cents` increases by the captured deposit, and the booking's date hold moves from `HELD` to `CONFIRMED`.

If a hold is never confirmed, it eventually lapses. During the scheduled expiry sweep, a `HELD` date hold whose `expires_at` is at or before the current clock moves to `EXPIRED`; expiring it releases the officiant's slot (decrementing `active_hold_count` and incrementing the officiant's `version`) and, if the booking is still in `HOLD`, moves that booking to `EXPIRED`. Date holds can be listed and filtered by `officiant_id`, `booking_id`, and `status`.

### 3.4. Customizing the Ceremony Script

A couple drafts the ceremony narrative as a **ceremony script** attached to their booking. Creating a script records the `booking_id` it customizes, the `opening_remarks`, the `vow_format` (one of `TRADITIONAL`, `PERSONAL`, or `MIXED`), an optional list of `readings` (default empty), an optional list of `ritual_elements` such as unity-candle or handfasting inclusions (default empty), and the `closing_blessing`. A new script begins in status `DRAFT` with `revision_count` at 0 and `officiant_notes` at `null`. While a script is in `DRAFT` or `CHANGES_REQUESTED`, the couple may edit its content — any of `opening_remarks`, `vow_format`, `readings`, `ritual_elements`, or `closing_blessing`.

The script moves through a review loop. The couple submits it for review, moving `DRAFT → SUBMITTED` or `CHANGES_REQUESTED → SUBMITTED`; resubmitting from `CHANGES_REQUESTED` increments `revision_count` by one, so the count records how many times the script has re-entered review after changes were requested. The assigned officiant then records a decision on a submitted script, supplying `decision` and optional `notes`. A `decision` of `APPROVE` moves `SUBMITTED → APPROVED`; a `decision` of `REQUEST_CHANGES` moves `SUBMITTED → CHANGES_REQUESTED`. In either case, the supplied `notes` are recorded on the script as `officiant_notes`. A decision requested when the script is not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`. As noted in Section 2.8, an approved script is automatically reverted to `CHANGES_REQUESTED` when the booking is re-opened by an officiant suspension, so that the incoming officiant re-reviews it. Scripts can be listed and filtered by `booking_id` and `status`.

### 3.5. Scheduling the Rehearsal

A couple books a **rehearsal** for their ceremony at a chosen venue. Scheduling a rehearsal records the `booking_id` it belongs to, the `venue_id` where it is held, and the rehearsal window `rehearsal_start` and `rehearsal_end` (`rehearsal_end` must be strictly after `rehearsal_start`). The rehearsal is created in status `SCHEDULED`. At scheduling time the venue double-booking check (half-open, unbuffered intervals as defined in Section 2.9) rejects any overlap with the same venue's existing `SCHEDULED` or `CONFIRMED` rehearsals using `ERR_VENUE_UNAVAILABLE`.

A rehearsal's status is one of `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `NO_SHOW`, or `CANCELLED`, and status changes are requested through `to_state`. The assigned officiant confirms a scheduled rehearsal, moving `SCHEDULED → CONFIRMED`, but only once the booking's ceremony script is `APPROVED`; if the script is not yet approved, confirmation is rejected with `ERR_SCRIPT_NOT_APPROVED`. From `CONFIRMED`, the officiant may move the rehearsal to `COMPLETED` or mark it `NO_SHOW`. A rehearsal may be cancelled (`SCHEDULED → CANCELLED` or `CONFIRMED → CANCELLED`) by the couple or a coordinator. Any of these transitions requested from an incompatible current state is rejected with `ERR_INVALID_STATE`. A confirmed rehearsal is also reverted automatically to `SCHEDULED` when the booking's approved script is reverted during the suspension cascade of Section 2.8. Rehearsals can be listed and filtered by `booking_id`, `venue_id`, and `status`.

### 3.6. Marriage-License Filing and Return Compliance

The **marriage license** is the legally binding artifact, and its lifecycle enforces jurisdiction, validity, and return-window compliance. A license record is created against a booking with its `booking_id`, the issuing `jurisdiction` (a two-letter state code), the county-issued `license_number`, the `issued_date`, and the `expiry_date` (which must be strictly after `issued_date`). A new license begins in status `NOT_FILED`, with `signed_at`, `recorded_at`, and `return_deadline` all `null` until the relevant steps occur. A license's status is one of `NOT_FILED`, `FILED`, `SIGNED`, `RECORDED`, `REJECTED`, `VOIDED`, or `EXPIRED`, and transitions are driven through `to_state`, with an optional `reason`.

The couple files the license, moving `NOT_FILED → FILED`. Filing requires, in order, that the license be in `NOT_FILED` (otherwise `ERR_INVALID_STATE`), that the backing booking be `CONFIRMED` or `BACKUP_CONFIRMED` (otherwise `ERR_BOOKING_NOT_CONFIRMED`), and that the license's `jurisdiction` equal the booking venue's `jurisdiction` (otherwise `ERR_LICENSE_JURISDICTION_MISMATCH`). The assigned officiant signs a filed license, moving `FILED → SIGNED`, but only while the license is still valid: the current clock must be at or before the license's `expiry_date`, otherwise the sign is rejected with `ERR_LICENSE_EXPIRED`. Signing stamps `signed_at` with the current clock and sets `return_deadline` to `signed_at` plus a ten-day return window.

A coordinator then records the signed license with the registry, moving `SIGNED → RECORDED`, but only within the return window: the current clock must be at or before `return_deadline` (the boundary is inclusive), otherwise the request is rejected with `ERR_LICENSE_RETURN_OVERDUE`. Recording stamps `recorded_at` with the current clock. Alternatively, a coordinator may reject a signed license, moving `SIGNED → REJECTED`. A rejected license can be refiled by the couple, moving `REJECTED → FILED`, provided the backing booking is still `CONFIRMED` or `BACKUP_CONFIRMED`; refiling clears the prior signature by resetting `signed_at` and `return_deadline` back to `null`. Separately, a filed license whose `expiry_date` has passed is moved to `EXPIRED` by the scheduled sweep, and any license that is `NOT_FILED`, `FILED`, or `SIGNED` is voided to `VOIDED` when its booking is cancelled. Licenses can be listed and filtered by `booking_id` and `status`.

### 3.7. Assigning a Backup Officiant

When a booking is sitting in `BACKUP_PENDING` — because its officiant was suspended — a coordinator assigns a replacement, advancing the booking `BACKUP_PENDING → BACKUP_CONFIRMED`. The booking must be in `BACKUP_PENDING` for this to be allowed; otherwise the request is rejected with `ERR_INVALID_STATE`. The replacement is chosen by a deterministic selection policy over all officiants other than the booking's current primary `officiant_id`.

A candidate officiant is eligible only if it satisfies every one of the following: its status is `ACTIVE`; the booking's `required_style` is among the candidate's `styles`; the candidate is certified for the booking venue's jurisdiction (that jurisdiction appears in the candidate's `certified_jurisdictions`); the candidate's `active_hold_count` is strictly below its `max_active_holds`; and the candidate has no officiant double-booking conflict against the booking's ceremony window `[ceremony_start, ceremony_end]`, evaluated with the same closed, travel-buffered interval rule used when placing a hold. Among the eligible candidates, the winner is chosen by ranking on `displayed_rating` in descending order, treating a `null` rating as `-1` so that unrated officiants sort last; ties are broken by earliest `created_at` in ascending order (never by `id`). If no candidate is eligible, the request is rejected with `ERR_NO_BACKUP_AVAILABLE` and the booking remains in `BACKUP_PENDING`. On a successful assignment, the booking's `backup_officiant_id` is set to the selected officiant, and that selected officiant's `active_hold_count` increases by one and its `version` increments by one.

### 3.8. Completing, Cancelling, and Settling a Booking

A booking that has been served is completed by the assigned officiant, moving `CONFIRMED → COMPLETED` or `BACKUP_CONFIRMED → COMPLETED`. Completion requires that the current clock be at or after the booking's `ceremony_start` and that the booking be in `CONFIRMED` or `BACKUP_CONFIRMED`; the state requirement is evaluated first, and a request that fails either check — a booking in the wrong state, or a clock still strictly before `ceremony_start` — is rejected with `ERR_INVALID_STATE`.

A booking may be cancelled from any of `HOLD`, `CONFIRMED`, `BACKUP_PENDING`, or `BACKUP_CONFIRMED`; a cancel requested from any other state is rejected with `ERR_INVALID_STATE`. The caller supplies `cancel_reason`, which is one of `COUPLE_REQUEST`, `OFFICIANT_UNAVAILABLE`, `VENUE_LOST`, `NO_BACKUP`, or `OTHER`. Cancellation records `cancel_initiator`, which is either `COUPLE` or `SERVICE`. For a cancellation from `HOLD`, `CONFIRMED`, or `BACKUP_CONFIRMED`, the initiator is `COUPLE` when the caller acts as a couple and `SERVICE` when the caller is a coordinator. For a cancellation from `BACKUP_PENDING`, the initiator is `SERVICE` when either the `cancel_reason` is `NO_BACKUP` or the caller is a coordinator, and `COUPLE` otherwise.

Cancelling from `HOLD` involves no money, because no deposit was captured: `refund_issued_cents` and `forfeit_retained_cents` are both 0. Cancelling from `CONFIRMED`, `BACKUP_PENDING`, or `BACKUP_CONFIRMED` runs the settlement, and the settlement algorithm depends on who initiated the cancellation.

- **Couple-initiated settlement.** The system recomputes the days remaining as the floor of the difference between `ceremony_start` and the current clock, in seconds, divided by the number of seconds in a day. The refund fraction is 100 percent when at least 90 days remain, 50 percent when at least 30 but fewer than 90 days remain, and 0 percent when fewer than 30 days remain. `refund_issued_cents` is the captured deposit `deposit_captured_cents` multiplied by that fraction, rounded half-up to a whole cent, and `forfeit_retained_cents` is the captured deposit minus the refund, so the two always sum back to the captured deposit.
- **Service-initiated settlement.** The couple is made whole and given a goodwill credit. A goodwill amount is computed as the booking's `quoted_subtotal_cents` multiplied by 10 percent, rounded half-up to a whole cent. `refund_issued_cents` is the full captured deposit plus that goodwill amount, and `forfeit_retained_cents` is 0.

After settlement, the couple's `refund_credit_cents` increases by `refund_issued_cents`, and the officiant's `escrow_balance_cents` decreases by the captured deposit minus the retained forfeit — that is, the refunded portion leaves escrow while the retained portion stays as earned. Cancellation then runs the cancellation cascade of Section 2.8: the booking's active date hold is released (returning the officiant's hold slot), and for cancellations from `CONFIRMED`, `BACKUP_PENDING`, or `BACKUP_CONFIRMED`, the booking's `SCHEDULED` or `CONFIRMED` rehearsal is cancelled and its `NOT_FILED`, `FILED`, or `SIGNED` marriage license is voided. Bookings can be listed and filtered by `officiant_id`, `backup_officiant_id`, `couple_id`, `package_id`, `venue_id`, and `status`.

### 3.9. Reviews and Officiant Reputation

After a ceremony is performed, the couple submits a **review** of the officiant. A review is submitted against the completed booking with its `booking_id`, an integer `rating` from 1 through 5, and free-text `text`; a review submitted for a booking that is not `COMPLETED` is rejected with `ERR_REVIEW_NOT_ALLOWED`. On creation the review is in status `SUBMITTED`, and its `officiant_id` is copied from the booking's officiant. A review's status is one of `SUBMITTED`, `PUBLISHED`, or `REMOVED`.

A coordinator moderates each review, supplying `decision`. A `decision` of `PUBLISH` moves a submitted review `SUBMITTED → PUBLISHED`; a `decision` of `REMOVE` moves a review `SUBMITTED → REMOVED` or `PUBLISHED → REMOVED`. Any review status change — whether creation or a moderation decision — recomputes the officiant's reputation. The officiant carries two mean ratings over its reviews, each rounded to two decimal places half-up and each `null` when its qualifying set is empty. The public `displayed_rating` is the mean `rating` over the officiant's reviews whose status is `PUBLISHED`. The operations-facing `internal_rating` is the mean `rating` over the officiant's reviews whose status is `SUBMITTED` or `PUBLISHED`. The officiant's `published_review_count` is the number of the officiant's reviews in `PUBLISHED`. Reviews can be listed and filtered by `officiant_id`, `booking_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that fetch, list, or modify an existing resource — including state transitions, moderation, and the administrative clock and expiry operations — return `200 OK`. The complete request and response bodies for each operation are reconstructed from the workflow narratives in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/officiants` | Register an officiant (starts `PENDING_REVIEW`) | Coordinator |
| GET | `/officiants/{id}` | Fetch one officiant, including computed reputation fields | Coordinator, Couple, Officiant |
| GET | `/officiants` | Browse the officiant roster with filters | Coordinator, Couple, Officiant |
| POST | `/officiants/{id}/transition` | Approve, suspend, or reinstate an officiant | Coordinator |
| POST | `/couples` | Create a couple intake record | Coordinator, Couple |
| GET | `/couples/{id}` | Fetch one couple | Coordinator, Couple |
| POST | `/packages` | Create a package / pricing tier | Coordinator |
| POST | `/venues` | Create a venue | Coordinator |
| POST | `/bookings` | Create a booking and compute the price quote | Coordinator, Couple |
| GET | `/bookings/{id}` | Fetch one booking | Coordinator, Couple, Officiant |
| GET | `/bookings` | List bookings with filters | Coordinator, Couple, Officiant |
| POST | `/bookings/{id}/confirm` | Pay the deposit and confirm the booking | Couple |
| POST | `/bookings/{id}/cancel` | Cancel a booking and run settlement | Couple, Coordinator |
| POST | `/bookings/{id}/assign-backup` | Assign a backup officiant | Coordinator |
| POST | `/bookings/{id}/complete` | Mark the ceremony performed | Officiant |
| POST | `/date-holds` | Place a date hold on the booking's officiant | Couple, Coordinator |
| GET | `/date-holds/{id}` | Fetch one date hold | Coordinator, Couple, Officiant |
| GET | `/date-holds` | List date holds with filters | Coordinator, Couple, Officiant |
| POST | `/ceremony-scripts` | Create a ceremony script draft | Couple |
| GET | `/ceremony-scripts/{id}` | Fetch one ceremony script | Coordinator, Couple, Officiant |
| GET | `/ceremony-scripts` | List ceremony scripts with filters | Coordinator, Couple, Officiant |
| PATCH | `/ceremony-scripts/{id}` | Edit script content (only in `DRAFT` or `CHANGES_REQUESTED`) | Couple |
| POST | `/ceremony-scripts/{id}/submit` | Submit a script for officiant review | Couple |
| POST | `/ceremony-scripts/{id}/decision` | Record the officiant's decision on a submitted script | Officiant |
| POST | `/rehearsals` | Schedule a rehearsal at a venue | Couple |
| GET | `/rehearsals/{id}` | Fetch one rehearsal | Coordinator, Couple, Officiant |
| GET | `/rehearsals` | List rehearsals with filters | Coordinator, Couple, Officiant |
| POST | `/rehearsals/{id}/transition` | Move rehearsal status | Officiant, Couple, Coordinator |
| POST | `/marriage-licenses` | Create a marriage-license record | Couple |
| GET | `/marriage-licenses/{id}` | Fetch one marriage license | Coordinator, Couple, Officiant |
| GET | `/marriage-licenses` | List marriage licenses with filters | Coordinator, Couple, Officiant |
| POST | `/marriage-licenses/{id}/transition` | Compliance transition (file, sign, record, reject, refile) | Couple, Officiant, Coordinator |
| POST | `/reviews` | Submit a review for a completed booking | Couple |
| GET | `/reviews/{id}` | Fetch one review | Coordinator, Couple, Officiant |
| GET | `/reviews` | List reviews with filters | Coordinator, Couple, Officiant |
| POST | `/reviews/{id}/moderate` | Publish or remove a review | Coordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock | Coordinator |
| POST | `/_expiry/run` | Run the scheduled expiry sweep | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_OFFICIANT_NOT_FOUND` | 404 |
| `ERR_COUPLE_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_SCRIPT_NOT_FOUND` | 404 |
| `ERR_REHEARSAL_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BOOKING_NOT_HOLD` | 409 |
| `ERR_OFFICIANT_UNAVAILABLE` | 409 |
| `ERR_STALE_OFFICIANT_VERSION` | 412 |
| `ERR_OFFICIANT_NOT_CERTIFIED` | 422 |
| `ERR_STYLE_MISMATCH` | 422 |
| `ERR_LICENSE_JURISDICTION_MISMATCH` | 422 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_LICENSE_EXPIRED` | 409 |
| `ERR_LICENSE_RETURN_OVERDUE` | 409 |
| `ERR_OFFICIANT_DOUBLE_BOOKED` | 409 |
| `ERR_VENUE_UNAVAILABLE` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_BACKUP_AVAILABLE` | 409 |
| `ERR_SCRIPT_NOT_APPROVED` | 409 |
| `ERR_BOOKING_NOT_CONFIRMED` | 409 |
| `ERR_REVIEW_NOT_ALLOWED` | 409 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |

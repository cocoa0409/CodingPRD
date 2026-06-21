# Golf Tee Time & Handicap API — Product Requirements Document

## 1. Introduction

Public and semi-private golf courses live at the intersection of two unrelated-looking problems that this API treats as one system: selling a scarce, time-boxed inventory of tee times, and maintaining a defensible Handicap Index for every golfer who posts a score. The platform mirrors the operational reality of a GHIN-style service. A pro shop publishes bookable slots on each of its courses, prices them by time of day, fills them as twosomes or foursomes, and runs a waitlist when demand exceeds capacity. In parallel, every round a golfer plays produces a score that is normalized against the course's USGA Course Rating and Slope Rating, folded into a running figure that updates the moment the score lands, and periodically frozen into an official index by a monthly refresh.

The design tension this document resolves is that the same underlying quantity — a golfer's Handicap Index — is computed two different ways at two different cadences. A live, uncapped provisional figure tracks the most recent rounds and moves with every post; an official, capped figure is published only when the pro shop runs a revision epoch, and it is bounded by anti-abuse caps anchored to the golfer's recent low. The two numbers can legitimately disagree, and the system must keep both. Layered on top is a booking engine where cancellations cascade — a freed seat promotes the top of a waitlist, which reprices that booking, which re-ranks everyone behind it — and where concurrent writers competing for the last seat must be serialized so a slot is never oversubscribed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. All paths described in this document are mounted under the `/golf` prefix (the test-driving clock endpoint excepted, as noted in §4).

### 2.1. User and Role-Based Access Control

Every request carries its caller identity in two mandatory HTTP headers: `X-User-ID`, the identifier of the acting user, and `X-User-Role`, the operational capacity that user is acting in. The system recognizes three roles, spelled exactly: `ProShop`, `Golfer`, and `Anonymous`. If either header is missing, or `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. The sole exception is the set of endpoints that explicitly permit `Anonymous` access (read-only browsing and self-registration), where an unauthenticated caller is allowed. When a caller presents valid headers but the role is not permitted for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles relate to persisted identity differently. When `X-User-Role` is `Golfer`, `X-User-ID` is the `id` of the acting `Golfer` entity; ownership checks on any resource that references a golfer compare the resource's golfer foreign key to `X-User-ID`. In particular, a golfer cancelling a booking must be the holder of that booking. When `X-User-Role` is `ProShop`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and a `ProShop` operator may act on any golfer's bookings or scores. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity and is never matched against a resource owner; the anonymous capacity exists only for public reads and golfer self-registration.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

The primary resources in this system — `Course`, `Golfer`, `Score`, `TeeTime`, and `Booking` — each carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and never feeds a business decision. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations the server performs as a cascade rather than at the client's direct request. The `version` field is an integer that starts at 1 and increments by exactly 1 on every mutation; it doubles as the optimistic-concurrency token described in §2.6.

The `HandicapRevision` resource is deliberately leaner. A revision record is an immutable audit entry: it carries only an `id` (server-minted UUID, no prefix) and a `created_at` timestamp. It has no `updated_at` field and no `version` field, because it is never mutated after the refresh that created it.

### 2.5. Hierarchical Consistency and Cascades

Several operations mutate more than one resource in a single logical step, and the system must keep the touched resources internally consistent. Whenever a booking is created, cancelled, or promoted, the owning tee time's derived state is recomputed in the same step: its `confirmed_count` is re-derived from the bookings that hold it, its `status` follows from that count, its `updated_at` is refreshed, and its `version` is incremented by 1. The most consequential cascade is booking cancellation, which can reach three levels deep: cancelling a confirmed booking frees a seat on the slot, which may promote the highest-priority waitlisted booking to confirmed, which in turn prices that promoted booking and re-ranks every booking still waiting behind it. Each entity touched along that chain has its own `updated_at` refreshed and, where it carries one, its `version` incremented. The monthly handicap refresh is a similar fan-out: a single request recomputes the official index for every eligible golfer and bumps each affected golfer's `version`.

### 2.6. Optimistic Concurrency on Slot Booking

Booking creation is guarded by optimistic concurrency control anchored on the target tee time's `version`. A request to book a slot must include `expected_tee_time_version`, carrying the `version` the client last observed on that `TeeTime`. This field is required for booking creation; it is not optional. Before the booking is accepted, the server compares `expected_tee_time_version` against the slot's current `version`. If they differ — meaning another writer has advanced the slot since the client read it, for example by taking the last open seat and flipping the slot to `FULL` — the request is rejected with `ERR_STALE_TEE_TIME_VERSION` and HTTP status 412. This prevents a client that holds a stale view of the slot from overwriting a booking it never observed and over-subscribing capacity. No other endpoint takes a version field; booking creation is the only OCC-guarded write.

### 2.7. Course Rating, Slope, and the Score Differential

Each course publishes the two USGA figures that normalize raw scores. The `course_rating` is the number of strokes a scratch golfer is expected to shoot and is a decimal in the inclusive range from 55.0 to 85.0. The `slope_rating` is an integer in the inclusive range from 55 to 155 and acts as the per-round normalizer. When a round is posted, the system freezes a `score_differential` on it: take the standard slope constant of 113, divide it by the course's `slope_rating`, multiply that ratio by the result of subtracting the course's `course_rating` from the round's `adjusted_gross_score`, and round the product half-up to one decimal place. This differential is computed once at posting time and is immutable thereafter — it is never recomputed even if the course's rating or slope is later changed.

### 2.8. Pricing Tiers and the Green Fee

Every course defines a daily peak window and two fee levels. The `peak_start_hour` is the local hour, inclusive, at which peak pricing begins and defaults to 7; the `peak_end_hour` is the local hour, exclusive, at which peak pricing ends and defaults to 15. A tee time whose local hour is at least the peak start hour and strictly less than the peak end hour is priced at the `PEAK` tier; any other hour is `OFF_PEAK`. The base fee is the course's `peak_fee_cents` for a peak slot and its `offpeak_fee_cents` for an off-peak slot; both are non-negative integer cent amounts charged before any member discount. Members enjoy a fractional discount given by `member_discount_pct`, a value between 0.0 and 1.0 inclusive that defaults to 0.20.

The final fee charged to a confirmed booking is computed by a strictly ordered procedure. First determine the base from the booking's frozen `pricing_tier` as above. If the holding golfer's `membership_tier` is `MEMBER`, multiply the base by the course's `member_discount_pct`, round that discount amount half-up to whole cents, and then subtract the rounded discount from the base; the order is pinned — round the discount first, subtract second. If the golfer's `membership_tier` is `PUBLIC`, there is no discount and the fee equals the base. All fees are integer cents. Computing the fee as the base times one-minus-the-percentage and rounding the product is not equivalent and is not permitted, because it can differ by a cent.

### 2.9. Field Ranges and Structural Validation

Beyond the rating and fee ranges above, the system enforces field-level validation on input. A course's `peak_end_hour` must be strictly greater than its `peak_start_hour`, and both hours lie in the inclusive range 0 through 23. A golfer's `membership_tier` must be one of `MEMBER` or `PUBLIC`, defaulting to `PUBLIC` when omitted. A tee time's `local_hour` is in the inclusive range 0 through 23, and its `group_type` must be one of `TWOSOME` or `FOURSOME`. A posted round's `adjusted_gross_score` is an integer in the inclusive range from 50 to 150. Any missing required field, malformed enum, out-of-range number, or violated ordering constraint is rejected with `ERR_VALIDATION` and HTTP status 422.

### 2.10. Precision

Monetary amounts are stored and returned as integer cents. Both handicap figures and the per-round score differential are carried to one decimal place using the round-half-up convention. As noted in §2.8, the member discount is the one place where rounding order is load-bearing: the discount is rounded half-up to whole cents before it is subtracted from the base.

## 3. Business Logic & Workflows

### 3.1. Standing Up Courses and Golfers

A `ProShop` operator establishes a course by supplying its `name`, its `course_rating` and `slope_rating`, the `peak_fee_cents` and `offpeak_fee_cents`, and optionally the peak-window hours `peak_start_hour` and `peak_end_hour` and the `member_discount_pct`; omitted optional values fall back to their defaults. Anyone — `ProShop`, a `Golfer`, or an `Anonymous` caller — may read a single course or page through the list of courses.

Golfers enter the system by registration, which is open to a `ProShop` operator or to an `Anonymous` self-registrant. A registration supplies the golfer's `full_name` and, optionally, a `membership_tier`; when the tier is omitted the golfer is `PUBLIC`. A newly registered golfer has no handicap history yet, so its computed `handicap_index`, `provisional_handicap_index`, and `low_handicap_index` all begin empty (null), its `handicap_revision` begins at 0, and these fields populate only as scores are posted and revisions are run. Reading a golfer returns those handicap fields alongside the identity fields, and golfers may be listed with an optional `membership_tier` filter.

### 3.2. Posting Scores and the Live Running Index

A score is posted by a `ProShop` operator or by a `Golfer`, identifying the round with `golfer_id` (the golfer who played), `course_id` (the course that supplies the rating and slope), `played_on` (the calendar date the round was played, written `YYYY-MM-DD`), and the `adjusted_gross_score`. On creation the score enters `POSTED` status, the system freezes its `score_differential` as described in §2.7, sets `counted_in_revision` to 0 to mark that no official refresh has yet folded it in, and increments the golfer's `version`. Scores may be fetched individually or listed; the list view accepts a `golfer_id` filter to see one golfer's rounds and a `course_id` filter to see rounds played on a given course.

Posting a score immediately recomputes the golfer's `provisional_handicap_index` — the live, uncapped running figure. This recomputation considers only the golfer's scores still in `POSTED` status; voided rounds are excluded. If fewer than three posted scores exist, there is insufficient data and the provisional index is null. Otherwise the system first applies the recency window: when more than 20 posted scores exist, only the most recent 20 are eligible, ordered by `played_on` descending and then `created_at` descending; with 20 or fewer, all of them are eligible. This trimming happens first. Only then are the eligible differentials sorted ascending, the lowest *k* of them taken, their arithmetic mean computed, an adjustment added, and the result rounded half-up to one decimal place. The order is pinned: trim to the recent 20 by date first, then sort and take the lowest *k* — taking the lowest *k* across all rounds before trimming would let an old low round survive a recency window that should have excluded it.

The count *k* and the adjustment both depend on how many eligible scores there are (capped at 20 for lookup). The number of lowest differentials averaged is: 1 for 3, 4, or 5 eligible scores; 2 for 6, 7, or 8; 3 for 9, 10, or 11; 4 for 12, 13, or 14; 5 for 15 or 16; 6 for 17 or 18; 7 for 19; and 8 for 20 or more. The adjustment added to the mean is −2.0 when there are exactly 3 eligible scores, −1.0 when there are exactly 4, −1.0 again when there are exactly 6, and 0.0 for every other count (5, and 7 through 20). The adjustment is additive, so the negative values pull the index down.

### 3.3. Voiding a Score

Only a `ProShop` operator may void a score, and only while it is in `POSTED` status; voiding a score already in `VOID` is rejected with `ERR_INVALID_STATE`. Voiding moves the score from `POSTED` to `VOID`, which removes it from every subsequent handicap calculation, and immediately recomputes the holding golfer's `provisional_handicap_index` over the remaining posted scores (excluding the now-voided one) using the same lowest-*k*-of-recent-20 procedure from §3.2, then increments the golfer's `version`. The next monthly refresh likewise ignores the voided score.

### 3.4. The Monthly Refresh and the Official Index

A `ProShop` operator runs a monthly Handicap Index refresh, supplying the `effective_utc` instant that anchors the run. The refresh creates a `HandicapRevision` whose `revision_number` is a global monotonic epoch counter — the Nth refresh ever run carries revision number N — and whose `golfer_count` records how many golfers had their official index written by this run. The supplied `effective_utc` must be strictly after the `effective_utc` of the most recent prior revision; a run that is not strictly later is rejected with `ERR_REVISION_NOT_MONOTONIC`.

For each golfer, the refresh computes the official `handicap_index` over that golfer's posted scores whose `played_on` falls on or before the date of the revision's `effective_utc`. This as-of-date filter is the first way the official figure diverges from the provisional one: the provisional index considers all posted scores regardless of when they were played, while the official index ignores rounds played after the refresh's effective date. Over those eligible scores the system computes the same base figure as the provisional index — trim to the most recent 20 by `played_on` then `created_at` descending, sort ascending, take the lowest *k*, average, add the count-based adjustment, and round half-up to one decimal place. A golfer with fewer than three eligible scores gets a null official index and is not counted in the refresh.

Two caps then apply to that base, and they are the second way the official figure diverges from the live one — the provisional index applies neither. The anchor is the golfer's `low_handicap_index`, the lowest official index observed across the trailing 365 days as of the run. If the base exceeds the anchor by more than the soft-cap threshold of 3.0, the excess above that threshold is damped to half its size: the capped value becomes the anchor plus 3.0 plus one-half of the amount by which the base exceeds the anchor-plus-3.0. The hard cap then clamps the result so it is never more than 5.0 above the anchor — that is, the value is the smaller of the soft-capped figure and the anchor plus 5.0. The final official index is that capped value rounded half-up to one decimal place. When a golfer has no anchor yet because no prior refresh has set a `low_handicap_index` (it is null), both caps are skipped entirely, the official index equals the uncapped base, and this same refresh seeds the golfer's `low_handicap_index` to that official index. On every run the anchor is refreshed to the minimum official index over the trailing 365 days, this run's index included.

When a golfer's official index is written, the refresh sets that golfer's `handicap_index`, sets the golfer's `handicap_revision` to this run's `revision_number`, and stamps `counted_in_revision` with this revision number on each score that contributed, then increments the golfer's `version`. Revisions can be fetched as a paginated list.

### 3.5. Publishing Tee Times

A `ProShop` operator publishes a bookable slot by supplying the `course_id` it belongs to, the `start_utc` start instant (ISO 8601 UTC, minute granularity), the `local_hour` used to decide its pricing tier, and the `group_type`. On creation the slot derives its `capacity` from the group type — `TWOSOME` seats 2 and `FOURSOME` seats 4 — sets `confirmed_count` to 0, and opens in `OPEN` status. Slots may be fetched individually or listed; the list view filters by `course_id` and by `status`.

Tee sheets cannot pack slots arbitrarily close together. A new tee time's `start_utc` must be at least the minimum tee interval of 8 minutes away from every existing non-closed tee time on the same course. This is a symmetric buffer test on the gap between start instants, not an occupancy-overlap test: the absolute difference between the new slot's start and any existing slot's start must not be under 8 minutes. Exactly 8 minutes apart is allowed; anything strictly closer collides and is rejected with `ERR_TEE_INTERVAL_CONFLICT`. Slots already in `CLOSED` status are ignored by this spacing check.

A `ProShop` operator may close a slot that is currently `OPEN`, moving it from `OPEN` to `CLOSED` and incrementing its `version`. Closing requires the slot be `OPEN`; attempting it from another state yields `ERR_INVALID_STATE`. A closed slot rejects all further booking creation, but bookings already confirmed on it are untouched. `CLOSED` is terminal.

### 3.6. Booking a Slot

Booking is the busiest workflow and the one whose inputs are spread across the most rules. A `ProShop` operator or a `Golfer` books a slot by identifying the holding `golfer_id`, supplying `expected_tee_time_version` for the concurrency check of §2.6, and optionally setting `join_standby`. Booking validations are evaluated in a fixed priority order so that the most fundamental failures surface first and more specific failures are not masked by generic ones. The order is: authentication first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then existence of the referenced slot and golfer (`ERR_NOT_FOUND`), then state admissibility, then the specific closed-slot rule, then the duplicate-booking rule, then the golfer time-conflict rule, then the slot-start-passed rule, then the optimistic-concurrency check, and finally the capacity/standby rule. The precise sequencing among the booking-specific checks is detailed below.

A slot must be in a bookable state to accept a booking; a slot that is not open to new bookings fails generic state admissibility with `ERR_INVALID_STATE`. More specifically, a slot already in `CLOSED` status rejects booking creation with `ERR_TEE_TIME_CLOSED`, which is the more specific code that takes precedence over the generic invalid-state result for the closed case. A golfer may hold at most one non-cancelled booking — confirmed or standby — on any given tee time; a second attempt while one still stands is rejected with `ERR_DUPLICATE_BOOKING`. A golfer also may not hold confirmed bookings on two slots whose occupancy windows overlap: each confirmed booking occupies its slot's start instant through 12 minutes later, treated as a half-open interval, so two slots collide when those 12-minute windows overlap; back-to-back slots that merely touch at the boundary do not conflict. A violation is rejected with `ERR_GOLFER_TIME_CONFLICT`. The slot's `start_utc` must also be strictly after the current clock — a slot whose start instant is exactly now or already past cannot be booked, and the attempt is rejected with `ERR_SLOT_START_PASSED`.

Once those guards pass and the optimistic-concurrency check on `expected_tee_time_version` succeeds, the outcome depends on capacity. Every booking records the slot it holds in `tee_time_id` and its holder in `golfer_id`. When the slot has an open seat, the booking is created `CONFIRMED`: the system freezes its `pricing_tier` from the slot's `local_hour` against the course's peak window, computes its `green_fee_cents` per §2.8, sets its `standby_rank` to 0, increments the slot's `confirmed_count`, and bumps the slot's `version`. If that confirmation takes the last seat — the confirmed count reaches capacity — the slot transitions from `OPEN` to `FULL`. When the slot is already `FULL` (confirmed count equals capacity), the request must opt into the waitlist by setting `join_standby` to true; if it does not, the booking is rejected with `ERR_SLOT_FULL_NO_STANDBY`. A request that does opt in is created in `STANDBY` status with `green_fee_cents` of 0 (no fee is charged while waitlisted), its `pricing_tier` still frozen at creation from the slot's hour for use if it is later promoted, and a `standby_rank` assigned by the waitlist ordering. Creating a standby booking does not change the slot's `confirmed_count` and the slot remains `FULL`. Bookings may be fetched individually, listed across the system with optional `golfer_id` and `status` filters, or listed for a single slot with an optional `status` filter.

### 3.7. The Waitlist Ordering and Promotion

The waitlist is ordered by member priority and then by arrival. Among a slot's standby bookings, those held by a `MEMBER` rank ahead of those held by a `PUBLIC` golfer; within the same membership priority, the earlier `created_at` ranks ahead. Each standby booking's `standby_rank` is its 1-based position in that ordering while it waits; a confirmed or cancelled booking has a rank of 0. When promotion must choose one booking, it selects the single highest-priority standby — member ahead of public, then earliest `created_at`, with ties broken strictly by `created_at` and never by `id`. If the slot has no standby bookings, no promotion occurs.

### 3.8. Cancelling a Booking and the Cascade

A booking is cancelled by its holding `Golfer` or by any `ProShop` operator; a golfer who is not the holder and is not acting as `ProShop` is rejected with `ERR_NOT_BOOKING_OWNER`. Only a booking currently `CONFIRMED` or `STANDBY` may be cancelled; cancelling one already `CANCELLED` is rejected with `ERR_INVALID_STATE`. `CANCELLED` is terminal.

Cancelling a confirmed booking is the deepest cascade in the system. The booking moves from `CONFIRMED` to `CANCELLED`, its `green_fee_cents` is zeroed, and the slot's `confirmed_count` is decremented. The system then looks for a waitlisted booking to promote. If at least one standby booking exists, the highest-priority one selected by the ordering in §3.7 is promoted from `STANDBY` to `CONFIRMED`: its `standby_rank` is reset to 0, its `green_fee_cents` is computed by the green-fee procedure of §2.8 using the `pricing_tier` that was frozen when it first joined the waitlist, the slot's `confirmed_count` is incremented back up so the slot stays `FULL`, and every booking still waiting behind it has its `standby_rank` recomputed. If no standby booking exists, no promotion happens and the slot reopens, moving from `FULL` to `OPEN`. Either way the slot's `version` is incremented.

Cancelling a standby booking is simpler because it never frees a confirmed seat. The booking moves from `STANDBY` to `CANCELLED` and the remaining standby bookings on the slot have their `standby_rank` recomputed; no promotion fires.

### 3.9. The Logical Clock

The slot-start-passed rule and the refresh windows both read a server-controlled current UTC instant. An administrative test-driving capability, restricted to a `ProShop` operator, sets that clock to a supplied instant via the `to_iso8601` field. This lets a test position the clock so that a given slot's start is in the future or in the past, and so that revision effective dates can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify or act on an existing resource — closing a slot, cancelling a booking, voiding a score, and setting the clock — return a `200 OK` status code. The monthly refresh creates a new revision record and returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/golf/courses` | Create a course with rating/slope, fees, peak window, member discount | ProShop |
| GET | `/golf/courses/{id}` | Fetch a course | ProShop, Golfer, Anonymous |
| GET | `/golf/courses` | List courses (paginated) | ProShop, Golfer, Anonymous |
| POST | `/golf/golfers` | Register a golfer (MEMBER or PUBLIC) | ProShop, Anonymous |
| GET | `/golf/golfers/{id}` | Fetch a golfer including handicap fields | ProShop, Golfer, Anonymous |
| GET | `/golf/golfers` | List golfers (paginated) | ProShop, Golfer, Anonymous |
| POST | `/golf/scores` | Post a score; freezes the differential and recomputes the provisional index | ProShop, Golfer |
| GET | `/golf/scores/{id}` | Fetch a score | ProShop, Golfer, Anonymous |
| GET | `/golf/scores` | List scores, filterable by golfer or course | ProShop, Golfer, Anonymous |
| POST | `/golf/scores/{id}/void` | Void a posted score; recomputes provisional index | ProShop |
| POST | `/golf/tee-times` | Create a bookable tee-time slot on a course | ProShop |
| GET | `/golf/tee-times/{id}` | Fetch a tee time | ProShop, Golfer, Anonymous |
| GET | `/golf/tee-times` | List tee times, filterable by course and status | ProShop, Golfer, Anonymous |
| POST | `/golf/tee-times/{id}/close` | Close a tee time to new bookings | ProShop |
| POST | `/golf/tee-times/{id}/bookings` | Book a slot (CONFIRMED or STANDBY); OCC-guarded | ProShop, Golfer |
| GET | `/golf/tee-times/{id}/bookings` | List bookings on a slot | ProShop, Golfer, Anonymous |
| GET | `/golf/bookings/{id}` | Fetch a booking | ProShop, Golfer, Anonymous |
| GET | `/golf/bookings` | List bookings, filterable by golfer and status | ProShop, Golfer, Anonymous |
| POST | `/golf/bookings/{id}/cancel` | Cancel a booking; may promote the top standby | ProShop, Golfer |
| POST | `/golf/handicap-revisions` | Run a monthly Handicap Index refresh | ProShop |
| GET | `/golf/handicap-revisions` | List handicap revisions (paginated) | ProShop, Golfer, Anonymous |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | ProShop |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_BOOKING_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TEE_TIME_CLOSED` | 409 |
| `ERR_DUPLICATE_BOOKING` | 409 |
| `ERR_GOLFER_TIME_CONFLICT` | 409 |
| `ERR_SLOT_START_PASSED` | 409 |
| `ERR_SLOT_FULL_NO_STANDBY` | 409 |
| `ERR_STALE_TEE_TIME_VERSION` | 412 |
| `ERR_REVISION_NOT_MONOTONIC` | 409 |
| `ERR_TEE_INTERVAL_CONFLICT` | 409 |

# Bed And Breakfast API — Product Requirements Document

## 1. Introduction

Running a small bed-and-breakfast or boutique inn means juggling a surprising amount of moving machinery behind what guests experience as a simple stay: seasonal rates that swing with demand, two-night minimums over holiday peaks, breakfast covers that must be prepped to dietary specification, the split between guests who book directly and those who arrive through online travel agencies, deposit and cancellation policies that have to be applied fairly and consistently, the cleaning turnover that gates one guest's departure against the next guest's arrival, and the occupancy-tax paperwork that the innkeeper owes the municipality. This API is the system of record that ties all of it together.

The platform models an inn as a configuration root under which rooms, seasonal rate periods, add-on packages, guests, gift certificates, bookings, breakfast plans, housekeeping turnover tasks, and tax remittances all live as peer collections. Its central concern is correctness of money and time: every nightly charge, deposit, refund, gift redemption, and tax figure is computed in integer cents with explicit rounding rules, and every date-sensitive decision — cancellation tiers, gift-certificate expiry, no-show eligibility, turnover readiness — is evaluated against a single server-controlled logical clock rather than wall-clock time, so that the same scenario always produces the same answer. Four roles share the system, each owning a slice of the operation: innkeepers manage inventory and the front desk, guests manage their own stays, housekeepers run turnover, and finance managers own gift certificates and tax remittance.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, the acting user's identifier, and `X-User-Role`, the operational capacity in which they are acting. The system recognizes exactly four roles, spelled precisely as follows: `Innkeeper`, `Guest`, `Housekeeper`, and `FinanceManager`. A request missing either header is rejected with `ERR_UNAUTHENTICATED`; a request whose `X-User-Role` is present but is not one of the four recognized role strings is likewise rejected with `ERR_UNAUTHENTICATED`, since it does not identify a recognized caller. A request whose role is authenticated but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

The four roles bind to identity in different ways. When `X-User-Role` is `Guest`, the `X-User-ID` is the `id` of the acting `Guest` entity; ownership checks on any resource that references a `Guest` compare the resource's guest foreign key to `X-User-ID`. Concretely, a `Guest` acting on a `Booking` must own it — the `Booking`'s `guest_id` must equal the caller's `X-User-ID` — and a guest-driven booking action (confirming, cancelling, redeeming a gift toward, or requesting a refund quote for a booking) performed by a guest who is not the owner is rejected with `ERR_NOT_BOOKING_OWNER`. When `X-User-Role` is `Innkeeper`, `Housekeeper`, or `FinanceManager`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but does not compare it against any entity's `id`. The `Innkeeper` owns inventory and front-desk operations, the `Housekeeper` executes room turnover, and the `FinanceManager` owns gift-certificate voiding and tax remittance.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0. A `limit` outside `[1, 100]`, a negative `offset`, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint explicitly states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock

All date and time arithmetic in the system reads from a single server-controlled logical clock, never the host's wall-clock. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default and never drifts toward real time. An administrative test-driving capability sets the clock to a supplied instant via the `to_iso8601` field; any of the four roles may invoke it, and the operation returns `200 OK`. A `to_iso8601` value that is missing or not a parseable ISO 8601 instant is rejected with `ERR_INVALID_REQUEST`. Cancellation-tier day math, gift-certificate issuance and expiry, no-show eligibility, turnover readiness, and the dates stamped on ledger entries and remittances all derive from this clock, so advancing it is how the passage of time is simulated.

### 2.5. Common Resource Properties

Most resources expose a standard system-managed quartet. The `id` is a server-minted UUID with no type prefix, serving identity only. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. The `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that occur as cascaded side effects of an operation on another resource. The `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation; it underpins optimistic concurrency control.

Two entities are deliberately leaner. A `Guest` carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a guest profile is not mutated through a versioned lifecycle. A `PaymentLedgerEntry` is append-only: it likewise carries only `id` and `created_at`, is never updated after it is written, and exposes no `updated_at` or `version` field.

### 2.6. Monetary Values, Rates, and Rounding

Every monetary amount in the system is an integer number of cents — there are no fractional-cent or floating-point money values anywhere. Rates and multipliers are expressed in basis points, where 10000 basis points equals a factor of 1.0; for example a `rate_multiplier_bps` of 15000 is a 1.5× peak multiplier, and a `lodging_tax_rate_bps` of 1450 is a 14.50% tax. Wherever a calculation multiplies cents by a basis-point factor, the result is divided by 10000 to return to cents.

Two distinct rounding disciplines apply and must not be confused. The per-night room charge is floored to whole cents for each night individually and only then summed — round-then-sum, never sum-then-round. The lodging-tax multiplication and the percentage-based deposit and refund computations are rounded half up to whole cents. Where a rounding step and a flooring or capping step both apply, the rounding happens first and the floor or cap is applied to the already-rounded figure.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a shared parent resource.

Confirming a booking commits the stay's night interval against its room and advances that room's `version`. The confirm request must therefore carry `expected_room_version`, the room `version` the client last observed. If the room's `version` has advanced since the client read it — for instance because another booking on the same room was confirmed in the interim and now occupies an adjacent or overlapping interval — the confirm is rejected with `ERR_STALE_ROOM_VERSION` at HTTP 412, so the client never confirms against committed intervals it has not seen.

Redeeming a gift certificate toward a booking debits the certificate's remaining balance and advances the certificate's `version`. The redemption request must carry `expected_gift_certificate_version`, the certificate `version` the client last observed. If that `version` no longer matches the certificate's current `version` — because another booking already drew down part of the balance — the redemption is rejected with `ERR_STALE_GIFT_VERSION` at HTTP 412 rather than overdrawing the certificate. Operations not named in these two rules take no version field and perform no such check; the optional `expected_room_version`, `expected_package_version`, `expected_gift_certificate_version`, and `expected_tax_remittance_version` accepted on retire-room, retire-package, void, and file are convenience guards only, not part of the two mandatory OCC contracts. Each is checked only when the client supplies it (an omitted or null value is ignored), and on mismatch the request is rejected at HTTP 412: void raises `ERR_STALE_GIFT_VERSION`, while retire-room, retire-package, and file each raise `ERR_STALE_ROOM_VERSION`.

### 2.8. Hierarchical Consistency and Cascades

The entities form a flat topology — rooms, bookings, gift certificates, packages, breakfast plans, housekeeping tasks, and tax remittances are peers under the shared inn, joined by foreign-key reference rather than nested ownership. Even so, a single operation frequently mutates several resources at once, and every such cascade independently refreshes each touched resource's `updated_at` and increments its `version`. A booking checkout, for instance, settles the booking's money axis, spawns a housekeeping task, and bumps the room version in one motion; a cancellation can write a ledger entry, restore a gift certificate's balance, and cancel a breakfast plan together. These secondary effects are specified alongside the workflows that trigger them in Section 3.

### 2.9. Nested Resource Retrieval and Validation Ordering

Endpoint paths are nested under the inn (for example, a turnover task lives beneath its inn). When a path carries several identifiers, the server validates them left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve within the inn scope, before evaluating any deeper resource or business rule.

Across all write operations the system evaluates checks in a fixed precedence so that the same failure always surfaces the same error. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`). Then role permission for the operation (`ERR_FORBIDDEN`). Then, for guest-driven booking actions, booking ownership (`ERR_NOT_BOOKING_OWNER`). Then existence of every path resource, left to right (`ERR_NOT_FOUND`). Then request-body well-formedness — required fields present, enum values legal, dates parseable, and integers non-negative where constrained (`ERR_INVALID_REQUEST`). Then, for booking creation and gift redemption, that every referenced foreign key belongs to the same inn as the path (`ERR_CROSS_INN_REFERENCE`). Only after these structural gates do the domain-specific temporal, occupancy, state, fiscal, and concurrency rules described in Section 3 apply. When two business rules could both fire on one request, the lower-priority-number rule is the one reported; the relevant orderings are called out where the rules are described.

## 3. Business Logic & Workflows

### 3.1. Building the Inn: Rooms, Rate Periods, and Packages

An `Innkeeper` stands up an inn as the configuration root by supplying its `name` and `lodging_tax_rate_bps`, and optionally a daily `checkin_time` (defaulting to `15:00`), a daily `checkout_time` (defaulting to `11:00`), a `gift_cert_expiry_days` window (defaulting to 365 days), and a `turnover_minutes` buffer (defaulting to 180 minutes, that is three hours). Each created inn begins at version 1.

Rooms are added under the inn by the innkeeper, who provides the room's `name` (its descriptive label, such as "Rose Suite"; intended to be unique within the inn, though the server does not enforce this uniqueness and accepts a duplicate name), its `base_rate_cents` nightly rack rate (which must be zero or greater), its `max_occupancy` headcount (which must be at least 1), and optionally `is_taxable` (defaulting to true). A new room is born `ACTIVE` at version 1. A room may later be retired, moving its `status` to `RETIRED`; a retired room accepts no new bookings. The room's `version` is significant: it is bumped not only when the room itself is edited or retired but on every booking confirm, checkout, cancellation, and no-show that commits or releases one of its night intervals — which is exactly why confirm participates in optimistic concurrency control.

Seasonal pricing is expressed through inn-wide rate periods, each created by the innkeeper with a human `label` (for example "Summer Peak"), an inclusive `start_date` and inclusive `end_date` in `YYYY-MM-DD` form, a `rate_multiplier_bps` applied to each room's base rate for nights falling inside the window (which must be zero or greater), and an optional `min_nights` floor (defaulting to 1, and never less than 1). A rate period created with an `end_date` earlier than its `start_date` is rejected with `ERR_INVALID_DATE_RANGE`. A rate period applies to every room of the inn, not to one room.

Add-on packages are likewise inn-scoped and innkeeper-owned. A package carries a `name`, an optional `flat_add_cents` charged once per booking that selects it (defaulting to 0, zero or greater), an optional `per_night_add_cents` charged for each night of the stay (defaulting to 0, zero or greater), and an optional `is_taxable` flag that defaults to false — package revenue is, by default, not subject to lodging tax. A package is created `ACTIVE` at version 1 and may be retired to `RETIRED`, after which it cannot be selected on new bookings.

### 3.2. Guests, Bookings, and the Price of a Stay

Guests register themselves (or are registered by an innkeeper) with a `full_name` and an `email` that is intended to be unique within the inn, though the server does not enforce this uniqueness and accepts a duplicate email; each guest is scoped to its inn via `inn_id`. A guest record holds only its identity and creation time.

A booking is created by a guest (for their own stay) or by an innkeeper, referencing the `room_id`, the `guest_id`, an optional `package_id`, and the booking `channel`, which is either `DIRECT` (booked through the inn) or `OTA` (booked through an online travel agency). A guest creating a booking may only book for their own stay: when the caller is a `Guest`, the supplied `guest_id` must equal the caller's `X-User-ID`, and a mismatch is rejected with `ERR_NOT_BOOKING_OWNER` (this ownership check is evaluated after the same-inn foreign-key checks). An OTA booking may carry an `ota_commission_bps` recording the commission the agency withholds; for a `DIRECT` booking this is forced to 0 and ignored. The stay is described by a `checkin_date` (the first occupied night) and a `checkout_date` (the departure morning), both `YYYY-MM-DD`, together with a `guest_count`. A booking enters the world in `reservation_status` `PENDING` and `payment_status` `UNPAID`, with `refund_cents` initialized to 0, `cancelled_on` to null, and `remitted` to false.

Several checks gate booking creation. The departure must be strictly after arrival so that the stay spans at least one night; otherwise `ERR_INVALID_DATE_RANGE`. The `guest_count` must be at least 1 — a value below 1 fails the body-well-formedness gate with `ERR_INVALID_REQUEST` — and it must not exceed the room's `max_occupancy`, in which case the request is rejected with `ERR_OCCUPANCY_EXCEEDED`. Booking against a `RETIRED` room, or selecting a package that is not `ACTIVE`, is rejected with `ERR_RESOURCE_RETIRED`. Every foreign key — `room_id`, `guest_id`, `package_id` — must belong to the same inn as the path, failing which the request is `ERR_CROSS_INN_REFERENCE`. And the two-night-minimum rule applies: the system computes `nights` and, if the stay touches any night governed by a rate period whose `min_nights` exceeds 1, requires `nights` to be at least the largest such `min_nights` across all touched periods; a shorter stay is rejected with `ERR_MIN_NIGHTS_NOT_MET`.

At creation the system computes the full price ladder and stores it on the booking. The night count, `nights`, is the number of whole days from `checkin_date` to `checkout_date`; the occupied nights are the half-open span running from the check-in night up to but not including the checkout date, so the checkout date itself is never charged. The `room_charge_cents` is built night by night in ascending date order: for each occupied night the system finds the rate period of the inn whose inclusive window contains that night, and when several periods contain it, it chooses the one with the highest `rate_multiplier_bps`, breaking any tie toward the period with the earlier `created_at`; if no period contains the night, a default multiplier of 10000 (factor 1.0) is used. That night's charge is the room's `base_rate_cents` multiplied by the chosen multiplier basis points divided by 10000, floored to whole cents, and these per-night figures are summed in that pinned order to yield `room_charge_cents`.

The `package_charge_cents` is 0 when no package was selected; otherwise it is the package's `flat_add_cents` plus its `per_night_add_cents` multiplied by `nights`. The `taxable_base_cents` accumulates only the revenue lines whose taxability is switched on: the room charge counts toward it only when the room's `is_taxable` is true, and the package charge counts toward it only when a package was selected and that package's `is_taxable` is true. The `lodging_tax_cents` is the `taxable_base_cents` multiplied by the inn's `lodging_tax_rate_bps` divided by 10000, rounded half up to whole cents. The `total_cents` is the sum of `room_charge_cents`, `package_charge_cents`, and `lodging_tax_cents`. Each of these money fields is recomputed at confirm time so the figures reflect the inventory and rate configuration as of confirmation. For reconciliation the booking also exposes `net_inn_revenue_cents`, the `total_cents` less the OTA commission (which applies only to the `OTA` channel) and less the `lodging_tax_cents` the inn merely collects on the municipality's behalf. The OTA commission is computed as `total_cents` multiplied by the booking's `ota_commission_bps` divided by 10000, rounded half up to whole cents (and is 0 for a `DIRECT` booking). `net_inn_revenue_cents` is recomputed alongside the rest of the ladder whenever the booking's money is recomputed, so on a freshly created booking it already reflects this formula and may be present (and, for an `OTA` booking with commission, less than `total_cents`) even before any payment.

### 3.3. Deposits, Cash Payments, and Gift Redemption

Every booking carries a `deposit_due_cents`, the amount that must be collected before the stay can be confirmed, and the policy is keyed on `channel`. For a `DIRECT` booking the deposit is 30% of `total_cents`, rounded half up to whole cents; for an `OTA` booking the deposit is the entire `total_cents`, since OTA stays prepay in full. A first-night floor then applies after rounding: the deposit is never less than the nightly charge of the first occupied night (the same floored per-night figure that opened the room-charge sum), so `deposit_due_cents` is the larger of the channel-policy amount and that first-night charge. For OTA the floor is inert, since a full-total prepayment already meets or exceeds one night.

Money flows onto a booking through two channels, both recorded as immutable `PaymentLedgerEntry` rows. A cash deposit is recorded by a guest or innkeeper supplying an `amount_cents`; the amount must be at least 1 and must not exceed the outstanding balance — the `total_cents` minus the current `deposit_paid_cents` — or the payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. A successful payment appends a `DEPOSIT` ledger entry with that positive amount and recomputes `deposit_paid_cents`. The `deposit_paid_cents` figure is the sum of `DEPOSIT` and `REDEMPTION` entry amounts (money in, including gift redemptions) net of any `REFUND` entries.

A gift certificate is applied toward the same outstanding balance through redemption. The redeemer supplies the `gift_certificate_id`, an `amount_cents`, and — as the optimistic-concurrency guard from §2.7 — the `expected_gift_certificate_version`, all three of which are required (a missing one is rejected with `ERR_INVALID_REQUEST`). The referenced `gift_certificate_id` must belong to the same inn as the path, else `ERR_CROSS_INN_REFERENCE`; the `expected_gift_certificate_version` is then matched against the certificate's current `version`, with a mismatch rejected as `ERR_STALE_GIFT_VERSION` (HTTP 412) before any of the sufficiency conditions below are evaluated. The redemption amount must be at least 1 and no greater than the lesser of the certificate's `remaining_cents` and the booking's outstanding owed balance (`total_cents` minus `deposit_paid_cents`); the certificate must be `ACTIVE` and not yet expired, meaning the logical clock date is strictly before its `expires_on`. A redemption that breaks any of these sufficiency conditions is rejected with `ERR_GIFT_INSUFFICIENT`. A valid redemption appends a positive `REDEMPTION` ledger entry that records the drawing certificate in its `gift_certificate_id`, debits the certificate's `remaining_cents` by the redeemed amount, increments the certificate's `version`, recomputes `deposit_paid_cents`, and — if the debit drives `remaining_cents` to exactly 0 — moves the certificate to `DEPLETED`. Each ledger entry also stamps the `occurred_on` date from the logical clock and carries a `source_kind` of `DEPOSIT`, `REFUND`, `REDEMPTION`, or `FORFEIT`; deposits and redemptions are positive money-in amounts, a refund is a negative money-out amount, and a forfeit is a zero-amount audit marker.

### 3.4. The Reservation Lifecycle

A booking's `reservation_status` walks a lifecycle of `PENDING`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, `CANCELLED`, and `NO_SHOW`, where `CHECKED_OUT`, `CANCELLED`, and `NO_SHOW` are terminal. Running in parallel on the same row is the `payment_status` money axis — `UNPAID`, `DEPOSIT_HELD`, `SETTLED`, `REFUNDED`, `FORFEITED` — which is never set directly by a client but only as a side effect of reservation transitions, with `REFUNDED` and `FORFEITED` terminal.

Confirming a booking advances it from `PENDING` to `CONFIRMED`. Confirmation requires the booking to be `PENDING`, the room to be `ACTIVE`, the deposit to be fully covered (`deposit_paid_cents` at least `deposit_due_cents`, possibly reached via gift redemption), and the night interval to be free of conflict. The overlap check (priority 70) looks at the half-open night interval running from `checkin_date` up to `checkout_date` and rejects the confirm with `ERR_ROOM_DOUBLE_BOOKED` if any other `CONFIRMED` or `CHECKED_IN` booking on the same room overlaps it; because the interval is half-open, a booking that ends exactly on the night another begins does not overlap, so same-day back-to-back turnover is permitted at the date level. If the deposit is short the confirm is rejected with `ERR_DEPOSIT_NOT_MET`; the deposit-coverage check (priority 80) is evaluated after the double-booking check, and both presuppose the booking is actually `PENDING` — a confirm on a booking in any other state fails the state guard with `ERR_INVALID_STATE`. The room-`ACTIVE` requirement is likewise enforced with `ERR_INVALID_STATE`: a confirm whose room has been `RETIRED` is rejected with `ERR_INVALID_STATE`, and this room-state check is evaluated after the deposit-coverage check. A successful confirm, which also carries `expected_room_version` and is rejected with `ERR_STALE_ROOM_VERSION` if that value no longer matches the room's `version` (§2.7), drives the money axis from `UNPAID` to `DEPOSIT_HELD` and increments the room's `version` by 1, committing the interval.

Checking in advances a `CONFIRMED` booking to `CHECKED_IN`. It requires the booking to be `CONFIRMED`, the logical clock date to have reached `checkin_date` (on or after it), and the room's turnover to be satisfied. The turnover gate (priority 72) looks at the room's most recent non-`SKIPPED` housekeeping task: it must be `DONE` (or there must be no such task at all for a fresh room) and its `ready_after` instant must be at or before the current logical clock; a check-in attempted while turnover is unmet is rejected with `ERR_TURNOVER_NOT_READY`. This buffer is an instant-level gap distinct from the date-level overlap rule of confirmation.

Checking out advances a `CHECKED_IN` booking to `CHECKED_OUT`. This single operation settles and cleans: the money axis moves from `DEPOSIT_HELD` to `SETTLED` (the balance is considered collected), a new housekeeping task is created in `PENDING` for the room with its `ready_after` set to the checkout instant plus the inn's `turnover_minutes`, and the room's `version` is incremented by 1.

### 3.5. Cancellations, No-Shows, and What Comes Back

A guest or innkeeper may cancel a booking while it is `PENDING` or `CONFIRMED`; a cancel from any other state is rejected with `ERR_INVALID_STATE`. Cancellation stamps `cancelled_on` with the current logical-clock date and computes `refund_cents` from the cancellation-refund tier table, which is keyed on the number of days between cancellation and arrival.

The refund tier is determined by `days_before`, the day count from `cancelled_on` to `checkin_date`, never allowed to go negative (a same-day or post-arrival cancellation is treated as 0). When `days_before` is 14 or more the refund is 100% of `deposit_paid_cents`; when it is at least 7 but fewer than 14 the refund is 50%; when it is at least 1 but fewer than 7 the refund is 10%; and when it is 0 (same day) the refund is nothing. The gross refund is `deposit_paid_cents` multiplied by the tier percentage and rounded half up to whole cents. One channel override applies on top of the table: an `OTA` booking cancelled with fewer than 14 days before arrival refunds nothing at all, regardless of which tier the day count would otherwise select.

The cancellation's side effects follow the computed refund. If `refund_cents` is greater than 0, the system appends a `REFUND` ledger entry carrying the negative refund amount and moves `payment_status` to `REFUNDED`. If `refund_cents` is 0 but the guest had paid something (`deposit_paid_cents` greater than 0), the system instead appends a zero-amount `FORFEIT` ledger entry and moves `payment_status` to `FORFEITED`. If `refund_cents` is 0 and nothing had been paid (`deposit_paid_cents` is 0), no ledger entry is written and `payment_status` is left unchanged at whatever it was (`UNPAID` or `DEPOSIT_HELD`). In all of these cases the room's `version` is incremented by 1 as the night interval is released and the room becomes re-bookable, and any breakfast plan still in `REQUESTED` or `CONFIRMED` for that booking cascades to `CANCELLED`.

When the cancelled booking had drawn on a gift certificate, the refund is paid back in a pinned waterfall order: cash first, then gift balance. The system looks at the booking's ledger and computes the cash deposit total (the sum of `DEPOSIT` entry amounts) and the redeemed gift total; the `refund_cents` is allocated to the cash bucket first, up to the amount of cash actually deposited, and only the remainder spills into the gift bucket. Exactly one negative `REFUND` ledger entry is written, and its magnitude is the cash portion of the refund whenever any cash was refunded; only when the entire refund flows to the gift bucket (no cash portion) does that single `REFUND` entry instead carry the gift-restored amount. The gift remainder is added back to certificate balances by walking the booking's `REDEMPTION` entries in most-recent-first (LIFO) order and restoring up to each redemption's amount until the remainder is exhausted; for the common single-certificate case the whole remainder returns to that certificate's `remaining_cents`. If a certificate had been sitting in `DEPLETED`, the restoration of a positive balance returns it to `ACTIVE` — provided its `expires_on` is still in the future relative to the logical clock.

Before committing to a cancel, a guest or innkeeper may pull a what-if refund quote on a booking — typically one still `CONFIRMED`, though the quote endpoint applies no reservation-status guard and will return a provisional figure for a booking in any state. The quote computes the refund the guest would receive if they cancelled at the current logical clock instant, using the same tier table but measuring `days_before` from today rather than from a stored cancellation date (the day count is clamped to never go negative, so a same-day or past arrival quotes a `days_before` of 0). The quote is purely advisory: it returns a booking snapshot whose `refund_cents` reflects the provisional figure but mutates nothing — no state change, no ledger entry, no gift restoration.

A no-show is the innkeeper's remedy for a confirmed guest who never arrives. It advances a `CONFIRMED` booking to `NO_SHOW`, but only after the arrival night has fully passed: the logical clock date must be strictly greater than `checkin_date`, and an attempt made before that point is rejected with `ERR_INVALID_STATE` as not yet no-show-eligible. A no-show forfeits the entire deposit with no refund — `payment_status` moves to `FORFEITED`, a zero-amount `FORFEIT` ledger entry is appended, the room's `version` is incremented by 1 as the interval is released, and any `REQUESTED` or `CONFIRMED` breakfast plan cascades to `CANCELLED`.

### 3.6. Breakfast and Dietary Plans

A booking may carry a single breakfast plan, requested by a guest or innkeeper against the `booking_id`, specifying a `party_size` (the number of covers to prepare each morning, at least 1) and an optional set of `dietary_flags`. The flags are drawn from `VEGETARIAN`, `VEGAN`, `GLUTEN_FREE`, `NUT_FREE`, and `DAIRY_FREE`, with the understanding that `VEGAN` implies `VEGETARIAN`; a `dietary_flags` value that is not a list, or that contains any token outside this set, is rejected with `ERR_INVALID_REQUEST`. When `VEGAN` is supplied, `VEGETARIAN` is materialized into the stored set as well, and the stored `dietary_flags` are normalized to a deduplicated, alphabetically sorted list. The referenced `booking_id` must resolve to a booking of the same inn (otherwise `ERR_NOT_FOUND`). The `party_size` must not exceed the parent booking's `guest_count`; an over-large party is rejected with `ERR_BREAKFAST_OVER_PARTY`. A new plan starts in `REQUESTED`.

The kitchen commits covers by confirming the plan, an innkeeper action that advances it from `REQUESTED` to `CONFIRMED`. Confirmation is allowed only while the plan is `REQUESTED` and the parent booking is `CONFIRMED` or `CHECKED_IN` — the kitchen will not commit covers for a stay that is not live — and a confirm in any other situation is rejected with `ERR_INVALID_STATE`. A plan may be cancelled from `REQUESTED` or `CONFIRMED`, either explicitly by a guest or innkeeper or implicitly as the cascade fired when its parent booking is cancelled or marked no-show; a cancel from any other status is rejected with `ERR_INVALID_STATE`, and `CANCELLED` is terminal. When a guest creates or explicitly cancels a breakfast plan, the guest must own the parent booking — the booking's `guest_id` must equal the caller's `X-User-ID`, else the request is rejected with `ERR_NOT_BOOKING_OWNER`.

### 3.7. Room Turnover

Each checkout spawns a housekeeping task that gates the next check-in on the same room. A task is born `PENDING`, copies the originating `booking_id` and the `room_id` from the booking, and carries a `ready_after` instant equal to the checkout instant plus the inn's `turnover_minutes` buffer — the earliest moment the room may receive a new arrival.

A `Housekeeper` works the task through its branches. Starting turnover advances it from `PENDING` to `IN_PROGRESS`, and completing it advances it from `IN_PROGRESS` to `DONE`; either action taken out of its required starting state is rejected with `ERR_INVALID_STATE`. Alternatively the innkeeper may skip turnover, advancing it directly from `PENDING` to `SKIPPED` to waive cleaning. Both `DONE` and `SKIPPED` are terminal, and both release the room for a new check-in once the `ready_after` instant has been reached on the logical clock — which is precisely the condition the check-in turnover gate of §3.4 enforces.

### 3.8. Gift Certificates

A `FinanceManager` or `Innkeeper` issues a gift certificate against an inn, supplying only its `face_value_cents` (which must be at least 1). The server mints everything else: a redemption `code` unique within the inn, an `issued_on` date stamped from the logical clock, an `expires_on` date computed as `issued_on` plus the inn's `gift_cert_expiry_days`, and an initial `remaining_cents` equal to the face value. The certificate starts `ACTIVE` at version 1, and its `remaining_cents` is a computed running balance that never goes negative.

A certificate's `status` branches through `ACTIVE`, `DEPLETED`, `EXPIRED`, and `VOID`, with `EXPIRED` and `VOID` terminal. As covered in §3.3, a redemption that zeroes the balance drives `ACTIVE` to `DEPLETED`, and a cancellation that restores balance returns a `DEPLETED` certificate to `ACTIVE` so long as it has not expired. A certificate is treated as expired — and a redemption attempt against it refused — once the logical clock date reaches or passes `expires_on`. Expiry is evaluated dynamically from the clock at the moment of each redemption; the server never writes `EXPIRED` into the stored `status`, so an expired certificate continues to report whatever stored status it last held (`ACTIVE` or `DEPLETED`) even though redemptions against it are refused. A `FinanceManager` may void a certificate, moving it from `ACTIVE` to `VOID`, but only when it has never been redeemed (no `REDEMPTION` ledger entry references it, equivalently its `remaining_cents` still equals its `face_value_cents`); a void attempt on a partially redeemed certificate fails the state guard with `ERR_INVALID_STATE`. A voided certificate can no longer be redeemed. The redemption ledger of a certificate can be listed to see every `REDEMPTION` entry that drew on it.

### 3.9. Occupancy and Lodging Tax Remittance

A `FinanceManager` periodically sweeps collected lodging tax into a remittance batch for filing with the municipality. Opening a remittance supplies the inn (`inn_id`), an inclusive `period_start` and `period_end` date window (with `period_end` required to be on or after `period_start`, else `ERR_INVALID_DATE_RANGE`), and a `variant` of `ESTIMATED` or `FINAL`. The window is matched against each booking's `checkout_date`.

The variant decides which bookings are swept, and both variants consider only bookings of the inn whose `remitted` flag is still false and whose `checkout_date` falls within the window. An `ESTIMATED` remittance is a forward-looking accrual: it sweeps bookings in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT` status. A `FINAL` remittance sweeps only realized revenue: bookings in `CHECKED_OUT` status. Because the final pool is a subset of the estimated pool, the final total for a window never exceeds the estimated total for the same window. At open time the system records `swept_booking_count`, the number of bookings in the pool, and `tax_total_cents`, the straight sum of the already-rounded `lodging_tax_cents` across those bookings, and it fixes the identity of the swept set itself at this moment. A remittance is created `OPEN` at version 1.

Filing a remittance is a `FinanceManager` action that advances it from `OPEN` to `FILED`, freezes `swept_booking_count` and `tax_total_cents` at their filed values, and stamps `remitted` true on every booking in the swept set — the set of booking identities fixed when the remittance was opened, not a fresh re-sweep at file time. Filing is permitted only while the remittance is `OPEN` (otherwise `ERR_INVALID_STATE`) and only when none of the swept bookings has already been remitted by an earlier filing; if any swept booking already carries `remitted` true, the filing is refused with `ERR_ALREADY_REMITTED` so the same revenue is never remitted twice.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, payments, redemptions, and filings — return `200 OK`. The administrative clock-setting endpoint also returns `200 OK`.

The full request and response shape for each endpoint, including which fields are required in the body and which side effects fire, is described in Section 3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Innkeeper, FinanceManager, Housekeeper, Guest |
| POST | `/inns` | Create an inn | Innkeeper |
| GET | `/inns/{inn_id}` | Get an inn | Innkeeper, FinanceManager, Housekeeper, Guest |
| POST | `/inns/{inn_id}/rooms` | Create a room | Innkeeper |
| GET | `/inns/{inn_id}/rooms` | List rooms | Innkeeper, FinanceManager, Housekeeper, Guest |
| GET | `/inns/{inn_id}/rooms/{room_id}` | Get a room | Innkeeper, FinanceManager, Housekeeper, Guest |
| POST | `/inns/{inn_id}/rooms/{room_id}/retire` | Retire a room | Innkeeper |
| POST | `/inns/{inn_id}/rate-periods` | Create a rate period | Innkeeper |
| GET | `/inns/{inn_id}/rate-periods` | List rate periods | Innkeeper, FinanceManager, Housekeeper, Guest |
| GET | `/inns/{inn_id}/rate-periods/{rate_period_id}` | Get a rate period | Innkeeper, FinanceManager, Housekeeper, Guest |
| POST | `/inns/{inn_id}/packages` | Create a package | Innkeeper |
| GET | `/inns/{inn_id}/packages` | List packages | Innkeeper, FinanceManager, Housekeeper, Guest |
| GET | `/inns/{inn_id}/packages/{package_id}` | Get a package | Innkeeper, FinanceManager, Housekeeper, Guest |
| POST | `/inns/{inn_id}/packages/{package_id}/retire` | Retire a package | Innkeeper |
| POST | `/inns/{inn_id}/guests` | Register a guest | Innkeeper, Guest |
| GET | `/inns/{inn_id}/guests` | List guests | Innkeeper, FinanceManager |
| GET | `/inns/{inn_id}/guests/{guest_id}` | Get a guest | Innkeeper, FinanceManager, Guest |
| POST | `/inns/{inn_id}/gift-certificates` | Issue a gift certificate | FinanceManager, Innkeeper |
| GET | `/inns/{inn_id}/gift-certificates` | List gift certificates | FinanceManager, Innkeeper, Guest |
| GET | `/inns/{inn_id}/gift-certificates/{gift_certificate_id}` | Get a gift certificate | FinanceManager, Innkeeper, Guest |
| GET | `/inns/{inn_id}/gift-certificates/{gift_certificate_id}/redemptions` | List redemptions drawing on a gift certificate | FinanceManager, Innkeeper, Guest |
| POST | `/inns/{inn_id}/gift-certificates/{gift_certificate_id}/void` | Void an unredeemed gift certificate | FinanceManager |
| POST | `/inns/{inn_id}/bookings` | Create a booking | Innkeeper, Guest |
| GET | `/inns/{inn_id}/bookings` | List bookings | Innkeeper, FinanceManager, Guest |
| GET | `/inns/{inn_id}/bookings/{booking_id}` | Get a booking | Innkeeper, FinanceManager, Guest |
| POST | `/inns/{inn_id}/bookings/{booking_id}/pay-deposit` | Record a cash deposit | Innkeeper, Guest |
| POST | `/inns/{inn_id}/bookings/{booking_id}/redeem-gift` | Redeem a gift certificate toward a booking | Innkeeper, Guest |
| GET | `/inns/{inn_id}/bookings/{booking_id}/refund-quote` | What-if cancellation refund quote | Innkeeper, Guest |
| POST | `/inns/{inn_id}/bookings/{booking_id}/confirm` | Confirm a booking | Guest, Innkeeper |
| POST | `/inns/{inn_id}/bookings/{booking_id}/check-in` | Check a booking in | Innkeeper |
| POST | `/inns/{inn_id}/bookings/{booking_id}/check-out` | Check a booking out | Innkeeper |
| POST | `/inns/{inn_id}/bookings/{booking_id}/cancel` | Cancel a booking | Guest, Innkeeper |
| POST | `/inns/{inn_id}/bookings/{booking_id}/mark-no-show` | Mark a booking as a no-show | Innkeeper |
| GET | `/inns/{inn_id}/bookings/{booking_id}/ledger` | List a booking's ledger entries | Innkeeper, FinanceManager, Guest |
| GET | `/inns/{inn_id}/payment-ledger-entries` | List ledger entries across the inn | Innkeeper, FinanceManager, Guest |
| GET | `/inns/{inn_id}/payment-ledger-entries/{payment_ledger_entry_id}` | Get a ledger entry | Innkeeper, FinanceManager, Guest |
| POST | `/inns/{inn_id}/breakfast-plans` | Create a breakfast plan | Innkeeper, Guest |
| GET | `/inns/{inn_id}/breakfast-plans` | List breakfast plans | Innkeeper, Guest |
| GET | `/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}` | Get a breakfast plan | Innkeeper, Guest |
| POST | `/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}/confirm` | Confirm a breakfast plan | Innkeeper |
| POST | `/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}/cancel` | Cancel a breakfast plan | Innkeeper, Guest |
| GET | `/inns/{inn_id}/housekeeping-tasks` | List turnover tasks | Innkeeper, Housekeeper |
| GET | `/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}` | Get a turnover task | Innkeeper, Housekeeper |
| POST | `/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/start` | Begin turnover | Housekeeper |
| POST | `/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/complete` | Finish turnover | Housekeeper |
| POST | `/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/skip` | Skip turnover | Innkeeper |
| POST | `/inns/{inn_id}/tax-remittances` | Open a tax remittance batch | FinanceManager |
| GET | `/inns/{inn_id}/tax-remittances` | List tax remittances | FinanceManager, Innkeeper |
| GET | `/inns/{inn_id}/tax-remittances/{tax_remittance_id}` | Get a tax remittance | FinanceManager, Innkeeper |
| POST | `/inns/{inn_id}/tax-remittances/{tax_remittance_id}/file` | File a tax remittance | FinanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_BOOKING_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CROSS_INN_REFERENCE` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_OCCUPANCY_EXCEEDED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RESOURCE_RETIRED` | 409 |
| `ERR_BREAKFAST_OVER_PARTY` | 422 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_TURNOVER_NOT_READY` | 409 |
| `ERR_MIN_NIGHTS_NOT_MET` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_GIFT_INSUFFICIENT` | 422 |
| `ERR_DEPOSIT_NOT_MET` | 422 |
| `ERR_ALREADY_REMITTED` | 409 |
| `ERR_STALE_ROOM_VERSION` | 412 |
| `ERR_STALE_GIFT_VERSION` | 412 |

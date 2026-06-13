# Parks & Rec Reservation API — Product Requirements Document

## 1. Introduction

Municipal parks departments juggle a finite stock of bookable assets — ball fields, courts, pools, and pavilions — against a constant stream of demand from residents, leagues, and outside organizations. This API is the system of record for that allocation problem. It governs the full arc of a reservation: a patron applies for a permit on a specific facility and time window, an operations coordinator reviews the request against availability and policy, money changes hands for both a usage fee and a refundable security deposit, and the slot is eventually completed, cancelled, or written off as a no-show.

The design has to reconcile several pressures that pull in different directions. Residents expect discounted pricing and priority for the most desirable evening slots, so the system distinguishes a verified resident from a walk-up applicant and runs a deterministic lottery for contested prime windows. Leagues need to book the same hour every week for a season, which means a single application can fan out into dozens of child reservations that must be granted, waitlisted, or cancelled as a coordinated group. Liability concerns require proof of insurance on file before certain facilities can be handed over. And because two coordinators may try to grant overlapping permits at the same moment, the platform enforces optimistic concurrency on each facility so the loser of a race is told their view is stale rather than silently double-booking the field.

This document specifies the entities, state machines, pricing and refund calculations, validation ordering, and role-based permissions that together make the reservation pipeline correct and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If the `X-User-Role` header is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the header names a valid role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly three roles: `RecCoordinator`, `Patron`, and `FinanceClerk`.

When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron`. Ownership checks compare the targeted resource's owning-patron foreign key to `X-User-ID`: for a permit, the `patron_id`; for an insurance certificate, its `patron_id`; for a lottery entry, its `patron_id`; for a league series, its `patron_id`. When a `Patron` attempts to cancel a permit, withdraw a lottery entry, or create an insurance certificate for a patron other than themselves — that is, on a resource whose owning patron is not `X-User-ID` — the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `RecCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `RecCoordinator` runs the operational side of the system — granting and denying permits, completing reservations and marking no-shows, opening and drawing lotteries, revoking certificates, and driving the logical clock and ops sweep. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the `FinanceClerk` captures payments and reads the payment and refund ledger.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed bound is rejected with `ERR_PAGINATION_INVALID` (HTTP 422).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in this system — patrons, facilities, insurance certificates, league series, permits, payments, refunds, lottery rounds, and lottery entries — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation to the resource. The `version` field is an integer that begins at 1 on creation and increments by one on every mutation; it underpins the optimistic-concurrency mechanism described in §2.6. All nine resource types in this system carry the full set, including `updated_at` and `version`.

### 2.5. Hierarchical Consistency and Derived Counts

Several entities maintain counters and statuses that are derived from the state of related resources, and the system keeps these in lockstep with their sources rather than expecting clients to refresh them. A `Facility` tracks `granted_permit_count`, the number of permits on it currently in `GRANTED` state; this rises and falls automatically as permits are granted, cancelled, completed, or marked no-show. A `LeagueSeries` tracks `granted_occurrence_count` (its child permits currently in `GRANTED`) and `conflicted_occurrence_count` (its child permits in `WAITLISTED` or `DENIED`), and its own `status` bubbles up from those counts. A `LotteryRound` tracks `entry_count`, the number of its entries in `ENTERED` state.

When an operation changes a child resource in a way that affects a parent's derived state, the system recomputes the parent in the same operation and treats that recomputation as a mutation of the parent — refreshing the parent's `updated_at` and incrementing its `version`. The facility `version` bump is especially load-bearing: it is the signal the concurrency control in §2.6 keys on. Note carefully which operations do and do not touch a facility's counters and version, because the rules differ by outcome and are spelled out per transition in §3.

### 2.6. Optimistic Concurrency on Facilities

Two operations write through a facility's availability and therefore guard against acting on a stale view of it: granting a permit, and drawing a lottery round. Both require the caller to submit `expected_facility_version` as a mandatory field carrying the `version` of the target `Facility` as the client last observed it.

When a permit is granted, the request must carry `expected_facility_version` matching the target facility's current `version`. If another writer — a competing grant, or a lottery draw that just placed a permit into the same prime window — has advanced the facility's `version` since the client last read it, the value no longer matches and the grant is rejected with `ERR_STALE_VERSION` (HTTP 412). This is what prevents a coordinator from granting into a slot that has been consumed under the double-booking rule between their read and their write.

The same protection applies when a lottery round is drawn: the draw request must carry `expected_facility_version` matching the facility's current `version`, and if a grant has advanced that `version` since the client last read it — potentially occupying the very prime slot the round allocates — the draw is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a facility version field for concurrency purposes; the facility-reconfiguration endpoint described in §3 separately accepts `expected_facility_version` to guard its own edit, but permit-application, payment, cancellation, completion, no-show, lottery entry, and all read endpoints do not.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents. Wherever a calculation produces a fractional cent it is resolved by rounding half up to a whole cent. The two pricing calculations differ deliberately in *when* that rounding happens relative to summation — the provisional quote rounds each component before summing, while the final grant fee sums first and rounds once — and those orderings are pinned in §3; they are not interchangeable, and identical inputs can legitimately yield a one-cent difference between the two. Hours used inside these calculations are kept as exact values and only the resulting cents amount is rounded.

### 2.8. Nested Resource Retrieval and Existence Validation

Many paths name more than one resource — for example a permit lives under its facility, and a lottery entry's actions reference its round. When a path or body names resource identifiers, the system validates their existence left-to-right along the path, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A grant request naming a non-existent facility fails on the facility before the permit is even looked up. This existence pass runs after authentication and role authorization but before business rules. A request whose body is malformed, omits a required field, or supplies an enum or range value outside its allowed set — for instance a `residency` that is neither `RESIDENT` nor `NON_RESIDENT`, or a `resident_discount_pct` that is not at least 0 and strictly less than 1 — is rejected with `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Patrons, Residency, and Standing

A patron is registered with a `full_name`, an `email` (which must be unique across all patrons), and a `residency` value that is one of `RESIDENT` or `NON_RESIDENT`. On registration the patron starts in `GOOD` standing with `no_show_strikes` set to 0, `wallet_credit_cents` set to 0, and `residency_verified` set to false.

Declaring oneself a resident is not enough to earn resident pricing. A coordinator must accept a proof of address, which sets `residency_verified` to true; this flag is only meaningful when `residency` is `RESIDENT`. Resident pricing and the heavier lottery weight both require `residency_verified` to be true in addition to a `residency` of `RESIDENT`.

A patron's `standing` is one of `GOOD`, `PROBATION`, or `BARRED`, and it is computed from `no_show_strikes` rather than set directly. The threshold cascade is evaluated against the strike count: if `no_show_strikes` is at least 4 the standing is `BARRED`; otherwise if `no_show_strikes` is at least 2 the standing is `PROBATION`; otherwise the standing is `GOOD`. These two thresholds — two strikes for probation and four strikes for being barred — are checked with at-least (inclusive) comparisons. A `PROBATION` patron may still apply and may still be granted ordinary slots, but is blocked from prime-window grants (see §3.5). A `BARRED` patron can neither apply nor be granted at all. Standing is recomputed whenever `no_show_strikes` changes — on a no-show, during the ops sweep, and when a strike count is injected directly for testing — and that injection capability sets `no_show_strikes` to the supplied `strikes` value and recomputes standing immediately.

The `wallet_credit_cents` balance accumulates refund credits whenever a refund is directed to credit rather than the original payment method, as described in §3.7.

### 3.2. Facilities and Their Pricing Configuration

A `RecCoordinator` creates a facility with a `name` and a `facility_type` that is one of `FIELD`, `COURT`, `POOL`, or `PAVILION`. A facility opens in `status` `OPEN`, with `granted_permit_count` at 0 and `version` at 1. A facility's `status` is one of `OPEN` or `CLOSED`; a `CLOSED` facility blocks new grants.

Pricing is configured per facility. The `hourly_rate_cents` is the base non-resident hourly rate in cents. The `resident_discount_pct` is the fractional discount applied to verified residents — for example a value of 0.40 means residents pay 60 percent of the base rate — and it must be at least 0 and strictly less than 1. The `prime_multiplier` is applied to the portion of a booking that falls inside the facility's prime window. The prime window itself is defined by `prime_start_hour` and `prime_end_hour`: `prime_start_hour` is an integer at least 0 and less than 24, and `prime_end_hour` is an integer strictly greater than `prime_start_hour` and at most 24, with the window treated as half-open so that the end hour is excluded.

Three further settings govern turnover, deposits, and insurance. The `buffer_minutes` value is a mandatory gap enforced between two granted permits on the facility for turnover and cleaning, defaulting to 0. The `deposit_cents` value is the refundable security deposit required to grant a permit on the facility, defaulting to 0. The `requires_coi` flag, defaulting to false, marks a facility where a valid certificate of insurance must be on file at grant time; when it is set, `min_coi_coverage_cents` (defaulting to 0) is the minimum coverage that certificate must carry.

A coordinator may reconfigure a facility — toggling its `status` between `OPEN` and `CLOSED` and adjusting `buffer_minutes`, `deposit_cents`, `requires_coi`, or `min_coi_coverage_cents`. Because this edit competes with grants for the facility's version, it requires `expected_facility_version` and increments the facility's `version` by one when it succeeds.

### 3.3. Applying for a Permit and the Provisional Quote

A permit application targets a facility and is made by, or on behalf of, a patron. The applicant supplies the `patron_id`, the reservation's `start_at`, its `end_at` (treated as exclusive), and optionally a `coi_id` naming an insurance certificate to present. A new permit enters `status` `APPLIED`. Its `facility_id` records the facility, its `patron_id` the applicant; `league_id` and `lottery_round_id` are left null on a direct application and are only set by the system when a permit is born from a league series or a lottery win respectively.

The reservation window must be well-formed: `start_at` must be strictly before `end_at`, and both must lie in the future relative to the current clock at application time. A window that violates either rule is rejected with `ERR_INVALID_WINDOW` (HTTP 422). The same well-formedness check applies when a league series is created. A patron whose `standing` is `BARRED` cannot apply; such an application is rejected with `ERR_PATRON_BARRED` (HTTP 403).

At application time the system computes whether the booking touches the facility's prime band and records it in `is_prime_requested`. To do this it splits the requested window `[start_at, end_at)` against the facility's daily prime window `[prime_start_hour, prime_end_hour)`, interpreted per calendar day in UTC, so that a long booking can straddle the boundary. The total hours of the booking are its duration divided into hours. The prime hours are the portion of `[start_at, end_at)` whose wall-clock hour falls at or after `prime_start_hour` and strictly before `prime_end_hour`; the non-prime hours are the total hours minus the prime hours. The flag `is_prime_requested` is true exactly when the prime hours are greater than zero.

Pricing is then locked into `pricing_residency`, which is one of `RESIDENT` or `NON_RESIDENT`. It resolves to `RESIDENT` only when the patron's `residency` is `RESIDENT` and their `residency_verified` is true at application time; in every other case it resolves to `NON_RESIDENT`. The provisional usage fee, stored in `quoted_fee_cents`, is then computed forward-looking from that snapshot. The effective hourly rate is the facility's `hourly_rate_cents`, except that for a `RESIDENT` tier it is reduced by the resident discount — that is, `hourly_rate_cents` multiplied by one minus `resident_discount_pct`. The non-prime component is the non-prime hours multiplied by the effective rate, rounded half up to whole cents. The prime component is the prime hours multiplied by the effective rate multiplied by the facility's `prime_multiplier`, rounded half up to whole cents independently. The provisional quote is the sum of those two already-rounded components — round each component, then sum. This estimate is persisted as `quoted_fee_cents`; `final_fee_cents` stays null until the permit is granted.

A permit also carries `deposit_held_cents` (0 until a deposit is held at grant), `refunded_cents` (0 until something is refunded), and `cancelled_lead_hours` (null until the permit is cancelled). Its `status` may ultimately be any of `APPLIED`, `GRANTED`, `WAITLISTED`, `DENIED`, `CANCELLED`, `COMPLETED`, or `NO_SHOW`.

### 3.4. Funding a Permit: Payments and the Refund Ledger

Before a permit can be placed into `GRANTED`, money must be on file. A payment is recorded against a permit by supplying the `permit_id`, a `fee_component_cents` covering the usage fee portion, and a `deposit_component_cents` covering the security deposit portion. A payment is captured immediately, so its `status` is one of `AUTHORIZED`, `CAPTURED`, or `VOIDED`, and a freshly recorded payment is `CAPTURED`. Capturing a payment is shared work between a `FinanceClerk` and a `RecCoordinator`.

Refunds are the system's record of money returned. A `Refund` names the `permit_id` it relieves and the `payment_id` it draws from, and carries a `refund_destination` of either `ORIGINAL` or `CREDIT`: `ORIGINAL` reverses the original card, while `CREDIT` adds the refunded amount to the patron's `wallet_credit_cents`. Each refund records a `fee_refund_cents` (the fee portion returned per the cancellation tier), a `deposit_refund_cents` (the deposit portion returned, full unless forfeited), and a `total_refund_cents` that is the sum of the fee refund and the deposit refund. Refunds are created by the system as a side effect of cancellation, completion, denial, and league cancellation — never by direct client construction — and the ledger is readable per permit and per payment.

### 3.5. Granting, Waitlisting, and Denying a Permit

Granting is the heart of the workflow and is performed by a `RecCoordinator`. A grant request carries `expected_facility_version` and may carry `on_conflict`. The outcome forks between `GRANTED` and `WAITLISTED`, and the two branches demand very different checks, so the order in which the system evaluates them matters.

The system evaluates guards in this priority order. First, the operation requires a recognized role (`ERR_UNAUTHENTICATED`) authorized for granting (`ERR_FORBIDDEN`). Next, every identifier in the path must resolve (`ERR_NOT_FOUND`). Then the target permit must be in a state from which a grant is defined — that is, `APPLIED` or `WAITLISTED`; otherwise `ERR_INVALID_STATE` (HTTP 409). Next the concurrency check: `expected_facility_version` must equal the facility's current `version`, or the request is rejected with `ERR_STALE_VERSION` (HTTP 412). After that, the patron's standing is checked: a `BARRED` patron cannot be granted, yielding `ERR_PATRON_BARRED` (HTTP 403).

Double-booking is evaluated next. A grant collides when some existing `GRANTED` permit on the same facility has a buffer-expanded window that overlaps this permit's window — concretely, when the existing permit's interval, widened on both sides by the facility's `buffer_minutes`, overlaps this permit's `[start_at, end_at)`. The collision behavior depends on `on_conflict`. If a conflict exists and the request did not carry `on_conflict` set to `WAITLIST`, the grant is rejected with `ERR_DOUBLE_BOOKING` (HTTP 409). If a conflict exists and the request did carry `on_conflict` set to `WAITLIST`, the grant short-circuits to the `WAITLISTED` outcome: the permit transitions `APPLIED → WAITLISTED`, and the insurance and payment gates below are deliberately skipped because the permit is not being placed into `GRANTED`. A facility that is not `OPEN` cannot accept a new grant into `GRANTED`; the `CLOSED` status blocks it.

When the outcome is `GRANTED` (no conflict, or the conflict was resolved by the blocking permit freeing its slot in a later `WAITLISTED → GRANTED`), the remaining gates apply in order. If the patron is in `PROBATION` standing and the permit's window `is_prime_requested`, the grant is blocked with `ERR_PROBATION_PRIME_BLOCKED` (HTTP 403) — probationary patrons are barred from prime-window slots specifically. If the facility's `requires_coi` is set, a `coi_id` must be present, its certificate must be `ACTIVE`, its `coverage_amount_cents` must be at least the facility's `min_coi_coverage_cents`, and its `expiry_date` must be strictly after the permit's `start_at`; a missing or non-active certificate yields `ERR_COI_REQUIRED` (HTTP 422), and a presented certificate whose coverage is below the minimum or whose `expiry_date` is at or before `start_at` yields `ERR_COI_INSUFFICIENT` (HTTP 422). Finally, a `CAPTURED` payment must exist for this permit covering the sum of `final_fee_cents` and the facility's `deposit_cents`; if no such payment exists the grant is rejected with `ERR_PAYMENT_REQUIRED` (HTTP 422). The payment and insurance gates apply only when the outcome would be `GRANTED`; they are never evaluated on the `WAITLISTED` branch.

On a successful grant the system computes `final_fee_cents` using the chronological pricing described in §3.6 and treats it as the authoritative usage fee overwriting the earlier provisional reference. It sets `deposit_held_cents` to the facility's `deposit_cents`, increments the facility's `granted_permit_count` by one, and increments the facility's `version` by one. When the granted permit belongs to a league series — that is, its `league_id` is set — the system recomputes that series' `granted_occurrence_count` and rolls its status up, as covered in §3.8. A `WAITLISTED → GRANTED` transition additionally decrements the series' `conflicted_occurrence_count` by one and increments `granted_occurrence_count` by one before re-rolling the series status, and likewise bumps the facility `version`.

The `WAITLISTED` outcome is comparatively quiet: the permit keeps its `quoted_fee_cents`, no `final_fee_cents` is set, no deposit is held, the facility's `granted_permit_count` is unchanged, and the facility's `version` is not bumped. If the waitlisted permit belongs to a league series, that series' `conflicted_occurrence_count` is incremented by one and its status rolls to `PARTIALLY_GRANTED`. A waitlisted permit is never promoted automatically; even after the blocking permit frees the window, the permit stays `WAITLISTED` until an explicit grant call moves it `WAITLISTED → GRANTED`, at which point the full grant preconditions — no overlapping buffer-expanded `GRANTED` permit any longer, plus the same insurance and payment gates as the `APPLIED → GRANTED` path — must hold.

Denial is a separate coordinator action available only while a permit is `APPLIED`; from any other state the denial is rejected with `ERR_INVALID_STATE`. Denying moves the permit `APPLIED → DENIED`. If a `CAPTURED` payment exists for the permit it is `VOIDED` and fully reversed as a compensation, with no cancellation fee taken. If the denied permit belongs to a league series, that series' `conflicted_occurrence_count` is incremented by one and its status rolls to `PARTIALLY_GRANTED`.

### 3.6. The Final Grant Fee and Its Divergence from the Quote

The fee charged at grant time, `final_fee_cents`, is recomputed rather than copied from the quote, and it can legitimately differ from `quoted_fee_cents` for the same permit. Two things change at grant. First, residency is re-resolved as of the grant moment: the final residency tier is `RESIDENT` only when the patron's `residency` is `RESIDENT` and `residency_verified` is true at the moment of grant, otherwise `NON_RESIDENT`. Because a patron's residency may have been verified between application and grant, this snapshot can differ from the one locked into `pricing_residency`. Second, the rounding order is pinned differently. The effective rate is again the facility's `hourly_rate_cents`, discounted by one minus `resident_discount_pct` when the final tier is `RESIDENT`. The raw fee is the non-prime hours multiplied by the effective rate, plus the prime hours multiplied by the effective rate multiplied by `prime_multiplier`. Unlike the provisional quote, the final fee sums those two raw components first and rounds the single total half up to whole cents once. This sum-then-round order, against the quote's round-each-then-sum order, is exactly why identical hours and rates can produce a one-cent difference between `quoted_fee_cents` and `final_fee_cents`. The same chronological calculation produces the fee on a permit synthesized by a lottery win.

### 3.7. Cancellation, Completion, No-Show, and Tiered Refunds

A permit can leave `GRANTED` or `APPLIED` by cancellation, performed by either the owning `Patron` or a `RecCoordinator`. A cancel request may carry a `refund_destination`. Cancellation is only valid before the reservation has started: the current clock must be strictly before the permit's `start_at`, and an attempt to cancel a reservation whose start time has already passed is rejected with `ERR_INVALID_STATE` (HTTP 409) — a started or past reservation must instead be completed or marked no-show.

Cancelling a permit that is still `APPLIED` moves it `APPLIED → CANCELLED`. Nothing was ever captured into a usage fee, so any `AUTHORIZED` payment is fully reversed, `refunded_cents` stays 0, and the facility's counters and `version` are untouched.

Cancelling a `GRANTED` permit moves it `GRANTED → CANCELLED` and runs the tiered cancellation refund. The system first sets `cancelled_lead_hours` to the number of hours between the current clock and the permit's `start_at` — that is, `start_at` minus the current clock, expressed in hours. The fee refund is a tiered fraction of `final_fee_cents` keyed on that lead time, with the tier boundaries inclusive on the low side. If the lead is at least 168 hours — a full seven days — the entire usage fee is refunded. If the lead is less than seven days but at least 48 hours — at least two days — half the usage fee is refunded. If the lead is under 48 hours, none of the usage fee is refunded. The fee refund is the chosen fraction of `final_fee_cents`, rounded half up to whole cents, and is recorded as `fee_refund_cents`. The deposit is handled separately: the full `deposit_held_cents` is returned as `deposit_refund_cents` unless the lead is under 24 hours — under one day — in which case the deposit is forfeited and the deposit refund is 0. The forfeited deposit stays captured; only the refundable portion reverses. The `total_refund_cents` is the sum of the fee refund and the deposit refund, and a `Refund` is created with these amounts and the supplied `refund_destination`; the permit's `refunded_cents` is set accordingly. Cancelling a `GRANTED` permit also decrements the facility's `granted_permit_count` by one and increments the facility's `version` by one. If a `WAITLISTED` permit on the same facility now fits the freed window it is not promoted automatically; it stays `WAITLISTED` until an explicit grant. When the cancelled permit belongs to a league series, that series' `granted_occurrence_count` is decremented by one and its status is re-rolled.

A patron can preview the cancellation refund before committing. The preview computes the same tiered refund using the current clock at the moment of the preview and returns a non-persisted `Refund` shape. Because the preview uses the clock at preview time while the actual refund uses the clock at the cancel mutation, the lead time can cross a tier boundary between the two, and the previewed numbers can therefore diverge from what is ultimately refunded.

Completion is a coordinator action on a `GRANTED` permit and is only allowed once the reservation has ended: the current clock must be at or after the permit's `end_at`. Completing moves the permit `GRANTED → COMPLETED`, releases the deposit in full by creating a `Refund` whose `deposit_refund_cents` equals `deposit_held_cents` and whose `fee_refund_cents` is 0, decrements the facility's `granted_permit_count` by one, and increments the facility's `version` by one.

A no-show is the punitive counterpart, also a coordinator action on a `GRANTED` permit allowed only once the current clock is at or after the permit's `end_at`. Marking a no-show moves the permit `GRANTED → NO_SHOW`, forfeits `deposit_held_cents` entirely with no refund created, increments the patron's `no_show_strikes` by one and recomputes the patron's `standing` from the new count, decrements the facility's `granted_permit_count` by one, and increments the facility's `version` by one.

### 3.8. League Series and the Cascade

A `LeagueSeries` lets an organizer book the same weekly slot across a season in one action, created by either a `Patron` or a `RecCoordinator`. The organizer supplies the target `facility_id`, the organizing `patron_id`, the `weekday` (0 for Monday through 6 for Sunday), the `start_hour` (at least 0 and less than 24), the `duration_minutes` (greater than 0), the `first_date` of the first occurrence, the number of weekly `occurrences` to generate (at least 1 and at most 26), and optionally a `coi_id` pinned for the whole series — left null when the facility does not require insurance. The series begins in `status` `PENDING` with `granted_occurrence_count` and `conflicted_occurrence_count` both at 0.

On creation the system generates one child `Permit` per occurrence at weekly cadence, each in `APPLIED` status with its `league_id` set to this series. Each child computes its own `is_prime_requested`, locks its own `pricing_residency`, and computes its own `quoted_fee_cents` exactly as a standalone application would. The series `status` is one of `PENDING`, `PARTIALLY_GRANTED`, `GRANTED`, or `CANCELLED`, and apart from cancellation it is derived from its children. The system rolls the series to `PARTIALLY_GRANTED` when at least one child is `GRANTED` and at least one child is `WAITLISTED` or `DENIED` — that is, when `granted_occurrence_count` is greater than 0 and less than `occurrences` and `conflicted_occurrence_count` is greater than 0. It rolls the series to `GRANTED` when every child is granted, meaning `granted_occurrence_count` equals `occurrences`. These roll-ups are recomputed by the system whenever a child permit's state changes; the bubble-up transitions out of `PENDING` and `PARTIALLY_GRANTED` carry no side effects of their own beyond the status change.

Cancelling a league series is the one manual terminal action, available from `PENDING`, `PARTIALLY_GRANTED`, or `GRANTED` to either the owning `Patron` or a `RecCoordinator`, and is rejected with `ERR_INVALID_STATE` if the series is already `CANCELLED`. A cancel may carry a `refund_destination`. Cancelling rolls the series to `CANCELLED` and cascades down: every child permit that is not already in a terminal state is cancelled through the permit cancel path. A child still `APPLIED` follows the `APPLIED → CANCELLED` full-reversal path, and a child currently `GRANTED` follows the `GRANTED → CANCELLED` path — running the tiered cancellation refund, creating its own `Refund`, decrementing the facility's `granted_permit_count`, and bumping the facility's `version` — so a single league cancellation can transitively spawn many refunds and many facility mutations.

### 3.9. The Prime-Slot Lottery

Demand for marquee evening slots is settled by lottery rather than first-come grants. A `RecCoordinator` opens a `LotteryRound` for a facility's prime slot, supplying the `facility_id`, the slot's `slot_start_at` and `slot_end_at` (exclusive), the `opens_at` time when entries are accepted, and the `closes_at` time after which the round may be drawn. The round opens in `status` `OPEN` with `entry_count` at 0; its `status` is one of `OPEN`, `DRAWN`, or `CANCELLED`, and its `winning_entry_id` is null until the round is drawn.

Entering a round is shared work between a `Patron` and a `RecCoordinator`; the entrant supplies the `patron_id`. Each entry records its `lottery_round_id` and `patron_id`, enters in `status` `ENTERED`, is assigned a monotonic per-round `entry_seq` on entry, and is given a `priority_weight`. The weight is 2 when the entrant is a verified resident — `residency` of `RESIDENT` with `residency_verified` true — and 1 otherwise. Creating an entry increments the round's `entry_count` by one. A patron may hold at most one `ENTERED` entry per round; a second entry by the same patron in the same round is rejected with `ERR_DUPLICATE_ENTRY` (HTTP 409). An entry's `status` is one of `ENTERED`, `WON`, `LOST`, or `WITHDRAWN`. A patron or coordinator may withdraw an entry, moving it `ENTERED → WITHDRAWN`, but only while the parent round is still `OPEN`; a withdrawal against a non-open round is rejected with `ERR_INVALID_STATE` (HTTP 409). Withdrawing decrements the round's `entry_count` by one.

Drawing the round is a coordinator action carrying `expected_facility_version`, and it is gated on time, participation, and availability. The current clock must be at or after the round's `closes_at`; a draw before close is rejected with `ERR_LOTTERY_NOT_CLOSED` (HTTP 409). The round must have at least one entry counted in `entry_count`; a draw on an empty round is rejected with `ERR_LOTTERY_NO_ENTRIES` (HTTP 409). No `GRANTED` permit may already occupy the slot `[slot_start_at, slot_end_at)` on the facility; if one does, the draw is rejected with `ERR_DOUBLE_BOOKING` (HTTP 409). And per §2.6, the `expected_facility_version` must still match the facility's `version`, or the draw is rejected with `ERR_STALE_VERSION`.

The winner is selected deterministically — there is no randomness in the observable result. Among the entries still in `ENTERED` status, the system picks the entry with the highest `priority_weight`; ties are broken by the lowest `entry_seq`, so the earliest qualifying entrant wins a tie. Drawing moves the round `OPEN → DRAWN`, records the chosen entry in `winning_entry_id`, transitions that winning entry `ENTERED → WON`, and transitions every other still-entered entry `ENTERED → LOST`. The system then synthesizes a `GRANTED` permit for the winner covering `[slot_start_at, slot_end_at)` with its `lottery_round_id` set, its `final_fee_cents` computed by the chronological grant pricing of §3.6, and its `deposit_held_cents` set to the facility's `deposit_cents`; this transitively increments the facility's `granted_permit_count` by one. Drawing increments the facility's `version` by one.

A coordinator may instead cancel an `OPEN` round, moving it `OPEN → CANCELLED`; this is rejected with `ERR_INVALID_STATE` if the round is not `OPEN`. Cancelling the round transitions all still-entered entries `ENTERED → WITHDRAWN` and synthesizes no permit.

### 3.10. Insurance Certificates and the Ops Sweep

A certificate of insurance is uploaded for a patron, supplied with the owning `patron_id`, the `coverage_amount_cents` liability limit, an `effective_date` when coverage starts, and an `expiry_date` when it ends. Uploading is shared work between a `Patron` (for their own certificate) and a `RecCoordinator`. A certificate's `status` is one of `ACTIVE`, `EXPIRED`, or `REVOKED`; it is created `ACTIVE`, unless its `expiry_date` is already at or before the current clock at upload time, in which case it is created `EXPIRED`. The `expiry_date` is compared against a permit's `start_at` whenever the certificate is presented as a grant's `coi_id`, as described in §3.5.

A coordinator may revoke an `ACTIVE` certificate, moving it `ACTIVE → REVOKED`; revoking a certificate that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A league series pins a single certificate for its whole run via the series `coi_id`.

Certificates also expire on the clock through the ops sweep. The sweep runs at the current clock and transitions every `ACTIVE` certificate whose `expiry_date` is at or before the current clock to `EXPIRED`. The sweep also recomputes each patron's `standing` from their `no_show_strikes`. As an audit side effect, when a certificate expires, every `GRANTED` permit that pinned it, whose `start_at` is still in the future and whose facility `requires_coi`, is flagged for review; the permit is not cancelled automatically. The sweep reports how many certificates it expired and how many patrons it recomputed. A companion test-driving capability advances the server's logical clock to a supplied `to_iso8601` instant, and that clock governs every temporal check in the system — window validity at application, lead time at cancellation, completion and no-show eligibility, certificate expiry, and lottery close.

Individual ledger and entry records are addressable for reads: a single refund is fetched by its `refund_id`, and a single lottery entry by its `lottery_entry_id`, in each case after the left-to-right existence pass of §2.8 confirms the identifier resolves.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or act on an existing resource, including state transitions and reads, return `200 OK`. Authentication, role authorization, and left-to-right existence checks precede the business rules described in §3 for every endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patrons` | Register a patron | RecCoordinator, Patron |
| GET | `/patrons/{patron_id}` | Get a patron | RecCoordinator, Patron, FinanceClerk |
| POST | `/patrons/{patron_id}/verify-residency` | Accept a patron's residency proof | RecCoordinator |
| GET | `/patrons/{patron_id}/permits` | List a patron's permits | RecCoordinator, Patron, FinanceClerk |
| GET | `/patrons/{patron_id}/insurance-certificates` | List a patron's certificates | RecCoordinator, Patron |
| POST | `/facilities` | Create a facility | RecCoordinator |
| GET | `/facilities/{facility_id}` | Get a facility | RecCoordinator, Patron, FinanceClerk |
| PATCH | `/facilities/{facility_id}` | Update facility status/config | RecCoordinator |
| GET | `/facilities/{facility_id}/permits` | List permits on a facility | RecCoordinator, Patron, FinanceClerk |
| POST | `/insurance-certificates` | Upload a certificate of insurance | RecCoordinator, Patron |
| GET | `/insurance-certificates/{coi_id}` | Get a certificate | RecCoordinator, Patron |
| GET | `/insurance-certificates` | List certificates, filterable by patron | RecCoordinator, Patron |
| POST | `/insurance-certificates/{coi_id}/revoke` | Revoke a certificate | RecCoordinator |
| POST | `/facilities/{facility_id}/permits` | Apply for a permit on a facility | RecCoordinator, Patron |
| GET | `/permits/{permit_id}` | Get a permit | RecCoordinator, Patron, FinanceClerk |
| GET | `/permits/{permit_id}/refund-preview` | Preview the cancellation refund at the current clock | RecCoordinator, Patron |
| POST | `/facilities/{facility_id}/permits/{permit_id}/grant` | Grant a permit | RecCoordinator |
| POST | `/facilities/{facility_id}/permits/{permit_id}/deny` | Deny a permit | RecCoordinator |
| POST | `/facilities/{facility_id}/permits/{permit_id}/cancel` | Cancel a permit | RecCoordinator, Patron |
| POST | `/facilities/{facility_id}/permits/{permit_id}/complete` | Complete a granted permit after end | RecCoordinator |
| POST | `/facilities/{facility_id}/permits/{permit_id}/no-show` | Mark a granted permit a no-show after end | RecCoordinator |
| POST | `/permits/{permit_id}/payments` | Capture a payment funding a permit | FinanceClerk, RecCoordinator |
| GET | `/permits/{permit_id}/payments` | List payments for a permit | FinanceClerk, RecCoordinator, Patron |
| GET | `/payments/{payment_id}` | Get a payment | FinanceClerk, RecCoordinator, Patron |
| GET | `/payments` | List payments, filterable by permit | FinanceClerk, RecCoordinator, Patron |
| GET | `/refunds/{refund_id}` | Get a refund | FinanceClerk, RecCoordinator, Patron |
| GET | `/permits/{permit_id}/refunds` | List refunds for a permit | FinanceClerk, RecCoordinator, Patron |
| POST | `/leagues` | Create a recurring league series | RecCoordinator, Patron |
| GET | `/leagues/{league_id}` | Get a league series | RecCoordinator, Patron, FinanceClerk |
| GET | `/leagues/{league_id}/permits` | List a league's child permits | RecCoordinator, Patron, FinanceClerk |
| POST | `/leagues/{league_id}/cancel` | Cancel an entire league series | RecCoordinator, Patron |
| GET | `/leagues` | List league series, filterable by facility/patron/coi | RecCoordinator, Patron, FinanceClerk |
| POST | `/lottery-rounds` | Open a prime-slot lottery round | RecCoordinator |
| GET | `/lottery-rounds/{lottery_round_id}` | Get a lottery round | RecCoordinator, Patron |
| POST | `/lottery-rounds/{lottery_round_id}/entries` | Enter a patron into a round | RecCoordinator, Patron |
| GET | `/lottery-rounds/{lottery_round_id}/entries` | List entries in a round | RecCoordinator, Patron |
| GET | `/lottery-entries/{lottery_entry_id}` | Get a lottery entry | RecCoordinator, Patron |
| POST | `/lottery-entries/{lottery_entry_id}/withdraw` | Withdraw a lottery entry | RecCoordinator, Patron |
| POST | `/lottery-rounds/{lottery_round_id}/draw` | Draw the winner after close | RecCoordinator |
| POST | `/lottery-rounds/{lottery_round_id}/cancel` | Cancel a lottery round | RecCoordinator |
| GET | `/lottery-entries` | List lottery entries, filterable by patron/round | RecCoordinator, Patron |
| GET | `/lottery-rounds` | List lottery rounds, filterable by facility | RecCoordinator, Patron |
| GET | `/permits` | List permits, filterable by coi/lottery/facility/patron/league | RecCoordinator, Patron, FinanceClerk |
| GET | `/refunds` | List refunds, filterable by payment/permit | FinanceClerk, RecCoordinator, Patron |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | RecCoordinator |
| POST | `/_ops/sweep` | Run the ops sweep at the current clock | RecCoordinator |
| POST | `/_inject/no_show_strikes` | Set a patron's no-show strikes directly | RecCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PATRON_BARRED` | 403 |
| `ERR_PROBATION_PRIME_BLOCKED` | 403 |
| `ERR_COI_REQUIRED` | 422 |
| `ERR_COI_INSUFFICIENT` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_DOUBLE_BOOKING` | 409 |
| `ERR_PAYMENT_REQUIRED` | 422 |
| `ERR_LOTTERY_NOT_CLOSED` | 409 |
| `ERR_LOTTERY_NO_ENTRIES` | 409 |
| `ERR_DUPLICATE_ENTRY` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |

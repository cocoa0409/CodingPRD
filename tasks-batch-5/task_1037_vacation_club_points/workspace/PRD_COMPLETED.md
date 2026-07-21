# Vacation-Club Points API — Product Requirements Document

## 1. Introduction

The Vacation-Club Points API powers a points-based timeshare club in the mold of a large branded vacation-ownership program. Members own an annual points allotment, earn a membership tier from the size of that ownership, and spend points to reserve nights at club resorts whose unit categories are priced by season and day of week. The platform must reconcile several tensions at once: points are a finite currency that can be banked forward to a future year, borrowed back from it, transferred between members, and refunded on cancellation, while resort inventory is a scarce nightly capacity that must never be oversold and that feeds a first-come waitlist when full.

Layered on top of the points economy is a billing economy. Each year a member owes a maintenance fee and club dues proportional to their ownership, plus any one-off special assessment, and the club must track partial payments, delinquency aging, and the eventual suspension of members who let a bill go unpaid past its grace period. Because most time-sensitive behavior — booking windows, statement aging, use-year rollover, reservation completion — depends on the passage of time, the system runs on an administrator-controlled logical clock rather than wall-clock time, and a single billing-cycle operation sweeps the whole system forward to the current instant.

This document specifies the entities, state machines, points and money calculations, validation ordering, and REST surface that together implement that club. It is written for the engineers building the service and is the sole authority on behavior; every rule the implementation must honor is stated here in prose.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing or not recognized, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check precedes every other form of validation.

The system recognizes exactly two roles, spelled `Member` and `ClubAdmin`. When a request invokes an operation the caller's role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting member entity; the header value is the identity of a real, persisted `Member`. Ownership checks on any resource that references a member compare the resource's owning member field to `X-User-ID`: a `Member` may act only on a `Reservation` whose `member_id` is their own, a `PointsBucket` whose `member_id` is their own, a `Statement` whose `member_id` is their own, a `Transfer` they are sending (`from_member_id`) when initiating it, and a `Transfer` they are receiving (`to_member_id`) when accepting or rejecting it. A member acting on a resource they do not own is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The `ClubAdmin` role owns inventory setup (resorts and unit types), member onboarding, statement generation, and the operations/clock surface; the server accepts the identifier as the acting operator but does not compare it to any entity's `id`. Both roles may perform read (GET) operations on the resources they are permitted to see; the specific authorizations appear in the endpoint table in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Billing Epoch

All time-dependent behavior in this system reads from an administrator-controlled **logical clock**, never from real wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until an administrator changes it. A `ClubAdmin` may set the clock to any UTC instant by supplying a `to_iso8601` value; the clock is then advanced or rewound to that instant, and every booking-window, expiry, aging, use-year, and refund rule evaluates against the new value.

Setting the clock does not, by itself, perform any state transitions. The system-driven consequences of time passing — statements aging, members being suspended, reservations completing, waitlist entries and listings expiring, and points buckets closing — are applied only when a `ClubAdmin` runs the billing cycle, which processes the whole system at the current clock instant. §3.9 describes the ordered work that sweep performs.

### 2.5. Common Resource Properties and Cascading Consistency

Every resource in this system carries a server-minted `id` that is a UUID with no type prefix and serves as identity only, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this API additionally carry an `updated_at` timestamp — refreshed on every mutation, including mutations applied as a side effect of another operation — and an integer `version` that starts at 1 when the resource is created and increases by one on every mutation.

Many operations mutate more than one resource at once. Whenever a cascade touches a resource — releasing points on a bucket, cancelling a held reservation, revoking a certificate, promoting a waitlist entry, suspending a member — that resource's `updated_at` is refreshed and its `version` is incremented exactly as if it had been changed by a direct request. Derived fields are part of this rule: when a bucket's counters change, its computed available balance is recomputed immediately (the consistency model is immediate, not deferred).

### 2.6. Points-Bucket Ledger Integrity

A `PointsBucket` is the ledger of a member's points for one use year, and its spendable balance is always derived from its own counters rather than stored independently. The available balance, exposed as `points_available`, is the annual allotment (`annual_allotment`) plus everything credited in — points banked in from the prior year (`banked_in`), points borrowed in from the next year (`borrowed_in`), and points transferred in from another member (`transferred_in`) — minus everything debited out: points banked out to the next year (`banked_out`), points borrowed out to a prior year (`borrowed_out`), points transferred out to another member (`transferred_out`), and points currently committed (`points_used`). The result is never allowed to be negative; if the arithmetic would yield a value below zero it is clamped to zero.

The `points_used` counter is the running total of points committed by active reservations, issued guest-certificate fees, and the escrow held for `PENDING` transfers sent from this bucket. It rises when points are committed and falls when they are released (a refund, a revoked certificate, a rejected or completed transfer's escrow release). Every one of these counter changes recomputes `points_available` in the same operation.

### 2.7. Monetary Precision and Rounding

All monetary amounts on a `Statement` are stored as integer **cents**. The two computed fee lines are each derived from the member's ownership and a per-point USD rate and are rounded independently to the nearest cent using the round-half-up method before being combined. The total is then the sum of the individually rounded lines; the system must not round a single combined rate, because per-line rounding can differ from that by a cent. §3.8 gives the exact rates and formula.

### 2.8. Optimistic Concurrency Control

Generating a member's statement is guarded by optimistic concurrency control on the member. The generate-statement operation requires an `expected_member_version` field carrying the member `version` the client last observed. If that value does not match the target member's current `version` — because another writer has generated the current-period statement and advanced the member since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because generation is a legitimate supersede that no state precondition blocks, this version check is the only guard against a stale double-generate, and it prevents a caller from overwriting a statement it never observed. No other endpoint takes a version field; only statement generation is version-guarded.

### 2.9. Nested Resource Retrieval and Validation Ordering

Several paths embed a resource identifier, and some embed a parent identifier followed by a child collection. All referenced identifiers — whether in the path or in the request body — are validated for existence in left-to-right order, and the first identifier that does not resolve produces the corresponding not-found error before any later check runs: a missing member yields `ERR_MEMBER_NOT_FOUND`, a missing resort `ERR_RESORT_NOT_FOUND`, a missing unit type `ERR_UNIT_TYPE_NOT_FOUND`, a missing bucket `ERR_POINTS_BUCKET_NOT_FOUND`, a missing reservation `ERR_RESERVATION_NOT_FOUND`, a missing waitlist entry `ERR_WAITLIST_NOT_FOUND`, a missing statement `ERR_STATEMENT_NOT_FOUND`, and a missing transfer `ERR_TRANSFER_NOT_FOUND`, each with HTTP 404.

The full validation order across all endpoints is fixed and each stage runs only after the previous one passes: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) existence of every referenced id, left to right (the not-found errors above); (4) ownership, i.e. a `Member` acting only on their own resource (`ERR_FORBIDDEN`); (5) field and format validity of the body (`ERR_VALIDATION`); (6) legal state for the requested transition, including the cross-entity state checks (`ERR_INVALID_STATE`, `ERR_MEMBER_SUSPENDED`, `ERR_BUCKET_CLOSED`); (7) the booking-window check on reservations and waitlist joins (`ERR_OUTSIDE_BOOKING_WINDOW`); (8) inventory and member-overlap checks (`ERR_NO_INVENTORY`, `ERR_MEMBER_DATE_OVERLAP`); (9) points sufficiency and bank/borrow caps (`ERR_INSUFFICIENT_POINTS`, `ERR_BANK_CAP_EXCEEDED`, `ERR_BORROW_CAP_EXCEEDED`); and (10) the optimistic-concurrency check on statement generation (`ERR_STALE_VERSION`). Where an endpoint does not involve a given stage, that stage is simply skipped, but the relative ordering of the stages that do apply is always preserved — for example, a suspended member attempting to confirm a reservation fails the state stage before any points check, and a body that fails format validity fails before any state or inventory check.

### 2.10. Inventory and Nightly Occupancy

Resort inventory is modeled as nightly capacity on a `UnitType`. Reservations are expressed as a half-open date range from the first night (`check_in`) up to but excluding the departure date (`check_out`); the number of nights is the count of dates in that half-open range. For any candidate range and unit type, a given night is occupied by every reservation of that unit type whose status is `HELD`, `CONFIRMED`, or `COMPLETED` and whose own half-open night range contains that night. A candidate range fits only when, for every one of its nights, the count of such occupying reservations is strictly less than the unit type's total capacity (`total_units`). Because ranges are half-open, two reservations that merely abut — one departing on the very day the next arrives — do not overlap and do not compete for the same night.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Member and Establishing Their Tier

A `ClubAdmin` onboards an owner by supplying their `full_name`, `email`, and `owned_points`, the size of the member's annual points ownership, which must be zero or greater. Onboarding returns a new member whose `account_status` begins as `ACTIVE`, whose `current_use_year` is set to the calendar year of the logical clock at creation, and whose `current_statement_id` is null until the first statement is generated.

A member's `tier` is computed from `owned_points` and is one of `STANDARD`, `SILVER`, `GOLD`, or `PLATINUM`. Ownership of at least 13,000 points confers `PLATINUM`; otherwise at least 7,000 points confers `GOLD`; otherwise at least 4,000 points confers `SILVER`; below 4,000 points the member is `STANDARD`. Each lower bound is inclusive, and the tier is re-derived whenever the member is read.

At onboarding the system also creates the member's initial points ledger for the current use year: an `OPEN` `PointsBucket` whose `use_year` equals the clock's current year and whose `annual_allotment` equals the member's `owned_points`. Every counter on that fresh bucket — `banked_in`, `banked_out`, `borrowed_in`, `borrowed_out`, `transferred_in`, `transferred_out`, and `points_used` — starts at zero, so its initial `points_available` equals the allotment. A member's buckets can be listed and optionally filtered by `use_year` and by bucket `status`.

### 3.2. Banking and Borrowing Across Use Years

Members manage points across use years by banking forward and borrowing back. Each `PointsBucket` belongs to one `use_year`, has a `status` of `OPEN` or `CLOSED`, and is owned via its `member_id`. Both banking and borrowing act between a bucket and the bucket for the immediately following use year (`use_year` + 1); if that next-year bucket does not yet exist, it is auto-created as `OPEN` with `annual_allotment` equal to the member's `owned_points`. Banking and borrowing may only be initiated by the owning member, and only against an `OPEN` bucket — an attempt against a `CLOSED` bucket is rejected with `ERR_BUCKET_CLOSED`.

**Banking** moves a requested number of `points` forward from a source bucket to the next year's bucket. The points always leave the source at par: the source bucket's `banked_out` rises by the requested points regardless of timing. What the next year receives depends on the banking deadline, which falls 273 days after January 1 of the source bucket's use year. If the logical clock's date is on or before that deadline, banking is at par and the next year's `banked_in` rises by the full requested points; if the clock's date is after the deadline, the bank is late and the next year's `banked_in` rises by only the floor of half the requested points (the fractional point is dropped). Two caps guard a bank request, both evaluated in the fiscal stage: the requested points may not exceed the floor of one-half of the source bucket's `annual_allotment`, or the request is rejected with `ERR_BANK_CAP_EXCEEDED`; and the requested points may not exceed the source bucket's current `points_available`, or the request is rejected with `ERR_INSUFFICIENT_POINTS`.

**Borrowing** pulls a requested number of `points` from the next year's bucket into the current one. The receiving bucket's `borrowed_in` rises by the requested points and the next year's bucket's `borrowed_out` rises by the same amount. Borrowing is likewise capped: the requested points may not exceed the floor of one-half of the source bucket's `annual_allotment`, or the request is rejected with `ERR_BORROW_CAP_EXCEEDED`; and the requested points may not exceed the next-year bucket's current `points_available`, or the request is rejected with `ERR_INSUFFICIENT_POINTS`. Both the bank and borrow operations respond with the source bucket named in the path — the acted-on bucket — reflecting its updated counters and derived `points_available`, not the next-year bucket. A bucket's balances are always observable directly, exposing all of its counters and its derived `points_available`.

### 3.3. Building Inventory: Resorts and Unit Types

A `ClubAdmin` builds the bookable catalog. A resort is created with a `name` and a `region` label. Within a resort, the administrator defines unit categories: each `UnitType` is created with a `name` (such as a villa size), a `total_units` capacity that must be at least 1 and represents the maximum concurrent reservations that may occupy any single night, and a four-cell seasonal points chart. The chart cells are the points charged per night for each combination of season and day class: `points_weekday_low` and `points_weekend_low` for weekday and weekend nights in low season, and `points_weekday_high` and `points_weekend_high` for weekday and weekend nights in high season. Each chart cell must be at least 1. A unit type is owned by its resort through `resort_id`; a resort's unit types can be listed, and any resort or unit type can be read directly.

### 3.4. Reserving Nights: Window, Cost, and the Hold

A `Member` reserves nights by supplying the paying `member_id`, the target `unit_type_id`, the `points_bucket_id` that will pay, and the `check_in` and `check_out` dates. A successful request creates a reservation in the `HELD` status, computes its cost, and commits that cost against the paying bucket.

Before a hold is created, the request passes through the ordered checks. The dates must be well formed and `check_out` must be strictly after `check_in`, or the request is rejected with `ERR_VALIDATION`. The paying bucket must be `OPEN`, or the request is rejected with `ERR_BUCKET_CLOSED`. **The booking window** is then enforced: the number of whole days from the current clock date to `check_in` must be greater than zero and at most the member's window length, or the request is rejected with `ERR_OUTSIDE_BOOKING_WINDOW`. The window length depends on tier — a member whose `tier` is `GOLD` or `PLATINUM` enjoys a priority window of 396 days, while every other member has the standard window of 366 days. Next, inventory and overlap are checked together: every requested night must have free capacity on the unit type per the occupancy rule in §2.10, or the request is rejected with `ERR_NO_INVENTORY`; and the booking member must not already hold another active reservation whose nights overlap the requested nights, or the request is rejected with `ERR_MEMBER_DATE_OVERLAP`. Finally the fiscal check runs: the paying bucket's `points_available` must cover the computed cost, or the request is rejected with `ERR_INSUFFICIENT_POINTS`.

The reservation's `nights` is the count of dates in the half-open range from `check_in` up to `check_out`. Its `points_cost` is the sum, over each individual night in that range, of the one chart cell that applies to that night. For each night, the season is high when the month of that night is June, July, August, or December, and low in every other month; the day class is weekend when that night falls on a Friday or a Saturday, and weekday otherwise. The applicable cell is then the unit type's price for that season and day class — `points_weekday_low`, `points_weekend_low`, `points_weekday_high`, or `points_weekend_high` — and these per-night prices are added together as whole points with no rounding. On creation the reservation is stored in `HELD` status, the paying bucket's `points_used` rises by `points_cost` (committing the points), and each night is occupied on the unit type. A reservation's `refunded_points` is zero until a cancellation sets it, and its `guest_certificate_id` is null until a certificate is attached. Reservations can be read individually and listed or filtered by `member_id`, `unit_type_id`, `points_bucket_id`, and `status`.

### 3.5. Confirming, Cancelling, and the Refund Ladder

The owning member confirms a held reservation, advancing it from `HELD` to `CONFIRMED`. Confirmation is legal only from `HELD` — confirming anything else is rejected with `ERR_INVALID_STATE`; the booking member's `account_status` must be `ACTIVE`, or the confirm is rejected with `ERR_MEMBER_SUSPENDED`; and the paying bucket must be `OPEN`, or `ERR_BUCKET_CLOSED`. Confirmation only changes the status to `CONFIRMED`; the points stay committed and `points_used` is unchanged.

The owning member may cancel a reservation from either `HELD` or `CONFIRMED`; cancelling from any other status is rejected with `ERR_INVALID_STATE`. Cancellation runs the **refund ladder** based on `days_out`, the whole number of days from the current clock date to `check_in`. If `days_out` is at least 60, the refund is full and `refunded_points` equals the entire `points_cost`. If `days_out` is at least 15 but less than 60, the refund is partial and `refunded_points` equals the floor of half the `points_cost`, with the forfeited remainder staying committed. If `days_out` is below 15, nothing is refunded and `refunded_points` is zero. The computed `refunded_points` is recorded on the reservation, the paying bucket's `points_used` is reduced by exactly that refunded amount (any forfeited remainder remains used), the reservation moves to `CANCELLED`, and every night it occupied on the unit type is released.

Cancellation also cascades to everything attached to the reservation. If the reservation carries an `ISSUED` guest certificate, that certificate is revoked (moving to `REVOKED`) and its `fee_points` are released back to the paying bucket by reducing `points_used` by the fee. If the reservation carries a `LISTED` market listing, that listing is withdrawn (moving to `WITHDRAWN`). Finally, because a night has been freed, the earliest-created `ACTIVE` waitlist entry on that unit type that now fits is promoted, per §3.7. `CANCELLED` and `COMPLETED` are the terminal statuses of a reservation.

### 3.6. Guest Certificates and Market Listings

A member may attach a **guest certificate** to their held or confirmed reservation, naming the guest permitted to occupy it via `guest_name`; attaching one to a reservation whose status is neither `HELD` nor `CONFIRMED` is rejected with `ERR_INVALID_STATE`. Issuing a certificate charges a fixed fee of 50 points, recorded on the certificate as `fee_points`; the paying bucket's `points_used` rises by that fee (subject to the same points-sufficiency check, `ERR_INSUFFICIENT_POINTS`, when the bucket cannot cover it), the certificate is created in `ISSUED` status linked to its reservation through `reservation_id`, and the reservation's `guest_certificate_id` is set to the new certificate. A certificate follows its reservation's fate: when the reservation later reaches `COMPLETED` the certificate transitions from `ISSUED` to `USED`, and when the reservation is cancelled the certificate transitions from `ISSUED` to `REVOKED` with its fee refunded as described above. `USED` and `REVOKED` are terminal. A reservation's certificates can be listed and filtered by `status`.

A member may also place a **market listing** on their reservation to offer it on the exchange or rental market. A listing is created with a `listing_type` of either `EXCHANGE` or `RENTAL` and, for a rental, an `ask_amount_cents` cash ask (which defaults to 0 and is 0 for an exchange). A listing may be created only when the underlying reservation is `CONFIRMED`; attempting to list a reservation in any other state is rejected with `ERR_INVALID_STATE`. A new listing begins in `LISTED` status linked to its reservation by `reservation_id`. A listing leaves `LISTED` in one of two system-driven ways: it is withdrawn to `WITHDRAWN` when its underlying reservation is cancelled (whether by the member or by a suspension cascade), and it expires to `EXPIRED` when the billing cycle runs at or after the reservation's `check_in`. A reservation's listings can be listed and filtered by `status`.

### 3.7. The Waitlist and Promotion

When a unit type is full for a desired range, a `Member` joins the **waitlist** by supplying the `member_id`, the desired `unit_type_id`, the paying `points_bucket_id`, and the desired `check_in` and `check_out`. Joining is subject to the same booking-window rule as a reservation — the days from the clock to `check_in` must be greater than zero and within the member's tier window (366 days standard, 396 days for `GOLD` or `PLATINUM`), or the join is rejected with `ERR_OUTSIDE_BOOKING_WINDOW`. A new entry begins `ACTIVE` with a null `promoted_reservation_id`; its `created_at` is the promotion-order key, earliest first. The owning member may leave the waitlist, moving the entry from `ACTIVE` to `CANCELLED`; attempting to leave an entry that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

Promotion is system-driven and happens whenever nightly capacity frees on a unit type — either from a member cancellation or from the reservation cancellations in a suspension cascade. When capacity frees, the system considers the `ACTIVE` waitlist entries on that unit type in creation order, earliest first, and promotes the first entry that now fits — meaning every night in its half-open range has free capacity, the promoting member's `account_status` is `ACTIVE`, and the paying bucket's `points_available` is at least the projected `points_cost` of the reservation the promotion would create (that projected cost uses the same per-night seasonal chart calculation as a normal reservation). Promotion sets the entry's status to `PROMOTED`, creates a new `HELD` reservation for the member, records that reservation on the entry as `promoted_reservation_id`, commits the reservation's `points_cost` on the paying bucket, and occupies its nights. An `ACTIVE` entry that is never promoted expires to `EXPIRED` when the billing cycle runs at or after its `check_in`. `PROMOTED`, `CANCELLED`, and `EXPIRED` are terminal. Waitlist entries can be read individually and listed or filtered by `member_id`, `unit_type_id`, `points_bucket_id`, and `status`.

### 3.8. Member-to-Member Transfers

A `Member` may move points to another member as a transfer or resale. The sender initiates a transfer by supplying the `from_member_id`, the `to_member_id`, and the `points` to move, which must be at least 1. The points are drawn from the sender's current-use-year bucket, and initiation requires that the sender's `points_available` cover the requested points (else `ERR_INSUFFICIENT_POINTS`) and that both the sending and receiving members be `ACTIVE` (else `ERR_MEMBER_SUSPENDED`). On initiation the transfer is created in `PENDING` status and the sender's current-use-year bucket escrows the points by raising its `points_used` by the transfer amount, which reduces the sender's available balance while the transfer is outstanding.

The receiving member then resolves the transfer by supplying an `outcome` of either `ACCEPT` or `REJECT`; a transfer can be resolved only while `PENDING`, and resolving anything else is rejected with `ERR_INVALID_STATE`. The active-member requirement applies only to an `ACCEPT` — accepting when either the sending or receiving member is not `ACTIVE` is rejected with `ERR_MEMBER_SUSPENDED`, whereas a `REJECT` releases the escrow regardless of either member's status. On `ACCEPT` the transfer moves to `COMPLETED`: the sender's bucket releases the escrow by reducing `points_used` by the transferred points and records `transferred_out` increased by that amount, while the receiver's current-use-year bucket records `transferred_in` increased by the same amount. Because the escrow release and the outbound record net to the same figure, the combined available balance of the two members is unchanged across an accepted transfer — the points simply move from one member to the other. On `REJECT` the transfer moves to `REJECTED`: the sender's bucket releases the escrow by reducing `points_used` by the transferred points, and no points move to the receiver. `COMPLETED` and `REJECTED` are terminal. Transfers where a member is sender or receiver can be listed for that member and filtered by `status`.

### 3.9. Statements: Billing, Payment, Aging, and Suspension

Billing is captured on the `Statement`, which carries two independent status axes that evolve separately: a `payment_status` of `UNPAID`, `PARTIALLY_PAID`, or `PAID`, and an `aging_status` of `CURRENT` or `PAST_DUE`.

**Generation.** A `ClubAdmin` generates (and thereby supersedes) a member's current-period statement, optionally supplying a one-off `special_assessment_cents` levy that defaults to 0, and always supplying the `expected_member_version` for the concurrency check in §2.8. A generated statement stamps its `member_id`, a `billing_year` equal to the clock's current year, an `issue_date` equal to the current clock date, and a `due_date` equal to 30 days after the issue date. Its two computed fee lines follow the rounding rule of §2.7: `maintenance_fee_cents` is the member's `owned_points` multiplied by the maintenance rate of 0.0653 US dollars per point, converted to cents and rounded half up to a whole cent; `club_dues_cents` is the member's `owned_points` multiplied by the club-dues rate of 0.0089 US dollars per point, converted to cents and rounded half up to a whole cent. The `total_due_cents` is the sum of these two independently rounded lines plus the `special_assessment_cents`. The statement begins with `amount_paid_cents` at 0, `payment_status` `UNPAID`, and `aging_status` `CURRENT`. Generation also sets the member's `current_statement_id` to the new statement and increments the member's `version` by one.

**Payment.** The owning member pays a statement by supplying an `amount_cents`, which must be at least 1. If the payment is a positive amount that is strictly less than the remaining balance (the `total_due_cents` minus the current `amount_paid_cents`), the statement moves from `UNPAID` to `PARTIALLY_PAID` and `amount_paid_cents` rises by the paid amount. If the payment brings `amount_paid_cents` to at least `total_due_cents`, the statement reaches `PAID`: `amount_paid_cents` rises by the paid amount, and on that payoff the `aging_status` is set to `CURRENT`, clearing any delinquency on the aging axis. `PAID` is terminal on the payment axis, and applying a payment to a statement that is already `PAID` is rejected with `ERR_INVALID_STATE`. When a payoff clears a member's last outstanding delinquent statement and that member is `SUSPENDED`, the payoff also reinstates the member to `ACTIVE`, as described below.

**Aging, suspension, and reinstatement.** Aging and suspension are driven only by the billing cycle and by payoff. A member's `account_status` cycles between `ACTIVE` and `SUSPENDED`: suspension is a delinquency consequence, and reinstatement follows payoff. A member is suspended only through the cascade described in §3.10. Reinstatement is the reverse: when a payment brings a statement to `PAID` and, after that payment, the member has no statement that is still `PAST_DUE` and not yet `PAID`, a `SUSPENDED` member is returned to `ACTIVE`. Reinstatement restores account standing only; no previously cancelled reservation is automatically restored. A member's statements can be listed and filtered by `aging_status` and `payment_status`.

### 3.10. The Ops Cycle and System-Driven Consequences

A `ClubAdmin` advances the system by running the billing cycle at the current logical clock instant. This single operation performs, in order, all the time-driven transitions the clock now warrants.

First, **aging**: any `CURRENT` statement whose `due_date` has passed (the clock is now after its `due_date`) and whose `payment_status` is not `PAID` moves to `PAST_DUE`.

Second, **suspension and its cascade**: for any member who is still `ACTIVE` and who has a statement that is `PAST_DUE`, not yet `PAID`, and now past its `due_date` plus the 15-day grace period (the clock is now more than 15 days beyond the `due_date`), the member is suspended, moving `account_status` from `ACTIVE` to `SUSPENDED`. Suspension cascades to that member's held inventory: every reservation of the member still in `HELD` status is cancelled with a full refund — `refunded_points` set to the reservation's entire `points_cost`, the paying bucket's `points_used` reduced by that `points_cost`, and the occupied nights released. Any `ISSUED` guest certificate on those reservations is revoked (moving to `REVOKED`) with its `fee_points` released back to the bucket, and any `LISTED` listing on them is withdrawn (moving to `WITHDRAWN`). For each unit type whose capacity is freed by these cancellations, the earliest-created `ACTIVE` waitlist entry that now fits is promoted exactly as in §3.7.

Third, **reservation completion**: any `CONFIRMED` reservation whose `check_out` the clock has reached or passed moves to `COMPLETED`, and any `ISSUED` guest certificate on it moves to `USED`.

Fourth, **expiries**: any `ACTIVE` waitlist entry whose `check_in` the clock has reached or passed moves to `EXPIRED`, and any `LISTED` listing whose reservation's `check_in` the clock has reached or passed moves to `EXPIRED`.

Fifth, **use-year rollover**: any `OPEN` points bucket whose `use_year` is now in the past — the clock's year is greater than the bucket's `use_year` — moves to `CLOSED`. Once a bucket is `CLOSED`, any later attempt to bank from it, borrow against it, or reserve using it is rejected with `ERR_BUCKET_CLOSED`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource, apply a payment, drive a state transition, or run a system routine return `200 OK`. The clock and ops routines return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied UTC instant | ClubAdmin |
| POST | `/_ops/run_billing_cycle` | Sweep the system at the current clock: age, suspend, complete, expire, close | ClubAdmin |
| POST | `/club/members` | Onboard a member; compute tier and create the initial points bucket | ClubAdmin |
| GET | `/club/members/{id}` | Get a member | Member, ClubAdmin |
| GET | `/club/members/{id}/points-buckets` | List a member's points buckets | Member, ClubAdmin |
| GET | `/club/members/{id}/statements` | List a member's statements | Member, ClubAdmin |
| GET | `/club/members/{id}/transfers` | List transfers where the member is sender or receiver | Member, ClubAdmin |
| GET | `/club/points-buckets/{id}` | Get a points bucket and its balances | Member, ClubAdmin |
| POST | `/club/points-buckets/{id}/bank` | Bank points forward to the next use year | Member |
| POST | `/club/points-buckets/{id}/borrow` | Borrow points from the next use year | Member |
| POST | `/club/resorts` | Create a resort | ClubAdmin |
| GET | `/club/resorts/{id}` | Get a resort | Member, ClubAdmin |
| POST | `/club/resorts/{id}/unit-types` | Create a unit type with capacity and seasonal chart | ClubAdmin |
| GET | `/club/resorts/{id}/unit-types` | List a resort's unit types | Member, ClubAdmin |
| GET | `/club/unit-types/{id}` | Get a unit type | Member, ClubAdmin |
| POST | `/club/reservations` | Create a held reservation | Member |
| GET | `/club/reservations/{id}` | Get a reservation | Member, ClubAdmin |
| GET | `/club/reservations` | List/filter reservations | Member, ClubAdmin |
| POST | `/club/reservations/{id}/confirm` | Confirm a held reservation | Member |
| POST | `/club/reservations/{id}/cancel` | Cancel a held or confirmed reservation | Member |
| POST | `/club/reservations/{id}/guest-certificates` | Issue a guest certificate | Member |
| GET | `/club/reservations/{id}/guest-certificates` | List a reservation's guest certificates | Member, ClubAdmin |
| POST | `/club/reservations/{id}/listings` | List a confirmed reservation on the market | Member |
| GET | `/club/reservations/{id}/listings` | List a reservation's market listings | Member, ClubAdmin |
| POST | `/club/waitlist-entries` | Join the waitlist for a unit type and date range | Member |
| GET | `/club/waitlist-entries/{id}` | Get a waitlist entry | Member, ClubAdmin |
| GET | `/club/waitlist-entries` | List/filter waitlist entries | Member, ClubAdmin |
| POST | `/club/waitlist-entries/{id}/cancel` | Leave the waitlist | Member |
| POST | `/club/members/{id}/statements` | Generate (supersede) the member's current-period statement | ClubAdmin |
| POST | `/club/statements/{id}/pay` | Apply a payment to a statement | Member |
| POST | `/club/transfers` | Initiate a points transfer | Member |
| POST | `/club/transfers/{id}/accept` | Accept or reject a pending transfer | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_RESORT_NOT_FOUND` | 404 |
| `ERR_UNIT_TYPE_NOT_FOUND` | 404 |
| `ERR_POINTS_BUCKET_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_WAITLIST_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_BUCKET_CLOSED` | 409 |
| `ERR_OUTSIDE_BOOKING_WINDOW` | 422 |
| `ERR_NO_INVENTORY` | 409 |
| `ERR_MEMBER_DATE_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_BANK_CAP_EXCEEDED` | 422 |
| `ERR_BORROW_CAP_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |

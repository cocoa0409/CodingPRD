# Indoor Playground & Kids' Café API — Product Requirements Document

## 1. Introduction

Running an indoor playground with an attached kids' café is a balancing act between delight and duty of care. Families arrive with and without reservations, children need timed play sessions with strict capacity limits, every child on the structure must be covered by a current waiver and grip socks, and the café kitchen must never serve an allergen to a child who cannot tolerate it. On top of the safety envelope, the business runs memberships with bundled session credits, a loyalty program, birthday-party room bookings with deposits and reschedule negotiations, and a sanitation regime whose overdue tasks can block a party from confirming. Today these concerns live in spreadsheets, paper waivers, and staff memory; the result is overbooked slots, disputed charges, and safety checks that depend on who is working the desk.

This document specifies a single REST API that becomes the operational backbone of the venue. It governs guardian accounts, children, waivers, membership plans and session credits, session slots and timed visits with a parallel payment dimension, café ordering with allergen interlock and points redemption, party rooms and packages with a deposit-and-reschedule booking cycle, staff and sanitation tasks, incident management including a lost-child check-out gate, loyalty accrual, and a periodic operations sweep that advances all time-driven transitions. All time-sensitive behavior is evaluated against a controllable logical clock so that the venue's rules — windows, cutoffs, expiries, and quotas — are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized roles, spelled exactly as shown, are `Anonymous`, `Guardian`, `FrontDesk`, `CafeStaff`, `Manager`, and `Admin`. A request whose `X-User-Role` header is missing or carries an undeclared role, or whose `X-User-ID` is missing for an entity-backed role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); endpoints that list `Anonymous` among their authorized roles are exempt from this authentication check. The exemption applies only when the `X-User-Role` header is entirely absent, in which case the request proceeds as `Anonymous`; a header that is present but carries an undeclared role value is still rejected with `ERR_UNAUTHENTICATED`, even on endpoints that list `Anonymous`. A request whose role is not permitted on the target endpoint, whose staff identity fails the staff checks below, or where a `Guardian` attempts to act on another guardian's resources, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity bound to `X-User-ID` differs by role:

- When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; ownership checks on any resource that references a `Guardian` compare the resource's guardian foreign-key field (in the path or body) to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`.
- When `X-User-Role` is `FrontDesk`, `CafeStaff`, or `Manager`, `X-User-ID` is the `id` of the acting `StaffMember`. The referenced `StaffMember` must exist, must be `ACTIVE`, and its `role` value (`FRONT_DESK`, `CAFE_STAFF`, or `MANAGER`) must match the presented `X-User-Role`; otherwise the request is rejected with `ERR_FORBIDDEN`. A `Manager` is a superset role and may perform every operation open to `FrontDesk` and `CafeStaff` in addition to manager-exclusive operations.
- When `X-User-Role` is `Anonymous` or `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A `limit` below 1 or above 100 is clamped into that range, and a negative `offset` is clamped to 0; a value that does not parse as an integer falls back to the default. Out-of-range pagination is never an error. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The venue's rules — check-in windows, cutoffs, expiries, and sweeps — never consult wall-clock time. Instead, every "now" in this document refers to a server-held logical clock. At startup, before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. An `Admin`-only capability sets the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; this is the only way time moves. Any instant is accepted — the server does not require the supplied instant to be later than the current reading. All system-stamped timestamps described in §3 (signing, check-in, check-out, completion, resolution) are taken from this logical clock.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique per resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by 1 on every mutation.

The one exception is the `LoyaltyTransaction` ledger entry, which is immutable once written: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.6. Money, Points, and Rounding

All monetary amounts are integer cents; no fractional cents exist anywhere in the system. Wherever a multiplication produces a fractional cent — per-line café discounts, party surcharges and discounts, deposits, membership-discounted visit charges, evacuation charges, and cancellation refunds — the result is rounded half-up to the nearest whole cent, and the rounding is applied at the stage the rule names, never deferred to a later sum. Loyalty points are integers produced by floor division: partial remainders are discarded, never rounded. These two disciplines — round half-up for money, floor for points — are load-bearing and apply uniformly across §3.

### 2.7. Optimistic Concurrency Control

Three write operations guard against a client acting on a stale view of a parent entity, and each names its own version field:

- Signing a new waiver for a guardian requires the request to carry `expected_guardian_version`, holding the guardian `version` the client last observed. If the guardian's current `version` has advanced since that read — for example because a newer waiver already superseded the client's view — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the guardian before signing.
- Resizing a session slot's `capacity` requires `expected_session_slot_version` matching the slot's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the slot's counters may have moved since the client read it, and the quota-reduction cascade must never run from a stale view.
- Creating a party booking requires `expected_party_room_version` matching the target room's current `version`. Because each created booking itself bumps the room's `version` by 1, an availability view can go stale between reads; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. The rejection is expressed purely as a stale-version check: the supplied value is compared to the parent entity's current `version`, and inequality yields `ERR_STALE_VERSION`. The comparison is performed at the point the workflow reaches the parent entity: for waiver signing immediately after the guardian resolves, for slot resizing after the slot resolves and before the capacity-floor check, and for party booking creation after the room/package status, child-count, and time-conflict checks.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed tier order, and the earliest failing tier determines the error. First, authentication (§2.1) yields `ERR_UNAUTHENTICATED`. Second, authorization — role permission, staff role/status matching, and guardian self-service — yields `ERR_FORBIDDEN`. Third, existence: every identifier in the path and every foreign-key reference in the body must resolve, checked left-to-right along the path (every URL path variable is named `id`), and the first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404). Fourth, state: the target resource must be in a valid from-state for the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409), with the slot-open gate for visit creation and check-in reported as `ERR_SLOT_NOT_OPEN` (HTTP 409). Fifth, business safety: waiver validity, grip-sock resolvability, child age, allergen intersection, lost-child gates, and child-reunion requirements. Sixth, structural business constraints: slot overlap, room time conflicts, duplicate visits, retired or inactive configuration, overdue sanitation, and capacity floors. Seventh, temporal cutoffs: the check-in window, the reschedule cutoff, and the guardian cancel cutoff. Eighth, fiscal and quota checks: reservation quota, slot capacity, membership and credit sufficiency, and points redemption limits. Ninth and last, payload shape: missing required fields or wrong types yield `ERR_VALIDATION` (HTTP 400), and enum fields carrying an undeclared member yield `ERR_INVALID_ENUM` (HTTP 400). One refinement on the third tier: an identifier that is missing or of the wrong type can never resolve, so such a field yields `ERR_VALIDATION` before the existence tier is reached. The trigger condition for each individual error is stated in §3 beside the workflow it guards.

### 2.9. Time Intervals, Capacity, and Quotas

The venue models time as half-open intervals. A session slot occupies the half-open interval from its `start_at` up to but not including its `end_at`; two slots on the same `slot_date` may touch — one ending exactly when another begins — but may never overlap while both are non-`CLOSED`. Party rooms follow the same discipline with one addition: every party occupies its booked window plus a thirty-minute cleanup buffer, and that extended interval is what must stay clear of other non-terminal bookings on the room.

Capacity is governed by two counters and one derived quota per slot. Of a slot's `capacity`, seventy percent rounded down is reserved for advance reservations as the `reservation_quota`; the remainder protects walk-in access. A new reservation is admitted only while the number of `RESERVED` visits is strictly below the quota, and a new walk-in only while the sum of `RESERVED` and `CHECKED_IN` visits is strictly below `capacity`. When either counter meets its boundary, the slot is full for that admission channel.

## 3. Business Logic & Workflows

### 3.1. Guardians, Children, and Waivers

A family enters the system when an unauthenticated visitor self-registers a guardian account with a `full_name`, `email`, and `phone`. The new `Guardian` starts with `membership_status` of `NONE`, `loyalty_tier` of `BRONZE`, every counter at zero, and `version` 1. Managers and admins can list guardians, optionally filtering by `membership_plan_id`; a guardian, desk staff, or manager can read a single guardian record, which always presents its computed credit and loyalty fields alongside the stored ones.

Each guardian registers their children with a `full_name`, a `birth_date`, and optionally an `allergies` list drawn from the codes `PEANUT`, `TREE_NUT`, `MILK`, `EGG`, `WHEAT`, `SOY`, `FISH`, and `SESAME` (defaulting to empty). The `birth_date` must be a parseable ISO calendar date; an unparseable value is rejected with `ERR_VALIDATION` (HTTP 400). A child's `guardian_id` ties the record to the owning family, and the child's age at any slot's date must fall between 1 and 12 inclusive for a visit to be created on that slot; a child outside that band is rejected with `ERR_CHILD_AGE_OUT_OF_RANGE` (HTTP 422). Children and their visit history are readable by the owning guardian, the front desk, and managers.

Before any child steps onto the structure, the family must hold a current waiver. Signing a waiver — by the guardian or assisted by the front desk — is an OCC-guarded write (§2.7) carrying `expected_guardian_version`. On success the new `Waiver` records `signed_at` from the logical clock and an `expires_at` exactly 365 days later, enters `SIGNED` status, and any previously `SIGNED` waiver for the same guardian flips to `SUPERSEDED` so that at most one waiver per guardian is ever current; the act of signing also increments the guardian's `version` by 1. A waiver whose `expires_at` has been reached by the logical clock is flipped to `EXPIRED` by the operations sweep, after which check-in is refused until a fresh waiver is signed. A guardian's waiver history is listable by the guardian, the desk, or a manager.

### 3.2. Membership and Session Credits

`Admin` configures the membership catalog as `MembershipPlan` records, each with a `name`, a `monthly_fee_cents` price, an `included_session_credits` bundle, a `party_discount_pct` fraction (for example 0.10 for ten percent), a `cafe_discount_pct` fraction, and a `socks_included` flag stating whether the plan provides grip socks free at check-in. Plans are created `ACTIVE` and may later be patched to `RETIRED` (or back), each patch bumping the plan's `version`. Catalog reads are public, with an optional `status` filter.

A guardian (or an `Admin` on their behalf) enrolls by posting a `membership_plan_id`. Enrollment requires the plan to be `ACTIVE`; a retired plan is rejected with `ERR_PLAN_RETIRED` (HTTP 422). On enrollment or plan change, the guardian's `membership_status` becomes `ACTIVE` and `credits_granted` increases by the plan's `included_session_credits`, bumping the guardian's `version`. Cancelling membership sets `membership_status` to `CANCELLED`, forfeits the available balance by adjusting `credits_granted` so that nothing remains available, and likewise bumps `version` — but credits already held by in-flight visits are still honored through completion or release.

Session credit accounting derives entirely from the guardian's visits. `credits_consumed` counts the guardian's credit-funded visits whose `admission_status` is `COMPLETED` or `NO_SHOW`; `credits_held` counts those in `RESERVED` or `CHECKED_IN`; `credits_granted` reflects the plan bundle while membership is `ACTIVE` and is frozen at grant time. Two readings of the balance exist. The real-time reading, `credits_available`, is `credits_granted` minus `credits_consumed` minus `credits_held` — forward-looking, so held-but-unused credits count against availability at the reservation gate. The reporting reading, `credits_statement`, is `credits_granted` minus `credits_consumed` only, so a held credit still shows as available on a statement until it actually settles.

### 3.3. The Session Slot Day: Scheduling, Opening, and Closing

The play floor runs on `SessionSlot` records created by a `Manager` or `Admin` from a `slot_date`, a `start_at`, an `end_at`, and a `capacity`. Creation enforces the half-open overlap rule of §2.9 against all non-`CLOSED` slots on the same `slot_date`; an overlap is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). A new slot starts `SCHEDULED`, with its `reservation_quota` computed as seventy percent of `capacity` rounded down, and its `reserved_count` and `checked_in_count` counters at zero. Slots and their live counters are publicly readable, listable with `slot_date` and `status` filters, and desk staff can list a slot's visits filtered by `admission_status`.

A `Manager` opens a `SCHEDULED` slot, moving `status` to `OPEN` and bumping the slot's `version`; only `OPEN` slots admit new visits and check-ins, and any attempt against a slot in another state is rejected with `ERR_SLOT_NOT_OPEN` (HTTP 409).

Resizing a slot is the OCC-guarded `capacity` patch described in §2.7, carrying `expected_session_slot_version`; the patch is not gated on the slot's `status`. The new `capacity` may not fall below the current `checked_in_count` — children already on the structure cannot be disowned arithmetically — and such an attempt is rejected with `ERR_CAPACITY_BELOW_OCCUPANCY` (HTTP 422). The patch recomputes `reservation_quota` from the new capacity, bumps `version`, and, when the existing `reserved_count` now exceeds the new quota, cancels `RESERVED` visits newest-first — ordered by `created_at` descending, breaking ties by `quoted_cents` descending — until the count no longer exceeds the quota. Each visit cancelled by this cascade follows the ordinary cancellation settlement: a credit hold is released, and a prepaid visit's `payment_status` flips to `REFUNDED`.

Closing a slot — a `Manager` action carrying a `reason` of `MANAGER_CLOSE` or `EMERGENCY`, or the operations sweep acting on its own once the slot's `end_at` has been reached, recording `OPS_ENDED` — is the venue's heaviest cascade and runs in three hops. A manual close is accepted from `SCHEDULED` or `OPEN`; attempting to close an already `CLOSED` slot is rejected with `ERR_INVALID_STATE` (HTTP 409). Hop 1 moves every `RESERVED` visit on the slot to `CANCELLED` and every `CHECKED_IN` visit to `EVACUATED`, stamping `checked_out_at` from the logical clock on each evacuated visit (cancelled reservations receive no `checked_out_at`). Hop 2 settles money and credits: each cancelled `RESERVED` credit visit releases its hold, each cancelled prepaid visit flips `payment_status` to `REFUNDED`, and each `EVACUATED` visit is charged a compassionate evacuation rate — one half of the tiered per-minute charge for the elapsed minutes (§3.5), rounded half-up — recorded as `final_charge_cents`; an evacuated prepaid visit then records `refund_delta_cents` as its `quoted_cents` minus that final charge and flips to `REFUNDED`, while an evacuated credit visit has its held credit restored and never consumes it. An evacuated visit that was never prepaid records the compassionate charge as `final_charge_cents` but keeps `payment_status` `PENDING`; no collection or refund occurs for it. Hop 3 compensates families: every guardian with a visit cancelled or evacuated by this close receives a +200-point `ADJUSTMENT` entry in their loyalty ledger (one entry per affected guardian, no matter how many of that guardian's visits the close cancelled or evacuated), recomputing `points_balance` and `lifetime_points`. Visits already `COMPLETED`, `CANCELLED`, or `NO_SHOW` are untouched, the slot's `close_reason` is recorded, and the slot's `version` bumps.

### 3.4. Booking Play Time: Reservations and Walk-Ins

A visit ties a child to a slot. Creation carries the `session_slot_id`, `child_id`, and `guardian_id`, a `visit_type` of `RESERVATION` or `WALK_IN`, and, optionally, `booked_duration_minutes`, a `use_credit` flag, a `sock_method`, and a `grip_socks_order_id`. The target slot must be `OPEN`, and no second visit may be created for the same child on the same slot while one already exists in `RESERVED` or `CHECKED_IN` — a violation is `ERR_DUPLICATE_VISIT` (HTTP 409). The server does not check that the child belongs to the named guardian; any resolvable `child_id` and `guardian_id` pair is accepted.

A reservation, typically placed by the guardian from home, requires `booked_duration_minutes` and starts life `RESERVED` with `payment_status` `PENDING`. Its `quoted_cents` is a provisional block price: the booked minutes are divided into 60-minute blocks with any partial block counting as a whole one, and the quote is 1,200 cents for the first block plus 900 cents for each additional block — a 90-minute booking therefore quotes 2,100 cents. Admission is subject to the quota gate: a reservation is accepted only while `reserved_count` is strictly below `reservation_quota`, otherwise `ERR_RESERVATION_QUOTA_FULL` (HTTP 409). Because the family is not yet at the venue, the waiver and grip-sock gates are not evaluated at booking time; they bite at the desk. Any `sock_method` or `grip_socks_order_id` supplied at booking time is ignored: a reservation is stored with `sock_method` `NONE` and no `grip_socks_order_id`, and the resolved method is recorded only at check-in. Setting `use_credit` true funds the visit from membership credits instead of money: it requires an `ACTIVE` membership (else `ERR_MEMBERSHIP_REQUIRED`, HTTP 422) and at least one credit in `credits_available` (else `ERR_INSUFFICIENT_CREDITS`, HTTP 402), and a successful credit reservation immediately holds one credit. Each new reservation also raises the slot's `reserved_count` by one.

A walk-in is admitted at the desk by `FrontDesk` (or a `Manager`) and is created directly in `CHECKED_IN`, with `checked_in_at` stamped from the logical clock and the slot's `checked_in_count` raised by one; `booked_duration_minutes` is optional and `quoted_cents` stays null. Because admission happens on the spot, walk-in creation applies the full desk gate set described for check-in below — current waiver, resolvable socks, child age, duplicate visit, and slot-open — and adds the capacity gate: the sum of `reserved_count` and `checked_in_count` must be strictly below `capacity`, otherwise `ERR_SLOT_AT_CAPACITY` (HTTP 409). A walk-in may also set `use_credit`, subject to the same `ACTIVE`-membership and credit-availability gates as a credit reservation.

A reserved visit can be prepaid by the guardian or the desk, moving `payment_status` from `PENDING` to `PREPAID` and collecting the quoted amount. Prepayment is only offered while `admission_status` is `RESERVED` and `use_credit` is false — credit visits can never be prepaid.

Cancelling a `RESERVED` visit releases its credit hold if `use_credit` was set, flips a prepaid visit's `payment_status` to `REFUNDED`, and lowers the slot's `reserved_count` by one. A guardian cancelling their own booking must do so strictly before the slot's `start_at`; at or after the start the attempt is rejected with `ERR_CANCEL_CUTOFF` (HTTP 422), while staff and system cancellations are unrestricted. Note that only prepaid visits ever reach `REFUNDED`: a `PENDING` unpaid visit that is cancelled simply becomes `CANCELLED` with no refund record.

### 3.5. Check-In, Check-Out, Charging, and Payment Reconciliation

Checking in a reserved visit — `FrontDesk`, with `Manager` override — moves `admission_status` from `RESERVED` to `CHECKED_IN`. Four gates apply, in the precedence tiers of §2.8 — slot state first, then the safety gates, then the temporal window. The slot must be `OPEN` (else `ERR_SLOT_NOT_OPEN`). The guardian must hold a current waiver — one in `SIGNED` status whose `expires_at` is strictly in the future — otherwise `ERR_WAIVER_INVALID` (HTTP 422). Grip-sock compliance must then resolve for the declared `sock_method`: `OWN_GRIP_SOCKS` always passes; `MEMBERSHIP_PROVIDED` requires the guardian's membership to be `ACTIVE` on a plan whose `socks_included` is true; and `PURCHASED` requires the supplied `grip_socks_order_id` to reference a `SERVED` café order of this guardian, created on the slot's date, containing a line whose menu item is flagged `is_grip_socks`. An unresolvable declaration is rejected with `ERR_GRIP_SOCKS_REQUIRED` (HTTP 422). Finally, the logical clock must sit inside the check-in window, from ten minutes before the slot's `start_at` through fifteen minutes after it, inclusive; outside that window the rejection is `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 422). A successful check-in stamps `checked_in_at`, records the resolved `sock_method` and the supplied `grip_socks_order_id`, and moves one unit from `reserved_count` to `checked_in_count`.

A reservation that is never checked in does not linger: once the logical clock reaches fifteen minutes past the slot's `start_at`, the operations sweep marks it `NO_SHOW`. A credit-funded no-show consumes the held credit as the penalty, while a prepaid no-show forfeits its payment — `payment_status` stays `PREPAID` and no refund is issued; either way `reserved_count` drops by one.

Check-out — again `FrontDesk` with `Manager` override — moves the visit from `CHECKED_IN` to `COMPLETED`, but only while no unresolved lost-child incident gates the visit (§3.8): the presence of a linked `LOST_CHILD` incident in `OPEN` or `TRIAGED` rejects the check-out with `ERR_LOST_CHILD_UNRESOLVED` (HTTP 409). At check-out the final charge is computed over actual elapsed time, measured from `checked_in_at` to `checked_out_at` and rounded up to whole minutes. The tiered price charges the first 60 elapsed minutes at 20 cents per minute, any elapsed minutes beyond 60 up to 120 at 15 cents per minute, and any elapsed minutes beyond 120 at 10 cents per minute; when the guardian's membership is `ACTIVE`, the resulting amount is reduced by ten percent and rounded half-up. A 90-minute stay therefore costs 1,650 cents, or 1,485 cents for a member, and the result is recorded as `final_charge_cents`.

Payment then reconciles along the visit's parallel `payment_status` dimension, which evolves independently of `admission_status`. A `PENDING` visit collects the final charge and settles to `SETTLED`. A `PREPAID` visit also settles to `SETTLED`, recording `refund_delta_cents` as the amount by which its `quoted_cents` exceeded the final charge — zero when the family underpaid or matched — so overpayment is returned and `refund_delta_cents` is never negative. Credit visits skip money entirely: the held credit converts to consumed (the guardian's `credits_held` drops by one and `credits_consumed` rises by one), the monetary charge is waived, and the visit settles. Loyalty accrues only on monetary visits (§3.9), and the slot's `checked_in_count` drops by one.

### 3.6. The Café Counter: Menu, Orders, and Allergen Safety

`Admin` maintains the menu as `CafeMenuItem` records with a `name`, a `price_cents` unit price, an `allergen_tags` list drawn from the same allergen codes as children's `allergies` (defaulting to empty), and an `is_grip_socks` flag that marks the one retail grip-socks item used for sock compliance at the desk (defaulting to false). Items are created `ACTIVE`, can be patched to `RETIRED` and back with a `version` bump, and are publicly listable with an optional `status` filter.

An order is placed by a `Guardian` or the desk with the ordering `guardian_id` and a `lines` array whose entries each name a `menu_item_id` and a `quantity`; `lines` must be a non-empty array and each `quantity` must be an integer (no minimum is enforced), and a negative `points_to_redeem` is rejected with `ERR_VALIDATION` (HTTP 400); the server fills each line's `unit_price_cents` from the menu and computes its `line_total_cents`. Every referenced item must be `ACTIVE`, else `ERR_MENU_ITEM_RETIRED` (HTTP 422). An order may optionally link a `visit_id` for a family on the floor or a `party_booking_id` as a party pre-order, and may carry a `child_ids` list naming the children the food is for. That list drives the allergen interlock: no order line's `allergen_tags` may intersect the union of the listed children's `allergies`, and a conflict is rejected with `ERR_ALLERGEN_CONFLICT` (HTTP 422); an empty `child_ids` list skips the check entirely.

Pricing pins its rounding order — per line first, then sum, never sum-then-round. Each line's total is the `unit_price_cents` multiplied by the `quantity` and by one minus the guardian's plan `cafe_discount_pct` (zero when membership is not `ACTIVE`), rounded half-up to whole cents; the order's `subtotal_cents` is the sum of those rounded line totals. Points redemption is then checked, in the order stated: the requested `points_to_redeem` (default 0) may not exceed the guardian's `points_balance`, else `ERR_INSUFFICIENT_POINTS` (HTTP 402), and may not exceed half of the `subtotal_cents` rounded down, else `ERR_REDEMPTION_CAP_EXCEEDED` (HTTP 422). The applied `points_redeemed` is the smallest of the request, the balance, and that half-subtotal cap, at a rate of one cent per point, and `total_cents` is the `subtotal_cents` minus the points actually applied. A successful redemption posts a `REDEEM` ledger entry for the applied points at placement time — only when the applied points are positive; a zero-point redemption writes no entry — and the new order starts `PLACED`.

Kitchen workflow is simple: `CafeStaff` (or a `Manager`) moves an order from `PLACED` to `PREPARING`, then from `PREPARING` to `SERVED`. Serving is the earning moment (§3.9): `points_earned` is computed on the post-redemption `total_cents` using the guardian's loyalty tier at the instant of serving, and an `EARN` entry is written — only when the computed points are positive; a zero-point earn writes no entry, here and at visit check-out alike. Cancelling an unserved order — by the guardian, a manager, or the party-cancel cascade of §3.7 — moves `PLACED` or `PREPARING` orders to `CANCELLED`, restores the applied `points_redeemed` through a `REVERSAL` ledger entry adding those points back, and reverses any earned points. Orders are readable by the owning guardian, café staff, and managers, including per-visit and per-booking filtered lists.

### 3.7. Parties: Rooms, Packages, and the Booking Cycle

Party inventory is configured by `Admin`. A `PartyRoom` has a `name` and a `capacity_children` limit and moves between `ACTIVE`, `MAINTENANCE`, and `CLOSED` via an admin or manager patch that bumps its `version`. A `PartyPackage` has a `name`, a `duration_minutes` party length, a `base_price_cents`, an `included_children` headcount covered by the base price, an `extra_child_price_cents` for each child beyond that headcount, and an informational `cafe_credit_cents` bundled with the package; packages are created `ACTIVE` and can be retired and reactivated. Rooms and packages are publicly readable with optional `status` filters, and bookings per room are listable by staff and admins with a `status` filter.

A booking is created by a guardian or the desk against a `party_room_id`, a `party_package_id`, the booking `guardian_id`, a `start_at`, and a `child_count`, and it is the third OCC-guarded write of §2.7: the request must carry `expected_party_room_version` matching the room's current `version`, because each created booking bumps the room's `version` by 1. Both the room and the package must be `ACTIVE` — otherwise `ERR_ROOM_INACTIVE` or `ERR_PACKAGE_RETIRED` respectively (both HTTP 422) — and the `child_count` may not exceed the room's `capacity_children`, else `ERR_CAPACITY_BELOW_OCCUPANCY` (HTTP 422). The booking's `end_at` is computed as `start_at` plus the package's `duration_minutes`, and the room-conflict rule of §2.9 applies: the occupied interval, running from `start_at` through `end_at` plus a thirty-minute cleanup buffer and half-open at both ends, must not intersect any non-terminal booking on the same room, else `ERR_ROOM_TIME_CONFLICT` (HTTP 409). A created booking starts `HELD`.

The quote is computed at creation and again whenever the schedule changes. Extra children are the excess of `child_count` over the package's `included_children`, floored at zero; the subtotal is the `base_price_cents` plus one `extra_child_price_cents` per extra child. When the party starts on a Saturday or Sunday (UTC), a peak surcharge of fifteen percent of the subtotal, rounded half-up, is added. The membership discount fraction is the guardian's plan `party_discount_pct` when membership is `ACTIVE`, otherwise zero, capped at twenty-five percent; the discount is that fraction applied to the subtotal plus the surcharge, rounded half-up. The `quoted_total_cents` is the subtotal plus the surcharge minus the discount, and the `deposit_cents` is the greater of 5,000 cents and twenty percent of the quoted total rounded half-up — a fifty-dollar floor with a one-fifth rule above it.

Confirming is the guardian's own act: it requires the room still `ACTIVE` (else `ERR_ROOM_INACTIVE`), no `OVERDUE` sanitation task on that room (else `ERR_SANITATION_OVERDUE`, HTTP 422), and a re-check that the window is still conflict-free (the booking itself excluded from the comparison). Confirmation collects the `deposit_cents`, sets `deposit_paid` true, and moves the booking from `HELD` to `CONFIRMED`. A `HELD` booking whose deposit goes unpaid is not kept forever: the operations sweep expires it to `EXPIRED` once the logical clock reaches 24 hours past its `created_at`, releasing the hold with no refund because no deposit was ever paid.

Plans change. The guardian may request a reschedule, moving `CONFIRMED` to `RESCHEDULE_REQUESTED` and recording a `proposed_start_at`, but only while the logical clock is at least 48 hours before the current `start_at`; inside that cutoff the request is rejected with `ERR_RESCHEDULE_CUTOFF` (HTTP 422). Approval is a `Manager` decision: the proposed window is re-checked for room conflicts including the cleanup buffer (else `ERR_ROOM_TIME_CONFLICT`), and on approval the booking's `start_at` becomes the `proposed_start_at`, `end_at` is recomputed from the package duration, the full quote — peak flag included, since the new date may fall on a weekend — is recomputed, and the booking returns to `CONFIRMED`, completing the cycle. There is deliberately no rejection endpoint: a guardian whose proposed time is not approved cancels the booking outright or lets the request stand.

Cancelling a booking — the guardian or a `Manager`, from `HELD` or `CONFIRMED` — runs a refund waterfall on the deposit and a cascade across the café. Cancelling at least seven days before `start_at` refunds the deposit in full; cancelling after that point but at least 48 hours before `start_at` refunds half, rounded half-up; cancelling inside 48 hours refunds nothing, and a `HELD` booking whose deposit was never paid records `refund_cents` of zero. The waterfall outcome is recorded in `refund_cents`. The cascade then cancels every linked café order — those whose `party_booking_id` names this booking — still in `PLACED` or `PREPARING`, and each cancelled order restores its applied `points_redeemed` through a `REVERSAL` entry, recomputing the guardian's `points_balance`; orders already `SERVED` keep their earned points. Finally, once the party has run — the logical clock at or past `end_at` — a `Manager` marks the booking `COMPLETED` and the remaining balance, the `quoted_total_cents` minus the `deposit_cents`, is collected.

### 3.8. Staffing, Sanitation, and Incident Response

`Admin` provisions `StaffMember` records with a `full_name` and a `role` of `FRONT_DESK`, `CAFE_STAFF`, or `MANAGER`; staff are created `ACTIVE` and can be patched to `INACTIVE` with a `version` bump. As §2.1 states, a staff member may act only while `ACTIVE` and only in the role matching the presented `X-User-Role`.

Hygiene runs on `SanitationTask` records scheduled by a `Manager` for a `party_room_id`, with a `kind` of `DEEP_CLEAN`, `BALL_PIT_WASH`, or `SURFACE_WIPE` and a `due_at` deadline; a room's task list is readable by staff and admins with an optional `status` filter. A task starts `SCHEDULED`, and desk staff or a manager moves it to `IN_PROGRESS`. The operations sweep flags any task whose `due_at` has been reached while still `SCHEDULED` or `IN_PROGRESS` as `OVERDUE`, and an `OVERDUE` task on a room blocks party confirmation there with `ERR_SANITATION_OVERDUE`. Completion — from `SCHEDULED`, `IN_PROGRESS`, or `OVERDUE` — requires the submission of `checklist_passed` true; a false or absent pass is rejected with `ERR_VALIDATION` (HTTP 400), and a successful completion stamps `completed_at` from the logical clock.

Incidents are reported by desk staff or a manager with a `kind` of `LOST_CHILD`, `INJURY`, `PROPERTY_DAMAGE`, or `BEHAVIOR`, a `severity` of `LOW`, `MEDIUM`, or `CRITICAL`, a free-text `description`, and an optional `visit_id` linking a visit — required for `LOST_CHILD`. The reporter's `X-User-ID` is recorded as `reported_by_staff_id` for audit only; it is not a foreign key. A new incident starts `OPEN`, and from that moment a `LOST_CHILD` incident gates its linked visit: while the incident stands in `OPEN` or `TRIAGED`, the visit cannot be checked out, and the attempt fails with `ERR_LOST_CHILD_UNRESOLVED`.

The incident lifecycle is managed and deliberately cyclic. A `Manager` triages an `OPEN` incident to `TRIAGED`; resolves a `TRIAGED` incident to `RESOLVED`, stamping `resolved_at` and lifting the lost-child gate — but for a `LOST_CHILD` incident only when `child_reunited` is submitted true, otherwise `ERR_CHILD_NOT_REUNITED` (HTTP 422), with an optional `resolution_note` recorded alongside; and closes a `RESOLVED` incident to `CLOSED`. If new information emerges, a manager can reopen a `RESOLVED` incident back to `TRIAGED`, which clears `resolved_at` (any recorded `child_reunited` and `resolution_note` are retained) and re-engages the lost-child check-out gate. Incidents are readable by desk staff and managers, including the per-visit incident list.

### 3.9. Loyalty Points, Manual Adjustments, and the Operations Sweep

The loyalty ledger is an append-only series of `LoyaltyTransaction` entries per guardian, each with a `kind` of `EARN`, `REDEEM`, `REVERSAL`, or `ADJUSTMENT`, a signed `points` value — positive for `EARN`, negative for `REDEEM`, whichever sign restores the balance for `REVERSAL`, and explicitly signed for `ADJUSTMENT` — a free-text `note`, and a `balance_after` snapshot of the guardian's `points_balance` immediately after the entry. The guardian's spendable `points_balance` is the sum of earned points minus redeemed points plus the signed adjustments and reversals across the ledger. The lifetime figure, `lifetime_points`, accumulates all points ever earned (`EARN`), plus positive `ADJUSTMENT` points, plus the signed points of every `REVERSAL` entry — a redemption restore adds its points back, an earned-points reversal subtracts them — while negative adjustments never reduce it; the result is floored at zero, and drives tier assignment: a guardian whose `lifetime_points` reaches at least 5,000 is `GOLD`, at least 1,000 is `SILVER` (the boundary is inclusive — exactly 1,000 is `SILVER`, exactly 5,000 is `GOLD`), and otherwise `BRONZE`. The ledger is listable by the guardian or a manager, filterable by `kind`.

Earning follows a pinned order wherever points and money meet. At the café, the order totals are computed first, redemption is applied second, and only then are points earned — on the post-redemption `total_cents` — as one point per whole 100 cents (floor division) multiplied by the guardian's tier multiplier: 1 for `BRONZE`, 2 for `SILVER`, 3 for `GOLD`, read at the moment of earning. The same rule rewards play: at check-out, a monetary visit earns its `final_charge_cents` divided by 100 and floored, times the same multiplier, while credit visits earn nothing. A `Manager` can also post a manual loyalty adjustment with a signed `points` value and a `note`; the entry is recorded as an `ADJUSTMENT`, the guardian's `points_balance` is recomputed as the raw signed ledger sum (it is not floored — a sufficiently negative adjustment can take it below zero), `lifetime_points` is recomputed floored at zero, and the guardian's `version` bumps.

The operations sweep — a `Manager` or `Admin` capability — is the single engine behind every time-driven transition in this document. One run marks no-shows for `RESERVED` visits fifteen minutes past their slot start, expires unpaid `HELD` party bookings at 24 hours of age, flags sanitation tasks whose `due_at` has passed as `OVERDUE`, closes slots whose `end_at` has passed with `close_reason` `OPS_ENDED` (running the full §3.3 cascade), expires waivers whose `expires_at` has been reached, and recomputes loyalty tiers from `lifetime_points`. The run reports its work as counts: `no_shows_marked`, `holds_expired`, `sanitations_flagged`, `slots_closed`, `waivers_expired`, and `tiers_recomputed`; `tiers_recomputed` counts every guardian record evaluated — all guardians are re-tiered on each run, whether or not any tier changed. Because the sweep and every timestamp in the system read the logical clock of §2.4, an `Admin` can drive an entire day — windows opening, cutoffs passing, sweeps running — by advancing the clock to a chosen instant.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act on an existing resource return `200 OK`. Error responses follow §2.2 and use the catalog in §5. The table below is a navigational summary only — request payloads, computed fields, side effects, and preconditions are defined by the workflows of §3 and the principles of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership-plans` | Create a membership plan | Admin |
| GET | `/membership-plans` | List membership plans | Any (including Anonymous) |
| PATCH | `/membership-plans/{id}` | Retire or reactivate a plan | Admin |
| POST | `/party-packages` | Create a party package | Admin |
| GET | `/party-packages` | List party packages | Any (including Anonymous) |
| PATCH | `/party-packages/{id}` | Retire or reactivate a package | Admin |
| POST | `/party-rooms` | Create a party room | Admin |
| GET | `/party-rooms` | List party rooms | Any (including Anonymous) |
| GET | `/party-rooms/{id}` | Get one party room | Any (including Anonymous) |
| PATCH | `/party-rooms/{id}` | Set room status (ACTIVE / MAINTENANCE / CLOSED) | Admin, Manager |
| POST | `/cafe-menu-items` | Create a menu item | Admin |
| GET | `/cafe-menu-items` | List menu items | Any (including Anonymous) |
| PATCH | `/cafe-menu-items/{id}` | Retire or reactivate a menu item | Admin |
| POST | `/staff-members` | Create a staff member | Admin |
| GET | `/staff-members/{id}` | Get one staff member | Manager, Admin |
| PATCH | `/staff-members/{id}` | Set staff status (ACTIVE / INACTIVE) | Admin |
| POST | `/guardians` | Self-register a guardian account | Anonymous |
| GET | `/guardians` | List guardians, optionally filtered by plan | Manager, Admin |
| GET | `/guardians/{id}` | Get one guardian with computed credit and loyalty fields | Guardian, FrontDesk, Manager, Admin |
| POST | `/guardians/{id}/children` | Register a child | Guardian, FrontDesk |
| GET | `/guardians/{id}/children` | List a guardian's children | Guardian, FrontDesk, Manager |
| GET | `/children/{id}` | Get one child | Guardian, FrontDesk, Manager |
| GET | `/children/{id}/visits` | List visits for a child | Guardian, FrontDesk, Manager |
| POST | `/guardians/{id}/waivers` | Sign a new waiver, superseding the prior one (OCC on guardian version) | Guardian, FrontDesk |
| GET | `/guardians/{id}/waivers` | List a guardian's waivers | Guardian, FrontDesk, Manager |
| POST | `/guardians/{id}/membership` | Enroll in or change a membership plan | Guardian, Admin |
| POST | `/guardians/{id}/membership/cancel` | Cancel membership | Guardian, Admin |
| GET | `/guardians/{id}/visits` | List a guardian's visits | Guardian, FrontDesk, Manager |
| GET | `/guardians/{id}/cafe-orders` | List a guardian's café orders | Guardian, CafeStaff, Manager |
| GET | `/guardians/{id}/party-bookings` | List a guardian's party bookings | Guardian, FrontDesk, Manager |
| GET | `/guardians/{id}/loyalty-ledger` | List loyalty ledger entries | Guardian, Manager |
| POST | `/guardians/{id}/loyalty-adjustments` | Post a manual signed-points adjustment | Manager |
| POST | `/session-slots` | Create a session slot with half-open overlap check | Manager, Admin |
| GET | `/session-slots` | List session slots | Any (including Anonymous) |
| GET | `/session-slots/{id}` | Get one slot with live counters | Any (including Anonymous) |
| PATCH | `/session-slots/{id}` | Resize capacity (OCC); over-quota reservations cancelled newest-first | Manager |
| POST | `/session-slots/{id}/open` | Open a slot for admissions | Manager |
| POST | `/session-slots/{id}/close` | Close a slot; cascades to visits, credits, refunds, compensation points | Manager |
| GET | `/session-slots/{id}/visits` | List visits on a slot | FrontDesk, Manager |
| POST | `/visits` | Create a reservation or desk-admitted walk-in | Guardian, FrontDesk, Manager |
| GET | `/visits/{id}` | Get one visit | Guardian, FrontDesk, Manager |
| POST | `/visits/{id}/pay` | Prepay a reservation at its quoted price | Guardian, FrontDesk |
| POST | `/visits/{id}/check-in` | Check in a reserved visit (slot, window, waiver, socks gates) | FrontDesk, Manager |
| POST | `/visits/{id}/check-out` | Check out; final charge, payment reconciliation, loyalty earn | FrontDesk, Manager |
| POST | `/visits/{id}/cancel` | Cancel a reserved visit | Guardian, FrontDesk, Manager |
| GET | `/visits/{id}/cafe-orders` | List café orders linked to a visit | Guardian, CafeStaff, Manager |
| GET | `/visits/{id}/incidents` | List incidents linked to a visit | FrontDesk, Manager |
| POST | `/party-bookings` | Create a party booking in HELD (OCC on room version) | Guardian, FrontDesk |
| GET | `/party-bookings` | List party bookings, filterable | Manager, Admin |
| GET | `/party-bookings/{id}` | Get one party booking | Guardian, FrontDesk, Manager |
| POST | `/party-bookings/{id}/confirm` | Pay deposit and confirm | Guardian |
| POST | `/party-bookings/{id}/request-reschedule` | Request a new start time (48-hour cutoff) | Guardian |
| POST | `/party-bookings/{id}/approve-reschedule` | Approve reschedule; re-check conflict, re-quote | Manager |
| POST | `/party-bookings/{id}/cancel` | Cancel with deposit refund waterfall; cascades to café orders and points | Guardian, Manager |
| POST | `/party-bookings/{id}/complete` | Mark a confirmed party completed after it ran | Manager |
| GET | `/party-bookings/{id}/cafe-orders` | List café orders linked to a party booking | Guardian, CafeStaff, Manager |
| GET | `/party-rooms/{id}/party-bookings` | List bookings for a room | FrontDesk, Manager, Admin |
| GET | `/party-rooms/{id}/sanitation-tasks` | List sanitation tasks for a room | FrontDesk, Manager, Admin |
| POST | `/cafe-orders` | Place an order (allergen check, per-line rounding, points redemption) | Guardian, FrontDesk |
| GET | `/cafe-orders/{id}` | Get one order | Guardian, CafeStaff, Manager |
| POST | `/cafe-orders/{id}/start-preparing` | Begin preparation | CafeStaff, Manager |
| POST | `/cafe-orders/{id}/serve` | Serve; grants loyalty points on the post-redemption total | CafeStaff, Manager |
| POST | `/cafe-orders/{id}/cancel` | Cancel an unserved order; restores redeemed points | Guardian, Manager |
| POST | `/sanitation-tasks` | Schedule a sanitation task for a party room | Manager |
| POST | `/sanitation-tasks/{id}/start` | Start a sanitation task | FrontDesk, Manager |
| POST | `/sanitation-tasks/{id}/complete` | Complete a task; checklist must pass | FrontDesk, Manager |
| POST | `/incidents` | Report an incident; LOST_CHILD links a visit and gates its check-out | FrontDesk, Manager |
| GET | `/incidents/{id}` | Get one incident | FrontDesk, Manager |
| POST | `/incidents/{id}/triage` | Triage an open incident | Manager |
| POST | `/incidents/{id}/resolve` | Resolve an incident; LOST_CHILD requires reunion | Manager |
| POST | `/incidents/{id}/reopen` | Reopen a resolved incident | Manager |
| POST | `/incidents/{id}/close` | Close a resolved incident | Manager |
| POST | `/ops-runs` | Run the operations sweep over all time-driven transitions | Manager, Admin |
| POST | `/_clock/set_current_utc` | Advance the logical clock | Admin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narrative of §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SLOT_NOT_OPEN` | 409 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 422 |
| `ERR_DUPLICATE_VISIT` | 409 |
| `ERR_CHILD_AGE_OUT_OF_RANGE` | 422 |
| `ERR_WAIVER_INVALID` | 422 |
| `ERR_GRIP_SOCKS_REQUIRED` | 422 |
| `ERR_RESERVATION_QUOTA_FULL` | 409 |
| `ERR_SLOT_AT_CAPACITY` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_CAPACITY_BELOW_OCCUPANCY` | 422 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_ROOM_INACTIVE` | 422 |
| `ERR_PACKAGE_RETIRED` | 422 |
| `ERR_PLAN_RETIRED` | 422 |
| `ERR_MENU_ITEM_RETIRED` | 422 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_SANITATION_OVERDUE` | 422 |
| `ERR_RESCHEDULE_CUTOFF` | 422 |
| `ERR_CANCEL_CUTOFF` | 422 |
| `ERR_MEMBERSHIP_REQUIRED` | 422 |
| `ERR_INSUFFICIENT_CREDITS` | 402 |
| `ERR_INSUFFICIENT_POINTS` | 402 |
| `ERR_REDEMPTION_CAP_EXCEEDED` | 422 |
| `ERR_LOST_CHILD_UNRESOLVED` | 409 |
| `ERR_CHILD_NOT_REUNITED` | 422 |

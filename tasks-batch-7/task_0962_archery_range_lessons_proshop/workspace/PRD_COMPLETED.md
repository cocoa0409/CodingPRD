# Archery Range, Lessons & Pro-Shop API — Product Requirements Document

## 1. Introduction

An archery facility runs three intertwined businesses under one roof: a lane range where archers book time by the half-hour, a coaching practice where lessons are negotiated back and forth between student and coach before a single dollar moves, and a pro-shop that sells merchandise, rents fitted equipment, and takes in repair work. Each line of business has its own rhythms — walk-ins versus reservations on the range, a confirm/counter negotiation cycle for lessons, a quote/approve/decline branch at the repair bench — but they share a single membership base, a single prepaid wallet per member, and a single logical clock that governs everything from whether a member counts as a minor to whether a no-show session forfeits its fees.

This document specifies the REST API that backs the facility. It is written for the engineer implementing the service: §2 pins down the system-wide contracts (authentication, response envelopes, pagination, the logical clock, money rounding, optimistic concurrency, and the fixed order in which validations fire), §3 walks the business workflows in narrative form with every rule attached to the workflow it guards, §4 tabulates the endpoints, and §5 catalogues the error identifiers. Safety and compliance are first-class concerns throughout: no archer steps onto a lane, rents a bow, takes a lesson, or enters a league without an active liability waiver, minors participate only under a guardian's consent, and three recorded safety strikes suspend a member and cascade-cancel their future bookings.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The declared roles, spelled exactly as the API expects them, are `Anonymous`, `Member`, `Coach`, `RangeOfficer`, `ShopClerk`, `LeagueDirector`, and `Admin`. An unauthenticated caller participates as `Anonymous`: it may register a new member and may read the public resources (lanes, coaches, leagues, standings, and pro-shop products), and nothing else.

Two roles are entity-backed. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — a session's creator, a participant's archer, a punch card's owner, a rental's renter, a lesson's student, a league entry's entrant, a repair order's equipment owner — compare the resource's foreign-key field to `X-User-ID`, and a member acting on another member's resource is rejected with `ERR_UNAUTHORIZED` (HTTP 403). When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; lesson actions that are reserved to the assigned coach compare `X-User-ID` to the lesson's `coach_id`, and a mismatch is likewise `ERR_UNAUTHORIZED`. The remaining roles are opaque operator identities: when `X-User-Role` is `Anonymous`, `RangeOfficer`, `ShopClerk`, `LeagueDirector`, or `Admin`, `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

`Admin` is the operator superset in a hierarchical-override model: it holds every staff read, and exclusively holds the logical-clock capability, lane and coach creation, coach activation and deactivation, signed wallet adjustments, and waiver revocation. `RangeOfficer` runs the range floor — check-in, close, safety strikes, reinstatement, rental returns and settlements — and may also book or cancel sessions. `ShopClerk` runs the retail counter and the repair bench: product creation, sales, repair intake, quoting, completion, and pickup. `LeagueDirector` creates, closes, and cancels leagues and adjudicates scorecards. A role attempting an operation outside its grant is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. Non-integer values fall back to the defaults, and out-of-range values are clamped into range (limit to [1, 100], offset floored at 0) rather than rejected. Results are always sorted by `created_at` ascending, with ties broken by creation order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching resources and `has_more` indicates whether further pages exist beyond the returned window.

### 2.4. Common Resource Properties

Every resource in this API carries four server-managed properties in addition to its domain fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC timestamp with three fractional digits, and `updated_at` follows the same format and is refreshed on every mutation. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource; it is the backbone of the optimistic concurrency rules in §2.7. Because every entity in this system shares these four properties, none of them are ever supplied by the client on creation.

### 2.5. The Logical Clock and the Epoch Sweep

The system does not use wall-clock time. All temporal judgments — whether a member is a minor, whether a reservation has enough lead time, whether a session has no-showed, whether a waiver has lapsed — are made against a **logical clock**. Before any operator intervention, the logical clock sits at exactly 2026-05-01T00:00:00Z. An `Admin`-only capability advances the clock to a supplied `to_iso8601` instant, and the response reports the resulting `current_utc` together with two sweep counters, `no_show_sessions` and `expired_waivers`.

Advancing the clock runs an epoch sweep with two branches. First, every range session still in `BOOKED` whose start time plus fifteen minutes has passed without a check-in is swept to `NO_SHOW`, with the full forfeiture and rental-void cascade described in §3.4. Second, every waiver in `ACTIVE` whose `valid_until` date is strictly before the new current date transitions to `EXPIRED`; a waiver remains valid through its `valid_until` date inclusive, so expiry only bites on the following day.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents — no fractional cents exist anywhere in the system. Every multiplication that can produce a fraction (peak multipliers, tier discounts, percentage fees, tax) is resolved with **round half up** at the step where the scaffold of each calculation marks it; the per-calculation rounding steps are stated with the formulas in §3, and where a calculation pins an evaluation order (per-line rounding before summation in a sale; range share computed from gross rather than from the prize pool in a league), that order is part of the contract, not an implementation detail. Durations are whole minutes, distances are whole UTC calendar days, and standings points are whole integers, each rounded as its formula specifies.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only two endpoints in the API that take a version field.

A scorecard correction — the edit/correction capability on an existing scorecard — must carry `expected_scorecard_version` holding the client's last observed `version` of that scorecard. If another writer has advanced the card's version since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412): the newer edit legitimately supersedes the prior content under the correction-cycle rules of §3.8, and the stale writer must re-read the card before editing.

Posting a quote against a repair order must carry `expected_repair_order_version` holding the client's last observed `version` of that repair order. A mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the newer quote legitimately supersedes the older one and the stale writer must re-read before quoting. No other endpoint accepts a version field; requests to any other operation must not include one. Within the §2.8 ordering, the version check fires after the target's state-machine precondition and before any resource-availability check.

### 2.8. Validation Priority Ordering

When several validations could reject the same request, they are evaluated in a fixed priority order, so the surfaced error is deterministic. Authentication comes first (missing headers or an undeclared role yield `ERR_UNAUTHENTICATED`), then authorization and entity-backed ownership (`ERR_UNAUTHORIZED`), then path-identifier existence resolved left-to-right (the leftmost unresolvable segment determines which `ERR_*_NOT_FOUND` is raised), then request shape — required fields present, enum values valid, ranges respected (`ERR_INVALID_REQUEST`). Only after the request is well-formed do state-machine preconditions fire (the specific state error of the target transition, such as `ERR_SESSION_NOT_BOOKED`), followed by the waiver-and-consent gate — within which the member-status check (`ERR_MEMBER_SUSPENDED`) fires first, then `ERR_WAIVER_MISSING`, `ERR_WAIVER_EXPIRED`, `ERR_MINOR_GUARDIAN_REQUIRED`, `ERR_GUARDIAN_NOT_ADULT` — then resource-constraint checks (`ERR_LANE_OVERLAP`, `ERR_LANE_CAPACITY_EXCEEDED`, `ERR_COACH_OVERLAP`, `ERR_DISCIPLINE_MISMATCH`, `ERR_DUPLICATE_LEAGUE_ENTRY`, `ERR_LEAGUE_FULL`), then booking-window rules (`ERR_BOOKING_WINDOW_VIOLATION`), then resource-availability checks (`ERR_RENTAL_ITEM_UNAVAILABLE`, `ERR_INSUFFICIENT_STOCK`, `ERR_PUNCH_CARD_EXHAUSTED`), and finally funds (`ERR_INSUFFICIENT_FUNDS`). A consequence worth internalizing: a request that is both in the wrong state and short of funds always surfaces the state error, never the funds error.

### 2.9. The Safety Compliance Gate

Waiver and consent checks form a cross-cutting gate over seven operations: waiver signing itself, session booking, adding a participant, session check-in, creating a rental agreement, requesting a lesson, and entering a league. In each, the acting or target member must hold a waiver in `ACTIVE` status: if the member has never signed any waiver the rejection is `ERR_WAIVER_MISSING` (HTTP 422); if the member's latest waiver is `EXPIRED` or `REVOKED` the rejection is `ERR_WAIVER_EXPIRED` (HTTP 422). Consent for minors is stricter: a minor may never sign their own waiver (`ERR_MINOR_GUARDIAN_REQUIRED`), and the signing guardian must be an adult member (`ERR_GUARDIAN_NOT_ADULT`). The full consent workflow is specified in §3.2.

### 2.10. Nested Resource Retrieval

Paths in this API are hierarchical — a waiver under a member, a participant or a check-in under a session, a punch card under a member, a scorecard under a league entry. Path identifiers are validated strictly left-to-right: each segment must resolve before the next is examined, and the leftmost segment that does not resolve determines the not-found error — `ERR_MEMBER_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_PUNCH_CARD_NOT_FOUND`, `ERR_RENTAL_ITEM_NOT_FOUND`, `ERR_RENTAL_AGREEMENT_NOT_FOUND`, `ERR_COACH_NOT_FOUND`, `ERR_LESSON_NOT_FOUND`, `ERR_LEAGUE_NOT_FOUND`, `ERR_LEAGUE_ENTRY_NOT_FOUND`, `ERR_SCORECARD_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, or `ERR_REPAIR_ORDER_NOT_FOUND`, each HTTP 404.

## 3. Business Logic & Workflows

### 3.1. Membership, Minors, and the Safety-Strike Suspension Cascade

Anyone may register as a member by supplying an `email` (unique across all members), a `full_name`, and a `date_of_birth` in ISO `YYYY-MM-DD` form; a `tier` of `BASIC`, `PLUS`, or `ELITE` may be supplied and defaults to `BASIC`. `is_minor` is never stored; it is derived against the current logical clock on every read and every check: a member is a minor if and only if the current logical-clock date is earlier than the eighteenth anniversary of their `date_of_birth` — a member whose eighteenth birthday is exactly today is an adult. When the new member is a minor at registration time, a `guardian_id` referencing an existing adult member (one whose `is_minor` is false) is mandatory; omitting it is rejected with `ERR_MINOR_GUARDIAN_REQUIRED`, pointing it at a member who does not exist is rejected with `ERR_MEMBER_NOT_FOUND`, and pointing it at a minor is rejected with `ERR_GUARDIAN_NOT_ADULT`. A new member starts with `status` `ACTIVE`, `safety_strikes` 0, and `wallet_balance_cents` 0. Members may be listed with optional `status` and `guardian_id` filters, plus the standard `limit` and `offset`.

The prepaid wallet, `wallet_balance_cents`, is the single funding source for lane fees, punch-card purchases, lesson fees, league entries, rental settlements, and repair pickups; it is mutated only by charges, refunds, and admin adjustments. An `Admin` may post a signed wallet adjustment carrying `amount_cents` (positive to top up, negative to debit) with an optional `reason`; the amount is added to the member's balance.

Safety on the range is enforced through strikes. A `RangeOfficer` records a strike against a member, optionally with a `reason` (accepted but not persisted — only the count is kept), incrementing `safety_strikes` by one; recording a strike against a member whose `status` is not `ACTIVE` is rejected with `ERR_MEMBER_SUSPENDED`. The strike that brings the count to exactly three — that is, the member stood at two strikes before it — auto-suspends the member: `status` flips from `ACTIVE` to `SUSPENDED`, and a three-hop cascade fires. First, every range session created by this member that is still `BOOKED` and whose `start_at` lies in the future transitions to `CANCELLED` as a system cancel, which always refunds in full. Second, each such cancellation voids that session's rental agreements still `OPEN`, moving them to `VOIDED`. Third, each voided agreement releases its rental item back to `AVAILABLE`. Every participant of each system-cancelled session is refunded in full — wallet credit, punch restore, or both — and the session's `payment_status` follows the same rule as any cancellation (§3.4): it becomes `REFUNDED` only when the refunded amount recorded in `cancellation_refund_cents` is greater than zero. Suspension also voids the member's own `OPEN` rental agreements directly, releasing their items, even where no session link exists. A `RangeOfficer` may later reinstate the member, returning `status` to `ACTIVE` and resetting `safety_strikes` to 0; reinstating a member who is not `SUSPENDED` is rejected with `ERR_MEMBER_NOT_SUSPENDED`. Conversely, any purchase, booking, or entry attempted by a member whose `status` is not `ACTIVE` is rejected with `ERR_MEMBER_SUSPENDED`.

### 3.2. Waivers and Guardian Consent

A waiver is signed by a `Member` through the member-scoped signing capability. Adults sign for themselves: the signer's identity must equal the member the waiver covers (a mismatch is `ERR_UNAUTHORIZED`), and the recorded `signed_by_member_id` is that same member. For a minor, the waiver must be signed by their guardian — the signer's identity must equal the minor member's `guardian_id`, and that guardian must be an adult; a minor attempting to sign their own waiver is rejected with `ERR_MINOR_GUARDIAN_REQUIRED`, and a signer who is not the member's adult guardian with `ERR_GUARDIAN_NOT_ADULT`. Signing stamps `signed_at` from the logical clock, computes `valid_until` as the signed date plus 365 days (the waiver is valid through that date inclusive), and sets `status` to `ACTIVE`. Each waiver also records the `member_id` it covers, and a member's waivers may be listed — a `Member` caller may list their own waivers or those of a member whose `guardian_id` they are.

Waivers lapse in two ways. The epoch sweep of §2.5 expires an `ACTIVE` waiver whose `valid_until` has passed, moving it to `EXPIRED`. An `Admin` may revoke a waiver outright, moving it from either `ACTIVE` or `EXPIRED` to the terminal `REVOKED`; revoking an already `REVOKED` waiver is rejected with `ERR_WAIVER_NOT_REVOKABLE`. Wherever §2.9's gate requires an active waiver, having none at all yields `ERR_WAIVER_MISSING` and having only lapsed ones yields `ERR_WAIVER_EXPIRED`.

### 3.3. Booking the Range: Sessions, Participants, and Metered Fees

Lanes are the bookable inventory. An `Admin` creates a lane with a unique `name`, a `lane_type` of `INDOOR` or `OUTDOOR`, and a `max_archers` of at least 1; anyone, including `Anonymous`, may list or read lanes, and the sessions booked on a lane may be listed per lane.

A `Member` books a session — or a `RangeOfficer` books one on a member's behalf by supplying `created_for_member_id` (mandatory for a `RangeOfficer`, its absence being `ERR_INVALID_REQUEST`; a `Member` supplying a `created_for_member_id` other than their own identity is `ERR_UNAUTHORIZED`; a creator id naming no existing member is `ERR_MEMBER_NOT_FOUND`), in which case that member becomes the recorded `created_by_member_id` (for a self-booking it is simply the caller's identity). The booking names a `lane_id`, a `booking_type` of `WALK_IN` or `RESERVATION`, and a `start_at`/`end_at` pair in UTC with `end_at` strictly after `start_at` (otherwise `ERR_INVALID_REQUEST`). The booking window depends on the type: a `RESERVATION` must start at least 120 minutes after the current logical clock, while a `WALK_IN` must start on the same UTC date as the current clock and end after it; violations are rejected with `ERR_BOOKING_WINDOW_VIOLATION`. Lane occupancy is the half-open interval from `start_at` inclusive to `end_at` exclusive, so back-to-back bookings are allowed, but any strict overlap with an existing `BOOKED` or `CHECKED_IN` session on the same lane is rejected with `ERR_LANE_OVERLAP`. The creator must be an active member holding an active waiver per §2.9. The session's `booked_minutes` — the whole-minute length of the booking, fractional minutes truncated — is computed at creation; a new session starts with `session_status` `BOOKED`, `payment_status` `UNPAID`, and `quoted_charge_cents` 0. Sessions may be listed with `lane_id`, `created_by_member_id`, and `session_status` filters.

Archers join a session as participants. Adding a participant to a session names the `member_id` of the archer, a `payment_method` of `WALLET` or `PUNCH_CARD`, and — exactly when the method is `PUNCH_CARD` — a `punch_card_id`. The session must still be `BOOKED` (`ERR_SESSION_NOT_BOOKED`, or `ERR_SESSION_ALREADY_CLOSED` when the session is `CLOSED`), the roster of `ACTIVE` participants must stay within the lane's `max_archers` (`ERR_LANE_CAPACITY_EXCEEDED`), each `member_id` is unique per session — a repeat add of the same member, whatever their participant status, is `ERR_INVALID_REQUEST`, evaluated after the state and waiver gates — and the archer must be an active, waivered member. A punch card used for payment must exist, belong to the session's creator (creators may pay for their guests), be `ACTIVE`, and have at least one punch remaining; any of these failing is `ERR_PUNCH_CARD_EXHAUSTED`. At add time the participant's `quoted_fee_cents` is computed by the **quoted** variant of the lane fee below. A wallet payment debits `quoted_fee_cents` from the archer's `wallet_balance_cents` (`ERR_INSUFFICIENT_FUNDS` if short); a punch payment consumes one punch as described in §3.5. Either way the participant starts `ACTIVE`, the session's `quoted_charge_cents` grows by the quoted fee, and `payment_status` moves to `PAID`. Participants may be listed with `session_id`, `member_id`, and `punch_card_id` filters; a `Member` may read an individual participant record only for their own participation or for a participant of a session they created.

The lane fee has two variants, both tiered over 30-minute blocks at a base rate of 1200 cents per block, with a peak multiplier of 1.25 when the session's `start_at` falls in a peak hour — UTC hours 17 through 20 inclusive — and a tier discount keyed to the **participant's** membership tier: 0% for `BASIC`, 10% for `PLUS`, 20% for `ELITE`. The quoted variant, metered on `booked_minutes`, computes: the number of blocks is `booked_minutes` divided by 30 rounded up to a whole number; the base is 1200 times that block count; if the session is peak, the base is multiplied by 1.25 and rounded half up; the tier discount is then applied and the result rounded half up; the fee is the greater of that discounted amount and the 1200-cent minimum charge; and finally, for a `WALK_IN` booking only, a 300-cent surcharge is added **after** the minimum-charge floor. The final variant, computed at close, is metered on actual checked-in time: the elapsed seconds between `checked_in_at` and `closed_at` are divided by 60 and rounded up to whole minutes; blocks, base, peak (still keyed on the session's `start_at`), discount, and the 1200-cent floor apply exactly as in the quoted variant — but the walk-in surcharge is **never** applied in the final variant. For punch-paid participants both fee figures are recorded for reporting, with no wallet movement.

Check-in is performed by a `RangeOfficer`. The session must be `BOOKED` (`ERR_SESSION_NOT_BOOKED`; operating on a session that already reached a terminal state such as `CLOSED` surfaces `ERR_SESSION_ALREADY_CLOSED`), the current logical clock must lie within the check-in window from `start_at` through fifteen minutes after it inclusive (`ERR_BOOKING_WINDOW_VIOLATION` outside it), at least one participant must be `ACTIVE` (a session with none is `ERR_INVALID_REQUEST`), and — a cross-entity gate — **every** `ACTIVE` participant must belong to a member whose `status` is `ACTIVE` and who holds an `ACTIVE` waiver (`ERR_MEMBER_SUSPENDED`, `ERR_WAIVER_MISSING`, or `ERR_WAIVER_EXPIRED` as applicable). A successful check-in stamps `checked_in_at` from the logical clock and moves `session_status` to `CHECKED_IN`.

Closing, likewise a `RangeOfficer` action, requires `CHECKED_IN` (from `BOOKED` the rejection is `ERR_SESSION_NOT_BOOKED`, from `CLOSED` it is `ERR_SESSION_ALREADY_CLOSED`) and a logical clock strictly after `checked_in_at` (`ERR_BOOKING_WINDOW_VIOLATION` otherwise). It stamps `closed_at`, recomputes every `ACTIVE` participant's `final_fee_cents` under the final variant, and sets the session's `final_charge_cents` to their sum. Wallets are then reconciled participant by participant: for each wallet-paying participant the difference between `final_fee_cents` and `quoted_fee_cents` is debited or credited — with no insufficient-funds check at close, so the debit applies even if it drives the balance negative — so a participant who shot a shorter or off-peak-adjusted session gets money back and one who stayed long pays the difference; `payment_status` stays at, or becomes, `PAID`. `final_charge_cents` remains null until close, just as `cancellation_refund_cents` remains null until a cancellation. The `payment_status` dimension evolves in parallel with `session_status`: `BOOKED` with all participants paid shows `PAID`; `CANCELLED` or `NO_SHOW` sessions that issued refunds show `REFUNDED`.

### 3.4. Cancellation, No-Show, and Refund Tiers

A `BOOKED` session may be cancelled voluntarily by its creator or a `RangeOfficer`; cancelling from any other state is `ERR_SESSION_NOT_BOOKED`, except a `CLOSED` session, which surfaces `ERR_SESSION_ALREADY_CLOSED`. The refund tier depends on notice — the gap between the current logical clock and `start_at`. Notice of at least 24 hours refunds 100% of each `ACTIVE` participant's quoted fees; notice of at least 4 hours but under 24 hours refunds 50%, rounded half up per participant; notice under 4 hours refunds nothing. The boundaries are inclusive upward: exactly 24 hours is a full refund, exactly 4 hours is the 50% tier. System cancels — the suspension cascade of §3.1 — always refund 100%. For punch-paid participants the punch, not money, is at stake: the punch is restored to the card (decrementing `punches_used`, and reactivating an `EXHAUSTED` card to `ACTIVE`) if and only if notice is at least 4 hours or the cancel is a system cancel; below four hours the punch is forfeited with no restore. A participant who receives any refund or punch restore transitions from `ACTIVE` to `REFUNDED`; one who forfeits — voluntary cancel under four hours' notice, or the no-show sweep — transitions to `FORFEITED`. The cancellation records the total in `cancellation_refund_cents` — wallet money only, so a punch restore contributes nothing to it — and `payment_status` becomes `REFUNDED` if and only if that refunded amount is greater than zero; a cancellation whose refunded amount is zero (for example, one that only restores punches) leaves `payment_status` unchanged.

Every cancellation, voluntary or system, also voids the session's equipment: any linked rental agreement still `OPEN` transitions to `VOIDED` with no charges, and each voided agreement releases its rental item from `RENTED` back to `AVAILABLE`.

If nobody checks in, the epoch sweep does the punishing: a session still `BOOKED` once the clock passes fifteen minutes after `start_at` becomes `NO_SHOW`. All quoted fees are forfeited — wallet participants keep their debit and punch participants lose their punch, every participant becoming `FORFEITED` — and the same rental-void cascade runs.

### 3.5. Punch Cards

A punch card is a prepaid pack of lane visits purchased by a `Member` (or an `Admin` on the member's behalf; a `Member` caller may purchase only for themselves — the path member must equal the caller's identity, else `ERR_UNAUTHORIZED`) through the member-scoped purchase capability, naming a `punches_total` of exactly 5 or exactly 10 (any other pack size is `ERR_INVALID_REQUEST`). The `price_paid_cents` is the pack size times 1000 cents per punch, times one minus the owner's tier discount at purchase time, rounded half up; the purchase debits that price from the owner's wallet (`ERR_INSUFFICIENT_FUNDS` if short). The card starts `ACTIVE` with `punches_used` 0, owned by the path member recorded as its `member_id`; `punches_remaining` is always the pack size minus `punches_used`. Cards may be listed per member or read individually.

Consumption happens at participant add time (§3.3): each punch-paid participant increments `punches_used` by one. The card exhausts at the exact boundary — when a consume makes `punches_used` equal to `punches_total`, the card flips from `ACTIVE` to its terminal `EXHAUSTED`. Restoration runs the boundary in reverse: a cancellation restore that brings `punches_used` back below `punches_total` flips an `EXHAUSTED` card back to `ACTIVE`.

### 3.6. Equipment Rental, Fitting, and Settlement

The rental fleet is managed as items: a `ShopClerk` or `Admin` creates a rental item with a `name`, an `item_type` of `BOW`, `ARROW_SET`, `ARMGUARD`, or `RELEASE`, and a non-negative `daily_rate_cents`; items start `AVAILABLE` and may be listed with an optional `status` filter.

Renting equipment — a `Member` or `RangeOfficer` action — names the `rental_item_id`, the renting `member_id` (a `Member` caller may rent only for themselves — `member_id` must equal the caller's identity, else `ERR_UNAUTHORIZED`), the fitting measurements, a `due_date` as an ISO date, and optionally a `session_id` linking the rental to a booked session (a supplied `session_id` must reference an existing session, else `ERR_SESSION_NOT_FOUND`; that link is what makes the agreement a cascade target when the session is cancelled or no-showed). The renter must be an active member holding an active waiver per §2.9, and the item must be `AVAILABLE` (`ERR_RENTAL_ITEM_UNAVAILABLE` otherwise). The fitting contract is precise: `draw_length_in` is a number from 14.0 to 32.0 inclusive in 0.5-inch steps, and `draw_weight_lb` is an integer from 10 to 70 inclusive; out-of-range or off-step values are `ERR_INVALID_REQUEST`. Creation stamps `checked_out_at` from the logical clock, opens the agreement in `OPEN`, and moves the item from `AVAILABLE` to `RENTED`. Agreements may be listed with `member_id`, `rental_item_id`, `session_id`, and `status` filters.

Return is a `RangeOfficer` action on an `OPEN` agreement (`ERR_RENTAL_INVALID_STATE` from any other state). It records a `returned_condition` of `GOOD` or `DAMAGED` and a `damage_fee_cents` that must be exactly 0 when the condition is `GOOD` and strictly greater than 0 when `DAMAGED` (mismatches are `ERR_INVALID_REQUEST`); the fee defaults to 0. Returning stamps `returned_at`, moves the agreement to `RETURNED`, and releases the item back to `AVAILABLE`.

Settlement, also `RangeOfficer`-only, requires `RETURNED` and computes `settlement_total_cents`: the billable days are the whole UTC calendar days between the checkout date and the return date, with a minimum of one day; the rental charge is those days times the item's `daily_rate_cents`; the late days are the whole UTC calendar days by which the return date passed `due_date`, floored at zero (day-granularity — a return later on the due date is not late); the late fee is 500 cents per late day; and the settlement total is rental charge plus late fee plus `damage_fee_cents`. Settlement then debits the total from the renter's wallet, requiring `wallet_balance_cents` to cover it (`ERR_INSUFFICIENT_FUNDS`), and the agreement reaches its terminal `SETTLED`. An agreement that is instead voided by cascade — its linked session cancelled or no-showed, or its renter suspended — moves from `OPEN` to terminal `VOIDED`, releases its item, and incurs no charges.

### 3.7. Lessons and the Coach Negotiation Cycle

Coaches are rostered by an `Admin` with a `full_name` and a non-empty `disciplines` array whose items are drawn from `RECURVE`, `COMPOUND`, and `TRADITIONAL`; a coach starts `ACTIVE`. An `Admin` may deactivate a coach (`ACTIVE` to `INACTIVE`) and later activate them again — either transition attempted from the wrong state is `ERR_INVALID_REQUEST`; while `INACTIVE`, a coach may not confirm, counter, or have lessons accepted — attempts are rejected with `ERR_COACH_INACTIVE`. Anyone may list coaches.

A `Member` requests a lesson by naming a `coach_id`, a `discipline`, a `proposed_start_at`, and optionally a `duration_minutes` that defaults to 60 and must lie between 30 and 120 inclusive. The requesting member (recorded from the caller's identity as the lesson's `member_id`) must be active and waivered, and the `discipline` must appear in the coach's `disciplines` (`ERR_DISCIPLINE_MISMATCH` otherwise). The `fee_cents` is computed at request time: 6000 cents per hour times the duration in hours — `duration_minutes` divided by 60 rounded up to a whole number — times one minus the member's tier discount, the product rounded half up. The lesson opens in `REQUESTED`. Lessons may be listed with `coach_id`, `member_id`, and `status` filters.

From `REQUESTED`, the lesson negotiates. The assigned coach may counter with a new `proposed_start_at`, moving the lesson to `COUNTERED`; the student may then counter back with their own `proposed_start_at`, returning it to `REQUESTED`; each counter overwrites `proposed_start_at`, and only the lesson's own coach (identity equal to `coach_id`) or its own student may play their side (`ERR_UNAUTHORIZED` otherwise, `ERR_COACH_INACTIVE` while the coach is inactive). Two paths end the negotiation in `CONFIRMED`: the assigned coach confirms a `REQUESTED` lesson, or the student accepts a `COUNTERED` lesson at its currently proposed time. Both paths enforce the full gate set — the coach must be `ACTIVE`, the schedule must be clear under the buffered-interval rule below, and the member's `wallet_balance_cents` must cover `fee_cents` (`ERR_INSUFFICIENT_FUNDS`) — and both debit `fee_cents` from the member's wallet on success. Any transition attempted from a state that does not allow it is rejected with `ERR_LESSON_NOT_ACTIONABLE`.

The buffered-interval rule protects a coach's calendar: confirming or accepting a lesson is rejected with `ERR_COACH_OVERLAP` if it would leave less than fifteen minutes of gap, on either side, to another `CONFIRMED` lesson of the same coach.

A `CONFIRMED` lesson is completed by its coach once the logical clock has reached `proposed_start_at` (completing earlier is `ERR_LESSON_NOT_ACTIONABLE`), moving to terminal `COMPLETED`. Either the member or the coach may cancel from `REQUESTED`, `COUNTERED`, or `CONFIRMED`; cancelling a `CONFIRMED` lesson refunds `fee_cents` in full to the member's wallet if and only if the current logical clock is still before `proposed_start_at` — at or after the lesson time, the cancel stands but the refund is zero.

### 3.8. Leagues, Entries, Scorecards, and Standings

A `LeagueDirector` creates a league with a `name`, a non-negative `entry_fee_cents`, and a `max_entries` of at least 1; the league opens in `OPEN` with `gross_entry_fees_cents`, `range_share_cents`, and `prize_pool_cents` all 0, and anyone may read it including those computed pool fields.

Entry is a `Member` action on an `OPEN` league (`ERR_LEAGUE_NOT_OPEN` otherwise): the entrant — recorded from the caller's identity, with the league recorded as the entry's `league_id` — must be active and waivered, may hold only one entry per league (`ERR_DUPLICATE_LEAGUE_ENTRY`), counting entries of any status so that even a `CANCELLED` entry blocks a fresh entry, and the league must have fewer than `max_entries` `CONFIRMED` entries (`ERR_LEAGUE_FULL`). Entry debits `entry_fee_cents` from the entrant's wallet (`ERR_INSUFFICIENT_FUNDS`), captures it as the entry's `fee_paid_cents`, and lands the entry directly in `CONFIRMED` with `refund_status` `NONE`. Entries may be listed with `league_id`, `member_id`, and `status` filters.

The money pool recomputes on every entry creation and on the cancel cascade, with a pinned evaluation order that breaks the apparent circularity between share and pool: first `gross_entry_fees_cents` is the sum of `fee_paid_cents` over entries in `CONFIRMED` only (cancelled entries are excluded); then `range_share_cents` is 15% of the **gross**, rounded half up — never a percentage of the pool; finally `prize_pool_cents` is the gross minus the range share.

Closing entries — a `LeagueDirector` action requiring `OPEN` and at least one `CONFIRMED` entry (`ERR_LEAGUE_NOT_OPEN` otherwise) — moves the league to `CLOSED` and opens the scoring phase: scorecards may now be submitted. A member submits a scorecard for their own `CONFIRMED` entry of a `CLOSED` league (any other league or entry state is `ERR_LEAGUE_NOT_OPEN`) by supplying `ends` and `x_hits`. The shape is exact: `ends` is an array of exactly 10 ends, each end an array of exactly 3 arrow scores, each arrow an integer from 0 to 10, and `x_hits` — the inner-ten count used as the scratch tie-break — an integer from 0 to 30; any deviation is `ERR_INVALID_REQUEST`. The server computes `total_points` as the sum of all arrow scores, ignoring any client-sent total, and the card lands in `SUBMITTED`; the card's parent is recorded as `league_entry_id`. An entry's scorecards may be listed.

A `LeagueDirector` then adjudicates: verify moves a `SUBMITTED` card to `VERIFIED` — from any other non-`LOCKED` state it is `ERR_SCORECARD_NOT_EDITABLE`, and it is gated cross-entity on the parent entry still being `CONFIRMED` (`ERR_LEAGUE_NOT_OPEN` otherwise) — dispute returns a `VERIFIED` card to `DISPUTED` for the member to correct (from any other non-`LOCKED` state, `ERR_SCORECARD_NOT_EDITABLE`), and lock moves a `VERIFIED` card to terminal `LOCKED` (from any other non-`LOCKED` state, `ERR_SCORECARD_NOT_EDITABLE`). Verify, dispute, or lock attempted on a `LOCKED` card is rejected with `ERR_SCORECARD_LOCKED`. Correction is the member's OCC-guarded edit of §2.7: from `SUBMITTED` it is a self-transition edit before verification, and from `DISPUTED` it returns the card to `SUBMITTED`; both require the acting member to own the parent entry and recompute `total_points` from the new `ends` while incrementing the card's `version` by one. Editing a card in `VERIFIED` or `LOCKED` is rejected with `ERR_SCORECARD_NOT_EDITABLE`.

Locking has a league-level side effect: when every submitted scorecard of every `CONFIRMED` entry is `LOCKED` and no `CONFIRMED` entry is left without at least one scorecard, the league auto-transitions from `CLOSED` to terminal `COMPLETED`.

A `LeagueDirector` may instead cancel the league — from `OPEN` unconditionally, or from `CLOSED` only while no scorecard of any entry is `LOCKED` (otherwise `ERR_LEAGUE_NOT_OPEN`); from any other state, such as `COMPLETED` or `CANCELLED`, the cancel is likewise `ERR_LEAGUE_NOT_OPEN`. Cancellation fires a two-hop cascade: every `CONFIRMED` entry transitions to terminal `CANCELLED`, and each cancelled entry credits its `fee_paid_cents` back to its member's wallet and sets `refund_status` to `REFUNDED`; with no `CONFIRMED` entries remaining, the pool recompute leaves all three pool fields at 0.

Standings are computed on demand over the `LOCKED` scorecards of `CONFIRMED` entries only — entries with no locked cards are excluded, and the computation is available in any league status — in two variants selected by the `variant` query parameter (any other value is `ERR_INVALID_REQUEST`); the response carries the echoed `variant` and the ranked `rows`. Each entry's average is the mean of its locked cards' `total_points`, rounded half up, and its handicap index is 1.2 times the amount by which that average falls short of the 300-point par — floored at zero — rounded half up. The `SCRATCH` variant (the default) ranks by the sum of locked `total_points` descending, breaking ties by the sum of `x_hits` descending, then by the earliest first-locked-card `created_at` ascending. The `HANDICAP` variant adds the handicap index to the points sum and ranks that adjusted figure descending, breaking ties by the raw points sum descending, then `x_hits` descending, then the same earliest-lock tiebreak; the handicap can therefore reorder standings relative to `SCRATCH` for identical scorecards. Each row carries `league_entry_id`, `member_id`, `total_points`, `x_hits`, `handicap_index`, `adjusted_points`, and a 1-based `rank` assigned after sorting — the two computed fields appear in `SCRATCH` rows as well.

### 3.9. Pro-Shop Sales and the Repair Bench

The shop's catalog is built by a `ShopClerk` or `Admin`: each product has a `name`, a unique `sku`, a non-negative `unit_price_cents`, and an `initial_stock` that seeds `stock_quantity` at creation. Anyone may list products. `stock_quantity` thereafter tracks on-hand minus sold minus repair-reserved and is never allowed to go negative.

Ringing up a sale is `ShopClerk`-only. The request carries `items` — a non-empty array of line items, each naming a `product_id` referencing a catalog product, a `qty` of at least 1, and an optional `line_discount_pct` from 0 to 0.9 defaulting to 0 — and optionally a `member_id` for a member purchase (a supplied `member_id` must reference an existing member, else `ERR_MEMBER_NOT_FOUND`); note that membership tier discounts do **not** apply to pro-shop sales. The total is computed with a pinned rounding order: first each line's gross is the quantity times the product's current `unit_price_cents` times one minus the line discount, rounded half up, collected in input order as `line_gross_cents`; then `subtotal_cents` is the sum of those already-rounded line grosses — per-line rounding first, summation second; then `volume_discount_cents` is 10% of the subtotal rounded half up, but only when the subtotal reaches 10000 cents, otherwise 0; then `tax_cents` is 8.25% of the taxable base — subtotal minus volume discount — rounded half up; and `total_cents` is the taxable base plus the tax. Stock is decremented per line by its quantity, and if any single line exceeds the product's on-hand `stock_quantity` the **whole** sale is rejected with `ERR_INSUFFICIENT_STOCK` — there are no partial sales. Sales may be listed with a `member_id` filter or read back.

Repair work begins with a `ShopClerk` intake naming the equipment owner's `member_id` (which must reference an existing member, else `ERR_MEMBER_NOT_FOUND`) and a free-text `item_description`; the order opens in `INTAKE`, and orders may be listed with `member_id` and `status` filters. Quoting — also `ShopClerk` — is valid from `INTAKE`, or again from `QUOTED` to supersede a prior quote, and is the OCC-guarded write of §2.7 requiring `expected_repair_order_version`; quoting from any other state is `ERR_REPAIR_INVALID_STATE`, and a re-quote from `QUOTED` first releases the previously reserved parts back to each product's `stock_quantity` before validating and reserving the new set. The quote names `parts` — each entry a `product_id` with a `qty` of at least 1, recorded on the order as `parts_reserved` — plus `labor_minutes` strictly greater than 0 and `promised_hours` until completion. `parts_total_cents` is the sum of each part's quantity times the product's `unit_price_cents` at quote time. Labor is billed in 30-minute blocks at 1500 cents per block: `labor_minutes` divided by 30 rounded up gives the block count; the block count times 1500 is discounted by the owner's membership tier with round half up; and when `promised_hours` is under 48, a rush fee of 25% of the discounted labor, rounded half up, is added on top — at 48 hours or more there is no rush fee. The result is `labor_total_cents`, and `quote_total_cents` is parts plus labor. Quoting reserves the parts — decrementing each product's `stock_quantity` by the reserved quantity (`ERR_INSUFFICIENT_STOCK` if any part is short), with the stock held until the order is declined or picked up — and increments the order's `version` by one. The order moves to `QUOTED`.

The equipment owner then decides: approving moves `QUOTED` to `IN_REPAIR` with the parts remaining reserved, while declining moves `QUOTED` to `DECLINED` and releases the reserved stock back to each product's `stock_quantity`; both are member actions on their own order, and both reject from any other state with `ERR_REPAIR_INVALID_STATE`. A `ShopClerk` marks an `IN_REPAIR` order complete, moving it to `READY`. Pickup — again `ShopClerk` — closes the order from either `READY` or `DECLINED` into terminal `PICKED_UP`; picking up a completed repair debits `quote_total_cents` from the owner's wallet (`ERR_INSUFFICIENT_FUNDS` if short), while a declined pickup collects nothing.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource returns HTTP 201 with the created resource — recording a safety strike and posting a wallet adjustment likewise return 201 even though they create no resource; all other modifications, state transitions, reads, and computed views return HTTP 200. Authentication, validation ordering, and error envelopes follow §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; runs the no-show and waiver-expiry sweep | Admin |
| POST | /members | Register a member; minors require an adult guardian | Anonymous |
| GET | /members | List members with filters | Member, RangeOfficer, Admin |
| GET | /members/{id} | Read a member | Member, RangeOfficer, Admin |
| POST | /members/{id}/safety-strikes | Record a safety strike; the third strike auto-suspends with cascade | RangeOfficer |
| POST | /members/{id}/reinstate | Reinstate a suspended member; resets strikes | RangeOfficer |
| POST | /members/{id}/wallet/adjustments | Signed wallet adjustment (top-up or debit) | Admin |
| POST | /members/{id}/waivers | Sign a waiver (self for adults, guardian for minors) | Member |
| GET | /members/{id}/waivers | List a member's waivers | Member, RangeOfficer, Admin |
| POST | /waivers/{id}/revoke | Revoke a waiver | Admin |
| POST | /lanes | Create a lane | Admin |
| GET | /lanes | List lanes | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| GET | /lanes/{id} | Read a lane | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| GET | /lanes/{id}/sessions | List sessions booked on a lane | Member, RangeOfficer, Admin |
| POST | /range-sessions | Book a lane session (walk-in or reservation) | Member, RangeOfficer |
| GET | /range-sessions | List sessions with filters | Member, RangeOfficer, Admin |
| GET | /range-sessions/{id} | Read a session | Member, RangeOfficer, Admin |
| POST | /range-sessions/{id}/participants | Add a participant; quotes fee and debits wallet or consumes a punch | Member, RangeOfficer |
| GET | /session-participants | List participants with filters | Member, RangeOfficer, Admin |
| GET | /session-participants/{id} | Read a participant | Member, RangeOfficer, Admin |
| POST | /range-sessions/{id}/check-in | Check in a booked session within its window | RangeOfficer |
| POST | /range-sessions/{id}/close | Close a checked-in session; final fees and wallet reconciliation | RangeOfficer |
| POST | /range-sessions/{id}/cancel | Voluntarily cancel a booked session; tiered refund | Member, RangeOfficer |
| POST | /members/{id}/punch-cards | Purchase a punch card | Member, Admin |
| GET | /members/{id}/punch-cards | List a member's punch cards | Member, RangeOfficer, Admin |
| GET | /punch-cards/{id} | Read a punch card | Member, RangeOfficer, Admin |
| POST | /rental-items | Create a rental item | ShopClerk, Admin |
| GET | /rental-items | List rental items | Member, RangeOfficer, ShopClerk, Admin |
| POST | /rental-agreements | Rent equipment with fitting specs | Member, RangeOfficer |
| GET | /rental-agreements | List rental agreements with filters | Member, RangeOfficer, ShopClerk, Admin |
| GET | /rental-agreements/{id} | Read a rental agreement | Member, RangeOfficer, ShopClerk, Admin |
| POST | /rental-agreements/{id}/return | Return the item with condition assessment | RangeOfficer |
| POST | /rental-agreements/{id}/settle | Settle a returned agreement; debits renter wallet | RangeOfficer |
| POST | /coaches | Create a coach | Admin |
| GET | /coaches | List coaches | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| POST | /coaches/{id}/deactivate | Deactivate a coach | Admin |
| POST | /coaches/{id}/activate | Reactivate a coach | Admin |
| POST | /lessons | Request a lesson | Member |
| GET | /lessons | List lessons with filters | Member, Coach, Admin |
| GET | /lessons/{id} | Read a lesson | Member, Coach, Admin |
| POST | /lessons/{id}/confirm | Coach confirms a requested lesson; debits fee | Coach |
| POST | /lessons/{id}/counter | Coach or member counters with a new proposed time | Member, Coach |
| POST | /lessons/{id}/accept | Member accepts a countered lesson; debits fee | Member |
| POST | /lessons/{id}/cancel | Cancel a lesson; conditional full refund from confirmed | Member, Coach |
| POST | /lessons/{id}/complete | Coach completes a confirmed lesson | Coach |
| POST | /leagues | Create a league | LeagueDirector |
| GET | /leagues/{id} | Read a league including pool fields | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| POST | /leagues/{id}/entries | Enter a league; debits entry fee | Member |
| GET | /league-entries | List league entries with filters | Member, LeagueDirector, Admin |
| GET | /league-entries/{id} | Read a league entry | Member, LeagueDirector, Admin |
| POST | /leagues/{id}/close | Close entries and open scoring | LeagueDirector |
| POST | /leagues/{id}/cancel | Cancel a league; cascades entry refunds | LeagueDirector |
| GET | /leagues/{id}/standings | Computed standings, scratch or handicap | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| POST | /league-entries/{id}/scorecards | Submit a scorecard for a confirmed entry | Member |
| GET | /league-entries/{id}/scorecards | List an entry's scorecards | Member, LeagueDirector, Admin |
| PUT | /scorecards/{id} | Edit or correct a scorecard (OCC-guarded) | Member |
| POST | /scorecards/{id}/verify | Verify a submitted scorecard | LeagueDirector |
| POST | /scorecards/{id}/dispute | Dispute a verified scorecard | LeagueDirector |
| POST | /scorecards/{id}/lock | Lock a verified scorecard; may auto-complete the league | LeagueDirector |
| POST | /shop-products | Create a pro-shop product | ShopClerk, Admin |
| GET | /shop-products | List products | Anonymous, Member, Coach, RangeOfficer, ShopClerk, LeagueDirector, Admin |
| POST | /sales | Ring up a pro-shop sale; all-or-nothing stock | ShopClerk |
| GET | /sales | List sales with filters | ShopClerk, Admin |
| GET | /sales/{id} | Read a sale | ShopClerk, Admin |
| POST | /repair-orders | Intake a repair order | ShopClerk |
| GET | /repair-orders | List repair orders with filters | ShopClerk, Member, Admin |
| GET | /repair-orders/{id} | Read a repair order | ShopClerk, Member, Admin |
| POST | /repair-orders/{id}/quote | Quote or re-quote a repair (OCC-guarded); reserves parts | ShopClerk |
| POST | /repair-orders/{id}/approve | Owner approves a quoted repair | Member |
| POST | /repair-orders/{id}/decline | Owner declines a quoted repair; releases parts | Member |
| POST | /repair-orders/{id}/complete | Mark an in-repair order ready for pickup | ShopClerk |
| POST | /repair-orders/{id}/pickup | Pick up from ready or declined; debits repair total | ShopClerk |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_WAIVER_NOT_FOUND | 404 |
| ERR_LANE_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_PARTICIPANT_NOT_FOUND | 404 |
| ERR_PUNCH_CARD_NOT_FOUND | 404 |
| ERR_RENTAL_ITEM_NOT_FOUND | 404 |
| ERR_RENTAL_AGREEMENT_NOT_FOUND | 404 |
| ERR_COACH_NOT_FOUND | 404 |
| ERR_LESSON_NOT_FOUND | 404 |
| ERR_LEAGUE_NOT_FOUND | 404 |
| ERR_LEAGUE_ENTRY_NOT_FOUND | 404 |
| ERR_SCORECARD_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_REPAIR_ORDER_NOT_FOUND | 404 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_MEMBER_NOT_SUSPENDED | 409 |
| ERR_SESSION_NOT_BOOKED | 409 |
| ERR_SESSION_ALREADY_CLOSED | 409 |
| ERR_LESSON_NOT_ACTIONABLE | 409 |
| ERR_SCORECARD_NOT_EDITABLE | 409 |
| ERR_SCORECARD_LOCKED | 409 |
| ERR_REPAIR_INVALID_STATE | 409 |
| ERR_RENTAL_INVALID_STATE | 409 |
| ERR_WAIVER_NOT_REVOKABLE | 409 |
| ERR_LEAGUE_NOT_OPEN | 409 |
| ERR_COACH_INACTIVE | 409 |
| ERR_WAIVER_MISSING | 422 |
| ERR_WAIVER_EXPIRED | 422 |
| ERR_MINOR_GUARDIAN_REQUIRED | 422 |
| ERR_GUARDIAN_NOT_ADULT | 422 |
| ERR_LANE_OVERLAP | 409 |
| ERR_LANE_CAPACITY_EXCEEDED | 422 |
| ERR_COACH_OVERLAP | 409 |
| ERR_DISCIPLINE_MISMATCH | 422 |
| ERR_DUPLICATE_LEAGUE_ENTRY | 409 |
| ERR_LEAGUE_FULL | 422 |
| ERR_BOOKING_WINDOW_VIOLATION | 422 |
| ERR_RENTAL_ITEM_UNAVAILABLE | 422 |
| ERR_INSUFFICIENT_STOCK | 422 |
| ERR_PUNCH_CARD_EXHAUSTED | 422 |
| ERR_INSUFFICIENT_FUNDS | 402 |
| ERR_STALE_VERSION | 412 |

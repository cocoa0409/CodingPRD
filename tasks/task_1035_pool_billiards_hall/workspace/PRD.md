# Pool & Billiards Hall API — Product Requirements Document

## 1. Introduction

This document specifies the back-office API for a combined pool-and-billiards hall and table-retail business. A single venue juggles a surprising number of moving parts: hourly table time and recurring memberships, league and tournament play with skill-based handicapping, a food-and-beverage service running on open tables, a pro-shop selling cues and cases alongside cue-retipping and table-recovering repair work, and privately booked events that block out several tables at once. Historically these were tracked in disconnected spreadsheets and point-of-sale terminals, so a member's house-account balance, their outstanding reservations, and the state of a table under maintenance were never in agreement.

The system described here replaces those silos with one authoritative service. Every member carries a prepaid house wallet that is debited by table charges, food tabs, tournament entry fees, repair pickups, and event deposits, and credited back by refunds and operator adjustments. Reservations, sessions, tournaments, repairs, and events each move through their own lifecycle, and several of those lifecycles are wired together: retiring a table must clear the reservations that depended on it, a member's third no-show in a billing cycle must suspend them and drop their bookings, and cancelling an event must unwind the reservations, sessions, and deposit it created. Because the business runs against wall-clock deadlines — grace periods, check-in windows, peak-hour pricing — the service is driven by an explicit logical clock rather than real time, so that operators and the automated test harness can reproduce time-sensitive behaviour deterministically.

The remainder of this document defines the global contracts every endpoint obeys (Section 2), the domain workflows and their calculations (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than open registration and anonymous reads must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. If either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the role is not permitted to perform the operation — or a member attempts to act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are four named roles plus an implicit anonymous caller:

- **`Member`** — a billiards-hall member acting on their own bookings, entries, tabs, repairs, and events. This role is entity-backed: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record. Ownership checks on any resource that references a member compare that resource's member foreign key (for example a reservation's `member_id`, a repair order's `member_id`, an event's `host_member_id`, or a member sub-resource's own `id`) against `X-User-ID`. A member may only read and mutate resources that resolve to their own `id`.
- **`FrontDesk`** — the front-of-house operator who confirms and checks in reservations, marks no-shows, opens and closes table sessions, submits and voids food tabs, checks in tournament entrants, and processes repair pickups. This role is opaque: when `X-User-Role` is `FrontDesk`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- **`Manager`** — the operator with configuration and administration authority over plans, tables, tournaments, and events, and the only role permitted to advance the logical clock. This role is opaque: `X-User-ID` is an operator identifier the server does not tie to any persisted entity.
- **`ProShopStaff`** — the pro-shop operator who manages products and inventory and services repair orders. This role is opaque as well: `X-User-ID` is an operator identifier not compared to any entity's `id`.

The implicit **anonymous** caller (no authenticated role) may register a new member and perform reads that are explicitly marked as public. Registration is also available to a `Manager`.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and may be no smaller than 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_PAGINATION` (HTTP 422).

Lists are returned in ascending order of `created_at` — that is, oldest first — unless a workflow explicitly states another order. The `meta` block of a list response reports the effective `limit` and `offset`, the `total_count` of records matching the filter before pagination is applied, and `has_more`, a boolean that is true when records beyond the current page remain.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable business records, so each additionally carries an `updated_at` timestamp (same format as `created_at`) and an integer `version`. The `version` begins at 1 when the resource is created and increases by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant on each such mutation. Whenever a cascade (described throughout Section 3) mutates a secondary resource, that resource's own `version` is incremented and its `updated_at` refreshed just as if it had been changed directly.

### 2.5. The Logical Clock and Temporal Evaluation

The service does not read the host machine's wall clock. Instead it maintains a single logical clock whose value before any adjustment is `2026-07-01T00:00:00Z`. A `Manager` may set this clock to a supplied instant through an administrative test-driving capability that accepts a `to_iso8601` value; every subsequent temporal comparison — grace periods, check-in windows, reservation horizons, peak-hour pricing, and membership expiry — is evaluated against the current logical-clock value.

Membership expiry is evaluated lazily. A member is not expired by a background job; instead, whenever a member record is read or written, the server first checks whether the current logical time has reached or passed that member's `membership_expires_at`, and if so applies the `ACTIVE → EXPIRED` transition (with its deferred-downgrade side effect described in Section 3.1) before returning.

### 2.6. Monetary Precision, Rounding, and the House Wallet

All monetary amounts are integer cents. Wherever a calculation must reduce a fractional cent to a whole cent, the system rounds half up — a value whose fractional part is exactly one half rounds away from zero to the next whole cent. Each calculation in Section 3 states precisely where rounding is applied; the guiding rule is that rounding happens once at the defined point (for the table charge, once at the very end of each variant; for the food tab, once per line item before summing).

Every member holds a house-account balance, `wallet_credit_cents`, denominated in whole cents. It is debited by table-session final charges, submitted food tabs, tournament entry fees, repair pickups, event deposits, membership renewals, and pro-shop sales charged to the member; it is credited by refunds, compensations, and operator adjustments. The wallet may never go negative: any debit that would drive `wallet_credit_cents` below zero is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402) and the balance is left unchanged. Operator adjustments may themselves be negative, but the same floor applies — an adjustment that would take the balance below zero is refused.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both compare a client-supplied expected version against the target's current `version`.

A plan change against a member must carry `expected_member_version` holding the `version` of that `Member` the client last observed. Because a new plan change legitimately supersedes any prior pending change — it overwrites the member's `pending_plan_id` or `plan_id` — a client acting on a stale view must not be allowed to silently clobber an intervening change. If `expected_member_version` does not equal the member's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

A reservation reschedule must carry `expected_reservation_version` holding the `version` of that `Reservation` the client last observed. A reschedule moves the reservation to a new window and supersedes its prior one; if another writer has advanced the reservation's `version` since the client read it, the reschedule is acting on a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.8. Validation Ordering and Error Precedence

When several checks could fail on one request, they are evaluated in a fixed order so the returned error is deterministic. The order is:

1. **Authentication** — headers present and well-formed, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted and, for an entity-backed member, is acting only on its own resources, else `ERR_FORBIDDEN` (403).
3. **Existence** — every `id` named in the path or body resolves to a live entity, validated left to right along the path, else `ERR_NOT_FOUND` (404).
4. **State** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
5. **Concurrency** — the supplied expected version matches the parent's current `version`, else `ERR_STALE_VERSION` (412).
6. **Table availability** — a table required by a confirm, check-in, reschedule, walk-in session open, or event book must be `ACTIVE` (not `MAINTENANCE` or `RETIRED`), else `ERR_TABLE_NOT_ACTIVE` (409).
7. **Dependent state** — a required related entity is in the correct state (a food tab's session `OPEN`, a tournament `SEEDED` for entry check-in, an event's payment reached at least deposit-paid for confirm), else `ERR_DEPENDENT_STATE` (409).
8. **Table time conflict** — a reservation window does not conflict with another booking on the same table within the turnover buffer, else `ERR_TABLE_TIME_CONFLICT` (409).
9. **Event capacity** — the event window has enough free `ACTIVE` tables, else `ERR_EVENT_CAPACITY_UNAVAILABLE` (409).
10. **Party capacity** — `party_size` does not exceed the table's `seat_capacity`, else `ERR_CAPACITY_EXCEEDED` (422).
11. **Window validity** — the reservation or event window is well-formed and within the allowed horizon, else `ERR_INVALID_WINDOW` (422).
12. **Domain precondition** — tournament seeding meets the minimum entry count and product sale has enough stock, else `ERR_PRECONDITION_NOT_MET` (409).
13. **Sufficient funds** — a wallet debit would not drive the balance below zero, else `ERR_INSUFFICIENT_FUNDS` (402).
14. **Body validity** — field types, enums, ranges, and required fields, else `ERR_VALIDATION` (422).
15. **Member standing** — the acting or owning member is not `SUSPENDED` when creating a reservation, tournament entry, or event, else `ERR_MEMBER_SUSPENDED` (409).

Uniqueness is enforced independently: a duplicate `tier` across active plans, `table_number`, member `email`, or product `sku` is rejected with `ERR_DUPLICATE` (409).

### 2.9. Cascading State Effects and Consistency

Several operations mutate more than one entity in a single atomic step. Where this happens, every secondary mutation described in Section 3 must be applied, and each affected resource's `version` and `updated_at` are advanced as in Section 2.4. The system is immediately consistent — there is no deferred settlement. The principal cascades are the no-show chain (a no-show strikes the member, a third strike suspends them, and suspension cancels their remaining bookings), the table-removal chain (maintenance or retirement cancels the table's future reservations, which for event-created reservations can in turn cancel the event), the event-cancellation chain (cancelling an event cancels its reservations, voids their open sessions, and refunds the deposit), and the tournament-cancellation chain (cancelling a tournament withdraws its captured entries, refunds their fees, and restores its slots). Each is specified in full in the relevant Section 3 subsection.

## 3. Business Logic & Workflows

### 3.1. Membership Plans and the Member Lifecycle

A `Manager` defines the venue's membership tiers as plans. Each plan names a `tier` — one of `BRONZE`, `SILVER`, or `GOLD`, unique across active plans — a `monthly_fee_cents` charged at renewal (at least zero), and a `table_discount_pct`, the fraction of a final table charge waived for members on that plan (between 0.0 and 0.5 inclusive). Two further attributes tune member privileges: `included_hours_per_month`, the free table-hours advertised for the tier (informational only in this system and not auto-deducted, defaulting to 0), and `reservation_horizon_days`, how many days ahead a member on the tier may reserve a table (defaulting to 14). Plans are readable by any staff role and by members.

Anyone may register a `Member` by supplying an `email` (unique login), a `full_name`, the `plan_id` of the chosen plan, and optionally a `handicap_rating` — a skill rating from 1 to 9 used later for tournament seeding, defaulting to 5. On registration the member's `membership_status` is `ACTIVE`, and `membership_expires_at` is set to the registration instant plus thirty days. A new member's computed fields start at their defaults: `pending_plan_id` is null, `wallet_credit_cents` is zero, and `no_show_strikes` is zero.

A member moves through three states — `ACTIVE`, `EXPIRED`, and `SUSPENDED`. Expiry is evaluated lazily on any read or write, as described in Section 2.5: when the current logical time reaches or passes `membership_expires_at`, an `ACTIVE` member transitions to `EXPIRED`. Expiry carries one deferred side effect — if the member has a `pending_plan_id` (a downgrade queued earlier), that pending plan becomes the member's `plan_id` and `pending_plan_id` is cleared. Expiry alone does not cancel a member's bookings; only suspension does.

**Renewal.** A member (or a `FrontDesk` operator on their behalf) may renew at any time, and renewal is what returns an `EXPIRED` or `SUSPENDED` member to `ACTIVE`. Renewal charges the member's current plan `monthly_fee_cents` against the wallet and always resets `no_show_strikes` to zero. Renewal has two calculation variants that differ only in how the new expiry is anchored. When the member was `ACTIVE` or `SUSPENDED`, the auto-renew variant applies: the new `membership_expires_at` is the *prior* `membership_expires_at` plus thirty days, extending the existing cycle without re-anchoring it to now. When the member was `EXPIRED`, the lapsed-prorated variant applies: the new `membership_expires_at` is the current logical time plus thirty days, starting a fresh cycle. A `SUSPENDED → ACTIVE` renewal and an `EXPIRED → ACTIVE` renewal both clear the strikes and set the expiry per their respective variant; an `ACTIVE → ACTIVE` renewal simply extends the cycle. Should the renewal charge exceed the wallet balance, it is refused with `ERR_INSUFFICIENT_FUNDS`.

**Plan change.** A member may change their own plan. An upgrade takes effect immediately — the member's `plan_id` becomes the `target_plan_id` at once — whereas a downgrade is deferred: the `target_plan_id` is recorded as `pending_plan_id` and only becomes the active `plan_id` at the next expiry. Every plan change increments the member's `version` by one and must carry `expected_member_version` matching the member's current `version`, on pain of the stale-version rejection described in Section 2.7. (Whether a target is an upgrade or a downgrade is a business classification made against the member's current tier; both paths run through the same OCC-guarded operation.)

**Operator wallet adjustments.** A `Manager` or `FrontDesk` operator may credit or debit a member's wallet directly by supplying an `amount_cents` (which may be negative) and an optional `reason`. The amount is added to `wallet_credit_cents`; a negative adjustment that would take the balance below zero is refused under the same zero-floor rule as any other debit.

**The no-show and suspension chain.** No-show handling originates in the reservation workflow (Section 3.2) but its consequences land here. Each no-show adds one to the member's `no_show_strikes`. When `no_show_strikes` reaches three, the member transitions `ACTIVE → SUSPENDED`, and that suspension in turn cancels every one of the member's reservations still in `PENDING` or `CONFIRMED`. A `SUSPENDED` member is barred from creating new reservations, tournament entries, or events (`ERR_MEMBER_SUSPENDED`); they regain standing only by renewing.

### 3.2. Tables, Reservations, and the Turnover Discipline

A `Manager` provisions the hall's tables. Each `PoolTable` has a unique `table_number` (at least 1), a `table_type` of `POOL_7FT`, `POOL_9FT`, `SNOOKER`, or `BILLIARDS`, a `seat_capacity` (at least 1) capping the party a reservation may bring, and an `hourly_rate_cents` (at least zero) that is the off-peak base rate; peak hours apply a multiplier described in Section 3.3. A table's `status` begins `ACTIVE` and cycles between `ACTIVE` and `MAINTENANCE`, or ends at the terminal `RETIRED`.

Putting a table into `MAINTENANCE` (`ACTIVE → MAINTENANCE`) or retiring it (`ACTIVE → RETIRED`, or `MAINTENANCE → RETIRED`) is a `Manager` action and requires that no table session for that table is currently `OPEN`. Both maintenance and retirement carry the same cascade: every future reservation on that table still in `PENDING` or `CONFIRMED` (whose `start_at` is at or after the current logical time) is moved to `CANCELLED`. Returning a table from `MAINTENANCE` to `ACTIVE` (activation) has no side effects. Because retirement cancels reservations, and an event-created reservation cancelling can cascade to its event (below), retiring a table can propagate all the way from the table through a reservation to an event and its host's wallet.

**Booking a reservation.** A `Member` (or `FrontDesk` acting on their behalf) reserves a table by supplying `member_id`, `table_id`, a `start_at` (inclusive) and `end_at` (exclusive) window, and a `party_size`. The reservation is created in `PENDING`. Several constraints guard creation, evaluated in the order of Section 2.8: the `party_size` must not exceed the table's `seat_capacity` (`ERR_CAPACITY_EXCEEDED`); the window must be well-formed — `start_at` strictly before `end_at`, both aligned to whole minutes, and the whole window falling within the member's plan `reservation_horizon_days` ahead of the current logical time (`ERR_INVALID_WINDOW`); the booking member must not be `SUSPENDED` (`ERR_MEMBER_SUSPENDED`); and the window must not conflict with another booking on the same table.

**The turnover buffer.** Two reservations on one table may not sit too close together. A new or rescheduled window `[start_at, end_at)` conflicts with any other reservation on the same table in `PENDING`, `CONFIRMED`, or `CHECKED_IN` if the two windows overlap once each is padded by a ten-minute turnover buffer — that is, there must be a clear gap of at least ten minutes between one reservation's end and the next reservation's start. A violation is rejected with `ERR_TABLE_TIME_CONFLICT`.

**Confirmation and rescheduling.** A `FrontDesk` operator confirms a `PENDING` reservation, moving it to `CONFIRMED`, provided the table is still `ACTIVE`. A member or front-desk operator may reschedule a reservation to a new `start_at`/`end_at` window; rescheduling re-runs the window-validity, party-capacity, table-active, and turnover-conflict checks against the new window, increments the reservation's `version` by one, and is guarded by `expected_reservation_version` as described in Section 2.7. A member or front-desk operator may cancel a reservation while it is `PENDING` or `CONFIRMED`, moving it to `CANCELLED`. If a cancelled reservation was created by an event booking (its `event_id` is set) and that event is still in booking status `BOOKED` or `CONFIRMED`, cancelling the reservation cancels that event too — the upstream half of the table-retire depth-three chain.

**Check-in and no-show.** A `FrontDesk` operator checks in a `CONFIRMED` reservation once the table is `ACTIVE` and the current logical time is at or after `start_at` minus fifteen minutes (early check-in is allowed up to a quarter-hour before the window opens). Check-in moves the reservation `CONFIRMED → CHECKED_IN` and opens a table session (Section 3.3). If the reserved party never arrives, a `FrontDesk` operator may mark the reservation a no-show once the current logical time is at or after `start_at` plus fifteen minutes; this moves it `CONFIRMED → NO_SHOW` and adds one to the member's `no_show_strikes`, which may trigger the suspension cascade of Section 3.1.

### 3.3. Table Sessions and Charge Calculation

A table session represents a table actually in use. Sessions arise two ways: a reservation check-in opens one automatically (`reservation_id` set to the reservation, `table_id` and `member_id` inherited), or a `FrontDesk` operator opens a walk-in session directly by supplying a `table_id` and an optional `member_id` (null for an anonymous walk-in, in which case no wallet is billed). Either way the session is created `OPEN`, its `started_at` stamped with the current logical time, and its `ended_at` left null. A walk-in requires the table to be `ACTIVE`.

At the moment a session opens, a **provisional charge** is stamped into `provisional_charge_cents`. The provisional charge is a flat off-peak estimate over the reserved window with no member discount. Let the reserved minutes be the whole-minute difference between the reservation's `end_at` and `start_at`; for a walk-in with no reservation, use the thirty-minute minimum in place of the reserved minutes. The billed minutes are the greater of the reserved minutes and a thirty-minute floor. The provisional charge is the billed minutes multiplied by the table's `hourly_rate_cents` divided by sixty, rounded half up to a whole cent. Peak pricing and member discounts are deliberately ignored at this stage.

When play ends, a `FrontDesk` operator closes the session (`OPEN → CLOSED`), which stamps `ended_at` to the current logical time and computes the **final charge** into `final_charge_cents`. The final charge is elapsed-time based and applies both peak pricing and any member discount:

- The actual minutes are the whole-minute difference between `ended_at` and `started_at`, and the billed minutes are the greater of the actual minutes and the thirty-minute floor.
- Consider the billing window that begins at `started_at` and runs for exactly the billed minutes. Count how many of those minutes fall in a peak hour, where peak means the minute's hour-of-day (UTC) is at or after 18:00 and before 24:00 — that is, the six-hour evening block from 6 p.m. up to (but not including) midnight. Those are the peak minutes; the remaining billed minutes are off-peak.
- The per-minute rate is the table's `hourly_rate_cents` divided by sixty, kept as an exact ratio rather than pre-rounded. The gross charge is the off-peak minutes at the plain per-minute rate plus the peak minutes at the per-minute rate multiplied by 1.5.
- The discount is the member's plan `table_discount_pct` when the session has a `member_id`, and zero otherwise. The final charge is the gross multiplied by one minus the discount, rounded half up to a whole cent exactly once, after the discount is applied.

Closing a session debits `final_charge_cents` from the member's `wallet_credit_cents`, but only when the session has a `member_id`; a debit that would take the wallet below zero is refused with `ERR_INSUFFICIENT_FUNDS`. If the session realizes a reservation (its `reservation_id` is set), closing it bubbles the reservation `CHECKED_IN → COMPLETED`.

Alternatively, a `FrontDesk` operator or `Manager` may void an `OPEN` session (`OPEN → VOIDED`) — for a mistaken open or an unbillable situation. Voiding stamps `ended_at`, sets `final_charge_cents` to zero, applies no wallet debit, and, if the session realizes a reservation that is still `CHECKED_IN`, moves that reservation to `CANCELLED`. Voiding is also the mechanism the event-cancellation cascade uses to unwind an event's in-progress sessions.

### 3.4. Food and Beverage Tabs

While a table session is open, a `Member` or `FrontDesk` operator may open a food-and-beverage tab against it by supplying the `session_id`, an optional `member_id` (the billed member, or null), and an array of `line_items`. Each line item names a menu item with a `name`, a `unit_price_cents`, and a `qty`. The tab is created `OPEN`; its computed `subtotal_cents`, `tax_cents`, and `total_cents` start at zero and are stamped when it is submitted.

A `FrontDesk` operator submits an `OPEN` tab (`OPEN → SUBMITTED`), which requires that the parent table session is still `OPEN` (otherwise `ERR_DEPENDENT_STATE`). Submission computes the tab totals. The `subtotal_cents` is the sum over the line items of `unit_price_cents` times `qty`. Tax is computed per line and then summed: for each line item, multiply `unit_price_cents` by `qty` by the food-and-beverage tax rate of 8.75 percent (0.0875) and round that line's tax half up to a whole cent; `tax_cents` is the sum of those per-line rounded amounts. This per-line-then-sum order is deliberate and can differ from taxing the subtotal as a whole at half-cent boundaries. The `total_cents` is `subtotal_cents` plus `tax_cents`. When the tab has a `member_id`, submission debits `total_cents` from that member's wallet, subject to the zero-floor rule. A `FrontDesk` operator may instead void an `OPEN` tab (`OPEN → VOIDED`), which charges nothing.

### 3.5. Tournaments, Entries, and Handicapping

A `Manager` creates a `Tournament` (which also models a league) with a `name`, a `format` of `SINGLE_ELIM`, `DOUBLE_ELIM`, `ROUND_ROBIN`, or `LEAGUE`, a `handicap_mode` of `FULL`, `CAPPED`, or `NONE` (defaulting to `CAPPED`), an `entry_fee_cents` charged to each entrant (at least zero), and a `max_entries` bracket capacity (which must be at least the four-entry seeding minimum). On creation the tournament is `SCHEDULED`, its `open_slots` initialized to `max_entries`, and its `prize_pool_cents` zero. Throughout its life the invariant `open_slots` plus captured entries equals `max_entries` is maintained.

A tournament advances `SCHEDULED → REGISTRATION_OPEN → SEEDED → IN_PROGRESS → COMPLETED` under `Manager` control, and may be cancelled from `SCHEDULED`, `REGISTRATION_OPEN`, or `SEEDED`. Opening registration, starting play from a seeded bracket, and completing an in-progress tournament each simply advance the status. Completing the tournament also marks its remaining checked-in entries `ELIMINATED` as the bracket resolves.

**Entering.** While registration is open, a `Member` enters by supplying the `tournament_id` and their own `member_id`. Entry creates a `TournamentEntry` in `ENTERED`, copies the tournament's `entry_fee_cents` onto the entry, debits that fee from the member's wallet (subject to the zero-floor rule), adds the fee to the tournament's `prize_pool_cents`, and decrements `open_slots` by one. A `SUSPENDED` member may not enter (`ERR_MEMBER_SUSPENDED`). A member may withdraw their own `ENTERED` entry while the tournament is in `REGISTRATION_OPEN` or `SEEDED`; withdrawal moves the entry `ENTERED → WITHDRAWN`, refunds the `entry_fee_cents` back to the member's wallet, subtracts that fee from `prize_pool_cents`, and restores one `open_slots`. A `FrontDesk` operator checks in an `ENTERED` entry (`ENTERED → CHECKED_IN`), which requires the tournament to be `SEEDED` (otherwise `ERR_DEPENDENT_STATE`).

The prize pool is the running sum of `entry_fee_cents` over the tournament's entries whose status is `ENTERED`, `CHECKED_IN`, or `ELIMINATED` — withdrawn entries are excluded — and is maintained incrementally as entries are captured and withdrawn.

**Seeding and the handicap spot.** A `Manager` seeds the bracket (`REGISTRATION_OPEN → SEEDED`) only once at least four entries have been captured (counting entries in `ENTERED` or `CHECKED_IN`); fewer than that is refused with `ERR_PRECONDITION_NOT_MET`. Seeding stamps each entry's `handicap_spot` — a number of games spotted relative to the strongest player. Let the top rating be the maximum `handicap_rating` among all non-withdrawn entries (those in `ENTERED` or `CHECKED_IN`); ties are resolved by value alone, so the result is order-independent. For a given entry, the raw spot is the top rating minus that entry's member's `handicap_rating`. The stamped `handicap_spot` then depends on the tournament's `handicap_mode`: under `FULL` it is the raw spot uncapped; under `CAPPED` it is the smaller of three and the raw spot; under `NONE` it is zero. Handicap spots are whole games and are never rounded. Until seeding, an entry's `handicap_spot` is null.

**Cancellation cascade.** Cancelling a tournament from `REGISTRATION_OPEN` or `SEEDED` withdraws every entry then in `ENTERED` or `CHECKED_IN` (moving each to `WITHDRAWN`), and for each such withdrawn entry refunds its `entry_fee_cents` to the member's wallet, decrements the tournament's `prize_pool_cents` by that fee, and restores one `open_slots`. Cancelling from `SCHEDULED` has no entries to unwind.

### 3.6. Pro-Shop Retail and Repair Services

**Products and inventory.** A `ProShopStaff` operator or `Manager` stocks the pro shop with products. Each `ProShopProduct` has a unique `sku`, a `name`, a `category` of `CUE`, `CASE`, `ACCESSORY`, `TABLE`, or `PART`, a `unit_price_cents` retail price (at least zero), and a `stock_qty` of on-hand units (never negative). Restocking adds a supplied `qty` to `stock_qty`. Selling subtracts a supplied `qty` from `stock_qty` and, when a `member_id` is supplied, debits `unit_price_cents` times `qty` from that member's wallet under the zero-floor rule. A sale is refused with `ERR_PRECONDITION_NOT_MET` when `qty` exceeds the available `stock_qty`; a non-positive `qty` on a restock or sale, or a sale that would otherwise drive stock below zero, is an `ERR_STOCK_NEGATIVE` (422) — though a sell whose quantity simply exceeds stock is reported as the precondition failure above.

**Repairs.** A `Member` or `ProShopStaff` operator drops off an item for service by creating a `RepairOrder` with the owning `member_id`, a `service_type` of `CUE_RETIP`, `CUE_REPAIR`, or `TABLE_RECOVER`, and an agreed `quote_cents` (at least zero) that will be charged at pickup. A repair optionally references the `product_id` of a pro-shop cue or part being serviced (null for a member-owned item) and optionally a `table_id` for a table-recover job (null otherwise). The order is created `RECEIVED`.

A repair moves `RECEIVED → IN_PROGRESS → READY → PICKED_UP` under staff and front-desk control, and may be cancelled from `RECEIVED` or `IN_PROGRESS`. A `ProShopStaff` operator starts a `RECEIVED` order and later marks an `IN_PROGRESS` order `READY`. Marking a table-recover job `READY` additionally requires that the referenced table's `status` is `MAINTENANCE` — the table must be pulled from service before its cloth work is signed off. A `FrontDesk` operator processes pickup of a `READY` order (`READY → PICKED_UP`), which debits the `quote_cents` from the owning member's wallet under the zero-floor rule. Cancelling a repair (by the member or by pro-shop staff, depending on stage) charges nothing.

### 3.7. Private Events

A private event blocks out several tables for a member's function, and it advances along two independent axes: a booking axis and a payment axis. The booking axis, `booking_status`, runs `INQUIRY → QUOTED → BOOKED → CONFIRMED → COMPLETED`, and may reach `CANCELLED` from any non-terminal booking state. The payment axis, `payment_status`, runs `UNPAID → DEPOSIT_PAID → PAID_IN_FULL`, and may reach `REFUNDED`. The two axes move independently except where a transition on one explicitly guards on the other.

A `Member` or `Manager` opens an event as an inquiry by supplying the `host_member_id`, a `table_count` of tables to block (at least 1), and the event window `start_at` (inclusive) and `end_at` (exclusive). The event is created with `booking_status` `INQUIRY` and `payment_status` `UNPAID`; its `quote_cents`, `deposit_cents`, and `deposit_paid_cents` start at zero. A `SUSPENDED` host may not open an event.

**Quoting.** A `Manager` quotes an `INQUIRY` event (`INQUIRY → QUOTED`), which requires that the window has enough capacity — at least `table_count` `ACTIVE` tables with no `CONFIRMED` or `CHECKED_IN` reservation overlapping `[start_at, end_at)` across the whole table pool; otherwise the quote is refused with `ERR_EVENT_CAPACITY_UNAVAILABLE`. Quoting computes and stamps `quote_cents` and `deposit_cents`. The number of hours is the whole-hour difference between `end_at` and `start_at`. The base is `table_count` times that hour count times the event rate of 4000 cents per table-hour. A bulk discount then applies by table count, with inclusive thresholds: 15 percent off when `table_count` is at least 10, otherwise 10 percent off when it is at least 6, otherwise 5 percent off when it is at least 3, otherwise none. The `quote_cents` is the base times one minus the bulk fraction, rounded half up to a whole cent. The `deposit_cents` is 25 percent of `quote_cents`, rounded half up to a whole cent.

**Paying the deposit.** The host member pays the deposit (`payment_status` `UNPAID → DEPOSIT_PAID`) while the event is `QUOTED` or `BOOKED`, provided the host's wallet holds at least `deposit_cents`; payment debits `deposit_cents` from the host wallet and records it in `deposit_paid_cents`. An insufficient balance is refused with `ERR_INSUFFICIENT_FUNDS`. Because the axes are independent, the deposit may be paid before or after the tables are booked.

**Booking, confirming, completing.** The host books a `QUOTED` event (`booking_status QUOTED → BOOKED`), which again requires `table_count` `ACTIVE` tables free across the window and creates that many `CONFIRMED` reservations on the selected tables, each stamped with this event's `event_id`. A `Manager` confirms a `BOOKED` event (`booking_status BOOKED → CONFIRMED`), but only once the payment axis has reached at least `DEPOSIT_PAID` — this cross-axis guard is enforced as a dependent-state check (`ERR_DEPENDENT_STATE`). A `Manager` completes a `CONFIRMED` event (`booking_status CONFIRMED → COMPLETED`), which advances `payment_status` to `PAID_IN_FULL` unless it has already been `REFUNDED`.

**Cancellation cascade.** A `Member` or `Manager` may cancel an event from any booking state other than `COMPLETED` or `CANCELLED`. Cancellation runs a multi-step unwind: every reservation carrying this event's `event_id` that is still `CONFIRMED` is moved to `CANCELLED`; for each such reservation that had an `OPEN` table session, that session is `VOIDED` (which zeroes its `final_charge_cents` and applies no wallet debit); and if the event's `payment_status` was `DEPOSIT_PAID`, the collected `deposit_paid_cents` is credited back to the host's wallet and `payment_status` becomes `REFUNDED`. This is the money-conserving compensation for a cancelled, deposit-paid event.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201; state transitions and other modifications return HTTP 200. All request and response bodies use the envelope of Section 2.2; the request payloads, side effects, and preconditions for each endpoint are specified in the Section 3 narratives rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/plans | Create a membership plan | Manager |
| GET | /v1/plans | List membership plans | Manager, FrontDesk, Member |
| GET | /v1/plans/{id} | Get a plan | Manager, FrontDesk, Member |
| POST | /v1/members | Register a member | Anonymous, Manager |
| GET | /v1/members | List/filter members | Manager, FrontDesk |
| GET | /v1/members/{id} | Get a member (lazy expiry on read) | Manager, FrontDesk, Member |
| POST | /v1/members/{id}/plan-change | Change plan (upgrade immediate, downgrade deferred; OCC-guarded) | Member |
| POST | /v1/members/{id}/renew | Renew membership | Member, FrontDesk |
| POST | /v1/members/{id}/wallet/adjustments | Credit/debit a member's wallet | Manager, FrontDesk |
| POST | /v1/tables | Create a pool table | Manager |
| GET | /v1/tables | List/filter tables | Manager, FrontDesk, Member |
| GET | /v1/tables/{id} | Get a table | Manager, FrontDesk, Member |
| POST | /v1/tables/{id}/maintenance | Put table into MAINTENANCE | Manager |
| POST | /v1/tables/{id}/activate | Return table to ACTIVE | Manager |
| POST | /v1/tables/{id}/retire | Retire a table | Manager |
| POST | /v1/reservations | Create a table reservation | Member, FrontDesk |
| GET | /v1/reservations | List/filter reservations | Manager, FrontDesk, Member |
| GET | /v1/reservations/{id} | Get a reservation | Manager, FrontDesk, Member |
| POST | /v1/reservations/{id}/confirm | Confirm a reservation | FrontDesk |
| POST | /v1/reservations/{id}/reschedule | Move a reservation window (OCC-guarded) | Member, FrontDesk |
| POST | /v1/reservations/{id}/cancel | Cancel a reservation | Member, FrontDesk |
| POST | /v1/reservations/{id}/check-in | Check in; opens a table session | FrontDesk |
| POST | /v1/reservations/{id}/no-show | Mark a confirmed reservation as no-show | FrontDesk |
| POST | /v1/sessions | Open a walk-in table session | FrontDesk |
| GET | /v1/sessions | List/filter sessions | Manager, FrontDesk, Member |
| GET | /v1/sessions/{id} | Get a session | Manager, FrontDesk, Member |
| POST | /v1/sessions/{id}/close | Close a session; final charge debits wallet | FrontDesk |
| POST | /v1/sessions/{id}/void | Void a session (no charge) | FrontDesk, Manager |
| POST | /v1/fnb-orders | Open a food/beverage tab on a session | Member, FrontDesk |
| GET | /v1/fnb-orders | List/filter fnb orders | Manager, FrontDesk, Member |
| GET | /v1/fnb-orders/{id} | Get an fnb order | Manager, FrontDesk, Member |
| POST | /v1/fnb-orders/{id}/submit | Submit tab; totals + wallet debit | FrontDesk |
| POST | /v1/fnb-orders/{id}/void | Void an open tab | FrontDesk |
| POST | /v1/tournaments | Create a tournament/league | Manager |
| GET | /v1/tournaments | List/filter tournaments | Manager, FrontDesk, Member |
| GET | /v1/tournaments/{id} | Get a tournament | Manager, FrontDesk, Member |
| POST | /v1/tournaments/{id}/open | Open registration | Manager |
| POST | /v1/tournaments/{id}/seed | Seed the bracket (stamps handicap spots) | Manager |
| POST | /v1/tournaments/{id}/start | Start play | Manager |
| POST | /v1/tournaments/{id}/complete | Complete tournament | Manager |
| POST | /v1/tournaments/{id}/cancel | Cancel; withdraw + refund all entries | Manager |
| POST | /v1/tournament-entries | Enter a tournament (entry fee debits wallet) | Member |
| GET | /v1/tournament-entries | List/filter entries | Manager, FrontDesk, Member |
| GET | /v1/tournament-entries/{id} | Get an entry | Manager, FrontDesk, Member |
| POST | /v1/tournament-entries/{id}/check-in | Check in an entry | FrontDesk |
| POST | /v1/tournament-entries/{id}/withdraw | Withdraw; refund + slot/pool restore | Member |
| POST | /v1/products | Create a pro-shop product | ProShopStaff, Manager |
| GET | /v1/products | List/filter products | Manager, FrontDesk, ProShopStaff, Member |
| GET | /v1/products/{id} | Get a product | Manager, FrontDesk, ProShopStaff, Member |
| POST | /v1/products/{id}/restock | Add units to stock | ProShopStaff, Manager |
| POST | /v1/products/{id}/sell | Sell units; optional member wallet charge | ProShopStaff, Manager |
| POST | /v1/repair-orders | Drop off a cue/table for service | Member, ProShopStaff |
| GET | /v1/repair-orders | List/filter repair orders | Manager, FrontDesk, ProShopStaff, Member |
| GET | /v1/repair-orders/{id} | Get a repair order | Manager, FrontDesk, ProShopStaff, Member |
| POST | /v1/repair-orders/{id}/start | Begin service | ProShopStaff |
| POST | /v1/repair-orders/{id}/ready | Mark ready for pickup | ProShopStaff |
| POST | /v1/repair-orders/{id}/pickup | Customer pickup; quote debits wallet | FrontDesk |
| POST | /v1/repair-orders/{id}/cancel | Cancel a repair before pickup | Member, ProShopStaff |
| POST | /v1/events | Create a private event inquiry | Member, Manager |
| GET | /v1/events | List/filter events | Manager, FrontDesk, Member |
| GET | /v1/events/{id} | Get an event | Manager, FrontDesk, Member |
| POST | /v1/events/{id}/quote | Quote the event | Manager |
| POST | /v1/events/{id}/pay-deposit | Pay deposit from host wallet | Member |
| POST | /v1/events/{id}/book | Book tables (creates confirmed reservations) | Member |
| POST | /v1/events/{id}/confirm | Confirm event (requires deposit paid) | Manager |
| POST | /v1/events/{id}/complete | Complete event | Manager |
| POST | /v1/events/{id}/cancel | Cancel event; cascade + deposit refund | Member, Manager |
| POST | /v1/_clock/set_current_utc | Set the logical clock | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TABLE_NOT_ACTIVE | 409 |
| ERR_DEPENDENT_STATE | 409 |
| ERR_TABLE_TIME_CONFLICT | 409 |
| ERR_EVENT_CAPACITY_UNAVAILABLE | 409 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_PRECONDITION_NOT_MET | 409 |
| ERR_INSUFFICIENT_FUNDS | 402 |
| ERR_VALIDATION | 422 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_STOCK_NEGATIVE | 422 |
| ERR_DUPLICATE | 409 |
| ERR_PAGINATION | 422 |

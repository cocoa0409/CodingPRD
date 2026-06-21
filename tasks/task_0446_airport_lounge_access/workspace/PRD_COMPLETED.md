# Airport Lounge Access API — Product Requirements Document

## 1. Introduction

The Airport Lounge Access platform powers a Priority-Pass-style network in which members carry a membership tier with an annual allotment of free visits, walk up to any participating lounge in the directory, and check in subject to eligibility, capacity, and standing rules. The product solves three intertwined problems at once: it meters each member's consumption of a finite annual allotment and prices anything beyond it; it arbitrates a lounge's physical capacity in real time as holds and check-ins compete for seats; and it keeps a faithful two-sided ledger — what each member owes the network, and what the network owes each lounge — so that money is never created or destroyed by a state change.

Three parties operate the system. A network back office configures the catalogue of plans and the directory of lounges, enrols members, issues credentials, runs the periodic housekeeping sweep, and settles payouts. The door staff of an individual lounge open holds, admit arriving members and their guests, and either complete or no-show each visit. Members themselves browse the directory, buy day passes, cancel holds they no longer need, and book amenity time. Because seats, allotment, and money are all conserved quantities that several actors touch concurrently, the system treats consistency as immediate: every derived counter — a lounge's live occupancy, a member's usage, a lounge's payable balance — is recomputed from its underlying facts on every mutation rather than drifted incrementally, and guarded writes carry an optimistic-concurrency token so that a stale view cannot slip a seat or a price past a change the caller never saw.

This document specifies the complete contract: the resource model, the lifecycle of each entity, the pricing and allotment calculations, the validation order, and the full endpoint and error surface.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `NetworkAdmin`, `LoungeAgent`, and `Member`. A request that omits either header, or that carries an `X-User-Role` value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The three roles differ in how `X-User-ID` binds to the data:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting member. Ownership checks on any resource that references a member compare that resource's owning member reference to `X-User-ID`: a member acting on a visit, day pass, eligibility card, or shower reservation must own it.
- When `X-User-Role` is `LoungeAgent`, `X-User-ID` is the `id` of the lounge whose door the agent staffs (the agent identity is backed by the `Lounge` entity). Ownership checks on any operation an agent performs against a visit compare that visit's `lounge_id` to `X-User-ID`; an agent may only act on visits at the lounge they staff.
- When `X-User-Role` is `NetworkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; the network operator is trusted across the whole network.

Ownership violations — a member touching a resource they do not own, or an agent touching a visit at a lounge they do not staff — are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and an explicitly supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the start of the result and defaults to 0. A `limit` below 1 or above 100, or a malformed pagination value, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system are full first-class records that carry a standard set of system-managed fields: an `id` formatted as a UUID with no type prefix; a `created_at` timestamp in ISO 8601 UTC with three fractional digits, fixed at creation; an `updated_at` timestamp in the same format, refreshed on every mutation; and a `version` integer that starts at 1 and increments by one on every mutation. The entities that carry this full set are membership plans, lounges, members, eligibility cards, visits, guests, day passes, shower suites, and shower reservations.

Two entities are append-only event records and deliberately carry a reduced field set: a settlement and a ledger entry each carry only `id` and `created_at`. For these two, both `updated_at` and `version` are absent — their status changes are modelled as new facts and recomputations elsewhere rather than as in-place versioned edits.

Time in this system is governed by a single server-side **logical clock** rather than wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. The network operator can advance the clock to any absolute instant by supplying a `to_iso8601` value (a required, non-empty string; a missing/empty value or one that does not parse as an ISO 8601 instant is rejected with `ERR_INVALID_REQUEST`); the response reports the new instant as `now` (re-emitted in the canonical three-fractional-digit `Z` format). Every time-derived field — a visit's `hold_expires_at`, a day pass's `valid_until`, a member's `membership_year_start` — and every "is it expired?" comparison reads this logical clock. This makes the entire temporal surface deterministically test-drivable.

### 2.5. Derived Counters and Reconciliation

Several fields are not written directly but are **derived** — recomputed from their underlying records every time a relevant fact changes. A lounge's `current_occupancy` is the sum of `occupant_count` over its visits that are currently `CHECKED_IN`, and its `held_occupancy` is the same sum over its visits that are currently `HELD`; both are bounded below by zero, and `current_occupancy` never exceeds the lounge's `capacity`. A lounge's `settlement_balance_cents` is the sum of `amount_cents` over that lounge's settlements that are still `PAYABLE`. A member's `visits_used`, `guest_visits_used`, `no_show_strikes`, and `wallet_balance_cents` are likewise derived from the member's visits and ledger entries as defined in §3.

Whenever an operation changes one of these underlying facts, the system recomputes the affected derived counter immediately within the same operation, so a read taken after the operation always reflects the new reality. When a recomputation mutates a resource that carries `version` — for example a lounge whose occupancy line moved — that mutation refreshes the resource's `updated_at` and increments its `version` like any other change.

### 2.6. Cascading Side Effects and Hierarchical Consistency

A single operation in this system frequently mutates more than one entity, and each such cascade is part of the contract, not an optimization. Checking a visit in moves seats from a lounge's held tally to its live tally and posts member charges; completing a visit creates a settlement and raises the lounge's payable balance; sweeping an expired hold can add a no-show strike to a member, which can in turn flip the member's standing and cancel that member's other outstanding holds, which in turn releases held seats at several lounges. These multi-hop cascades are spelled out in the workflow narratives of §3. The governing rule is that no derived quantity is left stale at the end of an operation: every counter touched by a cascade is recomputed before the response is returned.

### 2.7. Optimistic Concurrency on Guarded Writes

Three write operations are guarded by optimistic concurrency control, in each case keyed on a parent lounge's `version`. The client must supply `expected_lounge_version` in the request body carrying the `version` of the lounge it last observed. If that value does not match the lounge's current `version` at the moment the write is processed, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is mutated.

- Opening a hold requires `expected_lounge_version` to match the target lounge's current `version`. If the lounge's version has advanced since the client last read it — because, for instance, the lounge was just closed or its occupancy line moved — the client's view is stale and the hold is refused rather than allowed to slip a seat past a capacity or closure change the client never saw.
- Purchasing a day pass requires `expected_lounge_version` to match the lounge's current `version`. The pass price is snapshotted from the lounge at purchase, so a stale read could otherwise sell a pass at a superseded price or against a lounge that has since closed; the check forces the client to re-read first.
- Closing a lounge requires `expected_lounge_version` to match the lounge's current `version` before the close is applied.

These three are the only version-guarded writes. Endpoints not named here take no version field, and `expected_lounge_version` always refers to the lounge's `version`, never any other entity's.

### 2.8. Monetary Values, Counts, and Rounding

All money in the system is held in integer cents, and all allotment figures are integer counts; neither is ever represented as a fractional currency unit. Counts (visits used, guest visits, strikes, occupancy) are pure integers and involve no rounding. Where a calculation applies a member discount multiplier and therefore produces a fractional cent, the result is rounded to a whole number of cents using the **round-half-up** rule, and — critically — the rounding is applied per line item before the lines are summed, never to the sum afterward (the per-line order is specified precisely in §3.4, because summing first and rounding once yields a different total).

### 2.9. Resource Existence and Left-to-Right Resolution

Before any business rule runs, the system resolves the resources a request names. Identifiers that appear in the URL path are validated first, left to right, followed by foreign-key references carried in the request body — members, lounges, visits, day passes, plans, settlements, and cards alike. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later resource is examined and before any state or business check is attempted.

### 2.10. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the role header comes first (`ERR_UNAUTHENTICATED`), then role authorization for the operation (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then resource ownership (`ERR_NOT_RESOURCE_OWNER`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after these structural gates pass does the system evaluate the operation's domain-specific business rules; the relative ordering of those domain rules, where it matters, is given alongside the workflow that uses them in §3. Last of all, body-shape validation — required fields present, enum and type values legal, and on shower bookings the start instant strictly before the end instant — is enforced with `ERR_INVALID_REQUEST` (HTTP 400). The optimistic-concurrency check described in §2.7 likewise fires within this domain-rule phase, rejecting a stale guarded write with `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Network: Plans, Lounges, and Amenities

The network operator builds the catalogue before anyone can transact. A **membership plan** is the pricing template a member enrols against. Each plan is created with a `tier`, which is one of `STANDARD`, `PRESTIGE`, or `PRESTIGE_PLUS` and must be unique across all plans. A plan declares its annual entitlements and prices: `included_visits_per_year` is the yearly allotment of free primary visits and must be at least 0 (a `STANDARD` plan typically grants 0), with the special sentinel value of -1 meaning the allotment is unlimited; `included_guest_visits_per_year` is the yearly allotment of free guest visits and must be at least 0; `overage_charge_cents` is the per-visit amount billed to the member when a primary visit is not covered by allotment (at least 0); `guest_charge_cents` is the per-guest amount billed when a guest visit is not covered by guest allotment (at least 0); `annual_fee_cents` is the informational annual membership fee billed at enrolment (at least 0); and `min_card_status` is the minimum co-brand card tier — one of `BASIC`, `SILVER`, or `GOLD` — the plan requires a member to hold.

A **lounge** is an entry in the network directory. A lounge is created with a display `name`, an `airport_code` that must be exactly three uppercase letters of an IATA code, a `capacity` of at least 1 (the maximum number of occupants present at once, where each primary occupant and each guest counts as one), a `settlement_rate_cents` of at least 0 (what the network owes the lounge per occupant on a completed visit), a `guest_fee_cents` of at least 0 (the lounge's own door fee charged to the member per guest occupant at check-in, in addition to any plan guest charge), and a `day_pass_price_cents` of at least 0 (the price of a single-use day pass to the lounge). On creation a lounge starts in `OPEN` status with both occupancy counters and its settlement balance at zero. Its `status`, `current_occupancy`, `held_occupancy`, and `settlement_balance_cents` are all system-maintained and never set directly by the caller.

Lounges also host **shower suites** as a bookable amenity. A suite is created against a lounge with a `label` (for example, "Suite A") and an optional `turnover_minutes` cleaning buffer that defaults to 0 and must be at least 0; this buffer is enforced after each booking, as described in §3.7. A suite carries an `out_of_service` flag, system-maintained and false on creation, that when true causes the suite to accept no bookings.

The operator can take a lounge out of and back into service. Closing a lounge transitions its `status` to `CLOSED` from either `OPEN` or `OVERFLOW`; this is one of the version-guarded writes of §2.7 and requires the supplied lounge version to match. A closed lounge accepts no new holds and no check-ins, though visits already `CHECKED_IN` there may still be completed. Reopening a lounge is only defined from `CLOSED`; on reopen the system does not blindly return the lounge to `OPEN` but recomputes its status from the current occupancy line — landing on `OPEN` if seats remain or on `OVERFLOW` if the occupancy line is already at or above capacity (see §3.3).

### 3.2. Members and Their Credentials

The operator enrols a **member** onto a plan by supplying the target `plan_id` and the member's `full_name`. Enrolment stamps `membership_year_start` to the current logical-clock instant, starts the member in `GOOD` standing, and zeroes every usage counter: `visits_used`, `guest_visits_used`, `no_show_strikes`, and `wallet_balance_cents` all begin at 0. The first three count consumption within the current allotment year; `wallet_balance_cents` is the member's running ledger balance, which may legitimately go negative when credits exceed charges.

To enter a lounge on allotment or overage, a member needs an active **eligibility credential**. An eligibility card is issued to a member (identified by `member_id`) with a `card_status` of `BASIC`, `SILVER`, or `GOLD`; a `fare_class` for the active trip of `ECONOMY`, `BUSINESS`, or `FIRST`; and a `valid_until` UTC expiry instant. A card is the member's currently active credential when its `active` flag is true, and a member has at most one active card at a time: issuing a new card sets it active and flips any previously active card of that member to inactive, and explicitly activating one card likewise deactivates that member's other cards. A card whose `valid_until` is at or before the logical clock is expired.

A member's **standing** governs whether they may open new holds and is one of `GOOD` or `SUSPENDED`. Standing is driven solely by no-show strikes accumulating and by an operator reinstatement — it is not affected by card or fare eligibility, which is a separate per-hold gate described in §3.5. When the operator reinstates a suspended member, `no_show_strikes` is reset to 0 and `standing` returns to `GOOD`. A member whose standing is `SUSPENDED` cannot open new holds.

### 3.3. Holds, Capacity, and the Overflow Line

The core operational unit is the **visit**, which begins life as a *hold* — a reservation of seats opened with the intent to check in. A hold is opened against a lounge (`lounge_id`) by, or on behalf of, a member (`member_id`, which is absent only for a non-member day-pass entry — a hold that supplies no `day_pass_id` and no `member_id` is rejected with `ERR_INVALID_REQUEST`, since a non-day-pass entry requires a member), optionally redeeming a `day_pass_id`, and optionally bringing guests. The number of accompanying guests is given by `guest_count` (defaulting to 0, at least 0), and their names are supplied in `guest_names` in the order they will be funded; `guest_names` must be a list of strings, and when `guest_count` is greater than 0 it is required and its length must equal `guest_count` (a missing list when `guest_count > 0`, or a length that disagrees with `guest_count`, is rejected with `ERR_INVALID_REQUEST`). The visit's `occupant_count` is one plus the guest count — the seats the visit occupies. At hold time the system snapshots the member's active card onto the visit as `eligibility_card_id` (null for a day-pass-only entry), records `held_at` at the current logical clock, and sets `hold_expires_at` to thirty minutes after `held_at`. The hold's `status` begins at `HELD`. Opening a hold is a version-guarded write keyed on the lounge (see §2.7).

A lounge polices its physical capacity through a status machine over `OPEN`, `OVERFLOW`, and `CLOSED`. The **overflow line** is reached when the sum of a lounge's `current_occupancy` and `held_occupancy` is at or above its `capacity`: at that point an `OPEN` lounge is recomputed to `OVERFLOW`, in which state new holds are refused but existing holds may still check in if a seat is free. When a completion, cancellation, or sweep brings that combined occupancy strictly below capacity again, an `OVERFLOW` lounge recomputes back to `OPEN`. A request to open a hold is honoured only when the lounge's `status` is `OPEN`; a lounge in `OVERFLOW` or `CLOSED` rejects the new hold with `ERR_LOUNGE_OVERFLOW` (HTTP 409). When a hold is opened, the lounge's `held_occupancy` is recomputed upward by the visit's `occupant_count` and the lounge's status is recomputed (possibly flipping to `OVERFLOW`).

Before a hold is persisted, the system also resolves how the primary occupant's entry is funded and pins it as `entry_mode` — one of `ALLOTMENT`, `OVERAGE`, or `DAY_PASS` — together with the boolean `allotment_consumed`, which is true exactly when `entry_mode` is `ALLOTMENT`. The decision is a strict cascade. If a `day_pass_id` is supplied, the pass's validity is checked at hold time — it must be `ISSUED`, not past its `valid_until`, belong to the target lounge, and (when the pass is member-bound) belong to this member; a pass failing any of these is rejected with `ERR_DAY_PASS_INVALID` (HTTP 422). If a valid day pass is supplied, the entry mode is `DAY_PASS` and no allotment is consumed. Otherwise, if the plan's `included_visits_per_year` is the unlimited sentinel of -1, the entry mode is `ALLOTMENT` and allotment is consumed (usage is still tracked but never gates the decision). Otherwise, if the member's `visits_used` for the current year is strictly less than the plan's `included_visits_per_year`, the entry mode is `ALLOTMENT` and allotment is consumed. In every other case the entry mode is `OVERAGE` and no allotment is consumed. The boundary follows directly from the strict comparison: with six included visits, the seventh primary visit is the first to be charged as overage — the visit that observes `visits_used` equal to the included count is the first `OVERAGE`, while the visit that observes it one below is still free.

Guests are funded next, after the primary entry mode is resolved, by walking the visit's guests in creation order. The member's remaining guest allotment is the plan's `included_guest_visits_per_year` minus the member's `guest_visits_used` for the current year, floored at zero. The visit's `guest_allotment_consumed` is the lesser of `guest_count` and that remaining allotment. Walking the guests in order, the first `guest_allotment_consumed` of them are funded from allotment and the rest are charged: each guest's `funded_by` is set to `GUEST_ALLOTMENT` for those covered and `GUEST_CHARGE` for those beyond the split point. Because the split is positional, guest order must be pinned to creation order: when the remaining allotment is strictly between zero and the guest count, the earliest guests are covered and the later ones are charged; when the remaining allotment is zero — because it was already exhausted or the plan grants none — every guest is `GUEST_CHARGE`. On a non-member day-pass-only entry (no `member_id` and hence no plan to draw from), there is no guest allotment at all: `guest_allotment_consumed` is 0 and every guest is funded `GUEST_CHARGE`. This step reads the member's guest usage as it stood before the hold; resolving the primary entry mode does not alter guest usage.

A member may **cancel** a hold they own while it is still `HELD`, which is the only state from which cancellation is defined. Cancelling releases the held seats — the lounge's `held_occupancy` is recomputed downward by the visit's `occupant_count` — and the visit moves to the terminal `CANCELLED` status. Because a cancelled visit leaves the set of statuses that count toward usage, no allotment is consumed by it. If the cancelled hold had redeemed a day pass, that pass is released back as described in §3.6.

### 3.4. Check-in: Admission, Charges, and the Member Ledger

A lounge agent admits a held visit by checking it in, which is defined only from `HELD` and only for the agent who staffs the visit's lounge. Several gates apply at this moment, beyond the structural checks of §2.10. The hold must not have expired — its `hold_expires_at` must still be strictly after the logical clock. The lounge must be in `OPEN` or `OVERFLOW` status (a `CLOSED` lounge admits no one). The lounge must have room: the lounge's `current_occupancy` plus the visit's `occupant_count` must not exceed the lounge's `capacity`, and a check-in that would breach that ceiling is rejected with `ERR_OVER_CAPACITY` (HTTP 409). For any entry that is not a day-pass entry, the member's `standing` must be `GOOD`. If the day pass being redeemed is no longer valid at this point — neither `ISSUED` nor already held-`REDEEMED` for this same visit (a pass `REDEEMED` against a different visit, or in any other status, is invalid), expired, for the wrong lounge, or not owned by this member — the check-in is rejected with `ERR_DAY_PASS_INVALID` (HTTP 422).

On a successful check-in the visit moves to `CHECKED_IN`, and the system computes and pins the member's charge for the visit as `member_charge_cents`. This charge is the sum of three line items, and the rounding order is part of the contract: a per-occupant member discount is applied to each line and that line is rounded to whole cents before the lines are added together. The discount multiplier is 0.90 when the member's active card has `card_status` `GOLD`, and 1.0 otherwise. The first line is the overage line: when `entry_mode` is `OVERAGE`, it is the plan's `overage_charge_cents` multiplied by the discount and rounded half-up to whole cents; otherwise it is zero. The second contribution is the guest total, computed by walking the guests in creation order: for each guest whose `funded_by` is `GUEST_CHARGE`, that guest's `charge_cents` is the sum of the plan's `guest_charge_cents` and the lounge's `guest_fee_cents`, multiplied by the discount and rounded half-up; for each guest whose `funded_by` is `GUEST_ALLOTMENT`, only the lounge's `guest_fee_cents` applies (the plan guest charge is waived), multiplied by the discount and rounded half-up; the guest total is the sum of those already-rounded per-guest charges. The third line is the day-pass line: when `entry_mode` is `DAY_PASS`, it is the day pass's already-snapshotted `price_cents`, which is not discounted; otherwise it is zero. The visit's `member_charge_cents` is the sum of the rounded overage line, the guest total, and the day-pass line. Because each line is rounded before summing, the total can differ from rounding a single combined figure — for example two `GOLD`-discounted guest lines that each round 1505 cents at 0.90 to 1355 sum to 2710, whereas discounting the combined 3010 would yield 2709; the per-line order is what the system uses.

Each chargeable component posts a **ledger entry** against the member, recording the `member_id`, the originating `visit_id`, the `kind`, a signed `amount_cents`, and a `status` that begins at `POSTED`. Check-in posts one entry of kind `OVERAGE` when the entry mode is `OVERAGE` (only when that overage line is non-zero), and per guest posts up to two rows that together sum exactly to that guest's already-rounded `charge_cents`: a `LOUNGE_GUEST_FEE` row carrying the per-line-rounded lounge door-fee portion (clamped never to exceed the guest's `charge_cents`) is posted for every guest — both `GUEST_ALLOTMENT` and `GUEST_CHARGE` — whenever that portion is non-zero, and a `GUEST_CHARGE` row carrying the remaining plan portion is posted only for a `GUEST_CHARGE` guest and only when that remainder is non-zero. (Ledger entries are only posted for member-tied entries; a non-member day-pass-only entry posts none.) A day-pass purchase tied to a member posts a `DAY_PASS` entry, and the refund flow of §3.6 posts a `DAY_PASS_REFUND` entry; the settlement-reversal flow of §3.8 posts no member ledger entry (it acts only on the lounge's settlement and balance), so although `OVERAGE_REVERSAL` is a defined ledger kind, no operation in this system actually emits one. Every ledger amount is non-zero; positive amounts are charges to the member and negative amounts are credits. A ledger entry's `status` is `POSTED` or `VOID`, but every entry is created `POSTED` and no operation in this system ever transitions one to `VOID` — `VOID` is a defined status that no flow produces. The member's `wallet_balance_cents` is then recomputed as the sum of `amount_cents` over the member's `POSTED` ledger entries, net of credits. Also at check-in the lounge's seats are moved: `current_occupancy` is recomputed upward by `occupant_count` and `held_occupancy` downward by the same. If the visit redeemed a day pass, that pass is finalised as redeemed at this point (see §3.6).

A checked-in visit is brought to a close by the lounge agent **completing** it, which is defined only from `CHECKED_IN`. Completion computes and pins the visit's `settlement_amount_cents` as the visit's `occupant_count` multiplied by the lounge's `settlement_rate_cents`, where the occupant count is the value frozen at check-in (one plus the guest count) and the rate is the lounge's rate at completion time — if the lounge's settlement rate changed between check-in and completion, the rate in force at completion is the one that crystallises. Completion creates a **settlement** record for the lounge in `PAYABLE` status carrying that `amount_cents`, recomputes the lounge's `settlement_balance_cents` upward to include it, and frees the seats by recomputing the lounge's `current_occupancy` downward by `occupant_count`. The settlement records the owed `lounge_id`, the originating `visit_id`, the snapshotted `amount_cents`, and its `status`.

### 3.5. Eligibility and Suspension Gates on a Hold

Opening a hold for a member (as opposed to a non-member day-pass entry) is subject to a chain of business gates that fire after the structural checks of §2.10 and in addition to the capacity and overflow rules of §3.3. First, the member must hold an active, non-expired eligibility card; a member-route hold attempted with no such card is rejected with `ERR_NO_ACTIVE_CARD` (HTTP 422). A day-pass-only entry needs no card and is exempt from this requirement. Second, the eligibility gate proper: the member is permitted to enter on allotment or overage only when their active card's `card_status` meets or exceeds the plan's `min_card_status`, or their card's `fare_class` is `BUSINESS` or `FIRST`. A member who satisfies neither condition is not eligible and the hold is rejected with `ERR_NOT_ELIGIBLE` (HTTP 422); a day-pass entry bypasses this eligibility gate entirely. Third, the member's standing must be `GOOD`: a `SUSPENDED` member who attempts to open a hold is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409), while a day-pass-only entry is exempt. These eligibility and standing gates are distinct mechanisms — falling below the plan's card minimum makes a member ineligible for a particular hold but does not suspend them, and suspension blocks all member holds regardless of card status.

### 3.6. Day Passes

A **day pass** is a single-use admission to one lounge, bought either by a member or by a walk-up non-member. A purchase names the target lounge and supplies either a purchasing `member_id` or, for a non-member buyer, a `buyer_name` (at least one of the two is required; a body carrying neither is rejected with `ERR_INVALID_REQUEST`). When the buyer acts under the `Member` role, the supplied `member_id` must equal the acting principal — a member may only purchase for themselves, and any other (or absent) `member_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. The pass's `price_cents` is snapshotted from the lounge's `day_pass_price_cents` at purchase, and its `valid_until` is set to twenty-four hours after the purchase instant. The pass begins in `ISSUED` status with an empty `redeemed_visit_id`. Purchasing is a version-guarded write keyed on the lounge (§2.7), and a successful purchase itself bumps that lounge's `version` (refreshing its `updated_at`), so the next guarded write must re-read the lounge first. When the buyer is a member, the purchase posts a `DAY_PASS` ledger entry for the member and recomputes that member's `wallet_balance_cents`.

A day pass moves through a small non-linear lifecycle over `ISSUED`, `REDEEMED`, `REFUNDED`, and `EXPIRED`. Redemption happens through a visit: opening a hold with a valid `day_pass_id` immediately marks the pass `REDEEMED` and sets its `redeemed_visit_id` to that hold, and the subsequent check-in keeps it `REDEEMED` with the same `redeemed_visit_id`, provided the pass was valid (`ISSUED` or already held-`REDEEMED` for this visit), not past its `valid_until`, and belongs to the visit's lounge. If instead the redeeming hold is cancelled before check-in, a `REDEEMED`-held pass reverts to `ISSUED` and its `redeemed_visit_id` is cleared back to empty. The operator can refund a pass that is still `ISSUED` and was never redeemed (a pass in any other status is rejected with `ERR_INVALID_STATE`), and only when it is member-owned (a non-member, `buyer_name`-only pass is likewise rejected with `ERR_INVALID_STATE`, since refunds go only to member wallets): refunding moves the pass to the terminal `REFUNDED` status, posts a `DAY_PASS_REFUND` ledger entry for the member with a negative amount equal to the negation of the pass's `price_cents`, and recomputes the member's `wallet_balance_cents` so that it drops by the pass price. An `ISSUED` pass that reaches its `valid_until` without being redeemed is forfeited: the housekeeping sweep moves it to the terminal `EXPIRED` status with no refund.

### 3.7. Shower Reservations and the Turnover Buffer

A checked-in visitor can book amenity time in a shower suite. A **shower reservation** is created against a `shower_suite_id` and the `visit_id` of the checked-in visit it belongs to, with a `start_at` and `end_at` defining a half-open interval `[start_at, end_at)` in which the start instant must be strictly before the end instant. The booking is permitted only when the referenced visit is `CHECKED_IN` and the suite is not out of service; a booking against a visit that is not checked in, or a suite whose `out_of_service` is true, is rejected with `ERR_SHOWER_UNAVAILABLE` (HTTP 409). The reservation starts in `BOOKED` status.

Bookings of the same suite may not overlap once the suite's `turnover_minutes` cleaning buffer is taken into account. The buffer is applied after each existing booking, so an existing `BOOKED` reservation effectively occupies the interval from its `start_at` up to its `end_at` plus the suite's `turnover_minutes`. A proposed booking conflicts with an existing `BOOKED` reservation of the same suite exactly when the proposed `start_at` falls before that existing reservation's `end_at` plus the turnover minutes, and the existing reservation's `start_at` falls before the proposed `end_at`; any such conflict rejects the new booking with `ERR_SHOWER_CONFLICT` (HTTP 409). Touching exactly at the buffered boundary is not a conflict: when the suite's turnover is zero, a back-to-back booking whose `start_at` equals the existing reservation's `end_at` is allowed; when the turnover is greater than zero, a booking starting exactly at the existing reservation's `end_at` is rejected and must instead start at or after that end plus the turnover minutes.

The member who owns the reservation's visit may cancel it while it is `BOOKED`, which releases the interval and frees the suite for new overlapping bookings; the reservation moves to the terminal `CANCELLED` status. A lounge agent staffing the reservation's lounge may instead mark a `BOOKED` reservation `COMPLETED`. Both transitions are defined only from `BOOKED`.

### 3.8. Housekeeping Sweep, No-Show Cascades, and Settlement Payout

The network operator runs a **sweep** against a lounge at the current logical clock to resolve everything that time has aged out. The sweep performs three jobs and reports the counts as `swept_no_show_count`, `swept_abandoned_count`, and `expired_day_pass_count`. First, any `HELD` visit whose `hold_expires_at` is at or before the logical clock is expired to the terminal `NO_SHOW` status: its held seats are released (the lounge's `held_occupancy` is recomputed downward by its `occupant_count`), and for any entry that was not a day-pass entry the member's `no_show_strikes` is recomputed upward by one. A no-show still burns allotment, because `NO_SHOW` is one of the statuses that count toward usage — so a hold that expires unredeemed nonetheless consumes its `allotment_consumed` and `guest_allotment_consumed`. If the expired hold had redeemed a day pass, that pass's held redemption reverts to `EXPIRED` and the pass is forfeited.

Crossing the strike threshold triggers a cascade. When a member's recomputed `no_show_strikes` reaches three, the member's `standing` flips from `GOOD` to `SUSPENDED`, which by itself blocks any future hold. The suspension in turn auto-cancels every other visit of that member still in `HELD` status: each such hold transitions `HELD → CANCELLED`, and each cancellation releases that hold's `held_occupancy` at its own lounge — a third cascade hop that can flip several lounges back from `OVERFLOW` to `OPEN`. Reinstatement by the operator, as noted in §3.2, resets the strike count to zero and returns standing to `GOOD`.

Second, the sweep abandons stranded check-ins: a `CHECKED_IN` visit whose snapshotted eligibility card (`eligibility_card_id`) has a `valid_until` at or before the logical clock — the credential expired mid-visit — is moved to the terminal `ABANDONED` status. Abandonment frees the lounge's seats by recomputing `current_occupancy` downward by `occupant_count`, but creates no settlement (an abandoned visit is not billable to the network) and does not reverse the `member_charge_cents` already posted at check-in. Third, the sweep expires day passes: any `ISSUED` pass whose `valid_until` is at or before the logical clock moves to `EXPIRED` with no refund. The sweep recomputes all affected derived state as it goes.

Settlements owed to lounges are paid out and, where necessary, reversed by the operator. A settlement lives over `PAYABLE`, `PAID`, and `REVERSED`, and only a `PAYABLE` settlement may be paid or reversed — an attempt against any other status is rejected with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409). The operator can pay out a lounge's settlements as a batch in creation order, moving each `PAYABLE` settlement of that lounge to `PAID`; because the balance counts only `PAYABLE` settlements, paying them out recomputes the lounge's `settlement_balance_cents` down to zero, and the batch reports `paid_count` and `paid_total_cents`. The operator can also reverse an individual `PAYABLE` settlement as a compensation, moving it to `REVERSED` and recomputing the lounge's `settlement_balance_cents` downward by that settlement's amount as it drops out of the payable sum; the conserved-quantity invariant on settlements holds across reversal. A lounge's live `settlement_balance_cents` always reflects only its `PAYABLE` settlements; a separate settlement summary read exposes both this payable figure as `payable_balance_cents` and a `lifetime_earned_cents` that sums settlements in `PAYABLE` and `PAID` status (excluding `REVERSED`), alongside `paid_cents` — the two figures diverge once any settlement has been paid.

### 3.9. The Allotment Year and Its Reset

A member's usage counters are scoped to the current allotment year, anchored at `membership_year_start`. The member's `visits_used` is the count of that member's visits whose `held_at` is at or after the year start, whose `allotment_consumed` is true, and whose status is one of `CHECKED_IN`, `COMPLETED`, or `NO_SHOW`. The member's `guest_visits_used` is the sum of `guest_allotment_consumed` over the member's visits whose `held_at` is at or after the year start and whose status is one of those same three. The member's `no_show_strikes` is the count of the member's visits in `NO_SHOW` status whose entry was not a day-pass entry and whose `held_at` is at or after the year start. These counters are recomputed whenever one of a member's visits enters or leaves the consuming set, and whenever the operator rolls the member's year.

Rolling the year is the reset mechanism. When the operator advances a member's allotment year, `membership_year_start` is set to the current logical-clock instant, and the usage counters are recomputed; because the counters only include visits whose `held_at` is at or after the new year start, every prior-year visit drops out and `visits_used` falls back toward zero, restoring the member's free allotment for the new year.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource, and computed reads, return `200 OK`. All list and fetch reads return `200 OK`. Every request body and query string is interpreted against the field and rule narratives of §2 and §3; this table is a routing summary only and does not restate request or response shapes.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership-plans` | Create a membership plan | NetworkAdmin |
| GET | `/membership-plans` | List plans (filter by tier) | NetworkAdmin, Member, LoungeAgent |
| GET | `/membership-plans/{plan_id}` | Get a plan | NetworkAdmin, Member, LoungeAgent |
| POST | `/lounges` | Add a lounge to the directory | NetworkAdmin |
| GET | `/lounges` | Lounge directory (filter by airport_code, status) | NetworkAdmin, Member, LoungeAgent |
| GET | `/lounges/{lounge_id}` | Get a lounge with live occupancy and balance | NetworkAdmin, Member, LoungeAgent |
| GET | `/lounges/{lounge_id}/settlement-summary` | Payable and lifetime settlement figures | NetworkAdmin, LoungeAgent |
| POST | `/lounges/{lounge_id}/close` | Close a lounge (version-guarded) | NetworkAdmin |
| POST | `/lounges/{lounge_id}/reopen` | Reopen a closed lounge | NetworkAdmin |
| POST | `/lounges/{lounge_id}/sweep` | Run the housekeeping sweep at the logical clock | NetworkAdmin |
| POST | `/lounges/{lounge_id}/day-passes` | Purchase a day pass for this lounge (version-guarded) | NetworkAdmin, Member |
| POST | `/lounges/{lounge_id}/settlements/pay` | Batch-pay this lounge's payable settlements | NetworkAdmin |
| POST | `/memberships` | Enrol a member on a plan | NetworkAdmin |
| GET | `/memberships` | List members (filter by plan_id, standing) | NetworkAdmin |
| GET | `/memberships/{member_id}` | Get a member with live usage and standing | NetworkAdmin, Member |
| POST | `/memberships/{member_id}/reinstate` | Reinstate a suspended member | NetworkAdmin |
| POST | `/memberships/{member_id}/roll-year` | Advance the member's allotment year | NetworkAdmin |
| POST | `/eligibility-cards` | Issue an eligibility card to a member | NetworkAdmin |
| GET | `/eligibility-cards` | List cards (filter by member_id, active) | NetworkAdmin, Member |
| GET | `/eligibility-cards/{card_id}` | Get an eligibility card | NetworkAdmin, Member |
| POST | `/eligibility-cards/{card_id}/activate` | Make this card the member's active credential | NetworkAdmin, Member |
| POST | `/visits` | Open a hold (version-guarded on the lounge) | NetworkAdmin, LoungeAgent |
| GET | `/visits` | List visits (filter by member_id, lounge_id, eligibility_card_id, day_pass_id, status) | NetworkAdmin, Member, LoungeAgent |
| GET | `/visits/{visit_id}` | Get a visit | NetworkAdmin, Member, LoungeAgent |
| POST | `/visits/{visit_id}/check-in` | Admit a held visit | LoungeAgent |
| POST | `/visits/{visit_id}/complete` | Complete a checked-in visit | LoungeAgent |
| POST | `/visits/{visit_id}/cancel` | Cancel a held visit | Member, NetworkAdmin |
| GET | `/guests` | List guests (filter by visit_id) | NetworkAdmin, Member, LoungeAgent |
| GET | `/guests/{guest_id}` | Get a guest | NetworkAdmin, Member, LoungeAgent |
| GET | `/day-passes` | List day passes (filter by lounge_id, member_id, redeemed_visit_id, status) | NetworkAdmin, Member, LoungeAgent |
| GET | `/day-passes/{day_pass_id}` | Get a day pass | NetworkAdmin, Member, LoungeAgent |
| POST | `/day-passes/{day_pass_id}/refund` | Refund an unredeemed member-owned day pass | NetworkAdmin |
| GET | `/settlements` | List settlements (filter by lounge_id, visit_id, status) | NetworkAdmin, LoungeAgent |
| GET | `/settlements/{settlement_id}` | Get a settlement | NetworkAdmin, LoungeAgent |
| POST | `/settlements/{settlement_id}/reverse` | Reverse a payable settlement | NetworkAdmin |
| GET | `/ledger-entries` | List ledger entries (filter by member_id, visit_id, day_pass_id, kind, status) | NetworkAdmin, Member |
| GET | `/ledger-entries/{entry_id}` | Get a ledger entry | NetworkAdmin, Member |
| POST | `/shower-suites` | Add a shower suite to a lounge | NetworkAdmin |
| GET | `/shower-suites` | List shower suites (filter by lounge_id) | NetworkAdmin, Member, LoungeAgent |
| GET | `/shower-suites/{suite_id}` | Get a shower suite | NetworkAdmin, Member, LoungeAgent |
| POST | `/shower-reservations` | Book a shower suite for a checked-in visit | NetworkAdmin, Member, LoungeAgent |
| GET | `/shower-reservations` | List reservations (filter by shower_suite_id, visit_id, status) | NetworkAdmin, Member, LoungeAgent |
| GET | `/shower-reservations/{reservation_id}` | Get a shower reservation | NetworkAdmin, Member, LoungeAgent |
| POST | `/shower-reservations/{reservation_id}/cancel` | Cancel a booked reservation | Member, NetworkAdmin |
| POST | `/shower-reservations/{reservation_id}/complete` | Complete a booked reservation | LoungeAgent |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_ACTIVE_CARD` | 422 Unprocessable Entity |
| `ERR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_MEMBER_SUSPENDED` | 409 Conflict |
| `ERR_DAY_PASS_INVALID` | 422 Unprocessable Entity |
| `ERR_LOUNGE_OVERFLOW` | 409 Conflict |
| `ERR_OVER_CAPACITY` | 409 Conflict |
| `ERR_SHOWER_UNAVAILABLE` | 409 Conflict |
| `ERR_SHOWER_CONFLICT` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |

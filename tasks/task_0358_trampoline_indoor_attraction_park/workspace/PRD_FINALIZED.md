# Trampoline Indoor Attraction Park API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Trampoline Indoor Attraction Park API, the operational backbone for an indoor jump park that sells timed-session jump passes, hosts private party events, runs a tiered membership program, and enforces the safety paperwork that keeps jumpers on the courts. A single venue must reconcile several competing pressures at once: every timed session has a hard physical capacity, walk-in guests and pre-booked reservations both compete for the same seats, minors cannot jump without a guardian-cosigned waiver, and the front desk has to take money, attach grip socks and add-ons, and check people in under real-time clock constraints — all without ever overselling a session.

The system models these realities as a set of peer resources wired together by reference. A park publishes timed **session slots**; jumpers hold **jump passes** against those slots through either a reservation or a walk-in channel; families and groups book **party packages** into private rooms that draw down the same slot capacity; **members** earn discounts and included visits; and the desk files **incident reports** when something goes wrong on the court. The design goal is a single source of truth for seat accounting and money, so that capacity, refunds, membership inclusion, and safety gates all stay consistent even as bookings are created, paid, cancelled, swept, and reconciled throughout an operating day.

Because the park's clock drives check-in windows, waiver validity, cancellation refunds, and membership renewals, the API exposes an explicit logical clock that test harnesses and operators advance deliberately. All persisted timestamps are UTC.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the one-time park bootstrap and the health check must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they act. When either header is missing, malformed, or names an unrecognized role, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `ParkManager`, `FrontDesk`, `Member`, and `Guardian`.

The `ParkManager` and `FrontDesk` roles are operator roles: when `X-User-Role` is `ParkManager` or `FrontDesk`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow asks for it — for example, the manager who reviews an incident is captured in `reviewed_by_user_id` on the `IncidentReport` — but it never compares that operator identifier against any entity's `id`.

The `Member` role is entity-backed: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a `Member` compare the resource's member foreign key (the `member_id` on a `Membership`, `JumpPass`, or `Participant`, or the `host_member_id` on a `PartyBooking`) against `X-User-ID`. A `Member` acting on a membership or reservation that it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

The `Guardian` role is also entity-backed: when `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting signing `Participant`. A `Guardian` exists to e-sign a minor's waiver, so ownership for that role compares the signing participant against `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0, and it must be zero or greater. A `limit` outside 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list-based response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Derived-Field Reconciliation

Nearly every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation. The `version` field is an integer that starts at 1 and increments by 1 on every mutation; it underpins the optimistic concurrency control described in §2.6.

One resource type is deliberately leaner: a `PassAddOn` is immutable once attached, so it carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field. Every other entity (`Park`, `SessionSlot`, `Participant`, `Waiver`, `JumpPass`, `Member`, `Membership`, `PartyRoom`, `PartyPackage`, `PartyBooking`, and `IncidentReport`) carries the full set.

Several fields are *derived* rather than client-supplied — the slot's `seats_taken` and `status`, a pass's two status axes and its frozen money fields, a booking's totals, and a membership's inclusion counters are all recomputed by the server from the underlying facts. Whenever a derived field changes as a side effect of some action, that change is a mutation of its owning resource: it refreshes that resource's `updated_at` and increments its `version`. A `SessionSlot` in particular recomputes `seats_taken` and `status` whenever a pass or booking consumes or releases its capacity, and also recomputes them when the slot is read, so a fetched slot always reflects current occupancy.

### 2.5. Left-to-Right Reference Validation

Many endpoints carry one or more resource identifiers, in the URL path and again in the request body as foreign keys. The server validates these references in a fixed order: first the path identifiers, read left to right, then the body foreign keys. The request is rejected with `ERR_NOT_FOUND` against the first identifier that does not resolve to an existing resource, before any business rule for the operation is evaluated. A request that names a slot under a participant that does not exist, for instance, fails on the missing participant first.

### 2.6. Optimistic Concurrency Control on Slot Capacity

Seat capacity is the park's scarcest resource, and the only sanctioned guard against two writers each believing they hold the last seat is optimistic concurrency control keyed on the slot's `version`. Two write operations are governed by this control, and both take `expected_slot_version` as a required (non-optional) input field carrying the client's last observed `version` of the target `SessionSlot`.

Creating a `JumpPass` is the first such operation. The create must carry `expected_slot_version` equal to the target slot's current `version`. If another writer has advanced the slot's `version` since the client last read it — for example by legitimately consuming the last remaining seat — the create is rejected with `ERR_STALE_SLOT_VERSION` at HTTP 412, because the client's view of remaining capacity is stale and the create would over-subscribe the slot.

Holding the deposit on a `PartyBooking` — the step that first consumes guest seats against the slot — is the second. That request likewise must carry `expected_slot_version` matching the target slot's current `version`, and a mismatch is rejected with `ERR_STALE_SLOT_VERSION` at HTTP 412 for the same reason: a stale view of guest capacity would over-subscribe the slot. No other endpoint takes a slot version field; only these two seat-consuming writes participate in the version check.

### 2.7. Validation Ordering and the Safety-Before-Fiscal Principle

When several checks guard a single operation, they are evaluated in a fixed priority order, and the first failure determines the error returned. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced id (`ERR_NOT_FOUND`), then resource-ownership for member-scoped actions (`ERR_NOT_RESOURCE_OWNER`), then state-machine legality for the requested transition (`ERR_INVALID_STATE`). Domain-specific body validations follow. A request whose body is structurally malformed — a missing required field, an unrecognized enum value, a wrong type, or an out-of-range numeric input not covered by a more specific rule above — is rejected with the generic `ERR_VALIDATION`.

The seat-consuming endpoints make the ordering especially consequential. On those, the safety and paperwork gates are evaluated before the capacity (fiscal) gate: the waiver gate, signer rules, and the temporal check-in window all precede the optimistic concurrency `expected_slot_version` check, which in turn precedes the capacity check. Concretely, on check-in the waiver gate fires first, then the temporal window; on a seat-consuming create the `expected_slot_version` mismatch (`ERR_STALE_SLOT_VERSION`) is evaluated before the capacity test (`ERR_SLOT_CAPACITY_EXCEEDED`). The principle is that a request that fails for safety reasons should surface that failure rather than be masked by a later capacity or money check.

### 2.8. Money, Seats, and Rounding

All monetary amounts in the system are integer counts of cents. Where a calculation produces a fractional cent — a percentage discount or a deposit fraction — the result is rounded half up to a whole cent. Seat counts are whole integers. Money fields, once frozen at creation (a pass's `base_charge_cents`, a booking's `total_cents`), do not drift afterward; only the explicit payment and refund transitions move the running paid and refunded figures.

### 2.9. The Logical Park Clock

Time-gated behavior — check-in windows, waiver expiry, cancellation refund tiering, no-show sweeps, and membership renewal due dates — is evaluated against the park's current logical clock rather than wall-clock time. A `ParkManager` can advance or set this clock explicitly by supplying a target instant as `to_iso8601`. Every temporal rule in §3 reads "the park's current clock" to mean this value.

## 3. Business Logic & Workflows

### 3.1. Park Configuration and the Tunable Knobs

Everything begins with a one-time bootstrap that creates the **park**, the configuration root. A `ParkManager` supplies the park's trading `name`, and may optionally override a set of tunable knobs that govern pricing and policy across the venue. The `timezone` is an informational IANA zone (timestamps remain UTC) and defaults to `UTC`. The `grip_sock_price_cents` is the unit price of one mandatory pair of grip socks and defaults to 350 cents; it cannot be negative. The `minor_age_threshold` defaults to 18 years and must be at least 1: a participant strictly younger than this age in years is a minor. The `walkin_surcharge_cents` is a flat surcharge added to a walk-in pass and defaults to 500 cents; reservations never carry it, and it cannot be negative. The `party_deposit_pct` is the fraction of a party total taken as a non-refundable deposit and defaults to 0.25; it must be between 0 and 1 inclusive. The `cancellation_cutoff_minutes` defaults to 120 minutes and must be zero or greater; it is the boundary that separates a full-refund cancellation from a forfeit-the-pass cancellation.

Park configuration is readable by any authenticated role. The logical clock lives on the park as well, and only a `ParkManager` may move it.

### 3.2. Publishing Session Slots and Live Seat Accounting

A `ParkManager` publishes a **session slot** — a timed jump window — by naming its parent park via `park_id`, an inclusive start `starts_at`, an exclusive end `ends_at`, the `jump_capacity` (at least 1 confirmed jumper), and the `base_price_cents` that one reservation pass costs in this slot before socks, add-ons, surcharge, or member discount. The window must be valid: `ends_at` must fall strictly after `starts_at`, and a slot whose end is at or before its start is rejected with `ERR_INVALID_SLOT_WINDOW`. A freshly created slot starts with zero seats consumed and is `OPEN`.

A slot's occupancy is never stored as ground truth by the client; it is derived. The `seats_taken` figure is the number of jump passes against this slot whose `admission_status` is `RESERVED` or `CHECKED_IN` (each such pass holds exactly one seat regardless of how many sock pairs or add-ons it carries), plus the sum of `guest_count` across all party bookings against this slot whose `booking_status` is `DEPOSIT_HELD`, `CONFIRMED`, or `CHECKED_IN`. A booking in `PENDING`, `COMPLETED`, or `CANCELLED`, and a pass in `COMPLETED`, `CANCELLED`, or `NO_SHOW`, contribute zero. The slot recomputes `seats_taken` on every transition that consumes or releases capacity.

The slot's `status` is then derived from that count, with the closed flag winning over everything: if the slot is closed, its `status` is `CLOSED`; otherwise if `seats_taken` is greater than or equal to `jump_capacity`, the `status` is `FULL`; otherwise it is `OPEN`. The boolean `closed` field is false until a manager closes the slot. As seats are consumed the slot automatically flips from `OPEN` to `FULL` at the moment `seats_taken` reaches `jump_capacity` exactly; as seats are released a non-closed `FULL` slot flips back to `OPEN` the moment `seats_taken` falls below `jump_capacity`. These flips happen on their own as a side effect of seat changes, not by any direct client request.

A manager may explicitly **close** a slot, which is terminal — there is no reopen. Closing sets `closed` to true and `status` to `CLOSED`, and is permitted from either `OPEN` or `FULL` provided the slot is not already closed. Once `CLOSED`, the slot admits no further seat consumption. A slot can also be driven to `CLOSED` by a safety cascade described in §3.9.

When a slot's `ends_at` has passed on the park clock, a manager can **sweep no-shows** on that slot: every pass still sitting in `RESERVED` (its holder never checked in) is moved to `NO_SHOW`, which releases that pass's seat and recomputes the slot's `status`. A swept pass forfeits its pass price — there is no refund — but if it had consumed a membership inclusion, that one included visit is restored to the member, exactly as a cancellation would restore it.

### 3.3. Participants, Minors, and Guardians

Before anyone can jump, they exist as a **participant** under a park. Registering a participant takes the parent `park_id`, the jumper's legal `full_name` as it will appear on the waiver, and their `birthdate`. From the birthdate measured against the park's `minor_age_threshold` on the current clock, the server pins `is_minor` at creation time; this classification is fixed at creation and is not recomputed later. The optional `member_id` links the participant to a member account.

The guardian rule is strict and self-referential. A minor participant must reference a `guardian_participant_id` pointing to another participant who is a non-minor in the same park; the named guardian stands in for the minor on the waiver. An adult participant must not supply a guardian at all. Violating either side of this rule — a minor with no valid non-minor guardian in the same park, or an adult who supplied a guardian — is rejected with `ERR_GUARDIAN_REQUIRED`. Participants can be listed and filtered by `park_id`, by `member_id`, or by `guardian_participant_id` (the last being the reverse lookup that finds every minor under a given guardian).

### 3.4. Waivers and the Safety Gate

A **waiver** is the e-signed safety document that a participant must have on file before they can be admitted. Signing a waiver supplies the `participant_id` it covers, the `signed_by_participant_id` of whoever typed the signature, and the typed `signature_text`. The signer rule mirrors the guardian rule: for an adult, the `signed_by_participant_id` must equal the `participant_id` (adults self-sign); for a minor, the `signed_by_participant_id` must equal that participant's `guardian_participant_id`. A waiver whose signer violates this rule is rejected with `ERR_INVALID_SIGNER`.

On signing, the server stamps `signed_at` with the current park clock and computes `expires_at` as `signed_at` plus a validity window of 365 days; the waiver opens in `SIGNED` status. A waiver is *valid* only while it is in `SIGNED` status and the park's current clock is strictly before its `expires_at`. Signing a fresh waiver for a participant who already has a `SIGNED` waiver supersedes the prior one: the earlier waiver moves to `VOIDED`, leaving the new one as the live document. Waivers can be listed and filtered by `participant_id` or by `signed_by_participant_id`.

This document underpins the **check-in safety gate**. Admitting a reservation pass requires a valid (`SIGNED`, unexpired) waiver covering the participant, and for a minor the covering waiver is the one cosigned by their guardian. When no such waiver exists at check-in time, admission is refused with `ERR_WAIVER_MISSING_OR_EXPIRED`. This safety gate is evaluated ahead of any temporal, capacity, or fiscal consideration.

### 3.5. Jump Passes: The Two-Axis Lifecycle

A **jump pass** reserves one jumper seat in a session. Creating a pass supplies the `slot_id`, the `participant_id` holding it, the `channel` (`RESERVATION` or `WALKIN`), the number of grip-sock pairs as `sock_count`, an optional `member_id` to apply a membership, and the `expected_slot_version` that backs the optimistic concurrency check of §2.6. The `sock_count` must be at least 1 — every jumper needs socks, so a `sock_count` of 0 or less is rejected with `ERR_INVALID_QUANTITY` — and defaults to 1 when omitted.

A pass tracks two *independent* status axes that advance on their own triggers. The **admission axis**, `admission_status`, runs `RESERVED → CHECKED_IN → COMPLETED`, with the early exits `RESERVED → CANCELLED` and `RESERVED → NO_SHOW`. A reservation pass is born `RESERVED`; a walk-in pass is born already `CHECKED_IN` (the guest is at the desk). The **payment axis**, `payment_status`, runs `UNPAID → PAID` and then to either `REFUNDED` or `PARTIALLY_REFUNDED`; every pass starts `UNPAID`. Seat accounting is driven by the admission axis; refund accounting by the payment axis.

At creation the server consumes one slot seat: it adds one to the slot's `seats_taken`, recomputes the slot's `status`, and increments the slot's `version` by 1. The pass's `base_charge_cents` is frozen at this moment by the pricing rule below and never changes afterward. The two running money fields, `amount_paid_cents` and `amount_refunded_cents`, both begin at zero, and the `included_visit_consumed` flag begins false.

**Pass pricing.** The frozen `base_charge_cents` is computed in a pinned order. First the socks subtotal is the park's `grip_sock_price_cents` multiplied by `sock_count`. The surcharge is the park's `walkin_surcharge_cents` when the `channel` is `WALKIN`, and zero for a `RESERVATION`. The discountable amount is the slot's `base_price_cents` plus that surcharge — note that socks and add-ons are *never* discounted. Then one of three paths applies. If a member is applied, the membership is `ACTIVE`, and it has at least one included visit remaining (`included_visits_remaining` greater than 0), the inclusion path applies: the base-plus-surcharge is fully waived (covered by the membership) and only the socks subtotal is billed, so `base_charge_cents` equals the socks subtotal, and the pass is marked to consume one inclusion when it is paid. If a member is applied and the membership is `ACTIVE` but no included visits remain, the discount path applies: the membership's tier discount percentage is taken off the discountable amount (rounded half up to whole cents) and `base_charge_cents` is that discounted discountable amount plus the full socks subtotal — no inclusion is consumed. Otherwise `base_charge_cents` is simply the discountable amount plus the socks subtotal.

**Add-ons.** A pass can carry **add-on** line items, attached one at a time. Attaching supplies the `sku` — one of `ARM_SLEEVES`, `LOCKER`, `FAST_PASS`, or `PHOTO_PKG` — and a `quantity` of at least 1 (a quantity below 1 is rejected with `ERR_INVALID_QUANTITY`). The server resolves the `unit_price_cents` from its own catalog and ignores any client-supplied price: `ARM_SLEEVES` is 800 cents, `LOCKER` is 500 cents, `FAST_PASS` is 1500 cents, and `PHOTO_PKG` is 2500 cents. The `line_total_cents` is the resolved unit price multiplied by `quantity`. Each add-on references its pass through `jump_pass_id`, and a pass's add-ons can be listed back through that reference.

### 3.6. Paying, Checking In, Completing, and Cancelling a Pass

**Paying.** Collecting payment advances the payment axis from `UNPAID` to `PAID`. Payment is allowed only when `payment_status` is `UNPAID`, and only when the pass is not in `admission_status` `CANCELLED` or `NO_SHOW`. A second pay attempt on a pass that is already `PAID`, `REFUNDED`, or `PARTIALLY_REFUNDED` is rejected with `ERR_ALREADY_PAID`. On payment, `amount_paid_cents` is set to `base_charge_cents` plus the sum of every attached add-on's `line_total_cents`, and `payment_status` becomes `PAID`. If the pass was marked at pricing time to consume membership inclusion, this is the moment it does so: `included_visit_consumed` becomes true and the membership's `included_visits_remaining` is decremented by 1.

**Checking in.** Admitting a reservation advances the admission axis from `RESERVED` to `CHECKED_IN`, and is restricted to a `FrontDesk` operator. It requires four things, evaluated as a unit: the pass's `channel` is `RESERVATION`; a valid waiver covers the participant (and, for a minor, the guardian-cosigned waiver) per §3.4, else `ERR_WAIVER_MISSING_OR_EXPIRED`; the pass is already `PAID`; and the park's current clock falls within the check-in window. The seat was already held since the pass was reserved, so check-in does not change `seats_taken`. A walk-in pass is born `CHECKED_IN` and so never passes through this transition.

**The check-in window.** Admission is permitted only when the park's current clock is at or after the slot's `starts_at` minus the check-in lead time of 30 minutes, and strictly before the slot's `ends_at`. A check-in that is too early (before that lead-time boundary) or at/after the slot end is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`. The same window governs party check-in.

**Completing.** Marking a `CHECKED_IN` pass as `COMPLETED` is a `FrontDesk` action allowed only from `admission_status` `CHECKED_IN`. Completion releases the seat: the slot's `seats_taken` drops by 1 and the slot's `status` is recomputed (a `FULL` slot can fall back to `OPEN` if its occupancy drops below capacity).

**Cancelling.** A reservation pass can be **cancelled** by a `FrontDesk` operator or by the owning `Member`, but only while it is still `RESERVED` (a walk-in pass, never `RESERVED`, can never reach this transition). Cancellation sets `admission_status` to `CANCELLED`, releases the seat (decrement `seats_taken`, recompute `status`), and, if the pass had consumed a membership inclusion, restores one `included_visits_remaining` to the membership. If the pass had been paid, the cancellation refund rule runs and writes the refund outcome onto the payment axis.

**Cancellation refund.** The refund tier turns on how far ahead of the slot the cancellation lands. Compute `minutes_before` as the whole number of minutes from the park's current clock until the slot's `starts_at`. The socks-and-add-ons figure is the park's `grip_sock_price_cents` multiplied by the pass's `sock_count`, plus the sum of every add-on's `line_total_cents`. If `minutes_before` is at least the park's `cancellation_cutoff_minutes` (the boundary is inclusive), the cancellation is within the cutoff and earns a full refund: the refund equals everything actually paid (`amount_paid_cents`) and `payment_status` becomes `REFUNDED`. Otherwise the cancellation is late: the pass price is forfeited and only the socks-and-add-ons portion is refundable, so the refund is the lesser of `amount_paid_cents` and that socks-and-add-ons figure; `payment_status` becomes `PARTIALLY_REFUNDED` if that refund is strictly less than `amount_paid_cents`, or `REFUNDED` if it turns out nothing beyond socks-and-add-ons was actually paid. In either case the refunded amount is added to `amount_refunded_cents` and subtracted from `amount_paid_cents`.

Passes can be listed and filtered by `slot_id`, by `participant_id`, or by `member_id`, and the full set of passes for a slot can be retrieved as a reverse lookup.

### 3.7. Members, Tiers, and the Renewal Cycle

A **member** is an account holder under a park, created with the parent `park_id`, a login `email`, and the holder's `full_name`. The email must be unique within the park, compared case-insensitively; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. Members can be listed and filtered by `park_id`.

A member subscribes to a **membership** by naming the owning `member_id`, a `tier` (`BRONZE`, `SILVER`, or `GOLD`), and a `cycle_anchor_at` instant that anchors the monthly billing cadence. Each tier fixes three numbers — a monthly fee, a discount percentage, and an included-visit allotment per cycle: `BRONZE` is 2900 cents a month, a 10% (0.10) discount, and 2 included visits; `SILVER` is 4900 cents, 15% (0.15), and 4 included visits; `GOLD` is 7900 cents, 25% (0.25), and 8 included visits. At creation the membership opens `ACTIVE`, its `current_cycle_index` is 0, and `included_visits_remaining` is set to the tier's allotment. Only an `ACTIVE` membership grants its discount and included visits.

Billing cycles are 30-day windows measured from the `cycle_anchor_at`: the cycle with index *k* spans from the anchor plus *k* times 30 days up to the anchor plus *(k+1)* times 30 days, and the current cycle is whichever such window covers the park clock. The membership's lifecycle is cyclic. **Renewal** carries an `outcome` of `SUCCEEDED` or `FAILED`. A renewal from `ACTIVE` may only run once the park's current clock has reached the next cycle boundary — the anchor plus `current_cycle_index` plus 1, times 30 days; a premature renewal from `ACTIVE` is rejected with `ERR_RENEWAL_NOT_DUE`. A successful renewal from `ACTIVE` advances `current_cycle_index` by 1 and resets `included_visits_remaining` to the tier allotment (the membership stays `ACTIVE`). A failed renewal from `ACTIVE` moves the membership to `PAST_DUE` and freezes inclusion by setting `included_visits_remaining` to 0.

A `PAST_DUE` membership is **cured** by a successful renewal, which advances `current_cycle_index` by 1, sets the status back to `ACTIVE`, and resets `included_visits_remaining` to the tier allotment. From either `ACTIVE` or `PAST_DUE`, a membership can be **cancelled** to the terminal `CANCELLED` state; cancelling from `ACTIVE` also zeroes `included_visits_remaining`. A member may renew or cancel their own membership; a manager may act on any. A membership's memberships can be retrieved per member as a reverse lookup. Any renewal or cancellation requested from a state the rule does not permit is rejected with `ERR_INVALID_STATE`.

### 3.8. Party Rooms, Packages, and the Booking Fork

The park hosts groups in private **party rooms** and prices them with **party packages**, both manager-defined. A room is created with its parent `park_id`, a display `name`, a `room_capacity` (at least 1 guest), and a `turnover_buffer_minutes` cleaning buffer that defaults to 30 minutes and cannot be negative. A package is created with its parent `park_id`, a marketing `name`, a `per_guest_cents` price, a flat `base_room_fee_cents` host fee, and a `min_guests` floor of at least 1. Rooms and packages are each listable and filterable by `park_id`, and a room's bookings are retrievable as a reverse lookup.

A **party booking** is created in `PENDING` against a `package_id`, a `room_id`, and a `slot_id`, with a `guest_count` and an optional `host_member_id`. The `guest_count` must be at least the package's `min_guests` and at most the room's `room_capacity`; a count outside that band is rejected with `ERR_GUEST_COUNT_OUT_OF_RANGE`. Creating the booking freezes its `total_cents` but does not yet hold any seats or the room.

**Party pricing.** The frozen `total_cents` is built in a pinned order with the member discount applied before the room fee is added. The per-guest subtotal is the package's `per_guest_cents` multiplied by `guest_count`. If a host member is applied and that membership is `ACTIVE`, a guest discount equal to the per-guest subtotal times the membership's tier discount percentage (rounded half up to whole cents) is subtracted from the per-guest subtotal — the discount touches only the per-guest portion, never the room fee. The `total_cents` is then the package's `base_room_fee_cents` plus that (possibly discounted) per-guest subtotal. The `deposit_cents` is pinned later, at the hold-deposit step, as `total_cents` times the park's `party_deposit_pct`, rounded half up to whole cents.

The booking lifecycle is a branching fork that turns on the deposit. **Holding the deposit** moves the booking from `PENDING` to `DEPOSIT_HELD` and is the step that first consumes capacity. It requires that the slot is not `CLOSED` and that the slot's `seats_taken` plus this booking's `guest_count` does not exceed the slot's `jump_capacity` (else `ERR_SLOT_CAPACITY_EXCEEDED`); that the room interval — the window from the slot's `starts_at` to its `ends_at` — does not collide with any other non-`CANCELLED` booking on the same room, where the room's `turnover_buffer_minutes` must separate two bookings on each side (else `ERR_ROOM_CONFLICT`); and that the supplied `expected_slot_version` matches the slot's `version` (else `ERR_STALE_SLOT_VERSION`, per §2.6). On success the booking becomes `DEPOSIT_HELD`, the `deposit_cents` is computed and `balance_paid_cents` is set equal to it, the slot's `seats_taken` grows by `guest_count`, the slot's `status` is recomputed, and the slot's `version` is incremented by 1.

From `DEPOSIT_HELD`, **confirming** the booking sets `balance_paid_cents` to the full `total_cents` and moves it to `CONFIRMED`. A `CONFIRMED` booking is **checked in** by a `FrontDesk` operator (moving to `CHECKED_IN`) only when the park's current clock is within the same check-in window described in §3.6, else `ERR_OUTSIDE_CHECKIN_WINDOW`. A `CHECKED_IN` booking is **completed** by `FrontDesk` to `COMPLETED`, which releases the guest seats: the slot's `seats_taken` drops by `guest_count`, the slot's `status` is recomputed, and the slot's `version` is incremented by 1.

**Cancelling** a booking forks on its current state. A `PENDING` booking cancels cleanly: it goes to `CANCELLED` with no seats held, no deposit forfeited, and no change to the slot. From `DEPOSIT_HELD`, cancelling goes to `CANCELLED`, releases the held guest seats (decrement `seats_taken` by `guest_count`, recompute `status`, increment the slot's `version` by 1), and forfeits the deposit — `balance_paid_cents` stays at `deposit_cents` and nothing is refunded. From `CONFIRMED`, cancelling likewise goes to `CANCELLED` and releases the guest seats (decrement, recompute, increment `version`), but here the balance beyond the deposit is returned: the amount returned is `total_cents` minus `deposit_cents`, and `balance_paid_cents` settles back to `deposit_cents`, the deposit again being forfeited. Bookings can be listed and filtered by `package_id`, `room_id`, `slot_id`, or `host_member_id`, and a slot's bookings are retrievable as a reverse lookup.

### 3.9. Incident Reports and the Severe-Incident Cascade

When something happens on the court, a `FrontDesk` operator or a `ParkManager` files an **incident report** against the affected jumper's pass. Filing supplies the `park_id`, the `jump_pass_id` of the affected pass (which must be in `admission_status` `CHECKED_IN` at filing time), a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, and a free-text `narrative`. A new report opens in `FILED`, and its `reviewed_by_user_id` is empty until a manager handles it.

Severity carries a safety cascade. Filing a `SEVERE` incident force-closes the slot of the affected pass *at file time* (not at sign-off): the pass's `SessionSlot` is driven to `CLOSED` — `closed` becomes true and `status` becomes `CLOSED` — provided that slot is not already closed, halting all further seat consumption in that session. `MINOR` and `MODERATE` filings carry no such cascade.

A filed report follows a branching review path owned entirely by the `ParkManager`. **Reviewing** a `FILED` report moves it to `REVIEWED` and stamps `reviewed_by_user_id` with the acting manager's operator id. **Signing off** a `REVIEWED` report moves it to the terminal `SIGNED_OFF`. Alternatively, a `FILED` report that was filed in error can be **voided** straight to the terminal `VOIDED`. Any review, sign-off, or void requested from a state the path does not allow is rejected with `ERR_INVALID_STATE`. Incident reports can be listed and filtered by `park_id` or by `jump_pass_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-machine transitions and the clock-setting capability — return a `200 OK` status code. All list and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/park` | Bootstrap a park (one-time config root) | ParkManager |
| GET | `/park/{id}` | Read park config | ParkManager, FrontDesk, Member |
| POST | `/park/_clock/set_current_utc` | Set the park's current UTC clock | ParkManager |
| POST | `/park/slots` | Create a timed jump session slot | ParkManager |
| GET | `/park/slots/{id}` | Read a slot with derived occupancy | ParkManager, FrontDesk, Member |
| GET | `/park/slots` | List slots | ParkManager, FrontDesk, Member |
| POST | `/park/slots/{id}/close` | Close a slot (terminal) | ParkManager |
| POST | `/park/slots/{id}/sweep-no-shows` | Sweep reserved passes to no-show after slot end | ParkManager |
| GET | `/park/slots/{id}/jump-passes` | List all jump passes for a slot | ParkManager, FrontDesk, Member |
| GET | `/park/slots/{id}/party-bookings` | List all party bookings for a slot | ParkManager, FrontDesk, Member |
| POST | `/park/participants` | Register a participant | FrontDesk, Member, ParkManager |
| GET | `/park/participants/{id}` | Read a participant | ParkManager, FrontDesk, Member |
| GET | `/park/participants` | List participants | ParkManager, FrontDesk, Member |
| GET | `/park/participants/{id}/waivers` | List all waivers covering a participant | ParkManager, FrontDesk, Member |
| POST | `/park/waivers` | E-sign a waiver | FrontDesk, Member, Guardian, ParkManager |
| GET | `/park/waivers/{id}` | Read a waiver | ParkManager, FrontDesk, Member |
| GET | `/park/waivers` | List waivers | ParkManager, FrontDesk, Member |
| POST | `/park/jump-passes` | Create a jump pass | FrontDesk, Member |
| GET | `/park/jump-passes/{id}` | Read a jump pass | ParkManager, FrontDesk, Member |
| GET | `/park/jump-passes` | List jump passes | ParkManager, FrontDesk, Member |
| POST | `/park/jump-passes/{id}/pay` | Collect payment for a pass | FrontDesk, Member |
| POST | `/park/jump-passes/{id}/check-in` | Check a reservation pass in | FrontDesk |
| POST | `/park/jump-passes/{id}/complete` | Complete a checked-in pass | FrontDesk |
| POST | `/park/jump-passes/{id}/cancel` | Cancel a reserved pass | FrontDesk, Member |
| POST | `/park/jump-passes/{id}/add-ons` | Attach an add-on to a pass | FrontDesk, Member |
| GET | `/park/jump-passes/{id}/add-ons` | List all add-ons on a pass | ParkManager, FrontDesk, Member |
| POST | `/park/members` | Create a member account | FrontDesk, ParkManager |
| GET | `/park/members/{id}` | Read a member | ParkManager, FrontDesk, Member |
| GET | `/park/members` | List members | ParkManager, FrontDesk |
| GET | `/park/members/{id}/memberships` | List all memberships for a member | ParkManager, FrontDesk, Member |
| POST | `/park/memberships` | Subscribe a member to a tier | FrontDesk, Member, ParkManager |
| GET | `/park/memberships/{id}` | Read a membership | ParkManager, FrontDesk, Member |
| POST | `/park/memberships/{id}/renew` | Run a renewal cycle | Member, ParkManager |
| POST | `/park/memberships/{id}/cancel` | Cancel a membership (terminal) | Member, ParkManager |
| POST | `/park/rooms` | Create a private party room | ParkManager |
| GET | `/park/rooms/{id}` | Read a room | ParkManager, FrontDesk, Member |
| GET | `/park/rooms` | List rooms | ParkManager, FrontDesk, Member |
| GET | `/park/rooms/{id}/party-bookings` | List all party bookings for a room | ParkManager, FrontDesk, Member |
| POST | `/park/packages` | Create a party package | ParkManager |
| GET | `/park/packages/{id}` | Read a package | ParkManager, FrontDesk, Member |
| GET | `/park/packages` | List packages | ParkManager, FrontDesk, Member |
| POST | `/park/party-bookings` | Create a party booking (PENDING) | FrontDesk, Member |
| GET | `/park/party-bookings/{id}` | Read a party booking | ParkManager, FrontDesk, Member |
| GET | `/park/party-bookings` | List party bookings | ParkManager, FrontDesk, Member |
| POST | `/park/party-bookings/{id}/hold-deposit` | Hold the deposit (consumes guest seats) | FrontDesk, Member |
| POST | `/park/party-bookings/{id}/confirm` | Confirm a deposit-held booking | FrontDesk, Member |
| POST | `/park/party-bookings/{id}/check-in` | Check a confirmed party in | FrontDesk |
| POST | `/park/party-bookings/{id}/complete` | Complete a checked-in party | FrontDesk |
| POST | `/park/party-bookings/{id}/cancel` | Cancel a booking | FrontDesk, Member |
| POST | `/park/incidents` | File an incident report | FrontDesk, ParkManager |
| GET | `/park/incidents/{id}` | Read an incident report | ParkManager, FrontDesk |
| GET | `/park/incidents` | List incident reports | ParkManager, FrontDesk |
| POST | `/park/incidents/{id}/review` | Review a filed incident | ParkManager |
| POST | `/park/incidents/{id}/sign-off` | Sign off a reviewed incident | ParkManager |
| POST | `/park/incidents/{id}/void` | Void an erroneous filed incident | ParkManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_GUARDIAN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_SIGNER` | 422 Unprocessable Entity |
| `ERR_WAIVER_MISSING_OR_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 422 Unprocessable Entity |
| `ERR_ROOM_CONFLICT` | 409 Conflict |
| `ERR_INVALID_SLOT_WINDOW` | 422 Unprocessable Entity |
| `ERR_GUEST_COUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_STALE_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ALREADY_PAID` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_RENEWAL_NOT_DUE` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |

# Mini-Golf & Go-Kart Track API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Mini-Golf & Go-Kart Track API, the back-of-house system that runs a multi-attraction entertainment venue. A single property typically operates a fleet of go-kart heats running on a lane-limited track alongside a set of mini-golf courses sold in timed tee sessions, and the system must hold both kinds of capacity, the pricing attached to each, and the steady churn of walk-in and reservation traffic in one consistent ledger of truth.

The operational reality the API models is one of scarce, perishable slots. Lanes on a heat and player spots in a tee session exist only for a fixed window of time, so the system has to allocate them precisely, waitlist the overflow, and promote waiting guests the instant capacity is released — all while honouring height and waiver safety gates, combo-pass and arcade-card stored value, party-package deposits, and the ever-present possibility that weather forces the whole venue to pause. The remainder of this document describes the entities, the state machines that govern their lifecycles, the pricing and capacity calculations, the validation order, and the HTTP surface that exposes them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or `X-User-Role` does not name a role the system recognises, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognises exactly three roles: `OpsManager`, `Cashier`, and `Guest`. When a recognised role attempts an operation that its permissions do not cover, the request is rejected with `ERR_FORBIDDEN`.

The three roles differ in how `X-User-ID` is interpreted and in what they may do. When `X-User-Role` is `OpsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept it for audit purposes but never compares it to any entity's `id`. The `OpsManager` is the operations manager: it controls venue posture (including weather closure), creates and manages attractions, pricing plans, heats, and tee sessions, and may act on any booking or party group as an operational override. When `X-User-Role` is `Cashier`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. A `Cashier` works the front desk: walk-ins, check-ins, no-shows, arcade redemptions, and reservation assistance on behalf of any guest; a `Cashier` cannot change venue posture, attractions, pricing, or slot inventory.

When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest` entity. Ownership checks on any resource that references a `Guest` compare that resource's owning guest field to `X-User-ID`: a `Guest` may only read and act on resources it owns, where ownership is established through the `guest_id` of a booking, combo pass, waiver, or wallet, or through the `host_guest_id` of a party group. A `Guest` attempting to read or mutate another guest's resource is rejected with `ERR_FORBIDDEN`, and a `Guest` may never manage inventory, pricing, posture, or other guests' resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. A `limit` outside the 1–100 range, a negative `offset`, or a `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses carry the pagination bookkeeping in the `meta` object of the envelope, specifically the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. Common Resource Properties

Every primary resource — `Venue`, `Attraction`, `PricingPlan`, `Heat`, `TeeSession`, `Guest`, `Wallet`, `ComboPass`, `PartyGroup`, and `Booking` — carries a common set of system-managed fields. The `id` is a server-minted UUID used purely for identity; it carries no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation, and `updated_at` is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation of the resource — including mutations that arise only as a cascade or as the recomputation of a derived field. The `version` field is an integer that starts at 1 on creation and increases by exactly one on every mutation; it is the basis of optimistic concurrency control described in §2.8.

The `Waiver` resource is the sole exception. A waiver is immutable once written, so it carries only `id` and `created_at`; it has no `updated_at` field and no `version` field. Implementers must not synthesise either field for waivers.

Derived and computed fields are first-class members of their resource and are returned in responses just like input fields. On a `Venue` this includes `open_slot_count`; on a `Heat`, `lanes_committed` and `lanes_available`; on a `TeeSession`, `players_committed` and `players_available`; on a `Guest`, the derived `waiver_status`; on a `Wallet`, `arcade_card_balance_cents` and `total_loaded_cents`; on a `ComboPass`, `credits_redeemed` and `credits_remaining`; on a `PartyGroup`, `units_consumed`; and on a `Booking`, `gross_price_cents`, `credits_applied`, and `cash_due_cents`. When a derived field changes value as the result of an operation, that recomputation is itself a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Nested Reference Resolution and Validation Order

Although every collection in this system is addressed at the top level (a booking is reached at its own identifier, not nested beneath a venue), a single request commonly references several resources at once through its body — a booking, for example, names a venue, a guest, a slot, and a pricing plan. The system resolves these references left-to-right in dependency order: the venue first, then the attraction or slot, then the booking, group, or pass that hangs off them. The first referenced resource that does not exist causes the request to be rejected with `ERR_NOT_FOUND` before any deeper reference or business rule is evaluated. This ordering guarantees that a missing container is always reported before a rule that assumes the container is present.

### 2.6. Precision, Rounding, and Monetary Representation

All money in this system is held as an integer number of cents — `base_price_cents`, `peak_surcharge_cents`, `deposit_cents`, `amount_cents`, `arcade_card_balance_cents`, `total_loaded_cents`, `gross_price_cents`, and `cash_due_cents` are all integer-cent quantities. Wherever a calculation produces a fractional cent — applying a group discount, prorating a combo-credit value, or awarding a loyalty bonus — the result is rounded once, at the end of that calculation, using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger magnitude). Pricing in particular sums all of its per-unit components first and rounds the single final total; it never rounds each unit and then sums. Counts of lanes, players, credits, and units are whole integers throughout and are never rounded because they are never fractional.

### 2.7. Posture, Cascades, and Hierarchical Consistency

The venue's `posture` is the master gate for the whole property, and every other lifecycle-bearing resource — heats, tee sessions, bookings, combo passes, and party groups — tracks its own lifecycle in a `status` field. When the venue is not open, child operations are constrained, and several venue-level transitions reach down and reshape their children in a single atomic step. Whenever such a cascade fires, every entity it touches has its `updated_at` refreshed and its `version` incremented, exactly as if it had been mutated directly; the venue itself also advances its `version`. Capacity counters and other derived fields are recomputed as part of the same operation so that a reader never observes a parent and child that disagree. The specific cascades — which slots close, which bookings cancel, which bookings survive, and which deposits refund — are described with the lifecycles in §3, because each cascade only makes sense in the context of the transition that triggers it.

### 2.8. Optimistic Concurrency Control

Two write paths in this system are guarded by optimistic concurrency control, and on those two paths the version field is a required input, not an optional one. Confirming a booking requires the caller to supply the current `version` of the slot the booking occupies: `expected_heat_version` when the booking occupies a heat, or `expected_tee_session_version` when it occupies a tee session. If the supplied value does not match the slot's current `version` — because another writer has confirmed a booking that consumed lanes or player spots and advanced the slot's version since the caller last read it — the confirm is rejected with `ERR_STALE_SLOT_VERSION` at HTTP 412, protecting the caller from acting on a stale view of available capacity and over-committing the slot.

Confirming a party group is guarded the same way: the request must carry `expected_group_version` matching the group's current `version`. If another writer has added or removed a member booking since the caller last read the group — advancing the group's version and changing its `units_consumed` — the confirm is rejected with `ERR_STALE_GROUP_VERSION` at HTTP 412, because the confirmation decision was made against a member set that no longer reflects reality. No other endpoint takes a version field; endpoints not named here perform no OCC check.

### 2.9. Capacity, Stored Value, and Safety Invariants

Three running quantities must never go negative and are clamped at zero by construction. A heat's `lanes_available` is its `lane_capacity` minus its committed lanes, floored at zero; a tee session's `players_available` is its `party_slot_capacity` minus its committed players, floored at zero; and a combo pass's `credits_remaining` is its `total_credits` minus its `credits_redeemed`, floored at zero. Likewise, a booking's `cash_due_cents` is never negative. Arcade-card debits — redemptions and party deposits — may never drive the wallet's `arcade_card_balance_cents` below zero; an attempt to do so is refused rather than clamped. These invariants are restated, with their exact triggers, alongside the workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Venue and Its Inventory

A property begins with a `Venue`, which only an `OpsManager` may create by supplying a `name` and optionally a `timezone` (an IANA zone such as `America/New_York`, defaulting to `America/New_York` when omitted). A newly created venue starts in `posture` `OPEN`, with `open_slot_count` at zero, `version` at 1, and its `weather_hold_reason` null. Each venue also carries a `current_utc` server clock, which on creation is set to the creation wall-clock time. Because every time-gated check in the system — waiver expiry, check-in windows, no-show eligibility — reads this clock rather than real wall time, an `OpsManager` may drive it forward for testing through a dedicated clock-setting capability that accepts a single `to_iso8601` instant and writes it onto the venue's `current_utc`; setting the clock causes each guest's `waiver_status` to be re-derived against the new instant on the next read. Setting the clock is a test-driving system action rather than a domain mutation: it overwrites `current_utc` but does not refresh the venue's `updated_at` or increment its `version`. The supplied `to_iso8601` must parse as a valid ISO 8601 instant, and a value that does not is rejected with `ERR_INVALID_REQUEST`. The `open_slot_count` is a live count of the heats and tee sessions on the venue currently in `OPEN` status.

Against an open venue, an `OpsManager` builds inventory. An `Attraction` is created with a `venue_id`, a `name`, a `kind` of `GO_KART`, `MINI_GOLF`, or `ARCADE`, an optional `min_height_cm` (the minimum guest height the attraction will admit, defaulting to 0 meaning no restriction), and an optional `lane_count` (the number of lanes a go-kart attraction runs per heat, defaulting to 0 and ignored for the other kinds). Attractions are created `ACTIVE` and remain `ACTIVE` in this version of the system. A `PricingPlan`, also venue-scoped, is created with a `venue_id`, a `name`, a `mode`, and a `base_price_cents`; it too is created `ACTIVE` and stays `ACTIVE`. The `mode` is one of `PER_ROUND` (a mini-golf round price), `PER_HEAT` (a go-kart heat price), or `WRISTBAND` (a flat per-player band price). Three further plan inputs shape pricing: `peak_surcharge_cents`, a flat per-unit amount added when the slot's window is peak (default 0); `group_discount_pct`, a decimal fraction between 0 and 0.5 applied to large parties (default 0); and `wristband_unit_cap`, the maximum number of activity units a single wristband covers in one booking, where 0 means unlimited and the field is ignored for non-wristband plans (default 0).

### 3.2. Scheduling Slots: Heats and Tee Sessions

Go-kart capacity is sold as a `Heat`. An `OpsManager` creates a heat with a `venue_id`, an `attraction_id`, a `start_utc` (inclusive start), an `end_utc` (exclusive end), and an optional `window` of `OFF_PEAK` or `PEAK` (default `OFF_PEAK`). Both `start_utc` and `end_utc` must parse as valid ISO 8601 instants, and `end_utc` must be strictly after `start_utc`; a malformed instant or an `end_utc` that is at or before `start_utc` is rejected with `ERR_INVALID_REQUEST`. The named attraction must be of kind `GO_KART`; if it is not, creation is rejected with `ERR_ATTRACTION_KIND_MISMATCH`. At creation the heat snapshots the attraction's current `lane_count` into its own `lane_capacity`, and it starts in `SCHEDULED` status with `lanes_committed` at zero and `lanes_available` equal to `lane_capacity`. Heats use **half-open interval** semantics on the same attraction: a new heat's interval is `[start_utc, end_utc)`, and it collides with an existing non-terminal heat (one in `SCHEDULED`, `OPEN`, or `CLOSED`; cancelled heats are ignored) when the new start is before the existing end and the existing start is before the new end. Because the interval is half-open, exact adjacency — where one heat's `end_utc` equals the next heat's `start_utc` — does not collide and is permitted. Any inner overlap is rejected with `ERR_SLOT_OVERLAP`.

Mini-golf capacity is sold as a `TeeSession`, created by an `OpsManager` with a `venue_id`, an `attraction_id`, a `start_utc` (inclusive start), an `end_utc` (inclusive end), a `party_slot_capacity` (the maximum total players across all bookings in the session), and an optional `window` of `OFF_PEAK` or `PEAK` (default `OFF_PEAK`). Both `start_utc` and `end_utc` must parse as valid ISO 8601 instants, and because the session's end is inclusive, `end_utc` must be at or after `start_utc` (an equal start and end being permitted); a malformed instant or an `end_utc` before `start_utc` is rejected with `ERR_INVALID_REQUEST`. The named attraction must be of kind `MINI_GOLF`, else `ERR_ATTRACTION_KIND_MISMATCH`. A tee session starts `SCHEDULED` with `players_committed` at zero and `players_available` equal to `party_slot_capacity`. Tee sessions do **not** use half-open semantics; instead they enforce a **turnover buffer**. Two sessions on the same attraction must be separated by a clear gap of at least ten minutes so staff can reset the course between groups. Concretely, for a candidate session and each existing non-terminal session on the attraction, the system measures the gap: if the candidate starts at or after the existing session ends, the gap is the minutes from the existing end to the candidate start; if the existing session starts at or after the candidate ends, the gap is the minutes from the candidate end to the existing start; and if the two intervals interpenetrate, there is no gap at all. When that gap is less than ten minutes the creation is rejected with `ERR_SLOT_OVERLAP`. A consequence worth stating plainly: two sessions that merely abut, leaving a gap of exactly zero minutes, are rejected, because a zero gap is below the ten-minute buffer — this is the deliberate point of difference from heats, where abutting is fine. As with heats, only non-terminal sessions (`SCHEDULED`, `OPEN`, `CLOSED`) participate in the check and cancelled sessions are ignored.

A scheduled slot does not accept bookings until it is opened. An `OpsManager` opens a heat or a tee session, advancing it from `SCHEDULED` to `OPEN`; this is permitted only when the slot is currently `SCHEDULED` and the venue's `posture` is `OPEN`, and it bumps the slot's `version`. Opening a slot whose venue is not open is refused under the posture gate with `ERR_VENUE_NOT_OPEN`, and opening a slot that is not in `SCHEDULED` is refused as an invalid state transition with `ERR_INVALID_STATE`. Manually closing an open slot advances it from `OPEN` to `CLOSED`: on a manual close, every `CONFIRMED` and `CHECKED_IN` booking on that slot is moved to `COMPLETED`, while every `WAITLISTED` booking on it is moved to `CANCELLED` (no promotion happens, since the slot is going away), and the slot's `version` increments. Cancelling a scheduled slot advances it from `SCHEDULED` to `CANCELLED`, moving all of its non-terminal bookings — those in `HOLD` or `WAITLISTED` — to `CANCELLED` and bumping the slot's `version`. Close requires the slot to be `OPEN` and cancel requires it to be `SCHEDULED`; a request against any other state is rejected with `ERR_INVALID_STATE`. The terminal statuses `CLOSED` and `CANCELLED` admit no further transitions.

### 3.3. Guests, Waivers, and the Safety Gate

Anyone — an `OpsManager`, a `Cashier`, or a self-registering `Guest` — may register a `Guest` with a `full_name`, a `height_cm`, and an optional `birthdate` (an ISO date used only to derive whether the guest is a minor). A new guest starts with `waiver_status` `NONE`, and registering a guest also auto-creates an empty `Wallet` for that guest, carrying the new guest's `guest_id`, an `arcade_card_balance_cents` of zero, and a `total_loaded_cents` of zero.

Safety at this venue rests on two gates that a booking must clear before it can confirm: height and waiver. The height gate compares the guest's `height_cm` against the owning attraction's `min_height_cm`; a guest whose height is below the attraction's minimum is turned away from confirming with `ERR_HEIGHT_REQUIREMENT`.

The waiver gate rests on the `Waiver` resource and the guest's derived `waiver_status`. Signing a waiver for a guest records its `guest_id`, stamps `signed_at` with the venue's current clock value at the moment of signing, and computes `expires_at` as exactly 365 days after `signed_at`; because a guest is not bound to any single venue, the clock used for `signed_at` is the most-advanced `current_utc` among all existing venues, falling back to real wall-clock time only when no venue exists yet; a waiver remains valid only while the venue's `current_utc` is strictly before its `expires_at`. A waiver also carries an optional `guardian_name`. A guest is treated as a minor when their age at the time of signing — derived from `birthdate` against `signed_at` — is under 18 years; a minor's waiver must carry a `guardian_name`, and an attempt to sign a minor's waiver without one is rejected with `ERR_WAIVER_REQUIRED`. The guest's `waiver_status` is always derived from the latest waiver, never stored independently: take the waiver with the greatest `signed_at` (breaking ties by `created_at` ascending and taking the last), and report `NONE` when the guest has no waiver, `EXPIRED` when the venue's `current_utc` is at or after that waiver's `expires_at`, and `SIGNED` otherwise. The `current_utc` used for this derivation on a standalone guest read is again the most-advanced `current_utc` among all venues (with no venue present, the status remains `SIGNED` since there is no clock at or past the expiry); at booking confirm the derivation instead uses the booking's own venue clock. A booking whose guest does not hold a `SIGNED`, unexpired waiver at confirm time is rejected with `ERR_WAIVER_REQUIRED`.

### 3.4. The Arcade Wallet and Loyalty Bonus

Each guest's `Wallet` is the stored-value account behind the arcade card. Its `arcade_card_balance_cents` is the spendable balance — debited by arcade redemptions and by party-package deposits, credited by top-ups and by the refund of a draft party deposit — and its `total_loaded_cents` is the lifetime sum of top-up amounts, which deliberately excludes any loyalty bonus credited on top of those amounts. Topping up a wallet accepts an `amount_cents` and increases both the balance and the lifetime total, while loading value at the arcade through a redemption accepts an `amount_cents` and decreases only the balance. Each wallet mutation bumps the wallet's `version`.

A loyalty bonus rewards the single top-up that carries a guest's lifetime loading across the 5000-cent threshold. The bonus is evaluated on the running history of top-ups taken in chronological order by `created_at`. For a given top-up, if the guest's `total_loaded_cents` before this top-up is below 5000 cents and the total after adding this top-up's amount reaches or exceeds 5000 cents, then this is the threshold-crossing top-up and it earns a bonus equal to ten percent of that single top-up's amount, rounded half up; the bonus is credited to `arcade_card_balance_cents` on top of the amount itself but is never added to `total_loaded_cents`. Only the one crossing top-up earns the bonus — it is not applied retroactively to earlier top-ups and not applied to later ones, and because eligibility depends on the cumulative `total_loaded_cents` standing before each top-up, the order in which top-ups are processed determines which top-up earns it. Redemptions and party deposits always check the live `arcade_card_balance_cents` at the moment they are applied: a redemption or deposit whose amount exceeds the current balance is rejected outright with `ERR_INSUFFICIENT_CARD_BALANCE`, never partially applied.

### 3.5. Combo Passes

A `ComboPass` is a block of pre-purchased activity credits, where one credit covers one activity unit. A pass is created against a guest with that guest's `guest_id` and a `total_credits` count of at least one (a `total_credits` below 1 is rejected with `ERR_INVALID_REQUEST`), and it opens `ACTIVE` with `credits_redeemed` at zero and `credits_remaining` equal to `total_credits`. As bookings draw on the pass, `credits_remaining` is always `total_credits` minus `credits_redeemed`, floored at zero. Crucially, a pass's credits are *applied* at booking confirm but only *redeemed* against `credits_redeemed` at check-in: confirming a booking computes how many credits it will consume, but the pass's running `credits_redeemed` only advances when the booking is checked in. The moment a check-in drives `credits_remaining` to zero, the pass transitions from `ACTIVE` to `EXHAUSTED`, and that check-in bumps the pass's `version`. A combo pass named on a booking must belong to that booking's guest, be `ACTIVE`, and have at least one credit remaining; a pass that fails any of these is rejected at confirm with `ERR_COMBO_PASS_INVALID`.

### 3.6. Booking a Slot: Hold, Confirm, and the Waitlist Axis

A `Booking` is the heart of the system, and it moves through a lifecycle that begins the moment a slot is requested and may cycle between confirmed and waitlisted before it settles. A booking is created — by an `OpsManager`, a `Cashier`, or the owning `Guest` — by supplying a `venue_id`, a `guest_id`, a `slot_kind` of `HEAT` or `TEE_SESSION`, the matching slot reference (a `heat_id` when the kind is `HEAT`, a `tee_session_id` when the kind is `TEE_SESSION`, the other left null), a `pricing_plan_id`, an `origin` of `RESERVATION` or `WALK_IN`, and a `party_size` of at least one player or kart. It may optionally carry a `group_id` tying it into a party package, a `combo_pass_id` to draw on pre-purchased credits, and a `units` count of activity units (rounds or heats) which defaults to 1. The supplied `slot_kind` must agree with which of `heat_id` / `tee_session_id` was provided, and a mismatch is part of the malformed-request family rejected with `ERR_INVALID_REQUEST`; a `slot_kind` that does not match the owning attraction's kind is rejected with `ERR_ATTRACTION_KIND_MISMATCH`.

A new booking opens in `HOLD` status. At creation its `gross_price_cents` is computed in the provisional manner (see §3.7), its `credits_applied` is zero, and its `cash_due_cents` equals `gross_price_cents`; nothing is committed against slot capacity yet, because only confirmed and checked-in bookings consume capacity. If the booking names a wristband plan that caps units and the requested `units` exceeds that cap, creation is rejected with `ERR_WRISTBAND_CAP_EXCEEDED`.

Confirming a held booking is where capacity is tested. A confirm carries the slot's expected version — `expected_heat_version` or `expected_tee_session_version` as described in §2.8 — and proceeds only when the venue's `posture` is `OPEN`, the owning slot is `OPEN`, the OCC version matches, the height and waiver safety gates pass, any named combo pass is valid, and capacity is examined. If the slot's free capacity (`lanes_available` for a heat, `players_available` for a tee session) is greater than or equal to the booking's `party_size`, the booking moves from `HOLD` to `CONFIRMED`: its `gross_price_cents` is recomputed in the final manner, combo credits are applied to set `credits_applied` and `cash_due_cents`, the slot's committed counter rises by `party_size` and its available count is recomputed, the slot's `version` increments, and if a `group_id` is set the party group's `units_consumed` rises by `party_size` and the group's `version` increments. If instead the slot's free capacity is less than the booking's `party_size`, the booking moves from `HOLD` to `WAITLISTED` rather than being rejected: it receives a `waitlist_seq` equal to one more than the highest `waitlist_seq` among the slot's current waitlisted bookings (starting at 1 when it is the first), consumes no capacity, leaves the slot's `version` untouched, and keeps its provisional `cash_due_cents`. A direct confirm that is on a capacity-committing path and genuinely has no room — as opposed to one that is allowed to fall through to the waitlist — surfaces `ERR_CAPACITY_EXCEEDED`.

The confirmed-versus-waitlisted relationship is a cycle, not a one-way street. When capacity is released on a slot — by cancelling or no-showing a previously `CONFIRMED` booking — the system promotes the earliest-eligible waitlisted booking on that same slot, automatically and without a client request. Eligibility is decided by ordering the slot's waitlisted bookings by `created_at` ascending and then by `waitlist_seq` ascending, and promoting the first one whose `party_size` still fits within the newly freed capacity, provided the venue is `OPEN` and the slot is `OPEN`. Promotion moves the booking from `WAITLISTED` to `CONFIRMED`: it recomputes `gross_price_cents` in the final manner (the slot's `window` may have changed since the hold), re-derives `credits_applied` and `cash_due_cents`, raises the slot's committed counter by `party_size` with the available count recomputed, increments the slot's `version`, clears the booking's `waitlist_seq` to null, and — if the booking belongs to a group — raises that group's `units_consumed` by `party_size`. The booking's own `version` increments on every one of these transitions.

### 3.7. Pricing a Booking: Provisional and Final

A booking's price is computed by a single, step-ordered rule used in two variants. The per-unit price starts from the pricing plan's `base_price_cents`, and when the slot's `window` is `PEAK` the plan's `peak_surcharge_cents` is added to that per-unit price. For a wristband plan, the price is flat per player: the per-unit price is multiplied by the `party_size` to give the raw amount, and the booking's `units` are folded into the band rather than multiplied through. For a per-round or per-heat plan, the price scales with both units and players: the raw amount is the per-unit price multiplied by the effective unit count and then by the `party_size`. The effective unit count is normally the booking's `units`, except that for a wristband plan with a positive `wristband_unit_cap` the effective units are capped at that maximum — the smaller of the requested `units` and the cap.

A group discount then applies, but only to large parties. When the `party_size` is at least four players, the raw amount is multiplied by one minus the plan's `group_discount_pct`; for any smaller party the raw amount is left unchanged. The result is rounded exactly once, at the very end, using round-half-up, to yield the integer-cent `gross_price_cents`; the calculation never rounds a per-unit figure and then sums. The two variants differ only in timing and in what they finalize. The **provisional** variant runs at booking creation: it reads the slot's `window` as it stands at create time, stores the result as `gross_price_cents` on the held booking without applying any combo credits, and sets `credits_applied` to zero and `cash_due_cents` equal to `gross_price_cents`. The **final** variant runs at confirm and again at waitlist promotion: it re-reads the slot's `window` at that moment (it may have changed since the hold via a slot edit), recomputes `gross_price_cents`, then applies combo credits and finalizes `cash_due_cents`. Provisional and final prices diverge precisely when the slot's window changed between the hold and the confirm.

Combo credits, when a valid pass is attached, are allocated whole-unit-first with cash covering the remainder. The number of billable units for credit purposes is the same effective unit count used in pricing multiplied by the `party_size`. The credits applied is the smaller of the pass's `credits_remaining` and that billable-unit count. The fraction of the booking those credits cover is the credits applied divided by the billable units (kept as an exact ratio), the credit's cash value is `gross_price_cents` multiplied by that covered fraction and rounded half up, and `cash_due_cents` is `gross_price_cents` minus that credit value, floored at zero. When no combo pass is attached or the named pass is not `ACTIVE`, no credits are applied: `credits_applied` is zero and `cash_due_cents` equals `gross_price_cents`. Remember that this computation only sets how many credits the booking *will* consume; the pass's `credits_redeemed` is not advanced until the booking checks in.

### 3.8. Check-In, Completion, No-Show, and Cancellation

Once a booking is `CONFIRMED`, a `Cashier` (or an `OpsManager` exercising override) checks it in, moving it from `CONFIRMED` to `CHECKED_IN`. Check-in is permitted only while the owning slot is `OPEN` and only when the venue's `current_utc` falls inside the slot's active window — within `[start_utc, end_utc)` for a heat (start inclusive, end exclusive) and within `[start_utc, end_utc]` for a tee session (both ends inclusive). A check-in attempted outside that window is rejected with `ERR_CHECK_IN_WINDOW`. At check-in, if the booking drew on a combo pass, the pass's `credits_redeemed` advances by the booking's `credits_applied`, `credits_remaining` is recomputed, the pass flips to `EXHAUSTED` if `credits_remaining` reaches zero, and the pass's `version` increments; the booking's `version` increments as well. A checked-in booking reaches `COMPLETED` automatically when its owning heat or tee session is manually closed, as described in §3.2.

A confirmed booking that never showed can be marked a no-show by a `Cashier` or `OpsManager`, moving it from `CONFIRMED` to `NO_SHOW`, but only after the slot's window has fully passed — that is, only when the venue's `current_utc` is at or after the slot's `end_utc`. A no-show attempted before the window has passed is rejected with `ERR_NO_SHOW_WINDOW`. Recording a no-show releases the booking's capacity: the slot's committed counter drops by `party_size`, available is recomputed, the slot's `version` increments, the earliest-eligible waitlisted booking on the slot is promoted, and if the booking belongs to a group that group's `units_consumed` drops by `party_size`.

A booking may be cancelled from any non-terminal state — `HOLD`, `CONFIRMED`, or `WAITLISTED` — by the owning `Guest`, a `Cashier`, an `OpsManager`, or the system as part of a slot or venue cascade, moving it to `CANCELLED`. The downstream effects depend on the state it left. If it was `CONFIRMED`, its committed capacity is released (the slot's committed counter drops by `party_size`, available is recomputed, the slot's `version` increments, and the earliest-eligible waitlisted booking is promoted), and if it belonged to a group that group's `units_consumed` drops by `party_size`. If it was `WAITLISTED`, its `waitlist_seq` is cleared. If combo credits had been applied at confirm but not yet redeemed at check-in, those `credits_applied` are released without changing the pass's `credits_redeemed`. The booking's `version` increments on cancellation. The terminal booking statuses `COMPLETED`, `CANCELLED`, and `NO_SHOW` admit no further transitions, and a transition attempted against a booking already terminal, or otherwise out of the legal source state, is rejected with `ERR_INVALID_STATE`.

### 3.9. Capacity Roll-Up and Party-Group Balances

The committed and available counters on a slot are not free-floating numbers; they are a roll-up over the slot's bookings. A heat's `lanes_committed` is the sum of `party_size` over the bookings on that heat whose status is `CONFIRMED` or `CHECKED_IN`, and its `lanes_available` is `lane_capacity` minus that committed total, never below zero. A tee session's `players_committed` is the same sum of `party_size` over its `CONFIRMED` and `CHECKED_IN` bookings, and its `players_available` is `party_slot_capacity` minus that committed total, never below zero. Held and waitlisted bookings deliberately consume no capacity and are excluded from these sums. A party group's `units_consumed` is, in the same spirit, the sum of `party_size` over the group's member bookings in `CONFIRMED` or `CHECKED_IN`; any excess of `units_consumed` over the package's `included_unit_count` is the group's overage units (`overage_units`), floored at zero.

### 3.10. Party Packages

A `PartyGroup` bundles several bookings under one package with an up-front deposit. A group is created by an `OpsManager`, a `Cashier`, or a host `Guest` with a `venue_id`, a `host_guest_id` naming the host whose wallet backs the deposit, a `package_name`, an `included_unit_count` of activity units bundled across all member bookings, and a `deposit_cents` amount. Creation opens the group in `DRAFT` status with `units_consumed` at zero and debits `deposit_cents` from the host's wallet `arcade_card_balance_cents`; if the host's balance cannot cover the deposit, creation is rejected with `ERR_INSUFFICIENT_CARD_BALANCE`.

Confirming a group, guarded by `expected_group_version` as in §2.8, advances it from `DRAFT` to `CONFIRMED` and makes the deposit non-refundable. Confirmation requires the venue to be `OPEN` and requires the group to hold at least one member booking in `HOLD` or `CONFIRMED`; a group with no such member cannot be confirmed and is rejected with `ERR_PARTY_GROUP_EMPTY`. Checking in a group, performed by a `Cashier` or `OpsManager`, advances it from `CONFIRMED` to `CHECKED_IN` once at least one of its member bookings has itself been checked in; a check-in attempted while the group is not `CONFIRMED`, or while no member booking has yet reached `CHECKED_IN`, is rejected with `ERR_INVALID_STATE`. A group bubbles up to `COMPLETED` automatically, from either `CONFIRMED` or `CHECKED_IN`, once every member booking has reached a terminal state — `COMPLETED`, `CANCELLED`, or `NO_SHOW` — with at least one member having reached `COMPLETED`.

Cancelling a group, available from `DRAFT` or `CONFIRMED` and performed by a host `Guest`, a `Cashier`, or an `OpsManager`, moves it to `CANCELLED` and cascades: every non-terminal member booking is cancelled, carrying each booking's own cancellation side-effects including capacity release and waitlist promotion. The deposit's fate turns entirely on when the cancellation happens — if the group is cancelled while still `DRAFT`, the deposit is refunded by crediting `deposit_cents` back to the host wallet's `arcade_card_balance_cents`; if the group is cancelled while `CONFIRMED`, the deposit is forfeited and no refund is made. Every group transition increments the group's `version`. The terminal group statuses `COMPLETED` and `CANCELLED` admit no further transitions.

### 3.11. Weather Closure and Venue Shutdown

Weather is the system's standing disruption, and the venue `posture` axis exists to absorb it. An `OpsManager` places an open venue into a weather hold, supplying a `weather_hold_reason` and `expected_venue_version`, which advances `posture` from `OPEN` to `WEATHER_HOLD`. Consistent with §2.8, `expected_venue_version` is accepted on this and the other venue-posture transitions for the caller's convenience but is not OCC-enforced: the server never compares it to the venue's current `version` and never raises a stale-version error on these endpoints, regardless of the value supplied. The `weather_hold_reason` is a required non-empty string. The hold cascades immediately: the reason is captured into `weather_hold_reason`, every heat and tee session on the venue currently in `OPEN` status is moved to `CLOSED` so no new bookings are taken, and on each of those just-closed slots every `WAITLISTED` booking is moved to `CANCELLED`. Critically, `CONFIRMED` and `CHECKED_IN` bookings on those slots are *not* auto-completed under a weather hold — they stay `CONFIRMED` or `CHECKED_IN`, which is the deliberate difference from a manual slot close (where they would complete). The hold increments the venue's `version`. While the venue is in `WEATHER_HOLD`, the posture gate blocks slot opening, booking confirmation, booking check-in, and party-group confirmation with `ERR_VENUE_NOT_OPEN`.

An `OpsManager` resumes a held venue, supplying `expected_venue_version`, which advances `posture` from `WEATHER_HOLD` back to `OPEN`, clears `weather_hold_reason` to null, and increments the venue's `version`. Finally, an `OpsManager` may close a venue permanently, supplying `expected_venue_version`, which moves `posture` to `CLOSED` from either `OPEN` or `WEATHER_HOLD`. A permanent close is allowed only when no heat or tee session on the venue is currently in `OPEN` status; if any open slot remains the close is refused as an invalid state transition. The close cascades by moving every still-`SCHEDULED` slot on the venue to `CANCELLED`, which in turn cascades each such slot's non-terminal bookings to `CANCELLED`, and it increments the venue's `version`. `CLOSED` is terminal: once a venue is closed it accepts no further posture transitions, and while closed it blocks all child mutations under the posture gate.

### 3.12. Validation Precedence

Because several checks can be in play on one request, the order in which they are evaluated is itself a contract, so that the rejection a caller receives is predictable. The system evaluates, in this order: first that authentication headers are present and name a known role (`ERR_UNAUTHENTICATED`); then that the acting role is permitted for the operation and, for a `Guest`, that it owns the targeted resource (`ERR_FORBIDDEN`); then that every referenced resource exists, resolved left-to-right (`ERR_NOT_FOUND`); then that the request body is well-formed — required fields present, enums valid, `party_size` at least 1, `units` at least 1, amounts not negative, and `slot_kind` agreeing with the supplied slot reference (`ERR_INVALID_REQUEST`); then that the venue's posture permits the operation (`ERR_VENUE_NOT_OPEN`); then, on the two guarded write paths, that the supplied expected version matches the parent's current version (`ERR_STALE_SLOT_VERSION` for slot-guarded confirms, `ERR_STALE_GROUP_VERSION` for group confirms); then that the target is in a legal state for the requested transition, covering terminal-state lockdown and repeated-trigger rejection (`ERR_INVALID_STATE`).

After those system-level checks come the business rules, in their own precedence. Attraction-kind agreement on slot and booking creation is checked (`ERR_ATTRACTION_KIND_MISMATCH`), then the check-in window (`ERR_CHECK_IN_WINDOW`), then the no-show window (`ERR_NO_SHOW_WINDOW`), then the party-group-not-empty rule on group confirm (`ERR_PARTY_GROUP_EMPTY`). Then the safety gates evaluate: the height requirement (`ERR_HEIGHT_REQUIREMENT`) before the waiver requirement (`ERR_WAIVER_REQUIRED`). Then slot-interval collision on slot creation (`ERR_SLOT_OVERLAP`), then the wristband unit cap (`ERR_WRISTBAND_CAP_EXCEEDED`), then combo-pass validity (`ERR_COMBO_PASS_INVALID`), then arcade-card and deposit sufficiency (`ERR_INSUFFICIENT_CARD_BALANCE`), and finally, on a capacity-committing confirm or promotion that genuinely cannot fit, capacity exhaustion (`ERR_CAPACITY_EXCEEDED`). A booking confirm that lacks room falls through to the waitlist rather than failing; `ERR_CAPACITY_EXCEEDED` is reserved for a promotion (or other strictly capacity-committing path) that requires room it does not have.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that read a resource or drive a state transition on an existing resource return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1, and the request and response bodies for each operation are reconstructed from the workflow narratives in §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue (posture OPEN) | OpsManager |
| GET | `/venues` | List venues (filter by posture) | OpsManager, Cashier, Guest |
| GET | `/venues/{venue_id}` | Get venue details incl. posture and open_slot_count | OpsManager, Cashier, Guest |
| POST | `/venues/{venue_id}/weather-hold` | Put venue into WEATHER_HOLD | OpsManager |
| POST | `/venues/{venue_id}/resume` | Resume venue from WEATHER_HOLD to OPEN | OpsManager |
| POST | `/venues/{venue_id}/close` | Close venue permanently | OpsManager |
| POST | `/venues/{venue_id}/_clock/set_current_utc` | Set the venue server clock (test-driving) | OpsManager |
| POST | `/attractions` | Create an attraction | OpsManager |
| GET | `/attractions` | List attractions (filter by venue_id, kind) | OpsManager, Cashier, Guest |
| GET | `/attractions/{attraction_id}` | Get an attraction | OpsManager, Cashier, Guest |
| POST | `/pricing-plans` | Create a pricing plan | OpsManager |
| GET | `/pricing-plans` | List pricing plans (filter by venue_id, mode) | OpsManager, Cashier, Guest |
| GET | `/pricing-plans/{pricing_plan_id}` | Get a pricing plan | OpsManager, Cashier, Guest |
| POST | `/heats` | Create a go-kart heat | OpsManager |
| GET | `/heats` | List heats (filter by venue_id, attraction_id, status) | OpsManager, Cashier, Guest |
| GET | `/heats/{heat_id}` | Get a heat incl. lanes_available | OpsManager, Cashier, Guest |
| POST | `/heats/{heat_id}/open` | Open a heat for bookings | OpsManager |
| POST | `/heats/{heat_id}/close` | Close a heat | OpsManager |
| POST | `/heats/{heat_id}/cancel` | Cancel a scheduled heat | OpsManager |
| POST | `/tee-sessions` | Create a mini-golf tee session | OpsManager |
| GET | `/tee-sessions` | List tee sessions (filter by venue_id, attraction_id, status) | OpsManager, Cashier, Guest |
| GET | `/tee-sessions/{tee_session_id}` | Get a tee session incl. players_available | OpsManager, Cashier, Guest |
| POST | `/tee-sessions/{tee_session_id}/open` | Open a tee session for bookings | OpsManager |
| POST | `/tee-sessions/{tee_session_id}/close` | Close a tee session | OpsManager |
| POST | `/tee-sessions/{tee_session_id}/cancel` | Cancel a scheduled tee session | OpsManager |
| POST | `/guests` | Register a guest (auto-creates a Wallet) | OpsManager, Cashier, Guest |
| GET | `/guests` | List guests (filter by waiver_status) | OpsManager, Cashier, Guest |
| GET | `/guests/{guest_id}` | Get a guest incl. derived waiver_status | OpsManager, Cashier, Guest |
| POST | `/waivers` | Sign a height/safety waiver for a guest | OpsManager, Cashier, Guest |
| GET | `/waivers` | List waivers (filter by guest_id) | OpsManager, Cashier, Guest |
| GET | `/waivers/{waiver_id}` | Get a waiver | OpsManager, Cashier, Guest |
| GET | `/wallets` | List wallets (filter by guest_id) | OpsManager, Cashier, Guest |
| GET | `/wallets/{wallet_id}` | Get an arcade wallet | OpsManager, Cashier, Guest |
| POST | `/wallets/{wallet_id}/top-ups` | Load value onto the arcade card | OpsManager, Cashier, Guest |
| POST | `/wallets/{wallet_id}/redemptions` | Redeem arcade card value | Cashier, Guest |
| POST | `/combo-passes` | Purchase a combo pass | OpsManager, Cashier, Guest |
| GET | `/combo-passes` | List combo passes (filter by guest_id, status) | OpsManager, Cashier, Guest |
| GET | `/combo-passes/{combo_pass_id}` | Get a combo pass incl. credits_remaining | OpsManager, Cashier, Guest |
| POST | `/party-groups` | Create a party package / group (DRAFT) | OpsManager, Cashier, Guest |
| GET | `/party-groups` | List party groups (filter by venue_id, host_guest_id, status) | OpsManager, Cashier, Guest |
| GET | `/party-groups/{group_id}` | Get a party group incl. units_consumed | OpsManager, Cashier, Guest |
| POST | `/party-groups/{group_id}/confirm` | Confirm a party group (locks deposit) | OpsManager, Cashier, Guest |
| POST | `/party-groups/{group_id}/check-in` | Check in a party group | OpsManager, Cashier |
| POST | `/party-groups/{group_id}/cancel` | Cancel a party group | OpsManager, Cashier, Guest |
| POST | `/bookings` | Create a booking (HOLD) | OpsManager, Cashier, Guest |
| GET | `/bookings` | List bookings (filter by venue_id, guest_id, heat_id, tee_session_id, group_id, combo_pass_id, pricing_plan_id, status) | OpsManager, Cashier, Guest |
| GET | `/bookings/{booking_id}` | Get a booking incl. pricing fields | OpsManager, Cashier, Guest |
| POST | `/bookings/{booking_id}/confirm` | Confirm a HOLD booking (CONFIRMED or WAITLISTED) | OpsManager, Cashier, Guest |
| POST | `/bookings/{booking_id}/check-in` | Check in a confirmed booking | OpsManager, Cashier |
| POST | `/bookings/{booking_id}/cancel` | Cancel a booking; releases capacity and promotes waitlist | OpsManager, Cashier, Guest |
| POST | `/bookings/{booking_id}/no-show` | Mark a confirmed booking as no-show | OpsManager, Cashier |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_VENUE_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_GROUP_VERSION` | 412 Precondition Failed |
| `ERR_HEIGHT_REQUIREMENT` | 422 Unprocessable Entity |
| `ERR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ATTRACTION_KIND_MISMATCH` | 409 Conflict |
| `ERR_CHECK_IN_WINDOW` | 409 Conflict |
| `ERR_NO_SHOW_WINDOW` | 409 Conflict |
| `ERR_PARTY_GROUP_EMPTY` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WRISTBAND_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COMBO_PASS_INVALID` | 409 Conflict |
| `ERR_INSUFFICIENT_CARD_BALANCE` | 409 Conflict |

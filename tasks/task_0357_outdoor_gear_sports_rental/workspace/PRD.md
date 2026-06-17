# Outdoor Gear Rental API — Product Requirements Document

## 1. Introduction

This document specifies the Outdoor Gear & Sports Rental API, a back-office and counter-operations platform for a multi-discipline rental shop that handles kayaks, stand-up paddleboards, skis, and snowboards. The shop's economics are unforgiving: a single physical unit must be quoted at the cheapest of an hourly, daily, or flat seasonal tier; reservations must not double-book a hull or a pair of skis; deposits must be held and faithfully returned; and the demand swings of peak season must be priced into every quote. The API exists to make those rules machine-enforceable rather than dependent on a clerk's memory.

The platform models the full rental arc — a renter quotes a window against an available unit, optionally layers on lessons or packages, confirms with a deposit, picks the gear up at the counter, returns it, and finally settles the account once the gear has been inspected. Along the way the system must reconcile two parallel truths about every reservation (where it sits in its operational lifecycle versus what has happened to the money), track each unit through a cyclic condition-and-availability machine, and protect a renter's standing against repeated late returns, damage, and outright loss. Pricing is computed twice — once forward-looking at quote time and again on actual usage at check-in — and the two figures legitimately diverge. Because catalog edits and counter operations happen in parallel, the most contended writes are guarded by optimistic concurrency so that a clerk never silently overwrites a unit another writer has already committed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. All resource paths in this API are mounted under the `/rental` prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying values that cannot be validated, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `ShopAdmin`, `RentalAgent`, and `Renter`. When an authenticated principal attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how their identity binds to persisted data. When `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. Concretely, a `Renter` may only confirm, cancel, attach add-ons to, or dispute against reservations whose `customer_id` equals their own `X-User-ID`; an attempt to act on another customer's reservation is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server does not compare it to any entity's `id`. When `X-User-Role` is `RentalAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; an agent operates the counter on behalf of any renter and is not subject to the ownership check.

A `ShopAdmin` operates the catalog and back office: creating gear types, rate cards, season windows, add-ons, and physical gear units; repairing units; reassessing disputed damage assessments; and driving the test clock. A `RentalAgent` runs the rental counter: checkout, check-in, and settlement, plus the ability to create, confirm, attach add-ons to, and cancel reservations on a renter's behalf. A `Renter` acts only on their own reservations and may additionally dispute a damage assessment raised against one of their rentals. All three roles may read through the various `GET` listing and retrieval endpoints.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the count of leading items to skip and defaults to 0.

Unless an endpoint states otherwise, list responses are sorted by the resource's creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Two-Tier Identity Model

Every resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` is identity only and is never supplied by the client. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value rendered with three fractional digits.

Resources divide into two tiers. **Mutable resources** — `GearType`, `RateCard`, `Customer`, `AddOn`, `GearUnit`, `Reservation`, and `DamageAssessment` — additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 when the resource is created and increases by exactly 1 on every mutation, including mutations that arrive as cascades from operations on other resources; `updated_at` is refreshed to the current moment on each such mutation. **Append-only resources** — `SeasonWindow`, `ReservationAddOn`, `ConditionReport`, and `LedgerEntry` — carry only `id` and `created_at`: they have neither an `updated_at` field nor a `version` field, because they are written once and never modified in place.

### 2.5. Hierarchical Consistency and Cascade Semantics

Many counter operations mutate more than one resource in a single call, and every such secondary effect is part of the contract. When a reservation transition changes a gear unit's `availability`, sets or clears its `active_reservation_id`, or revises its `condition`, that gear unit is itself mutated: its `updated_at` is refreshed and its `version` increments. The same holds whenever a customer's derived `standing`, `strike_points`, or `open_loss_balance_cents` are recomputed, and whenever a damage assessment's `outcome`, `charge_cents`, `waiver_applied`, or `status` change. A single check-in, for example, simultaneously advances the reservation, transitions the gear unit into inspection, creates a condition report and a damage assessment, and re-derives the customer's standing — each affected mutable entity has its own `version` bumped independently.

### 2.6. Nested and Cross-Resource Lookup

This is a flat domain: resources reference one another by `id` through fields rather than through nested ownership URLs. Where an endpoint path or request body names several resources, the server validates their existence left to right and rejects the request at the first identifier that does not resolve, returning `ERR_NOT_FOUND`. A gear unit does not embed the reservation currently using it as a structural child; instead the unit exposes a denormalized `active_reservation_id` back-pointer, and the reservation behind a unit is discovered by listing reservations filtered by `gear_unit_id`. Likewise a reservation's snapshotted `rate_card_id` is a captured value, while the live structural link runs through the unit's own `rate_card_id`.

### 2.7. Monetary Values, Demand Multipliers, and Rounding

All money is expressed in whole integer cents; configured rates such as `hourly_cents`, `daily_cents`, `seasonal_flat_cents`, `deposit_cents`, `damage_waiver_cents_per_day`, `late_fee_cents_per_hour`, `loss_fee_cents`, and `price_cents` must each be non-negative integers, and a request supplying a negative cents value is malformed. Demand multipliers are expressed in basis points: a `demand_multiplier_bp` of 12000 means the base rate is multiplied by 1.2, and the default multiplier when no season applies is 10000 (that is, a multiplier of exactly one). Wherever a computation produces a fractional cent — applying a demand multiplier, a bundle discount, or a damage fraction — the result is rounded half up to the nearest whole cent. Where a calculation specifies a particular order of rounding relative to summation, that order is binding and is spelled out with the calculation in §3.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and only these two. Creating a reservation targets a `GearUnit` as its concurrency parent: the create request must carry `expected_gear_unit_version`, a non-optional field whose value is the `version` of the gear unit the client last observed. If that value does not equal the gear unit's current `version` — for instance because another writer has already moved the unit from `AVAILABLE` to `RESERVED` since the client read it — the create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing the client from reserving a unit on a stale view. Disputing a damage assessment targets the `DamageAssessment` as its concurrency parent: the dispute request must carry `expected_damage_assessment_version` matching that assessment's current `version`, and a mismatch — for instance because a `ShopAdmin` reassessment has already superseded the assessment the renter was looking at — is rejected with `ERR_STALE_VERSION` at HTTP 412. No other endpoint accepts or requires a version field; mutations outside these two paths perform no concurrency check.

### 2.9. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: first, payload well-formedness — required fields present, enums and types valid, every cents value non-negative, and on a reservation `pickup_at` strictly earlier than `due_at` — failing which the request is rejected with `ERR_VALIDATION` at HTTP 400. Second, authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`, 401). Third, authorization, including the renter-ownership rule (`ERR_UNAUTHORIZED`, 403). Fourth, existence of every referenced resource, validated left to right (`ERR_NOT_FOUND`, 404). Fifth, that the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`, 409). Sixth, referential business rules — the unit's availability, the active status of the gear type and rate card, and add-on category matching (`ERR_UNIT_NOT_AVAILABLE`, 409). Seventh, the reservation window-overlap check (`ERR_WINDOW_CONFLICT`, 409). Eighth, lesson-slot capacity (`ERR_SLOT_FULL`, 409). Ninth, the beginner-lesson safety rule (`ERR_LESSON_REQUIRED`, 422). Tenth, the customer-suspension rule (`ERR_CUSTOMER_SUSPENDED`, 409). Eleventh, the optimistic-concurrency version check (`ERR_STALE_VERSION`, 412). Twelfth, the dispute-blocks-settlement rule (`ERR_ASSESSMENT_DISPUTED`, 409). A failing check at any tier surfaces its own error and masks all lower-priority checks.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Gear Types, Rate Cards, Seasons, and Add-Ons

Before any rental can happen, a `ShopAdmin` populates the catalog. A **gear type** describes a model of equipment: its `category` is one of `KAYAK`, `SKI`, `SUP`, or `SNOWBOARD`; it carries a human-readable `name` and a `size_label` such as "170cm" or "L". A gear type may flag `requires_lesson_for_beginner`, which defaults to false; when true, a beginner renter must attach a lesson before they can confirm. The `active` flag defaults to true and governs whether new units may be created under the type; an inactive type blocks reservation against units that depend on it.

A **rate card** binds pricing to a gear type through `gear_type_id` and holds the full schedule of money fields: the `hourly_cents` base rate, the `daily_cents` rate that caps a 24-hour block, the `seasonal_flat_cents` rate charged once for an entire seasonal rental, the refundable `deposit_cents`, the optional `damage_waiver_cents_per_day`, the `late_fee_cents_per_hour` charged per started hour past grace, and the `loss_fee_cents` full-replacement charge. A rate card also carries `grace_minutes`, the slack after the due time before late fees begin, which defaults to 15. Its `active` flag defaults to true and governs whether quotes may draw on it.

A **season window** describes a demand period for one `category` and is append-only. Beyond its `label` it defines a half-open interval running from an inclusive `starts_on` up to but not including an exclusive `ends_on`, and a `demand_multiplier_bp` of at least 1 basis point. A pickup instant falls inside a season when it is at or after `starts_on` and strictly before `ends_on` and the season's `category` matches the gear type's category.

An **add-on** is either a `LESSON` or a `PACKAGE` (its `kind`), scoped to a `category`, with a display `name` and a flat `price_cents`. Its `capacity_per_slot`, defaulting to 1 and never below 1, caps how many `LESSON` bookings may share one instructor slot; a `PACKAGE` ignores capacity entirely. The `active` flag, default true, governs whether the add-on may be attached to new reservations.

### 3.2. Registering Renters and Tracking Their Standing

A customer is registered with a `full_name`, a unique `email`, and an optional `skill_level` — one of `BEGINNER`, `INTERMEDIATE`, or `EXPERT` — defaulting to `BEGINNER`. At registration the customer's derived fields are seeded: `standing` is `GOOD`, `strike_points` is 0, and `open_loss_balance_cents` is 0. A registered renter's `id` is what an authenticated `Renter` presents as `X-User-ID`.

A customer's `standing` is never set directly; it is re-derived from a strike tally and an outstanding-loss balance. Each of the customer's reservations contributes strike points: a late return adds 1 point, a damage outcome adds 2 points, and a loss outcome adds 4 points, summed across all of the customer's reservations; the total never goes negative. Separately, `open_loss_balance_cents` is the sum of the `amount_cents` of the customer's `LOSS_FEE` ledger entries that remain unsettled (`settled` is false). The standing is then resolved as follows: it is `SUSPENDED` whenever the open loss balance is greater than 0 **or** the strike total is at least 4; otherwise it is `WATCH` when the strike total is at least 2 and below 4; otherwise it is `GOOD`. This derivation runs in two passes during a rental's tail. At check-in, a **provisional** standing is computed from the just-created assessment whose `status` is `ASSESSED`, before any loss has been ledgered, so the open loss balance may still read 0 even when a loss occurred. At settlement, a **final** standing is computed after the `LOSS_FEE` and `DAMAGE_FEE` ledger entries have been posted; the freshly posted unsettled loss can flip a customer who looked clear at check-in into `SUSPENDED`. The same two-pass re-derivation is also re-run when a reservation is cancelled.

### 3.3. Quoting and Reserving a Unit

A renter (or an agent acting for one) opens a rental by creating a **reservation** against a specific physical unit. The create payload names the renter through `customer_id`, the unit through `gear_unit_id`, the requested window through `pickup_at` (the inclusive start) and `due_at` (the exclusive end, so the rental window is half-open from `pickup_at` up to but not including `due_at`), an optional `damage_waiver_opted` flag defaulting to false, and the concurrency token `expected_gear_unit_version` described in §2.8. The reservation is born with `lifecycle_status` of `QUOTED` and `payment_status` of `UNPAID`; the unit's current `rate_card_id` is snapshotted onto the reservation; and the unit transitions from `AVAILABLE` to `RESERVED`, with its `active_reservation_id` set to the new reservation and its `version` incremented.

A physical **gear unit** itself is created by a `ShopAdmin` from a `gear_type_id`, a `rate_card_id`, and a unique `asset_tag`, and is born `AVAILABLE` with `condition` `GOOD`. A reservation may only be created when the unit's `availability` reads `AVAILABLE`, and when the unit's gear type and rate card are both `active`; otherwise the create is rejected with `ERR_UNIT_NOT_AVAILABLE`. Independently, the requested window must not collide with any window already held on the same unit. **Window-overlap** is evaluated against every non-terminal reservation on that `gear_unit_id` — those whose lifecycle is `QUOTED`, `CONFIRMED`, or `PICKED_UP`. To model the time a unit needs between rentals, each existing window is extended at its tail by a fixed turnaround buffer of 30 minutes, so an existing reservation effectively occupies the interval from its `pickup_at` up to its `due_at` plus 30 minutes. The new window collides when its `pickup_at` is earlier than that buffered existing end **and** the existing `pickup_at` is earlier than the new `due_at`. Because the buffer is strictly positive, two back-to-back rentals that touch exactly — where the new `pickup_at` equals the existing `due_at` — still collide. A collision is rejected with `ERR_WINDOW_CONFLICT`.

**Quote pricing** is computed at create time and may be recomputed on demand without mutating the lifecycle. The quote works on the requested window. Let the started-hours count be the elapsed minutes from `pickup_at` to `due_at`, divided by 60 and rounded up to a whole number, and let the started-days count be those same minutes divided by 1440 and rounded up to a whole number. The applicable multiplier in basis points is taken from the season window whose half-open interval contains `pickup_at` and whose category matches the gear type's category; if no such season exists the multiplier is 10000. Three base figures are formed: the hourly base is `hourly_cents` times the started-hours count, the daily base is `daily_cents` times the started-days count, and the seasonal base is `seasonal_flat_cents` flat regardless of span. The chosen base is the smallest of these three, and `quoted_rate_basis` records which tier produced it; when two or more tie for cheapest, the tie is broken in the order `HOURLY` before `DAILY` before `SEASONAL`. The rental amount is the chosen base multiplied by the multiplier basis points divided by 10000, with the multiplier applied **before** rounding and the product then rounded half up to whole cents. A waiver amount is added only when `damage_waiver_opted` is true, equal to `damage_waiver_cents_per_day` times the started-days count, and zero otherwise. The provisional grand total stored as `quoted_total_cents` is the rental amount plus the waiver amount plus the add-ons subtotal (§3.4), and it is forward-looking — no late or damage charge is included.

### 3.4. Layering On Lessons and Packages

While a reservation is still `QUOTED`, the renter may attach add-ons. An attach names the `addon_id` and, for a lesson, the instructor slot bounded by `slot_start_at` and `slot_end_at`; a package leaves both slot fields null. Each attachment becomes a `ReservationAddOn` line carrying its own `reservation_id`, and the line's `price_cents` is snapshotted from the add-on at attach time. The add-on's `category` must match the unit's gear type category, or the attach is rejected with `ERR_UNIT_NOT_AVAILABLE`.

A lesson slot is treated as a closed interval — both `slot_start_at` and `slot_end_at` are inclusive boundaries. **Slot capacity** is enforced by counting the existing non-cancelled `ReservationAddOn` lines for the same `addon_id` whose closed slot interval intersects the requested closed interval; because the interval is closed, two slots that merely touch at an endpoint do intersect. If admitting the new booking would push that occupancy plus one above the add-on's `capacity_per_slot`, the attach is rejected with `ERR_SLOT_FULL`.

The **add-ons subtotal** that feeds `quoted_total_cents` (and later the final settlement) is recomputed whenever a line is attached. A bundle condition holds when the reservation carries at least 2 `PACKAGE` add-on lines; when it holds, every line's snapshotted `price_cents` is multiplied by 0.95, a 5% bundle discount. Lesson lines are never discounted but are still rounded individually. The rounding order is pinned: each line's post-discount price is rounded half up to whole cents **first**, and only then are the rounded line amounts summed — summing first and rounding the total is incorrect.

### 3.5. Confirmation and the Deposit Hold

When a renter is satisfied with the quote, confirming the reservation advances it from `QUOTED` to `CONFIRMED`. Confirmation is gated by three preconditions. The customer's `standing` must not be `SUSPENDED`; a suspended renter is turned away with `ERR_CUSTOMER_SUSPENDED`. If the gear type sets `requires_lesson_for_beginner` and the renter's `skill_level` is `BEGINNER`, the reservation must already carry at least one `LESSON` add-on line; absent it, confirmation is rejected with `ERR_LESSON_REQUIRED`. The unit must still be holding this reservation in `RESERVED`. On success, the reservation snapshots `deposit_cents` from its rate card, its `payment_status` moves from `UNPAID` to `DEPOSIT_HELD`, and a ledger entry of type `DEPOSIT_HOLD` is written for the positive deposit amount. The payment dimension advances independently of the lifecycle dimension: `payment_status` is its own parallel state machine whose start is `UNPAID` and whose terminal states are `SETTLED` and `REFUNDED`.

### 3.6. Counter Operations: Checkout, Check-In, and Inspection

The physical handover is a `RentalAgent` operation. **Checkout** carries the assessor's `condition_rating` and optional `notes`, recording a `CHECKOUT` `ConditionReport` whose `phase` is `CHECKOUT`; the rating is one of `GOOD`, `WORN`, `DAMAGED`, or `LOST`, and the report fixes its `gear_unit_id` from the reservation. Checkout advances the reservation from `CONFIRMED` to `PICKED_UP`, stamps `picked_up_at` with the current clock, moves the unit's `availability` from `RESERVED` to `CHECKED_OUT`, and sets the unit's `condition` from the checkout rating. Checkout is permitted at any time once the reservation is `CONFIRMED`; the clock need not have reached `pickup_at`.

**Check-in**, also at the counter, records a `CHECKIN` `ConditionReport` (its `phase` is `CHECKIN`) with the inspector's `condition_rating` and optional `notes` in the same call, advances the reservation from `PICKED_UP` to `RETURNED`, stamps `returned_at` with the current clock, and moves the unit from `CHECKED_OUT` to `INSPECTING`. Three computations run on check-in. First, the **late fee**: the grace deadline is `due_at` plus the rate card's `grace_minutes`; if `returned_at` is at or before that deadline the return is on time and `late_fee_cents` is 0, and the deadline is inclusive. Otherwise the late hours are the minutes from the grace deadline to `returned_at` divided by 60 and rounded up to a whole number, and `late_fee_cents` is `late_fee_cents_per_hour` times that started-hour count. Second, the **final settlement total**: this re-runs the tiered pricing on actual usage rather than the requested window — the actual-hours count is the minutes from `picked_up_at` to `returned_at` divided by 60 rounded up, the actual-days count those minutes divided by 1440 rounded up, and the multiplier is taken from the season covering `picked_up_at` (else 10000). The hourly, daily, and seasonal bases are recomputed on those actual counts, the cheapest is chosen by the same `HOURLY` before `DAILY` before `SEASONAL` tie-break, the rental amount is that chosen base times the multiplier basis points over 10000 rounded half up, and the waiver (when `damage_waiver_opted`) is `damage_waiver_cents_per_day` times the actual-days count. The `final_total_cents` is then that rental amount plus the waiver plus the add-ons subtotal plus `late_fee_cents` plus the damage charge from the assessment, with the rental rounded before the late and damage amounts are added; `final_total_cents` and `late_fee_cents` stay null and zero respectively until the reservation reaches `RETURNED`. Because the final selection runs on actual elapsed time, it legitimately diverges from the provisional quote whenever the actual window differs from the requested one.

The third computation creates a **damage assessment** from the check-in report, linked through `checkin_report_id`, with `status` `ASSESSED`. Severity ranks the ratings `GOOD` below `WORN` below `DAMAGED` below `LOST`. If the check-in rating is `LOST`, the `outcome` is `LOSS`, the `charge_cents` is the rate card's `loss_fee_cents`, and `waiver_applied` is false. Otherwise, if the check-in severity is strictly higher than the checkout severity and the check-in rating is `DAMAGED`, the `outcome` is `DAMAGE`: when `damage_waiver_opted` is true the `charge_cents` is 0 and `waiver_applied` is true, and otherwise the `charge_cents` is `loss_fee_cents` multiplied by 0.40 and rounded half up to whole cents, with `waiver_applied` false. In every other case the `outcome` is `NONE`, the `charge_cents` is 0, and `waiver_applied` is false. Check-in also re-derives the customer's standing in its provisional variant, and when the check-in rating is `LOST` the unit is routed from `INSPECTING` to `RETIRED` and permanently removed from rentable inventory, with `active_reservation_id` cleared.

### 3.7. Disputing and Reassessing Damage

A renter who disagrees with an assessment on their own rental may dispute it, moving its `status` from `ASSESSED` to `DISPUTED`. The dispute requires `expected_damage_assessment_version` to match the assessment's current `version` (§2.8); on success the assessment's `version` increments and settlement of the parent reservation is blocked until the dispute is resolved. A `ShopAdmin` resolves a dispute by reassessing, moving the `status` from `DISPUTED` back to `ASSESSED`; reassessment also requires `expected_damage_assessment_version` to match, increments the `version`, accepts an optional `override_outcome`, and recomputes `outcome` and `charge_cents` by the same severity-and-waiver rules. Each side of this loop is symmetric: both transitions are version-guarded, both increment the version, and both require the assessment to be in the correct originating status — `ASSESSED` to dispute, `DISPUTED` to reassess.

### 3.8. Settlement and Closing the Account

Settlement, performed by a `RentalAgent`, advances the reservation from `RETURNED` to `CLOSED` and is the moment money is posted. It is gated on the assessment having `status` `ASSESSED` and the unit being in `INSPECTING`; if the assessment is `DISPUTED`, settlement is refused with `ERR_ASSESSMENT_DISPUTED`. On success the `payment_status` moves from `DEPOSIT_HELD` to `SETTLED`, and the assessment's own `status` moves from `ASSESSED` to `SETTLED`. The system posts a `RENTAL_CHARGE` ledger entry for the rental portion together with `LATE_FEE` and `DAMAGE_FEE`/`LOSS_FEE` entries as applicable, each entry recording its `reservation_id`, its denormalized `customer_id`, an `entry_type`, a signed `amount_cents` (holds and charges positive, refunds negative), and a `settled` flag that starts false; the `created_at` of each entry is the ledger replay-order key. The deposit is then released as a `DEPOSIT_REFUND` entry for the negative deposit amount, unless an open `LOSS_FEE` absorbs it. Finally the unit leaves inspection: it returns from `INSPECTING` to `AVAILABLE` when its `condition` is `GOOD` or `WORN`, or moves from `INSPECTING` to `MAINTENANCE` when its `condition` is `DAMAGED`; in either case `active_reservation_id` is cleared. Settlement also re-derives the customer's standing in its final variant, by which point the posted unsettled loss is reflected in `open_loss_balance_cents`.

A unit parked in `MAINTENANCE` is returned to service by a `ShopAdmin` repair, which moves the unit from `MAINTENANCE` back to `AVAILABLE` and steps its `condition` from `DAMAGED` to `WORN`.

### 3.9. Cancellation and Deposit Conservation

A reservation may be cancelled while it is still `QUOTED` or `CONFIRMED` — never after pickup. Cancellation moves the `lifecycle_status` to `CANCELLED`, releases the unit by moving its `availability` from `RESERVED` back to `AVAILABLE` and clearing `active_reservation_id`. If the reservation's `payment_status` was `DEPOSIT_HELD`, a `DEPOSIT_REFUND` ledger entry is written for the negative deposit amount and the `payment_status` moves to `REFUNDED`. The compensating invariant is that the net money on a cancelled reservation's ledger returns to zero — the held deposit is fully conserved on the way out. Both `CLOSED` and `CANCELLED` are terminal lifecycle states. A request to drive a reservation through a transition it is not currently positioned for is rejected with `ERR_INVALID_STATE`.

### 3.10. The Test Clock

Because every late fee, settlement, and season selection depends on "now," a `ShopAdmin` may set the server's logical UTC clock by supplying a `to_iso8601` instant. The set clock governs the timestamps stamped into `picked_up_at` and `returned_at` and the season lookup at quote and settlement time. This capability mutates no business resource and returns no resource body.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource, or that drive an existing resource through a state transition or otherwise modify it, return `200 OK`. The reservation-addons endpoint creates a new `ReservationAddOn` line and therefore returns `201`. Full request and response shapes are reconstructed from the §3 narratives; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rental/gear-types` | Create a gear type | ShopAdmin |
| GET | `/rental/gear-types/{id}` | Get a gear type | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/gear-types` | List gear types | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/rate-cards` | Create a rate card for a gear type | ShopAdmin |
| GET | `/rental/rate-cards/{id}` | Get a rate card | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/rate-cards` | List rate cards, optionally by gear type | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/season-windows` | Create a seasonal demand window for a category | ShopAdmin |
| GET | `/rental/season-windows` | List season windows, optionally by category | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/addons` | Create a lesson/package add-on | ShopAdmin |
| GET | `/rental/addons` | List add-ons, optionally by category | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/customers` | Register a customer (renter) | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/customers/{id}` | Get a customer with derived standing | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/gear-units` | Create a physical gear unit | ShopAdmin |
| GET | `/rental/gear-units/{id}` | Get a gear unit | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/gear-units` | List gear units, optionally by type/rate card/availability | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/gear-units/{id}/repair` | Return a unit from MAINTENANCE to AVAILABLE | ShopAdmin |
| POST | `/rental/reservations` | Create (quote) a reservation against a unit | Renter, RentalAgent |
| GET | `/rental/reservations/{id}` | Get a reservation | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/reservations` | List reservations, optionally by customer/unit/lifecycle | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/reservations/{id}/quote` | Recompute and return the provisional quote | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/reservations/{id}/addons` | Attach a lesson/package add-on (QUOTED only) | Renter, RentalAgent |
| GET | `/rental/reservation-addons` | List reservation add-on lines | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/reservation-addons/{id}` | Get a reservation add-on line | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/reservations/{id}/confirm` | Confirm a quoted reservation (holds deposit) | Renter, RentalAgent |
| POST | `/rental/reservations/{id}/checkout` | Check out the gear (records CHECKOUT condition) | RentalAgent |
| POST | `/rental/reservations/{id}/checkin` | Check in the gear (records CHECKIN, computes settlement) | RentalAgent |
| POST | `/rental/reservations/{id}/settle` | Settle a returned reservation | RentalAgent |
| POST | `/rental/reservations/{id}/cancel` | Cancel a quoted/confirmed reservation | Renter, RentalAgent |
| GET | `/rental/condition-reports/{id}` | Get a condition report | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/condition-reports` | List condition reports by reservation or unit | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/damage-assessments/{id}` | Get a damage assessment | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/damage-assessments` | List damage assessments | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/damage-assessments/{id}/dispute` | Renter disputes a damage assessment | Renter |
| POST | `/rental/damage-assessments/{id}/reassess` | Admin reassesses a disputed assessment | ShopAdmin |
| GET | `/rental/ledger-entries/{id}` | Get a ledger entry | ShopAdmin, RentalAgent, Renter |
| GET | `/rental/ledger-entries` | List ledger entries by reservation or customer | ShopAdmin, RentalAgent, Renter |
| POST | `/rental/_clock/set` | Set the server's current UTC clock (test-driving) | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SLOT_FULL` | 409 Conflict |
| `ERR_LESSON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ASSESSMENT_DISPUTED` | 409 Conflict |
</content>
</invoke>

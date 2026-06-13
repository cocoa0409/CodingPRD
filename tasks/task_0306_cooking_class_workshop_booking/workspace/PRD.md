# Cooking Class & Culinary Workshop Booking API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Cooking Class & Culinary Workshop Booking API, the operational backbone of a culinary studio that sells seats at hands-on cooking classes. The studio runs a catalog of class templates spanning skill levels from absolute beginner to working professional, schedules those templates into individual sessions and into repeating series, and sells the finite seats of each session to members who may pay with a mixture of gift cards, studio wallet credit, and an external card. The domain is deceptively rich: seats are a scarce resource competed for under concurrency, kitchens and prep stations cannot be occupied by two sessions at once, members with poor attendance histories must be held back, and every cancellation ripples outward into refunds, waitlist promotions, prep-cost re-allocation, and series-level bookkeeping.

The API exists to make all of that arithmetic and all of those state changes deterministic and auditable. A booking is never a simple "yes"; it is a charge computed from base price, skill surcharge, group-size discounting, and — for private buyouts — a flat fee, settled across a strict funding waterfall, and recorded against a session whose seat count and version must reconcile exactly. Refunds and reliability scores are computed twice: once provisionally at the moment a member acts, and once finally when the session is locked and completed and the real-world outcome (did the freed seat refill? did the member actually show?) is known. This document defines those rules precisely so that an implementation can reproduce the studio's pricing, capacity, dietary-substitution, and member-standing policies without ambiguity.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, the response contract, and the cross-cutting principles that govern every endpoint. The entire API is mounted under the `/culinary` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. When the role is permitted in general but the specific resource being mutated is not owned by the acting principal, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The system recognizes exactly three roles, spelled precisely: `StudioAdmin`, `Instructor`, and `Member`.

`StudioAdmin` is the studio operator and the operational superset for catalog and lifecycle administration. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept it for audit purposes but does not compare it to any entity's `id`. A `StudioAdmin` exclusively registers instructors, creates and publishes and retires class templates, creates and publishes and cancels recurring series, creates and cancels sessions, voids gift cards, and performs operational wallet adjustments. It shares member registration, gift-card issuance, and booking creation with `Member`, and may perform any read.

`Instructor` teaches sessions. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any session-scoped operation compare the session's `instructor_id` foreign key to `X-User-ID`. An `Instructor` opens, locks, and completes its own sessions, marks no-shows on bookings of its own sessions, approves, rejects, and reverts substitution requests on its own sessions, and adds ingredient lines to its own sessions (the latter shared with `StudioAdmin`).

`Member` books seats, manages its own gift cards, and requests dietary substitutions. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks compare the relevant member-foreign-key field — a booking's `member_id`, a waitlist entry's `member_id`, or a gift card's `owner_member_id` — to `X-User-ID`. A `Member` exclusively confirms and cancels its own bookings, joins and withdraws its own waitlist entries, requests substitutions against its own bookings, and reloads its own gift cards. It shares member registration, gift-card issuance, and booking creation with `StudioAdmin`, and may perform reads.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp, `created_at`, in ascending order, so that the oldest resource appears first.

Each list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count` (the total number of matching rows before pagination), and `has_more` (a boolean that is true when rows remain beyond the current page).

### 2.4. Common Resource Properties and Audit Fields

Most resources in this system carry a standard set of system-managed fields. The `id` is a server-minted UUID assigned at creation; it carries no type prefix and is never supplied by the client. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent mutation; it is refreshed on every change. The `version` field is an integer that begins at creation and increments by one on every mutation of the resource, and it underpins the optimistic-concurrency protections described in §2.6.

Two ledger-style entities are deliberately leaner. A `GiftCardTxn` (a single gift-card ledger entry) and a `NoShowRecord` (a single attendance strike) are immutable once written: each carries only an `id` and a `created_at`, and neither carries an `updated_at` nor a `version`. Every other entity — instructors, members, series, templates, sessions, ingredient lines, bookings, waitlist entries, substitution requests, and gift cards — carries the full `id`, `created_at`, `updated_at`, and `version` quartet.

### 2.5. Monetary Values, Precision, and Rounding

Every monetary amount in this system is an integer number of cents — base prices, surcharges, fees, charges, refunds, balances, and wallet credit are all whole-cent integers, and no field stores fractional cents. Where a calculation produces a non-integer intermediate (a percentage discount, a per-seat ingredient cost, a refund tier), the result is rounded to whole cents using the round-half-up convention: a fractional part of exactly one-half rounds away from zero to the next whole cent. Each calculation section below states the exact point at which rounding occurs, because the order of rounding relative to summation and subtraction is significant and is pinned. Two allocation rules deviate from simple rounding and are called out where they apply: the station-cost allocation uses ceiling division (it always rounds up to the next whole cent), and the payment waterfall is exact (its three applied portions sum to the amount due with no rounding at all).

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control because they race against other writers over a shared, version-bumped parent.

The first guard protects seat claims. Confirming a pending booking is a write against the booking's parent `ClassSession`, and the confirm request must carry `expected_session_version` as a non-optional input field holding the client's last observed value of that session's `version`. If the session's current `version` no longer equals the supplied `expected_session_version` — because another writer has since confirmed or cancelled a booking and advanced the session — the confirm is rejected with `ERR_STALE_SESSION_VERSION` at HTTP status 412. This is checked as a version comparison, not as a seat-count comparison: a second writer may have legitimately consumed the last seat under the open-seat semantics, so the confirming client's view of the seat count is stale and the request must be turned away on the version mismatch before any seat arithmetic is attempted.

The second guard protects gift-card reloads. Reloading a depleted gift card is a write against that `GiftCard`, and the reload request must carry `expected_gift_card_version` as a non-optional input field holding the client's last observed `version` of the card. If the card's current `version` no longer equals the supplied `expected_gift_card_version` — because another redemption has depleted it further or another reload has already run — the reload is rejected with `ERR_STALE_GIFT_CARD_VERSION` at HTTP status 412.

No other endpoint takes a version field; operations not described here perform their mutations without an OCC check.

### 2.7. Hierarchical Consistency and Cascades

Many operations in this domain mutate more than one entity in a single atomic request, and every such cascade completes fully or not at all within the triggering request. When a recurring series is cancelled, every one of its non-terminal child sessions is cancelled too, and each of those session cancellations in turn cascades into its own bookings and waitlist entries. When a session completes, its confirmed bookings finalize as attended, its still-pending bookings cancel, its pending attendance strikes settle, and the reliability scores of every affected member are recomputed — all before the request returns. Each of these secondary mutations is a real mutation of its target: it refreshes that resource's `updated_at` and increments its `version`. The detailed cascade rules live in §3 alongside the workflows that trigger them; the principle here is simply that the system never leaves a parent and its children in an inconsistent intermediate state.

### 2.8. Nested Resource Retrieval and Path Validation

Several endpoints address a resource through a path that names a parent before a child — for example, a session's ingredient lines or a session's waitlist. For any such path, identifiers are validated left to right: the parent named earliest in the path is checked first, and the request is rejected with `ERR_NOT_FOUND` against the first identifier in the path that does not resolve to an existing resource, before any later identifier is examined. The same precedence governs request bodies that reference resources by foreign key: a referenced resource that does not exist yields `ERR_NOT_FOUND`. Reverse-reachability list endpoints (for example, listing the sessions spawned by a series, the bookings on a session, the ingredient lines of a session, the transactions of a gift card, or the strike records of a member) likewise resolve the addressed parent first.

### 2.9. Validation Ordering

When several validations could fire on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced resource (`ERR_NOT_FOUND`), then structural validity of the request body — all required fields present, correctly typed, and drawn from the allowed enum values (`ERR_INVALID_REQUEST`). Only after those pass does the system evaluate state validity for transition endpoints (`ERR_INVALID_STATE`), then the optimistic-concurrency version check (`ERR_STALE_SESSION_VERSION` or `ERR_STALE_GIFT_CARD_VERSION`), and finally the domain-specific business rules described throughout §3. Within a single operation, this ordering means a state error surfaces before a stale-version error, and a stale-version error surfaces before a seat-count or other business error.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Instructors and Class Templates

The catalog begins with instructors and the class templates they are qualified to teach. A `StudioAdmin` registers an `Instructor` by supplying a `full_name`, a unique `email` (no two instructors may share an email), and a `max_skill_level` — the highest rung the instructor is certified to teach, drawn from the ordered ladder `BEGINNER`, `INTERMEDIATE`, `ADVANCED`, `PROFESSIONAL`. A newly registered instructor's `status` begins at `ACTIVE`; the only other value it may take is `SUSPENDED`.

A class template is the reusable definition of a class. A `StudioAdmin` creates a `ClassTemplate` with a `title`, a `skill_level` from the same four-rung ladder, a per-seat `base_price_cents` (zero or more), a `default_capacity` between 1 and 40 inclusive that seeds the seat count of sessions built from it, a fixed `station_fixed_cost_cents` (zero or more) representing the per-session kitchen setup cost, a `prep_minutes` value between 0 and 480 inclusive giving the minutes of station occupation required before a session starts, and a `cleanup_minutes` value between 0 and 240 inclusive giving the mandatory buffer after a session ends during which the station is still occupied. A template's `status` starts at `DRAFT`; publishing it moves it to `PUBLISHED` so that series and sessions may instantiate it, and a retired template sits at `RETIRED`. The skill ladder ranks the four levels in the order `BEGINNER` below `INTERMEDIATE` below `ADVANCED` below `PROFESSIONAL`; this ordering is what the system means whenever it compares an instructor's `max_skill_level` against a template's `skill_level`.

### 3.2. Members, Wallets, and the Reliability Ledger

A `Member` is registered — by the member or by a `StudioAdmin` — with a `full_name`, a unique `email`, and an optional `dietary_flags` array of restriction tags (such as `GLUTEN_FREE`, `VEGAN`, or `NUT_ALLERGY`); when omitted, `dietary_flags` defaults to an empty array. The system seeds three accounting fields at registration: `wallet_credit_cents` starts at 0 and is the member's non-withdrawable studio credit balance in cents, which refunds credit and the payment waterfall debits, and which the system never allows to fall below 0; `reliability_score` starts at 100; and `booking_status` starts at `GOOD_STANDING`, the only alternative being `BLOCKED`.

A member accrues attendance strikes over time, each recorded as a `NoShowRecord` carrying the `member_id` of the offender, the `booking_id` that produced it, a `kind` of either `NO_SHOW` (the member never showed) or `LATE_CANCEL` (the member cancelled inside the no-refund window), and a `settlement_status` that begins at `PENDING` and flips to `SETTLED` when the session starts, with `WAIVED` reserved for forgiven strikes. Only `SETTLED` strikes count toward standing. The member's `no_show_count` is the number of that member's `SETTLED` strikes of kind `NO_SHOW`, and `late_cancel_count` is the number of `SETTLED` strikes of kind `LATE_CANCEL`; both are recomputed by the reliability calculation rather than supplied.

The reliability score is computed by starting from a perfect 100 and subtracting a penalty of 25 for each settled no-show and a penalty of 10 for each settled late cancel, then clamping the result so it can be no lower than 0 and no higher than 100. From the resulting score the system derives standing: a member whose reliability score is below 40 is placed in `BLOCKED`, and a member whose score is 40 or above sits in `GOOD_STANDING`. This score is computed in two variants. The **provisional** variant is what a read of a member returns: it counts only the member's `SETTLED` strikes and ignores any still-`PENDING` strike, so a member who has just incurred a no-show but whose session has not yet started still reads the pre-strike score. The **final** variant is computed when a session completes, after that session's pending strikes have flipped to `SETTLED`: the freshly settled strikes are now included, so the score may drop and, if it crosses below 40, the member's `booking_status` flips to `BLOCKED` within the same completion transaction. A `StudioAdmin` may also seed or adjust a member's wallet directly with an operational adjustment that adds a signed `amount_cents` to `wallet_credit_cents`; if the adjustment would drive the balance below 0 it is rejected with `ERR_INVALID_WALLET_ADJUSTMENT`.

### 3.3. Recurring Series and the Sessions They Spawn

A recurring series lets a `StudioAdmin` stamp out many identical sessions at once. A `RecurringSeries` is created in `DRAFT` with a `template_id` naming the catalog template every session will instantiate, an `instructor_id` naming the instructor assigned to every spawned session, a `cadence` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, an `occurrence_count` between 1 and 52 inclusive giving how many sessions to spawn, and a `first_start_at` timestamp marking when the first session begins. Its `status` lifecycle runs `DRAFT`, `PUBLISHED`, `CANCELLED`, and its `active_session_count` — the number of child sessions not yet cancelled or completed — starts at 0.

Publishing a series is restricted to a `StudioAdmin` and is permitted only while the series is in `DRAFT`. Before it may publish, three preconditions must hold: the referenced template must itself be `PUBLISHED`, the referenced instructor must be `ACTIVE`, and the instructor's `max_skill_level` must sit at or above the template's `skill_level` on the skill ladder — otherwise the publish is rejected with `ERR_INSTRUCTOR_SKILL_INSUFFICIENT`. On a successful publish, the series transitions `DRAFT → PUBLISHED` and spawns exactly `occurrence_count` sessions: the first begins at `first_start_at`, and each subsequent session is offset from the first by a fixed interval determined by cadence — 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, and 28 days for `MONTHLY` (these are fixed-length intervals, not calendar months). Concretely, the k-th spawned session (counting from zero) starts at `first_start_at` plus k times the cadence interval. Every spawned session is created in `SCHEDULED`, carries this series' identifier in its `series_id`, copies the template's `default_capacity` into its `planned_seats`, and is a group event. The publish also sets the series' `active_session_count` to `occurrence_count`.

Cancelling a series is also a `StudioAdmin` action and is permitted only while the series is `PUBLISHED`. The cancellation transitions the series `PUBLISHED → CANCELLED` and cascades: every child session whose status is neither `COMPLETED` nor `CANCELLED` is itself cancelled (which cascades further into that session's bookings and waitlist, exactly as a direct session cancellation would), and the series' `active_session_count` is set to 0.

### 3.4. Standing Up a Session: Ingredients, Stations, and Opening

A standalone session is created by a `StudioAdmin` in `SCHEDULED` with a `series_id` of null. The create payload names the `template_id` to instantiate, the `instructor_id` to teach it, the `station_id` of the physical kitchen it occupies, the `event_type` (`GROUP` or `PRIVATE`), a `start_at` and an `end_at` (both ISO 8601 UTC), and a `planned_seats` count between 1 and 40 inclusive. A `PRIVATE` session also carries a `private_event_fee_cents` flat buyout fee (zero or more, ignored entirely for a `GROUP` event); when omitted it defaults to 0. At create time two checks apply: the assigned instructor's `max_skill_level` must be at or above the template's `skill_level` on the skill ladder, or the create is rejected with `ERR_INSTRUCTOR_SKILL_INSUFFICIENT`; and `end_at` must be strictly later than `start_at`, or the create is rejected with `ERR_INVALID_TIME_WINDOW`. A freshly created session has `confirmed_seats` of 0 and `prep_cost_per_seat_cents` of 0; its `status` lifecycle is `SCHEDULED`, `OPEN`, `FULL`, `LOCKED`, `COMPLETED`, `CANCELLED`.

Before a session can open, its recipe is assembled from ingredient lines. An ingredient line is added to a session by a `StudioAdmin` or by the session's `Instructor`, and carries the `session_id` it belongs to, a `name`, a `qty_per_seat` (a decimal quantity of zero or more consumed per booked seat), a `unit_cost_cents` (zero or more, the cost of one unit), and a `dietary_tag`. The `dietary_tag` defaults to `NEUTRAL` and may instead be `CONTAINS_GLUTEN`, `CONTAINS_NUT`, `CONTAINS_DAIRY`, or `ANIMAL_PRODUCT`; only a non-`NEUTRAL` line is eligible to be substituted later. Adding an ingredient line recomputes the session's per-seat prep cost.

That per-seat prep cost is computed in a pinned order. For each ingredient line on the session, taken in ascending `created_at` order, the system multiplies that line's `qty_per_seat` by its `unit_cost_cents` and rounds that single product half-up to whole cents; these per-line whole-cent amounts are then summed to give the ingredient cost per seat. Separately, the template's `station_fixed_cost_cents` is divided by the session's `planned_seats` using ceiling division — that is, any remainder rounds the per-seat station allocation up to the next whole cent. The per-seat prep cost stored on the session is the sum of the ingredient-per-seat total and the station-per-seat allocation. This rounding order is significant: each line is rounded before the lines are summed, never after. The per-seat prep cost is recomputed whenever the ingredient-line set changes, whenever `planned_seats` changes, and whenever a booking confirms or cancels.

Opening a session is an `Instructor` action on its own session and advances it `SCHEDULED → OPEN`, which publishes it for booking and recomputes the per-seat prep cost. Opening requires that the session currently be `SCHEDULED` and that it have at least one ingredient line. Opening also enforces station exclusivity: a station may not host two overlapping occupations. A session's station occupation runs from `prep_minutes` before its `start_at` to `cleanup_minutes` after its `end_at`, treated as a half-open interval, so two occupations that merely touch at a shared endpoint do not overlap. If any other session sharing the same `station_id` and currently in `SCHEDULED`, `OPEN`, `FULL`, or `LOCKED` has an occupation interval that overlaps the opening session's occupation interval, the open is rejected with `ERR_STATION_DOUBLE_BOOKED`.

### 3.5. Booking a Seat: Charge Computation and Confirmation

Booking is a two-step affair: a member (or a `StudioAdmin` on the member's behalf) first creates a booking, which pins its price, and then the member confirms it, which takes the payment and the seat. Creating a `Booking` supplies the `session_id` being booked, the `member_id` who will own it, and a `seats_requested` count between 1 and 40 inclusive. The new booking starts with `lifecycle_status` of `PENDING` and `payment_status` of `UNPAID` — these are two independent dimensions that advance separately. At create time the system pins the booking's `charge_cents` and applies the buyout rule: for a `PRIVATE` session the `seats_requested` must equal the session's `planned_seats` (a whole-studio buyout), failing which the create is rejected with `ERR_PRIVATE_REQUIRES_FULL_BUYOUT`; for a `GROUP` session any `seats_requested` of at least 1 is acceptable.

The charge is computed from the session and its template in a pinned order. For a `PRIVATE` event the charge is simply the session's `private_event_fee_cents` — a flat buyout with no per-seat pricing, no group discount, and no skill surcharge. For a `GROUP` event the charge is built up: a per-seat skill surcharge is selected by the template's `skill_level` — 0 cents for `BEGINNER`, 500 cents for `INTERMEDIATE`, 1200 cents for `ADVANCED`, and 2500 cents for `PROFESSIONAL` — and the subtotal is the template's `base_price_cents` times `seats_requested` plus that per-seat skill surcharge times `seats_requested`. A group-size discount percentage is then chosen by the number of seats: a booking of 2 seats or fewer earns no discount, a booking of 3 to 5 seats earns 5 percent, a booking of 6 to 9 seats earns 10 percent, and a booking of 10 or more seats earns 15 percent. The discount is the subtotal multiplied by that percentage and rounded half-up to whole cents, and the final `charge_cents` is the subtotal minus that rounded discount.

Confirming a booking is a `Member` action on the member's own pending booking and advances both dimensions at once: `lifecycle_status` goes `PENDING → CONFIRMED` and `payment_status` goes `UNPAID → PAID`. A confirm is permitted only when the booking is `PENDING`, the session is `OPEN`, the member's `booking_status` is `GOOD_STANDING`, the seat block fits, and the supplied `expected_session_version` matches the session's current `version`. A `BLOCKED` member attempting to confirm is rejected with `ERR_MEMBER_BLOCKED`. If `confirmed_seats` plus this booking's `seats_requested` would exceed `planned_seats`, the confirm is rejected with `ERR_INSUFFICIENT_SEATS`. On success the system runs the payment waterfall (§3.6) against the booking's `charge_cents`, increments the session's `confirmed_seats` by `seats_requested`, refreshes the session's per-seat prep cost, and increments the session's `version` by one. If `confirmed_seats` reaches `planned_seats` exactly, the session automatically transitions `OPEN → FULL`, after which no further pending booking may confirm and newcomers must join the waitlist instead.

### 3.6. The Payment Waterfall and Gift Cards

Whenever an amount must be collected from a member — the full `charge_cents` at booking confirmation, or an incremental surcharge at substitution approval — it is distributed across three funding sources in a pinned order, and the three resulting portions always sum exactly to the amount due with no rounding. The waterfall first draws on the member's gift cards. Every `GiftCard` that the member owns and that is `ACTIVE` is consulted in ascending `created_at` order — oldest card first, never by identifier — and each card contributes the lesser of its remaining `balance_cents` and the amount still owed, recording that draw as a `REDEEM` ledger entry that reduces the card's balance; the total drawn from gift cards is recorded on the booking as `gift_card_applied_cents`. Whatever remains then draws on the member's `wallet_credit_cents`, contributing the lesser of the wallet balance and the remaining amount, recorded on the booking as `wallet_applied_cents`. Any residual is charged to the external card and recorded as `card_applied_cents`. When a gift card's `balance_cents` reaches 0 through redemption, that card transitions `ACTIVE → DEPLETED` and is no longer selected by the waterfall.

A gift card is issued — by the member or a `StudioAdmin` — with a unique `code`, an `owner_member_id` naming the member who owns and may redeem it, and an `initial_value_cents` face value of at least 1 cent. The new card is `ACTIVE`, its `balance_cents` is seeded to the initial value, and an `ISSUE` ledger entry records the load. Each `GiftCardTxn` records the `gift_card_id` it mutates, the `booking_id` that triggered it (null for an `ISSUE` or `RELOAD`), a `kind` of `ISSUE`, `REDEEM`, `RELOAD`, or `REVERSAL`, and a signed `amount_cents` that is positive for `ISSUE`, `RELOAD`, and `REVERSAL` and negative for `REDEEM`. A card's `balance_cents` equals its initial value minus the sum of redemptions plus the sum of reloads plus any reversal credits. When a booking confirmation selects a gift card for payment, every selected card's `owner_member_id` must equal the acting member; a card belonging to someone else is rejected with `ERR_GIFT_CARD_NOT_OWNED`.

A depleted card can be brought back to life by its owner with a reload. Reloading is permitted only while the card is `DEPLETED` and is guarded by optimistic concurrency: the request supplies an `amount_cents` to add (which must be at least 1 cent, else `ERR_INVALID_RELOAD_AMOUNT`) and an `expected_gift_card_version` that must match the card's current `version`, as described in §2.6. A successful reload appends a `RELOAD` ledger entry, increases `balance_cents` by the reloaded amount, transitions the card `DEPLETED → ACTIVE`, and increments its `version`. A `StudioAdmin` may void an `ACTIVE` card, transitioning it `ACTIVE → VOIDED`, after which its balance is frozen and it is no longer redeemable.

### 3.7. Cancellation, Refunds, and No-Show Handling

When a member cancels a confirmed booking, the refund is computed forward-looking and the freed seat is offered to the waitlist. Cancellation is a `Member` action on the member's own `CONFIRMED` booking and is permitted only while the session is `OPEN` or `FULL`; it advances the booking `CONFIRMED → CANCELLED`. The refund tier is keyed on how many hours separate the moment of cancellation from the session's `start_at`, measured against the system clock: a cancellation at least 168 hours before the start refunds 100 percent, at least 72 hours refunds 75 percent, at least 24 hours refunds 50 percent, and anything inside 24 hours refunds 0 percent. The gross refund is the booking's `charge_cents` times that tier percentage rounded half-up to whole cents, and the base refund is that gross minus a flat cancellation fee of 300 cents, floored at 0 so it can never go negative.

This refund is calculated in two variants. At the moment the member cancels, the **provisional** refund applies the tier formula above and credits that amount; the eventual waitlist outcome is not yet known, so `refilled_from_waitlist` does not enter the figure. The **final** refund is reconciled when the session locks and completes: if by then the booking's vacated seat was taken by a promoted waitlist booking — that is, `refilled_from_waitlist` is true — the refund becomes the full `charge_cents` minus the 300-cent fee (the studio lost no seat revenue, so the tier penalty is waived), and otherwise the provisional figure stands. The difference between the final and provisional figures is credited to or clawed back from the member's wallet at completion. On a provisional cancellation the computed `refund_cents` is credited to `wallet_credit_cents`, the gift-card portion of the original payment is reversed first via `REVERSAL` ledger entries up to `gift_card_applied_cents` with any remainder returned to the wallet, the session's `confirmed_seats` is decremented by `seats_requested`, the per-seat prep cost is refreshed, and the session's `version` is incremented. The booking's `payment_status` becomes `REFUNDED` if the refund equals the original charge and `PARTIALLY_REFUNDED` otherwise. If the cancellation falls within 24 hours of `start_at`, the system also creates a `LATE_CANCEL` strike (`settlement_status` `PENDING`) for the member.

The cancellation then attempts a waitlist promotion (§3.8). If no waitlist entry refills the freed seats and the session was `FULL`, the session automatically returns `FULL → OPEN`. Cancelling a booking that is still merely `PENDING` (whether by the member or as a side effect of a session cancel or complete) sets `refund_cents` to 0 and leaves `payment_status` at `UNPAID`, since nothing was ever paid.

An instructor handles non-attendance directly. Marking a no-show is an `Instructor` action permitted only while the booking is `CONFIRMED` and the session is `LOCKED`; it advances the booking `CONFIRMED → NO_SHOW`, creates a `NO_SHOW` strike (`settlement_status` `PENDING`) for the member, sets `refund_cents` to 0 with the charge forfeit, and leaves `payment_status` unchanged.

### 3.8. Waitlists and Seat Promotion

When a session is `FULL`, a member may queue for a seat. Joining the waitlist is a `Member` action that creates a `WaitlistEntry` carrying the `member_id` and a `seats_requested` count between 1 and 40 inclusive; the new entry's `queue_status` starts at `WAITING` and its `promoted_booking_id` is null. A join is permitted only when the session's status is `FULL` and the joining member has neither an existing `WAITING` entry nor a `CONFIRMED` booking on that same session; any other case is rejected with `ERR_WAITLIST_NOT_ALLOWED`. The full lifecycle of an entry's `queue_status` is `WAITING`, `PROMOTED`, `EXPIRED`, `WITHDRAWN`. A member may withdraw a still-waiting entry, advancing it `WAITING → WITHDRAWN`.

Promotion is triggered automatically when a confirmed booking is cancelled and frees seats while the session is `OPEN` or `FULL`. The system considers the waitlist entries for that session whose `queue_status` is `WAITING` and whose `seats_requested` is no greater than the number of freed seats, and from those candidates it promotes the single oldest by ascending `created_at` (never by identifier, and no further tie-break is needed). At most one entry is promoted per freed booking; seat blocks are never split across multiple waiting members. When a candidate is found, the system creates a new `CONFIRMED` booking for that waiting member with their requested seats and a freshly computed charge, runs the payment waterfall for that new booking, marks the waitlist entry `PROMOTED` with its `promoted_booking_id` set to the new booking, sets the cancelled booking's `refilled_from_waitlist` to true, and increases the session's `confirmed_seats` by the promoted entry's seats. This is a depth-three cascade: a cancel triggers a promotion, which creates a confirmed booking, which itself runs the waterfall. When a session is cancelled by the studio, every `WAITING` entry on it is expired (`WAITING → EXPIRED`) as part of that cascade.

### 3.9. Dietary Substitutions

A member who needs an ingredient swapped requests a substitution against a confirmed booking. Creating a `SubstitutionRequest` supplies the `booking_id` of the confirmed booking, the `ingredient_line_id` of the offending line to swap out, and an `alternate_unit_cost_cents` — the per-unit cost of the replacement ingredient. The request begins in `REQUESTED`; its lifecycle is `REQUESTED`, `APPROVED`, `REJECTED`, `REVERTED`. At creation the named ingredient line must belong to the same session as the booking and its `dietary_tag` must not be `NEUTRAL`; a line that is on a different session or that is `NEUTRAL` makes the request inapplicable and it is rejected with `ERR_SUBSTITUTION_NOT_APPLICABLE`.

Approving a substitution is an `Instructor` action on its own session, permitted only while the substitution is `REQUESTED`, the parent booking is `CONFIRMED`, the session is `OPEN`, `FULL`, or `LOCKED`, and the targeted ingredient line's `dietary_tag` is not `NEUTRAL`. Approval advances the substitution `REQUESTED → APPROVED` and computes the surcharge: the per-unit delta is the alternate unit cost minus the original line's `unit_cost_cents`, floored at 0 so that a cheaper substitute is free rather than a credit, and the `surcharge_cents` is that delta multiplied by the line's `qty_per_seat` and by the booking's `seats_requested`, rounded half-up to whole cents once at the end. The surcharge is added to the parent booking's `charge_cents` and settled through the same gift-card-then-wallet-then-card waterfall, updating the booking's `gift_card_applied_cents`, `wallet_applied_cents`, and `card_applied_cents` by the new deltas, and the booking's `version` is incremented.

An instructor may instead reject a `REQUESTED` substitution (`REQUESTED → REJECTED`), which changes no charge. An instructor may also revert a previously approved substitution while the session is `OPEN`, `FULL`, or `LOCKED`, advancing it `APPROVED → REVERTED`. A revert is a compensating operation: it subtracts the exact `surcharge_cents` that approval had added back out of the booking's `charge_cents`, and reverses the waterfall debits in the opposite order — card first, then wallet, then gift card via `REVERSAL` ledger entries — so that each funding source returns to its pre-approval value and the booking's `charge_cents` and the sum of its three applied funding fields both return to their pre-approval totals; the booking's `version` is incremented.

### 3.10. Locking, Completion, and the Attended/No-Show Settlement

The instructor closes out a session in two steps. Locking is an `Instructor` action permitted while the session is `OPEN` or `FULL` and advances it to `LOCKED`, which freezes the roster: no new bookings and no waitlist promotions occur on a locked session, though substitution requests remain allowed. Completing is an `Instructor` action permitted only while the session is `LOCKED` and advances it `LOCKED → COMPLETED`. Completion finalizes everything in one atomic transaction. Every confirmed child booking is finalized as attended (`CONFIRMED → ATTENDED`) unless it has already been marked `NO_SHOW`. Every child booking still `PENDING` is cancelled with its `refund_cents` computed under the final variant. Every `NoShowRecord` attached to the session's bookings that is still `PENDING` flips to `SETTLED`, at which point it counts toward reliability. The reliability score of every affected member is then recomputed under the final variant, and any member whose recomputed `reliability_score` falls below 40 has their `booking_status` set to `BLOCKED`. Finally, if the session belongs to a series, that series' `active_session_count` is decremented by one.

Studio-side cancellation is a different, blameless path. A `StudioAdmin` may cancel a session from any of `SCHEDULED`, `OPEN`, `FULL`, or `LOCKED`, moving it to `CANCELLED`. Because the studio is at fault, every child booking that is `PENDING` or `CONFIRMED` is cancelled with a full refund of its entire charge — the 300-cent cancellation fee is waived — its `payment_status` set to `REFUNDED` and the refund credited to the member's wallet; every `WAITING` waitlist entry on the session is expired; and if the session belongs to a series, that series' `active_session_count` is decremented by one.

The session's seat count oscillates over its life. As bookings confirm, the session climbs toward `FULL`; as confirmed bookings cancel without a waitlist refill, a `FULL` session drops back to `OPEN`. This `OPEN`–`FULL` oscillation is normal and is driven entirely by the automatic transitions described in §3.5 and §3.7.

### 3.11. The Test-Driving Clock

Because refund tiers and the late-cancel window depend on real elapsed time, the system exposes a logical clock for deterministic test driving. A `StudioAdmin` may set the server's current UTC instant by supplying a `to_iso8601` timestamp; the supplied value becomes the `current_utc` against which the cancellation refund's hours-before-start arithmetic and the 24-hour late-cancel window are measured. This is an operational capability, not a domain workflow, and it exists so that the time-dependent refund and strike rules can be exercised at any chosen instant.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition operations that advance an entity through its lifecycle — return a `200 OK` status code. Every list endpoint accepts the `limit` and `offset` pagination query parameters described in §2.3, in addition to any filters noted in its description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/culinary/instructors` | Register an instructor | StudioAdmin |
| GET | `/culinary/instructors/{id}` | Fetch an instructor | StudioAdmin, Instructor |
| POST | `/culinary/members` | Register a member | StudioAdmin, Member |
| GET | `/culinary/members/{id}` | Fetch a member (reliability score under provisional variant) | StudioAdmin, Member |
| GET | `/culinary/members/{id}/no-show-records` | List a member's strike records | StudioAdmin, Member |
| POST | `/culinary/members/{id}/wallet/adjustments` | Operational wallet credit adjustment | StudioAdmin |
| POST | `/culinary/templates` | Create a catalog template in DRAFT | StudioAdmin |
| POST | `/culinary/templates/{id}/publish` | Publish a template | StudioAdmin |
| GET | `/culinary/templates/{id}` | Fetch a template | StudioAdmin, Instructor, Member |
| POST | `/culinary/series` | Create a recurring series in DRAFT | StudioAdmin |
| POST | `/culinary/series/{id}/publish` | Publish a series, spawning its sessions | StudioAdmin |
| POST | `/culinary/series/{id}/cancel` | Cancel a series and cascade-cancel its sessions | StudioAdmin |
| GET | `/culinary/series/{id}` | Fetch a series | StudioAdmin, Instructor, Member |
| GET | `/culinary/series` | List/filter series (by `template_id`, `instructor_id`, `status`) | StudioAdmin, Instructor, Member |
| GET | `/culinary/series/{id}/sessions` | List sessions spawned by a series | StudioAdmin, Instructor, Member |
| POST | `/culinary/sessions` | Create a standalone session in SCHEDULED | StudioAdmin |
| GET | `/culinary/sessions/{id}` | Fetch a session | StudioAdmin, Instructor, Member |
| GET | `/culinary/sessions` | List/filter sessions (by `template_id`, `series_id`, `instructor_id`, `status`) | StudioAdmin, Instructor, Member |
| POST | `/culinary/sessions/{id}/open` | Open a session for booking | Instructor |
| POST | `/culinary/sessions/{id}/lock` | Lock the roster | Instructor |
| POST | `/culinary/sessions/{id}/complete` | Complete a session and finalize bookings | Instructor |
| POST | `/culinary/sessions/{id}/cancel` | Studio-cancel a session with full refunds | StudioAdmin |
| POST | `/culinary/sessions/{id}/ingredient-lines` | Add an ingredient line to a session | StudioAdmin, Instructor |
| GET | `/culinary/sessions/{id}/ingredient-lines` | List a session's ingredient lines | StudioAdmin, Instructor, Member |
| POST | `/culinary/bookings` | Create a PENDING booking; pins charge | Member, StudioAdmin |
| POST | `/culinary/bookings/{id}/confirm` | Confirm a booking under session OCC | Member |
| POST | `/culinary/bookings/{id}/cancel` | Member-cancel a booking; provisional refund and promotion | Member |
| POST | `/culinary/bookings/{id}/mark-no-show` | Mark a confirmed booking a no-show | Instructor |
| GET | `/culinary/bookings/{id}` | Fetch a booking | StudioAdmin, Instructor, Member |
| GET | `/culinary/bookings` | List bookings (by `session_id`, `member_id`, `lifecycle_status`) | StudioAdmin, Instructor, Member |
| POST | `/culinary/sessions/{id}/waitlist` | Join the waitlist of a FULL session | Member |
| POST | `/culinary/waitlist-entries/{id}/withdraw` | Withdraw a waitlist entry | Member |
| GET | `/culinary/sessions/{id}/waitlist` | List a session's waitlist entries | StudioAdmin, Instructor, Member |
| GET | `/culinary/waitlist-entries/{id}` | Fetch a single waitlist entry | StudioAdmin, Instructor, Member |
| GET | `/culinary/waitlist-entries` | List waitlist entries (by `member_id`, `session_id`, `promoted_booking_id`, `queue_status`) | StudioAdmin, Member |
| POST | `/culinary/substitutions` | Request a dietary substitution | Member |
| POST | `/culinary/substitutions/{id}/approve` | Approve a substitution and bill the surcharge | Instructor |
| POST | `/culinary/substitutions/{id}/reject` | Reject a substitution | Instructor |
| POST | `/culinary/substitutions/{id}/revert` | Revert an approved substitution | Instructor |
| GET | `/culinary/substitutions/{id}` | Fetch a substitution request | StudioAdmin, Instructor, Member |
| GET | `/culinary/substitutions` | List substitutions (by `booking_id`, `ingredient_line_id`, `status`) | StudioAdmin, Instructor, Member |
| POST | `/culinary/gift-cards` | Issue a gift card to a member | StudioAdmin, Member |
| POST | `/culinary/gift-cards/{id}/reload` | Reload a depleted gift card under OCC | Member |
| POST | `/culinary/gift-cards/{id}/void` | Void an active gift card | StudioAdmin |
| GET | `/culinary/gift-cards/{id}` | Fetch a gift card with current balance | StudioAdmin, Member |
| GET | `/culinary/gift-cards` | List gift cards (by `owner_member_id`, `status`) | StudioAdmin, Member |
| GET | `/culinary/gift-cards/{id}/transactions` | List a gift card's ledger transactions | StudioAdmin, Member |
| GET | `/culinary/gift-card-transactions/{id}` | Fetch a single gift-card transaction | StudioAdmin, Member |
| GET | `/culinary/gift-card-transactions` | List gift-card transactions (by `booking_id`, `gift_card_id`, `kind`) | StudioAdmin, Member |
| GET | `/culinary/no-show-records/{id}` | Fetch a single strike record | StudioAdmin, Member |
| GET | `/culinary/no-show-records` | List strike records (by `member_id`, `booking_id`, `kind`) | StudioAdmin, Member |
| POST | `/_clock/set_current_utc` | Set the server's logical current UTC clock (test-driving) | StudioAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_GIFT_CARD_VERSION` | 412 |
| `ERR_INSTRUCTOR_SKILL_INSUFFICIENT` | 422 |
| `ERR_MEMBER_BLOCKED` | 403 |
| `ERR_SUBSTITUTION_NOT_APPLICABLE` | 422 |
| `ERR_GIFT_CARD_NOT_OWNED` | 403 |
| `ERR_PRIVATE_REQUIRES_FULL_BUYOUT` | 422 |
| `ERR_INSUFFICIENT_SEATS` | 409 |
| `ERR_STATION_DOUBLE_BOOKED` | 409 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_WAITLIST_NOT_ALLOWED` | 409 |
| `ERR_INVALID_RELOAD_AMOUNT` | 422 |
| `ERR_INVALID_WALLET_ADJUSTMENT` | 422 |

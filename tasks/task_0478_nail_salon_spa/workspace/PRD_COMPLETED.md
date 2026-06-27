# Nail Salon & Spa Services API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Nail Salon & Spa Services API, the operational backbone of a multi-chair nail studio that juggles walk-in traffic, pre-booked appointments, technician scheduling, and the regulatory burden of sanitation compliance. A nail salon is deceptively complex: a single appointment threads together a client's booking posture, a technician's licensing and pay arrangement, a physical station whose sterilization state can change between cycles, a menu of services and à-la-carte add-ons, and a settlement step that touches deposits, loyalty points, and gift cards in one motion. This API exists to make those interactions deterministic and auditable.

The system models two largely independent dimensions of an appointment — where it stands in the *booking* journey (from request through service to completion) and where it stands in the *payment* journey (from unpaid through deposit to final settlement) — and keeps them in step without conflating them. Layered on top are the studio's protective controls: a no-show strike regime that escalates repeat offenders into mandatory deposits, an autoclave sterilization log that gates whether a chair may be used at all, and a technician earnings ledger that splits revenue differently depending on whether a technician works on commission or rents a booth. The remainder of this document defines the global contracts that every endpoint honors (Section 2) and then the business workflows that govern each entity's life (Section 3), before cataloguing the endpoints (Section 4) and error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that every endpoint obeys regardless of the business workflow it serves.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `SalonManager`, `FrontDesk`, `Technician`, and `Client`. When a recognized role attempts an operation it is not permitted to perform — or when an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

A `SalonManager` is the configuration and oversight authority. The manager owns the technician roster and its lifecycle, the station inventory, the service menu and add-on catalogue, gift-card voiding, and commission settlement, and may read across every collection. A `FrontDesk` operator runs the front-of-house flow: creating clients, booking appointments, collecting deposits, confirming, checking in, checking out, cancelling, marking no-shows, and issuing or redeeming gift cards. Both `SalonManager` and `FrontDesk` carry **opaque** identities: when `X-User-Role` is `SalonManager` or `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may accept and record it but does not compare it to any entity's `id`, and these two roles are never subject to ownership checks.

The remaining two roles are **entity-backed** and therefore subject to ownership comparison. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID`. A technician may begin service on their own appointment, record sanitation cycles, and read their own technician record, their own appointments, and their own commission statements. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. A client may cancel their own appointment and read their own client record, their own appointments, and their own gift cards.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`; it is a random 20-character alphanumeric suffix appended to the `req_` prefix.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Unlike resource `created_at`/`updated_at` stamps, this envelope timestamp is read from real wall-clock time, not the logical clock of Section 2.5.
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

List endpoints accept two query parameters for pagination. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the 1-to-100 range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by a server-assigned monotonic insertion sequence (creation order) rather than by `id`. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items returned on this page is strictly less than `total_count`.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system carry four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. Both `created_at` and `updated_at` are stamped from the logical clock of Section 2.5 (not real wall-clock time), so that period sweeps such as commission settlement (Section 3.16) read consistent instants. The `version` is an integer that starts at 1 and increments by one on every mutation of the resource; it underpins optimistic concurrency control (Section 2.9).

Two entities are deliberate exceptions that carry only `id` and `created_at`, with no `updated_at` and no `version`: the `SanitationLog`, which is an append-only audit record, and the `AppointmentAddOn` junction row that links an appointment to a selected add-on. Both are immutable once written, so neither receives an `updated_at` timestamp nor a `version` counter. Every other entity — `Technician`, `Station`, `ServiceMenuItem`, `AddOn`, `Client`, `Appointment`, `GiftCard`, and `CommissionStatement` — carries the full four-field set.

### 2.5. The Logical Clock

Every deadline, expiry, decay, and grace calculation in the system reads a single server-side **logical clock** rather than wall-clock time. At server startup the clock is fixed at `2026-01-01T00:00:00Z`, and until it is explicitly advanced it reads exactly this default; it never falls back to real time. An operator may advance the clock to a supplied `to_iso8601` instant via an administrative test-driving capability. License expiry checks, sanitation freshness windows, no-show grace and strike decay, and the cancellation free-window all evaluate against this clock.

### 2.6. Nested Resource Retrieval and Referential Existence

Many endpoints address a resource through a path identifier, and several address a child through a parent (for example, the add-ons attached to a given appointment, or the sanitation logs for a given station). The system validates path identifiers and body foreign keys strictly left-to-right: the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any later identifier or any body field is examined. The same `ERR_NOT_FOUND` rule applies to every foreign key supplied in a request body — `client_id`, `technician_id`, `station_id`, `service_item_id`, `gift_card_id`, `add_on_id`, `logged_by_technician_id`, `purchaser_client_id`, and `appointment_id` — each of which must reference an existing resource, validated in the order the body presents them.

### 2.7. Monetary Values, Points, and Precision

All monetary amounts in the system are stored and computed as integer **cents**; there are no fractional cents anywhere. Where a calculation produces a non-integer cent value — specifically the commission multiplications described in Section 3 — the result is rounded half up to the nearest whole cent. Loyalty points are whole integers. When loyalty points are converted to a cash value during settlement, the number of points actually consumed is computed by rounding up to the next whole point, so that any partial point needed to cover a cent amount consumes a full point. These precision rules are absolute: a reader reconstructing any total must use integer-cent arithmetic with half-up rounding on commission products and ceiling rounding on consumed loyalty points.

### 2.8. Sanitation Posture, Station Occupancy, and Derived State

Several fields are never written directly by clients but are **derived** on read. A `Station` exposes a `sanitation_status` of either `CLEAN` or `DIRTY`, a `last_pass_sanitation_at` timestamp, and an `in_service_appointment_id` pointer, all of which the system recomputes rather than stores as authoritative input. The `sanitation_status` is derived from the station's sanitation log history as described in Section 3; `last_pass_sanitation_at` is the `created_at` of the most recent passing log, or null if none exists; and `in_service_appointment_id` points to the appointment currently occupying the station, or null when the chair is free. Likewise a `Client` exposes a `deposit_required` flag and an `active_no_show_strikes` count that are recomputed against the logical clock on read. When a derived field's recomputation changes a stored field on the same entity, that counts as a mutation and refreshes `updated_at` and increments `version`.

### 2.9. Optimistic Concurrency Control

Three write operations require the client to prove it is acting on a current view of the target resource by supplying the resource's last-observed `version`: appointment checkout, standalone gift-card redemption, and add-on attachment (each carrying `expected_appointment_version` or `expected_gift_card_version` as noted below). These are the only endpoints that take a version field; every other write endpoint does not accept one and performs no version check.

The first is **appointment checkout**, which settles an appointment and runs the full settlement cascade described in Section 3.10 (gift-card draw, loyalty redemption, deposit credit, commission accrual, loyalty award, station release). A checkout request must carry `expected_appointment_version`. The server compares it to the target appointment's current `version`. If an add-on attach, a deposit payment, or a re-confirmation has advanced the appointment's `version` since the client last read it, the snapshotted subtotal the client is about to charge against is stale, and the checkout is rejected with `ERR_STALE_VERSION` (HTTP 412). The version guard is the only thing distinguishing a stale view from a legitimate checkout against an in-service appointment.

The second is **standalone gift-card redemption**, a manual balance draw against a gift card. The request must carry `expected_gift_card_version`. The server compares it to the target gift card's current `version`; if a prior redemption or a checkout draw has lowered the balance and advanced the card's `version` since the client last read it, the redemption is rejected with `ERR_STALE_VERSION` (HTTP 412), because the writer's view of the remaining balance is stale and the draw it computed could overdraw the card.

The third is **add-on attachment** (Section 3.5), which appends an add-on to a `REQUESTED` appointment. The request must carry `expected_appointment_version`; the server compares it to the appointment's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This OCC comparison is evaluated after the appointment-state and item-retirement checks of that workflow.

### 2.10. Cascading Side Effects and Cross-Entity Consistency

A handful of operations in this system mutate more than one entity in a single atomic step, and every one of those secondary effects is part of the contract. Checkout settles payment, accrues a technician's earnings, awards a client loyalty points, draws down a gift card (possibly depleting it), and frees a station — five entities touched by one call. Marking a no-show increments a client's strike count, may flip the client's deposit requirement, may forfeit a held deposit, and increments a technician's informational no-show tally. Refunding a settled appointment reverses the entire checkout cascade. Settling a commission statement resets a technician's accrued earnings to zero. Each of these cascades is detailed in the relevant Section 3 workflow; the governing principle here is that whenever an operation changes a related entity, that related entity's own `updated_at` and `version` are updated as part of the same operation.

### 2.11. Validation Ordering

When several checks could apply to a single request, the system evaluates them in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` before anything else. Authorization is checked second: a role not permitted for the operation, or an entity-backed actor acting on a resource it does not own, yields `ERR_FORBIDDEN`. Third, referential existence is checked — every path id and every body foreign key must resolve, left-to-right, or `ERR_NOT_FOUND` is returned. Fourth, the request body's structural well-formedness is checked: required fields present, enum values legal, integers within their declared ranges, and `start_at` parsing as an ISO 8601 instant, failing which `ERR_INVALID_REQUEST` is returned. Fifth, uniqueness collisions on create yield `ERR_DUPLICATE_RESOURCE`. Sixth, an attempted state transition that is not defined from the resource's current state yields `ERR_INVALID_STATE`. Only after these foundational checks pass does the system evaluate the domain-specific business rules (item-retirement, sterilization, licensing, scheduling overlaps, grace timing, deposit, loyalty, gift-card, and OCC checks), each described alongside the workflow it guards. Pagination-bound checks on list endpoints yield `ERR_INVALID_PAGINATION`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Studio: Technicians and Their Pay Models

A `SalonManager` populates the studio's roster by creating each `Technician` with a `full_name`, a `license_number`, a `license_expiry` instant, a `pay_model`, and a `home_station_id` naming the station the technician normally works. The `full_name` must be non-empty and the `license_number` must be non-empty and unique across all technicians; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. The `pay_model` is one of `COMMISSION` or `BOOTH_RENT`, and it determines how the technician is paid.

For a `COMMISSION` technician, the salon retains a fraction of each service's revenue defined by `commission_pct`, a number between 0 and 1 inclusive that defaults to 0.40; the technician keeps the complementary fraction. The `booth_rent_cents` field is ignored for commission technicians. For a `BOOTH_RENT` technician, the salon withholds a flat `booth_rent_cents` amount — a non-negative integer defaulting to 0 — once per settlement statement rather than per appointment, and `commission_pct` is ignored. Each technician also carries system-managed fields: a `status` lifecycle flag defaulting to `ACTIVE`, an `accrued_earnings_cents` running total of unsettled earnings defaulting to 0, and a `lifetime_no_show_strikes_attributed` counter defaulting to 0 that tallies how many of this technician's appointments ended in a no-show. The last field is purely informational and never gates any operation.

A technician's `status` moves through a small branching machine. Suspending an `ACTIVE` technician transitions `status` to `SUSPENDED`, but only when no appointment on that technician is currently `IN_SERVICE`; otherwise the transition is not available from the current state and is rejected with `ERR_INVALID_STATE`. Reinstating a `SUSPENDED` technician returns `status` to `ACTIVE`, but only if the technician's `license_expiry` is strictly after the current logical clock — a lapsed license cannot be reinstated, and an attempt is rejected with `ERR_LICENSE_EXPIRED`. Terminating a `SUSPENDED` technician moves `status` to `TERMINATED`, the terminal state, but only when the technician's `accrued_earnings_cents` equals 0, so that all outstanding earnings have been folded into a settled statement first; a non-zero balance makes the transition unavailable and yields `ERR_INVALID_STATE`. Each of these three transitions increments the technician's `version` by one.

### 3.2. Stations and the Sanitation Discipline

A `SalonManager` defines each physical chair as a `Station` with a `name` that must be non-empty and unique across stations (a collision yields `ERR_DUPLICATE_RESOURCE`), and a `requires_autoclave` boolean that defaults to true. A new station's derived `sanitation_status` begins `DIRTY` until a passing sterilization cycle is logged against it.

Sterilization cycles are recorded as append-only `SanitationLog` entries, which a `Technician` or a `SalonManager` may submit. A log carries the `station_id` of the serviced chair, the `logged_by_technician_id` of the technician who ran the cycle, a `cycle_result` of either `PASS` or `FAIL`, a `cycle_temp_c` peak chamber temperature in Celsius (which must be greater than 0), and a `hold_minutes` count of minutes held at temperature (a non-negative integer). A log claiming `PASS` is only honored if its `cycle_temp_c` is at least 121.0 and its `hold_minutes` is at least 30; a `PASS` claim that fails either of these thresholds is physically inconsistent and is rejected with `ERR_STERILIZATION_INVALID`. When a `PASS` log is accepted, the station's `sanitation_status` recomputes to `CLEAN` and its `last_pass_sanitation_at` is stamped with the log's `created_at`; when a `FAIL` log is accepted, the station's `sanitation_status` recomputes to `DIRTY`.

A station's `sanitation_status` is always a fresh derivation, never a stale stored flag. To compute it, take the station's sanitation logs ordered by `created_at` descending and consider the single most recent log. If there is no log at all, or that most recent log has `cycle_result` of `FAIL`, the status is `DIRTY`. If the most recent log is a `PASS` and the elapsed time from its `created_at` to the current logical clock is less than 24 hours, the status is `CLEAN`. If the most recent log is a `PASS` but that elapsed time is 24 hours or more, the status is `DIRTY` — the boundary is strict, so a pass exactly 24 hours old is already stale and reads `DIRTY`, while anything under 24 hours reads `CLEAN`. Separately, `last_pass_sanitation_at` always reflects the `created_at` of the most recent passing log regardless of staleness, or null if none has ever passed.

### 3.3. The Service Menu and Add-Ons

The `SalonManager` curates two catalogues. A `ServiceMenuItem` is created with a `name` (non-empty), a `category` of `MANICURE`, `PEDICURE`, or `ENHANCEMENT`, a `duration_minutes` of at least 5 standard chair-time minutes, and a `base_price_cents` list price (a non-negative integer). It may also carry a `loyalty_points_award` (a non-negative integer defaulting to 0) credited to the client when an appointment for the service completes, and a `requires_sterile_station` boolean defaulting to true that marks whether the service may only run at a chair whose `sanitation_status` is `CLEAN`. Each item also has a system-managed `is_active` flag defaulting to true; the manager may retire an item, flipping `is_active` to false. Retiring an item whose `is_active` is already false is an undefined transition and is rejected with `ERR_INVALID_STATE`. A retired item cannot be newly booked, but historical appointments that already reference it remain intact. Within the active set, a menu item's `name` must be unique on creation, and a collision yields `ERR_DUPLICATE_RESOURCE`.

An `AddOn` is created with a `name` (non-empty), a `price_cents` charge added to the appointment subtotal (a non-negative integer), and an `extra_minutes` contribution to chair time (a non-negative integer defaulting to 0). Like menu items, an add-on carries a system-managed `is_active` flag defaulting to true.

### 3.4. Clients, No-Show Strikes, and the Deposit Regime

A `FrontDesk` operator or `SalonManager` registers a `Client` with a `full_name` (non-empty) and an `email` that must be non-empty and unique across clients (a collision yields `ERR_DUPLICATE_RESOURCE`). The system maintains four computed fields on every client: a `loyalty_points_balance` of redeemable points (defaulting to 0), an `active_no_show_strikes` rolling count of unexpired strikes (defaulting to 0), a `deposit_required` flag (defaulting to false), and a `last_no_show_at` timestamp marking the most recent no-show (null until one occurs).

Strikes do not last forever. The `active_no_show_strikes` value is recomputed on read by decaying the stored raw strike count against the elapsed time since `last_no_show_at`. If `last_no_show_at` is null, the effective count equals the stored raw count. Otherwise, take the whole number of days that have elapsed from `last_no_show_at` to the current logical clock — that is, the elapsed seconds divided by 86,400 and rounded down — and from it derive the number of decayed strikes as that elapsed-day count divided by the decay window of 30 days, again rounded down. The effective `active_no_show_strikes` is then the stored raw count minus the decayed count, clamped so it never drops below 0. In practical terms, a client whose most recent no-show was under 30 days ago suffers no decay, a client past 30 days loses one strike, and a client past 60 days (two full windows) loses two strikes.

The `deposit_required` flag is itself derived from the decayed strike count: it is true exactly when `active_no_show_strikes` is at least 2, and false otherwise. The threshold is inclusive at 2, so one strike does not require a deposit but two do. Fetching a client always recomputes the decayed `active_no_show_strikes` and re-derives `deposit_required` against the current clock before responding.

### 3.5. Booking an Appointment

A `FrontDesk` operator or `SalonManager` books an `Appointment` by supplying a `client_id`, a `technician_id`, a `station_id`, a `service_item_id`, an `origin` of either `WALK_IN` or `APPOINTMENT`, and an optional `start_at`. For a `WALK_IN`, if `start_at` is omitted it defaults to the current logical clock; for an `APPOINTMENT`, `start_at` is mandatory and an omitted (or empty) value is rejected with `ERR_INVALID_REQUEST`. The booked `service_item_id` must reference a menu item whose `is_active` is true; booking a retired service is rejected with `ERR_ITEM_RETIRED`. A new appointment begins with `booking_status` of `REQUESTED` and `payment_status` of `UNPAID`, the initial states of the two parallel dimensions described in Section 3.6.

At booking time the system performs **deposit assessment** against the client's current posture. It reads the client's `active_no_show_strikes` (after decay) and, if that effective count is at least 2 — the deposit threshold — it sets the appointment's `deposit_due_cents` to the flat deposit of 2000 cents; otherwise it sets `deposit_due_cents` to 0. The client's `deposit_required` is not separately stored or mutated by booking: it is the derived flag of Section 2.8, recomputed from the decayed strike count on every read, so it already reads true when the effective count is at least 2 and false otherwise. Booking therefore writes only the appointment's `deposit_due_cents` and leaves the client record untouched. The appointment's window end, `end_at`, is computed as the `start_at` plus the service's `duration_minutes` plus the sum of the `extra_minutes` of any attached add-ons, expressed as a half-open interval that includes the start instant and excludes the end instant. Other computed appointment fields begin at their defaults: `deposit_paid_cents` at 0, `subtotal_cents` at 0, `total_charged_cents` at 0, `technician_earning_cents` at 0, and the idempotency guard `no_show_strike_charged` at false.

Add-ons are attached to a `REQUESTED` appointment one at a time by a `FrontDesk` operator or `SalonManager`, who supplies the `add_on_id` to select and the `expected_appointment_version` reflecting the version they last observed. Attaching creates an `AppointmentAddOn` junction row recording the `appointment_id`, the `add_on_id`, a `price_cents_snapshot` copying the add-on's `price_cents` at attach time, and an `extra_minutes_snapshot` copying its `extra_minutes`, so that later edits to the add-on catalogue never change a booked appointment. The selected add-on's `is_active` must be true, or the attach is rejected with `ERR_ITEM_RETIRED`. Attaching recomputes the appointment's `end_at` and increments the appointment's `version` by one.

### 3.6. The Two Parallel Dimensions of an Appointment

An appointment carries two independent state dimensions that advance separately. The **booking dimension**, `booking_status`, runs `REQUESTED` → `CONFIRMED` → `CHECKED_IN` → `IN_SERVICE` → `COMPLETED`, with `CANCELLED` and `NO_SHOW` as alternative terminal outcomes; `COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal. The **payment dimension**, `payment_status`, runs from `UNPAID` to `DEPOSIT_HELD` and ultimately to `SETTLED`, with `REFUNDED` and `FORFEITED` as the other terminal payment outcomes. The two dimensions interact at specific moments — a deposit-required client cannot confirm until a deposit is held, checkout settles payment while completing the booking, a no-show may forfeit a held deposit — but otherwise each advances on its own. An attempt to drive either dimension along a transition that is not defined from its current value is rejected with `ERR_INVALID_STATE`.

Collecting a deposit is a payment-dimension transition. A `FrontDesk` operator or `SalonManager` pays the owed deposit on an appointment whose `payment_status` is `UNPAID`, whose `deposit_due_cents` is greater than 0 (a deposit must actually be owed), and whose `booking_status` is `REQUESTED` or `CONFIRMED`. A request that violates any of these three preconditions — payment already past `UNPAID`, no deposit owed, or a booking status outside `REQUESTED`/`CONFIRMED` — is rejected with `ERR_INVALID_STATE`. This sets `deposit_paid_cents` equal to `deposit_due_cents`, advances `payment_status` from `UNPAID` to `DEPOSIT_HELD`, and increments the appointment's `version` by one. Because the dimensions are independent, a still-`REQUESTED` appointment can hold a deposit before it is ever confirmed.

### 3.7. Confirmation: Scheduling Guards and Subtotal Snapshot

Confirming a `REQUESTED` appointment, an action of `FrontDesk` or `SalonManager`, advances `booking_status` from `REQUESTED` to `CONFIRMED` and is the point at which the system enforces the schedule. Several guards apply here. First, if the booking client's `deposit_required` is true, the appointment's `payment_status` must already be `DEPOSIT_HELD`; a deposit-required client whose deposit has not been collected cannot confirm, and the attempt is rejected with `ERR_DEPOSIT_REQUIRED`.

Second, the confirmation enforces a **technician double-book guard**: the appointment's half-open window from `start_at` to `end_at` must not overlap the window of any other appointment on the same `technician_id` that is in `CONFIRMED`, `CHECKED_IN`, or `IN_SERVICE`. Any such overlap with zero buffer is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`.

Third, the confirmation enforces a **station turnover-buffer guard**: for every other appointment on the same `station_id` in `CONFIRMED`, `CHECKED_IN`, or `IN_SERVICE`, the two windows must be separated by a gap of at least the 10-minute station turnover allowance. Concretely, the new appointment satisfies the guard only if its `start_at` is at or after the other appointment's `end_at` plus 10 minutes, or its own `end_at` plus 10 minutes is at or before the other's `start_at`. A new `start_at` that falls strictly less than the other's `end_at` plus 10 minutes — while not lying entirely before that other window — conflicts and is rejected with `ERR_STATION_TURNOVER_CONFLICT`. The boundary is inclusive: a gap of exactly 10 minutes is allowed.

When confirmation succeeds, the system snapshots `subtotal_cents` as the service's `base_price_cents` plus the sum of the `price_cents_snapshot` values of all attached add-ons, recomputes `end_at` from the service duration plus add-on extra minutes, and increments the appointment's `version` by one. These checks are evaluated in the priority order of Section 2.11 — the deposit requirement is a fiscal check, while the double-book and turnover guards are temporal checks — so a transition that is undefined for the current `booking_status` surfaces as `ERR_INVALID_STATE` before any scheduling guard runs.

### 3.8. Check-In: License and Sterilization Gates

Checking in a `CONFIRMED` appointment, performed by `FrontDesk` or `SalonManager`, advances `booking_status` from `CONFIRMED` to `CHECKED_IN` and is gated by two cross-entity safety checks. The assigned technician must be fit to work: the technician's `status` must be `ACTIVE` and the technician's `license_expiry` must be strictly after the current logical clock. A suspended, terminated, or lapsed-license technician blocks check-in with `ERR_LICENSE_EXPIRED`.

The station must also be sterile when sterilization is required. If either the booked service's `requires_sterile_station` is true or the station's `requires_autoclave` is true, then the station's `sanitation_status` must be `CLEAN` at check-in time; if sterilization is required but the station is not clean, the check-in is rejected with `ERR_STATION_NOT_STERILE`. When both gates would fail, the station-sterility gate is evaluated first, so `ERR_STATION_NOT_STERILE` takes precedence over `ERR_LICENSE_EXPIRED`. A successful check-in increments the appointment's `version` by one.

### 3.9. Starting Service: Station Occupancy

A `Technician` (acting on their own appointment) or a `SalonManager` begins service on a `CHECKED_IN` appointment, advancing `booking_status` from `CHECKED_IN` to `IN_SERVICE`. This transition is available only when the assigned station's `in_service_appointment_id` is null — that is, the chair is not already occupied by another in-progress service. Starting service sets that station's `in_service_appointment_id` to this appointment's `id`, marking the chair occupied, and increments the appointment's `version` by one. Because `in_service_appointment_id` is a derived pointer rather than a stored foreign key, the occupying appointment can also be discovered in reverse by listing appointments filtered to a given `station_id` and `booking_status` of `IN_SERVICE`.

### 3.10. Checkout: The Settlement Cascade

Checkout is the system's most intricate operation. A `FrontDesk` operator or `SalonManager` checks out an `IN_SERVICE` appointment, advancing `booking_status` from `IN_SERVICE` to `COMPLETED` while settling payment. The request supplies `expected_appointment_version` (the OCC field of Section 2.9), and optionally `loyalty_points_redeemed` (defaulting to 0) and a `gift_card_id`. Several preconditions apply: the `payment_status` must be `UNPAID` or `DEPOSIT_HELD` (it must not already be settled); if a `gift_card_id` is supplied, that card's `status` must be `ACTIVE`; the `loyalty_points_redeemed` must not exceed the client's `loyalty_points_balance`, or the checkout is rejected with `ERR_INSUFFICIENT_LOYALTY`; and the `expected_appointment_version` must match the appointment's current `version`, or the checkout is rejected with `ERR_STALE_VERSION`.

The **settlement waterfall** runs in a strictly pinned order, resolving what looks like a circular dependency. Begin with the gross equal to the snapshotted `subtotal_cents`. First, apply the deposit already held: the deposit credit is `deposit_paid_cents` (0 if none was held), and the amount remaining after the deposit is the gross minus that credit, floored at 0. Second, apply loyalty redemption: the requested loyalty value in cents is `loyalty_points_redeemed` multiplied by the per-point value of 10 cents, and the loyalty actually applied is the smaller of that requested value and the amount remaining after the deposit. The number of points actually consumed is the loyalty applied divided by 10 cents, rounded up to the next whole point. The amount remaining after loyalty is the after-deposit amount minus the loyalty applied. Third, draw the gift card if one was supplied: the gift draw is the smaller of the card's `balance_cents` and the amount remaining after loyalty (0 if no card was supplied), and a draw may never push the card below 0. The amount remaining after the gift draw is the after-loyalty amount minus the gift draw. Fourth, the remainder is the client's charge: `total_charged_cents` equals the amount remaining after the gift draw.

The settlement also updates the side ledgers and triggers the full cascade. The client's `loyalty_points_balance` is reduced by the points consumed and the gift card's `balance_cents` is reduced by the gift draw. The system then computes `technician_earning_cents` (Section 3.11) and adds it to the assigned technician's `accrued_earnings_cents`. It awards the service's `loyalty_points_award` to the client's `loyalty_points_balance`. It sets `payment_status` to `SETTLED`. It clears the station's `in_service_appointment_id` back to null, freeing the chair. If the gift-card draw brought the card's `balance_cents` to exactly 0, the card's `status` transitions from `ACTIVE` to `DEPLETED` (a system-driven cascade hop) and the card's `version` increments. Finally the appointment's own `version` increments by one. Every related entity touched — client, technician, station, gift card — has its own `updated_at` and `version` refreshed by this operation.

### 3.11. Technician Per-Appointment Earnings

At the moment of checkout, the system records `technician_earning_cents` on the appointment as the technician's share of that appointment's service revenue, where the gross service revenue is the snapshotted `subtotal_cents` including add-ons. The computation depends on the technician's `pay_model`. For a `COMMISSION` technician, the earning is `subtotal_cents` multiplied by the complement of `commission_pct` (that is, one minus `commission_pct`), rounded half up to whole cents; the salon retains the `commission_pct` share. For a `BOOTH_RENT` technician, the earning is the full `subtotal_cents` at the line — booth-rent technicians keep 100% of per-appointment service revenue, because their flat booth rent is withheld once per statement rather than per appointment, so per-appointment salon retention is 0. This per-appointment earning is the amount accrued to the technician's `accrued_earnings_cents` during the checkout cascade.

### 3.12. Cancellation and the Free Window

A `FrontDesk` operator, `SalonManager`, or the owning `Client` may cancel an appointment whose `booking_status` is `REQUESTED` or `CONFIRMED`, moving `booking_status` to the terminal `CANCELLED`. The disposition of any held deposit depends on timing relative to the cancellation free window of 120 minutes. If the current logical clock is at or before the appointment's `start_at` minus 120 minutes and the `payment_status` is `DEPOSIT_HELD`, the deposit is refunded and `payment_status` moves to `REFUNDED`. Otherwise, if the `payment_status` is `DEPOSIT_HELD` but the cancellation falls inside the free window, the deposit is forfeited and `payment_status` moves to `FORFEITED`. A cancellation with no deposit held leaves the payment dimension untouched. Cancellation increments the appointment's `version` by one.

### 3.13. Marking a No-Show

When a confirmed client fails to appear, a `FrontDesk` operator or `SalonManager` marks the appointment a no-show, moving `booking_status` from `CONFIRMED` to the terminal `NO_SHOW`. This is permitted only after the grace period has elapsed: the current logical clock must be at or after the appointment's `start_at` plus 15 grace minutes, or the attempt is rejected with `ERR_NO_SHOW_TOO_EARLY`. The transition is also guarded by the appointment's `no_show_strike_charged` flag, which must be false; this idempotency guard ensures a re-read or duplicate sweep cannot double-count the strike.

Marking a no-show drives a cascade. It increments the client's `active_no_show_strikes` by one, sets the client's `last_no_show_at` to the current clock, and sets the appointment's `no_show_strike_charged` to true. If the resulting `active_no_show_strikes` is at least the deposit threshold of 2, it sets the client's `deposit_required` to true — a cascade hop in which a strike bump flips the deposit flag. If the `payment_status` was `DEPOSIT_HELD`, the deposit is forfeited and `payment_status` moves to `FORFEITED`. It also increments the assigned technician's informational `lifetime_no_show_strikes_attributed` by one. Finally the appointment's `version` increments by one, and the touched client and technician have their own `updated_at` and `version` refreshed.

### 3.14. Refunding a Settled Appointment

A `SalonManager` may issue a full refund of an already-settled appointment — for a service redo or a complaint — as a compensating action that reverses the checkout cascade. This payment-dimension transition applies only when `payment_status` is `SETTLED` (the booking dimension remains `COMPLETED`) and moves `payment_status` to the terminal `REFUNDED`. The refund restores the gift-card draw to the card's `balance_cents`; if that card had been `DEPLETED`, restoring a positive balance reverts its `status` from `DEPLETED` to `ACTIVE` (a cascade hop in which a balance restore reverts the card status, and the card's `version` increments). It returns the redeemed loyalty points to the client's `loyalty_points_balance` and removes the loyalty points that the completion had awarded, leaving the client's balance at its pre-checkout value. It debits the technician's `accrued_earnings_cents` by this appointment's `technician_earning_cents`, reversing the prior accrual. The station is already free, so nothing changes there. The appointment's `version` increments by one, and every reversed entity has its own `updated_at` and `version` refreshed. The net effect leaves the gift card's `balance_cents` and the client's `loyalty_points_balance` at the values they held before checkout ran.

### 3.15. Gift Cards Across Their Lifecycle

A `FrontDesk` operator or `SalonManager` issues a `GiftCard` with a `code` that must be non-empty and unique across gift cards (a collision yields `ERR_DUPLICATE_RESOURCE`), an `initial_balance_cents` that must be a positive integer, and an optional `purchaser_client_id` naming the buyer (informational only — any client may redeem). On issuance the card's `balance_cents` is initialized to `initial_balance_cents` and its `status` begins `ACTIVE`. Although `purchaser_client_id` does not gate redemption, it is the sole basis for `Client` ownership on the read path: a `Client` fetching a gift card directly via `GET /gift-cards/{id}` is permitted only when the card's `purchaser_client_id` equals the acting client's id, and is otherwise rejected with `ERR_FORBIDDEN`.

Beyond the automatic draws at checkout, a gift card supports a standalone manual redemption. A `FrontDesk` operator or `SalonManager` draws an `amount_cents` (a non-negative integer) from a card, supplying `expected_gift_card_version` for the OCC check of Section 2.9. The card must be `ACTIVE` and the `amount_cents` must not exceed the card's `balance_cents`; an attempt to overdraw or to draw against a non-active card is rejected with `ERR_GIFT_CARD_OVERDRAW`. (The same overdraw-and-active rule also guards the gift-card draw performed during appointment checkout.) A successful redemption reduces `balance_cents` by `amount_cents`, transitions the card's `status` from `ACTIVE` to `DEPLETED` if the draw brings the balance to exactly 0, and increments the card's `version` by one. A depleted card returns to `ACTIVE` when a previously-settled appointment that drew it is refunded and the restored `balance_cents` is positive, completing the cyclic `ACTIVE` → `DEPLETED` → `ACTIVE` path, again incrementing `version`.

A `SalonManager` may void an `ACTIVE` gift card, which sets its `balance_cents` to 0, moves its `status` to the terminal `VOID`, and increments its `version` by one. Voiding a card whose `status` is not `ACTIVE` is an undefined transition and is rejected with `ERR_INVALID_STATE`.

### 3.16. Commission Statements and Period Settlement

Earnings accrue on each technician through checkout and are periodically swept into a `CommissionStatement`. A `SalonManager` creates a `DRAFT` statement naming a `technician_id`, an inclusive `period_start`, and an exclusive `period_end`; the statement's computed totals — `gross_service_cents`, `technician_payout_cents`, `salon_retained_cents`, and `swept_appointment_count` — all begin at 0 until the statement settles, and its `status` begins `DRAFT`.

Settling a `DRAFT` statement, an action restricted to `SalonManager`, sweeps appointments and runs the payout calculation. The statement may settle only while its `status` is `DRAFT` and the referenced technician exists and is not `TERMINATED`; settling against a `TERMINATED` technician is rejected with `ERR_INVALID_STATE`. The sweep selects every appointment on the statement's `technician_id` whose `booking_status` is `COMPLETED` and whose completion instant — taken as the appointment's `updated_at` at the moment it reached `COMPLETED` — falls within the half-open window from `period_start` (inclusive) up to `period_end` (exclusive). The swept set is ordered by `updated_at` ascending, breaking ties by `created_at` ascending (never by id). The `swept_appointment_count` is the number of appointments swept, and `gross_service_cents` is the sum of their `subtotal_cents` (add-ons included).

The payout itself depends on the technician's `pay_model`, and the rounding strategy here deliberately differs from the per-appointment earning of Section 3.11. For a `COMMISSION` technician, the rounding order is pinned to **sum-then-round**: aggregate the gross over all swept appointments first, then apply the complement of `commission_pct` (one minus `commission_pct`) once to that aggregate, rounding half up to whole cents. This is the single rounding of the aggregate, not the sum of per-line rounded earnings, so the statement total may differ from the sum of the per-appointment `technician_earning_cents` by up to a cent. For a `BOOTH_RENT` technician, the payout is the gross minus the flat `booth_rent_cents`, floored at 0; the salon retains exactly `booth_rent_cents`, or the whole gross when the gross is smaller than the rent. In both models, `salon_retained_cents` is the `gross_service_cents` minus the `technician_payout_cents` and is never negative. Settling resets the technician's `accrued_earnings_cents` to 0 and increments the statement's `version` by one. Alternatively, a `SalonManager` may void a `DRAFT` statement without settling, moving its `status` to the terminal `VOID` and incrementing `version`; both `SETTLED` and `VOID` are terminal.

### 3.17. Test-Driving Capabilities

Three administrative capabilities exist purely to drive deterministic test scenarios. The first advances the logical clock to a supplied `to_iso8601` instant, as described in Section 2.5, and is available to `SalonManager` and `FrontDesk`; a missing `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and on success the response `data` is an empty object (the clock is not a persisted resource). The second, available to `SalonManager`, injects a client's strike and loyalty ledger to a known baseline — there is no realistic booking history to manufacture deep strike counts or large balances cheaply — by setting the stored raw strike count via `active_no_show_strikes`, the `last_no_show_at` instant, and/or the `loyalty_points_balance`, each of which is independently optional; any field omitted is left unchanged, and each supplied integer field must be non-negative. After injection the client's `deposit_required` is recomputed from the resulting strike count under the deposit-assessment rule, and the injection refreshes the client's `updated_at` and increments its `version` by one (even when no field was supplied), returning the updated client record. The third, also `SalonManager`-only, forces a specific `deposit_due_cents` onto a `REQUESTED` appointment regardless of the booking client's current strike posture, so that deposit-held payment flows can be exercised independently of strike history; it takes the target `appointment_id` and the `deposit_due_cents` (a non-negative integer) to set. The target appointment's `booking_status` must be `REQUESTED`; forcing a deposit onto an appointment in any other booking state is rejected with `ERR_INVALID_REQUEST`. A successful force refreshes the appointment's `updated_at` and increments its `version` by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions and the administrative test-driving capabilities — return a `200 OK` status code. All endpoints require the authentication headers of Section 2.1; the authorized roles below are evaluated after authentication and after referential existence per the ordering in Section 2.11.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/technicians` | Create a technician | SalonManager |
| GET | `/technicians` | List technicians; optional `home_station_id` and `status` filters | SalonManager, FrontDesk |
| GET | `/technicians/{id}` | Fetch one technician | SalonManager, FrontDesk, Technician |
| POST | `/technicians/{id}/suspend` | Suspend an active technician | SalonManager |
| POST | `/technicians/{id}/reinstate` | Reinstate a suspended technician | SalonManager |
| POST | `/technicians/{id}/terminate` | Terminate a suspended technician with zero accrued earnings | SalonManager |
| GET | `/technicians/{id}/appointments` | List appointments assigned to this technician; optional `booking_status` filter | SalonManager, FrontDesk, Technician |
| GET | `/technicians/{id}/commission-statements` | List commission statements for this technician; optional `status` filter | SalonManager, Technician |
| POST | `/stations` | Create a station | SalonManager |
| GET | `/stations` | List stations; optional `sanitation_status` filter (matched against the derived status) | SalonManager, FrontDesk, Technician |
| GET | `/stations/{id}` | Fetch one station with derived sanitation status and occupancy | SalonManager, FrontDesk, Technician |
| GET | `/stations/{id}/sanitation-logs` | List sanitation logs for this station (newest first); optional `cycle_result` filter | SalonManager, FrontDesk, Technician |
| POST | `/sanitation-logs` | Record an autoclave cycle for a station | Technician, SalonManager |
| GET | `/sanitation-logs` | List sanitation logs; optional filters `station_id`, `logged_by_technician_id`, `cycle_result` | SalonManager, FrontDesk, Technician |
| GET | `/sanitation-logs/{id}` | Fetch one sanitation log | SalonManager, FrontDesk, Technician |
| POST | `/menu-items` | Create a service menu item | SalonManager |
| GET | `/menu-items` | List menu items; optional `category` and `is_active` filters | SalonManager, FrontDesk, Technician |
| GET | `/menu-items/{id}` | Fetch one menu item | SalonManager, FrontDesk, Technician |
| POST | `/menu-items/{id}/retire` | Retire a menu item | SalonManager |
| POST | `/add-ons` | Create an add-on | SalonManager |
| GET | `/add-ons` | List add-ons; optional `is_active` filter | SalonManager, FrontDesk, Technician |
| GET | `/add-ons/{id}` | Fetch one add-on | SalonManager, FrontDesk, Technician |
| POST | `/clients` | Create a client | FrontDesk, SalonManager |
| GET | `/clients` | List clients; optional `email` and `deposit_required` filters (the latter matched against the recomputed flag) | FrontDesk, SalonManager |
| GET | `/clients/{id}` | Fetch a client with decayed strikes and recomputed deposit flag | FrontDesk, SalonManager, Client |
| GET | `/clients/{id}/appointments` | List appointments for this client; optional `booking_status` filter | FrontDesk, SalonManager, Client |
| GET | `/clients/{id}/gift-cards` | List gift cards purchased by this client (matched on `purchaser_client_id`); optional `status` filter | FrontDesk, SalonManager, Client |
| POST | `/appointments` | Book an appointment (walk-in or scheduled) | FrontDesk, SalonManager |
| GET | `/appointments` | List appointments with rich filtering (optional filters `client_id`, `technician_id`, `station_id`, `service_item_id`, `gift_card_id`, `booking_status`, `payment_status`) | FrontDesk, SalonManager |
| GET | `/appointments/{id}` | Fetch one appointment | FrontDesk, SalonManager, Client, Technician |
| POST | `/appointments/{id}/add-ons` | Attach an add-on to a requested appointment | FrontDesk, SalonManager |
| GET | `/appointments/{id}/add-ons` | List add-ons attached to this appointment | FrontDesk, SalonManager, Client, Technician |
| GET | `/appointment-add-ons` | List appointment add-on junction rows; optional `appointment_id` and `add_on_id` filters | FrontDesk, SalonManager, Technician |
| GET | `/appointment-add-ons/{id}` | Fetch one appointment add-on junction row | FrontDesk, SalonManager, Technician |
| POST | `/appointments/{id}/pay-deposit` | Collect the owed deposit | FrontDesk, SalonManager |
| POST | `/appointments/{id}/confirm` | Confirm a requested appointment | FrontDesk, SalonManager |
| POST | `/appointments/{id}/check-in` | Check in a confirmed appointment | FrontDesk, SalonManager |
| POST | `/appointments/{id}/start-service` | Begin service; occupies the station | Technician, SalonManager |
| POST | `/appointments/{id}/checkout` | Settle and complete the appointment | FrontDesk, SalonManager |
| POST | `/appointments/{id}/cancel` | Cancel a requested or confirmed appointment | FrontDesk, SalonManager, Client |
| POST | `/appointments/{id}/mark-no-show` | Mark a confirmed appointment as a no-show | FrontDesk, SalonManager |
| POST | `/appointments/{id}/refund-settled` | Full refund of a completed, settled appointment | SalonManager |
| POST | `/gift-cards` | Issue a gift card | FrontDesk, SalonManager |
| GET | `/gift-cards` | List gift cards; optional `code`, `status`, and `purchaser_client_id` filters | FrontDesk, SalonManager |
| GET | `/gift-cards/{id}` | Fetch one gift card | FrontDesk, SalonManager, Client |
| POST | `/gift-cards/{id}/redeem` | Manually draw an amount from a gift card | FrontDesk, SalonManager |
| POST | `/gift-cards/{id}/void` | Void an active gift card | SalonManager |
| POST | `/commission-statements` | Create a draft commission statement | SalonManager |
| GET | `/commission-statements` | List commission statements; optional `technician_id` and `status` filters | SalonManager |
| GET | `/commission-statements/{id}` | Fetch one commission statement | SalonManager, Technician |
| POST | `/commission-statements/{id}/settle` | Settle a draft statement | SalonManager |
| POST | `/commission-statements/{id}/void` | Void a draft statement without settling | SalonManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SalonManager, FrontDesk |
| POST | `/_inject/client_state` | Set a client's strike/loyalty ledger to a baseline | SalonManager |
| POST | `/_inject/appointment_deposit` | Force a specific deposit amount on a requested appointment | SalonManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ITEM_RETIRED` | 409 Conflict |
| `ERR_STATION_NOT_STERILE` | 409 Conflict |
| `ERR_LICENSE_EXPIRED` | 409 Conflict |
| `ERR_STERILIZATION_INVALID` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STATION_TURNOVER_CONFLICT` | 409 Conflict |
| `ERR_NO_SHOW_TOO_EARLY` | 409 Conflict |
| `ERR_DEPOSIT_REQUIRED` | 402 Payment Required |
| `ERR_INSUFFICIENT_LOYALTY` | 409 Conflict |
| `ERR_GIFT_CARD_OVERDRAW` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

# Costume & Prop Rental House API — Product Requirements Document

## 1. Introduction

A costume and prop rental house lives or dies on the gap between what is on the shelf and what has been promised to a production. A theatre company books forty Victorian tailcoats for an eight-week run; a film production needs weaponry with a three-day cleaning buffer between engagements; an event planner wants a single evening's worth of accessories. Each of these bookings competes for the same physical units, each unit cycles through checkout, cleaning, repair, and occasional loss, and every stage of that cycle carries money — rental charges, late fees, cleaning fees, damage valuations — that must be billed against the right production while the renter's credit exposure and insurance standing are continuously re-evaluated.

This document specifies the API for managing that business end to end: renter registration with insurance certificate verification, a catalog of items organized by period, category, size, and alteration policy, physical unit sourcing with condition grading, production date management with pinned long-run rate cards, reservation holds with expiring quote windows, pull-list picking and dispatch with automated unit selection, check-in with return assessment and restoration enforcement, the cleaning and repair turnaround loop, damage and loss claims with segregation of duties, and invoicing with payments, credit notes, and credit-limit enforcement. All date- and time-dependent behavior in the system — hold expiry, certificate expiry, late fees, production advancement, automatic loss — is evaluated against a server-side logical clock, never the wall clock, so that every rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint. The API is mounted under `/rental-house`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `HouseAdmin`, `WardrobeStaff`, `RenterContact`, and `Accountant`.

- `HouseAdmin` is the rental-house administrator: catalog and acquisitions, rate cards, insurance decisions, fitting decisions, deaccession, the operations checkpoint, and the logical clock. When `X-User-Role` is `HouseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by_user_id` on a certificate or fitting authorization it decides) but never compares it to any entity's `id`.
- `WardrobeStaff` is the wardrobe and floor staff: pull-list submit, picking, dispatch, check-in, loss reporting, damage claim creation, and cleaning advancement. When `X-User-Role` is `WardrobeStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assessed_by_user_id` on a return assessment or `created_by_user_id` on a damage claim) but never compares it to any entity's `id`.
- `RenterContact` is the production-company contact. When `X-User-Role` is `RenterContact`, `X-User-ID` is the `id` of the acting `Renter`; ownership checks on any resource that references a `Renter` compare the resource's foreign-key field to `X-User-ID`. A `RenterContact` may act only on resources whose `renter_id` equals their `X-User-ID` — the `renter_id` in a production-creation body, and any production, reservation, pull list, fitting authorization, invoice, or damage claim reachable through the request path or body. A violation is rejected with `ERR_RENTER_SCOPE_VIOLATION` (HTTP 403).
- `Accountant` is the house accountant: invoice generation, issue, payments, credit notes, and damage-claim posting and waiving. When `X-User-Role` is `Accountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `posted_by_user_id` on a posted claim) but never compares it to any entity's `id`.

All read (list and get) endpoints are available to all four roles.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Both parameters must be integers — a non-integer `limit` or `offset` is a wrong-type request-shape error rejected with `ERR_VALIDATION` per §2.9. Out-of-range integer values are clamped to the nearest bound rather than rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0. The clamped values are what the response `meta` reports in its `limit` and `offset` fields.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Operations Sweep

The server maintains a **logical clock**. Before any call to the clock-setting capability, the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default, never the real wall clock. A `HouseAdmin` may advance the logical clock by supplying a `to_iso8601` instant; the response echoes the new time as `current_utc`. Setting the clock changes no state by itself: all time-driven transitions fire only when the **daily operations sweep** is run.

The sweep is a `HouseAdmin`-only operations checkpoint evaluated against the current logical clock. In one run it: expires every certificate in `SUBMITTED` or `VERIFIED` status whose `expiry_date` is before the current logical date (with the renter-suspension cascade described in §3.1 when a `VERIFIED` certificate lapses); expires every `HELD` reservation whose `hold_expires_at` is before the current logical timestamp; advances productions (`CONFIRMED` to `IN_RUN` once the current logical date reaches `performance_start_date`, and `IN_RUN` to `WRAP` once the current logical date is past `closing_date`); auto-loses every line in `OUT` status whose `due_back_date` is more than seven days in the past; and evaluates every production for settlement. Date advancement is **transitive within a single run**: a `CONFIRMED` production evaluated when the current date is already past `closing_date` moves `CONFIRMED` → `IN_RUN` → `WRAP` in that one run, and the `WRAP` → `SETTLED` evaluation then runs in the same pass. The sweep response reports `current_utc` plus the identifier arrays `expired_certificate_ids`, `expired_reservation_ids`, `released_reservation_ids`, `advanced_production_ids`, `auto_lost_line_ids`, and `settled_production_ids`.

### 2.5. Common Resource Properties

Every resource in the system — renters, insurance certificates, rate cards, items, item units, productions, reservations, pull lists, pull-list lines, fitting authorizations, return assessments, damage claims, cleaning tickets, and invoices — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource.

Any mutation of a resource — including system-driven recomputation of derived fields such as a renter's `outstanding_balance_cents`, an item's `serviceable_unit_count`, or a production's pinned rate fields — updates `updated_at` and increments `version` on the mutated resource.

### 2.6. Monetary Values, Integer Cents and Rounding

All monetary values are represented as **integer cents** — no fractional cents exist anywhere in the system. Wherever a calculation can produce a non-integer intermediate result (per-unit charge division, discount application, late fees, damage valuation, rush cleaning fees), the final value is rounded **half up** to the nearest whole cent, and rounding is applied exactly once per computed charge, at the step specified by the business rules in §3. Per-line rental charges are rounded at line-assignment time and stored; invoice generation sums those stored per-line integers and never re-rounds the sum. (The two orders genuinely differ: two lines of 2666.4 raw cents yield 2666 + 2666 = 5332 when rounded per line, versus 5333 if the sum were rounded instead.)

### 2.7. Optimistic Concurrency Control

Two creation endpoints mutate the production aggregate as a side effect and are therefore guarded by optimistic concurrency control on the `Production`:

- **Reservation creation** and **pull-list creation** each require a non-optional `expected_production_version` field in the request body, carrying the client's last observed `version` of the target `Production`. If that value does not equal the production's current `version` — for example because another reservation was created against it, or the production was confirmed, since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a production it has not observed.

Both reservation creation and pull-list creation increment the production's `version` by one on success, so any previously captured `expected_production_version` becomes stale after either write. Endpoints not named above do not take a version field. The stale-version check is evaluated immediately after state checks and before any business rule, per the validation order in §2.9.

### 2.8. Cascades and Hierarchical Consistency

Many operations mutate more than one resource in a single request, and all such side effects are visible in the same response — the consistency model is immediate, with no deferred or asynchronous reconciliation. The recurring cascade patterns are: a renter's suspension releases or expires that renter's reservation holds; a production's cancellation releases its reservations and cancels its draft pull lists; an item's deaccession sweeps its units through disposal states; a pull list's dispatch advances its lines, its units, and its covered reservations together; a line's terminal event (return, damage, or loss) triggers pull-list auto-close evaluation, which in turn triggers production settle evaluation; and any invoice issue, payment, credit note, or void recomputes the renter's outstanding balance and credit hold. Each individual cascade is specified where its workflow lives in §3.

### 2.9. Validation Order and Nested Resource Resolution

When multiple checks could reject the same request, the server evaluates them in a fixed priority order, so that the surfaced error is deterministic:

1. **Authentication** — `X-User-Role` and `X-User-ID` present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role is permitted on the endpoint, else `ERR_FORBIDDEN`.
3. **Renter scoping** — for `RenterContact` requests, the resource's `renter_id` equals `X-User-ID`, else `ERR_RENTER_SCOPE_VIOLATION`.
4. **Existence** — every identifier in the path and body (renter, certificate, rate card, item, unit, production, reservation, pull list, line, fitting, assessment, claim, ticket, invoice) exists, validated left-to-right in the path and then the body, else `ERR_NOT_FOUND`. A request for a child under a non-existent parent therefore fails on the parent identifier first.
5. **State** — the target resource is in a valid from-state for the requested transition; this covers `ERR_INVALID_STATE` plus the domain state errors `ERR_RENTER_SUSPENDED`, `ERR_HOLD_EXPIRED`, `ERR_LINES_NOT_PICKED`, `ERR_RESERVATION_IN_USE`, `ERR_PRODUCTION_HAS_ACTIVE_PULLS`, `ERR_ITEM_HAS_ACTIVE_HOLDS`, `ERR_CLAIM_ALREADY_BILLED`, and the segregation-of-duties state error `ERR_SOD_VIOLATION`.
6. **Optimistic concurrency** — `expected_production_version` equals the current `Production.version` on reservation and pull-list creation, else `ERR_STALE_VERSION`; evaluated here, immediately after state checks and before any business rule.
7. **Safety policy** — insurance and alteration safety: certificate coverage minimums (`ERR_INSUFFICIENT_COVERAGE`, `ERR_CERTIFICATE_EXPIRED`), the production-confirm and dispatch insurance gates (`ERR_INSURANCE_NOT_VERIFIED`), and the alteration-policy gate (`ERR_ALTERATION_PROHIBITED`).
8. **Referential usability** — referenced objects are usable: the item is rentable (`ERR_ITEM_NOT_RENTABLE`), a `PUBLISHED` rate card exists (`ERR_RATE_CARD_REQUIRED`), one claim per line (`ERR_CLAIM_ALREADY_EXISTS`), claim type matches line status (`ERR_CLAIM_TYPE_MISMATCH`), barcode uniqueness (`ERR_DUPLICATE_BARCODE`).
9. **Temporal rules** — date windows: `window_end_date` on or after `window_start_date` and the window within production bounds (`ERR_WINDOW_OUT_OF_BOUNDS`); production date order (`ERR_DATE_ORDER`).
10. **Capacity and allocation** — the aggregate capacity check (`ERR_CAPACITY_EXCEEDED`), unit-selector shortfall (`ERR_NO_UNITS_AVAILABLE`), nothing to pull (`ERR_NOTHING_TO_PULL`), the deaccession unit-state gate (`ERR_DEACCESSION_BLOCKED`), the restoration gate at check-in (`ERR_RESTORATION_INCOMPLETE`), and a reservation `quantity` of at least 1 (`ERR_QUANTITY_INVALID`).
11. **Fiscal rules last** — credit-hold gates (`ERR_CREDIT_LIMIT_EXCEEDED`), empty-invoice rules (`ERR_INVOICE_EMPTY`), and payment/credit amount bounds (`ERR_PAYMENT_INVALID`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_CREDIT_INVALID`, `ERR_CREDIT_EXCEEDS_BALANCE`).
12. **Generic request shape** — missing required field, wrong type, invalid enum member, or malformed date, reported as `ERR_VALIDATION`; this is the lowest-priority check and surfaces only after all business rules pass.

## 3. Business Logic & Workflows

### 3.1. Renters, Insurance Certificates, and House Standing

A `HouseAdmin` registers a renter organization by providing its `name`, its `renter_type` — one of `THEATRE`, `FILM`, `EVENT`, or `INDIVIDUAL` — and a `credit_limit_cents` ceiling on outstanding billed balance. A new renter starts in `PENDING_VERIFICATION` status with `outstanding_balance_cents` of 0 and `credit_hold` false. The renter's `status` enumerates exactly `PENDING_VERIFICATION`, `ACTIVE`, and `SUSPENDED`; renters may be filtered by `status` when listed.

Insurance is the gate that turns a registration into a working account. A certificate submission — by a `HouseAdmin`, or by a `RenterContact` for their own `renter_id` — supplies the `insurer_name`, the `policy_number`, the per-incident `coverage_cents`, and the `effective_date` and `expiry_date` of coverage (the expiry date is inclusive). The new certificate's `status` is `SUBMITTED`, one of the four certificate states `SUBMITTED`, `VERIFIED`, `REJECTED`, `EXPIRED`, of which `REJECTED` and `EXPIRED` are terminal.

A `HouseAdmin` decides a `SUBMITTED` certificate by supplying a `decision`. Verifying enforces two safety checks: the `coverage_cents` must meet the renter-type minimum — 100000 cents for `THEATRE`, 500000 for `FILM`, 250000 for `EVENT`, and 50000 for `INDIVIDUAL` — or the decision is rejected with `ERR_INSUFFICIENT_COVERAGE`; and the `expiry_date` must be on or after the current logical date, or the decision is rejected with `ERR_CERTIFICATE_EXPIRED`. On either decision the certificate's `decided_by_user_id` records the deciding admin's `X-User-ID`; it remains null until decided. A verified certificate has two further effects: if the owning renter is `PENDING_VERIFICATION` or `SUSPENDED`, the renter's `status` becomes `ACTIVE` — so the first verified certificate activates a new renter, and a fresh verified certificate automatically reactivates a suspended one. Rejection simply moves the certificate to `REJECTED`.

Suspension arrives two ways. A `HouseAdmin` may patch a renter — the same update path also adjusts `credit_limit_cents` — to move `status` between `ACTIVE` and `SUSPENDED` only; manual reactivation requires at least one certificate in `VERIFIED` status with `expiry_date` on or after the current logical date, failing with `ERR_INSURANCE_NOT_VERIFIED` otherwise. Alternatively, the daily operations sweep suspends a renter automatically when its last `VERIFIED` certificate expires: a `VERIFIED` certificate whose `expiry_date` falls before the current logical date moves to `EXPIRED`, and if the renter then has no other `VERIFIED` certificate with `expiry_date` on or after the current logical date, the renter's `status` becomes `SUSPENDED`. Both paths trigger the same cascade: every reservation in `HELD` status on the renter's productions becomes `EXPIRED`, every reservation in `CONFIRMED` status becomes `RELEASED` with its held quantity freed, and from then on reservation confirmation and pull-list dispatch for that renter fail with `ERR_RENTER_SUSPENDED`. (`ERR_RENTER_SUSPENDED` also fires whenever an operation requires an `ACTIVE` renter and the renter has not yet been activated at all.)

### 3.2. The Catalog, Unit Sourcing, and Deaccession

The catalog describes *what* the house rents; units describe the physical copies. A `HouseAdmin` creates a catalog item with a `name` (say, "Victorian tailcoat"), a `period` (one of `ANCIENT`, `MEDIEVAL`, `RENAISSANCE`, `REGENCY`, `VICTORIAN`, `EDWARDIAN`, `TWENTIES`, `FIFTIES`, `EIGHTIES`, `CONTEMPORARY`, `FANTASY`), a `category` (one of `COSTUME`, `PROP`, `SET_DRESSING`, `WEAPONRY`, `ACCESSORY` — the category drives both cleaning buffer days and the base cleaning fee), a `size_class` (one of `NONE`, `XS`, `S`, `M`, `L`, `XL`, `PLUS`, with `NONE` used for props and set dressing), an `alteration_policy` (`PROHIBITED`, `REVERSIBLE_ONLY`, or `TAILORING_ALLOWED`, which gates fitting authorizations), the agreed full `replacement_value_cents`, and the `base_daily_rate_cents` and `base_weekly_rate_cents` price points. A new item's `status` is `ACTIVE` (the item states are `ACTIVE`, `DEACCESSION_PENDING`, and `DEACCESSIONED`) and its `serviceable_unit_count` starts at 0. Items may be listed with `period`, `category`, `size_class`, and `status` filters; deaccessioned items are hidden from default list results unless `include_deaccessioned` is true — a deaccessioned item is soft-deleted but remains queryable this way.

Sourcing acquires physical stock: a `HouseAdmin` acquires one unit of an `ACTIVE` item by supplying its `barcode`, its `condition_grade` at acquisition (`A`, `B`, `C`, or `D`), the `acquisition_date`, and the `acquisition_cost_cents`. The barcode must be unique house-wide — a duplicate is rejected with `ERR_DUPLICATE_BARCODE`. The unit's `item_id` ties it to its catalog item; a new unit starts `AVAILABLE`, and the item's `serviceable_unit_count` increases by one. Units may be listed by item with `status` and `condition_grade` filters. The unit lifecycle enumerates `AVAILABLE`, `OUT`, `CLEANING`, `REPAIR`, `AWAITING_DISPOSAL`, and `DISPOSED` (terminal); the unit's `last_returned_date` records the logical date of its most recent check-in and stays null until the unit has been rented. The computed `serviceable_unit_count` on an item counts exactly its units whose status is not `AWAITING_DISPOSAL` and not `DISPOSED` — this is the pool every reservation capacity check draws on. Grade `D` units are never assigned to pull lists.

Deaccession retires an item in three steps, all performed by a `HouseAdmin`. Requesting deaccession requires that no reservation for the item is in `HELD` or `CONFIRMED` status (`ERR_ITEM_HAS_ACTIVE_HOLDS`) and that every unit of the item is `AVAILABLE`, `AWAITING_DISPOSAL`, or `DISPOSED` — a single unit `OUT`, `CLEANING`, or `REPAIR` blocks the request with `ERR_DEACCESSION_BLOCKED`. On success the item moves `ACTIVE` → `DEACCESSION_PENDING`, every `AVAILABLE` unit moves to `AWAITING_DISPOSAL`, the item drops out of default list results, and new reservations against it are rejected with `ERR_ITEM_NOT_RENTABLE`. Cancelling deaccession reverses the preparation: the item returns `DEACCESSION_PENDING` → `ACTIVE` and every `AWAITING_DISPOSAL` unit returns to `AVAILABLE`. Completing deaccession requires every unit to be `AWAITING_DISPOSAL` or `DISPOSED` (`ERR_DEACCESSION_BLOCKED` otherwise); it moves the item to `DEACCESSIONED`, moves every `AWAITING_DISPOSAL` unit to `DISPOSED`, and recomputes `serviceable_unit_count`, which drops to 0.

### 3.3. Rate Cards and the Production Timeline

Pricing policy lives on the **rate card**. A `HouseAdmin` publishes a card with a `name`, the `long_run_threshold_weeks` at which a booking qualifies for the long-run rate, the `long_run_discount_pct` fraction for such bookings (for example 0.20), the `deep_run_threshold_weeks` at which a still deeper tier applies with its `deep_run_discount_pct` fraction (for example 0.30), and the `late_fee_daily_pct` fraction of a unit's daily rate charged per late day (for example 0.10). A new card is born `PUBLISHED`; publishing it automatically moves the previously `PUBLISHED` card to `SUPERSEDED`. Productions already confirmed keep their pinned card and are never re-priced — supersession affects only future confirmations.

A production represents one show's engagement. A `RenterContact` creates one for their own organization with the `renter_id`, a `title`, and three dates: `rehearsal_start_date`, `performance_start_date`, and `closing_date`. The dates must satisfy rehearsal start on or before performance start on or before closing, at creation and again at confirmation, else `ERR_DATE_ORDER`. A new production is `DRAFT` with `version` 1; the production states are `DRAFT`, `CONFIRMED`, `IN_RUN`, `WRAP`, `SETTLED`, and `CANCELLED`, with `SETTLED` and `CANCELLED` terminal. Productions may be listed filtered by `renter_id`, `status`, or `rate_card_id`.

Confirmation is the pivotal act, performed by the `RenterContact`. It enforces, in validation order: the renter is `ACTIVE` (`ERR_RENTER_SUSPENDED`); the renter holds a certificate in `VERIFIED` status whose `expiry_date` is on or after the production's `return_by_date` (`ERR_INSURANCE_NOT_VERIFIED`); a rate card in `PUBLISHED` status exists (`ERR_RATE_CARD_REQUIRED`); and the date ordering holds (`ERR_DATE_ORDER`). On success the production moves `DRAFT` → `CONFIRMED` and three computed fields are pinned from the published card. The `rate_card_id` and `rate_card_version` capture exactly which card and which version of it prices this production — every downstream charge for the production reads thresholds, discounts, and the late-fee percentage from that pinned card, never from whatever card is currently published. The `return_by_date` is the `closing_date` plus a three-day strike allowance. The `run_weeks` is the whole number of weeks in the run: the count of calendar days from `performance_start_date` through `closing_date` inclusive, divided by seven, rounded down — so a 55-day run yields 7 and a 56-day run yields 8. The `long_run` flag is true when `run_weeks` is at least the pinned card's `long_run_threshold_weeks` — a run exactly at the threshold qualifies. Confirmation increments the production's `version` by one.

From there the calendar takes over under the daily sweep: `CONFIRMED` → `IN_RUN` when the current logical date reaches `performance_start_date`, and `IN_RUN` → `WRAP` when the current logical date passes `closing_date`, applied transitively within a single run as described in §2.4. Settlement from `WRAP` is described in §3.8.

A `RenterContact` may cancel their own production from `DRAFT` or `CONFIRMED`. Cancellation releases the production's reservations — `HELD` and `CONFIRMED` alike become `RELEASED` — and cancels its pull lists still in `DRAFT`. (No pull list can be `PICKING` under a `DRAFT` production, because submission requires a `CONFIRMED` production.) Cancelling a `CONFIRMED` production is refused with `ERR_PRODUCTION_HAS_ACTIVE_PULLS` while any of its pull lists is `PICKING` or `DISPATCHED`.

### 3.4. Reservations: Holds, Quotes, and Amendments

A reservation is a dated hold on a quantity of one catalog item for one production. A `RenterContact` places a hold with a payload containing the `production_id`, the `item_id`, the `quantity` (at least 1, else `ERR_QUANTITY_INVALID`), the inclusive `window_start_date` and `window_end_date` of need, and the OCC guard `expected_production_version` described in §2.7. Creation requires: the renter `ACTIVE` (`ERR_RENTER_SUSPENDED`); the production in `DRAFT` or `CONFIRMED`; the item in `ACTIVE` status (`ERR_ITEM_NOT_RENTABLE`); and the window within the production's bounds — `window_end_date` on or after `window_start_date`, and the whole window inside the span from `rehearsal_start_date` through `return_by_date` inclusive, else `ERR_WINDOW_OUT_OF_BOUNDS`.

Capacity is evaluated per the **availability calculation**: start from the item's `serviceable_unit_count`; subtract the total `quantity` of every *other* reservation of the same item in `HELD` or `CONFIRMED` status whose window overlaps the requested one; subtract the count of pull-list lines in `PENDING`, `PICKED`, or `OUT` status whose reservation is for the same item and whose window overlaps. The request is valid only if the requested `quantity` is no more than the remainder; otherwise it fails with `ERR_CAPACITY_EXCEEDED`. Window overlap uses **inclusive** date intervals: a window overlaps another when its start is on or before the other's end and the other's start is on or before its end. Consequently two windows sharing a boundary day (one's end equal to the other's start) do overlap, while windows separated by even one day do not.

A created reservation starts `HELD`, with its price quoted immediately and its `hold_expires_at` set to the current logical clock plus 72 hours. The reservation states are `HELD`, `CONFIRMED`, `RELEASED`, `EXPIRED`, and `FULFILLED`, the last three terminal; reservations may be listed filtered by `production_id`, `item_id`, or `status`.

The quote selects a `rate_variant` and computes `quoted_charge_cents`. The window length in days is the count of calendar days from `window_start_date` through `window_end_date` inclusive. If the production's pinned `long_run` flag is true, the variant is `LONG_RUN`; otherwise, if the window spans at least seven days the variant is `WEEKLY`, else `DAILY`. Pricing then proceeds per variant, always in integer cents with a single round-half-up step at the reservation level:

- `DAILY`: the charge is the `quantity` times the item's `base_daily_rate_cents` times the number of window days.
- `WEEKLY`: the charge is the `quantity` times the item's `base_weekly_rate_cents` times the number of whole weeks the window spans, rounding the day count up to a whole week — a window of eight days bills two weeks.
- `LONG_RUN`: weekly pricing as above, then discounted: the discount fraction is the pinned card's `deep_run_discount_pct` when the production's `run_weeks` is at least the card's `deep_run_threshold_weeks`, and the card's `long_run_discount_pct` otherwise; the weekly charge is multiplied by one minus the discount. The same window prices lower under `LONG_RUN` than under `WEEKLY`.

All rate inputs — thresholds, discounts, the late-fee percentage — come from the production's pinned rate card (`rate_card_id` and `rate_card_version`), never from the currently published card.

Confirmation of a hold, by the `RenterContact`, re-validates but does not recompute the quote: the production must be `CONFIRMED` (`ERR_INVALID_STATE`), the renter must not be on credit hold (`ERR_CREDIT_LIMIT_EXCEEDED`, described in §3.8), the hold must be unexpired — the current logical timestamp on or before `hold_expires_at`, else `ERR_HOLD_EXPIRED` — and the capacity check above is re-run (`ERR_CAPACITY_EXCEEDED`). Success moves the reservation `HELD` → `CONFIRMED` and **freezes** `quoted_charge_cents`; it is no longer recomputed except via amendment.

Amendment reopens a hold. A `RenterContact` may amend the `quantity`, `window_start_date`, or `window_end_date` of a reservation in `HELD` or `CONFIRMED` status. The amended quantity and window must pass the same capacity check (`ERR_CAPACITY_EXCEEDED`) and stay within production bounds (`ERR_WINDOW_OUT_OF_BOUNDS`). Amending a `CONFIRMED` reservation drops it back to `HELD`; amending a `HELD` reservation keeps it `HELD`. Either way the quote is recomputed under the production's pinned rate card and `hold_expires_at` resets to the current logical clock plus another 72 hours. An amended reservation must be re-confirmed before any new pull-list submission can draw on it.

Release frees a hold. A `RenterContact` may release a `HELD` reservation unconditionally, and may release a `CONFIRMED` one only while no pull-list line in `PENDING`, `PICKED`, or `OUT` status references it — otherwise the release is rejected with `ERR_RESERVATION_IN_USE`. Either way the held quantity is freed for overlapping windows. Holds also end without client action: the daily sweep expires a `HELD` reservation once the current logical timestamp passes `hold_expires_at`, and the renter-suspension and production-cancellation cascades of §3.1 and §3.3 release or expire reservations in bulk. Finally, a `CONFIRMED` reservation becomes `FULFILLED` automatically at the moment a pull list covering its full quantity is dispatched — when the units actually leave the building. Submission alone does not fulfill: a submitted-but-undispatched reservation stays `CONFIRMED`, referenced by its active lines, which is exactly what makes `ERR_RESERVATION_IN_USE` reachable on manual release.

### 3.5. Pull Lists, Unit Selection, and Dispatch

The pull list turns confirmed holds into physical units on a truck. A `RenterContact` creates one for a production in `CONFIRMED` status via a payload containing the `production_id` and the OCC guard `expected_production_version`; the new list is `DRAFT`, and creation increments the production's `version` by one. The pull-list states are `DRAFT`, `PICKING`, `DISPATCHED`, `CLOSED`, and `CANCELLED`, with `CLOSED` and `CANCELLED` terminal; lists may be filtered by `production_id` or `status`.

Submission is the `WardrobeStaff` action that explodes the list into lines, and it is atomic. It requires the production `CONFIRMED` (`ERR_INVALID_STATE`); the production must have at least one reservation in `CONFIRMED` status not already covered by lines on a pull list in `PICKING`, `DISPATCHED`, or `CLOSED` status (`ERR_NOTHING_TO_PULL`); and the unit selector must find enough eligible units for every uncovered confirmed reservation — any shortfall rejects the entire submission with `ERR_NO_UNITS_AVAILABLE` and no lines are created at all. On success the list moves `DRAFT` → `PICKING`, `submitted_at` records the current logical timestamp, and one pull-list line per unit of quantity is created for each uncovered confirmed reservation, taken in reservation order by `window_start_date` ascending and then `created_at` ascending. Covered reservations remain `CONFIRMED` but are now referenced by active lines, so manual release of one fails with `ERR_RESERVATION_IN_USE`.

Each created line records its owning `pull_list_id`, the `reservation_id` it fulfills, and the `item_unit_id` assigned by the selector. The line states are `PENDING`, `PICKED`, `OUT`, `RETURNED`, `DAMAGED`, and `LOST`, the last three terminal; lines may be listed filtered by `pull_list_id`, `reservation_id`, `item_unit_id`, or `status`. The **unit selector** for a reservation window works as follows. Candidate units must belong to the reservation's item, be `AVAILABLE`, hold a `condition_grade` other than `D`, and have no other pull-list line in `PENDING`, `PICKED`, or `OUT` status whose occupied interval collides with the requested window. A line's occupied interval runs from its reservation's `window_start_date` through its reservation's `window_end_date` extended by a category-specific cleaning buffer — two days for `COSTUME`, one day for `PROP`, one day for `SET_DRESSING`, three days for `WEAPONRY`, and one day for `ACCESSORY`. A collision exists when the requested start is on or before the occupied interval's end and the occupied interval's start is on or before the requested end. Note this is a per-unit **strict buffered** exclusion, unlike the reservation-level inclusive aggregate check of §3.4: back-to-back windows falling inside the buffer are rejected for that unit. Candidates are ranked by `condition_grade` ascending (`A` first), then `last_returned_date` ascending with nulls first, then `created_at` ascending, and the top `quantity` units are taken.

Each line's `rental_charge_cents` is computed at assignment. The reservation's frozen-or-current `quoted_charge_cents` is divided by its `quantity` and rounded half up to a whole cent, pinning the division rounding at this step; that per-unit figure is then multiplied by a condition multiplier taken from the unit's `condition_grade` at assignment — 1.20 for grade `A`, 1.00 for grade `B`, 0.85 for grade `C` — and the result is rounded half up again. Per-line rounding is pinned here: invoice generation later sums these stored per-line integers and never re-rounds.

While the list is `PICKING`, `WardrobeStaff` mark each line picked; picking a line while its pull list is not `PICKING` fails with `ERR_INVALID_STATE`. Dispatch then requires every line in `PICKED` status (`ERR_LINES_NOT_PICKED`), plus three renter gates: the renter `ACTIVE` (`ERR_RENTER_SUSPENDED`), not on credit hold (`ERR_CREDIT_LIMIT_EXCEEDED`), and holding a certificate in `VERIFIED` status with `expiry_date` on or after the current logical date (`ERR_INSURANCE_NOT_VERIFIED`). Dispatch moves the list `PICKING` → `DISPATCHED`, stamps `dispatched_at` with the current logical timestamp, moves every line `PICKED` → `OUT` with its `due_back_date` set to the reservation's `window_end_date` (late fees accrue after that date), moves every assigned unit `AVAILABLE` → `OUT`, and — because the units have actually left the building — moves every covered reservation `CONFIRMED` → `FULFILLED`.

Cancellation is split by role and state. A `RenterContact` may cancel their own list while it is `DRAFT`; `WardrobeStaff` may cancel while it is `PICKING`. Cancelling a `PICKING` list deletes all its `PENDING` and `PICKED` lines and releases the unit assignments (the units were never removed from `AVAILABLE`), while the covered reservations stay `CONFIRMED` — fulfillment happens only at dispatch, so no rollback is needed. Once a list is `DISPATCHED` its lines are out the door and cancellation is no longer a valid transition. A dispatched list closes automatically: when every line has reached a terminal state (`RETURNED`, `DAMAGED`, or `LOST`), every approved fitting on its lines has been restored, and every `DAMAGED` or `LOST` line has a damage claim in `POSTED` or `WAIVED` status, the list moves to `CLOSED` and the production settle evaluation of §3.8 runs as a bubble-up.

### 3.6. Check-in, Restoration, and the Cleaning Cycle

What goes out must come back, and check-in is where the house learns what condition it came back in. A `WardrobeStaff` checks in an `OUT` line by supplying the observed `condition_grade_after` (`A`, `B`, `C`, or `D`), the `damage_severity` (one of `NONE`, `MINOR`, `REPAIRABLE`, `DESTROYED`), and a `restoration_complete` flag asserting that all approved alterations were reversed before return. One safety gate applies first: if the line carries a fitting authorization in `APPROVED` status, `restoration_complete` must be true or the check-in is rejected with `ERR_RESTORATION_INCOMPLETE`.

Check-in creates exactly one return assessment per line — a strict one-to-one, retrievable as an array of zero or one assessments for the line. The assessment records the `pull_list_line_id`, the `condition_grade_before` (the unit's grade at dispatch time), the supplied `condition_grade_after`, `damage_severity`, and `restoration_complete`, the computed `late_days`, and the `assessed_by_user_id` taken from the acting staff member's `X-User-ID`. The `late_days` is the number of whole days between the `due_back_date` and the return date, never below zero — returning exactly on the due date yields zero late days. The unit's `condition_grade` is updated to `condition_grade_after` and its `last_returned_date` set to the current logical date. When `restoration_complete` is true, every fitting authorization on the line in `APPROVED` status moves automatically to `RESTORED`.

Severity drives the branch. With `damage_severity` of `NONE` the line becomes `RETURNED`, the unit moves `OUT` → `CLEANING`, and a cleaning ticket is created with `requires_repair` false. With `MINOR` the line becomes `DAMAGED` but the unit still moves `OUT` → `CLEANING` with a no-repair ticket. With `REPAIRABLE` the line becomes `DAMAGED`, the unit moves `OUT` → `REPAIR`, and the ticket is created with `requires_repair` true. With `DESTROYED` the line becomes `DAMAGED`, the unit moves `OUT` → `DISPOSED`, no cleaning ticket is created, and the item's `serviceable_unit_count` is recomputed. In every branch the line's `returned_at` records the logical check-in timestamp, its late fee is computed, and — if this was the last non-terminal line — the pull-list auto-close evaluation runs (for a `DAMAGED` line, closing additionally requires a `POSTED` or `WAIVED` claim for that line).

The late fee, computed at check-in and stored as the line's `late_fee_cents`, is the `late_days` times the item's `base_daily_rate_cents` times the same condition multiplier used for line rental charges (1.20 for `A`, 1.00 for `B`, 0.85 for `C`, taken from the unit's current grade) times the pinned rate card's `late_fee_daily_pct`, rounded half up to whole cents.

Loss is a separate declaration. A `WardrobeStaff` may report an `OUT` line lost, and the daily sweep auto-loses any line still `OUT` once the current logical date is more than seven days past its `due_back_date`. Either way the line becomes `LOST`, the unit moves `OUT` → `DISPOSED`, `serviceable_unit_count` is recomputed, and the late fee is computed with `late_days` fixed at seven — a fixed grace, not an open-ended accrual. Pull-list auto-close evaluation runs, requiring a `POSTED` or `WAIVED` loss claim for the line.

Alterations are authorized per line. A `RenterContact` requests a fitting authorization for one of their own lines with the `pull_list_line_id`, an `alteration_type` (one of `HEM`, `TAKE_IN`, `LET_OUT`, `DYE`, `DISTRESS`, `TRIM`), and optional tailor `notes` (defaulting to empty). The line must be in `PENDING`, `PICKED`, or `OUT` status. The item's `alteration_policy` gates the request: `PROHIBITED` rejects every alteration type, and `REVERSIBLE_ONLY` allows only `HEM`, `TAKE_IN`, and `LET_OUT` — a forbidden request fails with `ERR_ALTERATION_PROHIBITED`; `TAILORING_ALLOWED` permits all six types. A new authorization is `REQUESTED`. A `HouseAdmin` then decides it with a `decision`: approval requires the line still be in `PENDING`, `PICKED`, or `OUT` (`ERR_INVALID_STATE` otherwise) and moves the authorization `REQUESTED` → `APPROVED`; rejection moves it to `REJECTED`. Either decision records the admin's `X-User-ID` in `decided_by_user_id`. The authorization states are `REQUESTED`, `APPROVED`, `REJECTED`, and `RESTORED`, with `REJECTED` and `RESTORED` terminal; authorizations may be listed filtered by `pull_list_line_id` or `status`.

Returned units re-enter the house through the cleaning cycle. A cleaning ticket, created at check-in, records the `item_unit_id`, the `queued_at` logical timestamp, the `queue_depth_at_creation`, the `requires_repair` flag, a `repair_done` flag starting false, a computed `cleaning_fee_cents`, an `invoiced` flag starting false, and a `ready_at` timestamp that stays null until the end. The ticket states are `QUEUED`, `IN_CLEANING`, `INSPECTION`, `REPAIR`, and `READY` (terminal); tickets for a unit may be listed filtered by `status`. `WardrobeStaff` advance a ticket one stage at a time: `QUEUED` → `IN_CLEANING` → `INSPECTION`, and from `INSPECTION` the path forks — a ticket with `requires_repair` true and `repair_done` false advances to `REPAIR`, a ticket with `requires_repair` false or `repair_done` true advances to `READY`, and a ticket in `REPAIR` advances back to `INSPECTION` with `repair_done` set true, so a repair always returns through inspection before release. Reaching `READY` stamps `ready_at` with the current logical timestamp and returns the unit from `CLEANING` or `REPAIR` to `AVAILABLE`.

The cleaning fee is fixed at ticket creation. The base fee depends on the item's `category`: 1500 cents for `COSTUME`, 800 for `PROP`, 1200 for `SET_DRESSING`, 2500 for `WEAPONRY`, and 500 for `ACCESSORY`. The `queue_depth_at_creation` counts the tickets in `QUEUED` or `IN_CLEANING` status at the moment of creation; when that depth is at least ten, the base fee is multiplied by a rush factor of 1.5 and rounded half up — a depth of exactly ten triggers the rush multiplier, nine does not. Below the threshold the fee is simply the base.

### 3.7. Damage and Loss Claims

Damage has a price, and who sets that price is deliberately separated from who bills it. A `WardrobeStaff` creates a claim with the `pull_list_line_id`, a `claim_type` of `DAMAGE` or `LOSS`, and — for `DAMAGE` claims — the `return_assessment_id` of the line's check-in assessment. Type must match reality: a `DAMAGE` claim requires the line in `DAMAGED` status together with its assessment, and a `LOSS` claim requires the line in `LOST` status with `return_assessment_id` null; a mismatch is `ERR_CLAIM_TYPE_MISMATCH`. Only one claim may exist per line — a second is rejected with `ERR_CLAIM_ALREADY_EXISTS`. The new claim is `DRAFT`, its `created_by_user_id` records the creator's `X-User-ID`, its `posted_by_user_id` stays null until posting, and its `invoice_id` stays null until billed. The claim states are `DRAFT`, `POSTED`, `DISPUTED`, and `WAIVED`, with `WAIVED` terminal; claims may be listed filtered by `return_assessment_id`, `pull_list_line_id`, `invoice_id`, or `status`.

Valuation is computed at creation and stored as `assessed_value_cents`, with the `valuation_method` recorded alongside. For `LOSS` claims the method short-circuits: the value is always the item's full `replacement_value_cents` — a total loss, no grade multiplier. For `DAMAGE` claims the method is `AGREED_VALUE` when the renter holds at least one certificate in `VERIFIED` status whose `coverage_cents` is at least the item's `replacement_value_cents` (equal coverage qualifies) and whose `expiry_date` is on or after the assessment date; otherwise it is `DEPRECIATED_REPLACEMENT`. The two methods value differently:

- `AGREED_VALUE`: the item's `replacement_value_cents` times a valuation grade multiplier — 1.00 for grade `A`, 0.80 for `B`, 0.60 for `C`, 0.40 for `D` — rounded half up. It is independent of acquisition cost and age.
- `DEPRECIATED_REPLACEMENT`: straight-line depreciation from the unit's `acquisition_cost_cents` over a five-year useful life. The unit's age in whole years is the number of days between its `acquisition_date` and the assessment date divided by 365, rounded down. The raw depreciated value is the acquisition cost times one minus the age in years divided by five. A salvage floor of ten percent of the item's `replacement_value_cents` applies: the larger of the raw value and the floor is taken, then multiplied by the same valuation grade multiplier, and the result is rounded half up to whole cents.

Posting and waiving belong to the `Accountant`, under segregation of duties: the posting request is rejected with `ERR_SOD_VIOLATION` (HTTP 403) when the poster's `X-User-ID` equals the claim's `created_by_user_id` — the wardrobe staff member who assessed the damage may not post its charge. Posting moves a `DRAFT` claim to `POSTED`, records `posted_by_user_id`, and makes the claim sweepable by invoice generation. Waiving a `DRAFT` claim moves it to `WAIVED` and no charge will be billed. The renter may push back: a `RenterContact` disputes a `POSTED` claim of their own, moving it to `DISPUTED` — but only while the claim's `invoice_id` is still null, because a claim already swept into an invoice cannot be disputed (`ERR_CLAIM_ALREADY_BILLED`). From `DISPUTED` the loop continues: an `Accountant` may re-post the claim (re-affirming it, with the same segregation-of-duties check) or waive it.

### 3.8. Invoicing, Payments, Credit, and Settlement

Billing is production-scoped and sweep-based. An `Accountant` generates an invoice for a `production_id`; the generation sweeps every unbilled charge of that production into a new `OPEN` invoice. The sweep set is pinned: rental charges from pull-list lines in `OUT`, `RETURNED`, `DAMAGED`, or `LOST` status with `rental_invoiced` false (rental bills at or after dispatch, before return); late fees from lines in `RETURNED`, `DAMAGED`, or `LOST` status with `late_fee_invoiced` false — the two flags are independent, so a line whose rental was already swept can still contribute a late fee to a later invoice; cleaning fees from tickets with `invoiced` false; and damage charges from claims in `POSTED` status with `invoice_id` null. An empty sweep set is rejected with `ERR_INVOICE_EMPTY`. Each swept record is stamped atomically with generation — `rental_invoiced` or `late_fee_invoiced` set true on lines, `invoiced` true on tickets, `invoice_id` set on claims.

The invoice's component totals are frozen at sweep time: `rental_charges_cents` is the sum of swept lines' `rental_charge_cents` (the per-line rounded values are summed, never re-rounded), `late_fee_cents` the sum of swept `late_fee_cents`, `cleaning_charges_cents` the sum of swept `cleaning_fee_cents`, and `damage_charges_cents` the sum of swept claims' `assessed_value_cents`. The `total_cents` is those four components minus the accumulated `credited_cents`, and the `balance_cents` is `total_cents` minus the accumulated `amount_paid_cents`; both `credited_cents` and `amount_paid_cents` start at 0. The invoice states are `OPEN`, `ISSUED`, `PARTIALLY_PAID`, `PAID`, `CREDITED`, and `VOID`, with `PAID`, `CREDITED`, and `VOID` terminal; invoices may be listed filtered by `production_id` or `status`.

Issuing, by an `Accountant`, requires a `total_cents` greater than zero (`ERR_INVOICE_EMPTY`); it moves the invoice `OPEN` → `ISSUED` and immediately pulls the balance into the renter's credit picture. The renter's `outstanding_balance_cents` is recomputed as the sum of `balance_cents` over all of that renter's invoices in `ISSUED` or `PARTIALLY_PAID` status, and `credit_hold` is recomputed as true exactly when the outstanding balance is **strictly greater** than `credit_limit_cents` — a balance equal to the limit does not hold. A renter on credit hold finds reservation confirmation and pull-list dispatch rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

Payments and credit notes follow a pinned evaluation order so the apparent cycle — invoice balance depends on payments, credit hold depends on balance, confirmation and dispatch gating depend on the hold — resolves deterministically within one request: first the invoice's `amount_paid_cents` or `credited_cents` is mutated, then the invoice's `balance_cents` and `total_cents` are recomputed, then the renter's `outstanding_balance_cents`, and finally the renter's `credit_hold`.

Recording a payment against an `ISSUED` or `PARTIALLY_PAID` invoice takes an `amount_cents` of at least 1 (`ERR_PAYMENT_INVALID`) and no more than the invoice's current `balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`). The payment accumulates into `amount_paid_cents`; a payment below the balance moves the invoice to `PARTIALLY_PAID` (or keeps it there), and one bringing `amount_paid_cents` level with `total_cents` moves it to `PAID`. Either way the renter aggregates are recomputed, and production settle evaluation runs.

A credit note, also by an `Accountant`, applies to an `OPEN`, `ISSUED`, or `PARTIALLY_PAID` invoice with an `amount_cents` and an optional `reason`. The amount must be at least 1 (`ERR_CREDIT_INVALID`) and no more than the current `balance_cents` (`ERR_CREDIT_EXCEEDS_BALANCE`); it accumulates into `credited_cents` and reduces `total_cents`. A credit equal to the full balance settles the invoice: from `ISSUED` or `PARTIALLY_PAID` it becomes `CREDITED`. A full-total credit note on an `OPEN` invoice is the administrative void of an unissued invoice: the invoice becomes `VOID`, and every record swept into it becomes unbilled again — `rental_invoiced` and `late_fee_invoiced` back to false on lines, `invoiced` back to false on tickets, and `invoice_id` back to null on claims. Each credit note also recomputes the renter aggregates and runs production settle evaluation.

Settlement is the production's finish line, evaluated after the daily sweep, after pull-list auto-close, and after every payment or credit note. A production in `WRAP` moves to `SETTLED` only when all of the following hold: every pull list of the production is `CLOSED` or `CANCELLED`; every invoice of the production is `PAID`, `CREDITED`, or `VOID`; and no unbilled charges remain — no pull-list line in `OUT`, `RETURNED`, `DAMAGED`, or `LOST` status with `rental_invoiced` false, no line in `RETURNED`, `DAMAGED`, or `LOST` status with `late_fee_invoiced` false, no `POSTED` damage claim with `invoice_id` null, and no cleaning ticket with `invoiced` false.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, decisions, sweeps, payments, and credit notes — return `200 OK`. Request bodies, response payloads, and side effects for each endpoint are specified by the workflows in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rental-house/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | HouseAdmin |
| POST | `/rental-house/run_daily_ops` | Run the daily operations sweep against the logical clock | HouseAdmin |
| POST | `/rental-house/renters` | Register a renter organization (`PENDING_VERIFICATION`) | HouseAdmin |
| GET | `/rental-house/renters` | List renters with optional status filter | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/renters/{id}` | Get one renter including computed balance and credit hold | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| PATCH | `/rental-house/renters/{id}` | Update credit limit and/or manually suspend or reactivate | HouseAdmin |
| POST | `/rental-house/renters/{id}/insurance-certificates` | Submit an insurance certificate for a renter | HouseAdmin, RenterContact |
| GET | `/rental-house/renters/{id}/insurance-certificates` | List a renter's certificates | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/insurance-certificates/{id}` | Get one certificate | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/insurance-certificates/{id}/decide` | Verify or reject a `SUBMITTED` certificate | HouseAdmin |
| POST | `/rental-house/rate-cards` | Publish a new rate card (prior published card superseded) | HouseAdmin |
| GET | `/rental-house/rate-cards` | List rate cards | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/rate-cards/{id}` | Get one rate card | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/items` | Create a catalog item | HouseAdmin |
| GET | `/rental-house/items` | List items; deaccessioned hidden unless include_deaccessioned | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/items/{id}` | Get one item including computed serviceable unit count | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/items/{id}/request-deaccession` | Begin deaccession; available units move to awaiting disposal | HouseAdmin |
| POST | `/rental-house/items/{id}/cancel-deaccession` | Abort deaccession; units return to available | HouseAdmin |
| POST | `/rental-house/items/{id}/complete-deaccession` | Finalize deaccession; units disposed | HouseAdmin |
| POST | `/rental-house/items/{id}/units` | Acquire (source) one physical unit of an item | HouseAdmin |
| GET | `/rental-house/items/{id}/units` | List units of an item | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/units/{id}` | Get one unit | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/productions` | Create a production (`DRAFT`) | RenterContact |
| GET | `/rental-house/productions` | List productions | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/productions/{id}` | Get one production including computed dates and pinned rate card | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/productions/{id}/confirm` | Confirm a `DRAFT` production and pin the rate card | RenterContact |
| POST | `/rental-house/productions/{id}/cancel` | Cancel a `DRAFT` or `CONFIRMED` production | RenterContact |
| POST | `/rental-house/reservations` | Place a dated hold on a quantity of an item (OCC-guarded) | RenterContact |
| GET | `/rental-house/reservations` | List reservations | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/reservations/{id}` | Get one reservation | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/reservations/{id}/confirm` | Confirm a `HELD` reservation and freeze its quote | RenterContact |
| POST | `/rental-house/reservations/{id}/release` | Release a `HELD` or `CONFIRMED` reservation | RenterContact |
| POST | `/rental-house/reservations/{id}/amend` | Amend quantity or window; confirmed holds drop back to held | RenterContact |
| POST | `/rental-house/pull-lists` | Create a `DRAFT` pull list for a confirmed production (OCC-guarded) | RenterContact |
| GET | `/rental-house/pull-lists` | List pull lists | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/pull-lists/{id}` | Get one pull list | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/pull-lists/{id}/submit` | Submit a draft list; atomically create lines and assign units | WardrobeStaff |
| POST | `/rental-house/pull-lists/{id}/dispatch` | Dispatch a fully picked list; lines and units go out | WardrobeStaff |
| POST | `/rental-house/pull-lists/{id}/cancel` | Cancel a draft or picking pull list | RenterContact, WardrobeStaff |
| GET | `/rental-house/pull-list-lines` | List pull-list lines | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/pull-list-lines/{id}` | Get one pull-list line | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/pull-list-lines/{id}/pick` | Mark a `PENDING` line `PICKED` | WardrobeStaff |
| POST | `/rental-house/pull-list-lines/{id}/check-in` | Check in an `OUT` line with return assessment | WardrobeStaff |
| POST | `/rental-house/pull-list-lines/{id}/report-lost` | Report an `OUT` line lost | WardrobeStaff |
| GET | `/rental-house/pull-list-lines/{id}/assessment` | Get the assessment for a line (array of 0 or 1) | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/fitting-authorizations` | Request an alteration on a line | RenterContact |
| GET | `/rental-house/fitting-authorizations` | List fitting authorizations | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/fitting-authorizations/{id}` | Get one fitting authorization | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/fitting-authorizations/{id}/decide` | Approve or reject a requested fitting authorization | HouseAdmin |
| POST | `/rental-house/damage-claims` | Create a damage or loss claim on a line | WardrobeStaff |
| GET | `/rental-house/damage-claims` | List damage claims | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/damage-claims/{id}` | Get one damage claim | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/damage-claims/{id}/post` | Post a draft or disputed claim (segregation of duties) | Accountant |
| POST | `/rental-house/damage-claims/{id}/dispute` | Dispute a posted, not-yet-billed claim | RenterContact |
| POST | `/rental-house/damage-claims/{id}/waive` | Waive a draft or disputed claim | Accountant |
| GET | `/rental-house/units/{id}/cleaning-tickets` | List cleaning tickets for a unit | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/cleaning-tickets/{id}/advance` | Advance a ticket one stage; ready returns the unit | WardrobeStaff |
| POST | `/rental-house/invoices/generate` | Generate an `OPEN` invoice sweeping unbilled production charges | Accountant |
| GET | `/rental-house/invoices` | List invoices | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| GET | `/rental-house/invoices/{id}` | Get one invoice | HouseAdmin, WardrobeStaff, Accountant, RenterContact |
| POST | `/rental-house/invoices/{id}/issue` | Issue an `OPEN` invoice; renter credit aggregates recomputed | Accountant |
| POST | `/rental-house/invoices/{id}/record-payment` | Record a payment against an issued invoice | Accountant |
| POST | `/rental-house/invoices/{id}/credit-note` | Apply a credit note; full-balance credit settles or voids | Accountant |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_RENTER_SCOPE_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RENTER_SUSPENDED` | 409 |
| `ERR_INSURANCE_NOT_VERIFIED` | 422 |
| `ERR_INSUFFICIENT_COVERAGE` | 422 |
| `ERR_CERTIFICATE_EXPIRED` | 422 |
| `ERR_ALTERATION_PROHIBITED` | 422 |
| `ERR_RESTORATION_INCOMPLETE` | 409 |
| `ERR_ITEM_NOT_RENTABLE` | 409 |
| `ERR_ITEM_HAS_ACTIVE_HOLDS` | 409 |
| `ERR_RATE_CARD_REQUIRED` | 409 |
| `ERR_WINDOW_OUT_OF_BOUNDS` | 422 |
| `ERR_DATE_ORDER` | 422 |
| `ERR_QUANTITY_INVALID` | 400 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_UNITS_AVAILABLE` | 409 |
| `ERR_NOTHING_TO_PULL` | 409 |
| `ERR_LINES_NOT_PICKED` | 409 |
| `ERR_RESERVATION_IN_USE` | 409 |
| `ERR_PRODUCTION_HAS_ACTIVE_PULLS` | 409 |
| `ERR_DEACCESSION_BLOCKED` | 409 |
| `ERR_DUPLICATE_BARCODE` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_CLAIM_TYPE_MISMATCH` | 409 |
| `ERR_CLAIM_ALREADY_BILLED` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_INVOICE_EMPTY` | 409 |
| `ERR_PAYMENT_INVALID` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_CREDIT_INVALID` | 422 |
| `ERR_CREDIT_EXCEEDS_BALANCE` | 422 |

# Frozen-Yogurt Self-Serve API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Frozen-Yogurt Self-Serve API, the back-office and point-of-sale engine for a by-weight, self-serve dessert shop. The system spans the full operational surface of such a store: guests dispense yogurt from soft-serve machines and add toppings, cups are weighed and priced by the ounce, and cashiers ring up tickets that later settle against a daily cash count. Around this core POS loop sit the supporting disciplines that keep a food-service operation honest — flavor and topping inventory with rotation, machine mix levels and a sanitation/cleaning cadence, allergen safety, waste and melt logging, loyalty punch-cards with seasonal promotions, party/catering bookings, and end-of-day reconciliation.

The API is fundamentally a **ledger-reconciliation** system wearing a retail skin. Nearly every mutation touches more than one entity: dispensing a cup depletes a machine's mix and a topping's stock, voiding a ticket restores them, and closing a reconciliation sweeps a day's charged tickets into finalized revenue while finalizing loyalty points and issuing reward vouchers. Because value flows across aggregates, the system is exacting about ordering, precision, and the exact moment each side effect fires. A second, compliance-flavored concern runs through it: machines fall out of service when their cleaning interval lapses, flavors suspend and resume with their parent machine, and allergen exclusions block unsafe cups outright.

Two pricing regimes coexist by design. At checkout a ticket is priced under a **QUOTED** variant (per-line discount, rounded then summed); at day-end close the same ticket is re-priced under a **FINALIZED** variant (summed first, discounted once), and the two can legitimately differ by rounding granularity. Understanding that distinction — and the many cascades, temporal windows, and optimistic-concurrency guards described below — is the essence of implementing this system correctly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operator's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly three roles, forming a strict hierarchy in which each higher role can do everything the roles beneath it can: `Cashier`, `ShiftLead`, and `Manager`, where `Manager` outranks `ShiftLead`, which outranks `Cashier`. A `Cashier` runs the front counter — opening tickets, weighing cups, checkout, loyalty enrollment, drafting and cancelling catering orders, and all general reads. A `ShiftLead` inherits everything a `Cashier` may do and additionally manages inventory and the shop floor: loading and rotating flavors, creating/restocking/rotating toppings, machine cleaning and mix refills and sanitation checks, voiding charged tickets, logging waste, and scheduling or cancelling maintenance windows. A `Manager` inherits everything a `ShiftLead` may do and additionally owns machine creation, catering resources, seasonal promotions, loyalty suspension, the entire catering order lifecycle (quote, confirm, fulfill), and the reconciliation lifecycle (open, close, post adjustments). When an operator attempts an action their role does not authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Reads of waste events, sanitation logs, and daily reconciliations are restricted to `ShiftLead` and `Manager` (reconciliations are `Manager`-only); the remaining reads are available to all three roles.

All three roles carry an **opaque** identity. When `X-User-Role` is `Cashier`, `ShiftLead`, or `Manager`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any resource's `id`, and no ownership check is performed against it. Authorization is therefore purely role-based, not identity-based.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 (a supplied value below 1 or above 100 is clamped to the nearest bound rather than rejected). The `offset` parameter is the number of items to skip and defaults to 0 (a negative value is clamped to 0). Unless a subsection states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties on `created_at` broken by creation (insertion) order.

Every list-based response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. List endpoints additionally accept the domain filters described alongside their resources — for example `status`, `sanitation_status`, `machine_id`, `flavor_id`, `topping_id`, `ticket_id`, `resource_id`, `loyalty_account_id`, `reconciliation_id`, `redeemed_voucher_id`, and `payment_status` — which narrow the result set before pagination is applied.

### 2.4. The Logical Clock

The server keeps a **logical clock** that governs every time-dependent rule in the system: sanitation cadence, seasonal-promotion windows, voucher issuance and expiry, catering and maintenance intervals, and every `*_at` timestamp written by a transition. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it, the clock returns precisely this default — it never falls back to wall-clock time. A test-driving capability lets any role set the clock to a supplied `to_iso8601` instant; all subsequent "now" evaluations use the most recently set value. Wherever this document says "the current clock" or "now," it means this logical clock.

### 2.5. Common Resource Properties

Most resources are **fully versioned** and carry a standard system-managed set of fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits marking creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that starts at its initial value and increments by one on every mutation. The versioned resources are Machine, Flavor, Topping, SeasonalPromotion, LoyaltyAccount, RewardVoucher, SaleTicket, MaintenanceWindow, CateringResource, CateringOrder, and DailyReconciliation.

Three resources are **append-only or immutable** and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field: `SaleLine` (an appended cup line on a ticket), `WasteEvent` (an immutable melt/waste log entry), and `SanitationLog` (an appended cleaning-log entry). Any derived field that changes on a versioned resource — a machine's mix level, a loyalty account's point balances, a reconciliation's expected revenue — is a genuine mutation that refreshes `updated_at` and increments `version`.

### 2.6. Monetary and Numeric Precision

All money in the system is expressed in **integer cents**; there are no fractional-cent values in stored fields or responses. Wherever a calculation rounds, it uses the **round-half-up** convention (ties round away from zero, to the next higher cent), and rounding is applied at exactly the step each formula names — never earlier and never later. Point balances are integers derived by **flooring** an integer-cents amount divided by a divisor. The precise rounding step of each formula (per-line versus after summing) is a load-bearing part of the specification and is spelled out in the relevant §3 subsection.

### 2.7. Validation Ordering

When several checks could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The global order is: first authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (the `ERR_*_NOT_FOUND` family, HTTP 404), then the target resource's state eligibility for the requested transition (HTTP 409), and only then the operation-specific business rules. A malformed body — a missing required field or a value of the wrong type — is rejected with `ERR_VALIDATION` (HTTP 400).

Existence is checked left-to-right: path identifiers are resolved before body foreign keys, and the first identifier that fails to resolve determines the 404. The not-found codes are resource-specific: `ERR_MACHINE_NOT_FOUND`, `ERR_FLAVOR_NOT_FOUND`, `ERR_TOPPING_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_LOYALTY_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_WASTE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND` (catering resource), `ERR_CATERING_NOT_FOUND` (catering order), `ERR_RECONCILIATION_NOT_FOUND`, and `ERR_SANITATION_LOG_NOT_FOUND` (sanitation log).

The most intricate ordering is the one that guards adding a cup to a ticket. On that operation, once the ticket and flavor are known to exist and the ticket is eligible, the business checks fire in this exact sequence: (1) the **allergen guard**, rejecting with `ERR_ALLERGEN_CONFLICT`; (2) the **sanitation gate**, requiring the flavor's machine to be `READY`, rejecting with `ERR_MACHINE_NOT_READY`; (3) **inventory availability** of the flavor and every requested topping, rejecting with `ERR_TOPPING_UNAVAILABLE`; (4) **net-weight validity**, rejecting with `ERR_INVALID_WEIGHT`; and (5) **mix sufficiency**, rejecting with `ERR_INSUFFICIENT_MIX`. The details of each check live in §3.4.

### 2.8. Hierarchical Consistency and Cascades

Several operations mutate more than one resource, and the system commits every cascade as part of the triggering operation. A machine and the flavors loaded into it move together: when a machine goes `OUT_OF_SERVICE`, every flavor loaded on it that is `LOADED` cascades to `SUSPENDED`; when that machine finishes cleaning and returns to `READY`, every `SUSPENDED` flavor on it cascades back to `LOADED`. Voiding a charged ticket reverses the ticket's inventory footprint across its lines' source machines and toppings. Closing a reconciliation sweeps a whole day's charged tickets to `RECONCILED` and, through that sweep, mutates the attached loyalty accounts and may issue reward vouchers. Each of these secondary mutations refreshes the affected resource's `updated_at` and increments its `version`, exactly as a direct mutation would.

### 2.9. Optimistic Concurrency Control

Two create operations legitimately **supersede** state on a parent resource, and both are protected by optimistic concurrency control so a client cannot overwrite state it has not observed.

Scheduling a maintenance window supersedes a machine's prior maintenance stamp: the request must carry `expected_machine_version` holding the client's last-observed `version` of the target Machine. Because a successful schedule re-stamps `next_maintenance_at` and increments the machine's `version`, a second request that still carries the pre-supersede value is stale; if `expected_machine_version` does not equal the machine's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Posting an adjustment to a daily reconciliation supersedes that reconciliation's running expected-revenue and variance: the request must carry `expected_daily_reconciliation_version` holding the client's last-observed `version` of the DailyReconciliation. Each posted adjustment re-derives those totals and increments the reconciliation's `version`, so an adjustment carrying the pre-supersede value is stale; if `expected_daily_reconciliation_version` does not equal the reconciliation's current `version`, the post is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and endpoints that do not appear here perform no OCC check.

## 3. Business Logic & Workflows

### 3.1. Machines, Mix Levels, and the Sanitation Cycle

A soft-serve **Machine** is created by a `Manager` with a human `name` (for example, "Barrel-A") and a target mix level, `mix_par_oz`, expressed in ounces — the level to which refills top the barrel up. An optional `initial_mix_oz` seeds the starting `current_mix_level_oz`; when omitted, the machine starts full at `mix_par_oz`. On creation the machine's `sanitation_status` is `READY`, its `last_cleaned_at` is stamped to the current clock, and `next_maintenance_at` is `null` until a maintenance window is scheduled. The `current_mix_level_oz` is read-only and moves only through dispensing, void restoration, and refills; `last_cleaned_at` and `next_maintenance_at` are likewise read-only.

The `sanitation_status` field cycles through `READY`, `CLEANING`, and `OUT_OF_SERVICE`. A `ShiftLead` begins a cleaning cycle from either `READY` or `OUT_OF_SERVICE`, moving the machine to `CLEANING`; if the machine is in neither eligible state the request is rejected with `ERR_MACHINE_INVALID_STATE`. Completing a cleaning cycle requires the machine to be `CLEANING` (otherwise `ERR_MACHINE_INVALID_STATE`) and drives it back to `READY`. Completion has three side effects committed together: a `SanitationLog` entry is appended recording `machine_id`, `cleaned_at` set to the current clock, and `previous_status` of `CLEANING`; the machine's `last_cleaned_at` is set to the current clock; and every flavor on that machine currently `SUSPENDED` cascades to `LOADED`.

Sanitation is enforced on a fixed cadence measured against `last_cleaned_at`. A machine is **overdue** when the current clock has reached or passed `last_cleaned_at` plus the cleaning interval, `CLEAN_INTERVAL_HOURS` (4 hours) — the boundary is inclusive, so the exact instant `last_cleaned_at` plus `CLEAN_INTERVAL_HOURS` already counts as overdue. When an overdue machine is still `READY`, the system transitions it from `READY` to `OUT_OF_SERVICE` and cascades every `LOADED` flavor on it to `SUSPENDED`. This evaluation runs both when a `ShiftLead` explicitly asks the machine to check its sanitation cadence and, implicitly, whenever a cup is about to be dispensed from one of its flavors — so a lapsed machine is caught at dispense time even if no one ran an explicit check. A `ShiftLead` refills a barrel by supplying `added_oz`; the new `current_mix_level_oz` is the smaller of `mix_par_oz` and the prior level plus `added_oz`, so a refill never overfills beyond par.

### 3.2. Flavors and Toppings

A **Flavor** is a mix loaded into a barrel by a `ShiftLead`, who supplies the parent `machine_id`, the flavor `name` (for example, "Tart Original"), a retail `price_per_oz_cents`, a cost basis `cost_per_oz_cents`, and an optional `allergen_tags` array drawn from the set `DAIRY`, `NUTS`, `SOY`, `GLUTEN`, `EGG` (empty by default). A new flavor's `status` is `LOADED`, meaning available to dispense. A flavor's `status` follows its barrel: it toggles between `LOADED` and `SUSPENDED` as its parent machine leaves and returns to service, as described in §3.1. A `ShiftLead` may permanently rotate a flavor off the menu, moving it from `LOADED` to the terminal `ROTATED_OUT`; this requires the flavor to currently be `LOADED`, and otherwise fails with `ERR_FLAVOR_INVALID_STATE`. Flavors can be listed and filtered by `machine_id` and `status`.

A **Topping** is a bar item created by a `ShiftLead` with a `name` (for example, "Mochi"), a flat per-serving `surcharge_cents` added to any cup that includes it, an `initial_units` count that seeds the read-only `on_hand_units`, and an optional `allergen_tags` array from the same allergen set. Each cup that includes a topping consumes one unit of its `on_hand_units`; voiding a ticket restores consumed units, and a `ShiftLead` may increase stock by supplying `added_units` on a restock, which adds to `on_hand_units`. A new topping's `status` is `AVAILABLE`; a `ShiftLead` may rotate it to the terminal `ROTATED_OUT`, which requires the topping to currently be `AVAILABLE` and otherwise fails with `ERR_TOPPING_INVALID_STATE`.

### 3.3. Seasonal Promotions

A `Manager` defines a **SeasonalPromotion** with a `name`, a fractional `discount_pct` between 0 and 1 (for example, `0.10` for ten percent) that applies to the yogurt-weight portion of a cup, and an active window bounded by `starts_at` (inclusive) and `ends_at` (exclusive). A promotion is active exactly when the current clock is at or after `starts_at` and strictly before `ends_at`. The discount that pricing uses is the one active at the relevant evaluation clock; when no promotion is active, the discount is zero. How the discount enters each pricing variant differs between checkout and finalization, and is detailed in §3.5 and §3.11 respectively.

### 3.4. The Self-Serve Sale: Tickets and Cups

A **SaleTicket** is opened by a `Cashier` and starts life with `payment_status` of `OPEN` and `reconciliation_status` of `UNRECONCILED` — two independent axes that advance separately. At open time the guest may attach an optional member via `loyalty_account_id` and declare an `excluded_allergens` array (a subset of `DAIRY`, `NUTS`, `SOY`, `GLUTEN`, `EGG`) capturing allergens the guest cannot have. The ticket's `reconciliation_id` and `redeemed_voucher_id` remain `null` until, respectively, a reconciliation sweeps the ticket and a voucher is redeemed at checkout.

Adding a cup appends a **SaleLine** to the ticket. A line is an append-only record (it carries only `id` and `created_at`, no `updated_at` or `version`) linked to its parent through `ticket_id`. The operator supplies the dispensed `flavor_id`, the scale's `gross_weight_oz` (cup plus product), an optional `container_tare_oz` (the empty cup's tare, defaulting to 0.0), and an optional `topping_ids` array naming the toppings applied to this cup. The read-only `net_weight_oz` is the gross weight minus the tare and must be strictly greater than zero. Each named topping consumes one unit of its stock and contributes its `surcharge_cents` to the cup.

Adding a cup runs the guarded sequence from §2.7 in order. First, the **allergen guard**: if any applied topping carries an allergen tag that appears in the ticket's `excluded_allergens`, the cup is rejected with `ERR_ALLERGEN_CONFLICT`. Second, the **sanitation gate**: the flavor's parent machine is re-evaluated for overdue sanitation (potentially flipping it to `OUT_OF_SERVICE` and suspending its flavors per §3.1), and the machine must be `READY` to dispense — a machine that is `CLEANING` or `OUT_OF_SERVICE` yields `ERR_MACHINE_NOT_READY`. Third, **availability**: the flavor must be `LOADED`, and every referenced topping must be `AVAILABLE` with `on_hand_units` of at least 1, otherwise `ERR_TOPPING_UNAVAILABLE`. Fourth, **weight**: the computed `net_weight_oz` must be strictly greater than zero, otherwise `ERR_INVALID_WEIGHT`. Fifth, **mix sufficiency**: the requested `net_weight_oz` must not exceed the flavor's machine `current_mix_level_oz`, otherwise `ERR_INSUFFICIENT_MIX`. When all checks pass, the machine's `current_mix_level_oz` is reduced by `net_weight_oz`, each applied topping's `on_hand_units` is reduced by one, and the line's read-only `line_quoted_cents` is computed at the current clock (see §3.5).

### 3.5. Checkout, Pricing, and Provisional Loyalty

Checkout is performed by a `Cashier` and advances the ticket's `payment_status` from `OPEN` to `CHARGED`. It requires the ticket to be `OPEN` (otherwise `ERR_TICKET_NOT_OPEN`) and to carry at least one cup (otherwise `ERR_EMPTY_TICKET`). If a `loyalty_account_id` is attached, that account must be `ACTIVE`, or checkout fails with `ERR_LOYALTY_ACCOUNT_SUSPENDED`. The request may include a `voucher_id` to redeem; if supplied, the voucher must be `ISSUED` and the current clock must be strictly before its `expires_at`, otherwise the request fails with `ERR_VOUCHER_NOT_REDEEMABLE` (voucher not in `ISSUED` status) or `ERR_VOUCHER_EXPIRED` (redeemed at or after `expires_at`).

Pricing at checkout uses the **QUOTED** variant, expressed in integer cents with round-half-up at every named step. Each cup's `line_quoted_cents` is computed when the cup is added, as the net weight times the flavor's per-ounce price, scaled by the complement of the seasonal discount, rounded to whole cents, and then increased by the flat topping surcharges: that is, `line_quoted_cents` equals the net weight in ounces multiplied by `price_per_oz_cents` multiplied by (one minus the active discount fraction), rounded half up to a whole number of cents, plus the sum of the `surcharge_cents` of every topping on that cup. The QUOTED subtotal is the sum of `line_quoted_cents` across all of the ticket's cups. That subtotal is then floored at the minimum ticket charge of 100 cents — the charge before any voucher is the larger of 100 cents and the subtotal. Finally, if a voucher is redeemed, its fixed value (500 cents) is subtracted, and the result is again floored at 100 cents: `quoted_total_cents` is the larger of 100 cents and (the pre-voucher amount minus the redeemed voucher value). The final charged amount is stored as the ticket's read-only `quoted_total_cents`.

Checkout also accrues provisional loyalty. The ticket's `provisional_points` is the floor of `quoted_total_cents` divided by 100 — one point per whole hundred cents charged. When a loyalty account is attached, that account's `points_provisional` is increased by this same amount, reflecting points that are earned but not yet finalized. If a voucher was supplied and accepted, it transitions from `ISSUED` to `REDEEMED` and the ticket's `redeemed_voucher_id` is set to it. When all side effects are applied, the ticket's `payment_status` becomes `CHARGED`.

### 3.6. Voiding a Ticket

A charged ticket that has not yet been reconciled can be reversed by a `ShiftLead`, moving `payment_status` from `CHARGED` to the terminal `VOIDED`. The void requires the ticket to be `CHARGED` (otherwise `ERR_TICKET_NOT_CHARGED`) and its `reconciliation_status` to still be `UNRECONCILED` (otherwise `ERR_TICKET_ALREADY_RECONCILED`) — once a ticket has been swept into a closed day it can no longer be voided. A void unwinds the ticket's entire footprint: every topping consumed by the ticket's cups has its `on_hand_units` restored by the number of units it consumed; each source machine's `current_mix_level_oz` is restored by the total `net_weight_oz` its flavor dispensed on this ticket, capped so it never exceeds that machine's `mix_par_oz`; if a loyalty account is attached, its `points_provisional` is reduced by the ticket's `provisional_points`; and if a voucher had been redeemed, that voucher reverts from `REDEEMED` back to `ISSUED` (un-redeemed and reusable). The ticket then settles at `payment_status` of `VOIDED`.

### 3.7. Waste and Melt Logging

A `ShiftLead` records a **WasteEvent** whenever mix or toppings are lost to melt, spillage, expiry, or a machine fault — the `reason` is one of `MELT`, `SPILL`, `EXPIRY`, or `MACHINE_FAULT`. A WasteEvent is immutable (only `id` and `created_at`). Each event is exactly one of two kinds, disambiguated by which fields are present. **Mix waste** supplies the source `machine_id`, the `flavor_id` whose rates value it, and a `waste_weight_oz`; **topping waste** supplies the `topping_id` and a count of `waste_units`. Logging the event depletes the corresponding inventory: mix waste reduces that machine's `current_mix_level_oz` by `waste_weight_oz`, and topping waste reduces that topping's `on_hand_units` by `waste_units`.

Every waste event is valued two ways and stores both. For mix waste, the cost basis `cogs_value_cents` is the `waste_weight_oz` multiplied by the flavor's `cost_per_oz_cents`, rounded half up to whole cents, and the retail basis `retail_value_cents` is the `waste_weight_oz` multiplied by the flavor's `price_per_oz_cents`, rounded half up. For topping waste, `cogs_value_cents` is `waste_units` multiplied by the fixed per-unit topping cost of 12 cents, and `retail_value_cents` is `waste_units` multiplied by the topping's `surcharge_cents`. The two valuations deliberately measure the same loss against different bases and will generally differ. Waste events can be listed and filtered by `machine_id`, `flavor_id`, or `topping_id`.

### 3.8. Loyalty Accounts, Points, Punches, and Vouchers

A **LoyaltyAccount** is created by any counter role with a `member_name`, an optional `phone`, and an optional `initial_punch_count` that seeds the read-only `punch_count` (defaulting to 0, for migration and operational convenience). A new account is `ACTIVE` with `points_provisional` and `points_lifetime` both starting at 0. A `Manager` may move an account from `ACTIVE` to `SUSPENDED`; this requires the account to currently be `ACTIVE`, otherwise `ERR_LOYALTY_INVALID_STATE`. A suspended account cannot be attached at checkout (§3.5). The `points_provisional` field tracks points from charged-but-unreconciled tickets and is reversed on void; `points_lifetime` holds finalized points; and `punch_count` tracks reconciled-visit punches, modulo the punch threshold.

The finalized side of loyalty is driven entirely by reconciliation close (§3.11): each reconciled charged ticket that carries a `loyalty_account_id` posts exactly one visit. For that ticket, the account's `points_lifetime` is increased by the ticket's `final_points`, its `points_provisional` is decreased by that ticket's `provisional_points` (draining the earlier provisional accrual), and its `punch_count` is increased by one. Whenever `punch_count` reaches or exceeds the punch threshold of 10, the system issues one **RewardVoucher** and subtracts 10 from `punch_count` — so a single close that carries an account across the threshold both issues a voucher and leaves the remainder of the punches standing.

A RewardVoucher is created only by this cascade; it is read-only through the API. It records its owning `loyalty_account_id`, a fixed cash-off `value_cents` of 500, and an `expires_at` set to the issuing clock plus a time-to-live of 720 hours (thirty days). Its `status` begins `ISSUED`; redeeming it at checkout moves it to `REDEEMED`, an expired redemption attempt (at or after `expires_at`) is rejected as `ERR_VOUCHER_EXPIRED` and the voucher is treated as `EXPIRED`, and a void that reverses a redemption returns it to `ISSUED`. Vouchers can be listed and filtered by `loyalty_account_id` and `status`.

### 3.9. Catering and Party Orders

Party bookings run against a **CateringResource** — a bookable asset such as a portable cart — created by a `Manager` with a `name` and an optional `capacity` (maximum supported guests; 0 means unspecified). A catering resource's `status` is always `AVAILABLE`; it is bookable at any time subject only to the temporal-overlap rule below.

A **CateringOrder** is drafted by any counter role, referencing the booked `resource_id`, an optional host `loyalty_account_id`, an `event_start` (inclusive) and `event_end` (exclusive) that must satisfy end strictly after start (otherwise `ERR_INVALID_WINDOW`), an expected `guest_count`, and a `line_items` array. Each line item is an object with an integer `qty`, an integer `unit_price_cents`, and a fractional `discount_pct` between 0 and 1. A new order's `status` is `DRAFT`, and its `invoice_total_cents`, `required_deposit_cents`, and `deposit_paid_cents` are respectively `null`, `null`, and 0 until it is quoted.

The order moves through `DRAFT → QUOTED → CONFIRMED → FULFILLED`, and any of `DRAFT`, `QUOTED`, or `CONFIRMED` may instead be cancelled to `CANCELLED`; all four transitions are driven by a `Manager` except cancellation, which any counter role may perform. Quoting requires the order to be `DRAFT` (otherwise `ERR_CATERING_INVALID_STATE`) and computes the invoice: for each line item, `line_cents` is `qty` multiplied by `unit_price_cents` multiplied by (one minus that line's `discount_pct`), rounded half up to whole cents; `invoice_total_cents` is the sum of those per-line amounts — each line is rounded first and only then summed. The `required_deposit_cents` is 25 percent of `invoice_total_cents`, rounded half up. Confirming requires the order to be `QUOTED` (otherwise `ERR_CATERING_INVALID_STATE`); the confirming request supplies `deposit_paid_cents`, which is recorded on the order. Confirmation enforces two further rules: the interval `[event_start, event_end)` must not overlap any other `CONFIRMED` or `FULFILLED` order on the same `resource_id` — the window is half-open, so two bookings that merely touch at an endpoint do not conflict, but any true overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`; and the recorded `deposit_paid_cents` must be at least `required_deposit_cents`, otherwise the confirmation is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402). Fulfilling requires the order to be `CONFIRMED` (otherwise `ERR_CATERING_INVALID_STATE`). Cancelling requires the order to be in `DRAFT`, `QUOTED`, or `CONFIRMED` (otherwise `ERR_CATERING_INVALID_STATE`); cancelling a confirmed order frees its booking so the interval no longer blocks other confirmations. Orders can be listed and filtered by `resource_id`, `loyalty_account_id`, and `status`.

### 3.10. Maintenance Windows

A `ShiftLead` reserves a **MaintenanceWindow** on a machine by supplying the `machine_id`, a `window_start` (inclusive), a `window_end` (exclusive) that must be strictly after the start (otherwise `ERR_INVALID_WINDOW`), and the `expected_machine_version` for the optimistic-concurrency check of §2.9. A new window's `status` is `SCHEDULED`. Two guards apply at creation: the OCC guard, which rejects a stale `expected_machine_version` with `ERR_STALE_VERSION`; and a spacing guard, which requires the new window to sit at least `MAINTENANCE_BUFFER_MINUTES` (60 minutes) away from every already-`SCHEDULED` window on the same machine — the required separation is measured as the gap between the two windows' nearest edges, so a gap of exactly the buffer is permitted and only a strictly smaller gap (or any true time overlap of the two windows) is a violation — and rejects a violation with `ERR_MAINTENANCE_WINDOW_CONFLICT`. When both guards would reject the request, the spacing guard is evaluated before the OCC guard, so a request that is simultaneously conflicting and stale is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` rather than `ERR_STALE_VERSION`. A successful create stamps the machine's `next_maintenance_at` to the new `window_start` and increments the machine's `version` by one.

A `ShiftLead` may cancel a scheduled window, moving it from `SCHEDULED` to the terminal `CANCELLED`; this requires the window to be `SCHEDULED` (otherwise `ERR_WINDOW_INVALID_STATE`). A cancelled window no longer participates in the spacing checks that guard future window creation. Maintenance windows can be listed and filtered by `machine_id` and `status`.

### 3.11. Daily Reconciliation, Finalization, and Variance

A `Manager` opens a **DailyReconciliation** for a `business_date` label (in `YYYY-MM-DD` form). A new reconciliation's `status` is `OPEN`, and its `counted_cash_cents`, `expected_revenue_cents`, and `cash_variance_cents` are `null` while its `adjustments` list is empty. Closing the reconciliation moves it from `OPEN` to the terminal `CLOSED`; it requires the reconciliation to be `OPEN`, otherwise `ERR_RECONCILIATION_INVALID_STATE`. The close carries a `counted_cash_cents` figure — the physically counted drawer — and performs the day's settlement as one transaction.

The close first **sweeps** tickets: every `SaleTicket` that is `CHARGED` and still `UNRECONCILED` advances on its reconciliation axis to `RECONCILED` (voided tickets are skipped entirely). For each swept ticket the system computes `final_total_cents` under the **FINALIZED** pricing variant, sets the ticket's `reconciliation_id` to this reconciliation, and computes the ticket's `final_points` as the floor of `final_total_cents` divided by 100. The FINALIZED variant differs from the QUOTED one of §3.5 in when the seasonal discount lands: for each cup, a `line_base` is the net weight times `price_per_oz_cents` rounded half up to whole cents, plus that cup's topping surcharges — with **no** discount applied per line; those `line_base` values are summed into `subtotal_base`; the seasonal discount active at the close is then applied **once** to that summed base, as `subtotal_base` multiplied by (one minus the discount fraction), rounded half up; that discounted figure is floored at the 100-cent minimum; and finally, if the ticket redeemed a voucher, the 500-cent voucher value is subtracted and the result floored again at 100 cents to yield `final_total_cents`. Because QUOTED rounds each discounted line before summing while FINALIZED discounts the summed base once, the two totals can legitimately differ by rounding granularity.

Through the sweep, each swept ticket that carries a `loyalty_account_id` finalizes loyalty exactly as described in §3.8: the account's `points_lifetime` rises by the ticket's `final_points`, its `points_provisional` falls by the ticket's `provisional_points`, its `punch_count` rises by one, and a crossing of the punch threshold of 10 issues a RewardVoucher and subtracts 10.

After the sweep, the reconciliation computes its totals. The `expected_revenue_cents` is the sum of `final_total_cents` over exactly the tickets whose `reconciliation_id` equals this reconciliation, plus the sum of the `amount_cents` of every posted adjustment. The `cash_variance_cents` is the `counted_cash_cents` minus `expected_revenue_cents`. The reconciliation's `status` then becomes `CLOSED`.

Even after settlement, a `Manager` may post a manual cash **adjustment** to a reconciliation, supplying an `amount_cents`, a free-text `reason`, and the `expected_daily_reconciliation_version` for the OCC check of §2.9. The post performs no reconciliation status-eligibility check (only the OCC check), so an adjustment may be recorded whether the reconciliation is still `OPEN` or already `CLOSED`. Each posted adjustment is appended to the `adjustments` array (each entry an `amount_cents`/`reason` pair), increments the reconciliation's `version` by one, and re-derives `expected_revenue_cents` and `cash_variance_cents` from the same formulas — adjustments taken in `created_at` ascending order — so the running totals always reflect every adjustment on record.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or append a new record to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock capability — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Cashier, ShiftLead, Manager |
| POST | `/machines` | Create a soft-serve machine | Manager |
| GET | `/machines` | List machines | Cashier, ShiftLead, Manager |
| GET | `/machines/{id}` | Get a machine | Cashier, ShiftLead, Manager |
| POST | `/machines/{id}/start-cleaning` | Begin a cleaning cycle | ShiftLead, Manager |
| POST | `/machines/{id}/complete-cleaning` | Finish cleaning; log sanitation; restore suspended flavors | ShiftLead, Manager |
| POST | `/machines/{id}/refill-mix` | Top up mix level | ShiftLead, Manager |
| POST | `/machines/{id}/check-sanitation` | Evaluate the sanitation cadence now | ShiftLead, Manager |
| POST | `/flavors` | Load a flavor mix onto a machine | ShiftLead, Manager |
| GET | `/flavors` | List flavors | Cashier, ShiftLead, Manager |
| GET | `/flavors/{id}` | Get a flavor | Cashier, ShiftLead, Manager |
| POST | `/flavors/{id}/rotate-out` | Rotate a flavor off the menu | ShiftLead, Manager |
| POST | `/toppings` | Create a topping inventory item | ShiftLead, Manager |
| GET | `/toppings` | List toppings | Cashier, ShiftLead, Manager |
| GET | `/toppings/{id}` | Get a topping | Cashier, ShiftLead, Manager |
| POST | `/toppings/{id}/restock` | Increase on-hand servings | ShiftLead, Manager |
| POST | `/toppings/{id}/rotate-out` | Rotate a topping off the bar | ShiftLead, Manager |
| POST | `/seasonal-promotions` | Create a seasonal promotion window | Manager |
| GET | `/seasonal-promotions` | List seasonal promotions | Cashier, ShiftLead, Manager |
| POST | `/loyalty-accounts` | Create a loyalty account | Cashier, ShiftLead, Manager |
| GET | `/loyalty-accounts` | List loyalty accounts | Cashier, ShiftLead, Manager |
| GET | `/loyalty-accounts/{id}` | Get a loyalty account | Cashier, ShiftLead, Manager |
| POST | `/loyalty-accounts/{id}/suspend` | Suspend a loyalty account | Manager |
| GET | `/reward-vouchers` | List reward vouchers | Cashier, ShiftLead, Manager |
| GET | `/reward-vouchers/{id}` | Get a reward voucher | Cashier, ShiftLead, Manager |
| POST | `/sale-tickets` | Open a new POS ticket | Cashier, ShiftLead, Manager |
| GET | `/sale-tickets` | List tickets | Cashier, ShiftLead, Manager |
| GET | `/sale-tickets/{id}` | Get a ticket | Cashier, ShiftLead, Manager |
| POST | `/sale-tickets/{id}/lines` | Weigh and add a cup to the ticket | Cashier, ShiftLead, Manager |
| GET | `/sale-tickets/{id}/lines` | List cups on a ticket | Cashier, ShiftLead, Manager |
| POST | `/sale-tickets/{id}/checkout` | Charge the ticket | Cashier, ShiftLead, Manager |
| POST | `/sale-tickets/{id}/void` | Void a charged, unreconciled ticket | ShiftLead, Manager |
| GET | `/sale-lines` | List sale lines | Cashier, ShiftLead, Manager |
| GET | `/sale-lines/{id}` | Get a sale line | Cashier, ShiftLead, Manager |
| POST | `/waste-events` | Log a melt/waste event | ShiftLead, Manager |
| GET | `/waste-events` | List waste events | ShiftLead, Manager |
| GET | `/waste-events/{id}` | Get a waste event | ShiftLead, Manager |
| GET | `/sanitation-logs` | List sanitation log entries | ShiftLead, Manager |
| GET | `/sanitation-logs/{id}` | Get a sanitation log entry | ShiftLead, Manager |
| POST | `/maintenance-windows` | Schedule a maintenance window (OCC on Machine) | ShiftLead, Manager |
| GET | `/maintenance-windows` | List maintenance windows | ShiftLead, Manager |
| GET | `/maintenance-windows/{id}` | Get a maintenance window | ShiftLead, Manager |
| POST | `/maintenance-windows/{id}/cancel` | Cancel a scheduled window | ShiftLead, Manager |
| POST | `/catering-resources` | Create a bookable catering resource | Manager |
| GET | `/catering-resources` | List catering resources | Cashier, ShiftLead, Manager |
| POST | `/catering-orders` | Create a catering/party order draft | Cashier, ShiftLead, Manager |
| GET | `/catering-orders` | List catering orders | Cashier, ShiftLead, Manager |
| GET | `/catering-orders/{id}` | Get a catering order | Cashier, ShiftLead, Manager |
| POST | `/catering-orders/{id}/quote` | Quote the order | Manager |
| POST | `/catering-orders/{id}/confirm` | Confirm the order | Manager |
| POST | `/catering-orders/{id}/fulfill` | Fulfill the order | Manager |
| POST | `/catering-orders/{id}/cancel` | Cancel a non-terminal order | Cashier, ShiftLead, Manager |
| POST | `/daily-reconciliations` | Open a reconciliation for a business date | Manager |
| GET | `/daily-reconciliations` | List reconciliations | Manager |
| GET | `/daily-reconciliations/{id}` | Get a reconciliation | Manager |
| POST | `/daily-reconciliations/{id}/close` | Close the reconciliation | Manager |
| POST | `/daily-reconciliations/{id}/adjustments` | Post a manual cash adjustment (OCC on DailyReconciliation) | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MACHINE_NOT_FOUND` | 404 |
| `ERR_FLAVOR_NOT_FOUND` | 404 |
| `ERR_TOPPING_NOT_FOUND` | 404 |
| `ERR_PROMOTION_NOT_FOUND` | 404 |
| `ERR_LOYALTY_NOT_FOUND` | 404 |
| `ERR_VOUCHER_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_WASTE_NOT_FOUND` | 404 |
| `ERR_WINDOW_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_CATERING_NOT_FOUND` | 404 |
| `ERR_RECONCILIATION_NOT_FOUND` | 404 |
| `ERR_SANITATION_LOG_NOT_FOUND` | 404 |
| `ERR_MACHINE_INVALID_STATE` | 409 |
| `ERR_FLAVOR_INVALID_STATE` | 409 |
| `ERR_TOPPING_INVALID_STATE` | 409 |
| `ERR_LOYALTY_INVALID_STATE` | 409 |
| `ERR_TICKET_NOT_OPEN` | 409 |
| `ERR_TICKET_NOT_CHARGED` | 409 |
| `ERR_TICKET_ALREADY_RECONCILED` | 409 |
| `ERR_EMPTY_TICKET` | 409 |
| `ERR_CATERING_INVALID_STATE` | 409 |
| `ERR_WINDOW_INVALID_STATE` | 409 |
| `ERR_RECONCILIATION_INVALID_STATE` | 409 |
| `ERR_LOYALTY_ACCOUNT_SUSPENDED` | 409 |
| `ERR_VOUCHER_NOT_REDEEMABLE` | 409 |
| `ERR_VOUCHER_EXPIRED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 409 |
| `ERR_MACHINE_NOT_READY` | 409 |
| `ERR_TOPPING_UNAVAILABLE` | 409 |
| `ERR_INVALID_WEIGHT` | 400 |
| `ERR_RESOURCE_DOUBLE_BOOKED` | 409 |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |
| `ERR_INSUFFICIENT_MIX` | 402 |
| `ERR_STALE_VERSION` | 412 |

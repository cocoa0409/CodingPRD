# Campground & RV Park Reservation API — Product Requirements Document

## 1. Introduction

Privately operated campgrounds and RV parks juggle a deceptively intricate booking problem: a single physical site may be sold by the night, by the week, or by the month; its price shifts with the season; and the same plot of ground must be protected from double-booking, maintenance closures, and the cleaning gap between one guest leaving and the next arriving. This API gives an operator the tooling to model that reality precisely — parks with their own timezones and house rules, rate plans per site type, seasonal surcharge windows, cancellation tiers, and individual sites with hookup levels and stay caps — while giving guests a self-service path to lock a site, pay a deposit, confirm, add amenities, and ultimately check in and out.

The system is built around two ideas that recur throughout this document. The first is that a reservation carries **two independent status dimensions** at once — where it sits in its booking lifecycle, and how much of its money has been collected — and these advance on their own schedules. The second is that money is never guessed: the provisional charge a guest sees at booking is recomputed at confirmation and reconciled to a final figure at checkout, with a tiered pricing engine that automatically chooses the cheapest of nightly, weekly, and monthly decompositions. Because operators and guests act on the same sites concurrently, the API also leans on optimistic concurrency control to keep a stale client from quietly overwriting a window it never actually saw.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. All resources are mounted directly beneath the root path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly two roles, spelled precisely as `Operator` and `Guest`.

When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may accept and record it but never compares it to any entity's `id`; an operator is trusted to administer any park, site, rate, season, policy, maintenance hold, and to perform check-in, check-out, and clock control. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest` entity. Ownership checks on any resource that references a `Guest` compare the resource's guest foreign key to `X-User-ID`: a guest acting on a reservation, an add-on, or a payment must own the underlying reservation — that is, the reservation's `guest_id` must equal `X-User-ID`. An attempt to act outside one's permitted role, or a guest reaching for a reservation it does not own, is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses surface the pagination state inside the envelope's `meta` object through the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system — parks, rate plans, seasons, cancellation policies, sites, maintenance holds, guests, reservations, and add-ons — carry a standard set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix that serves purely as identity. Each has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording first creation. Each has an `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, **including mutations that occur as a side effect of a cascade rather than a direct write to that resource**. And each has a `version`, an integer that starts at 1 on creation and increases by one on every mutation.

The lone exception is the `Payment` resource. A payment is an append-only ledger entry and is therefore immutable after creation: it carries only an `id` and a `created_at` (an ISO 8601 UTC timestamp with three fractional digits, which also serves as the chronological replay key for the ledger). A payment has no `updated_at` and no `version` field at all.

### 2.5. Monetary Precision and Rounding

All money in this system is held and returned as integer cents — there are no fractional cents and no floating-point currency. Wherever a calculation must convert a percentage or fraction into a cent figure, the result is rounded to the nearest whole cent using the **round half up** rule (a value exactly halfway between two cents rounds upward). The tiered stay charge and the booked-night aggregation rely only on integer arithmetic and whole-night floor division, so they require no rounding. Rounding therefore appears only where this document names it explicitly: the per-night season surcharge, the lodging tax line, the loyalty discount, and the percentage-based cancellation refund.

### 2.6. Optimistic Concurrency Control on Sites

Several site-targeted writes accept an `expected_site_version` field that the client must populate with the `version` of the site it last observed. This guards the operations that mutate a site's standing: creating a reservation against a site, putting a site into maintenance, reactivating it, retiring it, and placing a maintenance hold on it. Because a reservation legitimately locks nights on a site and therefore bumps the site's `version`, and because maintenance changes bump it too, a client whose view of the site has gone stale would otherwise risk double-locking a window it never actually saw.

Specifically, when a reservation is created against a site, the request must carry `expected_site_version` matching that site's current `version`. If another writer has advanced the site's `version` since the client last read it, the create is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412) before any locking takes place. This same `expected_site_version` field is required on the maintenance, reactivate, retire, and maintenance-hold operations, and a mismatch there is likewise rejected with `ERR_STALE_SITE_VERSION`. The park-update operation carries an analogous `expected_park_version`. Operations that do not target a site by version — confirm, check-in, check-out, cancel, add-on add/remove, payment recording, and all reads — do not take a version field.

### 2.7. Cascades, Reconciliation, and Hierarchical Consistency

A number of operations mutate more than one resource at once. When this happens, every affected resource has its `updated_at` refreshed and its `version` incremented, exactly as for a direct write. Retiring a site cancels its live reservations, which in turn create refund payments and recompute guest totals; checking a guest out reconciles the reservation's charges, may auto-record a balance payment, and rolls the guest's lifetime figures forward; cancelling a reservation releases its locked nights back to the site and may issue a refund. The specific mechanics of each cascade live with the workflow that triggers it in §3. The governing principle here is that the system performs these reconciliations automatically and immediately, without requiring a separate client request against each downstream resource, and that no derived count or balance is ever left drifting from the truth its inputs imply.

### 2.8. Nested Resource Retrieval and Validation Ordering

Many paths name more than one resource — a season under a park, a reservation under a site, an add-on under a reservation. For any such request the system validates existence **left to right** along the path: the park first, then the site or rate plan, then the reservation, then the add-on or payment. The first identifier in the path that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404), before any deeper resource is consulted and before any business rule is evaluated.

More broadly, the system evaluates every request against an ordered chain of checks, and the order is itself a contract because an earlier check masks any later one it precludes. Authentication comes first: if the headers are absent or malformed the answer is `ERR_UNAUTHENTICATED` (401). Authorization comes second: a role that may not perform the operation, or a guest reaching for a reservation it does not own, yields `ERR_FORBIDDEN` (403). Existence comes third, as just described, yielding `ERR_NOT_FOUND` (404). Request well-formedness comes fourth — required fields present, enum values legal, dates parseable, `check_out_date` strictly later than `check_in_date`, and all amounts non-negative — with any violation yielding `ERR_INVALID_REQUEST` (422). Only after these four foundational checks pass does the system reach the site optimistic-concurrency check (`ERR_STALE_SITE_VERSION`, 412), then the state-transition legality check (`ERR_INVALID_STATE`, 409), and then the domain-specific business rules described in §3, which are evaluated in the priority order set out there.

## 3. Business Logic & Workflows

### 3.1. Parks and Their Operating Configuration

The top of the hierarchy is the **Park**, created by an operator with a `name`. A park also carries operating configuration that defaults sensibly when omitted: a `timezone` (an IANA name such as `America/Denver`, defaulting to `America/Denver`); a `check_in_time` and `check_out_time` as local `HH:MM` strings (defaulting to `15:00` and `11:00`); and `quiet_hours_start` and `quiet_hours_end`, also local `HH:MM` strings (defaulting to `22:00` and `07:00`). Three numeric policy levers round out the configuration. `deposit_pct` is the fraction of the total charge collected as a deposit at confirmation time and defaults to 0.30; `tax_rate` is the lodging tax rate applied to the taxable base and defaults to 0.08; and `long_stay_nights_threshold` is the number of nights at or above which a stay is classified as long-term, defaulting to 28.

An operator may later revise a park's `check_in_time`, `check_out_time`, `quiet_hours_start`, `quiet_hours_end`, `deposit_pct`, `tax_rate`, and `long_stay_nights_threshold`. Such an update must carry `expected_park_version`; the park's `version` advances and `updated_at` refreshes. Whenever a park is created or updated, its configuration is range-checked: `deposit_pct` and `tax_rate` must each lie within the inclusive range from 0 to 1, and `full_refund_min_days` must be greater than or equal to `half_refund_min_days`, which must itself be at least 0. A park or policy whose configuration falls outside these ranges is rejected with `ERR_VALIDATION_FAILED` (422); this same range guard governs cancellation-policy creation.

### 3.2. Rate Plans, Seasons, and Cancellation Policies

Pricing inputs hang off the park as separate configuration resources, all authored by an operator. A **Rate Plan** prices a single `site_type` — one of `TENT`, `RV`, or `CABIN` — and records a `nightly_rate_cents`, a `weekly_rate_cents` (the flat price of a seven-night block), and a `monthly_rate_cents` (the flat price of a twenty-eight-night block). Each rate plan also exposes the `park_id` it belongs to. Rate plans can be listed for a park and optionally filtered by `site_type`, or fetched individually.

A **Season** marks a date window during which nightly pricing is surcharged. It is created with a `name` (a label such as `PEAK_SUMMER`), an inclusive `start_date` and inclusive `end_date` as `YYYY-MM-DD` strings, and a `surcharge_pct` expressed as a percent (for example, 12.5 means twelve and a half percent). Each season records its `park_id`. Seasons on a single park may never overlap: when a new season's closed date interval would intersect any existing season on that park, the creation is rejected with `ERR_SEASON_OVERLAP` (409). This non-overlap rule guarantees that any given calendar date is covered by at most one season, which the pricing engine in §3.6 relies upon.

A **Cancellation Policy** defines the park's refund tiers through two day thresholds, each recording its `park_id`. The `full_refund_min_days` is the number of whole days before check-in at or above which a cancellation earns a full deposit refund. The `half_refund_min_days` is the lower threshold: a cancellation made at or after this many days before check-in, but fewer than `full_refund_min_days`, earns a fifty-percent refund, and a cancellation closer in than `half_refund_min_days` earns nothing. As noted in §3.1, `full_refund_min_days` must be at least `half_refund_min_days`, which must be at least 0, or the policy is rejected with `ERR_VALIDATION_FAILED`.

### 3.3. Sites and Their Lifecycle

A **Site** is a single bookable plot within a park. An operator creates it with the `park_id` context, a `rate_plan_id` naming the rate plan that prices it, a human `label` such as `A-12`, a `site_type`, a `hookup_level` of `NONE`, `PARTIAL`, or `FULL` (covering water, electric, and sewer service), and a `max_length_of_stay_nights` hard cap. An optional `turnover_buffer_days` records how many days of cleaning and turnover buffer a maintenance hold reserves on each side of its window; it defaults to 1. At creation the rate plan and the site must agree: the named rate plan's `site_type` must equal the site's own `site_type`, and a mismatch is rejected with `ERR_RATE_PLAN_TYPE_MISMATCH` (422). A new site begins with `status` of `ACTIVE`, a `booked_night_count` of 0, and `version` 1. Sites can be fetched individually, listed and filtered globally (by `park_id`, `rate_plan_id`, `site_type`, or `status`), or listed within a single park (optionally filtered by `status`).

A site's `status` follows a cyclic lifecycle with a terminal branch. From `ACTIVE` an operator may move it to `MAINTENANCE`; this transition is permitted only while the site is `ACTIVE`, and it bumps the site's `version`. While in `MAINTENANCE` the site blocks new reservation locks and check-ins. From `MAINTENANCE` an operator may return it to `ACTIVE` (permitted only while it is `MAINTENANCE`), again bumping `version`. From either `ACTIVE` or `MAINTENANCE` an operator may retire the site, moving it to the terminal `RETIRED` state. Attempting any of these transitions from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (409).

Retirement triggers a three-level cascade, processed against the site's reservations in ascending `created_at` order. First, every reservation on the site whose `reservation_status` is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` is moved to `CANCELLED`. Second, each such cancelled reservation that had a positive `amount_paid_cents` receives a `REFUND` payment for the full `amount_paid_cents` and has its `payment_status` set to `REFUNDED`, with the payment's `reason` recorded as `SITE_RETIRED`. Third, each affected guest's `lifetime_spend_cents` and `completed_stays_count` are recomputed — these figures are unchanged in practice, since cancelled stays were never counted, but the recompute fires regardless. Finally the site's `booked_night_count` is reset to 0 and its `version` is incremented.

### 3.4. Maintenance Holds

Independently of the site's own status, an operator may block a date window on a site for cleaning or repair by creating a **Maintenance Hold**. It is created against a `site_id` with an inclusive `start_date` and inclusive `end_date` as `YYYY-MM-DD` strings and an optional free-text `reason`. The hold begins with `status` `ACTIVE` and `version` 1, and placing it bumps the host site's `version`; because this is a site-guarded write it requires `expected_site_version`. An active hold does not merely block its own dates — it blocks a buffered window that extends `turnover_buffer_days` on each side, using the host site's `turnover_buffer_days`. Maintenance holds on a site can be listed (optionally filtered by `status`).

A hold's `status` lifecycle is simple: from `ACTIVE` an operator may clear it, moving it to the terminal `CLEARED` state, which is permitted only while it is `ACTIVE` and which bumps the host site's `version`. A cleared hold no longer blocks reservations on the site. An attempt to clear a hold that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

### 3.5. Guests and the Reservation Lifecycle

A **Guest** registers with a unique `email` and a `full_name`; registration may be performed by an operator or by the guest. A new guest starts with `completed_stays_count` 0, `lifetime_spend_cents` 0, and `version` 1. The `completed_stays_count` tracks how many of the guest's reservations have reached `CHECKED_OUT`, and `lifetime_spend_cents` accumulates the final `total_due_cents` across those checked-out reservations. A guest can be fetched, and its own reservations listed (optionally filtered by `reservation_status`).

A guest locks a site by creating a **Reservation**, supplying the `guest_id` (which must equal `X-User-ID`), a `check_in_date` and a `check_out_date` as `YYYY-MM-DD` strings, and `expected_site_version`. The arrival date is the inclusive interval start; the departure date is the exclusive interval end, so the whole-night count `nights` is the number of days from `check_in_date` up to but not including `check_out_date`. A reservation also derives a `stay_class` of `SHORT_TERM` or `LONG_TERM`: it is `LONG_TERM` precisely when `nights` is at least the park's `long_stay_nights_threshold`, and `SHORT_TERM` otherwise. The reservation records its `site_id`, and at creation begins life with `reservation_status` `REQUESTED` and `payment_status` `UNPAID`. Creation computes the provisional charges described in §3.6 and increases the site's `booked_night_count` by `nights`, bumping the site's `version`. Reservations expose, in addition to the fields already named, an `actual_check_out_date` (null until checkout) and a `priced_nights` figure, plus the computed money fields `stay_charge_cents`, `season_surcharge_cents`, `addon_total_cents`, `discount_cents`, `tax_cents`, `total_due_cents`, `deposit_due_cents`, `amount_paid_cents`, and `balance_cents`. Reservations can be fetched, and listed under a site (optionally filtered by `reservation_status`).

Creation enforces a battery of guards, and the order in which they fire is fixed. After the universal authentication, authorization, existence, and well-formedness checks of §2.8, the site optimistic-concurrency check runs (`ERR_STALE_SITE_VERSION`, 412). Then the stay-length cap is enforced: `nights` must not exceed the site's `max_length_of_stay_nights`, where a stay whose `nights` exactly equals the cap is allowed and one night longer is rejected with `ERR_MAX_STAY_EXCEEDED` (422). Then site availability is checked: the site must be neither `RETIRED` nor `MAINTENANCE`, or the request is rejected with `ERR_SITE_UNAVAILABLE` (409). Then the maintenance-buffer check runs: the requested half-open interval from `check_in_date` up to `check_out_date` must not overlap the buffered window of any `ACTIVE` maintenance hold on the site, where the buffered window runs as a closed interval from the hold's `start_date` minus `turnover_buffer_days` through the hold's `end_date` plus `turnover_buffer_days`; an overlap is rejected with `ERR_MAINTENANCE_CONFLICT` (409). Finally the date-overlap check runs: the requested half-open interval must not overlap that of any other reservation on the site whose `reservation_status` is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`. Because the interval is half-open, a back-to-back booking where one reservation's `check_out_date` equals the next reservation's `check_in_date` is allowed; a genuine overlap is rejected with `ERR_DATE_OVERLAP` (409).

The booking lifecycle then advances through the `reservation_status` dimension. A guest confirms a `REQUESTED` reservation, moving it to `CONFIRMED`. Confirmation is permitted only when the reservation is `REQUESTED`, when its deposit has already been collected (its `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL`), and when the host site is `ACTIVE`; it also re-runs the maintenance-buffer and date-overlap checks above. Confirmation freezes the loyalty discount from the acting guest's spend tier onto `discount_cents`, recomputes `total_due_cents` and `deposit_due_cents`, and bumps both the site's `version` and the reservation's `version`. An operator checks a guest in, moving a `CONFIRMED` reservation to `CHECKED_IN`; this requires the reservation to be `CONFIRMED`, its `payment_status` to be `DEPOSIT_PAID` or `PAID_IN_FULL`, the site to be `ACTIVE`, and the current clock date to be at or after the `check_in_date`. Check-in bumps the reservation's `version`. An operator later checks the guest out, moving a `CHECKED_IN` reservation to the terminal `CHECKED_OUT` state, permitted only when the reservation is `CHECKED_IN`; the checkout reconciliation is detailed in §3.7. A guest (or the system, during a site retirement) may cancel a reservation that is `REQUESTED` or `CONFIRMED`, moving it to the terminal `CANCELLED` state; cancellation mechanics are detailed in §3.8. Any of these transitions attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`. Whenever a reservation is created, confirmed, cancelled, or checked out, and whenever the site is retired or put into maintenance, the site's `booked_night_count` is recomputed as the sum of `nights` across the reservations on that site whose `reservation_status` is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`; cancelled and checked-out reservations are excluded, and the count is an integer that is never negative.

### 3.6. Pricing: Tiered Stay Charge, Season Surcharge, Discount, and Tax

The money on a reservation is assembled in a strictly pinned order, and the dependency between discount and tax means the order cannot be rearranged. The figure is computed provisionally at creation, re-frozen at confirmation, recomputed whenever an add-on is added or removed, and reconciled finally at checkout.

The foundation is the **tiered stay charge**, `stay_charge_cents`, computed over a number of priced nights `N` using the rate plan for the site's `site_type`. The engine forms three candidate prices and takes the cheapest. The nightly candidate is `N` multiplied by `nightly_rate_cents`. The weekly candidate decomposes `N` into whole seven-night blocks plus a remainder: the number of whole weeks (the integer quotient of `N` divided by 7) priced at `weekly_rate_cents`, plus the leftover nights (the remainder of `N` divided by 7) priced at `nightly_rate_cents`. The monthly candidate decomposes `N` against twenty-eight-night blocks: the number of whole months (the integer quotient of `N` divided by 28) priced at `monthly_rate_cents`, plus, from the nights remaining after the whole months, the number of whole weeks (the integer quotient of that remainder divided by 7) priced at `weekly_rate_cents`, plus the final leftover nights (the remainder of that remainder divided by 7) priced at `nightly_rate_cents`. The stay charge is the minimum of the nightly, weekly, and monthly candidates. All three candidates are pure integer-cent arithmetic with whole-night floor division, so no rounding is involved. Here a week is 7 nights and a month is 28 nights.

The number of priced nights, `priced_nights`, is the lever that distinguishes the provisional and final variants. While the reservation has not yet reached `CHECKED_OUT`, the stay charge is computed provisionally over the full requested night count — the difference between `check_out_date` and `check_in_date` — and is recomputed on confirmation and on any add-on or discount change. At `CHECKED_OUT` the stay charge is recomputed finally over `priced_nights` equal to the larger of 1 and the actual number of nights stayed, which lets an early departure both reduce the night count and re-select the cheapest tier (see §3.7 for how the final result is floored).

Layered on top is the **season surcharge**, `season_surcharge_cents`. For each individual night date in the priced window — that is, each date from `check_in_date` for `priced_nights` consecutive nights — the engine checks whether any season on the park covers that date (a season covers date `d` when the season's `start_date` is on or before `d` and its `end_date` is on or after `d`). If a season covers the night, that night's surcharge is the nightly rate multiplied by the season's `surcharge_pct` divided by 100, rounded half up to whole cents; if no season covers it, that night contributes 0. The rounding order is pinned and load-bearing: each night's surcharge is rounded to whole cents first, and only then are the per-night surcharges summed. Summing the raw products and rounding once at the end would produce a different total and is incorrect. Because seasons never overlap (§3.2), at most one season covers any night.

The **loyalty discount**, `discount_cents`, is frozen onto the reservation at confirmation, keyed on the acting guest's `lifetime_spend_cents` as of that moment — not on the subtotal. A guest whose `lifetime_spend_cents` is at least 500000 cents earns a discount of 10 percent; a guest at or above 200000 cents (but below 500000) earns 5 percent; below 200000 cents the discount is 0 percent. The discount amount is the pre-discount subtotal multiplied by that percent divided by 100, rounded half up to whole cents. This system deliberately uses the **lifetime** spend tier — cumulative spend over all of the guest's `CHECKED_OUT` stays — so that a guest who spent heavily long ago retains their tier; it does not use any trailing-window interpretation that would let old spend age out and drop the guest to a lower tier.

These pieces combine into `total_due_cents` in a pinned nine-step order. First take `stay_charge_cents`; second `season_surcharge_cents`; third `addon_total_cents`, the sum of `amount_cents` across the reservation's add-ons whose `status` is `ACTIVE`. Fourth, form the pre-discount subtotal as the sum of those three. Fifth, determine `discount_cents` as above (keyed on guest tier, not the subtotal). Sixth, form the discounted subtotal as the larger of 0 and the pre-discount subtotal minus the discount. Seventh, form the taxable base as `stay_charge_cents` plus `season_surcharge_cents` plus the sum of `amount_cents` across `ACTIVE` add-ons whose `taxable` flag is true, minus `discount_cents` — the discount reduces the taxable base, and the taxable base is floored at 0. Eighth, the lodging tax `tax_cents` is the larger of 0 and the taxable base, multiplied by the park's `tax_rate`, rounded half up to whole cents. Ninth, `total_due_cents` is the discounted subtotal plus `tax_cents`. Rounding to whole cents via round half up is applied on the tax line; every other line is already integer cents. Finally `deposit_due_cents` is `total_due_cents` multiplied by the park's `deposit_pct`, rounded half up to whole cents, and frozen at confirmation time.

### 3.7. Payments, Settlement, and Checkout Reconciliation

A reservation's money is paid down through an append-only **Payment** ledger, with each entry created by the owning guest (or by the system) carrying a `type` of `DEPOSIT`, `BALANCE`, or `REFUND`, a positive `amount_cents`, and an optional free-text `reason` (defaulting to null, used for system-generated entries such as `CANCELLATION_REFUND` or `SITE_RETIRED`). Each payment records its `reservation_id`. Deposit and balance payments add to the amount paid; refund payments subtract from it. Accordingly `amount_paid_cents` is the sum of `DEPOSIT` and `BALANCE` payment amounts minus the `REFUND` amounts on the reservation, and `balance_cents` is `total_due_cents` minus `amount_paid_cents`.

The `payment_status` dimension advances independently of the booking lifecycle. It begins `UNPAID`. A guest records a deposit, moving an `UNPAID` reservation to `DEPOSIT_PAID`; this is permitted only while `payment_status` is `UNPAID`, and the deposit's `amount_cents` must equal the reservation's `deposit_due_cents`. From `DEPOSIT_PAID` or `UNPAID`, a balance payment (or the system's checkout settlement) moves the reservation to `PAID_IN_FULL`, permitted once the resulting `amount_paid_cents` is at least `total_due_cents`. From `DEPOSIT_PAID` or `PAID_IN_FULL`, a system refund — created by a cancellation or a site-retirement compensation — moves the reservation to `REFUNDED`. Each of these recomputes `amount_paid_cents` and `balance_cents` and bumps the reservation's `version`.

Payment recording is guarded. A `DEPOSIT` payment whose `amount_cents` does not equal `deposit_due_cents`, or a `BALANCE` payment whose amount would exceed the outstanding balance, is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (422). A payment attempted against a reservation that is already `PAID_IN_FULL` or `REFUNDED` is rejected with `ERR_PAYMENT_ALREADY_SETTLED` (409). When the `amount_paid_cents` and `balance_cents` are reported, they are derived by replaying the ledger in chronological `created_at` order.

Checkout is the reconciliation moment. When an operator checks out a `CHECKED_IN` reservation, the system sets `actual_check_out_date` to the earlier of the booked `check_out_date` and the current clock date, and sets `priced_nights` to the larger of 1 and the actual nights stayed. It then re-runs the final stay charge over those `priced_nights` and reassembles `total_due_cents` per §3.6; because an early checkout can only lower the night count, the reconciled `total_due_cents` is floored at `deposit_due_cents` — the deposit is never refunded for an early departure. If the resulting `balance_cents` is greater than 0, the system auto-records a `BALANCE` payment for exactly that remaining balance and sets `payment_status` to `PAID_IN_FULL`. The guest's `completed_stays_count` is then increased by 1 and `lifetime_spend_cents` increased by the final `total_due_cents`. The site's `booked_night_count` is recomputed, and the site's `version`, the guest's record, and the reservation's `version` are all advanced.

### 3.8. Cancellation and Refund Tiers

A guest may cancel their own `REQUESTED` or `CONFIRMED` reservation, and the system performs the same cancellation as a compensation step when a site is retired. Cancellation has two compensating legs. The booked-nights leg releases the locked window: the site's `booked_night_count` drops by the reservation's `nights` (in practice via the same recompute that excludes cancelled reservations) and the site's `version` is bumped. The money leg computes a refund.

The refund is tiered on how far ahead of check-in the cancellation falls. First compute `days_before` as the whole number of days from the current clock date to the `check_in_date`. If the reservation's `stay_class` is `LONG_TERM`, the refund is 0 — long-term deposits are non-refundable. Otherwise, if `days_before` is at least the policy's `full_refund_min_days`, the refund is the full `amount_paid_cents` (100 percent); else if `days_before` is at least `half_refund_min_days`, the refund is `amount_paid_cents` multiplied by 0.50, rounded half up to whole cents (50 percent); otherwise the refund is 0. The day thresholds use an at-or-above comparison on `days_before`. When the computed refund is greater than 0, the system creates a `REFUND` payment for that amount and sets `payment_status` to `REFUNDED`. The reservation's `version` is bumped.

### 3.9. Amenity Add-Ons

A guest enriches their own reservation with an **Add-On** — an amenity charge of `kind` `FIREWOOD`, `EXTRA_VEHICLE`, `PET_FEE`, or `EARLY_CHECKIN`, with an `amount_cents` charge and a `taxable` flag indicating whether it joins the taxable base (defaulting to true). Each add-on records its `reservation_id`, begins with `status` `ACTIVE` and `version` 1, and adding it recomputes the parent reservation's `addon_total_cents`, `tax_cents`, and `total_due_cents` and bumps the reservation's `version`. Add-ons on a reservation can be listed (optionally filtered by `status`).

An add-on's lifecycle moves from `ACTIVE` to the terminal `REMOVED` state when the owning guest removes it; this is permitted only while the add-on is `ACTIVE` and while the parent reservation has not been checked out. Removing an add-on likewise recomputes the reservation's `addon_total_cents`, `tax_cents`, and `total_due_cents` and bumps the reservation's `version`. Add-ons may only be added or removed while the parent reservation is non-terminal — neither `CHECKED_OUT` nor `CANCELLED`; an attempt to add to or remove from a terminal reservation is rejected with `ERR_ADDON_LOCKED` (409). An attempt to remove an add-on that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

### 3.10. The Test-Driving Clock

Because cancellation windows and check-in eligibility are date-relative, the system runs against a deterministic logical clock rather than wall time. An operator-only capability sets the server's current UTC instant by supplying a `current_utc` value, and all date-relative logic — `days_before` in the cancellation refund, the `CHECKED_IN` eligibility comparison against `check_in_date`, and the `actual_check_out_date` derivation at checkout — reads from this clock. A `current_utc` that cannot be parsed is rejected with `ERR_CLOCK_INVALID` (422).

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify or transition an existing resource, including state-machine actions and the clock control, return `200 OK`. Every endpoint requires the authentication headers of §2.1, and the request and response bodies must be reconstructed from the workflow narratives in §3 — this table lists only the method, path, purpose, and which roles may call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parks` | Create a park | Operator |
| GET | `/parks/{id}` | Get a park | Operator, Guest |
| PATCH | `/parks/{id}` | Update park config | Operator |
| POST | `/parks/{id}/rate-plans` | Create a rate plan for a site type | Operator |
| GET | `/parks/{id}/rate-plans` | List rate plans for a park | Operator, Guest |
| GET | `/rate-plans/{id}` | Get a rate plan | Operator, Guest |
| POST | `/parks/{id}/seasons` | Create a non-overlapping season window | Operator |
| GET | `/parks/{id}/seasons` | List seasons for a park | Operator, Guest |
| POST | `/parks/{id}/cancellation-policies` | Create the cancellation refund tier schedule | Operator |
| GET | `/parks/{id}/cancellation-policies` | List cancellation policies for a park | Operator, Guest |
| POST | `/parks/{id}/sites` | Create a site (rate plan must match site type) | Operator |
| GET | `/sites/{id}` | Get a site | Operator, Guest |
| GET | `/sites` | List/filter sites | Operator, Guest |
| GET | `/parks/{id}/sites` | List sites in a park | Operator, Guest |
| POST | `/sites/{id}/maintenance` | Put a site into MAINTENANCE | Operator |
| POST | `/sites/{id}/reactivate` | Return a MAINTENANCE site to ACTIVE | Operator |
| POST | `/sites/{id}/retire` | Retire a site; cascades cancel + refund of live reservations | Operator |
| POST | `/sites/{id}/maintenance-holds` | Block a date window on a site | Operator |
| GET | `/sites/{id}/maintenance-holds` | List maintenance holds on a site | Operator, Guest |
| POST | `/maintenance-holds/{id}/clear` | Clear a maintenance hold | Operator |
| POST | `/guests` | Register a guest | Operator, Guest |
| GET | `/guests/{id}` | Get a guest | Operator, Guest |
| GET | `/guests/{id}/reservations` | List a guest's reservations | Operator, Guest |
| POST | `/sites/{id}/reservations` | Create (lock) a reservation on a site | Guest |
| GET | `/reservations/{id}` | Get a reservation | Operator, Guest |
| GET | `/sites/{id}/reservations` | List reservations on a site | Operator, Guest |
| POST | `/reservations/{id}/confirm` | Confirm a reservation (freezes discount/deposit) | Guest |
| POST | `/reservations/{id}/check-in` | Check the guest in | Operator |
| POST | `/reservations/{id}/check-out` | Check the guest out; reconcile final charge | Operator |
| POST | `/reservations/{id}/cancel` | Cancel a reservation; refund per cancellation tier | Guest |
| POST | `/reservations/{id}/add-ons` | Add an amenity add-on to a reservation | Guest |
| GET | `/reservations/{id}/add-ons` | List add-ons on a reservation | Operator, Guest |
| POST | `/add-ons/{id}/remove` | Remove an add-on (recomputes reservation totals) | Guest |
| POST | `/reservations/{id}/payments` | Record a DEPOSIT or BALANCE payment | Guest |
| GET | `/reservations/{id}/payments` | List the payment ledger for a reservation | Operator, Guest |
| POST | `/_clock/set` | Set the server's current UTC instant (test-driving) | Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_SITE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RATE_PLAN_TYPE_MISMATCH` | 422 |
| `ERR_MAX_STAY_EXCEEDED` | 422 |
| `ERR_SITE_UNAVAILABLE` | 409 |
| `ERR_MAINTENANCE_CONFLICT` | 409 |
| `ERR_DATE_OVERLAP` | 409 |
| `ERR_SEASON_OVERLAP` | 409 |
| `ERR_PAYMENT_AMOUNT_INVALID` | 422 |
| `ERR_PAYMENT_ALREADY_SETTLED` | 409 |
| `ERR_ADDON_LOCKED` | 409 |
| `ERR_VALIDATION_FAILED` | 422 |
| `ERR_CLOCK_INVALID` | 422 |

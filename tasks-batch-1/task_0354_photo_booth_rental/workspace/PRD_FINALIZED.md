# Photo Booth Rental API — Product Requirements Document

## 1. Introduction

The Photo Booth Rental API powers an operator that rents photo booths for events — weddings, galas, corporate parties — where the booth is delivered, set up, staffed, run for a contracted window, torn down, and the resulting images delivered through a private digital gallery. The business problem is that a single event ties together several moving parts that must stay consistent: the customer picks a *package* (a pricing plan that bundles a number of coverage hours and printed copies onto a particular physical form factor of booth), the operator must reserve a physical *booth* unit and, when the package or its add-ons demand it, an on-site *attendant*, and money flows through a deposit-then-balance settlement that can be refunded or forfeited if the event is cancelled.

This API governs that whole lifecycle behind a small set of resources. A booking is the hub: it points at the customer who owns it and the package that prices it, and it accumulates add-on lines, payments, an event log of what actually happened on site, and finally a gallery of photos. Two things make the domain interesting. First, pricing is computed twice from the same booking — once forward-looking at booking and confirmation time using the *requested* event window, and once again as a chronological actual settlement after the event using the *logged* on-site timestamps — and these two numbers are deliberately allowed to differ. Second, a booking carries two independent lifecycles on the same record: a schedule lifecycle (from draft through to a completed or cancelled event) and a payment lifecycle (from unpaid through to paid-in-full, refunded, or forfeited) that advances on its own clock.

The sections below specify the global request/response contract, the system-wide principles (authentication, pagination, money precision, optimistic concurrency, interval reservation), the detailed business workflows, the full endpoint catalogue, and the error code catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `OperationsManager`, `FinanceClerk`, `Customer`, and `Anonymous`. A request that is missing either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. A request whose declared role is authenticated but not permitted for the requested operation is rejected with `ERR_FORBIDDEN`.

Two endpoints are exempt from the authentication requirement and may be called anonymously: self-registration of a customer and reading the server clock. All other endpoints require the headers.

Most roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `OperationsManager`, `FinanceClerk`, or `Anonymous`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `PlatformAdmin` seeds the catalog — booth models, packages, and add-ons — and drives the test clock. `OperationsManager` owns the booth and attendant inventory and runs the event lifecycle: confirmation, start of service, completion, event-log corrections and finalization, and all gallery operations. `FinanceClerk` owns money movements: deposits, balance payments, refunds, and forfeitures. `Anonymous` is the unauthenticated surface used only for self-registration and reading the clock.

The `Customer` role is different: its identity is **entity-backed**. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity, and ownership checks compare a resource's customer foreign key to `X-User-ID`. Concretely, for the customer-owned actions — cancelling a booking and reading one's own booking — the booking's `customer_id` must equal the caller's `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_BOOKING_OWNER`.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Nearly every persisted resource — booth models, packages, booths, attendants, customers, bookings, add-ons, add-on lines, attendant assignments, event logs, and galleries — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, carrying no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the last modification to the resource; it is refreshed on every mutation.
- `version` (integer): a counter that starts at the resource's creation and increments by one on every mutation of that resource. It is the basis for optimistic concurrency control (see §2.7).

There is one exception. The **Payment** resource is an append-only money event and carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because a payment record is never mutated after it is written.

Whenever a resource is mutated — whether by a direct field change or as a downstream side effect of another operation — its `updated_at` is refreshed and its `version` is incremented by one. This applies to derived fields too: for example, when a booking's `balance_due`, `quote_subtotal`, `amount_paid`, `amount_refunded`, `schedule_status`, or `payment_status` changes, that is a mutation of the booking and bumps the booking's `version`.

### 2.5. Money Precision and Rounding

All monetary amounts in the system are handled as decimal numbers and returned as JSON numbers (not strings). Every computed money value — `quote_subtotal`, `deposit_due`, `balance_due`, `travel_fee`, `final_subtotal`, `amount_paid`, `amount_refunded`, and each add-on `line_total` — is rounded to exactly two decimal places using the round-half-up method. Where a calculation specifies an internal evaluation order (for instance, rounding each add-on line individually before summing the lines), that order is part of the contract and is described with the relevant workflow in §3. Configuration and rate fields supplied as input — such as `base_price`, `overtime_rate_per_hour`, `idle_rate_per_hour`, `overage_print_rate`, and an add-on's `unit_price` — must each be provided with at most two decimal places.

### 2.6. Interval Reservation and Half-Open vs. Closed Overlap

Two scarce resources are reserved against time windows: the physical booth and, when required, the attendant. Both reservations are keyed off the booking's event window plus padding, but they use **different overlap semantics**, and the distinction is deliberate.

The **booth-occupied interval** runs from `event_start` minus a setup buffer of `SETUP_BUFFER_MIN` minutes up to `event_end` plus a teardown buffer of `TEARDOWN_BUFFER_MIN` minutes plus a turnaround buffer of `TURNAROUND_BUFFER_MIN` minutes. This interval is treated as **half-open**: a new claim whose start lands exactly on the end edge of an existing claim on the same booth is permitted (adjacency at the buffer edge is allowed), while any new claim that starts earlier than an existing claim's end edge conflicts. A conflicting booth claim is rejected with `ERR_BOOTH_INTERVAL_CONFLICT`.

The **attendant staffing interval** runs from `event_start` minus the same setup buffer of `SETUP_BUFFER_MIN` minutes up to `event_end` plus the teardown buffer of `TEARDOWN_BUFFER_MIN` minutes — note that the turnaround buffer is **not** applied to attendants. This interval is treated as **closed**: two events that touch exactly at the boundary minute conflict, because a single attendant cannot be in two places at that shared edge. A conflicting attendant claim is rejected with `ERR_ATTENDANT_INTERVAL_CONFLICT`.

Each attendant assignment records its own claimed window in `occupied_start` and `occupied_end`, stamped from the setup/teardown window at confirmation.

### 2.7. Optimistic Concurrency Control

Two operations require the client to assert the version of a parent resource it last observed, so that a write computed against a stale view is rejected rather than silently overwriting newer state.

Confirming a draft booking pins a specific candidate booth and stamps an interval claim on it. That request must carry `expected_booth_version`, which must equal the chosen booth's current `version`. If the booth's `version` has advanced since the client last read it — because another confirmation legitimately claimed an overlapping interval on the same unit and bumped that booth's `version` — the confirm is rejected as stale with `ERR_STALE_VERSION` (HTTP 412). The losing client re-reads the booth, observes the new claim, and either selects another unit or another time.

Finalizing an event log requires `expected_eventlog_version`, which must equal that event log's current `version`. If the event log's `version` has advanced since the client last observed it — because an actuals correction was applied in between, bumping the event log's `version` — the finalize is rejected as stale with `ERR_STALE_VERSION` (HTTP 412). The settlement math depends on the exact actuals, so a finalize carried out against an outdated view of the event log would settle the wrong number.

No other endpoint takes a version field; only confirmation and finalization perform an OCC check.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several read endpoints address a resource through a parent path segment — a booking's add-on lines, a booking's payments, a booking's attendant assignments, a booking's event logs, or a booking's galleries. When a path contains an identifier, that identifier is validated first: a reference to a resource that does not exist (whether named in the path or supplied as a foreign key in the body) is rejected with `ERR_NOT_FOUND`. All path and body references are validated left-to-right, so the first non-existent reference encountered is the one reported.

### 2.9. Validation Ordering

When several checks could apply to a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: first authentication (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN`); then booking-ownership for customer-owned actions (`ERR_NOT_BOOKING_OWNER`); then existence of all referenced resources (`ERR_NOT_FOUND`); then request well-formedness (`ERR_INVALID_REQUEST`), uniqueness (`ERR_DUPLICATE_KEY`), and quantity range (`ERR_QTY_OUT_OF_RANGE`); then state-machine preconditions (`ERR_INVALID_STATE`, and the draft-lock guard `ERR_BOOKING_LOCKED`); then the optimistic-concurrency version check (`ERR_STALE_VERSION`); then the temporal and selection checks at confirmation (`ERR_BOOTH_INTERVAL_CONFLICT`, `ERR_NO_BOOTH_AVAILABLE`, `ERR_ATTENDANT_INTERVAL_CONFLICT`, `ERR_NO_ATTENDANT_AVAILABLE`); and finally the fiscal exact-amount checks (`ERR_DEPOSIT_AMOUNT_MISMATCH`, `ERR_BALANCE_AMOUNT_MISMATCH`, `ERR_REFUND_AMOUNT_MISMATCH`) and the gallery-content check (`ERR_GALLERY_EMPTY`). In practice this means, for example, that on the confirm endpoint a stale `expected_booth_version` surfaces as `ERR_STALE_VERSION` before any interval-overlap check is attempted, and that a non-existent booking always reports `ERR_NOT_FOUND` before any state check runs.

## 3. Business Logic & Workflows

### 3.1. Seeding the Catalog and Inventory

Before any booking can exist, an administrator populates the catalog. A booth **model** describes a form factor and is created with a `name` (a display name such as "Open-Air Mirror"), a `booth_type` that is one of `OPEN_AIR`, `ENCLOSED`, `MIRROR`, or `ROAMING_360`, a `footprint_sqft` giving the floor space the model needs on site (at least 1), and a `max_prints_per_hour` printer-throughput ceiling (zero or more). A model also carries an `active` flag, defaulting to `true`, that controls whether new packages or booths may reference it.

A **package** is a pricing plan sold on a particular model. It is created against a `booth_model_id` and carries a marketing `name`, a `base_price` (a non-negative dollar amount) that covers the package's `included_hours` of live coverage (at least 1) and its `included_prints` (zero or more) of printed copies. Three rate fields drive overage settlement: `overtime_rate_per_hour` (dollars per whole hour of coverage beyond the included hours), `idle_rate_per_hour` (dollars per whole idle hour — the booth set up and staffed but not yet running), and `overage_print_rate` (dollars per print beyond the included prints, settled from actual counts). Each rate is non-negative. A package also has an `active` flag, defaulting to `true`, controlling whether new bookings may select it.

The operator's physical inventory consists of booths and attendants. A **booth** is registered against a `booth_model_id` with an `asset_tag`, an operator-assigned inventory tag that must be unique across all booths, and a `status` that is one of `AVAILABLE`, `MAINTENANCE`, or `RETIRED`, defaulting to `AVAILABLE`. A booth's status may later be updated — for example moving it from `AVAILABLE` to `MAINTENANCE` — and any such update increments that booth's `version`. An **attendant** is created with a `full_name` and a `status` that is one of `AVAILABLE`, `ON_LEAVE`, or `INACTIVE`, defaulting to `AVAILABLE`.

The **add-on** catalog lists the optional extras. Each add-on is created with a `code` that is one of `PROPS`, `BACKDROP`, `ATTENDANT`, or `ALBUM`, a display `name`, a `unit_price` (non-negative), a `requires_attendant` flag (defaulting to `false`), and a `max_qty` cap on how many units may be ordered per booking (at least 1, defaulting to 1). The `requires_attendant` flag is `true` for the attendant add-on: selecting such an add-on forces the system to staff an attendant when the booking is confirmed.

When the administrator creates a booth or a customer self-registers, uniqueness is enforced: a duplicate `asset_tag` on a booth, or a duplicate `email` on a customer, is rejected with `ERR_DUPLICATE_KEY`.

### 3.2. Customers and Drafting a Booking

Anyone may self-register as a **customer**, supplying an `email` (unique across customers), a `full_name`, and an optional `home_zip` that is purely informational billing-ZIP data. This is the only write available to the anonymous surface.

A `Customer` opens the booking workflow by drafting a booking. The create payload carries the `customer_id` of the owner, the `package_id` of the chosen pricing plan, the requested `event_start` and `event_end` (both ISO 8601 UTC instants for the live-coverage window, with `event_end` required to be strictly later than `event_start`), the one-way `venue_distance_miles` from the operator depot to the venue (zero or more), and an optional `requested_setup_lead_min` — the number of minutes before `event_start` the customer wants the booth running and staffed, which drives planned idle time and defaults to 0. A malformed payload — a missing required field, an invalid enum, an out-of-range number, or an `event_end` that is not strictly after `event_start` — is rejected with `ERR_INVALID_REQUEST`.

A freshly drafted booking begins with `schedule_status` of `DRAFT` and `payment_status` of `UNPAID`. On creation the system computes the travel fee, then a forward-looking quote, then derives the deposit and balance from that quote. The booking exposes `booth_id` (the physical unit assigned at confirmation, null while `DRAFT`), `quote_subtotal` (the forward-looking estimate), `deposit_due`, `balance_due`, `travel_fee`, `final_subtotal` (the chronological actual settlement, null until the event log is finalized), `amount_paid` (sum of applied non-refund payments less any forfeited write-back, starting at 0), and `amount_refunded` (sum of applied refund payments, starting at 0).

**Travel fee.** The travel fee considers only the single booking's `venue_distance_miles`, with no cross-entity aggregation. The billable mileage is the venue distance minus a free radius of `TRAVEL_FREE_RADIUS_MILES` (25) miles, floored at zero so that any distance within the free radius bills nothing. The raw fee is the per-mile rate `TRAVEL_RATE_PER_MILE` ($1.50) multiplied by those billable miles — charged one way, never round-trip. The `travel_fee` is that raw amount rounded half-up to two decimal places.

**The forward-looking quote.** The `quote_subtotal` is an estimate built from the *requested* window and is recomputed both at booking creation and at confirmation. Coverage hours are the requested span from `event_start` to `event_end`, expressed in hours and rounded **up** to the next whole hour (coverage is billed in whole hours). Overtime hours are the coverage hours minus the package's `included_hours`, floored at zero. The overtime charge is the package's `overtime_rate_per_hour` multiplied by those overtime hours, but capped at the overtime daily cap `OVERTIME_DAILY_CAP` ($750.00) — the charge is the smaller of the two. Planned idle hours are the `requested_setup_lead_min` divided by 60 and rounded **up** to a whole number of idle hours; the idle charge is the package's `idle_rate_per_hour` multiplied by those planned idle hours. The add-on total is the sum of the frozen `line_total` of every add-on line on the booking. The travel component is the travel fee described above. The evaluation order is pinned: each add-on line is rounded to two decimal places when the line is created (its `line_total` is frozen at that moment), and then the already-rounded line totals are summed — round-per-line, then sum — whereas the overtime, idle, and travel components are summed at full precision. The `quote_subtotal` is the package's `base_price` plus the overtime charge plus the idle charge plus the add-on total plus travel, the whole sum rounded half-up to two decimal places. Print overage is **not** part of the quote, because actual print counts are unknown until the event happens.

From that quote the system sets `deposit_due` to the `quote_subtotal` multiplied by the deposit percentage `DEPOSIT_PCT`, rounded half-up to two decimal places, and sets `balance_due` to the `quote_subtotal` (the full amount is outstanding until a deposit is recorded).

### 3.3. Building Out the Booking: Add-On Lines

While a booking is still `DRAFT`, its owning customer may attach add-on lines. Each line is created against the booking with the `add_on_id` of the catalog item and a `qty` of units. The quantity must fall within 1 through the catalog item's `max_qty`; a quantity outside that range is rejected with `ERR_QTY_OUT_OF_RANGE`. A line may be added only while the booking's `schedule_status` is `DRAFT`; attempting to add a line to a booking in any other schedule state is rejected with `ERR_BOOKING_LOCKED`.

When a line is added, its `line_total` is frozen as the add-on's `unit_price` multiplied by the ordered `qty`, rounded half-up to two decimal places, and held at that value thereafter regardless of any later catalog price change. Adding a line then recomputes the booking's forward-looking quote and re-derives `quote_subtotal`, `deposit_due`, and `balance_due` accordingly, and increments the booking's `version`.

### 3.4. Confirming the Booking: Selecting a Booth and Staffing

Confirmation is the pivotal step where the operator commits scarce resources to the booking. It is driven by an `OperationsManager` and advances the booking from `DRAFT` to `CONFIRMED`. Confirmation may proceed only when the booking's `schedule_status` is `DRAFT` and its `payment_status` is already `DEPOSIT_PAID` — the deposit must have been recorded before the booking can be confirmed. It additionally requires that the package referenced by `package_id` has `active` equal to `true`, that at least one booth of the package's model is available with no interval conflict, and, if any add-on line maps to an add-on whose `requires_attendant` is `true`, that at least one available attendant has no interval conflict. A confirmation requested against a booking not in `DRAFT` (or whose deposit precondition is unmet) is rejected with `ERR_INVALID_STATE`.

The confirm request carries `expected_booth_version`, the client's last-observed `version` of the booth it intends to claim. As described in §2.7, a mismatch against the chosen booth's live `version` is rejected with `ERR_STALE_VERSION`.

**Booth selection.** The booth selector considers only booths whose `booth_model_id` matches the booking's package's model, whose `status` is `AVAILABLE`, and that survive the booth-overlap filter against the new booking's booth-occupied interval (the half-open interval of §2.6). If no candidate survives, confirmation is rejected with `ERR_NO_BOOTH_AVAILABLE`; if a specific candidate would overlap an existing claim, that overlap is `ERR_BOOTH_INTERVAL_CONFLICT`. Among surviving candidates, the selector ranks first by the fewest existing active interval claims (load balancing), breaking ties by `created_at` ascending — never by `id`. The first booth in that ordering is chosen, its `id` written to the booking's `booth_id`, and its interval claimed (which bumps that booth's `version`).

**Attendant staffing.** If a `requires_attendant` add-on is present on the booking, the attendant selector runs. It considers only attendants whose `status` is `AVAILABLE` and who survive the attendant-overlap filter against the staffing interval (the closed interval of §2.6). If none survives, confirmation is rejected with `ERR_NO_ATTENDANT_AVAILABLE`; a specific overlap is `ERR_ATTENDANT_INTERVAL_CONFLICT`. Surviving candidates are ranked by the fewest active attendant assignments first, breaking ties by `created_at` ascending — never by `id`. The chosen attendant's `id` is recorded as the `attendant_id` of a newly created attendant assignment whose `status` is `ACTIVE`, with `occupied_start` and `occupied_end` stamped from the setup-and-teardown window. Attendant assignments may later be listed by their `attendant_id`.

As part of confirmation the system also recomputes the forward-looking quote, refreshing `quote_subtotal`, setting `deposit_due`, and setting `balance_due` to the `quote_subtotal` minus the already-paid amount. The booking's `version` is incremented. Confirmation therefore mutates two resources — the booking and the claimed booth — each of which carries its own version bump.

### 3.5. Running the Event and Capturing Actuals

Once confirmed, the booking is taken into service by an `OperationsManager`, advancing `schedule_status` from `CONFIRMED` to `IN_SERVICE`. This is permitted only when the booking is `CONFIRMED` and no event log yet exists for it; otherwise `ERR_INVALID_STATE`. Taking the booking into service creates exactly one **event log**, which begins in its `OPEN` lifecycle with `finalized` equal to `false`, and bumps the booking's `version`.

The event log records what actually happened on site. Its `booking_id` ties it to its booking, and it captures `actual_setup_start` (when the crew began setup), `actual_coverage_start` (when the booth started running for guests), `actual_coverage_end` (when the booth stopped running), `actual_teardown_end` (when teardown finished), and `actual_print_count` (the number of prints physically produced, zero or more). While the event log is still `OPEN`, an `OperationsManager` may correct any of these actuals — `actual_setup_start`, `actual_coverage_start`, `actual_coverage_end`, `actual_teardown_end`, or `actual_print_count` — and each such correction increments the event log's `version`. This is precisely the version movement that the finalize step guards against with its stale-version check.

**Finalizing.** An `OperationsManager` finalizes the event log to lock in the actual settlement, advancing it from `OPEN` to `FINALIZED`. Finalization requires that the event log's `finalized` is still `false`, that all four actual timestamps and the `actual_print_count` are present, that the timestamps are consistently ordered so that `actual_setup_start` is at or before `actual_coverage_start`, `actual_coverage_start` is strictly before `actual_coverage_end`, and `actual_coverage_end` is at or before `actual_teardown_end`, and that the parent booking's `schedule_status` is `IN_SERVICE`. A finalize that violates any of these is rejected with `ERR_INVALID_STATE` (or `ERR_INVALID_REQUEST` for a malformed actuals payload). The request must also carry `expected_eventlog_version`; a mismatch yields `ERR_STALE_VERSION` per §2.7.

On a successful finalize the system sets `finalized` to `true`, runs the chronological actual settlement to set the booking's `final_subtotal`, recomputes the booking's `balance_due` as that `final_subtotal` minus the `amount_paid`, and increments both the event log's `version` and the booking's `version`. That change to `balance_due` re-opens the balance-payment gate, and clearing that balance — reaching `PAID_IN_FULL` — is itself the precondition that later unblocks completion of the event.

**The chronological actual settlement.** This settlement uses the *logged* timestamps, processed in time order, and produces a number that may differ from the forward-looking quote for the same booking. Actual coverage hours are the exact span from `actual_coverage_start` to `actual_coverage_end` expressed in hours. Overtime hours are that actual coverage minus the package's `included_hours`, rounded **up** to a whole number and floored at zero. The overtime charge is the package's `overtime_rate_per_hour` multiplied by those overtime hours, capped at the overtime daily cap `OVERTIME_DAILY_CAP` ($750.00) — the smaller of the two. Actual idle minutes are the gap from `actual_setup_start` to `actual_coverage_start`; idle hours are those minutes divided by 60 and rounded **up** to a whole number, and the idle charge is the package's `idle_rate_per_hour` multiplied by those idle hours. Overage prints are the `actual_print_count` minus the package's `included_prints`, floored at zero; the print overage charge is the package's `overage_print_rate` multiplied by those overage prints, rounded half-up to two decimal places. The add-on total is again the sum of the frozen `line_total` values of the booking's add-on lines. The travel component is the same travel fee computed from `venue_distance_miles`. The `final_subtotal` is the package's `base_price` plus the overtime charge plus the idle charge plus the add-on total plus travel plus the print overage, the whole sum rounded half-up to two decimal places. Unlike the quote, this settlement *does* include print overage from the actual count, which is the principal reason the two figures can diverge.

### 3.6. The Money Lifecycle: Deposit, Balance, Refund, Forfeit

A booking's `payment_status` evolves independently of its schedule, on its own track from `UNPAID` through `DEPOSIT_PAID` to `PAID_IN_FULL`, with terminal branches of `REFUNDED` and `FORFEITED`. All money movements are recorded by a `FinanceClerk` as **payment** events. A payment carries the `booking_id` it belongs to, a `kind` that is one of `DEPOSIT`, `BALANCE`, or `REFUND`, and a strictly positive `amount` given to two decimal places (a refund's `amount` is the positive refunded value). Recording a payment appends the payment, adjusts the booking's `amount_paid` or `amount_refunded`, recomputes `balance_due`, advances `payment_status`, and increments the booking's `version`.

**Deposit.** A `DEPOSIT` payment moves the booking from `UNPAID` to `DEPOSIT_PAID`. It is allowed only when `payment_status` is `UNPAID` and `schedule_status` is `DRAFT`, and the payment `amount` must equal the booking's `deposit_due` exactly — the deposit is paid in full, never partially. A wrong deposit amount is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`. The payment is appended, `amount_paid` is increased by the amount, `balance_due` is recomputed, and the booking's `version` is incremented.

**Balance.** A `BALANCE` payment moves the booking from `DEPOSIT_PAID` to `PAID_IN_FULL`. It is allowed only when `payment_status` is `DEPOSIT_PAID`, the `schedule_status` is either `CONFIRMED` or `IN_SERVICE`, and the booking's event log has been finalized (`finalized` is `true`) so that `balance_due` reflects the final settlement rather than the estimate. The payment `amount` must equal the booking's `balance_due` exactly — it must clear the outstanding balance — otherwise `ERR_BALANCE_AMOUNT_MISMATCH`. On success the payment is appended, `amount_paid` is increased by the amount, `balance_due` is set to 0, and the booking's `version` is incremented.

**Refund.** A `REFUND` payment moves the booking from `DEPOSIT_PAID` to `REFUNDED`. It is allowed only when `schedule_status` is `CANCELLED`, `payment_status` is `DEPOSIT_PAID`, and the cancellation refund calculation returned a refundable amount greater than zero. The payment `amount` must equal that computed refundable amount exactly, otherwise `ERR_REFUND_AMOUNT_MISMATCH`. On success the refund payment is appended, `amount_refunded` is increased by the amount, and the booking's `version` is incremented.

**Forfeit.** Forfeiture is the other terminal branch out of `DEPOSIT_PAID`, driven by a `FinanceClerk`, moving `payment_status` from `DEPOSIT_PAID` to `FORFEITED`. It is allowed only when `schedule_status` is `CANCELLED`, `payment_status` is `DEPOSIT_PAID`, and the cancellation refund calculation returned a refundable amount of exactly zero (the inside-30-day tier). No money is returned; the deposit is retained by the operator, and the booking's `version` is incremented.

Any payment action attempted against a booking that is not in the right payment state for that transition is rejected with `ERR_INVALID_STATE`.

### 3.7. Cancellation and the Refund Tiers

A `Customer` may cancel their own booking while it is either `DRAFT` or `CONFIRMED`, moving `schedule_status` to `CANCELLED`; a cancel against any other schedule state is rejected with `ERR_INVALID_STATE`, and a cancel by a non-owner is rejected with `ERR_NOT_BOOKING_OWNER`. The two cancellation paths differ in what resources they must release.

Cancelling a `DRAFT` booking holds no booth or attendant yet, so nothing physical is released. The system runs the cancellation refund calculation (with the full `amount_paid` refundable, since no resource was committed). If `amount_paid` is greater than zero, the `FinanceClerk` must still issue the `REFUND` payment to move money; if `amount_paid` is zero, the `payment_status` moves to `REFUNDED` immediately. The booking's `version` is incremented.

Cancelling a `CONFIRMED` booking releases the held booth — clearing its interval claim — and, if one is present, releases the attendant assignment (moving its `status` from `ACTIVE` to `RELEASED`). Releasing the attendant frees its interval, which in turn lifts the attendant-conflict gate that had been blocking any overlapping `DRAFT` booking from confirming on that attendant. The cancellation refund calculation then sets the refundable amount. If the tier refunds the deposit in full and a `REFUND` payment clears it, the `payment_status` reaches `REFUNDED`; if the tier refunds zero, the deposit is `FORFEITED`. The booking's `version` is incremented.

**The refund tiers.** The cancellation refund is computed against the single booking's `deposit_due`, `amount_paid`, `event_start`, and the current server clock. The days-to-event figure is the span from the current clock instant to `event_start`, expressed in days and rounded **down** to a whole number of days. The deposit refund percentage is then tiered: if days-to-event is at least 60, the deposit is fully refundable (100%); otherwise if days-to-event is at least 30 (the 30-through-59 window), the deposit is 50% refundable; otherwise (fewer than 30 days) the deposit is forfeited and 0% refundable. The constants behind these tiers are a full-refund threshold of 60 days (`TIER_FULL_DAYS`) and a half-refund threshold of 30 days (`TIER_HALF_DAYS`). The refundable deposit is the `deposit_due` multiplied by that tier percentage, rounded half-up to two decimal places. Separately, any amount paid beyond the deposit is always fully refundable: the refundable balance is the `amount_paid` minus the `deposit_due` when `amount_paid` exceeds `deposit_due`, and zero otherwise. The total refundable amount is the refundable deposit plus the refundable balance, rounded half-up to two decimal places. This refundable amount is exactly what a `REFUND` payment must match, and a refundable amount of zero is exactly the condition that permits a forfeiture instead.

### 3.8. Completing the Event

Completion is the final schedule transition, driven by an `OperationsManager`, moving `schedule_status` from `IN_SERVICE` to `COMPLETED`. It is permitted only when the booking is `IN_SERVICE`, its event log has been finalized (`finalized` is `true`, so actuals have been submitted), and its `payment_status` is `PAID_IN_FULL`. A completion attempted before those conditions are met is rejected with `ERR_INVALID_STATE`. Completion releases the attendant assignment (moving its `status` from `ACTIVE` to `RELEASED`, freeing the attendant interval), creates the booking's **gallery** if none exists (with `status` of `DRAFT` and `photo_count` of 0), and increments the booking's `version`. Both `COMPLETED` and `CANCELLED` are terminal schedule states.

### 3.9. The Digital Gallery

A gallery holds the event's images and exposes a private share PIN. It carries its `booking_id`, a `photo_count` (the number of digital images uploaded, defaulting to 0), a `status` that is one of `DRAFT`, `PUBLISHED`, or `UNPUBLISHED`, and an `access_pin` — a server-minted six-digit share PIN regenerated on each publish. An `OperationsManager` uploads photos with a `count`, which increases the gallery's `photo_count` by that amount and increments the gallery's `version`.

The gallery follows a cyclic publish/unpublish lifecycle, all driven by an `OperationsManager`. Publishing from `DRAFT` to `PUBLISHED` requires that the gallery is in `DRAFT`, that its `photo_count` is at least 1, that the parent booking's `schedule_status` is `COMPLETED`, and that the parent booking's `payment_status` is `PAID_IN_FULL`; on success the system mints a fresh six-digit `access_pin` and increments the gallery's `version`. Unpublishing from `PUBLISHED` to `UNPUBLISHED` requires only that the gallery is `PUBLISHED`; it invalidates the `access_pin` (setting it to null) and increments the gallery's `version`. Re-publishing from `UNPUBLISHED` back to `PUBLISHED` requires that the gallery is `UNPUBLISHED`, that its `photo_count` is at least 1, and that the parent booking's `payment_status` is `PAID_IN_FULL`; it mints a fresh six-digit `access_pin` (a different PIN per publish) and increments the gallery's `version`. An attempt to publish a gallery whose `photo_count` is zero is rejected with `ERR_GALLERY_EMPTY`, and any publish or unpublish requested from the wrong gallery state is rejected with `ERR_INVALID_STATE`.

### 3.10. The Test Clock

Because the cancellation refund tiers depend on how far in the future the event lies, the system exposes a logical clock that a `PlatformAdmin` can pin. An admin-only capability sets the server's current UTC instant to a supplied `to_iso8601` value, and all subsequent day-tier computations measure from that pinned instant. The current clock may be read by anyone, including anonymous callers.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example a booth model, a package, a booth, an attendant, an add-on, a customer, a booking, an add-on line, or a payment) return a `201 Created` status code. Operations that modify an existing resource — the lifecycle transitions, status patches, photo uploads, gallery publish/unpublish, event-log corrections and finalization, and the clock set — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/booth-models` | Create a booth model | PlatformAdmin |
| GET | `/booth-models/{id}` | Read a booth model | PlatformAdmin, OperationsManager, Customer |
| POST | `/packages` | Create a package on a booth model | PlatformAdmin |
| GET | `/packages/{id}` | Read a package | PlatformAdmin, OperationsManager, Customer |
| GET | `/packages` | List packages, optionally filtered by booth model | PlatformAdmin, OperationsManager, Customer |
| POST | `/booths` | Register a physical booth unit | OperationsManager |
| GET | `/booths/{id}` | Read a booth | OperationsManager, PlatformAdmin |
| GET | `/booths` | List booths, optionally filtered by booth model | OperationsManager, PlatformAdmin |
| PATCH | `/booths/{id}` | Update a booth's status | OperationsManager |
| POST | `/attendants` | Create an attendant | OperationsManager |
| GET | `/attendants/{id}` | Read an attendant | OperationsManager, PlatformAdmin |
| POST | `/add-ons` | Create a catalog add-on | PlatformAdmin |
| GET | `/add-ons/{id}` | Read an add-on | PlatformAdmin, OperationsManager, Customer |
| POST | `/customers` | Self-register a customer | Anonymous |
| GET | `/customers/{id}` | Read a customer | Customer, OperationsManager, PlatformAdmin |
| POST | `/bookings` | Create a DRAFT booking | Customer |
| GET | `/bookings/{id}` | Read a booking | Customer, OperationsManager, FinanceClerk, PlatformAdmin |
| GET | `/bookings` | List bookings, optionally filtered by customer, package, booth, or schedule status | OperationsManager, FinanceClerk, PlatformAdmin, Customer |
| POST | `/bookings/{id}/add-ons` | Add an add-on line to a DRAFT booking | Customer |
| GET | `/bookings/{id}/add-ons` | List a booking's add-on lines | Customer, OperationsManager, PlatformAdmin |
| GET | `/add-on-lines/{id}` | Read a single add-on line | OperationsManager, PlatformAdmin, Customer |
| GET | `/add-on-lines` | List add-on lines filtered by add-on | OperationsManager, PlatformAdmin |
| POST | `/bookings/{id}/payments` | Record a DEPOSIT / BALANCE / REFUND money event | FinanceClerk |
| GET | `/bookings/{id}/payments` | List a booking's payments | FinanceClerk, OperationsManager, PlatformAdmin |
| POST | `/bookings/{id}/confirm` | Confirm a DRAFT booking | OperationsManager |
| POST | `/bookings/{id}/start-service` | Move a CONFIRMED booking IN_SERVICE | OperationsManager |
| POST | `/bookings/{id}/complete` | Complete an IN_SERVICE booking | OperationsManager |
| POST | `/bookings/{id}/cancel` | Cancel a DRAFT or CONFIRMED booking | Customer |
| POST | `/bookings/{id}/forfeit` | Forfeit the deposit of a CANCELLED booking | FinanceClerk |
| GET | `/bookings/{id}/attendant-assignments` | List a booking's attendant assignments | OperationsManager, PlatformAdmin |
| GET | `/attendant-assignments/{id}` | Read a single attendant assignment | OperationsManager, PlatformAdmin |
| GET | `/attendant-assignments` | List attendant assignments filtered by attendant | OperationsManager, PlatformAdmin |
| GET | `/event-logs/{id}` | Read an event log | OperationsManager, FinanceClerk, PlatformAdmin |
| GET | `/bookings/{id}/event-logs` | List a booking's event logs | OperationsManager, FinanceClerk, PlatformAdmin |
| PATCH | `/event-logs/{id}` | Correct OPEN event-log actuals before finalize | OperationsManager |
| POST | `/event-logs/{id}/finalize` | Finalize OPEN actuals and run final settlement | OperationsManager |
| GET | `/galleries/{id}` | Read a gallery | Customer, OperationsManager, PlatformAdmin |
| GET | `/bookings/{id}/galleries` | List a booking's galleries | Customer, OperationsManager, PlatformAdmin |
| POST | `/galleries/{id}/photos` | Upload photos to a gallery | OperationsManager |
| POST | `/galleries/{id}/publish` | Publish a DRAFT or UNPUBLISHED gallery | OperationsManager |
| POST | `/galleries/{id}/unpublish` | Unpublish a PUBLISHED gallery | OperationsManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | PlatformAdmin |
| GET | `/_clock` | Read the current server UTC clock | Anonymous, PlatformAdmin, OperationsManager, FinanceClerk, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_BOOKING_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_QTY_OUT_OF_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BOOKING_LOCKED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOOTH_INTERVAL_CONFLICT` | 409 |
| `ERR_NO_BOOTH_AVAILABLE` | 409 |
| `ERR_ATTENDANT_INTERVAL_CONFLICT` | 409 |
| `ERR_NO_ATTENDANT_AVAILABLE` | 409 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
| `ERR_BALANCE_AMOUNT_MISMATCH` | 422 |
| `ERR_REFUND_AMOUNT_MISMATCH` | 422 |
| `ERR_GALLERY_EMPTY` | 409 |

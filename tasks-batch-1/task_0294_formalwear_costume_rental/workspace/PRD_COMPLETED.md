# Formalwear & Costume Rental API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Formalwear & Costume Rental API, the system of record for a rental boutique that hires out formalwear and costume garments for dated events such as weddings, galas, and theatrical productions. The business problem it solves is fundamentally one of scarce physical inventory committed against future calendar dates: a single tuxedo or costume exists as a finite number of physical units in a finite set of sizes, and each unit can only be in one customer's possession at a time. The API therefore has to reconcile a customer's intent to rent a particular style and size for a particular event window against the real, time-bounded availability of the underlying garments, while accounting for the cleaning turnaround a unit needs between rentals.

Around that core allocation problem the system layers the commercial realities of the trade: refundable security deposits held at pickup, an optional damage waiver, late fees that accrue once a garment is held past its return window, damage and loss charges assessed at inspection, tailoring alterations, and the special coordination needs of wedding parties and costumed groups who must all be outfitted for the same date. Every monetary movement is recorded on an append-only ledger so that a customer's held deposits and outstanding balance can always be reconstructed. Three operational actors share the system — the renting customer, the shop-floor clerk who runs the counter, and the store manager who owns inventory and financial overrides — and the requirements below define exactly what each may do and how the numbers are computed at every step.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `Customer`, `StoreClerk`, and `StoreManager`. When an authenticated principal attempts an operation their role is not permitted to perform — or when an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The three roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. Concretely, a `Customer` may act only on the `Customer` record whose `id` is their own, on reservations whose `customer_id` is their own, on measurement profiles whose `customer_id` is their own, on alterations belonging to their own reservations, on party orders whose `coordinator_customer_id` is their own, on settlements belonging to their own reservations, on fit checks belonging to their own reservations, and on ledger entries whose `customer_id` is their own; acting on any such resource that is not their own is rejected with `ERR_FORBIDDEN`. Catalogs carry no customer foreign key and are readable by any authenticated `Customer`. When `X-User-Role` is `StoreClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`, and a clerk may act on any customer's resources from the shop floor. When `X-User-Role` is `StoreManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`, and the manager's authority covers inventory and financial overrides rather than ownership of customer-facing resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries the pagination bookkeeping in the `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource is minted by the server with a string `id` formatted as a UUID; this identifier carries no type prefix and is used for identity only. Most resources also carry three further system-managed fields. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; it never changes and additionally serves as the deterministic tie-break and sweep-order key wherever ordering matters. The `updated_at` field is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation; it is the basis for optimistic concurrency control described in §2.10.

One entity is deliberately leaner. A `LedgerEntry` is an immutable, append-only posting: once written it is never mutated. Accordingly a `LedgerEntry` carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field — and its `created_at` doubles as the append-order key for the ledger. Every other entity in the system (`Catalog`, `GarmentUnit`, `Customer`, `MeasurementProfile`, `Reservation`, `Alteration`, `PartyOrder`, `Settlement`, and `FitCheck`) carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Nested Resource Retrieval and Reference Validation

The API uses a flat topology: most resources are addressed at the root, and relationships are expressed through foreign keys carried in request bodies rather than through deep URL nesting. A small number of paths do nest one identifier beneath another — for example a customer's measurement-profile collection lives beneath the owning customer. Wherever a path or request body references another resource, the system validates those references left to right, in the order they appear, and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. This left-to-right rule governs every reference across `Catalog`, `GarmentUnit`, `Customer`, `MeasurementProfile`, `Reservation`, `Alteration`, `PartyOrder`, `Settlement`, and `FitCheck`. Reference existence (a 404 concern) is always evaluated before any state, ownership, or business rule on the referenced resource.

### 2.6. Validation Ordering

When several checks could fail a single request, the system evaluates them in a fixed priority order so that the returned error is deterministic. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization and ownership (`ERR_FORBIDDEN`); third, existence of every referenced resource (`ERR_NOT_FOUND`); fourth, structural well-formedness of the request body (`ERR_INVALID_REQUEST`); fifth, reservation window coherence on booking (`ERR_INVALID_WINDOW`); sixth, whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Business rules that are specific to a single transition are evaluated after these foundational checks, in the order described alongside each workflow in §3. A well-formed-body check applies to every create and update endpoint and covers: all required fields present, every enum-typed field holding one of its permitted values, every integer at or above its declared minimum, and — on customer creation — the `email` being unique across all existing customers.

### 2.7. Monetary Precision and Rounding

All money in the system is represented as whole integer cents; field names ending in `_cents` are integer counts of cents, never fractional currency. Wherever a calculation introduces a non-integer intermediate — for instance multiplying a daily rate by a discount multiplier, or taking a percentage of a replacement value — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger). The precise point at which rounding is applied within each formula is pinned in §3 and must be honored exactly, because rounding before versus after a multiplication can yield different totals. Ledger postings are exact integer movements and are never rounded.

### 2.8. Inventory Lifecycle and Cleaning Turnaround

A physical garment, modeled as a `GarmentUnit`, moves through a lifecycle captured by its `status`: it begins `AVAILABLE`, is held as `RESERVED` when allocated to a confirmed booking, becomes `OUT` when handed to the customer, enters `IN_CLEANING` on return, and either cycles back to `AVAILABLE` once cleaned or ends permanently `RETIRED`. Each unit also carries a `condition_grade` of `GRADE_A`, `GRADE_B`, or `GRADE_C`, starting at `GRADE_A` and degrading as damage accumulates, and a `damage_strike_count` that tallies damaged settlements against it. Returning a unit to service is not instantaneous: after a return the unit is unavailable for a mandatory cleaning turnaround, and its `available_from_iso` records the earliest moment it may next be picked up. Until a unit has ever been rented, `available_from_iso` is null.

### 2.9. Deposit Ledger and Account Balances

Every monetary movement is recorded as an immutable `LedgerEntry` whose `entry_type` is one of `DEPOSIT_HOLD`, `DEPOSIT_RELEASE`, `DEPOSIT_CAPTURE`, `FEE_CHARGE`, or `FEE_WAIVE`, with a signed `amount_cents`. A posting always names the `customer_id` it belongs to; its `reservation_id` is populated for reservation-scoped postings and is null for party-level postings. The sign convention is fixed: a `DEPOSIT_HOLD` posts the held deposit as a positive amount; a `DEPOSIT_RELEASE` posts the refunded portion as a negative magnitude; a `DEPOSIT_CAPTURE` posts the deposit consumed by fees as a negative magnitude; a `FEE_CHARGE` posts the fee the customer owes as a positive amount; and a `FEE_WAIVE` posts the waived credit as a negative magnitude. From this ledger the system derives a customer's live balances: `deposit_held_cents` equals the sum of `DEPOSIT_HOLD` amounts minus the magnitudes of all `DEPOSIT_RELEASE` and `DEPOSIT_CAPTURE` postings for that customer, and `balance_owed_cents` equals the sum of `FEE_CHARGE` amounts minus the magnitudes of all `FEE_WAIVE` postings for that customer. Over the full pickup-to-settle lifecycle of a single reservation the deposit is conserved: the amount held at pickup equals the refunded portion plus the captured portion, so the `DEPOSIT_HOLD` magnitude always equals the sum of the matching `DEPOSIT_RELEASE` magnitude and `DEPOSIT_CAPTURE` magnitude. A clean close with no fees refunds the entire hold and captures nothing; a close with damage or late fees captures part or all of the deposit and posts a `FEE_CHARGE` only for any overflow beyond the deposit.

### 2.10. Optimistic Concurrency Control

Several mutations require the client to prove it is acting on a current view of a parent resource by supplying that resource's last observed `version`. Confirming a member reservation that is linked to a party order checks `expected_party_order_version` against the linked `PartyOrder`'s current `version` only when that field is supplied — when it is supplied and does not match, the confirm is rejected with `ERR_STALE_VERSION` at HTTP 412 (so a coordinator never locks a party whose membership shifted underneath their last read), and when it is omitted the confirm proceeds with no concurrency check. Locking a party order requires `expected_party_order_version` and rejects with `ERR_STALE_VERSION` at HTTP 412 both when it is omitted and when it is supplied but does not match the `PartyOrder`'s current `version`, so the party is never frozen at a membership count the coordinator did not actually observe. Retiring a garment unit checks `expected_garment_unit_version` against that `GarmentUnit`'s current `version` only when that field is supplied — a supplied mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412, while an omitted field skips the check and the retire proceeds. Waiving a settlement fee requires `expected_settlement_version` and rejects with `ERR_STALE_VERSION` at HTTP 412 both when it is omitted and when it is supplied but does not match that `Settlement`'s current `version`. Endpoints not listed here do not take a version field and perform no concurrency check.

## 3. Business Logic & Workflows

### 3.1. Standing Up Inventory: Catalogs and Garment Units

The catalog is where the store defines what it rents. A `StoreManager` creates a `Catalog` by supplying a `style_name`, a `category` that is either `FORMALWEAR` or `COSTUME`, and the commercial parameters that govern every unit of that style: the `daily_rate_cents` charged per rental-day, the refundable `deposit_cents` held per unit at pickup, the `replacement_value_cents` that caps any damage charge, the `waiver_daily_rate_cents` surcharge billed per rental-day when a customer buys the damage waiver, the `cleaning_buffer_days` a returned unit must sit before it can next be picked up, and the `late_fee_daily_rate_cents` levied for each calendar day a garment is held past its return window. All of these monetary inputs must be zero or greater, and `cleaning_buffer_days` must be zero or greater, defaulting to 1 day when not provided. A freshly created catalog reports an `active_unit_count` of 0; this read-only figure always reflects the count of that catalog's garment units whose `status` is anything other than `RETIRED`.

Physical stock is added one unit at a time. A `StoreManager` registers a `GarmentUnit` by naming the `catalog_id` it belongs to and its `size_code`, which is one of `XS`, `S`, `M`, `L`, `XL`, or `XXL`. A new unit comes to life `AVAILABLE`, at `condition_grade` `GRADE_A`, with a `damage_strike_count` of 0, and the owning catalog's `active_unit_count` is recomputed to include it. A manager may also remove a unit from circulation. Retiring a unit is permitted only while it is `AVAILABLE` or while it is `IN_CLEANING`; the retirement carries the unit to the terminal `RETIRED` state, recomputes (decrementing) the owning catalog's `active_unit_count`, and advances the unit's own `version` by 1. Because retirement targets a specific unit, the request may carry `expected_garment_unit_version`; when present it must match that unit's current `version` or the retire is rejected with `ERR_STALE_VERSION`, and when omitted no concurrency check is run, as described in §2.10.

A unit that has been returned and cleaned does not re-enter the pool on its own at the counter level: once its cleaning turnaround has elapsed, a `StoreClerk` clears it from `IN_CLEANING` back to `AVAILABLE`. This is permitted only when the unit is `IN_CLEANING` and the current clock has reached or passed the unit's `available_from_iso`; a unit that is not `IN_CLEANING`, and equally a unit whose `available_from_iso` the clock has not yet reached, is rejected with `ERR_INVALID_STATE`. This endpoint takes no version field and runs no concurrency check. If, however, the unit has accumulated a `damage_strike_count` of 2 or more, clearing it instead routes the unit to `RETIRED` rather than back to `AVAILABLE`, because two damage strikes exhaust a unit's serviceable life.

### 3.2. Customers, Measurements, and Size Recommendation

Anyone can become a renter: a `StoreClerk` or a self-registering `Customer` creates a `Customer` account with a `full_name` and an `email`, the latter required to be unique across all customers. A new account opens with `deposit_held_cents`, `balance_owed_cents`, and `open_strike_count` all at 0. These three figures are always computed, never set directly, and the two monetary ones are derived purely from that customer's ledger postings exactly as defined in §2.9 (not from reservation status): `deposit_held_cents` is the sum of the customer's `DEPOSIT_HOLD` amounts minus the magnitudes of their `DEPOSIT_RELEASE` and `DEPOSIT_CAPTURE` postings — so a hold persists in this figure from pickup until it is closed by a `DEPOSIT_RELEASE` at finalization, even while the reservation sits in `RETURNED`; `balance_owed_cents` is the sum of the customer's `FEE_CHARGE` amounts minus the magnitudes of their `FEE_WAIVE` postings; and `open_strike_count` is the count of all the customer's settlements whose `disposition` is `DAMAGED`, with no time-window restriction, a figure that influences whether the damage waiver is required of them.

To fit a garment well the store records body measurements. A clerk or the customer themselves creates a `MeasurementProfile` for a customer by posting `chest_cm`, `waist_cm`, and `inseam_cm`, each a positive integer greater than 0, against that `customer_id`. From the chest measurement the system derives a `recommended_size_code` using a size chart whose buckets are half-open on the lower bound and open on the upper bound: a chest under 86 cm recommends `XS`; from 86 cm up to but not including 96 cm recommends `S`; from 96 cm up to but not including 106 cm recommends `M`; from 106 cm up to but not including 116 cm recommends `L`; from 116 cm up to but not including 126 cm recommends `XL`; and a chest of 126 cm or more recommends `XXL`. The same derivation runs whenever a profile is created and whenever it is updated.

### 3.3. Booking a Reservation by Event Date

A reservation is the customer's request to rent a particular style and size for a dated event. A `StoreClerk` or the renting `Customer` books a `Reservation` by supplying the `customer_id` who rents, the `catalog_id` of the desired style, the `requested_size_code`, the `event_date_iso` of the occasion, the `pickup_window_start_iso` that opens the pickup window, and the `return_window_end_iso` that closes the return window. Optionally the booking may name a `party_order_id` to attach the reservation to a group order, and may set `damage_waiver_opted` to indicate the customer is buying the damage waiver at booking; when omitted, `damage_waiver_opted` defaults to false. A new reservation starts `PENDING`, with no unit yet allocated — its `garment_unit_id` remains null until confirmation.

At booking the system enforces window coherence, evaluating these three temporal rules in this order: the `pickup_window_start_iso` must be on or before the `return_window_end_iso`; the `pickup_window_start_iso` must be on or before the `event_date_iso` (this is what "the pickup window must end on or before the event date" means — the comparison is against `pickup_window_start_iso`, not `return_window_end_iso`); and the `event_date_iso` must lie strictly in the future relative to the current clock (an `event_date_iso` equal to the current clock is rejected). Any violation of these temporal rules is rejected with `ERR_INVALID_WINDOW`. The reservation lifecycle proceeds through `PENDING`, `CONFIRMED`, `PICKED_UP`, then either `RETURNED` or `OVERDUE`, and finally the terminal `SETTLED`; an unfulfilled reservation may instead reach the terminal `CANCELLED`.

### 3.4. Confirmation: Allocating a Unit and Quoting the Charge

Confirmation is the moment a concrete physical unit is committed to the booking, and it is a `StoreClerk` action that moves the reservation from `PENDING` to `CONFIRMED`. Several conditions must hold, and they surface distinct errors. The reservation must currently be `PENDING`, or the transition is undefined and rejected with `ERR_INVALID_STATE`. These business gates are evaluated in a fixed order after the state check: first the customer-window conflict, then the party gates, and only last the unit-availability gate. The same customer must not already hold another reservation, in `CONFIRMED`, `PICKED_UP`, or `OVERDUE` status, whose rental window overlaps this one; the rental window is the half-open interval running from `pickup_window_start_iso` up to but not including `return_window_end_iso`, compared with no added buffer, and any overlap is rejected with `ERR_CUSTOMER_WINDOW_CONFLICT`. Next, if the reservation names a `party_order_id`, the linked party's `posture` must be `FORMING` or `READY` and the party's `event_date_iso` must equal the reservation's `event_date_iso`, failing which the confirm is rejected with `ERR_PARTY_NOT_OPEN`; and, as covered in §2.10, when the reservation is party-linked the supplied `expected_party_order_version` must match the party's current `version` or the confirm is rejected with `ERR_STALE_VERSION`. Only after those gates pass must there exist an allocatable unit (described below) or the confirm is rejected with `ERR_NO_UNIT_AVAILABLE`.

An allocatable unit is one of the reservation's `catalog_id` whose `size_code` equals the `requested_size_code`, whose `status` is `AVAILABLE`, whose `condition_grade` is `GRADE_A` or `GRADE_B` (a `GRADE_C` unit is never allocated), and whose `available_from_iso` is either null or on or before the `pickup_window_start_iso`. When more than one unit qualifies, the server selects deterministically by ranking the candidates: best condition first, ordering `GRADE_A` ahead of `GRADE_B`; then fewest prior strikes, ordering by ascending `damage_strike_count`; then oldest unit first, ordering by ascending `created_at`. The top-ranked candidate is chosen, with `created_at` ascending as the final tie-break — never the `id`. The chosen unit is pinned to the reservation by writing its identifier into `garment_unit_id`, and that unit transitions from `AVAILABLE` to `RESERVED`.

On confirmation the system also computes the provisional quote. First it derives `rental_days` as the inclusive span of the rental window: take the number of whole days from `pickup_window_start_iso` to `return_window_end_iso` and add 1, so a same-day pickup and return is 1 rental-day. A volume discount then applies to the per-day rate as a single multiplier chosen by the span: a span of 1 to 3 days uses a multiplier of 1.00; a span of 4 to 7 days uses 0.90; a span of 8 days or more uses 0.80. The discount applies to every day of the rental, not only the marginal days. The rounding order is pinned and must be followed exactly: first compute the effective per-day rate by multiplying `daily_rate_cents` by the chosen multiplier and rounding that per-day figure half-up to whole cents, and only then multiply the rounded per-day rate by `rental_days` to obtain the rental component. The waiver component is the `waiver_daily_rate_cents` multiplied by `rental_days` when `damage_waiver_opted` is true, and 0 when it is false. The `quoted_charge_cents` is the sum of the rental component and the waiver component. This quote is provisional — computed once at confirmation and never recomputed after pickup; it never includes late or damage fees, which are assessed only at settlement, and the rental component it establishes is carried forward as the rental baseline for settlement.

When the reservation is party-linked, confirming it recomputes the party's `confirmed_member_count`, recomputes its `posture` (flipping `FORMING` to `READY` once the confirmed count reaches the required count), and advances the party's `version` by 1.

### 3.5. Fit Checks and Alterations

Before a confirmed garment can leave the shop it must be cleared for fit. A `StoreClerk` records a `FitCheck` against a reservation by naming the `reservation_id` and the `measurement_profile_id` to use; recording a fit check imposes no precondition on the reservation's current `status` (the reservation need not be `CONFIRMED`) once both references resolve. The system computes a `verdict` by comparing sizes on an ordinal scale where `XS` is 0, `S` is 1, `M` is 2, `L` is 3, `XL` is 4, and `XXL` is 5. It takes the absolute difference between the ordinal of the measurement profile's `recommended_size_code` and the ordinal of the reservation's `requested_size_code`. A difference of 0 yields `PASS` — the measured size matches the requested garment. A difference of exactly 1 yields `NEEDS_ALTERATION` — an adjacent size that tailoring can close. A difference of 2 or more yields `FAIL` — the garment cannot be made to fit.

Tailoring is handled through alterations. A clerk or the customer requests an `Alteration` by naming the `reservation_id`, the `kind` (`HEM`, `TAKE_IN`, or `LET_OUT`), and the flat `fee_cents` the clerk quotes, which must be zero or greater; requesting an alteration imposes no precondition on the reservation's current `status` (the reservation need not be `CONFIRMED`) once the reference resolves. An alteration opens `REQUESTED`. A clerk completes it, moving it from `REQUESTED` to `COMPLETED`, but only while the parent reservation is `CONFIRMED`; attempting completion against a reservation in any other state is rejected with `ERR_INVALID_STATE`. Completion charges the alteration: the `fee_cents` is added to the customer's `balance_owed_cents` through a reservation-scoped `FEE_CHARGE` posting. An alteration may instead be cancelled from `REQUESTED` to `CANCELLED`, by a clerk or the customer, in which case no fee is charged. Alterations are also cancelled automatically as a side effect when their parent reservation is cancelled.

### 3.6. Pickup: Releasing the Garment to the Customer

Handing the garment over is a `StoreClerk` action that moves the reservation from `CONFIRMED` to `PICKED_UP`, and it is gated by four business checks evaluated after the foundational state check. The reservation must be `CONFIRMED`, or the transition is rejected with `ERR_INVALID_STATE`. First among the business gates, the reservation must be cleared for fit: there must exist a `FitCheck` on the reservation with a `verdict` of `PASS`, or one with `verdict` `NEEDS_ALTERATION` accompanied by at least one `COMPLETED` alteration on the reservation; a `FAIL` verdict never clears pickup. A reservation that is not fit-cleared is rejected with `ERR_FIT_NOT_CLEARED`. Next, no alteration on the reservation may still be outstanding: every alteration must be `COMPLETED` or `CANCELLED`, and any remaining `REQUESTED` alteration blocks pickup with `ERR_ALTERATION_PENDING`. Finally, the customer must owe nothing: if the customer's `balance_owed_cents` is greater than 0, pickup is blocked with `ERR_BALANCE_OUTSTANDING` until the outstanding fees are cleared.

When all gates pass, the allocated unit transitions from `RESERVED` to `OUT`, signifying it is physically with the customer. At the same moment the deposit is taken: the system appends a `DEPOSIT_HOLD` posting for the catalog's `deposit_cents`, and the customer's `deposit_held_cents` is recomputed to reflect the new hold.

### 3.7. Return, Settlement Charges, and the Damage Cascade

A return is recorded by a `StoreClerk`, who posts the `returned_at_iso` timestamp and the inspection `disposition` of `CLEAN`, `DAMAGED`, or `LOST`. The return both creates the `Settlement` that accounts for the rental and routes the reservation onto one of two branches depending on timing; the endpoint's success `data` is the newly created `Settlement` object, not the reservation. If the `returned_at_iso` is on or before the reservation's `return_window_end_iso`, the reservation follows the on-time branch from `PICKED_UP` to `RETURNED`. If the `returned_at_iso` is after the `return_window_end_iso`, the reservation follows the late branch: a late return executed while the reservation is still `PICKED_UP` carries it to `OVERDUE` (awaiting its deposit disposition at finalization), while a return executed while the reservation is already `OVERDUE` likewise follows the late branch and carries the reservation through to `SETTLED`. Either way a return is only valid while the reservation is `PICKED_UP` or `OVERDUE`.

The `Settlement` carries the full fee breakdown, computed against its reservation and catalog. The `late_days` is the number of whole calendar days the `returned_at_iso` falls strictly after the `return_window_end_iso`, taking the ceiling of the day difference, and is 0 when the return is on or before the window end; on the on-time branch `late_days` is forced to 0. The `late_fee_cents` is `late_days` multiplied by the catalog's `late_fee_daily_rate_cents`, and is therefore 0 on the on-time branch and positive only on the late branch. The `damage_fee_cents` depends on disposition: a `CLEAN` return carries a damage fee of 0; a `DAMAGED` return carries a damage fee equal to the smaller of the catalog's `replacement_value_cents` and 60 percent of that replacement value rounded half-up to whole cents, with the minimum applied after the percentage is rounded; and a `LOST` return carries a damage fee equal to the full `replacement_value_cents`. The `waiver_credit_cents` absorbs damage only, never late fees: when `damage_waiver_opted` is true it equals the smaller of `damage_fee_cents` and the waiver cap of 30000 cents, and when the waiver was not purchased it is 0. The gross fees are then `late_fee_cents` plus `damage_fee_cents` minus `waiver_credit_cents`.

The deposit is then applied as a waterfall against those gross fees. The deposit available is the catalog's `deposit_cents`. The amount drawn from the deposit is the smaller of the deposit and the gross fees. The `net_charge_cents` — what the customer still owes beyond the deposit — is the gross fees minus the deposit, floored at 0 so it is never negative. The `deposit_refund_cents` — what is returned to the customer — is the deposit minus the amount drawn from it. At return time the system appends the conservation postings described in §2.9: a `DEPOSIT_CAPTURE` for the portion of the deposit applied to fees, plus `FEE_CHARGE` or `FEE_WAIVE` postings as applicable, and the customer's `deposit_held_cents`, `balance_owed_cents`, and `open_strike_count` are recomputed.

The return also touches the physical unit and, on damage, cascades further. The unit transitions from `OUT` to `IN_CLEANING`, and its `available_from_iso` is set to the `returned_at_iso` plus the catalog's `cleaning_buffer_days`. If the disposition was `DAMAGED` or `LOST`, the unit's `condition_grade` is downgraded by one grade and its `damage_strike_count` is increased by 1; and the unit is automatically retired — carried to `RETIRED` — when its `damage_strike_count` reaches 2 or more, or whenever the disposition was `LOST`. A unit auto-retired in this way has its owning catalog's `active_unit_count` recomputed downward.

There is one important asymmetry between how a reservation reaches `OVERDUE`. A clerk-driven return that arrives past the window creates the `Settlement` immediately on the late branch as described above. But a reservation can also be flagged `OVERDUE` by the clock sweep (see §3.9) while still `PICKED_UP`; in that case no settlement is created and the unit stays `OUT` — the reservation is merely marked `OVERDUE` so that late fees will accrue. The eventual return called against such an `OVERDUE` reservation is what finally creates the `Settlement` (on the late branch) and carries the reservation to `SETTLED`.

### 3.8. Finalizing the Settlement and Closing the Deposit

A settlement created on the on-time branch leaves the reservation in `RETURNED`, and a settlement reached on the late branch may leave the reservation in `OVERDUE` awaiting its deposit disposition. In both cases a `StoreClerk` finalizes the settlement to close out the deposit hold and move the reservation to the terminal `SETTLED` state. Finalization is permitted only when a `Settlement` exists for the reservation and the reservation is in `RETURNED` or `OVERDUE`; it takes no version field and runs no concurrency check, and its success `data` is the `Settlement` object (the reservation is moved to `SETTLED` as a side effect). Finalizing posts a `DEPOSIT_RELEASE` for the settlement's `deposit_refund_cents` — the un-applied portion of the deposit returned to the customer — but only when that refund is greater than 0 (a zero refund posts nothing); it appends the corresponding conservation postings, and recomputes the customer's `deposit_held_cents`, since the hold is now closed. Finalizing leaves the settlement's own `version` unchanged.

Separately, a `StoreManager` may waive part or all of a settlement's outstanding fee as a goodwill override. The manager supplies a `waive_amount_cents` to forgive and the `expected_settlement_version` for the concurrency check. The waiver posts a `FEE_WAIVE` for the amount, reduces the settlement's `net_charge_cents` by `waive_amount_cents` floored at 0 so it never goes negative (a waiver larger than the current `net_charge_cents` simply zeroes it), recomputes the customer's `balance_owed_cents`, and advances the settlement's `version` by 1.

### 3.9. Group and Wedding-Party Coordination

A wedding party or costumed group is coordinated through a `PartyOrder`. A `Customer` or `StoreClerk` creates one by naming the `coordinator_customer_id` who runs it, the shared `event_date_iso` every member reservation must match, and the `required_member_count` of confirmed members the party needs before it may lock, which must be at least 1. A new party opens with a `posture` of `FORMING` and a `confirmed_member_count` of 0. The `confirmed_member_count` is always computed as the number of the party's member reservations whose status is one of `CONFIRMED`, `PICKED_UP`, `RETURNED`, `OVERDUE`, or `SETTLED`. The `posture` is derived: it is `LOCKED` once a coordinator has locked it and stays locked until dissolved; it is `DISSOLVED` once dissolved; otherwise it is `READY` when `confirmed_member_count` is at or above `required_member_count`, and `FORMING` when below. As members confirm and cancel, the party flips between `FORMING` and `READY` automatically — rising to `READY` when the confirmed count reaches the required count and dropping back to `FORMING` when it falls below.

Only the coordinator may lock or dissolve the party. Locking is a `Customer` action permitted when the `posture` is `READY` and the acting customer is the `coordinator_customer_id`. These conditions are checked in a fixed order: first the `posture` must be `READY` or the lock is rejected with `ERR_INVALID_STATE`; then the acting customer must be the coordinator or it is rejected with `ERR_NOT_COORDINATOR`; then `expected_party_order_version` must be supplied and match the party's current `version` or the lock is rejected with `ERR_STALE_VERSION`. Locking moves the `posture` from `READY` to `LOCKED`, freezes the member reservations so that `CONFIRMED` members may no longer be cancelled until pickup, and advances the party's `version` by 1. This freeze is enforced at cancellation time: a `CONFIRMED` member reservation whose party is `LOCKED` cannot be cancelled, and the attempt is rejected with `ERR_PARTY_LOCKED`.

Dissolving is a `Customer` action permitted when the `posture` is `FORMING` and the acting customer is the `coordinator_customer_id`; the `posture` is checked first (a non-`FORMING` party is rejected with `ERR_INVALID_STATE`) and only then the acting customer must be the coordinator (a non-coordinator is rejected with `ERR_NOT_COORDINATOR`). Dissolving moves the `posture` from `FORMING` to the terminal `DISSOLVED`, advances the party's `version` by 1, and cascades over the membership: every `PENDING` member reservation is cancelled, and each member that was `CONFIRMED` is also moved to `CANCELLED` and releases its allocated unit from `RESERVED` back to `AVAILABLE`. Unlike the standalone cancel endpoint, this dissolve cascade does not touch any `REQUESTED` alteration on the affected reservations — such alterations are left as-is.

Cancelling a member reservation has party-level consequences in every case. Cancelling is a `Customer` or `StoreClerk` action. A `PENDING` reservation cancels straight to `CANCELLED`; since no unit was ever allocated, there is nothing to release, but if the reservation was party-linked the party's `confirmed_member_count` and `posture` are recomputed and the party's `version` is advanced by 1. A `CONFIRMED` reservation cancels to `CANCELLED` only when its linked party (if any) is not `LOCKED`, otherwise the `ERR_PARTY_LOCKED` rejection applies; on success the allocated unit is released from `RESERVED` back to `AVAILABLE`, any `REQUESTED` alteration on the reservation is moved to `CANCELLED`, and — when party-linked — the party's `confirmed_member_count` and `posture` are recomputed (dropping `READY` back to `FORMING` when the count falls below the required count) and the party's `version` is advanced by 1.

### 3.10. The System Clock and the Overdue Sweep

Because the system reasons about pickup and return windows against the present moment, it maintains a logical clock that a `StoreManager` controls for test-driving. One capability sets the clock to a supplied UTC instant, given as `to_iso8601`, without running any sweep or firing any transitions — it is a pure setup operation. A second capability advances the clock to a supplied `to_iso8601` and runs the overdue-and-cleaning sweep as it does so. The sweep has two effects, processed in `created_at` ascending order across reservations. First, any reservation still `PICKED_UP` whose `return_window_end_iso` the clock has now crossed is flagged `OVERDUE`; as noted in §3.7, this sweep-driven transition creates no settlement and leaves the unit `OUT`, so late fees accrue and the eventual return will create the settlement. Second, any unit `IN_CLEANING` whose `available_from_iso` the clock has now reached or passed is returned to `AVAILABLE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the lifecycle transitions, the clock controls, and the read endpoints — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalogs` | Create a garment style/SKU | StoreManager |
| GET | `/catalogs/{id}` | Get a catalog style | StoreManager, StoreClerk, Customer |
| GET | `/catalogs` | List catalog styles (paginated) | StoreManager, StoreClerk, Customer |
| POST | `/garment-units` | Add a physical unit to a catalog style | StoreManager |
| GET | `/garment-units/{id}` | Get a garment unit | StoreManager, StoreClerk |
| GET | `/garment-units` | List/filter garment units | StoreManager, StoreClerk |
| POST | `/garment-units/{id}/clear-cleaning` | Return a unit from IN_CLEANING to AVAILABLE once the buffer has elapsed | StoreClerk |
| POST | `/garment-units/{id}/retire` | Retire a unit permanently | StoreManager |
| POST | `/customers` | Register a customer | StoreClerk, Customer |
| GET | `/customers/{id}` | Get a customer with computed balances | StoreManager, StoreClerk, Customer |
| POST | `/customers/{id}/measurement-profiles` | Create a measurement profile for a customer | StoreClerk, Customer |
| GET | `/customers/{id}/measurement-profiles` | List a customer's measurement profiles | StoreManager, StoreClerk, Customer |
| GET | `/measurement-profiles/{id}` | Get a measurement profile | StoreManager, StoreClerk, Customer |
| POST | `/reservations` | Book a reservation by event date | StoreClerk, Customer |
| GET | `/reservations/{id}` | Get a reservation | StoreManager, StoreClerk, Customer |
| GET | `/reservations` | List/filter reservations | StoreManager, StoreClerk, Customer |
| POST | `/reservations/{id}/confirm` | Allocate a unit and confirm the reservation | StoreClerk |
| POST | `/reservations/{id}/cancel` | Cancel a reservation | StoreClerk, Customer |
| POST | `/reservations/{id}/pickup` | Hand the garment to the customer | StoreClerk |
| POST | `/reservations/{id}/return` | Record a return; create the settlement and route the reservation | StoreClerk |
| POST | `/alterations` | Request an alteration on a confirmed reservation | StoreClerk, Customer |
| GET | `/alterations/{id}` | Get an alteration | StoreManager, StoreClerk, Customer |
| GET | `/alterations` | List/filter alterations | StoreManager, StoreClerk, Customer |
| POST | `/alterations/{id}/complete` | Mark an alteration completed and charge the fee | StoreClerk |
| POST | `/alterations/{id}/cancel` | Cancel an alteration | StoreClerk, Customer |
| POST | `/fit-checks` | Record a fit check on a confirmed reservation; compute the verdict | StoreClerk |
| GET | `/fit-checks/{id}` | Get a fit check | StoreManager, StoreClerk, Customer |
| GET | `/fit-checks` | List/filter fit checks | StoreManager, StoreClerk, Customer |
| POST | `/party-orders` | Create a group/wedding-party coordination order | Customer, StoreClerk |
| GET | `/party-orders/{id}` | Get a party order with computed posture/count | StoreManager, StoreClerk, Customer |
| GET | `/party-orders` | List/filter party orders | StoreManager, StoreClerk, Customer |
| POST | `/party-orders/{id}/lock` | Coordinator locks the party once READY | Customer |
| POST | `/party-orders/{id}/dissolve` | Coordinator dissolves a FORMING party | Customer |
| GET | `/settlements/{id}` | Get a settlement with computed fee breakdown | StoreManager, StoreClerk, Customer |
| GET | `/settlements` | List/filter settlements | StoreManager, StoreClerk, Customer |
| POST | `/settlements/{id}/finalize` | Finalize a returned/overdue reservation's settlement | StoreClerk |
| POST | `/settlements/{id}/waive-fee` | Manager waives part or all of a settlement's net fee | StoreManager |
| GET | `/ledger-entries/{id}` | Get a single ledger posting | StoreManager, StoreClerk, Customer |
| GET | `/ledger-entries` | List ledger postings | StoreManager, StoreClerk, Customer |
| POST | `/_clock/advance` | Advance the clock and run the overdue + cleaning sweep | StoreManager |
| POST | `/_clock/set` | Set the clock to a fixed instant without sweeping | StoreManager |

The list endpoints accept optional filters in addition to `limit` and `offset`: `/catalogs` filters by `category`; `/garment-units` by `catalog_id`, `status`, and `size_code`; `/reservations` by `customer_id`, `catalog_id`, `garment_unit_id`, `party_order_id`, and `status`; `/alterations` by `reservation_id` and `status`; `/fit-checks` by `reservation_id`, `measurement_profile_id`, and `verdict`; `/party-orders` by `coordinator_customer_id` and `posture`; `/settlements` by `reservation_id` and `disposition`; and `/ledger-entries` by `customer_id`, `reservation_id`, and `entry_type`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_UNIT_AVAILABLE` | 409 |
| `ERR_CUSTOMER_WINDOW_CONFLICT` | 409 |
| `ERR_PARTY_NOT_OPEN` | 409 |
| `ERR_PARTY_LOCKED` | 409 |
| `ERR_NOT_COORDINATOR` | 403 |
| `ERR_FIT_NOT_CLEARED` | 409 |
| `ERR_ALTERATION_PENDING` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_STALE_VERSION` | 412 |

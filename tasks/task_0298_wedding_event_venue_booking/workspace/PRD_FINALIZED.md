# Wedding & Event Venue Booking API — Product Requirements Document

## 1. Introduction

Wedding and large-event bookings are unusually fragile transactions: a single calendar date and a finite set of physical spaces must be held tentatively, then committed, while money moves through a sequence of milestones and a guest count slowly firms up from an early guess into a contractual guarantee. This API exists to coordinate that entire arc on behalf of a venue operator — reserving ceremony and reception space against a shared inventory, enforcing food-and-beverage minimums and deposit schedules, tracking vendor insurance, and absorbing the inevitable reschedules and force-majeure disruptions without ever double-occupying a room or losing track of what a client owes.

The platform serves four distinct constituencies who do not overlap in what they own. Clients shepherd their own celebrations from inquiry to the day itself. Venue coordinators run the operational lifecycle — placing holds, confirming bookings, clearing vendors, and scheduling walkthroughs. Venue administrators configure the bookable inventory (spaces, packages, coordinators) and operate the test clock that drives all deadline arithmetic. Finance officers post payments and refunds. The system's central discipline is that a booking advances along two independent tracks at once — a lifecycle track from inquiry through completion, and a settlement track from unpaid through paid-in-full or refunded — and that every charge, every milestone, and every refund reconciles deterministically from the underlying payment stream rather than from any hand-maintained running total.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a rule below references a specific business workflow, the detailed mechanics live in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `VenueAdmin`, `Coordinator`, `Client`, and `FinanceOfficer`. When a recognized role attempts an operation that its role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles divide ownership cleanly. A `VenueAdmin` owns inventory and configuration — venues, spaces, packages, coordinators — and the test-driving clock. A `Coordinator` is venue-side staff who drives the booking lifecycle, manages holds, vendors, walkthroughs, and reschedule counters. A `Client` is the booking owner who creates bookings, adds vendors, proposes reschedules, and cancels. A `FinanceOfficer` owns payment posting and refunds and may not drive any booking lifecycle transition.

Two of these roles are tied to a persisted entity, and two are not. When `X-User-Role` is `Coordinator`, `X-User-ID` is the `id` of the acting `Coordinator`; ownership checks on any resource that references a coordinator compare that resource's coordinator foreign key to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any booking or booking sub-resource compare the booking's `client_id` to `X-User-ID`. By contrast, when `X-User-Role` is `VenueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may accept and log it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never matched against an entity `id`.

Ownership is enforced as a distinct layer beyond mere role membership. For client-owned operations, the acting `X-User-ID` must equal the target booking's `client_id`; for coordinator operations on a booking, the coordinator must belong to the booking's venue. A violation of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the page begins; it defaults to 0 and has a minimum of 0. A `limit` or `offset` outside its permitted range is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422).

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Every list-based response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Versioning Discipline

Every primary resource carries a system-managed `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded when the resource is first created. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation of the resource. The `version` field underpins both optimistic concurrency (Section 2.6) and the audit trail.

One entity is deliberately leaner. A `Payment` is an immutable ledger event: once posted it is never edited in place (a reversal is expressed as a separate event), so a `Payment` carries only `id` and `created_at` — it has neither `updated_at` nor `version`. Implementers must not invent those two fields for payments. All other entities — `Venue`, `Space`, `Package`, `Client`, `Coordinator`, `Booking`, `SpaceHold`, `PaymentMilestone`, `Vendor`, `GuestCountGuarantee`, `Walkthrough`, and `RescheduleRequest` — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Cascading State

The system maintains strict consistency across the resource hierarchy. When a booking transitions along its lifecycle, child resources are propagated automatically, without the client issuing a separate request against each child. Committing a booking pulls every tentative space hold into a committed posture; cancelling or expiring a booking releases its holds and waives its outstanding milestones; completing a booking cancels any walkthrough still pending. Each such automatic mutation independently refreshes the affected resource's `updated_at` and increments its `version`, exactly as a direct edit would. Whenever a booking's own state, charge fields, or assignments change, the booking's `version` advances by one and its `updated_at` is refreshed.

For any path that names more than one resource (for example, a hold under a booking), identifiers are validated left to right. The first identifier in the path that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper resource is consulted, so a hold addressed under a non-existent booking fails on the booking, not the hold.

### 2.6. Optimistic Concurrency on Hold Creation

Adding a space hold to a booking is the one write in this system guarded by optimistic concurrency control. A request to create a `SpaceHold` against a booking must carry `expected_booking_version`, a non-optional field whose value is the `version` of the parent `Booking` the client last observed. If that value does not match the booking's current `version`, the create is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412). The intent is precise: creating a hold legitimately supersedes the client's earlier choice of space for the same block, so if another writer has already added or replaced a hold for this booking since the client read it, the client's view is stale and must be refreshed rather than allowed to silently double-occupy. No other endpoint takes a version field; only hold creation enforces this check.

### 2.7. The Two-Axis Booking State Model

A `Booking` advances along two independent state axes that never share a field. The lifecycle axis is `booking_status`, which begins at `INQUIRY` and moves through `HELD`, `CONFIRMED`, `GUARANTEED`, and finally to one of the terminal states `COMPLETED` or `CANCELLED`. The settlement axis is `payment_status`, which begins at `UNPAID` and moves among `DEPOSIT_PAID`, `PARTIALLY_PAID`, `PAID_IN_FULL`, and the terminal `REFUNDED`. These axes evolve independently: payment posting drives `payment_status` while lifecycle endpoints drive `booking_status`, and `payment_status` only gates a lifecycle transition where a precondition explicitly says so (confirmation requires a settled deposit; completion requires paid-in-full). Any attempt to drive a transition that is not defined from a resource's current state — whether on `booking_status`, `hold_status`, `vendor_status`, or `request_status` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.8. Monetary Precision and the F&B Charge Discipline

All monetary amounts are stored and returned as integer cents. The two configuration fractions that drive charge math — `service_charge_pct` and `tax_pct` on a package — are applied in a fixed order and rounded at named steps using the round-half-up convention, producing whole-cent results at each step. Rounding is never deferred to the end of a multi-step computation; each named step that the formula calls out is rounded to whole cents before the next step consumes it. The detailed charge formulas, the food-and-beverage minimum floor, and the milestone split all appear in Section 3, but the rounding contract is global: wherever a fraction multiplies a cent amount, the product is rounded half up to a whole number of cents.

### 2.9. Validation Ordering

When several checks could fail on the same request, they are evaluated in a fixed priority so the returned error is deterministic. Authentication comes first: a missing or unrecognized header pair yields `ERR_UNAUTHENTICATED`. Role permission is checked next, yielding `ERR_FORBIDDEN_ROLE`. Resource ownership follows, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of path identifiers comes next (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_REFERENCE_NOT_FOUND`). Only after those gates does the system validate the request body's shape — required fields present and well-typed, enums in range, numeric bounds satisfied — yielding `ERR_INVALID_REQUEST`. Time-window ordering is validated next (`ERR_INVALID_TIME_WINDOW`), then the target's state admissibility (`ERR_INVALID_STATE`), then the optimistic-concurrency version match (`ERR_STALE_BOOKING_VERSION`). Domain-specific business rules — capacity, space-kind compatibility, double-booking, walkthrough conflicts, coordinator capacity, vendor insurance, guarantee deadlines, deposit settlement, outstanding balance, overpayment, and reschedule exclusivity — are evaluated after that ordered front matter. In short: authentication, then role, then ownership, then path existence, then reference existence, then request shape, then time windows, then state, then version, then the business constraints.

## 3. Business Logic & Workflows

### 3.1. Building the Bookable Inventory

Before any celebration can be booked, a `VenueAdmin` stands up the inventory. A venue is created with a `name`, an optional IANA `timezone` (defaulting to `America/New_York`, and used to interpret event-day deadlines such as the guarantee cutoff and COI windows), an optional `cancellation_tier` drawn from `STANDARD`, `STRICT`, or `FLEXIBLE` (defaulting to `STANDARD`), and an optional `force_majeure_fee_pct` between 0.0 and 0.25 inclusive (defaulting to 0.0). A venue's `status` is system-managed, beginning `ACTIVE` and moving to `ARCHIVED` when the venue is archived; archiving hides the venue from new bookings but preserves bookings already in flight.

Within a venue, the admin defines spaces and packages. A `Space` carries a `venue_id`, a `name`, a `space_kind` of `CEREMONY`, `RECEPTION`, or `DUAL`, an integer `max_capacity` of at least 1, an integer `base_rental_cents` of at least 0, and an optional `turnover_buffer_minutes` (at least 0, defaulting to 0) that fixes the minimum gap required after one occupation ends before the next may begin on the same space. A space's `status` is system-managed (`ACTIVE` then `ARCHIVED`); archiving blocks new holds but keeps existing ones. A `Package` carries a `venue_id`, a `tier` of `SILVER`, `GOLD`, or `PLATINUM`, an integer `per_head_cents` of at least 0, an integer `fb_minimum_cents` of at least 0 representing the food-and-beverage minimum spend the booking must meet regardless of head count, an optional `service_charge_pct` between 0.0 and 0.50 inclusive (defaulting to 0.22), and an optional `tax_pct` between 0.0 and 0.30 inclusive (defaulting to 0.08). A package's `status` likewise runs `ACTIVE` then `ARCHIVED`, preserving bookings already on it. The admin also registers coordinators: a `Coordinator` carries a `venue_id`, a `full_name`, and an optional `active_booking_cap` (at least 1, defaulting to 8) that caps how many non-terminal bookings the coordinator may carry. A coordinator's `assigned_active_count` is a derived field — the live count of bookings assigned to that coordinator whose `booking_status` is neither `COMPLETED` nor `CANCELLED` — and begins at 0.

Clients register independently of venues. A `Client` carries a `full_name` and an `email`; the email must be a valid address and unique across all clients. Either a `VenueAdmin` or the `Client` themselves may register the account. When a write body references a parent that does not exist or is `ARCHIVED` — a venue, package, space, or client — the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 3.2. Opening a Booking and the Inquiry Stage

A booking begins as an inquiry. Either a `Client` or a `Coordinator` opens it by supplying the `client_id` who owns it, the `venue_id` and `package_id` being booked, an `event_date` (a calendar date in YYYY-MM-DD form on which both ceremony and reception occur), the four block instants `ceremony_start`, `ceremony_end`, `reception_start`, and `reception_end` (each an ISO 8601 UTC datetime), and an `expected_guest_count` of at least 1 representing the early estimate used for the provisional charge. On creation the booking lands at `booking_status` `INQUIRY` and `payment_status` `UNPAID`; its `coordinator_id` is null until assigned.

The block instants must obey a strict ordering: `ceremony_start` must be before `ceremony_end`, `ceremony_end` must be at or before `reception_start`, and `reception_start` must be before `reception_end`. Furthermore, `event_date` must be strictly in the future relative to the current clock at the moment of creation. Any violation of this block ordering, or an event date not strictly in the future, is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 422). Separately, the early estimate is bounded by physical reality: `expected_guest_count` must not exceed the seated `max_capacity` of the reception space, and a booking whose guest count overruns capacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422); this same capacity ceiling is re-checked at guarantee time and at reschedule approval.

A coordinator is attached to a booking through an assignment action available to a `VenueAdmin` or a `Coordinator`, which supplies the `coordinator_id` to bind. Assignment sets the booking's `coordinator_id` and folds the booking into that coordinator's live load. The coordinator's `assigned_active_count` is recomputed as the number of bookings assigned to them whose `booking_status` is not `COMPLETED` and not `CANCELLED`. An assignment that would push `assigned_active_count` above the coordinator's `active_booking_cap` is rejected with `ERR_COORDINATOR_AT_CAPACITY` (HTTP 409). When a booking later reaches a terminal lifecycle state, its coordinator's count drops accordingly — completion explicitly decrements `assigned_active_count` by one as part of the bubble-up.

A booking still at `INQUIRY` may be cancelled outright by the `Client` (or coordinator acting on their behalf); this moves `booking_status` from `INQUIRY` to `CANCELLED` and records `cancelled_reason` as `CLIENT_CANCEL`. Because no holds or money exist yet, nothing else cascades.

### 3.3. Reserving Space: Holds, Conflicts, and the Soft Hold

Space is reserved through `SpaceHold` records, each created by a `Coordinator` against a booking. A hold names the `space_id` to occupy and the `block_role` it covers, either `CEREMONY` or `RECEPTION`, and must carry `expected_booking_version` for the concurrency check described in Section 2.6. On creation the hold's `occupy_start` and `occupy_end` are copied by the system from the booking's matching block — the ceremony block instants for a `CEREMONY` hold, the reception block instants for a `RECEPTION` hold — and the hold's `hold_status` starts at `HELD`. A `booking_id` ties each hold to its booking.

Two business rules guard hold creation beyond the version check. First, the requested block must be compatible with the space: a `CEREMONY` hold requires the space's `space_kind` to be `CEREMONY` or `DUAL`, and a `RECEPTION` hold requires `space_kind` to be `RECEPTION` or `DUAL`; an incompatible pairing is rejected with `ERR_SPACE_KIND_MISMATCH` (HTTP 422). Second, the occupation must not collide with any other booking's blocking hold on the same space. Overlap is judged on the occupation interval extended by the space's `turnover_buffer_minutes`: a new occupation may not begin until at least that many minutes have elapsed after a conflicting occupation ends on that space. A collision is rejected with `ERR_SPACE_DOUBLE_BOOKED` (HTTP 409). The same double-booking check is re-run when a reschedule is approved and the committed blocks move.

Once at least one `HELD` hold covering a `CEREMONY` block and at least one `HELD` hold covering a `RECEPTION` block both exist for the booking, a `Coordinator` may place the soft hold — the transition that advances `booking_status` from `INQUIRY` to `HELD`. Placing the hold is permitted only while the booking is `INQUIRY` and only while both the venue and the package are `ACTIVE`. It sets `hold_expires_at` to the current clock plus the standard soft-hold window of six hours, after which an unconfirmed hold lapses. A `Coordinator` may also explicitly release a single `HELD` hold; releasing transitions that hold's `hold_status` from `HELD` to `RELEASED` and frees its space-date interval for others.

If the booking is cancelled while `HELD`, every hold still in `HELD` is released (its `hold_status` becomes `RELEASED`), `cancelled_reason` is set to `CLIENT_CANCEL`, and `hold_expires_at` is cleared to null. The soft hold can also lapse on its own. A `VenueAdmin` advances the test clock by supplying the target instant as `to_iso8601`; then a `VenueAdmin` or `Coordinator` may run the expire-hold sweep against the booking. If the booking is `HELD` and the current clock has reached or passed `hold_expires_at`, the sweep moves `booking_status` from `HELD` to `CANCELLED`, releases every `HELD` hold to `RELEASED`, records `cancelled_reason` as `NONPAYMENT`, and clears `hold_expires_at`. A sweep on a booking whose hold has not yet lapsed makes no change.

### 3.4. Confirmation, Deposits, and the Provisional Charge

Confirmation is the hinge of the booking. A `Coordinator` confirms a booking that is `HELD`, advancing `booking_status` to `CONFIRMED`. Confirmation is permitted only when the booking is `HELD`, the current clock is still before `hold_expires_at` (the hold has not lapsed), a coordinator is assigned (`coordinator_id` is not null), and the deposit has been settled — that is, `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL`. If the deposit milestone is not yet settled at confirm time, the request is rejected with `ERR_DEPOSIT_NOT_SETTLED` (HTTP 402).

When confirmation succeeds, several things cascade. Every `SpaceHold` of the booking still in `HELD` is committed — its `hold_status` becomes `COMMITTED`, hardening it into a conflict blocker against other bookings — and `hold_expires_at` is cleared to null. The system computes the provisional event charge and stores it on `event_charge_cents`, then builds the milestone schedule. The provisional charge is forward-looking and uses the early estimate rather than any guarantee. Concretely: the billable head count equals `expected_guest_count`; the food-and-beverage subtotal is the larger of that head count multiplied by the package's `per_head_cents` and the package's `fb_minimum_cents` (so the minimum floor binds whenever the per-head total falls short). The service charge equals the food-and-beverage subtotal multiplied by `service_charge_pct`, rounded half up to whole cents. The taxed base is the food-and-beverage subtotal plus that service charge, and the tax equals the taxed base multiplied by `tax_pct`, rounded half up to whole cents — service first, then tax on the serviced amount, in that pinned order. Rental is the sum of `base_rental_cents` across each distinct space among the booking's holds whose `hold_status` is `HELD` or `COMMITTED`; counting distinct spaces means a ceremony-plus-reception pair sharing one `DUAL` space is charged rental exactly once. The provisional `event_charge_cents` is the food-and-beverage subtotal plus the service charge plus the tax plus the rental. This same provisional computation is re-run if the package changes while the booking is still `CONFIRMED`.

### 3.5. The Payment Stream, Milestones, and Settlement

Money is recorded as a stream of `Payment` events, each posted by a `FinanceOfficer` against a booking. A payment names its `direction` — `INBOUND` when the client pays the venue, `OUTBOUND` when the venue refunds the client — a positive `amount_cents` of at least 1, and a `method` of `CARD`, `ACH`, `CHECK`, or `WIRE`. Its `status` begins `POSTED` and may become `VOIDED` if reversed before settlement, and its `posted_at` records the UTC instant of posting. The booking's `amount_paid_cents` is always derived from this stream: it is the sum of `amount_cents` over `INBOUND` payments with `status` `POSTED`, minus the sum over `OUTBOUND` payments with `status` `POSTED`. The booking's `balance_due_cents` is `event_charge_cents` minus `amount_paid_cents`, and may go negative when an overpayment is pending refund. An `INBOUND` payment may not exceed the current `balance_due_cents`; an attempt to pay more than the contracted charge leaves outstanding is rejected with `ERR_OVERPAYMENT` (HTTP 422).

The milestone schedule is built at confirmation and rebuilt at guarantee. The current `event_charge_cents` is split across three milestones by fixed fractions. The deposit milestone (sequence 1, `kind` `DEPOSIT`) takes 25 percent of the event charge, rounded half up. The interim milestone (sequence 2, `kind` `INTERIM`) takes 35 percent, rounded half up. The final milestone (sequence 3, `kind` `FINAL`) takes whatever remains — the event charge minus the deposit amount minus the interim amount — so it absorbs every rounding remainder and the three `amount_due_cents` values sum exactly to `event_charge_cents`; the final milestone is never independently rounded. Each milestone carries its `booking_id`, its `kind`, its `sequence`, its computed `amount_due_cents`, an `amount_allocated_cents` (how much posted money has been applied to it, starting at 0), a `due_date` calendar date, and a `milestone_status`. The deposit milestone's `due_date` defaults to the confirmation date and must be settled before the booking can be confirmed.

Posted payments are allocated to milestones by a waterfall. Net inbound money — `INBOUND` `POSTED` payments less `OUTBOUND` `POSTED` payments — is applied across milestones in ascending `sequence`: the sequence-1 milestone is filled to its `amount_due_cents` first, any overflow spills to sequence 2, then to sequence 3. Payments are processed in chronological order, ordered by `posted_at` ascending and then by `created_at` ascending, and only non-`WAIVED` milestones participate. Each milestone's `milestone_status` is derived from the result: `SETTLED` when `amount_allocated_cents` equals `amount_due_cents`, `PARTIAL` when allocation is positive but short of the amount due, and `OPEN` when nothing has been allocated. A milestone may also be `WAIVED` when a cancellation or force-majeure zeroes it out.

The settlement axis tracks this allocation. The booking begins `UNPAID`. It moves to `DEPOSIT_PAID` once the deposit milestone (sequence 1) is `SETTLED` after allocation while at least one of the interim or final milestones remains unsettled. It moves from `DEPOSIT_PAID` to `PARTIALLY_PAID` when a further inbound payment carries `amount_paid_cents` above the deposit milestone's `amount_due_cents` yet still below `event_charge_cents`. It reaches `PAID_IN_FULL` when `amount_paid_cents` is at least `event_charge_cents` (with a positive event charge) and every milestone is `SETTLED` or `WAIVED` — reachable either by progressing from `PARTIALLY_PAID` or by a single large inbound payment that settles all milestones at once directly from `DEPOSIT_PAID`. The terminal `REFUNDED` state is reached only on a cancelled booking: from `PAID_IN_FULL`, `PARTIALLY_PAID`, or `DEPOSIT_PAID`, when outbound refunds have netted `amount_paid_cents` back to zero and the booking is `CANCELLED`. Each of these settlement transitions is a system recompute after a payment posting or milestone re-allocation, and each increments the booking's `version`.

### 3.6. Vendors and Certificate-of-Insurance Clearance

A booking carries a vendor list, and required vendors must clear insurance before the guest count can be guaranteed. A `Coordinator` or `Client` adds a `Vendor` to a booking by supplying a `company_name` and a `vendor_role` from `CATERING`, `FLORAL`, `PHOTOGRAPHY`, `MUSIC`, `RENTAL`, or `OTHER`. The system derives `coi_required` — whether a Certificate of Insurance is mandatory for that role at that venue — and the vendor starts with `coi_on_file` false, `coi_expires_on` null, and `vendor_status` `PENDING`.

Clearance turns on a date comparison. A `Coordinator` uploads a Certificate of Insurance by supplying its `coi_expires_on` date. If the uploaded `coi_expires_on` is on or after the booking's `event_date`, the vendor moves to `CLEARED`, with `coi_on_file` set true and `coi_expires_on` recorded from the upload. If the uploaded certificate expires before the event date, the upload is rejected with `ERR_COI_EXPIRES_BEFORE_EVENT` (HTTP 422) only when the vendor is not already `CLEARED`; a vendor already `CLEARED` does not reject on such an upload but instead bounces back to `PENDING`, the upload succeeding with HTTP 200, `coi_on_file` set false, and the new (early) `coi_expires_on` recorded from the upload. A vendor already `CLEARED` can therefore bounce back to `PENDING` — either through an upload whose new `coi_expires_on` falls before `event_date`, or through system revalidation when a reschedule moves `event_date` later than the existing `coi_expires_on`; in that bounce `coi_on_file` is set false. A `Coordinator` may also reject a vendor from either `PENDING` or `CLEARED`, moving `vendor_status` to `REJECTED` and excluding it from the booking's cleared-vendor set.

### 3.7. The Guest-Count Guarantee and the Final Charge

The guarantee is where the early estimate hardens into a contractual floor. A `Coordinator` locks the guarantee on a `CONFIRMED` booking by supplying the `guaranteed_count` — the final guaranteed head count the food-and-beverage charge is computed against — which creates a `GuestCountGuarantee` carrying its `booking_id`, the `guaranteed_count`, a derived `guarantee_deadline`, and a `locked_at` instant. The `guarantee_deadline` is a calendar date derived as the `event_date` minus the venue's guarantee window, and the guarantee may only be locked on or before that deadline; an attempt after the deadline is rejected with `ERR_GUARANTEE_DEADLINE_PASSED` (HTTP 409). The guarantee transition advances `booking_status` from `CONFIRMED` to `GUARANTEED`.

Three preconditions gate the guarantee. The booking must be `CONFIRMED`; the current clock's date must be at or before the `guarantee_deadline`; every vendor of the booking whose `coi_required` is true must be `CLEARED` (no `PENDING` or `REJECTED` required-COI vendor may remain, else `ERR_VENDOR_COI_MISSING`, HTTP 409); and no `DEPOSIT`-kind milestone may still be `OPEN`. The guaranteed count is also bounded by the reception space's seated `max_capacity` — a guarantee that exceeds capacity is rejected with `ERR_CAPACITY_EXCEEDED`.

When the guarantee locks, the charge switches variants. The final event charge bills the food-and-beverage against the `guaranteed_count`, which is the contractual floor the client pays even if fewer guests attend; the guaranteed count replaces `expected_guest_count` entirely and is not blended with it. Concretely: the billable head count is `guaranteed_count`; the food-and-beverage subtotal is the larger of that count multiplied by `per_head_cents` and the package's `fb_minimum_cents`; the service charge is that subtotal multiplied by `service_charge_pct`, rounded half up to whole cents; the tax is the subtotal plus the service charge, multiplied by `tax_pct`, rounded half up to whole cents; the rental is the sum of `base_rental_cents` across each distinct space among the booking's `COMMITTED` holds. The final `event_charge_cents` is the subtotal plus the service charge plus the tax plus the rental, and it differs from the provisional figure whenever `guaranteed_count` differs from `expected_guest_count` or the minimum floor binds differently between the two. Locking the guarantee recomputes every milestone's `amount_due_cents` from the new event charge, re-runs the waterfall allocation, sets the guarantee's `locked_at` to the current clock, and increments the booking's `version`.

### 3.8. Walkthroughs and the Coordinator Calendar

A `Coordinator` schedules a `Walkthrough` against a booking by supplying a `scheduled_start` and a `scheduled_end`, both ISO 8601 UTC datetimes; the end must be after the start, and a violation is rejected with `ERR_INVALID_TIME_WINDOW`. A walkthrough carries its `booking_id` and a `walkthrough_status` that begins `SCHEDULED` and may later become `COMPLETED` or `CANCELLED`. Two further constraints apply. The appointment must fall strictly before the booking's `event_date`; a walkthrough scheduled on or after the event date is rejected with `ERR_WALKTHROUGH_AFTER_EVENT` (HTTP 422). And the appointment must not overlap another `SCHEDULED` walkthrough on the same coordinator's calendar; a clash is rejected with `ERR_WALKTHROUGH_CONFLICT` (HTTP 409). When a booking completes, every walkthrough still `SCHEDULED` is moved to `CANCELLED` as part of the completion cascade.

### 3.9. Completion and Cancellation with Refunds

Completion closes a booking after the event. A `Coordinator` completes a booking that is `GUARANTEED`, advancing `booking_status` to `COMPLETED`. Completion is permitted only when the booking is `GUARANTEED`, the current clock's date is strictly past `event_date` (the event has occurred), and `payment_status` is `PAID_IN_FULL`; an outstanding balance at completion is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 402). Completion cancels every still-`SCHEDULED` walkthrough, decrements the assigned coordinator's `assigned_active_count` by one, and increments the booking's `version`.

Cancellation is available to the `Client` (or a coordinator on their behalf) from `HELD`, `CONFIRMED`, or `GUARANTEED`, and each path cascades according to how much commitment exists. From `HELD`, holds in `HELD` are released to `RELEASED`, `cancelled_reason` is set to `CLIENT_CANCEL`, and `hold_expires_at` is cleared. From `CONFIRMED`, every hold in `HELD` or `COMMITTED` is released to `RELEASED` (freeing inventory), every non-terminal `PaymentMilestone` is set to `WAIVED`, a cancellation refund is computed and posted as an `OUTBOUND` `Payment`, and `cancelled_reason` is set to `CLIENT_CANCEL`. From `GUARANTEED`, the same hold release, milestone waiver, refund posting, and reason recording apply. In every cancellation that posts a refund, that outbound payment triggers a `payment_status` recompute, and if all inbound funds have been returned the booking lands at `REFUNDED`. Every cancellation increments the booking's `version`.

The refund amount is governed by a retention table keyed on the venue's `cancellation_tier` and the `booking_status` at the instant of cancel. Let the net inbound amount be the booking's `amount_paid_cents` before the refund. The retained fraction is read from the table: for a `STANDARD` tier the retention is 0 percent when cancelling from `HELD`, 25 percent from `CONFIRMED`, and 50 percent from `GUARANTEED`; for a `STRICT` tier it is 0 percent from `HELD`, 50 percent from `CONFIRMED`, and 100 percent from `GUARANTEED`; for a `FLEXIBLE` tier it is 0 percent from `HELD`, 0 percent from `CONFIRMED`, and 25 percent from `GUARANTEED`. The retained amount is the net inbound multiplied by that fraction, rounded half up to whole cents, and the refund is the net inbound minus the retained amount; an `OUTBOUND` payment is posted for that refund whenever it is positive. (A `STRICT`-tier cancellation from `GUARANTEED` therefore retains everything and refunds nothing.)

### 3.10. Rescheduling and Force Majeure

Dates move, and the system models the negotiation as a chain of `RescheduleRequest` rounds. A `Client` proposes a reschedule against their booking by supplying a `reason_kind` of `CLIENT_REQUEST` (an ordinary date move) or `FORCE_MAJEURE` (a qualifying disruption with fee relief), the proposed new schedule (`proposed_event_date`, `proposed_ceremony_start`, `proposed_ceremony_end`, `proposed_reception_start`, `proposed_reception_end`), and optionally a `supersedes_request_id` pointing at a prior round being replaced. A fresh request starts at `request_status` `PROPOSED`. Only one active request — one in `PROPOSED` or `COUNTERED` — may exist per booking at a time; proposing a second, non-superseding request while one is active is rejected with `ERR_RESCHEDULE_IN_PROGRESS` (HTTP 409). The proposed block times are subject to the same time-window ordering as a fresh booking, rejected with `ERR_INVALID_TIME_WINDOW` if out of order.

The venue side may counter. A `Coordinator` counters a `PROPOSED` request — permitted only when the request is `PROPOSED` and the parent booking is `CONFIRMED` or `GUARANTEED` — by supplying alternate `proposed_event_date`, `proposed_ceremony_start`, `proposed_ceremony_end`, `proposed_reception_start`, and `proposed_reception_end`, moving `request_status` from `PROPOSED` to `COUNTERED` and recording those counter times on the request. The client may answer a counter by re-proposing a new round whose `supersedes_request_id` points at the countered request; doing so withdraws the superseded request (its `request_status` becomes `WITHDRAWN`) and opens a fresh `PROPOSED` round, which is how the cyclic negotiation chains through `supersedes_request_id`.

Approval is the consequential step. A `Coordinator` approves a `PROPOSED` request; a `Client` approves a `COUNTERED` request (accepting the venue's counter). Approval carries `expected_booking_version`. Approving a `PROPOSED` request requires that no other `PROPOSED` or `COUNTERED` request exists for the booking and that the proposed block times pass the space-date overlap check against the target space (excluding this booking's own holds), rejected with `ERR_SPACE_DOUBLE_BOOKED` on a collision; approving a `COUNTERED` request likewise re-checks overlap on the counter times. On approval, the booking's `event_date` and all four block instants are rewritten to the approved values; every `COMMITTED` hold of the booking has its old interval released and a fresh `COMMITTED` hold re-created at the new interval; the guarantee's `guarantee_deadline` is re-derived from the new `event_date`; and every vendor is revalidated, so any vendor whose `coi_expires_on` now falls before the new `event_date` bounces from `CLEARED` to `PENDING`. The post-move guest count is re-checked against reception capacity, rejected with `ERR_CAPACITY_EXCEEDED` if it overruns. Approval increments the booking's `version`.

Force majeure changes the money. When an approved reschedule carries `reason_kind` `FORCE_MAJEURE`, instead of the tier retention table the venue retains `force_majeure_fee_pct` of `amount_paid_cents` as its administrative fee — that retained amount is the net inbound multiplied by `force_majeure_fee_pct`, rounded half up to whole cents — and the venue posts an `OUTBOUND` `Payment` refunding only the overpayment beyond the new `event_charge_cents`. This is the force-majeure remainder branch of the refund logic, distinct from an ordinary cancellation refund.

A reschedule round may also simply end. A `Coordinator` may decline a `PROPOSED` request, moving it to `DECLINED` with no change to the booking's block times. A `Client` may withdraw a request from either `PROPOSED` or `COUNTERED`, moving it to `WITHDRAWN`, again leaving the booking's block times untouched.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, uploads, and state changes — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue | VenueAdmin |
| GET | `/venues/{id}` | Fetch a venue | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/venues/{id}/archive` | Archive a venue (blocks new bookings) | VenueAdmin |
| POST | `/venues/{id}/spaces` | Create a bookable space under a venue | VenueAdmin |
| GET | `/venues/{id}/spaces` | List spaces under a venue | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/venues/{id}/packages` | Create an F&B package under a venue | VenueAdmin |
| GET | `/venues/{id}/packages` | List packages under a venue | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/venues/{id}/coordinators` | Create a coordinator under a venue | VenueAdmin |
| GET | `/venues/{id}/coordinators` | List coordinators under a venue | VenueAdmin, Coordinator, Client, FinanceOfficer |
| GET | `/coordinators/{id}` | Fetch a coordinator (with computed load) | VenueAdmin, Coordinator, FinanceOfficer |
| POST | `/clients` | Register a client account | VenueAdmin, Client |
| GET | `/clients/{id}` | Fetch a client | VenueAdmin, Client, Coordinator |
| POST | `/bookings` | Create a booking inquiry | Client, Coordinator |
| GET | `/bookings/{id}` | Fetch a booking with computed charge fields | VenueAdmin, Coordinator, Client, FinanceOfficer |
| GET | `/bookings` | List bookings (filterable) | VenueAdmin, Coordinator, FinanceOfficer |
| POST | `/bookings/{id}/assign-coordinator` | Assign a coordinator to a booking | VenueAdmin, Coordinator |
| POST | `/bookings/{id}/holds` | Create a SpaceHold for a block | Coordinator |
| GET | `/bookings/{id}/holds` | List SpaceHolds for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| GET | `/holds` | List SpaceHolds (filterable by space or booking) | VenueAdmin, Coordinator, FinanceOfficer |
| GET | `/holds/{id}` | Fetch a single SpaceHold | VenueAdmin, Coordinator, Client, FinanceOfficer |
| DELETE | `/bookings/{id}/holds/{holdId}` | Release a HELD SpaceHold explicitly | Coordinator |
| POST | `/bookings/{id}/place-hold` | Transition booking to the soft-hold state | Coordinator |
| POST | `/bookings/{id}/confirm` | Confirm a booking; commit holds, build milestones | Coordinator |
| POST | `/bookings/{id}/guarantee` | Lock the guest-count guarantee; switch to final charge | Coordinator |
| GET | `/bookings/{id}/guarantee` | Fetch the guarantee for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/bookings/{id}/complete` | Complete a booking after the event | Coordinator |
| POST | `/bookings/{id}/cancel` | Cancel a booking | Client, Coordinator |
| GET | `/bookings/{id}/milestones` | List payment milestones for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/bookings/{id}/payments` | Post a payment (inbound or refund) | FinanceOfficer |
| GET | `/bookings/{id}/payments` | List payments for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/bookings/{id}/vendors` | Add a vendor to the booking's vendor list | Coordinator, Client |
| GET | `/bookings/{id}/vendors` | List vendors for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/vendors/{id}/coi` | Upload/replace a Certificate of Insurance | Coordinator |
| POST | `/vendors/{id}/reject` | Reject a vendor | Coordinator |
| POST | `/bookings/{id}/walkthroughs` | Schedule a walkthrough appointment | Coordinator |
| GET | `/bookings/{id}/walkthroughs` | List walkthroughs for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/bookings/{id}/reschedule-requests` | Propose a reschedule | Client |
| GET | `/bookings/{id}/reschedule-requests` | List reschedule requests for a booking | VenueAdmin, Coordinator, Client, FinanceOfficer |
| GET | `/reschedule-requests` | List reschedule requests (filterable) | VenueAdmin, Coordinator, Client, FinanceOfficer |
| GET | `/reschedule-requests/{id}` | Fetch a single reschedule request | VenueAdmin, Coordinator, Client, FinanceOfficer |
| POST | `/reschedule-requests/{id}/counter` | Venue counters a proposed reschedule | Coordinator |
| POST | `/reschedule-requests/{id}/approve` | Approve a reschedule; rewrite block times | Coordinator, Client |
| POST | `/reschedule-requests/{id}/decline` | Decline a proposed reschedule | Coordinator |
| POST | `/reschedule-requests/{id}/withdraw` | Withdraw a proposed or countered reschedule | Client |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | VenueAdmin |
| POST | `/bookings/{id}/expire-hold` | System sweep: expire a lapsed soft hold | VenueAdmin, Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_BOOKING_VERSION` | 412 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_SPACE_KIND_MISMATCH` | 422 |
| `ERR_SPACE_DOUBLE_BOOKED` | 409 |
| `ERR_WALKTHROUGH_CONFLICT` | 409 |
| `ERR_COORDINATOR_AT_CAPACITY` | 409 |
| `ERR_VENDOR_COI_MISSING` | 409 |
| `ERR_GUARANTEE_DEADLINE_PASSED` | 409 |
| `ERR_DEPOSIT_NOT_SETTLED` | 402 |
| `ERR_BALANCE_OUTSTANDING` | 402 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_RESCHEDULE_IN_PROGRESS` | 409 |
| `ERR_WALKTHROUGH_AFTER_EVENT` | 422 |
| `ERR_COI_EXPIRES_BEFORE_EVENT` | 422 |
| `ERR_VALIDATION_LIMIT` | 422 |

# Wedding & Event Planning API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Wedding & Event Planning API, the operational backbone of a full-service event-planning practice. The system carries a single client engagement end to end: from the initial service package and signed contract, through budgeting and vendor selection, insurance tracking, run-of-show timelines, guest management and reception seating, day-of staffing, and finally either the completion of a delivered event or its cancellation. Every planning artifact — the contract, each vendor booking, each guest, each table, each staff shift — is a first-class resource, and the interactions between them (a booking that cannot proceed without verified insurance, a cancellation that must unwind payments and restore a budget, a declined guest whose seat must be released) are where the real complexity lives.

All resources are addressed as peer collections beneath a shared `/planning` namespace and are linked to one another by explicit identifier fields carried in request bodies rather than by nested URL paths. A resource's related children are discovered through filtered list queries. The remainder of this document is organized into system-wide specifications that hold for every endpoint (Section 2), the business workflows and calculation rules that make up the planning lifecycle (Section 3), a consolidated endpoint reference (Section 4), and the catalogue of error identifiers the API may return (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is absent, or if `X-User-Role` does not name one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_HEADERS`. The system recognizes exactly three roles: `Planner`, `Client`, and `Vendor`. When a well-identified principal attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The `Planner` is the full-service operator who drives the engagement. When `X-User-Role` is `Planner`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any resource's identifier. The `Planner` may create and drive events, author and progress contracts, maintain the vendor directory, verify insurance, propose and book vendors, record payments, build timelines, manage tables and seating, roster staff, and advance the logical clock.

The `Client` represents the couple or hosts of a single event. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `EventProject`; any ownership check on a resource that references an event compares that resource's `event_id` to `X-User-ID`. A `Client` may sign their own event's contract, request revisions to it, and add or update guests and their RSVPs on their own event. The `Vendor` represents an individual supplier. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`; any ownership check compares the referenced `vendor_id` to `X-User-ID`. A `Vendor` may submit Certificates of Insurance for their own vendor record. Whenever an entity-backed principal (`Client` or `Vendor`) acts on a resource whose owning identifier does not equal their `X-User-ID`, the request is rejected with `ERR_OWNERSHIP_VIOLATION`. All three roles may read every list and detail endpoint.

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

### 2.3. Pagination and List Filtering

Every list endpoint is paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints accept domain filters that narrow the result set: events may be filtered by `status`; vendors by `category`; contracts, tables, and staff members by `event_id`; guests by `event_id` and by `rsvp_status`; timeline blocks by `event_id` and by `zone`; vendor bookings by `event_id` and by `vendor_id`; vendor payments by `vendor_booking_id`; seat assignments by `event_id`, `guest_id`, and `table_id`; staff assignments by `event_id` and by `staff_member_id`; and COIs by `vendor_id`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp that is refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 when the resource is created and increments by one on every subsequent mutation.

The `version` is more than an audit aid: any change to a resource — including a change to one of its *computed* fields driven by activity elsewhere — counts as a mutation and therefore refreshes `updated_at` and increments `version`. When a vendor booking is booked and the parent event's rolled-up budget figures change, that event has been mutated. This versioning behavior is the foundation of the optimistic-concurrency guard described in Section 2.8.

### 2.5. Monetary Amounts and Rounding Discipline

All monetary quantities in the system are stored and returned as integer numbers of cents; there are no fractional cents. Wherever a calculation multiplies a monetary amount by a rate and the exact product is not a whole number of cents, the result is rounded half up to the nearest whole cent — that is, a residual of exactly one half-cent rounds away from zero, upward. This rounding rule governs planner fees, vendor deposits, cancellation fees, and staff labor costs alike.

One rounding-order convention deserves emphasis because it affects reconciliation exactness: when a contracted cost is split into a deposit and a balance, the deposit is rounded first and the balance is then taken as the exact remainder, never independently re-rounded. This guarantees that a booking's deposit and balance always sum back to its contracted cost to the cent.

### 2.6. The Logical Clock and Insurance Expiry

The server keeps a single logical clock that is the sole source of "now" for every time-dependent rule — event-date comparisons, insurance validity, cancellation-fee tiering, and the timestamps stamped onto signatures and payments. At startup the clock reads exactly `2026-03-01T00:00:00Z`; until it is explicitly set it holds that value and never falls back to wall-clock time. An operator-only capability sets the clock to a supplied `to_iso8601` instant.

Setting the clock is not merely bookkeeping: every time the clock is set, the server sweeps the insurance records. Any COI whose `coverage_expiry_date` is at or before the new clock value transitions to `EXPIRED`, regardless of whether it was previously `PENDING` or `VERIFIED`. This sweep is the only path by which a COI becomes `EXPIRED`, and it fires as an immediate side effect of the clock being set.

### 2.7. Request Processing Order and Existence Resolution

Every request is validated through a fixed sequence of gates, and the first gate that fails determines the response. The order is: (1) header authentication, returning `ERR_MISSING_OR_INVALID_HEADERS` on failure; (2) role authorization against the operation, returning `ERR_UNAUTHORIZED`; (3) ownership for entity-backed roles, returning `ERR_OWNERSHIP_VIOLATION`; (4) existence of every resource identifier referenced by the request; (5) well-formedness of the request body, returning `ERR_VALIDATION`; (6) interval well-formedness for endpoints that accept a time interval, returning `ERR_INVALID_INTERVAL`; (7) the optimistic-concurrency check on contract creation, returning `ERR_STALE_EVENT_VERSION`; and (8) the legality of the requested state transition, returning the transition-specific conflict error. Only after all of these pass does the system evaluate the endpoint-specific business rules described in Section 3.

The existence gate resolves identifiers left to right in the order they appear — path identifier first, then body identifiers in their listed order — and reports the first one that does not resolve using the not-found error for that resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND` for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block, `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table, `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND` for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment. A request that names a missing event and a missing table fails on the event first. Body well-formedness means required fields are present, every enumerated field holds a permitted member, and every integer field that must be non-negative is non-negative; violations return `ERR_VALIDATION`.

### 2.8. Optimistic Concurrency on Contract Creation

Creating a contract for an event is the one write in the system that carries an optimistic-concurrency guard, because it supersedes whatever contract the event currently points to. A contract-creation request must include `expected_event_version`, carrying the `version` of the target `EventProject` that the client last observed. Before any business processing on this path, the server compares `expected_event_version` to the event's current `version`; if the two differ, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412).

The reason this matters is the supersede mechanic itself. A successful contract creation voids the event's prior active contract, repoints `active_contract_id` at the new contract, and increments the event's `version` by one. Consequently, a second creation request that still carries the pre-supersede `version` is, by definition, stale — it was formed before the earlier creation advanced the event — and is rejected. This lets a planner supersede a contract without silently discarding an arrangement they have not yet seen. No other endpoint requires or consumes a version field.

### 2.9. Budget, Headcount, and Seat Reconciliation

Several fields on an event and on a table are *derived*: they are never written directly by a client but are recomputed by the system whenever the underlying facts change. On an `EventProject`, the computed fields are `committed_spend_cents`, `projected_spend_cents`, `budget_balance_cents`, `total_deposits_due_cents`, `estimated_headcount`, and `confirmed_headcount`, all of which initialize to 0 at event creation, plus `cancellation_fee_cents`, which is 0 until the event is cancelled. On a `Table`, `occupied_seats` is derived and initializes to 0. The precise formulas that produce these values are given alongside the workflows that drive them in Section 3.

The guiding principle is immediate reconciliation: any operation that changes a booking's status, a guest's RSVP, or a seat assignment recomputes the affected derived fields as part of the same operation, and because that recomputation mutates the owning resource, it refreshes that resource's `updated_at` and increments its `version`. The same principle governs the cascades that ripple across resources — an event completion that carries its booked vendors to completion, an event cancellation that voids a contract and cancels bookings, a booking cancellation that voids scheduled payments and restores the budget, and a guest who declines after being seated and thereby frees their seat. Each of these is described in the workflow where it originates.

## 3. Business Logic & Workflows

### 3.1. Founding the Event and Its Contract

Every engagement begins when a `Planner` creates an `EventProject`, supplying the `couple_names`, the `event_date` (the ISO 8601 UTC instant of the wedding or event, which anchors day-count and insurance-validity rules), the `venue_name`, the `package_type`, the `total_budget_cents`, and the `guest_count_estimate`. The `package_type` is the tier of service and is one of `FULL`, `PARTIAL`, or `DAY_OF`. The `total_budget_cents` and `guest_count_estimate` must both be non-negative. A newly created event opens in `DRAFT` status with every computed budget and headcount field at 0 and `active_contract_id` unset.

With an event in hand, the `Planner` creates a `Contract` for it by supplying the `event_id` it belongs to (along with the concurrency token discussed in Section 2.8). A contract copies the event's `package_type` onto itself, is created in `DRAFT`, and has its `planner_fee_cents` computed at creation time. Creating a contract supersedes any contract the event previously pointed at: the prior active contract is transitioned to `VOID`, the event's `active_contract_id` is set to the new contract, and the event's `version` is incremented by one. A contract also tracks a `revision_count`, which starts at 0, and a `signed_at` timestamp, which is unset until the client signs.

**Computing the planner fee.** The `planner_fee_cents` depends on the `package_type` and, for two of the three tiers, on the event's budget and estimated headcount. For a `DAY_OF` package, the fee is a flat 250,000 cents. For a `PARTIAL` package, the fee is a base of 400,000 cents plus 5,000 cents for every guest in `guest_count_estimate`; this per-guest term is independent of the budget. For a `FULL` package, a percentage rate is selected from the `total_budget_cents`: if the budget is at most 5,000,000 cents the rate is 12 percent; if it is greater than 5,000,000 cents but at most 15,000,000 cents the rate is 15 percent; if it exceeds 15,000,000 cents the rate is 18 percent. The `FULL` fee is then a base of 800,000 cents plus the selected rate applied to the entire `total_budget_cents`, with that rate-times-budget product rounded half up to whole cents before the base is added. Tier boundaries are inclusive of their upper edge, as stated.

**Progressing the contract.** A `DRAFT` contract is sent to the client, moving `DRAFT → SENT`; this is permitted only when the contract is in `DRAFT`, otherwise the attempt is rejected with `ERR_CONTRACT_NOT_DRAFT`. Once `SENT`, the contract can move in one of two directions. The `Client` who owns the event may sign it, moving `SENT → SIGNED` and stamping `signed_at` with the current logical clock; signing requires the contract to be `SENT` (otherwise `ERR_CONTRACT_NOT_SENT`) and requires the acting client to own the event. Alternatively, either the `Client` who owns the event or the `Planner` may request a revision, moving `SENT → DRAFT` and incrementing `revision_count` by one; this too requires the contract to be `SENT` (otherwise `ERR_CONTRACT_NOT_SENT`), and when the actor is the client the ownership check applies. This `DRAFT → SENT → DRAFT` loop may repeat any number of times. A `SIGNED` contract is countersigned by the `Planner`, moving `SIGNED → COUNTERSIGNED`; this requires the contract to be `SIGNED`, otherwise `ERR_CONTRACT_NOT_SIGNED`. `COUNTERSIGNED` and `VOID` are terminal contract states.

**Confirming the event.** Once the active contract is fully executed, the `Planner` confirms the event, advancing it `DRAFT → BOOKING`. Confirmation requires the event to be in `DRAFT` (otherwise `ERR_EVENT_NOT_DRAFT`) and requires the event's active contract to exist and be in `COUNTERSIGNED` status; if the active contract is anything other than `COUNTERSIGNED`, the confirmation is rejected with `ERR_CONTRACT_NOT_COUNTERSIGNED`. Entering `BOOKING` is the gate that unlocks vendor booking.

### 3.2. The Vendor Directory and Insurance Verification

Vendors live in a shared directory independent of any single event. A `Planner` adds a `Vendor` by supplying its business `name`, its `category`, and its `contact_email`. The `category` classifies the supplier and is one of `CATERING`, `FLORAL`, `RENTAL`, `PHOTO`, `VENUE`, `STAFFING`, or `OTHER`; design/décor and rental coordination are handled through the `FLORAL` and `RENTAL` categories.

Before a vendor can be booked, its insurance must be on file and verified. A Certificate of Insurance is submitted as a `COI`, carrying the `vendor_id` it covers, the `policy_number`, the `coverage_amount_cents` (a non-negative amount), and the `coverage_expiry_date`. A COI may be submitted either by the `Planner` or by the `Vendor` itself; a vendor may submit only for its own `vendor_id`, and a mismatch is an ownership violation. A submitted COI opens in `PENDING`.

The `Planner` verifies a pending certificate, moving it `PENDING → VERIFIED`. Verification requires the COI to be `PENDING` (otherwise `ERR_COI_NOT_PENDING`) and requires the `coverage_expiry_date` to be strictly after the current logical clock; a certificate whose `coverage_expiry_date` is at or before the current clock cannot be verified and the attempt is rejected with `ERR_COI_EXPIRED`. As described in Section 2.6, the clock sweep is the complementary rule: any `PENDING` or `VERIFIED` certificate whose `coverage_expiry_date` falls at or before a newly set clock is moved to `EXPIRED`, which is terminal.

### 3.3. Vendor Bookings, Payments, and the Budget Ledger

Engaging a vendor for an event is a two-step commitment. First, the `Planner` proposes a booking by supplying the `event_id`, the `vendor_id`, a `service_description` of what the vendor will provide, and an `estimated_cost_cents` (non-negative). The booking opens in `PROPOSED`, and its provisional estimate immediately feeds the event's forward-looking spend. At this stage `contracted_cost_cents`, `deposit_cents`, and `balance_cents` are all unset.

Second, the `Planner` books the proposed engagement, moving it `PROPOSED → BOOKED` and supplying the final `contracted_cost_cents` in the request. Booking is guarded by several conditions evaluated in a fixed order: the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally, checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the booking is rejected with `ERR_BUDGET_EXCEEDED`.

**Splitting the booking into payments.** On a successful booking, the contracted amount is split. The `deposit_cents` is 30 percent of `contracted_cost_cents`, rounded half up to whole cents. The `balance_cents` is then the exact remainder — `contracted_cost_cents` minus `deposit_cents` — and is never independently re-rounded, so deposit and balance always sum back to the contracted amount. The system mints two `VendorPayment` records for the booking, both opening in `SCHEDULED`: one of `payment_type` `DEPOSIT` whose `amount_cents` equals the booking's `deposit_cents`, and one of `payment_type` `BALANCE` whose `amount_cents` equals the booking's `balance_cents`. Both the `vendor_booking_id` and the `payment_type` of a payment are set by the system, not supplied by any client. A payment carries a `paid_at` timestamp that is unset until it is paid. The `Planner` pays a scheduled payment, moving it `SCHEDULED → PAID` and stamping `paid_at` with the current logical clock; a payment may be paid only from `SCHEDULED`, otherwise `ERR_PAYMENT_NOT_SCHEDULED`. `PAID` and `VOID` are terminal payment states.

**The budget roll-up.** Booking, proposing, cancelling a booking, and completing an event all recompute the event's four spend figures across its non-cancelled bookings; cancelled bookings are excluded from every sum. The `committed_spend_cents` is the sum of `contracted_cost_cents` over the bookings that are in `BOOKED` or `COMPLETED`. The `projected_spend_cents` is a forward-looking figure summed over bookings that are `PROPOSED`, `BOOKED`, or `COMPLETED`, counting each `BOOKED` or `COMPLETED` booking at its `contracted_cost_cents` and each `PROPOSED` booking at its `estimated_cost_cents`; it diverges from the committed figure exactly when a proposed booking exists. The `budget_balance_cents` is `total_budget_cents` minus `committed_spend_cents`. The `total_deposits_due_cents` sums, over only the bookings currently in `BOOKED` status, 30 percent of each booking's `contracted_cost_cents` rounded half up per booking, with those per-booking rounded deposits then added together.

**Cancelling a booking.** The `Planner` may cancel a booking that is in `PROPOSED` or `BOOKED`; any other state yields `ERR_BOOKING_NOT_CANCELLABLE`. Cancellation moves the booking to `CANCELLED`. Cancelling a merely `PROPOSED` booking simply drops its estimate from the projected figure. Cancelling a `BOOKED` booking additionally voids the compensation already scheduled: each of the booking's `SCHEDULED` payments transitions `SCHEDULED → VOID`, the booking's `contracted_cost_cents` is removed from `committed_spend_cents`, and the balance and deposits-due figures are recomputed. `COMPLETED` and `CANCELLED` are terminal booking states.

### 3.4. Guest List, RSVPs, and Catering Headcount

Guests are managed as parties rather than individuals. A `Planner`, or the `Client` who owns the event, adds a `Guest` by supplying the `event_id`, the `guest_name`, and the `party_size` (the number of seats the party consumes, which must be at least 1). An optional `meal_choice` may be given, drawn from `NONE`, `STANDARD`, `VEGETARIAN`, `VEGAN`, or `KIDS`; when omitted it defaults to `NONE`. A new guest opens in `INVITED` rsvp status.

An RSVP is changed by supplying a target `rsvp_status`, and optionally an updated `meal_choice`. A `Planner` or the owning `Client` may change an RSVP; when the actor is a client, the ownership check on the guest's event applies. The `rsvp_status` moves through a small cycle: an `INVITED` party may become `ACCEPTED` or `DECLINED`, and thereafter may flip between `ACCEPTED` and `DECLINED` as plans change. One flip carries a consequence: when a guest moves `ACCEPTED → DECLINED` and that guest currently holds a seat assignment, the system deletes the seat assignment and decrements the assigned table's `occupied_seats` by the seats that assignment held. Re-accepting afterward — moving `DECLINED → ACCEPTED` — does not automatically restore a seat; the party must be seated again explicitly.

**Headcount figures.** Every guest creation and every RSVP change recomputes two event figures over the event's guests, with declined parties excluded from both. The `estimated_headcount` is the sum of `party_size` over guests whose `rsvp_status` is `INVITED` or `ACCEPTED` — the planning outlook used to order chairs and meals for parties that have not yet responded. The `confirmed_headcount` is the sum of `party_size` over guests whose `rsvp_status` is `ACCEPTED` — the final catering guarantee. The two figures diverge exactly when at least one invited party has not yet responded.

### 3.5. Reception Seating

Reception tables are created by the `Planner`, each with an `event_id`, a `table_label`, and a `capacity` (the maximum number of seats, at least 1). A table's `occupied_seats` begins at 0 and is kept reconciled as guests are seated and unseated.

Seating a guest creates a `SeatAssignment` from an `event_id`, a `guest_id`, and a `table_id`. The assignment snapshots the guest's `party_size` at seating time into `seats_used`, and that snapshot is the amount later released if the assignment is removed. On a successful seating, the table's `occupied_seats` is increased by `seats_used`. Seating is subject to three business checks, applied in this order after the standard existence and body validations: first, the guest must be `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second, the referenced guest and table must both belong to the same event named by `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have room — its `occupied_seats` plus the guest's `party_size` must not exceed its `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`.

Removing a seat assignment releases its seats: the assignment is deleted and the table's `occupied_seats` is decreased by that assignment's `seats_used`. This is the compensating counterpart to seating, and — together with the automatic unseating triggered when an accepted guest declines — is what keeps a table's `occupied_seats` a faithful sum of the seats currently used against it.

### 3.6. The Run-of-Show Timeline

The `Planner` builds the event's run of show as a set of `TimelineBlock` records, each with an `event_id`, a `label`, a `zone`, a `block_type`, a `start_offset_min`, and an `end_offset_min`. Both offsets are expressed in minutes from midnight of the event day. The `zone` is the physical area the block occupies and is one of `CEREMONY_SPACE`, `RECEPTION_HALL`, `KITCHEN`, `LOADING_DOCK`, or `SUITE`. The `block_type` is the kind of activity and is one of `LOAD_IN`, `SETUP`, `CEREMONY`, `COCKTAIL`, `RECEPTION`, or `TEARDOWN`.

A block's interval is treated as half-open — it includes its start minute and excludes its end minute — and must be well-formed: `end_offset_min` must be strictly greater than `start_offset_min`, otherwise the block is rejected with `ERR_INVALID_INTERVAL`. Two blocks in the same event and the same `zone` may not occupy overlapping time. Under the half-open convention, a proposed block conflicts with an existing block in that zone when the proposed block's start is earlier than the existing block's end and the existing block's start is earlier than the proposed block's end; such a conflict is rejected with `ERR_TIMELINE_OVERLAP`. Blocks that merely touch at an endpoint — where the proposed block's end equals an existing block's start, or an existing block's end equals the proposed block's start — do not overlap and are allowed. Blocks in different zones never conflict with one another.

### 3.7. Day-of Staffing and Logistics

The `Planner` rosters day-of staff as `StaffMember` records, each with an `event_id`, a `staff_name`, a `role_title`, and an `hourly_rate_cents` (non-negative). The `role_title` is one of `COORDINATOR`, `SERVER`, `BARTENDER`, `SECURITY`, or `RUNNER`.

A staff member is put on a shift by creating a `StaffAssignment` with an `event_id`, a `staff_member_id`, a `shift_start_offset_min`, and a `shift_end_offset_min`, both in minutes from midnight of the event day. As with timeline blocks, the shift interval must be well-formed — `shift_end_offset_min` strictly greater than `shift_start_offset_min`, otherwise `ERR_INVALID_INTERVAL`. On creation the assignment's `labor_cost_cents` is computed: the shift length in minutes is `shift_end_offset_min` minus `shift_start_offset_min`, and the labor cost is the staff member's `hourly_rate_cents` multiplied by that number of minutes, divided by 60, rounded half up to whole cents.

A single staff member may not be double-booked, and the rule enforces a rest buffer of 30 minutes between shifts. A proposed shift conflicts with another shift of the same staff member unless the two are separated by a gap of at least 30 minutes — that is, unless the earlier shift's end plus 30 minutes is less than or equal to the later shift's start. A gap of exactly 30 minutes is permitted; any smaller gap, or an actual overlap, is a conflict rejected with `ERR_STAFF_DOUBLE_BOOKED`. Shifts assigned to different staff members never conflict with one another.

### 3.8. Delivering or Cancelling the Event

**Completion.** When the event has been delivered, the `Planner` completes it, moving it `BOOKING → COMPLETED`. Completion requires the event to be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`), requires the current logical clock to have reached or passed the `event_date` (otherwise `ERR_EVENT_DATE_NOT_REACHED`), and requires that no vendor booking for the event is still `PROPOSED` — every engagement must be resolved to booked or cancelled first, otherwise the completion is rejected with `ERR_UNRESOLVED_BOOKINGS`. As a cascade of completion, each of the event's bookings still in `BOOKED` is carried `BOOKED → COMPLETED`; because a completed booking still counts as committed, the committed spend figure is unchanged by this cascade. `COMPLETED` and `CANCELLED` are terminal event states.

**Cancellation.** The `Planner` may cancel an event that is in `DRAFT` or `BOOKING`; any other state yields `ERR_EVENT_NOT_CANCELLABLE`. Cancellation moves the event to `CANCELLED` and unwinds its commitments in three respects. First, it computes and records the `cancellation_fee_cents` on the event. Second, if the event has an active contract that is not already `VOID`, that contract is transitioned to `VOID`. Third, every vendor booking of the event that is still `PROPOSED` or `BOOKED` is cancelled as a cascade, and each such booking cancellation itself voids that booking's scheduled payments and restores the budget exactly as a direct booking cancellation would.

**Computing the cancellation fee.** The fee is a tiered percentage of the active contract's `planner_fee_cents`, scaled by how far away the event still is. The number of whole days remaining is the difference between the `event_date` and the current logical clock, taken in seconds, divided by 86,400 seconds per day, and rounded down to a whole number; this value may be negative if the event date has already passed. If at least 90 days remain, the rate is 25 percent; if fewer than 90 but at least 30 days remain, the rate is 50 percent; if fewer than 30 days remain, the rate is 100 percent. The `cancellation_fee_cents` is that rate applied to the active contract's `planner_fee_cents`, rounded half up to whole cents. If the event has no active contract, the fee basis is 0 and the cancellation fee is therefore 0.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state transition and the setting of the logical clock — return `200 OK`. The removal of a seat assignment returns `204 No Content`. The complete request and response semantics for each endpoint are given in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server logical clock; sweeps expired COIs | Planner |
| POST   | `/planning/events` | Create an event project | Planner |
| GET    | `/planning/events` | List event projects | Planner, Client, Vendor |
| GET    | `/planning/events/{eventId}` | Get one event project | Planner, Client, Vendor |
| POST   | `/planning/events/{eventId}/confirm` | Confirm event (DRAFT → BOOKING) | Planner |
| POST   | `/planning/events/{eventId}/complete` | Complete event (BOOKING → COMPLETED) | Planner |
| POST   | `/planning/events/{eventId}/cancel` | Cancel event | Planner |
| POST   | `/planning/contracts` | Create/supersede a contract for an event | Planner |
| GET    | `/planning/contracts` | List contracts | Planner, Client, Vendor |
| GET    | `/planning/contracts/{contractId}` | Get one contract | Planner, Client, Vendor |
| POST   | `/planning/contracts/{contractId}/send` | Send contract (DRAFT → SENT) | Planner |
| POST   | `/planning/contracts/{contractId}/sign` | Sign contract (SENT → SIGNED) | Client |
| POST   | `/planning/contracts/{contractId}/countersign` | Countersign contract (SIGNED → COUNTERSIGNED) | Planner |
| POST   | `/planning/contracts/{contractId}/request-revision` | Request revision (SENT → DRAFT) | Client, Planner |
| POST   | `/planning/vendors` | Create a vendor directory entry | Planner |
| GET    | `/planning/vendors` | List vendors | Planner, Client, Vendor |
| GET    | `/planning/vendors/{vendorId}` | Get one vendor | Planner, Client, Vendor |
| POST   | `/planning/cois` | Submit a Certificate of Insurance | Vendor, Planner |
| GET    | `/planning/cois` | List COIs | Planner, Client, Vendor |
| GET    | `/planning/cois/{coiId}` | Get one COI | Planner, Client, Vendor |
| POST   | `/planning/cois/{coiId}/verify` | Verify a COI (PENDING → VERIFIED) | Planner |
| POST   | `/planning/vendor-bookings` | Propose a vendor booking | Planner |
| GET    | `/planning/vendor-bookings` | List vendor bookings | Planner, Client, Vendor |
| GET    | `/planning/vendor-bookings/{bookingId}` | Get one vendor booking | Planner, Client, Vendor |
| POST   | `/planning/vendor-bookings/{bookingId}/book` | Book a proposed booking (PROPOSED → BOOKED) | Planner |
| POST   | `/planning/vendor-bookings/{bookingId}/cancel` | Cancel a booking | Planner |
| GET    | `/planning/vendor-payments` | List vendor payments | Planner, Client, Vendor |
| GET    | `/planning/vendor-payments/{paymentId}` | Get one vendor payment | Planner, Client, Vendor |
| POST   | `/planning/vendor-payments/{paymentId}/pay` | Pay a scheduled payment (SCHEDULED → PAID) | Planner |
| POST   | `/planning/timeline-blocks` | Add a run-of-show block | Planner |
| GET    | `/planning/timeline-blocks` | List timeline blocks | Planner, Client, Vendor |
| GET    | `/planning/timeline-blocks/{blockId}` | Get one timeline block | Planner, Client, Vendor |
| POST   | `/planning/guests` | Add a guest/party | Planner, Client |
| GET    | `/planning/guests` | List guests | Planner, Client, Vendor |
| GET    | `/planning/guests/{guestId}` | Get one guest | Planner, Client, Vendor |
| POST   | `/planning/guests/{guestId}/rsvp` | Change a guest's RSVP | Planner, Client |
| POST   | `/planning/tables` | Add a reception table | Planner |
| GET    | `/planning/tables` | List tables | Planner, Client, Vendor |
| GET    | `/planning/tables/{tableId}` | Get one table | Planner, Client, Vendor |
| POST   | `/planning/seat-assignments` | Seat a guest at a table | Planner |
| GET    | `/planning/seat-assignments` | List seat assignments | Planner, Client, Vendor |
| GET    | `/planning/seat-assignments/{assignmentId}` | Get one seat assignment | Planner, Client, Vendor |
| DELETE | `/planning/seat-assignments/{assignmentId}` | Remove a seat assignment | Planner |
| POST   | `/planning/staff-members` | Add a day-of staff member | Planner |
| GET    | `/planning/staff-members` | List staff members | Planner, Client, Vendor |
| GET    | `/planning/staff-members/{staffId}` | Get one staff member | Planner, Client, Vendor |
| POST   | `/planning/staff-assignments` | Assign a staff member to a shift | Planner |
| GET    | `/planning/staff-assignments` | List staff assignments | Planner, Client, Vendor |
| GET    | `/planning/staff-assignments/{assignmentId}` | Get one staff assignment | Planner, Client, Vendor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_HEADERS` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_COI_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TIMELINE_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_GUEST_NOT_FOUND` | 404 Not Found |
| `ERR_TABLE_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_SEAT_EVENT_MISMATCH` | 400 Bad Request |
| `ERR_STALE_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_EVENT_NOT_DRAFT` | 409 Conflict |
| `ERR_EVENT_NOT_BOOKING` | 409 Conflict |
| `ERR_EVENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_EVENT_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_UNRESOLVED_BOOKINGS` | 409 Conflict |
| `ERR_CONTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTRACT_NOT_SENT` | 409 Conflict |
| `ERR_CONTRACT_NOT_SIGNED` | 409 Conflict |
| `ERR_CONTRACT_NOT_COUNTERSIGNED` | 409 Conflict |
| `ERR_BOOKING_NOT_PROPOSED` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PAYMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_GUEST_NOT_ACCEPTED` | 409 Conflict |
| `ERR_COI_NOT_PENDING` | 409 Conflict |
| `ERR_COI_EXPIRED` | 422 Unprocessable Entity |
| `ERR_COI_NOT_VERIFIED` | 403 Forbidden |
| `ERR_TIMELINE_OVERLAP` | 409 Conflict |
| `ERR_STAFF_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_GUEST_ALREADY_SEATED` | 409 Conflict |
| `ERR_TABLE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |

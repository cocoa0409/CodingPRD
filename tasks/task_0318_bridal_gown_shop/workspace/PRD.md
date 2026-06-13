# Bridal Gown Shop API — Product Requirements Document

## 1. Introduction

A modern bridal boutique juggles an unusually dense web of commitments: a bride books a consultation, a stylist's chair and a fitting suite are both held for a window of time, a gown is ordered against a vendor lead time, alterations cycle through round after round of pins and re-pins, deposits and installment plans accrue against a moving balance, and veils or sashes are added and removed right up until the gown is steamed and carried out the door. This API is the system of record that holds all of those moving parts together. It governs appointment and fitting-room scheduling, gown ordering with size and rush pricing, the milestone-driven alteration workflow, deposit-and-installment payment plans, accessory add-ons, group (party) coordination, and the final pickup hand-off.

The platform is built around a small number of cooperating but independently owned surfaces. Front-of-house consultants run the appointment floor; seamstresses drive the alteration cycle; finance staff manage money; and a shop manager holds override authority over the order lifecycle and resource setup. Because a single gown can be simultaneously mid-alteration, partially paid, and pinned to a group event, the system tracks several state axes in parallel and reconciles every derived figure — order totals, ledger balances, occupant counts, member tallies — the moment a triggering event lands. The sections below define the contract every client and every implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly four roles: `ShopManager`, `BridalConsultant`, `Seamstress`, and `FinanceClerk`. A request that omits either header, or carries a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT`. A request whose role is authenticated but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

Every one of the four roles is an operational staff identity rather than a persisted customer entity. When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The same holds for `BridalConsultant`, `Seamstress`, and `FinanceClerk`: in each case `X-User-ID` is an opaque operator identifier, not tied to any stored row, and no ownership check anywhere in the system compares a resource's foreign-key field to `X-User-ID`. Authorization is therefore decided purely by role membership against the operation, never by record ownership.

The `ShopManager` is the store operator and holds override authority across surfaces — stylist and room setup, vendor receipt, order cancellation, no-show flagging, and party locking are theirs, and they may also act on most shared operations. A `BridalConsultant` runs the front-of-house floor: appointments, fitting-room holds, gown orders, accessories, and party formation. A `Seamstress` owns the alteration workflow and may also mark a received gown ready. A `FinanceClerk` owns payment plans, payments, and refunds. Read (`GET`) access to every collection is granted to all four roles. The precise operation-by-role grants are enumerated in the §4 endpoint table.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Almost every resource in the system — stylists, fitting rooms, bridal parties, appointments, fitting-room bookings, gown orders, accessory add-ons, alteration jobs, and payment plans — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix. The `id` is identity only; it is never a business-decision input.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g. `2025-05-24T10:30:00.123Z`), stamped when the resource is first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource's properties.
- **`version`** (integer): a system-managed counter that starts at the resource's creation and increments by one on every mutation, including mutations to derived fields. It backs optimistic concurrency control where applicable.

The single exception is the `Payment` resource. A payment is an immutable ledger record once posted, so it carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Whenever a server-driven reconciliation mutates a resource (for example, recomputing a plan's balance or a party's member tally), that counts as a mutation: the affected resource's `updated_at` is refreshed and its `version` is incremented exactly as a direct client edit would do.

### 2.5. Monetary Values, Counts, and Rounding

Every monetary amount in the system is stored and returned as an integer number of cents — there are no fractional-cent values and no floating-point money. Wherever a calculation in §3 introduces a percentage term (a size upcharge, a rush surcharge, a deposit floor, or a refit surcharge), the rounding behavior is fixed and described in full at the point the calculation is defined; in every such case rounding is applied to the integer-cent result as specified there, never to an intermediate float that is later truncated. Occupant counts and labor-minute totals are likewise plain integers.

### 2.6. Optimistic Concurrency on Plan Writes

Two endpoints mutate a payment plan's money ledger: posting a payment against a plan, and issuing a refund on a plan. Both are guarded by optimistic concurrency control to stop a client from writing against a balance it has not actually observed. Each of these two requests must carry `expected_plan_version`, a non-optional integer field holding the `version` of the target `PaymentPlan` that the client last read. If `expected_plan_version` does not equal the plan's current `version` at the time the write is processed, the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP status 412.

This matters because a prior write — another installment posting, or a refund that reversed the ledger — legitimately advances the plan's `amount_paid_cents` and `balance_due_cents` and bumps its `version`. A payment or refund carrying the pre-advance version is therefore working from a stale view of the plan's balance and must be refused so the client re-reads the plan first. No endpoint other than these two payment-plan writes takes a version field; all other mutations proceed without an OCC check.

### 2.7. Hierarchical Consistency and Cascades

The topology here is flat: parties, appointments, bookings, orders, accessories, alteration jobs, and plans are all peer top-level collections that reference one another by foreign-key fields carried in request bodies, not by nested URL paths. Consistency is nonetheless strict and is reconciled immediately — every cascade and every derived-field recompute completes atomically inside the request that triggered it, before the response is returned.

Several operations therefore touch more than one resource. Cancelling an order cascades into its alteration jobs, those jobs' room bookings, and its payment plan; completing or cancelling an appointment releases its held rooms; and posting a payment recomputes the plan ledger and may flip both the plan's and the order's status. Each of these knock-on mutations is a real mutation on the affected resource: it refreshes that resource's `updated_at` and increments its `version`. The exact cascade chains are described where the triggering workflow lives in §3.

### 2.8. Existence and Request-Shape Validation Ordering

Every request is screened by a fixed pipeline of checks, evaluated in strict priority order so that an earlier failure masks a later one. The order is: (1) authentication headers, rejecting with `ERR_MISSING_USER_CONTEXT`; (2) role authorization, rejecting with `ERR_FORBIDDEN_ROLE`; (3) existence resolution; (4) request-body well-formedness, rejecting with `ERR_INVALID_REQUEST`; (5) state legality of the targeted transition; (6) cross-entity referential preconditions; and then the domain-specific temporal, capacity, fiscal, and safety rules described in §3.

Existence resolution (step 3) walks the path identifier first and then the body's foreign keys in their declaration order, left to right, and rejects on the first identifier that does not resolve to an existing row. Each unresolved reference maps to its own 404 code: `ERR_STYLIST_NOT_FOUND`, `ERR_FITTING_ROOM_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ACCESSORY_NOT_FOUND`, `ERR_ALTERATION_JOB_NOT_FOUND`, or `ERR_PAYMENT_PLAN_NOT_FOUND`. Request-body validation (step 4) confirms that required fields are present, that enum values are in range, and that integer fields satisfy their declared bounds — a fitting room's `capacity` is at least 1, a booking's `party_size` is at least 1, a payment's `amount_cents` is at least 1, a plan's `term_installments` is at least 1, and any appointment or booking window must have an exclusive end strictly after its inclusive start. Any such shape failure is rejected with `ERR_INVALID_REQUEST` and HTTP status 422.

## 3. Business Logic & Workflows

### 3.1. Stylists, Rooms, and the Shop's Standing Resources

Before any booking can happen, the shop's standing resources must exist. A `ShopManager` registers each consultant as a **Stylist**, supplying a `full_name`; the stylist also carries a `turnaround_buffer_minutes` cleanup-and-reset window that defaults to 15 when omitted and must be a non-negative integer, and an `active` flag that defaults to `true`. An inactive stylist accepts no new appointment activity. The manager may later adjust any of these fields — toggling `active` or changing the buffer — through a stylist update.

Fitting rooms are likewise set up by a `ShopManager`. A **FittingRoom** carries a human `room_label` such as "Suite A", a `capacity` giving the maximum number of occupants the room can hold at any single instant (an integer of at least 1), and an `out_of_service` flag defaulting to `false`. When `out_of_service` is `true` the room accepts no new bookings.

A **BridalParty** groups several orders around one event. A `BridalConsultant` or `ShopManager` creates a party with a `party_name` (for example "Okafor Wedding") and an `event_date` in ISO 8601 UTC. A party may optionally name an anchor order through `lead_gown_order_id`, the self-referential link to the bride's own `GownOrder` that gates group coordination; it is nullable until set and may be assigned later through a party update that supplies `lead_gown_order_id`. On creation a party begins with `coordination_status` of `FORMING` and a `member_order_count` of 0. The `member_order_count` is a derived figure: it is the number of `GownOrder` rows whose `bridal_party_id` points at this party and whose `fulfillment_status` is anything other than `CANCELLED`. This count is recomputed and re-stamped whenever a linked order is created or cancelled, and is also recomputed when the party is fetched. Parties may be listed and filtered by their `lead_gown_order_id`.

Membership is frozen by a one-way lock. A `ShopManager` may transition a party from `FORMING` to `LOCKED`; the lock requires the party to currently be `FORMING`, otherwise it is rejected with `ERR_PARTY_NOT_FORMING`. Once `LOCKED`, the party freezes its membership, and any later attempt to create a `GownOrder` carrying this `bridal_party_id` is rejected with the same `ERR_PARTY_NOT_FORMING`. The membership-state guard thus governs two operations — the party lock itself and party-linked order creation — and both surface `ERR_PARTY_NOT_FORMING` when the party is not `FORMING`.

### 3.2. Booking Appointments and Holding Fitting Rooms

An **Appointment** reserves a stylist's time. A `BridalConsultant` or `ShopManager` books one by naming the `stylist_id`, an `appointment_type` of either `CONSULTATION` or `FITTING`, an inclusive `start_at` and an exclusive `end_at` (both ISO 8601 UTC, with `end_at` strictly after `start_at`), and an optional `bridal_party_id` linking a group appointment to a party. Appointments may later be listed and filtered by `stylist_id` or by `bridal_party_id`. A new appointment is created in `BOOKED` status.

Booking is subject to a double-booking guard built around each stylist's cleanup buffer. A candidate appointment must not overlap any other non-terminal appointment on the same stylist once each existing appointment is extended on its end side by that stylist's `turnaround_buffer_minutes`. The interval semantics are closed on the start and buffered on the end: two appointments conflict when the candidate's window overlaps an existing window whose end has been pushed out by the buffer, so back-to-back bookings are only legal once the full buffer has elapsed after the earlier appointment's `end_at`. A violation is rejected with `ERR_STYLIST_DOUBLE_BOOKED`. Because only non-terminal appointments count, appointments that have reached `COMPLETED`, `CANCELLED`, or `NO_SHOW` no longer block the stylist's calendar.

The appointment lifecycle is a small branching machine with a revert path. A `BridalConsultant` checks a client in, advancing `BOOKED → CHECKED_IN`; this requires the appointment to be `BOOKED` (else `ERR_APPOINTMENT_NOT_BOOKED`) and the stylist to be `active` (else `ERR_STYLIST_INACTIVE`). An accidental check-in can be undone by the same consultant, reverting `CHECKED_IN → BOOKED`, which requires the appointment to be `CHECKED_IN` (else `ERR_APPOINTMENT_NOT_CHECKED_IN`); the revert exists so a mistakenly checked-in slot can still be cancelled cleanly. Completing an appointment advances `CHECKED_IN → COMPLETED` and likewise requires the `CHECKED_IN` state (else `ERR_APPOINTMENT_NOT_CHECKED_IN`). A consultant or manager may cancel a `BOOKED` appointment, advancing `BOOKED → CANCELLED`; cancellation requires the `BOOKED` state, otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`. Finally, a `ShopManager` may flag a `BOOKED` appointment as a no-show, advancing `BOOKED → NO_SHOW`, again requiring the `BOOKED` state (else `ERR_APPOINTMENT_NOT_BOOKED`). The three terminating transitions — complete, cancel, and mark-no-show — share one side effect: every `HELD` fitting-room booking attached to that appointment is moved to `RELEASED`, freeing each room's capacity for the booking's interval.

A **FittingRoomBooking** holds a room slot for an appointment. A `BridalConsultant` or `ShopManager` creates one by supplying the `appointment_id` it serves, the `fitting_room_id` being occupied, the `party_size` (occupants this booking consumes, at least 1), and an inclusive `slot_start_at` and exclusive `slot_end_at` (the latter strictly after the former). A booking is created in `HELD` status, which consumes capacity; a `RELEASED` booking consumes none. Bookings may be listed and filtered by `appointment_id` or `fitting_room_id`.

Room capacity is enforced as an instantaneous overlap rule over half-open intervals. For a candidate booking on a given room, consider every instant within `[slot_start_at, slot_end_at)`; at each such instant, sum the `party_size` of all `HELD` bookings on the same room whose own `[slot_start_at, slot_end_at)` interval contains that instant. The peak of that running sum across the candidate's interval, plus the candidate's own `party_size`, must not exceed the room's `capacity`. If that ceiling would be breached at any instant, the booking is rejected with `ERR_FITTING_ROOM_OVERBOOKED`. The intervals are half-open, so adjacency does not conflict: a booking ending exactly when another begins does not overlap it, and the two may share a room boundary freely.

A held booking can be released directly — a `BridalConsultant` or `ShopManager` may release a booking, moving `HELD → RELEASED`, which requires the booking to be `HELD` (else `ERR_BOOKING_NOT_HELD`) and returns its `party_size` occupants to the room's capacity over the booking interval. Beyond this manual release, the system releases held bookings automatically as a side effect when their parent appointment is completed, cancelled, or marked no-show, and when a parent alteration job is cancelled (see §3.4 and §3.5).

### 3.3. Creating and Pricing a Gown Order

A **GownOrder** is the spine of a sale. A `BridalConsultant` or `ShopManager` opens one by supplying the `gown_style_code` from the catalog, the `ordered_size` (a non-negative integer dress size), the `base_price_cents` list price (non-negative integer cents), the vendor's `standard_lead_days` (an integer of at least 1), and an optional `is_rush` flag that defaults to `false`. The order may optionally be linked to a group through `bridal_party_id` and to the consultation it grew out of through `origin_appointment_id`. A new order is created with `fulfillment_status` of `DRAFT` and `payment_status` of `UNPAID`. Orders may be listed and filtered by `bridal_party_id` or `origin_appointment_id`. If a `bridal_party_id` is supplied, that party must be `FORMING` (a `LOCKED` party rejects the new membership with `ERR_PARTY_NOT_FORMING`), and on success the party's `member_order_count` is recomputed.

At creation the system stamps a provisional total into `quoted_total_cents`. The pricing begins from the gown's own subtotal. A plus-size upcharge applies only when `ordered_size` is at least the size-upcharge floor of 20: in that case the upcharge is fifteen percent of `base_price_cents`, rounded up to the next whole cent; for any smaller size the upcharge is zero. A rush surcharge applies only when `is_rush` is true: it is thirty percent of `base_price_cents`, rounded up to the next whole cent; otherwise it is zero. Each of those two percentage terms is rounded up to a whole cent independently, before anything is summed. The gown subtotal is then `base_price_cents` plus the size upcharge plus the rush surcharge. The quoted total stamped at creation is exactly this gown subtotal: no accessories exist yet at draft creation, so the quoted estimate carries no accessory contribution.

Each order also gets a `required_by_date`, computed as the order's `created_at` plus the effective lead time in days, expressed in ISO 8601 UTC. The effective lead time is derived from `standard_lead_days`, with a rush order shortening the lead; the date is stamped when the draft is submitted to the vendor (see §3.4).

Accessories ride on top of the order. A `BridalConsultant` or `ShopManager` attaches an **AccessoryAddOn** by naming the `gown_order_id` it attaches to, an `accessory_type` of `VEIL`, `TIARA`, `SASH`, or `SHOES`, and a `price_cents` (non-negative integer cents). An add-on is created `ACTIVE`. Either role may later remove an add-on, moving its `status` from `ACTIVE` to `REMOVED`; a `REMOVED` add-on drops out of the order total. Add-ons may be listed and filtered by `gown_order_id`. Because accessories can be attached and removed freely between draft and vendor receipt, the order's eventual final total can diverge from its original quote.

### 3.4. The Fulfillment Lifecycle: Submit, Receive, Ready, Pickup

A gown order's fulfillment travels through `DRAFT → ORDERED → RECEIVED → READY → PICKED_UP`, with `PICKED_UP` and `CANCELLED` as terminal states.

A `BridalConsultant` or `ShopManager` submits a draft to the vendor, advancing `DRAFT → ORDERED`. Submission requires the order to be `DRAFT` (else `ERR_ORDER_NOT_DRAFT`) and requires that a payment plan already exists for the order with a status other than `CANCELLED` (else `ERR_PAYMENT_PLAN_REQUIRED`). On submission the system stamps `required_by_date` from the order's `created_at` plus the effective lead days.

A `ShopManager` marks an ordered gown as received from the vendor, advancing `ORDERED → RECEIVED`; this requires the order to be `ORDERED` (else `ERR_ORDER_NOT_ORDERED`). Receipt is the moment the final total is locked in: the system stamps `final_total_cents` using the final pricing variant. That variant recomputes the gown subtotal exactly as at quote time — size upcharge and rush surcharge each rounded up to a whole cent independently, then summed onto `base_price_cents` — and then adds the sum of `price_cents` across every `ACTIVE` accessory add-on on the order; `REMOVED` add-ons are excluded. The rounding order is pinned: each accessory line is already an integer-cent amount and is not rounded again, the two gown percentage terms are each rounded up per term before summation, and the accessory sum is added last. This is round-per-term-then-sum, not sum-the-raw-amounts-then-round. Until an order reaches `RECEIVED`, `final_total_cents` is null.

A `Seamstress` or `ShopManager` marks a received gown ready, advancing `RECEIVED → READY`. This requires the order to be `RECEIVED` (else `ERR_ORDER_NOT_RECEIVED`) and requires that every alteration job belonging to the order has reached `COMPLETED` or `CANCELLED`; if any job is still outstanding the request is rejected with `ERR_ALTERATIONS_OUTSTANDING`.

A `BridalConsultant` or `ShopManager` performs the final steam and pickup, advancing `READY → PICKED_UP`. Pickup carries the `final_steam_done` flag in its request body. Three guards apply together: the order must be `READY` (else `ERR_ORDER_NOT_READY`); the order's `payment_status` must be `PAID_IN_FULL`, meaning the plan's balance has reached zero (else `ERR_BALANCE_OUTSTANDING`); and `final_steam_done` must be `true` in the request body (else `ERR_FINAL_STEAM_REQUIRED`). Pickup takes the gown off the floor and leaves the appointment lifecycle untouched.

Cancellation is the broad escape hatch and the most far-reaching cascade in the system. A `ShopManager` may cancel an order from any non-terminal fulfillment state — that is, any state that is not already `PICKED_UP` or `CANCELLED` (else `ERR_ORDER_NOT_CANCELLABLE`) — driving `fulfillment_status` to `CANCELLED`. The cancellation fans out in a fixed chain. First, every alteration job on the order that is not already `COMPLETED` or `CANCELLED` is moved to `CANCELLED`. Second, for each such cascade-cancelled job that holds a `HELD` fitting-room booking on its `fitting_room_id`, that booking is moved to `RELEASED`, which in turn frees the room's capacity over the booking interval. Third, the order's payment plan, if its status is not already `CANCELLED` and it has taken in no money (`amount_paid_cents` equal to 0), is moved to `CANCELLED`. Finally, the linked party's `member_order_count` is recomputed, since the now-cancelled order no longer counts toward membership. Every resource touched by this cascade has its `updated_at` refreshed and its `version` incremented.

### 3.5. The Alteration Cycle: Fitting, Adjusting, and Final Cost

An **AlterationJob** tracks one gown through the fitting room. A `Seamstress` or `ShopManager` creates a job by naming the `gown_order_id` being altered, an `estimated_labor_minutes` figure (a non-negative integer driving the provisional charge), and an optional `fitting_room_id` reserving a room for the job's scheduled fitting. A new job starts `QUEUED`, with `refitting_count` and `actual_labor_minutes` both initialized to 0. Jobs may be listed and filtered by `gown_order_id` or `fitting_room_id`.

At creation the system stamps a provisional charge into `estimated_cost_cents`. The labor rate is 120 cents per minute, so the estimate is `estimated_labor_minutes` multiplied by 120 cents. No refit surcharge applies to the estimate because `refitting_count` is 0 at creation.

The job then runs a cyclic fitting loop. A `Seamstress` starts the first fitting, advancing `QUEUED → FITTING`; this requires the job to be `QUEUED` (else `ERR_JOB_NOT_QUEUED`) and requires the linked gown order to be `RECEIVED` (else `ERR_ORDER_NOT_RECEIVED`), since alterations cannot begin before the gown is physically in the shop. From `FITTING`, the seamstress can request an adjustment, advancing `FITTING → ADJUSTING`, which requires the `FITTING` state (else `ERR_JOB_NOT_FITTING`) and increments `refitting_count` by one to record the revision round. To resume after an adjustment, the seamstress logs labor, advancing `ADJUSTING → FITTING`; this requires the `ADJUSTING` state (else `ERR_JOB_NOT_ADJUSTING`), carries a `minutes` value in the request body, and adds those `minutes` to the running `actual_labor_minutes` accumulator before cycling the job back to `FITTING`. A job may loop through `FITTING → ADJUSTING → FITTING` as many times as the work demands, each adjustment round bumping `refitting_count`.

A `Seamstress` completes a job from `FITTING`, advancing `FITTING → COMPLETED`; this requires the `FITTING` state (else `ERR_JOB_NOT_FITTING`). Completion stamps the final charge into `final_cost_cents` using the actual, refit-surcharged variant. That figure is the realized labor cost — `actual_labor_minutes` multiplied by 120 cents per minute — scaled by a refit multiplier of one plus ten percent for each refitting round, that is, one plus the product of 0.10 and `refitting_count`; the whole product is then rounded up to a whole cent, with the ceiling applied once to the final product rather than to any intermediate term. Until completion, `final_cost_cents` is null. Completion also carries a room side effect: if the job holds a `HELD` fitting-room booking on its `fitting_room_id`, that booking is moved to `RELEASED`.

A `Seamstress` or `ShopManager` may cancel a job from any non-terminal state — any state that is not already `COMPLETED` or `CANCELLED` (else `ERR_JOB_NOT_CANCELLABLE`) — driving `status` to `CANCELLED`. As with completion, any `HELD` fitting-room booking on the job's `fitting_room_id` is moved to `RELEASED`, freeing room capacity. A job is also cancelled automatically, with the same room release, when its parent gown order is cancelled (the cascade described in §3.4).

### 3.6. Deposits, Installments, and the Payment Plan Schedule

Every order is billed through one active **PaymentPlan**. A `FinanceClerk` or `ShopManager` creates the plan by naming the `gown_order_id` it bills against, the number of equal post-deposit installments `term_installments` (at least 1), and the up-front `deposit_cents`. On creation the plan snapshots its `plan_total_cents` as the order's `quoted_total_cents` plus the sum of `price_cents` across the order's currently `ACTIVE` accessory add-ons, and begins in `DEPOSIT_DUE` status. The `amount_paid_cents` and `balance_due_cents` ledger figures are derived (see §3.7) and start at 0 and `plan_total_cents` respectively.

The deposit floor is a hard fiscal guard. The minimum acceptable deposit is fifty percent of `plan_total_cents`, rounded up to the next whole cent. The supplied `deposit_cents` must be at least that floor; a deposit below the floor is rejected with `ERR_DEPOSIT_BELOW_FLOOR`. This is a validation, not a clamp — an under-floor deposit is refused outright, not silently raised.

The installment schedule is computed by waterfall allocation. The financed amount is `plan_total_cents` minus `deposit_cents`. The base installment is the financed amount divided by `term_installments`, rounded down to a whole cent. The remainder — the financed amount minus the base installment multiplied by `term_installments` — is loaded entirely onto the final installment, so that no cents are lost: every installment except the last charges the base amount, and the last charges the base amount plus the remainder. The plan's `installment_cents` field reports the base installment.

### 3.7. The Payment Ledger: Posting, Coverage, and Refunds

The plan ledger is kept exact, with no rounding. A plan's `amount_paid_cents` is the sum of `amount_cents` over its `SETTLED` payments of kind `DEPOSIT` or `INSTALLMENT`, minus the sum of `amount_cents` over its `SETTLED` payments of kind `REFUND`. The `balance_due_cents` is `plan_total_cents` minus `amount_paid_cents`. These two figures hold the conserved invariant that the amount paid always equals the plan total minus the balance due, and both are recomputed whenever the plan is read.

A `FinanceClerk` or `ShopManager` posts money against a plan by supplying an `amount_cents` (at least 1) and the OCC guard `expected_plan_version` described in §2.6. Each posting creates a **Payment** row referencing its `payment_plan_id`. The system sets the payment's `kind`: it is `DEPOSIT` while the deposit is still being covered and `INSTALLMENT` thereafter. A posted payment is `SETTLED`; the `settlement_status` of a payment is either `SETTLED` or `REVERSED`. An overpayment guard protects the ledger: a payment whose `amount_cents` would drive `amount_paid_cents` strictly above `plan_total_cents` is rejected with `ERR_OVERPAYMENT`. Each successful posting recomputes the plan's `amount_paid_cents` and `balance_due_cents` and increments the plan's `version` by one. Payments may be listed for a plan.

Posting a payment drives both the plan's own status and the linked order's `payment_status`, which move on two coordinated axes. The plan begins `DEPOSIT_DUE`. When the cumulative `amount_paid_cents` reaches the deposit (at least `deposit_cents`) but the plan is not yet fully paid (`amount_paid_cents` still below `plan_total_cents`), the plan advances `DEPOSIT_DUE → ACTIVE` and the linked order's `payment_status` advances `UNPAID → DEPOSIT_PAID`. When a payment drives the balance to zero — `amount_paid_cents` equal to `plan_total_cents` — the plan advances to `PAID_IN_FULL` (from either `DEPOSIT_DUE` or `ACTIVE`) and the order's `payment_status` advances to `PAID_IN_FULL` from either `UNPAID` or `DEPOSIT_PAID`. These transitions are driven by the system as a consequence of the payment, not by separate client calls.

Refunds run only after a sale collapses. A `FinanceClerk` or `ShopManager` issues a full refund on a plan; the refund request carries only the `expected_plan_version` OCC guard. A refund is permitted solely when the linked gown order's `fulfillment_status` is `CANCELLED`; a refund attempted on a non-cancelled order is rejected with `ERR_REFUND_NOT_ALLOWED`. The refund posts a single `REFUND` payment whose amount equals the plan's current `amount_paid_cents`, flips every prior `SETTLED` payment on the plan to `REVERSED`, returns the plan's `amount_paid_cents` to 0, moves the plan to `CANCELLED`, and moves the linked order's `payment_status` to `REFUNDED` (a transition allowed from `DEPOSIT_PAID` or `PAID_IN_FULL`). Like a payment posting, a refund increments the plan's `version` by one. A plan may also be cancelled outright while in `DEPOSIT_DUE` or `ACTIVE` (else `ERR_PLAN_NOT_CANCELLABLE`); the order-cancellation cascade of §3.4 uses exactly this path when the plan has taken in no money.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the posting of payments and refunds — return a `200 OK` status code, except the two payment-posting operations noted below which create new `Payment` resources and therefore return `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stylists` | Create a stylist (consultant) | ShopManager |
| GET | `/stylists` | List stylists | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/stylists/{id}` | Get a stylist | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| PATCH | `/stylists/{id}` | Update a stylist (toggle active, change buffer) | ShopManager |
| POST | `/fitting-rooms` | Create a fitting room | ShopManager |
| GET | `/fitting-rooms` | List fitting rooms | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/fitting-rooms/{id}` | Get a fitting room | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/bridal-parties` | Create a bridal party (group) | BridalConsultant, ShopManager |
| GET | `/bridal-parties` | List bridal parties; filter by lead_gown_order_id | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/bridal-parties/{id}` | Get a bridal party | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| PATCH | `/bridal-parties/{id}` | Set the party's lead order anchor | BridalConsultant, ShopManager |
| POST | `/bridal-parties/{id}/lock` | Lock a party so membership can no longer change | ShopManager |
| POST | `/appointments` | Book an appointment with a stylist | BridalConsultant, ShopManager |
| GET | `/appointments` | List appointments; filter by stylist or party | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/appointments/{id}` | Get an appointment | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/appointments/{id}/check-in` | Check a client in | BridalConsultant |
| POST | `/appointments/{id}/revert-check-in` | Undo an accidental check-in | BridalConsultant |
| POST | `/appointments/{id}/complete` | Complete an appointment | BridalConsultant |
| POST | `/appointments/{id}/cancel` | Cancel a booked appointment | BridalConsultant, ShopManager |
| POST | `/appointments/{id}/mark-no-show` | Flag a booked appointment as no-show | ShopManager |
| POST | `/fitting-room-bookings` | Hold a fitting room slot for an appointment | BridalConsultant, ShopManager |
| GET | `/fitting-room-bookings` | List bookings; filter by appointment or room | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/fitting-room-bookings/{id}` | Get a fitting-room booking | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/fitting-room-bookings/{id}/release` | Manually release a held room slot | BridalConsultant, ShopManager |
| POST | `/gown-orders` | Create a gown order in DRAFT | BridalConsultant, ShopManager |
| GET | `/gown-orders` | List gown orders; filter by party or origin appointment | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/gown-orders/{id}` | Get a gown order | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/gown-orders/{id}/submit` | Submit a DRAFT order to the vendor | BridalConsultant, ShopManager |
| POST | `/gown-orders/{id}/receive` | Mark an ordered gown received (final total stamped) | ShopManager |
| POST | `/gown-orders/{id}/mark-ready` | Mark a received gown ready for pickup | Seamstress, ShopManager |
| POST | `/gown-orders/{id}/pickup` | Final steam and pickup | BridalConsultant, ShopManager |
| POST | `/gown-orders/{id}/cancel` | Cancel a gown order (cascades) | ShopManager |
| POST | `/accessory-addons` | Attach a veil/accessory to a gown order | BridalConsultant, ShopManager |
| GET | `/accessory-addons` | List accessory add-ons; filter by gown order | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/accessory-addons/{id}` | Get an accessory add-on | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/accessory-addons/{id}/remove` | Remove an accessory add-on | BridalConsultant, ShopManager |
| POST | `/alteration-jobs` | Create an alteration job for a gown order | Seamstress, ShopManager |
| GET | `/alteration-jobs` | List alteration jobs; filter by order or room | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/alteration-jobs/{id}` | Get an alteration job | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/alteration-jobs/{id}/start-fitting` | Start the first fitting | Seamstress |
| POST | `/alteration-jobs/{id}/request-adjustment` | Send the job back for adjustment | Seamstress |
| POST | `/alteration-jobs/{id}/log-labor` | Log labor minutes and resume fitting | Seamstress |
| POST | `/alteration-jobs/{id}/complete` | Complete the alteration (final cost stamped) | Seamstress |
| POST | `/alteration-jobs/{id}/cancel` | Cancel an alteration job | Seamstress, ShopManager |
| POST | `/payment-plans` | Create the deposit + installment plan | FinanceClerk, ShopManager |
| GET | `/payment-plans` | List payment plans; filter by gown order | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| GET | `/payment-plans/{id}` | Get a payment plan (ledger recomputed) | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/payment-plans/{id}/payments` | Post a deposit/installment payment (OCC-guarded) | FinanceClerk, ShopManager |
| GET | `/payment-plans/{id}/payments` | List payments for a plan | ShopManager, BridalConsultant, Seamstress, FinanceClerk |
| POST | `/payment-plans/{id}/refund` | Issue a full refund on a cancelled order's plan (OCC-guarded) | FinanceClerk, ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STYLIST_NOT_FOUND` | 404 Not Found |
| `ERR_FITTING_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ACCESSORY_NOT_FOUND` | 404 Not Found |
| `ERR_ALTERATION_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_STYLIST_INACTIVE` | 409 Conflict |
| `ERR_BOOKING_NOT_HELD` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_ORDERED` | 409 Conflict |
| `ERR_ORDER_NOT_RECEIVED` | 409 Conflict |
| `ERR_ORDER_NOT_READY` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_JOB_NOT_QUEUED` | 409 Conflict |
| `ERR_JOB_NOT_FITTING` | 409 Conflict |
| `ERR_JOB_NOT_ADJUSTING` | 409 Conflict |
| `ERR_JOB_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PAYMENT_PLAN_REQUIRED` | 409 Conflict |
| `ERR_ALTERATIONS_OUTSTANDING` | 409 Conflict |
| `ERR_REFUND_NOT_ALLOWED` | 409 Conflict |
| `ERR_STYLIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_FITTING_ROOM_OVERBOOKED` | 409 Conflict |
| `ERR_PARTY_NOT_FORMING` | 409 Conflict |
| `ERR_DEPOSIT_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_BALANCE_OUTSTANDING` | 409 Conflict |
| `ERR_FINAL_STEAM_REQUIRED` | 409 Conflict |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |

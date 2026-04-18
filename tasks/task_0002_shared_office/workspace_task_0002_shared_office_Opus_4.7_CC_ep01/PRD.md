# Shared Office API — Product Requirements Document

## 1. Introduction

Co-working operators rarely fail because a single desk or meeting room is priced incorrectly. They fail because pricing, occupancy, visitor traffic, access control, and billing drift out of step with one another: a member checks out early but is still billed for a full daily slot; a visitor overstays by two hours and leaves no paper trail; a lease termination finalizes while the tenant is still running reservations and open DRAFT bills; a late fee compounds week over week because the formula kept reapplying itself. This document specifies a single shared-office platform API that keeps the operational, financial, and physical-access layers consistent by construction. Every resource booking, every badge swipe, every bill issuance, and every lease lifecycle event flows through the same consolidated model.

The scope covers tenants and their members, the bookable resource inventory (workstations, meeting rooms, and event areas), reservation workflows with dual-variant provisional and final pricing, visitor registration with overstay accounting, access badge control, bill consolidation with sum-then-round tax and weekly late-fee recomputation, and a multi-step lease-termination process with segregation of duties between reviewing and finalizing platform administrators. A deliberate test-driving facility is also specified: an administrator may advance the virtual clock and invoke a deterministic sweep that promotes reservations, visitors, and bills through their time-based transitions without side-effects leaking into other endpoints.

The audience is the implementing engineering team. Domain behavior is described first; the HTTP contract follows at the end. Whenever a specification appears to repeat across sections — for example, when access posture rules are mentioned in the access-control narrative and again in the billing narrative — that repetition is intentional reinforcement, not contradiction.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (except the health probe) must carry two headers: `X-User-ID` identifying the caller, and `X-User-Role` naming the caller's role. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH`. If `X-User-Role` carries a string that is not one of the declared roles, the request is rejected with `ERR_UNKNOWN_ROLE`. If the role is recognized but not permitted to perform the requested operation per the RBAC matrix, the request is rejected with `ERR_FORBIDDEN`.

The platform recognizes six roles. `PlatformAdmin` is the shared-office operator who provisions tenants, leases, resources, and access badges, finalizes lease terminations, and, in tests, drives the logical clock and the sweep. `TenantAdmin` is a tenant-side administrator who can manage members of their own tenant and who alone may request or withdraw a lease termination. `TenantMember` is a regular tenant employee who books resources, registers visitors, and generates access events through their own badge. `Receptionist` is the front-desk operator responsible for visitor check-in and check-out events. `BillingOfficer` consolidates and issues bills. `PaymentClerk` marks issued or overdue bills as paid; this responsibility is intentionally separated from `BillingOfficer` to enforce segregation of duties on the billing cycle.

Two roles are *entity-backed*, and four are *opaque*. When `X-User-Role` is `TenantAdmin` or `TenantMember`, the value of `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (for example, a reservation's `member_id` or a visitor's `host_member_id`) compare the resource's foreign-key field to `X-User-ID`, and tenant scoping is derived from the acting `Member`'s `tenant_id`. When `X-User-Role` is `PlatformAdmin`, `Receptionist`, `BillingOfficer`, or `PaymentClerk`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it (for example, the `PlatformAdmin` who performs `begin-review` on a lease is recorded as the `reviewer_user_id` of that lease so that the segregation-of-duties check at finalize time has something to compare against) but it does not compare the value to any entity's `id`.

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

### 2.3. Pagination

List endpoints accept two query parameters: `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be at least 0. A request with `limit` outside 1 through 100 inclusive, or with a negative `offset`, is rejected with `ERR_PAGINATION_OUT_OF_RANGE`. All list endpoints sort results by `created_at` ascending. The `meta` envelope on list responses includes `limit`, `offset`, `total_count` (the unpaginated match count after filters), and `has_more` (true when `offset + limit` is strictly less than `total_count`).

### 2.4. Common Resource Properties

Most entities carry four system-managed fields that are emitted on every read. The `id` is a server-minted UUID (version 4, no type prefix); callers never supply it. The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings with three fractional digits, populated by the server at creation time and refreshed by the server on every state mutation that modifies the row. The `version` field is an integer that begins at 1 on creation and increments by exactly 1 on every mutation. The entities carrying this full set are `Tenant`, `Member`, `Lease`, `Resource`, `Reservation`, `AccessBadge`, and `Bill`.

Two entities are lighter. A `Visitor` is stamped only with `id` and `created_at` — the `updated_at` timestamp and the `version` field are intentionally absent, because the visitor lifecycle (registration, arrival, departure) is already captured by its own timestamp columns and terminal status, and no optimistic-concurrency traffic is expected on the object. A `BillLine` likewise carries only `id` and `created_at`; bill lines are append-only artifacts of source calculations and are mutated only by voiding the parent bill.

### 2.5. Optimistic Concurrency Control

Every mutating endpoint that acts on a versioned row accepts an optional `version` field in the request body. When the caller omits `version`, the server performs no concurrency check. When the caller supplies `version`, the server compares the supplied integer to the current `version` of the target row; if the two disagree, the request is rejected with `ERR_VERSION_CONFLICT`. On a successful mutation, the server increments `version` by 1 and refreshes `updated_at` to the current clock. Callers that stage a read-modify-write flow should always echo back the `version` they observed to defend against concurrent mutation.

Beyond explicit `version` checks, the platform guarantees first-writer-wins serialization on five specific races. Two members, whether of the same tenant or of different tenants, who attempt to reserve the same `Resource` over overlapping half-open intervals will be serialized on `resource_id`; the loser is rejected with `ERR_RESERVATION_CONFLICT` and never reaches `PENDING`. A member triggering a badge check-in on a reservation while an administrator concurrently cancels that same reservation will be serialized on `Reservation.status`; exactly one transition succeeds and the loser, observing the terminal state, is rejected with `ERR_INVALID_RESERVATION_STATE`. A `PaymentClerk` paying a bill while the nightly overdue sweep concurrently advances the same bill from `ISSUED` to `OVERDUE` will be serialized on `Bill.status`; the loser sees the new status and is rejected with `ERR_INVALID_BILL_STATE`. Two administrators of the same tenant concurrently submitting a lease termination request will be serialized on `Lease.status`; at most one lease transitions from `ACTIVE` to `TERMINATION_REQUESTED`, and the loser is rejected with `ERR_INVALID_LEASE_STATE`. A host member revoking a visitor while reception concurrently performs the visitor check-in will be serialized on `Visitor.status`; exactly one transition succeeds and the loser is rejected with `ERR_INVALID_VISITOR_STATE`.

### 2.6. Time, Intervals, and Clock

All timestamps transmitted by the API are ISO 8601 UTC with three fractional digits. Reservation intervals are **half-open on the right**: a reservation with `start_at` 09:00 and `end_at` 11:00 occupies the time range that includes 09:00 and excludes 11:00, so back-to-back reservations of 09:00–11:00 and 11:00–13:00 on the same resource do not conflict. Reservation `start_at` and `end_at` must land on integer-minute boundaries (no sub-minute precision is accepted), `start_at` must be strictly earlier than `end_at`, and both endpoints must lie within the window that begins one hour before the current clock and ends 180 days after it; any violation is rejected with `ERR_INVALID_TIME_WINDOW`.

For test-driving purposes the platform exposes a logical clock. A `PlatformAdmin` may advance the clock to a supplied `to_timestamp` (ISO 8601 UTC), and may separately invoke a sweep that promotes reservations, visitors, and bills through their deferred transitions in a fixed order: first, `CONFIRMED` reservations whose `end_at` has passed transition to `NO_SHOW` if no check-in ever happened, otherwise to `COMPLETED`; second, `CHECKED_IN` visitors whose `expected_departure_at` plus six hours has passed transition to `CHECKED_OUT` with overstay accounting applied; third, `REGISTERED` visitors whose `expected_departure_at` has passed without any check-in transition to `NO_SHOW`; fourth, `ISSUED` bills whose `due_at` has passed transition to `OVERDUE` with the late fee computed; fifth, bills already in `OVERDUE` have their late fee recomputed against the current week count; sixth, `Tenant.outstanding_balance_cents` and `Tenant.access_posture` are recomputed for every affected tenant. Advancing the clock does not run the sweep; the sweep runs only when invoked.

### 2.7. Nested-Resource Path Validation

Path parameters are resolved strictly left-to-right. The path variables used across the API are `{tenantId}`, `{leaseId}`, `{memberId}`, `{reservationId}`, `{visitorId}`, `{badgeId}`, and `{billId}`. For a URL that names a tenant and then a lease under that tenant, the server first resolves the tenant; if the tenant does not exist the response is `ERR_NOT_FOUND` and the lease identifier is never inspected. If the tenant exists but the lease does not, the response is `ERR_NOT_FOUND` and no further cascade is evaluated. The same left-to-right rule applies to any other nested lookup (tenant → member, bill → line, and so on). Body-level foreign keys — `tenant_id`, `member_id`, `resource_id`, `host_member_id`, `bill_id` — are also resolved; if any one of them references a row that does not exist, the response is `ERR_REFERENCED_ENTITY_MISSING`.

### 2.8. Validation Ordering

When a single request is potentially rejectable by multiple rules, the server evaluates rules in a fixed priority order and reports the earliest applicable failure. Authentication comes first: missing headers produce `ERR_MISSING_AUTH`, then an unknown role produces `ERR_UNKNOWN_ROLE`, then an RBAC denial produces `ERR_FORBIDDEN`. Next comes existence: path parameters that do not resolve yield `ERR_NOT_FOUND`, then body-level foreign keys that do not resolve yield `ERR_REFERENCED_ENTITY_MISSING`. Next comes state: a supplied `version` that does not match yields `ERR_VERSION_CONFLICT`, then an illegal state transition yields the per-entity state error (`ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_BILL_STATE`, `ERR_INVALID_LEASE_STATE`, or `ERR_INVALID_VISITOR_STATE`, as applicable). Business-safety checks follow — segregation of duties first, then access-posture gating, then cross-tenant referential checks, then temporal checks such as reservation window and granularity and capacity, then the fiscal guards on bill issuance and lease finalization, and finally pagination-range validation on list endpoints. This ordering is important: a single request that is both unauthenticated and touches a non-existent tenant must surface the auth error, not the existence error.

### 2.9. Money, Precision, and Rounding

All monetary quantities are stored and transmitted as **integer cents** — no field carries fractional cents on the wire. Intermediate arithmetic that produces a non-integral cent amount is rounded half-up to the nearest integer cent, with the single exception of the meeting-room and workstation-hourly provisional and final fee calculations where the source rate is already denominated in integer cents per hour and the operand reaching the rounding step is a multiplication of hours by that rate (rounding still applies when a half-cent appears, always half-up).

Tax is computed **sum-then-round**: tax is applied once to the sum of a bill's line amounts, not per line. This matters because summing per-line taxes and summing the subtotal then taxing can differ by one cent on bills whose per-line amounts have specific fractional shapes; the platform pins the sum-then-round variant. Per-line amounts are themselves rounded by their source calculation (final reservation fee, visitor overstay fee, lease termination penalty, or monthly commitment) at the moment the `BillLine` is written, so the tax step operates on already-rounded integer inputs.

The late-fee formula is **non-compounding**: the late fee is always computed against the principal `subtotal_cents + tax_cents`, never against the previously stored `late_fee_cents`. Each weekly sweep rewrites `late_fee_cents` (it does not add to it), and `total_due_cents` is the plain sum of `subtotal_cents`, `tax_cents`, and `late_fee_cents`.

### 2.10. Access Posture — Tenant Gate

Every tenant carries a computed `access_posture` of `OPEN`, `RESTRICTED`, or `FROZEN` that gates new reservations, visitor check-ins, and access-badge activations. The posture is derived by the following ordered evaluation, where each clause short-circuits if it matches. If `Tenant.status` is `CLOSED`, posture is `FROZEN`. Otherwise, if any lease belonging to this tenant is in `TERMINATION_REVIEWING`, posture is `RESTRICTED`. Otherwise, if `Tenant.status` is `TERMINATING`, posture is `RESTRICTED`. Otherwise, if the tenant has any bill in `OVERDUE` whose `due_at` was passed by strictly more than 30 days ago, posture is `FROZEN`. Otherwise, if `outstanding_balance_cents` is greater than or equal to `credit_limit_cents`, posture is `RESTRICTED`. Otherwise, posture is `OPEN`. The posture is recomputed on every mutation to `Tenant.outstanding_balance_cents`, every `Bill.status` change, and on lease termination finalization.

The gates are operation-specific. Confirming a reservation requires `access_posture` equal to `OPEN`; a tenant in `RESTRICTED` or `FROZEN` cannot confirm new reservations and the confirmation is rejected with `ERR_ACCESS_POSTURE_DENIES`. Checking in to a confirmed reservation is more permissive: `access_posture` of `OPEN` or `RESTRICTED` is acceptable, but `FROZEN` blocks the check-in and returns `ERR_ACCESS_POSTURE_DENIES`. Visitor check-in is blocked only when `access_posture` is `FROZEN`; both `OPEN` and `RESTRICTED` permit it.

### 2.11. Bill Consolidation and Period Boundaries

Reservations that complete or no-show, visitors that leave with a positive overstay fee, and leases that finalize a termination penalty all consolidate onto the tenant's **current DRAFT Bill for the tenant's current billing period**. If no DRAFT bill exists at the moment of consolidation, the server creates one before appending the line. Every appended line recomputes `subtotal_cents`, `tax_cents`, and `total_due_cents` on the bill. One `Bill` exists per `(tenant_id, billing_period)`; the period is represented by `period_start_date` and `period_end_date` on the bill itself.

Voiding a DRAFT bill clears `bill_id` on every `Reservation` and every `Visitor` that pointed to the voided bill, so that the next consolidation step will attach them to the next DRAFT bill of the same tenant.

## 3. Business Logic & Workflows

### 3.1. Tenants, Members, and Leases

A shared-office engagement begins when a `PlatformAdmin` creates a new `Tenant`, specifying the `legal_name` (a string of 1 to 120 characters) and an optional `credit_limit_cents`. The credit limit defaults to 500,000 cents (that is, 5,000 dollars expressed in cents) and must be zero or positive. The new tenant is created with `status` of `ACTIVE`, `access_posture` of `OPEN`, and `outstanding_balance_cents` of 0.

Members are provisioned under a tenant by either a `PlatformAdmin` or a `TenantAdmin` of that tenant, supplying a `tenant_id`, an `email` (unique across every member in the system regardless of tenant), a `full_name`, and an optional `role_in_tenant` which may be either `ADMIN` or `STAFF` and defaults to `STAFF`. The referenced tenant must be in `status` `ACTIVE` or `TERMINATING`; a closed tenant cannot take new members. A member starts in `status` `ACTIVE`; the full lifecycle also permits `SUSPENDED` and `REVOKED`.

Leasing is the financial anchor that governs workstation pricing. A `PlatformAdmin` drafts a `Lease` by naming the `tenant_id`, declaring the `billing_plan` as one of `HOURLY`, `DAILY`, or `MONTHLY`, optionally supplying the `monthly_rate_cents` (meaningful only when `billing_plan` is `MONTHLY`; zero or positive; defaults to 0), and providing inclusive `term_start_date` and `term_end_date` in `YYYY-MM-DD` form. The lease enters `DRAFT`. Activation, performed by a `PlatformAdmin`, transitions the lease from `DRAFT` to `ACTIVE` provided the tenant is itself `ACTIVE` and the `term_start_date` is not after the `term_end_date`.

The billing-plan choice is consequential: for members of a tenant whose active lease is `HOURLY`, workstation reservations are priced per hour; for a `DAILY` plan, workstation reservations are priced per eight-hour day, rounded up; for a `MONTHLY` plan, each individual workstation reservation's provisional fee is zero because the workstation entitlement is already paid for through the monthly commitment. The lease whose rules apply to a given reservation is the tenant's active lease with the latest `term_start_date` (ties broken by the greatest `Lease.id` in lexicographic order).

### 3.2. The Resource Inventory

A `PlatformAdmin` registers each bookable space as a `Resource`. Every resource carries a `kind` enumeration of `WORKSTATION`, `MEETING_ROOM`, or `EVENT_AREA`, a short `code` that must be unique across all resources (for example, `WS-12`, `MR-3`, `EVT-A`), a `capacity` that is at least 1, and three per-kind rate fields — `hourly_rate_cents`, `daily_rate_cents`, and `block_rate_cents` — each of which defaults to 0 when the kind in question does not use it. Meeting rooms use `hourly_rate_cents`. Workstations use `daily_rate_cents` for the daily-plan lane and `hourly_rate_cents` for the hourly-plan lane. Event areas use `block_rate_cents` where one block equals four hours. Any rate field not used by a given kind should be 0. A resource is created with `status` of `AVAILABLE`; the full lifecycle also supports `MAINTENANCE` and `RETIRED`.

### 3.3. Reservations — Creation, Confirmation, and the Dual-Variant Pricing Engine

A reservation is created by a `TenantMember` (for themselves) or a `TenantAdmin` (for any member of the same tenant), POSTing a payload that carries a `tenant_id`, a `member_id`, a `resource_id`, and the two endpoints `start_at` and `end_at`. The request is evaluated first for the cross-tenant referential rule: the `member_id` must belong to a `Member` whose `tenant_id` equals the `tenant_id` in the payload, otherwise `ERR_TENANT_MISMATCH` is returned. Then the temporal rules run: `start_at` must be strictly earlier than `end_at`, both must fall on integer-minute boundaries, and both must lie within the window from one hour before the current clock to 180 days after it; a violation surfaces `ERR_INVALID_TIME_WINDOW`. Then the per-kind granularity rule runs: event-area reservation duration must be an exact multiple of four hours, meeting-room duration must be a multiple of half an hour, and workstation duration must be a multiple of one full hour; a mismatch surfaces `ERR_RESERVATION_GRANULARITY`. Then the capacity check runs: `Resource.capacity` must be at least the requested headcount, which defaults to 1 when the caller omits it, otherwise `ERR_CAPACITY_EXCEEDED`. Finally, the overlap guard runs: the proposed half-open interval from `start_at` inclusive to `end_at` exclusive must not overlap any existing reservation on the same `resource_id` whose status is one of `PENDING`, `CONFIRMED`, or `IN_USE`; a collision surfaces `ERR_RESERVATION_CONFLICT`. A reservation that passes all of these enters `PENDING`.

Confirmation is a deliberate second step. Acting as a `TenantMember` or `TenantAdmin`, the caller confirms a reservation that is currently `PENDING`, which requires the tenant's `access_posture` to be `OPEN`, the resource's `status` to be `AVAILABLE`, the reserving member's `status` to be `ACTIVE`, and no other reservation on the same resource in `CONFIRMED` or `IN_USE` to overlap the requested interval. Confirmation transitions the reservation from `PENDING` to `CONFIRMED` and computes the **provisional fee**, which is stored on `provisional_fee_cents`. Cancelling a `PENDING` reservation is always permitted; cancelling a `CONFIRMED` reservation is only permitted while the current clock remains strictly earlier than `start_at`, and it clears `provisional_fee_cents` back to 0 because a future refund has not yet been consolidated.

The provisional fee is computed by resource kind. The duration in hours is the difference between `end_at` and `start_at`, expressed in fractional hours on the half-open interval. For a meeting room, the billable unit count is the duration in hours rounded up to the nearest half-hour (so any spill past a half-hour boundary costs another half-hour), and the fee is the product of those units and `hourly_rate_cents`, rounded half-up to the nearest integer cent; the constant governing this rounding boundary is the meeting-room rounding unit of half an hour. For an event area, the block count is the duration in hours divided by four and rounded up (so a two-hour booking still costs one four-hour block); the gross fee is the block count multiplied by `block_rate_cents`; if both `start_at` and `end_at` fall on a Saturday or Sunday (the full-weekend condition), the gross is halved via integer division by two (a 50% full-weekend discount); otherwise the gross is the fee. For a workstation, pricing follows the tenant's governing active lease's `billing_plan`: an `HOURLY` plan multiplies the raw fractional hours by `hourly_rate_cents` and rounds half-up to the nearest integer cent; a `DAILY` plan divides the hours by the workstation-daily constant of eight hours per day, rounds up to the next whole day, and multiplies that day count by `daily_rate_cents`; a `MONTHLY` plan sets the provisional fee to 0 because the entitlement is already paid for through the monthly commitment.

Check-in is performed by the reserving `TenantMember` (or a `TenantAdmin` of the same tenant) through an access event. The access-event payload carries a `kind` (one of `CHECK_IN`, `CHECK_OUT`, `VISITOR_CHECK_IN`, `VISITOR_CHECK_OUT`), and, depending on the `kind`, a `reservation_id`, a `visitor_id`, and/or an optional `badge_id` identifying the physical badge used. To drive a reservation check-in, the event's `kind` is `CHECK_IN` and it names a matching `reservation_id`. Four preconditions must hold: the reservation must be in `CONFIRMED`, the member's `AccessBadge` must be `ACTIVE`, the tenant's `access_posture` must be `OPEN` or `RESTRICTED` (not `FROZEN`), and the current clock must lie within the 15-minute early-entry grace window before `start_at` through the reservation's `end_at` (exclusive). On success, the reservation transitions from `CONFIRMED` to `IN_USE`, `actual_start_at` is stamped with the current clock, and the badge's `last_used_at` is refreshed. If the tenant is in `FROZEN` when a check-in is attempted, the rejection carries `ERR_ACCESS_POSTURE_DENIES`.

Check-out is performed by the same member through an access event with `kind` equal to `CHECK_OUT` (or, alternatively, by the sweep when the current clock reaches `end_at` and the reservation is still `IN_USE`). The reservation must currently be `IN_USE`. On success, the reservation transitions from `IN_USE` to `COMPLETED`. The `actual_end_at` is set to the current clock when the transition was driven by an explicit check-out event, and to `end_at` when the transition was driven by the sweep. The **final fee** is then computed and stored on `final_fee_cents`, the reservation is associated to the tenant's current DRAFT bill (creating a new DRAFT bill if none exists for the tenant's current billing period), and the bill's `subtotal_cents`, `tax_cents`, and `total_due_cents` are recomputed.

The final fee is the second variant of the pricing engine, and it can differ from the provisional fee in two ways: first, because the actual time window can be shorter than the booked window (early check-out reduces hours for workstations and meeting rooms, though event-area blocks are pre-committed and never refunded); second, because for a workstation the cheaper tier is picked retrospectively — a booking that provisionally priced under `DAILY` may finalize under `HOURLY` if a short actual duration makes hourly arithmetic cheaper, and vice versa. The billable start is the later of `start_at` and `actual_start_at`; the billable end for a meeting room is the earlier of `end_at` and `actual_end_at` (late check-out past `end_at` is capped at `end_at`), while for a workstation the billable end is `actual_end_at` (the workstation lane allows early check-out to reduce hours but does not penalize tiny clock drift); for an event area the final fee is simply the provisional fee because blocks do not refund. The billable duration in hours is the difference of these endpoints expressed in fractional hours, clamped at zero. For a meeting room the billable unit count is the billable duration rounded up to the nearest half-hour and the fee is that count multiplied by `hourly_rate_cents`, rounded half-up to the nearest integer cent. For a workstation under a `MONTHLY` plan the final fee is 0; for a workstation under `HOURLY` or `DAILY`, two candidate fees are computed — the hourly candidate is the billable duration multiplied by `hourly_rate_cents`, rounded half-up to the nearest integer cent, and the daily candidate is the billable duration divided by the eight-hour-per-day constant, rounded up to the next whole day, then multiplied by `daily_rate_cents` — and the smaller of the two is chosen as the final fee; when the two candidates are exactly equal, the hourly candidate wins and the chosen plan is recorded as `HOURLY`. Concretely, a member who books a workstation for eight hours on a `DAILY` plan (say, 50.00 daily, 8.00 hourly: daily 50.00 beats hourly 64.00 at booking) but actually leaves after five hours will finalize at the hourly 40.00 because it is now cheaper than the daily 50.00 — that is the provisional-versus-final flip the finalization step is allowed to make.

A reservation that never gets a check-in also has to be reconciled: when the sweep observes a reservation still in `CONFIRMED` after `end_at` has passed, it transitions the reservation from `CONFIRMED` to `NO_SHOW`, sets `final_fee_cents` equal to the already-stored `provisional_fee_cents` (no-shows still bill), consolidates the reservation onto the tenant's current DRAFT bill, and recomputes the bill totals. A reservation in `PENDING` that is swept past its `end_at` is handled identically. A `CANCELLED` reservation generates no bill line and leaves no financial trace; its `provisional_fee_cents` has been cleared.

### 3.4. Visitors and Overstay

A `TenantMember` or `TenantAdmin` registers a `Visitor` by supplying `host_member_id`, `visitor_name`, `expected_arrival_at`, and `expected_departure_at`. The host member must belong to the same tenant as the denormalized `tenant_id` recorded on the visitor; if the host belongs to a different tenant, the registration is rejected with `ERR_TENANT_MISMATCH`. The declared visit window must be internally consistent: `expected_arrival_at` must be strictly earlier than `expected_departure_at`, and the span between them must be at most 24 hours; otherwise `ERR_INVALID_VISITOR_WINDOW`. On success the visitor enters `REGISTERED`.

Check-in is performed by a `Receptionist` through an access event with `kind` equal to `VISITOR_CHECK_IN` and a `visitor_id`. The visitor must currently be `REGISTERED`, the host member's `status` must be `ACTIVE`, the tenant's `access_posture` must not be `FROZEN`, and the current clock must lie within the window from 30 minutes before `expected_arrival_at` through six hours after `expected_departure_at`. On success, the visitor transitions from `REGISTERED` to `CHECKED_IN` and `actual_arrival_at` is stamped with the current clock.

Check-out is also performed by a `Receptionist` (or by the sweep when the current clock reaches six hours past `expected_departure_at` and the visitor is still `CHECKED_IN`). The visitor transitions from `CHECKED_IN` to `CHECKED_OUT`. The `actual_departure_at` is set to the current clock for an explicit check-out event, or to `expected_departure_at` plus six hours when the transition was driven by the sweep. The overstay fee is then computed into `overstay_fee_cents`: the overstay seconds are the larger of zero and the difference between `actual_departure_at` and `expected_departure_at`; the overstay minutes are that span divided by sixty; if the overstay is at most zero, the overstay fee is zero; otherwise the billable unit count is the overstay minutes divided by thirty and rounded up to the next whole unit, and the fee is that unit count multiplied by 500 cents per 30-minute block (that is, 5.00 dollars for each started half-hour). Because rates and unit counts are both integer, no fractional rounding is needed here. When the overstay fee is strictly greater than zero, the visitor is consolidated onto the tenant's current DRAFT bill (creating one if missing) and the bill totals are recomputed; when the overstay fee is zero, no bill line is written and `bill_id` remains absent.

Two terminal branches handle absence and cancellation. If the sweep observes a visitor still `REGISTERED` after `expected_departure_at` has passed, it transitions the visitor to `NO_SHOW` with no side effects. If the host member (or a `TenantAdmin` of the tenant) explicitly revokes a `REGISTERED` visitor before the visit, the visitor transitions to `REVOKED` with no side effects. Both branches are terminal.

### 3.5. Access Badges

A `PlatformAdmin` issues an `AccessBadge` to a `Member` by supplying `member_id` and a `badge_serial` that must be unique across all badges. The badge enters `ACTIVE`, with `last_used_at` initially absent. A `PlatformAdmin` may suspend an `ACTIVE` badge, move a `SUSPENDED` badge back to `ACTIVE` (which is only allowed when the owning tenant's `access_posture` is not `FROZEN` and the member's `status` is `ACTIVE`), or revoke either an `ACTIVE` or a `SUSPENDED` badge (which is terminal). A `SUSPENDED` badge blocks reservation check-ins and causes `ERR_INVALID_RESERVATION_STATE`-or-precondition-denial on any attempted access event that would have transitioned a reservation from `CONFIRMED` to `IN_USE`.

One further cascade governs badges. When a lease termination is finalized, every badge belonging to members of that tenant is scheduled to suspend on the lease's `termination_effective_date`. The actual transition from `ACTIVE` to `SUSPENDED` is performed by the sweep when it advances past that date — the cascade is deferred, not immediate.

### 3.6. The Lease Termination Process

Early termination is a multi-step process deliberately split across two platform users to enforce segregation of duties. A `TenantAdmin` of the tenant begins the process by requesting termination on an `ACTIVE` lease, transitioning the lease from `ACTIVE` to `TERMINATION_REQUESTED`. As a side effect, every `Reservation` of the same tenant whose `status` is `PENDING` or `CONFIRMED` and whose `start_at` is strictly after the current clock is cascade-cancelled to `CANCELLED`, and each of these cascades in turn clears `provisional_fee_cents` on the affected reservation. Reservations already in progress (`IN_USE`) are not cancelled; they continue to their natural check-out. The same `TenantAdmin` may withdraw the request at any time before the platform takes review: withdrawing transitions the lease from `TERMINATION_REQUESTED` back to `ACTIVE`, forming the reversible cycle `ACTIVE → TERMINATION_REQUESTED → ACTIVE`. Withdrawal has no other side effects; the already-cancelled future reservations are not restored.

A `PlatformAdmin` takes review by transitioning the lease from `TERMINATION_REQUESTED` to `TERMINATION_REVIEWING`. The server records the reviewing admin's `X-User-ID` on the lease as its `reviewer_user_id` — this is the identity that the later finalization step must differ from.

From `TERMINATION_REVIEWING` the process forks. A different `PlatformAdmin` may finalize the termination, transitioning the lease from `TERMINATION_REVIEWING` to `TERMINATED`. Finalization enforces segregation of duties: the acting `PlatformAdmin`'s `X-User-ID` must not equal the `reviewer_user_id` recorded at `begin-review`; if they match, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Finalization also requires a clean tenant: every reservation of the tenant whose status is `PENDING`, `CONFIRMED`, or `IN_USE` must be cancelled or completed first, otherwise `ERR_HAS_OPEN_RESERVATIONS`; and every bill of the tenant whose status is `DRAFT` must be issued or voided first, otherwise `ERR_HAS_DRAFT_BILLS`. On success, four side effects fire. First, the `termination_penalty_cents` is computed and the `termination_effective_date` is set to today's date. Second, a `BillLine` with `line_kind` equal to `TERMINATION_PENALTY`, `source_entity_id` equal to the lease's `id`, and `amount_cents` equal to `termination_penalty_cents` is appended to the tenant's current DRAFT bill (creating one if missing). Third, `Tenant.status` is set to `TERMINATING`, which in turn triggers a recomputation of `Tenant.access_posture` and flips the tenant to `RESTRICTED` if it was not already at least as restrictive. Fourth, every `AccessBadge` belonging to members of this tenant is scheduled to suspend on the `termination_effective_date` (the actual `ACTIVE → SUSPENDED` transition is performed by the sweep when it crosses that date). Alternatively, the `PlatformAdmin` may reject the termination, transitioning the lease from `TERMINATION_REVIEWING` to `REJECTED`, which is terminal and has no further side effects.

The termination penalty is computed as follows. The number of remaining full calendar months is the count of full calendar-month boundaries strictly after `termination_effective_date` up to and including `Lease.term_end_date`, clamped at zero below. If the lease's `billing_plan` is `MONTHLY`, the penalty is the remaining-full-months count multiplied by `monthly_rate_cents` multiplied by the penalty factor of 0.3 (that is, 30%), with the final product rounded half-up to the nearest integer cent. If the lease's `billing_plan` is `HOURLY` or `DAILY`, the penalty is 0 — the monthly-commitment penalty does not apply to non-monthly plans. The penalty becomes a bill line on the tenant's current DRAFT bill as described above.

### 3.7. Bills — Consolidation, Issuance, Payment, Late Fees, and Voiding

Every tenant has at most one DRAFT bill per billing period; a new one is created automatically at the moment some chargeable event (a completed reservation, a no-show reservation, a visitor overstay with a positive fee, or a termination penalty) needs a place to land. Each chargeable event appends a `BillLine` whose `bill_id` points at the DRAFT bill, whose `line_kind` identifies the source (`WORKSTATION_FEE`, `MEETING_ROOM_FEE`, `EVENT_AREA_FEE`, `VISITOR_OVERSTAY`, `TERMINATION_PENALTY`, or `MONTHLY_COMMITMENT`), whose `source_entity_id` is the polymorphic foreign key to the originating `Reservation`, `Visitor`, or `Lease`, and whose `amount_cents` has already been rounded at the source. The bill's `subtotal_cents` is the sum of `final_fee_cents` for its `COMPLETED` or `NO_SHOW` reservations, plus `overstay_fee_cents` for its `CHECKED_OUT` visitors with a consolidated fee, plus any termination-penalty line amount. Every append recomputes `subtotal_cents`, `tax_cents`, and `total_due_cents` on the bill.

Tax is applied once to the subtotal: `tax_cents` is the product of `subtotal_cents` and a tax rate of 8.25% (that is, 0.0825), rounded half-up to the nearest integer cent. The critical invariant is that tax is computed on the sum, not per line; implementations that accidentally tax each line and sum can differ by a cent on bills whose per-line amounts have particular fractional tails.

A `BillingOfficer` issues a DRAFT bill by transitioning it from `DRAFT` to `ISSUED`. Issuance has four preconditions. The bill must be in `DRAFT`, otherwise `ERR_INVALID_BILL_STATE`. The bill must carry at least one `BillLine` (equivalently, `subtotal_cents` must be strictly greater than zero), otherwise `ERR_EMPTY_BILL`. Every reservation pointing at this bill via `bill_id` must be in `COMPLETED` or `NO_SHOW`; a reservation still in `PENDING`, `CONFIRMED`, or `IN_USE` blocks issuance with `ERR_BILL_HAS_OPEN_RESERVATIONS`. The optional `version` may be supplied for concurrency control. On success, `issued_at` is stamped with the current clock and `due_at` is set to exactly 14 days after `issued_at`. The transition then enters the new bill into the tenant's outstanding balance, and `Tenant.outstanding_balance_cents` is recomputed as the sum of `total_due_cents` for every bill of the tenant whose status is `ISSUED` or `OVERDUE`. If the new outstanding balance is greater than or equal to the tenant's `credit_limit_cents`, the tenant's `access_posture` flips from `OPEN` to `RESTRICTED` per the evaluation ladder.

Payment is performed by a `PaymentClerk`, transitioning the bill from either `ISSUED` or `OVERDUE` to `PAID`. The `paid_at` is stamped with the current clock, `Tenant.outstanding_balance_cents` is recomputed (the paid bill no longer contributes to the sum), and `Tenant.access_posture` is recomputed accordingly — payment may relax a `FROZEN` tenant to `RESTRICTED` or `OPEN`, and may relax a `RESTRICTED` tenant to `OPEN`. Note that this path is the one racing against the nightly overdue sweep; the serialization is on `Bill.status`, and the loser observes the new status and is rejected with `ERR_INVALID_BILL_STATE`.

Overdue accrual is managed by the sweep. When the sweep observes an `ISSUED` bill whose `due_at` has passed, it transitions the bill to `OVERDUE` and recomputes the late fee. The late-fee formula counts the number of strictly-full weeks past the due date: the number of weeks is the floor of the number of seconds between the current clock and `due_at`, divided by seven days. At exactly the seven-day mark, the count becomes 1; at six days 23 hours the count is still 0 and the late fee is therefore 0. The principal on which the late fee is applied is `subtotal_cents + tax_cents` — the late fee does not compound on itself. The late fee is the product of that principal, a weekly rate of 1.5% (that is, 0.015), and the week count, rounded half-up to the nearest integer cent. The sweep rewrites `late_fee_cents` (it does not add), and `total_due_cents` is then set to `subtotal_cents + tax_cents + late_fee_cents`. After the overdue transition, `Tenant.outstanding_balance_cents` is recomputed, and `Tenant.access_posture` flips from `RESTRICTED` to `FROZEN` if any bill of this tenant has been `OVERDUE` for strictly more than 30 days.

A `PlatformAdmin` may void a DRAFT bill by transitioning it from `DRAFT` to `VOIDED`. The cascade clears `bill_id` on every `Reservation` and every `Visitor` linked to this bill, which allows those entries to re-consolidate onto the next DRAFT bill of the same tenant. Voiding is available only from `DRAFT`; an `ISSUED`, `OVERDUE`, or `PAID` bill cannot be voided.

## 4. Endpoint Definitions

All endpoints are mounted under the `/shared-office` prefix. Endpoints that create a new resource return HTTP 201; endpoints that read a resource or modify an existing resource's state return HTTP 200. Error responses carry their canonical HTTP status from the error catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| GET | `/shared-office/health` | Health check | PlatformAdmin, TenantAdmin, TenantMember, BillingOfficer, PaymentClerk, Receptionist |
| POST | `/shared-office/_clock/advance` | Advance the logical clock to the supplied `to_timestamp` (tests only) | PlatformAdmin |
| POST | `/shared-office/_sweep/run` | Run the deferred-action sweep (tests only) | PlatformAdmin |
| POST | `/shared-office/tenants` | Create a tenant | PlatformAdmin |
| GET | `/shared-office/tenants/{tenantId}` | Fetch a tenant (with computed `outstanding_balance_cents` and `access_posture`) | PlatformAdmin, TenantAdmin, BillingOfficer |
| GET | `/shared-office/tenants` | List tenants, filtered by `status` if provided | PlatformAdmin, BillingOfficer |
| POST | `/shared-office/leases` | Draft a lease | PlatformAdmin |
| POST | `/shared-office/leases/{leaseId}/activate` | Activate a draft lease | PlatformAdmin |
| POST | `/shared-office/leases/{leaseId}/request-termination` | Request early termination | TenantAdmin |
| POST | `/shared-office/leases/{leaseId}/withdraw-termination` | Withdraw a pending termination request | TenantAdmin |
| POST | `/shared-office/leases/{leaseId}/begin-review` | Begin platform review of a termination request (records the reviewer user) | PlatformAdmin |
| POST | `/shared-office/leases/{leaseId}/finalize-termination` | Finalize termination (segregated from the reviewer) | PlatformAdmin |
| POST | `/shared-office/leases/{leaseId}/reject-termination` | Reject termination | PlatformAdmin |
| GET | `/shared-office/leases/{leaseId}` | Fetch a lease | PlatformAdmin, TenantAdmin |
| POST | `/shared-office/members` | Create a member under a tenant | PlatformAdmin, TenantAdmin |
| GET | `/shared-office/members/{memberId}` | Fetch a member | PlatformAdmin, TenantAdmin, TenantMember |
| POST | `/shared-office/resources` | Register a bookable resource | PlatformAdmin |
| GET | `/shared-office/resources` | List resources, filtered by `kind` and/or `status` if provided | PlatformAdmin, TenantAdmin, TenantMember |
| POST | `/shared-office/reservations` | Create a reservation (enters PENDING) | TenantMember, TenantAdmin |
| POST | `/shared-office/reservations/{reservationId}/confirm` | Confirm a pending reservation (computes `provisional_fee_cents`) | TenantMember, TenantAdmin |
| POST | `/shared-office/reservations/{reservationId}/cancel` | Cancel a pending or pre-start confirmed reservation | TenantMember, TenantAdmin |
| GET | `/shared-office/reservations/{reservationId}` | Fetch a reservation | PlatformAdmin, TenantAdmin, TenantMember |
| GET | `/shared-office/reservations` | List reservations; filter by `tenant_id`, `resource_id`, `status`, `start_after`, `start_before` | PlatformAdmin, TenantAdmin, TenantMember, BillingOfficer |
| POST | `/shared-office/visitors` | Register a visitor | TenantMember, TenantAdmin |
| POST | `/shared-office/visitors/{visitorId}/revoke` | Revoke a registered visitor before check-in | TenantMember, TenantAdmin |
| GET | `/shared-office/visitors/{visitorId}` | Fetch a visitor | PlatformAdmin, TenantAdmin, TenantMember, Receptionist |
| POST | `/shared-office/access-badges` | Issue an access badge to a member | PlatformAdmin |
| POST | `/shared-office/access-badges/{badgeId}/suspend` | Suspend an active badge | PlatformAdmin |
| POST | `/shared-office/access-badges/{badgeId}/reactivate` | Reactivate a suspended badge | PlatformAdmin |
| POST | `/shared-office/access-badges/{badgeId}/revoke` | Revoke a badge (terminal) | PlatformAdmin |
| POST | `/shared-office/access-events` | Record an access event driving reservation and visitor check-in/check-out | TenantMember, TenantAdmin, Receptionist |
| POST | `/shared-office/bills/{billId}/issue` | Issue a DRAFT bill | BillingOfficer |
| POST | `/shared-office/bills/{billId}/pay` | Mark a bill paid | PaymentClerk |
| POST | `/shared-office/bills/{billId}/void` | Void a DRAFT bill | PlatformAdmin |
| GET | `/shared-office/bills/{billId}` | Fetch a bill (including its lines) | PlatformAdmin, TenantAdmin, BillingOfficer, PaymentClerk |
| GET | `/shared-office/bills` | List bills, filtered by `tenant_id` and/or `status` | PlatformAdmin, TenantAdmin, BillingOfficer, PaymentClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_MISSING` | 404 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_RESERVATION_CONFLICT` | 409 |
| `ERR_INVALID_RESERVATION_STATE` | 409 |
| `ERR_INVALID_BILL_STATE` | 409 |
| `ERR_INVALID_LEASE_STATE` | 409 |
| `ERR_INVALID_VISITOR_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_ACCESS_POSTURE_DENIES` | 422 |
| `ERR_TENANT_MISMATCH` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_RESERVATION_GRANULARITY` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_HAS_OPEN_RESERVATIONS` | 422 |
| `ERR_HAS_DRAFT_BILLS` | 422 |
| `ERR_EMPTY_BILL` | 422 |
| `ERR_BILL_HAS_OPEN_RESERVATIONS` | 422 |
| `ERR_INVALID_VISITOR_WINDOW` | 422 |
| `ERR_PAGINATION_OUT_OF_RANGE` | 400 |

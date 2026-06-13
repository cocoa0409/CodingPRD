# Locksmith & Lockout Dispatch API — Product Requirements Document

## 1. Introduction

This document specifies the Locksmith & Lockout Dispatch API, the operational backbone for a mobile-and-bench locksmith business that handles emergency lockouts, rekeying, hardware installation, and safe work. The platform coordinates the full arc of a service call: a customer's intake request, the dispatch of a certified technician with a promised arrival window, the on-site assessment that turns a rough call-out estimate into a measured final quote, the holding and consumption of lock parts from inventory, the capture of payment, and — should something fail later — the adjudication of warranty claims and refunds.

Two themes recur throughout. First, the business runs on two parallel clocks that are deliberately decoupled: a job's operational progress (intake through closure) advances independently of its money state (unpaid through paid or refunded), and the system must keep both axes coherent without letting one mask the other. Second, the same quantity is frequently computed twice from different vantage points — a forward-looking estimate at dispatch versus a measured final at the curb, a promised ETA at assignment versus a stamped actual at arrival — and the rules for each variant are distinct and must not be conflated. Pricing layers an after-hours window and an emergency-lockout surcharge on top of flat call-out and measured-labor rates, while inventory enforces a conserved unit ledger protected by optimistic concurrency so that two technicians cannot both spend the last blank.

The audience for this document is the engineering team building the reference implementation. It describes domain behavior first and wire format second; every rule a test could assert is stated here in prose.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_AUTH_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `Dispatcher`, `Technician`, `Customer`, `InventoryManager`, and `BillingAgent`. The operations desk role `Dispatcher` intakes jobs, dispatches technicians, manages bays and bay bookings, closes and cancels jobs, and adjudicates warranty claims. The `Technician` role covers field and bench work: departing, arriving, drafting/editing/submitting/reopening quotes, reserving parts, filing authorization records, and marking work complete. The `Customer` role is the job owner who approves, rejects, or revises submitted quotes and files warranty claims. The `InventoryManager` role owns the lock-part catalog and stock. The `BillingAgent` role captures payments against approved quotes.

The meaning of `X-User-ID` differs by role, and ownership checks depend on it. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; the technician identity is entity-backed, so a `Technician` principal corresponds to a persisted technician record. For the other four roles the identifier is opaque. When `X-User-Role` is `Dispatcher`, `InventoryManager`, or `BillingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is likewise an opaque principal identifier; it is not the `id` of a stored entity, but it is the value recorded as `customer_user_id` on a `ServiceJob` at intake, and ownership checks compare a job's `customer_user_id` to the acting `X-User-ID`. A `Customer` acting on a quote or warranty claim whose parent job's `customer_user_id` does not equal the caller's `X-User-ID` is rejected with `ERR_NOT_JOB_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Most resources in this system are mutable and carry a uniform set of system-managed fields. Every such resource exposes an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change, and an integer `version` that begins at 1 on creation and increments by one with each mutation. The mutable resources are `ServiceJob`, `Technician`, `JobBay`, `Dispatch`, `BayBooking`, `OnSiteQuote`, `LockPart`, `PartReservation`, `Payment`, and `WarrantyClaim`.

The `KeyAuthorizationRecord` is the sole exception: it is an append-only compliance record that is never updated after creation. It carries only `id` and `created_at`; it has no `updated_at` field and no `version` field, and there is no endpoint that mutates it once filed.

When the server mutates a resource as a side effect of another operation — for example, recomputing a job's money fields when a payment lands, or transitioning a child resource during a cascade — that mutation is a real change: it refreshes the resource's `updated_at` and increments its `version` exactly as a direct edit would. Recomputed fields such as `amount_due_cents`, `net_paid_cents`, `units_available`, `units_reserved`, and `units_committed` are themselves system-managed and are never accepted as client input.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address a resource through a path that names a parent and then a child, such as a job's dispatches, quotes, payments, authorization records, or warranty claims. For these, the server validates the existence of each identifier from left to right. The parent job's existence is checked first; if the job id does not resolve, the request fails with `ERR_JOB_NOT_FOUND` before any child is consulted. Only once the parent resolves does the server look up the child resource named further right in the path, returning the child-specific not-found error if that lookup fails.

This left-to-right discipline holds for all referenced ids, whether they arrive in the path or the body. Existence checks as a class run after authentication and authorization but before any state or business rule: a request that names a non-existent technician, bay, quote, dispatch, lock part, reservation, payment, or claim is rejected with the corresponding not-found error (`ERR_TECHNICIAN_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_LOCKPART_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`) ahead of any deeper validation.

### 2.6. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: first, authentication — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_MISSING_AUTH_CONTEXT`. Second, authorization — the role must be permitted for the operation, else `ERR_FORBIDDEN_ROLE`. Third, existence — every referenced id, validated left-to-right, must resolve, else the matching not-found error. Fourth, business-referential ownership — a `Customer` acting on a quote or filing a warranty claim must own the parent job, else `ERR_NOT_JOB_OWNER`. Fifth, the target resource's state must permit the requested transition, else the relevant state-conflict error. Sixth and beyond come the operation-specific business constraints (technician availability and certification, ETA-window and bay-slot geometry, authorization-on-file, part status and quantity, stock sufficiency, payment and refund bounds, and the optimistic-concurrency version check), each described alongside the workflow it guards in §3. Where an endpoint layers more than one of these later checks, the specific ordering relevant to that endpoint is called out in the workflow narrative.

### 2.7. Monetary and Temporal Precision

All money in the system is carried as an integer number of cents; there are no fractional-cent values stored or returned. Where a calculation multiplies cents by a labor-hour or surcharge factor and could land between whole cents, the result is rounded half up to the nearest whole cent. The precise point at which rounding is applied matters for the final quote and is specified in §3 with the calculation; in particular, surcharge multipliers are applied and rounded per line item before the lines are summed, never summed first and rounded once.

Time-of-day values — when a service is requested, when a technician's ETA window opens and closes, when a technician arrives, when a warranty claim is filed — are integer minutes from local midnight, ranging from 0 through 1439 inclusive. A minute value outside that range, or an ETA window or bench slot whose endpoints are out of order, is rejected with `ERR_INVALID_TIME_WINDOW`. Response-time figures are likewise integer minutes.

### 2.8. Inventory as a Conserved Unit Ledger

Each `LockPart` tracks four unit counts whose relationship is an invariant the system never violates: the total physical units owned, `units_total`, always equals the sum of `units_available` (free to reserve), `units_reserved` (held by live reservations), and `units_committed` (consumed by completed work). On creation a part's `units_available` equals its `units_total`, with `units_reserved` and `units_committed` both starting at 0. As reservations are made, committed, or released, the system recomputes these counts so the invariant holds at all times. `units_reserved` is the sum of `quantity` across this part's reservations in `RESERVED` status; `units_committed` is the sum of `quantity` across its reservations in `COMMITTED` status; and `units_available` is `units_total` minus those two sums. `units_available` must never go negative — a reservation that would drive it below zero is refused before any count is touched.

### 2.9. Optimistic Concurrency on Inventory Stock

Reserving units of a `LockPart` is the one operation that participates in optimistic concurrency control, because two reservations against the same part race over the same available stock. A request to reserve parts must carry `expected_lockpart_version`, the `version` of the target `LockPart` the client last observed. If that value does not match the part's current `version`, the create is rejected with `ERR_STALE_LOCKPART_VERSION` and HTTP status 412, and no stock is touched. The rationale is stale availability: a successful reservation decrements `units_available` and bumps the part's `version`, so a writer whose view of the part predates a prior reservation is holding an out-of-date availability count, and its create must be turned away on the version check before it can overspend the stock. The version comparison is performed before the stock-sufficiency check. The same `expected_lockpart_version` field is required when an inventory manager restocks or discontinues a part, so that catalog edits made on a stale view are likewise rejected with `ERR_STALE_LOCKPART_VERSION`. No other endpoint accepts or requires a version field.

### 2.10. Hierarchical Consistency and Cascades

A job is the root of a small hierarchy — dispatches, quotes, part reservations (through quotes), bay bookings, payments, and warranty claims all hang off it — and several operations transition more than one of these in a single act. Wherever this document describes such a cascade, every affected resource is mutated in full: each transitioned child has its status changed, its `updated_at` refreshed, and its `version` incremented, and any recomputed parent figures (the job's money fields, a part's unit counts) are updated in the same operation. The cascades are spelled out where their triggering workflow lives in §3; the governing principle is that no child is left in a state inconsistent with its parent after the operation completes.

## 3. Business Logic & Workflows

### 3.1. Intake and the Two Job Axes

A `Dispatcher` opens the system's central resource, the **service job**, at intake by supplying the `customer_name`, the `customer_user_id` (the opaque id of the customer principal who will own the job), the `service_type`, the `service_address` where on-site work will be performed, the `requested_at_minute` (the time-of-day, in minutes from local midnight, at which service is requested), and optionally `is_emergency`. The `service_type` is one of `LOCKOUT`, `REKEY`, `INSTALL`, or `SAFE`; a value outside that set is rejected with `ERR_INVALID_ENUM`. The `is_emergency` flag defaults to `false` when omitted and marks the call as an after-hours emergency call-out. A freshly intaken job starts with `job_status` of `INTAKE`, `payment_status` of `UNPAID`, `amount_due_cents` of 0, and `net_paid_cents` of 0.

A job carries two independent status axes that advance separately. The operational axis, `job_status`, moves through `INTAKE`, `DISPATCHED`, `ON_SITE`, `WORK_COMPLETE`, and terminally `CLOSED`, or terminally `CANCELLED`. The money axis, `payment_status`, moves through `UNPAID`, `PARTIALLY_PAID`, `PAID`, and terminally `REFUNDED`. The two are coupled only at specific gates described below — closing a job requires it to be fully paid, and an approved warranty claim drives a refund — but otherwise a job's progress on one axis does not imply anything about the other. The job's `amount_due_cents` is a derived figure: it is 0 until a quote is approved, at which point it becomes the approved quote's final total; and `net_paid_cents` is the running money tally described in §3.7.

Any of the read endpoints lists or fetches jobs; the job list may be filtered by `service_type` and by `job_status`.

### 3.2. Dispatching a Technician and the Promised ETA

Before a technician can take work, that technician must exist in the roster. A `Dispatcher` registers a **technician** with a `full_name`, a `certified_for` array enumerating which `service_type` values the technician may handle (a subset of `LOCKOUT`, `REKEY`, `INSTALL`, and `SAFE`), and a `base_travel_minutes` figure — the nominal one-way travel time, which must be zero or greater, used to project arrival. A technician's `status` begins `ON_DUTY` and may be toggled by the dispatcher to `OFF_DUTY` (no longer dispatchable) and back to `ON_DUTY` through the duty-toggle actions; the off-duty transition leaves the technician undispatchable and the on-duty transition restores them. A technician may hold several scheduled dispatches at once, so going on a trip does not change the technician's `status`.

Dispatching is the act that advances a job from `INTAKE` to `DISPATCHED`. A `Dispatcher` sends a technician to a job by providing the `technician_id` together with a promised arrival window: `eta_start_minute` and `eta_end_minute`, both minutes from local midnight, with the end strictly greater than the start. This creates a **dispatch** resource in `ASSIGNED` status referencing the job through `service_job_id` and the technician through `technician_id`, and it transitions the parent job's `job_status` from `INTAKE` to `DISPATCHED`. Dispatch creation does not alter the technician's `status`; the technician remains `ON_DUTY` and may carry further non-overlapping dispatches.

This operation is gated by a sequence of checks. The job must currently be in `INTAKE`; a job in any other operational state is rejected with `ERR_JOB_NOT_DISPATCHABLE`. The named technician must be `ON_DUTY` — an `OFF_DUTY` technician yields `ERR_TECHNICIAN_UNAVAILABLE` — and the job's `service_type` must appear in that technician's `certified_for` list, failing which the dispatch is rejected with `ERR_TECHNICIAN_NOT_CERTIFIED`. Finally the promised window is checked for collisions against the technician's other live work, described in §3.3.

At the moment of dispatch the system projects a forward-looking response time and stores it as the dispatch's `promised_eta_minutes`. The projection is the technician's `base_travel_minutes` plus a queue penalty for each of the technician's other live dispatches: count the technician's dispatches that are currently in `ASSIGNED` or `EN_ROUTE` status (excluding the one being created), multiply that count by a ten-minute per-dispatch queue penalty, and add the product to the base travel time. The dispatch's `actual_response_minutes` is left unset at this point and is stamped only on arrival.

### 3.3. ETA Window Geometry and Re-dispatch

A technician's promised windows are not allowed to crowd each other, because a technician needs travel slack between jobs. Each live window is treated as a half-open interval on the technician's timeline running from `eta_start_minute` up to `eta_end_minute`, and is extended forward by a fifteen-minute travel buffer. The window being created, running from its start up to its end, collides with an existing live window of the same technician when the new window's start falls before the existing window's end plus the fifteen-minute buffer, and at the same time the existing window's start falls before the new window's end plus the same fifteen-minute buffer. Because the intervals are half-open, a new window that begins exactly at an existing window's end plus the buffer does not collide — adjacency at that boundary is allowed. "Live" here means the same technician's dispatches in `ASSIGNED` or `EN_ROUTE` status; cancelled and arrived dispatches do not constrain the timeline. A new dispatch whose window collides under this rule is rejected with `ERR_ETA_WINDOW_OVERLAP`.

Cancelling a dispatch frees its window. A `Dispatcher` may cancel a dispatch while it is in `ASSIGNED` or `EN_ROUTE`, moving it to `CANCELLED`; a dispatch already arrived or already cancelled cannot be cancelled and yields `ERR_DISPATCH_NOT_CANCELLABLE`. Cancelling does not change the technician's `status`. Because a `CANCELLED` dispatch is no longer live, its former window stops blocking, and the technician can be re-dispatched into that slot.

### 3.4. The On-Site Trip: Depart and Arrive

Once assigned, a technician works the dispatch through its own lifecycle. Departing moves a dispatch from `ASSIGNED` to `EN_ROUTE`; attempting to depart a dispatch that is not in `ASSIGNED` is rejected with `ERR_DISPATCH_NOT_ASSIGNED`. Arriving moves the dispatch from `EN_ROUTE` to `ARRIVED` and requires the dispatch to be in `EN_ROUTE` — an arrive on a dispatch not yet en route is rejected with `ERR_DISPATCH_NOT_EN_ROUTE`. On the arrive call the technician supplies `arrived_at_minute`, the time-of-day in minutes at which they reached the site, which is stamped onto the dispatch.

Arrival also computes the dispatch's `actual_response_minutes` — the chronological, after-the-fact response time, computed differently from the dispatch-time projection. It is the `arrived_at_minute` minus the parent job's `requested_at_minute`; if that difference is negative (a next-day arrival, where the clock has wrapped past midnight), the actual response time is floored at 0 rather than going negative. This actual figure is independent of the projection inputs: it depends only on the two stamped timestamps, not on travel time or queue depth.

Arrival is the event that advances the operational axis: as the dispatch reaches `ARRIVED`, the parent job moves from `DISPATCHED` to `ON_SITE`, opening the job for on-site quoting.

### 3.5. Quoting: The Dispatch Estimate and the Measured Final

Pricing happens in two passes that produce two different totals on an **on-site quote**. A `Technician` drafts a quote against a job by referencing it through `service_job_id` and supplying the measured `labor_hours` (zero or greater) and the `part_lines` — an array in which each entry names a `lock_part_id`, a `quantity`, and a `unit_price_cents`. A new quote enters `DRAFTED` status. At draft time the system computes the quote's `estimated_total_cents`, a forward-looking dispatch estimate that uses only the flat call-out rate for the job's `service_type` and ignores measured labor and parts entirely. The flat call-out rates are 9000 cents for `LOCKOUT`, 12000 cents for `REKEY`, 15000 cents for `INSTALL`, and 20000 cents for `SAFE`. The estimate is that base rate multiplied by the job's surcharge multiplier (§3.6), rounded half up to whole cents.

While a quote sits in `DRAFTED`, a `Technician` may edit its `labor_hours` and `part_lines`; editing is permitted only while the quote is `DRAFTED`, and re-editing recomputes `estimated_total_cents`. Submitting a draft is what produces the measured final total. Submission requires the parent job to be in `ON_SITE` — a submit when the job is not on site is rejected with `ERR_JOB_NOT_ON_SITE` — and requires both `labor_hours` and `part_lines` to be present on the quote, failing which the submit is rejected with `ERR_QUOTE_INCOMPLETE`. On submit the quote moves from `DRAFTED` to `SUBMITTED` and the system computes `final_total_cents`.

The final total is a measured aggregation and diverges from the estimate because it adds the labor and parts the estimate omitted. Let the job's surcharge multiplier be the value from §3.6. The labor line is the labor rate of 8000 cents per hour multiplied by the quote's `labor_hours` and by the surcharge multiplier, rounded half up to whole cents. Then, walking the `part_lines` in the order they were submitted, each line contributes its `unit_price_cents` multiplied by its `quantity` and by the surcharge multiplier, rounded half up to whole cents for that line; these per-line amounts are accumulated. The `final_total_cents` is the labor line plus the sum of the per-line part amounts. The rounding is applied per line — each part line and the labor line are rounded individually and only then added — and must not be computed by summing raw products and rounding once at the end.

### 3.6. Surcharges: After-Hours and Emergency Lockouts

Both quote totals share a single surcharge multiplier derived from the job's intake facts: its `requested_at_minute`, its `is_emergency` flag, and its `service_type`. The multiplier starts at 1.0. If the requested time falls in the after-hours window, it is multiplied by 1.5. The after-hours window covers the evening and overnight stretch: a request at or after minute 1080 (18:00), through the end of the day, is after-hours, and so is a request before minute 480 (08:00). Equivalently, the after-hours surcharge applies when `requested_at_minute` is at least 1080 or is strictly less than 480; the boundary is inclusive at 1080 (minute 1080 triggers the surcharge, minute 1079 does not) and the morning cutoff at 480 is exclusive (minute 479 is after-hours, minute 480 is not). On top of that, if the job is flagged `is_emergency` and its `service_type` is `LOCKOUT`, the multiplier is further multiplied by 1.25; this emergency surcharge stacks only for emergency lockouts and never for other service types, even when flagged as emergencies. The two surcharges compound multiplicatively, so an after-hours emergency lockout carries both factors.

### 3.7. Reserving Parts Against a Quote

Parts named on a quote are held out of inventory through **part reservations**. A `Technician` reserves stock by referencing the consuming quote through `on_site_quote_id`, the inventory SKU through `lock_part_id`, and a positive `quantity`, together with `expected_lockpart_version` for the concurrency check of §2.9. A new reservation enters `RESERVED` status. Creating it decrements the part's `units_available` by the reserved `quantity` and increases its `units_reserved` by the same amount, and bumps the part's `version`.

Reservation is guarded by a layered set of checks evaluated in this order after existence: first the part's version is confirmed against `expected_lockpart_version` (mismatch → `ERR_STALE_LOCKPART_VERSION`, 412); restricted-blank authorization is enforced as described below; the part must not be discontinued and the requested `quantity` must be a positive count of at least 1 (a `DISCONTINUED` part yields `ERR_PART_DISCONTINUED`, a non-positive quantity yields `ERR_INVALID_QUANTITY`); and finally the part must have enough free stock, meaning `units_available` is at least the requested `quantity`, else the reservation is refused with `ERR_INSUFFICIENT_STOCK` before any count changes.

A **lock part** itself is cataloged by an `InventoryManager`, who provides a `sku`, an optional `part_status` (defaulting to `STOCKED`; the other value is `DISCONTINUED`, which blocks new reservations), an optional `restricted_blank` flag (defaulting to `false`), and the `units_total` count of physical units owned. The manager can later restock or discontinue a part, adjusting `units_total` or `part_status`; such an edit carries `expected_lockpart_version`, recomputes `units_available`, and increments the part's `version`.

### 3.8. Authorization Records for Restricted Work

Certain locksmith work is legally sensitive and must be backed by a signed authorization on file. A `Technician` files a **key/code authorization record** against a job by supplying the `auth_kind` — one of `KEY_DUPLICATION`, `CODE_RESET`, or `RESTRICTED_BLANK` — the `authorizing_party` (the property owner or authorized agent who signed off), and the `id_document_ref` (a reference to the verified identity document captured at the time). These records are append-only: once filed they are immutable and carry no version. They are listable per job for audit.

The records gate restricted-blank inventory. When a reservation targets a `LockPart` whose `restricted_blank` flag is `true`, the system requires that the quote's parent job already have a `RESTRICTED_BLANK` authorization record on file; if none exists, the reservation is rejected with `ERR_AUTHORIZATION_MISSING`. Parts that are not restricted blanks carry no such requirement.

### 3.9. Approving, Revising, and Rejecting Quotes

Once a quote is `SUBMITTED`, the job's owning customer decides its fate, and only the owner may act — a `Customer` whose `X-User-ID` does not match the parent job's `customer_user_id` is rejected with `ERR_NOT_JOB_OWNER` on any of these actions. Approval moves the quote from `SUBMITTED` to `APPROVED` and, as a side effect, sets the parent job's `amount_due_cents` to the quote's `final_total_cents`, fixing the amount the customer owes. A job may have only one approved quote at a time; approving a second when one is already approved on the job is rejected with `ERR_QUOTE_ALREADY_APPROVED`.

A customer who is not satisfied has two other moves on a `SUBMITTED` quote. Requesting a revision sends the quote back from `SUBMITTED` to `DRAFTED`, reopening the revision loop so the technician can adjust labor and parts and submit again. Rejecting the quote moves it from `SUBMITTED` to `REJECTED` and, as a cascade, releases every `RESERVED` part reservation under that quote back to inventory — each released reservation moves to `RELEASED`, the corresponding part's `units_reserved` is decremented and its `units_available` incremented by the reservation's `quantity`. A rejected quote is not dead end: a `Technician` may reopen it, moving it from `REJECTED` back to `DRAFTED`, provided the parent job is still `ON_SITE` (otherwise `ERR_JOB_NOT_ON_SITE`); this is the cyclic re-entry into the drafting loop. Any quote transition attempted from an incompatible status — approving a draft, reopening a quote that is not rejected, and the like — is rejected with `ERR_QUOTE_INVALID_STATE`.

### 3.10. Completing Work and Committing Parts

When the on-site work is done, a `Technician` marks the job work-complete. This requires the job to have an `APPROVED` quote; with no approved quote on the job the request is rejected with `ERR_NO_APPROVED_QUOTE`. Completing work moves the job's `job_status` from `ON_SITE` to `WORK_COMPLETE`, and in the same operation commits the parts held for the approved quote: every `RESERVED` part reservation under that quote moves from `RESERVED` to `COMMITTED`, and for each, the corresponding part's `units_reserved` is decremented and its `units_committed` incremented by the reservation's `quantity`. This is the point at which held stock becomes consumed stock; the units leave the reserved pool but stay out of available.

### 3.11. Booking Bench Bays

Bench work for rekeying and installation happens at a **job bay**, a labeled workshop bench a `Dispatcher` creates by supplying a `bay_name`. A bay's `status` is `OPEN` (bookable) by default and can be toggled to `CLOSED_FOR_MAINT` (not bookable) and back to `OPEN` through the close-for-maintenance and reopen actions. A `Dispatcher` books a bench slot through a **bay booking** that references the job via `service_job_id` and the bay via `job_bay_id`, with a `slot_start_minute` and `slot_end_minute` (minutes from local midnight, the end no earlier than the start). A booking enters `BOOKED` status, and the dispatcher can later release it, moving it to `RELEASED`.

A booking is refused if the target bay is not `OPEN` — a `CLOSED_FOR_MAINT` bay yields `ERR_BAY_NOT_OPEN`. The slot is also checked for collisions against the bay's other `BOOKED` bookings. Unlike the technician timeline, bay slots are treated as closed intervals with inclusive endpoints and no travel buffer: the new slot, running from its `slot_start_minute` to its `slot_end_minute`, collides with an existing booked slot of the same bay when the new slot's start is less than or equal to the existing slot's end and the existing slot's start is less than or equal to the new slot's end. Because the endpoints are inclusive, two slots that merely touch at a single shared endpoint minute do collide. A colliding booking is rejected with `ERR_BAY_SLOT_OVERLAP`.

### 3.12. Capturing Payment and Closing the Job

Money is collected against the approved amount. A `BillingAgent` captures a **payment** against a job by supplying the `captured_amount_cents` (at least 1). A capture requires the job to have an `APPROVED` quote — without one the capture is rejected with `ERR_NO_APPROVED_QUOTE`. The payment is recorded in `CAPTURED` status with its `service_job_id`, and the job's `net_paid_cents` is recomputed: it is the sum of `captured_amount_cents` across the job's payments in `CAPTURED` status, minus the sum of `refunded_amount_cents` across the job's payments in `REFUNDED` status (a payment's `refunded_amount_cents` is 0 until it is refunded, at which point it equals that payment's `captured_amount_cents`). A capture must not push `net_paid_cents` above the job's `amount_due_cents`; an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_DUE`. If the capture leaves `net_paid_cents` short of `amount_due_cents`, the job's `payment_status` becomes `PARTIALLY_PAID`; if it brings `net_paid_cents` exactly equal to `amount_due_cents`, the `payment_status` becomes `PAID`.

Closing a job is the dispatcher's final operational act. A job moves from `WORK_COMPLETE` to the terminal `CLOSED` only when its `payment_status` is `PAID`; an attempt to close a job that is not fully paid is rejected with `ERR_JOB_NOT_FULLY_PAID`. This is the one gate where the money axis blocks the operational axis.

### 3.13. Cancelling a Job and Its Cascade

A `Dispatcher` may cancel a job while its `job_status` is `INTAKE`, `DISPATCHED`, or `ON_SITE`; a job in `WORK_COMPLETE`, `CLOSED`, or already `CANCELLED` cannot be cancelled and yields `ERR_JOB_NOT_CANCELLABLE`. Cancellation drives the job to the terminal `CANCELLED` state and unwinds everything hanging off it in one operation. Every non-`CANCELLED` dispatch of the job moves to `CANCELLED` (the technicians' statuses are left untouched). Every non-terminal quote of the job — those in `DRAFTED`, `SUBMITTED`, or `APPROVED` — moves to `VOIDED`. For each quote so voided, the cascade continues into inventory: every `RESERVED` part reservation under it moves to `RELEASED`, with the part's `units_reserved` decremented and its `units_available` incremented by the reservation's `quantity`, restocking the held units. Every `BOOKED` bay booking of the job moves to `RELEASED`. Each of these transitioned resources is a full mutation, refreshing `updated_at` and bumping `version`.

### 3.14. Warranty Claims and Refunds

After a job is closed, its owning customer may file a **warranty claim**. A `Customer` who owns the job files against it by supplying the `filed_at_minute` (the time-of-day the claim is filed, kept for record only), the `days_since_close` (whole days elapsed since the job was closed, supplied by the filer), the `reason` (a defect description), and the `refund_amount_cents` requested (at least 1, and not exceeding the job's `net_paid_cents`). A non-owner filing on someone else's job is rejected with `ERR_NOT_JOB_OWNER`. A new claim enters `FILED` status.

A `Dispatcher` adjudicates the claim. Approval requires the parent job to be `CLOSED` — approving against a job not closed is rejected with `ERR_JOB_NOT_CLOSED` — and requires the warranty to still be in force and the refund to be affordable. The warranty is valid only when `days_since_close` is at most 90 days; a claim at exactly 90 days is still covered, but 91 days or more is expired and is rejected with `ERR_WARRANTY_EXPIRED`. The requested `refund_amount_cents` must not exceed the job's current `net_paid_cents`, else the approval is rejected with `ERR_REFUND_EXCEEDS_PAID`. When these hold, the claim moves from `FILED` to `APPROVED`, and the approval drives a refund on the job: the system selects the job's `CAPTURED` payment whose `captured_amount_cents` is at least the claim's `refund_amount_cents`, choosing the one with the lowest `captured_amount_cents` first and breaking ties by earliest `created_at`; that payment moves from `CAPTURED` to `REFUNDED` with its `refunded_amount_cents` set to its full `captured_amount_cents`; the job's `net_paid_cents` is recomputed; and the job's `payment_status` moves to the terminal `REFUNDED`. A dispatcher may instead deny a claim, moving it from `FILED` to `DENIED`. Approving or denying a claim that is not in `FILED` is rejected with `ERR_CLAIM_INVALID_STATE`.

### 3.15. Request Well-Formedness

Across all write endpoints, a request whose body is missing a required field or carries a value of the wrong type is rejected with `ERR_INVALID_REQUEST` before domain rules are considered. An enum-typed field bearing a value outside its declared set — `service_type` or `auth_kind`, for instance — is rejected with `ERR_INVALID_ENUM`, and any time-of-day minute outside 0 through 1439, or an out-of-order ETA window or bench slot, is rejected with `ERR_INVALID_TIME_WINDOW`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource — including the state-machine actions and the toggle endpoints — return `200 OK`. Request and response bodies are not enumerated here; reconstruct them from the workflow narratives in §3, where every input field and side effect is described.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-jobs` | Create a service job (intake) | Dispatcher |
| GET | `/service-jobs` | List service jobs | Dispatcher, Technician, Customer, InventoryManager, BillingAgent |
| GET | `/service-jobs/{id}` | Get a service job | Dispatcher, Technician, Customer, InventoryManager, BillingAgent |
| POST | `/service-jobs/{id}/cancel` | Cancel a job (cascades to dispatches, quotes, reservations, bay bookings) | Dispatcher |
| POST | `/service-jobs/{id}/complete-work` | Mark on-site work complete (commits reserved parts) | Technician |
| POST | `/service-jobs/{id}/close` | Close a fully-paid completed job | Dispatcher |
| POST | `/service-jobs/{id}/payments` | Capture a payment against an approved quote | BillingAgent |
| GET | `/service-jobs/{id}/payments` | List payments for a job | Dispatcher, BillingAgent, Customer |
| POST | `/service-jobs/{id}/key-authorizations` | File an append-only key/code authorization record | Technician |
| GET | `/service-jobs/{id}/key-authorizations` | List authorization records for a job | Dispatcher, Technician, InventoryManager |
| POST | `/service-jobs/{id}/warranty-claims` | File a warranty claim against a closed job | Customer |
| GET | `/service-jobs/{id}/warranty-claims` | List warranty claims for a job | Dispatcher, Customer |
| POST | `/service-jobs/{id}/dispatches` | Dispatch a technician with an ETA window | Dispatcher |
| GET | `/service-jobs/{id}/dispatches` | List dispatches for a job | Dispatcher, Technician |
| GET | `/dispatches` | List dispatches, filterable by technician | Dispatcher, Technician |
| GET | `/dispatches/{id}` | Get a dispatch | Dispatcher, Technician |
| POST | `/dispatches/{id}/depart` | Technician departs (ASSIGNED → EN_ROUTE) | Technician |
| POST | `/dispatches/{id}/arrive` | Technician arrives on-site (EN_ROUTE → ARRIVED), drives job to ON_SITE | Technician |
| POST | `/dispatches/{id}/cancel` | Cancel a dispatch (frees the ETA window) | Dispatcher |
| POST | `/technicians` | Register a technician | Dispatcher |
| GET | `/technicians` | List technicians | Dispatcher, Technician |
| GET | `/technicians/{id}` | Get a technician | Dispatcher, Technician |
| POST | `/technicians/{id}/set-off-duty` | Take a technician off duty | Dispatcher |
| POST | `/technicians/{id}/set-on-duty` | Return a technician to duty | Dispatcher |
| POST | `/job-bays` | Create a workshop bay | Dispatcher |
| GET | `/job-bays` | List job bays | Dispatcher, Technician |
| GET | `/job-bays/{id}` | Get a job bay | Dispatcher, Technician |
| POST | `/job-bays/{id}/close-for-maint` | Take a bay out of service for maintenance | Dispatcher |
| POST | `/job-bays/{id}/reopen` | Return a bay to service | Dispatcher |
| POST | `/bay-bookings` | Book a bench slot in a bay for a job | Dispatcher |
| GET | `/bay-bookings` | List bay bookings, filterable by job or bay | Dispatcher, Technician |
| GET | `/bay-bookings/{id}` | Get a bay booking | Dispatcher, Technician |
| POST | `/bay-bookings/{id}/release` | Release a bench slot | Dispatcher |
| POST | `/service-jobs/{id}/quotes` | Draft an on-site quote | Technician |
| GET | `/service-jobs/{id}/quotes` | List quotes for a job | Dispatcher, Technician, Customer |
| GET | `/quotes/{id}` | Get a quote | Dispatcher, Technician, Customer |
| POST | `/quotes/{id}/submit` | Submit a draft quote (computes final total, requires job ON_SITE) | Technician |
| POST | `/quotes/{id}/approve` | Customer approves a submitted quote | Customer |
| POST | `/quotes/{id}/reject` | Customer rejects a submitted quote (releases reserved parts) | Customer |
| POST | `/quotes/{id}/request-revision` | Customer requests changes (SUBMITTED → DRAFTED) | Customer |
| POST | `/quotes/{id}/reopen` | Technician reopens a rejected quote (REJECTED → DRAFTED) | Technician |
| PUT | `/quotes/{id}` | Update a drafted quote's labor and parts before re-submit | Technician |
| POST | `/lock-parts` | Create a LockPart inventory SKU | InventoryManager |
| GET | `/lock-parts` | List lock parts | InventoryManager, Dispatcher, Technician |
| GET | `/lock-parts/{id}` | Get a lock part (read current version for OCC) | InventoryManager, Dispatcher, Technician |
| PUT | `/lock-parts/{id}` | Restock or discontinue a lock part | InventoryManager |
| POST | `/part-reservations` | Reserve units of a LockPart for a quote (OCC on version) | Technician |
| GET | `/part-reservations` | List part reservations, filterable by quote or part | Technician, InventoryManager, Dispatcher |
| GET | `/part-reservations/{id}` | Get a part reservation | Technician, InventoryManager, Dispatcher |
| GET | `/warranty-claims/{id}` | Get a warranty claim | Dispatcher, Customer |
| POST | `/warranty-claims/{id}/approve` | Approve a warranty claim (drives refund on the job) | Dispatcher |
| POST | `/warranty-claims/{id}/deny` | Deny a warranty claim | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_JOB_OWNER` | 403 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_BAY_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_LOCKPART_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_QUOTE_INCOMPLETE` | 422 |
| `ERR_JOB_NOT_DISPATCHABLE` | 409 |
| `ERR_JOB_NOT_ON_SITE` | 409 |
| `ERR_JOB_NOT_CANCELLABLE` | 409 |
| `ERR_JOB_NOT_CLOSED` | 409 |
| `ERR_JOB_NOT_FULLY_PAID` | 409 |
| `ERR_NO_APPROVED_QUOTE` | 409 |
| `ERR_DISPATCH_NOT_ASSIGNED` | 409 |
| `ERR_DISPATCH_NOT_EN_ROUTE` | 409 |
| `ERR_DISPATCH_NOT_CANCELLABLE` | 409 |
| `ERR_TECHNICIAN_UNAVAILABLE` | 409 |
| `ERR_TECHNICIAN_NOT_CERTIFIED` | 409 |
| `ERR_ETA_WINDOW_OVERLAP` | 409 |
| `ERR_BAY_SLOT_OVERLAP` | 409 |
| `ERR_BAY_NOT_OPEN` | 409 |
| `ERR_QUOTE_INVALID_STATE` | 409 |
| `ERR_QUOTE_ALREADY_APPROVED` | 409 |
| `ERR_PART_DISCONTINUED` | 409 |
| `ERR_AUTHORIZATION_MISSING` | 403 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_STALE_LOCKPART_VERSION` | 412 |
| `ERR_PAYMENT_EXCEEDS_DUE` | 409 |
| `ERR_REFUND_EXCEEDS_PAID` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_CLAIM_INVALID_STATE` | 409 |

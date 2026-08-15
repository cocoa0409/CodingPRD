# Sail Loft & Rigging Service API — Product Requirements Document

## 1. Introduction

A full-service sail loft operates on a surprisingly long chain of custody: a boat is measured, a sail is designed against those measurements, cloth is reserved and cut on the production floor, the finished sail is fitted and delivered, and the relationship continues through rigging inspections, mast work, warranty claims, and the off-season storage program. Each stage constrains the next — a design cannot be submitted against an unfrozen measurement sheet, a work order cannot lock a design the customer has not approved, and a failed rigging inspection must ground the boat and freeze its crane bookings until a passing re-inspection clears it. This document specifies the API for that loft, covering measurement capture and sail design, material selection and production scheduling, standing and running rigging inspection with replacement intervals, mast unstepping and tuning, warranty repair-versus-replacement rulings, the storage and wash program, racing-class certification, and delivery with fit check. All resources are mounted under the `/lofts` path prefix.

Two design pressures shape every workflow that follows. First, money and material are both accounted with deliberate asymmetry: the provisional quote computed when a design is locked is forward-looking from the design specification, while the final invoice at delivery is chronological over the jobs that actually passed quality control, and the two are expected to diverge when options are declined or panels are rejected. Second, the boat record is the concurrency keystone of the system — design revisions and inspection scheduling both write against it under optimistic concurrency control, because a stale view of the boat means a stale view of everything pinned to it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare their operational capacity. The system recognizes five roles, spelled exactly as follows: `Customer`, `Sailmaker`, `Measurer`, `Rigger`, and `LoftManager`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the declared role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's customer foreign-key field to `X-User-ID`. This is how design approval, revision requests, delivery confirmation, warranty claims, and storage return confirmation are scoped to the boat's owner. When `X-User-Role` is `Sailmaker`, `Measurer`, `Rigger`, or `LoftManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a measurement sheet stamps the capturing operator as `captured_by_measurer_id` — but it is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both are optional on every list endpoint.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system — Customer, Boat, Measurement Sheet, Sail Design, Work Order, Production Job, Cloth Ledger Entry, Rigging Inspection, Mast Service Event, Storage Contract, and Class Certificate — carries the same four system-managed properties:

- `id` (string): a unique server-minted identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource.

Mutations caused by cross-entity cascades count as mutations of the affected resource: when a parent or sibling resource is transitioned automatically as a side effect, its `updated_at` is refreshed and its `version` is incremented, exactly as if a client had written to it directly.

### 2.5. Request Validation Order and Nested Path Semantics

Every request is validated in a fixed order, and a request that would fail several checks is always rejected with the earliest one in this sequence. First, the header context is checked (missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT`). Second, role authorization is evaluated against the endpoint's permitted roles (failure yields `ERR_FORBIDDEN_ROLE`). Third, path resource identifiers are resolved. Fourth, the generic source-state legality of the requested transition is verified (failure yields `ERR_INVALID_STATE`, HTTP 409). Fifth, the endpoint-specific business rules are evaluated. Finally, as the last gate, the optimistic-concurrency version check described in §2.7 is applied on the two boat-scoped creation capabilities that carry it.

Path identifiers are validated strictly left-to-right: a request addressed to a nested resource (for example, a measurement sheet under a boat under a customer) is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not correspond to an existing resource, and no later identifier or business rule is consulted until every earlier one resolves. A parent identifier that does not exist therefore masks everything beneath it.

### 2.6. Money, Measurements, and Rounding Discipline

All monetary amounts are integer numbers of cents — quotes, invoices, balances, credit limits, payments, option fees, and cloth prices alike — and every monetary computation concludes by rounding half-up to a whole number of cents. Sail area is the one quantity carried at finer precision: computed areas are rounded half-up to two decimal places of square metres. Rigging age is expressed in whole calendar months, and running-rigging usage in whole sail-hours.

Two rounding-order commitments deserve emphasis because alternative implementations diverge by cents. Storage fees are rounded per wash item first and only then summed — summing unrounded item fees and rounding once at the end is explicitly not the rule. And the final invoice accumulates each qualifying production job's cloth share before adding fitted-option fees, with the single round-half-up applied to the grand total. Requests with a missing required field, a type mismatch, or an enum value outside its declared set are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control on Boat-Scoped Writes

Two creation capabilities are guarded by optimistic concurrency control against the boat record: creating a new sail design revision for a boat, and scheduling a new rigging inspection for a boat. Each of these requests must carry `expected_boat_version`, a non-optional input field holding the `version` of the boat as the client last observed it. If that value does not equal the boat's current `version` — because another writer has advanced the boat record since the client last read it — the request is rejected with `ERR_STALE_BOAT_VERSION` (HTTP 412), and the client must re-read the boat before retrying. This check is the final validation gate on those requests: every other applicable rule runs first. Both guarded creations, on success, increment the boat's `version` by one, so a successful write by one client stales every other client's captured version. No other endpoint accepts a version field.

### 2.8. Customer Credit, Account Standing, and the Outstanding Balance

Each customer is registered with a `credit_limit_cents`, the maximum outstanding balance the loft will carry for them, and an `outstanding_balance_cents`, a running total of unpaid invoiced amounts that starts at zero. The balance is debited when an invoice is issued — at delivery confirmation for work orders and at return confirmation for storage contracts — and is credited by recorded payments and by warranty write-offs. Credits can never drive the balance below zero: both payment application and warranty write-off floor the resulting balance at zero.

A customer's `status` is one of `ACTIVE`, `SUSPENDED`, or `CLOSED`. Suspension is permitted only when the outstanding balance is strictly greater than the credit limit; reinstatement only when the balance is at or below the limit; and closure only when the balance is exactly zero and the customer owns no boat still in `ACTIVE` status. A violation of any of these three account rules is rejected with `ERR_ACCOUNT_RULE_VIOLATION` (HTTP 422). Suspension does not cancel existing work: any of the customer's work orders still `OPEN` remain `OPEN`, but they cannot be design-locked while the customer is suspended.

### 2.9. The Cloth Ledger and Material Reservation

The loft tracks physical cloth in a **cloth ledger** of bolts. A bolt is registered with a `bolt_code`, a `cloth_tier`, a `total_sqm` length in square metres, and a `price_per_sqm_cents` unit price; its `available_sqm` is derived, not stored by hand — it equals the bolt's `total_sqm` minus the sum of `reserved_cloth_sqm` across all non-terminal production jobs booked against that bolt. Registering a bolt initializes `available_sqm` to `total_sqm`.

Scheduling a production job reserves cloth: the job's `reserved_cloth_sqm` is computed from the pinned design's measured area, the reservation is charged against the ledger for the design's cloth tier, and the affected bolt's `available_sqm` is recomputed. If the reservation exceeds what is available for that tier, scheduling is rejected with `ERR_CLOTH_SHORTAGE` (HTTP 409). Reservations are returned to the ledger in exactly two circumstances — when a job passes quality control, and when a job is cancelled — and each return recomputes the bolt's `available_sqm`.

### 2.10. Bay Windows and Crane-Dock Slots

The production floor has three cutting bays, identified by `bay_code` values `BAY_A`, `BAY_B`, and `BAY_C`. A production job occupies its bay from `scheduled_start_date` through `scheduled_end_date`, both dates inclusive, and bays demand turnaround time between occupants: two jobs booked into the same bay conflict when the first job's scheduled start date falls on or before the calendar day immediately following the second job's scheduled end date, and the second job's scheduled start date falls on or before the calendar day immediately following the first job's scheduled end date. In effect, at least one full calendar day of turnaround must separate one job's last day in a bay from the next job's first day in that same bay. Jobs in `CANCELLED` status are excluded from the conflict set. A scheduling or rescheduling request that violates this rule is rejected with `ERR_BAY_WINDOW_CONFLICT` (HTTP 409).

Mast work books the crane and rig dock in half-open intervals: a mast service event occupies its slot from `slot_start_utc` up to but not including `slot_end_utc`. Two events on the same boat conflict when the first event's slot start is earlier than the second event's slot end and the second event's slot start is earlier than the first event's slot end; because the interval is half-open, one event ending at exactly the instant another begins is permitted. The conflict set comprises the boat's events in `BOOKED`, `IN_PROGRESS`, or `RIGGING_HOLD` status — events in `COMPLETED` or `CANCELLED` status are excluded. An overlapping booking is rejected with `ERR_MAST_SLOT_OVERLAP` (HTTP 409).

### 2.11. Rigging Replacement Clocks and Safety Holds

Standing and running rigging age on different clocks, and the loft tracks both. Standing rigging is calendar-driven: replacement comes due 120 months after installation, and at inspection time the boat's standing rigging age is computed as the whole calendar months between the installation date and the inspection timestamp. Running rigging is usage-driven: replacement comes due at 2,000 accumulated sail-hours. Either clock, once at or past its threshold, imposes a verdict floor of `ADVISORY` on the inspection — an inspector who submitted `PASS` has that verdict overridden to `ADVISORY`. Because the clocks measure different things, they can disagree for the same boat at the same moment: a two-year-old boat with 2,100 sail-hours passes the calendar test but trips the hours floor.

A `FAIL` verdict is a safety event, not merely a record: it takes the boat out of service and places every crane booking for that boat on hold until a passing replacement inspection closes the chain. The full mechanics live in §3.6.

## 3. Business Logic & Workflows

### 3.1. Enrolling Customers and Registering Boats

A `LoftManager` onboards a new customer with their `full_name`, `email`, and `credit_limit_cents`. The new Customer record starts with `outstanding_balance_cents` at zero and `status` set to `ACTIVE`. From then on the balance moves with the business: invoice issuance adds to it, while payments and warranty write-offs subtract from it, never below zero. Recording a payment is a `LoftManager` action that takes an `amount_cents` and reduces the customer's `outstanding_balance_cents` by that amount, floored at zero.

Account discipline is enforced through the three account transitions. Suspending a customer moves `status` from `ACTIVE` to `SUSPENDED` and is permitted only while the outstanding balance is strictly greater than the credit limit; the customer's `OPEN` work orders survive the suspension but cannot be design-locked until reinstatement. Reinstating moves `SUSPENDED` back to `ACTIVE` once the balance is at or below the limit. Closing moves `ACTIVE` to the terminal `CLOSED` and demands a zero balance plus no boat of the customer's still in `ACTIVE` status. Each rejected attempt — suspending a within-limit account, reinstating an over-limit one, or closing an account with a balance or an active boat — carries `ERR_ACCOUNT_RULE_VIOLATION`.

Boats join the loft through the owning customer. A `LoftManager` registers a boat with a `boat_name`, a `hull_length_m` (length overall in metres, which later determines the storage fee tier), a `racing_class` of `NONE`, `J70`, `J105`, `TP52`, `ORC`, or `PHRF`, the `standing_rigging_install_date` on which the current standing rigging was installed (the basis of the replacement clock), and optionally the `running_rigging_hours_accumulated` on the current running rigging, which defaults to 0. A new boat's `mast_status` is initialized to `STEPPED` and its `status` to `ACTIVE`; the full `status` enumeration also includes `OUT_OF_SERVICE` and `RETIRED`. The boat record keeps its owning customer reference as `customer_id`, and it is this field that `X-User-ID` is compared against whenever a `Customer`-role caller acts on the boat.

### 3.2. From Tape Measure to Frozen Sheet: Measurement and Class Certification

Every sail begins as numbers on a **measurement sheet**. A `Measurer` captures a draft sheet for a boat by submitting the four principal rig dimensions: `i_height_m` (foretriangle height I), `j_base_m` (foretriangle base J), `p_main_m` (mainsail luff length P), and `e_main_m` (mainsail foot length E). The sheet is created in `DRAFT` status with `frozen_at` null, and it records the capturing operator's `X-User-ID` as `captured_by_measurer_id` alongside its `boat_id`.

Freezing is the pivotal act. When the `Measurer` freezes a sheet, all four dimensions must be positive numbers — any non-positive value is rejected with `ERR_INVALID_MEASUREMENT` (HTTP 422). On a successful freeze the sheet's `measured_area_sqm` is computed and stored: the mainsail area is one half of `p_main_m` multiplied by `e_main_m`, the foretriangle area is one half of `i_height_m` multiplied by `j_base_m`, and the measured area is the sum of those two products, rounded half-up to two decimal places. The freeze also stamps `frozen_at` with the current UTC time and moves `sheet_status` from `DRAFT` to `FROZEN`.

A boat has at most one current sheet. Freezing a newer sheet for a boat automatically transitions any previously `FROZEN` sheet for that boat to the terminal `SUPERSEDED`, and the supersede cascades outward: every **class certificate** referencing the superseded sheet transitions from `ACTIVE` to `REVOKED`, and every sail design in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` that pins the superseded sheet transitions to `ARCHIVED`.

Certificates are the measurer's attestation that a boat measures for its declared class. A `Measurer` issues a class certificate by supplying a `measurement_sheet_id` and a `racing_class` — one of `J70`, `J105`, `TP52`, `ORC`, or `PHRF`. Issuance is refused with `ERR_CLASS_MISMATCH` (HTTP 422) when the certificate's `racing_class` differs from the boat's own `racing_class`, when the boat's `racing_class` is `NONE`, or when the referenced sheet is not in `FROZEN` status. A successfully issued certificate is stamped with `issued_at` and starts in `ACTIVE` status, where it remains unless its underlying sheet is later superseded.

### 3.3. Designing the Sail: Revisions, Approval, and Supersede

A `Sailmaker` creates a **sail design** for a boat by pinning a measurement sheet and specifying the build: the request carries a `measurement_sheet_id`, a `cloth_tier` of `CRUISE`, `PERFORMANCE`, `RACE`, or `GRAND_PRIX`, an optional `reinforcement_level` (an integer from 1 to 5, defaulting to 1, which drives the heavy-duty surcharge when the sail is large), an optional `option_codes` array (zero or more of `BATTENS`, `REEF_POINTS`, `UV_STRIP`, `NUMBERS`, and `LOGO`, defaulting to empty), and the mandatory `expected_boat_version` concurrency token described in §2.7. Creation performs no validation of the pinned sheet — the `measurement_sheet_id` is stored as supplied, and the requirement that the sheet exist and be `FROZEN`, with its `ERR_MEASUREMENT_NOT_FROZEN` rejection, is enforced only at submission — so a design may be created pinning a sheet that is missing or not yet frozen. A boat whose `version` has advanced past the client's captured value causes the creation to be rejected with `ERR_STALE_BOAT_VERSION` (HTTP 412) — the classic case being another sailmaker who has just created a revision, which supersedes the prior approved design and advances the boat's version. Each successful design creation increments the boat's `version` by one.

Every design begins life in `DRAFT` status. The first design of a line carries `revision_number` 1 and a null `supersedes_design_id`. When a prior design for the same boat is sitting in `APPROVED`, creating a new revision transitions that prior design from `APPROVED` to `SUPERSEDED`, and the new row is created in `DRAFT` with `revision_number` set to the prior revision's number plus one and `supersedes_design_id` set to the prior design's `id`. Superseding an approved design has one more consequence: any work order that pins that design and is still in `OPEN` status is transitioned to `CANCELLED`.

The review loop runs between sailmaker and customer. Submitting a `DRAFT` design moves `design_status` to `SUBMITTED`; the pinned measurement sheet must exist and be `FROZEN` at submission, and if it is missing or not frozen the submission is rejected with `ERR_MEASUREMENT_NOT_FROZEN` (HTTP 409). Approval is the customer's call and is guarded three ways: the acting customer's `X-User-ID` must equal the boat's `customer_id`, the customer's `status` must be `ACTIVE`, and the customer's `outstanding_balance_cents` plus the projected quote for the design must not exceed the customer's `credit_limit_cents`. The design-state check runs before the credit check, so an approval attempted on a design that is not `SUBMITTED` is rejected with `ERR_DESIGN_NOT_IN_REQUIRED_STATE` (HTTP 409) rather than any credit error, and an approval that passes the state gate but would break the credit limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). A successful approval moves the design from `SUBMITTED` to `APPROVED`.

Customers can also push a design back: requesting a revision on a `SUBMITTED` design — again restricted to the boat's owner — moves it to `REVISION_REQUESTED` and stores the payload's `rejection_reason` on the design. A `Sailmaker` then returns the design from `REVISION_REQUESTED` to `DRAFT` for editing; this is the same design row looping back, so its `revision_number` does not change, and the row may cycle `DRAFT` → `SUBMITTED` → `REVISION_REQUESTED` → `DRAFT` repeatedly. Designs are also archived without any client action: when the sheet a design pins is superseded, a design in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` transitions to the terminal `ARCHIVED` (per §3.2).

### 3.4. Work Orders and the Production Floor

A **work order** is opened by a `LoftManager` for a customer and a boat, carrying the `customer_id`, the `boat_id`, an `order_kind` of `NEW_SAIL`, `RIGGING_SERVICE`, `MAST_SERVICE`, `STORAGE_PROGRAM`, or `REPAIR`, and optionally a `sail_design_id` and a `warranty_flag` (which defaults to false). The order starts in `OPEN` status with both `quoted_total_cents` and `invoiced_total_cents` at zero. The order status enumeration runs `OPEN`, `DESIGN_LOCKED`, `IN_PRODUCTION`, `READY_FOR_FIT_CHECK`, `DELIVERED`, `WARRANTY_REVIEW`, `WARRANTY_REPAIR`, and the terminals `CLOSED` and `CANCELLED`.

Locking the design is the commercial gate for new-sail work. A `LoftManager` locks an `OPEN` order into `DESIGN_LOCKED`, which requires the `order_kind` to be `NEW_SAIL`, the pinned sail design to be in `APPROVED` status, and the customer's `status` to be `ACTIVE`; a design in any other state surfaces `ERR_DESIGN_NOT_IN_REQUIRED_STATE`, and note from §3.1 that a suspended customer's open orders cannot pass this gate. At lock time the provisional quote is computed and stored in `quoted_total_cents`. The quote starts from a base equal to the pinned sheet's `measured_area_sqm` multiplied by the per-square-metre cloth price for the design's `cloth_tier` — 4,200 cents for `CRUISE`, 6,800 cents for `PERFORMANCE`, 9,500 cents for `RACE`, and 14,000 cents for `GRAND_PRIX`. When the measured area is strictly greater than 150.00 square metres, the heavy-duty surcharge increases that base by 4 percent for each level of the design's `reinforcement_level` — that is, the base is multiplied by one plus 0.04 times the reinforcement level. Each option code on the design then contributes its flat fee: 18,000 cents for `BATTENS`, 12,000 cents for `REEF_POINTS`, 9,000 cents for `UV_STRIP`, 4,000 cents for `NUMBERS`, and 6,000 cents for `LOGO`. The base plus the option fees is multiplied by a class-complexity factor keyed on the boat's `racing_class` — 1.00 for `NONE`, 1.00 for `PHRF`, 1.05 for `ORC`, 1.05 for `J70`, 1.08 for `J105`, and 1.15 for `TP52` — and the result is rounded half-up to a whole number of cents. Being forward-looking, this provisional variant takes the design's `option_codes` and `reinforcement_level` as-is, and it may include options the customer later declines at fit check.

Production is scheduled per bay. A `Sailmaker` schedules a **production job** under a work order by naming a `bay_code` (`BAY_A`, `BAY_B`, or `BAY_C`) and an inclusive window from `scheduled_start_date` to `scheduled_end_date`. Two checks guard the booking, evaluated in this order: first the bay-turnaround rule of §2.10, with conflicts rejected as `ERR_BAY_WINDOW_CONFLICT`, and then the cloth availability rule of §2.9, with shortages rejected as `ERR_CLOTH_SHORTAGE` — so a request that would fail both surfaces the bay conflict. A booked job starts in `SCHEDULED` status, its `reserved_cloth_sqm` is computed from the pinned design's `measured_area_sqm`, and the bolt's `available_sqm` is recomputed. The job status enumeration is `SCHEDULED`, `CUTTING`, `SEAMING`, `FINISHING`, `QC_PASSED`, `QC_FAILED`, and the terminal `CANCELLED`, and each job carries its parent reference as `work_order_id`.

Work advances on the floor under the sailmaker's hand. Starting cutting moves a job from `SCHEDULED` to `CUTTING` and is permitted only while the parent work order is in `DESIGN_LOCKED` or `IN_PRODUCTION` and the pinned design is `APPROVED`; a pinned design in any other status surfaces `ERR_DESIGN_NOT_IN_REQUIRED_STATE` (HTTP 409) — the same design-state error as the lock-design gate — while a job- or order-state violation remains the generic `ERR_INVALID_STATE` of §2.5. When the first job under an order starts cutting, the parent bubbles from `DESIGN_LOCKED` to `IN_PRODUCTION` automatically. Advancing moves `CUTTING` to `SEAMING` and then `SEAMING` to `FINISHING`. At the end of the line the job is inspected: passing quality control moves `FINISHING` to the terminal `QC_PASSED`, releases the job's `reserved_cloth_sqm` back to the cloth ledger (recomputing the bolt's `available_sqm`), and — when every non-cancelled sibling job under the same work order has also reached `QC_PASSED` — bubbles the parent from `IN_PRODUCTION` to `READY_FOR_FIT_CHECK`. Failing quality control moves `FINISHING` to `QC_FAILED` and stores the sailmaker's `qc_notes` from the payload.

The quality-control loop is cyclic: a `QC_FAILED` job can be rescheduled into a fresh bay window, moving it back to `SCHEDULED`; the reschedule re-runs the bay-turnaround check against the new dates and recomputes the reservation on the new window. Cancellation of the parent order is the other way jobs end. Cancelling an `OPEN` work order moves it to `CANCELLED` and cascades in three hops: first, every production job of the order in `SCHEDULED`, `CUTTING`, `SEAMING`, or `FINISHING` transitions to `CANCELLED`; second, each such cancellation releases its `reserved_cloth_sqm` back to the cloth ledger and the bolt's `available_sqm` is recomputed; third, if the pinned sail design has no other non-cancelled work order referencing it, that design transitions to `ARCHIVED`.

### 3.5. Fit Check, Final Invoice, and Warranty Rulings

Once every job has passed inspection, the boat comes back for the fit check, and the customer closes the loop. Delivery confirmation is the owner's action on a `READY_FOR_FIT_CHECK` order — the acting customer's `X-User-ID` must match the boat's owning `customer_id` — and it may carry a `fitted_option_codes` array recording the options actually fitted, since a customer can decline options quoted in the design. Confirmation moves the order from `READY_FOR_FIT_CHECK` to `DELIVERED` and computes the final invoice into `invoiced_total_cents`. Where the provisional quote was forward-looking, the invoice is chronological: the system walks the work order's `QC_PASSED` production jobs in ascending `scheduled_start_date` order, breaking ties by ascending job creation time, and each job contributes a share equal to its `reserved_cloth_sqm` multiplied by the per-square-metre cloth price of the design's `cloth_tier` (the same 4,200 / 6,800 / 9,500 / 14,000-cent schedule as §3.4). The invoice subtotal is the sum of those job shares plus the flat fees of the options actually fitted at fit check — the same per-option price list as the provisional quote — and the total is rounded half-up to whole cents. Options the customer declined at fit check are excluded, which is precisely how the invoice can diverge from the quote. The invoiced amount is then debited to the customer: their `outstanding_balance_cents` increases by `invoiced_total_cents`.

Warranty covers the delivered work. The owner may open a warranty claim on a `DELIVERED` order, supplying a `claim_reason`, provided the claim is filed within 730 days of delivery — a claim filed later is rejected with `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 422). The order moves from `DELIVERED` to `WARRANTY_REVIEW` and awaits the manager's ruling.

Ruling the claim is a `LoftManager` decision expressed through a `ruling` payload, and the two outcomes diverge sharply. A `REPAIR` ruling moves the order from `WARRANTY_REVIEW` to `WARRANTY_REPAIR`: the work continues at no charge, the order's `warranty_flag` is set to true, and the invoice is credited back by reducing the customer's `outstanding_balance_cents` by the order's `invoiced_total_cents`, floored at zero. A `REPLACE` ruling instead moves the order from `WARRANTY_REVIEW` straight to `CLOSED` and spawns a brand-new work order in `OPEN` status with `order_kind` `NEW_SAIL` and `warranty_flag` set to true — the repair-versus-replace decision is the branch point, and only the ruling endpoint forks it. Independently of warranty, a `LoftManager` may close an order directly from `DELIVERED` or from `WARRANTY_REPAIR` into the terminal `CLOSED`.

### 3.6. Rigging Inspection and Mast Service

A `Rigger` schedules a **rigging inspection** for a boat by supplying a `rigging_scope` of `STANDING`, `RUNNING`, or `FULL`, together with the mandatory `expected_boat_version` concurrency token; a stale token is rejected with `ERR_STALE_BOAT_VERSION` (HTTP 412) per §2.7, and a successful scheduling increments the boat's `version` by one. The inspection starts in `SCHEDULED` status and keeps its `boat_id` reference.

Submitting the inspection report is where the replacement clocks are read. The rigger files a `verdict` of `PASS`, `ADVISORY`, or `FAIL`; the report stamps `inspected_at` with the current UTC time, moves `inspection_status` from `SCHEDULED` to `REPORTED`, and computes three derived fields. `standing_months_at_inspection` is the whole calendar months between the boat's `standing_rigging_install_date` and `inspected_at`; `standing_replacement_due_date` is exactly 120 calendar months after the installation timestamp — the day clamping to the target month's last day when that month is shorter — and is reported as an ISO 8601 UTC timestamp with three fractional digits in the same format as `created_at`, carrying the installation timestamp's time-of-day (an installation recorded as `2025-08-01T00:00:00Z` reports `2035-08-01T00:00:00.000Z`); and `running_replacement_due_hours` is the hours-variant threshold of 2,000 sail-hours. The verdict floor of §2.11 then applies on both clocks: if `standing_months_at_inspection` is at least 120, or if the boat's `running_rigging_hours_accumulated` is at least 2,000, a filed `PASS` is recorded as `ADVISORY`.

A `FAIL` verdict cascades across the boat. Filing a `FAIL` report transitions the boat's `status` from `ACTIVE` to `OUT_OF_SERVICE`, and — caused by that status change together with the open failed inspection — every mast service event for the boat sitting in `BOOKED` status transitions to `RIGGING_HOLD`. Closing the loop requires evidence: closing a `REPORTED` inspection whose verdict is `FAIL` is refused with `ERR_FAIL_NOT_SUPERSEDED` (HTTP 409) unless a replacement inspection with a non-`FAIL` verdict already exists in `REPORTED` status for the same boat and the same scope. When the failed inspection is closed on the strength of that passing replacement, the hold releases: the boat's `status` may return to `ACTIVE`, and the boat's held mast service events return from `RIGGING_HOLD` to `BOOKED` automatically.

Mast work itself is booked against the crane dock. A `Rigger` books a **mast service event** with a `service_kind` of `UNSTEP`, `STEP`, or `TUNE` and a half-open slot from `slot_start_utc` to `slot_end_utc`; the booking runs the adjacency-permitting overlap rule of §2.10, and overlaps are rejected with `ERR_MAST_SLOT_OVERLAP`. The event starts in `BOOKED` status, and when the `service_kind` is `UNSTEP` the boat's `mast_status` moves to `UNSTEPPING_SCHEDULED` at booking time. The `mast_status` enumeration is `STEPPED`, `UNSTEPPING_SCHEDULED`, `UNSTEPPED`, and `TUNING_IN_PROGRESS`.

Starting and completing the event are guarded on opposite ends. Starting moves a `BOOKED` event to `IN_PROGRESS`, but only while no rigging inspection for the boat sits in `REPORTED` with a `FAIL` verdict and the boat's `status` is not `OUT_OF_SERVICE` — a violation is rejected with `ERR_UNRESOLVED_RIGGING_FAIL` (HTTP 409). At start, the boat's `mast_status` moves per the `service_kind`: `UNSTEPPED` for an unstep, `STEPPED` for a step, and `TUNING_IN_PROGRESS` for a tune. Completing an `IN_PROGRESS` event moves it to the terminal `COMPLETED` and settles the mast accordingly: to `STEPPED` after a step, to `UNSTEPPED` after an unstep, and back to `STEPPED` after a tune. Cancelling a `BOOKED` event moves it to `CANCELLED`, and if the boat's `mast_status` had been left `UNSTEPPING_SCHEDULED` for that event it returns to `STEPPED`.

### 3.7. The Off-Season Storage and Wash Program

Come haul-out season, a `LoftManager` enrols a boat in the storage program by supplying a `season_code` (a season identifier such as WINTER_2026) and an optional `wash_item_codes` array selecting from `MAIN_WASH`, `GENOA_WASH`, `SPINNAKER_WASH`, and `RIG_WASH` — defaulting to empty, with each selected item priced individually. The contract starts in `ENROLLED` status with `quoted_storage_fee_cents` at zero; the full status enumeration is `ENROLLED`, `RECEIVED`, `WASHED`, `STORED`, `OUT_FOR_DELIVERY`, and the terminals `RETURNED` and `CANCELLED`.

Receiving the boat into the yard prices the season. When the `LoftManager` marks the contract received, `contract_status` moves from `ENROLLED` to `RECEIVED` and the quoted fee is computed into `quoted_storage_fee_cents`. The fee is built in a pinned rounding order: each selected wash item's price — 14,550 cents for `MAIN_WASH`, 12,350 cents for `GENOA_WASH`, 9,875 cents for `SPINNAKER_WASH`, and 21,000 cents for `RIG_WASH` — is first rounded half-up to whole cents individually; the rounded item fees are summed; and the season base determined by the boat's `hull_length_m` is added last — 180,000 cents for hulls under 10 metres, 260,000 cents for hulls at least 10 metres and at most 15 metres, and 390,000 cents for hulls over 15 metres. Sum-then-round is explicitly rejected; the per-item rounding must happen first.

From there the contract walks the yard's rhythm, each step a `LoftManager` action: completing the wash moves `RECEIVED` to `WASHED`, racking the boat moves `WASHED` to `STORED`, and staging for spring delivery moves `STORED` to `OUT_FOR_DELIVERY`. The final step belongs to the owner: confirming the return moves `OUT_FOR_DELIVERY` to the terminal `RETURNED`, is permitted only to the customer who owns the boat, and bills the season by adding `quoted_storage_fee_cents` to the customer's `outstanding_balance_cents`. A contract that never gets going can be cancelled while still `ENROLLED`, moving it to `CANCELLED`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a customer, boat, measurement sheet, design revision, work order, production job, cloth bolt, inspection, mast service event, storage contract, or certificate, and recording a payment — return a `201 Created` status code. Operations that modify an existing resource, including every lifecycle transition action, return a `200 OK` status code. Successful responses return the created or updated resource in the envelope's `data` field per §2.2.

List endpoints share a common filtering vocabulary in addition to the `limit` and `offset` pagination parameters of §2.3. The customer list accepts an optional `status` filter. The cross-customer boat list accepts `customer_id` and `status`. Measurement sheet lists accept `sheet_status`, and the cross-boat form also accepts `boat_id`. Sail design lists accept `design_status`, and the cross-boat form adds `boat_id`, `measurement_sheet_id`, and `supersedes_design_id`. The work order list accepts `customer_id`, `boat_id`, `sail_design_id`, and `order_status`. Production job lists accept `job_status`, and the cross-order form adds `work_order_id` and `bay_code`. The cloth ledger list accepts `cloth_tier`. Rigging inspection lists accept `inspection_status`, and the cross-boat form adds `boat_id` and `rigging_scope`. Mast service event lists accept `event_status`, and the cross-boat form adds `boat_id` and `service_kind`. Storage contract lists accept `contract_status`, and the cross-boat form adds `boat_id` and `season_code`. Class certificate lists accept `cert_status`, and the cross-boat form adds `boat_id`, `measurement_sheet_id`, and `racing_class`. All filters are exact matches against the named field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lofts/customers` | Register a new customer | LoftManager |
| GET | `/lofts/customers` | List customers | LoftManager, Sailmaker, Measurer, Rigger |
| GET | `/lofts/customers/{customerId}` | Get one customer | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/customers/{customerId}/suspend` | Suspend a customer whose balance exceeds the credit limit | LoftManager |
| POST | `/lofts/customers/{customerId}/reinstate` | Reinstate a suspended customer whose balance is back within the limit | LoftManager |
| POST | `/lofts/customers/{customerId}/close` | Close a customer account (balance zero, no active boats) | LoftManager |
| POST | `/lofts/customers/{customerId}/payments` | Record a payment against the customer's outstanding balance | LoftManager |
| POST | `/lofts/customers/{customerId}/boats` | Register a boat for a customer | LoftManager |
| GET | `/lofts/customers/{customerId}/boats` | List boats for a customer | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/boats` | List boats across customers, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/boats/{boatId}` | Get one boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/measurement-sheets` | Capture a draft measurement sheet for a boat | Measurer |
| GET | `/lofts/boats/{boatId}/measurement-sheets` | List measurement sheets for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/measurement-sheets` | List measurement sheets across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/measurement-sheets/{sheetId}` | Get one measurement sheet | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/measurement-sheets/{sheetId}/freeze` | Freeze a draft sheet: compute area, stamp frozen_at, supersede the prior FROZEN sheet | Measurer |
| POST | `/lofts/boats/{boatId}/sail-designs` | Create a new design revision pinning a measurement sheet (existence and FROZEN status are enforced at submission, not at creation); OCC-guarded on Boat.version | Sailmaker |
| GET | `/lofts/boats/{boatId}/sail-designs` | List sail designs for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/sail-designs` | List sail designs across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/sail-designs/{designId}` | Get one sail design | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/sail-designs/{designId}/submit` | Submit a DRAFT design for customer approval | Sailmaker |
| POST | `/lofts/boats/{boatId}/sail-designs/{designId}/approve` | Customer approves a SUBMITTED design | Customer |
| POST | `/lofts/boats/{boatId}/sail-designs/{designId}/request-revision` | Customer requests revision on a SUBMITTED design | Customer |
| POST | `/lofts/boats/{boatId}/sail-designs/{designId}/redraft` | Sailmaker returns a REVISION_REQUESTED design to DRAFT for editing | Sailmaker |
| POST | `/lofts/work-orders` | Open a work order for a customer and boat | LoftManager |
| GET | `/lofts/work-orders` | List work orders, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/work-orders/{workOrderId}` | Get one work order | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/work-orders/{workOrderId}/lock-design` | Lock the APPROVED design into the work order and compute the provisional quote | LoftManager |
| POST | `/lofts/work-orders/{workOrderId}/confirm-delivery` | Customer confirms delivery and fit check; the final invoice is computed | Customer |
| POST | `/lofts/work-orders/{workOrderId}/open-warranty-claim` | Customer opens a warranty claim on a DELIVERED order | Customer |
| POST | `/lofts/work-orders/{workOrderId}/rule-warranty` | Rule the claim: REPAIR credits the invoice and reworks; REPLACE spawns a replacement order | LoftManager |
| POST | `/lofts/work-orders/{workOrderId}/close` | Close a DELIVERED or WARRANTY_REPAIR work order | LoftManager |
| POST | `/lofts/work-orders/{workOrderId}/cancel` | Cancel an OPEN work order, cascading to production jobs, cloth ledger, and orphaned design | LoftManager |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs` | Schedule a production job into a bay window; reserves cloth | Sailmaker |
| GET | `/lofts/work-orders/{workOrderId}/production-jobs` | List production jobs for a work order | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/production-jobs` | List production jobs across work orders, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/production-jobs/{jobId}` | Get one production job | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs/{jobId}/start-cutting` | Advance SCHEDULED to CUTTING; bubbles the parent work order into IN_PRODUCTION | Sailmaker |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs/{jobId}/advance` | Advance CUTTING to SEAMING to FINISHING | Sailmaker |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs/{jobId}/qc-pass` | FINISHING to QC_PASSED; releases the cloth reservation; may bubble the parent to READY_FOR_FIT_CHECK | Sailmaker |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs/{jobId}/qc-fail` | FINISHING to QC_FAILED with notes | Sailmaker |
| POST | `/lofts/work-orders/{workOrderId}/production-jobs/{jobId}/reschedule` | QC_FAILED back to SCHEDULED into a new bay window | Sailmaker |
| POST | `/lofts/cloth-ledger` | Register a cloth bolt | LoftManager |
| GET | `/lofts/cloth-ledger` | List cloth bolts | LoftManager, Sailmaker |
| GET | `/lofts/cloth-ledger/{boltId}` | Get one cloth bolt | LoftManager, Sailmaker |
| POST | `/lofts/boats/{boatId}/rigging-inspections` | Schedule a rigging inspection; OCC-guarded on Boat.version | Rigger |
| GET | `/lofts/boats/{boatId}/rigging-inspections` | List rigging inspections for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/rigging-inspections` | List rigging inspections across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/rigging-inspections/{inspectionId}` | Get one rigging inspection | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/rigging-inspections/{inspectionId}/report` | Submit the inspection verdict; computes replacement clocks; FAIL cascades the boat OUT_OF_SERVICE and mast events to RIGGING_HOLD | Rigger |
| POST | `/lofts/boats/{boatId}/rigging-inspections/{inspectionId}/close` | Close a REPORTED inspection; FAIL verdicts require a passing replacement first | Rigger |
| POST | `/lofts/boats/{boatId}/mast-service-events` | Book a mast unstep, step, or tune slot (half-open interval, adjacency allowed) | Rigger |
| GET | `/lofts/boats/{boatId}/mast-service-events` | List mast service events for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/mast-service-events` | List mast service events across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/mast-service-events/{eventId}` | Get one mast service event | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/mast-service-events/{eventId}/start` | Start a BOOKED event; blocked while a FAIL inspection is unresolved | Rigger |
| POST | `/lofts/boats/{boatId}/mast-service-events/{eventId}/complete` | Complete an IN_PROGRESS event | Rigger |
| POST | `/lofts/boats/{boatId}/mast-service-events/{eventId}/cancel` | Cancel a BOOKED event | Rigger |
| POST | `/lofts/boats/{boatId}/storage-contracts` | Enrol a boat in the off-season storage and wash program | LoftManager |
| GET | `/lofts/boats/{boatId}/storage-contracts` | List storage contracts for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/storage-contracts` | List storage contracts across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/storage-contracts/{contractId}` | Get one storage contract | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/receive` | Mark the boat received; compute the quoted storage fee | LoftManager |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/complete-wash` | Mark wash service complete | LoftManager |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/rack-store` | Move the boat into rack storage | LoftManager |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/stage-delivery` | Stage the boat for spring delivery | LoftManager |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/confirm-return` | Customer confirms the boat is returned; the storage fee is billed | Customer |
| POST | `/lofts/boats/{boatId}/storage-contracts/{contractId}/cancel` | Cancel an ENROLLED contract | LoftManager |
| POST | `/lofts/boats/{boatId}/class-certificates` | Issue a racing-class certificate against a FROZEN measurement sheet | Measurer |
| GET | `/lofts/boats/{boatId}/class-certificates` | List class certificates for a boat | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/class-certificates` | List class certificates across boats, with optional filters | LoftManager, Sailmaker, Measurer, Rigger, Customer |
| GET | `/lofts/class-certificates/{certId}` | Get one class certificate | LoftManager, Sailmaker, Measurer, Rigger, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DESIGN_NOT_IN_REQUIRED_STATE` | 409 Conflict |
| `ERR_UNRESOLVED_RIGGING_FAIL` | 409 Conflict |
| `ERR_MAST_SLOT_OVERLAP` | 409 Conflict |
| `ERR_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MEASUREMENT_NOT_FROZEN` | 409 Conflict |
| `ERR_CLOTH_SHORTAGE` | 409 Conflict |
| `ERR_FAIL_NOT_SUPERSEDED` | 409 Conflict |
| `ERR_STALE_BOAT_VERSION` | 412 Precondition Failed |
| `ERR_CLASS_MISMATCH` | 422 Unprocessable Content |
| `ERR_INVALID_MEASUREMENT` | 422 Unprocessable Content |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 Unprocessable Content |
| `ERR_ACCOUNT_RULE_VIOLATION` | 422 Unprocessable Content |

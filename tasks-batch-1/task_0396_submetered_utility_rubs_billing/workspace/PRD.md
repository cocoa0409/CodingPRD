# Submetered Utility & RUBS Tenant Billing API — Product Requirements Document

## 1. Introduction

Multifamily property operators face a recurring accounting problem: a single master utility invoice arrives for an entire building, yet the cost must be fairly and legally redistributed to the individual residents who actually consumed it. This API is the system of record for that redistribution. It models the full chain from a vendor's master invoice down to each tenant's monthly statement, supporting two distinct allocation philosophies — direct submetered consumption, where each unit pays for what its meter records, and Ratio Utility Billing System (RUBS) allocation, where cost is divided by occupancy weight when submeters are unavailable.

The system is deliberately conservative about money and about the law. Every dollar of a master invoice is partitioned into a non-recoverable common-area reserve, a state-law recovery ceiling, and the recoverable pool that is actually divided among tenants; no allocation may exceed what the resident's home state permits a landlord to recover. Around this fiscal core sit the operational realities of property management: meters are assigned to units over effective date windows, reads are taken, validated, flagged, and re-read; tenants move in and out mid-period and are billed only for their occupied days; statements accrue late fees and march toward collections; and tenants may dispute a charge, triggering a credit or a fresh meter re-read.

Four roles cooperate across this lifecycle. A property manager configures the property and runs billing cycles; a meter technician records and submits reads; a tenant pays statements and raises disputes; and an auditor observes everything read-only. The remainder of this document specifies the global contracts that govern every request, the business logic that drives each workflow, the complete endpoint surface, and the catalogue of error conditions the system enforces.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `PropertyManager`, `MeterTech`, `Tenant`, and `Auditor`. A `PropertyManager` is the operator who configures properties, utilities, units, and meters, records and approves vendor bills, validates reads, runs billing cycles, issues statements, and resolves disputes. A `MeterTech` is a field technician who creates and submits meter reads and re-reads. A `Tenant` is a resident who views and pays their own statements, opens and reopens disputes on them, and gives notice on their own lease. An `Auditor` has read-only oversight across all resources.

Three of these roles carry an opaque identity. When `X-User-Role` is `PropertyManager`, `MeterTech`, or `Auditor`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Tenant`, however, `X-User-ID` is likewise an opaque identifier, but it carries ownership meaning: it is matched against the `tenant_user_id` recorded on a `Lease`. A `Tenant` may act only on disputes, payments, statements, and lease-notice operations belonging to a lease whose `tenant_user_id` equals the caller's `X-User-ID`; any attempt by a tenant to act on a statement, dispute, payment, or lease that does not belong to them is rejected with `ERR_NOT_STATEMENT_OWNER`. When a tenant opens a dispute or posts a payment, the server stamps the dispute's or payment's `tenant_user_id` from the calling `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource — `Property`, `Utility`, `Unit`, `Meter`, `Lease`, `VendorBill`, `MeterRead`, `BillingCycle`, `TenantStatement`, `Dispute`, and `Payment` — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All of these resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every modification, and a `version` integer that begins at the resource's first persisted value and increments by one on every mutation. There are no immutable, version-less resources in this domain; every entity participates in the standard mutation accounting.

Whenever a resource's stored fields change — including derived monetary fields such as a statement's totals or a property's computed status — that change is a mutation: it refreshes the resource's `updated_at` and increments its `version`. This is true even when the change is triggered indirectly by an operation on a different resource. For example, resolving a dispute mutates the underlying `TenantStatement`, and posting or reversing a payment likewise mutates that statement; in each case the statement's `version` advances independently of the dispute or payment that caused the change.

### 2.5. Nested and Filtered Resource Retrieval

Resources in this system are peers linked by foreign keys rather than deeply nested URLs. A request that names a resource identifier in its path must resolve that identifier to an existing resource, and where a path or body names more than one identifier the system validates them left-to-right, rejecting the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. List endpoints accept optional filter parameters that perform reverse reachability — for example, listing utilities by `property_id` and `utility_type`; listing units by `property_id` and `status`; listing meters by `property_id`, `utility_id`, `assigned_unit_id`, and `status`; listing leases by `unit_id`, `property_id`, `tenant_user_id`, and `status`; listing vendor bills by `property_id`, `utility_id`, `period_label`, and `status`; listing meter reads by `meter_id`, `property_id`, `period_label`, and `status`; listing billing cycles by `property_id`, `utility_id`, `period_label`, `vendor_bill_id`, and `status`; listing statements by `billing_cycle_id`, `lease_id`, `unit_id`, `property_id`, and `payment_status`; listing disputes by `statement_id`, `property_id`, and `status`; and listing payments by `statement_id`, `property_id`, and `status`. All such filter parameters are optional.

### 2.6. Monetary Values, Precision, and the Server Clock

All monetary amounts in this system are stored and exchanged as integer cents — there are no fractional cents anywhere in the API. Where a calculation multiplies a monetary amount by a percentage or a ratio, the result is reduced to a whole number of cents by taking the floor (truncating toward zero) of the product, except where a specific rule names a different rounding direction. The late-fee percentage base, for example, is rounded up to the next whole cent (ceiling), as detailed in §3.7; the state-law percentage cap on a late fee is floored. Every individual percentage product is reduced to integer cents at the point it is computed, before being combined with other terms.

The two percentage configuration fields on a `Property` — `recovery_cap_pct` and `common_area_pct` — are stored as fractional numbers and preserve their input precision; they are not cents. The `recovery_cap_pct` must be greater than 0 and less than or equal to 1, and the `common_area_pct` must be at least 0 and strictly less than 1.

Because several rules are time-gated — late-fee assessment, the collections threshold, and move-out finalization all depend on the current date — the system maintains a logical server clock rather than reading wall-clock time. An administrative test-driving capability sets the server's current UTC instant from a supplied `to_iso8601` value, and all subsequent temporal comparisons evaluate against that instant. All date arithmetic in this system is whole-day arithmetic in UTC.

### 2.7. State-Law Recovery, Common-Area Reserve, and the Recoverable Pool

A foundational fiscal principle governs how much of any master invoice may reach tenants. Each `Property` declares a two-letter US `state_code` (uppercase, one of `CA`, `TX`, `NY`, or `FL`), which selects the state-law recovery regime, together with a `recovery_cap_pct` (defaulting to 0.85) that expresses the maximum fraction of a vendor bill the state permits a landlord to recover from tenants, and a `common_area_pct` (defaulting to 0.10) that expresses the fraction of every vendor bill that must be reserved as non-recoverable common-area cost. When a vendor bill is approved, two independent ceilings are applied to its total, and the smaller post-processing result becomes the recoverable pool — the precise mechanics are given in §3.4. Every tenant allocation in a cycle draws only from this recoverable pool, never from the full invoice total.

### 2.8. Allocation Integrity and the Property Integrity Status

A `Property` exposes a computed `integrity_status` that is one of `OK` or `NEEDS_REVIEW`. It is `OK` on a freshly created property. When a billing cycle is closed, the system recomputes the cycle's allocation invariant — that the sum of the issued statements' utility charges reconciles to the cycle's allocated total — and sets the property's `integrity_status` to `NEEDS_REVIEW` if any closed cycle's invariant fails to recompute, leaving it `OK` otherwise. A newly created property also has a null `current_period_label`; this field is set to the period label of the most recently opened billing cycle.

### 2.9. Cascading Side Effects and Hierarchical Consistency

Many operations in this system mutate more than one resource. Validating a meter read updates the meter's last validated reading and may supersede sibling reads; allocating a cycle cascades a status change onto the referenced vendor bill; issuing statements creates one statement per eligible lease; resolving or reopening a dispute and posting or reversing a payment all reach into the affected statement and recompute its money fields. In every such case the system performs all side effects of the operation, and each mutated resource independently advances its own `updated_at` and `version`. The detailed cascades are described alongside the workflows that trigger them in §3; the governing rule here is simply that a side effect named in a workflow is mandatory, not optional, and that every resource it touches is mutated in full.

### 2.10. Optimistic Concurrency Control on Payments

Posting a payment is the one write in this system that is guarded by optimistic concurrency control, because a statement's live balance can legitimately move underneath a paying tenant — a dispute resolution may have applied a credit, or another payment may have been posted, between the moment the tenant read the statement and the moment they submit their payment. A payment request must therefore carry an `expected_statement_version` field, which is required and not optional, holding the `version` of the `TenantStatement` the client last observed. If that value does not equal the statement's current `version` at the time the payment is processed, the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, preventing the client from paying against a balance it has not actually seen. No other write endpoint in this system accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Establishing the Property, Its Utilities, Units, and Meters

A `PropertyManager` bootstraps the system by creating a `Property`, supplying its `name` and `state_code`, and optionally its `recovery_cap_pct` and `common_area_pct` (which otherwise take their defaults). A new property starts with `integrity_status` of `OK` and a null `current_period_label`.

Within a property, the manager configures one or more utilities. A `Utility` is created against a `property_id` and declares its `utility_type` — one of `WATER`, `ELECTRIC`, or `GAS` — its `allocation_method`, which is either `CONSUMPTION` for submeter-driven billing or `RUBS` for occupant-ratio billing, and its `unit_of_measure`, a free-text measurement label such as a gallon, kilowatt-hour, or therm unit. A utility may also carry a `monthly_admin_fee_cents`, a fixed per-unit monthly service fee that defaults to zero, must be at least zero, and is prorated on move-in and move-out. A newly created utility has `status` of `ACTIVE`, which may later become `ARCHIVED`.

Units are likewise created under a `property_id`. Each `Unit` carries a `unit_number` label that must be unique among the property's non-archived units — reusing a number is rejected with `ERR_DUPLICATE_UNIT_NUMBER` — and a `square_feet` area that must be greater than zero and serves as an alternate RUBS weighting basis. A unit begins life `VACANT` and moves between `VACANT`, `OCCUPIED`, and `ARCHIVED` as leases come and go; occupancy is driven entirely by the lease lifecycle, never set directly.

A `Meter` is a submeter created under a `property_id` and a `utility_id`, identified by a `serial_number` that must be unique per property; reusing a serial is rejected with `ERR_DUPLICATE_SERIAL`. A new meter is `UNASSIGNED`, has a null `assigned_unit_id`, null `assignment_effective_from` and `assignment_effective_to`, and a `last_validated_reading` of zero. Its lifecycle spans `UNASSIGNED`, `ASSIGNED`, and the terminal `RETIRED`.

### 3.2. Meter Assignment Windows and Retirement

Assigning a meter to a unit ties physical hardware to the unit it serves over an effective date window. The manager supplies the target `unit_id` and an `effective_from` instant, and optionally an `effective_to` instant; an omitted `effective_to` leaves the window open-ended. The window is half-open, inclusive of its start and exclusive of its end. Before recording the assignment the system confirms the target unit exists and is not `ARCHIVED`, rejecting otherwise with `ERR_UNIT_NOT_FOUND`. It then checks that the requested window does not overlap any other assignment of the same unit for the same utility; because the window is half-open, two windows overlap when one starts strictly before the other ends and ends strictly after the other starts, and a window that begins exactly where another ends does not overlap. An overlap is rejected with `ERR_METER_ASSIGNMENT_OVERLAP`. On success the meter moves from `UNASSIGNED` to `ASSIGNED` and its `assigned_unit_id`, `assignment_effective_from`, and `assignment_effective_to` are recorded; assignment does not by itself change the unit's occupancy status, which remains lease-driven.

An already-`ASSIGNED` meter may be re-assigned to a new window while staying `ASSIGNED`. The new window must not overlap the meter's existing window under the same half-open rule, again rejected with `ERR_METER_ASSIGNMENT_OVERLAP` on conflict. When the prior window was open-ended, it is closed by setting its `assignment_effective_to` to the new window's `effective_from`, and the new window is then recorded.

Retiring a meter moves it to `RETIRED`. A meter that is currently `ASSIGNED` may be retired only when it has no meter read in `SUBMITTED` or `RE_READ_REQUESTED` status tied to an `OPEN` billing cycle; if such a pending read exists the retirement is rejected with `ERR_METER_HAS_PENDING_READS`. A meter that is still `UNASSIGNED` may be retired with no such precondition. On retirement the status becomes `RETIRED` and the `assigned_unit_id` is retained for audit.

### 3.3. The Lease Lifecycle and Occupancy

A `Lease` records a tenant's occupancy of a unit. It is created against a `unit_id` and `property_id` with a `tenant_user_id` — the opaque identifier the tenant authenticates as — an `occupant_count` of at least one (this count is the RUBS allocation weight), and a `move_in_date` marking the inclusive first day of occupancy. A new lease starts `PENDING`, with null `notice_date` and null `move_out_date`. The status progresses through `PENDING`, `ACTIVE`, `NOTICE_GIVEN`, `MOVED_OUT`, and the terminal `CLOSED`.

Activating a lease drives it from `PENDING` to `ACTIVE` and is the move-in event. The system confirms the unit is not `ARCHIVED` (otherwise `ERR_UNIT_NOT_FOUND`) and that no other lease of the same unit in `ACTIVE` or `NOTICE_GIVEN` status has an occupancy interval that overlaps this lease's `move_in_date`. An occupancy interval runs from `move_in_date` to `move_out_date` with the move-out day treated as inclusive, and a null `move_out_date` makes the interval open-ended. A conflicting occupancy is rejected with `ERR_LEASE_OCCUPANCY_OVERLAP`. On success the lease becomes `ACTIVE` and the unit transitions to `OCCUPIED`.

Giving notice moves an `ACTIVE` lease to `NOTICE_GIVEN`. The request supplies the intended `move_out_date`, which must be on or after the `move_in_date`; an earlier date is rejected with `ERR_INVALID_MOVE_OUT_DATE`. On success the `notice_date` is stamped and the `move_out_date` is recorded. Either a `PropertyManager` or the owning `Tenant` may give notice; a tenant doing so must own the lease, or the request is rejected with `ERR_NOT_STATEMENT_OWNER`.

Finalizing move-out moves a `NOTICE_GIVEN` lease to `MOVED_OUT`, but only once the server clock's current date is strictly past the recorded `move_out_date`; attempting it earlier is rejected with `ERR_MOVE_OUT_NOT_DUE`. On finalization the lease becomes `MOVED_OUT` and the unit returns to `VACANT`. Finally, a `MOVED_OUT` lease may be closed, moving it to the terminal `CLOSED`, but only when none of the lease's statements still owe money — that is, when no `TenantStatement` of the lease has a `payment_status` of `UNPAID`, `PARTIALLY_PAID`, `DELINQUENT`, or `IN_COLLECTIONS`. A lease with any such open balance cannot be closed and the attempt is rejected with `ERR_LEASE_HAS_OPEN_BALANCE`.

### 3.4. Vendor Bills: Common-Area Deduction and the State-Law Recovery Cap

The billing chain begins when a master invoice arrives. A `PropertyManager` records a `VendorBill` against a `property_id` and a `utility_id`, naming the `period_label` it covers (for example a year-month label such as 2026-06) and the `total_cost_cents` the vendor charged, which must be strictly greater than zero. A new vendor bill is `RECEIVED`, with `common_area_cents`, `cap_cents`, and `recoverable_cents` all defaulting to zero until approval. The lifecycle runs `RECEIVED`, `APPROVED`, `ALLOCATED`, and the terminal `VOIDED`.

Approving a vendor bill moves it from `RECEIVED` to `APPROVED` and is where the two ceilings are computed. The total must still be greater than zero, or the request is rejected as an invalid request. The system then performs a two-step waterfall. First, the common-area reserve is computed as the floor of the bill's `total_cost_cents` multiplied by the property's `common_area_pct`; this amount is stored in `common_area_cents` and is permanently non-recoverable. Independently and from the same total, the state-law ceiling is computed as the floor of `total_cost_cents` multiplied by the property's `recovery_cap_pct`, and stored in `cap_cents`. The recoverable pool, stored in `recoverable_cents`, is then the smaller of two quantities: the post-deduction amount (the bill's total minus its `common_area_cents`) and the state-law cap (`cap_cents`). When the post-deduction amount exceeds the cap, the state-law ceiling binds and `recoverable_cents` equals `cap_cents`; when the post-deduction amount is less than or equal to the cap, the common-area deduction binds and `recoverable_cents` equals the total minus the common-area reserve. The common-area deduction is always applied first; the recovery cap is a second, independent ceiling on the same original total, not on the post-deduction figure.

A vendor bill advances from `APPROVED` to `ALLOCATED` only as a system cascade when a billing cycle that references it is allocated (see §3.6); that transition requires the bill to be `APPROVED` and locks its `recoverable_cents`. A vendor bill may be voided to the terminal `VOIDED` from either `RECEIVED` or `APPROVED`. A `RECEIVED` bill may be voided only when no billing cycle references it in any non-`OPEN` status, and an `APPROVED` bill may be voided only when no billing cycle references it in `ALLOCATED`, `STATEMENTS_ISSUED`, or `CLOSED` status; a referenced bill that cannot be voided is rejected with `ERR_VENDOR_BILL_IN_USE`.

### 3.5. Meter Reads: Submission, Validation, Flagging, and Re-Read

A meter read captures a cumulative reading at the end of a period. A `MeterTech` or `PropertyManager` creates a `MeterRead` against a `meter_id`, a `property_id`, and a `period_label`, supplying the `reading_value` — the cumulative reading at period end, which must be at least zero. A new read is `PENDING`, with `consumption` defaulting to zero, a `re_read_count` of zero, and a null `flag_reason`. The read's status spans `PENDING`, `SUBMITTED`, `VALIDATED`, `FLAGGED`, `RE_READ_REQUESTED`, and the terminal `SUPERSEDED`.

Submitting a read advances it from `PENDING` to `SUBMITTED`, and may be performed only by a `MeterTech`. The matching billing cycle — the one whose property, utility, and period align with this read — must be `OPEN`, or the submission is rejected with `ERR_CYCLE_NOT_OPEN`. On submission the read's `consumption` is computed as the reading value minus the meter's `last_validated_reading`, clamped so it is never negative; concretely, consumption is the larger of zero and the difference between `reading_value` and the meter's current `last_validated_reading`.

A `PropertyManager` validates a submitted read, moving it from `SUBMITTED` to `VALIDATED`. Validation enforces a high-reading safety band: if the meter's `last_validated_reading` is zero — the first-ever validated read for that meter — any non-negative consumption is accepted; otherwise the read's `consumption` may not exceed the `last_validated_reading` multiplied by the high-reading multiple of three. The boundary is inclusive: a consumption exactly equal to three times the prior validated reading is accepted, and only consumption strictly above that limit is rejected. A read that exceeds the band must not be validated; the attempt is rejected with `ERR_READING_OUT_OF_RANGE`, and the read must instead be flagged and re-read. On successful validation the system sets the meter's `last_validated_reading` to this read's `reading_value`, and any other read for the same meter and period that was in `SUBMITTED` or `VALIDATED` status is transitioned to `SUPERSEDED`.

When a submitted read looks suspicious, a `PropertyManager` may flag it instead, moving it from `SUBMITTED` to `FLAGGED` and recording a `flag_reason`. From `FLAGGED`, the manager may request a re-read, moving the read to `RE_READ_REQUESTED` and incrementing its `re_read_count` by one. The technician then submits the re-read, which carries the read from `RE_READ_REQUESTED` back to `SUBMITTED`; this submission again requires the matching billing cycle to be `OPEN` (otherwise `ERR_CYCLE_NOT_OPEN`), overwrites the `reading_value` with the re-read value supplied as `reading_value`, and recomputes `consumption` as the larger of zero and the difference between the new reading value and the meter's `last_validated_reading`. This flag-then-re-read loop may repeat, each pass returning the read to validation. Separately, when a newer read for the same meter and period is validated, any previously `VALIDATED` read is moved to `SUPERSEDED` by the system.

### 3.6. Running a Billing Cycle: Lock, Allocate, Issue

A `BillingCycle` ties a property's utility to a specific vendor bill for one period. A `PropertyManager` opens a cycle against a `property_id`, a `utility_id`, a `vendor_bill_id`, and a `period_label`, bounding the period with a `period_start` and `period_end` (both inclusive UTC dates). A new cycle is `OPEN`, with `allocated_total_cents` defaulting to zero, and opening it sets the property's `current_period_label` to the cycle's period. The cycle's status advances through `OPEN`, `READS_LOCKED`, `ALLOCATED`, `STATEMENTS_ISSUED`, and the terminal `CLOSED`.

Locking reads moves a cycle from `OPEN` to `READS_LOCKED` and freezes the period's reads. For a utility whose allocation method is `CONSUMPTION`, every assigned, non-`RETIRED` meter of that property and utility must have exactly one `VALIDATED` read for the period, with none lingering in `SUBMITTED`, `FLAGGED`, or `RE_READ_REQUESTED`; if any consumption meter lacks its single validated read or has an unresolved read, the lock is rejected with `ERR_READS_NOT_VALIDATED`.

Allocating a cycle moves it from `READS_LOCKED` to `ALLOCATED` and is where the recoverable pool is divided into per-unit shares. The cycle's referenced vendor bill must be `APPROVED`, or the allocation is rejected with `ERR_VENDOR_BILL_NOT_APPROVED`. The allocation runs in one of two modes according to the utility's `allocation_method`, both drawing on the vendor bill's `recoverable_cents` (the two modes are detailed in §3.7). The allocation produces a utility charge for each billed unit; as a cascade, the referenced vendor bill transitions from `APPROVED` to `ALLOCATED`, which locks its recoverable amount, and the cycle's `allocated_total_cents` is set to reflect the allocation.

Issuing statements moves a cycle from `ALLOCATED` to `STATEMENTS_ISSUED`. At least one lease in `ACTIVE`, `NOTICE_GIVEN`, or `MOVED_OUT` status must have occupied a billed unit during the period, or the issue is rejected with `ERR_NO_BILLABLE_LEASES`. On success the system creates exactly one `TenantStatement` per eligible lease, each born with `delivery_status` of `ISSUED` and `payment_status` of `UNPAID`, computes the prorated admin fee, sets the `due_date` to the issue date plus the net-terms window (described in §3.8), and computes each statement's total and balance.

Closing a cycle moves it from `STATEMENTS_ISSUED` to the terminal `CLOSED`, permitted only when no statement of the cycle has a dispute in `OPEN` or `UNDER_REVIEW` status; an open dispute blocks closure with `ERR_CYCLE_HAS_OPEN_DISPUTES`. On close, the system recomputes the allocation invariant for the cycle and updates the property's `integrity_status` accordingly, as described in §2.8.

### 3.7. Dividing the Pool: Consumption Allocation, RUBS Allocation, and Admin-Fee Proration

The two allocation modes share a common largest-remainder structure but differ in the weight they use. Under **consumption allocation**, used when the utility's `allocation_method` is `CONSUMPTION`, the total consumption is the sum over the billed units of each unit's `VALIDATED` meter read consumption for the period. Each unit's floor share is the floor of the recoverable pool multiplied by that unit's consumption divided by the total consumption. Because flooring each share leaves a remainder, the leftover cents — the recoverable pool minus the sum of all the floor shares — are distributed one cent at a time to units, taken in order of descending consumption and, where two units have equal consumption, ascending unit creation timestamp. Each unit's final utility charge is its floor share plus any remainder cents it received. When the total consumption for the period is zero, every unit's utility charge is zero and the recoverable pool is left unallocated (it is absorbed as a common-area shortfall rather than charged to tenants).

Under **RUBS allocation**, used when the utility's `allocation_method` is `RUBS`, meter reads are ignored entirely; the weight is occupancy, never metered consumption. The total weight is the sum over the billed units of each unit's active lease `occupant_count`. Each unit's floor share is the floor of the recoverable pool multiplied by that unit's occupant count divided by the total weight, and the leftover cents (the pool minus the sum of floor shares) are distributed one cent at a time in order of descending occupant count, breaking ties by ascending unit creation timestamp. Each unit's final utility charge is its floor share plus any remainder cents received. RUBS billing considers units occupied by a lease in `ACTIVE`, `NOTICE_GIVEN`, or `MOVED_OUT` status overlapping the period.

When statements are issued, each statement's monthly admin fee is prorated to the days the tenant occupied the unit within the period. The period length in whole days is the difference between `period_end` and `period_start` in whole days plus one, since both endpoints are inclusive. The occupancy start is the later of the lease's `move_in_date` and the period start; the occupancy end is the earlier of the period end and the lease's `move_out_date` (or the period end itself when no move-out date is set). The occupied-day count is the difference between that occupancy end and occupancy start in whole days plus one, again inclusive of both ends. If the occupied-day count is zero or negative, the `admin_fee_cents` is zero. If the occupied-day count meets or exceeds the full period length, the full `monthly_admin_fee_cents` is charged with no proration. Otherwise the `admin_fee_cents` is the floor of the utility's `monthly_admin_fee_cents` multiplied by the occupied days divided by the period days.

### 3.8. Statement Totals, Due Dates, and the Delivery Dimension

A `TenantStatement` is the per-tenant bill for one cycle. It references a `billing_cycle_id`, a `lease_id`, a `unit_id`, and a `property_id`, and carries the money fields `utility_charge_cents` (the allocated share from §3.7), `admin_fee_cents` (the prorated fee), `late_fee_cents`, `credit_cents` (cumulative dispute credits), `amount_paid_cents` (cumulative posted payments), and the two derived fields `total_due_cents` and `balance_due_cents`. The statement totals obey a strict invariant at all times: the `total_due_cents` equals the utility charge plus the admin fee plus the late fee minus the credits, and the `balance_due_cents` equals the `total_due_cents` minus the amount paid. These inputs are already integer cents, so no rounding is applied when totalling. Any change to the utility charge, admin fee, late fee, credit, or amount paid re-derives both totals.

Each statement also carries a `due_date`, computed when statements are issued as the issue date plus the net-terms window of twenty-one days; this due date drives the late-fee and delinquency checks.

A statement evolves along two independent dimensions. The `delivery_status` dimension tracks `DRAFT`, `ISSUED`, and `DELIVERED`, and the `payment_status` dimension tracks `UNPAID`, `PARTIALLY_PAID`, `PAID`, `DELINQUENT`, and `IN_COLLECTIONS`; the two never interfere with each other. Statements are born `ISSUED` on the delivery dimension when the cycle issues them (with the `due_date` computed at that point). A `PropertyManager` may mark an `ISSUED` statement as `DELIVERED`; this delivery action touches only the delivery dimension and never the payment dimension.

### 3.9. Payments, the Payment Dimension, and OCC

A `Tenant` (or a `PropertyManager` acting on their behalf) posts a payment against a statement. The payment supplies an `amount_cents` and the `expected_statement_version`. The amount must be strictly greater than zero and at most the statement's current `balance_due_cents`; an amount exceeding the balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. As described in §2.10, the `expected_statement_version` must equal the statement's current `version`, or the post is rejected with `ERR_STALE_VERSION`. A tenant may pay only their own statement, or the request is rejected with `ERR_NOT_STATEMENT_OWNER`.

A successful payment creates a `Payment` resource against a `statement_id` and `property_id` with its `tenant_user_id` stamped from the caller; the payment begins `POSTED` and may later become `REVERSED`. Posting adds the `amount_cents` to the statement's `amount_paid_cents`, recomputes `balance_due_cents`, and advances the statement's `version`. The payment dimension moves accordingly: a partial payment (a positive amount strictly less than the balance) takes an `UNPAID` statement to `PARTIALLY_PAID`; a payment exactly equal to the balance clears it, driving the balance to zero and the payment status to `PAID` — this applies whether the statement was `UNPAID`, `PARTIALLY_PAID`, or `DELINQUENT` at the time the balance is cleared in full.

A `PropertyManager` may reverse a posted payment, but only while the parent billing cycle is not `CLOSED`; a reversal against a closed cycle is rejected with `ERR_CYCLE_CLOSED`. Reversing a payment moves it to `REVERSED`, subtracts its `amount_cents` from the statement's `amount_paid_cents`, recomputes the `balance_due_cents`, recomputes the `payment_status` (for instance back from `PAID` to `PARTIALLY_PAID` or `UNPAID` as the restored balance dictates), and advances the statement's `version` as a compensating mutation.

### 3.10. Delinquency, Late Fees, and Collections

When a statement goes unpaid past its grace window, a `PropertyManager` (or the system on a clock advance) may assess a late fee. Assessment is permitted only when the current clock date is strictly past the `due_date` plus the grace window of five days and the statement's `balance_due_cents` is still greater than zero; an attempt before that grace has elapsed is rejected with `ERR_NOT_YET_DELINQUENT`. Assessment may carry an `UNPAID` or `PARTIALLY_PAID` statement to `DELINQUENT`.

The late fee itself is computed from the statement's `balance_due_cents` at the moment of assessment, in a fixed four-step order. First, a percentage base is computed as the balance multiplied by the late-fee rate of five percent, rounded up to the next whole cent. Second, a flat minimum of five hundred cents is applied by taking the larger of that flat floor and the percentage base. Third, an absolute dollar cap of five thousand cents is applied by taking the smaller of the running fee and that cap. Fourth, a state-law percentage cap is applied: the fee is reduced to the smaller of the running fee and the floor of the balance multiplied by the state-law late-fee ceiling of ten percent. The resulting value is the `late_fee_cents`. This evaluation order is fixed — percentage base, then flat floor, then absolute cap, then state-law percentage cap — and the order can change which limit binds. On assessment the computed late fee is added to the statement, the `total_due_cents` and `balance_due_cents` are recomputed, the payment status becomes `DELINQUENT`, and the statement's `version` advances.

A `DELINQUENT` statement may be escalated to `IN_COLLECTIONS` by a `PropertyManager`, but only when its `balance_due_cents` is still greater than zero and the statement has been delinquent long enough — the current clock date must be at or after the `due_date` plus the collections window of thirty days; an attempt before that threshold is rejected with `ERR_NOT_YET_COLLECTIONS`. Note that the delinquency threshold uses a strict "after" comparison while the collections threshold is satisfied at or after its boundary. On escalation the payment status becomes `IN_COLLECTIONS` and the statement's `version` advances. A statement that reaches `DELINQUENT` can still be brought current: a tenant paying the full outstanding balance, including the late fee, drives it to `PAID`.

### 3.11. Disputes, Credits, Re-Reads, and Reopening

A `Tenant` (or a `PropertyManager` on their behalf) may open a `Dispute` against a statement. The dispute is created against a `statement_id`, captures a `reason` — one of `HIGH_READING`, `WRONG_METER`, `RATIO_ERROR`, or `DOUBLE_BILLED` — and may set `requested_re_read` (defaulting to false) to indicate the dispute should trigger a fresh meter re-read, along with an optional `credit_amount_cents` (defaulting to zero) suggesting the credit to grant. The dispute also records a `property_id`, a `reopen_count` that starts at zero, and its `tenant_user_id`, which is stamped from the caller. A new dispute is `OPEN`; the lifecycle runs `OPEN`, `UNDER_REVIEW`, `RESOLVED`, and the terminal `REJECTED`. A tenant may dispute only their own statement, or the request is rejected with `ERR_NOT_STATEMENT_OWNER`.

A `PropertyManager` begins review, moving a dispute from `OPEN` to `UNDER_REVIEW`. If the dispute requested a re-read, this transition triggers a re-read cascade: the latest `VALIDATED` meter read for the disputed statement's meter and period is moved to `SUPERSEDED`, and a fresh read row in `RE_READ_REQUESTED` status is created so the field technician can take a new reading.

Resolving a dispute moves it from `UNDER_REVIEW` to `RESOLVED` and grants a credit. The `credit_amount_cents` granted on resolution must not exceed the statement's `total_due_cents`, or the resolution is rejected with `ERR_CREDIT_EXCEEDS_DUE`; a granted credit of zero is the reject-style resolution. On resolution the granted credit is added to the statement's `credit_cents`, the `total_due_cents` and `balance_due_cents` are recomputed, and if the resulting balance is zero or below the statement's payment status is set to `PAID`; the statement's `version` advances. Alternatively a dispute may be rejected outright, moving it from `UNDER_REVIEW` to the terminal `REJECTED` with no credit and no statement change.

A `RESOLVED` dispute may be reopened by either the owning `Tenant` or a `PropertyManager`, moving it back to `UNDER_REVIEW`. Reopening is allowed only while the parent billing cycle is not `CLOSED` (otherwise `ERR_CYCLE_CLOSED`) and only while the dispute's `reopen_count` is below the maximum of two reopens; exceeding that limit is rejected with `ERR_MAX_REOPENS_REACHED`. On reopen the `reopen_count` increments by one and the previously granted credit is reversed — the prior `credit_amount_cents` is subtracted back out of the statement's `credit_cents`, the balances are recomputed, and the statement's `version` advances as a compensating mutation, keeping the statement's money conserved across the reopen cycle.

### 3.12. Request Validation Ordering

Across all endpoints the system evaluates checks in a fixed precedence so that the same failure always surfaces the same error. Authentication comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Next, role authorization is checked, yielding `ERR_FORBIDDEN_FOR_ROLE` when the role may not perform the operation. Then every resource identifier named in the path or body is resolved left-to-right, yielding `ERR_NOT_FOUND` for the first that does not exist. After that, for tenant-scoped actions, ownership is checked, yielding `ERR_NOT_STATEMENT_OWNER` when the caller does not own the lease behind the resource. Then the request body is validated for well-formedness — required fields present, amounts and percentages in range, enumerations valid — yielding `ERR_INVALID_REQUEST` on a malformed body. Only then is the target's state checked: a transition requested from a state that does not allow it yields `ERR_INVALID_STATE`. Finally the endpoint-specific business rules run — meter-assignment overlap, lease-occupancy overlap, the read high-reading band, read-lock completeness, vendor-bill approval, late-fee timing, dispute-credit limits, payment OCC, and payment-amount bounds — each in the position its workflow describes. In particular, the optimistic-concurrency check on a payment surfaces as `ERR_STALE_VERSION` and the payment-amount bound surfaces as `ERR_PAYMENT_EXCEEDS_BALANCE`, as described in §3.9.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (such as a property, utility, unit, meter, lease, vendor bill, meter read, billing cycle, payment, or dispute) return a `201 Created` status code. State-transition and modification operations, as well as the clock-setting capability, return a `200 OK` status code. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | PropertyManager |
| POST | `/properties` | Create a Property | PropertyManager |
| GET | `/properties/{propertyId}` | Get a Property | PropertyManager, MeterTech, Tenant, Auditor |
| POST | `/utilities` | Create a Utility config under a Property | PropertyManager |
| GET | `/utilities/{utilityId}` | Get a Utility | PropertyManager, MeterTech, Tenant, Auditor |
| GET | `/utilities` | List Utilities filtered by property | PropertyManager, MeterTech, Auditor |
| POST | `/units` | Create a Unit under a Property | PropertyManager |
| GET | `/units/{unitId}` | Get a Unit | PropertyManager, MeterTech, Tenant, Auditor |
| GET | `/units` | List Units filtered by property | PropertyManager, MeterTech, Auditor |
| POST | `/meters` | Create a Meter under a Property+Utility | PropertyManager |
| GET | `/meters/{meterId}` | Get a Meter | PropertyManager, MeterTech, Auditor |
| GET | `/meters` | List Meters filtered by property/utility/assigned-unit | PropertyManager, MeterTech, Auditor |
| POST | `/meters/{meterId}/assign` | Assign a Meter to a Unit for an effective window | PropertyManager |
| POST | `/meters/{meterId}/retire` | Retire a Meter | PropertyManager |
| POST | `/leases` | Create a Lease (occupancy) on a Unit | PropertyManager |
| GET | `/leases/{leaseId}` | Get a Lease | PropertyManager, Tenant, Auditor |
| GET | `/leases` | List Leases filtered by unit/property/tenant | PropertyManager, Tenant, Auditor |
| POST | `/leases/{leaseId}/activate` | Activate a Lease (move-in) | PropertyManager |
| POST | `/leases/{leaseId}/give-notice` | Record move-out notice with intended move_out_date | PropertyManager, Tenant |
| POST | `/leases/{leaseId}/move-out` | Finalize move-out | PropertyManager |
| POST | `/leases/{leaseId}/close` | Close a Lease after balances settled | PropertyManager |
| POST | `/vendor-bills` | Record a master utility VendorBill | PropertyManager |
| GET | `/vendor-bills/{vendorBillId}` | Get a VendorBill | PropertyManager, Auditor |
| GET | `/vendor-bills` | List VendorBills filtered by property/utility/period | PropertyManager, Auditor |
| POST | `/vendor-bills/{vendorBillId}/approve` | Approve a VendorBill; compute deduction + cap + recoverable | PropertyManager |
| POST | `/vendor-bills/{vendorBillId}/void` | Void a VendorBill | PropertyManager |
| POST | `/meter-reads` | Create a PENDING MeterRead for a meter+period | MeterTech, PropertyManager |
| GET | `/meter-reads/{readId}` | Get a MeterRead | PropertyManager, MeterTech, Auditor |
| GET | `/meter-reads` | List MeterReads filtered by meter/property/period | PropertyManager, MeterTech, Auditor |
| POST | `/meter-reads/{readId}/submit` | Submit a read (or re-read) for validation | MeterTech |
| POST | `/meter-reads/{readId}/validate` | Validate a submitted read | PropertyManager |
| POST | `/meter-reads/{readId}/flag` | Flag a suspicious submitted read | PropertyManager |
| POST | `/meter-reads/{readId}/request-re-read` | Request a re-read of a flagged read | PropertyManager |
| POST | `/billing-cycles` | Open a BillingCycle for a property+utility+period | PropertyManager |
| GET | `/billing-cycles/{cycleId}` | Get a BillingCycle | PropertyManager, Auditor |
| GET | `/billing-cycles` | List BillingCycles filtered by property/utility/period/vendor-bill | PropertyManager, Auditor |
| POST | `/billing-cycles/{cycleId}/lock-reads` | Lock reads for the cycle | PropertyManager |
| POST | `/billing-cycles/{cycleId}/allocate` | Run consumption or RUBS allocation over recoverable cents | PropertyManager |
| POST | `/billing-cycles/{cycleId}/issue-statements` | Create tenant statements with prorated admin fee + due date | PropertyManager |
| POST | `/billing-cycles/{cycleId}/close` | Close the cycle (recompute allocation invariant) | PropertyManager |
| GET | `/statements/{statementId}` | Get a TenantStatement | PropertyManager, Tenant, Auditor |
| GET | `/statements` | List TenantStatements filtered by cycle/lease/unit/property | PropertyManager, Tenant, Auditor |
| POST | `/statements/{statementId}/mark-delivered` | Mark a statement delivered (delivery dimension only) | PropertyManager |
| POST | `/statements/{statementId}/assess-late-fee` | Assess late fee after grace, moving payment dimension to DELINQUENT | PropertyManager |
| POST | `/statements/{statementId}/send-to-collections` | Escalate a delinquent statement to collections | PropertyManager |
| POST | `/statements/{statementId}/payments` | Post a tenant payment against a statement (OCC-guarded) | Tenant, PropertyManager |
| GET | `/payments/{paymentId}` | Get a Payment | PropertyManager, Tenant, Auditor |
| GET | `/payments` | List Payments filtered by statement/property | PropertyManager, Tenant, Auditor |
| POST | `/payments/{paymentId}/reverse` | Reverse a posted payment (compensation) | PropertyManager |
| POST | `/statements/{statementId}/disputes` | Open a dispute against a statement (optionally requesting a re-read) | Tenant, PropertyManager |
| GET | `/disputes/{disputeId}` | Get a Dispute | PropertyManager, Tenant, Auditor |
| GET | `/disputes` | List Disputes filtered by statement/property | PropertyManager, Tenant, Auditor |
| POST | `/disputes/{disputeId}/start-review` | Begin review; if requested, trigger a re-read cascade | PropertyManager |
| POST | `/disputes/{disputeId}/resolve` | Resolve a dispute, granting credit to the statement | PropertyManager |
| POST | `/disputes/{disputeId}/reject` | Reject a dispute with no credit | PropertyManager |
| POST | `/disputes/{disputeId}/reopen` | Reopen a resolved dispute (reverses prior credit) | Tenant, PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_NOT_STATEMENT_OWNER` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_METER_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_METER_HAS_PENDING_READS` | 409 Conflict |
| `ERR_READING_OUT_OF_RANGE` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 Conflict |
| `ERR_LEASE_OCCUPANCY_OVERLAP` | 409 Conflict |
| `ERR_INVALID_MOVE_OUT_DATE` | 422 Unprocessable Entity |
| `ERR_MOVE_OUT_NOT_DUE` | 409 Conflict |
| `ERR_LEASE_HAS_OPEN_BALANCE` | 409 Conflict |
| `ERR_VENDOR_BILL_NOT_APPROVED` | 409 Conflict |
| `ERR_VENDOR_BILL_IN_USE` | 409 Conflict |
| `ERR_READS_NOT_VALIDATED` | 409 Conflict |
| `ERR_NO_BILLABLE_LEASES` | 409 Conflict |
| `ERR_CYCLE_HAS_OPEN_DISPUTES` | 409 Conflict |
| `ERR_CYCLE_CLOSED` | 409 Conflict |
| `ERR_NOT_YET_DELINQUENT` | 409 Conflict |
| `ERR_NOT_YET_COLLECTIONS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 Conflict |
| `ERR_CREDIT_EXCEEDS_DUE` | 409 Conflict |
| `ERR_MAX_REOPENS_REACHED` | 409 Conflict |

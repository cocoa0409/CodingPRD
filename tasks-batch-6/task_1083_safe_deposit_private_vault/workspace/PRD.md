# Safe-Deposit & Private-Vault Service API — Product Requirements Document

## 1. Introduction

The Safe-Deposit & Private-Vault Service API is the system of record for a physical vault operation that leases safe-deposit boxes to individuals and manages every downstream obligation those leases create: recurring billing and auto-pay, controlled physical access with dual-control logging, precious-metal storage with an insurance rider, beneficiary and deputy access grants, forced drilling and abandonment of delinquent boxes, and the compliance casework (KYC, sanctions, suspicious-activity, and currency-transaction reporting) that regulates all of it.

Two forces shape the design. The first is **compliance and auditability**: sensitive actions — verifying identity, approving a drill, exercising a beneficiary grant on a deceased renter, entering a vault under supervision — must be gated by role, segregated across distinct actors, and recorded in an immutable trail. The second is **temporal correctness of money and access**: rent accrues, invoices fall due, late fees escalate by tier, refunds prorate on surrender and again on close, and access appointments must fit inside a branch's viewing-room capacity across overlapping time windows. Because the two interact — a delinquent rental blocks access and ultimately triggers a drill whose proceeds are distributed by a fixed waterfall — the system runs on a **logical clock** rather than wall-clock time, so that billing cycles, grace periods, and appointment windows are all evaluated deterministically against an operator-controlled instant.

This document specifies the complete contract: global conventions in §2, the business workflows and their scattered rules in §3, the endpoint surface in §4, and the error catalogue in §5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply across the entire API. All resource collections are mounted under the `/vault` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a value the server cannot validate, is rejected with `ERR_UNAUTHENTICATED`. When a caller is authenticated but their role is not permitted for the target operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes six roles, spelled exactly as follows: `VaultAdmin`, `BillingClerk`, `VaultOfficer`, `ComplianceOfficer`, `Renter`, and `Any`. `VaultAdmin` is the operations superuser responsible for infrastructure (branches, box types, boxes), the rental lifecycle, invoice adjustments, payment reversal, drilling logistics, and the two system utilities (the logical clock and the billing cycle). `BillingClerk` handles registration, rental creation and activation, invoice issuance, and payment intake and clearing. `VaultOfficer` staffs the vault floor: appointments, dual-control access logging, and inventory intake and appraisal. `ComplianceOfficer` owns KYC decisions, compliance cases, access-grant activation, and drilling approval. `Renter` is the box lessee acting on their own rentals. `Any` denotes that any one of the five authenticated roles may perform the read (`GET`) operations.

All five operational roles carry an **opaque** identity: for `VaultAdmin`, `BillingClerk`, `VaultOfficer`, and `ComplianceOfficer`, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record it where a workflow requires — for example, as `requested_by_ref` and `approved_by_ref` on a `DrillingOrder`, or as `primary_accessor_ref` and `dual_control_officer_ref` on an `AccessEvent` — but it does not compare it to any entity's `id`. The lone exception in framing is the segregation-of-duties rule on drilling approval, where two opaque identifiers are compared to each other (see §2.10). The `Renter` role is **entity-backed**: when `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `Renter` entity, and ownership checks on any resource that references a renter compare that resource's renter foreign key to `X-User-ID`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. A `limit` or `offset` outside its permitted range is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (also ISO 8601 UTC, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on each mutation. These common fields are present on `Branch`, `BoxType`, `Box`, `Renter`, `Rental`, `Invoice`, `Payment`, `AccessGrant`, `AccessAppointment`, `InventoryItem`, `DrillingOrder`, and `ComplianceCase`.

The one exception is `AccessEvent`, which is an append-only audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is logged.

Time in this system is governed by a **logical clock**, not the host wall clock. On startup the clock reads `2026-05-01T00:00:00Z`, and it advances only when a `VaultAdmin` sets it by supplying a `to_iso8601` instant; the clock-set response echoes the new value as `current_utc`, and the clock never falls back to real time. All system-assigned timestamps — a rental's `start_date`, an invoice's `issued_on`, a payment's `cleared_on`, an access event's `occurred_at`, a drilling order's `drilled_at`, a compliance case's `opened_on` and `resolved_on` — are read from this clock at the moment of the action. Every date-based calculation (billing due dates, delinquency grace, surrender proration, appointment window checks) evaluates against the clock's current instant.

### 2.5. Hierarchical Consistency and Cascading State Propagation

Many operations mutate more than one resource. When a rental changes state, its box, its access grants, and its inventory items may change with it; when a payment clears, its invoices and its rental may change with it. In every such case, each affected resource is independently mutated — its `status` (or other fields) updated, its `updated_at` refreshed, and its `version` incremented — even though the client acted on only one resource directly. These secondary effects are described alongside the workflow that triggers them in §3, and they are not optional: a cascade that the specification names must always fire.

The most consequential cascade chains are the delinquency/drilling path (a delinquent rental whose box is drilled becomes `ABANDONED`, revoking its grants and releasing its inventory) and the cure path (a payment that zeroes the balance restores a `PAST_DUE` or `DELINQUENT` rental to `ACTIVE` and its box from `DELINQUENT` back to `RENTED`). Because the box, rental, grants, and inventory each version independently, a downstream reader always observes a consistent snapshot.

### 2.6. Nested Reference Validation Order

Requests are validated in a fixed precedence, evaluated top to bottom, so that the first failing gate determines the error returned:

1. **Authentication** — headers present and valid, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform this operation, and (for drilling approval) the segregation-of-duties rule holds, else `ERR_FORBIDDEN_FOR_ROLE` (403) or `ERR_SEGREGATION_OF_DUTIES` (403).
3. **Existence** — every referenced resource exists. Path identifiers and body foreign keys are checked left to right, and the first identifier that resolves to nothing yields `ERR_NOT_FOUND` (404). A body foreign key is only checked after the path resource it belongs to is confirmed.
4. **Request well-formedness** — required fields present, enums valid, numeric constraints satisfied (payment `amount_cents` greater than zero, `purity` in the half-open range greater than 0 and at most 1, and the precious-metal fields present when required), else `ERR_INVALID_REQUEST` (422).
5. **Compliance and identity safety** — the KYC, hold, and dual-control gates described in §2.10, using status 409.
6. **State validity** — the target resource (and any cross-entity dependency such as a box's or rental's status) is in a state that permits the transition, else `ERR_INVALID_STATE`, `ERR_BOX_NOT_AVAILABLE`, or `ERR_RENTAL_NOT_ACCESSIBLE` (all 409).
7. **Temporal sanity** — for appointment booking, the window is well-formed and future-dated, else `ERR_APPOINTMENT_IN_PAST` (409).
8. **Scheduling constraints** — for appointment booking, no box overlap and no room-capacity breach, else `ERR_APPOINTMENT_OVERLAP` or `ERR_ROOM_CAPACITY_EXCEEDED` (409).
9. **Referential consistency** — grant-to-rental linkage and beneficiary certificate requirements, else `ERR_GRANT_RENTAL_MISMATCH` or `ERR_DEATH_CERTIFICATE_REQUIRED` (409).
10. **Fiscal gates** — outstanding-balance and drilling-eligibility rules, else `ERR_OUTSTANDING_BALANCE` or `ERR_DRILL_NOT_ELIGIBLE` (409).
11. **Optimistic concurrency** — the version check described in §2.8, else `ERR_STALE_VERSION` (412).

This ordering matters: a compliance hold (priority 5) surfaces before a state error (priority 6), so a frozen renter attempting to check in sees the hold, not a state complaint.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer **cents**. Wherever a calculation divides or applies a rate, the result is rounded to whole cents using the **round-half-up** convention (a fractional half-cent rounds up). Two rounding disciplines are pinned and must not be reinterpreted:

- **Per-component then sum.** When an invoice's charges are assembled, the insurance rider and each individual precious-metal item surcharge are each rounded to whole cents *first*, and only then are the rounded components added together. The system never sums raw products and rounds once at the end.
- **Integer allocation with no rounding.** The drilling proceeds waterfall distributes an already-integer amount across buckets by subtraction, so no rounding occurs there; the buckets sum to the input exactly.

### 2.8. Optimistic Concurrency Control on Plan Adjustment

Adjusting a rental's plan or auto-pay settings is guarded by optimistic concurrency control. The adjust-plan request must include `expected_rental_version`, carrying the `version` of the target `Rental` that the client last observed. Before applying the change, the server compares that value to the rental's current `version`. If they differ — because a prior adjustment, a billing escalation, or a cure cascade has already advanced the version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no field is modified. This prevents a writer from overwriting a plan it has not observed. On success, the adjustment updates the requested fields and increments `version` by one. No other endpoint accepts a version field; only plan adjustment is version-gated.

### 2.9. Segregation of Duties and Dual Control

Two independent safeguards ensure that no single individual can both request and consummate a sensitive action.

**Segregation of duties on drilling.** A `DrillingOrder` records `requested_by_ref` (the `X-User-ID` that created it). Approval must be performed by a *different* operator: if the approving `X-User-ID` equals `requested_by_ref`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a successful approval the approver's `X-User-ID` is stored as `approved_by_ref`.

**Dual control on physical access.** Logging an `AccessEvent` requires two distinct people: the `primary_accessor_ref` who physically accesses the box and the `dual_control_officer_ref` who supervises. The supervising officer must differ from the accessor, and the `witness_count` — the number of controlling parties present — must be at least the required number of witnesses (see §3.7). A violation is rejected with `ERR_DUAL_CONTROL_REQUIRED`.

## 3. Business Logic & Workflows

### 3.1. Vault Infrastructure: Branches, Box Types, and Boxes

A `VaultAdmin` builds out the physical estate. A **branch** is created with a display `name`, a short `code` unique across branches, and a `viewing_room_capacity` — the number of private viewing rooms (at least 1) available for concurrent access appointments. A branch opens in `OPEN` status; a `CLOSED` branch blocks new boxes and appointments. Branches may be listed and filtered by `status`.

A **box type** captures a size class and its economics: `size_class` is one of `SMALL`, `MEDIUM`, `LARGE`, or `JUMBO`; `annual_rate_cents` is the yearly rental charge for that size (strictly positive); and `height_mm`, `width_mm`, and `depth_mm` record the interior dimensions. Box types may be filtered by `size_class`.

A physical **box** is placed in a branch by supplying its `branch_id`, its `box_type_id`, and a `box_number` (its physical label, unique within the branch). A new box starts `AVAILABLE`. Over its life a box moves through `AVAILABLE`, `RESERVED`, `RENTED`, `DELINQUENT`, `DRILL_PENDING`, `DRILLED`, and `OUT_OF_SERVICE`, almost always as a cascade from a rental or drilling order rather than by direct command. Two direct commands do exist, both `VaultAdmin`-only: taking an `AVAILABLE` box out of service moves it to `OUT_OF_SERVICE` (rejected with `ERR_BOX_NOT_AVAILABLE` if it is not `AVAILABLE`); and returning a `DRILLED` box to service moves it back to `AVAILABLE`, permitted only when the box is `DRILLED` and no active rental still references it. Boxes may be listed and filtered by `branch_id`, `box_type_id`, and `status`.

### 3.2. Renter Onboarding and KYC

Registering a **renter** — an action shared by `VaultAdmin` and `BillingClerk` — captures the renter's `full_name`, an `email` unique across renters, a `gov_id_ref` pointing to a government-ID document on file, and a `date_of_birth` as an ISO date. A new renter begins with `kyc_status` of `PENDING`, `standing` of `GOOD`, and `is_deceased` false. Renters may be listed and filtered by `kyc_status` and `standing`.

A `ComplianceOfficer` records the identity decision. Recording a decision on a `PENDING` renter either advances `kyc_status` to `VERIFIED` or, when the decision is a rejection, to `REJECTED`; the endpoint accepts an optional `decision` field to distinguish the two outcomes, and `REJECTED` is terminal. The decision is only valid while the renter is still `PENDING`.

The `standing` field is not part of the KYC lifecycle; it is a separate flag driven by compliance cases (§3.10). A renter is set to `FROZEN` while an active `HOLD` compliance case exists and returns to `GOOD` when no `HOLD` case remains open. The `is_deceased` flag is set true only when a beneficiary access grant is activated with a death certificate (§3.7).

### 3.3. The Rental Lifecycle: Creation, Activation, and Plan Adjustment

A **rental** binds a box to a renter. Creation (shared by `VaultAdmin` and `BillingClerk`) takes the `box_id` and `renter_id`, plus optional terms: `plan_term_months` (the lease length in months, at least 1, defaulting to 12), `autopay_enabled` (default false), `autopay_source_ref` (a stored payment instrument, default null), `insurance_rider_enabled` (default false), and `declared_contents_value_cents` (the renter-declared blanket contents value for the insurance rider, default 0). At creation the rental enters `PENDING`, and `annual_rate_cents` is snapshotted from the chosen box type so that later rate changes to the box type never disturb an existing lease.

Activation (shared by `VaultAdmin` and `BillingClerk`) is the gate that turns a `PENDING` rental into a live one, and it enforces three preconditions in this order. First, the renter's `kyc_status` must be `VERIFIED`, else `ERR_KYC_NOT_VERIFIED`. Second, the renter's `standing` must be `GOOD` with no open `HOLD` compliance case, else `ERR_COMPLIANCE_HOLD`. Third, the target box must be `AVAILABLE`, else `ERR_BOX_NOT_AVAILABLE`. When all three hold, the rental transitions to `ACTIVE`, its `start_date` is set from the logical clock, the box cascades from `AVAILABLE` to `RENTED`, and the first invoice for the term is issued (base rent plus insurance rider plus precious-metal surcharge, per §3.4), after which the rental's `balance_due_cents` is recomputed.

Adjusting a rental's plan is a `VaultAdmin`-only, version-gated operation (§2.8). It may change `plan_term_months`, `autopay_enabled`, and `autopay_source_ref`, and it requires `expected_rental_version`. A successful adjustment increments the rental's `version`.

Across its life a rental occupies one of `PENDING`, `ACTIVE`, `PAST_DUE`, `DELINQUENT`, `SURRENDER_PENDING`, `CLOSED`, or `ABANDONED`; `CLOSED` and `ABANDONED` are terminal. The middle states are cyclic — a rental that falls to `PAST_DUE` or `DELINQUENT` cures back to `ACTIVE` when its balance clears. Rentals may be listed and filtered by `box_id`, `renter_id`, and `status`. The system also tracks `paid_through_date` (the latest `period_end` fully covered by cleared payments) and `delinquent_since` (the timestamp the rental first entered `DELINQUENT`, cleared back to null on cure).

### 3.4. Billing: Invoices, Charges, and the Late-Fee Cycle

An **invoice** covers a billing period for a rental and is either issued automatically at activation or issued manually (by `BillingClerk` or `VaultAdmin`) for a period defined by `rental_id`, `period_start`, and `period_end`. Every invoice starts `OPEN` and may reach `PAID`, `VOID`, or `WRITTEN_OFF`. It records `issued_on` from the logical clock and a `due_date` equal to `issued_on` advanced by the standard invoice due window of 30 days after issuance. Invoices may be filtered by `rental_id` and `status`.

The invoice's monetary fields are computed, never supplied. `base_rent_cents` is the annual rate scaled to the period; for a full-term first invoice on a twelve-month plan, the base rent equals the rental's snapshotted `annual_rate_cents` in full. `insurance_rider_cents` is the rider charge: when the rental's `insurance_rider_enabled` is true, it is the declared contents value multiplied by the insurance rider annual rate of 150 basis points (that is, 1.50% of `declared_contents_value_cents` per year) divided by 10,000, rounded half-up to whole cents; when the rider is off, it is zero. `precious_metal_surcharge_cents` is the sum, over every non-`RELEASED` inventory item on the rental whose `category` is `PRECIOUS_METAL`, of that item's declared value multiplied by the precious-metal surcharge annual rate of 50 basis points (0.50% of `declared_value_cents` per year) divided by 10,000 — with each item's surcharge rounded half-up to whole cents *before* the items are summed. `late_fee_cents` accrues through the billing cycle (below) and defaults to zero. `total_cents` is the sum of `base_rent_cents`, `insurance_rider_cents`, `precious_metal_surcharge_cents`, and `late_fee_cents`. As payments clear against it, `amount_paid_cents` records the cleared amount applied to that invoice.

A rental's `balance_due_cents` is, at all times, the sum of `total_cents` over the rental's `OPEN` invoices minus the sum of `applied_cents` over the rental's `CLEARED` payments. `VOID`, `WRITTEN_OFF`, and `PAID` invoices are excluded from the first sum — `PAID` invoices are fully offset and would otherwise be double-counted. This balance is recomputed on every invoice issue, payment clear or reverse, and invoice void or write-off.

Running the **billing cycle** (a `VaultAdmin` utility) walks the `OPEN` invoices whose `due_date` has passed and accrues late fees, then escalates rental and box status per the logical clock; it returns the `issued_invoice_ids` and `escalated_rental_ids` it touched. The late fee for an invoice is computed as follows. Let the days past due be the whole number of days from the invoice's `due_date` to the clock's current date (floored). If that is zero or negative, the rate is zero and the late fee is zero. If it is at most 30, the rate is 0.05; if it is at most 60, the rate is 0.10; otherwise the rate is 0.15. A size multiplier is drawn from the box's size class — 1.00 for `SMALL`, 1.25 for `MEDIUM`, 1.50 for `LARGE`, and 2.00 for `JUMBO`. The outstanding amount is the invoice's `total_cents` minus its `amount_paid_cents`. The raw fee is the outstanding amount times the rate times the size multiplier; when the rate is nonzero, the late fee is that raw fee rounded half-up to whole cents and then clamped to lie between a minimum of 2,500 cents and a maximum of 25,000 cents.

An `OPEN` invoice may be **voided** by a `VaultAdmin`, but only when it has no applied payments — an invoice with `amount_paid_cents` greater than zero cannot be voided and yields `ERR_INVOICE_HAS_PAYMENTS`; voiding sets it to `VOID` and recomputes the rental balance. An `OPEN` invoice may also be **written off** by a `VaultAdmin`, moving it to `WRITTEN_OFF` and recomputing the balance. When a cleared payment fully covers an `OPEN` invoice (its `amount_paid_cents` reaches or exceeds `total_cents`), that invoice transitions to `PAID`.

The billing cycle also drives the delinquency escalations. When an `ACTIVE` rental has an `OPEN` invoice whose due date has passed and a positive balance, it moves to `PAST_DUE`. When the maximum days-past-due across its open invoices reaches the delinquency grace period of 15 days, it moves from `PAST_DUE` to `DELINQUENT`, stamps `delinquent_since` from the clock, and cascades its box from `RENTED` to `DELINQUENT`.

### 3.5. Payments: Intake, Clearing, Reversal, and Cure

A **payment** is created (by `BillingClerk` or `Renter`) against a `rental_id`, with an `amount_cents` strictly greater than zero and a `method` of `AUTOPAY`, `CARD`, `CASH`, `CHECK`, or `WIRE`. It may name a specific `invoice_id`; if that field is omitted, the payment auto-applies to the oldest `OPEN` invoice on the rental. A new payment is `INITIATED` and carries `applied_cents` of zero. Payments may be filtered by `rental_id` and `invoice_id`.

Clearing an `INITIATED` payment (by `BillingClerk` or `VaultAdmin`) is where money moves. The payment's amount is allocated as `applied_cents` to the target invoice, or to the oldest `OPEN` invoices in turn, increasing each invoice's `amount_paid_cents`; any invoice thereby fully covered flips to `PAID`; the rental's `balance_due_cents` is reduced by the applied amount; and `cleared_on` is stamped from the clock as the status becomes `CLEARED`. If, after applying, the balance reaches zero and the rental is `PAST_DUE` or `DELINQUENT`, the cure cascade fires: the rental returns to `ACTIVE`, `delinquent_since` is cleared to null, and — for a rental leaving `DELINQUENT` — the box cascades from `DELINQUENT` back to `RENTED`.

An `INITIATED` payment may instead be marked **failed** (by `BillingClerk` or `VaultAdmin`), moving it to `FAILED` with no ledger effect. A `CLEARED` payment may be **reversed** by a `VaultAdmin`: the previously applied amount is removed from its invoices, any invoice that had gone `PAID` reverts to `OPEN`, and the rental's `balance_due_cents` is increased back by the applied amount. This is a compensating action — the net receivable is restored exactly to what it was before the payment cleared. `FAILED` and `REVERSED` are terminal payment states.

### 3.6. Surrender and Closure: The Two-Stage Refund

A renter who no longer wants a box surrenders it, and the refund is computed twice — provisionally at request and finally at close — on deliberately different bases.

Requesting surrender (by `Renter` or `VaultAdmin`) is permitted only on an `ACTIVE` rental, else `ERR_INVALID_STATE`. It moves the rental to `SURRENDER_PENDING`, stamps `surrender_requested_at` from the clock, and computes `provisional_refund_cents` on a **whole-month** basis. For this provisional figure, take the monthly rate — the snapshotted `annual_rate_cents` divided by 12, rounded half-up to whole cents — and the days elapsed since `start_date` (a floored whole-day count against the clock). Round the days elapsed up to a whole number of months by dividing by the approximate 30-day month and taking the ceiling. The provisional refund is the greater of zero and (`plan_term_months` minus that whole-month count), multiplied by the monthly rate.

Closing a `SURRENDER_PENDING` rental (by `VaultAdmin`) requires two gates: the rental's `balance_due_cents` must be zero, else `ERR_OUTSTANDING_BALANCE`; and there must be no appointment in `BOOKED` or `CHECKED_IN`, else `ERR_APPOINTMENT_ACTIVE`. On success the rental moves to `CLOSED` and `final_refund_cents` is computed on an **exact-day** basis for full-term (twelve-month) rentals: the unused days are the greater of zero and (365 minus the days elapsed since `start_date`); the gross refund is the annual rate times those unused days divided by 365, rounded half-up to whole cents; and the final refund is the greater of zero and the gross minus any outstanding (unpaid) late fees on the rental. Closing also cascades: the box returns to `AVAILABLE`, every `ACTIVE` or `SUSPENDED` access grant on the rental is `REVOKED`, and every non-`RELEASED` inventory item on the rental is `RELEASED`.

### 3.7. Access: Grants, Appointments, and Dual-Control Events

**Access grants.** A rental's primary renter may extend access to others through an **access grant** (created by `Renter` or `VaultAdmin`), supplying the `rental_id`, a `grant_type` of `CO_RENTER`, `DEPUTY`, or `BENEFICIARY`, and the `grantee_name`, with optional `grantee_renter_id` (null when the grantee is an external, non-registered person), `grantee_gov_id_ref`, and `dual_control_required` (whether this grantee's access needs a supervising officer, default true). At creation the grant is `PENDING`, and `requires_death_certificate` is computed as true exactly when the grant type is `BENEFICIARY`. Grants may be filtered by `rental_id`, `grantee_renter_id`, and `status`.

Activating a grant (by `ComplianceOfficer` or `VaultAdmin`) requires the rental to be in `ACTIVE`, `PAST_DUE`, or `DELINQUENT`, else `ERR_INVALID_STATE`. For a `BENEFICIARY` grant, a `death_certificate_ref` must be supplied at activation, else `ERR_DEATH_CERTIFICATE_REQUIRED`; on success that reference is stored on `death_certificate_ref` and the underlying renter's `is_deceased` flag is set true. Activation moves the grant to `ACTIVE`. An active grant may be suspended (to `SUSPENDED`) and later resumed (back to `ACTIVE`) by `VaultAdmin` or `ComplianceOfficer`, forming a suspend/resume cycle. A grant may be revoked (by `Renter` or `VaultAdmin`) from `ACTIVE`, `SUSPENDED`, or `PENDING`, moving it to `REVOKED`. `REVOKED` and `EXERCISED` are terminal.

**Appointments.** Booking a vault-access **appointment** (by `Renter` or `VaultOfficer`) takes the `box_id`, the `rental_id`, the window's `scheduled_start` and `scheduled_end` (a half-open interval that includes the start and excludes the end), and an optional `grant_id` — present when access is exercised via a grant rather than by the primary renter. The server denormalizes the box's branch onto the appointment as `branch_id` for capacity checks. A new appointment is `BOOKED` and may reach `CHECKED_IN`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`. Appointments may be filtered by `box_id`, `rental_id`, `branch_id`, `grant_id`, and `status`.

Booking enforces, in order: the window must be well-formed and future — `scheduled_end` strictly after `scheduled_start`, and `scheduled_start` at or after the clock's current instant — else `ERR_APPOINTMENT_IN_PAST`; the window must not overlap another `BOOKED` or `CHECKED_IN` appointment on the same box (half-open comparison), else `ERR_APPOINTMENT_OVERLAP`; the branch's viewing rooms must not be oversubscribed, else `ERR_ROOM_CAPACITY_EXCEEDED`; and if a `grant_id` is given, that grant must belong to the same rental, else `ERR_GRANT_RENTAL_MISMATCH`. The room-capacity test is a buffered aggregate: for the candidate window, count the existing appointments at the same branch in `BOOKED` or `CHECKED_IN` whose window, widened by a 30-minute cleanup buffer on each side, intersects the candidate window; if that count plus one would exceed the branch's `viewing_room_capacity`, booking is refused.

Checking in an appointment (by `VaultOfficer`) has two gates evaluated safety-first: the renter must have no open `HOLD` compliance case, else `ERR_COMPLIANCE_HOLD`; and the rental must be `ACTIVE` or `PAST_DUE`, else `ERR_RENTAL_NOT_ACCESSIBLE`. Check-in itself is not clock-gated — the window is enforced at booking, not at check-in. A checked-in appointment is completed to `COMPLETED` by a `VaultOfficer`. A `BOOKED` appointment may be cancelled (by `Renter` or `VaultOfficer`), which frees the box's time window, or marked a no-show (by `VaultOfficer`) — the latter only once the clock has reached or passed `scheduled_end`.

**Dual-control events.** Physical entry is recorded as an append-only `AccessEvent` (logged by `VaultOfficer`) referencing the `appointment_id`, `box_id`, and `rental_id`, with an `event_type` of `ENTRY` or `EXIT`, a `primary_accessor_ref`, a `dual_control_officer_ref`, and a `witness_count` of at least 1. The event's `occurred_at` is stamped from the logical clock. Dual control requires the officer to differ from the accessor and the witness count to be at least the required two witnesses; a `witness_count` of exactly 2 passes while a count of 1 fails, and any violation yields `ERR_DUAL_CONTROL_REQUIRED`. Access events may be filtered by `appointment_id`, `box_id`, and `rental_id`.

### 3.8. Inventory and Precious-Metal Storage

Renters catalogue what they store as **inventory items** (declared by `Renter` or `VaultOfficer`), giving the `rental_id`, a `description`, a `category` of `PRECIOUS_METAL`, `JEWELRY`, `DOCUMENT`, or `OTHER`, and a `declared_value_cents` strictly greater than zero. When the category is `PRECIOUS_METAL`, three further fields are required: `metal_type` (`GOLD`, `SILVER`, or `PLATINUM`), `weight_grams`, and `purity` (a fineness greater than 0 and at most 1); for other categories these default to null. A new item is `DECLARED`. Items may be filtered by `rental_id` and `status`.

Valuation has two bases. The **declared basis** uses `declared_value_cents` verbatim; it drives the storage surcharge in §3.4 and routine reporting. The **appraised basis** is independent of the declared value: it is the item's `weight_grams` times its `purity` times the spot price per gram, rounded half-up to whole cents. Appraising an item (by `VaultOfficer` or `ComplianceOfficer`) moves a `DECLARED` item to `APPRAISED` and sets `appraised_value_cents`; the request supplies the `spot_price_per_gram_cents` used for the appraised-basis computation (and may alternatively carry an `appraised_value_cents` directly). Insuring an `APPRAISED` item (by `BillingClerk` or `VaultAdmin`) moves it to `INSURED`, with the appraised value serving as the coverage cap. Items reach the terminal `RELEASED` state through the rental close or abandonment cascade, from any of `DECLARED`, `APPRAISED`, or `INSURED`.

### 3.9. Drilling, Abandonment, and the Proceeds Waterfall

When a box must be forced open, a `VaultAdmin` opens a **drilling order** against a `box_id` and `rental_id` with a `reason` of `ABANDONMENT`, `DELINQUENCY`, `LOST_KEY`, or `COURT_ORDER`, and an optional `drilling_fee_cents` (default 15,000). The creating operator is recorded as `requested_by_ref`. For `ABANDONMENT` and `DELINQUENCY` reasons, drilling is only eligible when the box's rental is `DELINQUENT` and past the abandonment window; a request that fails this eligibility yields `ERR_DRILL_NOT_ELIGIBLE`. A new order is `REQUESTED`, and orders may be filtered by `box_id`, `rental_id`, and `status`.

The order then proceeds through a segregated approval chain. A `ComplianceOfficer` approves a `REQUESTED` order — but only if their `X-User-ID` differs from `requested_by_ref` (else `ERR_SEGREGATION_OF_DUTIES`) — moving it to `APPROVED` and recording `approved_by_ref`. A `VaultAdmin` schedules an `APPROVED` order by supplying `scheduled_at`, moving it to `SCHEDULED` and cascading the box from `DELINQUENT` to `DRILL_PENDING`. A `VaultAdmin` completes a `SCHEDULED` order, optionally supplying `proceeds_cents` (the gross realized, e.g., from a contents sale), which triggers the deepest cascade in the system: the order moves to `DRILLED` and stamps `drilled_at`; the proceeds waterfall is computed; the box moves from `DRILL_PENDING` to `DRILLED`; the (delinquent) rental moves to `ABANDONED`; and every `ACTIVE` or `SUSPENDED` access grant on that rental is `REVOKED`. A drilling order may be cancelled (by `VaultAdmin` or `ComplianceOfficer`) from `REQUESTED`, `APPROVED`, or `SCHEDULED`; cancelling from `REQUESTED` or `APPROVED` leaves the box untouched, while cancelling a `SCHEDULED` order restores the box from `DRILL_PENDING` back to `DELINQUENT`. `DRILLED` and `CANCELLED` are terminal.

The **proceeds waterfall** fills four buckets in a fixed priority order from a running remainder that starts at `proceeds_cents`. First, `proceeds_to_arrears_cents` takes the lesser of the remainder and the rental's arrears (its `balance_due_cents` — outstanding rent plus accrued late fees at completion), and the remainder is reduced accordingly. Next, `proceeds_to_drilling_cents` takes the lesser of the remainder and the order's `drilling_fee_cents`. Next, `proceeds_to_admin_cents` takes the lesser of the remainder and the fixed administrative fee of 5,000 cents. Finally, `proceeds_to_escrow_cents` receives whatever remainder is left, held for the renter or the state. The four buckets always sum to the input proceeds exactly; because these are integer allocations, no rounding is applied.

A separate abandonment path exists even without a drill: if a `DELINQUENT` rental's box reaches `DRILLED`, the rental is driven to `ABANDONED` and its `ACTIVE` or `SUSPENDED` grants are revoked — this is the same terminal outcome reached through completion above.

### 3.10. Compliance Cases and Holds

A `ComplianceOfficer` opens a **compliance case** against a `renter_id`, optionally linked to a specific `rental_id`, with a `case_type` of `KYC`, `SANCTIONS`, `SAR`, or `CTR` and a `severity` of `STANDARD` or `HOLD` (default `STANDARD`). The case's `opened_on` is stamped from the clock, and a new case is `OPEN`. Opening a `HOLD`-severity case freezes the renter — it sets the renter's `standing` to `FROZEN`, which blocks rental activation and physical access for that renter. Cases may be filtered by `renter_id`, `rental_id`, and `status`.

A case may be escalated from `OPEN` to `ESCALATED` by a `ComplianceOfficer`. A case may be cleared from either `OPEN` or `ESCALATED`, which stamps `resolved_on`, moves it to `CLEARED`, and — provided no other `HOLD` case remains open for that renter — restores the renter's `standing` to `GOOD`. `CLEARED` and `CLOSED` are the terminal case states. The presence of an open `HOLD` case is the single fact behind every `ERR_COMPLIANCE_HOLD` rejection: it blocks rental activation (§3.3) and appointment check-in (§3.7) alike.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; state transitions and other modifications to an existing resource return `200 OK`. The two system utilities return `200 OK`. Reconstruct each endpoint's request body, side effects, and computed responses from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vault/branches` | Create a branch | VaultAdmin |
| GET | `/vault/branches/{id}` | Get a branch | Any |
| GET | `/vault/branches` | List branches | Any |
| POST | `/vault/box-types` | Create a box size type | VaultAdmin |
| GET | `/vault/box-types/{id}` | Get a box type | Any |
| GET | `/vault/box-types` | List box types | Any |
| POST | `/vault/boxes` | Create a physical box | VaultAdmin |
| GET | `/vault/boxes/{id}` | Get a box | Any |
| GET | `/vault/boxes` | List/filter boxes | Any |
| POST | `/vault/boxes/{id}/decommission` | Take an AVAILABLE box out of service | VaultAdmin |
| POST | `/vault/boxes/{id}/return-to-service` | Return a DRILLED box to AVAILABLE | VaultAdmin |
| POST | `/vault/renters` | Register a renter | VaultAdmin, BillingClerk |
| GET | `/vault/renters/{id}` | Get a renter | Any |
| GET | `/vault/renters` | List/filter renters | Any |
| POST | `/vault/renters/{id}/verify-kyc` | Record KYC decision | ComplianceOfficer |
| POST | `/vault/rentals` | Create a rental (PENDING) | VaultAdmin, BillingClerk |
| GET | `/vault/rentals/{id}` | Get a rental | Any |
| GET | `/vault/rentals` | List/filter rentals | Any |
| POST | `/vault/rentals/{id}/activate` | Activate a rental | VaultAdmin, BillingClerk |
| POST | `/vault/rentals/{id}/adjust-plan` | Adjust plan/autopay (OCC-guarded) | VaultAdmin |
| POST | `/vault/rentals/{id}/request-surrender` | Request surrender | Renter, VaultAdmin |
| POST | `/vault/rentals/{id}/close` | Close a surrendered rental | VaultAdmin |
| POST | `/vault/invoices` | Manually issue an invoice for a rental period | BillingClerk, VaultAdmin |
| GET | `/vault/invoices/{id}` | Get an invoice | Any |
| GET | `/vault/invoices` | List/filter invoices | Any |
| POST | `/vault/invoices/{id}/void` | Void an unpaid invoice | VaultAdmin |
| POST | `/vault/invoices/{id}/write-off` | Write off an invoice | VaultAdmin |
| POST | `/vault/payments` | Create a payment | BillingClerk, Renter |
| GET | `/vault/payments/{id}` | Get a payment | Any |
| GET | `/vault/payments` | List/filter payments | Any |
| POST | `/vault/payments/{id}/clear` | Clear a payment (apply to invoices) | BillingClerk, VaultAdmin |
| POST | `/vault/payments/{id}/fail` | Mark a payment failed | BillingClerk, VaultAdmin |
| POST | `/vault/payments/{id}/reverse` | Reverse a cleared payment | VaultAdmin |
| POST | `/vault/access-grants` | Create an access grant | Renter, VaultAdmin |
| GET | `/vault/access-grants/{id}` | Get an access grant | Any |
| GET | `/vault/access-grants` | List/filter access grants | Any |
| POST | `/vault/access-grants/{id}/activate` | Activate a grant | ComplianceOfficer, VaultAdmin |
| POST | `/vault/access-grants/{id}/suspend` | Suspend an active grant | VaultAdmin, ComplianceOfficer |
| POST | `/vault/access-grants/{id}/resume` | Resume a suspended grant | VaultAdmin, ComplianceOfficer |
| POST | `/vault/access-grants/{id}/revoke` | Revoke a grant | Renter, VaultAdmin |
| POST | `/vault/access-appointments` | Book a vault access appointment | Renter, VaultOfficer |
| GET | `/vault/access-appointments/{id}` | Get an appointment | Any |
| GET | `/vault/access-appointments` | List/filter appointments | Any |
| POST | `/vault/access-appointments/{id}/check-in` | Check in an appointment | VaultOfficer |
| POST | `/vault/access-appointments/{id}/complete` | Complete an appointment | VaultOfficer |
| POST | `/vault/access-appointments/{id}/cancel` | Cancel a booked appointment | Renter, VaultOfficer |
| POST | `/vault/access-appointments/{id}/no-show` | Mark a no-show | VaultOfficer |
| POST | `/vault/access-events` | Log a dual-control access event | VaultOfficer |
| GET | `/vault/access-events/{id}` | Get an access event | Any |
| GET | `/vault/access-events` | List/filter access events | Any |
| POST | `/vault/inventory-items` | Declare a stored inventory item | Renter, VaultOfficer |
| GET | `/vault/inventory-items/{id}` | Get an inventory item | Any |
| GET | `/vault/inventory-items` | List/filter inventory items | Any |
| POST | `/vault/inventory-items/{id}/appraise` | Appraise an item | VaultOfficer, ComplianceOfficer |
| POST | `/vault/inventory-items/{id}/insure` | Mark an appraised item insured | BillingClerk, VaultAdmin |
| POST | `/vault/drilling-orders` | Request a drilling/abandonment order | VaultAdmin |
| GET | `/vault/drilling-orders/{id}` | Get a drilling order | Any |
| GET | `/vault/drilling-orders` | List/filter drilling orders | Any |
| POST | `/vault/drilling-orders/{id}/approve` | Approve a drilling order (SoD) | ComplianceOfficer |
| POST | `/vault/drilling-orders/{id}/schedule` | Schedule drilling | VaultAdmin |
| POST | `/vault/drilling-orders/{id}/complete` | Complete drilling (cascade + waterfall) | VaultAdmin |
| POST | `/vault/drilling-orders/{id}/cancel` | Cancel a drilling order | VaultAdmin, ComplianceOfficer |
| POST | `/vault/compliance-cases` | Open a compliance case | ComplianceOfficer |
| GET | `/vault/compliance-cases/{id}` | Get a compliance case | Any |
| GET | `/vault/compliance-cases` | List/filter compliance cases | Any |
| POST | `/vault/compliance-cases/{id}/escalate` | Escalate a compliance case | ComplianceOfficer |
| POST | `/vault/compliance-cases/{id}/clear` | Clear a compliance case | ComplianceOfficer |
| POST | `/vault/_clock/set_current_utc` | Set the server logical clock | VaultAdmin |
| POST | `/vault/_billing/run_cycle` | Run the billing cycle (accrue late fees, escalate delinquency) | VaultAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BOX_NOT_AVAILABLE` | 409 |
| `ERR_RENTAL_NOT_ACCESSIBLE` | 409 |
| `ERR_KYC_NOT_VERIFIED` | 409 |
| `ERR_COMPLIANCE_HOLD` | 409 |
| `ERR_DUAL_CONTROL_REQUIRED` | 409 |
| `ERR_APPOINTMENT_IN_PAST` | 409 |
| `ERR_APPOINTMENT_OVERLAP` | 409 |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 409 |
| `ERR_APPOINTMENT_ACTIVE` | 409 |
| `ERR_GRANT_RENTAL_MISMATCH` | 409 |
| `ERR_DEATH_CERTIFICATE_REQUIRED` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_DRILL_NOT_ELIGIBLE` | 409 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |

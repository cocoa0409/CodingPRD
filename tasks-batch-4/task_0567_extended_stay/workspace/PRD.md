# Extended-Stay & Corporate Housing API — Product Requirements Document

## 1. Introduction

This document specifies the Extended-Stay & Corporate Housing API, the operational backbone for a furnished-unit rental business in the mold of Sonder or Oakwood. The platform manages long-term stays — thirty nights and longer — in furnished apartments, where the commercial model differs sharply from nightly hotel booking: rent is quoted monthly, utilities and one-time cleaning are folded into the bill, and stays that cross the thirty-day line become exempt from transient occupancy tax. Because the same units are frequently leased in bulk to corporate tenants who rotate their own employees through them, the system must reconcile three distinct actors: the property operator who owns the physical inventory, the corporate administrator who manages a roster and a block of committed units, and the resident employee who actually occupies a unit.

The API governs the full arc of a stay — from booking a reservation against a rate plan, through check-in and the provisional invoice it generates, through optional mid-stay housekeeping and any damage assessed against the security deposit, to departure, final proration, turnover, and settlement. Several concerns are intertwined and must be handled with exactness: a master lease may be renegotiated concurrently and must guard against stale writes; a departure cascades through invoice finalization, unit turnover, and deposit reconciliation; and every monetary figure is carried in integer cents to avoid rounding drift. This document is the single authoritative description of those behaviors.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. If either header is absent, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `PropertyManager`, `CorporateAdmin`, and `Employee`.

- When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The `PropertyManager` is the property operator; the server does not compare this identifier to any entity's `id`. This role owns the physical inventory and operational surface: units, rate plans, corporate account onboarding, the master-lease lifecycle, stay check-in and turnover, housekeeping completion, damage assessment and charging, and invoicing.
- When `X-User-Role` is `CorporateAdmin`, `X-User-ID` is the `id` of the acting `CorporateAccount`. Ownership checks on any resource that references a `CorporateAccount` compare the resource's `corporate_account_id` to `X-User-ID`. A `CorporateAdmin` administers a single corporate account — its employee roster, its master leases, and stays booked against them.
- When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`. Ownership checks on a `Stay` compare the stay's `employee_id` to `X-User-ID`; ownership checks on housekeeping visits and damage charges resolve through the `stay_id` those resources carry back to the owning stay. An `Employee` is a corporate resident who acts only on their own stay.

When an entity-backed actor (`CorporateAdmin` or `Employee`) targets a resource they do not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). This ownership check is distinct from the role-permission check: `ERR_UNAUTHORIZED` means the role may never perform this operation, while `ERR_FORBIDDEN` means the role may perform it in general but not against this particular resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 to 100, or an `offset` below 0, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system carries a standard set of system-managed fields. The `id` is a server-minted UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation to the resource. The `version` field is an integer that begins at 1 and increments by exactly 1 on every mutation of the resource. All entities in this API — corporate accounts, rate plans, units, master leases, employees, stays, housekeeping visits, damage charges, invoices, and turnovers — carry all four fields.

Whenever the server recomputes a derived field on a resource (for example, a stay's `deposit_refundable_cents` or a master lease's `units_free`), that recomputation counts as a mutation of the resource: `updated_at` is refreshed and `version` is incremented.

### 2.5. Monetary Values and Precision

All monetary amounts in this system are carried as integers in cents; the field-name suffix `_cents` marks every such value. Wherever a calculation produces a fractional cent — most commonly when prorating a monthly rate across a partial month, or when applying a tax rate expressed in basis points — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up, away from zero). Rounding is applied at the points specified in the calculation rules of §3; where a subtotal is assembled from several independently rounded line items, each line is rounded first and the rounded lines are then summed, rather than summing exact values and rounding once at the end.

### 2.6. Optimistic Concurrency on Master-Lease Renegotiation

Renegotiating a master lease is guarded by optimistic concurrency control on the lease's `version`. A renegotiation request must carry `expected_master_lease_version`, a required field whose value is the `version` of the target `MasterLease` that the client last observed. Before applying the new rate, the server compares `expected_master_lease_version` against the lease's current `version`. If they differ — because an intervening activate, suspend, resume, or earlier renegotiate has advanced the lease's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made. This prevents a client from superseding a negotiated rate on the basis of a stale view of the lease. No other endpoint accepts or requires a version field; renegotiation is the only optimistic-concurrency-guarded operation in the system.

### 2.7. Cascading State Changes and Consistency

Several operations mutate more than one resource in a single logical step, and the system guarantees that every dependent effect lands atomically with its trigger.

Departure is the deepest cascade. Recording a stay's departure finalizes that stay's invoice, drives the occupied unit into turnover, and creates the turnover record — three coupled effects described in detail in §3.6. Each affected resource is independently mutated, so each has its own `updated_at` refreshed and its own `version` incremented.

The deposit ledger is the second cascade point. Charging or reversing a damage charge changes that charge's status, recomputes the owning stay's deposit balances, and — when the stay's invoice has already been finalized — recomputes the settlement figures on that invoice. Every touched resource's `updated_at` and `version` advance accordingly.

Because these cascades cross aggregate boundaries, the system applies them immediately and consistently: at no point is a unit left occupied by a departed stay, nor a finalized invoice left disagreeing with its stay's charged-damage total.

### 2.8. Resource Resolution and Validation Ordering

Entities in this system are peers linked by foreign keys; collections are addressed as top-level paths and children are discovered by filtering lists, not by nested ownership paths. When a request names resources — a path identifier and any foreign keys in the body — the server resolves them left to right and rejects the first one that does not exist with `ERR_NOT_FOUND` (HTTP 404).

Every request is evaluated through a fixed cascade of checks, and the first check that fails determines the response. The order is:

1. Authentication: both headers present and `X-User-Role` a declared role, else `ERR_UNAUTHENTICATED` (401).
2. Authorization: the role is permitted to invoke this endpoint, else `ERR_UNAUTHORIZED` (403).
3. Existence: all path and referenced foreign-key resources exist (resolved left to right), else `ERR_NOT_FOUND` (404).
4. Ownership: for a `CorporateAdmin`- or `Employee`-scoped write, the acting entity owns the target, else `ERR_FORBIDDEN` (403).
5. Body shape: required fields present, enum fields within their declared sets, dates parseable, pagination within range. A malformed body yields `ERR_VALIDATION` (400); an enum field carrying a value outside its declared set (for example, a `visit_type` other than `STANDARD` or `DEEP`) yields `ERR_INVALID_ENUM` (422).
6. State: the target resource is in a state that admits the requested transition, else `ERR_INVALID_STATE` (409).

Business-specific checks (unit availability, master-lease status, stay status, temporal conflicts, date sanity, minimum term, capacity, deposit sufficiency, and optimistic concurrency) follow the six generic checks above and are described alongside the workflows they guard in §3. Their relative priority, where two can apply to the same request, is: unit availability at check-in first, then master-lease-active, then stay-active, then the unit occupancy conflict, then employee double-booking, then date sanity, then minimum term, then master-lease capacity, then deposit-overdraw, and finally the renegotiation stale-version check.

### 2.9. The Logical Clock

The system operates against a logical clock rather than wall-clock time, so that time-dependent behavior (nights elapsed, tax thresholds, proration) is deterministic and test-drivable. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, every read returns precisely this default — never the real wall-clock time. An operator capability lets a `PropertyManager` advance the logical clock to a supplied instant by submitting a `to_iso8601` value; subsequent time-dependent computations use the new clock reading.

## 3. Business Logic & Workflows

### 3.1. Inventory, Rate Plans, Corporate Accounts, and Rosters

The foundational catalogue is maintained by the `PropertyManager`. A **corporate account** is onboarded with a `company_name` (the corporate tenant's legal name) and a `billing_email` (the recipient of its invoices). A **rate plan** captures the pricing snapshot a stay will draw on: a human `name`, the furnished-unit `monthly_rate_cents` (the monthly rent, at least zero), a flat `utility_monthly_cents` charged per month (at least zero), a one-time `cleaning_fee_cents` applied once per stay at turnover (at least zero), and an `occupancy_tax_rate_bps` giving the transient-occupancy tax rate in basis points, where 1200 basis points denotes twelve percent and the value must lie between 0 and 10000 inclusive.

A **unit** is a furnished apartment added to inventory with a `name` (its label, such as "Apt 4B"), a `property_name` (the building it sits in), and a `bedrooms` count (at least zero). Every unit is created in `AVAILABLE` status and moves through the cycle `AVAILABLE` → `OCCUPIED` → `TURNOVER` → `AVAILABLE` as stays come and go; its `status` is one of `AVAILABLE`, `OCCUPIED`, or `TURNOVER`.

The employee roster belongs to the corporate side. A `CorporateAdmin` adds an **employee** to a roster by supplying the `corporate_account_id` of the account they administer, the employee's `full_name`, and their `email`. Because this is an ownership-scoped write, the `corporate_account_id` in the body must match the admin's own `X-User-ID`, or the request is refused with `ERR_FORBIDDEN`. Employees and master leases belonging to an account are discovered by filtering their respective collections on `corporate_account_id`.

### 3.2. The Master Lease: Lifecycle and Committed Capacity

A **master lease** binds a corporate account to a block of furnished units at a negotiated rate. A `PropertyManager` creates one by supplying the `corporate_account_id` of the tenant, the `committed_units` count (the number of simultaneous units the account is entitled to, at least 1), the `negotiated_monthly_rate_cents` (at least zero), and the lease window as `start_date` and `end_date` in ISO 8601 UTC. A newly created lease begins in `DRAFT` status with `version` at 1, `units_consumed` at 0, and `units_free` equal to `committed_units`.

The lease's `status` follows the loop `DRAFT` → `ACTIVE` → `SUSPENDED` → `ACTIVE`. Activating a `DRAFT` lease moves it to `ACTIVE`; suspending an `ACTIVE` lease moves it to `SUSPENDED`; resuming a `SUSPENDED` lease returns it to `ACTIVE`. Each of these three transitions increments the lease's `version` by 1. A transition attempted from the wrong starting status — activating a lease that is not `DRAFT`, suspending one that is not `ACTIVE`, or resuming one that is not `SUSPENDED` — is rejected with `ERR_INVALID_STATE`.

Renegotiation supersedes the lease's monthly rate: it replaces `negotiated_monthly_rate_cents` with a new value and increments `version` by 1. Renegotiation may be performed by a `PropertyManager` or by the owning `CorporateAdmin`, and it is the sole optimistic-concurrency-guarded operation: the request must carry `expected_master_lease_version` matching the lease's current `version`, failing which it is rejected with `ERR_STALE_VERSION` as described in §2.6.

Committed capacity is a live count, not a stored counter. At any moment, `units_consumed` equals the number of stays on the lease whose `status` is either `RESERVED` or `ACTIVE`, and `units_free` equals `committed_units` minus `units_consumed`, floored at zero so it is never negative. The conservation identity `committed_units = units_consumed + units_free` therefore always holds. These figures are re-derived whenever a stay on the lease is booked, cancelled, or checked in, and are reported when the lease is read.

### 3.3. Booking a Stay

A **stay** is the central operational record. It is booked by a `PropertyManager` or a `CorporateAdmin` and enters `RESERVED` status. The booking body names the `unit_id` to occupy and the `rate_plan_id` that pins its pricing, the intended occupancy window as `move_in` (the inclusive interval start) and `planned_move_out` (the exclusive interval end) in ISO 8601 UTC, and the `deposit_held_cents` — the security deposit collected up front (at least zero). Corporate stays additionally supply a `master_lease_id` and an `employee_id`; retail (non-corporate) stays omit both, leaving them null. At creation the server computes `planned_nights`, sets `deposit_charged_cents` to 0 and `deposit_refundable_cents` equal to `deposit_held_cents`, and — for a corporate stay — re-derives the master lease's `units_consumed` and `units_free`.

A stay's `status` is one of `RESERVED`, `ACTIVE`, `COMPLETED`, `COMPLETED_EARLY`, or `CANCELLED`. The `planned_nights` figure is the whole number of 24-hour days between `move_in` and `planned_move_out` — the calendar-date difference of the two UTC midnights. The `billable_nights` figure is computed only at departure, as the whole number of days between `move_in` and `actual_move_out`; until then it is null, as is `actual_move_out` itself.

Booking is subject to a sequence of business checks, applied in this order after the generic checks of §2.8:

- **Master-lease active.** When a `master_lease_id` is supplied, the referenced master lease must be `ACTIVE`; otherwise the booking is rejected with `ERR_MASTER_LEASE_NOT_ACTIVE`.
- **Unit occupancy separation.** The new occupancy window must be kept clear of every non-cancelled stay already on the same unit by a turnover buffer of at least `TURNOVER_BUFFER_DAYS`, which is one day. Two windows that overlap, and two windows that merely touch end-to-start (the new stay beginning on the very day a prior stay ends), are both rejected with `ERR_UNIT_TIME_CONFLICT`: for a unit, adjacency is forbidden and at least one full day of separation is required.
- **Employee double-booking.** When an `employee_id` is supplied, the new half-open window `[move_in, planned_move_out)` must not overlap any non-cancelled stay of the same employee. Unlike the unit rule, adjacency is allowed here and no buffer is imposed: two of the employee's windows that merely touch end-to-start are permitted, but any true overlap is rejected with `ERR_EMPLOYEE_DOUBLE_BOOKED`.
- **Date sanity.** `planned_move_out` must be strictly later than `move_in`; a window that ends on or before it starts is rejected with `ERR_INVALID_DATE_RANGE`.
- **Minimum term.** `planned_nights` must be at least `MIN_LEASE_TERM_DAYS`, which is 30 nights. A shorter reservation is rejected with `ERR_MIN_TERM_NOT_MET`. This is the thirty-day floor that distinguishes extended-stay leasing from nightly booking.
- **Committed capacity.** For a corporate stay, accepting the booking must not push the master lease's `units_consumed` above its `committed_units`. A booking that would exceed the committed block is rejected with `ERR_MASTER_LEASE_CAP_EXCEEDED`.

A `RESERVED` stay may be cancelled by a `PropertyManager` or the owning `CorporateAdmin`, moving it to `CANCELLED`. Cancellation applies only to a stay still in `RESERVED`; from any other status it is rejected with `ERR_INVALID_STATE`. On cancellation, any provisional invoice already attached to the stay is left in `DRAFT` and is no longer billable, and — because the stay leaves the `RESERVED`/`ACTIVE` set — the master lease's `units_consumed` is re-derived downward, releasing the committed unit back to `units_free`.

Booking check-in aside, note that future bookings against an occupied unit are permitted: the unit availability requirement bites only at check-in time, not at booking time, provided the turnover-buffer separation above is respected.

### 3.4. Check-In and the Provisional Invoice

Checking in is a `PropertyManager` action that activates a reserved stay. It is admissible only when the stay is `RESERVED`, the referenced unit is currently `AVAILABLE`, and — if the stay carries a `master_lease_id` — that lease is `ACTIVE`. A stay that is not `RESERVED` yields `ERR_INVALID_STATE`; a unit that is not `AVAILABLE` at this moment yields `ERR_UNIT_NOT_AVAILABLE`; a master lease that is not `ACTIVE` yields `ERR_MASTER_LEASE_NOT_ACTIVE`.

On a successful check-in three effects land together: the stay advances `RESERVED` → `ACTIVE`, the unit advances `AVAILABLE` → `OCCUPIED`, and a **provisional invoice** is created for the stay in `DRAFT` status. The provisional invoice is computed against `planned_nights` — it projects the full committed term before any actual departure or damages are known.

An invoice's `invoice_kind` is `PROVISIONAL` while the stay is in progress and `FINAL` once the stay departs. Its `nights_billed` equals `planned_nights` while `PROVISIONAL` and `billable_nights` once `FINAL`. The invoice carries the computed pricing fields — `rate_subtotal_cents`, `cleaning_fee_cents`, `occupancy_tax_cents`, `amount_due_cents`, `damage_total_cents`, `total_settlement_cents`, and `deposit_refund_cents` — and a `status` of `DRAFT`, `ISSUED`, or `PAID`. Each field's derivation is given in §3.6 and §3.8.

### 3.5. Mid-Stay Housekeeping

During an active stay, housekeeping visits may be scheduled by a `PropertyManager` or by the resident `Employee`. A **housekeeping visit** names the `stay_id` it services, a `scheduled_date` (the calendar date of the visit, in ISO 8601 UTC), and an optional `visit_type` that is either `STANDARD` or `DEEP` and defaults to `STANDARD`. A visit may be scheduled only while its stay is `ACTIVE`; scheduling against a stay in any other status is rejected with `ERR_STAY_NOT_ACTIVE`.

A visit's `status` is `SCHEDULED`, `COMPLETED`, or `CANCELLED`. A `PropertyManager` marks a scheduled visit `COMPLETED`; either a `PropertyManager` or the resident `Employee` may cancel a scheduled visit, moving it to `CANCELLED`. Both transitions require the visit to be `SCHEDULED` and are otherwise rejected with `ERR_INVALID_STATE`. Housekeeping visits belonging to a stay are found by filtering the visit collection on `stay_id`.

### 3.6. Departure, Proration, and Turnover

Departure is recorded by a `PropertyManager` or the resident `Employee` and supplies a single field, `actual_move_out`. It is admissible only when the stay is `ACTIVE` and `actual_move_out` is on or after `move_in`; a stay that is not `ACTIVE` yields `ERR_INVALID_STATE`, and an `actual_move_out` earlier than `move_in` yields `ERR_INVALID_DATE_RANGE`. On departure the server sets `actual_move_out`, computes `billable_nights` as the whole number of days between `move_in` and `actual_move_out`, and branches on how that compares to the plan:

- When `actual_move_out` is on or after `planned_move_out`, the stay completes normally, advancing `ACTIVE` → `COMPLETED`.
- When `actual_move_out` is earlier than `planned_move_out`, the guest has left early: the stay advances `ACTIVE` → `COMPLETED_EARLY`, and `billable_nights` reflects the shortened, prorated term.

In both branches the same downstream cascade fires with equal force. The stay's provisional invoice is finalized: its `invoice_kind` becomes `FINAL`, its `nights_billed` becomes `billable_nights`, its totals are recomputed on that actual night count, and its `status` advances `DRAFT` → `ISSUED`. The occupied unit advances `OCCUPIED` → `TURNOVER`. And a **turnover** record is created in `SCHEDULED` status, capturing the `unit_id` being turned over, the `stay_id` of the outgoing stay that triggered it, and a `scheduled_date` equal to that stay's `actual_move_out`. A turnover's `status` is either `SCHEDULED` or `COMPLETED`.

The finalized invoice re-bills the stay on its actual nights. The night-billing computation works from `nights_billed` — `planned_nights` for the provisional pass, `billable_nights` for the final pass. Let the number of full months be the integer quotient of `nights_billed` divided by `DAYS_PER_MONTH`, which is 30, and let the remainder be `nights_billed` modulo 30. The rate subtotal is then assembled from four line items, each rounded half-up to a whole cent independently before any addition:

1. Full-month rent: `monthly_rate_cents` multiplied by the number of full months.
2. Full-month utilities: `utility_monthly_cents` multiplied by the number of full months.
3. Partial-month rent: `monthly_rate_cents` multiplied by the remainder nights, divided by 30.
4. Partial-month utilities: `utility_monthly_cents` multiplied by the remainder nights, divided by 30.

The `rate_subtotal_cents` field is the sum of these four rounded line items. The order is pinned: round every line first, then add — never sum the exact values and round once at the end.

Turnover is closed by a `PropertyManager`, who marks a scheduled turnover `COMPLETED`; this is admissible only when the unit is in `TURNOVER` and its turnover record is `SCHEDULED`, and it drives the unit `TURNOVER` → `AVAILABLE` while advancing the turnover `SCHEDULED` → `COMPLETED`, closing the unit's occupancy cycle. Attempting to complete a turnover whose record is not `SCHEDULED` is rejected with `ERR_INVALID_STATE`. Turnovers are discovered by filtering the turnover collection on `unit_id` or `stay_id`.

### 3.7. Occupancy Tax and the Thirty-Day Exemption

Occupancy tax is computed on each invoice from the `occupancy_tax_rate_bps` of the stay's rate plan, but only rent and utilities are taxable — the cleaning fee is never taxed. The taxable base is therefore `rate_subtotal_cents`. The thirty-day exemption is the pivotal rule: when `nights_billed` is at least `TAX_EXEMPT_THRESHOLD_DAYS`, which is 30, the stay is tax-exempt and `occupancy_tax_cents` is forced to 0. Only when `nights_billed` is fewer than 30 — for instance a 29-night early departure — is tax charged, computed as `rate_subtotal_cents` multiplied by `occupancy_tax_rate_bps`, divided by 10000, and rounded half-up to a whole cent.

This means the tax outcome can flip between the provisional and final invoices. A stay booked for the minimum thirty-night term is provisioned tax-exempt; if the guest departs a night early and `billable_nights` falls to 29, the finalized invoice becomes taxable and `occupancy_tax_cents` is recomputed on the shortened base. Conversely, a stay whose actual nights remain at or above 30 stays exempt through finalization.

### 3.8. Damage Charges, the Deposit Ledger, and Settlement

Damage against a stay's deposit is assessed by a `PropertyManager`, who records a **damage charge** naming the `stay_id`, an `amount_cents` (strictly greater than zero), and a free-text `description`. A new charge enters `ASSESSED` status. A charge's `status` is one of `ASSESSED`, `DISPUTED`, `CHARGED`, or `WAIVED`. Damage charges belonging to a stay are found by filtering on `stay_id`.

The deposit ledger is a live aggregation over a stay's charges. At any moment, `deposit_charged_cents` equals the sum of `amount_cents` across that stay's damage charges whose `status` is `CHARGED`, and `deposit_refundable_cents` equals `deposit_held_cents` minus `deposit_charged_cents`, floored at zero so it is never negative. The conservation identity `deposit_held_cents = deposit_refundable_cents + deposit_charged_cents` always holds. Before any damage is charged, the refundable balance equals the full `deposit_held_cents` (the estimated refund); once damages resolve, it equals `deposit_held_cents` minus `deposit_charged_cents` (the final refund).

Charges move through a small state machine, and the two paths into `CHARGED` are treated identically:

- **From assessment.** A `PropertyManager` charges an `ASSESSED` damage, moving it `ASSESSED` → `CHARGED`. This is permitted only if `amount_cents` is at most the stay's current `deposit_refundable_cents`, so the charge would not overdraw the deposit; a charge that would overdraw is rejected with `ERR_DAMAGE_EXCEEDS_DEPOSIT`.
- **After a dispute is upheld.** A resident `Employee` may dispute an `ASSESSED` charge, moving it `ASSESSED` → `DISPUTED`. If the dispute is later upheld against the guest, a `PropertyManager` charges the `DISPUTED` damage, moving it `DISPUTED` → `CHARGED` under the very same deposit-sufficiency requirement and the same `ERR_DAMAGE_EXCEEDS_DEPOSIT` rejection.

In both charging paths the ledger cascades identically: the stay's `deposit_charged_cents` is increased by `amount_cents` and its `deposit_refundable_cents` is recomputed; and if the stay's invoice is already `FINAL`, the invoice's `damage_total_cents`, `total_settlement_cents`, and `deposit_refund_cents` are recomputed to match.

Waiving unwinds a charge, and its two source states are likewise symmetric:

- **Waiving a dispute in the guest's favor.** A `PropertyManager` waives a `DISPUTED` charge, moving it `DISPUTED` → `WAIVED`. Because a disputed charge was never applied to the ledger, no deposit figures change.
- **Reversing a prior charge.** A `PropertyManager` waives a `CHARGED` charge, moving it `CHARGED` → `WAIVED`. This reverses the earlier debit: the stay's `deposit_charged_cents` is decreased by `amount_cents` and `deposit_refundable_cents` is recomputed, restoring the conserved deposit; and if the invoice is `FINAL`, its `damage_total_cents`, `total_settlement_cents`, and `deposit_refund_cents` are recomputed.

The invoice settlement figures tie the whole picture together. The `amount_due_cents` is the rent obligation — `rate_subtotal_cents` plus `cleaning_fee_cents` (the one-time cleaning fee copied from the rate plan) plus `occupancy_tax_cents` — and deliberately excludes the deposit. The `damage_total_cents` mirrors the stay's `deposit_charged_cents` at settlement. The `total_settlement_cents` is everything the guest owes: `amount_due_cents` plus `damage_total_cents`. The `deposit_refund_cents` is `deposit_held_cents` minus `damage_total_cents`, floored at zero. On the provisional pass, `nights_billed` is `planned_nights` and `damage_total_cents` is 0, projecting the full committed term with no damages; on the final pass, `nights_billed` is `billable_nights` and charged damages are folded in.

An issued invoice is settled by a `PropertyManager` or the owning `CorporateAdmin`, advancing it `ISSUED` → `PAID`. Payment is admissible only for an `ISSUED` invoice and is otherwise rejected with `ERR_INVALID_STATE`. Invoices belonging to a stay are found by filtering the invoice collection on `stay_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state transition and every read — return `200 OK`. All request and response bodies use the envelope of §2.2; the request payloads, side effects, and computed responses for each endpoint are described in the workflows of §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PropertyManager |
| POST | `/corporate-accounts` | Onboard a corporate account | PropertyManager |
| GET | `/corporate-accounts/{id}` | Get a corporate account | PropertyManager, CorporateAdmin |
| POST | `/rate-plans` | Create a rate plan | PropertyManager |
| GET | `/rate-plans/{id}` | Get a rate plan | PropertyManager, CorporateAdmin |
| POST | `/units` | Add a furnished unit to inventory | PropertyManager |
| GET | `/units/{id}` | Get a unit | PropertyManager, CorporateAdmin |
| POST | `/master-leases` | Create a master lease | PropertyManager |
| GET | `/master-leases/{id}` | Get a master lease | PropertyManager, CorporateAdmin |
| GET | `/master-leases` | List master leases | PropertyManager, CorporateAdmin |
| POST | `/master-leases/{id}/activate` | Activate a DRAFT master lease | PropertyManager |
| POST | `/master-leases/{id}/suspend` | Suspend an ACTIVE master lease | PropertyManager |
| POST | `/master-leases/{id}/resume` | Resume a SUSPENDED master lease | PropertyManager |
| POST | `/master-leases/{id}/renegotiate` | Renegotiate the monthly rate (OCC-guarded) | PropertyManager, CorporateAdmin |
| POST | `/employees` | Add an employee to a roster | CorporateAdmin |
| GET | `/employees/{id}` | Get an employee | CorporateAdmin, PropertyManager |
| GET | `/employees` | List employees | CorporateAdmin, PropertyManager |
| POST | `/stays` | Book a stay | PropertyManager, CorporateAdmin |
| GET | `/stays/{id}` | Get a stay | PropertyManager, CorporateAdmin, Employee |
| GET | `/stays` | List stays | PropertyManager, CorporateAdmin |
| POST | `/stays/{id}/check-in` | Check in a reserved stay | PropertyManager |
| POST | `/stays/{id}/depart` | Record a departure | PropertyManager, Employee |
| POST | `/stays/{id}/cancel` | Cancel a reserved stay | PropertyManager, CorporateAdmin |
| POST | `/housekeeping-visits` | Schedule a mid-stay housekeeping visit | PropertyManager, Employee |
| GET | `/housekeeping-visits/{id}` | Get a housekeeping visit | PropertyManager, Employee |
| GET | `/housekeeping-visits` | List housekeeping visits | PropertyManager, Employee |
| POST | `/housekeeping-visits/{id}/complete` | Mark a housekeeping visit completed | PropertyManager |
| POST | `/housekeeping-visits/{id}/cancel` | Cancel a scheduled housekeeping visit | PropertyManager, Employee |
| POST | `/damage-charges` | Assess a damage against a stay's deposit | PropertyManager |
| GET | `/damage-charges/{id}` | Get a damage charge | PropertyManager, Employee |
| GET | `/damage-charges` | List damage charges | PropertyManager, Employee |
| POST | `/damage-charges/{id}/charge` | Charge an assessed or disputed damage | PropertyManager |
| POST | `/damage-charges/{id}/dispute` | Dispute an assessed damage | Employee |
| POST | `/damage-charges/{id}/waive` | Waive a disputed or charged damage | PropertyManager |
| GET | `/invoices/{id}` | Get an invoice | PropertyManager, CorporateAdmin |
| GET | `/invoices` | List invoices | PropertyManager, CorporateAdmin |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | PropertyManager, CorporateAdmin |
| GET | `/turnovers/{id}` | Get a turnover record | PropertyManager |
| GET | `/turnovers` | List turnovers | PropertyManager |
| POST | `/turnovers/{id}/complete` | Complete a turnover, returning the unit to AVAILABLE | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_MASTER_LEASE_NOT_ACTIVE` | 409 |
| `ERR_STAY_NOT_ACTIVE` | 409 |
| `ERR_UNIT_TIME_CONFLICT` | 409 |
| `ERR_EMPLOYEE_DOUBLE_BOOKED` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_MIN_TERM_NOT_MET` | 422 |
| `ERR_MASTER_LEASE_CAP_EXCEEDED` | 402 |
| `ERR_DAMAGE_EXCEEDS_DEPOSIT` | 402 |
| `ERR_STALE_VERSION` | 412 |

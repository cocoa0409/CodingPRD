# Weights & Measures Device Inspection API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Weights & Measures Device Inspection API, the system of record for a county/city legal-metrology program. The program registers the commercial locations that own weighing and measuring equipment, catalogs each device (a retail scale, a fuel pump, or a checkout scanner), and governs the field inspections that certify those devices as accurate and honestly priced. Every consequential event in that world — a passing accuracy test that lets a device be sealed, a failing test that condemns it and assesses a monetary penalty, a consumer complaint that forces a re-test, an annual registration fee, or the suspension of an establishment that has not paid what it owes — is expressed here as a state transition with precisely defined side effects.

The domain is fundamentally a compliance-and-audit workflow layered over a small ledger. Devices move through a cyclic lifecycle in which the same physical instrument can be sealed, later condemned after a failed re-test, repaired, and sealed again. Financial state (registration fees and penalties) accrues against the owning establishment and is the lever the program uses to compel payment: an establishment with an outstanding balance may be suspended, which cascades through its sealed devices. The API must therefore keep three things in continuous agreement — the status of each device, the ledger balance of each establishment, and the count of a location's currently sealed devices — while enforcing accuracy tolerances, scanner-audit thresholds, scheduling protections, and optimistic-concurrency guarantees against stale writes.

This specification is written for the engineers implementing the service. Section 2 fixes the system-wide contracts (authentication, response envelope, pagination, common properties, precision, concurrency, and consistency). Section 3 narrates the business workflows in domain terms. Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a header the server cannot validate, is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles, spelled precisely as follows: `ProgramAdmin`, `Inspector`, and `Establishment`.

- `ProgramAdmin` is the weights-and-measures program operator. This role registers establishments, inspectors, and devices; files and resolves complaints; waives penalties; suspends and reinstates establishments; and controls the test clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it against any entity's `id`.
- `Inspector` is a field inspector who conducts inspections, records readings and audit items, and finalizes results. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` entity; any ownership check on a resource that references an inspector compares that resource's inspector foreign key to `X-User-ID`.
- `Establishment` is the regulated business itself. When `X-User-Role` is `Establishment`, `X-User-ID` is the `id` of the acting `Establishment` entity; ownership checks on a resource that references an establishment compare that resource's establishment foreign key to `X-User-ID`. In particular, an establishment may pay only its own penalties and its own fee invoices; an attempt to pay a penalty or invoice belonging to another establishment is rejected with `ERR_OWNERSHIP_VIOLATION`.

Authorization for each endpoint is enumerated in Section 4. Read (GET) endpoints are generally available to all three roles; the mutating endpoints are restricted as that table specifies.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, and must be at least 1 and at most 100. An out-of-range or unparseable value is not rejected but silently coerced: a `limit` below 1 is clamped up to 1, a `limit` above 100 is clamped down to 100, and a missing, non-integer, or otherwise unparseable `limit` falls back to the default of 10. The `offset` parameter is the number of items to skip and defaults to 0; a negative, non-integer, or unparseable `offset` is coerced to 0.

Unless a specific workflow states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order; resources sharing an identical `created_at` — common because timestamps are minted from the logical clock of §2.9 — are ordered among themselves by actual creation sequence, earliest first.

Every list response includes the following fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system share a common set of system-managed properties:

- `id` — a server-minted UUID with no type prefix. It is generated by the server on creation and is immutable.
- `created_at` — the ISO 8601 UTC timestamp, with three fractional digits, marking when the resource was first created.
- `updated_at` — the ISO 8601 UTC timestamp of the resource's most recent modification; it is refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation of the resource. It is the basis for the optimistic-concurrency mechanism described in §2.6.

The following entities carry all four common properties: `Establishment`, `Inspector`, `Device`, `Inspection`, `Complaint`, `Seal`, `CondemnationOrder`, `Penalty`, and `FeeInvoice`. Two entities are exceptions: a `TestReading` and a `ScannerAuditItem` are append-only line items recorded under an inspection and carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field.

Whenever a resource's derived fields change as a side effect of some other operation — for example when an establishment's `balance_due_cents` or `sealed_device_count` is recomputed, or when a device's `status` changes — that reconciliation is itself a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Amounts, Counts, and Rounding

All monetary quantities in the system — registration fees, penalty amounts, prices, and ledger balances — are expressed as **whole integer cents**. Field names carrying money always end in `_cents`.

Wherever a calculation multiplies an integer amount of cents by a fractional factor (a proration factor, a penalty rate, or a repeat-offense multiplier), the result is rounded to a whole number of cents using the **round-half-up** rule (a value ending in exactly one-half cent rounds up to the next whole cent). Section 3 specifies, for each calculation, the exact order in which multiplication and rounding are applied; that order is authoritative and must not be rearranged. Count-valued fields such as `sealed_device_count`, and error counts derived during a scanner audit, are exact integers.

### 2.6. Optimistic Concurrency on Inspection Scheduling

Scheduling an inspection is guarded by optimistic concurrency control keyed on the target device. The request that schedules a new inspection must carry the field `expected_device_version`, and this field is required, not optional. Its value must equal the current `version` of the `Device` named in the request. If the two do not match — because some other writer has advanced the device's `version` since the client last read the device (for example, the device may have just been retired or condemned by another writer whose write already advanced the version) — the scheduling request is refused with `ERR_STALE_DEVICE_VERSION` and HTTP status 412. This prevents a client from scheduling against a device state it has not actually observed.

A successful scheduling call itself increments the device's `version` by one, reserving the device for the concurrency contract; a subsequent stale writer working from the earlier version will then be rejected. No other endpoint takes a device-version field; the concurrency guard applies only to inspection scheduling.

### 2.7. Nested Resource Retrieval and Validation Ordering

Several endpoints address resources nested under a parent — for example the readings and audit items recorded beneath an inspection. For any path that contains more than one resource identifier, the server validates existence left to right and rejects the request at the first identifier in the path that does not resolve, returning that identifier's specific not-found error before attempting to locate anything further to its right.

More generally, every mutating request is evaluated through a fixed ladder of checks, applied in this order so that earlier failures mask later ones:

1. Authentication — valid `X-User-ID` and `X-User-Role` headers, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role is permitted for this operation, else `ERR_UNAUTHORIZED` (403).
3. Body validity — required fields are present and enum values are legal; for inspection scheduling, `scheduled_end` must be strictly later than `scheduled_start`. A malformed body yields `ERR_VALIDATION` (400); a non-strictly-ordered inspection window yields `ERR_SCHEDULE_WINDOW_INVALID` (400).
4. Existence — every path identifier and every foreign key in the body resolves to a real resource, validated left to right, else the corresponding 404 (`ERR_ESTABLISHMENT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_PENALTY_NOT_FOUND`, `ERR_FEE_INVOICE_NOT_FOUND`, or the generic `ERR_NOT_FOUND` for a seal or condemnation order).
5. Ownership — where an acting establishment pays a penalty or invoice, it must own that resource, else `ERR_OWNERSHIP_VIOLATION` (403).
6. State legality — the target resource must be in a state that admits the requested transition (see §3), else the relevant 409 conflict error.

The scheduling endpoint layers three further checks after state legality; their relative order is given in §3.3.

### 2.8. Cascading Consistency: Establishment Balance and Sealed-Device Count

Two derived properties on every `Establishment` are maintained by the server and must never be set directly by a client.

The `balance_due_cents` of an establishment is the sum of the `amount_due_cents` of all of that establishment's fee invoices whose `status` is `DUE`, plus the sum of the `amount_cents` of all of that establishment's penalties whose `status` is `ASSESSED`. It is recomputed from scratch on every event that could change it: registering a device (which raises a fee invoice), a device failing an inspection (which assesses a penalty), and paying or waiving any invoice or penalty. Invoices that are `PAID` and penalties that are `PAID` or `WAIVED` do not contribute to the balance.

The `sealed_device_count` of an establishment is the number of that establishment's devices whose `status` is currently `SEALED`. It is recomputed on every device transition into or out of `SEALED` — whether from a passing inspection that seals a device, a failing re-test or retirement that voids a seal, or the suspension cascade described in §3.1.

### 2.9. The Logical Inspection Clock

The server keeps a single logical clock that supplies the "current" time for time-dependent logic — most importantly, the calendar month used to prorate a registration fee (§3.2). On startup the clock reads exactly `2026-03-01T00:00:00Z`; until an operator explicitly sets it, the clock stays at this default and never falls back to wall-clock time. A `ProgramAdmin` may advance the clock by supplying a target instant `to_iso8601` (an ISO 8601 UTC timestamp). All timestamps the server mints for `created_at` and `updated_at`, and the month that drives fee proration, are read from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Establishments and Program Sanctions

An establishment is the regulated business location that owns devices. A `ProgramAdmin` registers one by supplying its legal `name` and its inspection `jurisdiction` code (a county or city identifier). A newly registered establishment begins in `status` `ACTIVE`, with `balance_due_cents` of 0 and `sealed_device_count` of 0.

The program's principal lever against a non-paying business is suspension. A `ProgramAdmin` may move an establishment from `ACTIVE` to `SUSPENDED`, optionally noting a `reason`, but only as a non-payment sanction: suspension is permitted only when the establishment's `balance_due_cents` is greater than 0. An attempt to suspend an establishment that owes nothing is rejected with `ERR_SUSPEND_REQUIRES_BALANCE`. This positive-balance check is the only precondition the server enforces; it does not additionally verify that the establishment is currently `ACTIVE`. Suspension is not a bookkeeping-only change; it cascades through the establishment's equipment. Every device of that establishment whose `status` is `SEALED` is moved from `SEALED` to `OUT_OF_SERVICE`; for each such device its `ACTIVE` seal is moved from `ACTIVE` to `VOIDED`; and the establishment's `sealed_device_count` is then recomputed, dropping by the number of devices just taken out of service. The establishment's own `updated_at` is refreshed and its `version` increments by one.

Reinstatement is the reverse transition, from `SUSPENDED` back to `ACTIVE`, also performed by a `ProgramAdmin`. It is allowed only once the establishment has cleared what it owes: reinstatement requires `balance_due_cents` to be exactly 0, and a reinstatement attempted while any balance remains is rejected with `ERR_OUTSTANDING_BALANCE`. As with suspension, this zero-balance check is the only precondition enforced; the establishment's current status is not otherwise verified. Reinstatement restores the establishment to `ACTIVE` and refreshes its `updated_at` and `version`, but it does not un-void any seals or move devices back on its own: devices left in `OUT_OF_SERVICE` by the suspension cascade stay in `OUT_OF_SERVICE` until they are re-tested and pass.

A `ProgramAdmin` also creates inspectors. An inspector is described by a `full_name`, a `badge_number` (recorded as supplied; the server does not enforce that badge numbers are unique across inspectors), and an optional `region` label; when `region` is omitted it defaults to `UNASSIGNED`.

### 3.2. Registering Devices and the Registration Fee

A `ProgramAdmin` registers a device against an existing establishment by supplying the owning `establishment_id`, the `device_type`, the manufacturer `serial_number`, and optionally the `device_class`. The `device_type` is one of `SCALE`, `FUEL_PUMP`, or `SCANNER`. The `device_class` is the accuracy class that later selects the tolerance tier and is one of `CLASS_III` or `CLASS_IIIL`; when omitted it defaults to `CLASS_III`. A new device starts in `status` `REGISTERED`.

Registration immediately raises the annual registration fee as a `FeeInvoice`. The invoice records the owning `establishment_id` and the `device_id`, carries `fee_type` `REGISTRATION`, and starts in `status` `DUE`. Its `base_amount_cents` is the full annual base fee for the device's type before any proration: 12000 cents for a `SCALE`, 8000 cents for a `FUEL_PUMP`, and 15000 cents for a `SCANNER`.

The amount actually owed, `amount_due_cents`, is the base fee prorated by the calendar quarter in which the device is registered, using the month of the logical clock at the moment of registration. The quarter factor is 1.00 when the registration month is January, February, or March; 0.75 when it is April, May, or June; 0.50 when it is July, August, or September; and 0.25 when it is October, November, or December. The amount due is the base fee multiplied by this quarter factor, rounded half up to a whole number of cents. The boolean `proration_applied` is set to true whenever the applied quarter factor is less than 1.00 — that is, for any registration outside the first quarter — and false otherwise. Registering the device recomputes the owning establishment's `balance_due_cents` so that the new `DUE` invoice is reflected.

### 3.3. Scheduling an Inspection

An inspection is the unit of field work performed on one device by one inspector. Either an `Inspector` or a `ProgramAdmin` may schedule one. The scheduling payload names the `device_id` under inspection, the `inspector_id` assigned to it, the `inspection_type`, the inspection window bounds `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants), the concurrency guard `expected_device_version`, and, only for a complaint re-test, a `complaint_id`. The `inspection_type` is one of `ACCURACY_TEST`, `PRICE_VERIFICATION`, or `COMPLAINT_RETEST`. A scheduled inspection starts in `status` `SCHEDULED` with its `outcome` unset (null).

Beyond the universal ladder of §2.7, scheduling applies a sequence of scheduling-specific checks, evaluated in the following order so that an earlier rejection takes precedence over a later one:

1. **Body and window validity.** The window must be well-formed: `scheduled_end` strictly after `scheduled_start`, otherwise `ERR_SCHEDULE_WINDOW_INVALID`.
2. **Device testability.** The target device must be in a testable state — one of `REGISTERED`, `SEALED`, `CONDEMNED`, or `OUT_OF_SERVICE`. A device in the terminal `RETIRED` state cannot be scheduled and the request is rejected with `ERR_DEVICE_NOT_TESTABLE`.
3. **Stale-device concurrency.** The `expected_device_version` must match the device's current `version`, otherwise `ERR_STALE_DEVICE_VERSION` (412), exactly as described in §2.6.
4. **Complaint linkage.** When `inspection_type` is `COMPLAINT_RETEST`, the `complaint_id` is mandatory and must reference a `Complaint` that is currently in `status` `FILED` and whose own `device_id` equals the inspection's `device_id`; a missing or mismatched complaint is rejected with `ERR_COMPLAINT_REQUIRED`. For the other two inspection types `complaint_id` is left unset.
5. **Inspector schedule conflict.** The assigned inspector must not already hold another non-terminal inspection (one in `SCHEDULED` or `IN_PROGRESS`) whose window overlaps this one. Overlap is judged on the half-open interval from `scheduled_start` up to but not including `scheduled_end`: two inspections that merely touch, where one's end equals the other's start, do not conflict, whereas any genuine overlap is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`.
6. **Device re-test buffer.** The device itself must be rested between inspections. Taking each of the device's other non-terminal inspections as a closed window and expanding it by a 60-minute buffer on each side, none of those expanded windows may contain any point of the new window. In practice, a gap of less than 60 minutes between this inspection and another of the device's non-terminal inspections is a conflict and is rejected with `ERR_DEVICE_RETEST_BUFFER`, while a gap of 60 minutes or more is allowed.

A successful scheduling call increments the device's `version` by one, which both reserves the device and arms the concurrency guard of §2.6 against any writer still holding the previous version.

### 3.4. Conducting an Inspection: Starting and Recording Evidence

An `Inspector` begins field work by moving a scheduled inspection from `SCHEDULED` to `IN_PROGRESS`. An inspection that is not in `SCHEDULED` cannot be started, and such an attempt is rejected with `ERR_INSPECTION_NOT_IN_PROGRESS` (this state check precedes the device-testability check below). Starting is permitted only while the underlying device remains testable — its `status` must be one of `REGISTERED`, `SEALED`, `CONDEMNED`, or `OUT_OF_SERVICE`; a device that has since been retired blocks the start with `ERR_DEVICE_NOT_TESTABLE`. Starting refreshes the inspection's `updated_at` and increments its `version`.

While an inspection is `IN_PROGRESS`, the inspector records the evidence that will decide its outcome, and the kind of evidence depends on the inspection type. For an `ACCURACY_TEST` or a `COMPLAINT_RETEST`, the inspector records one or more **test readings**. Each `TestReading` belongs to its inspection via `inspection_id` and captures the certified `applied_load` placed on the device (in grams) and the `indicated_value` the device displayed (also in grams). The server derives `error_grams` for the reading as the absolute difference between the indicated value and the applied load. For a `PRICE_VERIFICATION`, the inspector instead records one or more **scanner audit items**. Each `ScannerAuditItem` belongs to its inspection via `inspection_id` and captures the scanned `item_sku`, the shelf `posted_price_cents`, and the `scanned_price_cents` the register actually rang up. The server derives `overcharge_cents` for the item as the amount by which the scanned price exceeds the posted price, or zero when the scanned price is not higher than the posted price (an undercharge never produces a negative overcharge).

Readings and audit items are append-only line items; they carry an `id` and `created_at` but no `updated_at` or `version`. They can be listed back for a given inspection.

### 3.5. Deciding an Accuracy Test: Tolerance Evaluation

When an accuracy test or complaint re-test is finalized, the server evaluates every one of the inspection's test readings against the applicable tolerance and the inspection passes only if every reading is within tolerance. Two things select the tolerance for a reading: the device's accuracy class and, crucially, the device's current status.

Each reading's tolerance starts from a **maintenance tolerance** chosen by the device's `device_class` and by the tier into which the reading's `applied_load` falls. For a `CLASS_III` device the maintenance tolerance is 6 grams when the applied load is 5000 grams or less, 12 grams when the load is greater than 5000 grams and up to and including 20000 grams, and 20 grams when the load is greater than 20000 grams. For a `CLASS_IIIL` device it is 10 grams when the applied load is 10000 grams or less, 20 grams when the load is greater than 10000 grams and up to and including 50000 grams, and 40 grams when the load is greater than 50000 grams.

The tolerance actually applied then depends on whether the device has ever been placed into service. For a brand-new, never-sealed device — one whose `status` is still `REGISTERED` — the stricter **acceptance tolerance** applies, equal to exactly half of the maintenance tolerance (the maintenance constants are all even, so the halving is exact). For a device already in service — one whose `status` is `SEALED`, `CONDEMNED`, or `OUT_OF_SERVICE` — the looser maintenance tolerance applies as-is. As a consequence, identical reading data can pass on an in-service device yet fail on a never-sealed one. A single reading passes when its `error_grams` is less than or equal to the applicable tolerance; equality is a pass. The inspection's computed outcome is `PASS` when every reading passes and `FAIL` when any reading exceeds its tolerance.

### 3.6. Deciding a Price Verification: Scanner Audit

When a price-verification inspection is finalized, the server evaluates the inspection's scanner audit items. It first counts the **mispriced items** — those where the `scanned_price_cents` differs from the `posted_price_cents` in either direction (whether the scanner overcharged or undercharged). The inspection's computed outcome is `FAIL` when the number of mispriced items is strictly greater than 2, and `PASS` otherwise (so exactly two mispriced items still passes). A price verification requires at least one audit item to be finalized at all; finalizing with fewer than one recorded item is rejected as insufficient sample (see §3.7).

### 3.7. Finalizing: Sealing, Condemnation, and Penalties

Finalization is the pivotal act of an inspection and is performed by an `Inspector`. It may be applied only to an inspection that is `IN_PROGRESS`; finalizing an inspection in any other state is rejected with `ERR_INSPECTION_NOT_IN_PROGRESS`. Before an outcome can be computed, the inspection must carry enough evidence: an `ACCURACY_TEST` or `COMPLAINT_RETEST` must have at least one recorded test reading, and finalizing one with none is rejected with `ERR_NO_READINGS`; a `PRICE_VERIFICATION` must have at least one recorded audit item, and finalizing one with none is rejected with `ERR_INSUFFICIENT_SAMPLE`. Both of these evidence failures carry HTTP status 422.

Once evidence is sufficient, the server computes the outcome by the rule matching the inspection type — the tolerance evaluation of §3.5 for accuracy and complaint re-tests, or the scanner audit of §3.6 for price verifications — and the finalize forks into one of two branches with sharply different side effects.

**Pass branch.** When the computed outcome is `PASS`, the inspection's `outcome` is set to `PASS` and the inspection moves from `IN_PROGRESS` to the terminal `PASSED`. The pass then drives the device to `SEALED`. Sealing requires the owning establishment to be `ACTIVE`; if the establishment is `SUSPENDED`, the pass cannot seal the device and finalization is rejected with `ERR_ESTABLISHMENT_SUSPENDED`. When sealing proceeds, the device transitions into `SEALED` — from `REGISTERED`, from `OUT_OF_SERVICE`, or cyclically from `CONDEMNED` after a repair-and-retest — and a new `Seal` is created in `status` `ACTIVE`, linking the `device_id` and the `inspection_id` and carrying a server-minted sequential `seal_number` — a string of the form `SEAL-000001`, zero-padded to six digits and incrementing by one for each seal issued across the whole system. The establishment's `sealed_device_count` increases by one. When the device was `CONDEMNED` before this pass, its outstanding condemnation order is also resolved: that `CondemnationOrder` moves from `ISSUED` to `LIFTED`.

**Fail branch.** When the computed outcome is `FAIL`, the inspection's `outcome` is set to `FAIL` and the inspection moves from `IN_PROGRESS` to the terminal `FAILED`. The fail drives the device to `CONDEMNED` — from `REGISTERED`, from `OUT_OF_SERVICE`, or from `SEALED`; a suspended establishment does not block condemnation. If the device was `SEALED` before this fail, its `ACTIVE` seal is moved to `VOIDED` and the establishment's `sealed_device_count` decreases by one. Condemnation then creates two records: a `CondemnationOrder` in `status` `ISSUED`, whose `reason` is a human-readable description derived from the failing `inspection_type`; and a `Penalty` in `status` `ASSESSED`. Creating the penalty recomputes the owning establishment's `balance_due_cents` so that the newly assessed amount is reflected.

The penalty records the liable `establishment_id`, the offending `device_id`, its computed `amount_cents`, and a `violation_type`. The violation type is derived from the failing inspection: a failing price verification records `PRICE_ERROR`; a failing accuracy or complaint re-test records `OUT_OF_TOLERANCE`; and a failing inspection performed on a device that was already `CONDEMNED` records `OPERATING_CONDEMNED`, reflecting a device found still operating under an outstanding condemnation.

**Penalty amount.** The assessed `amount_cents` combines a base component with a repeat-offense multiplier. The multiplier is keyed on the establishment's prior condemnation history: count the condemnation orders belonging to any device of this establishment whose `created_at` is strictly earlier than this new order's `created_at` (both `ISSUED` and `LIFTED` orders count toward the history). Because `created_at` is minted from the logical clock (§2.9) and two orders created at the same clock instant carry an identical `created_at`, ties on equal `created_at` are broken by actual creation order: an order created before this new order is treated as strictly earlier even when their `created_at` values are equal. In effect, every condemnation order of this establishment that already existed at the moment this new order was created counts toward the history. The multiplier is 1.0 when there are no prior condemnations, 1.5 when there are one or two prior condemnations, and 2.0 when there are three or more.

- For a `PRICE_ERROR` penalty, the amount is built from the failing inspection's audit items. Consider only the items whose `overcharge_cents` is greater than zero. For each such item, multiply its `overcharge_cents` by the penalty rate of 1.5 and round that product half up to whole cents. Sum these per-item rounded amounts to form a subtotal, then multiply the subtotal by the repeat-offense multiplier and round half up to whole cents. This order is authoritative and must not be rearranged: round each item first, then sum, then apply the multiplier, then round the final figure.
- For an `OUT_OF_TOLERANCE` or `OPERATING_CONDEMNED` penalty, the amount is a flat base multiplied by the repeat-offense multiplier and rounded half up to whole cents. The base is 5000 cents for `OUT_OF_TOLERANCE` and 20000 cents for `OPERATING_CONDEMNED`.

### 3.8. Retiring Devices and Handling Complaints

A `ProgramAdmin` may retire (decommission) a device, optionally noting a `reason`, moving it into the terminal `RETIRED` state from `REGISTERED`, `SEALED`, `CONDEMNED`, or `OUT_OF_SERVICE`. Retirement is blocked while the device has an inspection that is `IN_PROGRESS`: such an attempt is rejected with `ERR_DEVICE_HAS_ACTIVE_INSPECTION`. When the retired device was `SEALED`, its `ACTIVE` seal is moved to `VOIDED` and the establishment's `sealed_device_count` decreases by one. Retirement refreshes the device's `updated_at` and increments its `version`. Once `RETIRED`, a device is terminal and no longer testable: any later action that targets an already-retired device — a second retirement, or any state transition on it — is rejected with `ERR_DEVICE_RETIRED`, while an attempt to schedule or start an inspection against it fails with `ERR_DEVICE_NOT_TESTABLE` as described in §3.3 and §3.4.

Consumer complaints run on their own short lifecycle. A `ProgramAdmin` files a `Complaint` against a device by supplying the `device_id`, the `complainant_name`, and a free-text `description`; the complaint opens in `status` `FILED`. A filed complaint is the prerequisite that lets a `COMPLAINT_RETEST` inspection be scheduled (§3.3), and that re-test is how the program confirms or clears the grievance. A `ProgramAdmin` resolves a complaint by supplying a `disposition` of either `UPHELD` or `DISMISSED`. Only a complaint still in `FILED` may be resolved; resolving one already in `UPHELD` or `DISMISSED` is rejected with `ERR_INVALID_STATE`. Upholding a complaint moves it from `FILED` to `UPHELD`, but only once a re-test has actually confirmed the problem: the targeted device must be in `status` `CONDEMNED` at the time of resolution, and an attempt to uphold a complaint whose device is not condemned is rejected with `ERR_INVALID_STATE`. Dismissing a complaint moves it from `FILED` to `DISMISSED` with no state precondition. Either resolution refreshes the complaint's `updated_at` and increments its `version`.

Seals and condemnation orders are themselves readable and listable records, retrievable individually or filtered by their device or inspection, but they are never mutated directly by a client — their `status` changes only as the side effects narrated above.

### 3.9. Settling Balances: Paying and Waiving

The establishment's `balance_due_cents` is cleared by paying its fee invoices and its penalties, or by an administrative waiver of a penalty. Each settlement recomputes the balance immediately.

A due fee invoice is paid by the owning `Establishment` (or by a `ProgramAdmin` acting on its behalf). Payment moves the invoice from `DUE` to `PAID` and recomputes the establishment's `balance_due_cents`, removing that invoice's `amount_due_cents` from the total. An invoice that is not in `DUE` cannot be paid again and the attempt is rejected with `ERR_INVOICE_NOT_PAYABLE`. When the payer acts as an `Establishment`, it may pay only its own invoice; paying another establishment's invoice is rejected with `ERR_OWNERSHIP_VIOLATION`.

An assessed penalty is likewise paid by the owning `Establishment` (or a `ProgramAdmin`). Payment moves the penalty from `ASSESSED` to `PAID` and recomputes the establishment's `balance_due_cents`, removing that penalty's `amount_cents`. A penalty that is not in `ASSESSED` cannot be paid and the attempt is rejected with `ERR_PENALTY_NOT_PAYABLE`; an establishment paying a penalty it does not own is rejected with `ERR_OWNERSHIP_VIOLATION`. Separately, a `ProgramAdmin` may waive an assessed penalty, optionally noting a `reason`; a waiver moves the penalty from `ASSESSED` to `WAIVED` and likewise recomputes `balance_due_cents`, removing the waived `amount_cents` from the total. A penalty that is not in `ASSESSED` cannot be waived, and the attempt is rejected with `ERR_PENALTY_NOT_PAYABLE`. Because both paying and waiving drop a penalty out of `ASSESSED`, and paying drops an invoice out of `DUE`, each of these actions can be exactly what brings an establishment's balance to zero and makes it eligible for reinstatement under §3.1.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or a new line item under a parent return `201 Created`. Operations that modify an existing resource — state transitions, payments, waivers, and the clock control — return `200 OK`. The clock control endpoint also returns `200 OK`. The complete request and response semantics for each endpoint are given by the workflow narratives in Section 3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/establishments` | Register an establishment | ProgramAdmin |
| GET | `/establishments/{id}` | Get an establishment | ProgramAdmin, Establishment, Inspector |
| POST | `/establishments/{id}/suspend` | Suspend an establishment for non-payment; cascades to seal voiding | ProgramAdmin |
| POST | `/establishments/{id}/reinstate` | Reinstate a suspended establishment once its balance is clear | ProgramAdmin |
| POST | `/inspectors` | Create an inspector | ProgramAdmin |
| POST | `/devices` | Register a device; assesses the prorated registration fee | ProgramAdmin |
| GET | `/devices/{id}` | Get a device | ProgramAdmin, Establishment, Inspector |
| GET | `/devices` | List devices (filter by establishment or status) | ProgramAdmin, Establishment, Inspector |
| POST | `/devices/{id}/retire` | Retire (decommission) a device | ProgramAdmin |
| POST | `/inspections` | Schedule an inspection on a device (device-version guarded) | Inspector, ProgramAdmin |
| GET | `/inspections/{id}` | Get an inspection | ProgramAdmin, Inspector, Establishment |
| GET | `/inspections` | List inspections (filter by device, inspector, complaint, or status) | ProgramAdmin, Inspector, Establishment |
| POST | `/inspections/{id}/start` | Begin conducting a scheduled inspection | Inspector |
| POST | `/inspections/{id}/finalize` | Finalize an inspection; computes PASS/FAIL and drives the device cascade | Inspector |
| POST | `/inspections/{id}/test-readings` | Record an accuracy test reading | Inspector |
| GET | `/inspections/{id}/test-readings` | List test readings for an inspection | ProgramAdmin, Inspector, Establishment |
| POST | `/inspections/{id}/audit-items` | Record a scanner audit item | Inspector |
| GET | `/inspections/{id}/audit-items` | List audit items for an inspection | ProgramAdmin, Inspector, Establishment |
| POST | `/complaints` | File a consumer complaint against a device | ProgramAdmin |
| GET | `/complaints/{id}` | Get a complaint | ProgramAdmin, Inspector |
| GET | `/complaints` | List complaints (filter by device or status) | ProgramAdmin, Inspector |
| POST | `/complaints/{id}/resolve` | Resolve a complaint as UPHELD or DISMISSED | ProgramAdmin |
| GET | `/seals/{id}` | Get a seal | ProgramAdmin, Inspector, Establishment |
| GET | `/seals` | List seals (filter by device, inspection, or status) | ProgramAdmin, Inspector, Establishment |
| GET | `/condemnations/{id}` | Get a condemnation order | ProgramAdmin, Inspector, Establishment |
| GET | `/condemnations` | List condemnation orders (filter by device, inspection, or status) | ProgramAdmin, Inspector, Establishment |
| GET | `/penalties/{id}` | Get a penalty | ProgramAdmin, Establishment |
| GET | `/penalties` | List penalties (filter by establishment, device, or status) | ProgramAdmin, Establishment |
| POST | `/penalties/{id}/pay` | Pay an assessed penalty | Establishment, ProgramAdmin |
| POST | `/penalties/{id}/waive` | Waive an assessed penalty (administrative) | ProgramAdmin |
| GET | `/fee-invoices/{id}` | Get a fee invoice | ProgramAdmin, Establishment |
| GET | `/fee-invoices` | List fee invoices (filter by establishment, device, or status) | ProgramAdmin, Establishment |
| POST | `/fee-invoices/{id}/pay` | Pay a due registration fee invoice | Establishment, ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (ISO 8601 UTC) | ProgramAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is described in the relevant narrative of Sections 2 and 3; this catalogue lists only the error identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_SCHEDULE_WINDOW_INVALID` | 400 |
| `ERR_ESTABLISHMENT_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_PENALTY_NOT_FOUND` | 404 |
| `ERR_FEE_INVOICE_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEVICE_NOT_TESTABLE` | 409 |
| `ERR_DEVICE_RETIRED` | 409 |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 |
| `ERR_ESTABLISHMENT_SUSPENDED` | 409 |
| `ERR_PENALTY_NOT_PAYABLE` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_STALE_DEVICE_VERSION` | 412 |
| `ERR_COMPLAINT_REQUIRED` | 409 |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_DEVICE_RETEST_BUFFER` | 409 |
| `ERR_NO_READINGS` | 422 |
| `ERR_INSUFFICIENT_SAMPLE` | 422 |
| `ERR_DEVICE_HAS_ACTIVE_INSPECTION` | 409 |
| `ERR_SUSPEND_REQUIRES_BALANCE` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 409 |

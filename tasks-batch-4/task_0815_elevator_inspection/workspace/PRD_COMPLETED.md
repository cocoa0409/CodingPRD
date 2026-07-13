# Elevator & Conveyance Inspection API — Product Requirements Document

## 1. Introduction

Public-safety authorities that oversee elevators, escalators, and other conveyances carry a heavy administrative burden: every passenger elevator, freight elevator, escalator, moving walk, and dumbwaiter in their jurisdiction must be registered, inspected on a recurring cadence by a licensed inspector, and kept in good fiscal and certification standing before it may legally carry the public. This API backs the authority's system of record for that entire lifecycle — from the moment a building owner's device is registered and its registration fee billed, through annual and periodic inspection scheduling, licensed-inspector assignment, on-site inspection with deficiency capture, citation and fine handling, operating-certificate issuance and posting, emergency shutdown orders, and accident investigation.

The domain is deliberately compliance-driven and temporally aware. Time does not advance from a wall clock; it advances only when an operator moves a **logical clock** forward, so that inspection windows, fee due dates, certificate expiry, and penalty accrual can all be exercised deterministically. Several concerns cut across the whole system: money is tracked as a single conserved outstanding balance per device, safety events cascade automatically into out-of-service orders and certificate suspensions, and a strict segregation-of-duties rule keeps the inspector who routinely services a device from also leading its accident investigation. The sections that follow first fix the system-wide contracts (authentication, response envelope, pagination, concurrency, precision, and propagation) and then narrate the business workflows in which the individual fields, thresholds, and state transitions live.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The four roles, spelled exactly, are `Registrar`, `LicensedInspector`, `SafetyAdministrator`, and `BuildingOwner`.

- A `Registrar` is an inspection-authority clerk who maintains the registry: registering owners, inspectors, and devices; activating devices; scheduling, assigning, and cancelling inspections; raising fee and renewal invoices; and issuing operating certificates. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `SafetyAdministrator` provides safety oversight: issuing and lifting out-of-service orders, adjudicating contested citations, and launching accident investigations. When `X-User-Role` is `SafetyAdministrator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it as a matter of audit but does not compare it to any entity's `id`.
- A `LicensedInspector` is a field inspector who performs inspections, records and resolves deficiencies, and closes accident investigations. When `X-User-Role` is `LicensedInspector`, `X-User-ID` is the `id` of the acting `Inspector`; ownership checks compare a resource's inspector foreign key — the `assigned_inspector_id` of an `Inspection` or the `lead_investigator_id` of an `AccidentReport` — to `X-User-ID`.
- A `BuildingOwner` is a device owner who pays fees and citations, contests citations, posts certificates, and files accident reports on owned devices. When `X-User-Role` is `BuildingOwner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks compare the `owner_id` of the `Device` referenced by the target resource to `X-User-ID`.

When an entity-backed actor (`LicensedInspector` or `BuildingOwner`) is authenticated and permitted for the operation but is not the owner of the specific resource being acted upon, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to citation payment and contest, certificate posting, fee-invoice payment, inspection start and completion, and accident-investigation closure.

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

All list endpoints accept two optional pagination query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and has a minimum of 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

List responses carry the pagination bookkeeping in the `meta` object: `limit` and `offset` echo the effective values applied, `total_count` reports the total number of matching records across all pages, and `has_more` is true when additional records remain beyond the current page. Unless an endpoint states otherwise, list results are ordered by `created_at` ascending — oldest record first.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource is assigned a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Every entity in this system is a mutable, versioned resource: in addition to `id` and `created_at`, each also carries an `updated_at` timestamp (same format as `created_at`) and an integer `version`. The `version` starts at 1 when the resource is created and increments by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the current instant on each such mutation. When a side effect described in this document mutates a resource, the reader should understand that both its `version` bump and its `updated_at` refresh accompany the change even where not restated.

Time in this system is measured in **period indices** — integer months counted from a fixed earliest instant. A single logical clock holds the authority's notion of "now" as `current_period_index`. At server startup the clock reads 0, the fixed earliest instant, and it never consults wall-clock time. An operator moves the clock by supplying an absolute `to_period_index`, after which `current_period_index` equals that value; the capability is available to `Registrar` and `SafetyAdministrator` operators and exists so that inspection windows, due dates, expiries, and penalties can be exercised deterministically. Whenever a workflow below records "the current period" onto a field — a `performed_period`, an `issued_period`, a `paid_period`, a `lifted_period`, a `posted_period`, or an `issue_period` — it captures the clock's `current_period_index` at the moment the action is processed.

### 2.5. Optimistic Concurrency and Certificate Supersession

Issuing an operating certificate is the one write in this system guarded by optimistic concurrency control. Because issuance supersedes the device's prior active certificate and advances the device's `version`, a client must prove it is acting on the device state it last observed. The certificate-issuance request therefore requires a non-optional `expected_device_version` field carrying the client's last observed `version` of the target `Device`. If `expected_device_version` does not equal the device's current `version` — for example because another writer has issued a certificate or otherwise advanced the device since the client last read it — the request is rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412), preventing the client from superseding a certificate state it has not seen. No other endpoint accepts or requires a version field.

### 2.6. The Conserved Outstanding Balance Ledger

Each device carries a single conserved fiscal quantity, `outstanding_balance_cents`, that always equals the money the device currently owes. It is defined as an aggregation over two unpaid sets: the sum, over the device's citations whose status is `ISSUED` or `CONTESTED`, of each citation's `surcharged_amount_cents`, plus the sum, over the device's fee invoices whose status is `PENDING` or `OVERDUE`, of each invoice's `amount_cents`. The rounding order is pinned: each citation's surcharge is rounded to whole cents and persisted per citation as its `surcharged_amount_cents` first, and only then are the per-citation amounts summed. Rounding the summed total instead is explicitly not permitted, as it can yield a different figure. In practice the balance is maintained incrementally — every citation or fee-invoice status change that adds a charge to, or removes one from, those unpaid sets adjusts `outstanding_balance_cents` by exactly the amount that entered or left the set, so the running balance always agrees with the aggregation just described.

### 2.7. Monetary and Scoring Precision

All monetary amounts are integer cents; all risk scores are integer points. Wherever a calculation multiplies by a rate or factor, the result is rounded half up to a whole number ("round half up" meaning a value exactly halfway between two integers rounds to the larger). This applies to every fee, penalty, fine, surcharge, and risk-score computation described in §3. Interval and period computations (due dates, expiry periods, next-inspection dates) are already whole integers and need no rounding.

### 2.8. Out-of-Service Propagation and Certificate Suspension

Device operability, out-of-service orders, and certificate posting move together as one consistency unit. A device counts its currently active shutdowns in `active_oos_count`. When an out-of-service order becomes `ACTIVE` on a device — whether raised directly by a safety administrator or created automatically by a cascade — `active_oos_count` is incremented by 1, and if the device was `REGISTERED` or `ACTIVE` it transitions to `OUT_OF_SERVICE`; at the same moment the device's active certificate, if it is `ISSUED` or `POSTED`, transitions to `SUSPENDED`. When an active order is later lifted, `active_oos_count` is decremented by 1; if that decrement brings `active_oos_count` to 0, the device returns from `OUT_OF_SERVICE` to `ACTIVE`, and a certificate that had been suspended is restored — reinstated to `POSTED` if it had been `POSTED` before suspension, but `REVOKED` instead if it had only ever been `ISSUED` (never posted) before suspension. These propagations are the reason a single safety action can ripple across the device, its certificate, and its shutdown count in one step.

### 2.9. Validation Ordering and Nested-Path Resolution

When several checks could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is: (1) user-context header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permission for the operation per the access-control matrix (`ERR_INSUFFICIENT_PERMISSIONS`); (3) existence of every resource id named in the URL path, validated left to right so that a parent id is checked before any child, each missing id yielding the corresponding not-found error such as `ERR_DEVICE_NOT_FOUND`; (4) existence of every foreign-key id supplied in the request body — `owner_id`, `device_id`, `deficiency_id`, `source_inspection_id`, `assigned_inspector_id`, `lead_investigator_id`, and `citation_id` — again yielding the matching not-found error such as `ERR_OWNER_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_OOS_ORDER_NOT_FOUND`, `ERR_FEE_INVOICE_NOT_FOUND`, or `ERR_ACCIDENT_NOT_FOUND`; (5) resource-ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`); (6) optimistic-concurrency version match on certificate issuance (`ERR_STALE_DEVICE_VERSION`); (7) the target resource being in a state that permits the requested transition (`ERR_*_NOT_<STATE>`); and (8) onward, the operation-specific business rules described in §3. A malformed body — missing required field, unknown enum value, or a type mismatch — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Later checks never mask an earlier one: if a higher-priority condition fails, its error is returned before any lower-priority check runs.

## 3. Business Logic & Workflows

### 3.1. Registering Owners, Inspectors, and Devices

The registry is seeded by a `Registrar`. Registering a building or property owner captures the owner's `name` and `contact_email`. Registering a licensed inspector captures the inspector's `name`, `license_number`, the `license_expiry_period` (the period index up to and including which the license remains valid — an inspector is unexpired as long as `current_period_index` is at most the `license_expiry_period`), and the `certified_categories`, the subset of device categories the inspector is licensed to inspect. A freshly created inspector begins with an `active_assignment_count` of 0; this counter is a conserved quantity tracking how many of the inspector's inspections are currently `ASSIGNED` or `IN_PROGRESS`, and it rises and falls exactly with the assignment and completion events described later. Inspectors can be listed and narrowed by a single `certified_category` filter.

Registering a conveyance device records the owning `owner_id`, the device `category` — one of `PASSENGER_ELEVATOR`, `FREIGHT_ELEVATOR`, `ESCALATOR`, `MOVING_WALK`, or `DUMBWAITER` — a free-text `location_description`, and the `install_period` in which the device was installed. On registration the device is placed in `REGISTERED` status and its `risk_class` is computed from its `category` via the authority's fixed risk-class map, taking one of the values `HIGH`, `MEDIUM`, or `LOW`: a `PASSENGER_ELEVATOR` maps to `HIGH`, a `FREIGHT_ELEVATOR` to `MEDIUM`, an `ESCALATOR` to `HIGH`, a `MOVING_WALK` to `MEDIUM`, and a `DUMBWAITER` to `LOW`. This derived `risk_class` is what later drives the risk multiplier in both the citation-fine and the accident-risk-score calculations. Registration is also a billing event: the system automatically creates a `REGISTRATION` fee invoice for the device, in `PENDING` status, whose due date is the device's `install_period`, and immediately reflects that charge in the device's conserved `outstanding_balance_cents`. Several device attributes are computed rather than supplied and begin empty: `next_inspection_due_period` is null until the device's first passing inspection, `accident_risk_score` starts at 0, `current_certificate_id` is not stored but derived at read time as the `id` of the device's certificate whose effective status is currently `ISSUED` or `POSTED` (or null when the device has no such certificate) — so it is null until the first certificate is issued, moves to each newly issued certificate as issuance supersedes the prior one, and reverts to null while the current certificate is suspended, expired, revoked, or superseded, and `active_oos_count` starts at 0. A device may be fetched individually — its response reflects the live computed balance, risk score, and due period — or listed with optional filters on `owner_id`, `status`, and `category`.

### 3.2. Fees, Renewals, Penalties, and Payment

Beyond the automatic registration charge, a `Registrar` may raise additional invoices against a device by supplying the `device_id`, the invoice `type` — one of `REGISTRATION`, `ANNUAL_RENEWAL`, `REINSPECTION`, or `LATE_PENALTY` — and the `due_period`. A new invoice opens in `PENDING` status with a provisional `amount_cents`, and the charge is added to the device's `outstanding_balance_cents`. The provisional amount assumes on-time payment and equals the invoice's base fee: for a `REGISTRATION` invoice the base is a flat 10000 cents; for every other type the base is the renewal fee for the device's category — 30000 cents for a `PASSENGER_ELEVATOR`, 25000 cents for a `FREIGHT_ELEVATOR`, 40000 cents for an `ESCALATOR`, 35000 cents for a `MOVING_WALK`, and 15000 cents for a `DUMBWAITER`.

An unpaid invoice is reclassified from `PENDING` to `OVERDUE` at read time once the clock's `current_period_index` has moved strictly past the invoice's `due_period`; this reclassification is presentational and does not alter `amount_cents` on its own. Payment of a fee invoice is an owner action: the acting `BuildingOwner` must own the device that the invoice is for, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`, and the invoice must be either `PENDING` or `OVERDUE`, failing which the request is rejected with `ERR_INVOICE_NOT_PAYABLE`. On payment the amount is finalized: the number of months overdue is the payment period minus the due period whenever the `paid_period` is strictly greater than the `due_period`, and zero otherwise. A late penalty then accrues as the base fee multiplied by ten percent per whole month overdue, rounded half up, but the penalty is capped at the full base fee (equivalently, the penalty is the smaller of the accrued amount and one times the base). The finalized `amount_cents` is the base plus this penalty. Payment records the `paid_period` as the current period, moves the invoice to `PAID`, and removes the finalized amount from the device's `outstanding_balance_cents`. Invoices can be fetched individually or listed with optional filters on `device_id`, `status`, and `type`.

### 3.3. Activating and Decommissioning a Device

Before a newly registered device may carry inspections or certificates, a `Registrar` activates it, moving it from `REGISTERED` to `ACTIVE`. Activation has two guards: the device must currently be `REGISTERED`, or the request is rejected with `ERR_DEVICE_NOT_REGISTERED`; and the device's `REGISTRATION` fee invoice must already be `PAID`, or the request is rejected with `ERR_REGISTRATION_FEE_UNPAID` (HTTP 402). This ties the registry's fiscal gate directly to operability — a device with an unpaid registration fee cannot be activated.

Either a `Registrar` or a `SafetyAdministrator` may permanently decommission a device, moving it to the terminal `DECOMMISSIONED` status. Decommissioning is allowed only while the device is `REGISTERED`, `ACTIVE`, or `OUT_OF_SERVICE`; attempting it on an already-decommissioned device is rejected with `ERR_DEVICE_ALREADY_DECOMMISSIONED`. Decommissioning cascades to the device's pending inspection work: every inspection for that device still in `SCHEDULED` or `ASSIGNED` status is moved to `CANCELLED`, and for each one that was `ASSIGNED`, the previously assigned inspector's `active_assignment_count` is decremented by 1 to compensate the assignment it had taken. Unlike the standalone cancellation of §3.4, this decommission cascade leaves each cancelled inspection's `assigned_inspector_id` in place rather than clearing it to null.

### 3.4. Scheduling and Assigning Inspections

A `Registrar` schedules an inspection against a device by supplying the `device_id`, the inspection `type` — one of `ANNUAL`, `PERIODIC`, `REINSPECTION`, or `ACCIDENT_FOLLOWUP` — and the scheduling window as a `scheduled_start_period` (inclusive) and `scheduled_end_period` (exclusive), a half-open interval. A new inspection opens in `SCHEDULED` status with no `assigned_inspector_id` and a null `performed_period`. Inspections can be fetched individually or listed with optional filters on `device_id`, `assigned_inspector_id`, and `status`.

Assigning an inspection to an inspector is also a `Registrar` action and carries the `assigned_inspector_id` to be assigned. Assignment moves the inspection from `SCHEDULED` to `ASSIGNED` and must satisfy three conditions. First, the inspection must currently be `SCHEDULED`, or the request is rejected with `ERR_INSPECTION_NOT_SCHEDULED`. Second, the chosen inspector must be certified for the device's `category` (that category must appear in the inspector's `certified_categories`) and the inspector's license must be unexpired (`current_period_index` at most the inspector's `license_expiry_period`); otherwise the request is rejected with `ERR_INSPECTOR_NOT_CERTIFIED` (HTTP 403). Third, the assignment must not create a scheduling collision: taking the inspection's half-open window from `scheduled_start_period` up to `scheduled_end_period` and expanding it on each side by a fixed buffer of 1 period, the buffered window must not overlap the window of any other inspection of the same inspector that is currently `ASSIGNED` or `IN_PROGRESS`; an overlap is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`. Concretely, a candidate assignment conflicts with an existing `ASSIGNED` or `IN_PROGRESS` inspection of the same inspector exactly when the candidate's `scheduled_start_period` is strictly less than that existing inspection's `scheduled_end_period` plus 1, and that existing inspection's `scheduled_start_period` is strictly less than the candidate's `scheduled_end_period` plus 1 (both comparisons strict). On a successful assignment the `assigned_inspector_id` is set on the inspection and the inspector's `active_assignment_count` is incremented by 1.

An inspection may be cancelled by a `Registrar` while it is still `SCHEDULED` or `ASSIGNED`; cancelling in any other state is rejected with `ERR_INSPECTION_NOT_CANCELLABLE`. Cancellation moves the inspection to the terminal `CANCELLED` status. When the inspection being cancelled was `ASSIGNED`, cancellation additionally decrements the assigned inspector's `active_assignment_count` by 1 — compensating the increment taken at assignment — and clears the `assigned_inspector_id` back to null. Cancelling a merely `SCHEDULED` inspection has no assignment-count or inspector effect.

### 3.5. Performing and Completing an Inspection

Only the assigned inspector performs the work. Starting an inspection moves it from `ASSIGNED` to `IN_PROGRESS` and requires the acting `LicensedInspector` to be the inspection's `assigned_inspector_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. The inspection must be `ASSIGNED`, or it is rejected with `ERR_INSPECTION_NOT_ASSIGNED`. Because an inspector cannot work on a device that is out of service or gone, the device must not be `OUT_OF_SERVICE` or `DECOMMISSIONED`; either state rejects the start with `ERR_DEVICE_NOT_OPERABLE`.

Completing an inspection is where the outcome branches. The acting inspector must again be the `assigned_inspector_id` (`ERR_NOT_RESOURCE_OWNER`) and the inspection must be `IN_PROGRESS` (`ERR_INSPECTION_NOT_IN_PROGRESS`). The request carries a `result` and, when applicable, a `deficiencies` list; each entry in that list describes a finding by its `code`, its `severity` — one of `MINOR`, `MAJOR`, or `CRITICAL` — and a `description`. Every completion, regardless of branch, stamps the inspection's `performed_period` with the current period and decrements the assigned inspector's `active_assignment_count` by 1.

- A `result` of PASS drives the inspection to the terminal `PASSED` state. A passing inspection must carry an empty `deficiencies` list; a non-empty list is rejected with `ERR_PASS_WITH_DEFICIENCIES`. On passing, the device's `next_inspection_due_period` is set to the inspection's `performed_period` plus the recurrence interval for the device's category, where the interval in months is 12 for a `PASSENGER_ELEVATOR`, 12 for a `FREIGHT_ELEVATOR`, 6 for an `ESCALATOR`, 6 for a `MOVING_WALK`, and 24 for a `DUMBWAITER`.
- A `result` of CONDITIONAL drives the inspection to the terminal `CONDITIONAL` state. The `deficiencies` list must be non-empty and must contain no entry of `CRITICAL` severity; a violation of either condition is rejected with `ERR_INVALID_REQUEST`. One `Deficiency`, in `OPEN` status, is created for each entry in the list, and the device remains operable.
- A `result` of FAIL drives the inspection to the terminal `FAILED` state. The `deficiencies` list must be non-empty; an empty list is rejected with `ERR_FAIL_WITHOUT_DEFICIENCIES`. One `Deficiency`, in `OPEN` status, is created for each entry. A failing inspection additionally triggers a safety cascade: for each `CRITICAL` deficiency it created, the system auto-issues a citation against that deficiency (moving the deficiency from `OPEN` to `CITED`), and that citation in turn auto-creates an `ACTIVE` out-of-service order with reason `CRITICAL_DEFICIENCY`, whose `effective_start_period` is the current period and whose `effective_end_period` is the current period plus the device-category interval given above; that order then drives the device to `OUT_OF_SERVICE` and suspends its active certificate exactly as described in §2.8.

Each created `Deficiency` copies the originating `inspection_id` and the `device_id` from the inspection, opens in `OPEN` status, and is given a `resolution_due_period` equal to the inspection's `performed_period` plus the grace period in months for the finding's `severity` — 6 months for a `MINOR` finding, 3 months for a `MAJOR` finding, and 1 month for a `CRITICAL` finding. Deficiencies may be fetched individually or listed with optional filters on `inspection_id`, `device_id`, `status`, and `severity`.

### 3.6. Resolving Deficiencies, Issuing Citations, and the Contest Loop

A `LicensedInspector` resolves a deficiency once the underlying condition is corrected, moving it to the terminal `RESOLVED` state. Resolution is permitted only while the deficiency is `OPEN` or `CITED`; any other state is rejected with `ERR_DEFICIENCY_NOT_RESOLVABLE`.

A `Registrar` or a `SafetyAdministrator` may issue a citation against a deficiency by supplying its `deficiency_id`. The deficiency must be `OPEN`, or the request is rejected with `ERR_DEFICIENCY_NOT_OPEN`. Issuance creates a `Citation` in `ISSUED` status, copies the `device_id` from the deficiency onto the citation, and moves the deficiency from `OPEN` to `CITED`. The citation's `issued_period` is stamped with the current period, and its `due_period` is the `issued_period` plus a citation grace period of 2 months. A new citation starts with a `contest_count` of 0.

At issuance the citation's monetary fields are computed. The base fine is set by the deficiency's `severity`: 5000 cents for `MINOR`, 20000 cents for `MAJOR`, and 50000 cents for `CRITICAL`. That base is risk-adjusted by multiplying by the device's risk factor — 1.5 when the device's `risk_class` is `HIGH`, 1.2 when `MEDIUM`, and 1.0 when `LOW` — with the product rounded half up. A repeat-offense surcharge is then added: count the citations already existing on the same device whose status is `ISSUED`, `CONTESTED`, or `PAID` that were created before this one, cap that count at 3, and multiply the capped count by 10000 cents. The `fine_amount_cents` is the risk-adjusted base plus the repeat surcharge, but never more than a ceiling of 100000 cents. Finally, the `surcharged_amount_cents` — the exact figure that enters and later leaves the device's ledger — is the `fine_amount_cents` multiplied by one plus the outstanding index rate of 0.0725, rounded half up. Upon issuance, `surcharged_amount_cents` is added to the device's `outstanding_balance_cents`. Citations may be fetched individually or listed with optional filters on `deficiency_id`, `device_id`, and `status`.

Once issued, a citation follows a cyclic contest loop driven by the owner and the safety administrator. The owning `BuildingOwner` may pay the citation while it is `ISSUED`; paying it in any other state is rejected with `ERR_CITATION_NOT_PAYABLE`, and a caller who does not own the device is rejected with `ERR_NOT_RESOURCE_OWNER`. Payment moves the citation to the terminal `PAID` state and removes its `surcharged_amount_cents` from the device's `outstanding_balance_cents`. Alternatively, the owner may contest the citation while it is `ISSUED`; contesting it in any other state is rejected with `ERR_CITATION_NOT_CONTESTABLE`, and a non-owner is again rejected with `ERR_NOT_RESOURCE_OWNER`. Contesting moves the citation to `CONTESTED` and increments its `contest_count` by 1.

A `SafetyAdministrator` adjudicates a contested citation by supplying an `outcome`. The citation must be `CONTESTED`, or the request is rejected with `ERR_CITATION_NOT_CONTESTED`. An `outcome` of UPHELD returns the citation from `CONTESTED` back to `ISSUED`, from which the owner may pay it or contest it once more — this is the loop, and each fresh contest again advances `contest_count`. An `outcome` of DISMISSED moves the citation to the terminal `DISMISSED` state, removes its `surcharged_amount_cents` from the device's `outstanding_balance_cents` (exactly reversing the debit taken at issuance), and moves the linked deficiency from `CITED` to the terminal `WAIVED` state.

### 3.7. Issuing, Posting, and Retiring Certificates

A `Registrar` issues an operating certificate for a device by supplying the `device_id`, the `source_inspection_id` of the passing inspection that grounds it, and the `expected_device_version` for the optimistic-concurrency check described in §2.5. Issuance is heavily guarded, and the guards are evaluated in the priority order of §2.9. The optimistic-concurrency check comes first among the business guards: a stale `expected_device_version` is rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412). The source inspection must be in `PASSED` status, or the request is rejected with `ERR_SOURCE_INSPECTION_NOT_PASSED`. The device must have zero deficiencies in `OPEN` status — an empty-set requirement — or issuance is rejected with `ERR_OPEN_DEFICIENCIES_EXIST`. The source inspection's `device_id` must equal the `device_id` on the request, or the request is rejected with `ERR_INSPECTION_DEVICE_MISMATCH`. And the device's `outstanding_balance_cents` must be exactly 0, or issuance is rejected with `ERR_OUTSTANDING_BALANCE` (HTTP 402).

When those guards pass, a new `Certificate` is created in `ISSUED` status with a system-minted `certificate_number`. Its `issue_period` is stamped with the current period, and its `expiry_period` is the `issue_period` plus the device-category interval — 12 months for a `PASSENGER_ELEVATOR` or `FREIGHT_ELEVATOR`, 6 months for an `ESCALATOR` or `MOVING_WALK`, and 24 months for a `DUMBWAITER`. Its `posted_period` starts null. Issuance is a supersede-in-place: the device's prior active certificate, if any, transitions to the terminal `SUPERSEDED` state; the device's `current_certificate_id` is set to the new certificate; if the device was still `REGISTERED` it transitions to `ACTIVE`; and the device's `version` is incremented by 1 (which is precisely why a concurrent issuer's `expected_device_version` can go stale). A certificate whose stored status is `ISSUED` or `POSTED` is reclassified to the terminal `EXPIRED` status at read time once the clock's `current_period_index` has moved strictly past its `expiry_period`; like the fee-invoice `OVERDUE` reclassification of §3.2 this is purely presentational — it is surfaced by the serialized `status` (and honoured by the `status` list filter) but does not mutate the stored status, so state guards that require a certificate to be `ISSUED` or `POSTED` continue to test the stored value, and a certificate in any other stored status (`SUSPENDED`, `REVOKED`, or `SUPERSEDED`) is never reclassified to `EXPIRED`. Certificates may be fetched individually or listed with optional filters on `device_id`, `source_inspection_id`, and `status`.

The owning `BuildingOwner` posts the certificate on the physical conveyance, moving it from `ISSUED` to `POSTED` and stamping its `posted_period` with the current period. Posting requires the certificate to be `ISSUED`; any other state is rejected with `ERR_CERTIFICATE_NOT_POSTABLE`, and a caller who does not own the device is rejected with `ERR_NOT_RESOURCE_OWNER`. Beyond posting, the certificate's remaining transitions are all system-driven and tied to device safety: when the device goes `OUT_OF_SERVICE`, the device's active certificate (whether `ISSUED` or `POSTED`) is `SUSPENDED`; when the last active out-of-service order is lifted and the device returns to `ACTIVE`, a certificate that had been `POSTED` before its suspension is reinstated to `POSTED`, whereas one that had only ever been `ISSUED` (never posted) is `REVOKED` instead. These suspend-and-restore rules are stated in full in §2.8.

### 3.8. Out-of-Service Orders and Restoration

A `SafetyAdministrator` issues a shutdown order against a device by supplying the `device_id`, a `reason` — one of `CRITICAL_DEFICIENCY`, `ACCIDENT`, `NONPAYMENT`, or `EXPIRED_CERTIFICATE` — the occupation window as an `effective_start_period` and `effective_end_period` (a closed interval, both endpoints inclusive), and optionally the `citation_id` of a citation that motivated the order. The new window must not overlap, on that closed interval, any order already `ACTIVE` on the same device; an overlap is rejected with `ERR_OOS_ORDER_OVERLAP`. A newly created order opens in `ACTIVE` status with a null `lifted_period`, and its activation propagates through the device exactly as §2.8 describes: the device's `active_oos_count` is incremented by 1, the device moves to `OUT_OF_SERVICE`, and its active certificate is suspended. The same order-creation-and-propagation is what the inspection-failure cascade (§3.5) and the accident-investigation cascade (§3.9) trigger internally. Out-of-service orders may be fetched individually or listed with optional filters on `device_id`, `citation_id`, and `status`.

A `SafetyAdministrator` lifts an active order, moving it to the terminal `LIFTED` state and stamping its `lifted_period` with the current period. The order must be `ACTIVE`, or the request is rejected with `ERR_OOS_ORDER_NOT_ACTIVE`. Lifting decrements the device's `active_oos_count` by 1; if that decrement brings the count to 0, the device returns to `ACTIVE` and its suspended certificate is reinstated or revoked per the §2.8 rules. A device under several concurrent orders therefore returns to service only when its final active order is lifted.

### 3.9. Accident Reporting and Investigation

Either a `SafetyAdministrator` or the affected `BuildingOwner` may file an accident report against a device, supplying the `device_id`, the accident `severity` — one of `MINOR`, `MODERATE`, `SEVERE`, or `FATAL` — the `occurred_period` in which the accident happened, and a narrative `description`. A new report opens in `REPORTED` status with a null `lead_investigator_id` and a null `final_risk_score`. At filing, a `provisional_risk_score` is computed as the severity weight alone: 10 for `MINOR`, 30 for `MODERATE`, 60 for `SEVERE`, and 100 for `FATAL`. Accident reports may be fetched individually or listed with optional filters on `device_id`, `lead_investigator_id`, and `status`.

A `SafetyAdministrator` opens the investigation by supplying the `lead_investigator_id`, moving the report from `REPORTED` to `UNDER_INVESTIGATION`. Three conditions guard this step. The report must be `REPORTED`, or it is rejected with `ERR_ACCIDENT_NOT_REPORTED`. The nominated lead must be an inspector certified for the device's `category` with an unexpired license, or the request is rejected with `ERR_INSPECTOR_NOT_CERTIFIED`. And the segregation-of-duties rule must hold: the nominated lead must not be the `assigned_inspector_id` of any inspection of this same device that is currently `ASSIGNED` or `IN_PROGRESS` — an inspector routinely servicing the device may not lead its accident investigation — otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. On success the `lead_investigator_id` is set and a safety cascade fires: an `ACTIVE` out-of-service order with reason `ACCIDENT` is auto-created, with `effective_start_period` at the current period and `effective_end_period` at the current period plus the device-category interval, which then drives the device to `OUT_OF_SERVICE` and suspends its active certificate.

The lead investigator — a `LicensedInspector` who must be the report's `lead_investigator_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` — closes the investigation by supplying a `finding`. The report must be `UNDER_INVESTIGATION`, or the request is rejected with `ERR_ACCIDENT_NOT_UNDER_INVESTIGATION`. The `finding` branches the outcome and the final scoring:

- A `finding` of SUBSTANTIATED moves the report to the terminal `SUBSTANTIATED` state. Its `final_risk_score` is the severity weight multiplied by the device's risk factor (1.5 for `HIGH`, 1.2 for `MEDIUM`, 1.0 for `LOW`) and rounded half up, then increased by a bonus of 20 points for each of the device's deficiencies whose `severity` is `CRITICAL` and whose status is either `OPEN` or `CITED`.
- A `finding` of UNSUBSTANTIATED moves the report to the terminal `UNSUBSTANTIATED` state. Its `final_risk_score` is the severity weight multiplied by a factor of 0.25 and rounded half up — a discount to one quarter of the weight, with no device-risk multiplier and no deficiency bonus.

In both branches the computed `final_risk_score` is written onto the report and also copied to the device's `accident_risk_score`, which thereby reflects the outcome of the most recently closed investigation for that device.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Creating a new resource returns HTTP 201; state-changing actions and all other successful operations return HTTP 200. Request and response payloads are not repeated here — the fields each operation accepts and the side effects it produces are described in the §3 workflow narratives above. Authenticated roles are enforced per §2.1; all endpoints additionally require the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set | Advance the logical clock to an absolute period index | Registrar, SafetyAdministrator |
| POST | /owners | Register a building/property owner | Registrar |
| GET | /owners/{id} | Get an owner | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /inspectors | Register a licensed inspector | Registrar |
| GET | /inspectors/{id} | Get an inspector | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /inspectors | List inspectors | Registrar, SafetyAdministrator |
| POST | /devices | Register a conveyance device with its category | Registrar |
| GET | /devices/{id} | Get a device (includes computed balance, risk score, due period) | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /devices | List devices | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /devices/{id}/activate | Activate a registered device | Registrar |
| POST | /devices/{id}/decommission | Permanently decommission a device | Registrar, SafetyAdministrator |
| POST | /inspections | Schedule an inspection for a device | Registrar |
| GET | /inspections/{id} | Get an inspection | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /inspections | List inspections | Registrar, SafetyAdministrator, LicensedInspector |
| POST | /inspections/{id}/assign | Assign a licensed inspector to a scheduled inspection | Registrar |
| POST | /inspections/{id}/start | Assigned inspector starts the inspection | LicensedInspector |
| POST | /inspections/{id}/complete | Complete an inspection with a branching result | LicensedInspector |
| POST | /inspections/{id}/cancel | Cancel a scheduled or assigned inspection | Registrar |
| GET | /deficiencies/{id} | Get a deficiency | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /deficiencies | List deficiencies | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /deficiencies/{id}/resolve | Mark a deficiency resolved | LicensedInspector |
| POST | /citations | Issue a citation against an open deficiency | Registrar, SafetyAdministrator |
| GET | /citations/{id} | Get a citation | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /citations | List citations | Registrar, SafetyAdministrator, BuildingOwner |
| POST | /citations/{id}/pay | Owner pays a citation | BuildingOwner |
| POST | /citations/{id}/contest | Owner contests a citation | BuildingOwner |
| POST | /citations/{id}/resolve-contest | Safety administrator resolves a contested citation | SafetyAdministrator |
| POST | /certificates | Issue an operating certificate from a passed inspection | Registrar |
| GET | /certificates/{id} | Get a certificate | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /certificates | List certificates | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /certificates/{id}/post | Owner posts the certificate on the conveyance | BuildingOwner |
| POST | /out-of-service-orders | Issue a shutdown / out-of-service order against a device | SafetyAdministrator |
| GET | /out-of-service-orders/{id} | Get an out-of-service order | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /out-of-service-orders | List out-of-service orders | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /out-of-service-orders/{id}/lift | Lift an out-of-service order | SafetyAdministrator |
| POST | /fee-invoices | Create a fee/renewal invoice for a device | Registrar |
| GET | /fee-invoices/{id} | Get a fee invoice | Registrar, SafetyAdministrator, BuildingOwner |
| GET | /fee-invoices | List fee invoices | Registrar, SafetyAdministrator, BuildingOwner |
| POST | /fee-invoices/{id}/pay | Owner pays a fee invoice (finalizes amount with any late penalty) | BuildingOwner |
| POST | /accident-reports | File an accident report for a device | SafetyAdministrator, BuildingOwner |
| GET | /accident-reports/{id} | Get an accident report | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| GET | /accident-reports | List accident reports | Registrar, SafetyAdministrator, LicensedInspector, BuildingOwner |
| POST | /accident-reports/{id}/open-investigation | Open an investigation and assign an independent lead investigator | SafetyAdministrator |
| POST | /accident-reports/{id}/close | Lead investigator closes the investigation with a branching finding | LicensedInspector |

## 5. Error Code Catalogue

The conditions that trigger each error are described in the §2 and §3 narratives. This catalogue lists only the error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_PAGINATION | 400 |
| ERR_OWNER_NOT_FOUND | 404 |
| ERR_INSPECTOR_NOT_FOUND | 404 |
| ERR_DEVICE_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_DEFICIENCY_NOT_FOUND | 404 |
| ERR_CITATION_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_OOS_ORDER_NOT_FOUND | 404 |
| ERR_FEE_INVOICE_NOT_FOUND | 404 |
| ERR_ACCIDENT_NOT_FOUND | 404 |
| ERR_STALE_DEVICE_VERSION | 412 |
| ERR_DEVICE_NOT_REGISTERED | 409 |
| ERR_DEVICE_ALREADY_DECOMMISSIONED | 409 |
| ERR_DEVICE_NOT_OPERABLE | 409 |
| ERR_INSPECTION_NOT_SCHEDULED | 409 |
| ERR_INSPECTION_NOT_ASSIGNED | 409 |
| ERR_INSPECTION_NOT_IN_PROGRESS | 409 |
| ERR_INSPECTION_NOT_CANCELLABLE | 409 |
| ERR_PASS_WITH_DEFICIENCIES | 409 |
| ERR_FAIL_WITHOUT_DEFICIENCIES | 409 |
| ERR_INSPECTOR_NOT_CERTIFIED | 403 |
| ERR_INSPECTOR_SCHEDULE_CONFLICT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DEFICIENCY_NOT_OPEN | 409 |
| ERR_DEFICIENCY_NOT_RESOLVABLE | 409 |
| ERR_CITATION_NOT_PAYABLE | 409 |
| ERR_CITATION_NOT_CONTESTABLE | 409 |
| ERR_CITATION_NOT_CONTESTED | 409 |
| ERR_SOURCE_INSPECTION_NOT_PASSED | 409 |
| ERR_INSPECTION_DEVICE_MISMATCH | 409 |
| ERR_OPEN_DEFICIENCIES_EXIST | 409 |
| ERR_OUTSTANDING_BALANCE | 402 |
| ERR_REGISTRATION_FEE_UNPAID | 402 |
| ERR_CERTIFICATE_NOT_POSTABLE | 409 |
| ERR_OOS_ORDER_OVERLAP | 409 |
| ERR_OOS_ORDER_NOT_ACTIVE | 409 |
| ERR_INVOICE_NOT_PAYABLE | 409 |
| ERR_ACCIDENT_NOT_REPORTED | 409 |
| ERR_ACCIDENT_NOT_UNDER_INVESTIGATION | 409 |


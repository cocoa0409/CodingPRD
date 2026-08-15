# Railcar Leasing & Fleet Management API — Product Requirements Document

## 1. Introduction

Railcar lessors operate in a business where the asset is mobile, the revenue streams are layered, and the regulatory clock never stops. A single covered hopper may be under a full-service lease to a grain shipper this quarter, sit in a shop for wheel work next month, and face a federally mandated retrofit deadline the quarter after — all while car-hire revenue accrues daily, mileage credits offset that revenue, and the lessee's outstanding balance must be watched against its credit limit. This document specifies the API for a Railcar Leasing & Fleet Management platform that administers that entire operating reality: lease origination and approval, car assignment and fleet utilization measurement, the maintenance responsibility split between lessor and lessee, car-hire and mileage-credit settlement, tank-car regulatory compliance with retrofit deadlines, cleaning and prior-commodity control, lease return condition and damage billing, and fleet retirement with reinvestment of salvage proceeds.

The platform serves two sides of the lease contract simultaneously. On the lessor side, commercial administrators draft leases, planners assign cars and plan retirements, shop controllers authorize repairs and retrofits, billing analysts settle car-hire statements, and compliance officers gate every regulated approval. On the lessee side, a representative reports monthly mileage, disputes statements and damage assessments, and pre-authorizes repair shares above a negotiated cap. Money moves in integer cents only, versions guard every concurrently editable aggregate, and every financial event — a finalized statement, a completed shop repair, a certified cleaning, an invoiced damage assessment, an early termination — lands on the lessee's outstanding balance, which the system watches continuously: the moment the balance exceeds the lessee's credit limit, the account suspends itself and new commercial activity is blocked until the position is cured.

Two archetypes dominate the design. The first is ledger reconciliation: car-hire statements exist in a provisional form priced off the tariff in effect at computation time, and are later re-priced at finalize against tariff rates pinned at assignment creation and mileage figures validated by billing — the provisional and final variants of the same settlement formula. The second is compliance audit: regulatory directives are announced, promoted to effective, and enforced through per-car retrofit orders with hard deadlines, grace periods, and daily penalties that are reported in both an accrued (forward exposure) and an assessed (billing basis) form. Throughout, a logical clock governs all date arithmetic; before any test-driving call sets it, the clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contract formats, and cross-cutting principles that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which the user acts. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly seven roles, spelled exactly as follows: `SystemAdmin`, `LeaseAdmin`, `FleetPlanner`, `MaintenanceController`, `BillingAnalyst`, `ComplianceOfficer`, and `LesseeRep`.

- `SystemAdmin` is the platform operator; it alone drives the logical clock and opens capital pools.
- `LeaseAdmin` is the commercial contracts administrator, responsible for lessee registration, tariff maintenance, and lease drafting, amendment, submission, and termination.
- `FleetPlanner` owns fleet assignment and retirement planning: railcar registration, assignment delivery and return, retirement proposals, and pool commitments.
- `MaintenanceController` is the shop-side controller for repairs, cleanings, retrofits, and damage line items.
- `BillingAnalyst` runs car-hire billing: mileage validation, statement generation, finalization and settlement, damage invoicing and payment application, and assignment settlement.
- `ComplianceOfficer` is the regulatory gatekeeper: lease approval, directive promotion, retrofit and cleaning certification, and retirement approval. Approval authority is deliberately segregated from proposing authority (see §2.8).
- `LesseeRep` is the lessee-side representative, acting only on resources owned by its own lessee.

Role identity is resolved in two distinct ways. When `X-User-Role` is `LesseeRep`, `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any resource that references a `Lessee` compare the resource's lessee foreign key to `X-User-ID`. A `LesseeRep` attempting to dispute a statement whose `lessee_id` names a different lessee, to resubmit a mileage report whose assignment's lease belongs to a different lessee, to dispute a damage assessment under another lessee's lease, or to pre-authorize a repair tied to another lessee's assignment is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When `X-User-Role` is any of `SystemAdmin`, `LeaseAdmin`, `FleetPlanner`, `MaintenanceController`, `BillingAnalyst`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on a `LeaseAgreement` at submission, or as `proposer_user_id` on a `RetirementCase` at proposal — but does not compare it to any entity's `id`, except for the segregation-of-duties comparison on retirement approval described in §2.8.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Money Representation

Every primary resource in the system — Lessee, Railcar, LeaseAgreement, TariffRate, LeaseAssignment, MileageReport, CarHireStatement, RepairAuthorization, CleaningRecord, DamageAssessment, ComplianceDirective, RetrofitOrder, RetirementCase, CapitalPool, and PurchaseCommitment — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including mutations driven by cascades and derived-field recomputation.

All monetary values throughout the system — balances, rates, shares, credits, penalties, invoices, budgets — are represented as integer cents. No floating-point money exists anywhere. Where a multiplication produces a fractional cent, the result is rounded half-up to a whole cent at the step the calculation rule pins, never earlier and never later. The only quantity in the system represented with two decimal places is the fleet utilization percentage, which is rounded half-up to two decimals (see §2.9).

### 2.5. The Logical Clock

All date and timestamp arithmetic in the system — lease expiry, car age, directive grace, penalty accrual, utilization month boundaries, proration windows — is evaluated against a logical clock, never against wall-clock time. Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z. A `SystemAdmin` may advance the clock to a supplied `to_iso8601` instant through the test-driving capability listed in §4; the response echoes the new reading as `current_utc`. Advancing the clock arms the lazy expiry evaluation of leases described in §3.3. The clock only moves forward through explicit calls; it never falls back to wall-clock, and reads are always consistent within a request.

### 2.6. Validation Order of Precedence

When several validation rules could reject the same request, the server evaluates them in a fixed priority order, and the first failing check determines the error returned — lower priority number wins on dual failure. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` present, and the role is one of the seven declared roles; failure yields `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the presented role is listed for the endpoint; failure yields `ERR_FORBIDDEN_ROLE` (403).
3. **Ownership and segregation of duties** — for `LesseeRep`-scoped operations, the representative's `X-User-ID` equals the owning lessee of the target resource (the statement's `lessee_id`, or the lease's `lessee_id` reached through the assignment); failure yields `ERR_FORBIDDEN_ROLE` (403). On retirement approval specifically, the approver's `X-User-ID` differing from the case's `proposer_user_id` is required, and failure there yields `ERR_SOD_VIOLATION` (403) instead.
4. **Existence** — path identifiers resolve left-to-right; failure yields the domain-specific 404 naming the failing segment (`ERR_LESSEE_NOT_FOUND`, `ERR_RAILCAR_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_REPAIR_NOT_FOUND`, `ERR_CLEANING_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_RETROFIT_NOT_FOUND`, `ERR_RETIREMENT_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` (404) when no domain variant applies.
5. **Body shape** — required fields present, types correct, enum membership valid, numeric ranges respected; failure yields `ERR_VALIDATION` (400).
6. **State-machine legality** — the target entity is in a state from which the requested transition exists; failure yields `ERR_INVALID_STATE` (409).
7. **Cross-entity state gates** — the gates named in §2.7, each carrying its domain error (for example `ERR_LEASE_NOT_ACTIVE`, `ERR_RAILCAR_NOT_AVAILABLE`, `ERR_LESSEE_NOT_ACTIVE`, `ERR_ASSIGNMENT_NOT_RETURNED`, `ERR_STATEMENT_NOT_PROVISIONAL`, `ERR_REPORT_NOT_VALIDATED`, `ERR_DAMAGE_ASSESSMENT_OPEN`, `ERR_OPEN_REPAIR_ORDERS`, `ERR_RETIREMENT_BLOCKED`), all at HTTP 409.
8. **Fleet safety on assignment creation** — the age, compliance-posture, and commodity-compatibility checks of §2.10, carrying `ERR_AGE_LIMIT_EXCEEDED`, `ERR_TANK_CAR_NONCOMPLIANT`, and `ERR_COMMODITY_INCOMPATIBLE` respectively (422).
9. **Tariff coverage** — the assignment-time tariff snapshot requirement of §3.4, carrying `ERR_TARIFF_NOT_FOUND` (422).
10. **Temporal sanity** — the date-ordering, window-containment, overlap, buffer, and month-membership rules scattered through §3, carrying `ERR_INVALID_DATE_RANGE`, `ERR_OUTSIDE_LEASE_TERM`, `ERR_ASSIGNMENT_OVERLAP`, `ERR_CLEANING_BUFFER_VIOLATION`, `ERR_TARIFF_WINDOW_OVERLAP`, `ERR_REPORT_MONTH_MISMATCH`, and `ERR_RETROFIT_DEADLINE_PASSED` (422).
11. **Uniqueness and segregation-of-duties uniqueness-class checks** — duplicate marks, codes, years, and report months, carrying `ERR_DUPLICATE_CAR_MARK`, `ERR_DUPLICATE_DIRECTIVE_CODE`, `ERR_DUPLICATE_POOL_YEAR`, and `ERR_DUPLICATE_REPORT_MONTH` (409); retirement approver-equals-proposer is checked here as `ERR_SOD_VIOLATION` (403).
12. **Fiscal gates** — credit-limit, pool-sufficiency, repair-preauthorization, unpaid-invoice, and exact-payment checks, carrying `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_CAPITAL_POOL_INSUFFICIENT`, `ERR_REPAIR_PREAUTH_REQUIRED`, `ERR_OUTSTANDING_BALANCE`, and `ERR_PAYMENT_MISMATCH` (422).

Because existence (priority 4) precedes body shape (priority 5), a request to a non-existent parent fails with the 404 variant even if its body is also malformed. Because state legality (priority 6) precedes the fiscal gates (priority 12), a settle attempted on an assignment that is not `RETURNED` surfaces `ERR_ASSIGNMENT_NOT_RETURNED` rather than any balance-related error. Within assignment creation, a car that is both too old and non-compliant surfaces `ERR_AGE_LIMIT_EXCEEDED` (priority 8) before tariff coverage (priority 9) is even consulted; and both surface before a date-range problem (priority 10), a duplicate (priority 11), or a credit-limit breach (priority 12).

### 2.7. Cross-Entity State Gates

Several actions are gated not by the target entity's own state machine alone but by the state of a related entity. These gates, each carrying its own error id at HTTP 409, are:

- Creating an assignment requires the lease to be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`), the lessee to be `ACTIVE` (`ERR_LESSEE_NOT_ACTIVE`), and the railcar to be `AVAILABLE` (`ERR_RAILCAR_NOT_AVAILABLE`).
- Delivering an assignment requires the railcar to be `AVAILABLE` (`ERR_RAILCAR_NOT_AVAILABLE`).
- Returning an assignment requires the railcar to be `ON_LEASE`; a car still `IN_SHOP` fails the return with `ERR_RAILCAR_NOT_AVAILABLE`.
- Lease submission and lease approval each require the lessee to be `ACTIVE` (`ERR_LESSEE_NOT_ACTIVE`).
- Settling an assignment requires the assignment to be `RETURNED` (`ERR_ASSIGNMENT_NOT_RETURNED`), no repair authorization on the assignment in `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, or `IN_PROGRESS` (`ERR_OPEN_REPAIR_ORDERS`), and every damage assessment on the assignment in `FINALIZED`, `INVOICED`, or `PAID` (`ERR_DAMAGE_ASSESSMENT_OPEN`).
- Finalizing a statement requires the statement to be `PROVISIONAL` (`ERR_STATEMENT_NOT_PROVISIONAL`) and the month's mileage report to exist and be `VALIDATED` (`ERR_REPORT_NOT_VALIDATED`).
- Approving a retirement requires the railcar to be `AVAILABLE` (`ERR_RETIREMENT_BLOCKED`).

### 2.8. Segregation of Duties on Retirement

Retirement of a revenue asset is the one workflow where the system hard-separates proposing from approving. The `FleetPlanner` who creates a retirement case is recorded on the case as `proposer_user_id`, copied from the `X-User-ID` header at creation. Approval of that case must come from a `ComplianceOfficer` whose `X-User-ID` is different from the recorded `proposer_user_id`; an approval attempt by the same identifier is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This comparison is the only place an opaque operator id is compared against a persisted field; everywhere else, opaque ids are never matched to entity ids.

### 2.9. Precision, Rounding, and Pinned Evaluation Order

All monetary arithmetic is performed in integer cents. Every multiplication that can produce a fractional cent is rounded half-up at exactly the step the governing calculation rule pins, and the pinned order of operations within each calculation is part of the contract — reordering the steps produces different integer results and is a defect. Specifically:

- The mileage credit rounds half-up at the excess-miles multiplication only (§3.7).
- The car-hire settlement rounds half-up at each multiplication step in its pinned order: first the lessor share of gross car hire, then the excess-miles term inside the credit, then the credit cap (§3.7).
- The repair responsibility split rounds half-up at the excess-share multiplication (§3.9).
- The damage billing schedule rounds half-up twice per line — once for the line cost, once for the betterment reduction — and then sums the rounded lines; summing raw values and rounding once at the end is explicitly wrong (§3.10).
- Lease proration performs no rounding at all until the final rent multiplication, which is exact integer arithmetic (§3.6).
- Fleet utilization is the single non-integer output: a percentage rounded half-up to two decimal places (§3.12).

### 2.10. Fleet Safety Gates on Assignment

Before a railcar may be placed under a new assignment, three safety gates run, in this order, all at HTTP 422. First, age: a car whose `car_age_years` — the calendar year of the logical clock minus its `built_year` — is 50 or older is rejected with `ERR_AGE_LIMIT_EXCEEDED`; the limit triggers at exactly 50. Second, regulatory posture: a car whose `compliance_posture` is `NON_COMPLIANT` is rejected with `ERR_TANK_CAR_NONCOMPLIANT`. Third, commodity compatibility: if the assignment's `planned_commodity` differs from the car's `last_commodity` and that last commodity is not `NONE`, the assignment is rejected with `ERR_COMMODITY_INCOMPATIBLE` unless a `CERTIFIED` cleaning record for the car, created after the car's last return, bridges the two commodities. Even with a certified cleaning, the turnaround buffer of §3.4 still applies.

### 2.11. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control on a parent entity's `version`. Each requires a dedicated expected-version field as a non-optional input; if the supplied value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Amending a lease agreement requires `expected_lease_version` carrying the client's last observed `version` of the lease. A lease in `DRAFT` or `ACTIVE` remains legitimately amendable, so a stale `expected_lease_version` is the only signal that another writer has already changed the terms the client based its amendment on; the mismatch is rejected with `ERR_STALE_VERSION` (412).
- Amending a tariff rate's window or unit rate requires `expected_tariff_version` carrying the client's last observed `version` of the tariff; the client's view of the rate grid is stale even though the tariff remains editable, and a mismatch is rejected with `ERR_STALE_VERSION` (412).
- Creating a purchase commitment against a capital pool requires `expected_pool_version` carrying the client's last observed `version` of the pool; the affordability check must run against the pool version the client actually observed, and a mismatch is rejected with `ERR_STALE_VERSION` (412).

No other endpoint takes an expected-version field. Successful OCC-guarded writes increment the parent entity's `version` by 1, as does every other mutation in the system per §2.4.

### 2.12. Nested Resource Retrieval

Where an endpoint path contains more than one identifier — the commitment endpoints nested under a capital pool are the system's one nested hierarchy — identifiers are validated left-to-right. A request naming a non-existent pool fails with `ERR_POOL_NOT_FOUND` (404) before the commitment id is examined; a request with a valid pool but a commitment id that does not resolve within that pool fails with `ERR_COMMITMENT_NOT_FOUND` (404). Creation of a commitment under a pool likewise resolves the pool first.

## 3. Business Logic & Workflows

### 3.1. Lessees, Credit, and the Outstanding Balance Ledger

A `LeaseAdmin` registers a lessee by supplying its `company_name`, a `credit_tier` of `TIER_A`, `TIER_B`, or `TIER_C`, a `credit_limit_cents` ceiling (zero or more), and a `security_deposit_cents` amount (zero or more). The lessee enters life `ACTIVE` with an `outstanding_balance_cents` of zero. The outstanding balance is the system's central receivables ledger: it rises when a car-hire statement is finalized, when a shop repair completes with a positive lessee share on an assignment-linked repair, when a cleaning certified as lessee-attributable lands its cost, when a damage assessment is invoiced, and when an assignment settle bills rent and termination fees; it falls when a statement is settled or a damage payment is recorded.

The ledger is watched continuously. After any mutation of `outstanding_balance_cents`, the system re-evaluates the credit rule: if the balance now exceeds the lessee's `credit_limit_cents`, the lessee is automatically transitioned from `ACTIVE` to `SUSPENDED`, and while suspended, new lease submissions and new assignment creations for that lessee are blocked (surfacing `ERR_LESSEE_NOT_ACTIVE` per §2.7). A `LeaseAdmin` may reinstate a suspended lessee, but only once the balance has been paid down to at most the credit limit; attempting reinstatement while the balance still exceeds the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (422).

A lessee whose commercial relationship is over may be terminated by a `LeaseAdmin`, from either `ACTIVE` or `SUSPENDED`, provided no lease agreement for the lessee remains in `DRAFT`, `PENDING_APPROVAL`, or `ACTIVE`; open leases block termination with `ERR_LESSEE_HAS_OPEN_LEASES` (409). `TERMINATED` is terminal.

### 3.2. The Railcar Registry and Car State

A `FleetPlanner` registers each car with its `car_mark` reporting mark (unique across the fleet — duplicates are rejected with `ERR_DUPLICATE_CAR_MARK`, 409), a `car_type` of `BOX`, `COVERED_HOPPER`, `GONDOLA`, `FLAT`, `TANK_GENERAL`, or `TANK_PRESSURE`, and a `built_year` between 1900 and 2100. A new car starts `AVAILABLE` with `compliance_posture` `COMPLIANT`, `last_commodity` `NONE`, `cumulative_miles` zero, `open_shop_repair_count` zero, and `retired_at` null.

The car's `status` walks a cyclic graph. From `AVAILABLE`, delivery of a scheduled assignment moves it to `ON_LEASE`. From `ON_LEASE`, return of the assignment moves it back to `AVAILABLE` and simultaneously writes the assignment's `planned_commodity` onto the car's `last_commodity`. From either `AVAILABLE` or `ON_LEASE`, starting work on an approved shop repair moves the car to `IN_SHOP`; the prior status is saved in `status_before_shop`, and `open_shop_repair_count` increments by one. When a shop repair completes, the count decrements by one, and only when it reaches zero does the car leave the shop — restored to whatever `status_before_shop` held (`AVAILABLE` or `ON_LEASE`), with `status_before_shop` cleared to null. Two overlapping shop repairs therefore keep the car `IN_SHOP` until both complete. Separately, approval of a retirement case moves an `AVAILABLE` car to `RETIREMENT_PENDING`; cancelling that case returns the car to `AVAILABLE`, while executing it moves the car to `RETIRED` with `retired_at` stamped at the current logical timestamp. `RETIRED` is terminal.

Two computed attributes ride on the registry. `car_age_years` is the calendar year of the logical clock minus `built_year` — it drives the 50-year age gate of §2.10 and the betterment rule of §3.10. `compliance_posture` is derived from directives and retrofit certification per §3.11 and takes values `COMPLIANT`, `RETROFIT_DUE`, or `NON_COMPLIANT`.

### 3.3. Lease Agreements: Drafting, Approval, Amendment, Termination

A `LeaseAdmin` drafts a lease by naming the `lessee_id` and supplying `lease_type` (`FULL_SERVICE` or `NET`, which drives the maintenance responsibility split of §3.9), a positive `base_daily_rate_cents` rent per billable day per car, the `car_hire_lessor_share_pct` (an integer from 0 to 100), the `authorized_repair_cap_cents` threshold (zero or more) above which lessee pre-authorization is required, and the `start_date` and inclusive `end_date` of the term. The lease is born `DRAFT`.

Submitting the draft (a `LeaseAdmin` action) moves it to `PENDING_APPROVAL` and stamps `submitted_by_user_id` with the caller's `X-User-ID`; submission requires the lessee to be `ACTIVE`, failing with `ERR_LESSEE_NOT_ACTIVE` (409) otherwise. A `ComplianceOfficer` then approves or rejects. Approval moves the lease to `ACTIVE` and is guarded by two checks: the lease's `end_date` must be strictly after its `start_date` (`ERR_INVALID_DATE_RANGE`, 422), and the lessee must still be `ACTIVE` (`ERR_LESSEE_NOT_ACTIVE`, 409). Rejection returns the lease to `DRAFT`, forming a revision loop.

Lease terms may be amended while the lease is `DRAFT` or `ACTIVE` via the OCC-guarded amendment described in §2.11: the caller supplies `expected_lease_version` plus any of `base_daily_rate_cents`, `car_hire_lessor_share_pct`, `authorized_repair_cap_cents`, or `end_date`. A successful amendment increments the lease's `version` by 1. Amendments never retroactively alter tariff snapshots already pinned onto assignments (§3.4).

Early termination of an `ACTIVE` lease is a `LeaseAdmin` action with three side effects. First, an `early_termination_fee_cents` is computed: take the number of days from the current logical date to the `end_date`, floor it at zero, cap it at 90 days, multiply by `base_daily_rate_cents`, and take 50 percent, rounding half-up to a whole cent. Second, every `SCHEDULED` assignment of the lease is cancelled with `cancellation_reason` `LEASE_TERMINATED`. Third, the fee is added to the lessee's `outstanding_balance_cents`, and the auto-suspension rule of §3.1 is re-evaluated.

A lease also expires passively: whenever the lease is read or mutated and the current logical date is after its `end_date`, an `ACTIVE` lease transitions to `EXPIRED`. Expiry does not strand cars — assignments already `ON_LEASE` continue until returned. Both `EXPIRED` and `TERMINATED` are terminal.

### 3.4. Assignment: Placement Gates, Tariff Pinning, Delivery, Return

Assignment is the act of putting a named car under a named lease for a window, and it concentrates more validation than any other operation. A `FleetPlanner` creates an assignment with `lease_id`, `railcar_id`, `planned_commodity` (any commodity enum value except `NONE` — one of `GRAIN`, `COAL`, `PLASTIC_PELLETS`, `CEMENT`, `LUMBER`, `CRUDE_OIL`, `GASOLINE`, `ETHANOL`, `CORN_SYRUP`, `CHEMICAL_SOLVENT`), and an inclusive window `scheduled_start` to `scheduled_end`.

The validation chain runs in the priority order of §2.6: role and existence first, then the cross-entity gates of §2.7 (lease `ACTIVE`, lessee `ACTIVE`, railcar `AVAILABLE`), then the three fleet-safety gates of §2.10 (age under 50; posture not `NON_COMPLIANT`; commodity compatibility through a `CERTIFIED` cleaning). Tariff coverage comes next: a `CAR_HIRE_BASE` tariff and a `MILEAGE_CREDIT` tariff for the car's `car_type` must both cover `scheduled_start`; if either is missing, creation fails with `ERR_TARIFF_NOT_FOUND` (422). When coverage exists, the two rates effective at `scheduled_start` are snapshotted onto the assignment as `pinned_car_hire_daily_cents` and `pinned_mileage_credit_cents` — these pinned values, not the live grid, later price the final settlement variant.

Temporal checks follow. `scheduled_end` must be on or after `scheduled_start` (`ERR_INVALID_DATE_RANGE`, 422). The whole assignment window must lie within the lease term from `start_date` to `end_date` (`ERR_OUTSIDE_LEASE_TERM`, 422). The window must not overlap any other `SCHEDULED`, `ON_LEASE`, or `RETURNED` assignment on the same railcar, comparing inclusive windows (`ERR_ASSIGNMENT_OVERLAP`, 422). And on a commodity change — `planned_commodity` differing from the car's `last_commodity` when the latter is not `NONE` — a turnaround buffer applies on top of the cleaning requirement: `scheduled_start` must be at least 3 days after the previous assignment's `scheduled_end`, even when the cleaning is already certified; violating the buffer fails with `ERR_CLEANING_BUFFER_VIOLATION` (422). Finally, the fiscal gate: the lessee's `outstanding_balance_cents` must be at most its `credit_limit_cents` at creation (`ERR_CREDIT_LIMIT_EXCEEDED`, 422). A created assignment holds status `SCHEDULED`, with `actual_on_lease_date`, `actual_off_lease_date`, `billable_days`, `final_rent_cents`, `termination_fee_cents`, and `cancellation_reason` all null.

Delivery moves the assignment `SCHEDULED → ON_LEASE`, stamps `actual_on_lease_date` with the current logical date, and moves the railcar to `ON_LEASE`; delivery requires the car to still be `AVAILABLE` (`ERR_RAILCAR_NOT_AVAILABLE`, 409). Return moves the assignment `ON_LEASE → RETURNED`, stamps `actual_off_lease_date`, moves the railcar back to `AVAILABLE`, and copies `planned_commodity` onto the car's `last_commodity`; return requires the car to be `ON_LEASE` — a car still `IN_SHOP` fails with `ERR_RAILCAR_NOT_AVAILABLE` (409). Returning also opens the damage-inspection loop: a `DamageAssessment` in `DRAFT` is cascade-created for the assignment. A `FleetPlanner` may cancel a `SCHEDULED` assignment; the cancellation records `cancellation_reason` `LESSEE_REQUEST`. (The other two cancellation reasons, `DIRECTIVE_EFFECTIVE` and `LEASE_TERMINATED`, come from the cascades in §3.11 and §3.3 respectively.) `SETTLED` and `CANCELLED` are the terminal states.

### 3.5. Mileage Reporting: Submission, Validation, Dispute

Each month, a `LesseeRep` reports the car's mileage by submitting a `MileageReport` with `railcar_id`, `lease_assignment_id`, the `report_month` in `YYYY-MM` form, and non-negative `loaded_miles` and `empty_miles`. The report must name a month in which the assignment was actually on lease (`ERR_REPORT_MONTH_MISMATCH`, 422), and only one non-`DISPUTED` report may exist per car per month: submitting a report for a `(railcar_id, report_month)` pair that already has a report in any status other than `DISPUTED` fails with `ERR_DUPLICATE_REPORT_MONTH` (409) — a `DISPUTED` report is considered superseded by its resubmission and does not block the pair. A fresh report is `SUBMITTED`, with `validated_loaded_miles` and `validated_empty_miles` null.

Validation is a `BillingAnalyst` action moving the report `SUBMITTED → VALIDATED`. The analyst may supply corrected `validated_loaded_miles` and `validated_empty_miles`; where either is omitted, the reported value stands. Validation has two far-reaching side effects. First, the car's `cumulative_miles` absorbs the report per the conservation rule of §3.8: the validated loaded plus validated empty miles are added, net of any miles this same report previously contributed (zero on first validation). Second, every `PROVISIONAL` car-hire statement for the report's `(lease_assignment_id, report_month)` is recomputed under the provisional variant using the now-validated miles (§3.7).

If billing later questions a validated report, the analyst disputes it (`VALIDATED → DISPUTED`) with a `reason`; the report's miles remain counted in `cumulative_miles` at their last validated values until the cycle completes. The lessee answers a dispute by resubmitting (`DISPUTED → SUBMITTED`) fresh `loaded_miles` and `empty_miles` — restricted to the `LesseeRep` whose `X-User-ID` equals the `lessee_id` of the lease behind the report's assignment (`ERR_FORBIDDEN_ROLE`, 403). Resubmission replaces the reported values but deliberately retains the last validated values until a fresh validation lands, at which point the conservation rule contributes only the delta. The mileage state machine has no terminal state; the validate–dispute–resubmit cycle may repeat.

### 3.6. Assignment Settlement and Lease Proration

Once a car is back, a `BillingAnalyst` settles the assignment (`RETURNED → SETTLED`). Settlement is gated by the full closure of shop and inspection work: the assignment must be `RETURNED` (`ERR_ASSIGNMENT_NOT_RETURNED`, 409); no repair authorization on the assignment may remain `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, or `IN_PROGRESS` (`ERR_OPEN_REPAIR_ORDERS`, 409); every damage assessment on the assignment must be `FINALIZED`, `INVOICED`, or `PAID` (`ERR_DAMAGE_ASSESSMENT_OPEN`, 409); and no damage assessment on the assignment may sit `INVOICED` but unpaid (`ERR_OUTSTANDING_BALANCE`, 422).

Settlement runs the lease proration calculation, whose evaluation order is pinned and must not be rearranged:

1. For every `COMPLETED` shop repair (`requires_shop` true) on this assignment, determine the responsibility split on the repair's `final_cost_cents` per §3.9.
2. Excluded days accumulate across exactly those repairs whose `lessor_share_cents` is greater than zero: for each such repair, count the days from `shop_entry_date` (inclusive) to `completion_date` (exclusive), clipped to the on-lease window, and sum them.
3. Raw days are the calendar-day difference from `actual_on_lease_date` (inclusive) to `actual_off_lease_date` (exclusive).
4. `billable_days` is raw days minus excluded days.
5. `final_rent_cents` is `billable_days` multiplied by the lease's `base_daily_rate_cents` — the first and only multiplication in this calculation, exact integer arithmetic with no rounding.
6. `termination_fee_cents` attributed to this settlement equals the lease's `early_termination_fee_cents` when the lease is `TERMINATED`, and zero otherwise.

The rationale for the pinned order is that responsibility must be known before excluded days can be identified, excluded days before billable days, and billable days before rent; the termination fee stands last and is independent of the rent computation. The settle then bills the sum of `final_rent_cents` and `termination_fee_cents` onto the lessee's `outstanding_balance_cents` and re-evaluates auto-suspension.

### 3.7. Car-Hire Statements: Provisional vs. Final Settlement

Car-hire billing runs monthly, in two priced variants of one settlement formula. A `BillingAnalyst` triggers generation for a `statement_month`; the system produces one `PROVISIONAL` statement per assignment that was on lease at any point in that month — assignments in `ON_LEASE`, `RETURNED`, or `SETTLED` overlapping the month — walking assignments in `created_at` ascending order, and skipping any `(lease_assignment_id, statement_month)` pair that already has a statement. Each statement records its `lease_assignment_id`, `railcar_id`, the `lessee_id` reached through the assignment's lease, and the `statement_month`.

The settlement formula, common to both variants, works as follows. `days_on_lease` counts the calendar days of the statement month on which the assignment was on lease: from the later of `actual_on_lease_date` and the first day of the month through the earlier of `actual_off_lease_date` (exclusive) and the last day of the month, inclusive — a car on lease for the whole of August contributes 31. `gross_car_hire_cents` is `days_on_lease` multiplied by the daily rate, where the daily rate is the variant's `CAR_HIRE_BASE` tariff for the car's type. The lessor's share is the gross multiplied by the lease's `car_hire_lessor_share_pct` and divided by 100, rounded half-up to a whole cent.

The mileage credit uses only loaded miles — empty miles never earn credit. Let the loaded miles used be the variant's miles figure, and let the prior accumulated loaded miles be the cumulative validated loaded miles on this lease in the calendar year of the statement month, excluding this statement. The full-rate miles are the lesser of the loaded miles used and the remaining room under the 120,000-mile high-mileage threshold (that is, the threshold minus the prior accumulation, floored at zero); the excess miles are the remainder of the loaded miles used above that full-rate portion. When the prior accumulation plus the current miles lands exactly on 120,000, the excess is zero — the threshold reads as miles strictly beyond 120,000. The uncapped credit is the full-rate miles multiplied by the mileage credit rate, plus the excess miles multiplied by the rate and by 80 percent, the excess term divided by 100 and rounded half-up to a whole cent. The excess miles figure is persisted on the statement as `tier_excess_miles`.

The credit is then capped: the cap is the gross car hire multiplied by 80 percent and divided by 100, rounded half-up, and the credited amount (`mileage_credit_cents`) is the lesser of the uncapped credit and the cap. The net due is the lessor share minus the credit. Rounding is pinned at each multiplication step in the order given: lessor share first, then the excess-miles term inside the credit, then the cap.

The two variants differ only in their inputs. The **provisional** variant — used at generation, at validation-triggered recompute, and at dispute recompute — prices the daily rate and the mileage credit rate off the tariffs effective on the first day of the statement month at compute time (`tariff_source` `CURRENT`), and takes its loaded miles from the latest reported figures (the validated loaded miles once the report is `VALIDATED`). It writes `days_on_lease`, `gross_car_hire_cents`, `loaded_miles_used`, `tier_excess_miles`, `mileage_credit_cents`, and `provisional_net_cents`. The **final** variant — used only at finalize — prices off the assignment's `pinned_car_hire_daily_cents` and `pinned_mileage_credit_cents` snapshotted at creation (`tariff_source` `PINNED`), takes its loaded miles from `validated_loaded_miles`, rewrites the same measured fields, and writes `final_net_cents`.

A statement's lifecycle runs `PROVISIONAL → FINALIZED → SETTLED`, with a dispute loop attached. A `LesseeRep` whose `X-User-ID` equals the statement's `lessee_id` may dispute a provisional statement (`PROVISIONAL → DISPUTED`) with a mandatory `dispute_reason`; a representative of any other lessee is refused with `ERR_FORBIDDEN_ROLE` (403). A `BillingAnalyst` recomputes a disputed statement (`DISPUTED → PROVISIONAL`) under the provisional variant against the latest miles. Finalize (`PROVISIONAL → FINALIZED`) requires the month's mileage report to exist and be `VALIDATED` (`ERR_REPORT_NOT_VALIDATED`, 409; the state gate itself carries `ERR_STATEMENT_NOT_PROVISIONAL`, 409), runs the final variant, then adds `final_net_cents` to the lessee's `outstanding_balance_cents` and re-evaluates auto-suspension. Settlement (`FINALIZED → SETTLED`) records an exact payment: `amount_cents` must equal `final_net_cents` to the cent (`ERR_PAYMENT_MISMATCH`, 422), and the paid amount is subtracted from the lessee's balance with auto-suspension re-evaluated. `SETTLED` is terminal.

### 3.8. Cumulative Mileage Conservation

The car's `cumulative_miles` is defined as the exact sum, over all of the car's mileage reports in `VALIDATED` or `DISPUTED` status, of validated loaded miles plus validated empty miles. A `DISPUTED` report keeps contributing its last validated pair until a revalidation replaces them. Revalidation after a resubmit therefore contributes only the delta between the new validated total and the previously counted validated total — never the full new amount on top of the old. The conservation invariant the system maintains: a validate → dispute → resubmit → validate round trip leaves `cumulative_miles` equal to the sum over the current validated values, with no double counting.

### 3.9. Repair Authorizations and the Responsibility Split

A `MaintenanceController` opens a repair authorization with `railcar_id`, an optional `lease_assignment_id` (the on-lease assignment for the car, when one exists), a free-text `defect_description`, a `defect_cause` of `WEAR_AND_TEAR`, `LESSEE_DAMAGE`, or `PRE_EXISTING`, a positive `estimate_cents`, and a `requires_shop` flag indicating whether the car must enter the shop. The repair enters `UNDER_REVIEW` with `revision_count` zero, `lessee_preauthorized` false, and `approved_amount_cents`, `final_cost_cents`, `shop_entry_date`, and `completion_date` null. At creation — and again at every revise and at completion — the responsibility split runs:

- If the defect cause is `LESSEE_DAMAGE`, the lessee bears the entire cost.
- Otherwise, if the lease behind the linked assignment is a `NET` lease, the lessee bears the entire cost. (A repair with no linked assignment is treated as `FULL_SERVICE`.)
- Otherwise, if the cause is `PRE_EXISTING`, the lessee bears nothing.
- Otherwise — a `FULL_SERVICE` lease with ordinary `WEAR_AND_TEAR` — the lessee bears a share of the excess over a wear allowance of 25,000 cents: the excess is the amount by which the cost exceeds 25,000, floored at zero, and the lessee's share is 40 percent of that excess, rounded half-up to a whole cent.

The lessee's share is persisted as `lessee_share_cents`, and the lessor's share (`lessor_share_cents`) is always the cost minus `lessee_share_cents`. The flag `lessee_preauth_required` is true exactly when a `lease_assignment_id` is present and `lessee_share_cents` exceeds the lease's `authorized_repair_cap_cents`.

Approval (`UNDER_REVIEW → APPROVED`) is a `MaintenanceController` action carrying `approved_amount_cents`, which must be positive (`ERR_VALIDATION`, 400). If `lessee_preauth_required` is set, approval is blocked until a `LesseeRep` of the owning lessee has pre-authorized the repair, which sets `lessee_preauthorized` true; approving without it fails with `ERR_REPAIR_PREAUTH_REQUIRED` (422). The controller may instead send the estimate back (`UNDER_REVIEW → REVISION_REQUESTED`) with `notes`, or reject the repair outright (`UNDER_REVIEW → REJECTED`) with a `reason`; `REJECTED` is terminal. A revision (`REVISION_REQUESTED → UNDER_REVIEW`) supplies a fresh positive `estimate_cents` (`ERR_VALIDATION`, 400), replaces the estimate, increments `revision_count` by one, recomputes the split and the preauthorization flag, and resets `lessee_preauthorized` to false — a materially changed estimate voids the earlier consent.

Starting work (`APPROVED → IN_PROGRESS`) on a repair with `requires_shop` true puts the car into the shop per §3.2 — the car must be `AVAILABLE` or `ON_LEASE` (`ERR_RAILCAR_NOT_AVAILABLE`, 409), `status_before_shop` is saved, `open_shop_repair_count` increments, and `shop_entry_date` is stamped with the current logical date. Completing work (`IN_PROGRESS → COMPLETED`) carries a positive `final_cost_cents` (`ERR_VALIDATION`, 400); the split is recomputed on the final cost, `completion_date` is stamped, and if the repair is assignment-linked with a positive lessee share, that share is added to the lessee's `outstanding_balance_cents` with auto-suspension re-evaluated. For a shop repair, completion also decrements `open_shop_repair_count`; when the count reaches zero the car is released from the shop back to its saved pre-shop status. `COMPLETED` is terminal.

### 3.10. Cleaning Records and Damage Assessments

**Cleaning.** A `MaintenanceController` schedules a cleaning with `railcar_id`, the `prior_commodity` being cleaned out, the `next_commodity` the car is being prepared for (both any commodity except `NONE`), a `planned_date`, and optionally `attributable_to_lessee` (defaulting to false). Two fields are computed at scheduling: `cleaning_grade_required` is `STEAM_CLEAN` when the prior commodity is `CRUDE_OIL`, `GASOLINE`, or `CHEMICAL_SOLVENT`, and `WASH` otherwise; `bill_to` is `LESSEE` when `attributable_to_lessee` is true and `LESSOR` otherwise. The record starts `SCHEDULED` with `certificate_ref` null.

Recording a performed cleaning (from `SCHEDULED`, or from `FAILED` for a re-clean cycle) carries the `cleaning_grade_performed` and the non-negative `cost_cents`. The performed grade must satisfy the required grade: `STEAM_CLEAN` satisfies both grades, while `WASH` satisfies only a `WASH` requirement; an insufficient grade fails with `ERR_VALIDATION` (400). On completion the record is `COMPLETED` and the cost is recorded (replaced, in a re-clean cycle). A `ComplianceOfficer` then certifies (`COMPLETED → CERTIFIED`) with a `certificate_ref`, or fails the inspection (`COMPLETED → FAILED`) with a `reason`. Certification is the billing trigger: when `bill_to` is `LESSEE`, the `cost_cents` is added to the outstanding balance of the lessee on the car's most recent `RETURNED` or `SETTLED` assignment, with auto-suspension re-evaluated. `CERTIFIED` is terminal; `FAILED` loops back through completion. Certified cleanings are also the commodity-compatibility bridge consumed by §2.10.

**Damage.** A `DamageAssessment` may be created in `DRAFT` by a `MaintenanceController` naming `lease_assignment_id` and `railcar_id`, and one is also cascade-created in `DRAFT` when an assignment is returned (§3.4). The controller submits or resubmits a non-empty `line_items` array (`ERR_VALIDATION`, 400 on empty), moving the assessment `DRAFT → SUBMITTED` or `DISPUTED → SUBMITTED`; resubmission replaces the line items entirely. Each line item names a `component`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, a `cause` of `LESSEE_DAMAGE`, `WEAR_AND_TEAR`, or `PRE_EXISTING`, `parts_cents`, `labor_hours`, and a `replaced` flag. A `LesseeRep` of the owning lessee disputes a submitted assessment (`SUBMITTED → DISPUTED`) with a `reason`; any other lessee's representative is refused with `ERR_FORBIDDEN_ROLE` (403).

Finalization (`SUBMITTED → FINALIZED`, a `MaintenanceController` action) freezes the money per the damage billing schedule, whose rounding order is pinned per line, then summed — summing raw values first and rounding once is explicitly wrong. For each line: the raw line cost is `parts_cents` plus `labor_hours` multiplied by a labor rate of 14,500 cents per hour and by the severity multiplier (1.00 for `MINOR`, 1.25 for `MODERATE`, 1.50 for `SEVERE`), and that raw cost is rounded half-up to a whole cent, giving the line cost. The lessee-liable portion of the line is then determined: if the cause is `LESSEE_DAMAGE`, the line's `replaced` flag is true, and the car's `car_age_years` is at least 30, a betterment reduction applies — the lessee pays 75 percent of the line cost (that is, 100 minus the 25 percent betterment), rounded half-up to a whole cent. If the cause is `LESSEE_DAMAGE` without the betterment conditions, the lessee pays the full line cost. For any other cause, the line contributes nothing to lessee liability. `total_assessed_cents` is the sum of the per-line rounded costs; `lessee_liable_cents` is the sum of the per-line rounded lessee amounts.

A `BillingAnalyst` invoices (`FINALIZED → INVOICED`), which adds `lessee_liable_cents` to the lessee's `outstanding_balance_cents` with auto-suspension re-evaluated; and records payment (`INVOICED → PAID`) for `amount_cents` exactly equal to `lessee_liable_cents` (`ERR_PAYMENT_MISMATCH`, 422), subtracting the amount from the balance with auto-suspension re-evaluated. `PAID` is terminal. As §3.6 notes, an `INVOICED`-but-unpaid assessment blocks assignment settle with `ERR_OUTSTANDING_BALANCE`.

### 3.11. Regulatory Directives and Retrofit Orders

A `ComplianceOfficer` announces a directive with a unique `directive_code` such as DOT-117R (duplicates fail with `ERR_DUPLICATE_DIRECTIVE_CODE`, 409), a free-text `description`, a non-empty `applies_to_car_types` array of car-type enum values, a `retrofit_deadline` date, an optional `grace_days` (defaulting to 30), a positive `daily_penalty_cents`, and a positive `penalty_cap_cents`. The directive is `ANNOUNCED`, and `effective_date` is null. At announcement, every railcar whose `car_type` is covered and which lacks a `CERTIFIED` retrofit order for the directive has its `compliance_posture` set to `RETROFIT_DUE`.

Promoting a directive (`ANNOUNCED → EFFECTIVE`, a `ComplianceOfficer` action) stamps `effective_date` with the current logical date and fires a cascade. First hop: every railcar whose `car_type` is in `applies_to_car_types` and which has no `CERTIFIED` retrofit order for this directive becomes `NON_COMPLIANT`. Second hop: every `SCHEDULED` lease assignment on each such railcar is cancelled with `cancellation_reason` `DIRECTIVE_EFFECTIVE`. `EFFECTIVE` is terminal.

A `MaintenanceController` schedules the per-car remediation as a retrofit order naming `railcar_id`, `directive_id`, and a `scheduled_date` that must be on or before the directive's `retrofit_deadline` (`ERR_RETROFIT_DEADLINE_PASSED`, 422). The order starts `SCHEDULED` with `deferral_count` zero and `completed_date` / `certification_ref` null. Deferral (`SCHEDULED → DEFERRED`) carries a `reason` and increments `deferral_count`; rescheduling (`DEFERRED → SCHEDULED`) supplies a fresh `scheduled_date`, again bounded by the deadline (`ERR_RETROFIT_DEADLINE_PASSED`, 422). Work proceeds `SCHEDULED → IN_PROGRESS` (start), `IN_PROGRESS → COMPLETED` (complete, stamping `completed_date`), and certification (`COMPLETED → CERTIFIED`) is a `ComplianceOfficer` action supplying `certification_ref`. Certification recomputes the car's `compliance_posture`: the car is `COMPLIANT` exactly when every `EFFECTIVE` directive covering its car type has a `CERTIFIED` retrofit for the car. An order may be cancelled from `SCHEDULED` or `DEFERRED`; `CERTIFIED` and `CANCELLED` are terminal.

Penalty exposure on a non-compliant car is computed on read, against the logical clock, in two variants. For each `EFFECTIVE` directive covering the car's type that lacks a `CERTIFIED` retrofit for the car, the days since effective is the calendar-day difference from `effective_date` to the current date, floored at zero. The **accrued** variant — forward-looking exposure — is simply the days since effective multiplied by `daily_penalty_cents`, ignoring grace and cap entirely. The **assessed** variant — the billing basis — counts only the days beyond `grace_days` (days since effective minus `grace_days`, floored at zero), multiplies by `daily_penalty_cents`, and caps the result at `penalty_cap_cents`; a car certified within its grace period assesses zero. The railcar-level compliance view rolls both variants up across all such directives: keyed by `car_id`, it reports the car's `posture`, the `open_directive_ids` still lacking certification, the `days_since_oldest_effective`, and the summed `accrued_penalty_cents` and `assessed_penalty_cents`. A `COMPLIANT` car accrues zero on both.

### 3.12. Fleet Utilization

Fleet utilization is reported per calendar month (the caller supplies `month` in `YYYY-MM` form). Eligible car-days sum, over all railcars, the days of the month on which each car was part of the fleet: a car never retired during the month contributes all of the month's calendar days; a `RETIRED` car contributes the days before the date of its `retired_at`; a car created mid-month contributes from the date of its `created_at`. On-lease car-days sum, over assignments in `ON_LEASE`, `RETURNED`, or `SETTLED`, the overlap in days between the assignment's on-lease span — from `actual_on_lease_date` inclusive to `actual_off_lease_date` exclusive (or to the end of the month when still on lease) — and the month. The utilization percentage is 100 times on-lease car-days divided by eligible car-days, rounded half-up to two decimal places; when there are no eligible car-days at all (an empty fleet), the percentage is 0.0 rather than a division error. The response carries `month`, `on_lease_car_days`, `eligible_car_days`, and `utilization_pct`.

### 3.13. Tariff Administration

The rate grid consists of tariff windows created by a `LeaseAdmin`, each naming a `car_type`, a `rate_kind` of `CAR_HIRE_BASE` (cents per day) or `MILEAGE_CREDIT` (cents per loaded mile), a half-open window from `effective_from` (inclusive) to `effective_to` (exclusive), and a positive `unit_rate_cents`. The window must be ordered — `effective_to` strictly after `effective_from` (`ERR_INVALID_DATE_RANGE`, 422) — and must not overlap any existing window for the same `(car_type, rate_kind)` pair; because windows are half-open, adjacency (one window's `effective_from` equal to another's `effective_to`) is allowed, while true overlap fails with `ERR_TARIFF_WINDOW_OVERLAP` (422). Tariffs are the inputs consumed by the assignment pinning of §3.4 and the statement variants of §3.7.

Amendment of an existing tariff is the OCC-guarded operation of §2.11: the caller supplies `expected_tariff_version` and optionally a new `unit_rate_cents`, `effective_from`, or `effective_to`. A successful amendment increments the tariff's `version` by 1, and the amended window is re-validated for overlap against the same `(car_type, rate_kind)` pair (`ERR_TARIFF_WINDOW_OVERLAP`, 422). A stale expected version fails with `ERR_STALE_VERSION` (412).

### 3.14. Retirement, Capital Pools, and Reinvestment

**Retirement.** A `FleetPlanner` proposes retiring a car by naming `railcar_id` and a `reason` of `AGE_LIMIT`, `DAMAGE_BEYOND_REPAIR`, `OBSOLESCENCE`, or `DIRECTIVE_ECONOMIC`; the case is `PROPOSED` and records the creator's `X-User-ID` as `proposer_user_id`. Appraisal (`PROPOSED → APPRAISED`, a `FleetPlanner` action) supplies non-negative `salvage_value_cents` and `book_value_cents`, and computes two figures: `impairment_loss_cents` is the amount by which book value exceeds salvage value, floored at zero; `reinvestment_credit_cents` equals the salvage value.

Approval (`APPRAISED → APPROVED`) belongs to a `ComplianceOfficer` and enforces the segregation of duties of §2.8 — the approver's `X-User-ID` must differ from `proposer_user_id` (`ERR_SOD_VIOLATION`, 403) — and requires the car to be `AVAILABLE` (`ERR_RETIREMENT_BLOCKED`, 409). Approval moves the car to `RETIREMENT_PENDING`. Execution (`APPROVED → EXECUTED`, a `FleetPlanner` action) requires a capital pool to exist for the fiscal year of the current logical date (`ERR_POOL_NOT_FOUND`, 404); it moves the car `RETIREMENT_PENDING → RETIRED`, stamps `retired_at`, and credits the pool: the pool's `replenishment_cents` increases by the case's `reinvestment_credit_cents`, and `available_cents` is recomputed per the waterfall below. A case may be cancelled from `PROPOSED`, `APPRAISED`, or `APPROVED`; cancelling an `APPROVED` case releases the car from `RETIREMENT_PENDING` back to `AVAILABLE` as compensation. `EXECUTED` and `CANCELLED` are terminal.

**Capital pools.** A `SystemAdmin` opens a reinvestment pool for a unique `fiscal_year` (duplicates fail with `ERR_DUPLICATE_POOL_YEAR`, 409) with a non-negative `opening_balance_cents`; the pool starts with `replenishment_cents`, `committed_cents`, and `delivered_spend_cents` all zero, so `available_cents` equals the opening balance. The pool's available funds follow a waterfall: `available_cents` is the opening balance plus replenishments minus committed funds minus delivered spend, where `replenishment_cents` sums the `reinvestment_credit_cents` of retirements executed in the pool's fiscal year, `committed_cents` sums the `unit_cost_cents` of commitments in `COMMITTED`, and `delivered_spend_cents` sums the `unit_cost_cents` of commitments in `DELIVERED`.

**Commitments.** A `FleetPlanner` commits pool funds to a replacement car through the OCC-guarded creation of §2.11, supplying `car_type`, a positive `unit_cost_cents`, and `expected_pool_version`. The created commitment carries the pool's identity as its `pool_id`. The affordability check requires `unit_cost_cents` to be at most the pool's `available_cents` at the observed pool version; exceeding it fails with `ERR_CAPITAL_POOL_INSUFFICIENT` (422), and a stale version fails with `ERR_STALE_VERSION` (412). Creation increments the pool's `version` by 1, adds the cost to `committed_cents`, and recomputes `available_cents`; the commitment is `COMMITTED` with `delivered_car_mark` null.

Delivery (`COMMITTED → DELIVERED`) supplies the new car's `car_mark` and `built_year`, moves the cost from `committed_cents` to `delivered_spend_cents`, recomputes `available_cents`, and cascade-creates the replacement railcar — registered with the supplied `car_mark`, the commitment's `car_type`, the supplied `built_year`, status `AVAILABLE` — recording its mark on the commitment as `delivered_car_mark`. Cancelling a `COMMITTED` commitment moves it to `CANCELLED`, subtracts its cost from `committed_cents`, and recomputes `available_cents` as exact compensation — committing an amount and later cancelling it restores the available funds exactly. `DELIVERED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions, amendments, and reads — return `200 OK`. All request bodies are JSON, and all responses use the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (default reading 2026-08-01T00:00:00Z before first set) | SystemAdmin |
| POST | `/lessees` | Register a lessee | LeaseAdmin |
| GET | `/lessees/{id}` | Get a lessee | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/lessees/{id}/reinstate` | Reinstate a suspended lessee | LeaseAdmin |
| POST | `/lessees/{id}/terminate` | Terminate a lessee with no open leases | LeaseAdmin |
| POST | `/railcars` | Register a railcar | FleetPlanner |
| GET | `/railcars` | List railcars with filters and pagination | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer |
| GET | `/railcars/{id}` | Get a railcar | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| GET | `/railcars/{id}/compliance` | Computed compliance view with both penalty variants | SystemAdmin, FleetPlanner, MaintenanceController, ComplianceOfficer, BillingAnalyst |
| GET | `/fleet/utilization` | Fleet utilization for a month | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst |
| POST | `/tariff-rates` | Create a tariff window (half-open) | LeaseAdmin |
| GET | `/tariff-rates` | List tariffs | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer |
| GET | `/tariff-rates/{id}` | Get a tariff | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer |
| PUT | `/tariff-rates/{id}` | Amend a tariff window/rate (OCC on version) | LeaseAdmin |
| POST | `/lease-agreements` | Create a lease in DRAFT | LeaseAdmin |
| GET | `/lease-agreements` | List leases (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer |
| GET | `/lease-agreements/{id}` | Get a lease (lazy EXPIRED evaluation) | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/lease-agreements/{id}/submit` | Submit lease for approval | LeaseAdmin |
| POST | `/lease-agreements/{id}/approve` | Approve lease | ComplianceOfficer |
| POST | `/lease-agreements/{id}/reject` | Reject lease back to DRAFT | ComplianceOfficer |
| PATCH | `/lease-agreements/{id}` | Amend lease terms (OCC on version); allowed in DRAFT or ACTIVE | LeaseAdmin |
| POST | `/lease-agreements/{id}/terminate` | Early-terminate an ACTIVE lease | LeaseAdmin |
| GET | `/lease-agreements/{id}/assignments` | Assignments of a lease | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer |
| POST | `/lease-assignments` | Assign a railcar to a lease (full validation chain; pins tariff snapshot) | FleetPlanner |
| GET | `/lease-assignments` | List assignments (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer |
| GET | `/lease-assignments/{id}` | Get an assignment | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/lease-assignments/{id}/deliver` | Deliver car to lessee | FleetPlanner |
| POST | `/lease-assignments/{id}/return` | Take car off lease; opens damage inspection | FleetPlanner |
| POST | `/lease-assignments/{id}/settle` | Close billing on a returned assignment | BillingAnalyst |
| POST | `/lease-assignments/{id}/cancel` | Cancel a scheduled assignment | FleetPlanner |
| POST | `/mileage-reports` | Lessee submits monthly mileage | LesseeRep |
| GET | `/mileage-reports` | List mileage reports (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer, LesseeRep |
| GET | `/mileage-reports/{id}` | Get a mileage report | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/mileage-reports/{id}/validate` | Validate (optionally correcting) reported miles | BillingAnalyst |
| POST | `/mileage-reports/{id}/dispute` | Billing disputes a validated report | BillingAnalyst |
| POST | `/mileage-reports/{id}/resubmit` | Lessee resubmits corrected miles | LesseeRep |
| POST | `/car-hire-statements/generate` | Generate provisional statements for a month, one per on-lease assignment | BillingAnalyst |
| GET | `/car-hire-statements` | List statements (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer, LesseeRep |
| GET | `/car-hire-statements/{id}` | Get a statement | SystemAdmin, LeaseAdmin, FleetPlanner, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/car-hire-statements/{id}/finalize` | Finalize with pinned tariffs and validated miles | BillingAnalyst |
| POST | `/car-hire-statements/{id}/dispute` | Lessee disputes a provisional statement | LesseeRep |
| POST | `/car-hire-statements/{id}/recompute` | Recompute a disputed statement back to PROVISIONAL | BillingAnalyst |
| POST | `/car-hire-statements/{id}/settle` | Record exact payment of a finalized statement | BillingAnalyst |
| POST | `/repair-authorizations` | Open a repair authorization | MaintenanceController |
| GET | `/repair-authorizations` | List repairs (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| GET | `/repair-authorizations/{id}` | Get a repair | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/repair-authorizations/{id}/preauthorize` | Lessee pre-authorizes its share above the cap | LesseeRep |
| POST | `/repair-authorizations/{id}/approve` | Approve estimate | MaintenanceController |
| POST | `/repair-authorizations/{id}/request-revision` | Send estimate back for revision | MaintenanceController |
| POST | `/repair-authorizations/{id}/revise` | Submit revised estimate | MaintenanceController |
| POST | `/repair-authorizations/{id}/reject` | Reject the repair | MaintenanceController |
| POST | `/repair-authorizations/{id}/start-work` | Begin work; shops the car when requires_shop | MaintenanceController |
| POST | `/repair-authorizations/{id}/complete` | Complete work at final cost | MaintenanceController |
| POST | `/cleaning-records` | Schedule a cleaning event | MaintenanceController |
| GET | `/cleaning-records` | List cleaning records (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, ComplianceOfficer |
| GET | `/cleaning-records/{id}` | Get a cleaning record | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, ComplianceOfficer |
| POST | `/cleaning-records/{id}/complete` | Record performed cleaning (from SCHEDULED or FAILED) | MaintenanceController |
| POST | `/cleaning-records/{id}/certify` | Certify a completed cleaning | ComplianceOfficer |
| POST | `/cleaning-records/{id}/fail` | Fail inspection of a completed cleaning | ComplianceOfficer |
| POST | `/damage-assessments` | Create a damage assessment in DRAFT | MaintenanceController |
| GET | `/damage-assessments` | List assessments (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| GET | `/damage-assessments/{id}` | Get an assessment | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, LesseeRep |
| POST | `/damage-assessments/{id}/submit` | Submit line items | MaintenanceController |
| POST | `/damage-assessments/{id}/dispute` | Lessee disputes submitted assessment | LesseeRep |
| POST | `/damage-assessments/{id}/resubmit` | Submit revised line items after dispute | MaintenanceController |
| POST | `/damage-assessments/{id}/finalize` | Freeze totals (per-line rounding) | MaintenanceController |
| POST | `/damage-assessments/{id}/invoice` | Invoice the lessee share | BillingAnalyst |
| POST | `/damage-assessments/{id}/record-payment` | Record exact payment | BillingAnalyst |
| POST | `/compliance-directives` | Announce a regulatory directive | ComplianceOfficer |
| GET | `/compliance-directives` | List directives | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer |
| GET | `/compliance-directives/{id}` | Get a directive | SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer |
| POST | `/compliance-directives/{id}/promote` | Make directive effective (cascade) | ComplianceOfficer |
| POST | `/retrofit-orders` | Schedule a retrofit for a car under a directive | MaintenanceController |
| GET | `/retrofit-orders` | List retrofit orders (filtered) | SystemAdmin, FleetPlanner, MaintenanceController, ComplianceOfficer |
| GET | `/retrofit-orders/{id}` | Get a retrofit order | SystemAdmin, FleetPlanner, MaintenanceController, ComplianceOfficer |
| POST | `/retrofit-orders/{id}/defer` | Defer a scheduled retrofit | MaintenanceController |
| POST | `/retrofit-orders/{id}/reschedule` | Reschedule a deferred retrofit | MaintenanceController |
| POST | `/retrofit-orders/{id}/start` | Start retrofit work | MaintenanceController |
| POST | `/retrofit-orders/{id}/complete` | Complete retrofit work | MaintenanceController |
| POST | `/retrofit-orders/{id}/certify` | Certify completed retrofit | ComplianceOfficer |
| POST | `/retrofit-orders/{id}/cancel` | Cancel a scheduled/deferred retrofit | MaintenanceController |
| POST | `/retirement-cases` | Propose retiring a railcar | FleetPlanner |
| GET | `/retirement-cases` | List retirement cases (filtered) | SystemAdmin, LeaseAdmin, FleetPlanner, ComplianceOfficer |
| GET | `/retirement-cases/{id}` | Get a retirement case | SystemAdmin, LeaseAdmin, FleetPlanner, ComplianceOfficer |
| POST | `/retirement-cases/{id}/appraise` | Record salvage and book values | FleetPlanner |
| POST | `/retirement-cases/{id}/approve` | Approve retirement (approver must differ from proposer) | ComplianceOfficer |
| POST | `/retirement-cases/{id}/execute` | Execute retirement; replenishes capital pool | FleetPlanner |
| POST | `/retirement-cases/{id}/cancel` | Cancel a non-executed retirement | FleetPlanner |
| POST | `/capital-pools` | Open a reinvestment capital pool for a fiscal year | SystemAdmin |
| GET | `/capital-pools/{id}` | Get a capital pool | SystemAdmin, FleetPlanner, ComplianceOfficer, BillingAnalyst |
| POST | `/capital-pools/{id}/commitments` | Commit pool funds to a replacement car (OCC on pool version) | FleetPlanner |
| GET | `/capital-pools/{id}/commitments` | List commitments of a pool | SystemAdmin, FleetPlanner, ComplianceOfficer, BillingAnalyst |
| GET | `/capital-pools/{poolId}/commitments/{id}` | Get a commitment | SystemAdmin, FleetPlanner, ComplianceOfficer, BillingAnalyst |
| POST | `/capital-pools/{poolId}/commitments/{id}/deliver` | Deliver the replacement car | FleetPlanner |
| POST | `/capital-pools/{poolId}/commitments/{id}/cancel` | Cancel a commitment (funds restored) | FleetPlanner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_LESSEE_NOT_FOUND` | 404 |
| `ERR_RAILCAR_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_REPAIR_NOT_FOUND` | 404 |
| `ERR_CLEANING_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_DIRECTIVE_NOT_FOUND` | 404 |
| `ERR_RETROFIT_NOT_FOUND` | 404 |
| `ERR_RETIREMENT_NOT_FOUND` | 404 |
| `ERR_POOL_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LEASE_NOT_ACTIVE` | 409 |
| `ERR_RAILCAR_NOT_AVAILABLE` | 409 |
| `ERR_LESSEE_NOT_ACTIVE` | 409 |
| `ERR_ASSIGNMENT_NOT_RETURNED` | 409 |
| `ERR_STATEMENT_NOT_PROVISIONAL` | 409 |
| `ERR_REPORT_NOT_VALIDATED` | 409 |
| `ERR_DAMAGE_ASSESSMENT_OPEN` | 409 |
| `ERR_OPEN_REPAIR_ORDERS` | 409 |
| `ERR_RETIREMENT_BLOCKED` | 409 |
| `ERR_AGE_LIMIT_EXCEEDED` | 422 |
| `ERR_TANK_CAR_NONCOMPLIANT` | 422 |
| `ERR_COMMODITY_INCOMPATIBLE` | 422 |
| `ERR_TARIFF_NOT_FOUND` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_OUTSIDE_LEASE_TERM` | 422 |
| `ERR_ASSIGNMENT_OVERLAP` | 422 |
| `ERR_CLEANING_BUFFER_VIOLATION` | 422 |
| `ERR_TARIFF_WINDOW_OVERLAP` | 422 |
| `ERR_REPORT_MONTH_MISMATCH` | 422 |
| `ERR_RETROFIT_DEADLINE_PASSED` | 422 |
| `ERR_DUPLICATE_CAR_MARK` | 409 |
| `ERR_DUPLICATE_DIRECTIVE_CODE` | 409 |
| `ERR_DUPLICATE_POOL_YEAR` | 409 |
| `ERR_DUPLICATE_REPORT_MONTH` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_CAPITAL_POOL_INSUFFICIENT` | 422 |
| `ERR_REPAIR_PREAUTH_REQUIRED` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 422 |
| `ERR_PAYMENT_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |

# Section 8 Housing Voucher API — Product Requirements Document

## 1. Introduction

The federal Housing Choice Voucher program (commonly called "Section 8") is administered locally by Public Housing Authorities (PHAs), each of which must reconcile an extraordinary number of moving parts: the income picture of an applicant household, the bedroom-size entitlement that flows from household composition, the Payment Standard tier that sets the program's ceiling for a given geography, the Housing Quality Standards (HQS) annual inspection cycle, the rent-reasonableness check that defends federal dollars against above-market rents, and the inter-PHA portability process that lets households relocate without losing assistance. Field staff today reconcile these flows across spreadsheets and ad-hoc systems; the resulting drift in calculations and missed deadlines translates directly into program-integrity findings and tenant hardship.

This API is the system of record for one PHA's voucher pipeline. It expresses the program rules as machine-checkable contracts so that caseworkers, inspectors, landlords, and applicants all see the same numbers, the same deadlines, and the same cascades when a deadline lapses. The benchmark for "correct" here is operational and fiscal: an annual review that approves on the wrong day, a rent-burden gate that rounds the wrong direction, or a portability absorption that fails to suppress next-month's HAP payment is not a minor bug — it is a federal compliance defect. The endpoints, calculations, and state machines below are written with that bar in mind.

The system mounts under the path prefix `/housing-voucher`. All paths in §4 are relative to this prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID` and `X-User-Role`. If either header is missing, the request is rejected with `ERR_AUTH_REQUIRED` at HTTP 401. If `X-User-Role` is not one of the six configured roles — `Applicant`, `Landlord`, `Inspector`, `CaseWorker`, `PortabilityCoordinator`, or `PHAAdmin` — or if the named role is not permitted to invoke the requested endpoint per the §4 authorization matrix, the request is rejected with `ERR_FORBIDDEN_ROLE` at HTTP 403.

Five of the six roles are entity-backed. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks compare resource foreign-key fields (the `applicant_id` on a `Voucher`, or the `Voucher.applicant_id` reached transitively from a `Tenancy.voucher_id`) to `X-User-ID`. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`, and the `Unit.landlord_id` field on each unit is compared to `X-User-ID` for ownership; for HAP payment visibility the chain `Tenancy.unit_id → Unit.landlord_id` is walked and compared to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` and is used to scope inspection-completion authority to the inspector's own PHA. When `X-User-Role` is `CaseWorker`, `X-User-ID` is the `id` of the acting `CaseWorker`. When `X-User-Role` is `PortabilityCoordinator`, `X-User-ID` is the `id` of the acting `PortabilityCoordinator`.

When `X-User-Role` is `PHAAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`; admin authority follows from the role string alone.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a request that exceeds the maximum or falls below the minimum is rejected as a validation failure (`ERR_VALIDATION`). `offset` defaults to 0 and must be non-negative. Results are always returned sorted by `created_at` in ascending order, so paging never reshuffles already-seen rows. The pagination `meta` block on list responses carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the filtered set before pagination and `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every entity with full common fields (Applicant, Voucher, Unit, Tenancy, Inspection, AnnualReview, PortabilityRequest) carries four server-managed properties: `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC timestamp with three fractional digits, set on creation and never modified), `updated_at` (same format, refreshed on every mutation including cascade-driven mutations from other resources), and `version` (a monotonically increasing integer that starts at 1 and increments by 1 on every mutation, including cascade-driven mutations).

Two entities carry only `id` and `created_at` because they are append-only configuration or ledger records: `PaymentStandard` (which is versioned through its own `effective_from` field rather than through a `version` integer) and `HAPPayment` and `RentReasonablenessRecord` (which are immutable once written). For those three entities, both `updated_at` and `version` are absent from the response payload.

### 2.5. Optimistic Concurrency Control

Every mutation that targets an existing resource accepts an optional `version` integer in the request body. When the caller omits `version`, no concurrency check runs and the mutation proceeds last-write-wins on the targeted fields. When the caller supplies `version` and it does not match the resource's current `version`, the request is rejected with `ERR_INVALID_STATE` at HTTP 409. Callers who care about lost-update protection are expected to read the resource, capture its `version`, and echo that value back on the next mutation.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values cross the API as integer **cents**. The system never serializes a dollar string or a floating-point dollar amount; the burden of converting between cents and the dollar values shown in user interfaces sits at the presentation layer, not in the API. Intermediate steps inside calculations specify their rounding direction explicitly — some quantities are floored (whole-month income divisions, median thresholds), others are ceilinged (percentage applications inside the total-tenant-payment computation), and the rent-burden gate is performed in exact rational arithmetic to avoid floating-point drift. Where a rounding rule is pinned in §3, it is pinned because reversing the order would shift cent values across the test boundary.

Aggregations into dollars for downstream reporting are taken in cents first, then divided by 100 with floor at the reporting layer — never by converting each row to dollars and summing. This is the pinned order for any reporting endpoint that sums across HAP payment rows.

### 2.7. Time and the Logical Clock

Time-gated transitions in this system — voucher expiration, inspection cure deadlines, the annual-review submission window, the 14-day deficient-cure window — all read from a single server-maintained logical clock. In a deployed environment the clock tracks wall-clock UTC. For test and replay purposes, the clock can be advanced explicitly by a `PHAAdmin` capability that accepts a `to_timestamp` payload and sets the logical clock to that instant. All `created_at`, `updated_at`, `issued_at`, `requested_at`, `submitted_at`, `decided_at`, `completed_at`, `scheduled_for`, `recorded_at`, and derived deadline fields (`search_deadline`, `cure_deadline`, `next_annual_inspection_due`, `review_due_date`) read from this clock. Sweeps are idempotent: re-running a sweep after the clock has advanced only further processes rows whose deadlines have actually elapsed.

### 2.8. Nested Resource Retrieval

When an endpoint contains nested path parameters (for example a hypothetical path that walks voucher → tenancy → inspection), each path id is resolved left-to-right. Each missing id yields `ERR_NOT_FOUND` at HTTP 404 immediately, without consulting the body, the role, or the deeper segments. Parent-child consistency (the named tenancy actually belongs to the named voucher) is checked after each successful lookup and also yields `ERR_NOT_FOUND` when violated.

### 2.9. Hierarchical Consistency and Cascade Discipline

State transitions on a parent or child entity routinely cascade into related entities. When a Tenancy advances from `PENDING_RENT_REASONABLE` to `ACTIVE`, the parent `Voucher` is cascaded from `SEARCHING` (or `SEARCHING_REISSUED`) to `LEASED`; when an `AnnualReview` is denied, the `Tenancy` cascades to `TERMINATED` and the `Voucher` cascades to `TERMINATED`; when a `PortabilityRequest` is absorbed, the `Voucher` cascades to `PORTED_OUT` and any active `Tenancy` cascades to `TERMINATED` with reason `PORTABILITY_ABSORBED`. Every cascade-driven mutation refreshes the affected entity's `updated_at` and increments its `version`, so a stale-version optimistic-concurrency check on the cascaded entity will fail exactly as it would for a directly-targeted mutation. The system enforces these cascades immediately and synchronously inside the originating request — there is no eventually-consistent delay between Tenancy termination and Voucher termination.

### 2.10. Validation Priority and Evaluation Order

When a single request can fail multiple gates, the system evaluates them in a pinned priority sequence so that the returned `error_id` is deterministic. The order is: authentication (header presence, then role-string validity), path-id existence (left-to-right), body-referenced foreign-key existence, state preconditions, voucher search-window expiration, then PHA-locality, then inspector-scope, then the business-safety and business-constraint checks in the order listed below.

Concretely, on `POST /tenancies/{id}/finalize` the gates run in this order: header presence (`ERR_AUTH_REQUIRED`), role validity (`ERR_FORBIDDEN_ROLE`), the tenancy id exists (`ERR_NOT_FOUND`), the tenancy is in `PENDING_RENT_REASONABLE` (`ERR_INVALID_STATE`), the voucher's `search_deadline` has not passed (`ERR_VOUCHER_EXPIRED`), the voucher is locally administered (`ERR_VOUCHER_NOT_LOCAL`), the special-mobility zone constraint holds (`ERR_MOBILITY_ZONE_VIOLATION`), the rent-reasonableness record is favorable (`ERR_RENT_NOT_REASONABLE`), the rent-burden divide-by-zero check (`ERR_RENT_BURDEN_DIVZERO`), and finally the rent-burden ceiling itself (`ERR_RENT_BURDEN_EXCEEDED`). This ordering is binding — a request that fails three of these gates simultaneously must surface the highest-priority one. For create or update endpoints whose request body carries foreign-key references (`applicant_id`, `voucher_id`, `unit_id`, `tenancy_id`, `receiving_pha_id`), each foreign key is dereferenced after the path-existence gate and before any state precondition; an unresolved body-referenced foreign key surfaces as `ERR_FK_NOT_FOUND` at HTTP 422. Generic body-shape failures (malformed datetime, negative cents) that are not caught by a more specific code surface as `ERR_VALIDATION` at HTTP 422.

### 2.11. State Enumeration Reference

The following state values are referenced throughout §3 and appear verbatim in API responses:

- `Voucher.status` ∈ {`ISSUED`, `SEARCHING`, `LEASED`, `SEARCHING_REISSUED`, `PORTED_OUT`, `EXPIRED`, `TERMINATED`, `REVOKED`}.
- `Tenancy.status` ∈ {`PENDING_INSPECTION`, `PENDING_RENT_REASONABLE`, `ACTIVE`, `ABATED`, `TERMINATED`, `REJECTED`}.
- `Tenancy.termination_reason` ∈ {`HQS_UNCURED`, `ANNUAL_REVIEW_DENIED`, `TENANT_MOVE_OUT`, `PORTABILITY_ABSORBED`, `NULL`}.
- `Inspection.status` ∈ {`SCHEDULED`, `COMPLETED_PASS`, `COMPLETED_FAIL_CURABLE`, `COMPLETED_FAIL_LIFETHREAT`, `CURED`, `EXPIRED_UNCURED`}.
- `Inspection.outcome` ∈ {`PASS`, `FAIL_NONLIFETHREATENING`, `FAIL_LIFETHREATENING`, `CURED`}.
- `Inspection.inspection_type` ∈ {`INITIAL`, `ANNUAL`, `REINSPECTION`}.
- `AnnualReview.status` ∈ {`DUE`, `SUBMITTED`, `DEFICIENT`, `APPROVED`, `DENIED`}.
- `PortabilityRequest.outcome` ∈ {`INITIATED`, `ABSORBED`, `BILLED`, `DENIED`}.
- `PortabilityRequest.denial_reason` ∈ {`RECEIVING_PHA_OVER_LEASING_CAP`, `INELIGIBLE_HOUSEHOLD`, `MOBILITY_ZONE_RESTRICTION`, `NULL`}.
- `Unit.occupancy_status` ∈ {`VACANT`, `OCCUPIED_PENDING`, `OCCUPIED_ACTIVE`, `OCCUPIED_ABATED`}.
- `Applicant.income_band` ∈ {`EXTREMELY_LOW`, `VERY_LOW`, `LOW`, `OVER_INCOME`}.
- `Applicant.eligibility_status` ∈ {`PENDING`, `ELIGIBLE`, `INELIGIBLE`}.
- `HAPPayment.status` ∈ {`PAID`, `ABATED_SUSPENDED`, `VOIDED_RETROACTIVE`}.
- `HAPPayment.event_ref_type` ∈ {`SCHEDULED_MONTHLY`, `ABATEMENT`, `AR_RECALC`, `PORTABILITY_CLOSEOUT`}.
- `zone` values used by `Voucher`, `Unit`, and `PaymentStandard` ∈ {`ZONE_A`, `ZONE_B`, `ZONE_C`}.
- `bedroom_size` values used by `Voucher` and `PaymentStandard` ∈ {`0`, `1`, `2`, `3`, `4`, `5`}.

### 2.12. Concurrency Posture

Six concurrent-write scenarios are explicitly engineered into the system, each with a pinned serialization point and a pinned loser `error_id`:

- Two `CaseWorker` operators finalizing the same Tenancy at the same instant: serialization is first-writer-wins on `Tenancy.status`; exactly one finalize advances `PENDING_RENT_REASONABLE → ACTIVE`, the loser receives `ERR_INVALID_STATE` because the tenancy is no longer in `PENDING_RENT_REASONABLE`.
- Two Tenancies submitted on the same `VACANT` Unit at the same instant: serialization is first-writer-wins on `Unit.occupancy_status`; one tenancy is accepted and flips occupancy to `OCCUPIED_PENDING`, the loser receives `ERR_UNIT_NOT_VACANT`.
- A voucher-expiration sweep running concurrently with a Tenancy finalize on the same voucher: serialization is first-writer-wins on `Voucher.status`; if the sweep wrote `EXPIRED` first, finalize is rejected with `ERR_VOUCHER_EXPIRED`; if finalize wrote `ACTIVE` first, the sweep skips that voucher.
- A `PortabilityRequest` absorb running concurrently with a new Tenancy creation on the same voucher: serialization is first-writer-wins on `Voucher.administering_pha_id`; once the absorb flips administering PHA, the new tenancy receives `ERR_VOUCHER_NOT_LOCAL`.
- Two Inspectors marking complete on the same `SCHEDULED` Inspection: serialization is first-writer-wins on `Inspection.status`; the loser receives `ERR_INSPECTION_ALREADY_COMPLETED`.
- Two CaseWorkers, one approving and one denying the same AnnualReview at the same instant: serialization is first-writer-wins on `AnnualReview.status`; the loser receives `ERR_INVALID_STATE` because the review has already left `SUBMITTED`.

## 3. Business Logic & Workflows

### 3.1. The Applicant Household and Initial Income Determination

Every voucher begins life with an applicant household, registered by either the household head themselves or by a `CaseWorker` on their behalf. The application payload carries the head-of-household legal name (`household_name`), the total persons in the household (`household_size`, which must be at least 1 and no more than 20), the count of dependents claimed for the dependent allowance (`dependents_count`, which must be zero or more and may not exceed `household_size`), a boolean (`elderly_or_disabled_head`) indicating whether the head qualifies for the elderly/disabled allowance, the self-reported gross household income in cents (`gross_annual_income_cents`, zero or more), an optional childcare expense in cents (`childcare_expense_annual_cents`, defaulting to 0), and an optional medical expense in cents (`medical_expense_annual_cents`, defaulting to 0).

Upon creation, the system immediately runs the initial adjusted-income computation and writes the result to `adjusted_annual_income_cents`. The mechanics are: a per-dependent allowance of $480 per dependent (forty-eight thousand cents per dependent) is summed for the household. If the head is elderly or disabled, a single household-level allowance of $400 (forty thousand cents) is added. The medical deduction is calculated only when the head is elderly or disabled, and only for the portion of the declared medical expense that exceeds three percent of gross annual income — the floor of gross times 0.03 is the medical threshold, and the deduction is the medical expense minus that threshold (zero if the expense does not exceed the threshold, or if the household does not qualify because the head is neither elderly nor disabled). The childcare deduction is the smaller of the declared childcare expense and the gross annual income (the latter functions as a hard cap so that childcare alone cannot drive a household to negative income). All four deductions — dependent, elderly, medical, childcare — are summed; the adjusted income is the gross minus the total deductions, floored at zero. All values remain in integer cents throughout; the medical threshold uses floor, and no other monetary rounding is applied at the output of this calculation.

Once the adjusted income is known, the household is classified into an `income_band` of `EXTREMELY_LOW`, `VERY_LOW`, `LOW`, or `OVER_INCOME` against the PHA's configured HUD limits, and the `eligibility_status` is set: a household whose adjusted income lands in `EXTREMELY_LOW`, `VERY_LOW`, or `LOW` becomes `ELIGIBLE`; one in `OVER_INCOME` becomes `INELIGIBLE`. A `PHAAdmin` may subsequently revoke an applicant's eligibility before any voucher has progressed past `ISSUED`; this revocation forces `eligibility_status` to `INELIGIBLE` and cascades any voucher still in `ISSUED` to `REVOKED`.

### 3.2. Voucher Issuance and the 120-Day Search Window

A `CaseWorker` issues a voucher to an `ELIGIBLE` applicant by submitting the `applicant_id`, the `zone` (one of `ZONE_A`, `ZONE_B`, `ZONE_C`), an optional `special_mobility_flag` (defaulting to false), and the `administering_pha_id` — which must be one of the configured PHAs in the network (the test deployment ships with `PHA_001`, `PHA_002`, and `PHA_003`). The system sets `issued_at` to the current logical-clock instant, computes the authorized `bedroom_size` from `household_size` using the PHA occupancy table (a 1-person household is authorized 0 bedrooms, 2 persons get 1 bedroom, 3 or 4 persons get 2 bedrooms, 5 or 6 persons get 3 bedrooms, 7 or 8 persons get 4 bedrooms, and 9 or more persons get 5 bedrooms), sets `search_deadline` to `issued_at` plus 120 days, and immediately advances the voucher's `status` from `ISSUED` to `SEARCHING`. `ISSUED` is a momentary state — by the time any caller reads the voucher back, it has already moved to `SEARCHING`.

On every read, the system recomputes `remaining_search_days` live: it is the count of days between the current logical-clock instant and `search_deadline`, which goes negative once the deadline has passed. If the search window elapses without a successful tenancy — either via the explicit voucher-expiration sweep or as a logical-clock advance crosses `search_deadline` — and no tenancy on this voucher is in `ACTIVE` or in a `PENDING_*` posture, the voucher transitions from `SEARCHING` to `EXPIRED`, which is terminal.

When the special-mobility program flag is set, the voucher is constrained to lease only into an opportunity zone (specifically `ZONE_A`) and uses the mobility tier of the Payment Standard table. A tenancy attempt that violates this constraint at lease-up is rejected with `ERR_MOBILITY_ZONE_VIOLATION`.

### 3.3. Units, Landlords, and the Payment Standard Configuration

A `Landlord` registers a unit by supplying its `street_address`, `zone`, `bedroom_count` (the unit's physical bedrooms, between 0 and 6 inclusive), the proposed monthly contract rent (`asking_rent_cents`, strictly greater than zero), and an optional PHA-supplied utility allowance for tenant-paid utilities at this zone-and-bedroom cell (`tenant_paid_utilities_cents`, defaulting to 0). The system tracks two computed timestamps on the unit: `last_inspection_passed_at` (the most recent inspection with outcome `PASS` or `CURED`; null if the unit has never been inspected) and `next_annual_inspection_due` (which is `last_inspection_passed_at` plus 365 days, recomputed on every read). The `occupancy_status` is derived from the presence of an active tenancy: `VACANT` when no tenancy occupies the unit, `OCCUPIED_PENDING` when a tenancy exists but has not yet reached `ACTIVE`, `OCCUPIED_ACTIVE` when the tenancy is `ACTIVE`, and `OCCUPIED_ABATED` when the tenancy is in `ABATED`.

The Payment Standard table is the PHA's published ceiling for HAP — one row per combination of `zone` and `bedroom_size` (so 18 rows for the three zones and six bedroom-sizes), with a `standard_amount_cents` for normal vouchers and a `mobility_amount_cents` for the special-mobility tier. The mobility amount is constrained to be at least equal to the standard amount and is typically set to 110 percent of it, rounded to the nearest cent. Each row carries an `effective_from` timestamp; the active row for any (zone, bedroom-size) cell is the one with the latest `effective_from` that is less than or equal to the current logical-clock instant. The list endpoint for Payment Standards accepts an `active_only` filter that, when true, returns only the currently-active row per cell. `PHAAdmin` configures these rows; `CaseWorker` and `Landlord` may read them.

### 3.4. RFTA: From Searching Voucher to a Pending Tenancy

A Request for Tenancy Approval (RFTA) is submitted by a `Landlord` or `CaseWorker` against a specific `voucher_id` and `unit_id`, with a proposed `lease_start` date. The voucher must be in `SEARCHING` or `SEARCHING_REISSUED`; otherwise the request is rejected with `ERR_INVALID_STATE`. The voucher's `search_deadline` must not have passed (otherwise `ERR_VOUCHER_EXPIRED`); the voucher's `administering_pha_id` must match the PHA serving the request (otherwise `ERR_VOUCHER_NOT_LOCAL`, which forces cross-PHA actions through the portability process); the unit must be `VACANT` (otherwise `ERR_UNIT_NOT_VACANT`); and no prior non-terminated tenancy on this unit may have a `[requested_at, terminated_at)` interval that overlaps the proposed tenancy — a unit's previous tenancy must have its `terminated_at` strictly before the next tenancy's `requested_at` (no same-day occupancy; the interval is closed at start and open at end). A violation here returns `ERR_UNIT_OCCUPANCY_OVERLAP`. The under-housing guard applies: when the voucher's authorized `bedroom_size` is at least 1, the unit's `bedroom_count` must also be at least 1 (the system refuses to lease a 0-bedroom unit to a household entitled to a 1-or-larger bedroom voucher), or the request is rejected with `ERR_UNIT_TOO_SMALL`. The proposed `lease_start` must be no later than the voucher's `search_deadline` (otherwise `ERR_LEASE_START_AFTER_DEADLINE`).

When all gates pass, the tenancy is created with `status` of `PENDING_INSPECTION` and the unit's `occupancy_status` flips to `OCCUPIED_PENDING`. Two financial fields are frozen onto the tenancy at this moment and never recomputed for the life of the tenancy: `gross_rent_cents`, the sum of the unit's `asking_rent_cents` and `tenant_paid_utilities_cents`; and `applicable_payment_standard_cents`, looked up from the Payment Standard table for the (voucher zone, smaller of voucher `bedroom_size` and unit `bedroom_count`) cell — using `standard_amount_cents` for normal vouchers or `mobility_amount_cents` for special-mobility vouchers, with the active row selected by the latest `effective_from` not after the tenancy's `requested_at`. The `requested_at` timestamp itself is set by the system to the current logical-clock instant.

### 3.5. HQS Inspections, Cure Windows, and the Abatement-or-Termination Branch

Inspections are scheduled by an `Inspector` or `CaseWorker` against a `tenancy_id`, with an `inspection_type` (`INITIAL`, `ANNUAL`, or `REINSPECTION`) and a `scheduled_for` timestamp. The system copies `unit_id` from the parent tenancy onto the inspection at creation. A guard rejects any new `ANNUAL` inspection scheduled less than 365 days after the last passing inspection on the same unit; adjacency at exactly 365 days is permitted (the gap is closed-closed on the year boundary), and a violation returns `ERR_INSPECTION_TOO_SOON`.

When the inspector files results via the completion capability, the request body carries `outcome` and `defects`. The outcome and defects must agree: `PASS` requires an empty `defects` array, while any `FAIL_*` outcome requires a non-empty `defects` array — a mismatch yields `ERR_INSPECTION_OUTCOME_MISMATCH`. Filing on an inspection already in a `COMPLETED_*` posture yields `ERR_INSPECTION_ALREADY_COMPLETED`. An `Inspector` may only complete inspections whose tenancy's voucher is administered by the inspector's own PHA; a violation returns `ERR_INSPECTOR_OUT_OF_SCOPE`. The system sets `completed_at` to the current logical-clock instant.

A `PASS` outcome transitions the inspection to `COMPLETED_PASS`. If this was the `INITIAL` inspection for a tenancy in `PENDING_INSPECTION`, the tenancy advances to `PENDING_RENT_REASONABLE`, and the unit's `last_inspection_passed_at` is set to `completed_at` (which, in turn, refreshes `next_annual_inspection_due` to `last_inspection_passed_at` plus 365 days).

A `FAIL_NONLIFETHREATENING` outcome transitions the inspection to `COMPLETED_FAIL_CURABLE` and sets `cure_deadline` to `completed_at` plus 30 days. A `FAIL_LIFETHREATENING` outcome transitions the inspection to `COMPLETED_FAIL_LIFETHREAT` and sets `cure_deadline` to `completed_at` plus 24 hours. Either failure branch on an `INITIAL` inspection blocks the tenancy from progressing past `PENDING_INSPECTION` until cure; either branch on an `ANNUAL` inspection of an `ACTIVE` tenancy cascades the tenancy to `ABATED`, sets `abatement_started_at` to `completed_at`, generates the next-month HAP payment row with `amount_cents` of 0 and `status` of `ABATED_SUSPENDED`, and flips the unit's `occupancy_status` to `OCCUPIED_ABATED`.

A subsequent `REINSPECTION` filed with outcome `CURED` before the original `cure_deadline` (24 hours for life-threatening, 30 days for non-life-threatening) transitions the failed inspection to `CURED`. If the parent tenancy was `ABATED`, it cascades back to `ACTIVE`, the unit's `occupancy_status` returns to `OCCUPIED_ACTIVE`, the unit's `last_inspection_passed_at` and `next_annual_inspection_due` are refreshed from the reinspection's `completed_at`, and the next-month HAP payment resumes at the tenancy's current HAP amount. If the parent tenancy was `PENDING_INSPECTION` (the cure of a failed initial inspection), it advances to `PENDING_RENT_REASONABLE`.

If the cure deadline elapses without a `CURED` reinspection — discovered either by the abatement sweep or by a clock advance — the failed inspection transitions to `EXPIRED_UNCURED`. For an initial inspection, the tenancy cascades from `PENDING_INSPECTION` to `REJECTED`, the unit's `occupancy_status` returns to `VACANT`, and the voucher remains `SEARCHING` (no transition). For an annual inspection of an `ACTIVE` tenancy that had gone to `ABATED`, the tenancy cascades to `TERMINATED` with `termination_reason` `HQS_UNCURED`, the voucher cascades from `LEASED` to `TERMINATED` (uncured HQS is a program violation, so the voucher is not reissued for further search), the unit's `occupancy_status` returns to `VACANT`, and all future scheduled HAP payment rows for this voucher are suppressed.

### 3.6. Rent Reasonableness

Before a tenancy can finalize, the proposed rent must be defended against above-market pricing. A `CaseWorker` attaches a rent-reasonableness record by submitting a `tenancy_id` and an array of `comparable_rents_cents` — monthly rents in integer cents of comparable units in the same `zone` with the same `bedroom_count`. The array must contain at least 3 entries; an array with fewer is rejected with `ERR_INSUFFICIENT_COMPARABLES`. The system sets `recorded_at` to the current logical-clock instant.

The system sorts the comparables ascending and computes `median_comparable_cents`. For an odd-length array, the median is the middle element (the element at index `(n-1)/2` after sorting). For an even-length array, the median is the **lower** of the two middle elements (not the arithmetic mean) — this tie-break is pinned because the mean could land between two cents and create downstream rounding ambiguity. The reasonable-threshold (`reasonable_threshold_cents`) is then the floor of the median multiplied by 1.10. The record's `is_reasonable` boolean is true when the tenancy's frozen `gross_rent_cents` is less than or equal to `reasonable_threshold_cents`, and false otherwise — a gross rent exactly equal to the floor of (median × 1.10) is reasonable; one cent above it is not. The computation also updates the parent tenancy's `rent_reasonable` field, which had been null since tenancy creation.

### 3.7. Finalize: From Pending to Active, with TTP and HAP

Once a passing initial inspection has moved the tenancy to `PENDING_RENT_REASONABLE` and a favorable rent-reasonableness record is attached, a `CaseWorker` finalizes the tenancy. The finalize capability accepts no body fields beyond the version envelope; it runs three gating checks in the order pinned in §2.10 and then performs the lease-up calculations and cascades.

The first finalize-time gate is the special-mobility zone check: if the voucher's `special_mobility_flag` is true, the unit's `zone` must equal `ZONE_A`, or the finalize is rejected with `ERR_MOBILITY_ZONE_VIOLATION`. The second is the rent-reasonableness gate: the attached rent-reasonableness record's `is_reasonable` must be true, or the finalize is rejected with `ERR_RENT_NOT_REASONABLE`. The third pair of gates concerns rent burden: if the applicant's `adjusted_annual_income_cents` is zero, the rent-burden ratio is undefined and the finalize is rejected with `ERR_RENT_BURDEN_DIVZERO` (this is intentionally a separate failure mode from the burden-exceeded case so that the test surface can distinguish "income missing" from "income too low"). Otherwise the rent-burden check itself is evaluated.

The rent-burden computation works as follows. Compute the monthly adjusted income as the floor of the applicant's `adjusted_annual_income_cents` divided by 12. Compute the tenant share at lease-up as the tenancy's `gross_rent_cents` minus the initial HAP. The burden ratio is the tenant share at lease-up divided by the monthly adjusted income — performed in exact rational arithmetic, never in floating-point, by the equivalent integer comparison: the tenant share multiplied by 100 must be less than or equal to 40 multiplied by the monthly adjusted income. The cap of 0.40 is **inclusive** — a burden exactly equal to 40 percent passes; a burden strictly greater than 40 percent is rejected with `ERR_RENT_BURDEN_EXCEEDED`. The computed `rent_burden_at_lease_up_pct` is recorded on the tenancy as a decimal number for visibility; it is the tenant share divided by the monthly adjusted income.

The initial total tenant payment (TTP) is the maximum of four floors: thirty percent of monthly adjusted income, ten percent of monthly gross income, the welfare-rent floor (`WELFARE_RENT_CENTS`, configured at 0 cents for non-welfare households), and the statutory minimum rent floor (`MINIMUM_RENT_CENTS`, configured at $50 per month — five thousand cents). The percent-of-income figures are computed in a specific order: monthly adjusted income is the floor of annual adjusted income divided by 12, and the thirty-percent figure is then the ceiling of monthly adjusted income times 0.30; monthly gross income is likewise the floor of annual gross income divided by 12, and the ten-percent figure is the ceiling of monthly gross income times 0.10. This rounding order is pinned: divide-then-floor first, then multiply-then-ceil — reversing the order produces different cent values. The maximum of these four candidates becomes `initial_total_tenant_payment_cents`.

The initial HAP (Housing Assistance Payment) is the smaller of `applicable_payment_standard_cents` (already frozen on the tenancy) and `gross_rent_cents`, minus the initial TTP, then floored at zero. The result is written to `initial_hap_cents`. Both `initial_total_tenant_payment_cents` and `initial_hap_cents` are then mirrored into `current_total_tenant_payment_cents` and `current_hap_cents` so that the steady-state ledger has a starting point.

When all three gates pass and the calculations complete, the tenancy advances from `PENDING_RENT_REASONABLE` to `ACTIVE`, the voucher cascades from `SEARCHING` (or `SEARCHING_REISSUED`) to `LEASED`, the unit's `occupancy_status` flips to `OCCUPIED_ACTIVE`, and the first DUE annual review is created on the tenancy with `review_due_date` set to `lease_start` plus 365 days. The first scheduled HAP payment row is then generated by the next monthly-ledger sweep that crosses into a new calendar month.

If any of the three finalize gates fails, the tenancy cascades to `REJECTED`, the unit's `occupancy_status` returns to `VACANT`, and the voucher remains `SEARCHING` with its original `search_deadline` intact — the applicant has not lost search time to a failed lease-up attempt.

### 3.8. Tenant Move-Out and Voucher Re-Issuance

A `CaseWorker` may initiate a tenant-initiated move-out with continued assistance by supplying a `move_out_date`. The tenancy cascades to `TERMINATED` with `termination_reason` `TENANT_MOVE_OUT`, the unit's `occupancy_status` returns to `VACANT`, and the voucher cascades from `LEASED` to `SEARCHING_REISSUED` with a fresh re-search window: `search_deadline` becomes `move_out_date` plus 60 days. The 60-day re-search window applies regardless of `special_mobility_flag`. Any annual review on the terminated tenancy that was in `DUE` auto-closes as void (it neither approves nor denies). When a subsequent tenancy on this same voucher reaches `ACTIVE`, the voucher transitions from `SEARCHING_REISSUED` to `LEASED` again. If the re-search window also elapses without a successful tenancy, the voucher transitions from `SEARCHING_REISSUED` to `EXPIRED`.

### 3.9. The Annual Review Cycle

When a tenancy reaches `ACTIVE`, a DUE annual review row is scheduled for one year out (`review_due_date` = `lease_start` + 365 days). The applicant is responsible for submitting updated income and household-size information within the 30-day window centered on `review_due_date`; specifically, the submission timestamp must lie within 30 days before or after `review_due_date`, or it is rejected with `ERR_REVIEW_WINDOW_CLOSED`.

The submission body carries `declared_gross_annual_income_cents` and `declared_household_size`. On submission, the review transitions from `DUE` to `SUBMITTED`; `submitted_at` is set to the current logical-clock instant; and three computations run in sequence using the recertification variant.

The recertification variant of adjusted-income differs from the initial variant in four pinned ways. First, the gross figure is the freshly declared `declared_gross_annual_income_cents`, not the original `Applicant.gross_annual_income_cents`. Second, the dependent count for the dependent-allowance step is derived from the recertification's `declared_household_size` minus 1 (subtracting the head of household) — this is the pinned recertification heuristic and produces a different dependent-allowance figure than the initial variant whenever the household has grown or shrunk since application. Third, the `elderly_or_disabled_head`, `medical_expense_annual_cents`, and `childcare_expense_annual_cents` inputs are read from the original `Applicant` record (frozen at application time and intentionally not redeclared at annual review). Fourth, the result is written to `new_adjusted_income_cents` on the AnnualReview rather than being written back to the Applicant. With those substitutions, the same arithmetic shape applies: a per-dependent allowance of $480 (forty-eight thousand cents) summed for the new dependent count, an elderly/disabled $400 (forty thousand cents) household allowance if applicable, a medical deduction limited to the amount above three percent of declared gross (using floor) and only for elderly/disabled households, and a childcare deduction capped at declared gross.

The recertification TTP is then computed against `new_adjusted_income_cents` and `declared_gross_annual_income_cents` using the same divide-then-floor, then multiply-then-ceil order and the same four-way maximum, with the welfare and minimum-rent floors unchanged. The result is written to `new_total_tenant_payment_cents`. The recertification HAP is then computed against the tenancy's frozen `applicable_payment_standard_cents` and frozen `gross_rent_cents` (the Payment Standard does not refresh at annual review — only TTP changes) and written to `new_hap_cents`.

A `CaseWorker` then reviews the submission and reaches one of three outcomes. If the review is approved, the new TTP and HAP cascade into the tenancy: `current_total_tenant_payment_cents` becomes `new_total_tenant_payment_cents`, `current_hap_cents` becomes `new_hap_cents`, the next-month HAP payment row uses the new amount, and a new DUE annual review is scheduled for 365 days after the current review's `review_due_date`. If the review is denied — for example when `new_adjusted_income_cents` exceeds the HUD low-income limit by more than 20 percent or a fraud determination is filed — the tenancy cascades to `TERMINATED` with `termination_reason` `ANNUAL_REVIEW_DENIED` and the voucher cascades from `LEASED` to `TERMINATED`. If the review is marked deficient (with a non-empty array of `deficiency_codes` such as missing pay stubs or missing IDs), the review transitions from `SUBMITTED` to `DEFICIENT` and the applicant has 14 days to resubmit. A resubmit within that window clears the `deficiency_codes`, recomputes `new_adjusted_income_cents`, `new_total_tenant_payment_cents`, and `new_hap_cents`, and re-enters `SUBMITTED` (this is the only cycle in any state machine in the system). If 14 days elapse without a resubmit, the deficient-review sweep transitions the review from `DEFICIENT` to `DENIED` and runs the same cascade as a directly denied review: tenancy to `TERMINATED` with `ANNUAL_REVIEW_DENIED`, voucher to `TERMINATED`.

### 3.10. Portability Across PHAs

When a household wishes to relocate to a unit administered by a different PHA, the applicant (or `CaseWorker` on their behalf) submits a portability request carrying `voucher_id` and `receiving_pha_id`. The voucher must be in `SEARCHING`, `LEASED`, or `SEARCHING_REISSUED`. The receiving PHA must differ from the voucher's current `administering_pha_id` and must be present in the configured PHA network; a violation returns `ERR_INVALID_RECEIVING_PHA`. The system sets `requested_at` to the current logical-clock instant.

A `PortabilityCoordinator` at the receiving PHA then decides the request. Absorption transfers administration of the voucher to the receiving PHA — `Voucher.administering_pha_id` becomes `receiving_pha_id`; if the voucher was `LEASED`, the active tenancy cascades to `TERMINATED` with `termination_reason` `PORTABILITY_ABSORBED`, the voucher cascades from `LEASED` to `PORTED_OUT`, any open annual review closes as void, and all future-month HAP payment rows for this voucher are suppressed (a `HAPPayment` row with `event_ref_type` of `PORTABILITY_CLOSEOUT` and `status` of `VOIDED_RETROACTIVE` is emitted for any month that had already been prebooked). When the voucher's `special_mobility_flag` is true, the receiving PHA must be one that offers `ZONE_A` units — this is a configuration check at the receiving side; an absorption that violates this constraint must be denied with `denial_reason` `MOBILITY_ZONE_RESTRICTION` rather than absorbed.

Billing is the alternative: the receiving PHA elects to bill the originating PHA monthly instead of absorbing administration. `administering_pha_id` is unchanged, HAP payments continue to be emitted by the originating PHA, and no tenancy cascade occurs. Denial requires a `denial_reason` from the set {`RECEIVING_PHA_OVER_LEASING_CAP`, `INELIGIBLE_HOUSEHOLD`, `MOBILITY_ZONE_RESTRICTION`, `NULL`}; a denial has no side effects on voucher or tenancy. All three outcomes record `decided_at` at the current logical-clock instant.

### 3.11. The Monthly HAP Ledger

HAP payments are recorded as immutable ledger rows. A monthly-ledger sweep is invoked by `PHAAdmin` with a `pay_period_month` (formatted YYYY-MM) and emits one `HAPPayment` row per locally-administered tenancy in `ACTIVE` or `ABATED`. For an `ACTIVE` tenancy, `amount_cents` is the tenancy's current `current_hap_cents` and the row's `status` is `PAID`. For an `ABATED` tenancy, `amount_cents` is 0 and the row's `status` is `ABATED_SUSPENDED`. A `TERMINATED` tenancy produces no row. Each row carries `event_ref_type` of `SCHEDULED_MONTHLY` and `event_ref_id` is the sweep run identifier — a polymorphic reference that, for other row sources, points instead at the `id` of the originating annual review, inspection, or portability request.

The rounding order for ledger aggregation is pinned: each per-tenancy row is already in integer cents (no per-row rounding occurs), and any reporting endpoint that sums across rows takes the sum in cents and only divides by 100 with floor at the presentation layer — never row-by-row conversion to dollars first. A row, once written, is never mutated; corrections take the form of subsequent compensating rows (`AR_RECALC`, `ABATEMENT`, `PORTABILITY_CLOSEOUT`) referencing the same `pay_period_month`.

### 3.12. The Logical Clock and Sweep Capabilities

Four sweep capabilities exist to drive deferred actions when the logical clock advances. The expiration sweep transitions any voucher whose `search_deadline` has passed and which has no `ACTIVE` or `PENDING_*` tenancy from `SEARCHING` (or `SEARCHING_REISSUED`) to `EXPIRED`, returning the list of expired voucher ids. The abatement sweep transitions any tenancy in `ABATED` whose abatement-triggering inspection's `cure_deadline` has elapsed without a `CURED` reinspection from `ABATED` to `TERMINATED` (with `termination_reason` `HQS_UNCURED`), cascading the voucher from `LEASED` to `TERMINATED`. The reviews sweep transitions any annual review in `DEFICIENT` past its 14-day cure window to `DENIED`, cascading tenancy and voucher as if the deny capability had been called directly. The monthly-HAP sweep is described in §3.11. All four are idempotent — re-running a sweep after the clock has advanced only processes rows whose deadlines have actually elapsed.

The clock-advance capability accepts a `to_timestamp` and sets the logical clock to that instant; advancing the clock backward is not permitted (it returns `ERR_VALIDATION`). The expiration sweep and the abatement sweep race against ongoing operations as described in §2.12; the deterministic loser `error_id` is `ERR_VOUCHER_EXPIRED` for finalize-loses-to-expiration, `ERR_VOUCHER_NOT_LOCAL` for new-tenancy-loses-to-absorb, and `ERR_INVALID_STATE` for the AnnualReview approve/deny race.

## 4. Endpoint Definitions

All endpoints below are mounted under the `/housing-voucher` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify or read an existing resource (or that act as commands with no new resource produced) return HTTP 200. Error responses use the HTTP status codes listed in §5. Each endpoint resolves path ids left-to-right (returning `ERR_NOT_FOUND` on the first missing id) before evaluating any other gate. Refer to §3 for the full request and response semantics of every endpoint — this table is a directory, not a contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /applicants | Submit a new applicant household; computes adjusted income, income band, eligibility status. | Applicant, CaseWorker |
| GET | /applicants/{id} | Read an applicant. | Applicant (own), CaseWorker, PHAAdmin |
| POST | /applicants/{id}/revoke | Revoke applicant eligibility; cascades any ISSUED voucher to REVOKED. | PHAAdmin |
| POST | /vouchers | Issue a voucher to an eligible applicant. | CaseWorker |
| GET | /vouchers/{id} | Read a voucher; remaining_search_days computed live. | Applicant (own), CaseWorker, PHAAdmin, PortabilityCoordinator |
| GET | /vouchers | List vouchers with filter and pagination. | CaseWorker, PHAAdmin |
| POST | /units | Landlord registers a unit. | Landlord |
| GET | /units/{id} | Read a unit. | Landlord (own), CaseWorker, Inspector |
| GET | /units | List units with filter and pagination. | Landlord (own filter), CaseWorker |
| POST | /payment-standards | Configure a Payment Standard row with effective_from. | PHAAdmin |
| GET | /payment-standards | List Payment Standards; supports active_only filter. | PHAAdmin, CaseWorker, Landlord |
| POST | /tenancies | Submit Request for Tenancy Approval; freezes gross_rent_cents and applicable_payment_standard_cents. | Landlord, CaseWorker |
| GET | /tenancies/{id} | Read a tenancy. | Landlord (own), CaseWorker, Inspector, Applicant (own) |
| POST | /tenancies/{id}/finalize | Run rent-burden and mobility-zone gates; compute initial TTP and HAP; cascade voucher to LEASED. | CaseWorker |
| POST | /tenancies/{id}/move-out | Tenant-initiated move-out with continued assistance; re-issues voucher search window. | CaseWorker |
| POST | /inspections | Schedule an inspection. Enforces 365-day gap between ANNUAL inspections on same unit. | Inspector, CaseWorker |
| POST | /inspections/{id}/complete | File outcome and defects; drives cascades into Tenancy. | Inspector |
| GET | /inspections/{id} | Read an inspection. | Inspector, CaseWorker, Landlord |
| POST | /rent-reasonableness-records | Attach comparables to a tenancy; computes median, threshold, is_reasonable. | CaseWorker |
| GET | /annual-reviews/{id} | Read an annual review. | Applicant (own), CaseWorker |
| POST | /annual-reviews/{id}/submit | Applicant submits updated income and household-size. | Applicant |
| POST | /annual-reviews/{id}/mark-deficient | Mark a submitted review as deficient; opens 14-day re-submit window. | CaseWorker |
| POST | /annual-reviews/{id}/resubmit | Resubmit after fixing deficiencies; cycles back to SUBMITTED. | Applicant |
| POST | /annual-reviews/{id}/approve | Approve; cascades new TTP/HAP into Tenancy.current_* and schedules next DUE review. | CaseWorker |
| POST | /annual-reviews/{id}/deny | Deny; cascades Tenancy and Voucher to TERMINATED. | CaseWorker |
| POST | /portability-requests | Submit a portability request to move voucher administration to receiving_pha_id. | Applicant (own), CaseWorker |
| POST | /portability-requests/{id}/absorb | Receiving PHA absorbs the voucher; cascades active tenancy to TERMINATED. | PortabilityCoordinator |
| POST | /portability-requests/{id}/bill | Receiving PHA elects to bill originating PHA instead of absorbing. | PortabilityCoordinator |
| POST | /portability-requests/{id}/deny | Deny the portability request; requires denial_reason. | PortabilityCoordinator |
| GET | /hap-payments | List HAP ledger entries with filter and pagination. | CaseWorker, PHAAdmin, Landlord (own) |
| POST | /_clock/advance | Advance the server's logical clock to a supplied to_timestamp. | PHAAdmin |
| POST | /_sweep/expirations | Run voucher-expiration sweep; idempotent. | PHAAdmin |
| POST | /_sweep/abatements | Run abatement-deadline sweep; terminates uncured ABATED tenancies. | PHAAdmin |
| POST | /_sweep/reviews | Run AnnualReview sweep; closes deficient reviews past 14-day window as DENIED. | PHAAdmin |
| POST | /_sweep/monthly-hap | Generate monthly HAPPayment rows for ACTIVE/ABATED tenancies. | PHAAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_VOUCHER_EXPIRED | 409 |
| ERR_VOUCHER_NOT_LOCAL | 403 |
| ERR_INSPECTOR_OUT_OF_SCOPE | 403 |
| ERR_MOBILITY_ZONE_VIOLATION | 422 |
| ERR_INSPECTION_OUTCOME_MISMATCH | 422 |
| ERR_UNIT_TOO_SMALL | 422 |
| ERR_LEASE_START_AFTER_DEADLINE | 422 |
| ERR_INSUFFICIENT_COMPARABLES | 422 |
| ERR_UNIT_NOT_VACANT | 409 |
| ERR_UNIT_OCCUPANCY_OVERLAP | 409 |
| ERR_INSPECTION_TOO_SOON | 409 |
| ERR_INSPECTION_ALREADY_COMPLETED | 409 |
| ERR_RENT_BURDEN_EXCEEDED | 422 |
| ERR_RENT_BURDEN_DIVZERO | 422 |
| ERR_RENT_NOT_REASONABLE | 422 |
| ERR_INVALID_RECEIVING_PHA | 422 |
| ERR_REVIEW_WINDOW_CLOSED | 409 |
| ERR_VALIDATION | 422 |

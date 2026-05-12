# Commercial Leasing API — Product Requirements Document

## 1. Introduction

Commercial real-estate portfolios mix long-lived hierarchical inventory with fast-moving leasing, billing, and settlement workflows. A single building may contain dozens of leasable units that are split, merged, or pulled offline for renovation while leases overlap their boundaries, tenants top up deposits, energy meters distribute consumption across neighbours, and finance officers reconcile fee disputes against move-out settlements. The Commercial Leasing API is the system of record for this end-to-end lifecycle: property hierarchy, tenant qualification, lease drafting through termination, deposit custody, rent and fee billing, and the audit trail that ties every state change back to the operator who caused it.

This document specifies the contract that downstream systems — payment processors, finance ledgers, energy-metering integrations, and access-control panels — rely on. The API governs four peer roles that act on the same domain from different angles: property managers who shape the physical inventory and adjudicate move-out inspections; leasing agents who onboard tenants and originate leases; finance officers who issue bills, confirm amendments, and close out settlements; and tenants who pay deposits, dispute charges, and submit move-out requests. The system treats every monetary value as integer cents, every date boundary as a UTC midnight, and every lease window as the half-open interval `[start_date, end_date)`. Operations that change a billable or contractual surface are recorded as immutable `AuditEvent` rows so that downstream finance and compliance functions can reconstruct any historical position.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying that principal's role. Requests missing either header, or carrying an unrecognized role, are rejected with `ERR_UNAUTHENTICATED`. Requests whose role is not permitted for the targeted endpoint are rejected with `ERR_FORBIDDEN`.

The system recognises exactly four roles: `PropertyManager`, `LeasingAgent`, `FinanceOfficer`, and `Tenant`. When `X-User-Role` is `PropertyManager`, `LeasingAgent`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on an `AuditEvent` row whose `actor_role` records which of these three roles acted) but does not compare it to any entity's `id`. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` — a `Lease`, a `Deposit`, a `FeeBill`, a `MoveOutRequest`, or a `Unit` reached through one of those — compare the resource's tenant foreign-key field to `X-User-ID`, and a tenant acting on a resource that belongs to another tenant is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned resources; it defaults to 10, is bounded by a minimum of 1, and by a maximum of 100. The `offset` parameter skips that many resources from the head of the listing and defaults to 0. Unless an endpoint specifies otherwise, list results are sorted by their `created_at` timestamp in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object so that the caller can recognise the end of the dataset.

### 2.4. Common Resource Properties

Every resource carries a server-minted UUID in its `id` field. UUIDs are emitted without any type-prefix and are immutable. All timestamp fields are ISO 8601 strings in UTC with three fractional digits — including the `created_at` field that every resource carries and the `updated_at` field carried by mutable resources. Date-only fields such as `start_date`, `end_date`, `period_start`, `period_end`, `target_move_out_date`, `license_expires_on`, `renovation_start_date`, `renovation_end_date`, and `effective_from` are also serialised as ISO 8601 timestamps anchored to UTC midnight (00:00:00.000Z) on the calendar day they represent. All monetary fields are integer cents (no decimals on the wire); they include `base_monthly_rent_cents`, `gross_rent_cents`, `rent_free_offset_cents`, `net_rent_cents`, `required_cents`, `collected_cents`, `retained_cents`, `refunded_cents`, `total_deposit_paid_cents`, `total_deposit_refunded_cents`, `total_deposit_retained_cents`, `amount_cents`, `rate_per_sqm_per_month_cents`, `fixed_rate_cents_per_month`, and `tariff_per_kwh_cents`.

Resources whose row is mutable after creation — `Building`, `Unit`, `Tenant`, `Lease`, `Deposit`, `FeeBill`, and `MoveOutRequest` — additionally carry a `version` integer that starts at 1 and increments by exactly one on every mutation that changes any field of the row, alongside an `updated_at` timestamp that the server refreshes on every such mutation. Two entity kinds are immutable after creation and therefore omit both `updated_at` and `version`: `RentScheduleItem` rows, which capture the rent ledger for a single calendar month and are never edited in place (regenerations during amendment overwrite the row rather than mutating it), and `AuditEvent` rows.

### 2.5. Optimistic Concurrency Control

Any mutating request body for a resource that carries a `version` field may include the caller's last-known `version` integer. When the request includes `version`, the server compares it against the current stored value; if they disagree, the request is rejected with `ERR_VERSION_MISMATCH` (HTTP 409). When the request body omits `version`, the server proceeds without the check and overwrites whatever is current. This protection extends to every endpoint that mutates a versioned row, from lease signing through fee-bill dispute resolution through deposit top-up.

### 2.6. Hierarchical Consistency and Cascades

The system treats unit, lease, and deposit state as a tightly-coupled hierarchy: a state change on one row often forces a cascading change on its neighbours. Whenever a `Lease` transitions from `DRAFT` to `SIGNED`, the bound `Unit` is forced to `LEASED`; whenever a `Lease` transitions through `TERMINATING` and finally to `TERMINATED`, the `Unit` is cascaded back to `VACANT` — but only after the lease's `Deposit` has reached `adjustment_status` of `SETTLED`, otherwise the cascade is blocked with `ERR_DEPOSIT_NOT_SETTLED`. Whenever a deposit's `adjustment_status` advances during the move-out lifecycle, the owning `MoveOutRequest.status` advances in lock-step: a proposal sets the request to `DEDUCTION_PROPOSED`, an approval cascades it to `DEDUCTION_APPROVED`, and a lease finalisation cascades it to `SETTLED`. Every such cascade is itself a mutation: it bumps the affected row's `version` by one and refreshes its `updated_at`. Mutations triggered by cascades are subject to the same OCC rules as direct mutations, and the `AuditEvent` rows describing them carry the system actor identity (`actor_role` set to `system`, `actor_id` set to `system`) rather than the operator who initiated the originating request.

### 2.7. Nested Resource Retrieval and Left-to-Right Path Validation

Many endpoints address a nested target — a unit inside a building, a child resource under a parent — through path segments such as `:building_id` followed by `:unit_id`, or `:request_id` for move-out endpoints, or `:bill_id`, `:deposit_id`, `:lease_id`, and `:tenant_id` for their respective resources. The server validates these identifiers strictly left-to-right. The first segment whose value does not resolve to a stored row causes the request to fail immediately with `ERR_NOT_FOUND` (HTTP 404); subsequent segments are not consulted. If every segment resolves but a child does not belong to its declared parent (for example, a `Unit` whose `building_id` does not match the `:building_id` in the path), the request likewise fails with `ERR_NOT_FOUND`. The same existence rule applies to foreign keys carried in request bodies — `unit_id`, `tenant_id`, `lease_id` — for any creation or update endpoint; unresolved bodies are rejected with `ERR_NOT_FOUND` before any business validation runs.

### 2.8. Precision, Rounding, and Per-Line Aggregation

All monetary calculations produce integer cents. Wherever a fractional cent arises during a calculation, the system applies the round-half-up convention. Two precision principles govern the per-line versus aggregate pattern. When a rent figure or property-fee figure is the product of a monthly rate and a multi-month or multi-day window, the rounding is applied **after** the area-by-rate-by-months product (or rate-by-days proration) in a single step — explicitly not per-month-then-summed. When an energy bill in `ALLOCATED` mode distributes a shared meter total across multiple units, each per-unit share is rounded half-up first, then summed; the unit whose `id` is lexicographically smallest in `shared_meter_group_unit_ids` absorbs whatever integer-cent remainder is needed to make the per-unit sum equal exactly the round-half-up of `shared_total_kwh × tariff_per_kwh_cents`. This per-line-then-sum-with-remainder-reconciliation is a compensating invariant: it is what keeps the group's billed total exactly equal to the total computed against the shared meter, even when individual rounded shares would otherwise drift by up to a small number of cents.

### 2.9. Deposit Ledger Integrity

Each `Tenant` exposes three aggregated balances: `total_deposit_paid_cents` (the sum of `collected_cents` across every `Deposit` whose owning `Lease` lists this tenant), `total_deposit_refunded_cents` (the sum of `refunded_cents` across the same set), and `total_deposit_retained_cents` (the sum of `retained_cents` across the same set). After every collection, refund, or retention against any single `Deposit` for the tenant, the live held-by-landlord balance for the tenant — `total_deposit_paid_cents − total_deposit_refunded_cents − total_deposit_retained_cents` — must equal the sum across that tenant's deposit rows of `collected_cents − refunded_cents − retained_cents`. These aggregates are integer cents and never rounded; they are exact sums of integers. Because the aggregates are derived from underlying rows, any mutation that touches `collected_cents`, `refunded_cents`, or `retained_cents` must recompute and persist the tenant's three totals as part of the same logical operation.

### 2.10. Validation Priority

When multiple validations could fire on a single request, the server evaluates them in a fixed order and returns the first failure. Authentication comes first — a missing or unrecognized `X-User-ID` / `X-User-Role` pair produces `ERR_UNAUTHENTICATED` (HTTP 401) before any other check. Role authorisation comes next; a recognized but unauthorised role produces `ERR_FORBIDDEN` (HTTP 403). Path-segment existence follows: every `:building_id`, `:unit_id`, `:lease_id`, `:tenant_id`, `:deposit_id`, `:bill_id`, and `:request_id` is resolved left-to-right, and the first unresolved id yields `ERR_NOT_FOUND` (HTTP 404). After path resolution comes foreign-key resolution for any ids embedded in the request body — `unit_id`, `tenant_id`, `lease_id` — which also produces `ERR_NOT_FOUND` on miss. Only after all four of these gates pass does the server examine state-machine preconditions (which fail with `ERR_INVALID_STATE`, HTTP 409) and the domain-specific business validations such as `ERR_TENANT_NOT_APPROVED`, `ERR_RENOVATION_LEASE_CONFLICT`, `ERR_LEASE_OVERLAP`, `ERR_MOVE_OUT_LEAD_TIME`, `ERR_DEDUCTION_EXCEEDS_DEPOSIT`, `ERR_DEPOSIT_OVERPAY`, `ERR_AREA_SUM_MISMATCH`, `ERR_STEPPED_SCHEDULE_INVALID`, `ERR_OUTSTANDING_FEE_BILL`, and `ERR_LEASE_NOT_BILLABLE`. The `ERR_VERSION_MISMATCH` check fires only against `PATCH` and `PUT` endpoints once those have reached their pre-mutation phase. Finally, request body type and required-field validation (`ERR_VALIDATION`, HTTP 422) runs at the tail.

### 2.11. Concurrency and Serialization Guarantees

Several operations admit racing callers and the system serialises them on a well-known key. Two `Lease` sign requests for the same `Unit` whose `[start_date, end_date)` windows overlap are serialised on the pair `(unit_id, overlapping window)`; the first to commit transitions its lease from `DRAFT` to `SIGNED`, and the second is rejected with `ERR_LEASE_OVERLAP` (HTTP 409). Two reservation attempts on the same `VACANT` unit are serialised on the unit row; the first wins, and the second is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409). Two simultaneous top-ups on the same `Deposit` are serialised on the deposit row; both succeed only if the cumulative `collected_cents` after both does not exceed `required_cents`, otherwise the loser is rejected with `ERR_DEPOSIT_OVERPAY` (HTTP 409). When a tenant disputes a `FeeBill` while a finance officer marks it `PAID` at the same time, the system serialises on `FeeBill.status` and exactly one wins; the loser is rejected with `ERR_INVALID_STATE` (HTTP 409). And as already noted in §2.5, any `PATCH` or `PUT` carrying a stale `version` field is rejected with `ERR_VERSION_MISMATCH` (HTTP 409).

### 2.12. Audit Logging

Every contractual or financial event of business consequence is captured as an immutable `AuditEvent` row. The event records the `subject_kind` (one of `LEASE`, `DEPOSIT`, `FEE_BILL`, or `UNIT`), the `subject_id` of the row whose lifecycle is being recorded, an `action` enumerated value (`CONTRACT_SIGNED`, `CONTRACT_AMENDED`, `CONTRACT_RENEWED`, `CONTRACT_TERMINATED`, `FEE_ADJUSTED`, `FEE_DISPUTED`, `DEPOSIT_DEDUCTED`, `DEPOSIT_REFUNDED`, `UNIT_SPLIT`, or `UNIT_MERGED`), the `actor_role` and `actor_id` of the operator who caused the event (the literal string `system` for cascades), an `occurred_at` server timestamp, and a frozen `payload` object capturing whichever fields of the subject are relevant at the moment of the event.

## 3. Business Logic & Workflows

### 3.1. Shaping the Building Inventory

A `PropertyManager` instantiates the property hierarchy. Creating a `Building` requires a human-readable `name`, a postal `address`, and a `floors_count` integer that records the building's total number of floors and must be at least 1. New buildings are persisted with `status` of `ACTIVE` (the alternative enumeration value being `DECOMMISSIONED`).

Inside a building, a `PropertyManager` creates `Unit` rows that represent the leasable inventory. Each unit declares the `floor` it sits on (an integer between 1 and the owning building's `floors_count` inclusive), a unique-per-building `code` string (e.g. `A-1201`), an `area_sqm` number rounded to 2 decimal places that records its floor area in square metres and which must be strictly greater than zero, an `orientation` drawn from the enumeration `N`, `S`, `E`, `W`, `NE`, `NW`, `SE`, `SW`, a `usage_type` drawn from `OFFICE`, `RETAIL`, `WAREHOUSE`, or `FB`, and a `rent_reference_per_sqm` reference monthly rent per square metre rounded to 2 decimal places and strictly greater than zero. The created unit begins with derived `status` `VACANT` (the full enumeration being `VACANT`, `RESERVED`, `LEASED`, `UNDER_RENOVATION`, `RETIRED`). The `building_id` on a `Unit` always reflects the building under whose path the unit was created.

A vacant unit may be taken offline for renovation. A property manager opens a renovation interval by supplying a `renovation_end_date`; the server stamps the unit's `renovation_start_date` and `renovation_end_date` from the request and transitions the unit's status from `VACANT` to `UNDER_RENOVATION`. The request is rejected with `ERR_INVALID_STATE` if the unit is not currently `VACANT`, with `ERR_INVALID_DATE_RANGE` if `renovation_end_date` is not strictly later than `renovation_start_date`, and with `ERR_RENOVATION_LEASE_CONFLICT` if any non-terminal `Lease` on this unit (one whose `status` is `SIGNED`, `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING`) has an interval `[start_date, end_date)` that overlaps the closed-with-buffer renovation window `[renovation_start_date, renovation_end_date + 1 day]` (one buffer day past the renovation's nominal end). Closing the renovation transitions the unit back to `VACANT` and clears both renovation dates.

Two structural transformations let property managers reshape the inventory after the fact. **Splitting** a `VACANT` unit retires it and creates one new `Unit` per child specification. Each child specifies its own `area_sqm`, `code`, and other unit fields; the parent's `code` becomes free for reuse. The operation is rejected with `ERR_INVALID_STATE` unless the parent is `VACANT`, with `ERR_AREA_SUM_MISMATCH` if the sum of `child_units[].area_sqm` does not equal the parent's `area_sqm` exactly when both are compared to 2 decimal places, and with `ERR_UNIT_CODE_CONFLICT` if any child's `code` is already taken inside the same building. On success, the parent's `status` becomes `RETIRED`; each child is persisted with `status` `VACANT`, with its `parent_unit_id` pointing at the retired parent's `id`, with its `building_id` inherited from the parent, and with its `rent_reference_per_sqm` inherited from the parent. An `AuditEvent` is recorded with `subject_kind` `UNIT` and `action` `UNIT_SPLIT`. **Merging** two or more vacant units retires them in favour of a new unit. The request carries a `source_unit_ids` array listing the units to merge and a `merged_code` string for the resulting unit. Each unit referenced by `source_unit_ids` must have `status` `VACANT` (otherwise `ERR_INVALID_STATE`) and all sources must share the same `building_id` and `floor` (otherwise `ERR_MERGE_LAYOUT_INVALID`). On success, every source unit's `status` becomes `RETIRED`, and a new `Unit` is persisted with `area_sqm` equal to the sum of the sources' `area_sqm`, with `code` taken from the request's `merged_code`, with `parent_unit_id` of null, with `status` `VACANT`, and with `rent_reference_per_sqm` set to the area-weighted average of the sources' reference rents, rounded half-up to 2 decimal places. An `AuditEvent` with `action` `UNIT_MERGED` records the operation.

A unit's `status` is not stored independently of these inputs — it is a derived field whose value is recomputed any time a lease state on the unit, the unit's renovation interval, or a split-or-merge event changes. The derivation is a priority-rule cascade evaluated first-match-wins: if a split or merge `AuditEvent` exists that retires this unit, the status is `RETIRED`; otherwise if the unit currently has both `renovation_start_date` and `renovation_end_date` set and the current server date falls inside the closed interval `[renovation_start_date, renovation_end_date]`, the status is `UNDER_RENOVATION`; otherwise if there exists a `Lease` for this unit whose `status` is among `SIGNED`, `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING`, the status is `LEASED`; otherwise if a reservation has been explicitly set on this unit through the reserve workflow described below, the status is `RESERVED`; otherwise the status is `VACANT`.

### 3.2. Tenant Onboarding and Qualification

A `LeasingAgent` records prospective tenants by supplying their `legal_name`, their `business_license_no` (which must be globally unique among non-rejected tenants), their `license_expires_on` date, and a `contact_email` for primary correspondence. A newly recorded tenant starts with `qualification_status` `PENDING_REVIEW`. The leasing agent then either approves the tenant (transitioning `qualification_status` from `PENDING_REVIEW` to `APPROVED`) or rejects it (transitioning to `REJECTED`, which is terminal). Approval is rejected with `ERR_LICENSE_EXPIRED` if `license_expires_on` is on or before the current server date — that is, if the license has not strictly outlasted today — and with `ERR_DUPLICATE_LICENSE` if any other tenant whose `qualification_status` is not `REJECTED` already carries the same `business_license_no`. Approval may also be revoked by a leasing agent, returning the tenant to `PENDING_REVIEW`; revocation is blocked with `ERR_TENANT_HAS_ACTIVE_LEASE` if the tenant currently holds any `Lease` whose `status` is `DRAFT`, `SIGNED`, `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING`. The tenant resource also exposes its three deposit aggregates (`total_deposit_paid_cents`, `total_deposit_refunded_cents`, `total_deposit_retained_cents`), each of which reflects the live state of every `Deposit` whose owning lease lists this tenant.

### 3.3. Reservations, Lease Drafting, and Signing

When a tenant has expressed intent for a specific vacant unit, a `LeasingAgent` may attach a soft reservation by supplying the `tenant_id` to the reserve action on a unit. The unit's status moves from `VACANT` to `RESERVED`. The reservation is rejected with `ERR_INVALID_STATE` unless the unit is presently `VACANT`, and with `ERR_UNIT_NOT_AVAILABLE` if there exists any other `Lease` on this unit whose status is `SIGNED`, `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING` with an overlapping window. A reservation is lifted by the inverse release action; release is rejected with `ERR_LEASE_DEPENDENCY` if a `DRAFT` or `SIGNED` lease still references this unit.

A leasing agent drafts a lease by supplying the `unit_id` and `tenant_id`, a `start_date` and `end_date` defining the half-open window `[start_date, end_date)` (end strictly later than start), a `base_monthly_rent_cents` for year 1, an `escalation_mode` drawn from `NONE`, `ANNUAL`, `BIENNIAL`, or `STEPPED`, the `escalation_pct_bps` rate in basis points where 500 means 5.00% (which the system uses for `ANNUAL` and `BIENNIAL` modes and ignores for `NONE` and `STEPPED`), an optional `stepped_schedule` array of objects each carrying an `effective_from` date and a `monthly_rent_cents` integer (required for `STEPPED` mode), an optional `rent_free_days` integer (defaulting to zero) granting that many free days starting at `start_date` and which must be at least 0 and strictly less than the lease window length in days, and a `deposit_months` integer between 1 and 6 inclusive that defines the security deposit as a multiple of `base_monthly_rent_cents`. The newly drafted lease is persisted with `status` `DRAFT`, `terminated_on` null, and `amendment_count` zero. Already at draft-creation time the system rejects a malformed `stepped_schedule` with `ERR_STEPPED_SCHEDULE_INVALID`, and the same check runs again whenever an amendment with a new schedule is initiated or confirmed.

Signing a drafted lease moves it from `DRAFT` to `SIGNED`. The signing endpoint is rejected with `ERR_TENANT_NOT_APPROVED` unless the lease's tenant has `qualification_status` `APPROVED`; with `ERR_UNIT_NOT_AVAILABLE` unless the unit is in `VACANT` or `RESERVED`; with `ERR_LEASE_OVERLAP` if any other lease on the same unit whose status is `SIGNED`, `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING` has an interval that overlaps the half-open window of this lease (note: adjacency where the `end_date` of one lease equals the `start_date` of another is permitted and does not count as overlap); with `ERR_RENOVATION_LEASE_CONFLICT` if the unit's current renovation interval — when extended by one buffer day at its end — overlaps the lease window; and with `ERR_STEPPED_SCHEDULE_INVALID` for any malformed `stepped_schedule` (rows must be strictly ascending in `effective_from`, the first row's `effective_from` must equal the lease's `start_date`, and the last row's `effective_from` must be strictly before the lease's `end_date`). On success, the lease's `status` becomes `SIGNED`, a `Deposit` row is created with `required_cents` equal to `deposit_months × base_monthly_rent_cents`, with `collected_cents` zero, with `adjustment_status` `AT_REST`, and with `frozen_status` `UNFROZEN`. The unit cascades to `LEASED`, the per-month rent ledger is generated as described below, and an `AuditEvent` with `subject_kind` `LEASE` and `action` `CONTRACT_SIGNED` is recorded.

### 3.4. Generating the Rent Schedule

The signing of a lease, the confirmation of an amendment, and the renewal of a lease all trigger generation (or regeneration) of `RentScheduleItem` rows — one per calendar month overlapping `[start_date, end_date)`. Each row carries the owning `lease_id`, a `period_start` set to the first day of that calendar month at UTC midnight, a `period_end` set to the first day of the following calendar month at UTC midnight, a computed `gross_rent_cents`, a computed `rent_free_offset_cents`, a computed `net_rent_cents`, and a `status` drawn from `PENDING`, `PAID`, `WAIVED`, or `VOIDED` that begins life at `PENDING`.

The generation algorithm proceeds in three steps for each month M in the lease window:

1. **Determine the monthly rent in effect on M.** When `escalation_mode` is `NONE`, the monthly rent is `base_monthly_rent_cents` unchanged for every month. When `escalation_mode` is `ANNUAL`, the algorithm computes the number of full years elapsed from the lease's `start_date` to the start of M as the floor of the elapsed days divided by 365.25 (the system's `DAYS_PER_YEAR` constant), then multiplies `base_monthly_rent_cents` by `(10000 + escalation_pct_bps) / 10000` raised to that integer power, and rounds the final result half-up to integer cents. When `escalation_mode` is `BIENNIAL`, the same calculation runs but with the elapsed-days divisor doubled to `2 × 365.25`, so escalations apply every two years rather than every year. When `escalation_mode` is `STEPPED`, the algorithm performs a table lookup against the `stepped_schedule` array: the monthly rent in effect on M is the `monthly_rent_cents` of the entry with the largest index whose `effective_from` is on or before M's start. Note that the stepped variant is table-driven and can diverge from `ANNUAL` or `BIENNIAL` for the same nominal effective rate when steps do not align with anniversaries; the system honours the table verbatim.
2. **Prorate for partial first or last months.** Let `days_in_month` be the calendar count of days in M, and let `active_days` be the count of days inside the intersection of M with `[start_date, end_date)`. Then `gross_rent_cents` for the row is the round-half-up of `monthly × active_days / days_in_month`, computed exactly in that order.
3. **Apply the rent-free deduction day-by-day.** The `rent_free_days` count applies to the earliest days of the lease, not spread across the lease. For each month M, the algorithm computes how many days of M fall inside the rent-free window — that window being the contiguous range starting at `start_date` and lasting `rent_free_days` days. Specifically, the count of free days in M is the maximum of zero and (the minimum of `rent_free_days` and the count of days from `start_date` to the end of M's active span) minus the count of days from `start_date` to the start of M. The `rent_free_offset_cents` for the row is then the round-half-up of `monthly × free_days_in_this_month / days_in_month`. The `net_rent_cents` of the row is the maximum of zero and `gross_rent_cents − rent_free_offset_cents`.

When an amendment is confirmed, only those rows whose `period_start` is on or after the amendment's `effective_from` are regenerated; rows for earlier months are preserved unchanged. When a renewal extends the lease, only the newly added months — those whose `period_start` lies in the open interval `(old end_date, new_end_date)` — are appended.

### 3.5. Activating, Amending, and Renewing a Lease

Once signed, a lease is brought live by activating it. Activation is rejected with `ERR_DEPOSIT_INCOMPLETE` unless the owning `Deposit` has `collected_cents` exactly equal to `required_cents`, and with `ERR_LEASE_NOT_YET_STARTED` unless the current server date is on or after the lease's `start_date`. On success, the lease's `status` becomes `ACTIVE`.

An `ACTIVE` lease can be amended by a `LeasingAgent`. Amendment payloads carry an `effective_from` date (the date from which regenerated rent rows apply) together with any combination of optional changes: `new_base_monthly_rent_cents`, `new_end_date`, `new_rent_free_days`, `new_deposit_months`, `new_stepped_schedule`, `new_escalation_mode`, and `new_escalation_pct_bps`. Initiating an amendment moves the lease's `status` to `AMENDMENT_PENDING` and simultaneously moves the owning `Deposit.adjustment_status` to `ADJUSTMENT_PENDING`. The amendment is then either confirmed by a `FinanceOfficer` or cancelled by a `LeasingAgent`. Confirmation is rejected with `ERR_AMENDMENT_PAYLOAD_INVALID` if the amendment payload references unknown fields or otherwise violates field constraints, with `ERR_LEASE_OVERLAP` if a changed `end_date` would put the lease in conflict with another lease on the unit, with `ERR_RENOVATION_LEASE_CONFLICT` if a changed window now overlaps the unit's current renovation interval (extended by one buffer day at its end), and with `ERR_STEPPED_SCHEDULE_INVALID` if a supplied `new_stepped_schedule` does not satisfy the same ordering rules as the original schedule. On success, the lease's `status` returns to `ACTIVE`, the `amendment_count` is incremented by one, the rent-schedule rows whose `period_start` is on or after the amendment's `effective_from` are regenerated per §3.4, the deposit's `required_cents` is recomputed against the post-amendment `deposit_months` and `base_monthly_rent_cents`, and the deposit's `adjustment_status` returns to `AT_REST`. An `AuditEvent` with `action` `CONTRACT_AMENDED` is recorded. Cancellation simply restores the lease's `status` to `ACTIVE` and the deposit's `adjustment_status` to `AT_REST` without other field changes.

Renewing an `ACTIVE` lease lets a leasing agent extend the lease's `end_date` and optionally update its base rent. The renewal payload carries a `new_end_date` and an optional `new_base_monthly_rent_cents`. Renewal is rejected with `ERR_INVALID_DATE_RANGE` unless `new_end_date` is strictly after the current `end_date`; with `ERR_LEASE_OVERLAP` if any other lease on the same unit has a window that intersects the half-open `(old end_date, new_end_date)`; with `ERR_RENOVATION_LEASE_CONFLICT` if the extended window overlaps the unit's renovation interval (extended by one buffer day at its end); and with `ERR_RENEWAL_WINDOW_NOT_OPEN` if the current server date is earlier than the lease's existing `end_date` minus 60 days — that is, the renewal window opens exactly 60 days before the lease's nominal end. On success, the lease's `end_date` is updated; if `new_base_monthly_rent_cents` was provided, the lease's `base_monthly_rent_cents` is updated; new `RentScheduleItem` rows are added for the months falling in the open interval `(old end_date, new_end_date)`; the deposit's `required_cents` is recomputed; and if the new required amount exceeds the previous one, the deposit's `adjustment_status` is set to `ADJUSTMENT_PENDING` so that the tenant must top up. An `AuditEvent` with `action` `CONTRACT_RENEWED` is recorded.

### 3.6. The Deposit Lifecycle

Each `Deposit` row is bound 1:1 to its owning `Lease` through `lease_id`. It carries two independent status fields. The `frozen_status` is either `UNFROZEN` or `FROZEN` and governs whether refund execution is permitted: a `FROZEN` deposit blocks refund execution. The `adjustment_status` is one of `AT_REST`, `ADJUSTMENT_PENDING`, `DEDUCTION_PENDING_APPROVAL`, or `SETTLED` and governs whether the deposit is currently waiting on funds, awaiting a deduction decision, or has been fully closed out. These two status fields evolve independently: a deposit can be `FROZEN` while still `AT_REST` or `DEDUCTION_PENDING_APPROVAL`, and a top-up does not change its frozen state.

A tenant tops up their deposit by supplying an `amount_cents` integer. The top-up is rejected with `ERR_DEPOSIT_OVERPAY` if `collected_cents + amount_cents` would exceed `required_cents` (the boundary is inclusive — equality is acceptable, strictly greater is rejected) and with `ERR_DEPOSIT_INCOMPLETE` if after applying the top-up the deposit is still short of `required_cents` and was in `ADJUSTMENT_PENDING`. On success, `collected_cents` is incremented by `amount_cents`, the tenant's three aggregate balances are recomputed per §2.9, and the deposit's `adjustment_status` returns to `AT_REST` when fully topped up.

The recompute formula for `required_cents` runs whenever an amendment is confirmed or a renewal completes with a base-rent change. The post-event `required_cents` is `deposit_months × base_monthly_rent_cents`. The delta between the new and old required amounts steers the next move: if the delta is strictly positive, the deposit's `adjustment_status` moves to `ADJUSTMENT_PENDING` and the tenant must top up; if the delta is strictly negative, the tenant is credited (the over-held amount is refunded immediately, with `retained_cents` unaffected for this delta); if the delta is zero, no change to status or balances results.

### 3.7. Property Fees, Energy Fees, and Disputes

A `FinanceOfficer` issues a `FeeBill` by supplying the `lease_id` of the lease being billed, the `bill_kind` (either `PROPERTY_FEE` or `ENERGY_FEE`), a `period_start` (which must be the first day of a month at UTC midnight) and a `period_end` (which must be the first day of a later month, also at UTC midnight). The owning lease's `unit_id` and `tenant_id` are derived and copied onto the bill. The bill's `amount_cents` is computed from the request and the bill is persisted with `status` `ISSUED`. The bill request is rejected with `ERR_LEASE_NOT_BILLABLE` unless the owning lease's `status` is `ACTIVE`, `AMENDMENT_PENDING`, or `TERMINATING` — bills against leases in `DRAFT`, `SIGNED`, or `TERMINATED` cannot be issued.

For `PROPERTY_FEE` bills, the request must additionally include a `property_fee_mode` of either `BY_AREA` or `FIXED_RATE`. In `BY_AREA` mode the request must include `rate_per_sqm_per_month_cents`, and the bill amount before capping is the round-half-up of `unit.area_sqm × rate_per_sqm_per_month_cents × months_in_period`, where `months_in_period` is the count of whole calendar months in `[period_start, period_end)` (the period must align to month boundaries, so this count is always an integer). In `FIXED_RATE` mode the request must include `fixed_rate_cents_per_month`, and the bill amount before capping is `fixed_rate_cents_per_month × months_in_period`. In both modes, the computed amount is then capped at the round-half-up of 5000 cents (50.00 currency units) per square metre per month, multiplied by the unit's `area_sqm` and by `months_in_period`; the bill's final `amount_cents` is the minimum of the computed amount and that cap.

For `ENERGY_FEE` bills, the request must additionally include an `energy_mode` of either `SUB_METER` or `ALLOCATED`, together with a `tariff_per_kwh_cents` that is strictly greater than zero. In `SUB_METER` mode the request must include `sub_meter_kwh` (which must be at least 0), and the bill amount is the round-half-up of `sub_meter_kwh × tariff_per_kwh_cents` — this charge ignores area entirely. In `ALLOCATED` mode the request must include `shared_total_kwh` (at least 0) recording the total kWh on the shared meter for the period, and `shared_meter_group_unit_ids` listing the units sharing the meter; that list must contain at least 2 unit ids and must include this bill's `unit_id`. The system then computes this unit's share of the shared kWh as `shared_total_kwh × (this_unit.area_sqm / total_group_area)`, where `total_group_area` is the sum of `area_sqm` across every unit in `shared_meter_group_unit_ids`; that share is **not** rounded at this point. The bill's `amount_cents` is then the round-half-up of the share multiplied by `tariff_per_kwh_cents`. When multiple bills are issued for the same shared-meter group over the same period, the canonical bill — the one whose `unit_id` is lexicographically smallest in `shared_meter_group_unit_ids` — absorbs the integer-cent remainder needed so that the sum across the group's bills equals exactly the round-half-up of `shared_total_kwh × tariff_per_kwh_cents`. Note that for the same unit consuming the same real kWh, `SUB_METER` and `ALLOCATED` may produce different `amount_cents` because allocation distributes all shared kWh by area rather than by actual use.

A `FeeBill` flows through a small lifecycle. A tenant paying a bill moves its `status` from `ISSUED` to `PAID`; payment is rejected with `ERR_LEASE_NOT_BILLABLE` unless the owning lease's `status` is `ACTIVE`, `AMENDMENT_PENDING`, `TERMINATING`, or `TERMINATED`. A tenant disputing a bill moves its `status` from `ISSUED` to `DISPUTED` and stores the supplied `dispute_reason` on the bill. A finance officer resolves a dispute by submitting a `resolution_keeps_bill` boolean; when true the bill cycles back to `ISSUED` and an `AuditEvent` with `action` `FEE_DISPUTED` is recorded, and when false the bill moves to `VOIDED` and an `AuditEvent` with `action` `FEE_ADJUSTED` is recorded. A finance officer may also void a bill outright from `ISSUED` to `VOIDED`, which similarly records `FEE_ADJUSTED`.

### 3.8. Move-Out, Inspection, Deductions, and Final Settlement

A tenant initiates a move-out from an `ACTIVE` lease by supplying a `target_move_out_date`. The move-out request is rejected with `ERR_MOVE_OUT_LEAD_TIME` unless `target_move_out_date` is at least 30 days after the current server date — the lead-time check is strict at the day granularity, so 29 days from today is rejected while 30 days from today is accepted — and with `ERR_INVALID_DATE_RANGE` if `target_move_out_date` is later than the lease's `end_date`. On success, the lease's `status` moves from `ACTIVE` to `TERMINATING`, a new `MoveOutRequest` is created with `requested_on` set to the server's current timestamp, `target_move_out_date` set from the request, and `status` `SUBMITTED`, and the deposit's `frozen_status` moves to `FROZEN`.

A property manager records the unit inspection on the request, supplying `inspection_findings` — an array of objects each carrying an `item` description, a `severity` of `MINOR` or `MAJOR`, and an `estimated_cost_cents` integer. This stores the findings on the request and moves its `status` to `INSPECTION_DONE`. The property manager then confirms restoration by submitting a `restoration_done` boolean; if `restoration_done` is false the request is rejected with `ERR_RESTORATION_INCOMPLETE`, and if true the request's `status` moves to `RESTORATION_CONFIRMED`. The property manager may, at any point while the request is still `SUBMITTED`, reject the request outright; rejecting it moves its `status` to `REJECTED`, reverts the owning lease's `status` from `TERMINATING` back to `ACTIVE`, and moves the deposit's `frozen_status` back to `UNFROZEN`.

While the move-out is in flight, a `PropertyManager` proposes deductions against the deposit by submitting a `deduction_items` array, where each element carries a `kind` (`OVERDUE_RENT`, `DAMAGE`, or `CLEANING`), an `amount_cents` integer, and an optional `note` string. The propose-deductions request is rejected with `ERR_INVALID_STATE` unless the owning lease's `status` is `TERMINATING`, and with `ERR_DEDUCTION_EXCEEDS_DEPOSIT` if the sum of `amount_cents` across the items strictly exceeds the deposit's `collected_cents` — equality is acceptable. On success, the deposit's `adjustment_status` moves to `DEDUCTION_PENDING_APPROVAL`, the supplied items are stored in `pending_deduction_items`, and the move-out request cascades to `DEDUCTION_PROPOSED`. A `FinanceOfficer` then either approves the deductions or rejects them. Approving is rejected with `ERR_INVALID_STATE` unless the owning move-out request's `status` is currently `RESTORATION_CONFIRMED` or `DEDUCTION_PROPOSED`; on success it sets the deposit's `retained_cents` to the sum of `pending_deduction_items[].amount_cents`, sets its `refunded_cents` to `collected_cents − retained_cents`, recomputes the tenant's `total_deposit_retained_cents` and `total_deposit_refunded_cents`, moves the deposit's `adjustment_status` to `SETTLED`, cascades the move-out request to `DEDUCTION_APPROVED`, and records two audit events — one with `action` `DEPOSIT_DEDUCTED` and one with `action` `DEPOSIT_REFUNDED`. Rejecting the deductions instead moves the deposit's `adjustment_status` back to `AT_REST` and clears `pending_deduction_items`, leaving the move-out request in its current state for the property manager to revise.

The lease is finalised by a finance officer once the move-out chain has reached `DEDUCTION_APPROVED`. Finalisation is rejected with `ERR_INVALID_STATE` unless the owning move-out request's `status` is `DEDUCTION_APPROVED`, with `ERR_DEPOSIT_NOT_SETTLED` unless the deposit's `adjustment_status` is `SETTLED`, and with `ERR_OUTSTANDING_FEE_BILL` if any `FeeBill` for this lease has `status` `ISSUED` or `DISPUTED` — every fee bill must be either `PAID` or `VOIDED` before settlement closes. On success, the lease's `status` moves from `TERMINATING` to `TERMINATED` and its `terminated_on` is set to the move-out request's `target_move_out_date`; every `RentScheduleItem` whose `period_start` is strictly after `terminated_on` is moved to `VOIDED`; the unit cascades back to `VACANT` (the deposit-settled precondition on that cascade is satisfied here by construction); the move-out request cascades to `SETTLED`; and an `AuditEvent` with `action` `CONTRACT_TERMINATED` is recorded.

### 3.9. Audit Visibility and Test-Driving Capabilities

Property managers and finance officers can list the audit trail with optional filters: `subject_kind` to narrow to one of `LEASE`, `DEPOSIT`, `FEE_BILL`, or `UNIT`; `subject_id` to narrow to a single subject row; `action` to narrow to a single recorded action; and `since` to narrow to events whose `occurred_at` is on or after a given timestamp. Each returned `AuditEvent` carries the full snapshot described in §2.12.

Two administrative capabilities exist purely so that automated tests can exercise time-gated transitions deterministically, and both are scoped to the `PropertyManager` role. An admin-only test-driving capability advances the logical server clock to a supplied `to` instant; this is required so that the move-out 30-day lead-time, the lease-activation start-date check, the 60-day renewal window, and renovation/lease overlap windows can all be probed without real-time waits. A second admin-only test-driving capability runs the scheduled sweep job that auto-voids `RentScheduleItem` rows whose `period_start` is strictly after the owning lease's `terminated_on`, recomputes the derived `Unit.status` per §3.1, and recomputes the tenant deposit aggregates per §2.9. These two capabilities are tools, not part of the business workflow.

## 4. Endpoint Definitions

Creation endpoints — the ones that mint a new top-level resource or a new child resource within a collection — return HTTP 201 on success. Endpoints that mutate the state of an existing resource (state transitions, top-ups, dispute resolutions, settlements, renovations, and the test-driving capabilities) return HTTP 200 on success. Path segments rendered as `:name` are URL placeholders.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/buildings` | Create a building | PropertyManager |
| GET  | `/buildings/:building_id` | Get a building | PropertyManager, LeasingAgent, FinanceOfficer |
| POST | `/buildings/:building_id/units` | Create a unit inside a building | PropertyManager |
| GET  | `/buildings/:building_id/units/:unit_id` | Get a unit (includes derived status) | PropertyManager, LeasingAgent, FinanceOfficer, Tenant |
| POST | `/buildings/:building_id/units/:unit_id/reserve` | Reserve a vacant unit pending lease signing | LeasingAgent |
| POST | `/buildings/:building_id/units/:unit_id/release-reservation` | Release a reservation | LeasingAgent |
| POST | `/buildings/:building_id/units/:unit_id/start-renovation` | Begin a renovation interval on a vacant unit | PropertyManager |
| POST | `/buildings/:building_id/units/:unit_id/finish-renovation` | End the current renovation interval | PropertyManager |
| POST | `/buildings/:building_id/units/:unit_id/split` | Split a vacant unit into children whose areas sum to the parent's | PropertyManager |
| POST | `/buildings/:building_id/units/merge` | Merge two or more vacant same-floor units into a new unit | PropertyManager |
| POST | `/tenants` | Onboard a prospective tenant | LeasingAgent |
| POST | `/tenants/:tenant_id/approve` | Approve a tenant's qualification | LeasingAgent |
| POST | `/tenants/:tenant_id/reject` | Reject a tenant's qualification | LeasingAgent |
| POST | `/tenants/:tenant_id/revoke-approval` | Revoke an APPROVED tenant back to PENDING_REVIEW | LeasingAgent |
| GET  | `/tenants/:tenant_id` | Get a tenant including aggregated deposit ledger | LeasingAgent, FinanceOfficer, Tenant |
| POST | `/leases` | Create a lease in DRAFT | LeasingAgent |
| POST | `/leases/:lease_id/sign` | Sign a DRAFT lease (creates Deposit and RentScheduleItems) | LeasingAgent |
| POST | `/leases/:lease_id/activate` | Activate a SIGNED lease once deposit is full and start date is reached | LeasingAgent |
| POST | `/leases/:lease_id/amend` | Begin a lease amendment | LeasingAgent |
| POST | `/leases/:lease_id/amend-confirm` | Confirm a pending amendment | FinanceOfficer |
| POST | `/leases/:lease_id/amend-cancel` | Cancel a pending amendment without changes | LeasingAgent |
| POST | `/leases/:lease_id/renew` | Renew an ACTIVE lease (extend end_date, optional rent change) | LeasingAgent |
| POST | `/leases/:lease_id/move-out-request` | Tenant submits a move-out request with 30-day lead time | Tenant |
| GET  | `/leases/:lease_id` | Get a lease (includes rent-schedule summary) | PropertyManager, LeasingAgent, FinanceOfficer, Tenant |
| GET  | `/leases/:lease_id/rent-schedule` | List RentScheduleItem rows for the lease | PropertyManager, LeasingAgent, FinanceOfficer, Tenant |
| GET  | `/deposits/:deposit_id` | Get a deposit | PropertyManager, LeasingAgent, FinanceOfficer, Tenant |
| POST | `/deposits/:deposit_id/top-up` | Tenant pays into deposit toward required_cents | Tenant |
| POST | `/deposits/:deposit_id/propose-deductions` | Property manager proposes deduction items against the deposit | PropertyManager |
| POST | `/deposits/:deposit_id/approve-deductions` | Finance officer approves the proposed deductions | FinanceOfficer |
| POST | `/deposits/:deposit_id/reject-deductions` | Finance officer rejects the proposed deductions (cycle back to AT_REST) | FinanceOfficer |
| POST | `/fee-bills` | Issue a property-fee or energy-fee bill for a lease | FinanceOfficer |
| GET  | `/fee-bills/:bill_id` | Get a fee bill | PropertyManager, FinanceOfficer, Tenant |
| POST | `/fee-bills/:bill_id/pay` | Tenant pays a fee bill | Tenant |
| POST | `/fee-bills/:bill_id/dispute` | Tenant disputes a fee bill | Tenant |
| POST | `/fee-bills/:bill_id/resolve-dispute` | Finance officer resolves a fee-bill dispute | FinanceOfficer |
| POST | `/fee-bills/:bill_id/void` | Void a fee bill | FinanceOfficer |
| GET  | `/move-out-requests/:request_id` | Get a move-out request | PropertyManager, FinanceOfficer, Tenant |
| POST | `/move-out-requests/:request_id/record-inspection` | Record inspection findings | PropertyManager |
| POST | `/move-out-requests/:request_id/confirm-restoration` | Confirm restoration is complete | PropertyManager |
| POST | `/move-out-requests/:request_id/reject` | Reject the move-out request (reverts lease to ACTIVE) | PropertyManager |
| POST | `/move-out-requests/:request_id/finalize` | Finalize settlement; lease becomes TERMINATED | FinanceOfficer |
| GET  | `/audit-events` | List audit events with optional filters | PropertyManager, FinanceOfficer |
| POST | `/_clock/advance` | Advance the server clock to a supplied instant (test helper) | PropertyManager |
| POST | `/_sweep/run` | Run the scheduled sweep (test helper) | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_TENANT_NOT_APPROVED` | 409 |
| `ERR_LICENSE_EXPIRED` | 409 |
| `ERR_DUPLICATE_LICENSE` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_LEASE_OVERLAP` | 409 |
| `ERR_RENOVATION_LEASE_CONFLICT` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_STEPPED_SCHEDULE_INVALID` | 422 |
| `ERR_LEASE_DEPENDENCY` | 409 |
| `ERR_DEPOSIT_INCOMPLETE` | 409 |
| `ERR_DEPOSIT_OVERPAY` | 409 |
| `ERR_DEDUCTION_EXCEEDS_DEPOSIT` | 409 |
| `ERR_DEPOSIT_NOT_SETTLED` | 409 |
| `ERR_OUTSTANDING_FEE_BILL` | 409 |
| `ERR_LEASE_NOT_BILLABLE` | 409 |
| `ERR_LEASE_NOT_YET_STARTED` | 409 |
| `ERR_MOVE_OUT_LEAD_TIME` | 409 |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 |
| `ERR_AREA_SUM_MISMATCH` | 409 |
| `ERR_UNIT_CODE_CONFLICT` | 409 |
| `ERR_MERGE_LAYOUT_INVALID` | 409 |
| `ERR_RESTORATION_INCOMPLETE` | 409 |
| `ERR_AMENDMENT_PAYLOAD_INVALID` | 422 |
| `ERR_TENANT_HAS_ACTIVE_LEASE` | 409 |

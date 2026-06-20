# Ccrc Life Plan Community API — Product Requirements Document

## 1. Introduction

A Continuing Care Retirement Community (also called a Life Plan Community) sells older adults a long-horizon promise: pay a substantial entrance fee and a recurring monthly service fee today, and in exchange the community guarantees a place to live and a graduated continuum of care — independent living, then assisted living, then skilled nursing — for the rest of one's life. The financial machinery behind that promise is unusually intricate. A community must price three flavors of life-care contract, hold a refundable portion of every entrance fee under one of several amortization schedules, manage a finite inventory of living units and health-center beds, run a priority waitlist when demand exceeds supply, and continuously demonstrate to regulators that the assets it has set aside are sufficient to cover its future obligations to residents already in the building.

This API is the system of record for that machinery. It governs the full residency lifecycle — from the moment a prospective resident's deposit is held, through unit assignment or waitlist placement, activation of the contract, the day-to-day accrual of occupancy and monthly billing, movement along the care continuum, and finally the voluntary or end-of-life termination that triggers a refund. Alongside the residency flow it tracks second occupants, health-center bed reservations, actuarial reserve disclosures that can freeze new admissions when funding falls dangerously low, and the resident council through which residents vote on community resolutions. Every monetary amount is expressed in integer cents and every rate in basis points so that the platform never depends on floating-point arithmetic.

The remainder of this document specifies the global contract that all endpoints share (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). Sections 2 and 3 together carry every behavioral rule; the tables in Sections 4 and 5 are deliberately thin and must be read against the narrative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `FinanceOfficer`, `AdmissionsDirector`, `CareCoordinator`, and `Resident`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`. When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `FinanceOfficer` owns the financial and governance surface of the platform: creating communities, advancing the community clock, authoring contract plans, issuing monthly invoices, settling refunds, generating actuarial reserve disclosures, and running the resident council (creating the council, drafting resolutions, and opening and closing them). When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `AdmissionsDirector` owns unit inventory, resident registration, and the residency lifecycle: opening residencies, assigning units, activating, terminating, adding and removing second persons, and operating the priority waitlist. When `X-User-Role` is `AdmissionsDirector`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `CareCoordinator` owns the care continuum and the health center: proposing, applying, and reverting care transitions, and holding, occupying, and releasing health-center bed reservations. When `X-User-Role` is `CareCoordinator`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `Resident` is an entity-backed role. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a `Resident` compare the resource's foreign-key field to `X-User-ID`. A `Resident` may read community data and cast a council vote on behalf of their own active residency. All four roles may call the read-only list and get endpoints.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource in the system — communities, contract plans, units, residents, residencies, second persons, waitlist entries, care transitions, bed reservations, monthly invoices, refund disbursements, resident councils, and council resolutions — carries a system-managed `id`, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation, and because it is minted with sub-millisecond uniqueness it serves as the canonical ordering key throughout the system. The `version` is an integer that begins at 1 (or the implementation's initial value) and increments by exactly one on every mutation of the resource. Whenever a field on a resource changes — including a derived field such as a residency's `care_level`, `occupied_months`, or `has_second_person` — that mutation refreshes `updated_at` and increments `version`.

Where the narrative says an operation "bumps the version" of an entity, it means precisely this: the entity's `version` rises by one and its `updated_at` is refreshed. This matters most for residencies, whose version is the anchor of optimistic concurrency control described in Section 2.8.

### 2.5. The Monthly Clock and Period Accrual

Time in this system does not advance with the wall clock. Each community maintains a deterministic monthly counter, `current_period_index`, which starts at 0 when the community is created and moves forward only when an operator advances the clock. Advancing the clock takes a single input, `by_periods`, which must be an integer of at least 1; any value below 1 or of the wrong type is rejected with `ERR_INVALID_CLOCK_ADVANCE`. Advancing by N raises `current_period_index` by N.

Advancing the clock has two cascading effects across the community. First, for every residency in that community whose status is `ACTIVE` at the moment of the advance, the residency's `occupied_months` counter is increased by exactly N. Because activation sets `occupied_months` to 0 at the activation period, a subsequent advance of N steps adds precisely N — the accrual is a pure counter increment, nothing more. Second, the advance sweeps the health center: every bed reservation still in `HELD` status whose hold window has lapsed — that is, where the community's new `current_period_index` is strictly greater than the reservation's `hold_expiry_period` — is transitioned to `EXPIRED`. A `HELD` reservation never consumed a bed, so expiry frees no unit.

### 2.6. Care Levels, Contract Types, and Refund Plans

Three enumerations recur throughout the domain and must use exact spellings. A care level is one of `INDEPENDENT`, `ASSISTED`, or `SKILLED`. A contract plan's `contract_type` is one of `TYPE_A`, `TYPE_B`, or `TYPE_C`: `TYPE_A` is full life-care with no per-diem charge for skilled nursing, `TYPE_B` is a modified contract that grants a capped number of discounted skilled days before per-diem applies, and `TYPE_C` is fee-for-service where every skilled day is billed. A plan's `refund_plan` is one of `DECLINING`, `FIFTY_REFUNDABLE`, or `NINETY_REFUNDABLE`: `DECLINING` amortizes the refundable balance toward zero, `FIFTY_REFUNDABLE` never lets the refund fall below half the entrance fee, and `NINETY_REFUNDABLE` never lets it fall below ninety percent.

### 2.7. Monetary Precision and Basis Points

All monetary amounts are stored and returned as integer cents — never as decimals or strings — and all rates are expressed in basis points, where 10000 basis points equals 100 percent. Wherever a calculation multiplies a cents amount by a basis-point rate, the product is divided by 10000 and the result is taken with the floor (rounded toward zero) so that the stored value is always a whole number of cents. The same flooring applies to present-value products and to the funded-ratio figure in the reserve disclosure. Because every input to monthly invoicing is already an integer number of cents, invoice totals require no rounding. Ranks and period indices are whole integers. There is no decimal arithmetic anywhere in the system.

### 2.8. Optimistic Concurrency on Residency Activation and Termination

Two residency operations carry a non-optional version guard so that a client never acts on a residency snapshot that another writer has already superseded. Both the activation operation and the termination operation require an `expected_residency_version` field in the request body that carries the client's last observed `version` of the target residency. This guard is evaluated before any state-machine precondition: if `expected_residency_version` does not equal the residency's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the state checks never run.

The reason the guard exists is concrete. Adding a second person to a residency legitimately bumps the residency's `version`; a holding of a bed reservation against the residency also bumps it. A client who read the residency before such a change and then attempts to activate it is carrying a stale version, and proceeding would act on an out-of-date snapshot — so the stale activation is rejected on the version check. Termination is even more sensitive: the refund a termination disburses is sized off the residency's `occupied_months` and `care_level`, so a stale view would compute the wrong refund tier; the version guard forces the client to re-read the residency before terminating. No other endpoint takes a version field; operations not named here perform no concurrency check.

### 2.9. Cross-Entity Cascades and Hierarchical Consistency

Many operations in this system mutate more than one entity in a single call. When a residency is assigned a unit, the unit's `status` flips in lockstep; when a residency terminates, units are freed, second persons are removed, and bed reservations are released in a chain. The governing principle is that the system never leaves a parent and its dependents in contradictory states: every secondary mutation that an operation implies is performed as part of the same operation, each affected resource independently refreshing its `updated_at` and incrementing its `version`. The precise cascades are described in Section 3 alongside the workflows that trigger them, because each cascade only makes sense in the context of its business event.

### 2.10. Nested Resource Retrieval and Validation Order

Several endpoints address a resource through a parent in the URL path — for example a residency identified by `rid`, a waitlist entry by `wid`, a care transition by `ctid`, a bed reservation by `brid`, a community by `cid`, a council by `coid`, a council resolution by `resid`, a contract plan by `pid`, a unit by `uid`, a resident by `resdid`, a second person by `spid`, an invoice by `invid`, or a refund disbursement by `dsbid`. Path identifiers are validated strictly left-to-right: the first identifier in the path that does not correspond to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404), before any later identifier or body field is examined.

The validation order for any write request is fixed and is the order in which a request must pass its gauntlet. Authentication comes first: a missing or malformed header yields `ERR_MISSING_AUTH`. Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Existence of path resources is third, yielding `ERR_NOT_FOUND`. Existence of foreign-key references in the request body is fourth: a body field that names a non-existent community, residency, resident, plan, unit, or council is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422). Request-body well-formedness is fifth — required fields present and correctly typed, enum values legal, and positive-amount constraints satisfied — yielding `ERR_INVALID_REQUEST` (HTTP 400). Only after these five layers does the system evaluate the optimistic-concurrency guard (sixth, yielding `ERR_STALE_VERSION`), then the state-machine and business rules described in Section 3. Where a specific business error and the generic `ERR_INVALID_STATE` (HTTP 409) could both describe a state problem, the specific error named in Section 3 takes precedence; `ERR_INVALID_STATE` is the fallback only when no more specific transition error applies.

### 2.11. The Actuarial Reserve and Admissions Freeze

A community holds `reserve_assets_cents` — the cash and investments set aside to back its promises — and is configured with an `actuarial_discount_rate_bps` (the annual discount rate used to present-value future obligations) and a `target_funded_ratio_bps` (the regulatory minimum funded ratio, defaulting to 10000, i.e. 100 percent). A community also carries a computed boolean, `is_admissions_frozen`, which begins false. When a generated reserve disclosure reveals that the community's funded ratio has fallen below half of its target funded ratio, `is_admissions_frozen` becomes true. Once frozen, the community blocks the three admitting operations — assigning a unit, placing a residency from the waitlist, and activating a residency — each rejected with `ERR_ADMISSIONS_FROZEN` (HTTP 403). The full disclosure computation and the precise freeze threshold are specified in Section 3.6.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Community and Its Catalogue

A `FinanceOfficer` establishes a community by supplying its legal `name` and its `actuarial_discount_rate_bps`, optionally overriding `target_funded_ratio_bps` (default 10000) and the opening `reserve_assets_cents` (default 0). On creation the community's `current_period_index` is 0 and `is_admissions_frozen` is false. The same officer reads a community to inspect its live `is_admissions_frozen` flag and `reserve_assets_cents`, and advances its clock as described in Section 2.5.

Against a community, the `FinanceOfficer` authors one or more contract plans. A plan names its parent through `community_id` and carries a marketing `name`, a `contract_type`, an `entrance_fee_cents`, a `refund_plan`, and a `monthly_service_fee_cents`, plus a flat `second_person_fee_cents` surcharge for a second occupant. Several pricing knobs are optional with defaults: `declining_monthly_bps` (default 200, i.e. 2.00 percent of the entrance fee amortized per occupied month under `DECLINING`, and also the monthly decline applied above the floor under the fifty- and ninety-percent plans), `declining_nonrefundable_bps` (default 400, the share retained immediately on move-in under `DECLINING`), `assisted_monthly_surcharge_cents` (default 0, the extra monthly fee while a resident is in `ASSISTED`), `skilled_per_diem_cents` (default 0, the gross per-diem for skilled days), and `typeb_discounted_days` (default 0, the number of discounted skilled days granted per residency under `TYPE_B` before per-diem begins; ignored for `TYPE_A` and `TYPE_C`). The `entrance_fee_cents` and `monthly_service_fee_cents` must each be strictly greater than zero, and `second_person_fee_cents` must be zero or greater; a violation of any of these — or a missing required field, a bad enum, or a malformed body — is rejected with `ERR_INVALID_REQUEST`.

Unit inventory is the `AdmissionsDirector`'s domain. Creating a unit names its `community_id`, a human-readable `unit_number` that is unique within the community, a `care_level`, and an optional `bed_capacity` (default 1, meaningful only for skilled health-center units). A unit's `status` is system-managed: it is `AVAILABLE` on creation, becomes `OCCUPIED` while assigned or while a bed against it is occupied, and returns to `AVAILABLE` when freed. The `care_level` supplied at unit creation must be a member of the care-level enumeration, and an out-of-set value is rejected with `ERR_INVALID_REQUEST`. The same director registers prospective residents, each carrying a `community_id`, a legal `full_name`, a `date_of_birth`, and an optional `priority_score` (default 0) that will later weigh into waitlist tie-breaking.

### 3.2. Opening a Residency and Securing a Unit

The residency is the contract at the heart of the platform. An `AdmissionsDirector` opens one by naming its `community_id`, the `primary_resident_id` of the contract holder, and the `contract_plan_id` that pins the contract type and fee schedule for the life of the residency. A freshly opened residency starts in `DEPOSIT_HELD` status with `care_level` of `INDEPENDENT`, no `unit_id` yet assigned, and its computed money fields — `entrance_fee_paid_cents`, `occupied_months`, `skilled_days_used`, `refund_disbursed_cents` — all at 0 and `has_second_person` false. From `DEPOSIT_HELD` the residency forks down one of two paths to securing a home: a direct unit assignment, or placement onto the priority waitlist.

The direct path is the assign-unit action, driving the residency from `DEPOSIT_HELD` to `RESERVED`. It takes a single `unit_id` in the body. The residency must currently be in `DEPOSIT_HELD`, or the action is rejected with `ERR_RESIDENCY_NOT_DEPOSIT_HELD`. The community must not be admissions-frozen, or the action is rejected with `ERR_ADMISSIONS_FROZEN`. The target unit must be `AVAILABLE`, or the action is rejected with `ERR_UNIT_NOT_AVAILABLE`. And the target unit's `care_level` must be `INDEPENDENT`, or the action is rejected with `ERR_UNIT_CARE_LEVEL_MISMATCH`. When all four hold, the residency's `unit_id` is set to the target unit, the unit's `status` flips to `OCCUPIED`, and the residency advances to `RESERVED`.

Once a residency holds a reserved unit, the `AdmissionsDirector` activates it, driving `RESERVED` to `ACTIVE`. Activation requires the `expected_residency_version` guard described in Section 2.8, checked first; the residency must currently be `RESERVED`, else `ERR_RESIDENCY_NOT_RESERVED`; it must have a `unit_id` set, else `ERR_NO_UNIT_ASSIGNED`; and the community must not be frozen, else `ERR_ADMISSIONS_FROZEN`. On activation, the residency freezes `entrance_fee_paid_cents` to the plan's `entrance_fee_cents`, resets `occupied_months` to 0, sets `care_level` to `INDEPENDENT`, and resets `skilled_days_used` to 0. The frozen entrance fee is simultaneously booked into the community's reserve: the community's `reserve_assets_cents` is increased by the residency's `entrance_fee_paid_cents`. This activation step bumps the residency's `version` by one — the very mutation that a concurrent stale activation or termination will collide with.

### 3.3. The Priority Waitlist

When no independent unit is free, an `AdmissionsDirector` enqueues a `DEPOSIT_HELD` residency onto the waitlist instead, driving `DEPOSIT_HELD` to `WAITLISTED`. The enqueue request names the `community_id`, the `residency_id` awaiting a unit, and the `target_care_level` of the unit being waited for, which must be a member of the care-level enumeration (an out-of-set value yields `ERR_INVALID_REQUEST`). The residency must be in `DEPOSIT_HELD`, else `ERR_RESIDENCY_NOT_DEPOSIT_HELD`, and the residency must not already have a `PENDING` waitlist entry, else `ERR_DUPLICATE_WAITLIST_ENTRY`. The new entry is created `PENDING`; its `enqueued_period_index` is snapshotted from the community's current `current_period_index`, its `priority_score` is snapshotted from the resident's `priority_score`, its `rank` is computed over the queue, and the parent residency moves to `WAITLISTED`.

Ordering a queue is the heart of fairness here. The candidate set for ranking is every waitlist entry that is `PENDING`, shares the same `community_id`, and shares the same `target_care_level`. Within that set, entries are ordered by three keys in strict precedence: first by `enqueued_period_index` ascending, so the entry that joined in the earliest period wins; then, among entries that joined in the same period, by `priority_score` descending, so a higher priority wins the tie; and finally, among entries still tied, by `created_at` ascending, so the earliest enqueue timestamp breaks the remaining tie. The `id` field is never used as a tie-breaker. Each entry's `rank` is its one-based position in this sorted order. Only the entry whose `rank` is 1 — the head of the queue — may be offered or placed; an attempt to offer or place any non-head entry is rejected with `ERR_WAITLIST_NOT_HEAD`. This ranking is recomputed whenever an entry is created, placed, or withdrawn.

A waitlist entry has its own lifecycle: `PENDING`, `OFFERED`, `PLACED`, or `WITHDRAWN`. Offering the head entry advances it from `PENDING` to `OFFERED`; the entry must currently be `PENDING`, else `ERR_WAITLIST_ENTRY_NOT_PENDING`, and it must be the head of its queue, else `ERR_WAITLIST_NOT_HEAD`. Placing the head entry drives it to `PLACED` and the residency to `RESERVED`. Placement requires the entry to be in `OFFERED` or `PENDING`, else `ERR_WAITLIST_ENTRY_NOT_PLACEABLE`; the entry must be the head of its queue (`rank` equal to 1), else `ERR_WAITLIST_NOT_HEAD`; the target unit named by `unit_id` must be `AVAILABLE` and of `care_level` `INDEPENDENT`, else `ERR_UNIT_NOT_AVAILABLE`; the parent residency must be in `WAITLISTED`, else `ERR_RESIDENCY_NOT_WAITLISTED`; and the community must not be frozen, else `ERR_ADMISSIONS_FROZEN`. On a successful placement, the residency's `unit_id` is set to that unit, the unit's `status` becomes `OCCUPIED`, the entry becomes `PLACED`, the residency becomes `RESERVED`, and every remaining `PENDING` entry for the same community and `target_care_level` is re-ranked so that the gap left by the placed entry is closed.

Withdrawing an entry takes it to `WITHDRAWN` and returns its residency to the pre-waitlist `DEPOSIT_HELD` state. Withdrawal is permitted only from `PENDING` or `OFFERED`, else `ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE`. As with placement, the remaining `PENDING` entries for the same community and `target_care_level` are re-ranked after a withdrawal to close the gap.

### 3.4. Second Occupants and the Care Continuum

A residency may host a second occupant. The `AdmissionsDirector` adds one by supplying the second person's `full_name` and `date_of_birth`; the new record references its residency through `residency_id` and starts `ACTIVE`. A second person may be added only to a residency that does not already have an `ACTIVE` second person — a second attempt is rejected with `ERR_SECOND_PERSON_EXISTS`. Adding the second person sets the residency's `has_second_person` to true and bumps the residency's `version` by one (precisely the kind of version advance that an in-flight stale activation will collide with). Removing a second person drives it from `ACTIVE` to `REMOVED`, clears the residency's `has_second_person` back to false, and again bumps the residency's `version`.

Movement along the care continuum is the `CareCoordinator`'s responsibility and proceeds in two steps: propose, then apply. Proposing a transition names the `residency_id` and the requested `to_level`. The parent residency must be `ACTIVE` at propose time, else `ERR_RESIDENCY_NOT_ACTIVE`; the proposal is created `PROPOSED`, and its `from_level` is snapshotted from the residency's current `care_level` while its `effective_period_index` stays 0 until applied. Applying a proposed transition advances it from `PROPOSED` to `APPLIED`. The transition must currently be `PROPOSED`, else `ERR_CARE_TRANSITION_NOT_PROPOSED`; the parent residency must still be `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`; and the requested `to_level` must be exactly one step away from `from_level` along the chain that runs `INDEPENDENT` to `ASSISTED` to `SKILLED`, in either direction, with no skipping a level — a jump such as `INDEPENDENT` straight to `SKILLED` is rejected with `ERR_INVALID_CARE_STEP`. Furthermore, if `to_level` is `SKILLED`, the residency must already hold an `OCCUPIED` bed reservation, else the apply is rejected with `ERR_NO_BED_OCCUPIED`. A successful apply sets the residency's `care_level` to `to_level`, stamps the transition's `effective_period_index` with the community's current `current_period_index`, and bumps the residency's `version` by one. Reverting a proposal instead drives `PROPOSED` to `REVERTED`; the transition must be `PROPOSED`, else `ERR_CARE_TRANSITION_NOT_PROPOSED`. A revert is a pure compensation: a never-applied proposal leaves the residency's `care_level` exactly as it was, so reverting changes nothing on the continuum.

### 3.5. Health-Center Bed Reservations

Skilled nursing happens in health-center units, whose beds are reserved before they are used. A `CareCoordinator` holds a bed by naming the `residency_id` holding the reservation, the `unit_id` of the skilled health-center unit, and a `hold_expiry_period` — the inclusive period index up to which a held reservation may still be occupied. The reservation is created `HELD`, its `hold_start_period` is stamped with the community's current `current_period_index`, its `occupied_start_period` stays 0 until occupied, and the act of holding bumps the parent residency's `version` by one. Two guards protect the hold. The `hold_expiry_period` must be strictly greater than the community's current period at hold time, else `ERR_INVALID_HOLD_WINDOW`. The target unit must have `care_level` `SKILLED`, else `ERR_UNIT_NOT_SKILLED`. And capacity is enforced: a skilled unit cannot accept a new reservation when the number of its committed reservations — those currently `HELD` plus those currently `OCCUPIED` — already equals the unit's `bed_capacity`, in which case the hold is rejected with `ERR_BED_CAPACITY_EXCEEDED`.

A bed reservation moves through `HELD`, then to one of three terminal states: `OCCUPIED`, `RELEASED`, or `EXPIRED`. Occupying a held reservation requires it to be `HELD`, else `ERR_BED_RESERVATION_NOT_HELD`; the community's `current_period_index` must not exceed the reservation's `hold_expiry_period`, else `ERR_BED_RESERVATION_EXPIRED`; and the parent residency must be `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`. Occupying stamps the reservation's `occupied_start_period` with the current `current_period_index` and flips the skilled unit's `status` to `OCCUPIED`, consuming the bed. Releasing a reservation can happen from either `HELD` or `OCCUPIED`. Releasing a `HELD` reservation requires it to be `HELD` (`ERR_BED_RESERVATION_NOT_HELD`) and frees no unit, because a held reservation never consumed the bed. Releasing an `OCCUPIED` reservation requires it to be `OCCUPIED`, else `ERR_BED_RESERVATION_NOT_RELEASABLE`, and frees its skilled unit by setting that unit's `status` back to `AVAILABLE`. Expiry is not an operator action: it happens only during the clock-advance sweep described in Section 2.5, when a still-`HELD` reservation's `hold_expiry_period` falls behind the advanced `current_period_index`; expiry frees no unit.

### 3.6. Monthly Billing, Actuarial Disclosure, and Reserve Reconciliation

Once a residency is `ACTIVE`, the `FinanceOfficer` issues a monthly service-fee invoice for the current period. The invoice records the `residency_id` it bills, the `period_index` it covers (the community's current `current_period_index`), and four computed money lines: `base_service_fee_cents`, `second_person_fee_cents`, `care_surcharge_cents`, and `total_cents`, after which it is `ISSUED` and immutable. An invoice may only be issued for a residency that is currently `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`. The request accepts an optional `skilled_days_in_period`, the number of skilled nursing days billed this period, which when supplied must be an integer between 0 and 30 inclusive, else `ERR_INVALID_REQUEST`; when omitted it is treated as 0.

The invoice total is assembled in a fixed order. The base line begins as the plan's `monthly_service_fee_cents`; if the residency's `care_level` is `ASSISTED`, the plan's `assisted_monthly_surcharge_cents` is added into that base. This assembled base is the invoice's `base_service_fee_cents`. The second-person line is the plan's flat `second_person_fee_cents` when the residency's `has_second_person` is true, and 0 otherwise — it is never scaled by care level — and this becomes `second_person_fee_cents`. The care surcharge depends on care level and contract type. If the residency's `care_level` is not `SKILLED`, the care surcharge is 0. If the residency is `SKILLED`, the surcharge is computed from the contract type using the skilled-day count for the period (call it the supplied `skilled_days_in_period`, defaulting to 0): under `TYPE_A`, the life-care contract, the surcharge is 0 because nursing carries no marginal monthly cost; under `TYPE_B`, the modified contract, the residency's first `typeb_discounted_days` skilled days across its whole life are free, so the number of still-free days is the larger of 0 and `typeb_discounted_days` minus the residency's already-accumulated `skilled_days_used`, the billable days are the larger of 0 and this period's skilled days minus those still-free days, and the surcharge is the billable days multiplied by the plan's `skilled_per_diem_cents`; under `TYPE_C`, fee-for-service, every skilled day of the period is billed, so the surcharge is this period's skilled days multiplied by `skilled_per_diem_cents`. The computed surcharge becomes `care_surcharge_cents`. The invoice `total_cents` is the sum of the base line, the second-person line, and the care surcharge. Crucially, the residency's `skilled_days_used` is read for the `TYPE_B` free-day calculation before this invoice is counted; only after the invoice has been computed, and only when the residency is `SKILLED`, is the residency's `skilled_days_used` increased by this period's skilled days. Because every input is integer cents, no rounding is performed.

Generating an actuarial reserve disclosure is the `FinanceOfficer`'s regulatory duty and is computed over the community's `ACTIVE` residencies. The report exposes `future_obligation_cents`, `refund_liability_cents`, `total_obligation_cents`, `funded_ratio_bps`, `is_deficient`, and the community's current `reserve_assets_cents`. The computation begins by deriving a monthly discount rate: the community's `actuarial_discount_rate_bps` divided by 10000, then divided by 12. It then walks every residency whose status is `ACTIVE` in the community, in ascending `created_at` order (never ordering by `id`). For each such residency it computes the months remaining on a 240-month actuarial horizon as the larger of 0 and 240 minus the residency's `occupied_months`. If the monthly rate is greater than 0, the present-value factor is one minus the quantity (one plus the monthly rate) raised to the power of the negative of the remaining months, all divided by the monthly rate; if the monthly rate is 0, the present-value factor is simply the remaining months. That residency's service-fee liability is the floor of the plan's `monthly_service_fee_cents` multiplied by the present-value factor, and it is accumulated into `future_obligation_cents`. In the same pass, the residency's voluntary refund liability — the refund it would owe if it terminated voluntarily today, computed by the refund formula of Section 3.7 under the voluntary variant using the residency's current `occupied_months` — is accumulated into `refund_liability_cents`. The `total_obligation_cents` is the sum of `future_obligation_cents` and `refund_liability_cents`.

The funded ratio follows. If `total_obligation_cents` is greater than 0, `funded_ratio_bps` is the floor of the community's `reserve_assets_cents` multiplied by 10000 and divided by `total_obligation_cents`; if the total obligation is 0, the funded ratio is taken to be 10000. The report's `is_deficient` flag is true exactly when `funded_ratio_bps` is strictly less than the community's `target_funded_ratio_bps`. The disclosure carries one consequential side effect: when `funded_ratio_bps` falls strictly below the floor of the community's `target_funded_ratio_bps` divided by 2 — that is, below half the target — the community's `is_admissions_frozen` is set to true, which (per Section 2.11) thereafter blocks unit assignment, waitlist placement, and activation with `ERR_ADMISSIONS_FROZEN`.

### 3.7. Termination, Refunds, and the Entrance-Fee Ledger

Terminating a residency is the most consequential operation in the system because it both unwinds every dependent resource and sizes a refund. An `AdmissionsDirector` terminates by supplying a `reason` and the `expected_residency_version` guard. The version guard is checked first (`ERR_STALE_VERSION`, per Section 2.8). The residency must be `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`. The `reason` must be exactly `VOLUNTARY` or `DEATH`; any other value is rejected with `ERR_INVALID_REQUEST`. A `VOLUNTARY` reason drives the residency to `TERMINATED_VOLUNTARY` and a `DEATH` reason to `TERMINATED_DEATH`; both branches perform the identical cascade and differ only in how the refund is sized.

The termination cascade unwinds the residency in three hops, and both terminal branches perform all of it. First, the residency's assigned independent unit has its `status` set back to `AVAILABLE`. Second, every `ACTIVE` second person on the residency is set to `REMOVED` and the residency's `has_second_person` is cleared to false. Third, every bed reservation for the residency that is `HELD` or `OCCUPIED` is set to `RELEASED`, and any skilled unit that was `OCCUPIED` through one of those reservations has its `status` returned to `AVAILABLE`. Then the refund is created: a refund disbursement is created `PENDING` referencing the residency through `residency_id`, snapshotting the residency's `entrance_fee_paid_cents` into `gross_entrance_fee_cents`, computing `refundable_cents` by the refund formula under the matching variant, and recording `termination_reason` as `VOLUNTARY` or `DEATH` to mirror the terminating branch; its `settlement_period_index` stays 0 while `PENDING`. The residency's own `refund_disbursed_cents` is set to that `refundable_cents`. Finally the ledger is reconciled in the opposite direction from activation: the community's `reserve_assets_cents` is decreased by `refundable_cents`, pairing with the entrance-fee credit booked at activation so the entrance-fee ledger conserves. Termination bumps the residency's `version` by one.

The refund itself follows the plan's tier schedule and is computed in a pinned order. Let the gross entrance fee be the residency's frozen `entrance_fee_paid_cents` and let the occupied-month count be the residency's `occupied_months` frozen at termination time. First compute a per-month amortization amount as the floor of the gross fee multiplied by the plan's `declining_monthly_bps` and divided by 10000 — this per-month figure is computed once and then multiplied by the occupied months, and this ordering is mandatory because computing the per-month amount first and then multiplying differs in cents from multiplying the gross fee by the rate and the months together before flooring. The schedule then branches on the plan's `refund_plan`. Under `DECLINING`, an immediate non-refundable retention is the floor of the gross fee multiplied by `declining_nonrefundable_bps` divided by 10000, and the refundable amount is the larger of 0 and the gross fee minus that retention minus the per-month amount times the occupied months — so under full amortization a `DECLINING` refund can reach 0 once the retention plus the accumulated monthly decline meets or exceeds the gross fee. Under `FIFTY_REFUNDABLE`, the floor is half the gross fee — the floor of the gross fee multiplied by 5000 divided by 10000 — and the refundable amount is the larger of that floor and the gross fee minus the per-month amount times the occupied months. Under `NINETY_REFUNDABLE`, the floor is ninety percent of the gross fee — the floor of the gross fee multiplied by 9000 divided by 10000 — and the refundable amount is the larger of that floor and the gross fee minus the per-month amount times the occupied months. Each basis-point product is floored toward zero, and the result is an integer number of cents.

The two refund variants differ only at the floored-plan branches. Under the `VOLUNTARY` variant, full amortization applies exactly as written above. Under the `DEATH` variant, the `FIFTY_REFUNDABLE` and `NINETY_REFUNDABLE` plans pay the full floor regardless of how many months were occupied — that is, the refundable amount equals the floor amount and the amortization subtraction is dropped entirely — while the `DECLINING` plan is unaffected and equals exactly the voluntary value. After a refund disbursement has been created, a `FinanceOfficer` settles it, driving it from `PENDING` to `SETTLED` and stamping `settlement_period_index` with the community's current `current_period_index`.

### 3.8. Resident Council Governance

Each community has exactly one resident council, created by a `FinanceOfficer` with a `community_id`, a `name`, and an optional `quorum_pct_bps` (default 5000, i.e. the basis points of active residencies that must cast a vote for a resolution to be decidable). Against a council, the officer drafts resolutions; a resolution names its parent through `council_id`, carries a `title`, and starts in `DRAFT` with `yes_votes`, `no_votes`, and `eligible_voter_count` all at 0. A resolution proceeds through `DRAFT`, `OPEN`, and then to one of two terminal states, `PASSED` or `FAILED`.

Opening a resolution drives it from `DRAFT` to `OPEN`; the resolution must be `DRAFT`, else `ERR_RESOLUTION_NOT_DRAFT`. Opening snapshots `eligible_voter_count` as the count of residencies whose status is `ACTIVE` and whose community matches the resolution's community — this snapshot is the fixed denominator for both quorum and majority. While a resolution is `OPEN`, a `Resident` casts a vote on behalf of their residency by supplying the `residency_id` and a `choice` of exactly `YES` or `NO`; any other choice is rejected with `ERR_INVALID_REQUEST`. The resolution must be `OPEN` to accept a vote, else `ERR_RESOLUTION_NOT_OPEN`. A residency may cast at most one vote per resolution and must be `ACTIVE` to vote; a second vote from the same residency, or a vote from a non-`ACTIVE` residency, is rejected with `ERR_DUPLICATE_VOTE`. A `YES` choice increments `yes_votes`; a `NO` choice increments `no_votes`.

Closing a resolution moves it out of `OPEN` to either `PASSED` or `FAILED`. The resolution must be `OPEN`, else `ERR_RESOLUTION_NOT_OPEN`. Quorum must be met, and quorum is met when the total votes cast — `yes_votes` plus `no_votes` — multiplied by 10000 is at least the `eligible_voter_count` multiplied by the council's `quorum_pct_bps`; if that threshold is not reached, the close is rejected with `ERR_QUORUM_NOT_MET`. When quorum is met, the outcome is decided by simple majority: if `yes_votes` is strictly greater than `no_votes`, the resolution closes `PASSED`; otherwise — when the yes votes do not exceed the no votes — it closes `FAILED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the action endpoints that drive a state transition, advance the clock, or settle a refund — return a `200 OK` status code. The reserve-report endpoint generates a fresh disclosure record and returns `201 Created`. All list and get endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ccrc/communities` | Create a community | FinanceOfficer |
| GET | `/ccrc/communities` | List communities | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/communities/{cid}` | Get a community | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/communities/{cid}/clock/advance` | Advance the community clock; accrue occupancy; sweep expired holds | FinanceOfficer |
| POST | `/ccrc/contract-plans` | Create a contract plan | FinanceOfficer |
| GET | `/ccrc/contract-plans` | List contract plans (filter by community_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/contract-plans/{pid}` | Get a contract plan | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/units` | Create a unit | AdmissionsDirector |
| GET | `/ccrc/units` | List units (filter by community_id, care_level, status) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/units/{uid}` | Get a unit | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/residents` | Register a prospective resident | AdmissionsDirector |
| GET | `/ccrc/residents` | List residents (filter by community_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/residents/{resdid}` | Get a resident | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/residencies` | Open a residency contract | AdmissionsDirector |
| GET | `/ccrc/residencies` | List residencies (filter by community_id, status, unit_id, contract_plan_id, primary_resident_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/residencies/{rid}` | Get a residency | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/residencies/{rid}/assign-unit` | Assign an independent unit directly | AdmissionsDirector |
| POST | `/ccrc/residencies/{rid}/activate` | Activate a reserved residency | AdmissionsDirector |
| POST | `/ccrc/residencies/{rid}/terminate` | Terminate a residency; refund and cascade releases | AdmissionsDirector |
| POST | `/ccrc/residencies/{rid}/second-persons` | Add a second person to a residency | AdmissionsDirector |
| GET | `/ccrc/second-persons` | List second persons (filter by residency_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/second-persons/{spid}` | Get a second person | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/second-persons/{spid}/remove` | Remove a second person | AdmissionsDirector |
| POST | `/ccrc/waitlist-entries` | Enqueue a residency onto the priority waitlist | AdmissionsDirector |
| GET | `/ccrc/waitlist-entries` | List waitlist entries (filter by community_id, residency_id, target_care_level, status) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/waitlist-entries/{wid}` | Get a waitlist entry | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/waitlist-entries/{wid}/offer` | Offer a unit to the head waitlist entry | AdmissionsDirector |
| POST | `/ccrc/waitlist-entries/{wid}/place` | Place the head waitlist entry into a unit | AdmissionsDirector |
| POST | `/ccrc/waitlist-entries/{wid}/withdraw` | Withdraw a waitlist entry | AdmissionsDirector |
| POST | `/ccrc/care-transitions` | Propose a care-level transition | CareCoordinator |
| GET | `/ccrc/care-transitions` | List care transitions (filter by residency_id, status) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/care-transitions/{ctid}` | Get a care transition | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/care-transitions/{ctid}/apply` | Apply a proposed care transition | CareCoordinator |
| POST | `/ccrc/care-transitions/{ctid}/revert` | Revert a proposed care transition | CareCoordinator |
| POST | `/ccrc/bed-reservations` | Hold a skilled health-center bed | CareCoordinator |
| GET | `/ccrc/bed-reservations` | List bed reservations (filter by residency_id, unit_id, status) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/bed-reservations/{brid}` | Get a bed reservation | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/bed-reservations/{brid}/occupy` | Convert a held reservation to occupied | CareCoordinator |
| POST | `/ccrc/bed-reservations/{brid}/release` | Release a held or occupied reservation | CareCoordinator |
| POST | `/ccrc/residencies/{rid}/invoices` | Issue a monthly service-fee invoice | FinanceOfficer |
| GET | `/ccrc/invoices` | List monthly invoices (filter by residency_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/invoices/{invid}` | Get a monthly invoice | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/refund-disbursements` | List refund disbursements (filter by residency_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/refund-disbursements/{dsbid}` | Get a refund disbursement | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/refund-disbursements/{dsbid}/settle` | Settle a pending refund | FinanceOfficer |
| POST | `/ccrc/communities/{cid}/reserve-reports` | Generate an actuarial reserve disclosure report | FinanceOfficer |
| POST | `/ccrc/councils` | Create the resident council for a community | FinanceOfficer |
| GET | `/ccrc/councils` | List councils (filter by community_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/councils/{coid}` | Get a council | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/council-resolutions` | Draft a council resolution | FinanceOfficer |
| GET | `/ccrc/council-resolutions` | List council resolutions (filter by council_id) | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| GET | `/ccrc/council-resolutions/{resid}` | Get a council resolution | FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident |
| POST | `/ccrc/council-resolutions/{resid}/open` | Open a resolution for voting | FinanceOfficer |
| POST | `/ccrc/council-resolutions/{resid}/votes` | Cast a vote on an open resolution | Resident |
| POST | `/ccrc/council-resolutions/{resid}/close` | Close an open resolution | FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ADMISSIONS_FROZEN` | 403 |
| `ERR_RESIDENCY_NOT_DEPOSIT_HELD` | 409 |
| `ERR_RESIDENCY_NOT_RESERVED` | 409 |
| `ERR_RESIDENCY_NOT_ACTIVE` | 409 |
| `ERR_RESIDENCY_NOT_WAITLISTED` | 409 |
| `ERR_NO_UNIT_ASSIGNED` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_UNIT_CARE_LEVEL_MISMATCH` | 422 |
| `ERR_DUPLICATE_WAITLIST_ENTRY` | 409 |
| `ERR_WAITLIST_ENTRY_NOT_PENDING` | 409 |
| `ERR_WAITLIST_ENTRY_NOT_PLACEABLE` | 409 |
| `ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE` | 409 |
| `ERR_WAITLIST_NOT_HEAD` | 409 |
| `ERR_CARE_TRANSITION_NOT_PROPOSED` | 409 |
| `ERR_INVALID_CARE_STEP` | 422 |
| `ERR_NO_BED_OCCUPIED` | 409 |
| `ERR_SECOND_PERSON_EXISTS` | 409 |
| `ERR_BED_RESERVATION_NOT_HELD` | 409 |
| `ERR_BED_RESERVATION_NOT_RELEASABLE` | 409 |
| `ERR_BED_RESERVATION_EXPIRED` | 409 |
| `ERR_INVALID_HOLD_WINDOW` | 422 |
| `ERR_BED_CAPACITY_EXCEEDED` | 409 |
| `ERR_UNIT_NOT_SKILLED` | 422 |
| `ERR_INVALID_CLOCK_ADVANCE` | 422 |
| `ERR_RESOLUTION_NOT_DRAFT` | 409 |
| `ERR_RESOLUTION_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |

# HCV Landlord Participation API — Product Requirements Document

## 1. Introduction

The Housing Choice Voucher (HCV) program places low-income families into privately owned rental housing and splits each month's rent between the family and the public housing authority. This document specifies the API through which a public housing authority administers the landlord-facing side of that program: registering landlords and their properties, listing individual units, contracting those units to voucher families, inspecting them against housing quality standards, calculating the split between the tenant portion and the authority-paid Housing Assistance Payment (HAP), and winding a contract down when the tenancy ends.

A participating landlord's journey is long-running. It begins when the authority registers the landlord's legal identity, continues as units are listed and matched to voucher families, and then settles into a yearly rhythm of inspections, rent-recertifications, and monthly disbursements. Along the way the system must respond to off-cycle events — a failed inspection that triggers abatement of subsidy payments, a landlord requesting a mid-term rent increase, or a family exercising portability to move to a different payment-standard area. Every one of these transitions touches multiple records at once (a failed inspection cascades to the unit, the monthly payment, and the contract), so the API leans on explicit state machines and optimistic-concurrency guards rather than implicit side effects.

This document is written for the engineers who will implement the service. §2 pins down the cross-cutting contracts that every endpoint obeys; §3 walks the business workflows in narrative form; §4 and §5 are the reference tables for HTTP surface area and error codes. All endpoints are mounted under the `/hcv` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. Three roles are recognized, and the spelling is exact:

- `HousingAuthorityAdmin` — public housing authority staff. This role's `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's foreign key.
- `Landlord` — a participating landlord. This role is entity-backed: when `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord` record, and ownership checks on any resource that references a landlord compare the resource's `landlord_id` (resolved through `Unit -> Property -> Landlord` when the resource is a unit, contract, inspection, or repair item) to `X-User-ID`.
- `Inspector` — an HQS inspector. Like the admin, this role's `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

A request missing `X-User-Role`, carrying an unrecognized role value, or missing `X-User-ID` when the role is entity-backed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks run before any resource is loaded.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and may not be negative. List responses return rows sorted by `created_at` ascending, and the `meta` envelope includes `limit`, `offset`, `total_count`, and `has_more` so a client can page deterministically through a stable result set.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix (no `land_`, `unit_`, or similar decoration). In addition to `id`, most entities carry `created_at`, `updated_at`, and `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set on creation and never changes, while `updated_at` is refreshed on every mutation. `version` is an integer that starts at 1 on creation and is incremented by exactly 1 on every mutation of that record, including mutations driven by system cascades rather than by a direct client call. The `HAPPayment` entity is the exception: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent on `HAPPayment` rows, and no endpoint exposes or requires a payment `version`.

### 2.5. Validation Order and Optimistic Concurrency Control

When a request fails more than one rule, the server reports the first failure in a fixed priority order rather than an arbitrary one. The evaluation sequence is: authentication of the headers first (`ERR_UNAUTHENTICATED`); then role-based permission on the endpoint (`ERR_UNAUTHORIZED`); then existence of every path-parameter and body-referenced resource, validated left-to-right as the identifiers appear in the URL and then the payload (`ERR_NOT_FOUND`); then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); then the optimistic-concurrency version match (`ERR_STALE_VERSION`); then the landlord-ownership check (`ERR_NOT_OWNER`); then the landlord-active check (`ERR_LANDLORD_SUSPENDED`); then the rent-increase timing check (`ERR_INCREASE_TOO_EARLY`); then the inspection-schedule timing check (`ERR_SCHEDULE_IN_PAST`); then the voucher-size match (`ERR_VOUCHER_SIZE_MISMATCH`); then the one-live-contract-per-unit check (`ERR_UNIT_ALREADY_UNDER_CONTRACT`); then amount positivity (`ERR_INVALID_AMOUNT`); then the rent-reasonableness ceiling (`ERR_RENT_NOT_REASONABLE`); then the fail-requires-items precondition (`ERR_FAIL_REQUIRES_ITEMS`); and finally the all-items-repaired precondition (`ERR_OPEN_REPAIR_ITEMS`). A consequence of this ordering is that a mid-flight authentication failure masks every other problem, and a missing resource masks every state or business rule that would otherwise fire.

Two write endpoints participate in optimistic concurrency control. Creating a HAP contract carries a required `expected_unit_version` field whose value must equal the target unit's current `version`; if the unit's version has advanced since the client last read it (for example because another writer has just created a contract for that same unit, flipping it from `LISTED` to `UNDER_CONTRACT` and bumping its version), the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Completing a recertification carries a required `expected_contract_version` field whose value must equal the parent contract's current `version`; because completing a recertification advances the contract's `next_recert_due_date` and increments the contract's `version`, a client that has not observed the most recent write is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to double-apply the anniversary advance. No other endpoint takes an `expected_*_version` field.

### 2.6. Ownership and Landlord Standing

Whenever the acting role is `Landlord` and the endpoint mutates a landlord-scoped resource, the server verifies that the resource's chain of ownership terminates at the acting landlord. The chain runs from `Unit.property_id` to `Property.landlord_id` for units, from `HAPContract.unit_id` through the unit to the property for contracts, and one level further for inspections and repair items. If the acting landlord's `id` does not equal the owning `landlord_id`, the request is rejected with `ERR_NOT_OWNER` (HTTP 403). This ownership check applies to: creating a unit within a property, creating a contract, submitting a contract, withdrawing a contract, delisting a unit, marking a repair item repaired, requesting a reinspection, creating a rent-increase request, and withdrawing a rent-increase request.

A landlord's standing also constrains what it may do. A landlord whose `status` is `SUSPENDED` or `TERMINATED` may not create a property, may not create a unit within a property, and may not initiate a new HAP contract; any of those attempts is rejected with `ERR_LANDLORD_SUSPENDED` (HTTP 409). Suspension does not unwind contracts that are already active — it only blocks the creation of new inventory and new contracts.

### 2.7. Monetary Precision and the Logical Clock

All money amounts are stored and returned as integer cents (`contract_rent_cents`, `approved_rent_cents`, `hap_portion_cents`, `tenant_portion_cents`, `annual_income_cents`, `new_family_income_cents`, `amount_cents`, `rent_cents`, `requested_rent_cents`, `hap_amount_cents`). Wherever a formula produces a fractional cent — a proportional share, a median across an even number of comparables, a per-day abatement deduction — the result is rounded half-up to the nearest whole cent. Two domain constants anchor the math: the family's minimum share of rent is thirty percent of monthly income (`INCOME_RATIO` of 0.30), and the rent-reasonableness ceiling is ten percent above the comparable-rent median (`COMPARABLE_CAP_RATIO` of 1.10).

The server maintains a logical clock that governs every date-driven transition. Before any client has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server MUST NOT fall back to real wall-clock time. An admin-only test-driving capability accepts a `to_iso8601` instant and sets the server's current UTC instant to that value. Advancing the clock evaluates every date-driven system transition: contracts whose failed-inspection repair deadline has now passed move from `ACTIVE` to `ABATED`, and recertifications whose `due_date` has now passed while still `OPEN` move to `OVERDUE`.

## 3. Business Logic & Workflows

### 3.1. Registering Landlords, Properties, and Units

A public housing authority onboards a new participating landlord by registering the landlord's legal identity. An admin supplies the `legal_name` and `tax_id`; `tax_id` is unique across all landlord records, so a duplicate tax ID is rejected at create time. The new landlord record starts in `ACTIVE` status. From there the inventory builds down through two levels: a `Property` is created with a `landlord_id` pointing at the owning landlord, a street `address`, and a `zip_code` that determines which payment-standard area the property falls into. Within a property, a `Unit` is created with a `property_id` pointing at the containing property, a `unit_label` (the apartment or suite number), and a `bedroom_count` that drives the payment-standard lookup. New units begin life `LISTED`. Either an admin or the owning landlord may create properties and units, but only while the landlord's `status` is `ACTIVE` — a suspended landlord is blocked from adding inventory with `ERR_LANDLORD_SUSPENDED`. A landlord who lists a unit in error may delist it, moving the unit from `LISTED` to `DELISTED` and incrementing the unit's `version`; delisting is owner-only and is only defined while the unit is `LISTED`, so attempting it against an `UNDER_CONTRACT` or `SUSPENDED_ABATEMENT` unit is rejected with `ERR_INVALID_STATE`.

A landlord's registration is not permanent. An admin may suspend an `ACTIVE` landlord, moving the record to `SUSPENDED` and incrementing `Landlord.version`. Suspension blocks new HAP contract creation for that landlord's units but does not touch existing contracts. A suspended landlord may be reinstated, moving `SUSPENDED` back to `ACTIVE`. An admin may also terminate an `ACTIVE` landlord outright, but only when no HAP contract for any of the landlord's units is in `ACTIVE` or `ABATED` status — the check exists so the authority never orphans a live subsidy stream.

The other side of the pairing is the voucher family, which an admin registers by supplying a `family_code` (unique across all voucher families), a `voucher_bedroom_size` recording the largest unit the voucher authorizes, and the household's `annual_income_cents`. The family's `status` begins at `SEARCHING` and remains there until a contract activates.

### 3.2. Payment Standards, Comparables, and Rent Reasonableness

Before any contract can be priced, the authority maintains two reference datasets. A `PaymentStandard` row pins a monthly subsidy ceiling for a combination of `zip_code` and `bedroom_count`, expressed as `amount_cents`. Each row is effective from `effective_from` (an ISO `YYYY-MM-DD` date, inclusive) through `effective_to` (also inclusive); a null `effective_to` means the row is open-ended. When more than one row matches a given ZIP, bedroom count, and target date, the row with the latest `effective_from` wins; a remaining tie is broken by `created_at` ascending. The second dataset is `RentComparable`, a record of observed market rents: each row carries the comparable's `zip_code`, `bedroom_count`, the observed `rent_cents`, and the `survey_date` on which the rent was surveyed.

When a contract is submitted for review, the system runs the rent-reasonableness calculation to set `approved_rent_cents`. The procedure first gathers the comparables: every `RentComparable` row whose `zip_code` equals the property's `zip_code`, whose `bedroom_count` equals the unit's `bedroom_count`, and whose `survey_date` falls within the twelve months preceding the current logical date, with the twelve-month boundary inclusive. If no comparables survive that filter, the approved rent is the lesser of the landlord's requested `contract_rent_cents` and the applicable payment standard's `amount_cents`. If at least one comparable survives, the median of their `rent_cents` values is computed — for an even number of comparables this is the average of the two middle values, rounded half-up to whole cents — and the cap becomes the lesser of the payment standard's `amount_cents` and the median multiplied by 1.10 (rounded half-up to cents). The approved rent is then the lesser of `contract_rent_cents` and that cap. The applicable payment standard for this calculation is the row whose `zip_code` and `bedroom_count` match the unit and whose effective window contains the contract's `lease_start_date`.

Once the approved rent is known, the HAP split is computed to determine `tenant_portion_cents` and `hap_portion_cents`. The family's minimum contribution is thirty percent of monthly income: `annual_income_cents` multiplied by 0.30, divided by 12, rounded half-up to cents. The tenant's base portion is the larger of that minimum and the excess of `approved_rent_cents` over the payment standard's `amount_cents` (this excess is zero when the approved rent is at or below the standard). The tenant portion is then capped at `approved_rent_cents`, and the housing authority's portion is whatever remains of `approved_rent_cents` after the tenant portion is subtracted. Because the tenant-minimum is rounded before the larger-of comparison, an implementer must round the thirty-percent figure first and only then compare.

### 3.3. From Listing to Lease: The Contract Pipeline

When a landlord and a voucher family agree on a unit, the landlord initiates a HAP contract by supplying the target `unit_id`, the family's `family_id`, the requested `contract_rent_cents`, and the `lease_start_date`. Because another writer might have just placed the same unit under contract, the request must also carry `expected_unit_version` matching the unit's current `version`; a stale value is rejected with `ERR_STALE_VERSION` before any other business rule is examined. Several guards then fire in the fixed order of §2.5: the landlord must own the unit (`ERR_NOT_OWNER`); the landlord must be `ACTIVE` (`ERR_LANDLORD_SUSPENDED`); the family's `voucher_bedroom_size` must be at least the unit's `bedroom_count`, since a family may under-occupy a smaller unit but may not over-occupy a larger one (`ERR_VOUCHER_SIZE_MISMATCH`); the unit must not already have another HAP contract in `DRAFT`, `PENDING_INSPECTION`, `APPROVED`, `ACTIVE`, or `ABATED` (`ERR_UNIT_ALREADY_UNDER_CONTRACT`); and both `contract_rent_cents` and the family's `annual_income_cents` must be positive-or-zero as appropriate (`ERR_INVALID_AMOUNT`). On success the contract is created in `DRAFT` status, with `approved_rent_cents`, `hap_portion_cents`, and `tenant_portion_cents` all initialized to 0 and `next_recert_due_date` null. The unit simultaneously flips from `LISTED` to `UNDER_CONTRACT` and its `version` is bumped — this is the version bump that a competing contract-creation request would observe.

A draft becomes real when the landlord submits it for review. Submission is only defined from `DRAFT`, is owner-only, and requires `contract_rent_cents` to be greater than zero. Submission runs the rent-reasonableness procedure to set `approved_rent_cents`, runs the HAP split to set `hap_portion_cents` and `tenant_portion_cents`, auto-creates an `INITIAL` inspection in `SCHEDULED` status, and moves the contract from `DRAFT` to `PENDING_INSPECTION` with a version bump. If the landlord thinks better of the submission before the inspector records a result, withdrawing the contract moves `PENDING_INSPECTION` back to `DRAFT`, closes the scheduled `INITIAL` inspection by moving it from `SCHEDULED` to `CLOSED`, resets `approved_rent_cents`, `hap_portion_cents`, and `tenant_portion_cents` all to 0, and bumps the contract's `version`.

### 3.4. Inspection, Repair, and Abatement

Inspections exist to enforce housing quality standards, and every contract touches at least one: the auto-created `INITIAL` inspection that gates approval. Beyond that, an admin may schedule additional inspections of type `ANNUAL`, `REINSPECTION`, or `COMPLAINT` against a contract, supplying an `inspection_type` and a `scheduled_date`. The scheduled date must not precede the current logical date — a back-dated schedule is rejected with `ERR_SCHEDULE_IN_PAST`.

When the inspector visits, they record a result. Recording a `PASS` against a `SCHEDULED` inspection moves it to `PASSED`, sets `result_recorded_date` to the current logical date, and bumps its `version`. If the passing inspection is the contract's `INITIAL` inspection and the contract is currently `PENDING_INSPECTION`, the contract simultaneously moves from `PENDING_INSPECTION` to `APPROVED` with a version bump of its own. Recording a `FAIL` is more involved: the inspector must have attached at least one `RepairItem` to the inspection before or with the failure result, otherwise the record-result call is rejected with `ERR_FAIL_REQUIRES_ITEMS`. Each repair item is attached to its parent inspection via `inspection_id` and carries a `description` plus an optional `is_life_threatening` flag defaulting to `false`. When the result is recorded as `FAIL`, the inspection moves from `SCHEDULED` to `FAILED`, `result_recorded_date` is set, and every attached repair item begins life in `OPEN` status. If the failed inspection's contract is currently `ACTIVE`, the repair-deadline clock is now ticking; the contract will auto-abate when the deadline breaches.

The repair deadline is measured from `result_recorded_date`. An ordinary item allows the landlord thirty days; a life-threatening item — one whose `is_life_threatening` is `true` — allows only one day. As soon as the logical clock advances past the deadline of any `OPEN` or `FAILED_VERIFICATION` repair item on a failed inspection, the contract flips from `ACTIVE` to `ABATED`, the unit flips from `UNDER_CONTRACT` to `SUSPENDED_ABATEMENT`, and every `HAPPayment` row for a period after the breach that was still `SCHEDULED` flips to `ABATED_HELD`. The contract's `version` is incremented. This cascade is the system's enforcement lever: subsidy stops flowing until the repairs are verified.

To cure the abatement, the landlord marks each repair item repaired, moving it from `OPEN` (or, after a failed verification, from `FAILED_VERIFICATION`) to `REPAIRED`. Marking is owner-only. Once every item on the inspection is in `REPAIRED`, the landlord requests a reinspection, moving the inspection from `FAILED` to `REPAIR_VERIFICATION`; if even one item is not yet `REPAIRED`, the request is rejected with `ERR_OPEN_REPAIR_ITEMS`. During the verification visit the inspector verifies each repaired item, recording an `outcome`. A `PASS` outcome moves the item from `REPAIRED` to `VERIFIED`; a `FAIL` outcome moves the item from `REPAIRED` to `FAILED_VERIFICATION`, drops the inspection from `REPAIR_VERIFICATION` back to `FAILED`, and restarts the repair-deadline clock from the new verification date. When the final non-`VERIFIED` item on the inspection is verified `PASS`, three things happen in one cascade: the inspection moves from `REPAIR_VERIFICATION` to `CLOSED`; the contract, if it was `ABATED`, moves back to `ACTIVE`; and the unit moves from `SUSPENDED_ABATEMENT` back to `UNDER_CONTRACT`. The `ABATED_HELD` payment rows are then recomputed with the abatement proration described in §3.6, and rows whose period has not yet disbursed return to `SCHEDULED` while rows already `PAID` stay `PAID` with the delta recorded.

### 3.5. Activation and the Payment Start Date

An approved contract does not start paying until the lease begins. An admin activates the contract once the current logical date is on or after `lease_start_date`; attempting activation before the lease start is rejected with `ERR_INVALID_STATE` because the transition is only defined when the contract is `APPROVED` and the lease start has arrived. Activation does four things. First, it sets `next_recert_due_date` to the date one year after `lease_start_date` — the first annual recertification anniversary. Second, it moves the linked voucher family from `SEARCHING` to `LEASED`. Third, it schedules the first `HAPPayment` row. Fourth, it increments the contract's `version`.

The payment-start rule is month-aligned. If the day-of-month of `lease_start_date` is 1, the first payment's `period_month` is the first of that same month. If the lease starts on any day from the 2nd through the 31st, the first payment's `period_month` is the first of the following month — the partial first month is the landlord's responsibility and no prorated HAP is paid for it. Either way, exactly one `HAPPayment` row is created at activation: its `period_month` set as just described, its `hap_amount_cents` equal to the contract's `hap_portion_cents`, and its `disbursement_status` set to `SCHEDULED`. Subsequent months' payment rows are managed outside the activation cascade.

### 3.6. Disbursement and Abatement Proration

Each `HAPPayment` row represents one month's subsidy for one contract. A row starts `SCHEDULED`, and an admin disburses it by moving `disbursement_status` from `SCHEDULED` to `PAID`; disbursement is only defined when the parent contract is `ACTIVE`, so a payment on an abated contract cannot be disbursed until the abatement is cured. When a contract enters `ABATED`, every future `SCHEDULED` row for that contract flips to `ABATED_HELD`. When the contract exits abatement back to `ACTIVE`, each `ABATED_HELD` row is recomputed with abatement proration, processing the rows in `period_month` ascending order.

Abatement proration works per payment row, not aggregated across the abatement window. For each row, count the calendar days within that row's `period_month` during which the contract was in `ABATED` status — the abatement window is start-inclusive and end-exclusive. Divide that count by the total calendar days in the month to get the abated fraction, multiply the full-month `hap_portion_cents` by that fraction, round half-up to whole cents, and subtract the result from `hap_portion_cents` to get the new `hap_amount_cents`. If every day of the month was abated, the new `hap_amount_cents` is 0. After recompute, a row whose period has not yet disbursed returns to `SCHEDULED` (including the zero-amount case, which is kept for record-keeping); a row that was already `PAID` stays `PAID` with the delta recorded. When a contract terminates, every future payment that is still `SCHEDULED` or `ABATED_HELD` flips to `VOID`.

### 3.7. Recertification and Rent Increases

Once a year the authority recertifies the family's income and resets the payment split. An admin opens a `Recertification` against an `ACTIVE` contract by supplying the `contract_id`, the `due_date` (which should be the lease anniversary), and the `new_family_income_cents` for the coming period. The new recertification begins `OPEN`. If the logical clock advances past `due_date` while the recertification is still `OPEN`, the system flips it to `OVERDUE` — a signal to caseworkers that the anniversary has been missed.

Completing the recertification is the versioned write. The request must carry `expected_contract_version` equal to the contract's current `version`; a stale value is rejected with `ERR_STALE_VERSION` because completing the recertification advances the contract's `next_recert_due_date` and bumps its `version`, and a client working from an old snapshot would otherwise double-apply the anniversary. On success, the recertification moves from `OPEN` to `COMPLETED`, the voucher family's `annual_income_cents` is overwritten with `new_family_income_cents`, the HAP split is recomputed against the new income to refresh `hap_portion_cents` and `tenant_portion_cents`, the contract's `next_recert_due_date` advances by one year, and a new `Recertification` row is auto-created with its `due_date` set to the newly advanced `next_recert_due_date`. Both the recertification's and the contract's `version` increment.

A landlord who believes market rents have moved may request a rent increase by submitting the `contract_id`, the `requested_rent_cents`, and the `effective_date`. The effective date must be on or after the contract's `next_recert_due_date` — an earlier date is rejected with `ERR_INCREASE_TOO_EARLY` both at request time and again at approval time, so an increase cannot slip in mid-year even if the anniversary moves between the two calls. The new request begins `PENDING`. An admin may deny it, moving it to `DENIED`, or the landlord may withdraw it, moving it to `WITHDRAWN` (owner-only). To approve it, the admin's approval call re-runs rent reasonableness against the requested rent: the requested `requested_rent_cents` must be at most the lesser of the applicable payment standard and the comparable-median times 1.10 when comparables exist, or at most the payment standard when they do not. A request that exceeds the ceiling is rejected with `ERR_RENT_NOT_REASONABLE`. Approval moves the request from `PENDING` to `APPROVED`, updates the contract's `contract_rent_cents` and `approved_rent_cents` to the requested figure, and recomputes `hap_portion_cents` and `tenant_portion_cents` effective from `effective_date` forward — prior periods are unchanged. The request's `version` increments.

### 3.8. Termination, Move-Out, and Portability

A tenancy ends when an admin terminates the contract. Termination is defined from both `ACTIVE` and `ABATED`. From `ACTIVE`, the cascade moves the contract to `TERMINATED`, returns the voucher family from `LEASED` to `SEARCHING`, returns the unit from `UNDER_CONTRACT` to `LISTED`, and flips every future `SCHEDULED` payment to `VOID`. From `ABATED`, the same cascade runs except that the unit moves from `SUSPENDED_ABATEMENT` to `LISTED` and any future `ABATED_HELD` payments also flip to `VOID`. Either way the contract's `version` increments and the family is free to search for a new unit. A family that gives up searching may be exited from the program by an admin, moving the family from `SEARCHING` to `EXITED`.

Portability handles the case where a family wants to use its voucher in a different payment-standard area. An admin initiates a `PortabilityAction` by supplying the `family_id`, the `destination_zip`, and an `action_type` of either `PORT_IN` or `PORT_OUT`. The new action begins `INITIATED`. An admin may accept the billing arrangement, moving `INITIATED` to `BILLING_ACCEPTED`; may terminate the action before billing is accepted, moving `INITIATED` to `TERMINATED`; or may absorb the family into the destination area, moving `BILLING_ACCEPTED` to `ABSORBED`. Absorption is the moment the move becomes real: if the action's `action_type` is `PORT_OUT`, the voucher family moves from `LEASED` to `PORTED_OUT` and the linked `ACTIVE` contract moves to `TERMINATED` through the same move-out cascade that a direct termination would trigger (unit back to `LISTED`, future payments voided). When a family has ported in from a different payment-standard area, subsequent HAP-split recalculations use the destination area's payment standard even when that standard is lower than the origin's, so the landlord may receive a lower HAP than under the origin standard.

## 4. Endpoint Definitions

All endpoints are mounted under the `/hcv` prefix. Creating a new resource returns HTTP 201; modifying an existing resource returns HTTP 200; list and single-resource retrieval return HTTP 200. Request and response bodies follow the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/hcv/landlords` | Register a landlord | `HousingAuthorityAdmin` |
| GET | `/hcv/landlords` | List landlords | `HousingAuthorityAdmin` |
| GET | `/hcv/landlords/{id}` | Get a landlord | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/landlords/{id}/suspend` | Suspend a landlord | `HousingAuthorityAdmin` |
| POST | `/hcv/landlords/{id}/reinstate` | Reinstate a suspended landlord | `HousingAuthorityAdmin` |
| POST | `/hcv/landlords/{id}/terminate` | Terminate a landlord registration | `HousingAuthorityAdmin` |
| GET | `/hcv/landlords/{id}/properties` | List a landlord's properties | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/properties` | Create a property for a landlord | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/properties/{id}` | Get a property | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/properties/{id}/units` | List a property's units | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/properties/{id}/units` | Create a unit within a property | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/units/{id}` | Get a unit | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/units/{id}/delist` | Delist a unit | `Landlord` |
| GET | `/hcv/units/{id}/contracts` | List a unit's HAP contracts | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/voucher-families` | Register a voucher family | `HousingAuthorityAdmin` |
| GET | `/hcv/voucher-families/{id}` | Get a voucher family | `HousingAuthorityAdmin` |
| POST | `/hcv/voucher-families/{id}/exit` | Exit a searching family from the program | `HousingAuthorityAdmin` |
| GET | `/hcv/voucher-families/{id}/portability-actions` | List a family's portability actions | `HousingAuthorityAdmin` |
| POST | `/hcv/payment-standards` | Create a payment standard row | `HousingAuthorityAdmin` |
| GET | `/hcv/payment-standards` | List payment standards | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/rent-comparables` | Record a market-rent comparable | `HousingAuthorityAdmin` |
| GET | `/hcv/rent-comparables` | List rent comparables | `HousingAuthorityAdmin` |
| POST | `/hcv/contracts` | Create a HAP contract in `DRAFT` | `Landlord` |
| GET | `/hcv/contracts` | List HAP contracts, optionally filtered by `family_id` | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/contracts/{id}` | Get a HAP contract | `HousingAuthorityAdmin`, `Landlord`, `Inspector` |
| POST | `/hcv/contracts/{id}/submit` | Submit a contract for review | `Landlord` |
| POST | `/hcv/contracts/{id}/withdraw` | Withdraw a submitted contract back to `DRAFT` | `Landlord` |
| POST | `/hcv/contracts/{id}/activate` | Activate an approved contract | `HousingAuthorityAdmin` |
| POST | `/hcv/contracts/{id}/terminate` | Terminate an active or abated contract | `HousingAuthorityAdmin` |
| GET | `/hcv/contracts/{id}/inspections` | List a contract's inspections | `HousingAuthorityAdmin`, `Landlord`, `Inspector` |
| GET | `/hcv/contracts/{id}/hap-payments` | List a contract's HAP payments | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/contracts/{id}/rent-increase-requests` | List a contract's rent increase requests | `HousingAuthorityAdmin`, `Landlord` |
| GET | `/hcv/contracts/{id}/recertifications` | List a contract's recertifications | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/contracts/{id}/inspections` | Schedule a non-initial inspection | `HousingAuthorityAdmin` |
| GET | `/hcv/inspections/{id}` | Get an inspection | `HousingAuthorityAdmin`, `Landlord`, `Inspector` |
| POST | `/hcv/inspections/{id}/record-result` | Record a PASS or FAIL result | `Inspector` |
| POST | `/hcv/inspections/{id}/request-reinspection` | Request reinspection after all items repaired | `Landlord` |
| GET | `/hcv/inspections/{id}/repair-items` | List an inspection's repair items | `HousingAuthorityAdmin`, `Landlord`, `Inspector` |
| POST | `/hcv/inspections/{id}/repair-items` | Attach a repair item to an inspection | `Inspector` |
| POST | `/hcv/repair-items/{id}/mark-repaired` | Mark a repair item repaired | `Landlord` |
| POST | `/hcv/repair-items/{id}/verify` | Verify or refute a repaired item | `Inspector` |
| POST | `/hcv/rent-increase-requests` | Request a rent increase | `Landlord` |
| GET | `/hcv/rent-increase-requests/{id}` | Get a rent increase request | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/rent-increase-requests/{id}/approve` | Approve a rent increase | `HousingAuthorityAdmin` |
| POST | `/hcv/rent-increase-requests/{id}/deny` | Deny a rent increase | `HousingAuthorityAdmin` |
| POST | `/hcv/rent-increase-requests/{id}/withdraw` | Withdraw a pending increase request | `Landlord` |
| POST | `/hcv/recertifications` | Open an annual recertification | `HousingAuthorityAdmin` |
| GET | `/hcv/recertifications/{id}` | Get a recertification | `HousingAuthorityAdmin`, `Landlord` |
| POST | `/hcv/recertifications/{id}/complete` | Complete a recertification | `HousingAuthorityAdmin` |
| POST | `/hcv/hap-payments/{id}/disburse` | Disburse a scheduled HAP payment | `HousingAuthorityAdmin` |
| POST | `/hcv/portability-actions` | Initiate a portability action | `HousingAuthorityAdmin` |
| GET | `/hcv/portability-actions/{id}` | Get a portability action | `HousingAuthorityAdmin` |
| POST | `/hcv/portability-actions/{id}/accept-billing` | Accept billing arrangement | `HousingAuthorityAdmin` |
| POST | `/hcv/portability-actions/{id}/absorb` | Absorb the ported family | `HousingAuthorityAdmin` |
| POST | `/hcv/portability-actions/{id}/terminate` | Terminate a portability action | `HousingAuthorityAdmin` |
| POST | `/hcv/_clock/set_current_utc` | Advance the logical clock | `HousingAuthorityAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_LANDLORD_SUSPENDED` | 409 |
| `ERR_INCREASE_TOO_EARLY` | 422 |
| `ERR_SCHEDULE_IN_PAST` | 422 |
| `ERR_VOUCHER_SIZE_MISMATCH` | 422 |
| `ERR_UNIT_ALREADY_UNDER_CONTRACT` | 409 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_RENT_NOT_REASONABLE` | 422 |
| `ERR_FAIL_REQUIRES_ITEMS` | 422 |
| `ERR_OPEN_REPAIR_ITEMS` | 409 |

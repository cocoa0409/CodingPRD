# Dmv Registration Title API — Product Requirements Document

## 1. Introduction

State Departments of Motor Vehicles routinely struggle with workflows that braid together half a dozen weakly-coupled regulatory regimes: a Vehicle Identification Number must be physically verified, ownership must transfer from a seller to a buyer, the federal REAL ID identity credential must be re-validated, an emissions inspection must clear within a moving window, taxes and registration fees must be assessed against a snapshot of the vehicle's curb weight and the buyer's residency, an electronic license plate must be physically issued, and salvage-branded titles must be siloed away from the clean-title pipeline. Existing batch systems force clerks to re-enter the same identifiers, hand-roll fee math, and reconcile salvage events against in-flight registrations after the fact — producing the kind of silent drift that audits inevitably surface.

This document defines the contract for a single-jurisdiction DMV system that unifies those workflows under one HTTP API. The API supports initial registration for newly-manufactured vehicles, ownership transfer with brand-aware title supersession, salvage branding with cascade enforcement, emissions inspection scheduling and outcome capture, REAL ID submission with a weighted document-score evaluation, lien attachment and release, fee assessment with a tiered processing surcharge, and electronic plate issuance with cyclic suspend/reinstate semantics. A deliberate segregation-of-duties boundary separates the clerk who assesses taxes from the clerk who issues the plate, and a compensating ledger guarantees that a tax assessment which sits unpaid for too long automatically unwinds with refund rows rather than disappearing.

The API is mounted under the prefix `/vehicles` and its sibling top-level resource paths (`/owners`, `/transfer-applications`, `/emissions-inspections`, `/titles`, `/lien-records`, `/real-id-applications`, `/plates`, `/transfer-applications/{id}/fee-ledger`, and an admin-only `/_clock/advance`). Every workflow expressed in §3 must, when implemented, also satisfy the global contracts in §2.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is exercising for this call. A request that omits either header is rejected with `ERR_AUTH_REQUIRED` at HTTP 401. A request whose `X-User-Role` is not one of the declared roles below is rejected with `ERR_INVALID_ROLE` at HTTP 403. A request whose role is declared but is not authorized to invoke the called endpoint (per the role/endpoint matrix implied by §4) is rejected with `ERR_ROLE_FORBIDDEN`, also at HTTP 403.

The nine roles are spelled exactly as follows: `Applicant`, `VinVerifier`, `TaxAssessor`, `PlateIssuer`, `SalvageOfficer`, `EmissionsInspector`, `LienClerk`, `RealIDReviewer`, and `PlatformAdmin`.

When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Owner` row; ownership checks on any resource that references an `Owner` (for example, a `TransferApplication` via its `applicant_owner_id`, or a `RealIDApplication` via its `owner_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is any of `VinVerifier`, `TaxAssessor`, `PlateIssuer`, `SalvageOfficer`, `EmissionsInspector`, `LienClerk`, `RealIDReviewer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, by remembering which `TaxAssessor` user-id ran fee assessment so the segregation-of-duties check can compare it against the `PlateIssuer` user-id later) but it does not match the value against any entity's `id`.

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted; its minimum is 1 and its maximum is 100. `offset` defaults to 0 when omitted; its minimum is 0. List endpoints sort results by `created_at` ascending (and, where the underlying entity does not carry `created_at`, by the system-supplied creation order, e.g. `issued_at` for a `Title` row). The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted resource is identified by a server-minted `id`, expressed as a UUID without any type prefix. Most entities additionally carry `created_at`, `updated_at`, and `version` — all of these are server-managed. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set once at resource creation and never changes, while `updated_at` is refreshed on every server-initiated mutation of the resource (including state-machine transitions and side-effects propagated from other resources). The `version` field is an integer that starts at 1 on creation and increments by 1 on every mutation.

Two entities are deliberate exceptions: `Title` rows carry only `id` and `issued_at` — they have no `updated_at` and no `version`. The `Title` lifecycle is captured by `superseded_at` and `is_active`, both of which are set by the system when a newer `Title` supersedes the older row; the older row remains historically queryable but is not "updated" in the usual sense. Similarly, `FeeLedgerEntry` rows carry only `id` and `occurred_at`; they are append-only, never edited, and have no `updated_at` and no `version`.

### 2.5. Optimistic Concurrency Control

PATCH endpoints accept an optional `version` field in the request body. When `version` is present, the server compares it against the target resource's current `version`; if they differ, the call is rejected with `ERR_VERSION_CONFLICT` at HTTP 409. When `version` is omitted, the concurrency check is skipped and the call proceeds against the current state. Every successful mutation increments `version` by 1 and refreshes `updated_at`.

### 2.6. Precision, Rounding, and Money Representation

All monetary amounts displayed on resources (the components of fee assessment — `fee_subtotal`, `processing_fee`, `total_due`, as well as `declared_sale_price`, `trade_in_value`, `principal_amount`) are stored and serialized as decimals with exactly two fractional digits. Any computed monetary amount is rounded to two decimal places using the round-half-up rule. Multi-step calculations round at each pinned step before the next step reads the value; the explicit rounding boundaries are stated alongside each calculation in §3. The `real_id_score` is also a number with exactly two fractional digits and is rounded half-up to two decimals.

`FeeLedgerEntry` rows record amounts in signed integer cents under `amount_cents`: debits posted by the assessment are positive, refunds posted by the timeout sweep are negative. The compensating-action invariant for any single `TransferApplication` is that the sum of all `amount_cents` values across its ledger is exactly zero once a refund cycle completes, and equals the positive `total_due` (converted to cents) while the assessment stands unpaid.

### 2.7. Nested Resource Resolution

Path parameters are resolved left-to-right. When a request hits, for example, the verify-vin entry point with both a `vehicle_id` and a transfer-application `id` in the path, the server first looks up the `Vehicle` (404 with `ERR_RESOURCE_NOT_FOUND` if absent), then the `TransferApplication`. Authorization is evaluated only after the resource chain has resolved successfully. The same left-to-right rule applies to the lien-creation path under `/titles/{title_id}/lien-records` (the `Title` must exist before the body is considered) and to the application-scoped fee-ledger listing under `/transfer-applications/{id}/fee-ledger`.

### 2.8. Validation Priority and Evaluation Order

All inbound requests are validated in a pinned priority order, and the **first** failing check determines the rejection. The order is:

1. Authentication — headers must be present (`ERR_AUTH_REQUIRED`).
2. Role recognition — `X-User-Role` must be one of the nine declared roles (`ERR_INVALID_ROLE`).
3. Endpoint authorization — the role must be permitted for the called endpoint (`ERR_ROLE_FORBIDDEN`).
4. Existence — every path-resolved resource id must exist (`ERR_RESOURCE_NOT_FOUND`), resolved left-to-right.
5. State checks — including the VIN-on-hold check (`ERR_VIN_ON_HOLD`), the transfer-application state-machine from-state check (`ERR_INVALID_STATE`), the salvage-lock check on the vehicle (`ERR_VEHICLE_SALVAGE_LOCKED`), and the emissions-start-while-salvage-pending check (also `ERR_VEHICLE_SALVAGE_LOCKED`).
6. Business safety — the emissions-expiry guard on fee assessment (`ERR_EMISSIONS_EXPIRED`), then the REAL ID revocation guard (`ERR_OWNER_REAL_ID_REVOKED`).
7. Business referential — the lien-active guard on fee assessment (`ERR_LIEN_ACTIVE`).
8. Business temporal — the inspection-slot overlap check (`ERR_INSPECTION_SLOT_OVERLAP`).
9. Business constraints — plate-number uniqueness (`ERR_PLATE_NUMBER_TAKEN`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), REAL ID revision limit (`ERR_REVISION_LIMIT_EXCEEDED`), odometer rollback (`ERR_ODOMETER_ROLLBACK`).
10. Business fiscal — payment-required guard on plate issuance (`ERR_PAYMENT_REQUIRED`).
11. Owner-holds guard on VIN verification (`ERR_OWNER_HAS_HOLDS`).
12. Release-reference required on lien release (`ERR_RELEASE_REFERENCE_REQUIRED`).
13. Optimistic concurrency check on PATCH endpoints (`ERR_VERSION_CONFLICT`).
14. Body shape and type conformance — VIN regex, plate regex, datetime format, numeric ranges (`ERR_VALIDATION`).

Because order is strict, the same request hitting two simultaneous failure modes always reports the higher-priority failure: a `PlateIssuer` who is also the `TaxAssessor` who ran fee assessment and who attempts to issue a plate on an application whose owner has had REAL ID revoked must see `ERR_OWNER_REAL_ID_REVOKED` (priority 10 — business safety) ahead of `ERR_SEGREGATION_OF_DUTIES` (priority 14 — business constraint).

### 2.9. Cascading Side Effects and Hierarchical Consistency

The system models the brand axis of a title (`title_status`) and the encumbrance axis (`lien_status`) as **independent parallel dimensions** on the same `Vehicle`. A change on one dimension never directly changes the other, but a change on either can cascade into emissions, plates, and in-flight transfer applications. Every cascade refreshes `updated_at` and increments `version` on every entity it touches. The precise cascade behavior is narrated alongside the workflow that triggers it in §3.

When a `TransferApplication` finalizes successfully, it creates a brand-new `Title` row for the destination `Owner`, marks the prior `Title` for that vehicle inactive by stamping `superseded_at` and flipping `is_active`, and updates `Vehicle.current_title_id` to point at the new row. Where a prior plate exists on the vehicle and the application is an ownership transfer, that prior plate is surrendered.

### 2.10. Status Codes

POST endpoints that create a brand-new resource return HTTP 201; mutation endpoints that drive an existing resource through its state machine or update its fields return HTTP 200. A successful DELETE returns HTTP 204. Validation, state, and business-rule violations return their declared HTTP status (401, 402, 403, 404, 409, or 422) carrying the error envelope defined in §2.2.

## 3. Business Logic & Workflows

### 3.1. Owners, Residency, and Outstanding Holds

An `Owner` enters the system through a self-creation flow available to `Applicant` and `PlatformAdmin`; the request body carries `full_name` (1 to 100 characters), `date_of_birth` (an ISO 8601 date in YYYY-MM-DD form), and `residency_state` (a two-character ISO 3166-2:US subdivision code). Upon creation, the server computes `is_resident` by checking whether `residency_state` equals the jurisdiction code `CA` — the boolean is true if and only if the codes match. `outstanding_holds_count` starts at 0 and is maintained by the system as unpaid fees or suspended plates accrue against this owner. The owner's `real_id_status` initializes to `NOT_APPLIED`, and the related fields `real_id_score` and `real_id_expires_at` initialize to null.

Verifying the VIN on a transfer application is gated on the owner being clear of holds: if `outstanding_holds_count` is greater than zero, VIN verification is rejected with `ERR_OWNER_HAS_HOLDS`. This makes the owner-level hold the earliest business-rule gate on a transfer workflow and ensures that an owner who has unsettled obligations cannot quietly continue accumulating new ones.

### 3.2. Vehicles, VIN Verification, and the Title-Status / Lien-Status Lattice

A `Vehicle` is intaked by a `VinVerifier` or `PlatformAdmin` with the manufacturer-supplied fields `vin`, `make`, `model`, `model_year`, `curb_weight_lbs`, and `fuel_type`. The `vin` must be 17 characters drawn from uppercase A through Z and digits 0 through 9, excluding the letters `I`, `O`, and `Q`, and is globally unique across the entire vehicle table. `make` and `model` are 1-to-50-character strings; `model_year` is a four-digit integer between 1900 and 2100; `curb_weight_lbs` is an integer between 200 and 40000; `fuel_type` is one of `GASOLINE`, `DIESEL`, `HYBRID`, or `ELECTRIC`. New vehicles start with `vin_verification_status` set to `UNVERIFIED` and `vin_verified_at` set to null, `title_status` set to `CLEAN`, `lien_status` set to `NONE`, `current_title_id` and `emissions_expires_at` both null.

VIN verification on a transfer application advances the vehicle's `vin_verification_status` from `UNVERIFIED` (or `VERIFIED`, if a prior verification has already happened on this vehicle) to `VERIFIED`, and stamps `vin_verified_at` to the current server time. If the vehicle's `vin_verification_status` is `HOLD` — set by some upstream investigative process — the verification call is rejected with `ERR_VIN_ON_HOLD`. The fourth allowed state, `MISMATCH`, is documented as a possible historical value but is not directly reachable through this API. The vehicle listing capability accepts optional `limit`, `offset`, `title_status`, `lien_status`, and `fuel_type` filters.

The two-dimensional state lattice on a vehicle has `title_status` taking values `CLEAN`, `SALVAGE_PENDING_REBUILD`, `REBUILT`, or `NON_REPAIRABLE`, and `lien_status` taking values `NONE`, `ACTIVE`, or `RELEASED`. The two evolve independently: a vehicle with `lien_status == ACTIVE` may still flip `title_status` from `CLEAN` to `SALVAGE_PENDING_REBUILD`, and a `REBUILT` vehicle may receive an `ACTIVE` lien like any other.

### 3.3. Salvage Events and Their Cascades

A `SalvageOfficer` records a salvage damage event against a vehicle by posting a body containing the `severity` field (either `PARTIAL` or `TOTAL`). A `PARTIAL` severity transitions `title_status` from `CLEAN` to `SALVAGE_PENDING_REBUILD`. A `TOTAL` severity transitions it to `NON_REPAIRABLE` regardless of the current `title_status` and is itself the permanent end of the vehicle's lifecycle on the road.

The cascades attached to either branch are intentionally aggressive because the salvage signal must outrun whatever else is in flight. When `title_status` flips to `SALVAGE_PENDING_REBUILD`, the server (a) clears `Vehicle.emissions_expires_at` to null, (b) cancels every `EmissionsInspection` on this vehicle that is currently `SCHEDULED` or `IN_PROGRESS` by flipping its `status` to `CANCELLED`, (c) suspends any `ACTIVE` `Plate` bound to this vehicle by flipping its `status` to `SUSPENDED` and stamping `suspended_at` (the `surrender_reason` that would apply on an eventual surrender is `SALVAGE_TRIGGERED`), and (d) reroutes every `TransferApplication` on the vehicle whose status is currently in `VIN_VERIFIED`, `EMISSIONS_PENDING`, `EMISSIONS_PASSED`, or `TAX_ASSESSED` into the salvage review track on next observation. An attempt to assess fees on a vehicle that has flipped to `SALVAGE_PENDING_REBUILD` or to `NON_REPAIRABLE` is rejected with `ERR_VEHICLE_SALVAGE_LOCKED`. When `title_status` flips to `NON_REPAIRABLE`, every `ACTIVE` or `SUSPENDED` plate on the vehicle is forced to `SURRENDERED` with `surrender_reason` set to `SALVAGE_TRIGGERED`, and the vehicle is removed from the registration pipeline permanently.

In the rebuild path, once a `SalvageOfficer` approves a salvage review on the transfer application, `Vehicle.title_status` is reset to `REBUILT` and `Vehicle.emissions_expires_at` is cleared to null so that a fresh emissions inspection is required before the rebuilt vehicle can complete registration.

### 3.4. The Transfer Application Workflow

A `TransferApplication` is created by an `Applicant` against a specific vehicle. The creation body carries `application_type` (either `INITIAL_REGISTRATION` for a freshly-manufactured vehicle or `TITLE_TRANSFER` for an ownership change — chosen at creation and immutable thereafter), `applicant_owner_id` (the owner who will hold the title on success), `declared_sale_price` (the declared sale price for a transfer, or declared MSRP for an initial registration; in either case a positive number between 0.01 and 2000000.00 with two decimal places), and an optional `trade_in_value` (defaulting to 0.00; same numeric domain as `declared_sale_price` but allowed to be zero, up to 1000000.00). The application enters the workflow in `DRAFT`, with `salvage_branch_taken` initialized to false, `fee_subtotal`, `processing_fee`, `total_due`, `paid_at`, `plate_id`, and `rejection_reason` all null.

The state machine on a `TransferApplication` flows through these named states: `DRAFT`, `VIN_VERIFIED`, `SALVAGE_REVIEW`, `SALVAGE_APPROVED`, `EMISSIONS_PENDING`, `EMISSIONS_PASSED`, `TAX_ASSESSED`, `PLATE_ISSUED`, `COMPLETED`, and `REJECTED`. `COMPLETED` and `REJECTED` are terminal. Every action endpoint that drives a state-machine transition rejects with `ERR_INVALID_STATE` if the application's current `status` does not match the from-state required by the transition.

A `VinVerifier` advances `DRAFT` to `VIN_VERIFIED` once the vehicle's `vin_verification_status` is `UNVERIFIED` or `VERIFIED` and the owner's `outstanding_holds_count` is zero. The side-effect of that transition is to flip the vehicle's `vin_verification_status` to `VERIFIED` and stamp `vin_verified_at`. The server then performs an immediate automatic branch evaluated at the end of the same call: if `Vehicle.title_status` is in the set `SALVAGE_PENDING_REBUILD` or `NON_REPAIRABLE`, the application advances to `SALVAGE_REVIEW` and `salvage_branch_taken` is set to true; if `Vehicle.title_status` is in the set `CLEAN` or `REBUILT`, the application advances to `EMISSIONS_PENDING` with no further side effects. These two automatic branches are siblings of each other and exhaust the title-status space; every freshly-verified application lands either in `SALVAGE_REVIEW` or in `EMISSIONS_PENDING` before the verify call returns.

An `Applicant` may withdraw a `DRAFT` application at any time before VIN verification; doing so transitions the application directly from `DRAFT` to `REJECTED` and sets `rejection_reason` to `WITHDRAWN`. No other state allows the applicant-initiated withdrawal.

### 3.5. Salvage Review, Emissions Inspection, and Their Interleaving

When the application is in `SALVAGE_REVIEW`, a `SalvageOfficer` decides the application by posting a `decision` of either `APPROVE` or `DENY`. An `APPROVE` is permitted only when `Vehicle.title_status` is `SALVAGE_PENDING_REBUILD` **and** `application_type` is `TITLE_TRANSFER` — initial registrations cannot pass through salvage approval. The approval transitions the application to `SALVAGE_APPROVED`, sets `Vehicle.title_status` to `REBUILT`, and clears `Vehicle.emissions_expires_at` to null so the rebuilt vehicle must obtain a fresh inspection. The server immediately follows on to `EMISSIONS_PENDING` with no further side effects. A `DENY` decision is reserved for the `NON_REPAIRABLE` case: when `Vehicle.title_status` is `NON_REPAIRABLE`, the decision transitions the application from `SALVAGE_REVIEW` directly to `REJECTED` with `rejection_reason` set to `NON_REPAIRABLE_SALVAGE`. The two sibling branches out of `SALVAGE_REVIEW` are mutually exclusive on the precondition: `APPROVE` requires `SALVAGE_PENDING_REBUILD`, `DENY` requires `NON_REPAIRABLE`.

An `EmissionsInspection` is scheduled independently of the transfer workflow. The scheduling request carries `vehicle_id`, `station_id` (a 1-to-40-character opaque identifier for the inspection station), `scheduled_start`, and `scheduled_end` — both ISO 8601 UTC timestamps with `scheduled_end` strictly later than `scheduled_start`. The new inspection's slot at the given `station_id` must not overlap any other non-cancelled inspection's half-open interval `[start, end + 15 minutes)` at that station; an overlap is rejected with `ERR_INSPECTION_SLOT_OVERLAP`. The inspection's `status` starts as `SCHEDULED`, its `result_recorded_at` and `odometer_reading` null.

An `EmissionsInspector` advances `SCHEDULED` to `IN_PROGRESS` provided three conditions hold: `Vehicle.title_status` is not `NON_REPAIRABLE`, `Vehicle.title_status` is not `SALVAGE_PENDING_REBUILD`, and the current time is at or after the inspection's `scheduled_start` minus 15 minutes (a 15-minute early-arrival grace window). The second precondition is enforced as `ERR_VEHICLE_SALVAGE_LOCKED`. Recording an outcome from `IN_PROGRESS` requires the caller to supply `odometer_reading` (an integer between 0 and 2000000 inclusive) and an `outcome` value of either `PASSED` or `FAILED`. If a prior `PASSED` inspection exists on this vehicle, the new `odometer_reading` must be at least equal to the prior `PASSED` inspection's odometer reading; a lower reading is rejected with `ERR_ODOMETER_ROLLBACK`. Recording `PASSED` stamps `result_recorded_at`, sets `Vehicle.emissions_expires_at` to the recorded time plus 730 days for `GASOLINE`, `DIESEL`, and `HYBRID` fuel types — and explicitly to null for `ELECTRIC` vehicles, which are exempt from emissions expiry. The same `PASSED` event advances any linked `TransferApplication` whose `status` is `EMISSIONS_PENDING` and which was last updated within the last 30 days to `EMISSIONS_PASSED`. Recording `FAILED` instead rejects every linked `EmissionsInspection`-bound transfer application by transitioning it to `REJECTED` with `rejection_reason` set to `EMISSIONS_FAILED`. The two sibling outcomes carry equal specification weight — both require `odometer_reading`, both stamp `result_recorded_at`; only `PASSED` writes the emissions expiry, only `FAILED` rejects the linked applications.

A `SCHEDULED` inspection can be cancelled outright by either the `Applicant` or the `EmissionsInspector`, which flips its `status` to `CANCELLED`. An `IN_PROGRESS` inspection on a vehicle that simultaneously transitions into `SALVAGE_PENDING_REBUILD` is auto-cancelled as part of the salvage cascade described in §3.3.

### 3.6. Liens, Their Activation, and Their Release

A `LienClerk` records a lien against the currently-active `Title` for a vehicle; the URL path carries the `title_id`. The creation body carries `lienholder_name` (1 to 120 characters) and `principal_amount` (a positive number between 0.01 and 2000000.00 with two decimal places). The lien row stores its parent under a `title_id` field. The `LienRecord` starts with `status` set to `ACTIVE`, `released_at` null, and `release_reference` null. Creating the lien also flips `Vehicle.lien_status` to `ACTIVE`. Lien creation requires that the underlying `Title` has `is_active` true — historical superseded titles are not lien-attachable.

While `Vehicle.lien_status` is `ACTIVE`, no `TransferApplication` on that vehicle may progress past `EMISSIONS_PASSED` into `TAX_ASSESSED` — the assess-fees call is rejected with `ERR_LIEN_ACTIVE`.

A `LienClerk` releases an `ACTIVE` lien by supplying a non-empty `release_reference` string. An empty or missing `release_reference` is rejected with `ERR_RELEASE_REFERENCE_REQUIRED`. A successful release transitions the lien's `status` from `ACTIVE` to `RELEASED`, stamps `released_at` to the current time, and — if no other `ACTIVE` `LienRecord` remains on the same title — flips `Vehicle.lien_status` to `RELEASED`. Two clerks releasing the same lien at the same time serialize at the row level: exactly one release wins and the loser receives `ERR_LIEN_ALREADY_RELEASED` once it observes that the record's `status` has already become `RELEASED`. The release endpoint accepts an optional `version` field for optimistic concurrency control.

### 3.7. Fee Assessment, the Three Calculations, and the Ledger

A `TaxAssessor` assesses fees on a `TransferApplication` whose `status` is `EMISSIONS_PASSED`. Before the assessment runs, four gates are evaluated. First, `Vehicle.emissions_expires_at` must be in the future: if it is null on a non-electric vehicle, or if the current server time is at or after the stored expiry instant (the boundary is inclusive — the expiry day itself fails), the call is rejected with `ERR_EMISSIONS_EXPIRED`. Second, `Owner.real_id_status` must be in the set `APPROVED`, `NOT_APPLIED`, or `PENDING`: a `REVOKED` REAL ID blocks fee assessment with `ERR_OWNER_REAL_ID_REVOKED`, while `DOC_REJECTED` is an application-side state rather than an owner-side state and does not directly gate here. Third, `Vehicle.lien_status` must be in the set `NONE` or `RELEASED`; an `ACTIVE` lien rejects with `ERR_LIEN_ACTIVE`. Fourth, `Vehicle.title_status` must not be `NON_REPAIRABLE` (handled under the §2.8 priority-7 salvage gate, yielding `ERR_VEHICLE_SALVAGE_LOCKED`).

The assessment runs three calculations and persists their results onto the application. The first is the **registration fee**, derived from the vehicle's curb weight, model age, and the owner's residency. The weight tier base is determined as follows: if `curb_weight_lbs` is strictly less than 3000 pounds, the weight base is 65.00; if it is at least 3000 pounds and strictly less than 6000 pounds, the weight base is 110.00; if it is at least 6000 pounds, the weight base is 185.00 — note that the heavy tier uses the inclusive boundary 6000, not strictly greater than 6000. The vehicle's age in years is the larger of zero and the current calendar year minus `model_year`; the age factor is the larger of 0.50 and the value 1.00 minus 0.05 multiplied by the age in years, with the 0.50 floor preventing arbitrarily old vehicles from depreciating below half the base. The surcharge is 22.00 if `Owner.is_resident` is true, otherwise it is 55.00. The registration fee is the weight base multiplied by the age factor, plus the surcharge, with the final result rounded half-up to two decimal places.

The second is the **sales tax on transfer**. This calculation has two dual variants selected by `Owner.is_resident`. In the resident variant, the taxable base is the larger of zero and `declared_sale_price` minus `trade_in_value`, and the sales tax is the taxable base multiplied by the resident rate of 0.0725, rounded half-up to two decimal places. In the non-resident variant, `trade_in_value` is ignored entirely: the taxable base is `declared_sale_price` outright, and the sales tax is the taxable base multiplied by the non-resident rate of 0.085, rounded half-up to two decimal places. For an `INITIAL_REGISTRATION` application, both variants apply identically with the single difference that `trade_in_value` is treated as zero on the resident branch (the same end behavior as supplying a zero trade-in).

The third is **total due with processing**, a pinned three-step composition. Step 1: the `fee_subtotal` is the sum of the registration fee and the sales tax, rounded half-up to two decimal places at this step before the next step reads it. Step 2: the `processing_fee` is selected from the rounded `fee_subtotal` against four tiers — when `fee_subtotal` is at most 200.00, the processing fee is a flat 8.00; when `fee_subtotal` is strictly greater than 200.00 and at most 1000.00, it is a flat 18.00; when `fee_subtotal` is strictly greater than 1000.00 and at most 5000.00, it is a flat 38.00; when `fee_subtotal` is strictly greater than 5000.00, the processing fee is two percent (0.02) of `fee_subtotal`, rounded half-up to two decimal places. Step 3: `total_due` is the sum of `fee_subtotal` and `processing_fee`, rounded half-up to two decimal places. Each step rounds independently before the next step's input is read; this evaluation order is fixed even though the dependency looks circular at a glance.

The successful assessment transitions the application's `status` from `EMISSIONS_PASSED` to `TAX_ASSESSED`, writes the three computed amounts onto the application, and appends exactly three `FeeLedgerEntry` rows whose `kind` values are `SALES_TAX`, `REG_FEE`, and `PROCESSING_FEE`, each with `amount_cents` equal to the positive cents amount of the corresponding figure and `occurred_at` stamped to the assessment time. The ledger is append-only — entries are never edited or deleted.

### 3.8. Payment, the Seven-Day Compensating Sweep, and Plate Issuance

The applicant marks the assessment paid by stamping `paid_at` to the current server time. The mark-paid action records that the out-of-band payment has cleared; it does not advance the state machine on its own. The application sits in `TAX_ASSESSED` until either the plate is issued or the unpaid-timeout sweep reverts it.

The compensating timeout is driven by the admin-only logical-clock advancement capability. The platform admin advances the server clock to a supplied `to` instant — an ISO 8601 datetime. For every `TransferApplication` whose `status` is `TAX_ASSESSED`, whose `paid_at` is still null, and whose `updated_at` plus seven days is at or before the new clock instant, the system reverts the application from `TAX_ASSESSED` back to `EMISSIONS_PASSED`, appends three refund `FeeLedgerEntry` rows whose `kind` values are `REFUND_TAX`, `REFUND_REG`, and `REFUND_PROCESSING` and whose `amount_cents` values are the **negatives** of the original three rows so they sum to zero net cents per application, and clears `fee_subtotal`, `processing_fee`, and `total_due` back to null. The clock-advance side effect also re-evaluates the REAL ID enforcement gating on plate issuance calls made after this point.

A `PlateIssuer` issues an electronic plate on a `TAX_ASSESSED` application provided four conditions hold: `paid_at` is not null (otherwise `ERR_PAYMENT_REQUIRED`); `Owner.real_id_status` is `APPROVED` **or** the current time is strictly earlier than `2027-05-07T00:00:00Z` (the federal REAL ID enforcement instant, which permits non-REAL-ID issuance only before that moment); the `X-User-ID` of this `PlateIssuer` call differs from the `X-User-ID` that originally ran fee assessment on this same application (otherwise `ERR_SEGREGATION_OF_DUTIES`); and the supplied `plate_number` is unique among `Plate` rows whose `status` is in the set `ISSUED`, `ACTIVE`, or `SUSPENDED` (a duplicate yields `ERR_PLATE_NUMBER_TAKEN`).

`plate_number` must match the pattern of 2 to 8 characters of uppercase A-Z or digit 0-9. The successful issuance creates a new `Plate` row whose `status` lands at `ACTIVE` after the system's immediate follow-on from `ISSUED` to `ACTIVE`, stamps `activated_at` to the current time, sets the application's `plate_id` to the new plate's id, transitions the application's `status` from `TAX_ASSESSED` to `PLATE_ISSUED`, and the system follows on from `PLATE_ISSUED` to `COMPLETED` in the same call. The completion side effects create a brand-new `Title` row for the application's `applicant_owner_id` with the title's `brand` carried over from the most appropriate source (a `REBUILT` vehicle yields a `REBUILT`-branded title; otherwise the brand is `CLEAN`), with `vehicle_id` and `owner_id` set, `issued_at` stamped to the current time, `source_application_id` set to this `TransferApplication`'s id, `is_active` set to true, and `superseded_at` null. The prior `Title` for the vehicle, if any, has `superseded_at` stamped to the current time and `is_active` flipped to false. `Vehicle.current_title_id` is updated to point at the new title row. If `application_type` is `TITLE_TRANSFER` and a prior plate existed on the vehicle, that prior plate is surrendered with its `status` flipping to `SURRENDERED` and `surrender_reason` set to `TRANSFER_COMPLETE`.

Two `PlateIssuer` operators attempting to issue plates against the same `TAX_ASSESSED` application serialize on the application row: exactly one issuance succeeds, and the loser sees the state already advanced and is rejected with `ERR_INVALID_STATE`. Two simultaneous issuances that both name the same `plate_number` serialize on the plate-number uniqueness constraint: the second is rejected with `ERR_PLATE_NUMBER_TAKEN`. An assess-fees call posted simultaneously with a salvage event against the same vehicle serializes on the vehicle's `title_status` lock: salvage wins, and the assess-fees attempt observes the salvaged state and is rejected with `ERR_VEHICLE_SALVAGE_LOCKED`. An emissions inspector recording `PASSED` on a vehicle that is concurrently flipping to `NON_REPAIRABLE` re-reads `Vehicle.title_status` under the same lock before committing; salvage wins and the `PASSED` record is rejected with `ERR_VEHICLE_SALVAGE_LOCKED`.

### 3.9. Plate Lifecycle: Suspend, Reinstate, Surrender

A `Plate` row, once issued, lives in the lifecycle `ISSUED → ACTIVE → SUSPENDED ↔ ACTIVE → SURRENDERED` (with `SURRENDERED` terminal). The `ISSUED → ACTIVE` transition is an automatic system follow-on at the moment of plate creation and stamps `activated_at`. A `PlatformAdmin` may suspend an `ACTIVE` plate by stamping `suspended_at`; the cyclic counterpart reinstates a `SUSPENDED` plate to `ACTIVE` and clears `suspended_at` to null. Reinstatement is permitted only when `Vehicle.title_status` is in the set `CLEAN` or `REBUILT`, and only when `Owner.real_id_status` is not `REVOKED` **or** the current time is strictly earlier than `2027-05-07T00:00:00Z` (the same REAL ID enforcement cutoff used by plate issuance). The `ACTIVE → SUSPENDED → ACTIVE` cycle may occur any number of times before the plate is finally surrendered.

Surrender is the only terminal transition. A surrender call carries `surrender_reason` (one of `SALVAGE_TRIGGERED`, `OWNER_REQUEST`, `LIEN_DEFAULT`, or `TRANSFER_COMPLETE`), and may be issued from either `ACTIVE` or `SUSPENDED`. Both source states carry equal weight — both lead to `SURRENDERED` with `surrender_reason` recorded on the plate. Suspension may also be triggered as a side effect when `Vehicle.title_status` flips to `SALVAGE_PENDING_REBUILD` (the vehicle's `ACTIVE` plate is suspended with the eventual surrender reason `SALVAGE_TRIGGERED` set as the cause-of-record) or when `Owner.real_id_status` flips to `REVOKED` (every `ACTIVE` plate on every vehicle whose current title's `owner_id` matches the revoked owner is suspended with `suspended_at` stamped).

### 3.10. REAL ID Submission, Scoring, and Revocation

A `RealIDApplication` is submitted by an `Applicant` against their own `Owner` id. The submission body carries three booleans — `documents_proof_of_identity`, `documents_proof_of_residency`, and `documents_proof_of_ssn` — each indicating whether the corresponding document is attached. The application starts in `SUBMITTED` with `revision_count` zero and `approved_at` null. The owner's `real_id_status` is moved to `PENDING` as a side effect of submission.

A `RealIDReviewer` starts the review by transitioning `SUBMITTED` to `DOC_REVIEW`; the precondition is that **all three** document booleans are true. The reviewer then evaluates the **REAL ID eligibility score**, a weighted scoring computation: 40 points for `documents_proof_of_identity` being true, 30 points for `documents_proof_of_residency` being true, and 25 points for `documents_proof_of_ssn` being true (each effectively a 0-or-1 multiplier on its weight). The owner age in years is the floor of the duration from `date_of_birth` to the current server time, divided by 365.25 days; an age bonus of 5 points is added if and only if the age is at least 18 and at most 80, otherwise the age bonus is 0. A revision penalty of 5 points is subtracted for every prior revision cycle (the raw deduction is the negative of 5 multiplied by `revision_count`). The raw score is the sum of the three document points, the age bonus, and the revision penalty; the final `real_id_score` is the raw score clamped to the closed interval from 0.00 to 100.00, then rounded half-up to two decimal places. The approval threshold is at least 80.00.

When the score is at least 80.00, the reviewer approves: `RealIDApplication.status` transitions from `DOC_REVIEW` to `APPROVED`, the owner's `real_id_status` is set to `APPROVED`, `Owner.real_id_expires_at` is set to the current time plus eight years, `Owner.real_id_score` is set to the computed score, and the application's `approved_at` is stamped. When the score is strictly less than 80.00, the reviewer rejects: the application transitions from `DOC_REVIEW` to `DOC_REJECTED` and the owner's `real_id_status` is rolled back to `PENDING`. Approval and rejection are sibling outcomes branching on the same numeric threshold; both record the same score, only one shifts the owner state to `APPROVED`.

From `DOC_REJECTED` the applicant may resubmit revised documents, cycling the application back to `SUBMITTED` and incrementing `revision_count` by 1. Resubmission is permitted only while `revision_count` is strictly less than 3; the fourth attempt is rejected with `ERR_REVISION_LIMIT_EXCEEDED`. The cycle `SUBMITTED → DOC_REVIEW → DOC_REJECTED → SUBMITTED` may therefore occur up to three times before the application is permanently denied. The resubmit action accepts an optional `version` for optimistic concurrency control.

A `PlatformAdmin` may revoke an `APPROVED` REAL ID at any time. The revocation transitions the application from `APPROVED` to `REVOKED` and the owner's `real_id_status` to `REVOKED`. The cascade is substantial: every `TransferApplication` whose `applicant_owner_id` equals this owner and whose `status` is in `VIN_VERIFIED`, `EMISSIONS_PENDING`, `EMISSIONS_PASSED`, or `TAX_ASSESSED` is frozen — subsequent fee-assessment and plate-issuance attempts on those applications return `ERR_OWNER_REAL_ID_REVOKED`; and every `ACTIVE` plate on every vehicle whose currently-active `Title.owner_id` is this owner is suspended with `suspended_at` stamped. All four sibling cascade targets carry equal narrative weight: the application freeze applies symmetrically to every one of the four named states.

### 3.11. The Fee Ledger Audit View

Any `TaxAssessor`, `PlatformAdmin`, or the owning `Applicant` may list the per-application audit trail of `FeeLedgerEntry` rows associated with a given `TransferApplication`. Each `FeeLedgerEntry` carries an `application_id` foreign-key to its parent application. The listing supports `limit` and `offset` pagination and returns ledger rows sorted by `occurred_at` ascending (the default `created_at` sort generalizes to `occurred_at` for this append-only ledger). The compensating-action invariant — every refund matches an original debit, and the per-application net is zero after a revert — is observable through this listing.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource (vehicle intake, owner creation, REAL ID application submission, transfer application creation, emissions inspection scheduling, lien creation) return HTTP 201. Endpoints that mutate or drive the state machine of an existing resource return HTTP 200. A successful cancellation of a scheduled inspection returns HTTP 204. Validation, state, and business-rule failures return the declared HTTP status (401, 402, 403, 404, 409, or 422) carrying the error envelope from §2.2. Request bodies and response payloads for each endpoint are derived from the narrative in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/vehicles` | Register a new vehicle record (intake; does not create a title). | `VinVerifier`, `PlatformAdmin` |
| GET | `/vehicles/{vehicle_id}` | Read a vehicle. | `VinVerifier`, `TaxAssessor`, `PlateIssuer`, `SalvageOfficer`, `EmissionsInspector`, `LienClerk`, `RealIDReviewer`, `Applicant`, `PlatformAdmin` |
| GET | `/vehicles` | List vehicles with pagination and filtering. | `VinVerifier`, `TaxAssessor`, `PlateIssuer`, `SalvageOfficer`, `EmissionsInspector`, `PlatformAdmin` |
| POST | `/vehicles/{vehicle_id}/salvage-event` | Record a salvage damage event; flips `title_status` and cascades. | `SalvageOfficer` |
| POST | `/owners` | Create an owner record. | `PlatformAdmin`, `Applicant` |
| GET | `/owners/{owner_id}` | Read an owner. | `PlatformAdmin`, `RealIDReviewer`, `TaxAssessor`, `PlateIssuer`, `Applicant` |
| POST | `/owners/{owner_id}/real-id-applications` | Submit a REAL ID upgrade application. | `Applicant` |
| POST | `/real-id-applications/{id}/start-review` | Advance the REAL ID application from `SUBMITTED` to `DOC_REVIEW`. | `RealIDReviewer` |
| POST | `/real-id-applications/{id}/approve` | Approve the REAL ID application when score is at least 80.00. | `RealIDReviewer` |
| POST | `/real-id-applications/{id}/reject` | Reject the REAL ID application when score is below 80.00. | `RealIDReviewer` |
| PATCH | `/real-id-applications/{id}/resubmit` | Cycle `DOC_REJECTED` back to `SUBMITTED` with revised documents. | `Applicant` |
| POST | `/real-id-applications/{id}/revoke` | Revoke an `APPROVED` REAL ID; cascades to plates and in-flight transfer applications. | `PlatformAdmin` |
| POST | `/vehicles/{vehicle_id}/transfer-applications` | Create a transfer application (initial registration or title transfer). | `Applicant` |
| GET | `/transfer-applications/{id}` | Read a transfer application. | `Applicant`, `VinVerifier`, `TaxAssessor`, `PlateIssuer`, `SalvageOfficer`, `PlatformAdmin` |
| GET | `/transfer-applications` | List transfer applications with filters. | `PlatformAdmin`, `VinVerifier`, `TaxAssessor`, `PlateIssuer` |
| POST | `/vehicles/{vehicle_id}/transfer-applications/{id}/verify-vin` | VIN verification; may auto-branch into salvage review or emissions pending. | `VinVerifier` |
| POST | `/transfer-applications/{id}/approve-salvage` | Salvage officer decision on a salvage-review application. | `SalvageOfficer` |
| POST | `/transfer-applications/{id}/assess-fees` | Run the three fee calculations and pin `fee_subtotal`, `processing_fee`, `total_due`. | `TaxAssessor` |
| POST | `/transfer-applications/{id}/mark-paid` | Applicant marks the assessment paid (out-of-band payment cleared). | `Applicant` |
| POST | `/transfer-applications/{id}/issue-plate` | Issue an electronic plate after payment; completes the application. | `PlateIssuer` |
| POST | `/transfer-applications/{id}/withdraw` | Applicant withdraws a `DRAFT` application. | `Applicant` |
| POST | `/emissions-inspections` | Schedule an emissions inspection slot at a station. | `Applicant`, `EmissionsInspector` |
| POST | `/emissions-inspections/{id}/start` | Inspector starts the inspection (`SCHEDULED` to `IN_PROGRESS`). | `EmissionsInspector` |
| POST | `/emissions-inspections/{id}/record-result` | Inspector records `PASSED` or `FAILED` with `odometer_reading`. | `EmissionsInspector` |
| DELETE | `/emissions-inspections/{id}` | Cancel a `SCHEDULED` inspection. | `EmissionsInspector`, `Applicant` |
| POST | `/titles/{title_id}/lien-records` | Create a `LienRecord` on the active title. | `LienClerk` |
| PATCH | `/lien-records/{id}/release` | Release an `ACTIVE` lien with a confirmation reference. | `LienClerk` |
| GET | `/plates/{id}` | Read a plate. | `PlatformAdmin`, `Applicant`, `PlateIssuer` |
| POST | `/plates/{id}/suspend` | Suspend an `ACTIVE` plate. | `PlatformAdmin` |
| POST | `/plates/{id}/reinstate` | Reinstate a `SUSPENDED` plate. | `PlatformAdmin` |
| POST | `/plates/{id}/surrender` | Surrender a plate (terminal). | `PlatformAdmin` |
| GET | `/transfer-applications/{id}/fee-ledger` | List `FeeLedgerEntry` rows for an application. | `PlatformAdmin`, `TaxAssessor`, `Applicant` |
| POST | `/_clock/advance` | Admin-only logical-clock advancement; drives unpaid-timeout reverts and REAL ID enforcement re-evaluation. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_INVALID_ROLE` | 403 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_VIN_ON_HOLD` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VEHICLE_SALVAGE_LOCKED` | 409 |
| `ERR_EMISSIONS_EXPIRED` | 409 |
| `ERR_OWNER_REAL_ID_REVOKED` | 409 |
| `ERR_LIEN_ACTIVE` | 409 |
| `ERR_INSPECTION_SLOT_OVERLAP` | 409 |
| `ERR_PLATE_NUMBER_TAKEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 |
| `ERR_ODOMETER_ROLLBACK` | 409 |
| `ERR_PAYMENT_REQUIRED` | 402 |
| `ERR_OWNER_HAS_HOLDS` | 409 |
| `ERR_RELEASE_REFERENCE_REQUIRED` | 422 |
| `ERR_LIEN_ALREADY_RELEASED` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |

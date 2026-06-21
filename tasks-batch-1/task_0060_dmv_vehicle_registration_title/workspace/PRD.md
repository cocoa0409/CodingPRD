# DMV Registration & Title API — Product Requirements Document

## 1. Introduction

This document specifies the behavior of the DMV Registration & Title platform, a counter-and-back-office system that drives a vehicle from intake through clear or rebuilt title, lien encumbrance, emissions clearance, fee assessment, registration activation, and license-plate issuance. It exists because the registration lifecycle is not a single transaction but a chain of gated steps: a vehicle's identification number must be verified before a title can move forward, a salvage-branded vehicle must pass a rebuild inspection before its title is issued, fees must be settled before a registration activates, and plates can only be assigned and remotely toggled once the underlying registration is live. Each gate exists to protect a downstream invariant, and the platform's job is to enforce them in the correct order rather than trusting the operator to remember them.

The system serves four constituencies working in concert. Counter clerks shepherd the bulk of the lifecycle; dedicated inspection stations file emissions and rebuild results; vehicle owners perform self-service intake, payment, and read-only lookups; and DMV administrators hold override authority over the registration lifecycle and over fiscal voids. Because money, ownership transfer, and lien priority all change hands here, the platform treats every calculation as exact-to-the-cent and every state transition as auditable, with optimistic concurrency guarding the two operations where a stale view of a registration would silently corrupt plate assignment or reinstatement.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present but the named role is not permitted to perform the requested operation (per the authorization table in §4), the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `ClerkAgent`, `InspectionStation`, `Owner`, and `DmvAdmin`.

When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity; ownership checks on any resource that references an owner compare the resource's owner foreign-key field (`owner_id` on a `Vehicle` or `Registration`, `applicant_owner_id` on a `TitleApplication`) to `X-User-ID`. When `X-User-Role` is `ClerkAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `DmvAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. When `X-User-Role` is `InspectionStation`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as the `station_id` on each `EmissionsInspection` and `SalvageInspection` that the station files, but does not compare it to any entity's `id`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a caller-supplied value outside that range is rejected as a malformed request. `offset` defaults to 0 and has a minimum of 0. List results are ordered by `created_at` ascending. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of rows matching the filter before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly 1 on each mutation. The two inspection-record entities are the exception: a `VinVerification` carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because it is written once and never mutated. All other entities — `Owner`, `Vehicle`, `TitleApplication`, `SalvageInspection`, `Lien`, `EmissionsInspection`, `FeeAssessment`, `Registration`, `LicensePlate`, and `RealIdApplication` — carry the full set including `updated_at` and `version`.

Whenever a transition mutates an entity, its `updated_at` is refreshed and its `version` is incremented. Crucially, a side effect that mutates a *related* entity bumps that related entity's `version` too: for example, when a VIN verification updates a vehicle's verification state, or a lien perfection adjusts a vehicle's lien counter, the affected `Vehicle.version` increments. These cross-entity version bumps are what make the optimistic-concurrency checks in §2.7 meaningful.

### 2.5. Monetary Calculation and Rounding

All monetary amounts are stored and transmitted as integer cents. Where a calculation multiplies a base amount by a rate and the result is not a whole number of cents, the product is rounded to the nearest integer cent using round-half-up (a fractional remainder of exactly one-half rounds upward). Pure sums of integer-cent quantities involve no rounding. Each calculation specifies precisely where rounding falls in its evaluation order, and that order is binding: rounding a sub-product before adding a later term can yield a different total than rounding the whole, so the order described in §3 must be followed exactly.

### 2.6. Half-Open Temporal Windows

Several rules turn on time windows, and every such window in this system is half-open — written conceptually as the interval from a start instant up to but not including an end instant. A window contains an instant when that instant is at or after the start and strictly before the end. The boundary instant equal to the window's end is therefore *outside* the window. Two adjacent windows that meet exactly at a shared boundary — where one window's end equals the next window's start — do not overlap. This single convention governs emissions-inspection validity, registration terms, and license-plate tenancy alike. The server maintains a logical current clock used to stamp these instants; an administrative test-driving capability can set this clock to a supplied instant so that time-window scenarios can be exercised deterministically.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and both pin on a `Registration`'s `version`. Each requires the non-optional input field `expected_registration_version`, which the client sets to the `version` it last observed on the target registration. If that value does not equal the registration's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state changes.

The first guarded operation is plate assignment: a request to assign a license plate to a registration must carry `expected_registration_version` matching the target registration's current `version`. If another writer has already advanced the registration's `version` since the client last read it — for instance by assigning the registration's single plate — the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from issuing a second plate against a registration whose state it has not observed. The second guarded operation is reinstatement of a suspended registration: that request must likewise carry `expected_registration_version` matching the registration's current `version`, and if a prior reinstatement has already advanced the `version` and reactivated the electronic plates, the stale caller's reinstatement is refused with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.8. Existence and State Preconditions

Before any business rule runs, the system validates that every resource referenced by the request — whether named in the URL path or in the body — exists, checking references left to right and rejecting the first missing reference with `ERR_NOT_FOUND` (HTTP 404). A malformed body or a missing required field is rejected with `ERR_VALIDATION` (HTTP 400). For every state-transition endpoint, if the target resource is not in a state from which the requested transition is legal, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). These structural checks precede the domain-specific gates described in §3.

### 2.9. Validation Precedence

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_FORBIDDEN`), then existence of referenced resources (`ERR_NOT_FOUND`), then — on transition endpoints — the basic state check (`ERR_INVALID_STATE`). Only after all of those pass are the domain-specific business gates of a given operation evaluated. Where one operation layers several business gates, the operation's narrative in §3 states their relative order.

## 3. Business Logic & Workflows

### 3.1. Owners, Vehicles, and VIN Verification

The lifecycle begins with an `Owner` and a `Vehicle`. An owner is created with a `full_name` and a `residence_county_code` — the county code that later selects the county tax add-on rate. An owner may optionally declare a `credential_type`, which is one of `STANDARD` or `REAL_ID` and defaults to `STANDARD`, and may optionally declare `identity_documents_verified`, a boolean recording whether identity documents were presented and verified at the counter, defaulting to false. Each owner also carries a computed `real_id_status` that mirrors the REAL ID upgrade lifecycle; it is one of `NONE`, `PENDING`, or `UPGRADED` and is initialized to `NONE` at creation.

A vehicle is created against an owner via `owner_id` and records its `vin`, its `model_year`, its declared `purchase_price_cents` (the use-tax basis), its `msrp_cents` (the registration-fee basis), and its `vehicle_class`, which is one of `PASSENGER`, `TRUCK`, or `MOTORCYCLE`. A vehicle may declare `is_salvage_branded`, a boolean defaulting to false that marks it as arriving with a salvage brand requiring rebuild inspection. At creation a vehicle's computed `vin_status` is `UNVERIFIED`, its computed `title_status` is `NONE`, and its computed `active_lien_count` is 0. The `vin` must be exactly 17 characters long and unique across all vehicles; a value that is not 17 characters, or that collides with an existing vehicle's VIN, is rejected with `ERR_INVALID_VIN` (HTTP 422). Because entities are linked by foreign keys rather than nested paths, vehicles can be looked up in reverse by filtering on `owner_id` or on `vin`.

VIN verification is recorded by a clerk against a vehicle by supplying the `vehicle_id`, the `submitted_vin` transcribed from the physical plate, and the `outcome`, which is one of `MATCH`, `MISMATCH`, or `NHTSA_FLAG`. A `MATCH` outcome sets the vehicle's `vin_status` to `VERIFIED`; an outcome of either `MISMATCH` or `NHTSA_FLAG` sets it to `FLAGGED`. Recording a verification increments the affected `Vehicle.version` by 1. Verification records are write-once and can be listed in reverse by `vehicle_id`.

### 3.2. The Title Lifecycle: Clear and Salvage Paths

A `TitleApplication` ties together a subject vehicle via `vehicle_id`, the `applicant_owner_id` who will hold the new title, and an `application_type` of either `INITIAL` (a first title) or `TRANSFER` (an ownership transfer). It is created in status `DRAFT` with `requires_salvage_path` initialized to false and `issued_title_brand` unset. Its `status` moves through the values `DRAFT`, `SUBMITTED`, `SALVAGE_HOLD`, `APPROVED`, `ISSUED`, and `REJECTED`, with `ISSUED` and `REJECTED` terminal.

Submitting a draft is the first gate and the branch fork. A clerk may submit only after the subject vehicle's `vin_status` is `VERIFIED`; otherwise submission is rejected with `ERR_VIN_NOT_VERIFIED` (HTTP 409). Additionally, when the `application_type` is `TRANSFER`, the subject vehicle must already hold a title — its `title_status` must be one of `CLEAR` or `REBUILT` — or submission is rejected with `ERR_TRANSFER_REQUIRES_TITLE` (HTTP 409). On a successful submit, the application's `requires_salvage_path` is set to the vehicle's `is_salvage_branded` flag. Here the path forks: if the vehicle is salvage-branded, the application moves to `SALVAGE_HOLD` rather than `SUBMITTED`; otherwise it advances to `SUBMITTED`.

From `SUBMITTED`, a clerk may approve the application, advancing it `SUBMITTED → APPROVED`, or reject it, advancing it `SUBMITTED → REJECTED`; each requires the application to actually be in `SUBMITTED` (otherwise `ERR_INVALID_STATE`, HTTP 409). The salvage branch rejoins the main flow only through a rebuild inspection. A clerk may approve a salvage-hold application, advancing it `SALVAGE_HOLD → APPROVED`, only when a `SalvageInspection` exists for that application with `result` of `PASS`; absent such a passing inspection, approval is rejected with `ERR_SALVAGE_INSPECTION_REQUIRED` (HTTP 409). Symmetrically, a clerk may reject a salvage-hold application, advancing it `SALVAGE_HOLD → REJECTED`, only when a `SalvageInspection` exists for that application with `result` of `FAIL`; absent such a failing inspection, the rejection is likewise refused with `ERR_SALVAGE_INSPECTION_REQUIRED` (HTTP 409).

Issuance is the consequential step and the deepest cascade in the system. A clerk may issue only an application in status `APPROVED` (otherwise `ERR_INVALID_STATE`, HTTP 409), advancing it `APPROVED → ISSUED`. Issuance proceeds in a fixed sequence of effects. First, the application's `issued_title_brand` is stamped: `REBUILT` if the application required the salvage path, and `CLEAR` otherwise. Second, as a direct consequence of issuance, the subject vehicle's `title_status` is set to match — `REBUILT` if the salvage path was required, `CLEAR` otherwise — and the vehicle's `owner_id` is reassigned to the application's `applicant_owner_id`, with the affected `Vehicle.version` incremented by 1. Third, and only when the `application_type` is `TRANSFER`, that owner reassignment releases the prior owner's encumbrances: every `Lien` on the vehicle currently in status `PERFECTED` transitions to `RELEASED`, because a prior owner's perfected lien does not carry to the new owner. Fourth, each such release decrements the vehicle's `active_lien_count` by 1, keeping the lien counter synchronized with the number of perfected liens remaining.

A `SalvageInspection` is filed against a salvage-hold application by supplying the `title_application_id` and a `result` of `PASS` or `FAIL`. The filing station's identifier is captured as `station_id`, and the record's `status` is `RECORDED`, which is terminal once filed. Salvage inspections can be listed in reverse by `title_application_id`.

### 3.3. Liens and the Lien Counter Invariant

A `Lien` records an encumbrance on a vehicle via `vehicle_id`, naming the `lien_holder_name` and the outstanding `principal_cents`. It is created in status `FILED`, and its `status` lifecycle runs `FILED`, `PERFECTED`, `RELEASED`, with `RELEASED` terminal. A filed lien may be perfected only once the vehicle actually holds a title — that is, the vehicle's `title_status` is not `NONE`; perfection against a titleless vehicle is rejected with `ERR_LIEN_REQUIRES_TITLE` (HTTP 409). Perfecting a lien advances it `FILED → PERFECTED`, increments the vehicle's `active_lien_count` by 1, and increments the affected `Vehicle.version` by 1.

Releasing a lien follows one of two paths depending on where the lien stands. Releasing a lien that is currently `PERFECTED` advances it `PERFECTED → RELEASED`, decrements the vehicle's `active_lien_count` by 1, and increments the affected `Vehicle.version` by 1. Releasing a lien that was never perfected — still in `FILED` — advances it `FILED → RELEASED` but does not touch the vehicle's `active_lien_count` and does not bump the vehicle's version, since that lien was never counted. The governing invariant is that a vehicle's `active_lien_count` always equals the number of lien rows on that vehicle whose status is `PERFECTED`; perfecting increments it, releasing a perfected lien decrements it, and the cascade at title transfer (§3.2) decrements it once per perfected lien it releases. Liens can be listed in reverse by `vehicle_id`.

### 3.4. Emissions Inspections and Their Validity

An `EmissionsInspection` is filed by an inspection station against a vehicle by supplying the `vehicle_id` and a `result` of `PASS` or `FAIL`. The station's identifier is captured as `station_id`. At filing, the server stamps `inspected_at` to the current clock and computes `valid_until` as `inspected_at` plus 365 days; together these define the half-open validity window that opens at `inspected_at` and closes at `valid_until`. The record's `status` is `RECORDED`, terminal once filed. Emissions inspections can be listed in reverse by `vehicle_id`.

The validity window matters at registration activation (§3.5). For a vehicle subject to emissions — described there — the inspection cited must be a `PASS` inspection whose window contains the current clock: the current clock must be at or after `inspected_at` and strictly before `valid_until`. An inspection whose `valid_until` exactly equals the current clock has expired and does not qualify, because the window excludes its closing boundary. When more than one passing inspection exists for a vehicle, the relevant one is the latest by `inspected_at` descending, breaking ties by `created_at` descending.

### 3.5. Fee Assessment and Registration Activation

A `Registration` ties a vehicle and an owner together via `vehicle_id` and `owner_id`, carries a `registration_type` of either `INITIAL` or `TRANSFER`, and records `bundle_real_id`, a boolean defaulting to false indicating whether the counter folded a REAL ID upgrade surcharge into this registration. It is created in status `PENDING_FEES` with `plate_assigned` false, `term_start` and `term_end` unset. Its `status` lifecycle covers `PENDING_FEES`, `ACTIVE`, `SUSPENDED`, and `EXPIRED`, with `EXPIRED` terminal. Registrations can be listed in reverse by `vehicle_id` or `owner_id`.

Before a registration can activate, its fees must be assessed and paid. A `FeeAssessment` is created for a registration by supplying its `registration_id`; on creation the system computes four monetary fields — `use_tax_cents`, `registration_fee_cents`, `real_id_surcharge_cents`, and `total_cents` — and sets `status` to `ASSESSED`. The assessment's `status` lifecycle is `ASSESSED`, `PAID`, `VOIDED`. The three component amounts are computed as follows.

The **use tax** is computed on the vehicle's declared `purchase_price_cents` as the taxable basis. The combined tax rate is the state base rate of 0.065 plus a county add-on selected from the owner's `residence_county_code`: 0.025 for county code `KING`, 0.014 for county code `PIERCE`, and 0.010 for any other county code. Multiply the basis by this combined rate and round that single product to the nearest integer cent, half-up. Then apply the transfer cap: if the registration's `registration_type` is `TRANSFER`, the use tax is the smaller of the rounded amount and the private-party cap of 150000 cents; an `INITIAL` registration is taxed at the full rounded amount with no cap. Two `INITIAL` and `TRANSFER` registrations with identical inputs therefore produce identical use tax up to the cap and diverge only once the rounded amount exceeds 150000 cents, where the transfer is held at the cap. The cap is applied strictly after rounding.

The **registration fee** is a depreciation component plus a flat weight fee, computed in a pinned order. First compute the vehicle's age in years as the current registration year of 2026 minus the vehicle's `model_year`. Select the depreciation rate by age band: an age of zero or negative uses the newest-band rate of 0.0110; an age of at most 3 years uses 0.0090; an age of at most 7 years uses 0.0060; an age greater than 7 years uses 0.0030. Multiply the vehicle's `msrp_cents` by the selected rate and round that product to the nearest integer cent, half-up, to obtain the depreciation component. Then add the flat weight fee chosen by `vehicle_class`: 4300 cents for `PASSENGER`, 9000 cents for `TRUCK`, and 2500 cents for `MOTORCYCLE`. The order is binding — the depreciation product is rounded first, and only then is the integer weight fee added.

The **REAL ID surcharge** depends on the bundling flag: `real_id_surcharge_cents` is 3000 cents when the registration's `bundle_real_id` is true, and 0 otherwise. Finally, `total_cents` is the plain integer sum of `use_tax_cents`, `registration_fee_cents`, and `real_id_surcharge_cents`, with no further rounding. This order is pinned because the surcharge depends on the bundling flag and the total depends on all three components. Fee assessments can be listed in reverse by `registration_id`.

Paying a fee assessment advances it `ASSESSED → PAID`; it must be in `ASSESSED` to be paid (otherwise `ERR_INVALID_STATE`, HTTP 409). When the assessment carries a `real_id_surcharge_cents` greater than zero, payment funds the owner's REAL ID upgrade, but it triggers no automatic credential change — a clerk must still drive the REAL ID application through its own review (§3.6). An assessment may instead be voided by an administrator, advancing it `ASSESSED → VOIDED`; voiding requires the assessment to be in `ASSESSED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and requires the parent registration to still be in `PENDING_FEES` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409).

Activation is the registration's central gate, and it layers several business preconditions on top of the structural state check. A clerk activates a `PENDING_FEES` registration, advancing it `PENDING_FEES → ACTIVE`, only when all of the following hold. The registration's `FeeAssessment` must be in status `PAID`, or activation is rejected with `ERR_FEES_UNPAID` (HTTP 402). The vehicle must have a `TitleApplication` in status `ISSUED` whose `applicant_owner_id` equals the registration's `owner_id`, or activation is rejected with `ERR_TITLE_NOT_ISSUED` (HTTP 409). If the vehicle's `vehicle_class` is not `MOTORCYCLE` and its `model_year` is 2010 or later, a passing emissions inspection whose half-open validity window contains the current clock must exist for the vehicle (per §3.4), or activation is rejected with `ERR_EMISSIONS_REQUIRED` (HTTP 409); a motorcycle, or a pre-2010 vehicle, is exempt from this check. Finally, the new term — the half-open interval from the current clock to the current clock plus 365 days — must not overlap the term of any existing `ACTIVE` registration on the same vehicle; two intervals overlap when the new term's start is before the existing term's end and the existing term's start is before the new term's end. Adjacency, where the new term's start exactly equals an existing term's end, does not overlap and is allowed; a genuine overlap is rejected with `ERR_REGISTRATION_TERM_OVERLAP` (HTTP 409). On a successful activation, `term_start` is set to the current clock and `term_end` to `term_start` plus 365 days, and `plate_assigned` is reconciled to reflect whether a license plate exists for this registration.

### 3.6. The REAL ID Upgrade Review

A `RealIdApplication` records an owner's request to upgrade their credential, created against an owner via `owner_id` and carrying `documents_complete`, a boolean defaulting to false that records whether the full document set was presented. It is created in status `SUBMITTED`, and its `status` lifecycle covers `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, and `DENIED`, with `DENIED` terminal.

A clerk begins review of a `SUBMITTED` application, advancing it `SUBMITTED → UNDER_REVIEW`; this requires the application to be in `SUBMITTED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and sets the owner's `real_id_status` to `PENDING`, incrementing the affected `Owner.version` by 1. From `UNDER_REVIEW`, three transitions are available, each requiring the application to actually be `UNDER_REVIEW`. Approving the upgrade, advancing it `UNDER_REVIEW → APPROVED`, requires that the application's `documents_complete` is true and the owner's `identity_documents_verified` is true; if either is false, approval is rejected with `ERR_DOCUMENTS_INCOMPLETE` (HTTP 409). A successful approval sets the owner's `credential_type` to `REAL_ID` and the owner's `real_id_status` to `UPGRADED`, incrementing `Owner.version` by 1. Denying the upgrade, advancing it `UNDER_REVIEW → DENIED` (otherwise `ERR_INVALID_STATE`), sets the owner's `real_id_status` back to `NONE` and increments `Owner.version` by 1. Returning the application for more documents, advancing it `UNDER_REVIEW → SUBMITTED` (otherwise `ERR_INVALID_STATE`), likewise sets the owner's `real_id_status` back to `NONE` and increments `Owner.version` by 1; this is the revert cycle that lets review bounce back to intake for a more complete document set.

### 3.7. License Plates: Assignment, Activation, and Electronic Toggling

A `LicensePlate` serves a registration via `registration_id` and records its `plate_number`, its `plate_type` of either `PHYSICAL` or `ELECTRONIC`, and a system-stamped `issued_at` and `surrendered_at`. Assignment is the entry point and is guarded by optimistic concurrency: the request supplies the `registration_id`, the `plate_number`, the `plate_type`, and `expected_registration_version`, and a mismatch against the registration's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.7. On a successful assignment, the plate is created in status `ISSUED`, its `issued_at` is stamped to the current clock and its `surrendered_at` left null, the registration's `plate_assigned` is set to true, and the registration's `version` is incremented by 1. A plate's `status` lifecycle covers `ISSUED`, `ACTIVE`, `DEACTIVATED`, and `SURRENDERED`, with `SURRENDERED` terminal; `DEACTIVATED` is reachable only for an electronic plate. Plates can be listed in reverse by `registration_id`.

Two further constraints guard assignment. A registration may hold at most one plate in status `ISSUED`, `ACTIVE`, or `DEACTIVATED` at a time; an attempt to assign a second such plate to a registration that already has one is rejected with `ERR_PLATE_ALREADY_ASSIGNED` (HTTP 409). And a `plate_number` may not be reused while a prior tenancy of that same number is still open. Each plate occupies its number for a tenancy interval that opens at `issued_at` and closes at `surrendered_at`; this interval is half-open and is still open while `surrendered_at` is null. A new assignment's tenancy must not overlap any existing plate row sharing the same `plate_number` whose interval is still open or has not yet closed before the new `issued_at`; reusing a `plate_number` whose prior tenancy was surrendered at or before the new `issued_at` is permitted, with adjacency allowed at the surrender instant. A forbidden reuse is rejected with `ERR_PLATE_NUMBER_TAKEN` (HTTP 409).

Once issued, a plate is activated by a clerk, advancing it `ISSUED → ACTIVE`, but only while its parent registration is in status `ACTIVE`; otherwise activation is rejected with `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 409). An electronic plate may be remotely deactivated by a clerk, advancing it `ACTIVE → DEACTIVATED`, but only when its `plate_type` is `ELECTRONIC`; a deactivation attempt on a physical plate is rejected with `ERR_PLATE_NOT_ELECTRONIC` (HTTP 409). A deactivated plate is reactivated by a clerk, advancing it `DEACTIVATED → ACTIVE`, again only while the parent registration is `ACTIVE` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`).

### 3.8. Administrative Registration Overrides

A DMV administrator holds override authority over an active registration's lifecycle, and these overrides cascade onto the registration's plates. Suspending an `ACTIVE` registration, advancing it `ACTIVE → SUSPENDED` (the registration must be `ACTIVE`, otherwise `ERR_INVALID_STATE`, HTTP 409), transitions every electronic plate of that registration currently in status `ACTIVE` to `DEACTIVATED` and increments the registration's `version` by 1. Reinstating a `SUSPENDED` registration, advancing it `SUSPENDED → ACTIVE`, is guarded by optimistic concurrency: it requires `expected_registration_version` matching the registration's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on a mismatch (§2.7); on success it transitions every electronic plate of that registration currently in status `DEACTIVATED` back to `ACTIVE` and increments the registration's `version` by 1. Expiring an `ACTIVE` registration, advancing it `ACTIVE → EXPIRED` (the registration must be `ACTIVE`, otherwise `ERR_INVALID_STATE`), surrenders every plate of that registration in status `ISSUED`, `ACTIVE`, or `DEACTIVATED` by transitioning it to `SURRENDERED` and stamping its `surrendered_at` to the current clock, which closes that plate's number tenancy, and increments the registration's `version` by 1.

The server's logical clock can be set to a supplied instant through an administrative test-driving capability that accepts a `to_iso8601` value; this clock is what stamps `inspected_at`, `valid_until`, `term_start`, `term_end`, `issued_at`, and `surrendered_at`, and what the half-open window checks consult.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. A request that successfully creates a new resource returns HTTP 201; a request that reads or mutates an existing resource returns HTTP 200. Request and response bodies, side effects, and preconditions are described in the §3 narratives; this table lists only the surface.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /owners | Create an owner | ClerkAgent, DmvAdmin, Owner |
| GET | /owners/{id} | Get an owner | ClerkAgent, DmvAdmin, Owner |
| POST | /vehicles | Create a vehicle | ClerkAgent, DmvAdmin, Owner |
| GET | /vehicles/{id} | Get a vehicle | ClerkAgent, DmvAdmin, Owner |
| GET | /vehicles | List/filter vehicles (reverse lookup by owner or VIN) | ClerkAgent, DmvAdmin, Owner |
| POST | /vin-verifications | Record a VIN verification outcome | ClerkAgent, DmvAdmin |
| GET | /vin-verifications/{id} | Get a VIN verification | ClerkAgent, DmvAdmin |
| GET | /vin-verifications | List VIN verifications | ClerkAgent, DmvAdmin |
| POST | /title-applications | Create a title application | ClerkAgent, DmvAdmin |
| GET | /title-applications/{id} | Get a title application | ClerkAgent, DmvAdmin, Owner |
| GET | /title-applications | List title applications | ClerkAgent, DmvAdmin, Owner |
| POST | /title-applications/{id}/submit | Submit a draft title application | ClerkAgent |
| POST | /title-applications/{id}/approve | Approve a submitted/salvage-hold application | ClerkAgent |
| POST | /title-applications/{id}/reject | Reject a title application | ClerkAgent |
| POST | /title-applications/{id}/issue | Issue the title | ClerkAgent |
| POST | /salvage-inspections | Record a rebuild (salvage) inspection | InspectionStation, DmvAdmin |
| GET | /salvage-inspections/{id} | Get a salvage inspection | ClerkAgent, InspectionStation, DmvAdmin |
| GET | /salvage-inspections | List salvage inspections | ClerkAgent, InspectionStation, DmvAdmin |
| POST | /emissions-inspections | Record an emissions inspection | InspectionStation, DmvAdmin |
| GET | /emissions-inspections/{id} | Get an emissions inspection | ClerkAgent, InspectionStation, DmvAdmin |
| GET | /emissions-inspections | List emissions inspections | ClerkAgent, InspectionStation, DmvAdmin |
| POST | /liens | File a lien on a vehicle | ClerkAgent, DmvAdmin |
| GET | /liens/{id} | Get a lien | ClerkAgent, DmvAdmin, Owner |
| GET | /liens | List liens | ClerkAgent, DmvAdmin, Owner |
| POST | /liens/{id}/perfect | Perfect a filed lien | ClerkAgent |
| POST | /liens/{id}/release | Release a lien | ClerkAgent, DmvAdmin |
| POST | /registrations | Create a registration | ClerkAgent, DmvAdmin |
| GET | /registrations/{id} | Get a registration | ClerkAgent, DmvAdmin, Owner |
| GET | /registrations | List registrations | ClerkAgent, DmvAdmin, Owner |
| POST | /registrations/{id}/activate | Activate a registration | ClerkAgent |
| POST | /registrations/{id}/suspend | Suspend an active registration | DmvAdmin |
| POST | /registrations/{id}/reinstate | Reinstate a suspended registration (OCC guarded) | DmvAdmin |
| POST | /registrations/{id}/expire | Expire an active registration | DmvAdmin |
| POST | /fee-assessments | Assess fees for a registration | ClerkAgent, DmvAdmin |
| GET | /fee-assessments/{id} | Get a fee assessment | ClerkAgent, DmvAdmin, Owner |
| GET | /fee-assessments | List fee assessments | ClerkAgent, DmvAdmin, Owner |
| POST | /fee-assessments/{id}/pay | Mark a fee assessment paid | ClerkAgent, DmvAdmin, Owner |
| POST | /fee-assessments/{id}/void | Void an assessed fee | DmvAdmin |
| POST | /license-plates | Assign a license plate (OCC guarded) | ClerkAgent |
| GET | /license-plates/{id} | Get a license plate | ClerkAgent, DmvAdmin, Owner |
| GET | /license-plates | List license plates | ClerkAgent, DmvAdmin, Owner |
| POST | /license-plates/{id}/activate | Activate or reactivate a plate | ClerkAgent |
| POST | /license-plates/{id}/deactivate | Deactivate an electronic plate | ClerkAgent |
| POST | /real-id-applications | Submit a REAL ID upgrade application | ClerkAgent, DmvAdmin, Owner |
| GET | /real-id-applications/{id} | Get a REAL ID application | ClerkAgent, DmvAdmin, Owner |
| GET | /real-id-applications | List REAL ID applications | ClerkAgent, DmvAdmin, Owner |
| POST | /real-id-applications/{id}/begin-review | Begin reviewing a submitted application | ClerkAgent |
| POST | /real-id-applications/{id}/approve | Approve a REAL ID upgrade | ClerkAgent |
| POST | /real-id-applications/{id}/deny | Deny a REAL ID upgrade | ClerkAgent |
| POST | /real-id-applications/{id}/return-for-documents | Return an application for more documents | ClerkAgent |
| POST | /_clock/set_current_utc | Set the server's logical current UTC clock (test-driving) | ClerkAgent, DmvAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_VIN | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_VIN_NOT_VERIFIED | 409 |
| ERR_TRANSFER_REQUIRES_TITLE | 409 |
| ERR_SALVAGE_INSPECTION_REQUIRED | 409 |
| ERR_EMISSIONS_REQUIRED | 409 |
| ERR_TITLE_NOT_ISSUED | 409 |
| ERR_FEES_UNPAID | 402 |
| ERR_LIEN_REQUIRES_TITLE | 409 |
| ERR_PLATE_NUMBER_TAKEN | 409 |
| ERR_REGISTRATION_TERM_OVERLAP | 409 |
| ERR_PLATE_ALREADY_ASSIGNED | 409 |
| ERR_PLATE_NOT_ELECTRONIC | 409 |
| ERR_REGISTRATION_NOT_ACTIVE | 409 |
| ERR_DOCUMENTS_INCOMPLETE | 409 |
| ERR_STALE_VERSION | 412 |
</content>
</invoke>

# Stairlift Mobility Equipment API — Product Requirements Document

## 1. Introduction

Families who need a stairlift, a vertical lift, or a mobility scooter rarely buy one the way they buy ordinary retail goods. A home must be measured, the staircase geometry must be certified safe for a particular machine, money often arrives from grants, insurers, charities, or veterans' programs rather than from the customer's own pocket, and the equipment itself may be sold outright, rented for a season, installed, serviced under a maintenance plan, and eventually removed, refurbished, and resold. Every one of those steps is a potential point of failure: a quote issued against stale measurements, an installer crew double-booked across town, a funding approval that never reaches the agreement it was meant to unlock, or a warranty claim paid against a plan whose coverage was already exhausted.

This document specifies an operations API for a stairlift and mobility-equipment business that manages that entire arc — from the first customer registration through home assessment, quoting, funding, installation, service coverage, claims, removal, and buyback. The API is mounted under `/stairlift-ops` and is consumed by sales representatives, field assessors, funding officers, install coordinators, inventory managers, claims adjusters, and platform administrators, as well as by customers acting on their own accounts. The system keeps its own logical clock so that time-dependent behavior — quote expiry, service-plan lapse, rental month accrual — is deterministic and testable. Engineers implementing this specification should treat the state machines, calculation rules, and concurrency contracts described here as binding: a workflow that produces the right happy-path result but violates a cascade, a rounding rule, or a staleness check is non-conforming.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly nine roles: `PlatformAdmin`, `Customer`, `SalesRep`, `Assessor`, `AssessmentReviewer`, `FundingOfficer`, `InstallCoordinator`, `InventoryManager`, and `ClaimsAdjuster`.

- A `PlatformAdmin` is the system operator: catalog management, logical-clock control, the audit trail, and a superset of read access, plus the ability to act on behalf of others on selected write operations. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on audit records but never compares it to any entity's `id`.
- A `Customer` is the end customer. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity, and ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID` — a customer may read only their own record, accept only their own quotes, submit funding applications and warranty claims only against their own quotes and agreements, and record payments only against their own agreements.
- A `SalesRep` manages customer registration, assessment scheduling, quote creation, issuance, and revision. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `Assessor` performs site measurements and may also schedule assessments; measurement is segregated from approval. When `X-User-Role` is `Assessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `AssessmentReviewer` is the senior reviewer who approves or rejects measured assessments — deliberately segregated from the `Assessor` role. When `X-User-Role` is `AssessmentReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `FundingOfficer` adjudicates funding applications, may move an agreement past the funding gate, records payments, and cancels agreements. When `X-User-Role` is `FundingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `InstallCoordinator` schedules and drives install and removal jobs, activates and closes agreements, and manages service plans. When `X-User-Role` is `InstallCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `InventoryManager` owns the equipment lifecycle after removal — restocking refurbished units and retiring dead ones — and receives new units into stock. When `X-User-Role` is `InventoryManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `ClaimsAdjuster` reviews, adjudicates, and pays warranty claims. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

For the opaque roles above, the server may record the identifier (for example as `actor_role` context on `AuditEvent` rows) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. Every list response sorts by `created_at` ascending unless otherwise noted, and its `meta` object carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

The platform runs on a **logical clock**, not the wall clock. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it must return exactly that default and must never fall back to wall-clock time. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `now_iso8601`. Every server-stamped timestamp described in this document — `measured_at`, `approved_at`, `issued_at`, `acquired_at`, `completed_at`, and the rest — is read from this logical clock.

Advancing the clock fires two scheduled sweeps. First, any quote still sitting in `ISSUED` whose `expires_at` has been reached moves to `EXPIRED`. Second, any service plan attached to an agreement in `ACTIVE` whose `next_service_due_utc` is more than 90 days in the past moves to `LAPSED`. Both sweeps record audit events. The same clock governs rental accrual: while a rental agreement remains in `ACTIVE`, the installed unit's `lifetime_rental_months` increments by one on each subsequent logical-month rollover.

### 2.5. Resource Identity, Timestamps, and Money

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Resources with standard lifecycle metadata additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version` integer that starts low and increments by one on every mutation of that resource. Two resource kinds are deliberately leaner: a `ProductModel` catalog entry and an `AuditEvent` row carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

All monetary amounts are integer **cents** — never floats, never decimal strings. Wherever a calculation produces a fractional cent, the platform rounds half-up to the nearest whole cent at the step the rule specifies; rail-length derivation rounds half-up to two decimal places of a metre. Measurements of staircases are integer millimetres, and rail lengths are metres.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two take a version field at all.

A customer quote acceptance must carry `expected_customer_version` holding the value of the customer's `version` the client last observed. If the customer's current `version` has advanced since that read — because another workflow mutated the customer record, most notably a recompute of `lifetime_outstanding_cents` — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing against customer state it has not observed. A successful acceptance itself increments the customer's `version` by one.

Recording an out-of-pocket payment against an agreement must carry `expected_agreement_version` holding the value of that agreement's `version` the client last observed. If the agreement's current `version` no longer matches — for example because a funding decision advanced it through the auto-funding cascade, or a skip-funding transition mutated it between the client's read and this write — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful payment increments the agreement's `version` by one. Endpoints other than these two do not accept a version field.

### 2.7. Technician Crew Scheduling Discipline

Crew conflict rules differ deliberately between installs and removals. For **install jobs**, bookings on the same `technician_crew_id` must respect a 60-minute buffer: each booking is treated as a half-open interval from its `scheduled_start_utc` (inclusive) to its `scheduled_end_utc` (exclusive), extended by 60 minutes on both sides, and a proposed install whose extended interval overlaps the extended interval of any existing same-crew install job in `SCHEDULED` or `IN_PROGRESS` is rejected with `ERR_CREW_OVERLAP`. Two jobs where one's end is exactly the other's start count as adjacent, not overlapping — the buffer applies only when they are not exactly adjacent. For **removal jobs**, the rule is daily capacity rather than a buffer: a crew may perform at most 2 removals per UTC calendar day, counted among removal jobs in `SCHEDULED` on the calendar date of the proposed `scheduled_start_utc`; a third same-day booking on that crew is rejected with `ERR_CREW_OVERLAP`.

### 2.8. Pre-Request Check Ordering

When a request fails several rules at once, the response is deterministic: checks are evaluated in a fixed global order and the first failing check wins. The order is:

1. Header presence and well-formedness — failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role authorization for the endpoint — failure yields `ERR_UNAUTHORIZED` (403).
3. Reference resolution — path-templated identifiers resolve left-to-right, and each foreign key in the payload resolves — failure yields `ERR_NOT_FOUND` (404).
4. State permission — the target resource is in a state that permits the requested transition — failure yields `ERR_INVALID_STATE` (409).
5. Assessment safety and geometry gates on approval (stair width versus the model's minimum, power source, landing clearance) and the waiver block on wear-and-tear claims — failures yield `ERR_STAIR_TOO_NARROW`, `ERR_NO_POWER_SOURCE`, `ERR_LANDING_CLEARANCE_TOO_SMALL`, or `ERR_WAIVER_BLOCKS_CLAIM` (422).
6. Model compatibility with the assessment on quote issue — failure yields `ERR_MODEL_INCOMPATIBLE` (422).
7. Uniqueness — one issued quote per customer, one active install job per agreement — failures yield `ERR_ACTIVE_QUOTE_EXISTS` or `ERR_INSTALL_ALREADY_SCHEDULED` (409).
8. Temporal gates — quote expiry, install start time, purchase cooling-off — failures yield `ERR_QUOTE_EXPIRED`, `ERR_TOO_EARLY`, or `ERR_REMOVAL_COOLING_OFF` (409).
9. Crew temporal-overlap rules — failure yields `ERR_CREW_OVERLAP` (409).
10. Equipment-unit availability and model match — failure yields `ERR_UNIT_NOT_AVAILABLE` (409).
11. Fiscal gates on skip-funding, activation, and removal — failures yield `ERR_PENDING_FUNDING_APPS`, `ERR_SERVICE_PLAN_REQUIRED`, or `ERR_RENTAL_BALANCE_OUTSTANDING` (402).
12. Claim fiscal checks on adjudication — failures yield `ERR_SERVICE_PLAN_INACTIVE`, `ERR_CLAIM_KIND_NOT_COVERED`, or `ERR_COVERAGE_CAP_EXCEEDED` (402).
13. Optimistic-concurrency staleness — failure yields `ERR_STALE_VERSION` (412).

Independently of this ordering, any request body that is missing a required input field or supplies a value of the wrong type is rejected with `ERR_INVALID_REQUEST` (400).

### 2.9. Audit Trail

Material state changes are journaled into an append-only `AuditEvent` log. Each event records the `entity_kind` (the name of the affected entity, such as `Agreement`), the `entity_id` of the affected row, the `event_kind` (a transition name or cascade label — for example `ASSESS_MEASURED`, `ASSESS_SUPERSEDED`, or `QUOTE_EXPIRED`), the `actor_role` that triggered it, and a free-form JSON `payload` snapshotting pre/post state. Assessment measurement and supersession, quote issuance, revision, acceptance, and expiry, funding decisions, install completion, claim payment, and the cascades described throughout §3 all append audit events. The log is read-only and exposed only to `PlatformAdmin`, with optional `entity_kind` and `entity_id` filters.

## 3. Business Logic & Workflows

### 3.1. Customer Intake and the Home Assessment Pipeline

Everything begins with the customer. Registration by a `PlatformAdmin` or `SalesRep` captures the customer's `full_name`, `date_of_birth` (an ISO 8601 date used later for age-based funding eligibility), and `home_region_code` (a region code such as `NORTH` or `SOUTH` that funding and buyback rules consult). A newly registered customer starts in `PROSPECT` status with `lifetime_outstanding_cents` at zero; the customer list supports an optional `status` filter.

Before any equipment can be quoted, a site visit is arranged. A `SalesRep` or `Assessor` schedules a home assessment against the customer's record by supplying a `scheduled_date`; the assessment is born `SCHEDULED`. Scheduling is disruptive by design: if the same customer already has an assessment in `SCHEDULED` or `MEASURED`, the older one is pushed to `SUPERSEDED` by cascade, an `ASSESS_SUPERSEDED` audit event is appended, and — critically — when a `MEASURED` assessment is superseded this way, any quote still in `DRAFT` or `ISSUED` that was built on it is also cascaded to `SUPERSEDED`. There is therefore never a live quote hanging off a dead measurement.

After the visit, an `Assessor` submits the measurement set: the `staircase_kind` (`STRAIGHT`, `CURVED`, or `OUTDOOR`), the vertical `stair_rise_mm` (at least 500 and at most 6000 millimetres), the horizontal `stair_run_mm` (at least 500 and at most 12000), the narrowest `stair_width_mm` (at least 600 and at most 1500), the `landing_clearance_mm` at the bottom landing (between 0 and 3000), whether any portion of track is exposed to weather (`has_outdoor_exposure`, defaulting to false), and whether a 230V outlet exists within two metres of the proposed rail top (`electrical_outlet_within_2m`). Measurement is only permitted while the assessment is `SCHEDULED`; any other state is rejected with `ERR_INVALID_STATE`. All measurement fields must be present and inside their ranges, and a geometric safety minimum applies to curved staircases: for `CURVED`, the `stair_run_mm` must be at least twice the `stair_rise_mm`. Any range or geometry violation is rejected with `ERR_INVALID_MEASUREMENT` (422). A successful submission moves the assessment to `MEASURED`, stamps `measured_at` from the logical clock, appends an `ASSESS_MEASURED` audit event, and derives the rail length used downstream: the square root of the sum of the squares of the rise and the run, each converted from millimetres to metres at 1,000 millimetres per metre, rounded half-up to two decimal places.

Approval is segregated from measurement. An `AssessmentReviewer` approves a `MEASURED` assessment against a target catalog model pinned as `model_code` in the request. Three safety gates apply, and each carries its own error: the measured `stair_width_mm` must be at least the model's `min_stair_width_mm`, otherwise `ERR_STAIR_TOO_NARROW`; there must be a power source — either `electrical_outlet_within_2m` is true or the staircase is `OUTDOOR` — otherwise `ERR_NO_POWER_SOURCE`; and the `landing_clearance_mm` must be at least 500 millimetres, otherwise `ERR_LANDING_CLEARANCE_TOO_SMALL`. Approval moves the assessment to `APPROVED` and stamps `approved_at`. Alternatively, the reviewer may reject a `MEASURED` assessment outright, moving it to `REJECTED`. `APPROVED`, `REJECTED`, and `SUPERSEDED` are the terminal states of an assessment.

### 3.2. Product Catalogue and Equipment Inventory

The catalog describes what can be sold. A `PlatformAdmin` creates each `ProductModel` with its unique `model_code` SKU (for example `SL-STRAIGHT-100`), its `kind` (`STAIRLIFT`, `VERTICAL_LIFT`, or `SCOOTER`), two capability flags — `supports_curved` for curved staircases and `supports_outdoor` for weather exposure — the `min_stair_width_mm` the model fits, the `base_purchase_price_cents`, the `monthly_rental_rate_cents`, and the standard `install_labor_hours` used to size install slots and price labor. Catalog entries are listed with an optional `kind` filter, and a single entry is fetched by its `model_code`. Catalog rows are reference data: they carry an `id` and `created_at` but no `updated_at` and no `version`.

Physical stock is tracked one serialized unit at a time. Receiving by an `InventoryManager` or `PlatformAdmin` records the unit's `model_code` and globally unique `serial_number`; the unit arrives `IN_STOCK` in `condition_grade` `NEW` with `acquired_at` stamped from the logical clock and `lifetime_rental_months` at zero. The inventory list supports optional `model_code`, `status`, and `condition_grade` filters. A unit's `status` walks `IN_STOCK` → `RESERVED` → `INSTALLED` → `IN_SERVICE` → `REMOVED` as agreements consume it, and each of those moves is a cascade from the agreement lifecycle described below rather than a direct write. After removal, the `InventoryManager` dispositions the unit: a `REMOVED` unit graded `REFURB_A` or `REFURB_B` may be restocked, returning to `IN_STOCK` with its `condition_grade` unchanged, while a `REMOVED` unit graded `REFURB_C` or `RETIRED` may be retired, moving to `RETIRED`, the terminal state. The full `condition_grade` vocabulary is `NEW`, `REFURB_A`, `REFURB_B`, `REFURB_C`, and `RETIRED`.

### 3.3. Quoting: Estimate, Issue, and Revision

With an approved measurement in hand, a `SalesRep` drafts a quote against the customer's record, naming the `home_assessment_id` it is based on, the catalog `model_code`, and the `acquisition_mode` — `RENTAL` or `PURCHASE`. The quote is born `DRAFT` with `revision_number` at 1, and the platform immediately computes a forward-looking `provisional_total_cents` from catalog data. For `PURCHASE`, the provisional total is the model's `base_purchase_price_cents` plus its `install_labor_hours` at the standard labor rate of 8,500 cents per hour. For `RENTAL`, it is the model's `monthly_rental_rate_cents` multiplied by a nominal commitment of six months, plus the same labor charge. Each quote also pins the `valid_rail_length_m` derived from its assessment's measurements — the Pythagorean rail length rounded half-up to two decimal places — which later anchors the installed price. Quotes for a customer can be listed with an optional `status` filter, and a filtered quote list form exists for reverse reachability with optional `home_assessment_id`, `status`, and `customer_id` filters.

Issuing is where the estimate becomes a price. A `SalesRep` may issue only a `DRAFT` quote — anything else is `ERR_INVALID_STATE`. The referenced assessment must be `APPROVED`, otherwise `ERR_ASSESSMENT_NOT_APPROVED` (409). The catalog model must be compatible with the measured site: if the assessment's `staircase_kind` is `CURVED` the model must have `supports_curved`, and if the assessment recorded `has_outdoor_exposure` the model must have `supports_outdoor`; a mismatch is `ERR_MODEL_INCOMPATIBLE` (422). Finally, no other quote on the same customer may currently be `ISSUED`; a second live offer is `ERR_ACTIVE_QUOTE_EXISTS` (409).

At issue the forward-looking estimate is swapped for an actuals-based `issued_total_cents`. The rail materials cost comes first: the pinned `valid_rail_length_m` multiplied by 22,000 cents per metre, rounded half-up to a whole cent. If the staircase is `CURVED`, that rail cost is then multiplied by 1.35 and again rounded half-up to a whole cent. If the site has outdoor exposure, a flat sealing surcharge of 45,000 cents is added to the rail cost. The base depends on mode: for `PURCHASE` it is the model's `base_purchase_price_cents`; for `RENTAL` it is the model's `monthly_rental_rate_cents` multiplied by the nominal six-month commitment. The issued total is then the base plus the rail cost plus the model's `install_labor_hours` at the 8,500-cent hourly labor rate. The rounding order is pinned: the rail cost is rounded to whole cents before anything is summed. Issuing stamps `issued_at` from the logical clock and sets `expires_at` to `issued_at` plus the platform-configured quote time-to-live `QUOTE_TTL_DAYS`; an audit event is appended.

Offers are not forever. When the logical clock passes a quote's `expires_at` while it is still `ISSUED`, the expiry sweep moves it to `EXPIRED` with a `QUOTE_EXPIRED` audit event. Before that happens, a `SalesRep` may pull an `ISSUED` quote back to `DRAFT` for revision — a cyclic loop in which `revision_number` increments by one and `issued_total_cents` is cleared back to 0 until the quote is re-issued. Both revision and acceptance check freshness against the logical clock: an attempt on a quote whose `expires_at` has already passed is rejected with `ERR_QUOTE_EXPIRED` (409).

### 3.4. Acceptance, Funding, and Payments

Acceptance is the customer's act. The customer (or a `PlatformAdmin` acting on their behalf) accepts an `ISSUED` quote by naming the `equipment_unit_id` to reserve, the `expected_customer_version` concurrency token described in §2.6, and — for rentals — a `committed_rental_months` commitment of at least 3 months; the payload may also carry `liability_waiver_signed`, which defaults to false when omitted. The named unit must exist, must still be `IN_STOCK`, and must belong to the quote's `model_code`; otherwise the acceptance is rejected with `ERR_UNIT_NOT_AVAILABLE` (409). A stale customer version is rejected with `ERR_STALE_VERSION` as specified in §2.6.

A successful acceptance does several things at once. The quote moves to `ACCEPTED`. The unit cascades from `IN_STOCK` to `RESERVED`. A new agreement is created in `PENDING_FUNDING`, carrying the `quote_id` of the accepted quote it consummates and the `customer_id` denormalized from that quote for reverse lookup, with its `mode` copied from the quote's `acquisition_mode` and `version_anchor_quote_revision` recording the quote's `revision_number` at the moment of acceptance so stale-quote acceptance can be detected later. The agreement's `list_price_cents` is mode-dependent: for `PURCHASE` it is the quote's `issued_total_cents`; for `RENTAL` it is the model's `monthly_rental_rate_cents` multiplied by the `committed_rental_months` from the acceptance payload. Its `funding_applied_cents` starts at 0, and the customer's `lifetime_outstanding_cents` is recomputed.

Most customers do not pay list price alone. Funding applications are filed against the quote — by the customer, a `FundingOfficer`, or a `PlatformAdmin` — each recording the `quote_id` of the quote it funds alongside a `source_kind` (`STATE_GRANT`, `INSURANCE`, `CHARITY`, or `VETERAN_BENEFIT`), the `requested_cents` sought, and a `priority_rank`; lower ranks win earlier allocation, and the rank must be unique within a quote. Applications are born `PENDING` with `approved_cents` at 0, and may be listed with an optional `status` filter. A `FundingOfficer` decides each application with a `decision` and a `decision_reason`. A full approval requires the `approved_cents` to equal the `requested_cents` and moves the application to `APPROVED`; a partial approval requires `approved_cents` greater than zero and strictly less than `requested_cents` and moves it to `PARTIALLY_APPROVED`; a denial requires the `decision_reason` and moves it to `DENIED`. Any decision on an application no longer `PENDING` is `ERR_INVALID_STATE`.

Every decision recomputes the **funding waterfall** on the parent agreement. Eligible applications — those on the agreement's quote in `APPROVED` or `PARTIALLY_APPROVED` — are ordered by `priority_rank` ascending with `created_at` ascending as the tiebreak, never by identifier. The waterfall walks that order allocating each application the smaller of its `approved_cents` and the remaining unallocated balance of `list_price_cents`, accumulating `funding_applied_cents` until the balance reaches zero; the applied sum is therefore capped at `list_price_cents`. When the recomputed `funding_applied_cents` reaches or exceeds `list_price_cents` while the agreement is still `PENDING_FUNDING`, the agreement auto-transitions to `FUNDED`, the customer's `lifetime_outstanding_cents` is recomputed, and an audit event is appended.

Two escape hatches exist around the funding gate. A `FundingOfficer` may move a `PENDING_FUNDING` agreement straight to `SCHEDULED` via skip-funding — but only if the customer has signed the liability waiver on the agreement or every funding application on the quote is already `DENIED` or `WITHDRAWN`; otherwise the skip is rejected with `ERR_PENDING_FUNDING_APPS` (402). And a `FundingOfficer` may cancel an agreement outright while it is in `PENDING_FUNDING`, `FUNDED`, or `SCHEDULED`: the reserved unit is released back to `IN_STOCK` as a compensating action, every funding application on the quote moves to `WITHDRAWN`, any install job still `SCHEDULED` is cancelled, and the customer's outstanding rollup is recomputed. Cancellation from any later state is `ERR_INVALID_STATE`.

Out-of-pocket payments are recorded against the agreement by the customer, a `FundingOfficer`, or a `PlatformAdmin`, carrying the `amount_cents` and the `expected_agreement_version` token. A matching version adds the amount to `paid_to_date_cents`, increments the agreement's `version` by one, and recomputes the customer's rollup; a stale version is `ERR_STALE_VERSION` (412). The rollup itself is a standing invariant: `lifetime_outstanding_cents` is the sum, across all of the customer's agreements in `ACTIVE` or `REMOVAL_REQUESTED`, of each agreement's `list_price_cents` minus its `funding_applied_cents` minus its `paid_to_date_cents`, floored at zero, and it is re-derived on every cascade that touches agreement status, funding, or payments. Agreements may be listed with optional `status`, `customer_id`, and `mode` filters, and the agreements hanging off a quote or referencing a unit are reachable as sub-resource lists.

### 3.5. Installation and Activation

Once an agreement is `FUNDED` — whether by the waterfall or by skip-funding — an `InstallCoordinator` books the install. Every job, plan, or claim created under an agreement from this point on records the `agreement_id` of the agreement it belongs to. Creating an install job takes the `technician_crew_id`, a `scheduled_start_utc`, and a `scheduled_end_utc` that must be strictly later than the start. Three guards apply: the agreement must be `FUNDED` (anything else is `ERR_INVALID_STATE`); no other install job on the same agreement may be sitting in `SCHEDULED` or `IN_PROGRESS` (`ERR_INSTALL_ALREADY_SCHEDULED`, 409); and the same-crew 60-minute buffer rule from §2.7 must pass (`ERR_CREW_OVERLAP`). The reserved unit must also still be `RESERVED`, otherwise `ERR_UNIT_NOT_AVAILABLE`. Creating the job moves the agreement from `FUNDED` to `SCHEDULED` and the job is born `SCHEDULED`.

On the day, the coordinator starts the job — permitted only once the logical clock has reached `scheduled_start_utc`, otherwise `ERR_TOO_EARLY` (409) — moving it to `IN_PROGRESS`. Completion requires the crew's actuals: `measured_labor_hours` and the `installed_rail_length_m` actually fitted. A completion stamps `completed_at` and fans out: the parent agreement cascades from `SCHEDULED` to `INSTALLED`, the unit moves from `RESERVED` to `INSTALLED`, and a `PROSPECT` customer becomes `ACTIVE`. If the fitted rail length differs from the quote's pinned `valid_rail_length_m` by more than half a metre, the quote's `issued_total_cents` is reconciled — recomputed through the issued-price formula with the actual `installed_rail_length_m` and `measured_labor_hours` standing in for the pinned length and catalog labor. A job that goes wrong on site is instead marked failed, moving to `FAILED`; the parent agreement stays `SCHEDULED` and a fresh install job may be created. A job still in `SCHEDULED` may also simply be cancelled. `COMPLETED`, `FAILED`, and `CANCELLED` are terminal.

An installed agreement cannot go live until it is covered. A `InstallCoordinator` or `SalesRep` attaches a service plan to the `INSTALLED` agreement by choosing a `tier` — `BASIC`, `STANDARD`, or `PREMIUM`. The plan is born `ACTIVE` with `coverage_used_cents` at zero, `next_service_due_utc` set 180 days out from the logical clock, and two computed numbers. The `coverage_cap_cents` is the tier's lifetime repair cap: 50,000 cents for `BASIC`, 150,000 for `STANDARD`, and 400,000 for `PREMIUM`. The `monthly_fee_cents` starts from the tier base fee — 2,900 cents for `BASIC`, 4,900 for `STANDARD`, 7,900 for `PREMIUM` — then adds risk adders as additive percentages of that base: 15% when the assessment recorded `has_outdoor_exposure`, 20% when the staircase is `CURVED`, and 10% when the installed unit's `condition_grade` is `REFURB_B` or `REFURB_C`. The result is rounded half-up to a whole cent. When the agreement's `liability_waiver_signed` is true, a waiver-discounted variant applies instead: the fee after risk adders is multiplied by 0.85 — a 15% discount applied strictly after the adders — and then rounded half-up. With an `ACTIVE` plan in place, the coordinator activates the agreement, moving it from `INSTALLED` to `ACTIVE`; attempting activation without one is `ERR_SERVICE_PLAN_REQUIRED` (402). Activation cascades the unit from `INSTALLED` to `IN_SERVICE`, begins rental month accrual for rentals, and recomputes the customer's outstanding rollup.

### 3.6. Service Plans and Warranty Claims

A live plan is a claimable plan. While an agreement is `ACTIVE`, the customer, a `ClaimsAdjuster`, or a `PlatformAdmin` files a warranty claim naming the `service_plan_id` it draws against, the `claim_kind` — `MECHANICAL`, `ELECTRICAL`, `STRUCTURAL`, or `WEAR_AND_TEAR` — and the customer-estimated `claimed_cents`. Claims are born `SUBMITTED` with `approved_cents` at zero and can be listed per agreement with an optional `status` filter, or per plan as a sub-resource list.

Adjudication belongs to the `ClaimsAdjuster`. Review moves a `SUBMITTED` claim to `UNDER_REVIEW`. From there the adjuster adjudicates with a `decision`. Denial moves the claim to `DENIED` and requires a `denial_reason`. Approval is gated by four fiscal checks: the plan must still be `ACTIVE`, otherwise `ERR_SERVICE_PLAN_INACTIVE` (402); if the agreement's `liability_waiver_signed` is true and the claim is `WEAR_AND_TEAR`, the waiver blocks it with `ERR_WAIVER_BLOCKS_CLAIM` (422); the `claim_kind` must be inside the plan's tier coverage — `BASIC` excludes `STRUCTURAL` and `WEAR_AND_TEAR`, `STANDARD` excludes `STRUCTURAL`, and `PREMIUM` covers all four kinds — otherwise `ERR_CLAIM_KIND_NOT_COVERED` (402); and the plan's `coverage_used_cents` plus the `claimed_cents` must not exceed the `coverage_cap_cents`, otherwise `ERR_COVERAGE_CAP_EXCEEDED` (402). An approved claim sets its `approved_cents` to the smaller of `claimed_cents` and the plan's remaining headroom (`coverage_cap_cents` minus `coverage_used_cents`). Payment then moves an `APPROVED` claim to `PAID`, adds the `approved_cents` into the plan's `coverage_used_cents` — the compensating invariant that keeps the cap honest — and appends an audit event. `DENIED` and `PAID` are terminal.

Coverage is perishable. If preventive maintenance lapses — the agreement is `ACTIVE` and `next_service_due_utc` falls more than 90 days behind the logical clock — the lapse sweep moves the plan to `LAPSED`. A coordinator may also cancel an `ACTIVE` plan outright, and removal of the equipment cascades the plan to `CANCELLED`. Once a plan is no longer `ACTIVE`, adjudication of its claims fails as described above.

### 3.7. Removal, Buyback, and End of Life

Every installation eventually comes out. An `InstallCoordinator` books a removal job against an `ACTIVE` agreement with a `technician_crew_id`, `scheduled_start_utc`, and `scheduled_end_utc`. Two mode-dependent fiscal and temporal gates apply first. For a `RENTAL` agreement, removal is blocked until the rental is fully paid — `paid_to_date_cents` must have reached `list_price_cents` — otherwise `ERR_RENTAL_BALANCE_OUTSTANDING` (402). For a `PURCHASE` agreement, a cooling-off period applies: at least 30 days must have elapsed since the install completed, otherwise `ERR_REMOVAL_COOLING_OFF` (409). The crew daily-capacity rule from §2.7 — at most two removals per crew per UTC calendar day — also applies (`ERR_CREW_OVERLAP`). Creating the job moves the agreement from `ACTIVE` to `REMOVAL_REQUESTED` and computes the `buyback_offered_cents` on the job.

The buyback offer is deliberately dual-variant, keyed off the agreement's `mode`, and always starts from the model's catalog `base_purchase_price_cents` at the time of removal. For a **rental**, the straight-line variant applies: the base is multiplied by the larger of zero and one minus the elapsed whole months of installation divided by a 120-month useful life, then multiplied by the condition factor for the grade recorded on the removal — 0.85 for `REFURB_A`, 0.65 for `REFURB_B`, 0.35 for `REFURB_C`, and 0.0 for `RETIRED` — so the offer can decay all the way to zero. For a **purchase**, the market-adjusted variant applies: the base is multiplied by 0.85 raised to the number of years installed (whole months of installation divided by twelve, as a floating value), then by the same condition factor, then by a regional demand factor read from the customer's `home_region_code` — 1.10 for `NORTH`, 0.95 for `SOUTH`, 1.00 for `EAST`, and 1.05 for `WEST` — so the offer never quite reaches zero. In both variants the evaluation order is pinned: depreciation first, then the condition factor, then the region factor for market-adjusted offers; the result is rounded half-up to a whole cent after the full multiplication chain.

Completing the removal requires the assessor-graded `condition_grade_at_removal` (`REFURB_A`, `REFURB_B`, `REFURB_C`, or `RETIRED`) and triggers the largest cascade in the system: the agreement moves from `REMOVAL_REQUESTED` to `REMOVED`; the unit moves to `REMOVED` and takes on that graded condition; the service plan cascades to `CANCELLED`; and every warranty claim still in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` is forcibly moved to `DENIED` with its `denial_reason` set to `AGREEMENT_REMOVED` — a compensating reversal even for claims already approved but not yet paid. The customer's outstanding rollup is recomputed. A removal job still `SCHEDULED` may instead be cancelled, which is itself compensating: the agreement reverts from `REMOVAL_REQUESTED` back to `ACTIVE`.

The final administrative act is closure. A `InstallCoordinator` closes a `REMOVED` agreement once every warranty claim on it has reached a terminal state (`DENIED` or `PAID`); the agreement moves to `CLOSED`. If that was the customer's last open agreement — none remaining in `PENDING_FUNDING`, `FUNDED`, `SCHEDULED`, `INSTALLED`, `ACTIVE`, or `REMOVAL_REQUESTED` — the customer cascades from `ACTIVE` to `FORMER`, closing the lifecycle that began at registration. The graded unit, meanwhile, returns to §3.2's inventory flow: restocked for another life or retired for good.

## 4. Endpoint Definitions

All endpoints are mounted under `/stairlift-ops`. Operations that create a new resource respond with HTTP 201; reads, state transitions, and modifications of an existing resource respond with HTTP 200. Request payloads, computed fields, cascades, and error semantics are defined in §2 and §3 — this table is an index, not a schema. List endpoints accept `limit` and `offset` per §2.3, plus any resource-specific filters described in the workflow narratives above.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /stairlift-ops/_clock/set_current_utc | Set the logical clock to an ISO 8601 UTC instant and run time-based sweeps | PlatformAdmin |
| POST | /stairlift-ops/customers | Register a new Customer | PlatformAdmin, SalesRep |
| GET | /stairlift-ops/customers | List Customers | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, FundingOfficer, InstallCoordinator, InventoryManager, ClaimsAdjuster |
| GET | /stairlift-ops/customers/{id} | Get a Customer (self only for Customer role) | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, FundingOfficer, InstallCoordinator, InventoryManager, ClaimsAdjuster, Customer |
| POST | /stairlift-ops/customers/{id}/home-assessments | Schedule a HomeAssessment (supersedes prior open assessments) | SalesRep, Assessor |
| GET | /stairlift-ops/customers/{id}/home-assessments | List HomeAssessments for a Customer | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, InstallCoordinator |
| GET | /stairlift-ops/home-assessments/{id} | Get a HomeAssessment | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, InstallCoordinator |
| POST | /stairlift-ops/home-assessments/{id}/measure | Submit measurements (SCHEDULED to MEASURED) | Assessor |
| POST | /stairlift-ops/home-assessments/{id}/approve | Approve a MEASURED assessment against a target model | AssessmentReviewer |
| POST | /stairlift-ops/home-assessments/{id}/reject | Reject a MEASURED assessment | AssessmentReviewer |
| POST | /stairlift-ops/product-models | Create a ProductModel catalog entry | PlatformAdmin |
| GET | /stairlift-ops/product-models | List ProductModels | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, InstallCoordinator, InventoryManager |
| GET | /stairlift-ops/product-models/{id} | Get a ProductModel by its model_code | PlatformAdmin, SalesRep, Assessor, AssessmentReviewer, InstallCoordinator, InventoryManager |
| POST | /stairlift-ops/equipment-units | Receive a new EquipmentUnit into inventory | InventoryManager, PlatformAdmin |
| GET | /stairlift-ops/equipment-units | List EquipmentUnits | PlatformAdmin, InventoryManager, SalesRep, InstallCoordinator |
| GET | /stairlift-ops/equipment-units/{id} | Get an EquipmentUnit | PlatformAdmin, InventoryManager, SalesRep, InstallCoordinator |
| POST | /stairlift-ops/equipment-units/{id}/restock | Restock a REMOVED unit as refurbished | InventoryManager |
| POST | /stairlift-ops/equipment-units/{id}/retire | Retire a REMOVED unit | InventoryManager |
| POST | /stairlift-ops/customers/{id}/quotes | Create a DRAFT Quote against a measured/approved assessment | SalesRep |
| GET | /stairlift-ops/customers/{id}/quotes | List Quotes for a Customer | PlatformAdmin, SalesRep, FundingOfficer, Customer |
| GET | /stairlift-ops/quotes/{id} | Get a Quote | PlatformAdmin, SalesRep, FundingOfficer, Customer |
| GET | /stairlift-ops/quotes | List Quotes (filtered reverse-lookup form) | PlatformAdmin, SalesRep, FundingOfficer |
| GET | /stairlift-ops/quotes/{id}/agreements | List Agreements for a Quote | PlatformAdmin, SalesRep, FundingOfficer, InstallCoordinator |
| GET | /stairlift-ops/equipment-units/{id}/agreements | List Agreements referencing an EquipmentUnit | PlatformAdmin, InventoryManager, InstallCoordinator |
| GET | /stairlift-ops/service-plans/{id}/warranty-claims | List WarrantyClaims against a ServicePlan | PlatformAdmin, ClaimsAdjuster, InstallCoordinator |
| POST | /stairlift-ops/quotes/{id}/issue | Issue a DRAFT Quote (DRAFT to ISSUED) | SalesRep |
| POST | /stairlift-ops/quotes/{id}/revise | Return an ISSUED Quote to DRAFT (cyclic revision) | SalesRep |
| POST | /stairlift-ops/quotes/{id}/accept | Customer accepts a Quote; creates Agreement and reserves the unit | Customer, PlatformAdmin |
| POST | /stairlift-ops/quotes/{id}/funding-applications | Submit a FundingApplication for a Quote | Customer, FundingOfficer, PlatformAdmin |
| GET | /stairlift-ops/quotes/{id}/funding-applications | List FundingApplications for a Quote | PlatformAdmin, FundingOfficer, Customer, SalesRep |
| GET | /stairlift-ops/funding-applications/{id} | Get a FundingApplication | PlatformAdmin, FundingOfficer, Customer |
| POST | /stairlift-ops/funding-applications/{id}/decide | Adjudicate a FundingApplication | FundingOfficer |
| GET | /stairlift-ops/agreements | List Agreements | PlatformAdmin, SalesRep, FundingOfficer, InstallCoordinator, ClaimsAdjuster |
| GET | /stairlift-ops/agreements/{id} | Get an Agreement | PlatformAdmin, SalesRep, FundingOfficer, InstallCoordinator, ClaimsAdjuster, Customer |
| POST | /stairlift-ops/agreements/{id}/skip-funding | Move PENDING_FUNDING to SCHEDULED without waiting for funding | FundingOfficer |
| POST | /stairlift-ops/agreements/{id}/payments | Record a customer out-of-pocket payment (OCC-guarded) | Customer, FundingOfficer, PlatformAdmin |
| POST | /stairlift-ops/agreements/{id}/activate | Activate an INSTALLED Agreement (requires an ACTIVE ServicePlan) | InstallCoordinator |
| POST | /stairlift-ops/agreements/{id}/cancel | Cancel an Agreement (compensating release) | FundingOfficer |
| POST | /stairlift-ops/agreements/{id}/close | Close a REMOVED Agreement | InstallCoordinator |
| POST | /stairlift-ops/agreements/{id}/install-jobs | Schedule an InstallJob (Agreement must be FUNDED) | InstallCoordinator |
| GET | /stairlift-ops/agreements/{id}/install-jobs | List InstallJobs for an Agreement | PlatformAdmin, InstallCoordinator, SalesRep |
| GET | /stairlift-ops/install-jobs/{id} | Get an InstallJob | PlatformAdmin, InstallCoordinator, SalesRep |
| POST | /stairlift-ops/install-jobs/{id}/start | Start a SCHEDULED InstallJob | InstallCoordinator |
| POST | /stairlift-ops/install-jobs/{id}/complete | Complete an IN_PROGRESS InstallJob with measured actuals | InstallCoordinator |
| POST | /stairlift-ops/install-jobs/{id}/fail | Fail an IN_PROGRESS InstallJob | InstallCoordinator |
| POST | /stairlift-ops/install-jobs/{id}/cancel | Cancel a SCHEDULED InstallJob | InstallCoordinator |
| POST | /stairlift-ops/agreements/{id}/service-plans | Attach a ServicePlan to an INSTALLED Agreement | InstallCoordinator, SalesRep |
| GET | /stairlift-ops/agreements/{id}/service-plans | List ServicePlans for an Agreement | PlatformAdmin, InstallCoordinator, SalesRep, ClaimsAdjuster, Customer |
| GET | /stairlift-ops/service-plans/{id} | Get a ServicePlan | PlatformAdmin, InstallCoordinator, SalesRep, ClaimsAdjuster, Customer |
| POST | /stairlift-ops/service-plans/{id}/cancel | Cancel an ACTIVE ServicePlan | InstallCoordinator |
| POST | /stairlift-ops/agreements/{id}/warranty-claims | Submit a WarrantyClaim against an ACTIVE Agreement | Customer, ClaimsAdjuster, PlatformAdmin |
| GET | /stairlift-ops/agreements/{id}/warranty-claims | List WarrantyClaims for an Agreement | PlatformAdmin, ClaimsAdjuster, Customer, InstallCoordinator |
| GET | /stairlift-ops/warranty-claims/{id} | Get a WarrantyClaim | PlatformAdmin, ClaimsAdjuster, Customer |
| POST | /stairlift-ops/warranty-claims/{id}/review | Move a SUBMITTED claim to UNDER_REVIEW | ClaimsAdjuster |
| POST | /stairlift-ops/warranty-claims/{id}/adjudicate | Adjudicate an UNDER_REVIEW claim (approve or deny) | ClaimsAdjuster |
| POST | /stairlift-ops/warranty-claims/{id}/pay | Pay an APPROVED claim | ClaimsAdjuster |
| POST | /stairlift-ops/agreements/{id}/removal-jobs | Schedule a RemovalJob (Agreement ACTIVE to REMOVAL_REQUESTED) | InstallCoordinator |
| GET | /stairlift-ops/agreements/{id}/removal-jobs | List RemovalJobs for an Agreement | PlatformAdmin, InstallCoordinator, SalesRep |
| GET | /stairlift-ops/removal-jobs/{id} | Get a RemovalJob | PlatformAdmin, InstallCoordinator, SalesRep |
| POST | /stairlift-ops/removal-jobs/{id}/complete | Complete a RemovalJob with the graded condition | InstallCoordinator |
| POST | /stairlift-ops/removal-jobs/{id}/cancel | Cancel a SCHEDULED RemovalJob (Agreement reverts to ACTIVE) | InstallCoordinator |
| GET | /stairlift-ops/audit-events | List AuditEvents | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflow narratives of §2 and §3; this table is an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_PENDING_FUNDING_APPS | 402 |
| ERR_RENTAL_BALANCE_OUTSTANDING | 402 |
| ERR_SERVICE_PLAN_REQUIRED | 402 |
| ERR_SERVICE_PLAN_INACTIVE | 402 |
| ERR_CLAIM_KIND_NOT_COVERED | 402 |
| ERR_COVERAGE_CAP_EXCEEDED | 402 |
| ERR_INVALID_STATE | 409 |
| ERR_ASSESSMENT_NOT_APPROVED | 409 |
| ERR_ACTIVE_QUOTE_EXISTS | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_UNIT_NOT_AVAILABLE | 409 |
| ERR_REMOVAL_COOLING_OFF | 409 |
| ERR_INSTALL_ALREADY_SCHEDULED | 409 |
| ERR_CREW_OVERLAP | 409 |
| ERR_TOO_EARLY | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_MEASUREMENT | 422 |
| ERR_STAIR_TOO_NARROW | 422 |
| ERR_NO_POWER_SOURCE | 422 |
| ERR_LANDING_CLEARANCE_TOO_SMALL | 422 |
| ERR_MODEL_INCOMPATIBLE | 422 |
| ERR_WAIVER_BLOCKS_CLAIM | 422 |

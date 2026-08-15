# Building Energy Benchmarking & Disclosure API — Product Requirements Document

## 1. Introduction

Municipal benchmarking ordinances oblige the owners of large buildings to measure, disclose, and steadily improve the energy performance of their stock. Compliance is not a single filing but a year-round discipline: the city must first decide which buildings are covered, owners must assemble whole-building consumption data — often spanning tenant spaces whose occupants must consent to aggregation — accredited third parties must verify the numbers, and the city must publish results, levy penalties for lateness or non-compliance, and track performance against long-term reduction trajectories. Each of these steps interacts with the others: a voided utility record can reopen a verified report, a revoked consent can suppress a published score, and an approved deadline extension can dissolve fines that were already accruing.

This document specifies the Building Energy Benchmarking & Disclosure API, the system of record for that ordinance. It covers the covered-building list and its jurisdiction thresholds, whole-building data aggregation under tenant consent, annual submission deadlines with penalty accrual, third-party data verification with anomaly flagging, energy-score computation and labeling, performance-standard trajectory fines, exemption and extension requests, and public disclosure publication. All endpoints are mounted under the `/v1` prefix. The specification is written for the engineers who will implement the service; it defines the observable contract precisely while presenting the business rules in the narrative contexts where they operate.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare the caller's operational capacity. The system recognizes exactly five roles: `BuildingOwner`, `TenantRep`, `DataVerifier`, `UtilityAgent`, and `ComplianceOfficer`. A request whose headers are missing, empty, or whose role value is not one of these five declared roles is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Every endpoint also carries a list of roles permitted to invoke it; a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`. Read endpoints accept any authenticated role.

Three of the five roles are entity-backed, meaning `X-User-ID` is compared against persisted resources. When `X-User-Role` is `BuildingOwner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that references an owner or a building compare the building's `owner_id` to `X-User-ID`. When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id` of the `TenantUnit` the caller represents; consent decisions on a grant are authorized only when the grant's `tenant_unit_id` equals `X-User-ID`. When `X-User-Role` is `DataVerifier`, `X-User-ID` is the `id` of the acting `Verifier`; sign-off and rejection of a verification record are authorized only when the record's `verifier_id` equals `X-User-ID`. A failure of any of these entity-backed ownership checks is rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining two roles carry opaque identifiers. When `X-User-Role` is `UtilityAgent`, `X-User-ID` is an opaque operator identifier for a city-authorized utility data feed, not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque officer identifier; the server records it — for example as `created_by_officer_id` on a reporting cycle at creation time — but does not treat it as the `id` of any registered entity. The recorded `created_by_officer_id` later drives the segregation-of-duties check on certification described in §3.6.

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

Requests addressed to a path the API does not define, or with a method the path does not support, are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range or unparseable values are never an error: an unparseable `limit` or `offset` falls back to its default, a `limit` below 1 or above 100 is clamped into that range, and a negative `offset` is treated as 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — owners, verifiers, reporting cycles, buildings, tenant units, consent grants, utility accounts, usage records, benchmark reports, verification records, anomaly flags, fine assessments, exemption requests, and disclosure publications — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T00:00:00.000Z`), set when the resource is first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating the last modification. It refreshes on every change to the resource, including changes produced by system cascades.
- **`version` (integer):** A system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects originating elsewhere. This field backs the optimistic concurrency control mechanism of §2.7.

All fourteen entity types in this system carry the full set of common fields; none of them omit `updated_at` or `version`. At creation `version` is 1 and `updated_at` equals `created_at`. `created_at` and `updated_at` are stamped from the server's wall-time clock — kept strictly increasing so no two stamps collide — not from the logical clock of §2.5, and they always render with three fractional digits. Every other datetime field (`filing_deadline_at`, `period_start`, `period_end`, `decided_at`, `submitted_at`, `verified_at`, `assessed_at`, `noticed_at`, `paid_at`, `extended_deadline_at`, `published_at`, `superseded_at`, and the clock endpoint's `current_utc`) renders as ISO 8601 UTC with the fractional part omitted when the value lands exactly on a whole second.

### 2.5. The Logical Clock

Time in this system is governed by a server-side logical clock, never by wall-clock time. Every rule that depends on the current instant — filing-deadline comparisons at submission and close-filing, the lazily-applied expiry of consent windows, day-count computations for late fines — reads this logical clock. Before the clock has ever been explicitly set, it reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time under any circumstance.

A `ComplianceOfficer` may advance the logical clock through a dedicated test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`; an unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. Setting the clock does not itself fire any background jobs; time-dependent state such as consent expiry is re-evaluated lazily against the logical clock on subsequent reads and recomputations, as described in §3.3.

### 2.6. Measurement, Unit Conversion, and Rounding Discipline

Energy quantities originate in the native unit of each metered commodity — kilowatt-hours for electricity, therms for natural gas, kilopounds for district steam, gallons for fuel oil — and are normalized to thousands of British thermal units. The conversion factors are fixed: each kilowatt-hour of `ELECTRICITY` contributes 3.412 kBtu, each therm of `NATURAL_GAS` contributes 100 kBtu, each kilopound of `DISTRICT_STEAM` contributes 1194 kBtu, and each gallon of `FUEL_OIL` contributes 138.5 kBtu.

Rounding order is pinned and non-negotiable: conversion and rounding happen **per usage record**, and only then are the per-record values summed. Each record's `kbtu` is its `consumption_value` multiplied by its commodity's factor, rounded half-up to a whole integer of kBtu; the whole-building total is the sum of those already-rounded integers. Raw consumption values are never summed first and converted afterward.

Two further precision conventions apply throughout. Energy-use-intensity values and percentage values (`site_eui`, `data_completeness_pct`, score intermediates, delta percentages, trajectory targets) are carried at exactly two decimal places with round-half-up rounding. Monetary amounts are integer numbers of cents, with any multiplication that yields a fractional cent rounded half-up to a whole cent. Durations of lateness are measured in whole 24-hour days of 86,400 seconds each, discarding any partial-day remainder.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both name their expectation field after the entity being modified. A request to update a building must carry `expected_building_version` equal to the building's current `version`; the field is required, not optional. A request to edit a reporting cycle's configuration must likewise carry `expected_cycle_version` equal to the cycle's current `version`. An expectation field that is absent or not an integer is rejected with `ERR_INVALID_REQUEST`. When the supplied value does not match the entity's current `version` — because the client is building on a stale read — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check runs after existence checks and before all business logic. No other endpoint accepts a version field.

### 2.8. Validation Order and Error Priority

When a single request violates several rules, the system does not choose arbitrarily among them: checks are evaluated in a fixed priority order, and the request reports the error belonging to the lowest-numbered priority tier. The tiers, in order, are:

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must be present, non-empty, and carry a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization.** The caller's role must appear in the endpoint's role list (`ERR_FORBIDDEN_ROLE`).
3. **Entity-backed ownership.** A `BuildingOwner` must own the building acted on, a `TenantRep` must act on their own unit, and a `DataVerifier` must be the record's assigned verifier (`ERR_NOT_RESOURCE_OWNER`).
4. **Existence.** Every path- or body-referenced resource must exist, validated left to right (`ERR_NOT_FOUND`).
5. **Optimistic concurrency.** `expected_building_version` or `expected_cycle_version` must match the entity's current `version` (`ERR_STALE_VERSION`).
6. **Input semantics.** Required fields present, enum values valid, numbers positive where required, date ranges coherent, string minimum lengths honored, and partial replacement field sets refused (`ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`). Request fields the endpoint does not define are ignored rather than rejected.
7. **State-machine preconditions.** The target resource's current state must allow the requested transition (`ERR_INVALID_STATE_TRANSITION`).
8. **Cycle and deadline gates.** Report creation requires an `OPEN` cycle (`ERR_CYCLE_NOT_OPEN`), submission requires an `OPEN` cycle (`ERR_FILING_CLOSED` once filing has closed or the cycle is published), close-filing requires the logical clock to sit strictly past the deadline (`ERR_CYCLE_NOT_CLOSABLE`), cycle configuration edits are allowed only while the cycle is `SCHEDULED` or `OPEN` (`ERR_CYCLE_NOT_EDITABLE`), and disclosure publication requires a closed or published cycle (`ERR_CYCLE_NOT_CLOSED`).
9. **Safety and compliance gates.** Certification is forbidden to the officer who created the cycle (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), submission requires zero open anomaly flags (`ERR_OPEN_ANOMALIES_EXIST`, HTTP 409), a report may have at most one pending verification record (`ERR_VERIFIER_ALREADY_ASSIGNED`, HTTP 409), and an exemption request may not be filed once a report exists for the cycle (`ERR_REPORT_ALREADY_FILED`, HTTP 409).
10. **Constraint gates.** Data completeness at or above the cycle minimum (`ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`, HTTP 422), consent windows that do not overlap (`ERR_CONSENT_WINDOW_OVERLAP`, HTTP 409), usage periods that do not overlap (`ERR_USAGE_PERIOD_OVERLAP`, HTTP 409), one report per building and cycle (`ERR_DUPLICATE_REPORT`, HTTP 409), account numbers unique per building (`ERR_DUPLICATE_ACCOUNT`, HTTP 409), at most one open consent request per unit (`ERR_CONSENT_REQUEST_OPEN`, HTTP 409), at most one open exemption request per building and cycle (`ERR_EXEMPTION_REQUEST_OPEN`, HTTP 409), at most one approved extension per building and cycle (`ERR_EXTENSION_ALREADY_GRANTED`, HTTP 409), the building on the covered list (`ERR_BUILDING_NOT_COVERED`, HTTP 422), a performance standard defined for the building's property type (`ERR_STANDARD_NOT_DEFINED`, HTTP 422), no existing draft publication for the cycle (`ERR_DRAFT_PUBLICATION_EXISTS`, HTTP 409), and the archive guards (`ERR_OPEN_FINES_EXIST`, `ERR_OPEN_REPORTS_EXIST`, both HTTP 409).
11. **Fiscal gates.** Submission is blocked while the owner's standing is `RESTRICTED` (`ERR_OWNER_RESTRICTED`, HTTP 403), and fine payment must match the noticed amount exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`, HTTP 422).

### 2.9. Nested Resource Retrieval

Several creation and retrieval operations address a child resource through its parent — a tenant unit beneath a building, a consent grant beneath a unit, a usage record beneath a utility account, a verification record or anomaly flag beneath a benchmark report, an exemption request beneath a building, a disclosure publication beneath a cycle. For every such request the system validates the identifiers in the path sequentially from left to right, rejecting immediately with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any deeper identifier or business rule is examined. Body-referenced resources — a `building_id` or `cycle_id` in a creation payload, for instance — are validated under the same existence tier: a body reference that is absent or not a string is rejected with `ERR_INVALID_REQUEST`, and a well-formed identifier that matches no persisted resource is rejected with `ERR_NOT_FOUND`. When the caller's ownership of a referenced resource is in question, that resource's existence is confirmed first — ownership of a resource that does not exist cannot be evaluated.

### 2.10. Cascading Consistency

The system's consistency model is immediate: every side effect of an operation is applied atomically with the operation itself and is visible in that operation's response and in every subsequent read. There is no asynchronous settlement. Cascades in this domain run deep — voiding a usage record can recompute a report's aggregates, reopen its verification, and supersede a published disclosure in a single request — and every resource mutated along a cascade chain, whether it is the direct target of the request or a downstream parent, refreshes its `updated_at` and increments its `version`. When a cascade creates a new resource (a replacement usage record, an anomaly flag, a fine assessment, a replacement draft publication), that resource is created within the same atomic boundary.

## 3. Business Logic & Workflows

### 3.1. Administering the Ordinance: Registry and Reporting Cycles

Before any filing season begins, a `ComplianceOfficer` populates the registry. Registering a building owner requires the owner's legal `name` and `contact_email`; a newly registered owner starts with `standing` of `NORMAL` and `outstanding_fines_cents` of zero. Registering a data verifier requires the verifier's `name` and `license_number`, which must be unique across all verifiers — a duplicate is rejected with `ERR_INVALID_REQUEST` — and accepts an optional `accredited` flag that defaults to true.

With the registry in place, the officer creates a **reporting cycle** for a calendar year. Creation takes the `cycle_year` — which must be unique across cycles and whose coverage window runs from the first instant of January 1 of that year up to but not including the first instant of January 1 of the following year — together with the `filing_deadline_at`, the `covered_floor_area_threshold_sqft`, the list of `covered_property_types`, the `late_fine_daily_rate_cents`, the `late_fine_cap_days`, the `non_compliance_fine_cents`, and the `performance_standards` array. Each entry of `performance_standards` is a per-property-type object carrying `property_type`, `median_eui`, `score_slope`, `baseline_eui_default`, `annual_reduction_pct`, `shortfall_tolerance_pct`, `fine_rate_cents_per_sqft`, and `performance_fine_cap_cents`; every entry must carry all eight fields, `property_type` must be one of the declared property types, and the other seven fields must be numbers — violations are rejected with `ERR_INVALID_REQUEST`, as are `covered_property_types` entries that are not declared property types and a `cycle_year` already taken by another cycle. Four further knobs are optional at creation: `data_completeness_min_pct` defaults to 90, `correction_tolerance_pct` defaults to 5, `anomaly_yoy_threshold_pct` defaults to 25, and `weather_adjustment_factor` defaults to 1.0. A new cycle begins in `SCHEDULED` status, and the system records the creating officer's header identity as `created_by_officer_id`; the cycle's `published_at` stays null until the cycle is first published.

A cycle's configuration — the deadline, the fine rates, the weather factor, the performance standards, and the four optional thresholds — may be edited only while the cycle is `SCHEDULED` or `OPEN`; once filing has closed, the attempt is rejected with `ERR_CYCLE_NOT_EDITABLE`. Fields outside that editable set — `cycle_year`, `covered_floor_area_threshold_sqft`, `covered_property_types`, and anything unrecognized — are ignored rather than rejected. The `SCHEDULED`/`OPEN` state check fires before the deep validation of any supplied `performance_standards` entries, so an edit attempt on a closed cycle fails with `ERR_CYCLE_NOT_EDITABLE` even when the payload's standards entries are malformed. Every such edit is OCC-guarded per §2.7 and increments the cycle's `version`.

Opening the cycle moves it `SCHEDULED → OPEN` and is valid only from `SCHEDULED`, otherwise `ERR_INVALID_STATE_TRANSITION`. Closing the filing window is the season's pivotal act. It requires the cycle to be `OPEN` and the logical clock to sit strictly later than `filing_deadline_at` — at exactly the deadline instant, or before it, the attempt fails with `ERR_CYCLE_NOT_CLOSABLE`. On success the cycle moves `OPEN → FILING_CLOSED` and a two-stage sweep runs. First, every covered building with no report in `VERIFIED` or `CERTIFIED` for this cycle receives a `FineAssessment` of `fine_type` `NON_COMPLIANCE` in `ASSESSED` status whose `provisional_amount_cents` equals the cycle's `non_compliance_fine_cents`. Second, every covered building that does hold a `VERIFIED` or `CERTIFIED` report is evaluated under the performance-shortfall rule of §3.6, and a `PERFORMANCE_SHORTFALL` fine in `ASSESSED` status is created whenever that rule trips. Each fine created by the sweep immediately recomputes the affected owner's exposure per §3.7, and an owner whose `outstanding_fines_cents` crosses above the restriction threshold flips to `RESTRICTED` standing as part of the same request.

A cycle reaches `PUBLISHED` only as a side effect of disclosure publication (§3.9); there is no direct cycle-level publish action. `PUBLISHED` is the cycle's terminal state.

### 3.2. Buildings and the Covered-Building List

A building is registered with its street `address`, its `gross_floor_area_sqft` (which must be strictly greater than zero), and its `property_type`, one of `OFFICE`, `MULTIFAMILY`, `RETAIL`, `HOTEL`, or `INDUSTRIAL`. When a `BuildingOwner` registers the building, the system takes `owner_id` from the caller's `X-User-ID` — a body `owner_id` sent by a `BuildingOwner` is ignored, and the system does not verify that the resulting id names a registered owner; when a `ComplianceOfficer` registers one, the officer must supply `owner_id` in the request body, where an absent `owner_id` yields `ERR_INVALID_REQUEST` and one naming no registered owner yields `ERR_NOT_FOUND`. Every new building starts `ACTIVE`. Buildings may be listed with optional `owner_id` and `property_type` filters.

Whether a building appears on a cycle's **covered-building list** is a pure function of four conditions, all of which must hold: the building is `ACTIVE`; its `gross_floor_area_sqft` is at least the cycle's `covered_floor_area_threshold_sqft` — the threshold is inclusive, so a building at exactly the threshold is covered; its `property_type` is among the cycle's `covered_property_types`; and no `APPROVED` exemption request of `request_type` `EXEMPTION` exists for that building and cycle. Listing buildings with the `covered_in_cycle_id` query parameter applies this determination for the named cycle and returns exactly the covered list; a `covered_in_cycle_id` naming no existing cycle is rejected with `ERR_NOT_FOUND`. The same determination drives report creation (§3.5), the close-filing sweep (§3.1), and the compliance summary below.

Building attributes may be updated by the owning `BuildingOwner` or a `ComplianceOfficer`. The updatable attributes are `address`, `gross_floor_area_sqft`, and `property_type`; other fields, `owner_id` included, are ignored. The update is OCC-guarded by `expected_building_version` and increments the building's `version`. When `gross_floor_area_sqft` changes, the `site_eui` of every one of the building's reports currently in `DRAFT` or `FLAGGED` is recomputed against the new area (aggregated consumption is unaffected).

Archiving retires a building from the program: a `ComplianceOfficer` moves it `ACTIVE → ARCHIVED`. Two guards protect the transition — the building must have no fine assessment in `ASSESSED` or `NOTICED` (otherwise `ERR_OPEN_FINES_EXIST`) and no benchmark report in `DRAFT`, `SUBMITTED`, or `FLAGGED` (otherwise `ERR_OPEN_REPORTS_EXIST`) — and the building itself must currently be `ACTIVE`, else `ERR_INVALID_STATE_TRANSITION`. `ARCHIVED` is terminal.

A per-cycle **compliance summary** is available for any building, keyed by the `cycle_id` query parameter. It is a computed read, not a stored entity, and it exposes: `covered`, the coverage determination for that cycle; `report_status`, the status of the building's report for the cycle or null when none exists; `outstanding_fines_cents`, the owner's current outstanding exposure across all of their buildings; `settled_exposure_cents` and `projected_exposure_cents`, the two exposure reads defined in §3.7; `latest_score_as_reported` and `latest_label_grade`, the most recent verified score and label, or null when the building has none; and `effective_deadline_at`, the deadline actually governing the building — the approved extension's `extended_deadline_at` when one exists, else the cycle's `filing_deadline_at`. The `cycle_id` query parameter is required (`ERR_INVALID_REQUEST` when absent) and must name an existing cycle (`ERR_NOT_FOUND`). "Most recent" for the score and label reads means the building's report with a non-null `verified_at` belonging to the cycle with the largest `cycle_year`.

### 3.3. Tenant Units and Consent Management

Whole-building data frequently spans tenant-controlled space, and the ordinance requires tenant consent before a unit's consumption may be aggregated. The owner models the building's rentable space as **tenant units**, each created under its building with a `unit_label`, a `floor_area_sqft` strictly greater than zero, a `space_type` of `OFFICE`, `RETAIL`, `RESIDENTIAL`, `COMMON`, or `OTHER`, and an `occupied` flag that defaults to true. Units may be listed with an optional `building_id` filter. An owner may later update a unit's `floor_area_sqft` or `occupied`; such an update recomputes `data_completeness_pct` on every one of the building's reports currently in `DRAFT` or `FLAGGED`.

Consent flows through a **consent grant** lifecycle. The `BuildingOwner` initiates it by requesting consent for a unit, which creates a grant in `REQUESTED` status whose `scope` is fixed to `WHOLE_BUILDING_AGGREGATION` and whose `valid_from`, `valid_to`, and `decided_at` stay null until a decision; at most one `REQUESTED` grant may exist per unit at a time, and a second request is refused with `ERR_CONSENT_REQUEST_OPEN`. The decision belongs to the tenant: a `TenantRep` whose `X-User-ID` matches the grant's `tenant_unit_id` may grant or deny it, and any other caller receives `ERR_NOT_RESOURCE_OWNER`. Denial moves the grant `REQUESTED → DENIED` and stamps `decided_at`.

Granting consent is more involved. The tenant supplies a `valid_from` and `valid_to`, both calendar dates — a value that is not a parseable calendar date is rejected with `ERR_INVALID_REQUEST` — and the window is a closed interval — both endpoints are included. The grant request must still be `REQUESTED` (else `ERR_INVALID_STATE_TRANSITION`), `valid_from` must not fall after `valid_to` (else `ERR_INVALID_DATE_RANGE`), and the new window must not intersect any other `GRANTED` window on the same unit. Two closed windows intersect exactly when the new window's `valid_from` falls on or before the existing window's `valid_to` **and** the existing window's `valid_from` falls on or before the new window's `valid_to`; an intersecting grant is rejected with `ERR_CONSENT_WINDOW_OVERLAP`. Lazy expiry applies to the comparison: a window whose `valid_to` has already passed against the logical clock reads as `EXPIRED` and does not block a new grant. A successful grant moves `REQUESTED → GRANTED`, stamps `decided_at`, and recomputes `data_completeness_pct` on the building's reports in `DRAFT`, `FLAGGED`, or `SUBMITTED` for every cycle whose calendar year the new window covers.

A granted consent can be withdrawn: revocation moves `GRANTED → REVOKED` and carries the same tenant-identity check. Because expiry is lazy, a grant that already reads as `EXPIRED` against the logical clock can no longer be revoked — the attempt yields `ERR_INVALID_STATE_TRANSITION`. Revocation recomputes `data_completeness_pct` on **all** of the building's reports for the affected cycles regardless of their status — `DRAFT`, `FLAGGED`, `SUBMITTED`, `VERIFIED`, and `CERTIFIED` alike — and where the recomputed completeness of a `VERIFIED` or `CERTIFIED` report falls below the score-eligibility floor of 75 percent, that report's `score_as_reported` and `score_weather_normalized` are suppressed to null and its `label_grade` becomes `INSUFFICIENT_DATA`, while the report's status is left unchanged. If such a suppressed report is included in a currently `PUBLISHED` disclosure publication, the publication is superseded per the cascade in §3.9.

Consent windows also expire with time. When the logical clock's current date falls strictly after a grant's `valid_to`, the grant reads as `EXPIRED` and is excluded from completeness computation. Expiry is lazy: it is evaluated whenever a grant is read or a completeness recomputation runs, and no background job sweeps for it. `DENIED`, `REVOKED`, and `EXPIRED` are terminal. Grants may be listed filtered by `tenant_unit_id` or `status`, with lazy expiry applied to the results.

### 3.4. Utility Accounts and Usage Data

Metered commodities enter the system through **utility accounts** registered on a building by the owning `BuildingOwner` or a `ComplianceOfficer`. Each account carries an `account_number`, which must be unique within its building — a duplicate is refused with `ERR_DUPLICATE_ACCOUNT` — and a `commodity` of `ELECTRICITY`, `NATURAL_GAS`, `DISTRICT_STEAM`, or `FUEL_OIL`. Accounts may be listed filtered by `building_id` or `commodity`.

A `UtilityAgent` uploads **usage records** against an account. Each record declares a `period_start` and `period_end` describing a half-open interval — the start instant is included and the end instant is excluded — together with a `consumption_value` strictly greater than zero, expressed in the account commodity's native unit. The end must fall strictly after the start, else `ERR_INVALID_DATE_RANGE`. Within one account, the half-open periods of `ACTIVE` records may never intersect: two half-open periods overlap whenever each one's start falls strictly before the other's end, and an intersecting upload is rejected with `ERR_USAGE_PERIOD_OVERLAP`. At creation the record's `commodity` is copied from its account, its `kbtu` is computed under the pinned per-record rounding rule of §2.6, and its `status` begins as `ACTIVE` with `void_reason` and `replaces_usage_record_id` null. The upload also recomputes `aggregated_kbtu` and `site_eui` on the building's report for the matching cycle year when that report is in `DRAFT` or `FLAGGED`. Records may be listed filtered by `utility_account_id`, `status`, or `replaces_usage_record_id`.

Corrections happen by voiding. A `UtilityAgent` voids an `ACTIVE` record — a record in any other state yields `ERR_INVALID_STATE_TRANSITION` — supplying a `reason` that is recorded as `void_reason` as the record moves `ACTIVE → VOIDED`. Optionally the void carries an atomic replacement: the caller may include `replacement_period_start`, `replacement_period_end`, and `replacement_consumption_value`, and the three are all-or-nothing — presenting any one or two of them is rejected with `ERR_INVALID_REQUEST`. A replacement's period must satisfy the same end-after-start rule (else `ERR_INVALID_DATE_RANGE`) and the half-open overlap rule against the account's other `ACTIVE` records, with the record being voided excluded from the comparison (else `ERR_USAGE_PERIOD_OVERLAP`). On success the system creates the replacement as a new `ACTIVE` record on the same account, its `replaces_usage_record_id` pointing at the voided record and its own `kbtu` computed per §2.6.

The void then propagates. First, the building's report for each affected cycle year — the voided record's year and, when a replacement period lands in a different year, the replacement's year as well — whatever its status, recomputes `aggregated_kbtu` and `site_eui`; reports in `DRAFT` or `FLAGGED` recompute `data_completeness_pct` as well. Second, when that report is `VERIFIED` or `CERTIFIED`, the post-verification correction check of §3.6 runs, and a delta beyond tolerance drops the report to `FLAGGED` with a fresh anomaly flag. Third, if the affected report is included in a currently `PUBLISHED` disclosure publication, that publication is superseded per §3.9.

### 3.5. Filing the Benchmark Report

The **benchmark report** is the building's filing for one cycle. A `BuildingOwner` creates it with a payload containing the `building_id` and the `cycle_id`. Creation requires the cycle to be `OPEN` — a cycle still in `SCHEDULED` rejects the request with `ERR_CYCLE_NOT_OPEN`, and a `FILING_CLOSED` or `PUBLISHED` cycle rejects creation with `ERR_CYCLE_NOT_OPEN` as well — and requires the building to be on that cycle's covered list, else `ERR_BUILDING_NOT_COVERED`. One building files at most one report per cycle; a second creation for the same pair is refused with `ERR_DUPLICATE_REPORT`. The new report starts in `DRAFT` with `revision_number` zero, `is_late` false, `days_late` zero, and `submitted_at`, `verified_at`, `verified_site_eui`, `target_eui`, both score fields, and `label_grade` all null until the lifecycle reaches them, and the system immediately computes its `aggregated_kbtu`, `site_eui`, and `data_completeness_pct` so the draft reflects the data on hand. Reports may be listed filtered by `building_id`, `cycle_id`, or `status`.

The whole-building aggregation behind `aggregated_kbtu` is worth stating once in full, because every later computation rests on it. The aggregate includes exactly the `ACTIVE` usage records belonging to the building's utility accounts whose half-open period is fully contained in the cycle year: `period_start` on or after midnight of January 1 of the `cycle_year`, and `period_end` on or before midnight of January 1 of the following year. Records that straddle the year boundary are excluded entirely, as are `VOIDED` records. Each included record contributes its already-rounded integer `kbtu`, and `aggregated_kbtu` is their sum. The report's `site_eui` is `aggregated_kbtu` divided by the building's current `gross_floor_area_sqft`, rounded half-up to two decimal places.

The `data_completeness_pct` measures how much of the building's floor area is backed by consent. All of the building's tenant units are summed; whatever floor area remains — the gross area minus the unit total, floored at zero — is owner-controlled common area and always counts. To that, add the `floor_area_sqft` of every unit holding at least one consent grant that is `GRANTED` (with lazy expiry applied), whose `valid_from` falls on or before January 1 of the cycle year, and whose `valid_to` falls on or after December 31 of the cycle year — the window must cover the entire cycle year, closed dates at both ends. The percentage is one hundred times the counted area divided by `gross_floor_area_sqft`, rounded half-up to two decimal places. This ratio is recomputed at report creation, at submission, at verification sign-off, on consent grant and revoke, on tenant-unit floor-area changes, and lazily on report reads when a consent window has newly lapsed against the logical clock; the lazy read-time recompute only ever lowers the stored percentage — a read never raises it.

Submission is the filing act, and it is heavily gated; under the validation order of §2.8 the report's state and the caller's ownership are confirmed first, then the cycle gate, then the safety, constraint, and fiscal gates. The report must be in `DRAFT` or `FLAGGED` (any other state yields `ERR_INVALID_STATE_TRANSITION`), the caller must own the building (`ERR_NOT_RESOURCE_OWNER`), and the cycle must be `OPEN` — a `SCHEDULED` cycle yields `ERR_CYCLE_NOT_OPEN`, while a `FILING_CLOSED` or `PUBLISHED` cycle yields `ERR_FILING_CLOSED`. No anomaly flag with status `OPEN` may exist on the report (`ERR_OPEN_ANOMALIES_EXIST`). The report's `data_completeness_pct` must be at least the cycle's `data_completeness_min_pct` — the threshold is inclusive — or the submission fails with `ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`. Finally, the building owner's `standing` must not be `RESTRICTED` (`ERR_OWNER_RESTRICTED`).

A successful submission recomputes `aggregated_kbtu`, `site_eui`, and `data_completeness_pct` at that moment, sets `submitted_at` to the logical clock, and moves the report to `SUBMITTED`; a resubmission out of `FLAGGED` additionally increments `revision_number` by one. Lateness is then judged against the **effective deadline**: when an `APPROVED` extension request exists for the building and cycle, its `extended_deadline_at` governs; otherwise the cycle's `filing_deadline_at` governs. A submission at or before the effective deadline is on time — lateness uses a strict comparison. The report's `days_late` is the number of whole 86,400-second days by which `submitted_at` passed the effective deadline, never below zero, and `is_late` is true exactly when `days_late` exceeds zero — so a submission inside the first twenty-four hours past the deadline is not late. When `days_late` exceeds zero, the system creates a `FineAssessment` of `fine_type` `LATE_SUBMISSION` in `ASSESSED` status whose `provisional_amount_cents` is the provisional late-fine variant of §3.7, and recomputes the owner's exposure; when `days_late` is zero, no fine is created.

Every successful submission also runs the year-over-year anomaly check. The system locates the building's report in `VERIFIED` or `CERTIFIED` status from the cycle with the largest `cycle_year` strictly earlier than the current cycle's — at most one report exists per building and cycle, so no tie is possible. When such a prior report exists and its `aggregated_kbtu` is greater than zero, the check computes the absolute difference between the current and prior `aggregated_kbtu`, divides it by the prior value, multiplies by one hundred, and rounds half-up to two decimal places. If that delta is strictly greater than the cycle's `anomaly_yoy_threshold_pct` — a delta at exactly the threshold does not flag — and no `CONSUMPTION_SPIKE` flag has ever existed on this report, the system creates an `AnomalyFlag` of `anomaly_type` `CONSUMPTION_SPIKE` in `OPEN` status and the report lands in `FLAGGED` instead of `SUBMITTED`. The submission still succeeds; the response simply shows the report in `FLAGGED`.

### 3.6. Verification, Scoring, and Certification

Once a report is `SUBMITTED`, the owner engages an accredited third party by creating a **verification record** naming the chosen `verifier_id`. The `verifier_id` must name a registered verifier (`ERR_NOT_FOUND`); the verifier's `accredited` flag is not consulted at assignment. At most one record may be `PENDING` per report; a second assignment while one is outstanding is refused with `ERR_VERIFIER_ALREADY_ASSIGNED`. The record begins `PENDING` with `decided_at` and `rejection_reason` null. Records may be listed filtered by `report_id` or `verifier_id`.

The assigned `DataVerifier` — the caller whose `X-User-ID` equals the record's `verifier_id`, else `ERR_NOT_RESOURCE_OWNER` — then signs off or rejects. Sign-off requires the record to be `PENDING` and the report to be `SUBMITTED` (violations yield `ERR_INVALID_STATE_TRANSITION`), and it requires the cycle's `performance_standards` to contain an entry for the building's `property_type`, without which verification cannot proceed and the call fails with `ERR_STANDARD_NOT_DEFINED`. On sign-off the record moves `PENDING → SIGNED_OFF` with `decided_at` stamped, and the report moves `SUBMITTED → VERIFIED`: `verified_at` is set to the logical clock, the aggregates and completeness are recomputed one final time, the report's `verified_site_eui` freezes the then-current `site_eui` as the baseline for all later correction checks, and the scoring pipeline runs.

Scoring produces two variants from the performance-standard entry matching the building's `property_type`. When the report's `data_completeness_pct` is below the eligibility floor of 75 percent, both `score_as_reported` and `score_weather_normalized` are null and `label_grade` is `INSUFFICIENT_DATA`. Otherwise the as-reported raw score is fifty plus the difference between the standard's `median_eui` and the report's `site_eui`, that difference multiplied by the standard's `score_slope`; the raw value is rounded half-up to a whole integer and then clamped into the inclusive range from 1 to 100, yielding `score_as_reported`. The weather-normalized variant first multiplies `site_eui` by the cycle's `weather_adjustment_factor`, rounded half-up to two decimals, then runs the identical pipeline — fifty plus the median-minus-normalized difference times `score_slope`, rounded half-up to an integer, clamped between 1 and 100 — yielding `score_weather_normalized`. The label always follows the as-reported variant: `A` when `score_as_reported` is at least 90, otherwise `B` at 75 or above, otherwise `C` at 50 or above, otherwise `D` at 25 or above, and `E` below that. Both score fields remain null until verification, and the label likewise.

Verification also computes the report's `target_eui`, the performance-standard trajectory target for the cycle. The evaluation order is pinned, because the target may depend on earlier verified reports of the same building but never on the current report itself. First, among this building's reports in `VERIFIED` or `CERTIFIED` belonging to cycles with a strictly earlier `cycle_year`, select the one from the lowest `cycle_year`; if several qualify, break the tie by the reports' `created_at` in ascending order. That report's `verified_site_eui` becomes the baseline and its cycle year the baseline year. When no such earlier report exists, the baseline is the standard's `baseline_eui_default` and the elapsed time is pinned to exactly one year, treating the default baseline as one year back. When an earlier report was found, the elapsed years are the current `cycle_year` minus the baseline year. The target is the baseline multiplied by the annual retention factor — one minus the standard's `annual_reduction_pct` expressed as a fraction of one hundred — raised to the power of the elapsed years, rounded half-up to two decimal places. Only after the target is fixed is the current report's `site_eui` consulted for any shortfall comparison.

That comparison runs at close-filing (§3.1) for each covered building holding a `VERIFIED` or `CERTIFIED` report. If the cycle's `performance_standards` has no entry for the building's `property_type`, the building is skipped and no fine arises. Otherwise the tolerance threshold is the report's `target_eui` inflated by the standard's `shortfall_tolerance_pct` — the target multiplied by one plus the tolerance expressed as a fraction of one hundred, rounded half-up to two decimals **before** any comparison. When the report's currently stored `site_eui` — after any corrections — is strictly greater than that rounded threshold (a value exactly at the threshold incurs no fine), the shortfall percentage is the excess over the threshold divided by `target_eui`, multiplied by one hundred and rounded half-up to two decimals. The fine is the building's `gross_floor_area_sqft` multiplied by the standard's `fine_rate_cents_per_sqft` multiplied by that shortfall percentage, rounded half-up to whole cents, and finally capped at the standard's `performance_fine_cap_cents` — the cap applies last. The resulting amount becomes the `provisional_amount_cents` of a new `PERFORMANCE_SHORTFALL` fine in `ASSESSED` status.

Rejection is the other verification outcome. It requires the record `PENDING` and the caller to be the assigned verifier, and it requires a `rejection_reason` of at least ten characters (`ERR_INVALID_REQUEST`). The record moves `PENDING → REJECTED` with `decided_at` and the reason recorded; the report falls to `FLAGGED`; and an `AnomalyFlag` of `anomaly_type` `VERIFICATION_FAILED` opens.

`VERIFIED` reports culminate in certification. A `ComplianceOfficer` certifies a report only while it is `VERIFIED` and only while the cycle is `OPEN` or `FILING_CLOSED` (both violations yield `ERR_INVALID_STATE_TRANSITION`), moving it `VERIFIED → CERTIFIED`. Segregation of duties applies: the officer whose `X-User-ID` matches the cycle's `created_by_officer_id` may not certify reports in that cycle, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Two further routes lead into `FLAGGED`. A `ComplianceOfficer` may raise a manual review on any report in `SUBMITTED`, `VERIFIED`, or `CERTIFIED` by supplying a `detail`; the report falls to `FLAGGED` and an `AnomalyFlag` of `anomaly_type` `MANUAL_REVIEW` opens with that detail. And the post-verification correction check fires when a usage void (§3.4) recomputes the report of a `VERIFIED` or `CERTIFIED` building: the check divides the absolute difference between the newly recomputed `site_eui` and the frozen `verified_site_eui` by `verified_site_eui`, multiplies by one hundred, and rounds half-up to two decimals, using the rounded stored values on both sides. When the frozen `verified_site_eui` is zero, a recomputed `site_eui` of zero leaves the report untouched while any nonzero value is treated as beyond tolerance. A delta strictly greater than the cycle's `correction_tolerance_pct` — exactly at tolerance does not reopen — moves the report to `FLAGGED` and opens an `AnomalyFlag` of `anomaly_type` `VERIFICATION_REOPENED`. Whenever a report included in a `PUBLISHED` disclosure publication falls to `FLAGGED` through the manual or correction routes, the publication is superseded per §3.9.

An open anomaly is cleared in one of two ways. The owning `BuildingOwner` resolves it with a `resolution_note` of at least twenty characters (`ERR_INVALID_REQUEST`), moving the flag `OPEN → RESOLVED` with the note recorded; resolution applies to an `OPEN` flag on a report in `FLAGGED`. A `ComplianceOfficer` may instead waive it by supplying a `waive_reason` (`ERR_INVALID_REQUEST` when absent), moving the flag `OPEN → WAIVED`. Both `RESOLVED` and `WAIVED` are terminal. Flags may be listed filtered by `report_id` or `status`.

### 3.7. Fines and Owner Standing

Three kinds of **fine assessment** exist, distinguished by `fine_type`: `LATE_SUBMISSION`, created at a late filing; `NON_COMPLIANCE`, created by the close-filing sweep for covered buildings without a verified filing; and `PERFORMANCE_SHORTFALL`, created by that sweep when a verified building misses its trajectory target. Every fine records its `building_id`, `cycle_id`, `assessed_at`, a `provisional_amount_cents` computed at assessment time, and a `final_amount_cents` that stays null while the fine is `ASSESSED`. Fines may be listed filtered by `building_id`, `cycle_id`, `status`, or `fine_type`.

The late fine carries two variants of the same formula. The provisional variant, frozen onto the fine at assessment, measures days from the effective deadline to submission: the fine's `days_late` records the report's uncapped days late at that moment (for `NON_COMPLIANCE` and `PERFORMANCE_SHORTFALL` fines, `days_late` is always zero), and `provisional_amount_cents` is the smaller of `days_late` and the cycle's `late_fine_cap_days`, multiplied by the cycle's `late_fine_daily_rate_cents`. The final variant is computed when the fine is noticed: it measures whole 86,400-second days from the effective deadline to the report's `verified_at` — or, when the report is still unverified at notice time, to the fine's `noticed_at` — never below zero, applies the same day cap, and multiplies by the same daily rate. Because the final variant measures to verification rather than submission, identical inputs produce a larger amount whenever verification lands after submission. For `NON_COMPLIANCE` and `PERFORMANCE_SHORTFALL` fines the provisional amount is the full computed amount, and their final amount simply copies the provisional.

An officer issues notice on an `ASSESSED` fine — any other state yields `ERR_INVALID_STATE_TRANSITION` — which moves it `ASSESSED → NOTICED`, stamps `noticed_at`, computes `final_amount_cents` per the rules above, and recomputes the owner's exposure. Payment belongs to the owning `BuildingOwner` and is exact: the request's `paid_amount_cents` must equal the fine's `final_amount_cents` to the cent, and any deviation fails with `ERR_PAYMENT_AMOUNT_MISMATCH`. A paid fine moves `NOTICED → PAID`, stamps `paid_at`, and recomputes exposure — which may flip the owner's standing back to `NORMAL`. A `ComplianceOfficer` may waive a fine in `ASSESSED` or `NOTICED`, recording a mandatory `waive_reason` (`ERR_INVALID_REQUEST` when absent); a waived fine moves to `WAIVED` and exposure is recomputed. The system itself also waives fines in one circumstance — the extension-approval cascade of §3.8 — recording `AUTO_EXTENSION_APPROVED` as the `waive_reason`. `PAID` and `WAIVED` are terminal.

An owner's **exposure** aggregates across every building they own. The `outstanding_fines_cents` on the owner sums each fine's `final_amount_cents` when the fine is `NOTICED` and its `provisional_amount_cents` when the fine is `ASSESSED`; `PAID` and `WAIVED` fines contribute nothing. Whenever this total is strictly greater than one hundred thousand cents — exactly one thousand dollars, the restriction threshold — the owner's `standing` is `RESTRICTED`; at exactly the threshold the standing stays `NORMAL`, and a total at or below the threshold leaves or returns the owner to `NORMAL`. This recomputation runs on every fine creation, notice, payment, and waiver, including the automatic waivers of the extension cascade. The compliance summary (§3.2) exposes two further reads built from the same inputs: `settled_exposure_cents`, the sum of `final_amount_cents` over `NOTICED` fines, representing what is enforceable now; and `projected_exposure_cents`, the settled amount plus the sum of `provisional_amount_cents` over `ASSESSED` fines, representing the worst case. A `RESTRICTED` owner cannot submit reports, per the fiscal gate of §3.5.

### 3.8. Exemptions and Extensions

An owner who believes a building should escape a cycle's obligations files an **exemption request** under the building, supplying the `cycle_id`, a `request_type` of `EXEMPTION` or `EXTENSION`, and a `reason` of at least ten characters. An `EXEMPTION` asks that the building be excluded from coverage for the cycle; an `EXTENSION` asks that the filing deadline be moved, and then `requested_extension_days` is required and must lie between one and ninety days inclusive — for `EXEMPTION` requests the field, when supplied, is stored on the request but has no effect. Two gates protect filing. At most one request per building and cycle may be open — that is, in `SUBMITTED`, `UNDER_REVIEW`, or `APPEALED` — and a second open request is refused with `ERR_EXEMPTION_REQUEST_OPEN`. And an `EXEMPTION` request may not be filed once a report in `SUBMITTED`, `VERIFIED`, or `CERTIFIED` exists for the building and cycle; such a filing is rejected with `ERR_REPORT_ALREADY_FILED`. A new request begins `SUBMITTED`, with `appeal_used` false and `decision_note` and `extended_deadline_at` null.

Adjudication belongs to the `ComplianceOfficer`. Starting review moves the request `SUBMITTED → UNDER_REVIEW`, and the same action restarts review of an `APPEALED` request; from any other state the attempt fails with `ERR_INVALID_STATE_TRANSITION`. The officer then decides with a `decision` of `APPROVED` or `DENIED` — any other value is rejected with `ERR_INVALID_REQUEST` — and a `decision_note` that is recorded at decision time. One further constraint guards approval of an `EXTENSION`: at most one approved extension may exist per building and cycle, and a duplicate approval fails with `ERR_EXTENSION_ALREADY_GRANTED`.

Approval takes effect immediately. An approved `EXEMPTION` excludes the building from the coverage determination for that cycle, with all the downstream consequences described in §3.2. An approved `EXTENSION` sets the request's `extended_deadline_at` to the cycle's `filing_deadline_at` plus `requested_extension_days` days, and then runs a waiver cascade: every `LATE_SUBMISSION` fine for that building and cycle currently in `ASSESSED` or `NOTICED` moves to `WAIVED` with `waive_reason` recorded as `AUTO_EXTENSION_APPROVED`, after which the owner's exposure is recomputed. The extended deadline becomes the building's effective deadline everywhere lateness is judged.

Denial depends on the appeal history. A first `DENIED` decision — one where `appeal_used` is still false — moves the request `UNDER_REVIEW → DENIED`. The owner may appeal exactly once: the appeal requires the request in `DENIED`, the caller to own the building (`ERR_NOT_RESOURCE_OWNER`), `appeal_used` still false (a second appeal attempt fails with `ERR_INVALID_STATE_TRANSITION`), and an `appeal_note` of at least ten characters (`ERR_INVALID_REQUEST`). A successful appeal moves the request `DENIED → APPEALED` and sets `appeal_used` true, from which the officer restarts review. A `DENIED` decision rendered after the appeal has been used — `appeal_used` true — instead moves the request `UNDER_REVIEW → DENIED_FINAL`. `APPROVED` and `DENIED_FINAL` are terminal. Requests may be listed filtered by `building_id`, `cycle_id`, or `status`.

### 3.9. Public Disclosure

The ordinance's transparency obligation is met through **disclosure publications** on a closed cycle. A `ComplianceOfficer` creates a draft publication for a cycle once filing is closed: the cycle must be `FILING_CLOSED` or `PUBLISHED`, else `ERR_CYCLE_NOT_CLOSED`, and no other `DRAFT` publication may exist for the cycle, else `ERR_DRAFT_PUBLICATION_EXISTS`. The new publication starts in `DRAFT`, and its `publication_version` is one greater than the highest version already existing for the cycle — or 1 for the cycle's first publication. Its `included_report_count` begins at zero, and `published_at` and `superseded_at` stay null.

Publishing is the point of freeze. The officer publishes a `DRAFT` publication — from any other state, `ERR_INVALID_STATE_TRANSITION` — under the same cycle gate of `FILING_CLOSED` or `PUBLISHED` (`ERR_CYCLE_NOT_CLOSED`). The publication moves `DRAFT → PUBLISHED`, stamps `published_at`, and freezes `included_report_count` as the count of the cycle's reports then in `VERIFIED` or `CERTIFIED`. When the cycle was still `FILING_CLOSED`, the same action moves the cycle itself to `PUBLISHED` and sets the cycle's `published_at`; the publication set is published as-reported scores alongside their weather-normalized variants for context. Publishing a draft never itself supersedes an earlier `PUBLISHED` publication for the cycle — only the cascades below do that.

A publication, once published, can be overtaken by events — never directly, only by system cascade. Two triggers supersede it: a report included in the publication falls to `FLAGGED` through the correction cascade of §3.4 and §3.6 or through a manual review flag, or an included `VERIFIED` or `CERTIFIED` report has its scores suppressed and its label forced to `INSUFFICIENT_DATA` by the consent-revocation cascade of §3.3. On either trigger the publication moves `PUBLISHED → SUPERSEDED`, stamps `superseded_at`, and the system immediately creates a replacement publication for the same cycle in `DRAFT` whose `publication_version` is one greater than the superseded version, ready for the officer to review and publish anew. `SUPERSEDED` is terminal. Publications may be listed filtered by `cycle_id` or `status`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new resources to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, updates, decisions, and the clock set — return a `200 OK` status code. The request and response shapes of every operation are governed by the narratives of §3 together with the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/owners` | Register a building owner | ComplianceOfficer |
| GET | `/v1/owners/{id}` | Get an owner (standing, outstanding fines) | Any (any authenticated role) |
| POST | `/v1/verifiers` | Register an accredited data verifier | ComplianceOfficer |
| GET | `/v1/verifiers/{id}` | Get a verifier | Any (any authenticated role) |
| POST | `/v1/reporting-cycles` | Create a reporting cycle with thresholds, fine rates, and performance standards | ComplianceOfficer |
| GET | `/v1/reporting-cycles/{id}` | Get a reporting cycle | Any (any authenticated role) |
| PATCH | `/v1/reporting-cycles/{id}` | Edit cycle configuration while SCHEDULED or OPEN (OCC-guarded) | ComplianceOfficer |
| POST | `/v1/reporting-cycles/{id}/open` | Open a cycle for filings (SCHEDULED → OPEN) | ComplianceOfficer |
| POST | `/v1/reporting-cycles/{id}/close-filing` | Close filing past the deadline; sweep non-compliance and shortfall fines | ComplianceOfficer |
| POST | `/v1/buildings` | Register a building | BuildingOwner, ComplianceOfficer |
| GET | `/v1/buildings/{id}` | Get a building | Any (any authenticated role) |
| GET | `/v1/buildings` | List buildings; `covered_in_cycle_id` yields the covered-building list | Any (any authenticated role) |
| PATCH | `/v1/buildings/{id}` | Update building attributes (OCC-guarded) | BuildingOwner, ComplianceOfficer |
| POST | `/v1/buildings/{id}/archive` | Archive a building (guarded by open fines and reports) | ComplianceOfficer |
| GET | `/v1/buildings/{id}/compliance-summary` | Per-cycle compliance read: coverage, report status, exposure, score, deadline | Any (any authenticated role) |
| POST | `/v1/buildings/{id}/tenant-units` | Add a tenant unit to an owned building | BuildingOwner |
| GET | `/v1/tenant-units` | List tenant units (filterable by building) | Any (any authenticated role) |
| GET | `/v1/tenant-units/{id}` | Get a tenant unit | Any (any authenticated role) |
| PATCH | `/v1/tenant-units/{id}` | Update a unit's floor area or occupancy | BuildingOwner |
| POST | `/v1/tenant-units/{id}/consent-grants` | Request whole-building-aggregation consent for a unit | BuildingOwner |
| POST | `/v1/consent-grants/{id}/grant` | Tenant grants consent with a closed validity window | TenantRep |
| POST | `/v1/consent-grants/{id}/deny` | Tenant denies a consent request | TenantRep |
| POST | `/v1/consent-grants/{id}/revoke` | Tenant revokes a granted consent | TenantRep |
| GET | `/v1/consent-grants` | List consent grants (lazy expiry applied) | Any (any authenticated role) |
| GET | `/v1/consent-grants/{id}` | Get a consent grant (lazy expiry applied) | Any (any authenticated role) |
| POST | `/v1/buildings/{id}/utility-accounts` | Register a utility account on a building | BuildingOwner, ComplianceOfficer |
| GET | `/v1/utility-accounts` | List utility accounts | Any (any authenticated role) |
| GET | `/v1/utility-accounts/{id}` | Get a utility account | Any (any authenticated role) |
| POST | `/v1/utility-accounts/{id}/usage-records` | Upload a usage record; per-record kBtu computed | UtilityAgent |
| POST | `/v1/usage-records/{id}/void` | Void a usage record, optionally with atomic replacement | UtilityAgent |
| GET | `/v1/usage-records` | List usage records | Any (any authenticated role) |
| GET | `/v1/usage-records/{id}` | Get a usage record | Any (any authenticated role) |
| POST | `/v1/benchmark-reports` | Create a DRAFT benchmark report for a covered building and OPEN cycle | BuildingOwner |
| GET | `/v1/benchmark-reports/{id}` | Get a benchmark report | Any (any authenticated role) |
| GET | `/v1/benchmark-reports` | List benchmark reports | Any (any authenticated role) |
| POST | `/v1/benchmark-reports/{id}/submit` | Submit a DRAFT or FLAGGED report; lateness, provisional fine, YoY check | BuildingOwner |
| POST | `/v1/benchmark-reports/{id}/certify` | Certify a VERIFIED report (segregated from cycle creator) | ComplianceOfficer |
| POST | `/v1/benchmark-reports/{id}/verification-records` | Assign a verifier to a SUBMITTED report | BuildingOwner |
| POST | `/v1/verification-records/{id}/sign-off` | Verifier signs off; report becomes VERIFIED and scored | DataVerifier |
| POST | `/v1/verification-records/{id}/reject` | Verifier rejects; report falls to FLAGGED | DataVerifier |
| GET | `/v1/verification-records` | List verification records | Any (any authenticated role) |
| GET | `/v1/verification-records/{id}` | Get a verification record | Any (any authenticated role) |
| POST | `/v1/benchmark-reports/{id}/anomaly-flags` | Officer raises a MANUAL_REVIEW anomaly | ComplianceOfficer |
| GET | `/v1/anomaly-flags` | List anomaly flags | Any (any authenticated role) |
| GET | `/v1/anomaly-flags/{id}` | Get an anomaly flag | Any (any authenticated role) |
| POST | `/v1/anomaly-flags/{id}/resolve` | Owner resolves an OPEN anomaly | BuildingOwner |
| POST | `/v1/anomaly-flags/{id}/waive` | Officer waives an OPEN anomaly | ComplianceOfficer |
| GET | `/v1/fine-assessments` | List fine assessments | Any (any authenticated role) |
| GET | `/v1/fine-assessments/{id}` | Get a fine assessment | Any (any authenticated role) |
| POST | `/v1/fine-assessments/{id}/notice` | Issue notice; compute the final amount | ComplianceOfficer |
| POST | `/v1/fine-assessments/{id}/pay` | Owner pays a NOTICED fine (exact amount) | BuildingOwner |
| POST | `/v1/fine-assessments/{id}/waive` | Officer waives an ASSESSED or NOTICED fine | ComplianceOfficer |
| POST | `/v1/buildings/{id}/exemption-requests` | File an EXEMPTION or EXTENSION request | BuildingOwner |
| GET | `/v1/exemption-requests` | List exemption requests | Any (any authenticated role) |
| GET | `/v1/exemption-requests/{id}` | Get an exemption request | Any (any authenticated role) |
| POST | `/v1/exemption-requests/{id}/start-review` | Officer starts (or restarts) review | ComplianceOfficer |
| POST | `/v1/exemption-requests/{id}/decide` | Officer decides an UNDER_REVIEW request | ComplianceOfficer |
| POST | `/v1/exemption-requests/{id}/appeal` | Owner appeals a DENIED request (once only) | BuildingOwner |
| POST | `/v1/reporting-cycles/{id}/disclosure-publications` | Create a DRAFT disclosure publication for a closed cycle | ComplianceOfficer |
| POST | `/v1/disclosure-publications/{id}/publish` | Publish a DRAFT publication; freeze counts; publish the cycle | ComplianceOfficer |
| GET | `/v1/disclosure-publications` | List disclosure publications | Any (any authenticated role) |
| GET | `/v1/disclosure-publications/{id}` | Get a disclosure publication | Any (any authenticated role) |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock (test-driving) | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is defined in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_FILING_CLOSED` | 409 Conflict |
| `ERR_CYCLE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CYCLE_NOT_EDITABLE` | 409 Conflict |
| `ERR_CYCLE_NOT_CLOSED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OPEN_ANOMALIES_EXIST` | 409 Conflict |
| `ERR_VERIFIER_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_REPORT_ALREADY_FILED` | 409 Conflict |
| `ERR_DATA_COMPLETENESS_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_CONSENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_USAGE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT` | 409 Conflict |
| `ERR_CONSENT_REQUEST_OPEN` | 409 Conflict |
| `ERR_EXEMPTION_REQUEST_OPEN` | 409 Conflict |
| `ERR_EXTENSION_ALREADY_GRANTED` | 409 Conflict |
| `ERR_BUILDING_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_STANDARD_NOT_DEFINED` | 422 Unprocessable Entity |
| `ERR_DRAFT_PUBLICATION_EXISTS` | 409 Conflict |
| `ERR_OPEN_FINES_EXIST` | 409 Conflict |
| `ERR_OPEN_REPORTS_EXIST` | 409 Conflict |
| `ERR_OWNER_RESTRICTED` | 403 Forbidden |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |

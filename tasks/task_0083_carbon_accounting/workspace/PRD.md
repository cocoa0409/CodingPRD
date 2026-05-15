# Carbon Accounting API — Product Requirements Document

## 1. Introduction

Enterprises that disclose their greenhouse-gas (GHG) footprint operate under intense and conflicting pressure: external auditors expect every kilogram of CO2-equivalent to be traceable to a specific activity row, a specific emission factor version, and a specific organizational-boundary decision, while internal teams need the system to keep up with day-to-day changes — a facility is sold, a fuel supplier publishes a better factor, a verifier requests revisions a week before the disclosure deadline. The Carbon Accounting API is the system of record that holds this contract together. It captures organizational boundary choices, identifies emission sources, ingests activity data from meters and invoices, pins emission factors at the moment activity is recorded, computes Scope 1 / 2 / 3 totals under both location-based and market-based methodologies, applies internal-reduction and external-offset credits, and produces multi-standard disclosure reports through a strict draft → review → verified → published workflow.

Because the carbon ledger feeds public disclosures and assurance engagements under standards such as the GHG Protocol, ISO 14064, CDP, TCFD, and local mandatory regimes, this product must enforce four properties that ordinary line-of-business systems often relax. First, segregation of duties — the person who entered a number cannot also be the person who signs it off. Second, double-counting prevention — a carbon credit serial number that has been recognised by one organization cannot be claimed by another. Third, version pinning with full audit history — when a factor library is revised, prior disclosures stay attached to the factor version they were verified against, while in-flight reports are flagged for recomputation. Fourth, comparability across the chosen consolidation approach — equity-share, financial-control, or operational-control — without silently switching denominators behind the user's back.

This document specifies the API contract: the resources the system manages, the lifecycle each resource follows, the calculations the server performs, the validations that protect data integrity, and the role-based authorization model that ties human responsibility to API authority.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` (a non-empty string identifying the caller) and `X-User-Role` (a non-empty role string). A request missing either header, or with either header empty, is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. A request whose role is not authorized for the requested endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403.

Five roles are defined. Their exact spellings are:

- `PlatformAdmin` — operates the platform: creates and updates organizations, adds and adjusts facilities, records boundary changes, cancels reporting periods, and may emit test events or advance the logical clock for integration testing.
- `DataSteward` — handles day-to-day data work: creates and updates emission sources, enters activity data, manages reduction projects, creates reports, compiles them, and reopens reports that need rework.
- `FactorManager` — curates the emission-factor library: creates draft factor versions, approves them into the active library, and retires unused drafts.
- `Verifier` — third-party or internal reviewer: verifies compiled reports or sends them back for revisions.
- `Discloser` — owns the public-facing side: records purchased carbon credits, retires or transfers them, and publishes verified reports.

For all five roles, `identity` is **opaque**: when `X-User-Role` is `PlatformAdmin`, `DataSteward`, `FactorManager`, `Verifier`, or `Discloser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as `entered_by_user_id` on an `ActivityData` row, as `approved_by_user_id` on an approved `EmissionFactor`, as `verifier_user_id` on a verified `Report`, as `recorded_by_user_id` on a `BoundaryChange`, and as `actor_user_id` on every `AuditLog` row) but does not compare it to any entity's `id`. Where business safety requires distinguishing two users (notably segregation of duties on report verification), the comparison is between two `X-User-ID` values previously captured on different rows — never between `X-User-ID` and any entity primary key.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside this range are rejected with `ERR_VALIDATION_FAILED`. `offset` defaults to 0 and must be a non-negative integer. Items are returned in `created_at` ascending order. The response `meta` block carries `limit`, `offset`, `total_count` (the total number of items matching the query before pagination), and `has_more` (true when `offset + returned_count < total_count`).

### 2.4. Common Resource Properties

Every resource has an `id` that is a server-minted UUID, emitted without any type prefix or namespace. Timestamps `created_at` and `updated_at` are ISO 8601 UTC strings with three fractional digits. The `version` field is an integer starting at 1 on creation, and increments by exactly 1 on every server-side mutation (whether the mutation was a direct PATCH, a state-transition POST, or a cascade triggered by a sibling resource's change). Two entities are exceptions to the "full common fields" rule: `BoundaryChange` and `AuditLog` carry only `id` and `created_at` — neither has `updated_at` nor `version`, because both are append-only event records that are never edited after they are written.

### 2.5. Optimistic Concurrency Control

Every mutating endpoint accepts an optional `version` field in the request body (or as a query parameter where the request has no body). When a client supplies `version` and the value does not equal the resource's current `version`, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409 before any business validation runs. When a client omits `version`, the OCC check is skipped and the request proceeds against whatever the current state is. On a successful mutation, the server increments `version` by one and refreshes `updated_at`.

### 2.6. Precision, Rounding, and Decimal Discipline

All emission quantities and money-shaped numbers use deterministic banker-safe rounding: the rounding mode is round half up. Decimal precisions differ by field family because each carries a different physical meaning. Per-record emission output `kg_co2e` is rounded half up to four decimal places. The pinned report totals — `gross_scope1_kg_co2e`, `gross_scope2_location_kg_co2e`, `gross_scope2_market_kg_co2e`, `gross_scope3_kg_co2e`, `applied_offsets_kg_co2e`, `net_emissions_kg_co2e`, `intensity_per_revenue`, `intensity_per_employee`, and `intensity_per_unit_output` — are also rounded half up to four decimal places. The materiality and completeness numbers `materiality_threshold_pct` and `completeness_pct` are rounded half up to two decimal places. Activity-quantity input `quantity` uses four decimal places, factor `kg_per_unit` uses six decimal places, organization `materiality_threshold_pct` and reporting-period `revenue` use two decimal places, facility `ownership_share_pct` uses two decimal places, and reporting-period `unit_output` uses four decimal places. A request whose numeric field violates these precisions is rejected with the field-specific validator (for example, `ERR_DENOMINATOR_INVALID` for `revenue` / `headcount` / `unit_output`, `ERR_MATERIALITY_OUT_OF_RANGE` for `materiality_threshold_pct`) or with the generic `ERR_VALIDATION_FAILED` for fields lacking a dedicated code.

### 2.7. Nested Resource Resolution and Multi-Tenancy Isolation

URLs are resolved left to right. For a path such as the one used to enter activity data — which threads through an organization id, then a reporting-period id, then the activity-data collection — the server first checks the organization exists (returning `ERR_NOT_FOUND` if not), then the reporting period exists and belongs to that organization (again `ERR_NOT_FOUND` if missing), and only then validates the body. In addition to existence, every foreign key embedded in the request body (`facility_id`, `emission_source_id`, `reporting_period_id`, `linked_reduction_project_id`, `emission_factor_id`, etc.) must refer to a row in the same organization as the URL path; a cross-tenant reference is rejected with `ERR_CROSS_ORG_REFERENCE` and HTTP 403.

### 2.8. Validation Priority Order

When more than one validation rule could fire on the same request, they are evaluated in a fixed order so that the most specific cause surfaces. The order is: (1) presence of both auth headers — `ERR_AUTH_REQUIRED`; (2) role authorization — `ERR_FORBIDDEN`; (3) left-to-right path existence — `ERR_NOT_FOUND` for the first missing id; (4) state precondition on the target resource — `ERR_INVALID_STATE`; (5) optimistic-concurrency version match — `ERR_VERSION_CONFLICT`; (6) segregation of duties on report verification — `ERR_SEGREGATION_OF_DUTIES`; (7) carbon-credit double-counting prevention — `ERR_CREDIT_DOUBLE_COUNTED`; (8) factor traceability at compile — `ERR_TRACEABILITY_MISSING`; (9) activity-data window inside reporting period — `ERR_ACTIVITY_OUTSIDE_PERIOD`; (10) per-source activity-interval non-overlap — `ERR_ACTIVITY_INTERVAL_OVERLAP`; (11) per-organization reporting-period non-overlap — `ERR_PERIOD_OVERLAP`; (12) applicable factor exists — `ERR_NO_APPLICABLE_FACTOR`; (13) estimation-basis presence rule — `ERR_ESTIMATION_BASIS_REQUIRED`; (14) facility within boundary — `ERR_FACILITY_OUT_OF_BOUNDARY`; (15) assurance readiness at verify — `ERR_ASSURANCE_NOT_READY`; (16) boundary-change effective-date monotonicity — `ERR_BOUNDARY_CHANGE_ORDER`; (17) factor effective-from monotonicity — `ERR_FACTOR_EFFECTIVE_FROM_ORDER`; (18) materiality threshold within range — `ERR_MATERIALITY_OUT_OF_RANGE`; (19) Scope-3 category match — `ERR_SCOPE3_CATEGORY_MISMATCH`; (20) reporting-period denominator non-negativity — `ERR_DENOMINATOR_INVALID`; (21) multi-tenancy isolation on every embedded reference — `ERR_CROSS_ORG_REFERENCE`. Generic input shape failures that have no dedicated code surface as `ERR_VALIDATION_FAILED`.

### 2.9. Audit Logging

Every mutation that has accounting consequence appends an `AuditLog` row. The audit row captures `actor_user_id` (taken from `X-User-ID`), `actor_role` (taken from `X-User-Role`), `event_type` (one of `ACTIVITY_ENTRY`, `ACTIVITY_ARCHIVE`, `FACTOR_APPROVE`, `FACTOR_SUPERSEDE`, `REPORT_COMPILE`, `REPORT_VERIFY`, `REPORT_PUBLISH`, `BOUNDARY_CHANGE`, `CREDIT_RETIRE`, or `EXTERNAL_SYNC`), `target_entity` (the entity type name), `target_id` (the affected row's id), and `payload_json` (a frozen snapshot of the relevant fields before and after the change). Audit rows are append-only — they have `id` and `created_at` but no `updated_at` or `version` — and are never edited or deleted by any API endpoint.

### 2.10. Cascades, Pinning, and Version Increments

The carbon ledger is built around pinning: at the moment activity data is recorded, the applicable emission factor version is captured on the derived `EmissionRecord` row via `emission_factor_id`, and the gas-type and GWP value used at that instant are likewise captured on the record. When the underlying factor is later revised — the predecessor moving to `SUPERSEDED` — already-pinned `EmissionRecord` rows do not silently change their numbers; instead, the records covered by the supersession flip to `STALE` (their `version` is bumped and `updated_at` refreshed), and any `Report` in `DRAFT` or `UNDER_REVIEW` whose period contains such records moves to `RECOMPUTE_REQUIRED` (its `version` is bumped and `updated_at` refreshed). This three-hop cascade — factor publication, then record staleness, then report recompute flag — guarantees that the auditor can tell the difference between "this number was recomputed because the underlying factor changed" and "this number is the same as it was at compile time".

## 3. Business Logic & Workflows

### 3.1. Organizational Boundary and Facility Inclusion

An organization is created with its `legal_name`, the chosen `consolidation_approach` (`EQUITY_SHARE`, `FINANCIAL_CONTROL`, or `OPERATIONAL_CONTROL`), a `base_year` that must be between 1990 and 2100 inclusive, an ISO-4217 `functional_currency` consisting of exactly three uppercase letters, and an optional `materiality_threshold_pct` that defaults to 1.0 percent and must lie between 0.0 and 5.0 percent inclusive with two decimal places; a value outside that band is rejected with `ERR_MATERIALITY_OUT_OF_RANGE`. The organization profile carries a system-managed `status` that begins at `ACTIVE` and may move to `ARCHIVED`.

Facilities are added under an organization with a `name`, the two-letter uppercase `country_code` (used to choose grid-average factors when the facility consumes purchased energy), the `ownership_share_pct` of equity held (between 0.0 and 100.0 percent inclusive, two decimal places), and two independent boolean flags `financial_control` and `operational_control`. Each facility has a system-managed `status` that defaults to `ACTIVE` and may move to `RETIRED`.

Whether a facility is **in boundary** is computed, not stored as input — the `included_in_boundary` field is derived. The rule depends entirely on the organization's `consolidation_approach`: under `EQUITY_SHARE`, a facility is in boundary when its `ownership_share_pct` is strictly greater than zero — a facility with 0.00 percent share is excluded even if `financial_control` is true; under `FINANCIAL_CONTROL`, inclusion follows the `financial_control` flag and `ownership_share_pct` is ignored; under `OPERATIONAL_CONTROL`, inclusion follows the `operational_control` flag. The boundary resolver is rerun on every facility creation, every facility update, and every boundary-change recording. If the resolver causes a facility to flip from included to excluded, every `EmissionSource` whose `facility_id` points at that facility is automatically moved to `RETIRED` in the same transaction, and every `FRESH` `EmissionRecord` referencing those sources flips to `STALE`, with `updated_at` and `version` refreshed on every affected row.

Boundary changes are recorded as immutable events in the `BoundaryChange` log. Each event captures `organization_id`, a `change_type` of `ADD_FACILITY`, `REMOVE_FACILITY`, `APPROACH_SWITCH`, or `OWNERSHIP_ADJUSTMENT`, the affected `facility_id` (which must be null exactly when `change_type` is `APPROACH_SWITCH`), `from_approach` and `to_approach` (which are set only on approach switches), an `effective_date` in UTC ISO 8601, and a 5-to-1000-character `rationale`. The server fills in the audit fields: `previous_change_id` points at the prior `BoundaryChange` for the same organization (null for the first one) and `recorded_by_user_id` is captured from `X-User-ID`. The new event's `effective_date` must be strictly greater than the latest existing change's `effective_date` for the same organization; a violation is rejected with `ERR_BOUNDARY_CHANGE_ORDER`. Recording a boundary change appends an `AuditLog` row with `event_type` `BOUNDARY_CHANGE`.

### 3.2. Reporting Periods

A reporting period scopes a year-or-shorter window of accounting against the organization. Each period has a `label` (such as "FY2025", 1–50 characters, unique within the organization), a `start_date` and `end_date` interval — interpreted as half-open `[start_date, end_date)` — a `revenue` denominator in the organization's functional currency, an integer `headcount` denominator, and a `unit_output` denominator in whatever physical unit of product the organization uses. `revenue`, `headcount`, and `unit_output` must each be at least zero; `revenue` uses two decimal places, and `unit_output` uses four; a negative value or a wrong-precision value is rejected with `ERR_DENOMINATOR_INVALID`. The status begins at `OPEN` and may move to `CLOSED` or `CANCELLED`.

Two reporting periods of the same organization whose status is anything other than `CANCELLED` must not overlap on their half-open intervals; a violating create or update is rejected with `ERR_PERIOD_OVERLAP`. `end_date` must be strictly greater than `start_date`.

Closing a reporting period is the responsibility of a `DataSteward` (or, equivalently, a `PlatformAdmin`); the close request is rejected with `ERR_INVALID_STATE` if the period is not currently `OPEN` or if the server clock has not yet reached the period's `end_date`. Tests advance the clock via an admin-only test-driving capability that sets the logical now to a supplied `to_timestamp` instant. The completeness check (described in §3.5) is also run at close — if completeness falls below the materiality-derived threshold, the close still proceeds but the period transitions with the completeness numbers recorded for downstream reporting. Closing a period mass-archives every `ActivityData` row whose `reporting_period_id` matches (status `RECORDED` becomes `ARCHIVED`), then mass-archives every `EmissionRecord` of the period (both `FRESH` and `STALE` become `ARCHIVED`), and finally auto-transitions any `Report` still in `DRAFT` or `UNDER_REVIEW` for that period to `REVISIONS_REQUIRED`. An `AuditLog` row with `event_type` `ACTIVITY_ARCHIVE` is appended. Cancellation of a period is restricted to `PlatformAdmin`: the period must be `OPEN`, no `PUBLISHED` `Report` may reference it, and on success the activity-data and emission-record rows of the period are mass-archived in the same way.

### 3.3. Emission Source Inventory

An emission source is the persistent definition of a place where greenhouse gases are emitted (a diesel generator, a grid connection, a fugitive coolant loop, a tier-1 supplier's manufacturing footprint, and so on). Each source is created with a `facility_id` referring to a facility of the same organization, a `code` that is 1–50 characters from the set `[A-Z0-9_-]` and unique within the organization, a `category` from the GHG-Protocol set `STATIONARY_COMBUSTION`, `MOBILE_COMBUSTION`, `PROCESS`, `FUGITIVE`, `PURCHASED_ENERGY`, or `VALUE_CHAIN`, a `gas_type` from `CO2`, `CH4`, `N2O`, `HFC`, `PFC`, `SF6`, or `NF3`, and a `factor_code` that points at an emission-factor family the source resolves to at activity-entry time. The factor family must belong to the same organization and its `gas_type` must equal the source's `gas_type`.

`scope` is derived, not entered. The mapping is fixed: a source whose `category` is `STATIONARY_COMBUSTION`, `MOBILE_COMBUSTION`, `PROCESS`, or `FUGITIVE` is `SCOPE_1`; a source whose `category` is `PURCHASED_ENERGY` is `SCOPE_2`; a source whose `category` is `VALUE_CHAIN` is `SCOPE_3`. For value-chain sources, `scope3_category` carries the GHG-Protocol Scope-3 category number from 1 through 15 inclusive. The rule is paired: `scope3_category` must be provided when `category` is `VALUE_CHAIN` and must be null otherwise; a value-chain source without a category number, a non-value-chain source carrying one, or a value-chain source whose number falls outside 1..15 is rejected with `ERR_SCOPE3_CATEGORY_MISMATCH`.

At creation, the source's facility must satisfy `included_in_boundary` equal to true and `status` equal to `ACTIVE`; otherwise the request is rejected with `ERR_FACILITY_OUT_OF_BOUNDARY`. The source itself has a system-managed `status` that defaults to `ACTIVE` and may move to `RETIRED` (either explicitly via update or implicitly via the boundary-resolver cascade described in §3.1).

### 3.4. Emission Factor Lifecycle

An emission factor converts a quantity of activity (litres of fuel, kWh of electricity, tonne-kilometres of freight) into a mass of a specific greenhouse gas. The library is versioned. Each entry has a `code` that groups versions of the same factor, a `version` integer that is server-assigned starting at 1 and increases strictly per code, a `library` of `IPCC_DEFAULT`, `NATIONAL_PUBLISHED`, `SUPPLIER_SPECIFIC`, or `MEASURED`, a `gas_type` from the same gas enumeration as sources, a `kg_per_unit` value (non-negative, six decimal places), an `uncertainty_rating` of `LOW`, `MEDIUM`, or `HIGH`, an `effective_from` instant, and a `traceability_url` of 1–500 characters that points at the citation. For purchased-energy factors the `scope2_method` distinguishes `LOCATION_BASED` (grid-average) from `MARKET_BASED` (contractual instruments); `scope2_method` must be null for any factor that does not serve a purchased-energy source.

A factor begins in `DRAFT`. A `FactorManager` may either approve it, moving it to `ACTIVE` and triggering the supersession cascade below, or delete it, moving it to `RETIRED`. The delete-to-retire path is permitted only when no `EmissionRecord` references the factor; otherwise it is rejected with `ERR_INVALID_STATE`.

Approval is the central event in factor management. The new version's `effective_from` must be strictly greater than the predecessor `ACTIVE` version's `effective_from` for the same `code` — zero-length windows and reverse-time approvals are rejected with `ERR_FACTOR_EFFECTIVE_FROM_ORDER`. The approving user's id is captured on `approved_by_user_id`. On a successful approval, the predecessor (if any) transitions from `ACTIVE` to `SUPERSEDED` and its `effective_to` is set equal to the new version's `effective_from` (the chain is half-open and adjacency-allowed). Every `EmissionRecord` whose `emission_factor_id` equals the now-superseded row and whose parent `ReportingPeriod` is `OPEN` flips from `FRESH` to `STALE`. Every `Report` whose `status` is `DRAFT` or `UNDER_REVIEW` and whose `reporting_period_id` lies among the affected periods flips to `RECOMPUTE_REQUIRED`. In each cascade hop `updated_at` is refreshed and `version` is incremented on every touched row. Two `AuditLog` rows are appended: `FACTOR_APPROVE` for the newly active row, and `FACTOR_SUPERSEDE` for the predecessor.

When two `FactorManager`s race to approve two `DRAFT` versions for the same `code` at the same time, approvals serialize on the `code`: at most one transition from `DRAFT` to `ACTIVE` succeeds, and the loser sees a freshly superseded predecessor — the loser receives `ERR_FACTOR_VERSION_CONFLICT` and HTTP 409.

### 3.5. Activity Data Entry, Pinning, and Per-Record Calculation

Entering activity data is how raw consumption (a fuel-delivery invoice, a metered electricity reading, an estimated supplier emission figure) becomes a quantified contribution to the ledger. A `DataSteward` posts an activity record into the activity-data collection of a `reporting_period_id` that must be currently `OPEN`. The payload carries an `emission_source_id`, a `data_source` classification of `METER_READING`, `INVOICE`, `SUPPLIER_DATA`, or `ESTIMATION`, a non-negative `quantity` (four decimal places) in the source's `unit` (1–20 characters), an `activity_start` and `activity_end` window in UTC, and an optional `estimation_basis` free-text explanation of 5–500 characters.

The `data_quality_score` is derived from `data_source`: `METER_READING` scores 1.00, `INVOICE` scores 0.80, `SUPPLIER_DATA` scores 0.65, and `ESTIMATION` scores 0.40. The `entered_by_user_id` is captured from `X-User-ID`. The status defaults to `RECORDED` and may later move to `ARCHIVED` when the period closes. The estimation-basis rule is symmetric: when `data_source` is `ESTIMATION`, `estimation_basis` must be a non-null 5-to-500-character string; when `data_source` is anything else, `estimation_basis` must be null. A violation in either direction is rejected with `ERR_ESTIMATION_BASIS_REQUIRED`.

Temporal validity requires `activity_end` to be strictly greater than `activity_start`, with both lying inside the parent reporting period's half-open `[start_date, end_date)` interval — equivalently, `start_date` ≤ `activity_start` and `activity_end` ≤ `end_date`; a window outside the period or with a non-positive duration is rejected with `ERR_ACTIVITY_OUTSIDE_PERIOD`. The activity window is also checked for overlap against any prior activity row for the same `emission_source_id`: two activity rows of the same source must not overlap on their half-open intervals `[activity_start, activity_end)`, and a second writer is rejected with `ERR_ACTIVITY_INTERVAL_OVERLAP`. At entry time the source's facility must still satisfy `included_in_boundary` equal to true and `status` equal to `ACTIVE`; otherwise the request is rejected with `ERR_FACILITY_OUT_OF_BOUNDARY`.

The factor is then **pinned**: the server picks the `EmissionFactor` whose `code` equals the source's `factor_code`, whose `status` is `ACTIVE`, whose `effective_from` is less than or equal to `activity_start`, and whose `effective_to` is either null or strictly greater than `activity_start`. If no such factor exists, the request is rejected with `ERR_NO_APPLICABLE_FACTOR`. Otherwise the server records the pinning result on a new `EmissionRecord` row: `emission_factor_id` is the pinned factor's id, `gas_type` is copied from the source's `gas_type`, `gwp_factor` is the GWP-100 value for that gas (CO2 = 1, CH4 = 28, N2O = 265, HFC = 1430, PFC = 7390, SF6 = 23500, NF3 = 16100), and for purchased-energy sources `scope2_method` is copied from the factor's `scope2_method` (null for `SCOPE_1` and `SCOPE_3` records).

The contribution in kg CO2-equivalent is then computed: `kg_co2e` is the `quantity` from the activity row multiplied by the pinned factor's `kg_per_unit` multiplied by the GWP value, with the final result rounded half up to four decimal places. The `reporting_period_id` and `activity_data_id` on the record point back at the entries that produced it. The record's `status` defaults to `FRESH`. An `AuditLog` row with `event_type` `ACTIVITY_ENTRY` is appended.

### 3.6. Reduction Projects and Carbon Credits

A reduction project represents either an internal effort to cut emissions or an external offset purchase. Each project is created with a `name` (1–200 characters), a `project_type` of `INTERNAL_REDUCTION` or `EXTERNAL_OFFSET`, a `reduction_kg_co2e` value (non-negative, four decimal places) representing the expected or realised reduction attributable to the project for its linked `reporting_period_id`, and — for internal-reduction projects only — a `facility_id` that names the facility whose emissions the project reduces. The `facility_id` must be supplied when `project_type` is `INTERNAL_REDUCTION` and must be null otherwise. The project status begins at `PLANNED`.

A `DataSteward` advances a project through its lifecycle. Activation moves it from `PLANNED` to `ACTIVE` and requires the parent reporting period to be `OPEN`. Completion moves it from `ACTIVE` to `COMPLETED`; the parent reporting period must be `OPEN` or `CLOSED`, and for external-offset projects every linked `CarbonCredit` must have status `RETIRED` before completion is allowed. On completion, the applied-offsets value of any `DRAFT` or `UNDER_REVIEW` `Report` on the same period is recomputed and `updated_at` and `version` are refreshed. Cancellation is available from either `PLANNED` or `ACTIVE`, provided no `CarbonCredit` with status `RETIRED` references the project.

A carbon credit row records a purchased external offset. The payload carries a `registry` of `VCS`, `GOLD_STANDARD`, or `CCER`, a `serial_number` (1–100 characters) that is **globally unique across every `CarbonCredit` row of every organization** — a duplicate is rejected with `ERR_CREDIT_DOUBLE_COUNTED`, even across tenants — a `vintage_year` between 1990 and the year of the parent reporting period's `end_date` inclusive, a `quantity_kg_co2e` strictly greater than zero (four decimal places), a `linked_reduction_project_id` whose project must have `project_type` equal to `EXTERNAL_OFFSET`, and a `reporting_period_id` against which the credit is applied. The status begins at `PURCHASED`.

A `Discloser` retires a credit by transitioning it from `PURCHASED` to `RETIRED` and supplying a `retirement_certificate_url` of 1–500 characters; the linked reduction project must be in `ACTIVE` status, the credit's `vintage_year` must not exceed the year of the parent period's `end_date`, and the credit must currently be `PURCHASED` — otherwise the call is rejected with `ERR_INVALID_STATE`. On a successful retire, `retired_at` is set to the current server time, and any `DRAFT` or `UNDER_REVIEW` `Report` on the parent reporting period has its `applied_offsets_kg_co2e` and `net_emissions_kg_co2e` recomputed (with `updated_at` refreshed and `version` bumped on the touched report). An `AuditLog` row with `event_type` `CREDIT_RETIRE` is appended. Two simultaneous retirements of the same credit serialize on `CarbonCredit.status`: exactly one succeeds, and the loser is rejected with `ERR_INVALID_STATE` and HTTP 409. Two attempts to create credits with the same `serial_number` from different organizations serialize on the global `serial_number` constraint: the second creator is rejected with `ERR_CREDIT_DOUBLE_COUNTED`. Alternatively, a `Discloser` may transfer a credit out, moving it from `PURCHASED` to `TRANSFERRED`; transfer is only allowed when the parent reporting period is `OPEN`.

### 3.7. Report Compilation, Verification, and Publication

A report is the disclosure artifact. A `DataSteward` creates a report by naming the `reporting_period_id` the report covers and the `standard` template to use — one of `GHG_PROTOCOL`, `ISO_14064`, `CDP`, `TCFD`, or `LOCAL_MANDATORY`. The report begins in `DRAFT`.

**Compilation** advances the report from `DRAFT` to `UNDER_REVIEW` and **pins** every aggregated total on the report row. Compilation requires the parent reporting period to be `OPEN` or `CLOSED` and requires that no `EmissionRecord` for the period is in `STALE` status; either violation is rejected with `ERR_INVALID_STATE`. In addition, every `FRESH` `EmissionRecord` of the period must reference an `EmissionFactor` whose `status` is `ACTIVE` or `SUPERSEDED` and whose `traceability_url` is non-empty; a record whose factor lacks traceability blocks compile with `ERR_TRACEABILITY_MISSING`. The compiled-at timestamp is set to the current server time.

The gross subtotals are computed as follows. The inclusion set consists of every `EmissionRecord` whose `reporting_period_id` matches the report's, whose `status` is `FRESH`, and whose source's facility satisfies `included_in_boundary` equal to true. Each record contributes its `kg_co2e` multiplied by a per-facility consolidation weight. The weight depends on `consolidation_approach`: under `EQUITY_SHARE`, the weight is the facility's `ownership_share_pct` divided by 100; under `FINANCIAL_CONTROL`, the weight is 1 when the facility's `financial_control` flag is true and 0 otherwise; under `OPERATIONAL_CONTROL`, the weight is 1 when the facility's `operational_control` flag is true and 0 otherwise. For identical facility rows, switching the approach can flip `included_in_boundary` from true to false and produce a strictly different scope-1 total. The four gross subtotals are computed by accumulating contributions per facility-scope combination, rounding each per-facility-scope subtotal half up to four decimal places, then summing the rounded subtotals — explicitly not round-once-at-end. `gross_scope1_kg_co2e` is the sum across all `SCOPE_1` records, `gross_scope2_location_kg_co2e` is the sum across `SCOPE_2` records whose `scope2_method` is `LOCATION_BASED`, `gross_scope2_market_kg_co2e` is the sum across `SCOPE_2` records whose `scope2_method` is `MARKET_BASED`, and `gross_scope3_kg_co2e` is the sum across all `SCOPE_3` records. Because location-based and market-based Scope-2 read against different factor families (grid-average versus contractual instruments), the two scope-2 subtotals can differ strictly for identical underlying activity data — the report carries both.

The applied offsets are the sum of `quantity_kg_co2e` for every `CarbonCredit` whose status is `RETIRED` and whose `reporting_period_id` matches, plus the sum of `reduction_kg_co2e` for every `ReductionProject` whose status is `COMPLETED`, whose `project_type` is `INTERNAL_REDUCTION`, and whose `reporting_period_id` matches; the total is rounded half up to four decimal places and stored as `applied_offsets_kg_co2e`.

`net_emissions_kg_co2e` is the canonical net figure used for disclosure dashboards and intensity indicators. It is computed as `gross_scope1_kg_co2e` plus `gross_scope2_market_kg_co2e` (market-based is canonical under the GHG-Protocol Scope-2 Guidance) plus `gross_scope3_kg_co2e` minus `applied_offsets_kg_co2e`, with the result rounded half up to four decimal places and floored at zero — negative nets are not exposed, the floor takes the larger of the rounded difference and 0.0.

The three intensity indicators each divide `net_emissions_kg_co2e` by a denominator from the reporting period: `intensity_per_revenue` divides by `revenue`, `intensity_per_employee` divides by `headcount`, and `intensity_per_unit_output` divides by `unit_output`. Each denominator is independently checked for zero: when `revenue` is zero, `intensity_per_revenue` is recorded as 0; when `headcount` is zero, `intensity_per_employee` is recorded as 0; when `unit_output` is zero, `intensity_per_unit_output` is recorded as 0. Each non-zero quotient is rounded half up to four decimal places.

The completeness check is run at compile (and also at period close). The identified-source count is the number of `ACTIVE` `EmissionSource` rows of the organization whose facility satisfies `included_in_boundary` equal to true. The covered-source count is the number of distinct emission sources referenced by at least one `FRESH` `EmissionRecord` in the period. When the identified count is zero, `completeness_pct` is recorded as 0.00; otherwise it is 100 multiplied by the covered count divided by the identified count, rounded half up to two decimal places. The pass threshold is 100 minus the organization's `materiality_threshold_pct`, also rounded half up to two decimal places; `completeness_passes` is true when `completeness_pct` is greater than or equal to the threshold (the comparison is inclusive — `>=`, not strict `>`). `assurance_ready` is true when `completeness_passes` is true, no `EmissionRecord` of the period is in `STALE` status, and the parent reporting period's `status` is `OPEN` or `CLOSED`. An `AuditLog` row with `event_type` `REPORT_COMPILE` is appended.

**Verification** advances the report from `UNDER_REVIEW` to `VERIFIED`. A `Verifier` performs this transition; the report must be in `UNDER_REVIEW` and its `assurance_ready` must be true — otherwise the call is rejected with `ERR_ASSURANCE_NOT_READY`. Segregation of duties is strictly enforced here: the verifying user's `X-User-ID` must not equal the `entered_by_user_id` of any `ActivityData` row whose `reporting_period_id` matches the report's reporting period — i.e., a person who entered any activity data for the period cannot verify the report that consumes it. A violation surfaces as `ERR_SEGREGATION_OF_DUTIES` with HTTP 403. On a successful verify, `verified_at` is set to the current server time and `verifier_user_id` is captured from `X-User-ID`. An `AuditLog` row with `event_type` `REPORT_VERIFY` is appended.

A verifier who finds the report unsatisfactory may instead send it back, moving it from `UNDER_REVIEW` to `REVISIONS_REQUIRED`. From `REVISIONS_REQUIRED`, a `DataSteward` reopens it back to `DRAFT`, at which point `compiled_at` is cleared to null and every pinned total is reset to null. The same reopen handles the parallel case where the report has been auto-flipped to `RECOMPUTE_REQUIRED` by a factor supersession cascade; the same clear-and-reset side effect applies. A report in `DRAFT` that has had a pinned factor superseded transitions to `RECOMPUTE_REQUIRED` via the cascade; similarly a report in `UNDER_REVIEW` transitions to `RECOMPUTE_REQUIRED` via the cascade.

When a verifier attempts to verify a report at the same moment the cascade is flipping it to `RECOMPUTE_REQUIRED`, the two operations serialize on `Report.version`. If the cascade wins, the verify call is rejected with `ERR_INVALID_STATE` and HTTP 409 because the report is no longer in `UNDER_REVIEW`. If the verify wins, the cascade attempt is rejected with `ERR_INVALID_STATE` because it observes a version conflict on the report row.

**Publication** advances the report from `VERIFIED` to `PUBLISHED`. A `Discloser` performs this transition; the report must be in `VERIFIED`, and every external-offset credit that has been booked against the report's reporting period must be fully retired — no purchased credit may remain in `PURCHASED` status. A violation is rejected with `ERR_INVALID_STATE`. On success, `published_at` is set to the current server time and an `AuditLog` row with `event_type` `REPORT_PUBLISH` is appended.

The report exposes a dual-scope-2 readout that returns three numbers — `net_with_location_scope2` (computed by substituting `gross_scope2_location_kg_co2e` for the market-based subtotal in the canonical net formula), `net_with_market_scope2` (the canonical net), and `delta_kg_co2e` (the location-based net minus the market-based net) — for compliance teams that need both views. For identical underlying activity data the two nets are typically different.

### 3.8. External Integration and Test Harness

The platform exposes two operator-only capabilities to support deterministic testing. An admin-only test-driving capability advances the logical clock to a supplied `to_timestamp` instant; this is used to age out a reporting period so that closing it becomes legal. A second admin-only capability emits an external sync event from a named `source_system` (for example, an ERP, an energy-metering platform, a supplier-data exchange, or a carbon-market registry) with a free-form `payload`; on receipt the server appends an `AuditLog` row with `event_type` `EXTERNAL_SYNC` capturing the actor and payload. Neither capability mutates business state directly; both exist to drive the cross-cutting flows above.

## 4. Endpoint Definitions

All endpoints sit under the `/organizations` mount. New resources are created with HTTP 201; modifications, state transitions, and reads return HTTP 200; the DELETE that retires an unused draft factor returns HTTP 204. Request and response payloads, side-effects, and validation triggers are described in §3; this table is a directory only — re-read §3 to reconstruct each endpoint's body.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /organizations | Create organization profile. | PlatformAdmin |
| GET | /organizations/{org_id} | Read organization profile. | PlatformAdmin, DataSteward, FactorManager, Verifier, Discloser |
| PATCH | /organizations/{org_id} | Update consolidation approach, materiality threshold, or other mutable fields. | PlatformAdmin |
| POST | /organizations/{org_id}/facilities | Add facility to organization. | PlatformAdmin |
| PATCH | /organizations/{org_id}/facilities/{id} | Adjust ownership share or control flags. | PlatformAdmin |
| GET | /organizations/{org_id}/facilities | List facilities. | PlatformAdmin, DataSteward, FactorManager, Verifier, Discloser |
| POST | /organizations/{org_id}/boundary-changes | Record a boundary change. | PlatformAdmin |
| GET | /organizations/{org_id}/boundary-changes | List boundary-change history. | PlatformAdmin, DataSteward, Verifier, Discloser |
| POST | /organizations/{org_id}/reporting-periods | Create reporting period. | DataSteward, PlatformAdmin |
| PATCH | /organizations/{org_id}/reporting-periods/{id} | Update denominator fields on an OPEN period. | DataSteward, PlatformAdmin |
| POST | /organizations/{org_id}/reporting-periods/{id}/close | Close a reporting period. | DataSteward, PlatformAdmin |
| POST | /organizations/{org_id}/reporting-periods/{id}/cancel | Cancel a reporting period. | PlatformAdmin |
| POST | /organizations/{org_id}/sources | Create emission source. | DataSteward |
| PATCH | /organizations/{org_id}/sources/{id} | Update mutable fields of a source. | DataSteward |
| GET | /organizations/{org_id}/sources | List sources. | DataSteward, FactorManager, Verifier, Discloser |
| POST | /organizations/{org_id}/factors | Create a DRAFT factor version. | FactorManager |
| POST | /organizations/{org_id}/factors/{id}/approve | Approve a DRAFT factor and cascade. | FactorManager |
| DELETE | /organizations/{org_id}/factors/{id} | Retire an unused DRAFT factor. | FactorManager |
| GET | /organizations/{org_id}/factors | List factors by code with version history. | FactorManager, DataSteward, Verifier |
| POST | /organizations/{org_id}/reporting-periods/{period_id}/activity-data | Enter activity data; emission record is computed in the same transaction. | DataSteward |
| GET | /organizations/{org_id}/reporting-periods/{period_id}/activity-data | List activity-data rows. | DataSteward, Verifier |
| GET | /organizations/{org_id}/reporting-periods/{period_id}/emission-records | List computed emission records. | DataSteward, Verifier, Discloser |
| POST | /organizations/{org_id}/projects | Create reduction project. | DataSteward |
| POST | /organizations/{org_id}/projects/{id}/activate | Activate a PLANNED project. | DataSteward |
| POST | /organizations/{org_id}/projects/{id}/complete | Complete an ACTIVE project. | DataSteward |
| POST | /organizations/{org_id}/projects/{id}/cancel | Cancel a PLANNED or ACTIVE project. | DataSteward |
| POST | /organizations/{org_id}/credits | Record an external carbon credit purchase. | Discloser |
| POST | /organizations/{org_id}/credits/{id}/retire | Retire a credit. | Discloser |
| POST | /organizations/{org_id}/credits/{id}/transfer | Transfer a credit out. | Discloser |
| POST | /organizations/{org_id}/reports | Create a Report for a reporting period. | DataSteward |
| POST | /organizations/{org_id}/reports/{id}/compile | Compile DRAFT to UNDER_REVIEW and pin totals. | DataSteward |
| POST | /organizations/{org_id}/reports/{id}/verify | Verify UNDER_REVIEW to VERIFIED. | Verifier |
| POST | /organizations/{org_id}/reports/{id}/request-revisions | Send UNDER_REVIEW back to REVISIONS_REQUIRED. | Verifier |
| POST | /organizations/{org_id}/reports/{id}/reopen | Reopen REVISIONS_REQUIRED or RECOMPUTE_REQUIRED back to DRAFT. | DataSteward |
| POST | /organizations/{org_id}/reports/{id}/publish | Publish VERIFIED to PUBLISHED. | Discloser |
| GET | /organizations/{org_id}/reports/{id} | Read report including pinned totals. | DataSteward, FactorManager, Verifier, Discloser |
| GET | /organizations/{org_id}/reports/{id}/dual-scope2 | Return location-based and market-based net emissions side by side. | DataSteward, Verifier, Discloser |
| GET | /organizations/{org_id}/audit-log | List audit-log events. | PlatformAdmin, Verifier |
| POST | /_events/emit | Test-only: emit an external sync event. | PlatformAdmin |
| POST | /_clock/advance | Test-only: advance the server clock. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CREDIT_DOUBLE_COUNTED | 409 |
| ERR_TRACEABILITY_MISSING | 422 |
| ERR_ACTIVITY_OUTSIDE_PERIOD | 422 |
| ERR_ACTIVITY_INTERVAL_OVERLAP | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_NO_APPLICABLE_FACTOR | 422 |
| ERR_ESTIMATION_BASIS_REQUIRED | 422 |
| ERR_FACILITY_OUT_OF_BOUNDARY | 422 |
| ERR_ASSURANCE_NOT_READY | 422 |
| ERR_BOUNDARY_CHANGE_ORDER | 422 |
| ERR_FACTOR_EFFECTIVE_FROM_ORDER | 422 |
| ERR_MATERIALITY_OUT_OF_RANGE | 422 |
| ERR_SCOPE3_CATEGORY_MISMATCH | 422 |
| ERR_DENOMINATOR_INVALID | 422 |
| ERR_CROSS_ORG_REFERENCE | 403 |
| ERR_FACTOR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION_FAILED | 422 |

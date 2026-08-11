# Group Home & IDD Residential Waiver API — Product Requirements Document

## 1. Introduction

This document specifies the behavior of a residential waiver management platform serving provider agencies that operate group homes for individuals with intellectual and developmental disabilities (IDD) under Home and Community-Based Services (HCBS) waiver programs. The system coordinates the full operational arc of residential services: admitting an individual, authoring and maintaining the person-centered Individual Service Plan (ISP), allocating waiver-funded service authorizations and their finite units, scheduling and verifying direct-support staffing, recording medication administration and behavior-support oversight, logging and escalating incidents, coordinating day-program transport, and producing and reconciling Medicaid billing claims.

The platform must satisfy two sometimes-competing demands. On the one hand, it is an operational system: case managers draft plans, QIDPs approve them, DSPs deliver care and record evidence of delivery, agency administrators schedule staff and vehicles, and billing specialists reconcile remittances. On the other hand, it is a compliance-and-audit system: every action must be attributable to a role and, where roles are entity-backed, to a specific staff member; every state transition must respect segregation-of-duties boundaries; every dollar claimed must trace back to verified service delivery that itself traces back to an authorization with remaining units; and the compliance posture of a home must gate downstream activity in real time.

A distinguishing feature of the domain is the density of cross-entity cascades. A single incident submission can propagate from an incident, to a home's compliance posture, to a hold on outstanding draft claims for every resident of that home, to a recomputed agency ledger counter. A single ISP expiration can cascade into suspended service authorizations, which in turn reject pending and exception EVV visits. The design treats these cascades as first-class, observable side effects rather than implicit implementation details, and every rule that governs them is stated explicitly in this document.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); an unrecognized role name in `X-User-Role` is rejected with the same error. If the role named in `X-User-Role` is not permitted for the endpoint per the role matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven role names with exact spelling: `AgencyAdmin`, `CaseManager`, `QIDP`, `DSP`, `BillingSpecialist`, `ComplianceOfficer`, and `Any`. The `Any` role denotes that any authenticated caller (any of the six preceding roles) may perform the operation — in practice, all GET endpoints.

Three of the roles are **entity-backed**, meaning `X-User-ID` resolves to a persisted `StaffMember` record. When `X-User-Role` is `CaseManager`, `QIDP`, or `DSP`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`. The system additionally requires that the resolved `StaffMember` exist, be in `ACTIVE` status, and have a `staff_role` matching the value carried by `X-User-Role`; failure of any of these — including an `X-User-ID` that resolves to no `StaffMember` at all — is rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403), never with `ERR_NOT_FOUND`.

The remaining roles are **opaque**: when `X-User-Role` is `AgencyAdmin`, `BillingSpecialist`, `ComplianceOfficer`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` on a `BillingClaim` where the claim submission writes it) but does not compare it to any entity's `id`.

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
- An unexpected server failure is rendered in the same envelope with `error_id` `ERR_INTERNAL` and HTTP status 500.

### 2.3. Pagination

All list endpoints accept the query parameters `limit` and `offset`. The default value of `limit` is 10, the minimum permitted value is 1, and the maximum permitted value is 100. The default value of `offset` is 0, and the minimum permitted value is 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses always sort by `created_at` in ascending order, with ties on `created_at` broken by creation (insertion) order. List responses populate the `meta` block with the fields `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through a result set; `total_count` counts the full filtered result set, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

Each list endpoint additionally accepts optional exact-match query parameters on the resource's own stored fields; a record is included only when every supplied filter equals the record's field. The supported filter fields per endpoint are: `/homes` — `agency_id`, `status`; `/individuals` — `agency_id`, `status`, `mobility_level`; `/isps` — `individual_id`, `status`, `authored_by_staff_id`, `approved_by_staff_id`; `/authorizations` — `individual_id`, `isp_id`, `service_code`, `status`; `/staff` — `agency_id`, `staff_role`, `status`; `/shifts` — `home_id`, `staff_member_id`, `status`; `/bed-assignments` — `home_id`, `bed_label`, `individual_id`, `status`; `/medication-orders` — `individual_id`, `status`; `/admin-events` — `medication_order_id`, `administered_by_staff_id`, `witness_staff_id`, `outcome`; `/behavior-plans` — `individual_id`, `status`, `level`, `authored_by_staff_id`, `approved_by_staff_id`; `/incidents` — `individual_id`, `home_id`, `severity`, `status`, `submitted_by_staff_id`; `/evv-visits` — `individual_id`, `authorization_id`, `staff_member_id`, `shift_id`, `verification_status`, `billing_status`, `billed_claim_id`; `/transport-trips` — `home_id`, `vehicle_id`, `trip_date`, `status`; `/claims` — `individual_id`, `status`. Query parameters outside this set are ignored.

### 2.4. Common Resource Properties

Every entity in the system, with one exception noted below, carries the following common fields: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix, serialized in the canonical dashed 8-4-4-4-12 hexadecimal form (for example, `3f6b0e3a-1c2d-4e5f-8a9b-0c1d2e3f4a5b`). The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits. Every other timestamp the server writes into a response — server-stamped fields such as `enrolled_at`, `activated_at`, `approved_at`, and `submitted_at`, server-computed fields such as `report_due_at`, `review_due_at`, and the medication-adherence read's `window_start` and `window_end`, and the clock endpoint's `current_utc` echo — is rendered in that same ISO 8601 UTC format with exactly three fractional digits and a `Z` suffix (for example, `2026-06-03T08:30:00.000Z`). The `version` is a non-negative integer that starts at exactly 1 on creation and increments by exactly 1 on every successful mutation of the resource; clients treat `version` as opaque and never write to it directly.

The single exception is `MedAdminEvent`, which is an append-only Medication Administration Record event. It carries only `id` and `created_at`; both `updated_at` and `version` are absent, and the record is immutable once written.

Many entities also carry a `status` field whose value is an enum drawn from the entity's lifecycle; the exact state values per entity are enumerated in §3 alongside each entity's workflow narrative.

### 2.5. Optimistic Concurrency Control

Two write endpoints in the system participate in optimistic concurrency control, and they are the only endpoints that accept a version-bearing request field. All other endpoints do not take a version field.

A request to create an ISP must carry `expected_individual_version`, which holds the client's last observed `version` of the target `Individual`. If the `Individual` resource's current `version` does not match `expected_individual_version` at the moment of the write, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The product rationale for guarding ISP creation is that a new DRAFT ISP legitimately supersedes any existing DRAFT ISP for the same individual, so a writer holding a stale individual version would otherwise silently overwrite another writer's fresh draft.

A request to amend an ISP must carry `expected_isp_version`, which holds the client's last observed `version` of the target `ISP`. If the `ISP` resource's current `version` does not match `expected_isp_version` at the moment of the write, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The product rationale here is that amending while an amendment is already in flight (that is, an amendment requested from `AMENDMENT_DRAFT` state, which remains in `AMENDMENT_DRAFT` and supersedes the in-flight amendment content) would silently discard another writer's amendment if it were not guarded.

In both cases the OCC check runs after existence resolution and before any business logic executes, so a stale version surfaces as `ERR_STALE_VERSION` rather than being masked by a later rule.

### 2.6. Validation Ordering

When multiple validation rules apply to a single endpoint, the system evaluates them in a fixed priority order so that an earlier failure surfaces before a later one is examined. The order is:

1. Authentication header presence (missing or empty `X-User-ID` / `X-User-Role`).
2. Role permission against the RBAC matrix.
3. Role identity resolution for entity-backed roles.
4. Existence of every path id and every body foreign-key id.
5. Optimistic-concurrency check, when the endpoint declares `expected_*_version` — this check runs before any business logic.
6. Generic state check that the target resource is in a state permitting the requested transition; a failure here is rejected with `ERR_INVALID_STATE` (HTTP 409).
7. Domain-specific state preconditions (individual-enrolled, ISP-active, home-active, authorization-active, medication-order-active), then business-safety checks (certification, witness), then business-temporal checks (shift overlap, bed overlap, vehicle overlap, span containment), then business-referential checks (FK coherence, ownership, segregation of duties), then business-constraint checks (home posture, home capacity, vehicle capacity, day-program authorization), then business-fiscal checks (per-authorization cap, per-individual cap, waterfall full-placement, claim-period validity, sweep emptiness, overpayment), and finally input-shape checks (required fields, unknown fields, enum validity, date parseability, narrative length, plan-level/restrictive-intervention consistency).

Within business-fiscal checks, the per-authorization cap is evaluated before the per-individual annual cap. Within claim generation, the claim-period validity check (`service_period_end` not earlier than `service_period_start`, otherwise `ERR_CLAIM_PERIOD_INVALID`) runs before the sweep-emptiness check (`ERR_NO_BILLABLE_VISITS`).

### 2.7. Precision and Rounding

All monetary amounts in the system are represented as integer cents; no decimal currency values appear anywhere in the API. All unit quantities are integers. Where a computation produces a non-integer intermediate (notably, rounding visit minutes into fifteen-minute units, and computing the recoupment portion of a full payment), the rounding rule is stated alongside the calculation in §3 and is one of: round half-up to the nearest integer, floor to the nearest lower integer, or ceiling to the nearest higher integer. The system never sums unrounded values across visits and then rounds; per-visit rounding always happens first and the integer per-visit values are then summed.

### 2.8. Nested Resource Retrieval and Path Validation

The API is flat in structure — all resources are top-level and addressable by their own `id`. Where a path carries more than one path parameter, parameters are validated left-to-right: the leftmost id is resolved first, and each subsequent id is resolved in the context of the already-resolved leftward resources. Any id that fails to resolve (or any body foreign-key id that does not reference an existing resource) yields `ERR_NOT_FOUND` (HTTP 404), or a resource-specific variant where one is named for the endpoint. A request to a path the API does not define, or with a method the path does not support, is likewise answered with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

### 2.9. The Logical Clock

The system maintains a logical clock that is independent of wall-clock time. At startup the clock is exactly `2026-05-01T00:00:00Z`. An administrator-only capability advances the clock by writing a target instant to a test-driving endpoint that accepts `to_iso8601`; the response payload echoes the new clock as `current_utc`. Advancing the clock fires all time-based automatic transitions that have become due — ISP expiration past `plan_year_end`, service-authorization activation at `span_start` and expiration past `span_end`, behavior-support-plan expiration past `review_due_at`, and transport-trip completion past `return_at` — together with the cascades those transitions trigger.

### 2.10. Hierarchical Consistency and Cascading Side Effects

Many operations in this system produce cross-entity side effects beyond the primary entity they mutate. Whenever any entity's `version` is incremented as part of a mutation, the entity's `updated_at` is also refreshed to the current server clock. Cascading transitions that affect multiple entities recompute every derived counter on the affected parents — for example, `GroupHome.current_occupancy` is recomputed whenever a `BedAssignment` enters or leaves the `ACTIVE` state, and `ProviderAgency.held_claims_count` is recomputed whenever any `BillingClaim` enters or leaves the `HOLD` state. These recomputations are immediate and transactional with the triggering mutation; readers never observe an intermediate state in which a counter is stale relative to its underlying records.

### 2.11. The Compliance-Posture Gate

Every `GroupHome` carries a derived `compliance_posture` whose value is one of `GOOD_STANDING`, `PROVISIONAL`, or `CRITICAL`. The posture is recomputed immediately on incident submission and incident closure (the exact rule is given in §3.7). While a home's posture is `CRITICAL`, two downstream operations are blocked: creating a new bed assignment into that home, and submitting a billing claim for any resident of that home. Both rejections carry `ERR_HOME_POSTURE_CRITICAL` (HTTP 409). The posture also drives a cascading hold on draft claims, described in §3.7.

## 3. Business Logic & Workflows

### 3.1. Agency Bootstrap, Homes, and the Logical Clock

A new deployment begins with the creation of a provider agency. An `AgencyAdmin` creates the agency by supplying the agency's legal `name` and, optionally, three tuning parameters: `day_staff_ratio` (individuals per DSP on `DAY` shifts; default 4), `night_staff_ratio` (individuals per DSP on `NIGHT` shifts; default 8), and `evv_grace_minutes` (allowed clock-drift minutes between an EVV visit and its linked shift window; default 15). On creation the agency's three computed counters are initialized to zero: `cash_collected_cents`, `recoupment_balance_cents`, and `held_claims_count`. These counters are mutated only by the billing workflows described in §3.9 and §3.10.

Once an agency exists, the administrator registers group homes. Creating a home requires `agency_id`, `name`, `license_number`, and `certified_bed_count`; the `license_number` must be unique within the owning agency and `certified_bed_count` must be an integer no less than 1. A newly created home starts in `ACTIVE` status with `compliance_posture` equal to `GOOD_STANDING` and `current_occupancy` equal to zero.

A home's lifecycle has three states. From `ACTIVE`, a `ComplianceOfficer` may suspend the home, which transitions it to `SUSPENDED`; the suspension cascades to cancel every `PENDING` bed assignment at that home (active assignments are not affected by suspension), and increments the home's `version`. From `SUSPENDED`, a `ComplianceOfficer` may reinstate the home back to `ACTIVE`. From `ACTIVE`, an `AgencyAdmin` may close the home, transitioning it to the terminal state `CLOSED`; closure is permitted only when `current_occupancy` is zero and the home has no `PENDING` bed assignments, and is otherwise rejected with `ERR_HOME_OCCUPIED` (HTTP 409). Closing is the only transition that takes the home out of circulation permanently.

While a home is not `ACTIVE` (that is, `SUSPENDED` or `CLOSED`), five operations are rejected with `ERR_HOME_NOT_ACTIVE` (HTTP 409): creating a shift at the home, creating a bed assignment into the home, executing move-in for a pending assignment, recording an incident at the home, and scheduling a transport trip from the home.

### 3.2. Individuals, Enrollment, and Discharge

A `CaseManager` registers a new individual by supplying `agency_id`, `legal_name`, `medicaid_id`, `date_of_birth`, and `mobility_level`. The `medicaid_id` must be unique across the entire system. The `mobility_level` is one of `AMBULATORY`, `ASSIST`, or `WHEELCHAIR`, and feeds the staffing weighting described in §3.4. A newly registered individual starts in `APPLICANT` status.

A `QIDP` transitions an `APPLICANT` individual to `ENROLLED` via the enrollment action. Successful enrollment sets `enrolled_at` to the current server clock and increments the individual's `version`. Enrollment is the gateway precondition for nearly every downstream workflow: an individual must be `ENROLLED` for ISP activation, behavior-plan activation, service-authorization creation, bed-assignment creation, medication-order creation, incident creation, EVV visit creation, transport-leg inclusion, and claim generation; when the rule bites, the rejection is `ERR_INDIVIDUAL_NOT_ENROLLED` (HTTP 409).

Discharge, also performed by a `QIDP`, transitions an `ENROLLED` individual to the terminal state `DISCHARGED` and triggers the widest cascade in the system. On discharge: every `ACTIVE` bed assignment of the individual transitions to `ENDED` with `move_out_date` set to today (each such ending assignment frees its `bed_label` and triggers a recompute of the owning home's `current_occupancy`); every `PENDING` bed assignment transitions to `CANCELLED`; every service authorization of the individual in `PENDING`, `APPROVED`, `ACTIVE`, or `SUSPENDED` transitions to `CANCELLED` with `consumed_units` frozen as history; every `ACTIVE` ISP of the individual transitions to `DISCONTINUED`; every `ACTIVE` behavior support plan of the individual transitions to `EXPIRED`; and the individual's `version` increments.

### 3.3. Individual Service Plans and Service Authorizations

The Individual Service Plan is the person-centered document that anchors all downstream authorizations. A `CaseManager` or `QIDP` drafts an ISP by supplying `individual_id`, `plan_year_start`, `plan_year_end`, `goals_summary`, and optionally `meeting_date`; the `plan_year_end` must be strictly after `plan_year_start`, and `goals_summary` must be a narrative of at least 10 characters. Creation writes `authored_by_staff_id` from the caller's `X-User-ID`. A newly created ISP starts in `DRAFT` status with `amendment_count` equal to zero. If another ISP for the same individual already exists in `DRAFT` state, the existing DRAFT is immediately transitioned to `SUPERSEDED` (a system-side transition) when the new draft is created; the individual's `version` is also incremented as part of this write.

The create-ISP request is OCC-guarded. The caller must supply `expected_individual_version` equal to the individual's current `version` as last observed; if another writer has advanced the individual's `version` since then, creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the individual and re-issue.

From `DRAFT` (or from `AMENDMENT_DRAFT`, discussed below), the plan is submitted for review by a `CaseManager` or `QIDP`; submission from `DRAFT` additionally requires that `goals_summary` be at least 10 characters long, failing which the request is rejected with `ERR_INVALID_REQUEST`. Successful submission moves the plan to `PENDING_REVIEW` and increments its `version`. From `PENDING_REVIEW`, a `QIDP` may either return the plan to `DRAFT` for revision (optionally carrying a `return_reason`) or approve it. Approval enforces segregation of duties: the approving `QIDP` (identified by `X-User-ID`) must not be the same person as the ISP's `authored_by_staff_id`; a same-person approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On successful approval the system writes `approved_by_staff_id` from the caller's `X-User-ID` and transitions the plan to `APPROVED`.

Activation moves an `APPROVED` plan to `ACTIVE`, sets `activated_at` to the current server clock, and increments `version`. Activation requires that the individual be `ENROLLED` (otherwise `ERR_INDIVIDUAL_NOT_ENROLLED`). If another ISP for the same individual is currently `ACTIVE`, that prior ISP is transitioned to `SUPERSEDED` as part of the activation — the create-with-supersede-at-activation rule. Once `ACTIVE`, the plan may be amended. Amending is OCC-guarded: the request carries `expected_isp_version` matching the plan's current `version`, optionally a replacement `goals_summary` (which when present must again be at least 10 characters) and/or `plan_year_end` (which when present must be strictly after the plan's `plan_year_start`, otherwise `ERR_INVALID_REQUEST`), and is rejected with `ERR_STALE_VERSION` (HTTP 412) if the plan's `version` has advanced since the caller last read it. Amending an `ACTIVE` plan transitions it to `AMENDMENT_DRAFT`; amending an `AMENDMENT_DRAFT` plan leaves it in `AMENDMENT_DRAFT` and supersedes the in-flight amendment content. In both cases `amendment_count` increments by 1 and `version` increments by 1. The amendment is then submitted for review, approved, and activated through the same path as a fresh plan.

Finally, the system clock drives expiration: when the logical clock advances past `plan_year_end`, an `ACTIVE` ISP transitions automatically to `EXPIRED`. This transition fires a two-link cascade: every `ACTIVE` service authorization anchored to this individual transitions to `SUSPENDED` (link 1), and each such suspended authorization in turn transitions all of its EVV visits that are in `PENDING` or `EXCEPTION` to `REJECTED` (link 2). The ISP's `version` increments.

Service authorizations allocate waiver units against an `ACTIVE` ISP. A `CaseManager` creates an authorization by supplying `individual_id`, `isp_id`, `service_code`, `unit_type`, `authorized_units`, `rate_cents`, `span_start`, and `span_end`. The `service_code` is one of `RES_HAB`, `DAY_PROG`, `RESPITE`, or `SUPPORTED_EMPLOYMENT`; the `unit_type` is one of `FIFTEEN_MIN` or `DAY`; `authorized_units` and `rate_cents` must each be integers no less than 1. The `isp_id` must reference an ISP that is currently `ACTIVE`; otherwise the create is rejected with `ERR_ISP_NOT_ACTIVE` (HTTP 409). The referenced ISP must also belong to the stated `individual_id`; a cross-individual reference is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `span_start` must be on or after the linked ISP's `plan_year_start`, and `span_end` must be on or after `span_start` and on or before the linked ISP's `plan_year_end`; a span that escapes the plan year is rejected with `ERR_OUT_OF_SPAN` (HTTP 422). Two fiscal caps are then applied in order: first the per-authorization cap, which requires that the product of `authorized_units` and `rate_cents` be no greater than 5000000 cents and rejects with `ERR_UNIT_CAP_EXCEEDED` (HTTP 422); then the per-individual annual cap, which requires that the sum, over all of the individual's non-`CANCELLED` authorizations including the new one, of each authorization's product of `authorized_units` and `rate_cents` be no greater than 20000000 cents and rejects with `ERR_INDIVIDUAL_CAP_EXCEEDED` (HTTP 422). A successfully created authorization starts in `PENDING` status with `consumed_units` equal to zero.

From `PENDING`, a `QIDP` approves the authorization, moving it to `APPROVED`. If `span_start` is on or before today and today is on or before `span_end`, the transition continues immediately to `ACTIVE` as part of the same call. The system clock also moves an `APPROVED` authorization to `ACTIVE` automatically when the clock reaches `span_start` and today is still within the span. From `ACTIVE`, several exits exist: a `CaseManager` may cancel the authorization to `CANCELLED` (cancellation is in fact available from `PENDING`, `APPROVED`, `ACTIVE`, or `SUSPENDED`); the logical clock advancing past `span_end` transitions it to `EXPIRED`; the consumption of the last remaining unit transitions it to `EXHAUSTED` (see §3.8); and the anchored ISP expiring transitions it to `SUSPENDED` as described above. From `SUSPENDED`, a `QIDP` may resume the authorization back to `ACTIVE`, but only when the linked ISP is itself `ACTIVE` (otherwise `ERR_ISP_NOT_ACTIVE`) and today is within the closed span from `span_start` to `span_end` (otherwise `ERR_OUT_OF_SPAN`).

### 3.4. Staff, Shifts, and Weighted Staffing Compliance

An `AgencyAdmin` hires staff by supplying `agency_id`, `full_name`, `staff_role`, `certifications`, and `hire_date`. The `staff_role` is one of `DSP`, `CASE_MANAGER`, or `QIDP`; for entity-backed calls the `staff_role` on the resolved `StaffMember` must match the `X-User-Role` header. The `certifications` field is an array drawn from `MED_CERT`, `BEHAVIOR_CERT`, `CPR`, and `CDL`. A newly hired staff member starts in `ACTIVE` status. Termination by an `AgencyAdmin` moves a staff member from `ACTIVE` to the terminal state `TERMINATED` and cascades: every shift assignment for this staff member in `SCHEDULED` or `CONFIRMED` status whose `window_start` is strictly after now transitions to `CANCELLED`.

Shift assignments are created by an `AgencyAdmin` and bind a staff member to a home over a time window. The create carries `home_id`, `staff_member_id`, `window_start`, `window_end`, `shift_type` (one of `DAY` or `NIGHT`, which selects the staffing ratio used in §3.4's staffing check), and optionally `requires_med_pass` (defaulting to `false`). The `window_start` must be strictly before `window_end`. When `requires_med_pass` is `true`, the assigned staff member must hold the `MED_CERT` certification; if not, the create is rejected with `ERR_CERTIFICATION_MISSING` (HTTP 403). The create also enforces an eight-hour rest buffer against the assigned staff member's other shifts: for every existing non-`CANCELLED` shift of the same staff member, the new window's start must be no earlier than eight hours after the prior shift's `window_end`, and the new window's end plus eight hours must be no later than the next shift's `window_start`. A violation rejects with `ERR_SHIFT_OVERLAP` (HTTP 409). A successfully created shift starts in `SCHEDULED` status.

The assigned DSP confirms their own shift, moving it from `SCHEDULED` to `CONFIRMED`; the confirmation enforces ownership by requiring that the caller's `X-User-ID` equal the shift's `staff_member_id`, rejecting with `ERR_OWNERSHIP_MISMATCH` (HTTP 403) otherwise. An `AgencyAdmin` may cancel a shift from `SCHEDULED` or `CONFIRMED`, transitioning it to `CANCELLED`. The terminal `COMPLETED` state is reached automatically: when an EVV visit carrying a `shift_id` pointing at a `CONFIRMED` shift is verified (or its exception is resolved), the linked shift transitions to `COMPLETED`.

Two computed reads expose home-level compliance with staffing ratios. The census read accepts `as_of_date` (a required query parameter; its absence or a malformed value rejects with `ERR_INVALID_REQUEST`) and returns `as_of_date` (echoed), `current_census`, `projected_census`, `certified_bed_count`, and `current_occupancy`. The current census on a given date is the count of `ACTIVE` bed assignments at the home whose `move_in_date` is on or before the date and whose `move_out_date` is either absent or strictly after the date — a half-open interval convention. The projected census adds to the current census the count of `PENDING` bed assignments at the home whose `move_in_date` is on or before the date plus fourteen days; the projected view is what the admission gate in §3.5 uses.

The staffing-check read accepts `shift_date` and `shift_type` (both required query parameters; either absent, a malformed `shift_date`, or a `shift_type` other than `DAY` or `NIGHT` rejects with `ERR_INVALID_REQUEST`) and returns `shift_date` and `shift_type` (echoed), `weighted_census`, `required_dsps`, `scheduled_dsps`, `actual_dsps`, `compliant_scheduled`, and `compliant_actual`. The weighted census sums a per-resident weight over individuals with an `ACTIVE` bed assignment at the home on `shift_date` (under the same half-open interval convention as the census read): the weight is 2 if the resident's `mobility_level` is `WHEELCHAIR` and 1 otherwise. The applicable ratio is the agency's `day_staff_ratio` when `shift_type` is `DAY` and the agency's `night_staff_ratio` when `shift_type` is `NIGHT`. The required DSP count is the weighted census divided by the ratio and rounded up to the next integer; a census of zero residents yields zero required DSPs. The scheduled DSP count is the number of shift assignments at the home whose `window_start` calendar date equals `shift_date`, with matching `shift_type` and status in `SCHEDULED`, `CONFIRMED`, or `COMPLETED` (cancelled shifts are excluded). The actual DSP count is the number of distinct `staff_member_id` values on EVV visits whose `shift_id` points at one of this home's shifts on `shift_date` with matching `shift_type` and whose `verification_status` is `VERIFIED`. Compliance is evaluated independently on both views: `compliant_scheduled` is true when the scheduled DSP count is at least the required count (equality is compliant), and `compliant_actual` is true when the actual DSP count is at least the required count. The two views can diverge — the first is a prospective plan view, the second a retrospective reality view based on verified attendance.

### 3.5. Bed Assignments and the Admission Gate

A `CaseManager` initiates an admission by creating a bed assignment carrying `home_id`, `bed_label`, `individual_id`, and `move_in_date`. The `bed_label` is a free-text bed identifier scoped to the home (for example, `Room2-B`); the bed-overlap resource key is the pair of `home_id` and `bed_label`. Creation enforces four gates, evaluated in the §2.6 order (so the individual-enrolled domain precondition is checked before the home-active one). The individual must be `ENROLLED` (otherwise `ERR_INDIVIDUAL_NOT_ENROLLED`). The referenced home must be `ACTIVE` (otherwise `ERR_HOME_NOT_ACTIVE`). The home's `compliance_posture` must not be `CRITICAL` (otherwise `ERR_HOME_POSTURE_CRITICAL`). And the capacity gate: the projected census at `move_in_date`, plus one for the new admission, must be no greater than the home's `certified_bed_count`; filling the last bed exactly is permitted. A failure here rejects with `ERR_HOME_CAPACITY_EXCEEDED` (HTTP 409). A successfully created assignment starts in `PENDING` status with `move_out_date` absent.

A `QIDP` executes move-in by transitioning a `PENDING` assignment to `ACTIVE`. Move-in requires that `move_in_date` be on or before today (a future move-in rejects with `ERR_MOVE_IN_FUTURE`, HTTP 422), that no overlapping `ACTIVE` assignment exist on the same pair of `home_id` and `bed_label` under a half-open interval intersection (overlap rejects with `ERR_BED_OVERLAP`, HTTP 409; adjacency — one assignment's `move_out_date` exactly equal to the next's `move_in_date` — is permitted), and that the home be `ACTIVE` (otherwise `ERR_HOME_NOT_ACTIVE`). The bed-overlap rule is also enforced at assignment creation against assignments in `PENDING` or `ACTIVE` status. On successful move-in the home's `current_occupancy` is recomputed.

Move-out transitions an `ACTIVE` assignment to the terminal state `ENDED`. The `move_out_date` may be supplied by the caller; if absent it defaults to today. In either case the resulting `move_out_date` must be strictly after `move_in_date` (otherwise `ERR_INVALID_REQUEST`). Move-out triggers a recompute of the home's `current_occupancy` (a decrement) and frees the `bed_label`. Cancellation by a `CaseManager` moves a `PENDING` assignment to the terminal state `CANCELLED`.

### 3.6. Medication Orders and Medication Administration Records

A `QIDP` creates a medication order by supplying `individual_id`, `drug_name`, `dosage`, `schedule_times`, `start_date`, and optionally `requires_witness` (defaulting to `false`) and `end_date` (absent meaning open-ended). The `schedule_times` field is a non-empty array of 24-hour `HH:MM` strings. A new order starts in `ACTIVE` status. Discontinuation by a `QIDP` transitions an `ACTIVE` order to the terminal state `DISCONTINUED`; a discontinuation attempt against an order that is not `ACTIVE` rejects with `ERR_MED_ORDER_DISCONTINUED` (HTTP 409), and once discontinued, no further administration events may be recorded against the order (a recording attempt likewise rejects with `ERR_MED_ORDER_DISCONTINUED`, HTTP 409).

A `DSP` records a medication administration event — an append-only MAR record — by supplying `medication_order_id`, `scheduled_time`, `outcome`, and optionally `administered_time` and `witness_staff_id`. The `outcome` is one of `GIVEN`, `REFUSED`, `HELD`, or `MISSED`. On creation the system writes `administered_by_staff_id` from the caller's `X-User-ID`. Three rules govern the record. First, the recording DSP must hold `MED_CERT`; otherwise the create is rejected with `ERR_CERTIFICATION_MISSING`. Second, when the linked order's `requires_witness` is `true` and the `outcome` is `GIVEN`, the `witness_staff_id` must be present and must not equal `administered_by_staff_id`; a missing or self-witness rejects with `ERR_WITNESS_REQUIRED` (HTTP 400). Third, the `administered_time` is required unless the `outcome` is `MISSED`, and when present it must lie within sixty minutes before or after the `scheduled_time`; a deviation outside that window rejects with `ERR_OUT_OF_SPAN` (HTTP 422).

A computed read exposes the medication adherence rate for an individual, accepting `as_of` (a required query parameter; its absence or a malformed value rejects with `ERR_INVALID_REQUEST`) and returning `window_start`, `window_end`, `total_events`, `given_count`, and `adherence_pct`. The window is the thirty-day span ending at `as_of`, closed on both ends — an event whose `scheduled_time` falls exactly at `as_of` minus thirty days is included. The events counted are all MAR events whose linked medication order belongs to the individual and whose `scheduled_time` lies inside the window; all outcomes count toward the denominator. The adherence percentage is the floor of one hundred times the count of events with `outcome` equal to `GIVEN` divided by the total event count. When the window contains no events, `adherence_pct` is null.

### 3.7. Behavior Support Plans and Incident Reporting

A behavior support plan (BSP) is authored by a `CaseManager` or `QIDP` supplying `individual_id`, `level`, and `restrictive_interventions`. The `level` is one of `LEVEL_1` (non-restrictive) or `LEVEL_2` (restrictive). On creation the system writes `authored_by_staff_id` from the caller's `X-User-ID`, and the plan starts in `DRAFT` status with `approved_at`, `review_due_at`, and `approved_by_staff_id` all absent.

Submission to the Human Rights Committee moves a `DRAFT` plan to `HRC_REVIEW`. Submission enforces consistency between `level` and `restrictive_interventions`: a `LEVEL_2` plan must carry a non-empty `restrictive_interventions` array, and a `LEVEL_1` plan must carry an empty one; a mismatch rejects with `ERR_RESTRICTIVE_INTERVENTION_MISMATCH` (HTTP 400). From `HRC_REVIEW`, a `QIDP` may reject the plan back to `DRAFT`, or approve it to `APPROVED`. HRC approval enforces segregation of duties against the plan's `authored_by_staff_id` (same-person approval rejects with `ERR_SEGREGATION_OF_DUTIES`), and on success writes `approved_at` to now and `approved_by_staff_id` from `X-User-ID`. Activation moves an `APPROVED` plan to `ACTIVE`, requires that the individual be `ENROLLED` (otherwise `ERR_INDIVIDUAL_NOT_ENROLLED`), sets `review_due_at` to `approved_at` plus 180 days for a `LEVEL_2` plan or plus 365 days for a `LEVEL_1` plan, and supersedes any other `ACTIVE` plan for the same individual (that prior plan transitions to `SUPERSEDED`). The system clock moves an `ACTIVE` plan to `EXPIRED` when it advances strictly past `review_due_at`; on the due date itself the plan remains `ACTIVE`.

Incidents are drafted by a `DSP` or `QIDP` supplying `individual_id`, `home_id`, `category`, `severity`, `occurred_at`, `discovered_at`, and `description`. The `category` is one of `MED_ERROR`, `INJURY`, `ABUSE_ALLEGATION`, `BEHAVIOR`, or `ELOPEMENT`; the `severity` is one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; the `discovered_at` must be on or after `occurred_at`; and the `description` must be a narrative of at least 10 characters. On creation the system writes `submitted_by_staff_id` from the caller's `X-User-ID` and the incident starts in `DRAFT` status with `submitted_at`, `report_due_at`, and `is_late` unset.

Submission moves a `DRAFT` incident to `SUBMITTED` and enforces ownership: the caller's `X-User-ID` must equal the incident's `submitted_by_staff_id` (otherwise `ERR_OWNERSHIP_MISMATCH`). On submission the server stamps `submitted_at` to now and computes `report_due_at` as `discovered_at` plus a severity-dependent window: 24 hours when `severity` is `CRITICAL`, 48 hours when `severity` is `HIGH`, and 72 hours otherwise. The `is_late` flag is then computed as whether `submitted_at` is strictly later than `report_due_at`; submission exactly at `report_due_at` is not late. Submission of a `CRITICAL`-severity incident also triggers the first link of the posture cascade described below.

From `SUBMITTED`, a `QIDP` begins review, moving the incident to `UNDER_REVIEW`. From `UNDER_REVIEW`, a `QIDP` may request more information, moving the incident to `NEEDS_INFO`. From `NEEDS_INFO`, the original submitter (or another `DSP` or `QIDP` acting with the same identity) resubmits, moving the incident back to `SUBMITTED`; resubmission enforces the same ownership rule against `submitted_by_staff_id`, updates `submitted_at` to now, and recomputes `is_late` against the original `report_due_at` (the due date is not extended by resubmission). Resubmission does not recompute the home's compliance posture and does not fire the posture cascades described below. From `UNDER_REVIEW`, a `QIDP` closes the incident, moving it to the terminal state `CLOSED`; closure enforces segregation of duties against `submitted_by_staff_id` (same-person closure rejects with `ERR_SEGREGATION_OF_DUTIES`).

The compliance posture of a home is recomputed at two moments: on incident submission and on incident closure. The rule examines all incidents of the home whose status is one of `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` (drafts and closed incidents are excluded). If any open incident has `severity` equal to `CRITICAL`, the posture becomes `CRITICAL`; otherwise, if any open incident has `severity` equal to `HIGH`, the posture becomes `PROVISIONAL`; otherwise the posture is `GOOD_STANDING`. Whenever the posture recomputed after a submission is `CRITICAL` — whether or not the submission changed the posture — a second cascade link fires: every `DRAFT` billing claim of every individual who holds an `ACTIVE` bed assignment at this home transitions to `HOLD`, and a third link recomputes `held_claims_count` for the home's agency and for the agency of every individual whose claim transitioned. Whenever the posture recomputed after a closure is below `CRITICAL`, the inverse cascade fires: every `HOLD` billing claim of residents of this home transitions back to `DRAFT`, and `held_claims_count` is recomputed for the same set of agencies.

### 3.8. EVV Visits, Waterfall Allocation, and the Consumption Ledger

Electronic Visit Verification records the delivery of a service. A `DSP` creates a visit by supplying `individual_id`, `authorization_id`, `service_date`, `check_in_at`, `check_out_at`, `geo_within_radius`, and optionally `shift_id`. On creation the system writes `staff_member_id` from the caller's `X-User-ID`. The referenced authorization must belong to the same individual as the visit (a body foreign-key coherence failure rejects with `ERR_INVALID_REQUEST`), must be `ACTIVE` (otherwise `ERR_AUTHORIZATION_NOT_ACTIVE`, HTTP 409), and the `service_date` must lie inside the authorization's closed span from `span_start` to `span_end` (otherwise `ERR_OUT_OF_SPAN`, HTTP 422). The `check_out_at` must be strictly after `check_in_at`. When `shift_id` is supplied, the referenced shift must belong to the visit's staff member; a shift owned by a different staff member rejects with `ERR_INVALID_REQUEST` (HTTP 400). If `geo_within_radius` is `false`, the new visit enters `EXCEPTION` status instead of `PENDING`.

The system then computes `provisional_units` from the raw timestamps. Let the visit duration be the number of minutes between `check_in_at` and `check_out_at`. When the authorization's `unit_type` is `FIFTEEN_MIN`, `provisional_units` is the duration divided by 15, rounded half-up to the nearest integer, with a floor of one unit (a non-zero-duration visit always bills at least one unit). When the authorization's `unit_type` is `DAY`, `provisional_units` is 1 if the duration is at least 360 minutes and 0 otherwise. The new visit's `billing_status` starts as `UNBILLED`, its `billed_claim_id` is absent, and its `allocated_units_entries` log is empty.

Verification and exception-resolution are the two paths by which a visit locks in its final units and debits the authorization ledger. A `QIDP` verifies a `PENDING` visit, transitioning it to `VERIFIED`: `final_units` is set to the previously computed `provisional_units`, and the waterfall allocation described below runs against `final_units`. A `QIDP` may instead flag a `PENDING` visit, moving it to `EXCEPTION` (a bookkeeping transition), or reject a `PENDING` or `EXCEPTION` visit outright to the terminal state `REJECTED` with a mandatory `reason`. From `EXCEPTION`, a `QIDP` resolves the visit by supplying `adjusted_minutes` and a `resolution_note`. The `adjusted_minutes` must be a positive multiple of 15 (otherwise `ERR_INVALID_REQUEST`); the final units are then exactly `adjusted_minutes` divided by 15, with no further rounding. The waterfall then runs against this final value. On either verification path, if `shift_id` is set and the linked shift is `CONFIRMED`, the shift transitions to `COMPLETED`.

The waterfall allocation is the system's central units-consumption rule, and it applies identically at verify and at resolve-exception. Candidates for allocation are ordered: the visit's own authorization first, then any successor authorizations of the same individual with the same `service_code`, in `ACTIVE` status, whose span contains the `service_date`, ordered by `span_start` ascending and tie-broken by `created_at` ascending (never by `id`). For each candidate in order, the allocation takes the smaller of the candidate's remaining units (that is, `authorized_units` minus `consumed_units`) and the still-unallocated portion of the visit's final units. If, after all candidates have been considered, any unallocated units remain, the entire allocation is rejected with `ERR_AUTHORIZATION_UNITS_EXHAUSTED` (HTTP 409) — there is no partial debit; no candidate's `consumed_units` is modified and the visit remains in its prior `verification_status` (the `final_units` value assigned before the allocation attempt remains recorded on the visit). On success the visit's `allocated_units_entries` records one entry per candidate in allocation order, each entry holding the candidate's `authorization_id` and the `units` placed there; each candidate's `consumed_units` is incremented by its allocated amount; and any candidate whose `consumed_units` reaches or exceeds its `authorized_units` (equality is the trigger) transitions to `EXHAUSTED`. The `remaining_units` field of an authorization always equals `authorized_units` minus `consumed_units`.

The billing-sweep and claim-void flows described in §3.9 mutate a visit's `billing_status` independently of its `verification_status`: the sweep flips `UNBILLED` to `BILLED` and sets `billed_claim_id`; the void flips `BILLED` back to `UNBILLED` and clears `billed_claim_id`. Each such billing-dimension mutation increments the visit's `version`.

### 3.9. Day-Program Transport and Vehicle Capacity

An `AgencyAdmin` schedules a day-program transport trip by supplying `home_id`, `vehicle_id`, `trip_date`, `depart_at`, `return_at`, and `legs`. The `vehicle_id` is a free-text fleet reference (for example, `VAN-1`); the vehicle-overlap resource key is the pair of `vehicle_id` and `trip_date`. The `return_at` must be strictly after `depart_at`. The vehicle-overlap rule rejects any new trip whose half-open window from `depart_at` to `return_at` intersects an existing non-`CANCELLED` trip for the same key, with touching endpoints permitted; a violation rejects with `ERR_VEHICLE_OVERLAP` (HTTP 409).

The `legs` array carries one entry per rider, each holding `individual_id`, a boolean `wheelchair_seat`, and `pickup_at` and `dropoff_at` times. For every leg: the individual must be `ENROLLED`, must hold an `ACTIVE` bed assignment at this home on `trip_date`, and must hold an `ACTIVE` `DAY_PROG` authorization whose span covers `trip_date` — otherwise the create is rejected with `ERR_NO_DAY_PROG_AUTHORIZATION` (HTTP 409). Within a leg, `pickup_at` must be strictly before `dropoff_at`, and both times must lie inside the closed trip window from `depart_at` to `return_at` (a `pickup_at` equal to `depart_at` or a `dropoff_at` equal to `return_at` is permitted). The trip's `occupied_slots` is the sum over legs of 2 for a wheelchair seat and 1 otherwise, and the total must not exceed 8; a violation rejects with `ERR_VEHICLE_CAPACITY_EXCEEDED` (HTTP 409). A successfully created trip starts in `SCHEDULED` status. An `AgencyAdmin` may cancel a `SCHEDULED` trip to `CANCELLED`. The system clock moves a `SCHEDULED` trip to the terminal state `COMPLETED` when it advances past `return_at`.

### 3.10. Billing Claims, Recoupment Netting, and Void Compensation

A `BillingSpecialist` generates a claim by supplying `individual_id`, `service_period_start`, and `service_period_end`. The `service_period_end` must be on or after `service_period_start` (otherwise `ERR_CLAIM_PERIOD_INVALID`, HTTP 400), and this check runs before the sweep-emptiness check. The sweep selects the individual's EVV visits whose `verification_status` is `VERIFIED`, whose `billing_status` is `UNBILLED`, and whose `service_date` lies inside the closed claim period from `service_period_start` to `service_period_end`, ordered by `service_date` ascending and then `created_at` ascending (never by `id`). If the sweep set is empty, generation is rejected with `ERR_NO_BILLABLE_VISITS` (HTTP 422) and no claim is created.

Claim lines are grouped by distinct allocated authorization: each swept visit contributes its `allocated_units_entries` to the line of the entry's `authorization_id`, so a visit whose units spilled onto a successor authorization lands on the successor's line. Lines appear in the order each authorization first appears across the sorted sweep. Each line carries `authorization_id`, `service_code`, `units`, `rate_cents`, and `amount_cents`. For each line, `units` is the sum of allocated entry units for that authorization across swept visits, and `amount_cents` is the line's `units` multiplied by the authorization's `rate_cents` (an exact integer multiplication, no rounding). The claim's `total_units` is the sum of line `units`, and `total_amount_cents` is the sum of line `amount_cents`. The per-visit rounding order is pinned: units are rounded per visit first (during the provisional/final computation), and the integer per-visit units are then summed into the claim line; summing raw minutes across visits and then rounding is forbidden and would produce different totals. At generation the claim starts in `DRAFT` status, `submitted_by_user_id` and `submitted_at` are absent, `paid_amount_cents` and `posted_net_cents` are absent, `denial_reason` is absent, and every swept visit's `billing_status` flips from `UNBILLED` to `BILLED` with `billed_claim_id` set to the new claim's `id`.

A `BillingSpecialist` submits a claim from `DRAFT` or `CORRECTED`, transitioning it to `SUBMITTED`. A claim with no lines cannot be submitted (rejected with `ERR_INVALID_STATE`, HTTP 409). Submission is gated by the resident's home posture: if any home at which the individual holds an `ACTIVE` bed assignment has `compliance_posture` equal to `CRITICAL`, submission is rejected with `ERR_HOME_POSTURE_CRITICAL` (HTTP 409). On success the server stamps `submitted_at` to now and writes `submitted_by_user_id` from the caller's `X-User-ID`.

Remittance posting by a `BillingSpecialist` moves a `SUBMITTED` claim to `PAID` or `PARTIALLY_PAID`. Posting enforces segregation of duties: the poster's `X-User-ID` must not equal the claim's `submitted_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). The `paid_amount_cents` must be a non-negative integer (otherwise `ERR_INVALID_REQUEST`) and no greater than the claim's `total_amount_cents` (otherwise `ERR_OVERPAYMENT`, HTTP 400). When `paid_amount_cents` equals `total_amount_cents`, the claim transitions to `PAID` and the recoupment netting runs in a pinned evaluation order: the gross is the claim's `total_amount_cents`; the recouped portion is the smaller of two values — the floor of ten percent of the gross, and the agency's `recoupment_balance_cents` measured before this payment; the `posted_net_cents` is the gross minus the recouped portion; the agency's `cash_collected_cents` is incremented by `posted_net_cents`; and the agency's `recoupment_balance_cents` becomes its pre-payment balance minus the recouped portion. The ten-percent rate applies to the gross, never to the net. When `paid_amount_cents` is strictly less than `total_amount_cents`, the claim transitions to `PARTIALLY_PAID`, `posted_net_cents` equals `paid_amount_cents`, no recoupment occurs, the agency's `cash_collected_cents` is incremented by `posted_net_cents`, and the `recoupment_balance_cents` is unchanged.

A payer denial is recorded by a `BillingSpecialist` via the deny action, which requires a `denial_reason` (its absence rejects with `ERR_INVALID_REQUEST`) and moves a `SUBMITTED` claim to `DENIED`. Correction moves a `DENIED` claim to `CORRECTED`: the caller supplies `lines_override`, and each entry must reference an authorization already on this claim with `units` no less than 0 (otherwise `ERR_INVALID_REQUEST`); the corrected units per line must be no greater than that authorization's `remaining_units` plus the units already billed on this claim line (otherwise `ERR_AUTHORIZATION_UNITS_EXHAUSTED`). `lines_override` need not cover every line: a line absent from `lines_override` keeps its existing `units`. On success the claim's `lines` are recomputed — `units` from `lines_override` where supplied, `amount_cents` equal to `units` multiplied by `rate_cents` — and the totals are recomputed; the corrected claim is then resubmitted through the normal submit path.

Voiding moves a `PAID` or `PARTIALLY_PAID` claim to the terminal state `VOIDED` and is the system's compensation pathway. On void: the agency's `cash_collected_cents` is decremented by the claim's `posted_net_cents`, and the agency's `recoupment_balance_cents` is incremented by the same amount (this is the source of the recoupment balance that later full payments net against); every EVV visit swept into this claim has its `billing_status` flipped from `BILLED` back to `UNBILLED` and its `billed_claim_id` cleared; and each visit's `allocated_units_entries` is released in reverse order (last-in-first-out), decrementing each referenced authorization's `consumed_units` by the entry's `units`, after which the visit's `allocated_units_entries` log is cleared to empty. An authorization whose `consumed_units` thereby drops below its `authorized_units` and that was in `EXHAUSTED` status transitions back to `ACTIVE`. The claim's `version` increments on void as on every mutation.

## 4. Endpoint Definitions

All endpoints are mounted under the top-level path `/`. Resources newly created by a `POST` that did not previously exist are returned with HTTP status 201; all other successful operations (reads, transitions, updates) return 200. The response envelope, pagination mechanics, and error envelope are specified in §2. The table below is intentionally minimal: it names each endpoint, the role or roles authorized to call it, and a brief description. Full request bodies, response shapes, side effects, and the validation rules that guard each endpoint are specified in §3 and §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/agencies` | Create a provider agency (bootstrap) | AgencyAdmin |
| GET | `/agencies/{agencyId}` | Get agency including computed ledger fields | Any |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires time-based auto-transitions | AgencyAdmin |
| POST | `/homes` | Create a group home | AgencyAdmin |
| GET | `/homes` | List homes (filtered) | Any |
| GET | `/homes/{homeId}` | Get home including posture and occupancy | Any |
| POST | `/homes/{homeId}/suspend` | Suspend home admissions and operations | ComplianceOfficer |
| POST | `/homes/{homeId}/reinstate` | Reinstate a suspended home | ComplianceOfficer |
| POST | `/homes/{homeId}/close` | Close a home (zero residents and zero pending assignments) | AgencyAdmin |
| GET | `/homes/{homeId}/census` | Computed read: current vs projected census for a date | Any |
| GET | `/homes/{homeId}/staffing-check` | Computed read: weighted staffing requirement vs coverage | Any |
| POST | `/individuals` | Register an individual (APPLICANT) | CaseManager |
| GET | `/individuals` | List individuals (filtered) | Any |
| GET | `/individuals/{individualId}` | Get an individual | Any |
| POST | `/individuals/{individualId}/enroll` | Enroll an applicant into waiver services | QIDP |
| POST | `/individuals/{individualId}/discharge` | Discharge individual; cascades to beds, authorizations, ISP, BSP | QIDP |
| POST | `/isps` | Create ISP draft (OCC on Individual; supersedes existing DRAFT) | CaseManager, QIDP |
| GET | `/isps` | List ISPs (filtered) | Any |
| GET | `/isps/{ispId}` | Get an ISP | Any |
| POST | `/isps/{ispId}/submit-review` | Submit draft or amendment for review | CaseManager, QIDP |
| POST | `/isps/{ispId}/approve` | QIDP approval (segregation of duties vs author) | QIDP |
| POST | `/isps/{ispId}/return` | Return plan to DRAFT for revision | QIDP |
| POST | `/isps/{ispId}/activate` | Activate approved plan; supersedes prior ACTIVE | QIDP |
| POST | `/isps/{ispId}/amend` | Amend plan (OCC on ISP; re-amend supersedes in-flight amendment) | CaseManager, QIDP |
| POST | `/authorizations` | Create waiver service authorization anchored to an ACTIVE ISP | CaseManager |
| GET | `/authorizations` | List authorizations (filtered) | Any |
| GET | `/authorizations/{authId}` | Get authorization including consumed/remaining units | Any |
| POST | `/authorizations/{authId}/approve` | Approve; immediately ACTIVE when today is inside span | QIDP |
| POST | `/authorizations/{authId}/cancel` | Cancel (from PENDING, APPROVED, ACTIVE, or SUSPENDED) | CaseManager |
| POST | `/authorizations/{authId}/resume` | Resume suspended authorization | QIDP |
| POST | `/staff` | Hire a staff member | AgencyAdmin |
| GET | `/staff` | List staff (filtered) | Any |
| GET | `/staff/{staffId}` | Get a staff member | Any |
| POST | `/staff/{staffId}/terminate` | Terminate staff; future SCHEDULED/CONFIRMED shifts cancelled | AgencyAdmin |
| POST | `/shifts` | Assign a DSP shift to a home | AgencyAdmin |
| GET | `/shifts` | List shifts (filtered) | Any |
| GET | `/shifts/{shiftId}` | Get a shift | Any |
| POST | `/shifts/{shiftId}/confirm` | Assigned DSP confirms own shift | DSP |
| POST | `/shifts/{shiftId}/cancel` | Cancel a SCHEDULED or CONFIRMED shift | AgencyAdmin |
| POST | `/bed-assignments` | Create admission (PENDING) with posture and capacity gates | CaseManager |
| GET | `/bed-assignments/{baId}` | Get a bed assignment | Any |
| GET | `/bed-assignments` | List bed assignments (filtered) | Any |
| POST | `/bed-assignments/{baId}/move-in` | Execute move-in | QIDP |
| POST | `/bed-assignments/{baId}/move-out` | Execute move-out; frees the bed | QIDP |
| POST | `/bed-assignments/{baId}/cancel` | Cancel a PENDING assignment | CaseManager |
| POST | `/medication-orders` | Create a medication order | QIDP |
| GET | `/medication-orders` | List medication orders (filtered) | Any |
| GET | `/medication-orders/{moId}` | Get a medication order | Any |
| POST | `/medication-orders/{moId}/discontinue` | Discontinue an order | QIDP |
| POST | `/admin-events` | Record a MAR event | DSP |
| GET | `/admin-events/{eventId}` | Get a MAR event | Any |
| GET | `/admin-events` | List MAR events (filtered) | Any |
| GET | `/individuals/{individualId}/med-adherence` | Computed read: 30-day adherence rate | Any |
| POST | `/behavior-plans` | Create BSP draft | CaseManager, QIDP |
| GET | `/behavior-plans/{bpId}` | Get a behavior support plan | Any |
| GET | `/behavior-plans` | List BSPs (filtered) | Any |
| POST | `/behavior-plans/{bpId}/submit-hrc` | Submit plan to Human Rights Committee review | CaseManager, QIDP |
| POST | `/behavior-plans/{bpId}/hrc-approve` | HRC approval (segregation of duties vs author) | QIDP |
| POST | `/behavior-plans/{bpId}/hrc-reject` | HRC rejection back to DRAFT | QIDP |
| POST | `/behavior-plans/{bpId}/activate` | Activate approved plan; supersedes prior ACTIVE; sets review due | QIDP |
| POST | `/incidents` | Draft an incident report | DSP, QIDP |
| GET | `/incidents/{incidentId}` | Get an incident | Any |
| GET | `/incidents` | List incidents (filtered) | Any |
| POST | `/incidents/{incidentId}/submit` | Submit; computes report due and lateness; CRITICAL cascades posture | DSP, QIDP |
| POST | `/incidents/{incidentId}/start-review` | QIDP begins review | QIDP |
| POST | `/incidents/{incidentId}/request-info` | Send incident back for more information | QIDP |
| POST | `/incidents/{incidentId}/resubmit` | Resubmit after NEEDS_INFO; lateness recomputed against original due | DSP, QIDP |
| POST | `/incidents/{incidentId}/close` | Close (segregation of duties vs submitter); may release HOLD claims | QIDP |
| POST | `/evv-visits` | Create EVV visit; provisional units computed | DSP |
| GET | `/evv-visits/{visitId}` | Get an EVV visit | Any |
| GET | `/evv-visits` | List EVV visits (filtered) | Any |
| POST | `/evv-visits/{visitId}/verify` | Verify pending visit; waterfall allocation debits authorizations | QIDP |
| POST | `/evv-visits/{visitId}/flag-exception` | Flag a pending visit as exception | QIDP |
| POST | `/evv-visits/{visitId}/resolve-exception` | Resolve exception with adjusted minutes | QIDP |
| POST | `/evv-visits/{visitId}/reject` | Reject a PENDING or EXCEPTION visit | QIDP |
| POST | `/transport-trips` | Schedule a day-program transport trip | AgencyAdmin |
| GET | `/transport-trips/{tripId}` | Get a transport trip | Any |
| GET | `/transport-trips` | List transport trips (filtered) | Any |
| POST | `/transport-trips/{tripId}/cancel` | Cancel a scheduled trip | AgencyAdmin |
| POST | `/claims` | Generate claim by sweeping VERIFIED + UNBILLED visits in period | BillingSpecialist |
| GET | `/claims/{claimId}` | Get a claim | Any |
| GET | `/claims` | List claims (filtered) | Any |
| POST | `/claims/{claimId}/submit` | Submit claim (posture gate; from DRAFT or CORRECTED) | BillingSpecialist |
| POST | `/claims/{claimId}/post-payment` | Post remittance; full payment runs recoupment netting | BillingSpecialist |
| POST | `/claims/{claimId}/deny` | Record payer denial | BillingSpecialist |
| POST | `/claims/{claimId}/correct` | Correct a denied claim's lines | BillingSpecialist |
| POST | `/claims/{claimId}/void` | Void a paid claim; cash reversal, visits unbilled, units released LIFO | BillingSpecialist |

## 5. Error Code Catalogue

The table below enumerates every 4xx error identifier the system may return, together with its HTTP status code; an unexpected server failure additionally returns `ERR_INTERNAL` (HTTP 500) in the standard error envelope. Trigger conditions are specified in §2 and §3 alongside the rules that produce them.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_ROLE_IDENTITY_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_INDIVIDUAL_NOT_ENROLLED | 409 |
| ERR_ISP_NOT_ACTIVE | 409 |
| ERR_HOME_NOT_ACTIVE | 409 |
| ERR_AUTHORIZATION_NOT_ACTIVE | 409 |
| ERR_MED_ORDER_DISCONTINUED | 409 |
| ERR_CERTIFICATION_MISSING | 403 |
| ERR_WITNESS_REQUIRED | 400 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_BED_OVERLAP | 409 |
| ERR_VEHICLE_OVERLAP | 409 |
| ERR_OUT_OF_SPAN | 422 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_HOME_POSTURE_CRITICAL | 409 |
| ERR_HOME_CAPACITY_EXCEEDED | 409 |
| ERR_VEHICLE_CAPACITY_EXCEEDED | 409 |
| ERR_NO_DAY_PROG_AUTHORIZATION | 409 |
| ERR_UNIT_CAP_EXCEEDED | 422 |
| ERR_INDIVIDUAL_CAP_EXCEEDED | 422 |
| ERR_AUTHORIZATION_UNITS_EXHAUSTED | 409 |
| ERR_NO_BILLABLE_VISITS | 422 |
| ERR_OVERPAYMENT | 400 |
| ERR_CLAIM_PERIOD_INVALID | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_MOVE_IN_FUTURE | 422 |
| ERR_RESTRICTIVE_INTERVENTION_MISMATCH | 400 |
| ERR_HOME_OCCUPIED | 409 |

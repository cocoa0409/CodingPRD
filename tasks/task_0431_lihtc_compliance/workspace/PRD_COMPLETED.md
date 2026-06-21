# LIHTC Compliance API — Product Requirements Document

## 1. Introduction

The Low-Income Housing Tax Credit (LIHTC) program is the principal federal mechanism for financing affordable rental housing in the United States, and the compliance obligations that follow an allocation of credit stretch across a fifteen-year compliance period. Property owners must demonstrate, continuously, that the units they pledged as affordable are in fact occupied by income-qualified households at rents that stay below regulated ceilings, while the state Housing Finance Agency that administers the allocation must independently verify that posture through physical inspections, income-certification review, and the filing of noncompliance reports (IRS Form 8823) when the property drifts out of compliance.

This API models that two-party compliance lifecycle as a system of record. It tracks projects, their constituent buildings and residential units, the households that occupy them, and the income certifications and leases that bind households to units. On top of that data model it enforces the regulatory arithmetic — income and rent limits by Area Median Income band, the minimum set-aside test, the applicable fraction and qualified basis that determine the annual credit, and the dual-variant first-year credit calculation that distinguishes a forward-looking allocation estimate from a chronological year-one true-up. The system also governs the credit-delivery lifecycle (Form 8609 issuance, revocation, and recapture), the inspection lifecycle under the Uniform Physical Condition Standards (UPCS), and the noncompliance lifecycle that connects findings to 8823 filings. A strict segregation-of-duties model separates the owner's operational role from the agency's oversight role, so that the party that performs work is never the party that reports a violation against it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API. The domain-specific business workflows that these principles support are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`; for this purpose an `X-User-ID` that is absent, empty, or only whitespace is treated as missing, and an `X-User-Role` whose value is not exactly one of the two recognized roles is treated as malformed and likewise rejected with `ERR_UNAUTHENTICATED` (not `ERR_UNAUTHORIZED`). This authentication check is performed first, before any role-authorization check, body parsing, or resource resolution, so an unauthenticated request is rejected with `ERR_UNAUTHENTICATED` regardless of any other defect in the request. This header requirement is universal: even the test-driving clock endpoint requires both headers.

The system recognizes exactly two roles, spelled precisely as `OwnerAgent` and `StateHFA`. The `OwnerAgent` is the property owner or management agent. It creates and operates the LIHTC project and its buildings, units, and households; it certifies tenant income; it leases units; and it corrects findings. The `StateHFA` is the State Housing Finance Agency, the independent oversight authority that approves or rejects certifications, certifies the minimum set-aside, issues and revokes and recaptures Form 8609 credit certificates, schedules and conducts UPCS inspections, and files Form 8823 noncompliance reports. When a request is well-authenticated but the acting role is not permitted to perform the requested operation, the system rejects it with `ERR_UNAUTHORIZED`.

Both roles carry an **opaque** identity. When `X-User-Role` is `OwnerAgent`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a scaffold transition writes it — for example, an agent's identifier may become the `origin_agent_id` recorded on a `Finding` whose underlying chain that agent authored — but the server does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `StateHFA`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (again as the `origin_agent_id` on a `Finding` that a `StateHFA` action creates) but does not compare it to any entity's `id`. The one place these opaque identifiers are compared to each other rather than to an entity is the segregation-of-duties check described in Section 3.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100 by clamping — a supplied `limit` below 1 is raised to 1 and a supplied `limit` above 100 is lowered to 100 rather than rejected. The `offset` parameter specifies how many items to skip from the front of the result and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Topology and Reference Discovery

The system uses a **flat topology**: every entity type is its own top-level collection, and there are no nested resource URLs. Relationships between entities are expressed as foreign-key fields carried in request bodies — a building names its owning project through `project_id`, a unit names its building through `building_id`, a household names its project through `project_id`, and a certification names both its household and unit through `household_id` and `unit_id`. Because the topology is flat, the reverse direction of each relationship is discovered through filtered list endpoints rather than nested paths: buildings can be listed filtered by `project_id`, units by `building_id`, households by `project_id`, certifications by `unit_id` or `household_id`, leases by `unit_id` or `household_id`, inspections by `building_id`, Form 8609 certificates by `building_id`, and findings by `project_id`, `building_id`, or `inspection_id`.

Whenever a request references resources — whether by an `id` in the URL path or by a foreign-key identifier in the body — the system resolves every referenced resource before applying any business rule. Resolution proceeds left-to-right across the referenced identifiers in this order: project, building, unit, household, certification, inspection, finding. If any referenced identifier fails to resolve to an existing resource, the request is rejected immediately with `ERR_NOT_FOUND`, and later identifiers are not examined. A malformed body, a missing required field, or an invalid enum or type value is rejected with `ERR_VALIDATION`.

### 2.5. Common Resource Properties

All entities in this system are first-class records that carry the full common-field set. Every resource exposes:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified. It is refreshed on any mutation of the resource.
- `version` — a system-managed integer that begins at its initial value of 1 on creation and increments by one on every mutation of the resource. It underpins the optimistic concurrency control described in Section 2.7.

When a derived field on a resource changes as the consequence of a recomputation — for example when a building's `applicable_fraction`, `qualified_basis_cents`, or `annual_credit_cents` are recomputed, or when a project's `posture` or `open_finding_count` change — that recomputation is a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments accordingly. This mutation is conditional on a derived value actually changing: a recomputation that recomputes the same values it already held leaves the resource's `updated_at` and `version` untouched. (An explicit status-transition write — for example a project's own `status` advancing or a building's own `credit_status` advancing on an 8609 issuance — always mutates the resource regardless of whether a derived field changes.)

### 2.6. Precision, Rounding, and Monetary Representation

All monetary quantities in this system are integers denominated in **cents**; there are no fractional-cent values. The two classes of rounding used by the regulatory arithmetic are applied exactly as specified and never interchanged:

- **Money derived by division is always floored** (rounded down toward zero / `ROUND_DOWN`). Income limits, gross rent ceilings, qualified basis, and credit amounts are all computed by flooring at each named division step, in the exact order the calculation lists those steps. Where a calculation has several floored steps, each intermediate result is floored before it feeds the next step; the flooring is not deferred to the end.
- **Fractions are rounded half-up to a fixed number of decimal places.** The applicable fraction and the first-year fractions are carried to 4 decimal places using round-half-up. The average-income designation used in the set-aside test is carried to 2 decimal places using round-half-up.

These two conventions — floor for derived money, round-half-up for fractions — are the only rounding behaviors in the system.

### 2.7. Optimistic Concurrency Control on Building Credit

Two credit-lifecycle operations on a building are guarded by optimistic concurrency control to prevent a writer from acting on a stale view of the building's credit state. Both operate on the `Building` entity and both key off the building's `version`.

The first guarded operation is the issuance of a **FINAL** Form 8609. A request that issues a FINAL 8609 must carry the field `expected_building_version`, and its value must equal the target building's current `version`. If another writer has advanced the building's `version` since the client last read it — for instance by having already issued the FINAL 8609 and pinned the chronological fraction — then the requesting client's view is stale and the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412). The PROVISIONAL issuance of a Form 8609 does not take a version field and is not subject to this check.

The second guarded operation is **recapture**. A recapture request must carry `expected_building_version` matching the building's current `version`; if the building's `version` has advanced since the client last observed it (for example because a FINAL 8609 was just re-issued), the recapture carries a stale version and is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than FINAL 8609 issuance and recapture takes a version field, and neither check is framed in terms of requests arriving together — each is purely a comparison of the client's last-observed version against the server's current version.

### 2.8. Compliance Posture and Hierarchical Consistency

Compliance is computed and propagated upward through the hierarchy rather than stored independently at each level. The lowest-level signal is a `Finding`, which records a discrete noncompliance event against a project and building. A project's `posture` — one of `COMPLIANT`, `AT_RISK`, or `NONCOMPLIANT` — and its `open_finding_count` are both **computed** fields, recomputed from the findings under the project whenever any finding's status changes, whenever a unit is disqualified, and whenever the set-aside is certified.

The `open_finding_count` is the number of unresolved findings under the project, where a finding counts as unresolved while its `status` is either `OPEN` or `REPORTED_8823`; findings in `CORRECTED` status are excluded. Filing an 8823 against a finding keeps that finding unresolved, so reporting does not change the count — only correcting a finding decrements it. The `posture` is determined by precedence: if at least one finding under the project is in `REPORTED_8823` status, the posture is `NONCOMPLIANT`; otherwise, if at least one finding is in `OPEN` status, the posture is `AT_RISK`; otherwise the posture is `COMPLIANT`. In words, `NONCOMPLIANT` dominates `AT_RISK`, which dominates `COMPLIANT`.

Whenever a unit's low-income contribution changes, the building it belongs to must be reconciled: the building's `applicable_fraction`, `qualified_basis_cents`, and `annual_credit_cents` are recomputed (Section 3 details the formula), and that recomputation mutates the building. When a finding is created, reported, or corrected, the owning project's `open_finding_count` and `posture` are recomputed, and that recomputation mutates the project. These reconciliations are performed automatically by the server as the side effect of the triggering operation; a client does not issue a separate request against the parent to keep it in step.

## 3. Business Logic & Workflows

### 3.1. Projects, Buildings, and Units: the Compliance Backbone

A LIHTC engagement begins when an `OwnerAgent` creates a **project**. The create payload supplies a `name`, the area median income baseline `area_median_income_cents` (the annual AMI for a four-person household, in cents, which must be at least 100000 cents and serves as the baseline for every unit income limit in the project), the elected minimum set-aside test `minimum_set_aside`, and the `placed_in_service_date` that marks the start of the compliance period. On creation the project's `status` is `DRAFT`, its `posture` is `COMPLIANT`, and its `open_finding_count` is 0. The `minimum_set_aside` is one of three elected tests: `TWENTY_FIFTY`, `FORTY_SIXTY`, or `AVERAGE_INCOME`. The project's `status` advances through `DRAFT`, `SET_ASIDE_MET`, `CREDIT_PERIOD`, and `COMPLIANCE_PERIOD`, with `CLOSED` as the terminal state; the transitions between these are described in Section 3.7.

An `OwnerAgent` adds **buildings** to a project by supplying the owning `project_id` together with the building's `bin` (its Building Identification Number, unique within the project), the depreciable `eligible_basis_cents` for credit (which must be at least 0), the `credit_type` (`NINE_PERCENT` or `FOUR_PERCENT`, the applicable credit-percentage class), the `total_residential_units` count (at least 1), and the `total_residential_sqft` of residential floor space (at least 1). A new building starts with `credit_status` of `PRE_ALLOCATION` and with its computed credit fields `applicable_fraction`, `qualified_basis_cents`, and `annual_credit_cents` all at 0; its `first_year_fraction` is likewise 0 until an 8609 is issued. The building also carries the credit-lifecycle states `PROVISIONAL_8609`, `FINAL_8609`, and the terminal `RECAPTURED`, discussed in Section 3.6.

An `OwnerAgent` creates **units** under a building by supplying the owning `building_id`, the `unit_number` (unique within the building), the `bedroom_count` (an integer between 0 and 3 inclusive, where 0 denotes a studio), the unit `sqft` (at least 1), the monthly `utility_allowance_cents` (at least 0), and the targeted AMI band `ami_designation`. The `ami_designation` is one of `AMI_40`, `AMI_50`, `AMI_60`, `AMI_80`, or `MARKET`; a `MARKET` unit is never a low-income unit and never carries income or rent limits. At creation, a unit's `li_status` is `VACANT_NEVER_OCCUPIED` and its computed `is_low_income_counted` flag is false. A non-`MARKET` unit's income and rent limits — `income_limit_cents`, `gross_rent_ceiling_cents`, and `net_max_rent_cents` — are computed on creation as described next; a `MARKET` unit skips the computation entirely and leaves all three of those fields null.

The income-and-rent-limit computation for a single non-`MARKET` unit proceeds in the following pinned order, all in integer cents, using the owning project's `area_median_income_cents` as the AMI baseline. First, an AMI percentage is selected from the unit's `ami_designation`: 40 for `AMI_40`, 50 for `AMI_50`, 60 for `AMI_60`, and 80 for `AMI_80`. Second, an imputed household size is derived from `bedroom_count`: for a studio (a `bedroom_count` of 0) the imputed size is 1; otherwise it is the `bedroom_count` multiplied by 1.5 and rounded to the nearest whole number, but never less than 1. Third, a household-size factor in basis points is looked up from the imputed household size, using the schedule where an imputed size of 1 maps to 7000, 2 maps to 8000, 3 maps to 9000, 4 maps to 10000, 5 maps to 10800, and 6 maps to 11600. The `income_limit_cents` is then the AMI baseline multiplied by the AMI percentage divided by 100, multiplied by the household-size factor divided by 10000, with the result floored. The `gross_rent_ceiling_cents` is the `income_limit_cents` multiplied by 30, divided by 100, divided by 12, floored — that is, thirty percent of the annual income limit expressed as a monthly figure, floored. Finally, the `net_max_rent_cents` is the `gross_rent_ceiling_cents` minus the unit's `utility_allowance_cents`. These limits are recomputed whenever the project's `area_median_income_cents` changes or the unit's `ami_designation`, `bedroom_count`, or `utility_allowance_cents` change.

### 3.2. Households and the Student Rule

Before a household can occupy a unit it must be registered. An `OwnerAgent` registers a **household** within a project by supplying the `project_id`, the `head_name`, the `household_size` (at least 1), and the boolean `all_full_time_students` flag indicating whether every member of the household is a full-time student. The payload may also carry a `student_exception`, which defaults to `NONE` and is otherwise one of `TANF`, `JOB_TRAINING`, `SINGLE_PARENT`, `MARRIED_JOINT_FILER`, or `FORMER_FOSTER` — each a recognized exception that rescues an all-student household.

The computed `student_eligible` flag captures the student rule. A household is student-ineligible — `student_eligible` is false — in exactly one situation: when `all_full_time_students` is true and `student_exception` is `NONE`. In every other case `student_eligible` is true: a household that is not entirely full-time students is eligible regardless of the exception value, and an all-student household that carries any exception other than `NONE` is rescued and therefore eligible. The consequence of student-ineligibility is felt at certification submit time, described in Section 3.3.

### 3.3. Income Certification: Drafting, Submission, and Approval

A unit becomes a counted low-income unit only through an approved income certification. An `OwnerAgent` creates a **certification** by supplying the `household_id` of the household being certified, the `unit_id` of the unit the certification is for, the `cert_type` (`INITIAL` for move-in qualification or `RECERT` for annual recertification), the certified `annual_income_cents` (at least 0), and the `effective_date`. A new certification is created in `DRAFT` status. Its `status` lifecycle runs `DRAFT`, `SUBMITTED`, then either `APPROVED` or `REJECTED`, with a `SUBMITTED` certification able to return to `DRAFT` through a revise action.

When the `OwnerAgent` submits a certification, the certification advances from `DRAFT` to `SUBMITTED`, but only after two preconditions are met. First, the certified household must be student-eligible; if the household's `student_eligible` is false, the submission is rejected with `ERR_STUDENT_INELIGIBLE`. Second, for an `INITIAL` certification only, the certified `annual_income_cents` must not exceed the unit's `income_limit_cents` for its designation and bedroom count; if the income is above that limit, the submission is rejected with `ERR_INCOME_OVER_LIMIT`. (A `RECERT` is not subject to the move-in income limit at submit; over-income on recertification is handled through the over-income threshold below rather than by blocking submission.) Submission also recomputes two certification fields. The `over_income_threshold_cents` is set to the unit's `income_limit_cents` multiplied by 140, divided by 100, floored — that is, 140 percent of the income limit, floored. The `is_over_income` flag is set true only when the `cert_type` is `RECERT` and the certified `annual_income_cents` is strictly greater than `over_income_threshold_cents`; income exactly equal to 140 percent of the limit is not over-income, because the boundary is strict.

An `OwnerAgent` may send a `SUBMITTED` certification back to `DRAFT` with a revise action, which simply returns the certification to `DRAFT` so it can be edited and resubmitted. A submitted certification can only be revised while it is in `SUBMITTED`.

A `StateHFA` decides a `SUBMITTED` certification by approving or rejecting it, supplying a `decision` in the request body. A decision to reject moves the certification to `REJECTED` and changes no unit state. A decision to approve moves the certification to `APPROVED` and drives the unit's low-income status according to the kind of certification:

- Approving an `INITIAL` certification on a designated low-income unit (a non-`MARKET` unit) transitions that unit's `li_status` from `VACANT_NEVER_OCCUPIED` to `QUALIFIED`. The unit's qualification arises from an approved `INITIAL` certification whose `annual_income_cents` is within the unit's `income_limit_cents`.
- Approving a `RECERT` certification whose `is_over_income` is true transitions the unit's `li_status` from `QUALIFIED` to `OVER_INCOME`. The unit remains counted as low-income in this state (its `is_low_income_counted` stays true), but this transition **arms the available-unit rule** for the building: the next available comparable-or-smaller unit must be rented to a qualified household.
- Approving a `RECERT` certification whose `is_over_income` is false on a unit currently in `OVER_INCOME` transitions the unit's `li_status` from `OVER_INCOME` back to `QUALIFIED`, which disarms that unit's contribution to the available-unit rule.

After any approval that changes a unit's low-income contribution, the owning building's `applicable_fraction`, `qualified_basis_cents`, and `annual_credit_cents` are recomputed as the derived-field reconciliation described in Section 3.5.

### 3.4. Leasing, Rent Ceilings, and Occupancy Intervals

An `OwnerAgent` **leases** a unit to a household, creating a `Lease`. The lease body supplies the `household_id` of the leasing household, the tenant-paid contract `monthly_rent_cents` (at least 0), the `rent_start_date` (the inclusive occupancy start), and the `rent_end_date` (the exclusive occupancy end); the `unit_id` is taken from the targeted unit rather than the body. A lease is created in `ACTIVE` status and is an append-only occupancy record — there is no lease-termination action in this version, so `ACTIVE` is the only lease status. Leasing a `MARKET` unit transitions that unit's `li_status` from `VACANT_NEVER_OCCUPIED` to `MARKET_RENTED`.

Several checks guard a lease. The tenant-paid `monthly_rent_cents` must not exceed the unit's `net_max_rent_cents` (the unit's net rent ceiling, already net of the utility allowance); a lease whose rent is above that ceiling is rejected with `ERR_RENT_OVER_LIMIT`, the rent-plus-utility-allowance overcharge guard. Occupancy intervals on the same unit may not collide: the lease's occupancy interval is the half-open interval running from `rent_start_date` inclusive up to `rent_end_date` exclusive. A new lease overlaps an existing `ACTIVE` lease on the same unit when the new start is before the existing end and the existing start is before the new end; in that case the new lease is rejected with `ERR_LEASE_OVERLAP`. Because the interval is half-open with zero buffer, a back-to-back lease that begins exactly at a prior lease's `rent_end_date` does not overlap and is permitted. Finally, the available-unit rule guards leasing: while any unit in the building is in `OVER_INCOME` status, a comparable-or-smaller unit — one whose `bedroom_count` is less than or equal to the over-income unit's `bedroom_count` — may not be leased to a non-qualified household (a `MARKET` household or a student-ineligible one); such a lease is rejected with `ERR_AVAILABLE_UNIT_RULE`.

### 3.5. Building Applicable Fraction, Qualified Basis, and Annual Credit

A building's credit is derived from how much of it is occupied by counted low-income units. The flag `is_low_income_counted` on a unit is true exactly when the unit's `li_status` is `QUALIFIED` or `OVER_INCOME`; units that are `DISQUALIFIED`, `MARKET_RENTED`, or `VACANT_NEVER_OCCUPIED` are not counted. This flag drives the numerator of the building's applicable fraction.

The building reconciliation recomputes, in this pinned order, whenever any unit's `li_status` changes under the building, on any `INITIAL` or `RECERT` approval, and on recapture. First, the unit fraction is the count of the building's counted low-income units divided by the building's `total_residential_units`, rounded half-up to 4 decimal places. Second, the floor-space fraction is the sum of the `sqft` of the building's counted low-income units divided by the building's `total_residential_sqft`, rounded half-up to 4 decimal places. Third, the building's `applicable_fraction` is the smaller of the unit fraction and the floor-space fraction. Fourth, the `qualified_basis_cents` is the building's `eligible_basis_cents` multiplied by the `applicable_fraction`, floored. Fifth, a credit factor in basis points is taken from the building's `credit_type` — 900 basis points for `NINE_PERCENT` and 400 basis points for `FOUR_PERCENT` — and the `annual_credit_cents` is the `qualified_basis_cents` multiplied by that credit factor divided by 10000, floored. The evaluation order is fixed: fraction first, then qualified basis, then credit.

### 3.6. Form 8609 Credit Delivery, Revocation, and Recapture

The credit-delivery lifecycle moves a building's `credit_status` from `PRE_ALLOCATION` through `PROVISIONAL_8609` to `FINAL_8609`, with a `RECAPTURED` terminal state and a defined branch back from `FINAL_8609` to `PROVISIONAL_8609`. All four transitions are `StateHFA` actions, and each issuance of an 8609 produces a `Form8609` record.

A `StateHFA` issues a **PROVISIONAL** Form 8609 to move a building from `PRE_ALLOCATION` to `PROVISIONAL_8609`. The issuance supplies the `issuance_type` of `PROVISIONAL`, and it is permitted only when the building is in `PRE_ALLOCATION` and the owning project's `status` is `SET_ASIDE_MET` or `CREDIT_PERIOD`; an issuance against a project that has not reached the set-aside-met state is rejected with `ERR_SET_ASIDE_NOT_MET`. Issuing the PROVISIONAL 8609 pins the building's `first_year_fraction` to the **forward-looking provisional fraction**, which treats every designated low-income unit as qualified for the full year regardless of actual month-by-month occupancy: the provisional fraction is the count of the building's non-`MARKET` (designated) units divided by `total_residential_units`, rounded half-up to 4 decimal places. The building's `annual_credit_cents` is then recomputed as the `eligible_basis_cents` multiplied by that provisional fraction, multiplied by the credit factor in basis points (900 for `NINE_PERCENT`, 400 for `FOUR_PERCENT`) divided by 10000, floored. A `Form8609` snapshot is created with `issuance_type` of `PROVISIONAL` and `status` of `ISSUED`; the snapshot records the `allocated_fraction` (a snapshot of the building's `first_year_fraction` at issuance) and the `allocated_annual_credit_cents` (a snapshot of the building's `annual_credit_cents` at issuance).

A `StateHFA` issues a **FINAL** Form 8609 to move a building from `PROVISIONAL_8609` to `FINAL_8609`. The issuance supplies the `issuance_type` of `FINAL`, the `monthly_qualified_units` array, and the `expected_building_version`. The building must be in `PROVISIONAL_8609`, and the optimistic-concurrency guard from Section 2.7 applies — `expected_building_version` must match the building's current `version`, or the request is rejected with `ERR_STALE_VERSION`. The FINAL issuance pins the building's `first_year_fraction` to the **final chronological fraction**, which is the average of the twelve month-end qualified fractions: for each of the twelve months, the month's qualified-unit count (supplied as the twelve-element `monthly_qualified_units` array in the request body) is divided by `total_residential_units`; those twelve monthly fractions are summed and divided by 12, and that average is rounded half-up to 4 decimal places. This is deliberately the same underlying data viewed through a different algorithm than the provisional variant, so the final fraction and the resulting `annual_credit_cents` generally differ from the provisional ones. The building's `annual_credit_cents` is recomputed from the final `first_year_fraction`, a `Form8609` snapshot with `issuance_type` of `FINAL` and `status` of `ISSUED` is created, and the building's `version` increments by one.

A `StateHFA` may **revoke a FINAL** 8609, branching the building back from `FINAL_8609` to `PROVISIONAL_8609`. This sets the FINAL `Form8609`'s `status` to `REVOKED`, restores the building's `first_year_fraction` to the provisional fraction, and recomputes `annual_credit_cents` accordingly.

A `StateHFA` may **recapture** credit, moving a building from `FINAL_8609` to the terminal `RECAPTURED`. Recapture is permitted only when the building is in `FINAL_8609`, when the owning project's `posture` is `NONCOMPLIANT` (otherwise the request is rejected with `ERR_RECAPTURE_REQUIRES_NONCOMPLIANT`), and when the supplied `expected_building_version` matches the building's current `version` (otherwise `ERR_STALE_VERSION` as described in Section 2.7). Recapture is a compensating action: it sets the building's `annual_credit_cents`, `applicable_fraction`, and `qualified_basis_cents` all to 0, sets the FINAL `Form8609`'s `status` to `REVOKED`, and increments the building's `version` by one.

### 3.7. Set-Aside Certification and the Project Status Lifecycle

The minimum set-aside test is a design-level test of how the project's units are designated, evaluated over unit counts and not over occupancy or current `li_status`. Its denominator is the sum of `total_residential_units` across all buildings of the project. A `StateHFA` certifies the set-aside to advance a project from `DRAFT` to `SET_ASIDE_MET`; if the elected test is not satisfied, the certification is rejected with `ERR_SET_ASIDE_NOT_MET`. The very same computed result is the precondition the 8609-issuance check reuses, so the set-aside outcome is consistent between project certification and credit issuance.

The test is evaluated according to the project's elected `minimum_set_aside`:

- Under `TWENTY_FIFTY`, the designated units are those whose `ami_designation` is `AMI_40` or `AMI_50`. The test is satisfied when the count of designated units is at least 25 percent of the total residential units, evaluated by cross-multiplication: the designated count multiplied by 100 is at least 25 multiplied by the total units.
- Under `FORTY_SIXTY`, the designated units are those whose `ami_designation` is `AMI_40`, `AMI_50`, or `AMI_60`. The test is satisfied when the designated count multiplied by 100 is at least 40 multiplied by the total units (at least 40 percent).
- Under `AVERAGE_INCOME`, the low-income units are those whose `ami_designation` is `AMI_40`, `AMI_50`, `AMI_60`, or `AMI_80`. Each contributes its band percentage (40, 50, 60, or 80). The average designation is the sum of those band percentages divided by the count of low-income units, rounded half-up to 2 decimal places. The test is satisfied when there is at least one low-income unit and the average designation is at most 60.00.

Once the set-aside is met, a `StateHFA` advances the project from `SET_ASIDE_MET` to `CREDIT_PERIOD`, but only when at least one building under the project has reached `FINAL_8609`; otherwise the advance is rejected with `ERR_INVALID_STATE`. From `CREDIT_PERIOD` a `StateHFA` advances the project to `COMPLIANCE_PERIOD`, and from `COMPLIANCE_PERIOD` a `StateHFA` closes the project to the terminal `CLOSED` state — but a project may close only when its `open_finding_count` is 0; a close attempted while findings remain unresolved is rejected with `ERR_OPEN_FINDINGS_BLOCK_CLOSE`. Certifying the set-aside also recomputes the project's `posture`.

### 3.8. UPCS Inspections and the Inspection Lifecycle

A `StateHFA` schedules a **UPCS inspection** of a building by supplying the `building_id`, the inspection window bounds `window_start` and `window_end`, the `inspected_on` date, the `deduction_points` array (one integer deduction for each UPCS deficiency found), and the optional `has_exigent_health_safety` flag (defaulting to false) indicating that a life-threatening deficiency was found. A scheduled inspection starts in `SCHEDULED` status; its lifecycle is `SCHEDULED`, then `CONDUCTED`, then `CLOSED`.

Inspection windows on the same building must be separated. The inspection window is the closed interval running from `window_start` to `window_end` inclusive, and two inspections on one building must be at least a seven-day separation buffer apart on each side. Concretely, a new window conflicts with an existing window on the same building when the new start is at or before the existing end plus seven days and the existing start is at or before the new end plus seven days; if any existing inspection on the building conflicts under that buffered, closed-interval rule, the new inspection is rejected with `ERR_INSPECTION_WINDOW_CONFLICT`. (This is intentionally a different rule from the lease overlap: leases use half-open intervals with zero buffer, while inspection windows are closed intervals expanded by a seven-day buffer.)

When a `StateHFA` **conducts** a `SCHEDULED` inspection, it advances to `CONDUCTED` and the score and result are computed. The `score` is 100 minus the sum of all the `deduction_points`, floored at 0 (it never goes negative). The `result` is `FAIL` if `has_exigent_health_safety` is true or the `score` is below the passing threshold of 60; otherwise the `result` is `PASS`. If the result is `FAIL`, the system creates a `Finding` whose `category` is `UPCS_FAIL` and whose `status` is `OPEN`, recording the conducting `StateHFA`'s `X-User-ID` as the finding's `origin_agent_id`; that new finding bumps the owning project's `open_finding_count` and recomputes the project's `posture` as the cascade described in Section 2.8.

When a `StateHFA` **closes** a `CONDUCTED` inspection, it advances to the terminal `CLOSED` status, but only when no finding linked to that inspection (matching its `inspection_id`) is still in `OPEN` or `REPORTED_8823` status; a close attempted while a linked finding remains unresolved is rejected with `ERR_OPEN_FINDINGS_BLOCK_CLOSE`.

### 3.9. Unit Disqualification, Findings, and the 8823 Lifecycle

Beyond inspections, the agency can enforce the available-unit rule directly. A `StateHFA` **disqualifies** a unit that is in `QUALIFIED` or `OVER_INCOME` status — for example when an audit finds an available-unit-rule breach — supplying the `discovered_on` date. Disqualification drives the unit's `li_status` to the terminal `DISQUALIFIED` and sets `is_low_income_counted` to false. It then cascades: the owning building's `applicable_fraction`, `qualified_basis_cents`, and `annual_credit_cents` are recomputed (Section 3.5), and a new `Finding` is created with `category` of `AVAILABLE_UNIT_VIOLATION`, recording the acting `StateHFA`'s `X-User-ID` as the finding's `origin_agent_id`. That finding in turn bumps the project's `open_finding_count` and recomputes the project's `posture`. Both the `QUALIFIED → DISQUALIFIED` and the `OVER_INCOME → DISQUALIFIED` paths produce the same cascade and the same `AVAILABLE_UNIT_VIOLATION` finding.

A **finding** is the system's record of a discrete noncompliance event. Every finding carries the `project_id` and `building_id` it is logged against and an `inspection_id` that points to the originating inspection for a `UPCS_FAIL` finding or is null for findings raised outside an inspection (such as an `AVAILABLE_UNIT_VIOLATION` produced by a disqualify action). A finding's `category` is one of `OVER_INCOME_UNCURED`, `STUDENT_VIOLATION`, `RENT_OVERCHARGE`, `UPCS_FAIL`, `SET_ASIDE_FAILURE`, or `AVAILABLE_UNIT_VIOLATION`, and it records the `discovered_on` date. A finding's `status` runs from `OPEN` to either `CORRECTED` or `REPORTED_8823`, and from `REPORTED_8823` it can still move to `CORRECTED` when the property comes back into compliance.

A `StateHFA` **files Form 8823** against an `OPEN` finding, advancing it from `OPEN` to `REPORTED_8823`. This is the point where segregation of duties is enforced: the acting `StateHFA`'s `X-User-ID` must differ from the finding's `origin_agent_id` — the opaque identifier of the actor who conducted the inspection or otherwise created the underlying chain — so that the agency that performed the originating work cannot self-clear by being the one to report it. A report by that same originating actor is rejected with `ERR_SEGREGATION_OF_DUTIES`. Filing the 8823 sets the finding's `reported_8823_on` to the current clock time and recomputes the project's `posture`, which remains `NONCOMPLIANT` while any finding is `OPEN` or `REPORTED_8823`. Because reporting leaves the finding unresolved, it does not change `open_finding_count`.

An `OwnerAgent` **corrects** a finding, moving it to `CORRECTED` from either `OPEN` or `REPORTED_8823` once the noncompliance is cured. Correcting a finding decrements the project's `open_finding_count` by one and recomputes the project's `posture`. (Note the role split that segregation of duties enforces: the agency files the 8823, and the owner corrects the finding.)

### 3.10. The Logical Clock

The system stamps date-bearing events — a finding's `discovered_on` where applicable and a finding's `reported_8823_on` — against a logical clock rather than real wall-clock time. Both an `OwnerAgent` and a `StateHFA` may advance the clock by supplying a `to_iso8601` instant; this sets the logical clock to that instant. The server's startup default for the clock is `2026-01-01T00:00:00Z`, and before any explicit set the clock reads exactly that default and never the real wall-clock time.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code; this includes creating a project, building, unit, household, certification, lease, inspection, and the issuance of a Form 8609. All other state-changing operations — the action endpoints that drive transitions, and the logical-clock set — return a `200 OK` status code. List and get endpoints return `200 OK`. Each request must carry the `X-User-ID` and `X-User-Role` headers described in Section 2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | OwnerAgent, StateHFA |
| POST | `/projects` | Create a LIHTC project | OwnerAgent |
| GET | `/projects` | List projects (paginated) | OwnerAgent, StateHFA |
| GET | `/projects/{id}` | Get a project | OwnerAgent, StateHFA |
| POST | `/projects/{id}/certify-set-aside` | Certify the minimum set-aside is met | StateHFA |
| POST | `/projects/{id}/begin-credit-period` | Advance project to the credit period | StateHFA |
| POST | `/projects/{id}/begin-compliance-period` | Advance project to the compliance period | StateHFA |
| POST | `/projects/{id}/close` | Close a project | StateHFA |
| POST | `/buildings` | Create a building under a project | OwnerAgent |
| GET | `/buildings` | List buildings, optionally filtered by `project_id` | OwnerAgent, StateHFA |
| GET | `/buildings/{id}` | Get a building | OwnerAgent, StateHFA |
| POST | `/buildings/{id}/form8609` | Issue a Form 8609 (PROVISIONAL or FINAL) | StateHFA |
| GET | `/form8609s` | List Form 8609 certificates, optionally filtered by `building_id` | OwnerAgent, StateHFA |
| GET | `/form8609s/{id}` | Get a Form 8609 certificate | OwnerAgent, StateHFA |
| POST | `/buildings/{id}/revoke-final` | Revoke a FINAL 8609 | StateHFA |
| POST | `/buildings/{id}/recapture` | Recapture credit on a building | StateHFA |
| POST | `/units` | Create a unit under a building | OwnerAgent |
| GET | `/units` | List units, optionally filtered by `building_id` | OwnerAgent, StateHFA |
| GET | `/units/{id}` | Get a unit | OwnerAgent, StateHFA |
| POST | `/units/{id}/lease` | Lease a unit to a household | OwnerAgent |
| POST | `/units/{id}/disqualify` | Disqualify a unit (enforcement) | StateHFA |
| GET | `/leases` | List leases, optionally filtered by `unit_id` or `household_id` | OwnerAgent, StateHFA |
| GET | `/leases/{id}` | Get a lease | OwnerAgent, StateHFA |
| POST | `/households` | Register a household within a project | OwnerAgent |
| GET | `/households` | List households, optionally filtered by `project_id` | OwnerAgent, StateHFA |
| GET | `/households/{id}` | Get a household | OwnerAgent, StateHFA |
| POST | `/certifications` | Create an income certification | OwnerAgent |
| GET | `/certifications` | List certifications, optionally filtered by `unit_id` or `household_id` | OwnerAgent, StateHFA |
| GET | `/certifications/{id}` | Get a certification | OwnerAgent, StateHFA |
| POST | `/certifications/{id}/submit` | Submit a DRAFT certification | OwnerAgent |
| POST | `/certifications/{id}/revise` | Send a SUBMITTED certification back to DRAFT | OwnerAgent |
| POST | `/certifications/{id}/approve` | Approve or reject a SUBMITTED certification | StateHFA |
| POST | `/inspections` | Schedule a UPCS inspection for a building | StateHFA |
| GET | `/inspections` | List inspections, optionally filtered by `building_id` | OwnerAgent, StateHFA |
| GET | `/inspections/{id}` | Get an inspection | OwnerAgent, StateHFA |
| POST | `/inspections/{id}/conduct` | Conduct a scheduled inspection | StateHFA |
| POST | `/inspections/{id}/close` | Close a conducted inspection | StateHFA |
| GET | `/findings` | List findings, optionally filtered by `project_id`, `building_id`, or `inspection_id` | OwnerAgent, StateHFA |
| GET | `/findings/{id}` | Get a finding | OwnerAgent, StateHFA |
| POST | `/findings/{id}/report` | File Form 8823 for an OPEN finding | StateHFA |
| POST | `/findings/{id}/correct` | Mark a finding corrected | OwnerAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STUDENT_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INCOME_OVER_LIMIT` | 422 Unprocessable Entity |
| `ERR_RENT_OVER_LIMIT` | 422 Unprocessable Entity |
| `ERR_LEASE_OVERLAP` | 409 Conflict |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_AVAILABLE_UNIT_RULE` | 409 Conflict |
| `ERR_SET_ASIDE_NOT_MET` | 409 Conflict |
| `ERR_OPEN_FINDINGS_BLOCK_CLOSE` | 409 Conflict |
| `ERR_RECAPTURE_REQUIRES_NONCOMPLIANT` | 409 Conflict |

# Farmworker Housing Compliance API — Product Requirements Document

## 1. Introduction

Operators of migrant and seasonal farmworker housing carry a regulatory burden out of proportion to the size of their portfolios: beds sit empty most of the year and then fill within days as crews arrive; state housing agencies, USDA Rural Development, HUD, and county health departments each assert inspection jurisdiction; and every rent dollar collected through payroll deduction is subject to federal garnishment ceilings and household-signed authorization caps. The record-keeping that proves compliance — pre-occupancy certifications, habitability complaints, pest-exclusion intervals, wage-deduction authorizations — is exactly the record-keeping that slips during the harvest rush.

This API is the operating system for that compliance workload. It models the operator's world as flat, top-level collections — housing sites, season windows, buildings, housing units, unit certifications, households, household members, tenancies, a charge ledger, deduction authorizations, work orders, pest treatments, complaints, regulatory inspections, and migrant service referrals — and it makes enforcement automatic rather than aspirational. Bed capacity is a hard ceiling, not a guideline. A `CRITICAL` work order puts its unit on hold the moment it is reported, and a regulator's `CRITICAL` finding condemns the unit outright, force-noticing its tenancies and flagging its households for rehousing priority. Wage deductions are capped by the household's own authorization, by a federal percentage ceiling, and by a protected net-wage floor — whichever binds hardest.

Because the domain is audit-driven, the API is built around evidence: state-changing transitions record who performed them, the person who completes a repair may never be the person who verifies it, the inspector who issues findings may never certify their cure, and writes that legitimately replace a parent's current plan — a new season window, a new deduction authorization, a pre-lease against a unit in notice — are guarded by optimistic concurrency so a stale writer cannot silently overwrite a decision it never observed.

## 2. Global Specifications & System-Wide Principles

This section fixes the contracts that apply uniformly across the API: authentication, response shape, pagination, the logical clock, resource identity, monetary precision, optimistic concurrency, validation ordering, the site compliance posture, segregation of duties, and existence checking.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before anything else is evaluated. A recognized role attempting an operation it is not permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Six roles are recognized. `OperatorAdmin` is the housing operator's administrator and owns sites, buildings, units, season windows, ledger posting and voids, and the logical clock. `SiteManager` runs the property day to day: pest treatments, complaint handling, and work-order verification and closure. `MaintenanceLead` supervises maintenance: triage, assignment, execution, and completion of work orders. `ComplianceInspector` performs pre-occupancy unit certifications and regulatory inspections. `IntakeCoordinator` owns resident intake: households, household members, eligibility decisions, tenancies, deduction authorizations, payments, and migrant service referrals. `Resident` is the head of a household acting on their own household's affairs.

For five of these roles — `OperatorAdmin`, `SiteManager`, `MaintenanceLead`, `ComplianceInspector`, and `IntakeCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition captures an actor (for example `inspector_id` on a certification, `created_by` on a deduction authorization, `completed_by` and `verified_by` on a work order, and `issued_by` and `cure_certified_by` on a regulatory inspection), but it never compares the header value to any entity's `id`. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any resource that references a household compare that household foreign key — concretely, the tenancy's `household_id` when a resident files a complaint or gives notice — against `X-User-ID`, and a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`.

Read access is uniform: every list and get endpoint is available to all six roles. Write access is allocated per operation in §4.

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

List endpoints paginate through two query parameters. `limit` sets the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets how many matching records to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Operational Dates

Every date- and time-derived rule in the system — certification expiry, pest-exclusion windows, complaint response SLAs, delinquency aging, season-window coverage — reads from a single logical clock, never from wall-clock time. An `OperatorAdmin` advances this clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`. Until that capability is first invoked, the clock reads exactly 2026-08-01T00:00:00Z, and the implementation must never fall back to wall-clock time. Wherever this document says "the clock date", "the current date", or "today", it means the calendar date of this logical clock; timestamps derived from it (such as a complaint's filing time) carry the clock's full instant.

### 2.5. Common Resource Properties

All fifteen resources share one identity contract. `id` is a server-minted UUID with no type prefix. `created_at` records when the resource was created and `updated_at` the last time any of its properties changed, both as ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that increments by one on every mutation of the resource. Because several writes legitimately land effects on a parent resource, the version that advances is not always the resource named in the request: creating a tenancy increments the unit's `version`; posting a ledger entry, voiding one, or recording a payroll payment increments the tenancy's; adding a household member, creating a deduction authorization, or updating eligibility increments the household's; creating a season window and every site lifecycle transition increment the site's. Each such increment is restated where its workflow is described.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents. The API never accepts or emits fractional cents, decimal strings, or floating-point dollars. When a calculation yields a fraction — prorated move-in rent, subsidy credits, utility overage lines, payroll deduction caps — the result is rounded half up to whole cents, and the rounding point is pinned by the workflow: each utility usage line is rounded before the lines are summed (never the reverse); each payroll-cap candidate is rounded before the candidates are compared; prorated rent and subsidy credits are rounded at posting time; and a weekly dorm rate derived from monthly rent is rounded half up to whole cents before being multiplied. Two computed habitability numbers are not money: the cumulative score is an integer, while the worst-case score keeps two decimal places.

### 2.7. Optimistic Concurrency on Superseding Writes

Three create operations carry a mandatory optimistic-concurrency field because each legitimately replaces or depends on a parent's current state. Creating a season window requires `expected_site_version`; creating a deduction authorization requires `expected_household_version`; creating a tenancy requires `expected_unit_version`. In every case the field is non-optional and must equal the parent entity's current `version` — the site's, the household's, or the unit's respectively. When another write has advanced the parent's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard matters precisely because these writes supersede: a new season window supersedes the site's existing `PLANNED` window, a new authorization supersedes the household's existing `ACTIVE` one, and a tenancy create may pre-lease a unit whose occupancy or hold state the client has never observed. The stale-version check runs after existence checks and ahead of every business rule. Endpoints not named here do not accept a version field.

### 2.8. Validation Order and Error Precedence

Checks execute in a fixed global order so that the same failure always produces the same error. First, header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, permission: the role must be allowed on the endpoint and on the target transition, and a `Resident` caller must own the tenancy in question (`ERR_INSUFFICIENT_PERMISSIONS`). Third, request-body shape — required fields present, types correct, enum values inside their declared sets, and the conditional field rules: a `UTILITY_OVERAGE` entry must carry `usage_lines` and must not carry `amount_cents`; a `DAMAGE` entry must carry `source_work_order_id`; `PASSED` and `FAILED` certification results carry `deficiency_count`; assigning a work order carries `assignee_name`; resolving a complaint carries `resolution_note`; issuing findings carries `findings` — all under `ERR_INVALID_REQUEST` (HTTP 400), applied on every mutation endpoint. Fourth, existence: path identifiers first, then body foreign keys, validated left to right with typed not-found codes (§2.11). Fifth, and only after existence, the stale-version check on the three versioned creates (`ERR_STALE_VERSION`). Sixth, segregation of duties on work-order verification and cure certification (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`).

Seventh, state-machine validity: the requested target status must be a declared transition from the entity's current status, and creating a work order or a pest treatment against a `DECOMMISSIONED` unit is likewise rejected — `ERR_INVALID_STATE` (HTTP 409); this gate covers every status-driving update, those two child creations, and season-window cancellation. A half-step later, the ledger-and-complaint gate: recording a payment, posting a ledger entry directly, or filing a complaint each require the tenancy to stand in `ACTIVE` or `NOTICE` (`ERR_INVALID_STATE`). Eighth, site lifecycle gates: tenancy activation, notice rescission, and inspection conduct require the site to be `OPEN` (`ERR_SITE_NOT_OPEN`). Ninth, the unit status gate at activation: the unit must be `CERTIFIED` or `OCCUPIED`, and a `CONDEMNED` unit surfaces the domain-specific `ERR_UNIT_CONDEMNED` rather than the generic code. Tenth, the posture gate: activation and notice rescission are rejected while the site's posture is `RESTRICTED` (`ERR_SITE_RESTRICTED`). Eleventh, pest safety: a move-in date inside an applied treatment's exclusion window (`ERR_UNIT_UNDER_PEST_EXCLUSION`), and clearing a treatment before its buffer elapses (`ERR_REENTRY_BUFFER_ACTIVE`). Twelfth, certification validity at activation (`ERR_NO_VALID_CERTIFICATION`). Thirteenth, occupancy ceilings, both at activation and when a member is added to a housed household (`ERR_OCCUPANCY_LIMIT_EXCEEDED`, HTTP 422).

Fourteenth, the season-window calendar rules — overlap checked first (`ERR_SEASON_WINDOW_OVERLAP`), maintenance gap second (`ERR_SEASON_GAP_TOO_SHORT`). Fifteenth, season-closure pest recency (`ERR_SEASON_PEST_TREATMENT_MISSING`). Sixteenth, the referential and eligibility gates, each with its own code: household not `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`), a member already housed elsewhere (`ERR_MEMBER_ALREADY_HOUSED`), an education referral without a minor (`ERR_EDUCATION_REFERRAL_REQUIRES_MINOR`, HTTP 422), an eligibility grant without verified agricultural work (`ERR_AG_WORK_NOT_VERIFIED`, HTTP 422), a damage charge citing an unverified work order (`ERR_WORK_ORDER_NOT_VERIFIED`), complaint resolution with open linked work orders (`ERR_LINKED_WORK_ORDERS_OPEN`), cure certification with unresolved critical findings (`ERR_UNRESOLVED_CRITICAL_FINDINGS`), and closure or decommission blocked by live tenancies (`ERR_ACTIVE_TENANCIES_REMAIN`) or by open work orders (`ERR_OPEN_WORK_ORDERS_REMAIN`). Seventeenth, the payment gates: an `ACTIVE` authorization must exist (`ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION`) and the capped amount must be positive (`ERR_NOTHING_TO_COLLECT`, HTTP 422). Eighteenth and last, the void gate: the target entry must still be `POSTED` (`ERR_ENTRY_ALREADY_VOIDED`).

### 2.9. Site Compliance Posture

Every site carries a computed `compliance_posture` — `NORMAL`, `WATCH`, or `RESTRICTED` — that aggregates the site's enforcement-relevant state and gates what may happen next. A site is `RESTRICTED` when any of its units is `CONDEMNED`, when two or more of its units stand in `HABITABILITY_HOLD`, or when any of its regulatory inspections stands at `FINDINGS_ISSUED` with an `open_critical_count` greater than zero. Failing that, a site is `WATCH` when exactly one of its units stands in `HABITABILITY_HOLD`, when any non-terminal work order of `CRITICAL` severity exists on the site, or when any complaint with `sla_breached` set still stands in `FILED`, `ACKNOWLEDGED`, `INVESTIGATING`, or `ESCALATED_TO_AGENCY`. Otherwise the posture is `NORMAL`.

The posture is recomputed whenever its inputs can change: any unit status change; work-order creation, verification, reopening, closure, or cancellation; an inspection issuing findings or certifying a cure; and a complaint being acknowledged, resolved, or closed. While a site is `RESTRICTED`, tenancy activation and notice rescission are rejected with `ERR_SITE_RESTRICTED` — new move-ins stop until the site digests its enforcement backlog.

A computed compliance read for a site reports the `compliance_posture` together with its constituent counts: `units_on_hold_count`, `condemned_units_count`, `open_critical_work_orders`, `breached_open_complaints`, and `units_missing_season_pest_treatment`.

### 2.10. Segregation of Duties

The same individual may never both finish and sign off on the same compliance artifact. A work order completed by one operator can be verified only by a different one: verification requires the caller's `X-User-ID` to differ from the recorded `completed_by`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). Symmetrically, the inspector who issued a regulatory inspection's findings may not certify their cure: cure certification requires the caller's `X-User-ID` to differ from `issued_by`, with the same error on a match. The verifier and cure-certifier identities are recorded as `verified_by` and `cure_certified_by` respectively. These checks sit ahead of state-transition validity in the global order (§2.8), so a same-person attempt fails as a duties violation rather than as a generic state error.

### 2.11. Existence Checks and Typed Not-Found Errors

Existence is validated left to right: path identifiers first, in path order, then foreign keys in the request body. Six resource types carry dedicated not-found codes — `ERR_SITE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and `ERR_INSPECTION_NOT_FOUND` — and the specific code takes precedence for its type; every other resource type (season windows, buildings, certifications, household members, authorizations, ledger entries, pest treatments, complaints, referrals) uses the generic `ERR_NOT_FOUND`. All are HTTP 404.

## 3. Business Logic & Workflows

### 3.1. Season Planning and the Site Lifecycle

An operator's year begins with a housing site. An `OperatorAdmin` creates it with a `name` and a `state_code` — exactly two uppercase letters, the US state code — and the site is born in `DRAFT` with a `compliance_posture` of `NORMAL`. Sites cycle through a season lifecycle with no terminal state: `DRAFT`, then `OPENING`, then `OPEN`, then `CLOSING`, then `CLOSED`, and back to `OPENING` again for the next season.

Before a site can open, its season must be planned. A season window is created against a `site_id` with a human `label` (say, "2026 Harvest"), a `planned_open_date`, and a `planned_close_date`, both ISO 8601 dates, with the close date on or after the open date; the window's dates form a closed interval, inclusive of both endpoints. A new window starts `PLANNED`. Because planning legitimately replaces earlier planning, creating a window supersedes any existing `PLANNED` window for the same site: the older window moves `PLANNED → SUPERSEDED` — supersession is observable through its `status` alone, since the superseding window's id is not stored on it — and the site's `version` increments by one. The create carries `expected_site_version` per §2.7. An `OperatorAdmin` may also abandon a planned window outright, moving it `PLANNED → CANCELLED` through a delete-style operation that returns no content. `COMPLETED`, `SUPERSEDED`, and `CANCELLED` are the window's terminal states.

The calendar defends a maintenance corridor between seasons. When a window is created, its dates are checked against the site's other windows — those `ACTIVE` or `COMPLETED`, plus `PLANNED` ones not being superseded by this create. Overlap is checked first: because intervals are closed, the new window intersects an existing one whenever its `planned_open_date` falls on or before the existing window's `planned_close_date` while its `planned_close_date` falls on or after the existing window's `planned_open_date`, and an intersecting create is rejected with `ERR_SEASON_WINDOW_OVERLAP`. The maintenance gap is checked second, and only against windows that survived the overlap test: the free span between the intervals must exceed fourteen days, so a gap of one to fourteen days in either direction is rejected with `ERR_SEASON_GAP_TOO_SHORT`, exactly fifteen days is the smallest legal separation, and a new window that opens on the very day an existing one closes already fails the overlap rule.

With a covering window in place, an `OperatorAdmin` drives the site forward. Moving `DRAFT → OPENING` requires a `PLANNED` window whose closed date interval covers the clock date; without one the transition is rejected with `ERR_NO_COVERING_SEASON_WINDOW`. An opening can be aborted — `OPENING → DRAFT` — without preconditions. Completing the opening, `OPENING → OPEN`, requires at least one unit of the site to hold `CERTIFIED` status (`ERR_NO_CERTIFIED_UNIT`); on success the covering `PLANNED` window turns `ACTIVE` and the site's `version` increments by one. Moving `OPEN → CLOSING` is unconditional, and while a site stands in `CLOSING` tenancy activations are refused through the usual site gate (`ERR_SITE_NOT_OPEN`).

Final closure, `CLOSING → CLOSED`, is the audit moment, and three conditions must hold. No tenancy on any unit of the site may remain in `ACTIVE` or `NOTICE` (`ERR_ACTIVE_TENANCIES_REMAIN`). No work order on any unit of the site may remain in `REPORTED`, `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, or `REOPENED` (`ERR_OPEN_WORK_ORDERS_REMAIN`). And every unit standing in `CERTIFIED`, `OCCUPIED`, or `HABITABILITY_HOLD` must show at least one pest treatment in `APPLIED` or `CLEARED` whose `applied_date` falls within the `ACTIVE` window's planned dates (`ERR_SEASON_PEST_TREATMENT_MISSING`). Closing then cascades: the `ACTIVE` window becomes `COMPLETED`; a certification expiry sweep flips every `PASSED` certification whose `expiry_date` is before the clock date to `EXPIRED`, and each affected unit in `CERTIFIED` that holds no other valid `PASSED` certification falls back to `REGISTERED`; and the site's `version` increments by one. A closed site reopens cyclically — `CLOSED → OPENING` — under the same covering-window requirement as the first opening.

### 3.2. Buildings, Units, and Pre-Occupancy Certification

Within a site, inventory is two-tiered. An `OperatorAdmin` registers a building with its `site_id` and a `name`, then registers housing units against a `building_id`. Each unit also carries a denormalized `site_id` that must equal its building's site — a mismatch is `ERR_INVALID_REQUEST` — plus a `unit_code`, a `unit_type`, a `max_occupancy` of at least one, and a `monthly_rent_cents` of zero or more. The `unit_type` — `FAMILY_UNIT` or `SEASONAL_DORM` — is not cosmetic: it selects the proration variant used at move-in (§3.4). A unit is born `REGISTERED` with `current_occupancy` zero, both habitability scores at zero, `under_pest_exclusion` false, and `pest_exclusion_end_date` null.

A unit may be retired only when nothing live depends on it. From `REGISTERED`, from `CERTIFIED`, or from `HABITABILITY_HOLD`, an `OperatorAdmin` may move a unit to `DECOMMISSIONED` provided no tenancy in `PENDING_MOVE_IN`, `ACTIVE`, or `NOTICE` references it (`ERR_ACTIVE_TENANCIES_REMAIN`); each decommission recomputes the site's posture and increments the unit's `version`. Once decommissioned, the unit refuses new children — creating a work order or a pest treatment against it is `ERR_INVALID_STATE`, and a certification visit cannot begin on it.

No unit may house anyone until an inspector certifies it. A `ComplianceInspector` schedules a certification against a `unit_id`, optionally with `notes`; the certification starts `SCHEDULED` and records its creator as `inspector_id`. Beginning the visit — `SCHEDULED → IN_PROGRESS` — is allowed only while the unit is not `DECOMMISSIONED` (`ERR_INVALID_STATE`). Recording a result requires `deficiency_count`, a non-negative integer, on either outcome. `IN_PROGRESS → PASSED` stamps `inspection_date` with the clock date, sets `expiry_date` 180 days later, lifts a `REGISTERED` unit to `CERTIFIED`, and recomputes the site posture. `IN_PROGRESS → FAILED` stamps the same `inspection_date` but leaves `expiry_date` null, and likewise recomputes the posture. Remediation loops: from `FAILED` the certification may return to `IN_PROGRESS` only when the unit has zero non-terminal `CRITICAL` work orders (`ERR_OPEN_WORK_ORDERS_REMAIN`).

Certifications decay two ways. An inspector may void a `PASSED` certification — with `notes` documenting why — and the system also expires them lazily: whenever a write consults a certification (a tenancy activation, a site status change, or a certification update), a `PASSED` certification whose `expiry_date` is before the clock date flips to `EXPIRED`. Either way, if the unit holds no other `PASSED` certification with an `expiry_date` on or after the clock date, its standing collapses: a `CERTIFIED` unit falls to `REGISTERED`, and an `OCCUPIED` unit drops to `HABITABILITY_HOLD` — existing tenancies continue, but new activations are refused — with the site posture recomputed in both cases. `VOIDED` and `EXPIRED` are terminal for the certification.

A computed availability read for a unit answers, in one place, everything an intake decision needs: `unit_status`, `current_occupancy`, `available_beds`, `under_pest_exclusion`, `pest_exclusion_end_date`, `has_valid_certification`, `habitability_score_cumulative`, and `habitability_score_worst_case`.

### 3.3. Household Intake, Eligibility, and Migrant Service Referrals

An `IntakeCoordinator` opens a household file with the `head_of_household_name` and the `annual_family_income_cents` (zero or more); `ag_work_verified` may be supplied at intake and defaults to false. The household starts `PENDING_ELIGIBILITY` with `member_count` and `minor_count` at zero, `rehousing_priority` false, and `eligibility_notes` unset.

Eligibility is a deliberate decision, not a default. Granting it — `PENDING_ELIGIBILITY → ELIGIBLE` — requires `ag_work_verified` to be true, and an unverified grant is refused with `ERR_AG_WORK_NOT_VERIFIED` (HTTP 422). Denying it — `PENDING_ELIGIBILITY → INELIGIBLE` — is unconditional, and a household may re-apply with new documentation, `INELIGIBLE → PENDING_ELIGIBILITY`. Revoking a grant — `ELIGIBLE → INELIGIBLE` — blocks new tenancy creation and activation for the household while leaving its existing tenancies untouched. The coordinator may attach `eligibility_notes` when recording the decision, and every eligibility update increments the household's `version`.

Household composition drives the occupancy math. Each member is added with the `household_id`, a `full_name`, a `date_of_birth`, and a `relationship` — `HEAD`, `SPOUSE`, `CHILD`, or `OTHER`. The system derives `is_minor` — true when the member is under eighteen years of age on the clock date — and recomputes `member_count` and `minor_count` on every add, incrementing the household's `version`. Adding members is not free once the household is housed: when the household holds an `ACTIVE` or `NOTICE` tenancy, an add that would push the unit past its `max_occupancy` is rejected with `ERR_OCCUPANCY_LIMIT_EXCEEDED`.

Intake is also the linkage point for migrant services. An `IntakeCoordinator` may create a service referral with the `household_id`, a `referral_type` of `EDUCATION` or `HEALTH`, the receiving `agency_name`, and optional `notes`. Two gates apply at creation: the household must be `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`), and an `EDUCATION` referral requires at least one minor in the household — a `minor_count` of zero is rejected with `ERR_EDUCATION_REFERRAL_REQUIRES_MINOR` (HTTP 422). A referral starts `INITIATED` and proceeds `INITIATED → ACCEPTED_BY_AGENCY → COMPLETED`; an agency that will not take the case ends it `INITIATED → DECLINED`. `COMPLETED` and `DECLINED` are terminal.

### 3.4. Tenancy: Pre-Leasing, Move-In Activation, Notice, and Termination

A tenancy binds a household to a unit. An `IntakeCoordinator` creates one with the `household_id`, the `unit_id`, a `move_in_date`, and `expected_unit_version` per §2.7; the household must already be `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`). The tenancy starts `PENDING_MOVE_IN`, and the create increments the unit's `version`. Pre-leasing is explicitly legitimate: a unit whose current tenancy stands in `NOTICE` may take a new tenancy for a future date, which is exactly why the create guards on the unit's version rather than on its vacancy.

Activation — `PENDING_MOVE_IN → ACTIVE`, performed by an `IntakeCoordinator` — is the most heavily gated transition in the system, and its checks run in the global order of §2.8. The site must be `OPEN` (`ERR_SITE_NOT_OPEN`). The unit must stand in `CERTIFIED` or `OCCUPIED`; any other status is `ERR_INVALID_STATE`, except `CONDEMNED`, which surfaces `ERR_UNIT_CONDEMNED`. The site's `compliance_posture` must not be `RESTRICTED` (`ERR_SITE_RESTRICTED`). The `move_in_date` must clear pest exclusion: if any `APPLIED` treatment on the unit has an `exclusion_end_date` on or after the `move_in_date`, activation is rejected with `ERR_UNIT_UNDER_PEST_EXCLUSION`, while a move-in date later than every such end date is allowed. The unit must hold a `PASSED` certification with an `expiry_date` on or after the clock date (`ERR_NO_VALID_CERTIFICATION`) — and as a side effect of this very check, a `PASSED` certification whose `expiry_date` has already passed flips to `EXPIRED`. Occupancy must fit: the projected occupancy — the unit's `current_occupancy`, defined as the sum of `member_count` across its `ACTIVE` and `NOTICE` tenancies, plus the incoming household's `member_count` — may equal the unit's `max_occupancy` but not exceed it; one person over the cap is rejected with `ERR_OCCUPANCY_LIMIT_EXCEEDED` (HTTP 422), counting all members regardless of `is_minor`. The household must be `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`). And no member of the household may belong to another tenancy in `ACTIVE` or `NOTICE` (`ERR_MEMBER_ALREADY_HOUSED`).

Activation posts money. The unit's `current_occupancy` grows by the household's `member_count`, and a `CERTIFIED` unit gaining its first `ACTIVE` tenancy becomes `OCCUPIED`. The system posts a `RENT` ledger entry for the move-in month, prorated by unit type. For a `FAMILY_UNIT`, the charge is the unit's full `monthly_rent_cents` times the days remaining in the move-in month — counted inclusively, from the `move_in_date` through the last day of that month — divided by the number of days in that calendar month, rounded half up to whole cents. For a `SEASONAL_DORM`, the monthly rent is first converted to a weekly slot rate — twelve months per year over fifty-two weeks per year, rounded half up to whole cents — and the charge is that weekly rate times the number of weeks the remaining days span, computed as the days remaining divided by seven and rounded up to a whole number: a partially used week bills the whole slot.

Subsidy relief follows immediately, keyed on gross rent rather than net to break the apparent circle. Monthly income is the household's `annual_family_income_cents` divided by twelve, rounded half up to whole cents. When monthly income computes to zero, the household receives the maximum tier, 0.30. Otherwise the rent-burden ratio is the unit's full `monthly_rent_cents` divided by monthly income: a ratio of at least 0.50 earns the 0.30 tier, a ratio of at least 0.30 earns the 0.15 tier, and anything below earns nothing — boundaries inclusive. The credit is the tier times the prorated rent charge, rounded half up to whole cents, posted as a `SUBSIDY_CREDIT` entry after the `RENT` entry and skipped entirely when the tier is zero. Whatever tier was computed locks onto the tenancy as `subsidy_tier_percent` — 0, 0.15, or 0.30 — and does not float afterward. Activation closes with a full balance, bucket, and delinquency recompute (§3.5).

Notice has two doors. An `IntakeCoordinator` moving an `ACTIVE` tenancy to `NOTICE` records an operator-initiated `notice_reason` of `OPERATOR`. A `Resident` may give notice on their own tenancy — the tenancy's `household_id` must equal the caller's `X-User-ID`, otherwise `ERR_INSUFFICIENT_PERMISSIONS` — and the recorded `notice_reason` is `RESIDENT`. Notice can be rescinded: an `IntakeCoordinator` returns the tenancy `NOTICE → ACTIVE` when the site is `OPEN` (`ERR_SITE_NOT_OPEN`), the posture is not `RESTRICTED` (`ERR_SITE_RESTRICTED`), the unit stands in `CERTIFIED` or `OCCUPIED` (`ERR_INVALID_STATE`), and the `notice_reason` is not `CONDEMNATION` — a condemnation notice can never be rescinded, and the attempt is rejected with `ERR_UNIT_CONDEMNED`. A successful rescission clears `notice_reason` back to null.

Termination is symmetric from `ACTIVE` or from `NOTICE`: an `IntakeCoordinator` supplies a `move_out_date` on or after the `move_in_date` (`ERR_INVALID_REQUEST` otherwise). In both cases the date is recorded, the unit's `current_occupancy` drops by the household's `member_count`, an `OCCUPIED` unit whose occupancy thereby reaches zero returns to `CERTIFIED`, and the site posture recomputes. A tenancy that never begins may instead be cancelled outright — `PENDING_MOVE_IN → CANCELLED` — with no preconditions. `TERMINATED` and `CANCELLED` are terminal. There is also a third, forced route into `NOTICE` — condemnation — described with the inspection workflow in §3.7.

### 3.5. The Charge Ledger, Payroll Deductions, and Delinquency

Every tenancy carries an append-only ledger of charges and credits. An `OperatorAdmin` posts entries directly with the `tenancy_id`, an `entry_type`, and an optional free-text `description`; the tenancy must stand in `ACTIVE` or `NOTICE` (`ERR_INVALID_STATE`). Four entry types are postable directly — `RENT`, `UTILITY_OVERAGE`, `DAMAGE`, and `SUBSIDY_CREDIT` — while `PAYMENT` entries arise only through the payroll-payment capability below. The `amount_cents` is always positive, with the sign derived from the type: `RENT`, `UTILITY_OVERAGE`, and `DAMAGE` are debits; `SUBSIDY_CREDIT` and `PAYMENT` are credits. The server stamps `charge_date` from the clock at posting, and each entry is born `POSTED`.

Two entry types carry conditional payloads. A `UTILITY_OVERAGE` entry must not supply `amount_cents` — the server computes it — and must instead supply `usage_lines`, a list of `{utility_type, usage_units}` pairs with `utility_type` one of `ELECTRIC`, `GAS`, or `WATER` and `usage_units` a non-negative integer. Each line is priced independently: consumption beyond the allowance — 200 units for `ELECTRIC`, 100 for `GAS`, 150 for `WATER` — is the overage; the first 100 overage units on the line bill at 12.5 cents each and any further units at 18.75 cents each; the line total is rounded half up to whole cents, and only then are the already-rounded lines summed into the entry's `amount_cents`. Summing first and rounding once is explicitly not the rule: two lines of five overage units each bill 126 cents in total, not 125. A `DAMAGE` entry, conversely, requires `amount_cents` like any manual charge and additionally requires `source_work_order_id` citing the work order the damage was remediated under — and that work order must stand in `VERIFIED` or `CLOSED` (`ERR_WORK_ORDER_NOT_VERIFIED`). For every other entry type, `usage_lines` and `source_work_order_id` are forbidden.

Balances are kept in three buckets and always recomputed from `POSTED` entries — `VOIDED` ones are excluded from every sum. The rent bucket, `rent_bucket_balance_cents`, nets `RENT` debits against rent-purpose payment portions and `SUBSIDY_CREDIT`s. The utility bucket, `utility_bucket_balance_cents`, nets `UTILITY_OVERAGE` debits against the utility overflow of rent-and-utilities payments. The damage bucket, `damage_bucket_balance_cents`, accumulates `DAMAGE` debits and is never touched by payroll credits. The tenancy's `balance_cents` is the sum of the three. Allocation is chronological: entries are processed in `created_at` ascending order with ties broken by `entry_type` ascending — never by id — and within each bucket, credits consume the oldest debit residuals first. Delinquency derives from that walk: `oldest_unpaid_charge_date` is the earliest `charge_date` among debits with residual remaining, across all buckets, and is null when the balance is zero; `is_delinquent` is true when the balance is positive and the oldest unpaid charge is more than ten days old — a charge exactly ten days old is not yet delinquent. A computed statement read for a tenancy exposes all of it: `balance_cents`, `rent_bucket_balance_cents`, `utility_bucket_balance_cents`, `damage_bucket_balance_cents`, `is_delinquent`, `oldest_unpaid_charge_date`, and the locked `subsidy_tier_percent`.

Payroll deduction is the primary collection channel, and it is authorization-first. An `IntakeCoordinator` records a household's consent as a deduction authorization carrying the `household_id`, a `cap_percent` — the household-authorized maximum fraction of gross wages, greater than zero and at most one — a `purpose` of `RENT` or `RENT_AND_UTILITIES`, an `effective_date`, and `expected_household_version` per §2.7. The authorization starts `ACTIVE` and records its creator as `created_by`. Consent replaces consent: creating an authorization supersedes the household's existing `ACTIVE` one, which moves `ACTIVE → SUPERSEDED` with its `superseded_by_id` pointing at the newcomer — a self-referential link — and the household's `version` increments by one. An `IntakeCoordinator` may instead revoke an `ACTIVE` authorization, moving it `ACTIVE → REVOKED`. `SUPERSEDED` and `REVOKED` are terminal.

A payroll payment is recorded by an `IntakeCoordinator` against a tenancy in `ACTIVE` or `NOTICE` with `gross_wages_cents`, `pay_period_start`, and `pay_period_end`. The household must hold an `ACTIVE` authorization (`ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION`). The covered balance is the rent bucket, plus the utility bucket when the authorization's `purpose` is `RENT_AND_UTILITIES`. The collectible amount is the smallest of four candidates, each rounded half up to whole cents before the comparison: the authorization's `cap_percent` of gross wages; thirty percent of gross wages, the federal ceiling; gross wages minus a protected net-wage floor of 40,000 cents — the worker always takes home at least four hundred dollars; and the covered balance itself. When the smallest candidate is zero or negative there is nothing to collect and the payment is rejected with `ERR_NOTHING_TO_COLLECT` (HTTP 422). Otherwise the system creates a `POSTED` `PAYMENT` entry at that amount and applies the credit as a waterfall: the rent bucket first, down to zero, with overflow into the utility bucket only when the authorization's `purpose` is `RENT_AND_UTILITIES`; the damage bucket is never touched by payroll money. The payment increments the tenancy's `version` by one and triggers the balance, bucket, and delinquency recompute.

Corrections are compensating, never destructive. An `OperatorAdmin` voids a ledger entry with a `void_reason`; the target must still be `POSTED`, and voiding an already-voided entry is rejected with `ERR_ENTRY_ALREADY_VOIDED`. The void records the reason, moves the entry `POSTED → VOIDED`, excludes it from every sum, recomputes the tenancy's balances and delinquency, and increments the tenancy's `version` by one. `VOIDED` is terminal.

### 3.6. Work Orders, Habitability Scoring, and Pest Exclusion

Maintenance begins with a report. An `OperatorAdmin`, `SiteManager`, or `MaintenanceLead` creates a work order with the `unit_id`, an optional `complaint_id` linking it to a resident complaint, a `category` — `PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, `PEST`, `APPLIANCE`, or `OTHER` — a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a `description`. The order starts `REPORTED`. Severity is enforced from the first second: creating a `CRITICAL` work order immediately moves its unit to `HABITABILITY_HOLD` (unless the unit is `CONDEMNED` or `DECOMMISSIONED`), recomputes the habitability scores, and recomputes the site posture.

Every unit maintains two habitability scores over its open set — work orders in `REPORTED`, `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, or `REOPENED` — weighted 25 for `CRITICAL`, 10 for `MAJOR`, and 3 for `MINOR`. The enforcement number, `habitability_score_cumulative`, is the plain weighted sum over the open set. The triage preview, `habitability_score_worst_case`, is the largest single weight in the open set plus one quarter of the sum of the remaining weights — heavily discounting long tails of minor items — is zero when the open set is empty, keeps two decimal places, and surfaces on reads only. Enforcement follows the cumulative variant exclusively: from `REGISTERED`, from `CERTIFIED`, or from `OCCUPIED`, a unit moves to `HABITABILITY_HOLD` whenever the cumulative score reaches 40 or any `CRITICAL` order is open, with the site posture recomputed on each transition. The hold clears on matching terms: whenever a work order is verified, closed, or cancelled and the recomputed cumulative score is below 40 with zero non-terminal `CRITICAL` orders, the unit leaves `HABITABILITY_HOLD` — to `CERTIFIED` when it holds a valid `PASSED` certification, to `OCCUPIED` instead when its `current_occupancy` is above zero, and to `REGISTERED` when no valid certification remains — again recomputing the posture.

The workflow itself is a supervised pipeline. A `MaintenanceLead` moves an order `REPORTED → TRIAGED`, then `TRIAGED → ASSIGNED` by naming an `assignee_name` — omitting it is `ERR_INVALID_REQUEST` — and `ASSIGNED → IN_PROGRESS` as work begins. Completion, `IN_PROGRESS → COMPLETED`, records the finisher as `completed_by`. Verification takes a different pair of hands: a `SiteManager` moves `COMPLETED → VERIFIED` only when the caller's `X-User-ID` differs from `completed_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), records `verified_by`, and runs the hold-clear recompute described above. When verification instead reveals deficient work, a `SiteManager` returns the order `COMPLETED → REOPENED`, which counts the order as open again and recomputes both the scores and the posture; a `MaintenanceLead` then re-assigns it, `REOPENED → ASSIGNED`, again requiring `assignee_name`. A verified order is closed by a `SiteManager` — `VERIFIED → CLOSED` — with a posture recompute. Cancellation is available from `REPORTED`, `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, or `REOPENED`, to either a `SiteManager` or a `MaintenanceLead`; every cancellation recomputes the scores — possibly clearing a hold — and the posture. `CLOSED` and `CANCELLED` are terminal.

Pest control runs on closed intervals. A `SiteManager` schedules a treatment with the `unit_id`, a `treatment_type` of `ROUTINE`, `TARGETED`, or `FUMIGATION`, a `scheduled_date`, and a `reentry_buffer_days` of zero or more; the treatment starts `SCHEDULED`, and a treatment that turns out unneeded may be cancelled, `SCHEDULED → CANCELLED`. Marking it applied — `SCHEDULED → APPLIED`, refused against a `DECOMMISSIONED` unit with `ERR_INVALID_STATE` — stamps `applied_date` from the clock and computes `exclusion_end_date` as the applied date plus the buffer days. The exclusion is a closed interval: both the applied date and the end date are unoccupiable, so the unit's `under_pest_exclusion` holds while the clock date is on or before the `exclusion_end_date`, and a move-in whose `move_in_date` falls on or before any applied treatment's end date is refused per §3.4. With several applied treatments, the unit's `pest_exclusion_end_date` is the latest of their end dates — and null when no treatment is applied. Clearing — `APPLIED → CLEARED` — requires the clock date to be strictly past the `exclusion_end_date`; the buffer's final day is still excluded, and an early clear is rejected with `ERR_REENTRY_BUFFER_ACTIVE`. Clearing recomputes the unit's exclusion flags across the remaining applied treatments. `CLEARED` and `CANCELLED` are terminal. Season closure leans on this history: every live unit must show a treatment applied within the season window, per §3.1.

### 3.7. Complaints, Regulatory Inspections, and the Condemnation Cascade

A complaint is the resident's channel into enforcement. A `Resident` files against their own tenancy — the `tenancy_id` must resolve to a tenancy whose `household_id` equals the caller's `X-User-ID`, otherwise `ERR_INSUFFICIENT_PERMISSIONS` — or an `IntakeCoordinator` files on the household's behalf; either way the tenancy must stand in `ACTIVE` or `NOTICE` (`ERR_INVALID_STATE`). The complaint carries a `category` — `HABITABILITY`, `RENT`, `UTILITY`, `HARASSMENT`, or `OTHER` — and a `description`, starts `FILED`, and stamps `filed_at` from the logical clock.

Response speed is measured. A `SiteManager` acknowledges — `FILED → ACKNOWLEDGED` — which stamps `acknowledged_at` from the clock and evaluates the SLA: `sla_breached` becomes true only when the acknowledgement lands strictly later than seventy-two hours after `filed_at`; acknowledgement at exactly the seventy-two-hour mark is compliant. Acknowledgement recomputes the site posture, since a breached, still-open complaint is one of the `WATCH` inputs. Investigation proceeds `ACKNOWLEDGED → INVESTIGATING`. Resolution — `INVESTIGATING → RESOLVED` — requires a `resolution_note` (`ERR_INVALID_REQUEST` when absent) and requires every work order linked through `complaint_id` to stand in `VERIFIED`, `CLOSED`, or `CANCELLED` (`ERR_LINKED_WORK_ORDERS_OPEN`), recomputing the posture on success. Where the operator cannot resolve locally, the complaint escalates — `INVESTIGATING → ESCALATED_TO_AGENCY` — and an agency that refers the matter back returns it `ESCALATED_TO_AGENCY → INVESTIGATING`. A resolved complaint is finally closed — `RESOLVED → CLOSED` — with a posture recompute; `CLOSED` is terminal.

Regulatory inspections are the external enforcement track. A `ComplianceInspector` schedules one against a `site_id` with the inspecting `agency` — `STATE_HOUSING`, `USDA_RD`, `HUD`, or `COUNTY_HEALTH` — and a `scheduled_date`; the inspection starts `SCHEDULED`, and may be cancelled, `SCHEDULED → CANCELLED`. Conducting it — `SCHEDULED → CONDUCTED` — requires the site to be `OPEN` (`ERR_SITE_NOT_OPEN`).

Issuing findings — `CONDUCTED → FINDINGS_ISSUED` — is the cascade point. The `findings` payload must be present, though it may be an empty array (`ERR_INVALID_REQUEST` when absent); each finding cites a `unit_id`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a violation `code`. The transition records the issuer as `issued_by` and sets `open_critical_count` to the number of `CRITICAL` findings. Every `CRITICAL` finding then condemns its cited unit: from `CERTIFIED`, from `OCCUPIED`, or from `HABITABILITY_HOLD`, the unit moves to `CONDEMNED`. Condemnation force-notices the unit's residents: every tenancy on the unit in `ACTIVE` or `NOTICE` moves to — or remains in — `NOTICE` with `notice_reason` set to `CONDEMNATION`, overriding any earlier `RESIDENT` or `OPERATOR` reason, and each affected household's `rehousing_priority` flips to true. The site posture recomputes, and since a condemned unit is a `RESTRICTED` input, a single critical finding can freeze move-ins site-wide. Re-inspection is cyclic: `FINDINGS_ISSUED → CONDUCTED` opens another visit, with the prior `findings` and `issued_by` persisting.

Cure certification closes the loop with fresh eyes. Moving `FINDINGS_ISSUED → CURE_CERTIFIED` requires the caller's `X-User-ID` to differ from `issued_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and requires `open_critical_count` to have reached zero — meaning every `CRITICAL` finding's cited unit now holds a `PASSED` certification whose `inspection_date` is later than the date the findings were issued; any shortfall is `ERR_UNRESOLVED_CRITICAL_FINDINGS`. The certifier is recorded as `cure_certified_by`, every `CONDEMNED` unit cited by the inspection returns to `REGISTERED` — and must pass a fresh certification to climb back to `CERTIFIED`, completing the re-certification cycle — and the site posture recomputes. A certified inspection then closes, `CURE_CERTIFIED → CLOSED`; `CLOSED` and `CANCELLED` are terminal. Throughout, the site's computed compliance read (§2.9) stays current: posture, units on hold, condemned units, open critical work orders, breached open complaints, and units missing their in-season pest treatment.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` with the created resource in `data`. Reads, lifecycle transitions, and actions on existing resources — including the ledger void and the clock setter — return `200 OK`. The single delete-style operation, cancelling a planned season window, returns `204 No Content`. All collections are top-level paths; there is no nested URL hierarchy, so related resources are reached through body foreign keys and filtered list queries. The supported list filters are `site_id`, `building_id`, `unit_id`, `household_id`, `tenancy_id`, `complaint_id`, `status`, `eligibility_status`, `compliance_posture`, `entry_type`, `source_work_order_id`, `severity`, `referral_type`, and `superseded_by_id`, alongside the pagination parameters `limit` and `offset`. Read endpoints are available to all six roles and are marked "All roles" below; write endpoints list their authorized roles explicitly.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | OperatorAdmin |
| POST | `/housing-sites` | Create a housing site (status DRAFT, posture NORMAL) | OperatorAdmin |
| GET | `/housing-sites` | List housing sites with pagination | All roles |
| GET | `/housing-sites/{id}` | Get a housing site | All roles |
| PUT | `/housing-sites/{id}` | Drive the site season lifecycle (status in OPENING / DRAFT / OPEN / CLOSING / CLOSED) | OperatorAdmin |
| GET | `/housing-sites/{id}/compliance-summary` | Computed compliance posture read for the site | All roles |
| POST | `/season-windows` | Create a season window (supersedes an existing PLANNED window for the site; OCC on site version) | OperatorAdmin |
| GET | `/season-windows` | List season windows | All roles |
| GET | `/season-windows/{id}` | Get a season window | All roles |
| DELETE | `/season-windows/{id}` | Cancel a PLANNED season window | OperatorAdmin |
| POST | `/buildings` | Create a building | OperatorAdmin |
| GET | `/buildings` | List buildings | All roles |
| GET | `/buildings/{id}` | Get a building | All roles |
| POST | `/housing-units` | Create a housing unit (status REGISTERED) | OperatorAdmin |
| GET | `/housing-units` | List housing units | All roles |
| GET | `/housing-units/{id}` | Get a housing unit | All roles |
| PUT | `/housing-units/{id}` | Decommission a unit (status=DECOMMISSIONED) | OperatorAdmin |
| GET | `/housing-units/{id}/availability` | Computed occupancy/exclusion/certification read for the unit | All roles |
| POST | `/unit-certifications` | Schedule a pre-occupancy certification inspection (status SCHEDULED) | ComplianceInspector |
| GET | `/unit-certifications` | List unit certifications | All roles |
| GET | `/unit-certifications/{id}` | Get a unit certification | All roles |
| PUT | `/unit-certifications/{id}` | Drive certification lifecycle (status in IN_PROGRESS / PASSED / FAILED / VOIDED) | ComplianceInspector |
| POST | `/households` | Create a household (PENDING_ELIGIBILITY) | IntakeCoordinator |
| GET | `/households` | List households | All roles |
| GET | `/households/{id}` | Get a household | All roles |
| PUT | `/households/{id}` | Set eligibility (eligibility_status in ELIGIBLE / INELIGIBLE / PENDING_ELIGIBILITY) | IntakeCoordinator |
| POST | `/household-members` | Add a household member (occupancy re-check when the household is housed) | IntakeCoordinator |
| GET | `/household-members` | List household members | All roles |
| GET | `/household-members/{id}` | Get a household member | All roles |
| POST | `/deduction-authorizations` | Create a wage deduction authorization (supersedes the household's ACTIVE authorization; OCC on household version) | IntakeCoordinator |
| GET | `/deduction-authorizations` | List deduction authorizations | All roles |
| GET | `/deduction-authorizations/{id}` | Get a deduction authorization | All roles |
| PUT | `/deduction-authorizations/{id}` | Revoke an authorization (status=REVOKED) | IntakeCoordinator |
| POST | `/tenancies` | Create a tenancy (PENDING_MOVE_IN); pre-leasing a unit that has a NOTICE tenancy is legitimate | IntakeCoordinator |
| GET | `/tenancies` | List tenancies | All roles |
| GET | `/tenancies/{id}` | Get a tenancy | All roles |
| PUT | `/tenancies/{id}` | Drive tenancy lifecycle (status in ACTIVE / NOTICE / TERMINATED / CANCELLED; ACTIVE from NOTICE rescinds) | IntakeCoordinator, Resident |
| POST | `/tenancies/{id}/payments` | Record a payroll-deduction payment capped per the deduction-cap rules | IntakeCoordinator |
| GET | `/tenancies/{id}/statement` | Computed ledger statement for the tenancy | All roles |
| POST | `/charge-ledger-entries` | Post a ledger charge/credit (RENT / UTILITY_OVERAGE / DAMAGE / SUBSIDY_CREDIT) | OperatorAdmin |
| GET | `/charge-ledger-entries` | List ledger entries | All roles |
| GET | `/charge-ledger-entries/{id}` | Get a ledger entry | All roles |
| POST | `/charge-ledger-entries/{id}/void` | Void a POSTED ledger entry (compensating action) | OperatorAdmin |
| POST | `/work-orders` | Report a work order (status REPORTED); CRITICAL severity immediately puts the unit on HABITABILITY_HOLD | OperatorAdmin, SiteManager, MaintenanceLead |
| GET | `/work-orders` | List work orders | All roles |
| GET | `/work-orders/{id}` | Get a work order | All roles |
| PUT | `/work-orders/{id}` | Drive work order lifecycle (status in TRIAGED / ASSIGNED / IN_PROGRESS / COMPLETED / VERIFIED / REOPENED / CLOSED / CANCELLED) | MaintenanceLead, SiteManager |
| POST | `/pest-treatments` | Schedule a pest treatment (status SCHEDULED) | SiteManager |
| GET | `/pest-treatments` | List pest treatments | All roles |
| GET | `/pest-treatments/{id}` | Get a pest treatment | All roles |
| PUT | `/pest-treatments/{id}` | Drive treatment lifecycle (status in APPLIED / CLEARED / CANCELLED) | SiteManager |
| POST | `/complaints` | File a complaint (Resident may file only for own household's tenancy) | Resident, IntakeCoordinator |
| GET | `/complaints` | List complaints | All roles |
| GET | `/complaints/{id}` | Get a complaint | All roles |
| PUT | `/complaints/{id}` | Drive complaint lifecycle (status in ACKNOWLEDGED / INVESTIGATING / RESOLVED / ESCALATED_TO_AGENCY / CLOSED) | SiteManager |
| POST | `/regulatory-inspections` | Schedule a regulatory inspection (status SCHEDULED) | ComplianceInspector |
| GET | `/regulatory-inspections` | List regulatory inspections | All roles |
| GET | `/regulatory-inspections/{id}` | Get a regulatory inspection | All roles |
| PUT | `/regulatory-inspections/{id}` | Drive inspection lifecycle (status in CONDUCTED / FINDINGS_ISSUED / CURE_CERTIFIED / CLOSED / CANCELLED) | ComplianceInspector |
| POST | `/service-referrals` | Create a migrant education/health referral (household must be ELIGIBLE; EDUCATION requires a minor) | IntakeCoordinator |
| GET | `/service-referrals` | List service referrals | All roles |
| GET | `/service-referrals/{id}` | Get a service referral | All roles |
| PUT | `/service-referrals/{id}` | Drive referral lifecycle (status in ACCEPTED_BY_AGENCY / COMPLETED / DECLINED) | IntakeCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows and validation ordering in §2 and §3; this table is the reference index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 Not Found |
| `ERR_TENANCY_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_COVERING_SEASON_WINDOW` | 409 Conflict |
| `ERR_NO_CERTIFIED_UNIT` | 409 Conflict |
| `ERR_SITE_NOT_OPEN` | 409 Conflict |
| `ERR_SITE_RESTRICTED` | 409 Conflict |
| `ERR_UNIT_CONDEMNED` | 409 Conflict |
| `ERR_UNIT_UNDER_PEST_EXCLUSION` | 409 Conflict |
| `ERR_REENTRY_BUFFER_ACTIVE` | 409 Conflict |
| `ERR_NO_VALID_CERTIFICATION` | 409 Conflict |
| `ERR_OCCUPANCY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEASON_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SEASON_GAP_TOO_SHORT` | 409 Conflict |
| `ERR_SEASON_PEST_TREATMENT_MISSING` | 409 Conflict |
| `ERR_HOUSEHOLD_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_MEMBER_ALREADY_HOUSED` | 409 Conflict |
| `ERR_EDUCATION_REFERRAL_REQUIRES_MINOR` | 422 Unprocessable Entity |
| `ERR_AG_WORK_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_WORK_ORDER_NOT_VERIFIED` | 409 Conflict |
| `ERR_LINKED_WORK_ORDERS_OPEN` | 409 Conflict |
| `ERR_UNRESOLVED_CRITICAL_FINDINGS` | 409 Conflict |
| `ERR_ACTIVE_TENANCIES_REMAIN` | 409 Conflict |
| `ERR_OPEN_WORK_ORDERS_REMAIN` | 409 Conflict |
| `ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION` | 409 Conflict |
| `ERR_NOTHING_TO_COLLECT` | 422 Unprocessable Entity |
| `ERR_ENTRY_ALREADY_VOIDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |

# Oil Tank Remediation API — Product Requirements Document

## 1. Introduction

A residential oil-tank services contractor lives or dies by paperwork. A buried heating-oil tank in a New Jersey, New York or Connecticut back yard is at once a fire-marshal matter, a municipal permit matter, a laboratory chain-of-custody matter, a homeowner-consent matter, an insurance matter and — when a real-estate closing is pending — a matter of whether a licensed professional is willing to put their signature on a no-further-action letter. Today the contractor's field crews, its laboratory partners, its licensed site professionals and its compliance desk each keep their own spreadsheet, and the resulting drift is expensive: crews mobilize before a fire-marshal notice has taken effect, soil aliquots sit past their holding time and get quietly re-collected, change orders push excavation past the contracted ceiling, and trust-fund reimbursement applications get filed against cost figures that a later change order already invalidated.

This document specifies the API for a single system of record that spans the whole job — from the first sweep survey that locates the tank, through the removal-versus-abandonment recommendation, the permit and notification gates, the excavation itself, confirmation sampling and laboratory turnaround, remediation scoping, insurance tender, state trust-fund reimbursement, and finally the no-further-action letter that lets the closing proceed. The system is deliberately built as a compliance-audit engine rather than a project-tracker: every state change is gated on the regulatory precondition that justifies it, every derived number is recomputed from first principles rather than incremented in place, and every cost figure carries an explicit basis so that a reviewer can tell whether they are looking at a provisional grid estimate or a surveyed weigh-ticket number.

Two design commitments shape everything that follows. First, **segregation of duties is structural, not advisory**: field work, laboratory reporting, licensed-professional sign-off and regulatory decision-making are held by different roles, and the licensed site professional who drafts a no-further-action letter is forbidden from signing it. Second, **derived state is never stale**: a single laboratory result can cascade through sample status, project classification, remediation volume, remediation cost, insurance reserve allocation and carrier-notification status in one atomic request, and a rescinded closure letter must walk that cascade backwards, reopening remediation and returning an already-approved reimbursement claim to review.

## 2. Global Specifications & System-Wide Principles

The resource graph is flat. Every business resource is a top-level collection, and relationships are carried as identifier fields inside request bodies rather than as nested URL segments. The collections are mounted at the service root.

### 2.1. Operating Roles, Authentication and Segregation of Duties

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting. Exactly six roles exist, and their names are spelled `ProjectCoordinator`, `FieldTechnician`, `LabAnalyst`, `Homeowner`, `LicensedSiteProfessional` and `ComplianceOfficer`. If either header is absent, or if `X-User-Role` carries any value outside those six, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the named role does not appear in the authorized-role list for the endpoint being addressed (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The `ProjectCoordinator` is the contractor-side operator: they intake sites, record sweep surveys, send homeowner disclosures, file permits, register crews, schedule field work and drive the billing dimension of a work order. The `FieldTechnician` is a crew member who executes field events and collects soil aliquots but may never report or retract a laboratory result. The `LicensedSiteProfessional` is the licensed environmental professional who scopes remediation change orders and drafts and signs no-further-action letters. The `ComplianceOfficer` is the regulatory operator who renders permit decisions, registers laboratories, decides change orders, administers trust-fund claims, notifies insurance carriers and rescinds no-further-action letters; a `ComplianceOfficer` may neither draft nor issue a closure letter, may not perform field work, and may not report laboratory results.

Four of the six roles carry an **opaque** identity. When `X-User-Role` is `ProjectCoordinator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any resource's `id`. The same holds for `FieldTechnician`, for `LicensedSiteProfessional` and for `ComplianceOfficer`. The server does, however, record those opaque identifiers where the workflow demands attribution: the collecting technician's identifier is stored as `collected_by_user_id` on a soil sample; the drafting professional's identifier is stored as `requested_by_user_id` on a change order and as `drafted_by_user_id` on a closure letter; the signing professional's identifier is stored as `issued_by_user_id`; and the deciding compliance operator's identifier is stored as `approved_by_user_id` on a change order.

The remaining two roles are **entity-backed**, and for them `X-User-ID` is an ownership claim that the server checks. When `X-User-Role` is `LabAnalyst`, `X-User-ID` is the `id` of the acting `Laboratory`; ownership checks on any soil sample compare that sample's `laboratory_id` to `X-User-ID`. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Property`; ownership checks compare the `property_id` of the addressed project — or of the project behind the addressed disclosure or letter — to `X-User-ID`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership gate guards exactly nine operations: the homeowner response to a disclosure notice, the disclosure list read, the single-disclosure read, the single-property read, the single-project read, the single-closure-letter read, and the three laboratory-facing sample operations — the custody event, the result posting, and the result retraction.

Segregation of duties is enforced at one further point beyond the role matrix. The `LicensedSiteProfessional` whose `X-User-ID` signs a no-further-action letter must differ from the `drafted_by_user_id` recorded on that letter. When they are the same principal, issuance is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and that refusal is evaluated ahead of the substantive closure checks so that a self-signing attempt never reveals whether the project would otherwise have been closeable.

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

Every collection read accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

Collection reads are ordered by `created_at` ascending, so that a paged walk over a project's samples, change orders or claims reproduces the chronological order in which they were authored. The `meta` block of a list response carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before the window was applied, and `has_more` as a boolean indicating whether rows remain beyond the current window.

### 2.4. Resource Identity, Audit Fields and the Project Version Counter

Every resource in the system — properties, tank projects, homeowner disclosures, permits, crews, decommission work orders, laboratories, soil samples, remediation change orders, trust-fund claims, no-further-action letters and insurance notifications alike — carries the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written. `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation. No entity in this system is exempt: there is no resource that omits `updated_at` or `version`.

A mutation for these purposes includes writes to derived fields. When a laboratory result forces the recomputation of a project's `contamination_class`, or when a change-order approval rewrites `remediation_cost_cents`, or when the insurance waterfall rewrites the allocation triple on a notification, the touched rows have their `updated_at` refreshed and their `version` incremented just as an operator-driven edit would.

The `version` of a `TankProject` carries additional contractual weight, because it is the value clients echo back when authoring against the project (§2.8). Three operations increment `TankProject.version` by exactly 1 as an explicit, documented effect: recording the sweep survey, creating a remediation change order, and creating a trust-fund claim. Cascaded writes to the project's derived fields increment it as well, under the general rule above.

### 2.5. The Logical Site Clock

All time in this system is read from a server-side **logical clock** rather than from wall-clock time. On startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A capability restricted to `ComplianceOfficer` and `ProjectCoordinator` sets the clock to a supplied `to_iso8601` instant and echoes the resulting `current_utc`; setting the clock mutates no entity and fires no cascade.

Every instant the server stamps reads this clock — `survey_completed_at`, `sent_at`, `responded_at`, `submitted_at`, `issued_at`, `notified_at`, `collected_at`, `dispatched_at`, `received_at`, `reported_at`, `decided_at`, `paid_at`, `rescinded_at` — and so does every deadline comparison: the disclosure response window ending at `expires_at`, the fire-marshal lead time ending at `notice_effective_at`, permit validity, laboratory holding time, laboratory turnaround, and the `closing_date` check at letter issuance.

### 2.6. Reference Resolution Across a Flat Resource Graph

Because the graph is flat, references arrive in two places: as the single identifier in a path, and as identifier fields inside a request body. Both are resolved before any business rule runs, and both produce the 404 that names the entity that failed to resolve. A path identifier that does not resolve yields `ERR_PROPERTY_NOT_FOUND`, `ERR_TANK_PROJECT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LABORATORY_NOT_FOUND`, `ERR_SOIL_SAMPLE_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_NFA_LETTER_NOT_FOUND` or `ERR_INSURANCE_NOTIFICATION_NOT_FOUND` as appropriate. Where a path carries more than one identifier, they are validated strictly left to right, and the first one that fails to resolve determines the error returned.

Body-carried references are resolved with the same entity-specific codes. The references the server resolves are `property_id`, `tank_project_id`, `crew_id`, `laboratory_id`, `work_order_id`, `retest_of_sample_id` and `supersedes_change_order_id`, and this resolution step runs on all nine creation operations: creating a tank project, a disclosure, a permit, a work order, a soil sample, a change order, a trust-fund claim, a closure letter and an insurance notification. Note the ordering consequence: an unresolvable `retest_of_sample_id` is a 404, whereas a resolvable one pointing at a sample in the wrong state is a later 409.

### 2.7. Cascade Discipline and Recomputation Order

Derived values in this system are always **recomputed from their inputs**, never adjusted by a delta. When a project's remediation cost changes, the server does not add the difference to the previous figure; it re-runs the cost calculation over the project's currently approved change orders and writes the result. The same holds for `approved_scope_cubic_yards`, for the contamination maxima, for the insurance allocation triple and for the blocker list read at closure.

Cascades run to completion inside the request that triggered them, and they run in a fixed order. The deepest cascade in the system runs five levels from a single laboratory result posting: the sample reaches `RESULTED`; the project's confirmation round completes and the project advances to `ASSESSED` with its classification recomputed; the classification routes the project onward to `CLEARED` or to `REMEDIATION_ACTIVE` with a fresh remediation volume and cost; the new cost re-runs the insurance waterfall over the project's notifications; and each rewritten notification then re-derives its own status. A mirror-image cascade runs four levels from the rescission of a closure letter: the letter becomes `RESCINDED`; the project returns to `REMEDIATION_ACTIVE`; every approved trust-fund claim on the project is walked back to review; and the notifications' allocations and statuses are rewritten.

Two consistency rules follow. First, a cascade never touches a row in a terminal state that the cascade's own definition excludes — an insurance notification already `CLOSED` is never rewritten, and a change order already `REJECTED` or `SUPERSEDED` never re-enters a cost sum. Second, project-level flags that record that something *has happened* are latches: `remediation_started` is set true the first time a project enters `REMEDIATION_ACTIVE` and is never reset, and `contamination_disclosure_required` is set true the first time the project's `contamination_class` becomes `ELEVATED` or `GROSS` and is likewise never reset, even when a later round classifies `CLEAN`.

### 2.8. Authoring Against a Current View of the Project

Two authoring operations require the client to prove it was looking at a current view of the project when it composed its request. Both use the same non-optional input field, `expected_project_version`, which must carry the client's last observed `version` of the addressed `TankProject`.

Creating a `RemediationChangeOrder` requires `expected_project_version` in the request body. If that value does not equal the target project's current `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The rule exists because a change order may legitimately supersede a prior approved change order, and the author's scope arithmetic is only sound if it was derived from the project's current approved scope and cost; a stale value means that arithmetic rests on superseded data.

Creating a `TrustFundClaim` likewise requires `expected_project_version`, and a value that does not equal the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). A close-out claim withdraws the project's open interim claim as a side effect, so it must be filed against a current project view; a stale value means the claimed costs were copied from a project snapshot that a subsequent change-order approval has already replaced.

No other operation in the system accepts a version field. Endpoints not named above take no `expected_project_version` and perform no version comparison.

### 2.9. Units, Precision and Rounding

Money is carried exclusively as **integer cents** in fields whose names end in `_cents`. There are no fractional-cent values anywhere in the system, and no monetary field is represented as a decimal number. Volumes are decimal cubic yards, tonnage is decimal tons, depths are integer inches, capacities are integer gallons, and elapsed laboratory intervals are decimal hours.

Rounding is always **half up**, and where it happens is pinned:

- The abandonment-suitability score, `method_score`, is clamped into the closed range from 0.00 to 100.00 *before* it is rounded, and is then rounded half up to 2 decimal places.
- The remediation volume, `remediation_volume_cubic_yards`, is rounded half up to 2 decimal places exactly once, at the end of whichever variant produced it.
- A change order's `line_amount_cents` is rounded half up to whole cents *per line, before any summation*. Summing first and rounding once is incorrect and will differ by whole cents whenever two or more lines carry a half-cent remainder. Once the per-line amounts are integers, the summation is exact integer arithmetic.
- A claim's `admin_fee_cents` is rounded half up to whole cents at the point it is computed; every subsequent step of the eligibility calculation is exact integer arithmetic.
- The laboratory timing figures `holding_time_elapsed_hours` and `turnaround_hours` are each rounded half up to 2 decimal places *before* they are compared to their thresholds.
- The insurance waterfall performs no rounding at all. It is pure integer-cent arithmetic, which is what allows its conservation invariant to hold with zero drift: for every non-closed notification of a project, `first_party_allocated_cents` plus `third_party_allocated_cents` plus `homeowner_out_of_pocket_cents` equals the project's `remediation_cost_cents` exactly.

### 2.10. Boundary Conventions for Thresholds and Windows

Regulatory thresholds in this domain are conventionally generous at the boundary, and the system honours that convention uniformly: **a value exactly at a limit is compliant, and only a value strictly beyond it is a breach.**

Concretely, a soil result sitting exactly on an action level is not an exceedance — contamination comparisons are strictly greater-than, so a sample at exactly 500.0 mg/kg of total petroleum hydrocarbons and exactly 0.5 mg/kg of benzene classifies as `CLEAN`. A holding time exactly equal to the laboratory's permitted maximum is compliant. A turnaround exactly equal to the laboratory's commitment is not a breach, so `turnaround_breach` stays false. A homeowner responding at exactly the instant a disclosure expires is in time. A crew mobilizing at exactly the instant the fire-marshal notice becomes effective is authorized, and mobilizing at exactly the instant a municipal permit expires is still authorized. A closure letter whose `closing_date` falls exactly on the current logical instant is issuable. A change-order approval that brings approved scope to exactly the project's excavation ceiling is permitted. In the one place where the convention runs the other way, it does so explicitly: the abandonment recommendation flips at a score of *at least* 55.00, and the laboratory analysis-window occupancy test uses a **closed** interval whose two endpoints both count as occupied.

### 2.11. Order of Rejection

When a single request violates more than one rule, the response must carry the error of the highest-priority violated rule. The ladder below is evaluated top to bottom; the first violation found terminates the request.

1. **Header and role authentication** — `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Endpoint role authorization** — `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
3. **Ownership for entity-backed roles** — `ERR_NOT_RESOURCE_OWNER` (403). Applies to the nine operations enumerated in §2.1.
4. **Path identifier resolution, left to right** — the entity-specific 404 from §2.6. Applies to every endpoint that carries an identifier in its path.
5. **Body reference resolution** — the entity-specific 404 from §2.6. Applies to the nine creation operations enumerated in §2.6.
6. **Request-body shape** — `ERR_INVALID_REQUEST` (422): a required field absent, an enum value outside its declared members, a number outside its declared range, a work-order interval whose `scheduled_end_at` is not strictly later than its `scheduled_start_at`, or a sweep survey reporting at least one tank without supplying all five tank descriptors. Applies to every write endpoint.
7. **Pagination bounds** — `ERR_INVALID_PAGINATION` (422). Applies to every list endpoint.
8. **Project version freshness** — `ERR_STALE_PROJECT_VERSION` (412). Applies to change-order creation and trust-fund-claim creation.
9. **State legality** — the target resource, and the project behind it, must be in a state from which the requested operation is declared. For project-targeted operations the code is `ERR_PROJECT_STATE_INVALID` (409); for other targets the entity-specific state code is used — `ERR_DISCLOSURE_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_SAMPLE_STATE_INVALID`, `ERR_CHANGE_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or `ERR_NFA_STATE_INVALID`, each HTTP 409. Applies to every action endpoint.
10. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403), on closure-letter issuance only.
11. **The regulatory safety family**, in this internal order: the fire-marshal notice effectiveness check (`ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE`, 409); the municipal permit checks (`ERR_PERMIT_NOT_ISSUED` and `ERR_PERMIT_EXPIRED`, both 409); the tank-located check (`ERR_NO_TANK_LOCATED`, 409); the disclosure window check (`ERR_DISCLOSURE_EXPIRED`, 409); the laboratory accreditation check (`ERR_LAB_NOT_ACCREDITED`, 409); the contamination-disclosure acknowledgement check (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, 409); and the closure blocker check (`ERR_NFA_BLOCKED`, 409).
12. **Referential integrity of optional links and reason fields**, in this internal order: `ERR_SUPERSEDE_TARGET_INVALID` (409), `ERR_RETEST_TARGET_INVALID` (409), then `ERR_METHOD_OVERRIDE_REASON_REQUIRED` (422).
13. **Temporal constraints**, in this internal order: `ERR_CREW_BOOKING_CONFLICT` (409), `ERR_LAB_CAPACITY_EXCEEDED` (409), `ERR_HOLDING_TIME_EXCEEDED` (409), then `ERR_CLOSING_DATE_IN_PAST` (422).
14. **Fiscal ceilings**, in this internal order: `ERR_EXCAVATION_LIMIT_EXCEEDED` (409), then `ERR_CLAIM_NOT_ELIGIBLE` (409).
15. **Uniqueness and quota constraints**, in this internal order: `ERR_DUPLICATE_DISCLOSURE` (409), `ERR_WORK_ORDER_ALREADY_OPEN` (409), `ERR_DUPLICATE_FINAL_CLAIM` (409), then `ERR_INFO_REQUEST_LIMIT_REACHED` (409).

Note two consequences of this ordering that implementers routinely get wrong. Because body shape (rule 6) precedes the tank-located check (rule 11), a sweep survey reporting zero tanks and omitting the tank descriptors passes shape validation — the descriptors are only required when at least one tank was found — and is then refused with `ERR_NO_TANK_LOCATED`. And because the required-reason check for a method override sits at rule 12 rather than with the other shape checks, a work order whose method contradicts the recommendation and whose override justification is missing is refused only after the crew-independent checks above it have all passed, and specifically *before* the crew calendar is consulted.

## 3. Business Logic & Workflows

### 3.1. Site Intake and the Tank-Locating Sweep Survey

A `ProjectCoordinator` opens the file by registering the **Property** — the residential site itself. Registration records the `street_address`, the `state_code` (one of `NJ`, `NY` or `CT`), the `county_code` that will appear on the municipal permit, the `homeowner_name` and `homeowner_email` that disclosures are addressed to, and the `insurance_carrier_code` of the carrier who will be notified of first-party and liability exposure. Two coverage figures may be supplied and otherwise take their defaults: `first_party_coverage_limit_cents`, which defaults to 2,000,000 cents — twenty thousand dollars of first-party property capacity — and `third_party_sublimit_cents`, which defaults to 5,000,000 cents, or fifty thousand dollars of liability sublimit. Neither may be negative. Registration also derives two read-only figures: `trust_fund_deductible_cents`, taken from the state deductible schedule for the property's `state_code`, and `open_project_count`, which starts at 0.

The state deductible schedule is fixed by statute and is the same schedule that later gets snapshotted onto every reimbursement claim: five hundred dollars in New Jersey, one thousand dollars in New York, and two hundred fifty dollars in Connecticut — 50,000, 100,000 and 25,000 cents respectively. `open_project_count` tracks how many of the property's projects are still live, meaning every `TankProject` on the property whose `status` is neither `CLOSED_SETTLED` nor `VOID`. It increments by 1 when a project is opened, and decrements by 1 when a project reaches either of those two terminal states.

Opening a **TankProject** requires only the `property_id`, though the coordinator may pin the excavation contract at the same time. `baseline_scope_cubic_yards` is the contracted excavation volume before any change order and defaults to 8.0 cubic yards; `excavation_limit_cubic_yards` is the hard ceiling that change-order approvals are measured against and defaults to 40.0 cubic yards. Both must be strictly greater than zero. A fresh project begins in `INTAKE` with `sampling_round` at 0, `contamination_class` at `UNCLASSIFIED`, `approved_scope_cubic_yards` equal to `baseline_scope_cubic_yards`, `remediation_cost_cents` at 0, and a blocker list that already names two obstacles — field work has not happened and contamination has not been cleared.

Locating the tank is the first substantive act, shared between the `ProjectCoordinator` and the `FieldTechnician`. The sweep survey advances the project `INTAKE → SURVEYED` and records the `survey_method` used — `GPR` for ground-penetrating radar, `MAGNETOMETER`, or `PROBE_ROD` — together with `tanks_detected_count` and, stamped from the logical clock, `survey_completed_at`. If the sweep locates nothing, that is, if `tanks_detected_count` is 0, the survey is refused with `ERR_NO_TANK_LOCATED` and the project stays in `INTAKE`; a project that never had a tank has no decommissioning to authorize. When at least one tank was located, all five tank descriptors must accompany the survey or the request is refused with `ERR_INVALID_REQUEST`: `tank_capacity_gallons` for nominal capacity, `tank_depth_to_top_inches` for the depth of cover over the tank crown, `tank_distance_to_foundation_inches` for horizontal clearance from the tank shell to the dwelling foundation, the boolean `tank_under_structure` indicating whether any part of the tank lies beneath a permanent structure, and `tank_material`, which is either `STEEL` or `FIBERGLASS`. Recording the survey also increments the project's `version` by 1.

**The removal-versus-abandonment recommendation.** Regulators in all three states permit a tank to be abandoned in place — cleaned, cut, filled and left — when digging it out would cost more risk than it removes, and require removal otherwise. The system reduces that judgement to a score, `method_score`, built from exactly the five tank descriptors just recorded; no other project data, and no sample data, participates. Five factors are computed independently, each clamped on its own before anything is summed:

- The **depth factor** rewards cover. Take the depth of cover in inches, subtract the 24 inches of cover that are treated as free, multiply the remainder by half a point per inch, then clamp the result into the range from 0.0 to 40.0. Cover of 24 inches or less contributes nothing; cover of 104 inches or more contributes the full 40.0.
- The **proximity factor** rewards being close to the house, where excavation risks undermining the foundation. Take 60 inches — the clearance below which the foundation is considered at concern — subtract the tank's actual clearance to the foundation, multiply the remainder by three quarters of a point per inch, then clamp into the range from 0.0 to 30.0. A tank 60 inches or further from the foundation contributes nothing; a tank flush against it contributes the full 30.0.
- The **structure factor** is 35.0 when `tank_under_structure` is true and 0.0 otherwise.
- The **capacity factor** is a two-step tier: 15.0 when `tank_capacity_gallons` is at least 1000, otherwise 8.0 when it is at least 550, otherwise 0.0.
- The **material factor** is 10.0 when `tank_material` is `STEEL` and 0.0 otherwise; fibreglass shells earn nothing here.

The five clamped factors are added together, that raw sum is capped at 100.0, and *only then* is the capped figure rounded half up to two decimal places to become `method_score`. The clamp-before-round order is pinned. `recommended_method` is then `ABANDONMENT_IN_PLACE` when `method_score` is at least 55.00, and `REMOVAL` otherwise. Both fields are read-only outputs of the survey; the method actually executed is captured separately, as `decommission_method`, when the crew begins work.

Alongside the ordinary single-project read, a computed posture snapshot is available to the `ProjectCoordinator`, the `LicensedSiteProfessional` and the `ComplianceOfficer`. It returns the project's `status`, its `contamination_class`, `approved_scope_cubic_yards`, `remediation_volume_cubic_yards`, `remediation_volume_basis`, `remediation_cost_cents`, `nfa_blockers`, the project's current `version`, and two convenience counts: `open_change_order_count`, the number of change orders on the project that are still in `DRAFT` or `SUBMITTED`, and `current_round_sample_count`, the number of soil samples whose `sampling_round` equals the project's current `sampling_round`. Projects may also be listed with optional `property_id` and `status` filters.

### 3.2. Homeowner Disclosure and Consent

New Jersey, New York and Connecticut all require that the homeowner be told what was found under their yard, and that they be given an opportunity to respond before work proceeds. A `ProjectCoordinator` sends a **HomeownerDisclosure** by naming the `tank_project_id` and the `disclosure_kind`, which is either `SWEEP_FINDINGS` for the results of the locating survey or `CONTAMINATION_FINDINGS` for the results of soil analysis. The notice is created in `PENDING` with `sent_at` stamped from the logical clock and `expires_at` derived as three days later — the response window is 72 hours. Only one notice of a given kind may be outstanding on a project at a time: attempting to send a second `SWEEP_FINDINGS` notice while an earlier one is still `PENDING` is refused with `ERR_DUPLICATE_DISCLOSURE`. Disclosures may be listed with optional `tank_project_id`, `disclosure_kind` and `status` filters.

Only the `Homeowner` may respond, and only on their own property's project. The response carries two fields: `response`, which is either `ACKNOWLEDGED` or `DECLINED`, and `response_channel`, recording how the homeowner replied — `EMAIL`, `PORTAL` or `WET_SIGNATURE`. A response to a notice that is no longer `PENDING` is refused with `ERR_DISCLOSURE_STATE_INVALID`.

Expiry is evaluated **first**, at the very start of the response, and it is a write. If the logical clock has passed `expires_at` while the notice was still `PENDING`, the server transitions the notice `PENDING → EXPIRED`, persists that transition, and only then rejects the incoming response with `ERR_DISCLOSURE_EXPIRED`. The homeowner who replies one minute late therefore finds their notice permanently expired rather than merely refused, and a fresh notice must be sent.

An acknowledgement inside the window transitions the notice `PENDING → ACKNOWLEDGED`, stamps `responded_at` from the logical clock and stores the `response_channel`. When the acknowledged notice was a `SWEEP_FINDINGS` notice and the project is sitting in `SURVEYED`, the project advances `SURVEYED → DISCLOSED`, which is the gate that permitting waits behind. When the acknowledged notice was a `CONTAMINATION_FINDINGS` notice, the project's closure blocker list is recomputed, because acknowledging contamination is one of the things that can clear a blocker.

A disclosure notice never leaves `ACKNOWLEDGED`, `DECLINED` or `EXPIRED` once it arrives there; all three are terminal, and a project needing a fresh answer needs a fresh notice.

A decline is far more consequential. The notice transitions `PENDING → DECLINED` with `responded_at` stamped, and when the declined notice was a `SWEEP_FINDINGS` notice on a project in `SURVEYED`, the project is voided outright: `SURVEYED → VOID`. The void carries a three-part cascade. Every `Permit` on the project whose `status` is `SUBMITTED` or `ISSUED` is transitioned to `REVOKED` with `revocation_reason` set to `HOMEOWNER_DECLINED`. Every `DecommissionWorkOrder` on the project whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS` is transitioned to `ABORTED` with `abort_reason` set to `PROJECT_VOIDED`, and its `billing_status` is transitioned to `WRITTEN_OFF`. And the property's `open_project_count` is decremented by 1. `VOID` is terminal — nothing further happens on that project.

### 3.3. Permitting and the Fire-Marshal Notice Window

Two authorizations must exist before a tank may be touched, and the system models them as two rows of the same **Permit** collection distinguished by `permit_type`. A `MUNICIPAL_DECOMMISSION` permit is the municipality's affirmative authorization to decommission. A `FIRE_MARSHAL_NOTIFICATION` is the statutory notice filed with the fire marshal, which is not an approval but a waiting period. A `ProjectCoordinator` files either one by naming the `tank_project_id` and the `permit_type`; the row is created in `SUBMITTED` with `submitted_at` stamped from the logical clock. Permits may be listed with optional `tank_project_id`, `permit_type` and `status` filters.

Only a `ComplianceOfficer` renders the authority's decision, supplying `decision` as `ISSUED`, `DENIED` or `REVOKED`. The three branches carry deliberately disjoint effects, and each is specified in full below.

**The `ISSUED` branch** requires the permit to be in `SUBMITTED`. For a `MUNICIPAL_DECOMMISSION` permit it additionally requires the project to be in `DISCLOSED`; for a `FIRE_MARSHAL_NOTIFICATION` it requires the project to be in either `DISCLOSED` or `PERMITTED`, since the fire-marshal notice may legitimately be filed and acknowledged after the municipal permit has already landed. On success the permit transitions `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock, and `expires_at` is derived as exactly 180 days after issuance, after which the permit lapses. The `notice_effective_at` field is where the two types diverge: for a `FIRE_MARSHAL_NOTIFICATION` it is 48 hours after `issued_at`, encoding the two-day statutory wait before ground may be broken, while for a `MUNICIPAL_DECOMMISSION` it is simply equal to `issued_at`. Finally, and only for a `MUNICIPAL_DECOMMISSION` permit, the project advances `DISCLOSED → PERMITTED`. Issuing a fire-marshal notification advances no project state.

**The `DENIED` branch** requires the permit to be in `SUBMITTED` and requires `denial_reason` to accompany the decision. The permit transitions `SUBMITTED → DENIED` and the free-text `denial_reason` is stored. Nothing else happens: the project's `status` is unchanged and remains `DISCLOSED`, no work order is touched, and no blocker is added. A denial is a dead end for that permit row, not for the project — a fresh application may be filed.

**The `REVOKED` branch** is the stop-work order. It requires the permit to be in `ISSUED` and requires `revocation_reason` to accompany the decision. The permit transitions `ISSUED → REVOKED`, the reason is stored, and two cascades fire. Every `DecommissionWorkOrder` on the project whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS` is transitioned to `ABORTED` with `abort_reason` set to `PERMIT_REVOKED`, and its `billing_status` is transitioned to `WRITTEN_OFF`. Then the project's closure blocker list is recomputed and now names `PERMIT_REVOKED`. A permit decision requested from a state that does not permit it — asking for `ISSUED` twice, or asking for `REVOKED` on a permit still in `SUBMITTED` — is refused with `ERR_PERMIT_STATE_INVALID`.

A permit may also lapse. `EXPIRED` is reached only by the system, and only at one moment: at the start of a crew mobilization attempt. If the project's `MUNICIPAL_DECOMMISSION` permit is `ISSUED` but the logical clock has passed its `expires_at`, the server writes the transition `ISSUED → EXPIRED` and persists it, then rejects the mobilization with `ERR_PERMIT_EXPIRED`. As with disclosure expiry, the lapse is recorded before the refusal, so the operator who mobilizes late discovers a genuinely dead permit rather than a transient error. `DENIED`, `REVOKED` and `EXPIRED` are all terminal for a permit row.

### 3.4. Crew Scheduling and Field Execution

A **Crew** is registered by a `ProjectCoordinator` with a `crew_name`, a `cert_level` recording the certification tier of the crew lead — `TANK_TECH_I`, `TANK_TECH_II` or `LSP_SUPERVISED` — and a `mobilization_buffer_minutes` figure that defaults to 90 and may not be negative. That buffer is the travel-and-decontamination allowance the scheduler must leave on both ends of any booking the crew takes, and it is applied symmetrically.

Scheduling a **DecommissionWorkOrder** is how field work is booked. The coordinator supplies the `tank_project_id`, the `crew_id` whose calendar will be occupied, the `method` to execute (`REMOVAL` or `ABANDONMENT_IN_PLACE`), and the booking interval as `scheduled_start_at` and `scheduled_end_at`. The interval is half-open: the start instant is inclusive and the end instant is exclusive, and the end must be strictly later than the start or the request is refused with `ERR_INVALID_REQUEST`. A work order is created with `field_status` at `SCHEDULED` and `billing_status` at `UNBILLED`. Work orders may be listed with optional `tank_project_id`, `crew_id`, `field_status` and `billing_status` filters.

Two guards constrain the booking. First, when the requested `method` differs from the project's `recommended_method`, the scheduler is overriding a computed regulatory recommendation and must justify it: `method_override_reason` is required in that case, and its absence is refused with `ERR_METHOD_OVERRIDE_REASON_REQUIRED`. When the method matches the recommendation, the field may be omitted. Second, a project may have at most one live work order: if the project already has a work order whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS`, the new booking is refused with `ERR_WORK_ORDER_ALREADY_OPEN`.

**The buffered crew calendar.** A crew cannot be in two places at once, and it cannot teleport between them. The overlap test therefore compares the *requested* interval, expanded by the crew's `mobilization_buffer_minutes` on both ends, against the *raw* intervals of the crew's existing bookings. The candidate set is every other `DecommissionWorkOrder` carrying the same `crew_id` whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS`; aborted and field-complete bookings release the calendar and are ignored. The booking is refused with `ERR_CREW_BOOKING_CONFLICT` when, for any candidate, the requested start minus the buffer falls strictly before that candidate's end **and** that candidate's start falls strictly before the requested end plus the buffer. Both comparisons are strict, so with the default 90-minute buffer — an hour and a half of travel and decontamination — a new booking that begins exactly 90 minutes after an existing booking ends is accepted, while one beginning 89 minutes after is not.

**The field dimension.** Field progress is driven by the `FieldTechnician` supplying an `event` of `MOBILIZE`, `START`, `COMPLETE` or `ABORT`. The dimension runs `SCHEDULED → MOBILIZED → IN_PROGRESS → FIELD_COMPLETE`, with `ABORTED` reachable from any of the first three; `FIELD_COMPLETE` and `ABORTED` are terminal. An event requested from a state that does not allow it is refused with `ERR_WORK_ORDER_STATE_INVALID`.

`MOBILIZE` moves `SCHEDULED → MOBILIZED` and is the most heavily gated event in the system, because it is the moment a crew physically arrives on a residential site. It requires the work order to be in `SCHEDULED` and the project to be in `PERMITTED`. It requires that the project carry a `FIRE_MARSHAL_NOTIFICATION` permit in `ISSUED` whose `notice_effective_at` is at or before the current logical instant — absence of such a notice, or arrival before its notice has taken effect, is refused with `ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE`. And it requires the project's `MUNICIPAL_DECOMMISSION` permit to be in `ISSUED`, failing which the refusal is `ERR_PERMIT_NOT_ISSUED`, and to be unexpired, failing which the permit is first flipped to `EXPIRED` as described in §3.3 and the refusal is `ERR_PERMIT_EXPIRED`.

`START` moves the field dimension `MOBILIZED → IN_PROGRESS` and requires the project to be in `PERMITTED`. It is also the moment the project's own lifecycle turns over: the project advances `PERMITTED → DECOMMISSIONING`, entering the `DECOMMISSIONING` state in which the tank is physically being pulled or filled, and the work order's `method` is copied onto the project as `decommission_method`, freezing what was actually executed independently of what had been recommended.

`COMPLETE` moves the field dimension `IN_PROGRESS → FIELD_COMPLETE` and requires the crew to report two numbers with the event: `actual_excavated_cubic_yards`, the volume actually dug, and `hauled_tons`, the tonnage of soil taken off site on weigh tickets. Both are mandatory; their absence is refused with `ERR_INVALID_REQUEST`. On success both values are stored on the work order and copied onto the project, the billing dimension advances `UNBILLED → BILLABLE`, the project's `sampling_round` moves from 0 to 1, and the project advances `DECOMMISSIONING → SAMPLING`. Confirmation sampling has now formally opened.

`ABORT` is accepted while `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS`, and requires an `abort_reason`. The work order transitions to `ABORTED` with that reason recorded, its `billing_status` is transitioned to `WRITTEN_OFF` whenever it currently stands at `UNBILLED`, `BILLABLE` or `INVOICED`, and the crew's booking interval is released so the crew's calendar no longer collides with future bookings. The identical treatment is applied when an abort arrives as a cascade rather than as an operator action — from a permit revocation, where `abort_reason` reads `PERMIT_REVOKED`, or from a project void, where it reads `PROJECT_VOIDED`.

### 3.5. The Billing Dimension and the Surveyed Close-Out Volume

A work order carries a second, **independent** state dimension. `billing_status` evolves on its own timeline and is never inferred from `field_status`: a work order can sit at `INVOICED` while its project has already moved on to `SAMPLING` or `REMEDIATION_ACTIVE`. It runs `UNBILLED → BILLABLE → INVOICED → RECONCILED`, with `WRITTEN_OFF` reachable as an escape; `RECONCILED` and `WRITTEN_OFF` are terminal.

The first step is not an operator action at all. `UNBILLED → BILLABLE` is written by the system as a side effect of a successful field `COMPLETE`, and it fires only when the billing dimension is standing at `UNBILLED` — the billing dimension advances from `UNBILLED` by that route alone. Thereafter a `ProjectCoordinator` drives the dimension by supplying an `event` of `INVOICE`, `RECONCILE` or `WRITE_OFF`.

`INVOICE` moves `BILLABLE → INVOICED` and requires nothing beyond the billing dimension standing at `BILLABLE`; field progress is irrelevant to it.

`RECONCILE` moves `INVOICED → RECONCILED` and is the close-out act, so it carries three preconditions: the billing dimension must stand at `INVOICED`, the field dimension must have reached `FIELD_COMPLETE`, and the project's `remediation_started` latch must be true. Reconciliation has one substantive effect beyond the state change: it recomputes the project's `remediation_volume_cubic_yards` under the **`FINAL_SURVEYED`** variant and sets `remediation_volume_basis` to `FINAL_SURVEYED`.

That variant is the surveyed truth rather than an estimate. It reads exactly one input — the project's `hauled_tons` as reported by the crew at field completion — and ignores every soil sample. The tonnage is divided by a soil density of 1.35 tons per cubic yard, and the quotient is rounded half up to two decimal places. Because it measures removed mass rather than impacted footprint, it will disagree with the provisional grid estimate that §3.7 describes even on identical project data; that disagreement is expected and is exactly why `remediation_volume_basis` exists.

`WRITE_OFF` is accepted while `billing_status` stands at `UNBILLED`, `BILLABLE` or `INVOICED`, and moves the dimension to `WRITTEN_OFF`. A billing event requested from a state that does not allow it is refused with `ERR_WORK_ORDER_STATE_INVALID`.

### 3.6. Soil Sampling, Chain of Custody and Laboratory Reporting

A **Laboratory** is registered by a `ComplianceOfficer` with a `lab_name` and four operating parameters. `accredited` defaults to true and records whether the lab holds state accreditation; an unaccredited lab may not take custody of samples at all. `committed_turnaround_hours` defaults to 72 and serves double duty — it is both the contractual turnaround the lab promises and the length of time each sample occupies one of the lab's analysis slots. `holding_time_hours` defaults to 336, which is the fourteen days a petroleum aliquot may sit between collection and laboratory receipt. `max_concurrent_analyses` defaults to 2 and is the aggregate number of overlapping analysis windows the lab can sustain; it must be at least 1, while the two hour figures must both be strictly greater than zero.

The `FieldTechnician` logs a **SoilSample** by naming the `tank_project_id`, the `work_order_id` for the excavation the aliquot came from, and the `laboratory_id` that will analyse it, plus the `sample_point` describing where within the excavation the aliquot was taken — `TANK_BOTTOM`, `NORTH_SIDEWALL`, `SOUTH_SIDEWALL`, `STOCKPILE` or `CONFIRMATION_FLOOR` — and `depth_inches`, the depth below grade, which must be strictly greater than zero. The sample is created in `COLLECTED` with `collected_at` stamped from the logical clock and `collected_by_user_id` set from `X-User-ID`. Its own `sampling_round` is set to the project's `sampling_round` at the moment of collection, and the project's blocker list is recomputed, now naming `SAMPLES_PENDING`. Samples may be listed with optional `tank_project_id`, `work_order_id`, `laboratory_id`, `retest_of_sample_id`, `sampling_round` and `status` filters.

A sample may also be a **retest**. Supplying `retest_of_sample_id` declares that this aliquot re-tests an earlier one that was thrown out; the named row must belong to the same project and must be in `INVALIDATED`, and any other target is refused with `ERR_RETEST_TARGET_INVALID`. A retest that lands a good result is what clears the invalidated-sample blocker described in §3.9.

**Opening a new confirmation round.** Logging a sample is also the act that reopens sampling after remediation. When the project stands at `REMEDIATION_ACTIVE`, the first sample created transitions the project `REMEDIATION_ACTIVE → SAMPLING`: `sampling_round` increments by 1, and it is the *incremented* value that the new sample records as its own `sampling_round`. The project's `contamination_class` is reset to `UNCLASSIFIED` and both `max_tph_mg_kg` and `max_benzene_mg_kg` are reset to null, because the previous round's maxima no longer describe the site. That reopening is blocked while remediation scoping is unsettled: if the project has any `RemediationChangeOrder` still in `DRAFT` or `SUBMITTED`, the request is refused. Samples created while the project is already in `SAMPLING` do **not** increment `sampling_round`; they simply join the round in progress.

**Chain of custody.** Three custody events are recorded through a single operation that takes an `event`. `DISPATCH` is a `FieldTechnician` act: it moves the sample `COLLECTED → IN_TRANSIT` and stamps `dispatched_at` from the logical clock. `VOID` is also a technician act, accepted while the sample is in `COLLECTED` or `IN_TRANSIT`, and moves it to `VOIDED`; a voided sample stops counting toward round completeness and toward the closure blockers entirely. `RECEIVE` is a `LabAnalyst` act, permitted only to the lab named as the sample's `laboratory_id`, and moves the sample `IN_TRANSIT → AT_LAB`. A custody event requested from a state that does not allow it is refused with `ERR_SAMPLE_STATE_INVALID`.

Receipt carries three gates, evaluated in order. First, the receiving lab's `accredited` flag must be true, or the receipt is refused with `ERR_LAB_NOT_ACCREDITED`. Second, the holding time is computed and checked: `holding_time_elapsed_hours` is the interval from `collected_at` to the current logical instant expressed in hours and rounded half up to two decimal places. If that figure **strictly exceeds** the lab's `holding_time_hours`, the aliquot is legally worthless, and the server records that fact before refusing: the sample transitions `IN_TRANSIT → INVALIDATED`, its `qc_flag` is set to `HOLDING_TIME_EXCEEDED`, `holding_time_elapsed_hours` is persisted, `received_at` is left null, the project's blocker list is recomputed and now names `INVALIDATED_SAMPLE_WITHOUT_RETEST`, and only then is the receipt rejected with `ERR_HOLDING_TIME_EXCEEDED`. An elapsed figure exactly equal to the permitted maximum is compliant and receipt proceeds. Third, the lab's analysis capacity must be free. Count the lab's other samples — same `laboratory_id`, `status` at `AT_LAB` — whose analysis window contains the receipt instant, where a window runs from that sample's `received_at` to `received_at` plus the lab's `committed_turnaround_hours` and **both endpoints count as inside**. If that count has already reached `max_concurrent_analyses`, the receipt is refused with `ERR_LAB_CAPACITY_EXCEEDED`; it proceeds only while the count is strictly below capacity. On success `received_at` is stamped from the logical clock, starting this sample's own analysis window.

**Reporting the result.** The owning `LabAnalyst` posts the analysis by supplying `tph_mg_kg`, the total petroleum hydrocarbons figure, and `benzene_mg_kg`, the benzene concentration. Both are required and neither may be negative. The sample must be in `AT_LAB`. On success the sample transitions `AT_LAB → RESULTED`, `reported_at` is stamped from the logical clock, and two timing figures are derived: `turnaround_hours` is the interval from `received_at` to `reported_at` in hours rounded half up to two decimal places, and `turnaround_breach` is true only when that figure strictly exceeds the lab's `committed_turnaround_hours` — a turnaround landing exactly on the commitment is not a breach. A sample's `qc_flag` otherwise reads `NONE`.

**Closing the round and classifying the site.** Posting a result is also when the server asks whether the confirmation round is finished. The round is complete when the project has no sample in the current `sampling_round` whose `status` is `COLLECTED`, `IN_TRANSIT` or `AT_LAB`, and at least one whose `status` is `RESULTED`. When both hold, the project advances `SAMPLING → ASSESSED` and its classification is recomputed.

The classification reads **only** the samples of the project's current `sampling_round` whose `status` is `RESULTED`. Samples that are `INVALIDATED`, `VOIDED`, `COLLECTED`, `IN_TRANSIT` or `AT_LAB` are excluded, as are all samples from earlier rounds. If that set is empty, `max_tph_mg_kg` and `max_benzene_mg_kg` are both null and `contamination_class` is `UNCLASSIFIED`. Otherwise `max_tph_mg_kg` is the highest `tph_mg_kg` in the set and `max_benzene_mg_kg` the highest `benzene_mg_kg`, and the class is decided by two tiers of strictly-greater-than comparisons: the class is `GROSS` when `max_tph_mg_kg` exceeds 5000.0 mg/kg or `max_benzene_mg_kg` exceeds 5.0 mg/kg; failing that it is `ELEVATED` when `max_tph_mg_kg` exceeds the 500.0 mg/kg action level or `max_benzene_mg_kg` exceeds the 0.5 mg/kg action level; and failing both it is `CLEAN`.

The moment the project enters `ASSESSED`, it is routed onward, and the two branches are mutually exclusive and immediate. When `contamination_class` is `CLEAN`, the project advances `ASSESSED → CLEARED` and nothing else changes. When `contamination_class` is `ELEVATED` or `GROSS`, the project advances `ASSESSED → REMEDIATION_ACTIVE` and a five-part cascade fires: `contamination_disclosure_required` is latched true, `remediation_started` is latched true, `remediation_volume_cubic_yards` is recomputed under the `PROVISIONAL_GRID` variant with `remediation_volume_basis` set to `PROVISIONAL_GRID`, `remediation_cost_cents` is recomputed, and that cost change in turn re-runs the insurance waterfall over every one of the project's insurance notifications whose `status` is not `CLOSED`, rewriting each one's allocation and then re-deriving each one's `status`.

**Retracting a result.** A `LabAnalyst` may retract a result it posted, supplying a `reason`. Retraction requires the sample to be in `RESULTED`, requires the acting analyst to own the sample's laboratory, and requires the project to be in `SAMPLING`, `ASSESSED`, `CLEARED` or `REMEDIATION_ACTIVE`; a project already at `CLOSED_NFA` or `CLOSED_SETTLED` is past the point where a laboratory may reopen it, and the attempt is refused. The retraction is also scoped to the current round: the sample's `sampling_round` must equal the project's `sampling_round`. On success the sample transitions `RESULTED → INVALIDATED` and its `qc_flag` is set to `RESULT_RETRACTED`, while `tph_mg_kg` and `benzene_mg_kg` are deliberately preserved for audit rather than cleared. The project is then walked backwards to `SAMPLING` from whichever of the three post-assessment states it occupied — `ASSESSED → SAMPLING`, `CLEARED → SAMPLING` or `REMEDIATION_ACTIVE → SAMPLING` — with `contamination_class` reset to `UNCLASSIFIED` and both `max_tph_mg_kg` and `max_benzene_mg_kg` reset to null in each case. The blocker list is recomputed and now names both `INVALIDATED_SAMPLE_WITHOUT_RETEST` and `CONTAMINATION_NOT_CLEARED`. Note that retraction does *not* increment `sampling_round`; the round stays open and awaits a retest. Both `INVALIDATED` and `VOIDED` are terminal for a sample — a discredited aliquot is never rehabilitated, and the only remedy is a fresh sample naming it through `retest_of_sample_id`.

### 3.7. Remediation Scoping: Change Orders, the Excavation Ceiling and Cost

When a project is `REMEDIATION_ACTIVE`, the licensed professional's job is to say how much more soil must come out and what that will cost. A `LicensedSiteProfessional` drafts a **RemediationChangeOrder** naming the `tank_project_id`, the `additional_cubic_yards` of extra excavation requested (strictly greater than zero), the `unit_rate_cents` per cubic yard before disposal loading (strictly greater than zero), and the `disposal_class`, which is either `NON_HAZARDOUS` or `HAZARDOUS`. The draft must be authored against a current view of the project, so `expected_project_version` accompanies it as described in §2.8. A change order may also carry `supersedes_change_order_id`, naming an already-approved change order on the same project that this one replaces; a target on another project, or one whose `status` is anything other than `APPROVED`, is refused with `ERR_SUPERSEDE_TARGET_INVALID`. The row is created in `DRAFT` with `requested_by_user_id` set from `X-User-ID`, the project's `version` is incremented by 1, and the project's blocker list is recomputed and now names `OPEN_CHANGE_ORDER`. Change orders may be listed with optional `tank_project_id`, `supersedes_change_order_id` and `status` filters.

Submission is the author's own act: the same `LicensedSiteProfessional` whose identifier is recorded as `requested_by_user_id` moves the row `DRAFT → SUBMITTED`, and only while the project stands at `REMEDIATION_ACTIVE`. The blocker list is recomputed, and `OPEN_CHANGE_ORDER` remains present for as long as any row on the project sits in `DRAFT` or `SUBMITTED`. Submit or decision requested from a state that does not allow it is refused with `ERR_CHANGE_ORDER_STATE_INVALID`.

A `ComplianceOfficer` then supplies a `decision` of `APPROVED` or `REJECTED`, optionally with a `decision_note`. Both branches require the row to be in `SUBMITTED`, and both are specified in full.

**Approval** additionally requires the project to be in `REMEDIATION_ACTIVE`, re-checks that any named `supersedes_change_order_id` still points at an `APPROVED` row on the same project — a target that has moved on is refused with `ERR_SUPERSEDE_TARGET_INVALID` at decision time exactly as it would be at draft time — and enforces the excavation ceiling. The ceiling test is computed prospectively: take the project's `baseline_scope_cubic_yards`, add the `additional_cubic_yards` of every change order that would be in `APPROVED` status once this approval and any supersession it triggers have been applied, and require the total to be at or below the project's `excavation_limit_cubic_yards`. A total exceeding the ceiling is refused with `ERR_EXCAVATION_LIMIT_EXCEEDED`; a total landing exactly on it is permitted. On success the row transitions `SUBMITTED → APPROVED`, `approved_by_user_id` is set from `X-User-ID`, `decided_at` is stamped from the logical clock, and `line_amount_cents` is computed. When `supersedes_change_order_id` was supplied, that prior row transitions `APPROVED → SUPERSEDED` and its `decided_at` is cleared to null, which is how its `additional_cubic_yards` leaves the approved-scope sum. The project's `approved_scope_cubic_yards` and `remediation_cost_cents` are then recomputed, the cost change re-runs the insurance waterfall over every non-closed notification of the project and re-derives each notification's `status`, and the blocker list is recomputed.

**Rejection** transitions the row `SUBMITTED → REJECTED`, sets `approved_by_user_id` from `X-User-ID` and stamps `decided_at` from the logical clock. It has no fiscal effect at all: `approved_scope_cubic_yards` and `remediation_cost_cents` are left exactly as they were. The blocker list is recomputed, and `OPEN_CHANGE_ORDER` drops away once no row on the project remains in `DRAFT` or `SUBMITTED`. `REJECTED` and `SUPERSEDED` are both terminal for a change-order row.

**Approved scope.** The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`. Rows in `DRAFT`, `SUBMITTED`, `REJECTED` or `SUPERSEDED` contribute nothing.

**Remediation cost.** The project's `remediation_cost_cents` is rebuilt in three pinned steps whenever it is touched — when the project enters `REMEDIATION_ACTIVE`, when a change order is approved, when one is superseded, and when a closure letter is rescinded.

*Step one* computes each line amount, iterating the project's change orders whose `status` is `APPROVED` in ascending `created_at` order — never in identifier order. For each such row, multiply its `additional_cubic_yards` by its `unit_rate_cents`, then by the disposal multiplier for its `disposal_class`: a factor of 1.0 for `NON_HAZARDOUS` soil, and a factor of 1.85 for `HAZARDOUS` soil, reflecting the eighty-five percent premium a licensed hazardous-waste facility charges over an ordinary landfill. Round that product half up to whole cents and store it as that row's `line_amount_cents`.

*Step two* sums those already-rounded integer line amounts. Rounding per line before summing is required; summing the unrounded products and rounding once at the end produces a different figure whenever two or more lines carry a half-cent remainder, and is wrong.

*Step three* adds mobilization, but only once remediation has genuinely begun. While the project's `remediation_started` latch is false, `remediation_cost_cents` is 0 regardless of what any change order says. Once the latch is true, `remediation_cost_cents` is the flat mobilization charge of 185,000 cents — one thousand eight hundred fifty dollars — plus the line total from step two.

**The provisional grid volume.** When a project first enters `REMEDIATION_ACTIVE`, nothing has been dug yet, so the volume that drives change-order scoping and the insurance reserve has to be estimated from sample geometry. The `PROVISIONAL_GRID` variant considers only the *impacted* samples: those on the project whose `sampling_round` equals the project's current round, whose `status` is `RESULTED`, and whose `tph_mg_kg` **strictly exceeds** the 500.0 mg/kg action level. If no sample qualifies, the volume is 0.00. Otherwise the impacted footprint is the number of qualifying samples multiplied by 100.0 square feet, the grid cell each sample point is taken to represent; the depth is the greatest `depth_inches` among the qualifying samples converted to feet by dividing by 12; the footprint is multiplied by that depth to give cubic feet; that figure is divided by the 27 cubic feet in a cubic yard; and the quotient is rounded half up to two decimal places. Because the estimate grows with the number of exceeding sample points and is entirely independent of what was actually hauled, it will differ from the `FINAL_SURVEYED` figure of §3.5 — which is exactly why `remediation_volume_basis` records which of the two produced the number currently stored.

### 3.8. Insurance Tender and the Reserve Waterfall

A `ComplianceOfficer` opens an **InsuranceNotification** by naming the `tank_project_id` and the `notification_kind`, which is either `FIRST_PARTY` for a property claim against the homeowner's own policy or `THIRD_PARTY_LIABILITY` for a tender of liability exposure — a neighbouring property's contaminated well, typically. The row is created in `OPEN`, `carrier_code` is snapshotted from the project's property `insurance_carrier_code`, and `notified_at` is stamped from the logical clock. Creating a notification immediately runs the waterfall across the project's notifications and re-derives each status. Notifications may be listed with optional `tank_project_id`, `notification_kind` and `status` filters.

**The waterfall.** The allocation answers one question — who pays the project's `remediation_cost_cents` — and it fills three buckets in a fixed order that never varies with creation time or identifier: first-party coverage, then third-party liability, then the homeowner. It is pure integer-cent arithmetic with no rounding anywhere.

Bucket one is first-party property coverage, whose capacity is the property's `first_party_coverage_limit_cents`. `first_party_allocated_cents` is the smaller of the project's `remediation_cost_cents` and that capacity.

Bucket two is the third-party liability sublimit, and its capacity is conditional. It equals the property's `third_party_sublimit_cents` **only if** the project has at least one notification whose `notification_kind` is `THIRD_PARTY_LIABILITY` and whose `status` is `OPEN`, `RESERVED` or `THIRD_PARTY_REVIEW`; with no such live tender on the project, bucket two's capacity is zero. `third_party_allocated_cents` is then the smaller of the cost remaining after bucket one and that capacity.

Bucket three is the homeowner, and it is unbounded. `homeowner_out_of_pocket_cents` is the project's `remediation_cost_cents` less `first_party_allocated_cents` less `third_party_allocated_cents`. Finally `reserve_amount_cents` is `first_party_allocated_cents` plus `third_party_allocated_cents` — the carrier's total exposure. Every non-closed notification on the project carries the identical triple, and the three parts always sum exactly to the project's `remediation_cost_cents`.

**Status derivation.** Each time the waterfall rewrites a notification, that notification re-derives its own `status` from the freshly written figures, and the rule is a strict cascade with no memory: the status becomes `THIRD_PARTY_REVIEW` when `third_party_allocated_cents` is greater than zero; failing that, `RESERVED` when `reserve_amount_cents` is greater than zero; and failing both, `OPEN`. Every one of the resulting movements is a system transition with no operator endpoint behind it: `OPEN → RESERVED` when a reserve exists with no third-party share, `OPEN → THIRD_PARTY_REVIEW` and `RESERVED → THIRD_PARTY_REVIEW` when a third-party share appears, and `THIRD_PARTY_REVIEW → RESERVED` when the third-party share falls back to zero while a reserve remains. A notification whose `status` is `CLOSED` is excluded from the rewrite entirely and never re-derives anything.

The waterfall re-runs on every occasion the project's `remediation_cost_cents` moves — the project entering `REMEDIATION_ACTIVE`, a change order being approved, a change order being superseded, and a closure letter being rescinded — as well as on the creation of a notification. Closure is the one movement the waterfall does not drive: when the project settles, every notification whose `status` is `OPEN`, `RESERVED` or `THIRD_PARTY_REVIEW` is transitioned to `CLOSED` and its allocation figures are frozen at their then-current values. `CLOSED` is terminal.

### 3.9. Trust-Fund Reimbursement, No-Further-Action Closure and Settlement

**Filing a claim.** Each of the three states runs a petroleum trust fund that reimburses homeowners for remediation, and a `ComplianceOfficer` applies on the project's behalf by creating a **TrustFundClaim**. The application names the `tank_project_id`, the `variant` — either `PRELIMINARY_ESTIMATE` for the interim application filed while remediation is still open, or `FINAL_SETTLEMENT` for the close-out application — and the `claimed_costs_cents` submitted to the fund, which must be strictly greater than zero. It must also carry `expected_project_version` per §2.8. The claim is created in `DRAFT`, its `state_code` is snapshotted from the project's property, the project's `version` is incremented by 1, and the full eligibility breakdown is computed. Claims may be listed with optional `tank_project_id`, `variant` and `status` filters. A project may hold at most one `FINAL_SETTLEMENT` claim whose `status` is neither `DENIED` nor `WITHDRAWN`; a second is refused with `ERR_DUPLICATE_FINAL_CLAIM`.

Creating a `FINAL_SETTLEMENT` claim also **withdraws the interim application**. Every `PRELIMINARY_ESTIMATE` claim on the same project whose `status` is `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` is transitioned to `WITHDRAWN`, and the code `SUPERSEDED_BY_FINAL_SETTLEMENT` is appended to that claim's `eligibility_findings`. Claims in `APPROVED`, `PAID` or `DENIED` are untouched, and `FINAL_SETTLEMENT` claims are never withdrawn by this rule.

**The eligibility calculation.** Eight steps run exactly once, in a pinned order, with no iteration. The dependency looks circular — the cap is keyed on the gross figure while the fee is keyed on the capped figure and the eligible amount is keyed on both — but executing the steps once in sequence resolves it. The calculation reads nothing beyond the claim's own `claimed_costs_cents`, its snapshotted `state_code` and its `variant`; no project or change-order data participates.

1. The gross figure is the claim's `claimed_costs_cents`.
2. `deductible_cents` is taken from the state deductible schedule for the claim's snapshotted `state_code`: five hundred dollars for `NJ`, one thousand dollars for `NY`, two hundred fifty dollars for `CT`.
3. `cap_cents` is the reimbursement ceiling selected by the gross figure across three tiers: forty thousand dollars when the gross figure is at most fifty thousand dollars; ninety thousand dollars when it is at most one hundred twenty thousand dollars; and one hundred twenty-five thousand dollars above that. In cents, the tier boundaries are 5,000,000 and 12,000,000, and the caps are 4,000,000, 9,000,000 and 12,500,000.
4. The capped figure is the smaller of the gross figure and `cap_cents`.
5. `admin_fee_cents` is the capped figure multiplied by the fund's administrative rate of three and a half percent, rounded half up to whole cents.
6. The net figure depends on the `variant`, and this is the *only* place the two variants differ. Under `PRELIMINARY_ESTIMATE`, the cap is applied to the gross figure first and the deductible is then subtracted from the already-capped figure: take the capped figure less `deductible_cents`, floor that difference at zero, and subtract `admin_fee_cents`. Under `FINAL_SETTLEMENT`, the deductible is subtracted from the gross figure first and the cap is applied to the net: take the gross figure less `deductible_cents`, take the smaller of that difference and `cap_cents`, floor the result at zero, and subtract `admin_fee_cents`. For identical `claimed_costs_cents` above the cap, the close-out variant therefore yields an eligible amount exactly one deductible higher than the interim variant, because the interim variant makes the deductible come out of the reimbursable ceiling while the close-out variant makes it come out of the gross costs.
7. `eligible_amount_cents` is the net figure floored at zero.
8. `unreimbursed_balance_cents` is `eligible_amount_cents` less `reimbursed_amount_cents`, the latter being 0 until cash is actually disbursed.

**Submission and the review cycle.** A claim is submitted by a `ComplianceOfficer` from `DRAFT` or from `INFO_REQUESTED`, transitioning to `SUBMITTED` with `submitted_at` stamped from the logical clock. Submission from `DRAFT` requires the project to be in `ASSESSED`, `REMEDIATION_ACTIVE`, `CLEARED` or `CLOSED_NFA`, requires `eligible_amount_cents` to be strictly greater than zero — a zero-value claim is refused with `ERR_CLAIM_NOT_ELIGIBLE` — and, when the project's `contamination_disclosure_required` latch is true, requires that a `CONTAMINATION_FINDINGS` disclosure on the project already stand at `ACKNOWLEDGED`; a missing acknowledgement is refused with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`. Re-submission from `INFO_REQUESTED` requires the same set of project states but not the eligibility or disclosure re-checks. Submit or decision requested from a claim state that does not allow it is refused with `ERR_CLAIM_STATE_INVALID`.

Review decisions are recorded by a `ComplianceOfficer` supplying a `decision` and an optional `decision_note`. `UNDER_REVIEW` is accepted from `SUBMITTED` and simply opens the review. `INFO_REQUESTED` is accepted from `UNDER_REVIEW` and increments `info_request_count` by 1; because the fund permits at most two rounds of questions, the decision is available only while `info_request_count` is strictly below 2, and a third attempt is refused with `ERR_INFO_REQUEST_LIMIT_REACHED`. The cycle `SUBMITTED → UNDER_REVIEW → INFO_REQUESTED → SUBMITTED` may therefore run twice at most. `APPROVED` is accepted from `UNDER_REVIEW`, requires `eligible_amount_cents` to be strictly greater than zero — otherwise `ERR_CLAIM_NOT_ELIGIBLE` — and stamps `decided_at` from the logical clock. `DENIED` is accepted from `UNDER_REVIEW`, stamps `decided_at`, and sets `reimbursed_amount_cents` to 0. `DENIED`, `PAID` and `WITHDRAWN` are the claim's terminal states.

**Closure blockers.** Before any letter can be signed, the project publishes an explicit, machine-readable list of everything standing in the way. `nfa_blockers` is recomputed on every mutation of the project or of any of its disclosures, permits, samples or change orders, and it is assembled from seven independent tests:

- `CONTAMINATION_NOT_CLEARED` is present whenever the project's `contamination_class` is anything other than `CLEAN` — including `UNCLASSIFIED`.
- `SAMPLES_PENDING` is present whenever the project has at least one sample in the current `sampling_round` whose `status` is `COLLECTED`, `IN_TRANSIT` or `AT_LAB`.
- `INVALIDATED_SAMPLE_WITHOUT_RETEST` is present whenever the project has at least one sample in the current `sampling_round` whose `status` is `INVALIDATED` for which no sample exists whose `retest_of_sample_id` names it and whose own `status` is `RESULTED`. A successful retest is what removes it.
- `OPEN_CHANGE_ORDER` is present whenever the project has at least one change order in `DRAFT` or `SUBMITTED`.
- `CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED` is present whenever the project's `contamination_disclosure_required` latch is true and the project has no `CONTAMINATION_FINDINGS` disclosure standing at `ACKNOWLEDGED`.
- `PERMIT_REVOKED` is present whenever the project has at least one `MUNICIPAL_DECOMMISSION` permit whose `status` is `REVOKED` or `EXPIRED`.
- `FIELD_WORK_INCOMPLETE` is present whenever the project has no work order whose `field_status` is `FIELD_COMPLETE`.

The resulting codes are deduplicated and sorted lexicographically ascending — never by creation time or identifier — so the list is stable and directly comparable between reads. Closure requires it to be empty.

**Drafting and signing the letter.** A `LicensedSiteProfessional` drafts an **NFALetter** naming the `tank_project_id` and the `closing_date`, the scheduled real-estate closing the letter is needed for. The row is created in `DRAFT` with `drafted_by_user_id` set from `X-User-ID`. Letters may be listed with optional `tank_project_id` and `status` filters.

Issuance is a **second** `LicensedSiteProfessional`'s act, and it carries five preconditions: the letter must be in `DRAFT`; the project must be in `CLEARED`; the project's `nfa_blockers` must be empty, failing which the attempt is refused with `ERR_NFA_BLOCKED`; the acting `X-User-ID` must differ from `drafted_by_user_id`, failing which the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`; and the letter's `closing_date` must be at or after the current logical instant, failing which the attempt is refused with `ERR_CLOSING_DATE_IN_PAST` — a letter cannot be issued for a closing that has already happened. On success the letter transitions `DRAFT → ISSUED`, `issued_at` is stamped from the logical clock, `issued_by_user_id` is set from `X-User-ID`, and the project advances `CLEARED → CLOSED_NFA`. Issue or rescind requested from a letter state that does not allow it is refused with `ERR_NFA_STATE_INVALID`.

**Settlement.** With the project at `CLOSED_NFA`, an approved claim can be paid. A `ComplianceOfficer` records a `decision` of `PAID`, which requires the claim to be in `APPROVED` and the project to be in `CLOSED_NFA`. The claim transitions `APPROVED → PAID`, `paid_at` is stamped from the logical clock, `reimbursed_amount_cents` is set equal to `eligible_amount_cents`, and `unreimbursed_balance_cents` becomes 0. The project then advances `CLOSED_NFA → CLOSED_SETTLED`, every insurance notification on the project whose `status` is not `CLOSED` is transitioned to `CLOSED` with its allocation figures frozen, and the property's `open_project_count` is decremented by 1. `CLOSED_SETTLED` is terminal, and it is the only satisfactory ending the workflow has.

**Rescission — walking the closure backwards.** Occasionally a closure has to be undone: a neighbouring property's monitoring well comes back dirty, or a regulator reopens the file. A `ComplianceOfficer` rescinds an issued letter by supplying a `rescission_reason`, which is required; the letter must be in `ISSUED` and the project in `CLOSED_NFA`. The letter transitions `ISSUED → RESCINDED` with `rescinded_at` stamped from the logical clock, and a four-level cascade follows.

The project transitions `CLOSED_NFA → REMEDIATION_ACTIVE`, its `contamination_class` is reset to `UNCLASSIFIED`, both `remediation_volume_cubic_yards` and `remediation_volume_basis` are reset to null, and `remediation_started` remains true. The project's departure from `CLOSED_NFA` then walks back every `TrustFundClaim` on it whose `status` is `APPROVED`: each is transitioned `APPROVED → UNDER_REVIEW`, its `reimbursed_amount_cents` is reset to 0, its `decided_at` is cleared to null, its `unreimbursed_balance_cents` is recomputed — which, with nothing reimbursed, restores it to the full `eligible_amount_cents` — and the code `NFA_RESCINDED_REVALIDATION_REQUIRED` is appended to its `eligibility_findings`, which like all finding lists is kept sorted ascending. Claims already `PAID` are not reopened by this rule. Finally the project's re-entry into `REMEDIATION_ACTIVE` recomputes `remediation_cost_cents`, which re-runs the insurance waterfall over every notification of the project whose `status` is not `CLOSED`, and each rewritten notification re-derives its `status` exactly as described in §3.8. From `REMEDIATION_ACTIVE`, the project can be re-sampled, re-scoped and re-closed by the same route it took the first time — but the rescinded letter itself is finished: `RESCINDED` is terminal for a letter, so re-closure requires a freshly drafted and separately signed one.

## 4. Endpoint Definitions

All collections are mounted at the service root. Creating a new resource returns HTTP 201 with the created resource in the envelope's `data` field; every other successful operation — reads, list reads, and the action endpoints that advance a state machine — returns HTTP 200 with the affected or requested resource. The table below is a routing summary only: request payloads, response contents and side effects are specified in §2 and §3, and the trigger conditions of the error codes are specified there as well.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/properties` | Register a residential tank site. | ProjectCoordinator |
| GET | `/properties/{id}` | Read one property. | ProjectCoordinator, FieldTechnician, LabAnalyst, LicensedSiteProfessional, ComplianceOfficer, Homeowner |
| POST | `/tank-projects` | Open a decommissioning project on a property. | ProjectCoordinator |
| GET | `/tank-projects` | List projects, optionally filtered by property or status. | ProjectCoordinator, FieldTechnician, LabAnalyst, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/tank-projects/{id}` | Read one project, including all computed fields and its current version. | ProjectCoordinator, FieldTechnician, LabAnalyst, LicensedSiteProfessional, ComplianceOfficer, Homeowner |
| GET | `/tank-projects/{id}/summary` | Computed read: posture snapshot used by the coordinator dashboard. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/tank-projects/{id}/sweep-survey` | Record the tank-locating sweep survey and derive the removal-versus-abandonment recommendation. | ProjectCoordinator, FieldTechnician |
| POST | `/disclosures` | Send a homeowner disclosure notice for sweep findings or contamination findings. | ProjectCoordinator |
| GET | `/disclosures` | List disclosures, optionally filtered by project, kind or status. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer, Homeowner |
| GET | `/disclosures/{id}` | Read one disclosure. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer, Homeowner |
| POST | `/disclosures/{id}/respond` | Homeowner acknowledges or declines a disclosure notice. | Homeowner |
| POST | `/permits` | File a municipal decommissioning permit application or the statutory fire-marshal notification. | ProjectCoordinator |
| GET | `/permits` | List permits, optionally filtered by project, type or status. | ProjectCoordinator, FieldTechnician, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/permits/{id}` | Read one permit. | ProjectCoordinator, FieldTechnician, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/permits/{id}/decision` | Authority issues, denies or revokes the permit; the three branches carry disjoint side-effect sets. | ComplianceOfficer |
| POST | `/crews` | Register an excavation crew and its symmetric mobilization buffer. | ProjectCoordinator |
| GET | `/crews/{id}` | Read one crew. | ProjectCoordinator, FieldTechnician, ComplianceOfficer |
| POST | `/work-orders` | Schedule the decommissioning field work; occupies the crew's calendar interval. | ProjectCoordinator |
| GET | `/work-orders` | List work orders, optionally filtered by project, crew or either state dimension. | ProjectCoordinator, FieldTechnician, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/work-orders/{id}` | Read one work order, including both state dimensions. | ProjectCoordinator, FieldTechnician, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/work-orders/{id}/field-events` | Advance the field dimension: MOBILIZE, START, COMPLETE or ABORT. | FieldTechnician |
| POST | `/work-orders/{id}/billing-events` | Advance the billing dimension independently of field progress: INVOICE, RECONCILE or WRITE_OFF. | ProjectCoordinator |
| POST | `/laboratories` | Register an analytical laboratory with its accreditation, turnaround commitment, holding time and concurrent-analysis capacity. | ComplianceOfficer |
| GET | `/laboratories/{id}` | Read one laboratory. | ProjectCoordinator, FieldTechnician, LabAnalyst, ComplianceOfficer |
| POST | `/soil-samples` | Log a collected soil aliquot; the first sample created while the project is REMEDIATION_ACTIVE opens a new confirmation round. | FieldTechnician |
| GET | `/soil-samples` | List samples, optionally filtered by project, work order, lab, retest parent, round or status. | ProjectCoordinator, FieldTechnician, LabAnalyst, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/soil-samples/{id}` | Read one sample with its chain-of-custody timestamps and timing metrics. | ProjectCoordinator, FieldTechnician, LabAnalyst, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/soil-samples/{id}/chain-of-custody` | Record a custody event: DISPATCH (technician), RECEIVE (lab), or VOID (technician). | FieldTechnician, LabAnalyst |
| POST | `/soil-samples/{id}/result` | Laboratory posts the analytical result; may complete the sampling round and cascade through classification, remediation volume, cost and insurance allocation. | LabAnalyst |
| POST | `/soil-samples/{id}/retract-result` | Laboratory retracts a posted result; the project reverts to SAMPLING and its classification is cleared. | LabAnalyst |
| POST | `/change-orders` | Draft a remediation scope change order against a current view of the project. | LicensedSiteProfessional |
| GET | `/change-orders` | List change orders, optionally filtered by project, supersession parent or status. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/change-orders/{id}` | Read one change order. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/change-orders/{id}/submit` | Author submits their draft change order for compliance decision. | LicensedSiteProfessional |
| POST | `/change-orders/{id}/decision` | Compliance approves or rejects the change order; approval enforces the excavation limit and supersedes the named prior order. | ComplianceOfficer |
| POST | `/trust-fund-claims` | File a state trust-fund reimbursement claim against a current view of the project. | ComplianceOfficer |
| GET | `/trust-fund-claims` | List trust-fund claims, optionally filtered by project, variant or status. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/trust-fund-claims/{id}` | Read one trust-fund claim with its full eligibility breakdown. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/trust-fund-claims/{id}/submit` | Submit a DRAFT or INFO_REQUESTED claim to the trust fund. | ComplianceOfficer |
| POST | `/trust-fund-claims/{id}/decision` | Record a review decision: UNDER_REVIEW, INFO_REQUESTED, APPROVED, DENIED or PAID. | ComplianceOfficer |
| POST | `/nfa-letters` | Draft a no-further-action letter for a real-estate closing. | LicensedSiteProfessional |
| GET | `/nfa-letters` | List NFA letters, optionally filtered by project or status. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/nfa-letters/{id}` | Read one NFA letter. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer, Homeowner |
| POST | `/nfa-letters/{id}/issue` | A second licensed site professional signs and issues the letter, closing the project out. | LicensedSiteProfessional |
| POST | `/nfa-letters/{id}/rescind` | Compliance pulls back an issued letter, reopening remediation and revalidating the trust-fund claim. | ComplianceOfficer |
| POST | `/insurance-notifications` | Notify the carrier of a first-party claim or tender a third-party liability exposure. | ComplianceOfficer |
| GET | `/insurance-notifications` | List insurance notifications, optionally filtered by project, kind or status. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| GET | `/insurance-notifications/{id}` | Read one insurance notification with its waterfall allocation. | ProjectCoordinator, LicensedSiteProfessional, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical UTC clock to a supplied instant. | ComplianceOfficer, ProjectCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_TANK_PROJECT_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_LABORATORY_NOT_FOUND` | 404 |
| `ERR_SOIL_SAMPLE_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_NFA_LETTER_NOT_FOUND` | 404 |
| `ERR_INSURANCE_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_METHOD_OVERRIDE_REASON_REQUIRED` | 422 |
| `ERR_CLOSING_DATE_IN_PAST` | 422 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_PROJECT_STATE_INVALID` | 409 |
| `ERR_DISCLOSURE_STATE_INVALID` | 409 |
| `ERR_PERMIT_STATE_INVALID` | 409 |
| `ERR_WORK_ORDER_STATE_INVALID` | 409 |
| `ERR_SAMPLE_STATE_INVALID` | 409 |
| `ERR_CHANGE_ORDER_STATE_INVALID` | 409 |
| `ERR_CLAIM_STATE_INVALID` | 409 |
| `ERR_NFA_STATE_INVALID` | 409 |
| `ERR_NO_TANK_LOCATED` | 409 |
| `ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_DISCLOSURE_EXPIRED` | 409 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 409 |
| `ERR_LAB_NOT_ACCREDITED` | 409 |
| `ERR_NFA_BLOCKED` | 409 |
| `ERR_SUPERSEDE_TARGET_INVALID` | 409 |
| `ERR_RETEST_TARGET_INVALID` | 409 |
| `ERR_CREW_BOOKING_CONFLICT` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_HOLDING_TIME_EXCEEDED` | 409 |
| `ERR_EXCAVATION_LIMIT_EXCEEDED` | 409 |
| `ERR_CLAIM_NOT_ELIGIBLE` | 409 |
| `ERR_DUPLICATE_FINAL_CLAIM` | 409 |
| `ERR_DUPLICATE_DISCLOSURE` | 409 |
| `ERR_WORK_ORDER_ALREADY_OPEN` | 409 |
| `ERR_INFO_REQUEST_LIMIT_REACHED` | 409 |

# Rental Registration & Inspection API — Product Requirements Document

## 1. Introduction

Municipal housing authorities are responsible for ensuring that rental properties remain safe, habitable, and properly licensed. Today that responsibility is spread across disconnected spreadsheets, paper inspection forms, and ad-hoc notice letters, which makes it hard to trace a single property from its first registration through the full lifecycle of licensing, periodic and complaint-driven inspections, violation cure cycles, and — in the worst cases — condemnation. This document specifies a backend API that unifies that entire regulatory workflow into one coherent system of record.

The platform serves four distinct constituencies. Landlords register their properties, pay and renew licenses, and submit evidence that violations have been cured through a self-service portal. Municipal inspectors schedule and conduct on-site inspections, record life-safety and habitability checklist findings, and finalize results that may spawn enforceable violations. Housing registrars — the officials who administer the program — issue and refund licenses, escalate dangerous violations, dispatch official tenant notices, and, when a property becomes uninhabitable, draft and issue condemnation orders. Tenants file complaints about the conditions they live in and acknowledge the notices they receive.

A central design goal is deterministic, auditable enforcement. Fees, penalties, and inspection scores are computed by fixed rules rather than operator discretion; property, license, and violation states advance through well-defined machines whose transitions cascade predictably; and all time-sensitive behavior is governed by an explicit logical clock so that cure deadlines, license expiries, and notice windows can be tested and reproduced exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, or `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation according to the authorization rules in this document, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Landlord`, `Inspector`, `Registrar`, and `Tenant`.

Two of these roles are backed by persisted entities, and their identity ties directly to resource ownership. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`; ownership checks on any resource that references a `Landlord` compare the resource's owning-landlord foreign key to `X-User-ID`. Because a `Property` records its owner via `landlord_id`, and licenses and violations belong to a property, the landlord who owns the underlying property is the owner for those resources as well. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; ownership checks on any resource that references an `Inspector` compare the resource's `inspector_id` to `X-User-ID`. An ownership violation — an entity-backed actor operating on a resource it does not own — is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The other two roles are opaque. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `Tenant`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity; a tenant is identified in domain data only by the email and unit fields they supply on complaints and by the recipient fields on the notices they acknowledge, never by matching `X-User-ID` to a stored record.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, so the oldest record appears first.

For every list response, the `meta` object carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. The `total_count` reflects the full number of matching records before pagination is applied, and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. Most resources also carry three additional system-managed properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increments by one on every mutation of that resource. The `created_at` value is fixed at creation and never changes; `updated_at` is refreshed on every mutation; and any state transition, field change, or cascade that touches a resource bumps that resource's `version` and refreshes its `updated_at`.

There is one exception. The recorded checklist item resource carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`, because checklist findings are immutable once recorded. Every other resource in this specification (landlords, inspectors, properties, licenses, complaints, inspections, violations, tenant notices, and condemnation orders) carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. The Logical Clock

All time-sensitive behavior is evaluated against a single logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it holds precisely this default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied instant. Timestamps that the system records — a complaint's `filed_at`, a notice's `sent_at`, an inspection's `conducted_at`, a license's `issued_at`, an acknowledgement's `acknowledged_at`, an order's `issued_at` — are all read from this logical clock at the moment the corresponding action occurs.

Several deadlines are evaluated lazily. A license whose expiry instant has passed transitions from `ACTIVE` to `EXPIRED`, and a notice whose acknowledgement window has passed transitions from `SENT` to `EXPIRED`; both of these are computed at the moment the resource is next read or next written, not by any background process. Whenever the clock is advanced or a property is fetched, any licenses touched are lazily expired if their expiry instant has passed.

### 2.6. Monetary Amounts, Scores, and Rounding

All monetary quantities — license fees, penalties, paid-fee ledgers, and payment amounts — are expressed as integer numbers of cents. Wherever a monetary computation would produce a fractional cent, the result is rounded half up to the nearest whole cent. License fees are rounded to whole cents. Each violation's penalty is rounded to whole cents individually, on a per-violation basis, before any aggregation occurs.

Inspection habitability scores are decimal numbers carried to one decimal place, also rounded half up. A property's aggregate penalty total is a sum of already-rounded per-violation integers; the rounding happens once per violation and the whole-cent results are then added, rather than summing raw amounts and rounding once at the end.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both express the client's last observed version of a parent resource as a mandatory input field.

Issuing a new license against a property requires the request to carry `expected_property_version`, which must equal the target property's current `version`. Because issuing a license bumps the property's `version` and supersedes its prior current-license pointer, a create request that still carries the property version observed before some earlier write is working from a stale view; when `expected_property_version` does not match the property's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Renewing a license requires the request to carry `expected_license_version`, which must equal the target license's current `version`. A prior renewal, or a cascaded suspension of the license, advances the license's `version`; a renewal that still carries the earlier value is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.8. Nested Resource Retrieval and Path Validation

Several read endpoints are nested — for example, the licenses, complaints, and tenant notices reachable under a specific property, and the checklist items reachable under a specific inspection. Path parameters are validated left to right: the outer resource is resolved before any inner resource or filter is considered. If a path resource does not exist, the request fails with the not-found error naming that specific resource type (for example `ERR_PROPERTY_NOT_FOUND` or `ERR_INSPECTION_NOT_FOUND`, HTTP 404) before any deeper validation runs.

### 2.9. Cascading Consistency and State Propagation

Many operations mutate more than one resource in a single, immediate, synchronous cascade. When an inspection fails and produces violations, when a property is suspended or reinstated, when a license is revoked, and when a condemnation order is issued, every affected resource has its state advanced, its `version` bumped, and its `updated_at` refreshed as part of the same operation. The system maintains immediate consistency: the computed compliance counters on a property (`open_violation_count`, `open_critical_violation_count`, and `total_penalty_cents`) always reflect the current state of that property's violations at the moment the property is read, and the property's `registration_status` always reflects whether it currently holds any open critical violation. The precise cascade chains are described in the workflow sections below.

### 2.10. Validation Precedence

When several checks apply to one request, they are evaluated in a fixed order, and the first failure determines the response. Authentication comes first: absent or unknown-role headers yield `ERR_UNAUTHENTICATED`. Next comes role authorization against the endpoint's permitted roles, yielding `ERR_UNAUTHORIZED`, followed by ownership for entity-backed actors, yielding `ERR_FORBIDDEN_OWNERSHIP`. Existence is checked next: the path resource is resolved left to right — so, for example, a missing license, notice, or condemnation order in the URL yields `ERR_LICENSE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or `ERR_CONDEMNATION_NOT_FOUND` respectively — and only then are body foreign keys resolved. After existence comes structural validation of the payload: missing required fields, invalid enum values, or out-of-range numbers (a `unit_count` below 1, a `term_years` outside 1, 2, or 3, or a `duration_minutes` that is not greater than 0) yield `ERR_VALIDATION`. Only after all of the above passes is the target resource's current state checked: if a transition is attempted from a state that does not allow it, the request is rejected with `ERR_INVALID_STATE`. Any remaining business rules — habitability safety, fiscal, referential, temporal, and threshold checks named throughout §3 — are evaluated after the state check.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Landlords, Inspectors, and Properties

A `Registrar` seeds the directory of participants. Registering a landlord captures the owner's legal `full_name`, contact `email`, `phone`, and `mailing_address` — the last serving as the address of record for official correspondence. Registering an inspector captures the inspector's `full_name`, municipal `badge_number`, and contact `email`, together with two optional attributes: a `certification_level`, which is one of `STANDARD`, `SENIOR`, or `LEAD_CERTIFIED` and defaults to `STANDARD` when omitted, and an `active` flag indicating whether the inspector is currently on duty, which defaults to true.

A property enters the system when either a `Landlord` or a `Registrar` registers it. Registration supplies the owning `landlord_id`, the `street_address`, the `unit_count`, and the `year_built`. The unit count must be an integer of at least 1, and the referenced landlord must already exist — a missing landlord reference fails with `ERR_LANDLORD_NOT_FOUND`. A newly registered property begins in `registration_status` `REGISTERED`, with its money ledger `total_fees_paid_cents` initialized to 0 and its `current_license_id` unset until a license is later issued. At registration the system computes `has_lead_risk`, setting it to true exactly when `year_built` is earlier than 1978; properties built in 1978 or later carry no lead risk. This lead-risk determination later drives both a licensing surcharge and lead-paint notice obligations.

Whenever a property is fetched, the response includes its live compliance picture: the `open_violation_count`, the `open_critical_violation_count`, the aggregate `total_penalty_cents`, and the `has_lead_risk` flag, all computed at read time. Fetching a property also lazily expires any of that property's licenses whose expiry instant has passed. A landlord may list properties through the portal, optionally narrowing the list to their own by supplying a `landlord_id` filter or narrowing by `registration_status`; a registrar may list across all properties.

### 3.2. Tenant Complaints and Scheduling Inspections

Tenants raise concerns by filing a complaint against a property. A complaint identifies the `property_id`, the complaining tenant's `tenant_email` and `tenant_unit`, a `category` drawn from `LIFE_SAFETY`, `HABITABILITY`, `LEAD_PAINT`, or `STRUCTURAL`, a free-text `description`, and a tenant-alleged `severity_alleged` of `MINOR`, `MAJOR`, or `CRITICAL`. A filed complaint records its `filed_at` from the logical clock and begins life in status `FILED`.

Inspections are the enforcement backbone, and either an `Inspector` or a `Registrar` may schedule one. Scheduling supplies the `property_id`, the assigned `inspector_id`, the `inspection_type`, a `scheduled_date` for the planned on-site start, and an optional `duration_minutes` that defaults to 60 and must be greater than 0. The `inspection_type` is one of `PERIODIC`, `COMPLAINT`, or `REINSPECTION`. A `COMPLAINT` inspection additionally references the originating `complaint_id`, and scheduling it transitions the linked complaint from `FILED` to `INSPECTION_SCHEDULED`. A `REINSPECTION` additionally references the failed inspection it re-checks via `prior_inspection_id`; that prior inspection must itself be in the `FAILED` state, and a prior inspection in any other state makes the transition invalid. Any referenced property, inspector, complaint, or prior inspection that does not exist fails with the matching not-found error (`ERR_PROPERTY_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or `ERR_INSPECTION_NOT_FOUND`). A freshly scheduled inspection begins in status `SCHEDULED`, and its computed `overdue` flag becomes true once the logical clock passes its `scheduled_date` while it is still `SCHEDULED`.

Three scheduling guardrails protect inspectors and properties, and they are evaluated after the referenced resources are confirmed to exist and the payload is structurally valid. First, an inspector may not be double-booked: if the assigned inspector already has an inspection whose half-open interval — from its `scheduled_date` up to but not including `scheduled_date` plus its `duration_minutes` — overlaps the interval of the new inspection, scheduling is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. Intervals that merely abut (one ending exactly when the next begins) do not overlap and are allowed. Second, a property has a cooldown buffer: if the same property already has another non-terminal inspection whose `scheduled_date` falls within 24 hours of the new one — a closed window on both sides — scheduling is rejected with `ERR_INSPECTION_COOLDOWN`. Third, a reinspection may not be scheduled too soon after the inspection it re-checks: its `scheduled_date` must be at or after the prior inspection's `conducted_at` plus 48 hours, and an earlier date is rejected with `ERR_REINSPECTION_TOO_EARLY`.

Inspections can be listed and filtered by property, inspector, complaint, prior inspection, or status through `property_id`, `inspector_id`, `complaint_id`, `prior_inspection_id`, and `status` filters, and a single inspection can be fetched directly. When an inspection is read while still in progress, its `result_score` is a provisional figure, as described in the next section.

### 3.3. Conducting the Inspection: Checklist and Provisional Scoring

Only the assigned inspector may work an inspection on-site. Beginning the on-site visit advances the inspection from `SCHEDULED` to `IN_PROGRESS`, and it is permitted only when the acting inspector's `X-User-ID` matches the inspection's `inspector_id`. Two further conditions guard the start: the inspection must currently be `SCHEDULED`, and the property must be in `registration_status` `REGISTERED` — attempting to begin against a property that is not registered is rejected with `ERR_PROPERTY_NOT_REGISTERED`.

While an inspection is `IN_PROGRESS`, the assigned inspector records checklist items, one at a time. Each recorded item names its `inspection_id`, a `category` of `LIFE_SAFETY`, `HABITABILITY`, `LEAD_PAINT`, or `STRUCTURAL`, a `code` such as `SMOKE_DETECTOR`, `HEAT`, `PLUMBING`, or `LEAD_HAZARD`, and a `result` of `PASS`, `FAIL`, or `NOT_APPLICABLE`. When a result is a failure, the item also carries a `severity` of `MINOR`, `MAJOR`, or `CRITICAL` (defaulting to `MINOR`) and optional free-text `notes`. Checklist items may only be recorded while the inspection is in progress. The recorded items of an inspection can be listed on their own.

Each recorded item updates the inspection's provisional `result_score`. The habitability score is a weighted sum computed over the checklist items whose `result` is `FAIL`; passing and not-applicable items contribute nothing. Each failing item contributes its severity weight multiplied by its category multiplier. The severity weights are 1 for `MINOR`, 3 for `MAJOR`, and 10 for `CRITICAL`. The category multipliers are 2.0 for `LIFE_SAFETY`, 1.0 for `HABITABILITY`, 1.5 for `LEAD_PAINT`, and 1.5 for `STRUCTURAL`. The sum of these products, rounded half up to one decimal place, is the provisional score. While the inspection is in progress the provisional score considers only the items recorded so far; it does not check whether every mandatory category has been covered, and it adds no synthetic penalty.

### 3.4. Completing the Inspection: Final Scoring, Violations, and Reconciliation

Only the assigned inspector completes an in-progress inspection, which drives it from `IN_PROGRESS` to either `PASSED` or `FAILED`. Completion first sets `conducted_at` from the logical clock and finalizes the `result_score` using the final scoring variant, then applies the outcome-dependent side effects. The final score is computed the same way as the provisional score — the weighted sum over failing items — but with one addition: for each mandatory category that has zero recorded items, a synthetic critical failure is charged, contributing the critical severity weight of 10 multiplied by that category's multiplier. The mandatory categories are `LIFE_SAFETY` and `HABITABILITY`, so a missing `LIFE_SAFETY` category adds 20.0 and a missing `HABITABILITY` category adds 10.0. This synthetic charge exists only in the final variant and can turn a provisional pass into a final failure.

An inspection passes when three conditions all hold at completion: the final score is strictly less than the pass threshold of 5.0, no recorded item is a `CRITICAL` failure, and every mandatory category has at least one recorded item. If any of those three conditions fails, the inspection is `FAILED`. When the three conditions hold the inspection lands in `PASSED`; otherwise it lands in `FAILED`.

When a `PERIODIC` or `COMPLAINT` inspection fails, each checklist item whose `result` is `FAIL` produces a new violation in status `OPEN`. Each such violation records its owning `inspection_id` and `property_id`, points back at the failing item through `checklist_item_id`, and copies that item's `code`, `category`, and `severity`. Its `cure_deadline` is set to `conducted_at` plus the cure window for its severity: 30 days for `MINOR`, 14 days for `MAJOR`, and 3 days for `CRITICAL`. The property's `open_violation_count` rises by the number of violations created. Then, as a second cascade hop, every newly opened violation whose `severity` is `CRITICAL` drives the property from `REGISTERED` to `SUSPENDED`, which in turn suspends the property's active or expired license (see the licensing and cascade sections). A `COMPLAINT` inspection that instead passes resolves its linked complaint, transitioning it from `INSPECTION_SCHEDULED` to `RESOLVED`.

A reinspection never mints new violations. Whether it passes or fails, completing a `REINSPECTION` runs a reconciliation against the violations of the inspection named by `prior_inspection_id`. For each of those prior violations currently in `OPEN`, `REMEDIATION_SUBMITTED`, or `ESCALATED`, the system finds the reinspection's checklist item bearing the same `code`. If that item's `result` is `PASS`, the violation is transitioned to `VERIFIED_RESOLVED`, the property's `open_violation_count` is decremented by one, and — if this was the property's last open critical violation — the property bubbles from `SUSPENDED` back to `REGISTERED`. If that item's `result` is `FAIL` and the violation was in `REMEDIATION_SUBMITTED`, the violation reverts to `OPEN`. If no item with the matching `code` was recorded, the violation is left unchanged. A violation that reaches `VERIFIED_RESOLVED` is terminal and stops accruing any penalty.

### 3.5. The Licensing Lifecycle: Issue, Pay, Renew, and Refund

A `Registrar` issues a license for a property, which is created in status `PENDING_PAYMENT`. Issuance references the `property_id` and accepts an optional `term_years` — the term length in years, which must be 1, 2, or 3 and defaults to 1 — and requires `expected_property_version` for concurrency control as described above. On issuance the system mints a human-readable `license_number`, computes the fee, sets the property's `current_license_id` to the new license, and increments the property's `version`. Because a new license supersedes any prior one, the concurrency guard ensures the issuing client observed the property's latest state.

The `fee_cents` is computed at issuance and again at renewal. The annual base is chosen by the property's `unit_count`: a single-unit property has an annual base of 15000 cents; a property of 2 to 4 units, 30000 cents; a property of 5 to 20 units, 60000 cents; and a property of more than 20 units, 120000 cents. If the property's `year_built` is earlier than 1978, a lead surcharge of 5000 cents is added to that annual base, and the license's `lead_surcharge_applied` flag is set to true; otherwise no surcharge applies and the flag is false. The resulting annual figure is multiplied by `term_years` to give the base fee. Under the on-time variant — used at issuance and at any renewal performed at or before the license's expiry instant — the fee equals that base fee. Under the late variant — used at a renewal performed strictly after the expiry instant — the base fee is first multiplied by 1.5 and rounded half up to whole cents, and then a flat reinstatement fee of 10000 cents is added; for the same inputs the late fee is always strictly greater than the on-time fee.

A `Landlord` pays the fee to activate a `PENDING_PAYMENT` license, advancing it to `ACTIVE`. Payment carries the `amount_cents` the landlord tenders, and only the owning landlord — whose `X-User-ID` matches the property's `landlord_id` — may pay. Activation is gated by several checks: the license must currently be `PENDING_PAYMENT`; the property must have no open critical violations, otherwise payment is blocked with `ERR_UNSAFE_HABITABILITY`; the property must already have at least one `PERIODIC` inspection in status `PASSED`, otherwise payment is blocked with `ERR_NO_PASSED_INSPECTION`; and the tendered `amount_cents` must exactly equal the license's computed `fee_cents`, otherwise the payment is rejected with `ERR_FEE_MISMATCH` (HTTP 402). On success the system sets `issued_at` to the current clock, sets `expires_at` to `issued_at` plus `term_years` years, adds the paid `fee_cents` to the property's `total_fees_paid_cents`, points the property's `current_license_id` at this license, and increments the property's `version`.

An `ACTIVE` license lazily transitions to `EXPIRED` once the logical clock reaches its `expires_at`, evaluated the next time the license is read or written. Either a `Landlord` or a `Registrar` renews a license that is `ACTIVE` or `EXPIRED`, returning it to `ACTIVE`. Renewal requires `expected_license_version` for the concurrency guard and is blocked with `ERR_UNSAFE_HABITABILITY` while the property has any open critical violation. Renewal recomputes `fee_cents` — on-time if the clock is at or before the old `expires_at`, late otherwise — sets a fresh `issued_at` from the clock, sets `expires_at` to that new `issued_at` plus `term_years` years, increments `renewal_count` by one, adds the new `fee_cents` to the property's `total_fees_paid_cents`, and increments the license's `version`.

A `Registrar` may refund the most recently paid fee, which reverts an `ACTIVE` license to `PENDING_PAYMENT` as a compensating action. The refund subtracts the most recently paid `fee_cents` from the property's `total_fees_paid_cents`, restoring the ledger to its pre-payment value, clears the license's `issued_at` and `expires_at`, and clears the property's `current_license_id` if it currently points at this license. The licenses issued for a property can be listed through the property's license sub-resource.

### 3.6. Violations: Remediation, Escalation, and Penalties

A violation carries a `code`, `category`, and `severity` copied from the failing checklist item that produced it, along with its lifecycle `status`. The owning `Landlord` responds by submitting remediation on an `OPEN` violation, which moves it to `REMEDIATION_SUBMITTED`; only the landlord who owns the underlying property (whose `X-User-ID` matches the property's `landlord_id`) may do so, and the violation must currently be `OPEN`. The submission records the landlord-supplied `remediation_notes`. Actual resolution is not granted here — it is confirmed later, when a reinspection re-checks the same `code` and passes, as described in the completion workflow.

A `Registrar` escalates a critical violation once a property's critical caseload crosses a threshold, moving the violation from `OPEN` to `ESCALATED`. Escalation is permitted only when the violation is `OPEN`, its `severity` is `CRITICAL`, and the property's count of critical violations meets the escalation threshold of 2. That escalation count is the number of the property's violations whose `severity` is `CRITICAL` and whose status is either `OPEN` or `REMEDIATION_SUBMITTED`; exactly one such violation is not enough, while two or more is eligible. If the threshold is not met, escalation is rejected with `ERR_ESCALATION_THRESHOLD_NOT_MET`. Escalating a violation dispatches a `VIOLATION_NOTICE` tenant notice, created in `SENT`, for the property.

Each violation accrues a monetary penalty over time, exposed as `penalty_cents` and computed whenever the violation is read. The clock is compared against the violation's `cure_deadline`, which is its originating inspection's `conducted_at` plus the severity's cure window (30 days for `MINOR`, 14 for `MAJOR`, 3 for `CRITICAL`). At or before the cure deadline the penalty is exactly 0; strictly after it, the penalty is positive. Once overdue, the number of overdue days is the elapsed time past the deadline divided into days and rounded up to the next whole day, so any partial day counts as a full day. The raw penalty is the per-day rate for the severity multiplied by the overdue-day count, but capped: the daily rates are 1000 cents for `MINOR`, 2500 for `MAJOR`, and 10000 for `CRITICAL`, and the caps are 30000, 75000, and 300000 cents respectively. Finally a 7.5% administrative fee is applied — the capped raw amount is multiplied by 1.075 and rounded half up to whole cents. A penalty only accrues while the violation is `OPEN`, `REMEDIATION_SUBMITTED`, or `ESCALATED`; a `VERIFIED_RESOLVED` or `CONDEMNED_BASIS` violation accrues nothing.

A property's `total_penalty_cents` aggregates these penalties. It is the sum, over the property's violations whose status is `OPEN`, `REMEDIATION_SUBMITTED`, or `ESCALATED`, of each violation's individual penalty. The per-violation penalties are each rounded to whole cents first, in `created_at` ascending order for deterministic accumulation, and only then summed — the rounding is never deferred to a single final rounding of the raw total. The property's `open_violation_count` is the number of its violations in `OPEN`, `REMEDIATION_SUBMITTED`, or `ESCALATED`, and its `open_critical_violation_count` is the number of those whose `severity` is `CRITICAL`. Violations can be fetched individually — including the computed `cure_deadline` and `penalty_cents` — and listed with filters on `property_id`, `inspection_id`, `checklist_item_id`, and `status`.

### 3.7. Official Tenant Notices

A `Registrar` issues an official notice to a tenant, naming the `property_id`, the `recipient_email`, the `recipient_unit`, and a `notice_type` of `LEAD_PAINT_DISCLOSURE`, `INSPECTION_NOTICE`, `VIOLATION_NOTICE`, or `CONDEMNATION_NOTICE`. A notice is created in status `SENT` with its `sent_at` read from the logical clock, and its `ack_deadline` is set to `sent_at` plus 30 days. Some notices are also generated automatically by the system — a `VIOLATION_NOTICE` when a violation is escalated, and a `CONDEMNATION_NOTICE` when a property is condemned — and those follow the same `SENT` status and 30-day acknowledgement window.

A `Tenant` acknowledges a notice before its window closes, moving it from `SENT` to `ACKNOWLEDGED` and recording `acknowledged_at` from the clock. Acknowledgement is allowed only while the notice is `SENT` and the clock is at or before the `ack_deadline`; acknowledging after the deadline is rejected with `ERR_NOTICE_EXPIRED`. A notice whose deadline has passed lazily transitions from `SENT` to `EXPIRED`, evaluated the next time it is read or an acknowledgement is attempted. The notices issued for a property can be listed through the property's notice sub-resource.

### 3.8. Suspension, Reinstatement, and Condemnation Cascades

The property registration state responds automatically to the property's critical-violation load. When an inspection failure opens a critical violation, the property moves from `REGISTERED` to `SUSPENDED`, and as a side effect its non-terminal license — one currently `ACTIVE` or `EXPIRED` — moves to `SUSPENDED` as well. Conversely, when a reinspection resolves a violation and the property's `open_critical_violation_count` returns to 0, the property bubbles from `SUSPENDED` back to `REGISTERED`, and its `SUSPENDED` license is reinstated to `ACTIVE`. These state changes propagate immediately and bump the `version` and `updated_at` of every resource they touch.

Condemnation is the terminal enforcement path, and it begins when a `Registrar` drafts a condemnation order. Drafting names the `property_id`, a written `basis` justifying the action, and an optional `triggering_violation_id` citing the escalated violation that grounds the order (left unset when the order rests on aggregate grounds); a cited violation that does not exist fails with `ERR_VIOLATION_NOT_FOUND`. A drafted order begins in status `DRAFT`.

A `Registrar` then issues the order, moving it from `DRAFT` to `ISSUED`. Issuance is permitted only when the order is `DRAFT` and the property has at least one violation currently in `ESCALATED`; without such a basis, issuance is rejected with `ERR_NO_CONDEMNATION_BASIS`. Issuing sets the order's `issued_at` from the clock and triggers a three-level cascade. First, the property — whether it was `REGISTERED` or `SUSPENDED` — transitions to the terminal `CONDEMNED` state, and one `CONDEMNATION_NOTICE` tenant notice (status `SENT`) is generated for the property. Second, the property's non-terminal license — one currently `ACTIVE`, `EXPIRED`, or `SUSPENDED` — is transitioned to the terminal `REVOKED` state. Third, as a consequence of that revocation, every one of the property's non-terminal violations — those in `OPEN`, `REMEDIATION_SUBMITTED`, or `ESCALATED` — is transitioned to the terminal `CONDEMNED_BASIS` state. Condemnation orders can be fetched individually and listed with filters on `property_id`, `triggering_violation_id`, and `status`.

### 3.9. Clock Administration

To make time-dependent behavior reproducible, a `Registrar` may drive the logical clock through an administrative test-driving capability that sets the current instant to a supplied `to_iso8601` value. Advancing the clock lazily expires any licenses and notices whose deadlines have passed the next time those resources are accessed, as described in the logical-clock principles above.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Creating a new resource returns HTTP 201; state transitions and other modifications on existing resources return HTTP 200; reads return HTTP 200. Request and response bodies are not restated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/landlords` | Register a landlord | Registrar |
| POST | `/inspectors` | Register an inspector | Registrar |
| POST | `/properties` | Register a rental property (created REGISTERED) | Landlord, Registrar |
| GET | `/properties/{id}` | Fetch a property with computed compliance fields | Landlord, Registrar, Inspector |
| GET | `/properties` | List properties; portal filters by landlord | Landlord, Registrar |
| GET | `/properties/{id}/rental-licenses` | List a property's licenses | Landlord, Registrar |
| GET | `/properties/{id}/complaints` | List complaints against a property | Registrar, Landlord |
| GET | `/properties/{id}/tenant-notices` | List tenant notices for a property | Registrar, Landlord |
| POST | `/rental-licenses` | Issue a license for a property (PENDING_PAYMENT) | Registrar |
| POST | `/rental-licenses/{id}/pay` | Pay the fee to activate a license | Landlord |
| POST | `/rental-licenses/{id}/renew` | Renew a license | Landlord, Registrar |
| POST | `/rental-licenses/{id}/refund` | Refund the most recent paid fee | Registrar |
| POST | `/complaints` | File a habitability complaint | Tenant |
| POST | `/inspections` | Schedule an inspection | Inspector, Registrar |
| GET | `/inspections/{id}` | Fetch an inspection | Inspector, Registrar, Landlord |
| GET | `/inspections` | List inspections with filters | Inspector, Registrar, Landlord |
| POST | `/inspections/{id}/begin` | Begin the on-site inspection | Inspector |
| POST | `/inspections/{id}/checklist-items` | Record a checklist item | Inspector |
| GET | `/inspections/{id}/checklist-items` | List an inspection's checklist items | Inspector, Registrar, Landlord |
| POST | `/inspections/{id}/complete` | Complete the inspection (PASSED/FAILED) | Inspector |
| GET | `/violations/{id}` | Fetch a violation with computed penalty | Registrar, Landlord, Inspector |
| GET | `/violations` | List violations with filters | Registrar, Landlord, Inspector |
| POST | `/violations/{id}/submit-remediation` | Submit remediation for an OPEN violation | Landlord |
| POST | `/violations/{id}/escalate` | Escalate a CRITICAL violation | Registrar |
| POST | `/tenant-notices` | Issue a tenant notice (created SENT) | Registrar |
| POST | `/tenant-notices/{id}/acknowledge` | Acknowledge a notice before its deadline | Tenant |
| POST | `/condemnation-orders` | Draft a condemnation order (DRAFT) | Registrar |
| GET | `/condemnation-orders/{id}` | Fetch a condemnation order | Registrar, Landlord |
| GET | `/condemnation-orders` | List condemnation orders with filters | Registrar, Landlord |
| POST | `/condemnation-orders/{id}/issue` | Issue the order (triggers condemnation cascade) | Registrar |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | Registrar |

## 5. Error Code Catalogue

The table lists every error identifier and its HTTP status. The conditions that trigger each error are described in the relevant §2 and §3 narratives.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_LANDLORD_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_VIOLATION_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_CONDEMNATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROPERTY_NOT_REGISTERED` | 409 |
| `ERR_NO_PASSED_INSPECTION` | 409 |
| `ERR_UNSAFE_HABITABILITY` | 409 |
| `ERR_ESCALATION_THRESHOLD_NOT_MET` | 409 |
| `ERR_NO_CONDEMNATION_BASIS` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_INSPECTION_COOLDOWN` | 409 |
| `ERR_REINSPECTION_TOO_EARLY` | 422 |
| `ERR_NOTICE_EXPIRED` | 409 |
| `ERR_FEE_MISMATCH` | 402 |
| `ERR_STALE_VERSION` | 412 |

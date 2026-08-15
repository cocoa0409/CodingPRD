# Multifamily Pest Control API — Product Requirements Document

## 1. Introduction

Operating a pest-control program across a portfolio of apartment communities is a coordination problem disguised as a scheduling problem. A vendor contract fixes the scope of covered pests, a monthly visit cadence, and a fiscal cap; on-site managers must get residents to prepare their units, technicians must record what they actually find, and every confirmed bed bug sighting sets off a regulated chain of adjacent-unit inspections, treatment cycles, furniture disposal, and clearance monitoring. Layered on top is a money problem: when residents fail to prepare or deny access, lease clauses allow the community to recover costs — but only if the chargeback amounts, dispute windows, and billing segregation rules are enforced consistently enough to survive a habitability claim.

This document specifies a REST API that runs that program end to end. It covers service-contract lifecycle and budget enforcement, the unit-level inspection and severity pipeline, the treatment workflow with its preparation protocol and reschedule discipline, the bed bug case machine with adjacent-exposure cascades and clearance evaluation, the resident chargeback ledger with disputes and collections, and the compliance documentation packets assembled when a dispute escalates into a habitability claim. All operations hang off a single logical clock so that notice windows, dispute deadlines, and month-boundary accounting are deterministic. The API is mounted under `/pest`, with a test-driving clock endpoint mounted at the root.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming exactly one of the declared roles. The roles are `ProgramAdmin`, `PropertyManager`, `Technician`, `Resident`, `BillingClerk`, and `ComplianceOfficer`, spelled exactly as shown. A request missing either header, or naming an undeclared role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The one nuance is the logical-clock endpoint: it still requires the `ProgramAdmin` role but does not require an `X-User-ID`. When the role is legitimate but not authorized for the endpoint — or when an entity-backed ownership check fails — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles divide the program deliberately:

- A `ProgramAdmin` is the platform operator: it creates communities, contracts, units, and technicians, drives the contract lifecycle, and owns the logical clock. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `PropertyManager` is the on-site community manager running the day-to-day program: leases, residents, inspections, treatments, preparation verification, disposals, and clearance. Its `X-User-ID` is likewise an opaque operator identifier, recorded where a workflow calls for it but never compared to an entity `id`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` record; assignment checks on any resource that references a technician compare the resource's `technician_id` field to `X-User-ID`. A technician acts only on records assigned to them, and a technician may read only their own technician record and their own schedule lists — reading another technician's record or schedule is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). An `X-User-ID` that matches no persisted `Technician` (or, for `Resident`, no persisted `Resident`) record is likewise rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).
- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident` record; ownership checks compare the resident's `unit_id` (and, for chargeback actions, the resident's `lease_id`) against the target resource's scoping fields. A resident acts only on records of their own unit and lease.
- A `BillingClerk` is the fiscal operator who assesses, bills, and collects chargebacks; its `X-User-ID` is an opaque identifier, recorded as the assessor on each chargeback it creates. By design it is barred from resolving disputes.
- A `ComplianceOfficer` adjudicates disputes and assembles and finalizes habitability claim packets; its `X-User-ID` is an opaque identifier, recorded as the resolver on each dispute it decides. It is barred from assessing or billing chargebacks.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an integer outside the permitted range is clamped (limit into [1, 100], offset up to 0) rather than rejected. List responses order results by `created_at` ascending, breaking ties by creation sequence (records minted at the same logical instant appear in the order they were created), and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Certain list endpoints accept additional filter parameters — `floor` on the unit list, `status` on lease-chargeback, technician-treatment, technician-inspection, unit-treatment, bed-bug-case, and furniture-disposal lists, and `kind` on the unit-inspection list — all of which are optional. Filters match by exact equality; an unrecognized filter value is not an error and simply yields an empty page.

### 2.4. The Logical Clock and Lazy State Transitions

The server never uses wall-clock time. Every timestamp the server stamps — `created_at`, `completed_at`, `assessed_at`, and every other system-set instant — comes from a single logical clock. At startup, before any clock call, the logical clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin` advances it through the clock endpoint, supplying `to_iso8601`; the response echoes the new logical time as `current_utc`. All deadline arithmetic in this document — the 48-hour preparation notice, the 14-day dispute window, month boundaries, day-count windows — evaluates against this logical clock.

Two lifecycle transitions are not triggered by any client action but are applied lazily whenever the server observes them to be due: a contract whose `end_date` has passed flips from `ACTIVE` to `EXPIRED`, and a lease whose `end_date` has passed flips from `ACTIVE` to `ENDED`, each incrementing the entity's `version` by 1. A read of the contract or lease, or any contract-gated operation, applies the transition if the current logical date is past the end date. Terminal states reject every further action with `ERR_ALREADY_TERMINAL` (HTTP 409); a transition that is simply not defined from the entity's current non-terminal state is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.5. Common Resource Properties

Every resource in this API carries four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by 1 on every mutation of the resource, including system-driven cascades and lazy transitions. Computed fields named throughout this document — a property's `posture`, a unit's `pest_flag`, a lease's `outstanding_balance_cents`, a technician's `booked_minutes`, an inspection's `severity`, a treatment's `planned_minutes`, a case's `consecutive_negative_count`, a chargeback's amounts, a packet's `pinned_references` — are maintained by the server and are never accepted as client input.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and the guard field is a required input on those operations.

Rescheduling a treatment requires the request to carry `expected_treatment_version`, holding the treatment `version` the client last observed. If that value no longer matches the treatment's current `version` — because another writer has rescheduled, notified, or otherwise mutated the treatment since the client read it — the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the treatment before retrying. Per the fixed validation order of §2.10, when the request fails both the stale-version check and an earlier stage — for example a reschedule attempted from a status outside `SCHEDULED`/`NON_COMPLIANT`, which fails the state-precondition stage — the earlier stage's rejection (`ERR_INVALID_STATE`) is the one reported.

Resolving a chargeback dispute requires the request to carry `expected_chargeback_version`, holding the chargeback `version` the deciding officer last observed. A mismatch with the chargeback's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the officer's view of the dispute is stale and must be refreshed. Endpoints not named in this section take no version field at all.

### 2.7. Nested Resource Resolution

Endpoints that address a child resource through its parent validate path identifiers strictly left to right: the outermost id first, then each nested id, then the resource id itself, and finally any foreign-key reference in the request body. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404). A malformed body, a missing required field, an unknown enum member, or a treatment window whose `window_start` is not strictly earlier than its `window_end` produces `ERR_INVALID_REQUEST` (HTTP 400) at the same existence-and-shape stage.

### 2.8. Monetary Precision and the Rate Card

All money in this system is integer cents. Where a monetary computation produces a fraction, the result is rounded half-up to whole cents; the chargeback rules below pin rounding to occur per line, before summing. The program's rate card is fixed: a `NON_COMPLIANCE_FEE` chargeback carries a base of 15000 cents, a `REPEAT_INFESTATION` chargeback 22000 cents, a `HEAT_SURCHARGE` 65000 cents, and a `LATE_FEE` 5000 cents. Furniture disposal is billed per item at 7995 cents. Treatment work beyond the planned window is billed at 175 cents per minute of overage. Every chargeback amount carries a 7.5 percent administrative surcharge applied line by line. Treatment cost estimates for budget purposes are 12000 cents for a `CHEMICAL` treatment, 65000 for `HEAT`, 9000 for `EXCLUSION`, and 6000 for `TRAPPING`.

### 2.9. Scheduling Safety Invariants

Three conflict rules protect every treatment window, evaluated against other treatments that are not yet in a terminal state (`COMPLETED` or `CANCELLED`). First, a unit may not be double-booked: the half-open interval from `window_start` to `window_end` — including the start instant, excluding the end instant — must not intersect any other non-terminal treatment of the same unit; violations return `ERR_UNIT_DOUBLE_BOOKED` (HTTP 409). Second, a technician needs travel time: the new window, expanded by 15 minutes on both sides, must not intersect the similarly expanded interval of any other non-terminal treatment assigned to the same technician; violations return `ERR_TREATMENT_WINDOW_CONFLICT` (HTTP 409). Third, heat treatments on a floor need breathing room: a `HEAT` treatment's `window_start` must sit at least 24 hours away from the `window_start` of every other non-terminal `HEAT` treatment anywhere on the same property and floor; violations return `ERR_HEAT_FLOOR_GAP_VIOLATION` (HTTP 409). When a treatment is being rescheduled, that treatment itself is excluded from all three conflict sets. Separately, any `HEAT` treatment scheduled or rescheduled without `vacancy_attested` set to true is rejected with `ERR_HEAT_SAFETY_VIOLATION` (HTTP 422), because heat work in an occupied unit is a safety incident.

### 2.10. Order of Validation

When several rules could reject the same request, the server evaluates them in a fixed order and reports the first failure. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization and entity-backed ownership (`ERR_FORBIDDEN_ROLE`), then the existence-and-shape stage (`ERR_NOT_FOUND` and `ERR_INVALID_REQUEST`), then state preconditions (`ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, and the domain state guards such as `ERR_CONTRACT_NOT_ACTIVE`, `ERR_LEASE_NOT_ACTIVE`, `ERR_PREP_NOT_NOTIFIED`, `ERR_PREP_NOT_ACKNOWLEDGED`, and `ERR_CASE_NOT_MONITORING`), then the stale-version check (`ERR_STALE_VERSION`), then heat safety (`ERR_HEAT_SAFETY_VIOLATION`), then the three temporal conflicts in the fixed order unit double-booking, technician buffered overlap, heat floor gap, then the remaining temporal windows (`ERR_PREP_NOTICE_TOO_LATE`, `ERR_DISPUTE_WINDOW_EXPIRED`), then business constraints such as the reschedule limit, clearance criteria, disposal verification, claim-packet staleness, property restriction, inspection completion, and duplicate unit numbers, then referential and scope checks (`ERR_CONTRACT_SCOPE_EXCLUDED`, `ERR_LEASE_CLAUSE_MISSING`, and the request-shape variants of `ERR_INVALID_REQUEST`), then fiscal checks (`ERR_CONTRACT_BUDGET_EXCEEDED`, `ERR_PAYMENT_AMOUNT_MISMATCH`), and finally segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Community: Properties, Contracts, and the Unit Grid

A `ProgramAdmin` onboards a community by creating a property with its `name` and `address`; the `timezone` defaults to America/Los_Angeles for schedule display when not supplied. From that moment the property continuously exposes two computed health indicators: `open_bed_bug_case_count`, the number of bed bug cases across the property's units whose status is `OPEN`, `TREATING`, `MONITORING`, or `REOPENED`, and `posture`, which is `RESTRICTED` when that count reaches at least 3, `ELEVATED` when it is at least 1, and `STANDARD` otherwise. The count thresholds are inclusive, and both indicators recompute on every case creation, reopen, and clearance. A computed summary read returns `posture`, `open_bed_bug_case_count`, and `total_outstanding_balance_cents`, the aggregate of outstanding balances across the property.

Each property runs under a service contract with a pest-control vendor. Contracts, units, and claim packets all record their owning community through a server-assigned `property_id` referencing the property's `id`. The contract captures the `vendor_name`; the `scope_pest_types` array, drawn from `ANTS`, `ROACHES`, `RODENTS`, `BED_BUGS`, and `TERMITES`, which must be non-empty; the contracted `visits_per_month`, at least 1; `coverage_per_incident_cents`, a vendor-absorbed credit applied to repeat-infestation chargebacks, zero or more; `heat_treatment_included`, which decides whether heat surcharges may ever be billed to residents; the fiscal cap `monthly_budget_cents`, at least 1; and the inclusive `start_date` and `end_date`, with the end date not earlier than the start date. A new contract is born in `DRAFT` and only a `ProgramAdmin` moves it: activation requires a non-empty scope and a current logical date that falls on or between the two dates, and takes the contract from `DRAFT` to `ACTIVE`; a failed activation precondition — including a current logical date outside the contract's date window — is rejected with `ERR_INVALID_STATE` (HTTP 409). From `ACTIVE` it may be suspended and later reactivated — reactivation requires that the current logical date has not passed the `end_date`, and a violation of that precondition is likewise `ERR_INVALID_STATE` (HTTP 409) — and either `ACTIVE` or `SUSPENDED` may be terminated outright. Each of these transitions increments the contract's `version` by 1. As noted in §2.4, a contract past its `end_date` flips lazily to `EXPIRED`. The computed `spent_cents` accumulates the estimated cost of every treatment completed under the contract during the current calendar month and resets at the month boundary. Wherever this document refers to the property's `ACTIVE` contract and several contracts are `ACTIVE` at once, the earliest-created `ACTIVE` contract governs.

Units describe the physical grid that drives adjacency. Creating a unit requires a `unit_number` unique within its property — a duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409) — plus a `floor` and a `stack_index`, each at least 1, and a `bedrooms` count of zero or more. The `operational_status` is `OCCUPIED`, `VACANT`, or `RENOVATION`, defaulting to `OCCUPIED`; units under renovation are invisible to the exposure cascade. Each unit carries a computed `pest_flag` — `CLEAR`, `MONITORING`, or `INFESTED` — whose evaluation order is pinned: `INFESTED` whenever the unit has any bed bug case in `OPEN`, `TREATING`, `MONITORING`, or `REOPENED`; otherwise `MONITORING` whenever the unit has any auto-created `INITIAL` inspection still `SCHEDULED`; otherwise `CLEAR`. A unit also accumulates `no_access_strikes`, the count of consecutive denied inspections, which resets to zero when the strike penalty fires.

### 3.2. Leases, Residents, and the Chargeback Clause

A `PropertyManager` creates a lease on a unit by supplying the inclusive `start_date` and `end_date` (the end not earlier than the start), the `pest_addendum_signed` flag recording whether the resident signed the pest-control chargeback clause, the `chargeback_clause_version` string such as v2026.1, and the `chargeback_cap_cents` ceiling applied per chargeback, zero or more. Lease creation is refused while the property's `posture` is `RESTRICTED`, returning `ERR_PROPERTY_RESTRICTED` (HTTP 409) — a community in a full bed bug response does not paper new tenancies. A lease begins `ACTIVE` and flips lazily to `ENDED` once the current logical date passes its `end_date`. Residents are registered on a unit against a governing lease, supplying `full_name`, `email`, and the `lease_id`; the resident's `unit_id` is fixed by the unit path. A `lease_id` that exists but governs a different unit does not resolve within the unit's scope and is rejected with `ERR_NOT_FOUND` (HTTP 404) per §2.7.

Every lease carries a computed ledger position. `outstanding_balance_cents` is the sum of `provisional_amount_cents` over the lease's chargebacks in `ASSESSED` or `DISPUTED`, plus the sum of `final_amount_cents` over chargebacks in `UPHELD` or `BILLED`; chargebacks that are `WAIVED` or `PAID` contribute zero. The lease's `delinquent` flag is true exactly when the outstanding balance is greater than zero. Because `UPHELD` chargebacks contribute their final amount — which does not exist until billing — an upheld-but-unbilled dispute contributes zero to the balance, and the balance shifts when the chargeback is billed.

A late-fee trigger runs after every upward recompute of the balance: when the outstanding balance reaches at least 50000 cents and the lease has no `LATE_FEE` chargeback in `ASSESSED`, `DISPUTED`, `UPHELD`, or `BILLED`, the system creates a `LATE_FEE` chargeback in `ASSESSED` — base 5000 cents before surcharge — and recomputes the balance once more. The threshold crossing is inclusive, and the trigger's guard means at most one live late fee per lease. A `LATE_FEE` may never be assessed manually; an attempt returns `ERR_INVALID_REQUEST` (HTTP 400). Every system-created chargeback — the late fee here, the no-access strike penalty of §3.3, and the non-compliance fee of §3.4 — records the literal string `system` as its `assessed_by`.

### 3.3. Inspections: Findings, Severity, and the Bed Bug Exposure Cascade

A `PropertyManager` schedules an inspection on a unit by naming the assigned `technician_id` — the technician must be `active`, a registration flag that defaults to true, and an inactive technician is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — along with the `kind` (`ROUTINE`, `INITIAL`, or `FOLLOW_UP`), the `pest_type` from the same five-member pest enum, and the planned `scheduled_for` instant. A `bed_bug_case_id` links the inspection into a case; it is set on follow-ups and on the auto-created initial inspections described below, and is null for ad-hoc routine inspections. The `pest_type` must lie within the property's `ACTIVE` contract scope, or scheduling fails with `ERR_CONTRACT_SCOPE_EXCLUDED` (HTTP 422). A new inspection is `SCHEDULED`.

Only the assigned technician may complete an inspection, and only from `SCHEDULED`. Completion supplies three findings: `live_sightings` and `evidence_count`, each zero or more, and the `bed_bug_positive` confirmation flag. The server stamps `completed_at` from the logical clock and computes `severity` — null until this moment — from inclusive thresholds: `SEVERE` when live sightings are at least 10 or evidence traces are at least 20; otherwise `MODERATE` when live sightings are at least 4 or evidence at least 8; otherwise `LOW` when either count is at least 1; otherwise `NONE`.

When a completion reports `bed_bug_positive` as true, a four-link cascade fires. Link one: if the unit has no bed bug case in `OPEN`, `TREATING`, `MONITORING`, or `REOPENED`, the server creates a new case in `OPEN`; if the unit's existing case sits in `MONITORING`, that case reopens to `REOPENED`, resetting its `consecutive_negative_count` to zero; if the unit's existing live case sits in `OPEN`, `TREATING`, or `REOPENED`, no new case is created, the existing case is left unchanged, and links two and three do not fire; in all three variants the unit's `pest_flag` becomes `INFESTED` and link four still recomputes the property indicators. Link two: a case entering `OPEN` triggers the adjacent-exposure selector. The selector examines every other unit of the same property that is not in `RENOVATION`, and keeps those horizontally adjacent — same `floor`, `stack_index` exactly one apart — or vertically adjacent — same `stack_index`, `floor` exactly one apart. Candidates are processed in `unit_number` ascending order, which is unique per property so no further tie-break is reachable; an empty candidate pool is a silent no-op. For each exposed unit the server creates an inspection of `kind` `INITIAL`, `pest_type` `BED_BUGS`, status `SCHEDULED`, `bed_bug_case_id` pointing at the new case, `scheduled_for` set 24 hours after the current logical time, and assigned to the technician who completed the originating inspection. Link three: each such auto-created initial inspection moves its target unit's `pest_flag` from `CLEAR` to `MONITORING`. Link four: the property's `open_bed_bug_case_count` and `posture` recompute.

Completion also drives the clearance counters: when a completed `FOLLOW_UP` inspection carries a `bed_bug_case_id`, the server replays that case's clearance evaluation, and a positive finding resets the case's `consecutive_negative_count` to zero. Every completion increments the inspection's `version` by 1.

A technician who cannot get in marks the inspection no-access, optionally supplying a `reason` (accepted but not persisted); the inspection moves from `SCHEDULED` to `NO_ACCESS`, and the unit's `no_access_strikes` increments by 1. When the strike count reaches 2, it resets to zero and — if the unit has an `ACTIVE` lease whose `pest_addendum_signed` is true — the system auto-creates a `NON_COMPLIANCE_FEE` chargeback in `ASSESSED` against the unit's earliest-created qualifying lease, which in turn recomputes the lease balance and may set off the late-fee cascade of §3.2. Marking no-access does not re-evaluate the unit's `pest_flag`; an auto-created `INITIAL` inspection that goes `NO_ACCESS` therefore leaves a `MONITORING` flag in place until the next re-evaluation trigger. A `PropertyManager` may instead cancel a `SCHEDULED` inspection; cancelling an auto-created `INITIAL` inspection re-evaluates the unit's `pest_flag`, dropping `MONITORING` back to `CLEAR` once no auto-created initial inspection remains `SCHEDULED` on the unit. An inspection in `COMPLETED`, `NO_ACCESS`, or `CANCELLED` is terminal: any further completion, no-access, or cancellation attempt on it is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 3.4. Treatment Lifecycle: Scheduling, Preparation, and Verification

Scheduling a treatment on a unit is a `PropertyManager` action with a battery of gates. The request names the assigned `technician_id` (who must be `active`; an inactive technician is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the `pest_type`, the `treatment_type` (`CHEMICAL`, `HEAT`, `EXCLUSION`, or `TRAPPING`), and the visit window `window_start` and `window_end`; it may also carry the originating `inspection_id` and a `bed_bug_case_id` that links the treatment into a case. The property's contract must be `ACTIVE` — any of `DRAFT`, `SUSPENDED`, `TERMINATED`, or `EXPIRED` produces `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — and the `pest_type` must fall inside the contract's scope, else `ERR_CONTRACT_SCOPE_EXCLUDED`. The fiscal gate compares `spent_cents` plus the treatment-type estimate from §2.8 against `monthly_budget_cents`; a sum that would exceed the budget is rejected with `ERR_CONTRACT_BUDGET_EXCEEDED` (HTTP 422). The safety invariants of §2.9 apply: heat work requires `vacancy_attested` true, and all three conflict rules run. A new treatment is born `SCHEDULED` with `reschedule_count` at zero and `vacancy_attested` defaulting to false unless the manager supplies it. The server derives `planned_minutes` as the whole-minute length of the window and recomputes the technician's `booked_minutes` — the sum of window lengths over that technician's treatments in `SCHEDULED`, `PREP_NOTIFIED`, `PREP_VERIFIED`, or `NON_COMPLIANT`. Creating a treatment that names a `bed_bug_case_id` moves that case from `OPEN` — or from `REOPENED` — into `TREATING`, incrementing the case's `version`.

Preparation is a three-party handshake. At least 48 hours before `window_start` — a notify attempted inside that window fails with `ERR_PREP_NOTICE_TOO_LATE` (HTTP 422) — the `PropertyManager` issues the prep notice, moving the treatment from `SCHEDULED` to `PREP_NOTIFIED` and stamping `prep_notified_at`. The resident of the unit then acknowledges the prep requirements; acknowledgement is a field update that leaves the treatment in `PREP_NOTIFIED`, stamps `prep_acknowledged_at`, and may happen only once — a second acknowledgement is rejected with `ERR_INVALID_STATE` (HTTP 409) — and only by a resident whose `unit_id` matches the treatment's unit. Finally the `PropertyManager` verifies preparation, passing `compliant` and optionally `notes` (accepted but not persisted). Verification before the prep notice is rejected with `ERR_PREP_NOT_NOTIFIED` (HTTP 409); verification before the resident's acknowledgement is rejected with `ERR_PREP_NOT_ACKNOWLEDGED` (HTTP 409).

A compliant verification moves the treatment to `PREP_VERIFIED`. A non-compliant verification moves it to `NON_COMPLIANT` and fires a second cascade. Link one: if the unit has an `ACTIVE` lease with `pest_addendum_signed` true, the system auto-creates a `NON_COMPLIANCE_FEE` chargeback in `ASSESSED` against the unit's earliest-created qualifying lease whose `source_treatment_id` points at this treatment. Link two: the new chargeback recomputes the lease's `outstanding_balance_cents` and `delinquent`. Link three: if that recompute crosses the 50000-cent late-fee threshold upward under the guard of §3.2, a `LATE_FEE` chargeback in `ASSESSED` follows and the balance recomputes again.

### 3.5. Moving Windows, Cancelling Visits, and Completing the Work

A treatment window moves through the reschedule action, available from `SCHEDULED` — a plain move that leaves the treatment `SCHEDULED` — and from `NON_COMPLIANT`, which returns the treatment to `SCHEDULED`. Every reschedule carries the OCC guard of §2.6 via `expected_treatment_version`, supplies the new `window_start` and `window_end`, re-runs the contract-active, heat-safety, and all three temporal-conflict validations with the rescheduled treatment excluded from its own conflict sets, and increments `reschedule_count` by 1. The hard limit is 2 reschedules; a third attempt is rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED` (HTTP 422). A reschedule out of `NON_COMPLIANT` additionally clears `prep_notified_at` and `prep_acknowledged_at` to null, forcing the preparation handshake to restart. In both flavors the technician's `booked_minutes` recompute across the old and new windows.

A `PropertyManager` may cancel a treatment while it sits in `SCHEDULED`, `PREP_NOTIFIED`, or `NON_COMPLIANT`, optionally supplying a `reason` (accepted but not persisted); cancellation moves it to `CANCELLED` and releases the technician's booked window. Attempting any action on a `COMPLETED` or `CANCELLED` treatment hits the terminal-state rejection.

Only the assigned technician completes a treatment, and only from `PREP_VERIFIED`, supplying the on-site `actual_minutes` of at least 1. Completion books the treatment-type estimate of §2.8 into the `spent_cents` of the property's `ACTIVE` contract — or, when no contract is `ACTIVE`, of the property's most recently created contract; a property with no contract at all books nothing — removes the window from the technician's booked set, and — when the treatment carries a `bed_bug_case_id` — checks whether every treatment linked to that case is now `COMPLETED` and every furniture disposal of the case is `VERIFIED` or none exist; if so the case advances from `TREATING` to `MONITORING`.

### 3.6. Bed Bug Cases: Disposal, Monitoring, and Clearance

A bed bug case is born `OPEN` through the exposure cascade of §3.3, moves to `TREATING` when the first linked treatment is created, and to `MONITORING` when the completion condition of §3.5 is met — every linked treatment completed, and every disposal verified or none logged. A `PropertyManager` logs furniture disposals against a case with an `item_description` and a `quantity` of at least 1; logging is accepted in any case status, and each disposal begins `PENDING`. Verification with `verified` true moves a `PENDING` disposal to `VERIFIED`, stamps `verified_at`, and re-evaluates the case's treating-to-monitoring condition; verification with `verified` false moves it to `REJECTED`. An optional `note` may accompany the verdict (accepted but not persisted). `VERIFIED` and `REJECTED` are terminal for a disposal: a further verification attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Verified disposals are also the billable population for furniture-disposal chargebacks.

Monitoring ends in clearance. A `PropertyManager` evaluates clearance on a case in `MONITORING` — a `CLEARED` case is terminal and returns `ERR_ALREADY_TERMINAL` (HTTP 409), and any other status (`OPEN`, `TREATING`, `REOPENED`) returns `ERR_CASE_NOT_MONITORING` (HTTP 409). The clearance rule replays the case's completed `FOLLOW_UP` inspections in chronological order by `completed_at`, breaking ties by `created_at` ascending; an entry counts as negative when `bed_bug_positive` is false and `severity` is `NONE`, and any non-negative entry resets the running count, producing the case's `consecutive_negative_count`. Clearance passes only when the running count is at least 2, the two most recent consecutive negatives were completed at least 14 days apart inclusive, and every disposal of the case is `VERIFIED` or none exist. A shortfall in the count or spacing returns `ERR_CLEARANCE_CRITERIA_UNMET` (HTTP 422); a disposal still `PENDING` or `REJECTED` returns `ERR_DISPOSAL_UNVERIFIED` (HTTP 422). A passing evaluation moves the case to `CLEARED`, stamps `cleared_at`, recomputes the unit's `pest_flag` — an `INFESTED` unit returns to `CLEAR` when no other non-terminal case and no scheduled auto-created initial inspection remain — and recomputes the property's case count and posture. A case in `MONITORING` that suffers a positive follow-up reopens to `REOPENED`, resets its negative counter, recomputes the property indicators, and may return to `TREATING` when a fresh linked treatment is created.

### 3.7. Chargebacks: Assessment, Dispute, and Collection

A `BillingClerk` assesses a chargeback against a lease, supplying the `kind` — `NON_COMPLIANCE_FEE`, `REPEAT_INFESTATION`, `HEAT_SURCHARGE`, or `FURNITURE_DISPOSAL` — and optionally a `note`, a `source_treatment_id`, and the case linkage. Assessment requires the lease to be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE` (HTTP 409), and requires `pest_addendum_signed` true, else `ERR_LEASE_CLAUSE_MISSING` (HTTP 422). Kind-specific shape rules apply: a `FURNITURE_DISPOSAL` chargeback must carry `bed_bug_case_id` and a `planned_item_count` of at least 1; a `HEAT_SURCHARGE` is assessable only when the property's `ACTIVE` contract exists and its `heat_treatment_included` is false — with no `ACTIVE` contract the surcharge is not assessable; a manual `LATE_FEE` is never permitted. Shape violations return `ERR_INVALID_REQUEST` (HTTP 400). The server stamps `assessed_at` from the logical clock, records the clerk's `X-User-ID` as `assessed_by`, computes `provisional_amount_cents`, and lands the chargeback in `ASSESSED`.

Amount computation runs in two variants with a pinned evaluation order. Each line's base is computed first; the vendor coverage credit — the smaller of the `coverage_per_incident_cents` of the property's `ACTIVE` contract and 22000, or zero when the property has no `ACTIVE` contract — applies to the `REPEAT_INFESTATION` line base only; every line is then multiplied by 1.075 and rounded half-up to whole cents individually; the rounded lines are summed; and the total is clamped to at most the lease's `chargeback_cap_cents` and never below zero. Per-line rounding before summation is mandatory — three disposal lines illustrate why: 7995 cents with the surcharge is 8594.625 per line, rounding each line first yields three lines of 8595 summing to 25785, whereas summing first and rounding once would yield 25784; the pinned behavior is 25785. The line composition is: `NON_COMPLIANCE_FEE`, one line of 15000; `REPEAT_INFESTATION`, one line of 22000 reduced by coverage, floored at zero; `HEAT_SURCHARGE`, one line of 65000; `LATE_FEE`, one line of 5000. For `FURNITURE_DISPOSAL`, the provisional variant uses `planned_item_count` lines of 7995 each, while the final variant uses one line of 7995 per `VERIFIED` disposal of the linked case, excluding `PENDING` and `REJECTED` items. The final variant alone appends an overage line — the excess of `actual_minutes` over `planned_minutes`, floored at zero, multiplied by 175 cents — when a `source_treatment_id` is set and that treatment is `COMPLETED`; the provisional variant never includes an overage line. Every assessment, dispute, resolution, billing, waiver, and payment recomputes the lease balance of §3.2 and can trigger the late-fee cascade.

The resident of the lease may dispute an `ASSESSED` chargeback, supplying a `reason`, within 14 days of `assessed_at` inclusive; a later attempt returns `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422). Disputing moves the chargeback to `DISPUTED` and stamps `disputed_at` and `dispute_reason`. A `ComplianceOfficer` then resolves the dispute with a `resolution` of `UPHELD` or `WAIVED`, under the OCC guard of §2.6 via `expected_chargeback_version`, and under segregation of duties: the resolver's `X-User-ID` must differ from the chargeback's `assessed_by`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Resolution stamps `resolved_by` and `resolution`; `UPHELD` contributes zero to the lease balance until billed, while `WAIVED` contributes zero outright and restores the balance.

Billing — from `ASSESSED` or `UPHELD`, by a `BillingClerk` — computes `final_amount_cents` under the final variant, stamps `billed_at`, and replaces the provisional contribution with the final one in the lease balance. Recording payment requires the submitted `amount_cents` to equal `final_amount_cents` exactly; a mismatch returns `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A matching payment moves the chargeback to `PAID`, stamps `paid_at`, and zeroes its contribution to the balance. `WAIVED` and `PAID` are terminal.

### 3.8. Habitability Claim Packets

When a dispute escalates toward a habitability claim, a `ComplianceOfficer` assembles a claim packet on a property, supplying the external `claim_reference` and a `references` array naming the evidentiary records — each entry an `entity_type` of `Inspection`, `Treatment`, or `BedBugCase` paired with an `entity_id`; an entry with any other `entity_type` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an `entity_id` naming no existing record of that type is rejected with `ERR_NOT_FOUND` (HTTP 404). Referenced entities are not required to belong to the packet's property — no cross-property check is applied. At creation the server snapshots every referenced entity's current `version` into `pinned_references`, and the packet sits in `DRAFT`.

Finalization is the integrity checkpoint. It requires the packet still in `DRAFT`, every pinned entity still in existence, every pinned version still equal to the referenced entity's current `version` — a drifted reference returns `ERR_CLAIM_PACKET_STALE_REFERENCE` (HTTP 409) — and every referenced inspection in `COMPLETED`, else `ERR_INSPECTION_NOT_COMPLETED` (HTTP 409). A passing finalization stamps `finalized_at`, moves the packet to `FINALIZED`, and renders it immutable. A packet that should not be filed moves from `DRAFT` to `DISCARDED`. Both endpoints increment the packet's `version`.

### 3.9. Risk Scores and Exposure Reads

A computed per-unit risk score supports both operational planning and audit. The read takes a required `variant` query parameter — `FORWARD` or `HISTORICAL`; a missing or unrecognized variant is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and returns the `score` plus the four contributing components `severe_recent`, `prior_cases_points`, `adjacent_open_points`, and `recency_points`, with the `variant` echoed.

The score sums four terms, capped at 100. The severe-history term contributes 40 when the unit has any completed inspection with `severity` `SEVERE` whose `completed_at` lies within the trailing 90 days — the 90-day boundary is inclusive, so a completion exactly 90 days ago counts — and zero otherwise. The prior-cases term contributes 15 per bed bug case of the unit, regardless of status, counting at most 3 cases. The adjacent-exposure term contributes 10 per live case — status `OPEN`, `TREATING`, `MONITORING`, or `REOPENED` — on units the adjacency predicate of §3.3 would select for this unit, counting at most 2 such cases. The recency term depends on the variant: under `FORWARD`, relevant treatments are those in `SCHEDULED`, `PREP_NOTIFIED`, `PREP_VERIFIED`, or `COMPLETED`, so a future-dated scheduled treatment zeroes the term; under `HISTORICAL`, only `COMPLETED` treatments count, so scheduled-but-incomplete work is invisible and the term stays high. When no relevant treatment exists with a `window_start` inside the trailing 180 days — again inclusive at the boundary — the recency term contributes its full 25; otherwise it contributes 5 points per whole 30-day step elapsed since the most recent relevant `window_start` — negative elapsed time floors at zero days — capped at 25. The components sum as integers and the total clamps at 100.

A companion read exposes, for any unit, exactly the set of units the adjacent-exposure selector would pick under the predicate of §3.3 — useful for planning walk-throughs before a case is ever opened. It returns the standard paginated list envelope of §2.3 with `response_type` `array`, each element a unit object, ordered by `created_at` ascending like every other list.

## 4. Endpoint Definitions

The API is mounted under `/pest`; the logical-clock endpoint sits at the root. Creating a new resource returns 201; every successful modification, action, or read returns 200. Request and response bodies follow the envelope of §2.2, and every workflow rule, precondition, and side effect lives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server logical clock | ProgramAdmin |
| POST | /pest/properties | Create a community | ProgramAdmin |
| GET | /pest/properties | List properties (paginated) | ProgramAdmin, PropertyManager, BillingClerk, ComplianceOfficer |
| GET | /pest/properties/{id} | Read one property | ProgramAdmin, PropertyManager, BillingClerk, ComplianceOfficer |
| GET | /pest/properties/{id}/summary | Computed read: posture, open case count, aggregate outstanding balance | ProgramAdmin, PropertyManager, BillingClerk, ComplianceOfficer |
| POST | /pest/properties/{id}/contracts | Create a contract in DRAFT | ProgramAdmin |
| GET | /pest/properties/{id}/contracts | List contracts of a property | ProgramAdmin, PropertyManager, BillingClerk |
| GET | /pest/contracts/{id} | Read one contract (lazy EXPIRED applies) | ProgramAdmin, PropertyManager, BillingClerk |
| POST | /pest/contracts/{id}/activate | DRAFT → ACTIVE | ProgramAdmin |
| POST | /pest/contracts/{id}/suspend | ACTIVE → SUSPENDED | ProgramAdmin |
| POST | /pest/contracts/{id}/reactivate | SUSPENDED → ACTIVE | ProgramAdmin |
| POST | /pest/contracts/{id}/terminate | ACTIVE or SUSPENDED → TERMINATED | ProgramAdmin |
| POST | /pest/properties/{id}/units | Create a unit | ProgramAdmin |
| GET | /pest/properties/{id}/units | List units of a property (filterable by floor) | ProgramAdmin, PropertyManager, Technician, BillingClerk, ComplianceOfficer |
| GET | /pest/units/{id} | Read one unit | ProgramAdmin, PropertyManager, Technician, BillingClerk, ComplianceOfficer, Resident |
| GET | /pest/units/{id}/risk-score | Computed unit pest risk score per variant | ProgramAdmin, PropertyManager |
| GET | /pest/units/{id}/adjacent-exposure | Computed read: units the exposure selector would pick | ProgramAdmin, PropertyManager |
| POST | /pest/units/{id}/leases | Create a lease (blocked while property RESTRICTED) | PropertyManager |
| GET | /pest/units/{id}/leases | List leases of a unit | ProgramAdmin, PropertyManager, BillingClerk, Resident |
| GET | /pest/leases/{id} | Read one lease (lazy ENDED applies) | ProgramAdmin, PropertyManager, BillingClerk, Resident |
| GET | /pest/leases/{id}/chargebacks | List chargebacks of a lease (filterable by status) | ProgramAdmin, PropertyManager, BillingClerk, Resident |
| POST | /pest/units/{id}/residents | Register a resident on a unit and lease | PropertyManager |
| GET | /pest/units/{id}/residents | List residents of a unit | ProgramAdmin, PropertyManager |
| GET | /pest/leases/{id}/residents | List residents of a lease | ProgramAdmin, PropertyManager, BillingClerk |
| POST | /pest/technicians | Register a vendor technician | ProgramAdmin |
| GET | /pest/technicians/{id} | Read one technician (includes booked minutes) | ProgramAdmin, PropertyManager, Technician |
| GET | /pest/technicians/{id}/treatments | List treatments assigned to a technician (schedule view) | ProgramAdmin, PropertyManager, Technician |
| GET | /pest/technicians/{id}/inspections | List inspections assigned to a technician | ProgramAdmin, PropertyManager, Technician |
| POST | /pest/units/{id}/inspections | Schedule an inspection | PropertyManager |
| GET | /pest/units/{id}/inspections | List inspections of a unit (filterable by kind, status) | ProgramAdmin, PropertyManager, Technician, Resident |
| GET | /pest/inspections/{id} | Read one inspection | ProgramAdmin, PropertyManager, Technician, Resident, ComplianceOfficer |
| GET | /pest/bed-bug-cases/{id}/inspections | List inspections linked to a bed bug case | ProgramAdmin, PropertyManager, Technician |
| GET | /pest/inspections/{id}/treatments | List treatments originating from an inspection | ProgramAdmin, PropertyManager, Technician |
| POST | /pest/inspections/{id}/complete | Complete with findings; computes severity; may fire the bed bug cascade | Technician |
| POST | /pest/inspections/{id}/no-access | Mark NO_ACCESS; accrues a unit strike | Technician |
| POST | /pest/inspections/{id}/cancel | Cancel a scheduled inspection | PropertyManager |
| POST | /pest/units/{id}/treatments | Schedule a treatment (contract, scope, budget, safety, overlap gates) | PropertyManager |
| GET | /pest/units/{id}/treatments | List treatments of a unit (filterable by status) | ProgramAdmin, PropertyManager, Technician, Resident |
| GET | /pest/treatments/{id} | Read one treatment | ProgramAdmin, PropertyManager, Technician, Resident, BillingClerk, ComplianceOfficer |
| GET | /pest/bed-bug-cases/{id}/treatments | List treatments linked to a bed bug case | ProgramAdmin, PropertyManager, Technician |
| GET | /pest/treatments/{id}/chargebacks | List chargebacks sourced from a treatment | ProgramAdmin, PropertyManager, BillingClerk |
| POST | /pest/treatments/{id}/notify-prep | SCHEDULED → PREP_NOTIFIED; requires 48-hour notice | PropertyManager |
| POST | /pest/treatments/{id}/acknowledge-prep | Resident acknowledges prep requirements (state unchanged) | Resident |
| POST | /pest/treatments/{id}/verify-prep | compliant true → PREP_VERIFIED; false → NON_COMPLIANT plus chargeback cascade | PropertyManager |
| POST | /pest/treatments/{id}/reschedule | Move the window from SCHEDULED or NON_COMPLIANT; OCC-guarded; limit 2 | PropertyManager |
| POST | /pest/treatments/{id}/complete | PREP_VERIFIED → COMPLETED; books contract spend; may advance the case | Technician |
| POST | /pest/treatments/{id}/cancel | Cancel from SCHEDULED, PREP_NOTIFIED, or NON_COMPLIANT | PropertyManager |
| GET | /pest/units/{id}/bed-bug-cases | List bed bug cases of a unit (filterable by status) | ProgramAdmin, PropertyManager, Resident |
| GET | /pest/bed-bug-cases/{id} | Read one bed bug case | ProgramAdmin, PropertyManager, Technician, Resident |
| GET | /pest/bed-bug-cases/{id}/chargebacks | List chargebacks linked to a bed bug case | ProgramAdmin, PropertyManager, BillingClerk |
| POST | /pest/bed-bug-cases/{id}/furniture-disposals | Log a furniture disposal item (PENDING) | PropertyManager |
| GET | /pest/bed-bug-cases/{id}/furniture-disposals | List disposal items of a case (filterable by status) | ProgramAdmin, PropertyManager, Resident |
| POST | /pest/furniture-disposals/{id}/verify | verified true → VERIFIED; false → REJECTED | PropertyManager |
| POST | /pest/bed-bug-cases/{id}/evaluate-clearance | MONITORING → CLEARED when the clearance rule passes | PropertyManager |
| POST | /pest/leases/{id}/chargebacks | Assess a chargeback (provisional amount; late-fee cascade) | BillingClerk |
| GET | /pest/chargebacks/{id} | Read one chargeback | ProgramAdmin, PropertyManager, BillingClerk, ComplianceOfficer, Resident |
| POST | /pest/chargebacks/{id}/dispute | ASSESSED → DISPUTED within the 14-day window | Resident |
| POST | /pest/chargebacks/{id}/resolve-dispute | DISPUTED → UPHELD or WAIVED; OCC-guarded; segregation of duties | ComplianceOfficer |
| POST | /pest/chargebacks/{id}/bill | ASSESSED or UPHELD → BILLED; computes the final amount | BillingClerk |
| POST | /pest/chargebacks/{id}/record-payment | BILLED → PAID when the amount matches the final | BillingClerk |
| POST | /pest/properties/{id}/claim-packets | Assemble a habitability documentation packet (snapshots versions) | ComplianceOfficer |
| GET | /pest/properties/{id}/claim-packets | List claim packets of a property | ProgramAdmin, PropertyManager, ComplianceOfficer |
| GET | /pest/claim-packets/{id} | Read one claim packet | ProgramAdmin, ComplianceOfficer |
| POST | /pest/claim-packets/{id}/finalize | DRAFT → FINALIZED; validates pinned versions and completed inspections | ComplianceOfficer |
| POST | /pest/claim-packets/{id}/discard | DRAFT → DISCARDED | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_PREP_NOT_NOTIFIED | 409 |
| ERR_PREP_NOT_ACKNOWLEDGED | 409 |
| ERR_CASE_NOT_MONITORING | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_HEAT_SAFETY_VIOLATION | 422 |
| ERR_UNIT_DOUBLE_BOOKED | 409 |
| ERR_TREATMENT_WINDOW_CONFLICT | 409 |
| ERR_HEAT_FLOOR_GAP_VIOLATION | 409 |
| ERR_PREP_NOTICE_TOO_LATE | 422 |
| ERR_DISPUTE_WINDOW_EXPIRED | 422 |
| ERR_RESCHEDULE_LIMIT_EXCEEDED | 422 |
| ERR_CLEARANCE_CRITERIA_UNMET | 422 |
| ERR_DISPOSAL_UNVERIFIED | 422 |
| ERR_CLAIM_PACKET_STALE_REFERENCE | 409 |
| ERR_PROPERTY_RESTRICTED | 409 |
| ERR_INSPECTION_NOT_COMPLETED | 409 |
| ERR_DUPLICATE_UNIT_NUMBER | 409 |
| ERR_CONTRACT_SCOPE_EXCLUDED | 422 |
| ERR_LEASE_CLAUSE_MISSING | 422 |
| ERR_CONTRACT_BUDGET_EXCEEDED | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |

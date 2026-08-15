# Multi-State Employment Tax API — Product Requirements Document

## 1. Introduction

An employer with a distributed workforce accumulates employment-tax obligations every time an employee crosses a state line: a remote hire in a new state can create withholding and unemployment-insurance nexus within weeks, each agency demands its own registration and account number, local jurisdictions stack on top of state taxes, and every missed deposit or unanswered notice compounds into penalties. This document specifies the Multi-State Employment Tax API, the system of record through which an employment tax team determines nexus from employee work locations, registers with state and local agencies, manages reciprocity and courtesy-withholding elections, maintains unemployment insurance rates (including voluntary contribution buy-downs), tracks remote-worker location changes, drives the filing calendar and deposit schedules, and resolves agency notices through penalty abatement.

Two design commitments shape everything that follows. First, the API is compliance-audit grade: a singleton Employer aggregate maintains a live compliance posture and penalty counters that every workflow re-derives, segregation-of-duties rules separate proposers from approvers, and optimistic concurrency guards the handful of writes that legitimately extend a parent aggregate. Second, time is explicit: the server runs on a logical clock that a director can advance, and a scheduled sweep attached to that clock is what moves agreements, elections, obligations, contributions, and location changes through their time-triggered transitions. All endpoints are mounted under the `/etax` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request with either header missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows:

- `TaxDirector` — the employment tax director: catalog administration, nexus exemptions, voluntary-contribution approval and decline, abatement review and decision, location-change reversal, registration close, and clock control.
- `NexusAnalyst` — the nexus and registration analyst: employees, work locations, nexus cases, the registration lifecycle, election validation and rejection, location-change review and editing, and local-assignment resolution.
- `UISpecialist` — the unemployment insurance specialist: rate notice intake, review, contest, and make-effective, plus voluntary-contribution proposal, remittance, and application.
- `PayrollComplianceLead` — payroll compliance: filing-obligation filing and confirmation, agency-notice intake, triage, escalation and resolution, and abatement preparation, submission, and withdrawal.
- `Employee` — employee self-service: submits their own location changes and withholding elections, revokes their own elections, cancels their own location changes, and reads their own records.
- `Auditor` — a read-only auditor.

Role identity works as follows. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's `employee_id` foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule governs employee-role access to election creation and revocation, location-change creation and cancellation, and the employee's own record reads. When `X-User-Role` is `TaxDirector`, `NexusAnalyst`, `UISpecialist`, `PayrollComplianceLead`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow nominates an actor (for example as `submitted_by_user_id` on a WithholdingElection or LocationChange, `proposed_by_user_id` and `approved_by_user_id` on a VoluntaryContribution, `filed_by_user_id` and `confirmed_by_user_id` on a FilingObligation, `prepared_by_user_id` and `reviewed_by_user_id` on an AbatementRequest, or `reviewed_by_user_id` on a LocationChange) but never compares it to any entity's `id`. Those recorded identifiers exist so that segregation-of-duties checks can compare originator and approver.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List endpoints additionally accept the filter query parameters implied by their resource's field names (for example, filtering employees by `status` or `resident_state_code`, or registrations by `agency_id`).

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Scheduled Sweep

The server maintains a logical clock that governs every time-triggered behavior in the system. Before it has ever been set, the clock defaults to 2026-08-01T00:00:00Z. A `TaxDirector`-only capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The clock is monotonic and never moves backward; an attempt to set it to an earlier instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Setting the clock runs the scheduled sweep, a single pass that applies every pending time-based transition: ReciprocityAgreement `status` is recomputed against the clock (an agreement is `SCHEDULED` before its first covered date, `ACTIVE` within its covered range, and `EXPIRED` once its last covered date has passed); WithholdingElections in `VALIDATED` whose `effective_from` has been reached move to `ACTIVE`, and elections in `VALIDATED` or `ACTIVE` whose `effective_to` has passed move to `EXPIRED`; VoluntaryContributions still `PROPOSED` past their `decision_deadline` move to `EXPIRED`; FilingObligations move from `SCHEDULED` to `DUE` once their period has ended and from `DUE` to `LATE` once the day after their due date arrives, with the penalty-notice cascade described in §3.8; LocationChanges in `APPROVED` whose `effective_date` has been reached effectuate per §3.6; and the Employer's compliance posture is recomputed. Clients observe all of these transitions only by advancing the clock and then reading the affected resources.

### 2.5. Common Resource Properties

Every resource in the system — Employer, TaxAgency, ReciprocityAgreement, WorkLocation, Employee, NexusCase, Registration, WithholdingElection, LocalAssignment, UIRate, VoluntaryContribution, LocationChange, FilingObligation, AgencyNotice, and AbatementRequest — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that increments by one with every modification to the resource.

"Modification" includes automatic and cascaded writes, not just direct client requests: recomputation of derived fields on the Employer, supersession of a LocalAssignment segment, or a clock-sweep transition are all mutations that refresh `updated_at` and increment `version` on the affected resource. Several workflows nominate this increment explicitly — employee termination, location-change effectuation and reversal, election creation, and manual assignment override each increment the Employee's `version` by one; registration activation and schedule recomputation increment the Registration's `version`; UI-rate intake increments the Registration's `version`; registration creation increments the Employer's `version`; editing a pending location change increments the LocationChange's `version`.

### 2.6. Monetary Amounts, Basis-Point Rates, and Rounding Discipline

All monetary values in the system are integer cents — wages, obligation amounts, penalties, contributions, and projected liabilities alike. All tax rates are integer basis points, where one basis point is one hundredth of a percent (so a 4.8 percent rate is carried as 480).

Rounding follows one rule everywhere: round half up. Where a computation produces per-employee lines, each line is rounded half up to cents first and the rounded lines are then summed; summing unrounded lines and rounding once at the end produces different cents and is non-conformant. One computation deliberately deviates: the `STATUTORY` abatement eligibility amount halves the outstanding penalty using floor (rounding down). Rate-bracket arithmetic works in integer basis points, with round half up applied to the reserve ratio. Dates are date-granular; period and coverage endpoints are inclusive at both ends unless a field is explicitly documented as half-open, and date-only inputs such as `hire_date` or an agreement's `effective_from` are carried as an ISO date at 00:00:00Z.

### 2.7. Employer-Wide Compliance Posture and Aggregate Counters

The Employer is a singleton aggregate whose computed fields summarize the entire book of business. `open_notice_count` counts AgencyNotices whose status is `RECEIVED`, `TRIAGED`, `RESPONSE_IN_PROGRESS`, or `ESCALATED` — these four statuses are the "open" notices throughout this document. `outstanding_penalty_cents` sums, over those open notices, each notice's `penalty_amount_cents` minus its `abated_amount_cents`. `registered_state_count` counts the distinct `state_code` values across Registrations in `ACTIVE` status.

`compliance_posture` is derived and takes one of three values. The posture is `DELINQUENT` when any open notice is `ESCALATED`, or any FilingObligation is `LATE` with `late_days` greater than 30, or `outstanding_penalty_cents` exceeds 1,000,000 cents (ten thousand dollars). Otherwise it is `WATCH` when any open notice exists, or any FilingObligation is `LATE`, or any NexusCase is `THRESHOLD_MET`. Otherwise it is `GOOD_STANDING`. Escalating a notice therefore forces `DELINQUENT` posture outright, and a single `THRESHOLD_MET` nexus case forces at least `WATCH`.

These aggregates recompute immediately, without a client request on the Employer itself, whenever an AgencyNotice is created, escalated, resolved, or closed; whenever a FilingObligation goes late, is filed, is waived, or is confirmed; whenever a NexusCase changes state; whenever an AbatementRequest is decided; and whenever a Registration is activated or closed. Each such recomputation is a mutation of the Employer under §2.5.

### 2.8. Optimistic Concurrency Control

Five write endpoints protect a parent aggregate against stale observations. Each requires a non-optional expected-version field in the request body, carrying the value of the parent's `version` the client last observed; if that value does not match the parent entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The five rules are:

- Creating a Registration (`POST /etax/registrations`) requires `expected_employer_version` matching the Employer's current `version`, because creating a registration legitimately extends the employer's registration portfolio and a writer who has not observed that extension must not proceed.
- Creating a WithholdingElection (`POST /etax/withholding-elections`) requires `expected_employee_version` matching the Employee's current `version`, since the creation may legitimately supersede the employee's current same-type election.
- A manual LocalAssignment override (`POST /etax/local-assignments/override`) requires `expected_employee_version` matching the Employee's current `version`, since an override legitimately truncates the employee's current assignment segment.
- Intaking a UIRate (`POST /etax/ui-rates`) requires `expected_registration_version` matching the Registration's current `version`, since intake legitimately supersedes the current rate for the same registration and rate year.
- Editing a pending LocationChange (`PATCH /etax/location-changes/{id}`) requires `expected_location_change_version` matching the LocationChange's current `version`.

Endpoints not listed here do not take a version field. The check exists so that a client never overwrites a state of the parent it has not observed; the rejection is purely a function of the version values, independent of when any other request was made.

### 2.9. Validation Order and Error Surface

When several checks could reject the same request, the server evaluates them in a fixed order and reports the first failure. The order is:

1. **Header presence.** `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The caller's role is listed for the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence.** Path identifiers resolve to existing resources, validated left to right along the path, and foreign-key identifiers in the request body must exist, else `ERR_NOT_FOUND` (HTTP 404).
4. **Employee ownership.** An `Employee`-role caller may act only on resources whose `employee_id` equals their `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
5. **Date sanity.** Date pairs and deadlines are coherent — `effective_from` strictly earlier than `effective_to`, a contribution's `decision_deadline` strictly in the future, a notice's `response_due_date` no earlier than its `received_date` — else `ERR_INVALID_DATE_RANGE` (HTTP 400).
6. **From-state legality.** The target resource is in a state from which the requested transition is allowed (terminal states are locked down, and a voluntary contribution may be created only against an `EFFECTIVE` rate), else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Within this same tier, creating or approving a location change against a `TERMINATED` employee raises `ERR_EMPLOYEE_NOT_ACTIVE` (HTTP 409); when both fire, the from-state check reports first.
7. **Optimistic concurrency.** The `expected_*_version` field matches the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
8. **Business safety gates.** Registration submission requires the state's NexusCase `CONFIRMED` (`ERR_NEXUS_NOT_CONFIRMED`, HTTP 409); voluntary-contribution approval requires the Employer's posture not be `DELINQUENT` (`ERR_COMPANY_POSTURE_DELINQUENT`, HTTP 409).
9. **Segregation of duties.** The approver, confirmer, or reviewer differs from the originator by `X-User-ID` — voluntary-contribution approver versus proposer, obligation confirmer versus filer, abatement reviewer versus preparer, location-change approver versus submitter — else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
10. **Uniqueness and singleton constraints.** The Employer singleton already exists (`ERR_EMPLOYER_ALREADY_EXISTS`); an active TaxAgency with the same kind, state, and locality exists (`ERR_DUPLICATE_AGENCY`); a NexusCase for the state exists among the monitored statuses (`ERR_DUPLICATE_NEXUS_CASE`); a non-`CLOSED` Registration for the agency exists (`ERR_DUPLICATE_REGISTRATION`); the employee already has an open location change (`ERR_LOCATION_CHANGE_PENDING`); an election overlaps (`ERR_ELECTION_OVERLAP`); an agreement overlaps (`ERR_AGREEMENT_OVERLAP`) — all HTTP 409.
11. **Referential fitness.** Agency-kind fitness (`ERR_AGENCY_KIND_MISMATCH`, HTTP 422); election work/resident semantics (`ERR_INVALID_REQUEST`, HTTP 400); reciprocity coverage (`ERR_RECIPROCITY_NOT_AVAILABLE`, HTTP 422); courtesy registration presence (`ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409); new-employer voluntary contribution (`ERR_VC_NOT_ALLOWED_NEW_EMPLOYER`, HTTP 422); contribution application against a superseded rate (`ERR_RATE_SUPERSEDED`, HTTP 409).
12. **Temporal windows.** Remittance after the decision deadline (`ERR_DEADLINE_PASSED`, HTTP 409); abatement submission past the sixty-day window (`ERR_ABATEMENT_WINDOW_CLOSED`, HTTP 409).
13. **Fiscal checks.** Requested abatement exceeds the outstanding penalty (`ERR_AMOUNT_EXCEEDS_PENALTY`, HTTP 422); a contribution projecting no positive savings (`ERR_NO_NET_SAVINGS`, HTTP 422); abatement submission with zero eligibility (`ERR_ABATEMENT_NOT_ELIGIBLE`, HTTP 422); notice resolution while a linked abatement is non-terminal (`ERR_ABATEMENT_PENDING`, HTTP 409); registration close while unsettled (`ERR_REGISTRATION_NOT_SETTLED`, HTTP 409).
14. **General request sanity.** Malformed bodies, invalid enum values, non-positive amounts, missing required fields, a notice with no link, an inactive target work location, and a certificate-form mismatch fall through to `ERR_INVALID_REQUEST` (HTTP 400), the catch-all rejection.

## 3. Business Logic & Workflows

### 3.1. Establishing the Employer, the Agency Catalog, and Reciprocity Coverage

Everything begins with the Employer. A `TaxDirector` creates it once, supplying `legal_name`, `fein` (the federal employer identification number: exactly nine digits and globally unique), and `home_state_code` (the headquarters state's two-letter code). At creation the posture is `GOOD_STANDING` and every counter is zero. A second attempt to create the Employer is rejected with `ERR_EMPLOYER_ALREADY_EXISTS`.

The TaxAgency catalog is the reference data every downstream workflow resolves against. A `TaxDirector` creates each agency with an `agency_kind` of `STATE_WITHHOLDING`, `STATE_UI`, or `LOCAL`, a two-letter `state_code`, and a display `agency_name`. A `LOCAL` agency carries a `locality_code` matcher token — an uppercase city name such as PHILADELPHIA, a postal code such as 19103, or the statewide token formed by the state code followed by `-ALL` — while state-level agencies leave `locality_code` null. Kind-specific rate data rides on the same record: a `STATE_WITHHOLDING` agency declares a flat `withholding_rate_bp`; a `LOCAL` agency declares `resident_rate_bp` and `nonresident_rate_bp` plus a `precedence_rank` (defaulting to 100, lower values win assignment precedence); a `STATE_UI` agency declares `new_employer_rate_bp`, an optional `solvency_surcharge_bp` (defaulting to 0, added after the bracket lookup), and the annual `ui_wage_base_cents` taxable wage base per employee. The catalog flag `is_active` defaults to true. Among active agencies the combination of kind, state, and locality must be unique; a duplicate is rejected with `ERR_DUPLICATE_AGENCY`.

Reciprocity between states is catalogued as ReciprocityAgreements, again `TaxDirector`-maintained. Each agreement names an unordered pair of states via `state_a` and `state_b`, a first covered date `effective_from` (inclusive), and an optional last covered date `effective_to` that is also inclusive — a null `effective_to` means the agreement is open-ended. The optional `certificate_form_code` records the certificate form an employee must supply (for example NJ-165), and `scope` is either `FULL` or `WAGES_ONLY`. The agreement's `status` is computed from the clock — `SCHEDULED` before the first covered date, `ACTIVE` within the covered range, `EXPIRED` once the last covered date has passed — and is refreshed by the scheduled sweep. Two agreements for the same unordered pair whose closed date ranges share even a single day are rejected with `ERR_AGREEMENT_OVERLAP`: because both endpoints are inclusive, a new agreement's `effective_from` must fall strictly after the existing agreement's `effective_to` for the ranges to be disjoint.

### 3.2. Work Locations, Employee Intake, and Local Jurisdiction Resolution

A `NexusAnalyst` registers each place work happens as a WorkLocation: a `label`, the street `address_line1`, the `city`, the two-letter `state_code`, the `postal_code`, and a `location_type` of `COMPANY_OFFICE`, `REMOTE_HOME`, or `CLIENT_SITE`. The `is_active` flag defaults to true; an inactive location rejects new assignments and new location changes targeting it with `ERR_INVALID_REQUEST`.

Employee intake likewise belongs to the `NexusAnalyst`. The payload carries an external `employee_ref` (unique across employees), `full_name`, the `resident_state_code`, an optional `resident_locality_code` (an uppercase locality token matching agency `locality_code` values), the `hire_date` (an ISO date at midnight UTC — day attribution starts here), `annual_wage_cents` (the annualized wage in cents, which must be greater than zero), and `current_work_location_id`. The employee starts `ACTIVE`. Creation automatically runs local jurisdiction resolution and creates the employee's initial LocalAssignment with `resolution_source` `AUTO_GEOCODE`, covering from `hire_date`.

Jurisdiction resolution is a deterministic selector, run on both the work side and the resident side. Work-side candidates are active `LOCAL` agencies of the work location's state whose `locality_code` matches any of three tokens: the location's `postal_code` (a postal match, specificity 0), the uppercased location `city` (a city match, specificity 1), or the statewide token (specificity 2). Resident-side candidates use the employee's `resident_state_code` and `resident_locality_code` instead — postal matching is not available on that side; a `locality_code` equal to `resident_locality_code` scores specificity 1 and the statewide token scores 2. On both sides, candidates rank by ascending `precedence_rank`, then ascending specificity, then ascending `created_at`; the first row wins and is recorded as `work_agency_id` or `resident_agency_id` respectively. An empty candidate set yields a null agency — a valid outcome meaning no local tax applies — and the human-readable `precedence_trace` records the ranking, noting `NONE_FOUND` for a side with no candidate. When the same agency wins both sides, `resident_agency_id` is set to null and the trace notes `COLLAPSED`.

Assignment segments are half-open intervals: `effective_from` inclusive, `effective_to` exclusive, with `effective_to` null while the segment is open; `status` is `CURRENT` or `SUPERSEDED`. A new segment never overlaps an existing one — it truncates it. The employee's `CURRENT` segment receives an `effective_to` equal to the earlier of its existing `effective_to` and the new segment's `effective_from`; if that truncation leaves `effective_to` at or before `effective_from`, the old row is `SUPERSEDED` outright. Overlap is resolved by truncation, never by rejection — a deliberate contrast with withholding elections, which reject overlap, and with reciprocity agreements, which reject closed-interval overlap.

Two operations produce new segments beyond intake. A `NexusAnalyst` can re-run automatic resolution for an employee and work location from a supplied `effective_from`, producing an `AUTO_GEOCODE` row with the same truncation. A `TaxDirector` can impose a manual override, supplying `employee_id`, `work_location_id`, `effective_from`, an `override_reason`, optional `resident_agency_id` and `work_agency_id` values, and `expected_employee_version` per §2.8; the override bypasses candidate selection but still requires every named agency to be a `LOCAL` agency (otherwise `ERR_AGENCY_KIND_MISMATCH`), marks the row `resolution_source` `MANUAL_OVERRIDE`, truncates the current segment identically, and increments the employee's `version`.

Termination ends attribution. A `NexusAnalyst` terminates an employee by supplying `termination_date`; the employee must currently be `ACTIVE` (otherwise `ERR_INVALID_STATE_TRANSITION`), and any location change still `PENDING_REVIEW` or `APPROVED` for that employee blocks termination with `ERR_LOCATION_CHANGE_PENDING`. The `termination_date` is recorded and day attribution stops there; the `CURRENT` assignment is truncated at that date (a zero-length remainder is `SUPERSEDED`); the NexusCase for the truncated assignment's state is recomputed; and the employee's `version` increments by one. `TERMINATED` is terminal.

### 3.3. Nexus Monitoring: Attribution, Thresholds, and Posture Coupling

A NexusCase watches one state, opened by a `NexusAnalyst` with just a `state_code`. Only one case per state may exist among the statuses `WATCH`, `THRESHOLD_MET`, `CONFIRMED`, and `LAPSED`; a duplicate is rejected with `ERR_DUPLICATE_NEXUS_CASE`. Creation runs the attribution model immediately, so a case can enter `THRESHOLD_MET` at once if the workforce already crosses a threshold.

The attribution model counts employee presence state by state. Each employee contributes calendar days through their LocalAssignment segments — whether `CURRENT` or `SUPERSEDED` — that intersect the counting window. A day counts for a state when the segment covering that day belongs to a work location in that state and the day falls no earlier than the latest of the employee's `hire_date`, the segment's `effective_from`, and the window start, and no later than the earliest of the employee's `termination_date` (unbounded when the employee is active), the segment's `effective_to` (unbounded while open), and the clock; day counting is date-granular with both ends inclusive. Days with no covering segment fall back to the state of the employee's `current_work_location_id`, for dates on or after `hire_date`. Three computed fields carry the results: `employee_days_ytd`, the counted days from January 1 of the clock's year through the clock; `employee_days_trailing_90d`, the counted days in the ninety days ending at the clock (the lapse signal); and `wages_ytd_cents`, the sum over employees of each employee's `annual_wage_cents` multiplied by that employee's year-to-date days in the state and divided by 365 — each employee's figure is rounded half up to cents before the per-employee figures are summed, and that order is pinned. `last_recomputed_at` records the clock time of the most recent recompute.

Nexus thresholds are fixed: at least 20 attributable employee-days, or `wages_ytd_cents` of at least 5,000,000 cents (fifty thousand dollars). The computed `threshold_basis` records which are met — `NONE`, `DAYS`, `WAGES`, or `BOTH`. Recomputation drives the cyclic core of the case: from `WATCH`, a basis other than `NONE` moves the case to `THRESHOLD_MET`; from `THRESHOLD_MET`, a basis of `NONE` returns it to `WATCH` (for example when a reversed location change removes days). Either move recomputes the Employer's posture, and a `THRESHOLD_MET` case forces posture of at least `WATCH` per §2.7.

Confirmation is the human gate: a `NexusAnalyst` confirms a case only from `THRESHOLD_MET` (any other state draws `ERR_INVALID_STATE_TRANSITION`), moving it to `CONFIRMED` and stamping `established_date` with the clock; posture recomputes. A `CONFIRMED` case lapses when a recompute finds `employee_days_trailing_90d` at zero and the clock has reached ninety days past `established_date` — the case moves to `LAPSED`, registrations are unaffected (the Employer's `registered_state_count` does not change), and posture recomputes. From `LAPSED`, a recompute that finds renewed trailing-ninety-day activity returns the case to `WATCH`.

De-minimis relief is a director's call. A `TaxDirector` may exempt a case in `WATCH` or `THRESHOLD_MET` (otherwise `ERR_INVALID_STATE_TRANSITION`), supplying an `exempt_reason` that is copied onto the case; the case moves to `EXEMPT` and posture recomputes. Exemption is not a hole in the monitoring net: a later recompute that finds a basis other than `NONE` — renewed activity invalidating the exemption — moves the case from `EXEMPT` back to `WATCH`, again recomputing posture.

Recomputation is available on demand to a `NexusAnalyst`, and the same evaluation also fires as a system cascade from location-change effectuation, location-change reversal, and employee termination, so case states track workforce reality without polling.

### 3.4. Registrations: Submission, Activation, and the Filing Calendar

With nexus established, the team registers with the agency. A `NexusAnalyst` creates a Registration against an `agency_id`, supplying `projected_annual_withholding_cents` (the projected annual withholding in cents, zero or more, which drives the provisional filing frequency) and `expected_employer_version` per §2.8. The new record starts `DRAFT`; its `registration_kind` and `state_code` are copied from the agency. Only one non-`CLOSED` registration may exist per agency — a second is `ERR_DUPLICATE_REGISTRATION` — and creation increments the Employer's `version` by one.

Submission moves the registration to `SUBMITTED` from either `DRAFT` or `REJECTED` (any other state draws `ERR_INVALID_STATE_TRANSITION`), and it is gated on nexus: the NexusCase for the registration's state must be `CONFIRMED`, else `ERR_NEXUS_NOT_CONFIRMED`. Submission stamps `submitted_at` with the clock; resubmission after a rejection additionally clears the stored `rejection_reason`. An agency rejection — recorded by a `NexusAnalyst` with a `rejection_reason` copied onto the record — moves `SUBMITTED` to `REJECTED`, and the submit-reject-resubmit loop can repeat as often as the agency requires.

Activation is the pivotal act: a `NexusAnalyst` activates a `SUBMITTED` registration by supplying the agency-assigned `account_number`. The server stamps `activated_at`, computes the provisional deposit schedule (below), generates the filing obligations for the calendar quarter containing activation, recomputes the Employer's `registered_state_count`, and increments the registration's `version`.

The deposit schedule assigns `filing_frequency` and `deposit_tier`. A `STATE_UI` registration always files `QUARTERLY`. For withholding registrations at activation, the provisional variant reads `projected_annual_withholding_cents`: below 250,000 cents ($2,500) the frequency is `QUARTERLY`; at least 250,000 cents and at most 5,000,000 cents it is `MONTHLY`; above 5,000,000 cents it is `SEMIWEEKLY`. The boundary values land as written — exactly 250,000 cents and exactly 5,000,000 cents are both `MONTHLY`. Activation records `frequency_basis` as `PROVISIONAL`. The `deposit_tier` is `NEXT_DAY` when any withholding-deposit obligation of the registration carries an `amount_due_cents` of at least 1,000,000,000 cents (ten million dollars); otherwise `ACCELERATED` when the frequency is `SEMIWEEKLY`; otherwise `STANDARD`.

Calendar generation produces FilingObligation rows for the full calendar quarter containing activation, even if the quarter is partially elapsed. A `MONTHLY` registration gets one `WITHHOLDING_DEPOSIT` row per calendar month in the quarter, the period being the month, due the 15th of the following month. A `QUARTERLY` registration gets one deposit row for the quarter, due the last day of the month after the quarter ends. A `SEMIWEEKLY` registration gets deposit rows per liability window: the window running Saturday through Tuesday is due the Friday of the same week, and the window running Wednesday through Friday is due the Wednesday of the following week, with windows clipped to the quarter boundary. Every withholding registration additionally gets one `WITHHOLDING_RETURN` per quarter, due the last day of the month after the quarter — the return covers the full quarter by the per-line rule of §3.8 and is never computed by summing deposit rows. A `STATE_UI` registration receives one `UI_RETURN` and one `UI_CONTRIBUTION` per quarter on the same due-date rule; a `LOCAL` registration receives one `LOCAL_RETURN` per quarter, likewise. On every row `period_start` is inclusive and `period_end` is the inclusive last day of the period carried at midnight UTC. A due date landing on a Saturday rolls forward two days to Monday; one landing on a Sunday rolls forward one day to Monday; no holiday calendar is observed. When the deposit tier flips to `NEXT_DAY`, the `due_date` of each non-terminal `WITHHOLDING_DEPOSIT` recomputes to the next business day after its `period_end` under the same weekend roll.

Actual liability eventually displaces projection. A `NexusAnalyst` can trigger schedule recomputation, which applies the lookback variant: `lookback_liability_cents` sums `amount_due_cents` over the registration's `WITHHOLDING_DEPOSIT` and `WITHHOLDING_RETURN` obligations whose `period_end` lies within the trailing four closed calendar quarters and whose status is `DUE`, `LATE`, `FILED`, `CONFIRMED`, or `WAIVED`; the same three thresholds classify that sum into a frequency, and `frequency_basis` becomes `LOOKBACK`. Provisional and lookback bases can legitimately disagree for identical registration data — one reads an input estimate, the other trailing actuals. When the frequency changes, the registration's still-`SCHEDULED` rows move to `WAIVED` (recorded as a frequency change) and a fresh calendar is generated; the deposit tier and any `NEXT_DAY` due dates recompute as above; and the registration's `version` increments.

Closure is a director's decision and requires a settled book. A `TaxDirector` closes an `ACTIVE` registration only when no obligation remains in `SCHEDULED`, `DUE`, or `LATE` and no linked notice is `RECEIVED`, `TRIAGED`, `RESPONSE_IN_PROGRESS`, or `ESCALATED`; otherwise the close is rejected with `ERR_REGISTRATION_NOT_SETTLED`. A successful close stamps `closed_at`, recomputes `registered_state_count`, and lands the registration in terminal `CLOSED`.

### 3.5. Withholding Elections: Reciprocity Exemptions and Courtesy Withholding

Employees across state lines elect how withholding flows through a WithholdingElection. Creation is self-service — an `Employee`-role caller must pass their own `id` as `employee_id`, else `ERR_NOT_RESOURCE_OWNER` — or performed by a `NexusAnalyst` on the employee's behalf. The payload carries `employee_id`, an `election_type` of `RECIPROCITY_EXEMPTION`, `COURTESY_RESIDENT`, or `COURTESY_WORK`, the `work_state_code` where work is performed, an `effective_from`, an optional `effective_to`, an optional `certificate_form_code`, an optional `supersede_existing` flag, and `expected_employee_version` per §2.8. At creation the employee's `resident_state_code` is snapshotted onto the election, `submitted_by_user_id` records the creator, and the election starts `SUBMITTED`. The coverage interval is half-open — `effective_from` inclusive, `effective_to` exclusive — a null `effective_to` is open-ended, and `effective_to` when present must be strictly later than `effective_from` (date sanity per §2.9).

Overlap between elections is rejected rather than truncated. Without `supersede_existing`, a new election whose half-open interval intersects a same-type election of the same employee in `SUBMITTED`, `VALIDATED`, or `ACTIVE` is rejected with `ERR_ELECTION_OVERLAP`; adjacency is allowed, so a new election starting exactly at the prior election's end does not overlap. With `supersede_existing` true, creation instead moves the employee's prior same-type election in `VALIDATED` or `ACTIVE` to `SUPERSEDED` and links it through the new election's `supersedes_election_id`. Either way, creation increments the employee's `version` by one.

Validation is where an analyst checks the election against the tax landscape, and the same work/resident semantics apply at creation and at validation: `work_state_code` must differ from the employee's resident state, and it must equal the state of the employee's current work location; violations draw `ERR_INVALID_REQUEST`. Per-type guards then apply. A `RECIPROCITY_EXEMPTION` election requires an `ACTIVE` ReciprocityAgreement covering the unordered pair of work and resident states and covering `effective_from` — without one, validation fails with `ERR_RECIPROCITY_NOT_AVAILABLE` — and when that agreement declares a `certificate_form_code`, the election's `certificate_form_code` must match it (else `ERR_INVALID_REQUEST`). A `COURTESY_RESIDENT` election requires an `ACTIVE` registration whose agency is a `STATE_WITHHOLDING` agency of the resident state; a `COURTESY_WORK` election requires the same for the work state; each is otherwise rejected with `ERR_REGISTRATION_NOT_ACTIVE`. Validation is allowed only from `SUBMITTED` (else `ERR_INVALID_STATE_TRANSITION`). When `effective_from` lies strictly in the future the election lands `VALIDATED` and the scheduled sweep moves it to `ACTIVE` once the clock reaches that date; when `effective_from` has already been reached, validation lands the election `ACTIVE` directly, with every guard of the `SUBMITTED`-to-`VALIDATED` path applied identically.

The remaining transitions are short. A `NexusAnalyst` may reject a `SUBMITTED` election, copying the supplied `rejection_reason`, moving it to terminal `REJECTED`. Revocation — by the owning `Employee` (ownership enforced, else `ERR_NOT_RESOURCE_OWNER`) or a `NexusAnalyst` — moves a `VALIDATED` or `ACTIVE` election to terminal `REVOKED`. The sweep expires elections: a `VALIDATED` or `ACTIVE` election whose `effective_to` is set and has passed moves to terminal `EXPIRED`. `SUPERSEDED` elections, recorded at creation time as above, are likewise terminal.

### 3.6. Remote Worker Location Changes and Their Reversal

When an employee moves, the employee reports it. Submission is `Employee`-only and owner-scoped: the payload carries `employee_id`, the destination `to_work_location_id`, the `effective_date` of the move (which may lie in the past for retroactive corrections), and a free-text `reason`. The new LocationChange starts `PENDING_REVIEW`; a `from_location_snapshot` captures the employee's current `work_location_id`, `state_code`, and `label` at creation, and `submitted_by_user_id` records the submitter. Only one open change per employee is permitted — an existing change in `PENDING_REVIEW` or `APPROVED` blocks a new one with `ERR_LOCATION_CHANGE_PENDING` — and a change for a `TERMINATED` employee is rejected with `ERR_EMPLOYEE_NOT_ACTIVE`, evaluated in the same tier as the from-state check with the from-state check reporting first on a tie (§2.9).

While pending, a `NexusAnalyst` may edit the change — its `effective_date`, `to_work_location_id`, or `reason` — by carrying `expected_location_change_version` per §2.8; each edit increments the change's `version`.

Approval is the analyst's gate, with a hard separation of duties. Moving `PENDING_REVIEW` to `APPROVED` requires the employee still be `ACTIVE` (else `ERR_EMPLOYEE_NOT_ACTIVE`), the destination location be active (else `ERR_INVALID_REQUEST`), and the approver's `X-User-ID` differ from `submitted_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). Approval records `reviewed_by_user_id` and computes `impact_summary`, naming the states whose nexus cases will recompute — the old state and the new state. Rejection copies the supplied `rejection_reason` and moves the change to terminal `REJECTED`. The owning employee may cancel at any point before effectuation, moving `PENDING_REVIEW` or `APPROVED` to terminal `CANCELLED` (ownership enforced as `ERR_NOT_RESOURCE_OWNER`).

Effectuation happens on the sweep. Once the clock reaches `effective_date`, an `APPROVED` change becomes `EFFECTIVE` — provided the employee is still `ACTIVE` at sweep time; otherwise the change simply waits in `APPROVED` until the employee is active or the change is cancelled. Effectuation is a multi-entity cascade: the employee's `current_work_location_id` becomes `to_work_location_id` and the employee's `version` increments; the employee's `CURRENT` LocalAssignment is truncated at `effective_date` (a zero-length remainder is `SUPERSEDED`) and a new segment is created by automatic resolution (`AUTO_GEOCODE`) covering from `effective_date`; nexus recompute cascades fire for both the old and the new state, and the `WATCH`-to-`THRESHOLD_MET` auto-transitions may fire in either direction; and the Employer's posture recomputes.

Reversal is the compensating action, reserved for a `TaxDirector` and allowed only from `EFFECTIVE`. Reversing restores the employee's `current_work_location_id` from `from_location_snapshot` and increments the employee's `version` again; the segment created by effectuation is `SUPERSEDED` while the previously truncated segment is reinstated — its `effective_to` cleared to null and its status returned to `CURRENT`; nexus recomputes cascade for both states so attribution totals return to their pre-effectuation values; and posture recomputes. `REVERSED` is terminal, as are `REJECTED` and `CANCELLED`.

### 3.7. Unemployment Insurance Rates and Voluntary Contribution Buy-Downs

Each year the state UI agency issues a rate notice; a `UISpecialist` intakes it as a UIRate against an `ACTIVE` `STATE_UI` registration (a registration of any other kind is rejected with `ERR_AGENCY_KIND_MISMATCH`). The payload carries `registration_id`, the `rate_year` the rate applies to, the `experience_rated` flag, the `assigned_rate_bp` printed on the notice (informational only), and the three-year lookback figures `contributions_paid_3yr_cents` and `benefits_charged_3yr_cents` (each zero or more) and `taxable_payroll_3yr_cents` (greater than zero), plus `expected_registration_version` per §2.8. `received_date` stamps the clock at creation, the computed rate fields derive immediately, and intake increments the registration's `version`. Intaking a rate for a registration and `rate_year` that already has one supersedes the existing rate — whether it is `RECEIVED`, `UNDER_REVIEW`, `CONTESTED`, or `EFFECTIVE`, each moves to `SUPERSEDED`; voluntary contributions still `PROPOSED`, `APPROVED`, or `REMITTED` against the superseded rate remain on the books, but applying them is blocked with `ERR_RATE_SUPERSEDED`.

The experience-rate computation runs in a pinned order. For a new-employer account — `experience_rated` false — `reserve_ratio_bp` is null and `final_rate_bp` is simply the agency's `new_employer_rate_bp`, full stop; voluntary contributions against such a rate are rejected with `ERR_VC_NOT_ALLOWED_NEW_EMPLOYER`. Otherwise `reserve_ratio_bp` is ten thousand times the net reserve — contributions paid plus `voluntary_contribution_applied_cents` (the running total of applied voluntary contributions against this rate year, starting at zero) minus benefits charged — divided by `taxable_payroll_3yr_cents`, rounded half up; the ratio may be negative. The ratio selects a bracket: a ratio of at least 1500 yields 50; 1000 through 1499 yields 120; 500 through 999 yields 240; 100 through 499 yields 360; 0 through 99 yields 480; negative 499 through negative 1 yields 600; negative 999 through negative 500 yields 750; and negative 1000 or below yields 900. `final_rate_bp` is the bracket value plus the agency's `solvency_surcharge_bp`, then clamped to never fall below the floor of 50 nor exceed the ceiling of 900. Two variants share this machinery: the standard variant, when no voluntary contribution has been applied, excludes them from the ratio; the buy-down variant adds applied contributions, raising the ratio and potentially dropping the bracket — identical base data then yields a lower `final_rate_bp`.

Rate review is a specialist loop. Review moves `RECEIVED` to `UNDER_REVIEW` and re-opens a `CONTESTED` rate back to `UNDER_REVIEW` (from any other state, `ERR_INVALID_STATE_TRANSITION`). Contesting moves `UNDER_REVIEW` to `CONTESTED` and copies the supplied `contest_reason`. Making the rate effective — again only from `UNDER_REVIEW` — lands it in `EFFECTIVE` and recomputes `amount_due_cents` on the registration's `SCHEDULED` `UI_CONTRIBUTION` obligations whose period starts in `rate_year`, using the new `final_rate_bp`.

Against an `EFFECTIVE` rate, a `UISpecialist` may propose a voluntary contribution — a payment that buys the rate down. The payload names `ui_rate_id`, a `proposed_amount_cents` greater than zero, and a `decision_deadline` that must lie strictly in the future (else `ERR_INVALID_DATE_RANGE`); a rate in any status other than `EFFECTIVE` rejects creation with `ERR_INVALID_STATE_TRANSITION`. Creation computes a three-part projection in pinned order. First `projected_rate_without_vc_bp` is the rate as it stands. Then `projected_rate_with_vc_bp` recomputes the experience rate with `voluntary_contribution_applied_cents` increased by the proposed amount — the proposal itself shifts the reserve ratio that selects the bracket that determines the saving. Projected taxable wages sum, over every employee with at least one attributed day in the registration's state during `rate_year`, the lesser of the employee's `annual_wage_cents` and the agency's `ui_wage_base_cents`. Finally `projected_net_savings_cents` is the rate difference — the without-projection minus the with-projection, in basis points — multiplied by those projected taxable wages and divided by ten thousand, the product rounded half up to cents, minus the proposed contribution. Only a strictly positive projection survives; anything else is rejected with `ERR_NO_NET_SAVINGS`. Projections are pinned at creation — a later approval re-validates nothing. The contribution starts `PROPOSED` with `proposed_by_user_id` recorded.

Approval belongs to the `TaxDirector` and is double-gated: the Employer's `compliance_posture` must not be `DELINQUENT` (else `ERR_COMPANY_POSTURE_DELINQUENT`), and the approver must differ from `proposed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); approval records `approved_by_user_id`. A director may instead decline, moving `PROPOSED` or `APPROVED` to terminal `DECLINED`. Once `APPROVED`, a `UISpecialist` records remittance to the agency — allowed only while the clock has not passed `decision_deadline`; the exact deadline instant is permitted, and any later attempt is `ERR_DEADLINE_PASSED` — stamping `remitted_at` and landing in `REMITTED`. Finally the specialist applies a `REMITTED` contribution, which requires the linked rate still be `EFFECTIVE` (else `ERR_RATE_SUPERSEDED`): the proposed amount is added to the rate's `voluntary_contribution_applied_cents`, `reserve_ratio_bp` and `final_rate_bp` recompute under the buy-down variant, and the registration's open `UI_CONTRIBUTION` obligations — those `SCHEDULED` or `DUE` — whose period year equals `rate_year` have their `amount_due_cents` recomputed. The contribution lands in terminal `APPLIED`.

Only `PROPOSED` rows auto-expire: the sweep moves a `PROPOSED` contribution whose `decision_deadline` has passed to terminal `EXPIRED`. `APPROVED` rows never auto-expire — after approval the remit deadline guard is the sole enforcement, so the deadline boundary stays observable at remit time.

### 3.8. Filing Obligations: From Scheduled to Confirmed, and the Cost of Lateness

FilingObligations are never created by clients; activation and schedule recomputation generate them against their `registration_id`, each with an `obligation_kind` of `WITHHOLDING_RETURN`, `WITHHOLDING_DEPOSIT`, `UI_RETURN`, `UI_CONTRIBUTION`, or `LOCAL_RETURN`, an inclusive `period_start`, an inclusive `period_end` carried at midnight UTC of the last day, a computed `due_date`, a computed `amount_due_cents` (which may be zero), `amount_paid_cents` starting at zero, and `late_days` starting at zero. Every obligation starts `SCHEDULED`.

The amount calculations share the per-line discipline of §2.6. A withholding deposit or return for a state charges each employee with at least one attributed day in that state during the period: the line is `annual_wage_cents` multiplied by the employee's attributed days in the period, divided by 365, multiplied by the agency's `withholding_rate_bp`, divided by ten thousand — each line rounded half up to cents, and `amount_due_cents` the sum of the rounded lines. The quarterly `WITHHOLDING_RETURN` covers the full quarter by this same per-line rule, never by summing that quarter's deposit rows. A `UI_CONTRIBUTION` for a quarter charges each employee with at least one attributed day in the registration's state during that quarter on the taxable slice of wages: year-to-date wages at any boundary are `annual_wage_cents` multiplied by days employed year-to-date at that boundary — counted from the later of `hire_date` and January 1 through the earlier of the boundary and `termination_date` (or the boundary itself when the employee is active) — divided by 365 and rounded half up; the quarter's taxable amount is the lesser of year-to-date wages at quarter end and the `ui_wage_base_cents`, minus the lesser of year-to-date wages at the day before quarter start and the wage base, floored at zero; the line multiplies that taxable amount by the effective rate and divides by ten thousand, rounded half up, and the obligation sums the lines. The effective rate is the registration's `EFFECTIVE` UIRate whose `rate_year` matches the year of the quarter's start, falling back to the agency's `new_employer_rate_bp` when no such rate exists. A `LOCAL_RETURN` for a local agency charges each employee whose covering LocalAssignment during the quarter names that agency as `work_agency_id`: the rate is the agency's `resident_rate_bp` when the employee's `resident_locality_code` equals the agency's `locality_code`, otherwise its `nonresident_rate_bp`; the line is `annual_wage_cents` multiplied by covered days in the quarter, divided by 365, multiplied by the rate, divided by ten thousand, rounded half up, and the obligation sums the lines.

The sweep moves obligations through their early life. Once `period_end` has passed, `SCHEDULED` becomes `DUE`. Once the current date reaches the day after `due_date` while the obligation is still `DUE`, it becomes `LATE`, and `late_days` — calendar days counted from the day after `due_date` to the filing timestamp, or to the clock while unfiled, and zero when filed on or before the due date — recompute daily.

Going late has teeth, provided the obligation carries money. On the transition to `LATE`, when `amount_due_cents` is greater than zero, the system creates an AgencyNotice of type `PENALTY_ASSESSMENT` linked to the obligation and its registration, with `received_date` set to the current date, `response_due_date` set thirty days out, and `penalty_amount_cents` set to the provisional penalty at one late day — the two-percent tier subject to the floor — and the Employer's `open_notice_count`, `outstanding_penalty_cents`, and `compliance_posture` recompute. A zero-amount obligation goes late without penalty and without a notice.

The penalty itself is tiered on `late_days`: one through five late days cost two percent of `amount_due_cents`; six through fifteen cost five percent; more than fifteen cost ten percent. The assessed penalty is the greater of 2,500 cents (twenty-five dollars) and the tiered percentage of the amount due, rounded half up. Provisional and final assessments share one notice: the late cascade posts the penalty computed at one late day, and filing from `LATE` recomputes the penalty at the final `late_days` tier — which can be higher — and updates that same notice's `penalty_amount_cents` in place.

Filing and confirmation close the loop under segregation of duties. A `PayrollComplianceLead` files a `DUE` or `LATE` obligation (any other state draws `ERR_INVALID_STATE_TRANSITION`), optionally supplying `filed_at`, which defaults to the clock and may not lie in the future (else `ERR_INVALID_REQUEST`). Filing sets `amount_paid_cents` equal to `amount_due_cents`, records `filed_by_user_id` from the caller, finalizes `late_days`, and — from `LATE` — triggers the final penalty recompute and Employer counter refresh described above; the obligation lands `FILED`. Confirmation, again a `PayrollComplianceLead`, moves `FILED` to terminal `CONFIRMED` and requires a confirmer whose `X-User-ID` differs from `filed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), recording `confirmed_by_user_id`. One more path ends an obligation: when an abatement decision leaves the linked notice's outstanding penalty at zero while the obligation is `LATE`, the obligation moves to terminal `WAIVED` and Employer counters recompute.

### 3.9. Agency Notices and Penalty Abatement

Agency mail arrives as AgencyNotices, recorded by a `PayrollComplianceLead` — alongside the notices the system creates itself in the late cascade. Intake carries a `notice_type` of `PENALTY_ASSESSMENT`, `RATE_NOTICE`, `MISSING_RETURN`, `ACCOUNT_INQUIRY`, or `AUDIT`; the `received_date`, which anchors the abatement window; a `response_due_date` no earlier than `received_date` (date sanity per §2.9); an optional `registration_id` and an optional `filing_obligation_id` — at least one of the two links is required, else `ERR_INVALID_REQUEST`; and a `penalty_amount_cents` defaulting to zero. The computed `severity` is `HIGH` when the notice is an `AUDIT` or its penalty reaches at least 500,000 cents (five thousand dollars), `MEDIUM` when the penalty reaches at least 50,000 cents (five hundred dollars), and `LOW` otherwise. A notice starts `RECEIVED`, and its creation recomputes the Employer's counters and posture.

Working a notice follows a short ladder. Triage moves `RECEIVED` to `TRIAGED`. Drafting an abatement request that references the notice moves it — from `RECEIVED` or `TRIAGED` alike — to `RESPONSE_IN_PROGRESS`. Escalation moves `TRIAGED` or `RESPONSE_IN_PROGRESS` to `ESCALATED` and recomputes posture, which an open `ESCALATED` notice drives to `DELINQUENT` per §2.7. Resolution — a `PayrollComplianceLead` supplying `resolution_notes`, copied onto the notice — moves `TRIAGED`, `RESPONSE_IN_PROGRESS`, or `ESCALATED` to `RESOLVED`, but only while no linked AbatementRequest remains in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`; a pending abatement blocks resolution with `ERR_ABATEMENT_PENDING`. Employer counters recompute on resolution. Finally a `TaxDirector` closes a `RESOLVED` notice, moving it to terminal `CLOSED` with one last counter refresh.

Penalty abatement is the negotiation track, and it begins with eligibility. A `PayrollComplianceLead` drafts an AbatementRequest against a `PENALTY_ASSESSMENT` notice that has not reached a terminal state, supplying `agency_notice_id`, an `abatement_type` of `FIRST_TIME`, `REASONABLE_CAUSE`, or `STATUTORY`, a `requested_amount_cents` greater than zero and no more than the notice's outstanding penalty — `penalty_amount_cents` minus `abated_amount_cents` — with an excess rejected as `ERR_AMOUNT_EXCEEDS_PENALTY`, and a `reason` justification (which for `REASONABLE_CAUSE` must run at least twenty characters). Drafting computes two fields. `prior_penalty_count_3yr` counts `PENALTY_ASSESSMENT` notices whose `received_date` falls within the three years ending strictly before this notice's `received_date` and whose outstanding penalty is positive, examined in ascending `received_date` then `created_at` order. `eligible_amount_cents` then depends on type: `FIRST_TIME` yields the full outstanding amount when that count is zero and nothing otherwise; `REASONABLE_CAUSE` yields the full outstanding amount; `STATUTORY` yields half the outstanding amount rounded down. The draft records `prepared_by_user_id` and starts in `DRAFT`.

Submission is windowed: a `PayrollComplianceLead` submits a `DRAFT` request while the current date is no later than sixty days after the notice's `received_date` — day sixty is allowed, day sixty-one is rejected with `ERR_ABATEMENT_WINDOW_CLOSED` — and only while `eligible_amount_cents` is greater than zero, else `ERR_ABATEMENT_NOT_ELIGIBLE` (a `FIRST_TIME` request with prior penalties in the three-year lookback is the canonical ineligible case). Submission stamps `submitted_at`.

Review and decision belong to the `TaxDirector` under segregation of duties. Opening review moves `SUBMITTED` to `UNDER_REVIEW` with a reviewer different from `prepared_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), recording `reviewed_by_user_id`. The decision payload carries `decision` and a conditional `granted_amount_cents`. Granting pins the granted amount to `eligible_amount_cents`, so the `granted_amount_cents` input must be omitted — supplying it draws `ERR_INVALID_REQUEST`. A partial grant requires `granted_amount_cents` of at least one and strictly less than `eligible_amount_cents`, anything else drawing `ERR_INVALID_REQUEST`. Denial takes no `granted_amount_cents` (again `ERR_INVALID_REQUEST`) and grants zero. All three decisions stamp `decided_at` and land in the matching terminal state — `GRANTED`, `PARTIALLY_GRANTED`, or `DENIED`. Granted amounts, full or partial, are added to the notice's `abated_amount_cents`; when the notice links a filing obligation and the abatement leaves the notice's outstanding penalty at zero while that obligation is `LATE`, the obligation moves to `WAIVED` per §3.8; and the Employer's counters recompute. Before review, the preparer may withdraw: a `PayrollComplianceLead` moves a `DRAFT` or `SUBMITTED` request to terminal `WITHDRAWN`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, edits, filings, decisions — return a `200 OK` status code. All endpoints are mounted under the `/etax` prefix; request payloads, computed fields, and side effects are defined by the narratives of §2 and §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/etax/_clock/set_current_utc` | Set the logical clock and run the scheduled sweep | TaxDirector |
| POST | `/etax/employers` | Create the singleton Employer | TaxDirector |
| GET | `/etax/employers/{id}` | Get the Employer, including computed posture and counters | Any authenticated role |
| POST | `/etax/tax-agencies` | Create a catalog TaxAgency | TaxDirector |
| GET | `/etax/tax-agencies` | List TaxAgencies | Any authenticated role |
| GET | `/etax/tax-agencies/{id}` | Get a TaxAgency | Any authenticated role |
| POST | `/etax/reciprocity-agreements` | Create a ReciprocityAgreement (closed-interval overlap per pair rejected) | TaxDirector |
| GET | `/etax/reciprocity-agreements` | List ReciprocityAgreements | Any authenticated role |
| GET | `/etax/reciprocity-agreements/{id}` | Get a ReciprocityAgreement | Any authenticated role |
| POST | `/etax/work-locations` | Create a WorkLocation | NexusAnalyst |
| GET | `/etax/work-locations` | List WorkLocations | Any authenticated role |
| GET | `/etax/work-locations/{id}` | Get a WorkLocation | Any authenticated role |
| POST | `/etax/employees` | Create an Employee; auto-creates the initial LocalAssignment | NexusAnalyst |
| GET | `/etax/employees` | List Employees | Any authenticated role |
| GET | `/etax/employees/{id}` | Get an Employee | Any authenticated role |
| POST | `/etax/employees/{id}/terminate` | Terminate an Employee (`ACTIVE` to `TERMINATED`) | NexusAnalyst |
| POST | `/etax/nexus-cases` | Open a NexusCase for a state (initial `WATCH` plus immediate recompute) | NexusAnalyst |
| GET | `/etax/nexus-cases` | List NexusCases | Any authenticated role |
| GET | `/etax/nexus-cases/{id}` | Get a NexusCase | Any authenticated role |
| POST | `/etax/nexus-cases/{id}/recompute` | Recompute attribution and apply auto-transitions | NexusAnalyst |
| POST | `/etax/nexus-cases/{id}/confirm` | Confirm nexus (`THRESHOLD_MET` to `CONFIRMED`) | NexusAnalyst |
| POST | `/etax/nexus-cases/{id}/exempt` | Grant a de-minimis exemption | TaxDirector |
| POST | `/etax/registrations` | Create a Registration in `DRAFT` (OCC on Employer version) | NexusAnalyst |
| GET | `/etax/registrations` | List Registrations | Any authenticated role |
| GET | `/etax/registrations/{id}` | Get a Registration | Any authenticated role |
| POST | `/etax/registrations/{id}/submit` | Submit to the agency; requires `CONFIRMED` nexus | NexusAnalyst |
| POST | `/etax/registrations/{id}/reject` | Record an agency rejection | NexusAnalyst |
| POST | `/etax/registrations/{id}/activate` | Activate with the agency account number; generates the quarter's obligations | NexusAnalyst |
| POST | `/etax/registrations/{id}/close` | Close an `ACTIVE` registration once settled | TaxDirector |
| POST | `/etax/registrations/{id}/recompute_schedule` | Recompute frequency via lookback and regenerate future obligations | NexusAnalyst |
| POST | `/etax/withholding-elections` | Create a WithholdingElection (OCC on Employee version; optional supersede) | Employee, NexusAnalyst |
| GET | `/etax/withholding-elections` | List WithholdingElections | Any authenticated role |
| GET | `/etax/withholding-elections/{id}` | Get a WithholdingElection | Any authenticated role |
| POST | `/etax/withholding-elections/{id}/validate` | Validate a `SUBMITTED` election; lands `VALIDATED` or `ACTIVE` | NexusAnalyst |
| POST | `/etax/withholding-elections/{id}/reject` | Reject a `SUBMITTED` election | NexusAnalyst |
| POST | `/etax/withholding-elections/{id}/revoke` | Revoke a `VALIDATED` or `ACTIVE` election | Employee, NexusAnalyst |
| POST | `/etax/local-assignments/resolve` | Re-run automatic jurisdiction resolution from a date | NexusAnalyst |
| POST | `/etax/local-assignments/override` | Manual jurisdiction override (OCC on Employee version) | TaxDirector |
| GET | `/etax/local-assignments` | List LocalAssignments | Any authenticated role |
| GET | `/etax/local-assignments/{id}` | Get a LocalAssignment | Any authenticated role |
| POST | `/etax/ui-rates` | Intake a UI rate notice (OCC on Registration version) | UISpecialist |
| GET | `/etax/ui-rates` | List UIRates | Any authenticated role |
| GET | `/etax/ui-rates/{id}` | Get a UIRate | Any authenticated role |
| POST | `/etax/ui-rates/{id}/review` | Begin or reopen review | UISpecialist |
| POST | `/etax/ui-rates/{id}/contest` | Contest the rate | UISpecialist |
| POST | `/etax/ui-rates/{id}/make_effective` | Make the reviewed rate `EFFECTIVE` | UISpecialist |
| POST | `/etax/voluntary-contributions` | Propose a voluntary contribution (buy-down projection) | UISpecialist |
| GET | `/etax/voluntary-contributions` | List VoluntaryContributions | Any authenticated role |
| GET | `/etax/voluntary-contributions/{id}` | Get a VoluntaryContribution | Any authenticated role |
| POST | `/etax/voluntary-contributions/{id}/approve` | Approve a `PROPOSED` contribution (posture gate and SoD) | TaxDirector |
| POST | `/etax/voluntary-contributions/{id}/decline` | Decline a `PROPOSED` or `APPROVED` contribution | TaxDirector |
| POST | `/etax/voluntary-contributions/{id}/remit` | Record remittance to the agency (deadline-guarded) | UISpecialist |
| POST | `/etax/voluntary-contributions/{id}/apply` | Apply a `REMITTED` contribution to the rate | UISpecialist |
| POST | `/etax/location-changes` | Employee submits a location change | Employee |
| GET | `/etax/location-changes` | List LocationChanges | Any authenticated role |
| GET | `/etax/location-changes/{id}` | Get a LocationChange | Any authenticated role |
| PATCH | `/etax/location-changes/{id}` | Edit a `PENDING_REVIEW` change (OCC on its version) | NexusAnalyst |
| POST | `/etax/location-changes/{id}/approve` | Approve a pending change (SoD versus submitter) | NexusAnalyst |
| POST | `/etax/location-changes/{id}/reject` | Reject a pending change | NexusAnalyst |
| POST | `/etax/location-changes/{id}/cancel` | Employee-owner cancels a pending or approved change | Employee |
| POST | `/etax/location-changes/{id}/reverse` | Reverse an `EFFECTIVE` change (compensating action) | TaxDirector |
| GET | `/etax/filing-obligations` | List FilingObligations | Any authenticated role |
| GET | `/etax/filing-obligations/{id}` | Get a FilingObligation | Any authenticated role |
| POST | `/etax/filing-obligations/{id}/file` | File and pay a `DUE` or `LATE` obligation | PayrollComplianceLead |
| POST | `/etax/filing-obligations/{id}/confirm` | Confirm agency acceptance (SoD versus filer) | PayrollComplianceLead |
| POST | `/etax/agency-notices` | Record an inbound agency notice | PayrollComplianceLead |
| GET | `/etax/agency-notices` | List AgencyNotices | Any authenticated role |
| GET | `/etax/agency-notices/{id}` | Get an AgencyNotice | Any authenticated role |
| POST | `/etax/agency-notices/{id}/triage` | Triage a received notice | PayrollComplianceLead |
| POST | `/etax/agency-notices/{id}/escalate` | Escalate a notice (forces `DELINQUENT` posture) | PayrollComplianceLead |
| POST | `/etax/agency-notices/{id}/resolve` | Resolve a notice (blocked by non-terminal abatement) | PayrollComplianceLead |
| POST | `/etax/agency-notices/{id}/close` | Close a resolved notice | TaxDirector |
| POST | `/etax/abatement-requests` | Draft an abatement request against a penalty notice | PayrollComplianceLead |
| GET | `/etax/abatement-requests` | List AbatementRequests | Any authenticated role |
| GET | `/etax/abatement-requests/{id}` | Get an AbatementRequest | Any authenticated role |
| POST | `/etax/abatement-requests/{id}/submit` | Submit a draft abatement (sixty-day window and eligibility guards) | PayrollComplianceLead |
| POST | `/etax/abatement-requests/{id}/review` | Open review (SoD versus preparer) | TaxDirector |
| POST | `/etax/abatement-requests/{id}/decide` | Decide: grant, partially grant, or deny | TaxDirector |
| POST | `/etax/abatement-requests/{id}/withdraw` | Withdraw a draft or submitted abatement | PayrollComplianceLead |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EMPLOYER_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_AGENCY` | 409 Conflict |
| `ERR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_NEXUS_CASE` | 409 Conflict |
| `ERR_NEXUS_NOT_CONFIRMED` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_REGISTRATION_NOT_SETTLED` | 409 Conflict |
| `ERR_ELECTION_OVERLAP` | 409 Conflict |
| `ERR_RECIPROCITY_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGENCY_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VC_NOT_ALLOWED_NEW_EMPLOYER` | 422 Unprocessable Entity |
| `ERR_NO_NET_SAVINGS` | 422 Unprocessable Entity |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_RATE_SUPERSEDED` | 409 Conflict |
| `ERR_LOCATION_CHANGE_PENDING` | 409 Conflict |
| `ERR_ABATEMENT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ABATEMENT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ABATEMENT_PENDING` | 409 Conflict |
| `ERR_AMOUNT_EXCEEDS_PENALTY` | 422 Unprocessable Entity |
| `ERR_COMPANY_POSTURE_DELINQUENT` | 409 Conflict |

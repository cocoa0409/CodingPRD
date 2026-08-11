# Adult Family Home Residential Care API — Product Requirements Document

## 1. Introduction

Adult family homes occupy a particular niche in the long-term care landscape: state-licensed residences of two to six beds in which a small operator household delivers round-the-clock personal care, nursing-delegated tasks, and medication assistance to a compact census of adults. The regulatory burden on these homes is disproportionate to their size. Every admission must be justified by a current assessment and a properly certified bed, every overnight hour must satisfy staffing-ratio rules, every state-reportable incident carries a twenty-four-hour filing deadline, and every billing cycle must price two very different payer populations — private-pay residents and Medicaid-funded residents — off the same occupancy calendar. Operators who get any of this wrong face citations, suspension of their license, or repayment demands.

This document specifies an API that acts as the system of record for one or more such homes. It governs the full arc of operation: registering and licensing a home; managing beds, caregivers, and shifts; moving a prospective resident through assessment, admission, daily care, and discharge; logging medication administrations and assistance with activities of daily living against verified shift coverage; filing and adjudicating incidents and state compliance cases; and producing auditable invoices under both private-pay and Medicaid rate schedules. Two design commitments shape everything that follows. First, consistency is immediate and cascading: a single decision — a home closure, a discharge, a substantiated citation — propagates through beds, admissions, medication orders, shifts, and derived counters in one step, and every propagation is recorded. Second, all time in the system is logical rather than wall-clock, so surveys, audits, deadline checks, and billing reconstructions replay deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Provider`, `Nurse`, and `CaregiverRole`. A request whose `X-User-Role` header is missing or names no declared role — or whose `X-User-ID` is missing or unresolvable where the role requires it — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `Provider` is the licensed adult-family-home operator or administrator and runs the home, its billing, its admission decisions, and its compliance responses. When `X-User-Role` is `Provider`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by` on an admission decision — but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `Nurse`: `X-User-ID` is an opaque identifier of the assessing nurse, recorded where a workflow calls for it but never matched against a stored entity's `id`. When `X-User-Role` is `CaregiverRole`, `X-User-ID` is the `id` of the acting `Caregiver`; ownership checks on any resource that references a caregiver compare the resource's foreign-key field to `X-User-ID`, and a missing or unknown caregiver identifier fails authentication.

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

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every timestamp this document calls "now" comes from a server-maintained logical clock, never from wall-clock time. Before the clock is ever set, it reads exactly 2026-05-01T00:00:00Z, and the server never falls back to wall-clock time. A `Provider`-only test-driving capability, `POST /api/_clock/set_current_utc`, advances the clock to a supplied `to_iso8601` instant and returns the new value as `current_utc`. All system-stamped fields — `assessed_at`, `reported_at`, `decided_at`, `admitted_at`, `discharged_at`, `received_at`, and the fourteen-day `correction_plan_due_at` — read this clock, and so do the late-fee evaluation at invoice issue, the twenty-four-hour incident reporting deadline, and every day-boundary computation. Every timestamp the API emits — the clock-stamped and computed fields above, the clock endpoint's `current_utc`, `created_at` and `updated_at`, and echoes of client-supplied timestamps such as `occurred_at`, `administered_at`, `performed_at`, a shift's `start_at` and `end_at`, and `correction_plan_submitted_at` — is rendered as an ISO 8601 UTC string with exactly three fractional digits and a trailing `Z`; the clock's initial value, for example, renders as `2026-05-01T00:00:00.000Z`. The API as a whole is mounted under `/api`.

### 2.5. Common Resource Properties

Primary resources carry a standard system-managed quartet of fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a counter that increments by one on every mutation, including mutations caused by cascades rather than direct client writes.

Four record types are append-only exceptions to this convention: a `MedicationLog`, an `ADLLog`, a `Payment`, and a `DischargeRecord` each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these four resources.

### 2.6. Home-Local Time, Day Boundaries, and Half-Open Intervals

Each home declares an IANA `timezone` — defaulting to `America/Los_Angeles` when omitted — that defines its local day boundary. Billing occupancy days, medication windows, and staffing windows are all evaluated in home-local time. For staffing purposes the day window runs from 06:00 to 22:00 local and the overnight window runs from 22:00 to 06:00 local.

Throughout the system, time intervals are half-open: the start instant is included and the end instant is excluded. Two shifts that merely touch at an endpoint do not overlap, and they never both cover the shared boundary instant — the incoming interval owns it. A shift's `end_at` must be strictly after its `start_at`, and a single shift's duration may not exceed sixteen hours. Windows, deadlines, and rolling caps are compared at minute granularity on the logical clock.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names a non-optional expectation field in its request body:

- A `POST /api/admissions` request must carry `expected_bed_version` equal to the target bed's current `version`. If the bed's version has advanced since the client last read it — another writer may have taken the bed out of service, or a competing admission may have held it — the client's view of the bed is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A `POST /api/shifts` request must carry `expected_caregiver_version` equal to the caregiver's current `version`. A credential or status change (for example a suspension) may have landed since the client last observed the caregiver, so the stale write is refused with `ERR_STALE_VERSION` (HTTP 412) rather than silently re-validated against old data.
- A `POST /api/residents/{id}/invoices/generate` request must carry `expected_resident_version` equal to the resident's current `version`. A payer-type change or a discharge landing in between changes which rate schedule and which occupancy window apply, so the stale generation is refused with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above take no version-expectation field at all.

### 2.8. Money, Rates, and Rounding

All monetary values in the system are integer counts of cents; no value is ever represented with fractional cents. Invoice line amounts are each rounded to whole cents first, and the invoice `subtotal_cents` is the sum of those already-rounded line amounts — round per line, then sum. A final daily Medicaid rate is rounded half-up to whole cents, with its nursing component truncated to whole cents before being summed into the rate. The late fee is rounded half-up before being clamped to a floor of 2500 cents and a ceiling of 15000 cents.

### 2.9. The Validation Pipeline

Every request passes through a fixed, globally ordered validation pipeline, and the first failing check determines the error returned. The order is:

1. Authentication — headers per §2.1; failure yields `ERR_UNAUTHENTICATED`.
2. Authorization — the role is permitted on the endpoint; failure yields `ERR_UNAUTHORIZED`.
3. Existence — every identifier referenced in the path and in the body exists, validated left-to-right (§2.10); failure yields `ERR_NOT_FOUND`.
4. Stale-version rejection on the three OCC-guarded writes (§2.7); failure yields `ERR_STALE_VERSION`.
5. State-machine legality — the target resource is in a from-state that permits the transition and is not terminally locked; failure yields `ERR_INVALID_STATE`. This code is also the generic fallback when no more specific error applies.
6. Segregation of duties on admission approval; failure yields `ERR_SELF_APPROVAL`.
7. The critical-incident block on resident discharge; failure yields `ERR_BLOCKED_BY_INCIDENT`.
8. The twenty-four-hour reporting deadline on opening a compliance case; failure yields `ERR_LATE_REPORT`.
9. The medication window and duplicate-dose checks on logging an administration; failure yields `ERR_OUTSIDE_MED_WINDOW`.
10. Caregiver shift overlap and the rolling sixteen-hour cap on scheduling a shift; failure yields `ERR_SHIFT_CONFLICT`.
11. Forward staffing-ratio adequacy on scheduling or cancelling a shift; failure yields `ERR_UNDERSTAFFED`.
12. Medicaid bed certification on admission creation; failure yields `ERR_BED_NOT_CERTIFIED`.
13. Discharge notice sufficiency; failure yields `ERR_INSUFFICIENT_NOTICE`.
14. Currency of the pinned assessment at admission approval; failure yields `ERR_ASSESSMENT_SUPERSEDED`.
15. On-shift verification of the caregiver named on a care log; failure yields `ERR_CAREGIVER_NOT_ON_SHIFT`.
16. Order still active when logging an administration; failure yields `ERR_ORDER_DISCONTINUED`.
17. Rate-schedule availability for every occupied day of a billing window; failure yields `ERR_RATE_NOT_FOUND`.
18. Payment amount within bounds; failure yields `ERR_OVERPAYMENT`.
19. Licensed capacity at admission completion; failure yields `ERR_CAPACITY_EXCEEDED`.
20. Correction-plan timeliness when closing a substantiated case; failure yields `ERR_LATE_CORRECTION_PLAN`.
21. The occupied-bed guard on taking a bed out of service; failure yields `ERR_BED_OCCUPIED`.
22. Structural payload validity — a missing required field, a wrong type, an enum outside its declared set, or an inverted range such as a `period_end` not after its `period_start` or an `end_at` not after its `start_at`; failure yields `ERR_INVALID_REQUEST`.

Because the pipeline is ordered, relative priority matters wherever several checks guard one endpoint. Admission approval evaluates state legality, then segregation of duties, then the pinned-assessment check. Logging a medication administration evaluates state legality, then the window check, then on-shift verification, then the order-active check. Scheduling a shift evaluates the stale-version check, then state legality, then the conflict checks, then the staffing-ratio check. Discharge evaluates state legality, then the critical-incident block, then the notice rule.

### 2.10. Nested Resource Retrieval

Requests that target nested resources are validated left-to-right along the path: the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier or body reference is examined. A request for a bed listing under a non-existent home identifier, for example, fails on the home identifier before any bed is ever looked up, and the same left-to-right discipline applies to identifiers referenced in request bodies after the path has resolved.

### 2.11. Derived Counters and Hierarchical Consistency

Two home-level counters are maintained by the server rather than accepted as input. `current_census` counts the home's residents in `ADMITTED` status and is recomputed on every admission completion and every discharge. `open_case_count` counts the home's compliance cases in `OPEN` or `SUBSTANTIATED` status and is recomputed on every compliance-case status change. Each recomputation is itself a mutation of the home record: `updated_at` is refreshed and `version` increments by one.

More broadly, when a parent's transition renders children non-operational — a closure against beds and shifts, a discharge against a bed and medication orders, a substantiated abuse citation against the home itself — the server performs the cascade in the same step as the triggering write, without requiring a separate client request per resource. Every cascaded mutation refreshes the child's `updated_at` and increments its `version`, and every such chain is spelled out in the workflow narratives of §3.

## 3. Business Logic & Workflows

### 3.1. Establishing the Home: Registration, Licensing, and Closure

A `Provider` registers a home with its state-issued `license_number` (unique across all homes), an operating `name`, the `licensed_bed_capacity` the state license permits — between 2 and 6 beds inclusive — and an optional `timezone`. A new home begins `PROVISIONAL`. Beds are then added to the home, each with a human `label` such as Room 1-A (unique within the home) and an optional `medicaid_certified` flag that defaults to false; every bed begins `AVAILABLE`. Caregivers are registered with a `full_name`, a state `credential_id` (an HCA or NAC number, unique across homes), and an optional `awake_overnight_qualified` flag that defaults to false; every caregiver begins `ACTIVE`.

Licensing — the `PROVISIONAL` → `LICENSED` transition performed by a `Provider` — requires the home to have at least one bed that is not `OUT_OF_SERVICE` and at least one `ACTIVE` caregiver, and it bumps the home's `version`. A `LICENSED` home may be suspended at any time (`LICENSED` → `SUSPENDED`), and suspension also arrives automatically through the compliance cascade described in §3.6; while a home is `SUSPENDED`, new admission approvals are blocked. Reinstatement moves `SUSPENDED` → `LICENSED` and is permitted only when the home's `open_case_count` is zero — no compliance case in `OPEN` or `SUBSTANTIATED`.

Closure is terminal (`CLOSED`), is reachable from either `LICENSED` or `SUSPENDED`, and requires a `current_census` of zero — no `ADMITTED` residents remain. Closing a home cascades in the same step: every bed not already `OUT_OF_SERVICE` goes `OUT_OF_SERVICE`; where such a bed was `HELD`, its linked `PENDING` admission is forced to `REJECTED` with the system recorded as the decider, and the admission's usual bed-release compensation is suppressed because the bed is leaving service rather than returning to availability — a depth-three chain from home to bed to admission. All `SCHEDULED` shifts go `CANCELLED`, and staffing-ratio revalidation is skipped for closure cascades.

Bed service control works in both directions. Taking a bed out of service moves `AVAILABLE` → `OUT_OF_SERVICE`, or `HELD` → `OUT_OF_SERVICE` with the forced rejection of its pending admission applied first, exactly as in the closure cascade. An `OCCUPIED` bed can never leave service — the attempt is rejected with `ERR_BED_OCCUPIED` — until its resident has been discharged. Returning a bed (`OUT_OF_SERVICE` → `AVAILABLE`) requires the home to be `PROVISIONAL` or `LICENSED`.

Caregiver standing follows its own small lifecycle at the provider's discretion: `ACTIVE` → `SUSPENDED` → `ACTIVE`, and a `SUSPENDED` caregiver may not be newly scheduled. Termination — from `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` — immediately cancels all of the caregiver's future `SCHEDULED` shifts, meaning those whose `start_at` lies after the current logical time.

### 3.2. Prospective Residents, Assessment, and the Care Plan

Registration brings a prospective resident into a home with a `full_name`, a `date_of_birth` given as an ISO 8601 date, and a `payer_type` of `PRIVATE_PAY` or `MEDICAID` — the funding source that later drives rate-schedule selection and bed-certification checks. The resident begins `PROSPECT`, with `admitted_at` and `discharged_at` null until the corresponding transitions occur.

A `Nurse` then records an assessment: `nursing_hours_per_week` (the assessed direct nursing hours needed per week, from 0 to 40 inclusive), an `adl_dependency_score` (the count, from 0 to 6, of the six activities of daily living with which the resident needs full assistance), and a structured `care_plan` object covering diet, mobility, medication assistance level, and ADL assist flags. The assessment begins `DRAFT`, and `assessed_at` is stamped from the logical clock at record time.

Finalization by a `Nurse` moves the assessment `DRAFT` → `FINALIZED` and requires the resident to be `PROSPECT`, `APPLICANT`, or `ADMITTED` with all assessed fields complete. Finalization has three effects beyond the assessment itself. If the resident was `PROSPECT`, they are promoted to `APPLICANT` — the first finalized assessment is what makes a prospect an applicant. Any previously `FINALIZED` assessment for the same resident becomes `SUPERSEDED`, a terminal state, in a version-pinned replacement loop that supports cyclic re-assessment. And a `PENDING` admission that pinned the now-superseded assessment is left untouched at this moment — the pin references the assessment's `id`, which remains on record — but its later approval will be rejected with `ERR_ASSESSMENT_SUPERSEDED` (§3.3).

Withdrawal lets an `APPLICANT` return to `PROSPECT` through a `Provider` action, permitted only when no admission in `PENDING` or `APPROVED` exists for the resident. Withdrawal does not disturb the resident's assessments: anything `FINALIZED` remains `FINALIZED`.

### 3.3. The Admission Pipeline: Hold, Decision, and Move-In

A `Provider` opens an admission by naming `resident_id`, `bed_id`, `assessment_id`, and an `expected_admission_date`, together with the OCC field `expected_bed_version` described in §2.7. The pinned assessment must be a `FINALIZED` assessment belonging to that resident — it is what authorizes the admission. Creation is refused with `ERR_BED_NOT_CERTIFIED` when a `MEDICAID` resident references a bed whose `medicaid_certified` flag is false. Creation further requires the bed to be `AVAILABLE` and the bed's home to be `PROVISIONAL` or `LICENSED`. A successful creation moves the bed `AVAILABLE` → `HELD`, incrementing the bed's `version`, and the admission begins `PENDING`.

Approval — a `Provider` decision moving `PENDING` → `APPROVED` — enforces its checks in the pipeline order of §2.9. The admission must actually be `PENDING`, else `ERR_INVALID_STATE`. The approving operator's `X-User-ID` must differ from the identifier recorded as the admission's creator — segregation of duties, so the requester can never approve their own admission — else `ERR_SELF_APPROVAL`. The home must be `LICENSED`; a `SUSPENDED` home blocks all new admission approvals. The pinned assessment must still be `FINALIZED`, else `ERR_ASSESSMENT_SUPERSEDED`. And the bed must be `HELD` by this admission. A successful approval stamps `decided_by` from the acting `X-User-ID` and `decided_at` from the logical clock.

Rejection moves `PENDING` → `REJECTED`, stamps the same two decision fields, and releases the hold: the bed returns `HELD` → `AVAILABLE` as compensation. Cancellation abandons an approved move-in, `APPROVED` → `CANCELLED`, with the same bed-release compensation. `REJECTED`, `CANCELLED`, and `COMPLETED` are all terminal.

Completion — `APPROVED` → `COMPLETED` — is the physical move-in. It requires the home `LICENSED` and the home's `current_census` strictly below its `licensed_bed_capacity`; a home already at capacity rejects the completion with `ERR_CAPACITY_EXCEEDED`. A delinquent prior final invoice does not block completion — no such check is applied at move-in. Completion chains three mutations in one step: the resident moves `APPLICANT` → `ADMITTED` with `admitted_at` stamped from the clock, the bed moves `HELD` → `OCCUPIED`, and the home's `current_census` is recomputed. Every mutated resource's `version` increments.

Bed holds interact with service control in both directions, as §3.1 describes: when a `HELD` bed is taken out of service, the linked `PENDING` admission is auto-rejected first with the system recorded as `decided_by`, and the admission's bed-release compensation is suppressed because the bed is leaving service rather than returning to availability.

### 3.4. Daily Care: Medication Orders, Administration Windows, and ADL Logs

A `Nurse` places a medication order for an `ADMITTED` resident with a `drug_name`, a `dose` giving dose and route (for example, 5mg oral), and `schedule_times` — between one and six local wall-clock administration times per day, such as 08:00 and 20:00, from which the medication windows derive. Orders begin `ACTIVE`. A `Nurse` may discontinue an order, moving `ACTIVE` → `DISCONTINUED`, while the resident is not `DISCHARGED`; discharge discontinues all remaining `ACTIVE` orders automatically (§3.8). `DISCONTINUED` is terminal, and any attempt to log an administration against a discontinued order is rejected with `ERR_ORDER_DISCONTINUED`.

Logging an administration — a `Nurse` or `CaregiverRole` action — records `resident_id`, `order_id`, `administered_at`, an `outcome` of `GIVEN`, `REFUSED`, `HELD`, or `SELF_ADMINISTERED`, the acting `caregiver_id`, and an optional free-text `note` that becomes required whenever the outcome is `REFUSED` or `HELD`. Each scheduled time T on a local date opens a half-open window running from sixty minutes before T — inclusive — to sixty minutes after T — exclusive: an administration exactly at the window's lower edge is inside, while one exactly at the upper edge is outside. The `administered_at` instant must fall inside at least one open window of the order, and no earlier log with outcome `GIVEN` or `SELF_ADMINISTERED` may already exist in the same window for the same order — that is duplicate-dose detection. Outcomes `REFUSED` and `HELD` do not consume a window, so a later `GIVEN` inside the same window remains permitted. A window miss or a duplicate dose is rejected with `ERR_OUTSIDE_MED_WINDOW`. Separately, the caregiver named on the log must hold a `SCHEDULED` shift covering `administered_at`, else the log is rejected with `ERR_CAREGIVER_NOT_ON_SHIFT`. On this endpoint the window check is evaluated before the on-shift verification, and both precede the order-active check, per the pipeline in §2.9.

ADL assistance is logged by a `Nurse` or `CaregiverRole` with `resident_id`, an `adl_type` of `BATHING`, `DRESSING`, `GROOMING`, `TOILETING`, `TRANSFERRING`, or `EATING`, an `assistance_level` of `INDEPENDENT`, `SUPERVISION`, `PARTIAL`, or `FULL`, a `performed_at` timestamp, and a `caregiver_id`. The same on-shift rule applies: the named caregiver must hold a `SCHEDULED` shift covering `performed_at`, else `ERR_CAREGIVER_NOT_ON_SHIFT`. Both log types are append-only records per §2.5.

### 3.5. Staffing the Home: Shifts, Ratios, and Overnight Coverage

A `Provider` schedules a shift with `home_id`, `caregiver_id`, `start_at`, `end_at`, an optional `overnight_mode`, and the OCC field `expected_caregiver_version` described in §2.7; creating the shift increments the caregiver's `version`. The caregiver must be `ACTIVE` — a `SUSPENDED` caregiver may not be newly scheduled — and the temporal bounds of §2.6 apply: `end_at` strictly after `start_at`, duration of at most sixteen hours. A shift begins `SCHEDULED`.

Two personal-capacity rules guard the caregiver, evaluated before the home-level ratio check. First, strict half-open overlap: the new shift conflicts with an existing `SCHEDULED` shift of the same caregiver when the new shift starts before the existing one ends and the existing one starts before the new one ends. Back-to-back shifts, where one ends exactly when the other begins, do not conflict. Second, aggregate capacity: the caregiver's total `SCHEDULED` hours within any rolling twenty-four-hour window must not exceed sixteen — the window slides in one-minute steps, so touching intervals still accumulate toward the cap. Either violation is rejected with `ERR_SHIFT_CONFLICT`.

Home-level coverage is evaluated over atomic half-open segments cut at every shift boundary across the union of the home's `SCHEDULED` shifts, using the home's `current_census` as the census figure. A day segment — one touching the 06:00–22:00 local window and not touching the 22:00–06:00 overnight window — requires on-duty coverage of at least the census divided by four, rounded up to a whole caregiver. An overnight segment — any overlap with 22:00–06:00 — passes in either of two ways: the number of covering `AWAKE` shifts staffed by `awake_overnight_qualified` caregivers is at least the census divided by two, rounded up; or at least one awake-overnight-qualified caregiver covers the segment and the total on-duty count is at least the census divided by three, rounded up, which is the mixed `AWAKE`/`ASLEEP` staffing pattern. A segment whose on-duty coverage falls below its requirement is non-compliant. Creating a shift is rejected with `ERR_UNDERSTAFFED` whenever its addition would leave any currently occupied hour — an hour during which the home's census is above zero — non-compliant, and cancelling a shift is rejected with `ERR_UNDERSTAFFED` whenever its removal would do the same. The `overnight_mode` field is required when a shift covers any part of the 22:00–06:00 window and is otherwise ignored; `AWAKE` shifts count individually at the one-caregiver-per-two-residents ratio and demand the qualification, while `ASLEEP` shifts contribute only to the one-per-three aggregate alongside a co-scheduled awake-qualified caregiver.

Cancelling a shift moves `SCHEDULED` → `CANCELLED`, a terminal state, and a cancelled shift is excluded from all staffing computations. Cancellation beyond the manual action is automatic — without staffing-ratio revalidation — when the home closes (§3.1) or when the caregiver is terminated for shifts starting after the current logical time. For forward visibility, a `Provider` or `Nurse` can run the same ratio evaluation over a supplied window from `from_iso8601` to `to_iso8601` and receive the per-segment results as `segments` together with an overall `compliant` flag. The evaluation spans the whole supplied window, not only shift-covered time: a stretch of the window with no covering shift still appears as a segment with zero on-duty coverage — non-compliant whenever the home's census is above zero — and `compliant` is true only when every segment of the window is compliant.

### 3.6. Incidents and State Compliance Cases

Any role — `Provider`, `Nurse`, or `CaregiverRole` — files an incident with `resident_id`, an `incident_type` of `FALL`, `MED_ERROR`, `ELOPEMENT`, `ABUSE_ALLEGATION`, or `INJURY`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, the `occurred_at` timestamp of the event, and a narrative `description`; the server stamps `reported_at` from the logical clock at filing time. Severity drives everything downstream: `MINOR` is internal-review only, `MAJOR` and `CRITICAL` are state-reportable, and `CRITICAL` additionally blocks that resident's discharge while under investigation and — through the citation cascade below — can suspend new admissions for the whole home.

The state reporting deadline is twenty-four hours. The delay from `occurred_at` to `reported_at` is measured in whole minutes and expressed in hours; a `MAJOR` or `CRITICAL` incident filed more than twenty-four hours after the event is still accepted, but a late flag is set on it, and the later attempt to open a compliance case from it is refused with `ERR_LATE_REPORT`. The boundary is strict: a delay of exactly twenty-four hours and zero minutes is not late, while twenty-four hours and one minute is.

A `MINOR` incident closes directly — `REPORTED` → `CLOSED` through the provider's minor-close action — without any compliance case. For a `MAJOR` or `CRITICAL` incident, the provider opens a case: the incident moves `REPORTED` → `UNDER_REVIEW` and a linked compliance case is created in `OPEN`. There is exactly one case per incident — the case's `incident_id` is unique — and the case's `citation_code` stays null until a substantiation. Opening the case recomputes the home's `open_case_count`. If additional findings arrive, the review resets — `UNDER_REVIEW` → `REPORTED` — but only while the linked case is still `OPEN`; a case already substantiated or unfounded cannot be reopened through the incident, and the case itself stays `OPEN` through the reopen. Because there is exactly one case per incident, calling the open-case action again while that case is still `OPEN` — the state a reopen leaves behind — is not an error and creates no second case: the incident moves `REPORTED` → `UNDER_REVIEW` once more and the existing `OPEN` case is returned with 201, leaving the home's counters untouched.

The case adjudicates in one of two directions. Substantiation requires the provider to supply a `citation_code`: the case moves `OPEN` → `SUBSTANTIATED`, `correction_plan_due_at` is set to the decision timestamp plus fourteen days, the linked incident bubbles up `UNDER_REVIEW` → `RESOLVED`, and the home's `open_case_count` is recomputed. When the citation begins with WAC388-76-10 — the abuse and neglect findings — the home itself is suspended in the same step (`LICENSED` → `SUSPENDED`), blocking new admission approvals until reinstatement. Marking a case unfounded moves `OPEN` → `UNFOUNDED`, resolves the linked incident in the same way, and recomputes the counter.

Closing a case — from `SUBSTANTIATED` or from `UNFOUNDED` to the terminal `CLOSED` — recomputes `open_case_count` once more. From `SUBSTANTIATED`, the provider submits `correction_plan_submitted_at`, which must be present and must not fall after `correction_plan_due_at`; a late or missing plan is rejected with `ERR_LATE_CORRECTION_PLAN`. From `UNFOUNDED`, closure needs no plan. Only when the linked case has reached `CLOSED` may the provider close the incident itself, `RESOLVED` → `CLOSED`, the terminal state for both records.

### 3.7. Rate Schedules and Invoice Generation

A `Provider` publishes a rate schedule for a home with a `payer_type` marking which payer population it prices, a positive `room_and_board_daily_cents`, and three band add-ons — `care_low_daily_cents` at zero or more, `care_medium_daily_cents` at least the low figure, and `care_high_daily_cents` at least the medium figure — together with an inclusive `effective_from` date and an optional exclusive `effective_to` date, where null means open-ended. A new schedule whose effective window intersects an existing schedule for the same home and the same `payer_type` — a half-open intersection — is rejected with `ERR_RATE_OVERLAP`.

Invoice generation by a `Provider` takes `period_start`, `period_end` (which must be after `period_start`), a `due_date`, and the OCC field `expected_resident_version` described in §2.7, and produces a `DRAFT` invoice. The resident's `payer_type` at generation time is copied onto the invoice as `payer_type_snapshot`, and rate selection stays pinned to that snapshot even if the resident's funding source later changes. Generation increments the resident's `version`.

An occupied day is a home-local calendar date within the half-open billing period — `period_start` inclusive, `period_end` exclusive — on which a bed-stay exists: the resident's `admitted_at` falls at or before the end of that day, and either `discharged_at` is null or it falls after the start of that day. Each occupied day is priced off the unique schedule that matches `payer_type_snapshot` and whose `effective_from` is on or before that day while its `effective_to` is after that day or null — unique, because overlapping schedules are forbidden at publish time. If no schedule covers an occupied day, generation fails with `ERR_RATE_NOT_FOUND`.

Two variants diverge at the resident's status. While the resident is still `ADMITTED`, generation is provisional and forward-looking: days inside the period that have not yet elapsed are projected and billed anyway, and the acuity band is pinned from the resident's current `FINALIZED` assessment. Once the resident is `DISCHARGED`, generation becomes a chronological replay of the actual stay — nothing is projected, only elapsed days count, and the calendar day containing `discharged_at` is included and charged because the discharge falls after that day's start; the band is pinned from the `FINALIZED` assessment that was current at discharge time. For an identical period, the final variant therefore yields a subtotal smaller than or equal to the provisional one whenever the period extends beyond the discharge. In both variants the assessment selected is the latest `FINALIZED` one by `assessed_at`, with ties broken in favor of the earliest `created_at`.

The acuity band itself comes from two assessment inputs: `LOW` when `adl_dependency_score` is at most two and `nursing_hours_per_week` is below five; `HIGH` when `adl_dependency_score` is at least five or `nursing_hours_per_week` is at least fifteen; `MEDIUM` otherwise. A `PRIVATE_PAY` day line is the room-and-board figure plus the band's add-on. A `MEDICAID` day line combines the same room-and-board floor and band add-on with a nursing component: the weekly nursing cost is `nursing_hours_per_week` times 1500 cents, capped at 9000 cents per week; that capped weekly amount is divided by seven to prorate it per day and truncated to whole cents; and the resulting daily rate is rounded half-up to whole cents. With identical inputs, a private-pay day prices lower than a Medicaid day, because the nursing component is a Medicaid-only state supplement that private-pay billing skips entirely.

The invoice's `line_items` carry one row per occupied day — room-and-board or acuity-band care — plus flat ancillary rows, and each line carries `day`, `description`, `qty`, `unit_price_cents`, and `amount_cents`. Every line's `amount_cents` is already rounded to whole cents, and `subtotal_cents` is their sum — round per line, then sum, per §2.8. The `late_fee_cents` of a freshly generated invoice is zero.

### 3.8. Issuing, Settlement, and Discharge Accounting

Issuing by a `Provider` moves a `DRAFT` invoice to `ISSUED` and requires the invoice to have at least one line item. The late fee is evaluated at this exact moment against the logical clock: when the home-local current date is strictly after `due_date`, the fee is five percent of `subtotal_cents`, rounded half-up and then clamped to no less than 2500 cents and no more than 15000 cents; issuing exactly on `due_date` incurs no fee at all. The `total_cents` is the `subtotal_cents` plus the `late_fee_cents`, finalized at issue. Voiding moves `DRAFT` → `VOID` freely, or `ISSUED` → `VOID` only while no payments have been recorded against the invoice; `VOID` and `PAID` are both terminal.

A `Provider` records a payment with `resident_id`, `invoice_id`, `amount_cents`, and a `method` of `CASH`, `CHECK`, `ACH`, `CARD`, or `MEDICAID_REMIT`; `received_at` is stamped from the logical clock. The amount must be positive and must not exceed the invoice's outstanding balance, else the payment is rejected with `ERR_OVERPAYMENT`. A payment below the outstanding balance moves the invoice `ISSUED` → `PARTIALLY_PAID`; a payment exactly equal to the outstanding balance moves it `ISSUED` → `PAID` directly; and once cumulative payments reach the `total_cents`, a `PARTIALLY_PAID` invoice becomes `PAID`.

Discharge by a `Provider` takes a `reason` of `VOLUNTARY`, `HOSPITALIZATION`, `LEVEL_OF_CARE_EXCEEDED`, `NONPAYMENT`, or `DECEASED`, plus a `notice_days` count of the advance notice given. The incident block is evaluated first, per §2.9: while any `CRITICAL` incident for the resident is `REPORTED` or `UNDER_REVIEW`, the discharge is rejected with `ERR_BLOCKED_BY_INCIDENT`. Then the notice rule: `notice_days` must be at least thirty unless the reason is `HOSPITALIZATION` or `DECEASED`, else `ERR_INSUFFICIENT_NOTICE`. A successful discharge moves the resident `ADMITTED` → `DISCHARGED` — terminal — stamps `discharged_at` from the clock and copies it onto the new discharge record, returns the occupied bed to `AVAILABLE`, discontinues every remaining `ACTIVE` medication order, recomputes the home's `current_census`, and switches invoice generation for the occupancy window to the final, chronological variant of §3.7.

The same step computes a prepaid room-and-board refund onto the discharge record's `refund_amount_cents`. The prepaid pool is the sum of payments attributable to room-and-board lines dated strictly after the discharge date, across the resident's invoices. From that pool, a waterfall subtracts the outstanding balances on any `ISSUED` or `PARTIALLY_PAID` invoices, taking the oldest invoice by `period_start` first and breaking ties in favor of the earliest `created_at`. The remainder — never below zero, since negative refunds are not issued — is the refund, and it is applied against the final invoice. The discharge record itself, carrying `reason`, `notice_days`, `discharged_at`, and `refund_amount_cents`, is append-only per §2.5.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. Collection endpoints accept `limit` and `offset` for pagination plus resource-appropriate filters: `status` on most collections, `payer_type` on resident and rate-schedule listings, `severity` on incident listings, and the foreign-key filters `resident_id`, `bed_id`, `assessment_id`, `order_id`, `caregiver_id`, `home_id`, `incident_id`, and `invoice_id` where a collection is reachable through multiple parents.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | Provider |
| POST | `/api/homes` | Register a new adult family home (starts `PROVISIONAL`) | Provider |
| GET | `/api/homes` | List homes with pagination | Provider, Nurse, CaregiverRole |
| GET | `/api/homes/{id}` | Get one home including computed `open_case_count` and `current_census` | Provider, Nurse, CaregiverRole |
| POST | `/api/homes/{id}/license` | Transition `PROVISIONAL` → `LICENSED` | Provider |
| POST | `/api/homes/{id}/suspend` | Transition `LICENSED` → `SUSPENDED` | Provider |
| POST | `/api/homes/{id}/reinstate` | Transition `SUSPENDED` → `LICENSED`; requires zero open cases | Provider |
| POST | `/api/homes/{id}/close` | Transition to `CLOSED` (terminal); cascades beds and shifts | Provider |
| GET | `/api/homes/{id}/staffing-compliance` | Run the staffing-ratio evaluation over a window and return per-segment compliance | Provider, Nurse |
| POST | `/api/homes/{id}/beds` | Add a bed to a home | Provider |
| GET | `/api/homes/{id}/beds` | List beds of a home | Provider, Nurse, CaregiverRole |
| GET | `/api/beds/{id}` | Get one bed | Provider, Nurse |
| POST | `/api/beds/{id}/take-out-of-service` | `AVAILABLE`/`HELD` → `OUT_OF_SERVICE`; a `HELD` bed forces its linked pending admission to `REJECTED` | Provider |
| POST | `/api/beds/{id}/return-to-service` | `OUT_OF_SERVICE` → `AVAILABLE` | Provider |
| POST | `/api/homes/{id}/residents` | Register a prospective resident (starts `PROSPECT`) | Provider, Nurse |
| GET | `/api/homes/{id}/residents` | List residents of a home | Provider, Nurse, CaregiverRole |
| GET | `/api/residents/{id}` | Get one resident | Provider, Nurse, CaregiverRole |
| POST | `/api/residents/{id}/withdraw` | `APPLICANT` → `PROSPECT` when no live admission exists | Provider |
| POST | `/api/residents/{id}/discharge` | `ADMITTED` → `DISCHARGED`; creates the discharge record, computes the refund, cascades bed and medication orders | Provider |
| POST | `/api/residents/{id}/assessments` | Create a `DRAFT` assessment with care plan | Nurse |
| GET | `/api/residents/{id}/assessments` | List assessments of a resident | Provider, Nurse |
| GET | `/api/assessments/{id}` | Get one assessment | Provider, Nurse |
| POST | `/api/assessments/{id}/finalize` | `DRAFT` → `FINALIZED`; supersedes the prior `FINALIZED` assessment and promotes a `PROSPECT` resident | Nurse |
| POST | `/api/admissions` | Create a `PENDING` admission (holds the bed); OCC-guarded on the bed's version | Provider |
| GET | `/api/admissions` | List admissions, filterable by resident, bed, assessment, and status | Provider, Nurse |
| GET | `/api/admissions/{id}` | Get one admission | Provider, Nurse |
| POST | `/api/admissions/{id}/approve` | `PENDING` → `APPROVED`; segregation of duties enforced | Provider |
| POST | `/api/admissions/{id}/reject` | `PENDING` → `REJECTED`; releases the bed hold | Provider |
| POST | `/api/admissions/{id}/cancel` | `APPROVED` → `CANCELLED`; releases the bed hold | Provider |
| POST | `/api/admissions/{id}/complete` | `APPROVED` → `COMPLETED`; resident admitted, bed occupied, capacity enforced | Provider |
| POST | `/api/residents/{id}/medication-orders` | Create an `ACTIVE` medication order for an `ADMITTED` resident | Nurse |
| GET | `/api/residents/{id}/medication-orders` | List medication orders of a resident | Provider, Nurse, CaregiverRole |
| POST | `/api/medication-orders/{id}/discontinue` | `ACTIVE` → `DISCONTINUED` | Nurse |
| POST | `/api/medication-logs` | Log an administration; window, duplicate-dose, and on-shift validation | Nurse, CaregiverRole |
| GET | `/api/medication-logs` | List medication logs | Provider, Nurse |
| GET | `/api/medication-logs/{id}` | Get one medication log | Provider, Nurse |
| POST | `/api/adl-logs` | Log ADL assistance; on-shift validation | Nurse, CaregiverRole |
| GET | `/api/adl-logs` | List ADL logs | Provider, Nurse |
| GET | `/api/adl-logs/{id}` | Get one ADL log | Provider, Nurse |
| POST | `/api/homes/{id}/caregivers` | Register a caregiver | Provider |
| GET | `/api/homes/{id}/caregivers` | List caregivers of a home | Provider, Nurse |
| GET | `/api/caregivers/{id}` | Get one caregiver | Provider, Nurse, CaregiverRole |
| POST | `/api/caregivers/{id}/suspend` | `ACTIVE` → `SUSPENDED` | Provider |
| POST | `/api/caregivers/{id}/reinstate` | `SUSPENDED` → `ACTIVE` | Provider |
| POST | `/api/caregivers/{id}/terminate` | `ACTIVE`/`SUSPENDED` → `TERMINATED` (terminal); future scheduled shifts are cancelled | Provider |
| POST | `/api/shifts` | Schedule a shift; overlap, rolling-cap, and forward staffing-ratio validated; OCC-guarded on the caregiver's version | Provider |
| GET | `/api/shifts` | List shifts | Provider, Nurse |
| GET | `/api/shifts/{id}` | Get one shift | Provider, Nurse |
| POST | `/api/shifts/{id}/cancel` | `SCHEDULED` → `CANCELLED` when the staffing ratio stays satisfied | Provider |
| POST | `/api/incidents` | File an incident (stamps `reported_at` from the logical clock) | Provider, Nurse, CaregiverRole |
| GET | `/api/incidents` | List incidents | Provider, Nurse |
| GET | `/api/incidents/{id}` | Get one incident | Provider, Nurse |
| POST | `/api/incidents/{id}/open-case` | `REPORTED` → `UNDER_REVIEW`; creates the linked compliance case in `OPEN` — or, when the linked case is still `OPEN` after a reopen, returns that same case with 201 instead of creating a second one; late reports refused | Provider |
| POST | `/api/incidents/{id}/reopen` | `UNDER_REVIEW` → `REPORTED` while the case is still `OPEN` | Provider |
| POST | `/api/incidents/{id}/close` | `RESOLVED` → `CLOSED` when the linked case is `CLOSED` | Provider |
| POST | `/api/incidents/{id}/close-minor` | `REPORTED` → `CLOSED` for `MINOR` severity only | Provider |
| GET | `/api/compliance-cases` | List compliance cases | Provider, Nurse |
| GET | `/api/compliance-cases/{id}` | Get one compliance case | Provider, Nurse |
| POST | `/api/compliance-cases/{id}/substantiate` | `OPEN` → `SUBSTANTIATED`; sets the correction-plan deadline; may suspend the home on abuse citations | Provider |
| POST | `/api/compliance-cases/{id}/mark-unfounded` | `OPEN` → `UNFOUNDED` | Provider |
| POST | `/api/compliance-cases/{id}/close` | `SUBSTANTIATED` (on-time plan) or `UNFOUNDED` → `CLOSED` | Provider |
| POST | `/api/homes/{id}/rate-schedules` | Publish a rate schedule; overlapping windows for the same payer type are rejected | Provider |
| GET | `/api/homes/{id}/rate-schedules` | List rate schedules of a home | Provider, Nurse |
| POST | `/api/residents/{id}/invoices/generate` | Generate a `DRAFT` invoice for a billing period; provisional while admitted, final after discharge; OCC-guarded on the resident's version | Provider |
| GET | `/api/residents/{id}/invoices` | List invoices of a resident | Provider, Nurse |
| GET | `/api/invoices/{id}` | Get one invoice with line items | Provider, Nurse |
| POST | `/api/invoices/{id}/issue` | `DRAFT` → `ISSUED`; late fee evaluated against the logical clock | Provider |
| POST | `/api/invoices/{id}/void` | `DRAFT`/`ISSUED` → `VOID` (`ISSUED` only with zero payments) | Provider |
| POST | `/api/payments` | Record a payment against an `ISSUED` or `PARTIALLY_PAID` invoice | Provider |
| GET | `/api/payments` | List payments | Provider, Nurse |
| GET | `/api/payments/{id}` | Get one payment | Provider, Nurse |
| GET | `/api/discharge-records` | List discharge records | Provider, Nurse |
| GET | `/api/discharge-records/{id}` | Get one discharge record | Provider, Nurse |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SELF_APPROVAL` | 409 Conflict |
| `ERR_BLOCKED_BY_INCIDENT` | 409 Conflict |
| `ERR_LATE_REPORT` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_MED_WINDOW` | 422 Unprocessable Entity |
| `ERR_SHIFT_CONFLICT` | 409 Conflict |
| `ERR_UNDERSTAFFED` | 422 Unprocessable Entity |
| `ERR_BED_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_NOTICE` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_SUPERSEDED` | 409 Conflict |
| `ERR_CAREGIVER_NOT_ON_SHIFT` | 422 Unprocessable Entity |
| `ERR_ORDER_DISCONTINUED` | 409 Conflict |
| `ERR_RATE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_LATE_CORRECTION_PLAN` | 422 Unprocessable Entity |
| `ERR_BED_OCCUPIED` | 409 Conflict |
| `ERR_RATE_OVERLAP` | 409 Conflict |

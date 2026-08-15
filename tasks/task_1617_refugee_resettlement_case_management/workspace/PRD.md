# Refugee Resettlement Case Management API — Product Requirements Document

## 1. Introduction

This document specifies the REST API for a refugee resettlement case management system operated by a local affiliate office of a national resettlement agency. The affiliate receives arrival notifications from the national office, prepares housing and furnishings before each family lands, meets the family at the airport, and then has strict federally-mandated windows — thirty days for some services, ninety days for others — in which to deliver and document a defined battery of services: home visits, health screenings, Social Security and state identification applications, benefits enrollment, school enrollment for school-age children, employment services for work-eligible adults, and a six-topic cultural orientation curriculum.

The operational pain this system addresses is fragmentation. Today, arrival notifications live in one spreadsheet, housing preparation in another, benchmark deadlines are tracked on wall calendars, and the federal report is hand-assembled at the end of each quarter by counting paper files. Case managers lose track of which benchmarks are approaching their due dates; housing coordinators do not know when a unit can be promised to the next arrival; employment specialists cannot show the funder which households have crossed the self-sufficiency income threshold; and the agency director cannot demonstrate to the national office that every included case carries the documentation the funder requires. The system described here replaces that patchwork with a single API that enforces the workflow rules at the moment an operator attempts an action, derives compliance posture and unit availability from the underlying records on every read, and produces the federal report as a snapshot whose numbers cannot drift after generation.

The API serves five operator roles — case managers, housing coordinators, employment specialists, the agency director, and a federal reviewing officer — each with segregated authorities. A logical clock underlies every date computation in the system so that demonstrations, audits, and automated tests can advance time deterministically without waiting for real calendar days to pass.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting an `X-User-Role` value that is not one of the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The five roles, spelled exactly as the API expects them in `X-User-Role`, are:

- `CaseManager` — affiliate case manager; owns the case lifecycle from arrival notification through services, documentation, and transfer initiation.
- `HousingCoordinator` — affiliate housing coordinator; owns the housing unit pool and housing preparation/furnishing.
- `EmploymentSpecialist` — affiliate employment specialist; owns self-sufficiency plans and certification.
- `AgencyDirector` — affiliate director; waiver authority, receiving-side transfer response, federal report generation and submission, and control of the logical clock.
- `FederalOfficer` — national-office reviewer; reviews submitted federal reports. Segregation of duties applies even when one operator holds both the `AgencyDirector` and `FederalOfficer` roles: the reviewing `X-User-ID` must differ from the report's recorded `submitted_by_user_id`.

For all five roles — `CaseManager`, `HousingCoordinator`, `EmploymentSpecialist`, `AgencyDirector`, and `FederalOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires attribution (for example, as `initiated_by_user_id` on a `CaseTransfer`, as `responded_by_user_id` when a director responds, as `submitted_by_user_id` and `reviewed_by_user_id` on a `FederalReport`, and as the source for `author_role` on a `CaseNote`), but it never compares `X-User-ID` to any entity's `id` for ownership purposes. The single exception to "no comparison" is the segregation-of-duties check on report review, which compares the reviewer's `X-User-ID` against the report's stored `submitted_by_user_id` and rejects with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when they are equal.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and must not exceed 100. `offset` defaults to 0. List responses sort by `created_at` ascending unless a more specific ordering is stated for the endpoint, and the `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes and `version` increments by 1 on every mutation of the resource. The sole exception is `CaseNote`, which is append-only documentation: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

All date and datetime reasoning in the system runs against a **logical clock**, not wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z` and must never fall back to wall-clock time. An `AgencyDirector` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant; the clock never moves backward. Every rule in this document that says "today", "the current date", or "the logical clock date" refers to this logical clock.

### 2.5. Validation Order and Error Selection

When a request violates more than one rule, the API reports exactly one error, chosen by the following priority order, highest first. First, authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the five declared roles, else `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted on the endpoint, else `ERR_FORBIDDEN`. Third, existence: path identifiers are validated left-to-right, and then body foreign-key identifiers (`case_id`, `member_id`, `housing_unit_id`, `evidence_note_id`) must identify existing resources, else `ERR_NOT_FOUND`. Fourth, schema and field validity: required fields present, enum values valid, date ranges correctly ordered, `fulfilled_on` inside the allowed window, numeric fields non-negative, else `ERR_VALIDATION`. Fifth, optimistic concurrency on the one endpoint that requires it, else `ERR_STALE_VERSION`. Sixth, state-machine legality — wrong from-state, terminal lockdown, state-gated creates — else `ERR_INVALID_STATE` or `ERR_BENCHMARK_NOT_PENDING`. Seventh, housing capacity, else `ERR_HOUSING_CAPACITY_INSUFFICIENT`. Eighth, temporal interval conflicts, else the matching one of `ERR_UNIT_OCCUPANCY_CONFLICT`, `ERR_SESSION_SCHEDULE_CONFLICT`, or `ERR_REPORT_PERIOD_OVERLAP`. Ninth, the remaining domain constraints (housing readiness, single-setup, furnishing duplication and completeness, topic duplication and scheduling, transfer freeze, duplicate transfer, member eligibility, duplicate case number) with their specific error identifiers. Tenth, evidence linkage on benchmark fulfillment, else `ERR_EVIDENCE_NOTE_INVALID`. Eleventh and last, the reporting audit gates, else `ERR_REPORT_DOCUMENTATION_INCOMPLETE` or `ERR_SEGREGATION_OF_DUTIES`.

### 2.6. Optimistic Concurrency on Employment Plan Creation

Exactly one endpoint participates in optimistic concurrency control. Creating an employment plan requires the request to carry `expected_case_version`, a non-optional integer holding the `version` of the target case as the client last observed it. If the case's current `version` has advanced past that value — for example because another writer has just created a plan (which legitimately supersedes the prior `ACTIVE` plan) or recorded the arrival — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building a plan on a view of the case it has not observed. No other endpoint accepts a version field.

### 2.7. Monetary Precision and Date Arithmetic

All money in the system is integer cents; there are no fractional-cent amounts anywhere, and no rounding is ever applied except where the per-capita allocation rule in §3.7 explicitly rounds half-up per case. All calendar arithmetic is performed on whole ISO dates with no time component. Occupancy windows and report periods are half-open intervals: the start date is included and the end date is excluded, so two windows that merely touch at a boundary do not overlap.

### 2.8. Derived Fields and Snapshot Semantics

Some fields are never stored but computed on every read from the current state of related records and the logical clock: a case's `posture`, a case's `topics_completed`, a housing unit's `status`, and a household member's `age_at_arrival` / `school_age_at_arrival` (once arrival is recorded). In contrast, the counts and dollar figures on a `FederalReport` are **snapshots** frozen at generation time: later benchmark transitions, arrivals, or transfer cascades do not mutate an existing report's numbers. Implementations must not confuse the two regimes — derived fields track the world as it is now; snapshot fields remember the world as it was at generation.

## 3. Business Logic & Workflows

### 3.1. Arrival Notification and Case Registration

A case begins when the national office notifies the affiliate of an arriving household. A `CaseManager` registers the notification by supplying the agency-assigned `case_number`, the `agency_affiliate_code` of the receiving office, the declared `household_size` (which must be at least 1, since it later drives both housing capacity and income thresholds), and the `scheduled_arrival_date` as an ISO `YYYY-MM-DD` date. Case numbers are unique across the system: a registration repeating an already-registered `case_number` is rejected with `ERR_DUPLICATE_CASE_NUMBER` (HTTP 409). The new case starts in `PRE_ARRIVAL` status with `actual_arrival_date` null, `airport_pickup_completed` false, and `open_transfer_id` null.

While the case is `PRE_ARRIVAL`, the case manager builds the household roster. Each member record carries the owning `case_id`, the member's `full_name`, `date_of_birth` as an ISO date, a `relationship` of `PRINCIPAL`, `SPOUSE`, `CHILD`, or `OTHER_RELATIVE`, and a `work_eligible` flag recording whether the arrival notification says the member may legally work. Member creation is permitted only while the case is `PRE_ARRIVAL`; once the family has arrived, attempting to add a member is rejected with `ERR_INVALID_STATE` (HTTP 409). Two attributes of each member — `age_at_arrival` and `school_age_at_arrival` — stay null until arrival and are then computed and stored.

### 3.2. Housing Preparation: Units, Setups, and Furnishing

In parallel with roster building, the `HousingCoordinator` prepares a home. Housing units enter the agency pool with an `address` and a `bedrooms` count (zero or more). A unit's `status` is never stored; it is derived on every read from the unit's non-terminal housing setups — those in `PREPARING`, `READY`, or `OCCUPIED`, with `VACATED` setups excluded — against the logical clock date. If any non-terminal setup's occupancy window covers today (that is, `occupancy_start` is on or before today and today is strictly before `occupancy_end`), the unit reads `OCCUPIED`. Otherwise, if at least one non-terminal setup exists for the unit, it reads `RESERVED`. Otherwise it reads `AVAILABLE`. Vacating a setup — manually or through the transfer cascade — removes it from the non-terminal set, so the unit falls back to `AVAILABLE` unless another non-terminal setup still covers it.

A housing setup ties a case to a unit for a declared occupancy window. Creating one takes the `case_id` (the case must still be `PRE_ARRIVAL`, else `ERR_INVALID_STATE`), the `housing_unit_id`, and the half-open window `occupancy_start` (inclusive) through `occupancy_end` (exclusive); an end that is not strictly after the start fails schema validation with `ERR_VALIDATION` (HTTP 400). Two safety rules guard creation. The capacity rule prevents overcrowding: the unit's `bedrooms` must be at least the household size divided by two and rounded up to a whole number — a household of five therefore needs at least three bedrooms — and a unit that is too small is rejected with `ERR_HOUSING_CAPACITY_INSUFFICIENT` (HTTP 422). The scheduling rule keeps one unit from being double-promised: the new occupancy window must not overlap the window of any other non-terminal setup on the same unit, where overlap is judged on half-open intervals so a window starting the day another ends is allowed; a genuine overlap is rejected with `ERR_UNIT_OCCUPANCY_CONFLICT` (HTTP 409). A case may also have at most one non-terminal setup at a time — a second setup for a case that already has one in `PREPARING`, `READY`, or `OCCUPIED` is rejected with `ERR_SETUP_ALREADY_EXISTS` (HTTP 409). A fresh setup starts `PREPARING` with `furnishing_items_completed` empty, and its creation immediately recomputes the unit's derived status to `RESERVED` (or `OCCUPIED` if the window already covers today).

Before the family can move in, the coordinator must complete the six required furnishings. The coordinator marks one item at a time complete by naming the `item`; the item is appended to `furnishing_items_completed`. Naming an item that is already in that list is rejected with `ERR_ITEM_ALREADY_FURNISHED` (HTTP 409), and naming a value outside the required-furnishings set fails schema validation with `ERR_VALIDATION`. Once `furnishing_items_completed` contains every member of the required set, the coordinator may mark the setup ready, moving it `PREPARING → READY`; if any required item is still missing, the ready call fails with `ERR_FURNISHING_INCOMPLETE` (HTTP 409). A setup in any of `PREPARING`, `READY`, or `OCCUPIED` may also be vacated by the coordinator, moving it to the terminal `VACATED` state and recomputing its unit's derived status.

### 3.3. Arrival Day: The Arrival Cascade and Benchmark Seeding

Recording arrival is the pivotal event of the case lifecycle, performed by a `CaseManager` supplying the `actual_arrival_date` as an ISO date. The case must be `PRE_ARRIVAL` — recording arrival a second time is rejected with `ERR_INVALID_STATE` — and, critically, the case must have a housing setup in `READY` status: a family cannot be recorded as arrived when no ready home exists, and the attempt is rejected with `ERR_HOUSING_NOT_READY` (HTTP 409).

A successful arrival fires a cascade across five entity kinds, all visible in the same response. The case itself moves `PRE_ARRIVAL → ARRIVED`; `actual_arrival_date` is stored from the request and `airport_pickup_completed` becomes true, since airport pickup is recorded as part of arrival. Every household member's `age_at_arrival` is computed as age in whole years on the `actual_arrival_date`, and `school_age_at_arrival` becomes true exactly when that age is at least 5 and at most 17. The `READY` housing setup for the case transitions `READY → OCCUPIED`, and because that setup became `OCCUPIED`, its unit's derived status recomputes to `OCCUPIED` while today is inside the occupancy window. The case's `version` increments by 1.

Arrival also seeds the case's service benchmarks, the compliance heart of the system. Five benchmarks are always seeded — `HOME_VISIT`, `HEALTH_SCREENING`, `SSN_APPLICATION`, and `BENEFITS_ENROLLMENT` each carrying a `due_rule` of `DAYS_30`, plus `CULTURAL_ORIENTATION` carrying `DAYS_90`. Two more are seeded conditionally from the freshly computed member attributes: a `SCHOOL_ENROLLMENT` benchmark with `due_rule` `DAYS_30` is seeded only when at least one member has `school_age_at_arrival` true, and an `EMPLOYMENT_PLAN` benchmark with `due_rule` `DAYS_90` is seeded only when at least one member is `work_eligible` and has `age_at_arrival` of at least 18. Every benchmark is stored with two due dates computed at seeding time from its `due_rule`: 30 days for `DAYS_30`, 90 days for `DAYS_90`. The planning view, `planned_due_date`, is the `scheduled_arrival_date` plus the rule's offset. The compliance view, `due_date`, is the `actual_arrival_date` plus the same offset. Whenever actual arrival differs from schedule, the two bases diverge, and the same fulfillment date can be late under the scheduled basis yet on time under the actual basis; only the actual basis drives compliance. Each seeded benchmark starts `PENDING` with `fulfilled_on`, `evidence_note_id`, `on_time`, and `waived_reason` all null.

From arrival onward, reading the case reports a derived `posture` against the logical clock. If any of the case's benchmarks is `PENDING` with a `due_date` strictly before today, the posture is `OVERDUE`. Otherwise, if any `PENDING` benchmark has a `due_date` on or before today plus a seven-day look-ahead window, the posture is `AT_RISK`. Otherwise the posture is `ON_TRACK`. The boundary matters: a benchmark due exactly today is `AT_RISK`, not `OVERDUE` — overdue requires the due date to be strictly in the past.

### 3.4. Delivering Services: Benchmarks, Evidence Notes, and Documentation

Case notes are the system's append-only documentation stream. A `CaseManager`, `HousingCoordinator`, `EmploymentSpecialist`, or `AgencyDirector` may append a note carrying the `case_id`, a `note_type` of `GENERAL`, `SERVICE_DELIVERY`, `INCIDENT`, or `TRANSFER`, a free-text `body`, and an optional `service_date` recording when a documented service occurred. The server stamps `author_role` from the request's `X-User-Role` — one of `CASE_MANAGER`, `HOUSING_COORDINATOR`, `EMPLOYMENT_SPECIALIST`, or `AGENCY_DIRECTOR`. Notes are never edited or deleted; the `FederalOfficer` can read them but cannot author them.

Fulfilling a benchmark is how a `CaseManager` records that a mandated service happened. The request supplies the `fulfilled_on` date and an `evidence_note_id`, plus an `enrolled_member_ids` list used only for school enrollment. The benchmark must be `PENDING` — fulfilling or waiving a benchmark in any other state is rejected with `ERR_BENCHMARK_NOT_PENDING` (HTTP 409) — and the case must have no open transfer, else `ERR_CASE_TRANSFER_PENDING`. The evidence note must exist, must belong to the same case as the benchmark, and must be a `SERVICE_DELIVERY` note; any other linkage is rejected with `ERR_EVIDENCE_NOTE_INVALID` (HTTP 422). The `fulfilled_on` date must fall on or after the case's `actual_arrival_date` and on or before the current logical clock date; outside that window the request fails with `ERR_VALIDATION`. For a `SCHOOL_ENROLLMENT` benchmark there is one further eligibility gate: `enrolled_member_ids` must equal exactly the set of the case's members with `school_age_at_arrival` true — no missing school-age child and no extra member — else `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 422). A successful fulfillment moves the benchmark `PENDING → MET`, stores `fulfilled_on` and `evidence_note_id` from the request, and sets `on_time` by comparing `fulfilled_on` against the actual-basis `due_date`: fulfillment on or before the due date counts on time, with the boundary inclusive, so fulfilling exactly on the due date is on time and fulfilling one day after is late.

One benchmark fulfills itself. The `CULTURAL_ORIENTATION` benchmark moves `PENDING → MET` automatically at the moment an orientation-session completion makes the case's `topics_completed` cover all six curriculum topics; in that auto-fulfillment `fulfilled_on` is the completing session's `completed_on`, `evidence_note_id` stays null, and `on_time` is computed by the same inclusive comparison.

Two corrective actions round out the benchmark lifecycle. A benchmark in `PENDING` may be waived by an `AgencyDirector` supplying a `reason`, which is stored in `waived_reason`; manual waiver requires the case to have no open transfer. And a `MET` benchmark may be rescinded back to `PENDING` by a `CaseManager` when the documentation was wrong — rescinding clears `fulfilled_on`, `evidence_note_id`, and `on_time` back to null. Only manually fulfilled benchmarks can be rescinded: an auto-fulfilled `CULTURAL_ORIENTATION` benchmark has a null `evidence_note_id`, and attempting to rescind it is rejected with `ERR_INVALID_STATE`. Rescinding likewise requires the case to have no open transfer. Note the resulting topology: `WAIVED` is terminal — there is no path out of a waiver — while `MET` loops back to `PENDING` through rescind.

Benchmarks are queryable in three shapes: the benchmarks of one case, listed in seeding order (`HOME_VISIT`, `HEALTH_SCREENING`, `SSN_APPLICATION`, `BENEFITS_ENROLLMENT`, `CULTURAL_ORIENTATION`, then the conditional `EMPLOYMENT_PLAN` and `SCHOOL_ENROLLMENT`) and filterable by `status` and `service_type`; a single benchmark by id; and a cross-case audit listing filterable by `case_id`, `status`, `service_type`, and `evidence_note_id` — the last of which finds the benchmark a given note evidences and therefore returns an array of length zero or one.

### 3.5. Benefits, Employment, and Cultural Orientation After Arrival

Three parallel service tracks open once the case is `ARRIVED`. All three share a gate: the case must have no open transfer, and a create attempted while a transfer is `INITIATED` is rejected with `ERR_CASE_TRANSFER_PENDING` (HTTP 409); a create attempted before arrival is rejected with `ERR_INVALID_STATE`.

**Benefits.** A `CaseManager` opens a benefit application with the `case_id`, the `member_id` of the member the application is for — that member must belong to the case, else `ERR_NOT_FOUND` — and a `benefit_type` of `SSN`, `STATE_ID`, `CASH_ASSISTANCE`, `MEDICAL`, or `FOOD_ASSISTANCE`. Cash assistance carries an eligibility rule: the member must be `work_eligible`, else the create is rejected with `ERR_MEMBER_NOT_ELIGIBLE`. Applications start in `DRAFT` and move through a cyclic state machine driven by the case manager naming a `to_status`. From `DRAFT` an application is filed, moving to `FILED` with `filed_on` stamped from the logical clock. From `FILED` it is decided: `APPROVED` or `DENIED`, either way stamping `decided_on` from the clock. A `DENIED` application may be appealed, moving to `APPEALED` with no date stamping, and an `APPEALED` application may be re-filed back to `FILED` — the re-file stamps `filed_on` anew and clears `decided_on` to null, since the prior decision no longer stands. This `DRAFT → FILED → DENIED → APPEALED → FILED` loop is the appeal cycle. Withdrawal is also possible: from `DRAFT` or `FILED` the case manager may withdraw the application to `WITHDRAWN`. `APPROVED` and `WITHDRAWN` are terminal, and any transition that does not match one of these pairs — including deciding an `APPROVED` application or appealing a `FILED` one — is rejected with `ERR_INVALID_STATE`. Applications can be listed with `case_id`, `member_id`, and `status` filters plus pagination.

**Employment.** An `EmploymentSpecialist` creates the household's self-sufficiency plan by supplying the `case_id` and the OCC field `expected_case_version` described in §2.6. Creation starts the plan `ACTIVE` with `monthly_income_cents`, `trailing_3m_income_cents`, and `employed_members_count` each defaulting to 0 and `job_start_date` defaulting to null, and it supersedes any existing `ACTIVE` plan for the same case — the prior plan moves `ACTIVE` → `SUPERSEDED` automatically, so at most one plan is ever `ACTIVE` per case. Creation also increments the case's `version` by 1, which is precisely why the OCC check exists: two specialists working from the same stale case read must not both create plans. The specialist maintains the income picture on the `ACTIVE` plan by patching any subset of `monthly_income_cents` (gross monthly household earned income in cents, zero or more), `trailing_3m_income_cents` (gross earned income over the trailing three calendar months in cents, zero or more), `job_start_date` (the most recent employment start as an ISO date, or null if unemployed), and `employed_members_count` (zero or more). Patching a plan that is no longer `ACTIVE` is rejected with `ERR_INVALID_STATE`.

Certification is the employment track's verdict. The specialist certifies an `ACTIVE` plan by naming a determination `variant`, and the system runs the self-sufficiency determination. The threshold depends on the case's `household_size`: the monthly threshold in cents is a base of 130000 (that is, $1,300.00) plus 45000 ($450.00) for each household member beyond the first. Under the `MONTHLY` variant — the current-month run-rate test — the earned-income disregard of 20000 cents ($200.00) is applied to `monthly_income_cents`: the effective income is the monthly income minus the smaller of the monthly income itself and the disregard, and the household is self-sufficient when that effective income is at least the monthly threshold. Under the `ANNUALIZED` variant — the trailing-quarter run-rate test — three times the disregard is applied against `trailing_3m_income_cents`: the effective trailing income is the trailing income minus the smaller of the trailing income itself and three times the disregard, and the household is self-sufficient when that effective trailing income is at least three times the monthly threshold. All comparisons are integer cents with an inclusive boundary — exactly at threshold passes. The two variants can legitimately disagree: a recently hired household may pass `MONTHLY` while failing `ANNUALIZED`, and a household whose income has just collapsed may show the reverse. When the determination passes, the plan moves `ACTIVE → CERTIFIED` with `self_sufficient` true, the used variant recorded in `determination_variant`, and `certified_on` stamped from the logical clock; `CERTIFIED` is terminal. When it fails, the plan remains `ACTIVE` with `self_sufficient` false and `determination_variant` still recorded, and the specialist may update income fields and certify again.

**Cultural orientation.** A `CaseManager` schedules an orientation session with the `case_id`, a `topic` from the six-topic curriculum — `US_LAWS`, `HEALTHCARE_ACCESS`, `EDUCATION_SYSTEM`, `EMPLOYMENT_RIGHTS`, `HOUSING_SAFETY`, `BUDGETING` — and a window `start_at` to `end_at` (both ISO 8601 datetimes; an end not strictly after the start fails with `ERR_VALIDATION`). Two delivery rules protect the curriculum: a topic already delivered — that is, having a `COMPLETED` session for this case — is rejected with `ERR_TOPIC_ALREADY_DELIVERED` (HTTP 409), and a topic that already has a `SCHEDULED` session for this case is rejected with `ERR_TOPIC_ALREADY_SCHEDULED` (HTTP 409). A scheduling rule protects the family's calendar: the new session must keep a 30-minute buffer against every `SCHEDULED` or `COMPLETED` session of the same case — meaning no other such session may start less than 30 minutes after this one ends or end less than 30 minutes before this one starts — and a violation is rejected with `ERR_SESSION_SCHEDULE_CONFLICT` (HTTP 409). New sessions start `SCHEDULED`.

Completing a session — again a `CaseManager` action, requiring no open transfer — moves it `SCHEDULED → COMPLETED` and stamps `completed_on` from the logical clock. That completion recomputes the case's derived `topics_completed`, the sorted unique list of topics with a `COMPLETED` session, adding the session's topic. And if that recomputation makes `topics_completed` cover all six topics while the case's `CULTURAL_ORIENTATION` benchmark is still `PENDING`, the benchmark auto-transitions to `MET` as described in §3.4 — the completion is the fulfillment, with no separate evidence note.

### 3.6. Secondary Migration: Case Transfer and the Transfer-Out Cascade

Refugees sometimes relocate to another affiliate's territory. A `CaseManager` initiates the transfer by supplying the `case_id` (the case must be `ARRIVED`; a `PRE_ARRIVAL` case cannot be transferred), the `receiving_affiliate_code` of the destination office, and a `reason` of `SECONDARY_MIGRATION`, `FAMILY_REUNIFICATION`, or `EMPLOYMENT_OPPORTUNITY`. Only one transfer may be open per case: initiating while another transfer for the same case is `INITIATED` is rejected with `ERR_TRANSFER_ALREADY_OPEN` (HTTP 409). The new transfer starts `INITIATED`, stamps `initiated_by_user_id` from the initiator's `X-User-ID`, and freezes the case: the case's `open_transfer_id` is set to the new transfer's id and the case's `version` increments by 1.

While a transfer is `INITIATED`, the freeze blocks child mutations on the case — benefit application creation, employment plan creation, orientation session scheduling and completion, benchmark fulfillment, manual waiver, and rescind all fail with `ERR_CASE_TRANSFER_PENDING` — while case notes, transfer response and withdrawal, and all reads remain allowed.

The receiving side responds through an `AgencyDirector`, who supplies a `decision` and an optional `decision_note`; the responder's `X-User-ID` is stamped into `responded_by_user_id`. The response has two branches with deliberately asymmetric consequences. On `REJECTED`, the transfer moves `INITIATED → REJECTED`, the case's `open_transfer_id` clears to null, the case's `version` increments by 1, and nothing else happens — no service cascade touches the sessions, applications, plan, or housing setup. On `ACCEPTED`, the transfer moves `INITIATED → COMPLETED` and the case itself transitions `ARRIVED → TRANSFERRED_OUT`, firing the full transfer-out cascade in the same request: `open_transfer_id` clears to null; the case's non-terminal housing setup (whether `PREPARING`, `READY`, or `OCCUPIED`) moves to `VACATED` and the unit's derived status recomputes — `AVAILABLE` unless another non-terminal setup still covers today; any `ACTIVE` employment plan moves to `CLOSED_TRANSFERRED`; every benefit application in `DRAFT`, `FILED`, `DENIED`, or `APPEALED` moves to `WITHDRAWN` (applications already `APPROVED` or `WITHDRAWN` are untouched, since those states are terminal); every `SCHEDULED` orientation session moves to `CANCELLED`; because those sessions were cancelled, the case's `CULTURAL_ORIENTATION` benchmark, if still `PENDING`, moves to `WAIVED` with `waived_reason` recorded as `TRANSFER`; and every other `PENDING` benchmark likewise moves to `WAIVED` with `waived_reason` `TRANSFER`. The case's `version` increments by 1 with the transition. `TRANSFERRED_OUT` is the case's terminal state.

The initiator may also abandon the process: withdrawing an `INITIATED` transfer moves it `INITIATED → WITHDRAWN`, clears the case's `open_transfer_id` to null, and increments the case's `version` by 1 — like rejection, withdrawal performs no service cascade.

### 3.7. Federal Reporting: Snapshots, Submission, and Review

Each reporting cycle, an `AgencyDirector` generates a federal report by supplying `period_start` (inclusive) and `period_end` (exclusive) as ISO dates, with the end strictly after the start else `ERR_VALIDATION`. Report periods must not overlap any existing federal report of any status — again judged as half-open intervals, so a period starting exactly where another ends is allowed — and an overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409).

Generation freezes a snapshot. The included cases are those whose `actual_arrival_date` falls inside the half-open period, in any status — `ARRIVED` or `TRANSFERRED_OUT` both count; `PRE_ARRIVAL` cases are never included because they have no actual arrival. `cases_arrived_count` is the number of included cases. The counted benchmarks are the benchmarks belonging to included cases whose actual-basis `due_date` falls inside the period — a due date exactly on `period_start` is included, a due date exactly on `period_end` is excluded. From those counted benchmarks, `benchmarks_met_count` counts the ones in `MET` status, `benchmarks_met_on_time_count` counts the subset of those with `on_time` true, `benchmarks_pending_count` counts those still `PENDING`, and `benchmarks_waived_count` counts those `WAIVED`. Because these are snapshots taken at generation, benchmark transitions that happen afterwards never mutate an existing report.

The report's funding figure, `per_capita_allocation_cents`, is computed per included case and then summed, with a pinned rounding order. For each included case: count the case's covered months as the number of calendar months whose own month-start-to-next-month-start window overlaps the window from the later of the case's `actual_arrival_date` and `period_start` through `period_end` (exclusive). Cap the household size at 8 members — the size used is the smaller of `household_size` and 8. The case's raw allocation is the annual per-capita rate of 1250000 cents ($12,500.00) times the capped size times the covered months, divided by 12. Round each case's allocation half-up to integer cents first, and only then sum the per-case rounded amounts into `per_capita_allocation_cents`. The alternative order — summing raw values and rounding once at the end — is forbidden: the two orders diverge by at least a cent whenever two or more cases carry fractional-cent remainders. A new report starts `DRAFT` with `revision_count` 0, `submitted_by_user_id` null, and `reviewed_by_user_id` null.

Submission carries a documentation gate: an `AgencyDirector` may submit a `DRAFT` report only when every case counted in `cases_arrived_count` has at least one case note; a report covering an undocumented case is rejected with `ERR_REPORT_DOCUMENTATION_INCOMPLETE` (HTTP 422). Successful submission moves the report `DRAFT` → `SUBMITTED` and stamps `submitted_by_user_id` from the submitter's `X-User-ID`.

Review is the `FederalOfficer`'s exclusive act, supplying a `decision` and an optional `review_note`. Segregation of duties is enforced on user identity, not role: the reviewer's `X-User-ID` must differ from the report's `submitted_by_user_id`, even when the same operator holds both roles, else the review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On `ACCEPTED` the report moves `SUBMITTED` → `ACCEPTED` — its terminal state — with `reviewed_by_user_id` stamped. On `REJECTED` the report returns `SUBMITTED` → `DRAFT`: `reviewed_by_user_id` is stamped, `submitted_by_user_id` is cleared to null, and `revision_count` increments by 1, opening the revision loop in which the director may correct and re-submit the same report.

## 4. Endpoint Definitions

All endpoints follow the response envelope and error format of §2.2. Endpoints that create a new resource return HTTP 201 with the created resource; endpoints that modify an existing resource, read, or list return HTTP 200. The one administrative endpoint returns HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cases | Register an arrival notification as a new case | CaseManager |
| GET | /cases/{id} | Get a case including computed `posture` and `topics_completed` | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /cases/{id}/arrive | Record airport pickup and actual arrival; seeds the 30/90-day benchmarks and occupies the READY housing setup | CaseManager |
| POST | /members | Add a household member to a `PRE_ARRIVAL` case | CaseManager |
| GET | /cases/{id}/members | List household members of a case | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /housing-units | Register a housing unit in the agency pool | HousingCoordinator |
| GET | /housing-units/{id} | Get a housing unit including its derived `status` | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /housing-setups | Create a housing setup assigning a unit and occupancy window to a `PRE_ARRIVAL` case | HousingCoordinator |
| GET | /cases/{id}/housing-setups | List housing setups of a case | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| GET | /housing-units/{id}/housing-setups | List housing setups assigned to a unit | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /housing-setups/{id}/furnish | Mark one required-furnishings `item` complete on a `PREPARING` setup | HousingCoordinator |
| POST | /housing-setups/{id}/ready | Mark a `PREPARING` setup `READY` (requires all six furnishing items complete) | HousingCoordinator |
| POST | /housing-setups/{id}/vacate | Vacate a non-terminal setup, releasing the unit | HousingCoordinator |
| GET | /cases/{id}/benchmarks | List benchmarks of a case in seeding order; filterable by `status` and `service_type` | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| GET | /benchmarks/{id} | Get a single benchmark | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| GET | /benchmarks | List benchmarks across cases with `case_id`, `status`, `service_type`, and `evidence_note_id` filters (audit view) | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /benchmarks/{id}/fulfill | Fulfill a `PENDING` benchmark with a `SERVICE_DELIVERY` evidence note | CaseManager |
| POST | /benchmarks/{id}/waive | Waive a `PENDING` benchmark (director authority) | AgencyDirector |
| POST | /benchmarks/{id}/rescind | Rescind a manually fulfilled benchmark back to `PENDING` | CaseManager |
| POST | /benefit-applications | Open a benefit application for a member of an `ARRIVED` case | CaseManager |
| GET | /benefit-applications/{id} | Get a benefit application | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| GET | /benefit-applications | List benefit applications with filters and pagination | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /benefit-applications/{id}/transition | Advance a benefit application per its state machine by naming `to_status` | CaseManager |
| POST | /employment-plans | Create the self-sufficiency plan for an `ARRIVED` case; supersedes any existing `ACTIVE` plan; OCC-guarded | EmploymentSpecialist |
| GET | /cases/{id}/employment-plans | List employment plans of a case (current and superseded) | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| PATCH | /employment-plans/{id} | Update income and employment fields of an `ACTIVE` plan | EmploymentSpecialist |
| POST | /employment-plans/{id}/certify | Run the self-sufficiency determination with the requested `variant`; `CERTIFIED` on pass, stays `ACTIVE` on fail | EmploymentSpecialist |
| POST | /orientation-sessions | Schedule a cultural-orientation session for an `ARRIVED` case | CaseManager |
| GET | /cases/{id}/orientation-sessions | List orientation sessions of a case | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /orientation-sessions/{id}/complete | Mark a `SCHEDULED` session delivered; may auto-fulfill the `CULTURAL_ORIENTATION` benchmark | CaseManager |
| POST | /case-notes | Append a case note (`author_role` taken from `X-User-Role`) | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector |
| GET | /cases/{id}/case-notes | List case notes of a case with pagination | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /case-transfers | Initiate a secondary-migration transfer; freezes child mutations while `INITIATED` | CaseManager |
| GET | /cases/{id}/case-transfers | List transfers of a case | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /case-transfers/{id}/respond | Receiving-side response: `ACCEPTED` runs the full transfer-out cascade; `REJECTED` unfreezes without side effects | AgencyDirector |
| POST | /case-transfers/{id}/withdraw | Withdraw an `INITIATED` transfer, unfreezing the case | CaseManager |
| POST | /federal-reports | Generate a point-in-time federal report snapshot for a period | AgencyDirector |
| GET | /federal-reports/{id} | Get a federal report | CaseManager, HousingCoordinator, EmploymentSpecialist, AgencyDirector, FederalOfficer |
| POST | /federal-reports/{id}/submit | Submit a `DRAFT` report (documentation gate applies) | AgencyDirector |
| POST | /federal-reports/{id}/review | Federal review: `ACCEPTED` finalizes; `REJECTED` returns to `DRAFT` with `revision_count` incremented | FederalOfficer |
| POST | /_clock/set_current_utc | Set the logical clock (`to_iso8601`); before any set call the clock reads exactly 2026-08-01T00:00:00Z | AgencyDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this catalogue is the canonical identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_HOUSING_NOT_READY | 409 |
| ERR_HOUSING_CAPACITY_INSUFFICIENT | 422 |
| ERR_UNIT_OCCUPANCY_CONFLICT | 409 |
| ERR_SETUP_ALREADY_EXISTS | 409 |
| ERR_FURNISHING_INCOMPLETE | 409 |
| ERR_ITEM_ALREADY_FURNISHED | 409 |
| ERR_SESSION_SCHEDULE_CONFLICT | 409 |
| ERR_TOPIC_ALREADY_DELIVERED | 409 |
| ERR_TOPIC_ALREADY_SCHEDULED | 409 |
| ERR_CASE_TRANSFER_PENDING | 409 |
| ERR_TRANSFER_ALREADY_OPEN | 409 |
| ERR_MEMBER_NOT_ELIGIBLE | 422 |
| ERR_EVIDENCE_NOTE_INVALID | 422 |
| ERR_BENCHMARK_NOT_PENDING | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_REPORT_DOCUMENTATION_INCOMPLETE | 422 |
| ERR_DUPLICATE_CASE_NUMBER | 409 |

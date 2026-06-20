# Occupational Health Clinic API — Product Requirements Document

## 1. Introduction

Occupational health clinics sit at the intersection of clinical care, regulatory compliance, and employer billing. A single clinic serves dozens of employer accounts, each with its own testing protocol, its own roster of workers, and its own regulatory posture — some operate vehicles under federal Department of Transportation rules, others do not. Against this backdrop the clinic must run pre-employment physicals and drug screens, manage workplace injury cases and the federal recordability determinations that follow them, conduct periodic surveillance exams such as audiometric tests and respirator fit tests, issue fit-for-duty clearances, and bill it all back to the right employer on the right terms.

This document specifies the API that orchestrates that work. The system is organized around an **Employer** account that owns a single active testing **Protocol**, a population of **Workers**, and a stream of clinical **Encounters**. Each encounter forks into one of four downstream pipelines — physical, drug screen, injury, or surveillance — with distinct result entities, chain-of-custody requirements, and completion preconditions. The defining tension of the domain is the separation of duties between the operational roles that staff an encounter and the Medical Review Officer who independently adjudicates a regulated drug result, layered on top of a forensic chain-of-custody log and a deterministic per-employer clock that drives surveillance recheck windows, invoice aging, and return-to-work timelines. The remainder of this document defines the global contracts that every endpoint honors, the business workflows that govern each entity's lifecycle, the full endpoint surface, and the catalogue of error identifiers the API can return.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across every endpoint in the API. The entire surface is mounted under the `/clinic` prefix, with the sole exception of an administrative clock-control capability described in §2.10.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting operator, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `ClinicAdmin`, `Clinician`, `Collector`, and `MRO`. The `ClinicAdmin` administers employer accounts, protocols, and invoices, voids encounters, and controls the clock. The `Clinician` runs encounters and clinical results — entering lab results, creating injury and surveillance records, and issuing clearances. The `Collector` records chain-of-custody collection steps and may create drug screens. The `MRO` (Medical Review Officer) independently receives, verifies, and recollects drug screens.

All four roles use an **opaque** identity model: in every case, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record the acting operator's id where the workflow requires it. When a `Clinician` schedules an encounter, the server pins that operator's `X-User-ID` onto the encounter as `clinician_user_id`. When an `MRO` receives a drug screen, the server pins the acting `X-User-ID` onto the screen as `mro_user_id`. When any operator records a chain-of-custody step, the server records their `X-User-ID` as the custody event's `actor_user_id`. None of these recorded identifiers is ever matched against an entity's `id`; they are used only for the segregation-of-duties and MRO-assignment comparisons described in §3.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. Out-of-range and malformed pagination values are coerced rather than rejected: a `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, a negative `offset` is clamped up to 0, and a non-integer `limit` or `offset` falls back to its default (10 and 0 respectively); no pagination error is ever returned.

Unless a particular endpoint specifies otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. The chain-of-custody listing is the documented exception: custody events are returned ordered by their per-screen `seq` index. The response envelope's `meta` object carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more` for every list response.

### 2.4. Common Resource Properties and Audit Fields

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, recording when the resource was first created and when it was last modified, respectively. The `version` is an integer that begins at its initial value on creation and increments by one on every mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.8.

One entity is deliberately exempt from this convention. A **CustodyEvent** is an append-only forensic record and carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`, because a custody event is never modified after it is written. All other entities — Employer, Protocol, Worker, Encounter, DrugScreen, InjuryCase, WorkStatus, SurveillanceExam, Clearance, and Invoice — carry the full complement of `id`, `created_at`, `updated_at`, and `version`.

Derived and computed fields participate in the audit lifecycle the same way input fields do: when the system recomputes a derived value (for example an employer's `outstanding_balance_cents` after an invoice event) and that recomputation actually changes the stored value, the change is a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`. A balance recompute that leaves the value unchanged (for example voiding a `DRAFT` invoice, which contributed nothing to the balance) does not on its own refresh `updated_at` or increment `version`. The two write operations that §2.8 declares always advance the employer's `version` — protocol activation and invoice issuance — and the clock-set of §2.7/§2.10 advance the employer's `version` unconditionally regardless of whether the balance value moved.

### 2.5. Nested and Cross-Aggregate Reference Resolution

The entity model is flat: every collection lives directly under `/clinic`, and child resources reference their parents through foreign-key fields in the request body rather than through nested URL paths. A drug screen carries the `encounter_id` of its owning encounter; an injury case carries its `encounter_id`; a work-status note carries its `injury_case_id`; a custody event carries its `drug_screen_id`; protocols, workers, encounters, and invoices each carry an `employer_id`. Children are discovered through filtered list endpoints rather than nested routes.

When an endpoint path contains a resource identifier, the system validates it before doing any work, returning the resource-specific not-found error (for example `ERR_EMPLOYER_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`, `ERR_DRUG_SCREEN_NOT_FOUND`, `ERR_INJURY_CASE_NOT_FOUND`, `ERR_SURVEILLANCE_EXAM_NOT_FOUND`, `ERR_WORK_STATUS_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`) when it does not exist. The one path-addressable resource with no entry in the §5 catalogue is the custody event read at `GET /clinic/custody-events/{custodyEventId}`: a non-existent custody-event id returns `ERR_CUSTODY_EVENT_NOT_FOUND` (HTTP 404). Where a path carries more than one identifier, they are validated left to right and the first missing identifier determines the error. Body-referenced foreign keys are validated for both existence and consistency: a referenced resource must exist and must belong to the same employer aggregate as the rest of the body — a worker must belong to the body's employer, and a child whose parent is an encounter must reference an encounter under the same employer. A body reference that is missing or that crosses employer boundaries is rejected with `ERR_CROSS_EMPLOYER_REFERENCE` (HTTP 404).

### 2.6. Validation Ordering

When several checks could fail on a single request, the system evaluates them in a fixed priority order so that the returned error is deterministic. The order is: first, user-context authentication (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 401); second, role authorization (`ERR_INSUFFICIENT_PERMISSIONS`, 403); third, existence of every resource named in the path (the resource-specific not-found errors, 404); fourth, existence and employer-consistency of body-referenced foreign keys (`ERR_CROSS_EMPLOYER_REFERENCE`, 404); fifth, request-body well-formedness (`ERR_INVALID_REQUEST`, 400) — which covers missing required fields, invalid enum values, negative numbers where non-negative is required, an interval whose `valid_from` is later than its `valid_to`, and a missing `restriction_text` where one is mandatory; sixth, the optimistic-concurrency version check on endpoints that require it (`ERR_STALE_EMPLOYER_VERSION`, 412); and seventh, the target resource's state precondition for the requested transition (the `ERR_..._NOT_...` state errors, 409). Business-rule checks specific to an operation — custody sequencing, MRO assignment, segregation of duties, panel and job-category matching, DOT eligibility, surveillance windows, and payment limits — are evaluated after these foundational layers, within the workflow descriptions in §3. The defining consequence of this ordering is that the concurrency check runs after existence, authorization, and body-shape validation but before any state precondition or business rule.

### 2.7. The Employer Clock and Deterministic Time

Time in this system is not wall-clock time; it is a deterministic, per-employer anchor. Each employer carries a `current_date`, a UTC date that defaults to 1970-01-01 when an employer is created without one. Every time-sensitive determination — surveillance recheck windows, return-to-work validity, invoice issue dates, due dates, and aging — reads this employer-scoped `current_date` rather than the server's real clock. The clock advances only through the administrative clock-control capability of §2.10; nothing else moves it.

Advancing the clock is itself a consequential event. When an employer's `current_date` is moved forward, the system re-evaluates that employer's invoices for aging: any invoice in `ISSUED` or `PARTIALLY_PAID` status whose `due_date` is now earlier than the new `current_date` flips to `OVERDUE`. A partially paid invoice that ages retains its accumulated `paid_cents` while moving to `OVERDUE`. Because the clock advance mutates the employer, it increments the employer's `version`.

### 2.8. Optimistic Concurrency Control on the Employer

Two write operations carry the risk of a client acting on a stale view of an employer, and both are protected by an optimistic-concurrency check keyed on the employer's `version`. In each case the request body must include `expected_employer_version`, carrying the `version` of the employer the client last observed; this field is non-optional on these two endpoints, and no other endpoint accepts it.

The first protected operation is **protocol activation**. A request to activate a protocol must carry `expected_employer_version` matching the owning employer's current `version`. Activation legitimately supersedes any prior active protocol and may flip the employer from `PROSPECT` to `ACTIVE` — both of which advance the employer's `version` — so if another writer has advanced the employer's version since the client last read it, the supplied `expected_employer_version` will no longer match and the activation is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412). This prevents a client from activating a protocol against an employer view it has not observed.

The second protected operation is **invoice issuance**. A request to issue an invoice must carry `expected_employer_version` matching the employer's current `version`. Issuance marks line-item encounters as billed and recomputes the employer's outstanding balance, both of which advance the employer's `version`; a later issuance whose `expected_employer_version` is outdated would consume encounters that a prior issuance already billed, so it is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412). Frame both rules as stale-view rejection: the version mismatch, not the timing of requests, is what triggers the refusal.

### 2.9. Monetary Precision and Rounding

All monetary amounts in the system are integer cents — employer balances, panel prices, encounter billable amounts, invoice subtotals, discounts, totals, and payments. Where a calculation produces a non-integer intermediate (specifically the volume discount on an invoice, which multiplies a subtotal by a fractional rate), the result is rounded to whole cents using the round-half-up method, and rounding is applied exactly once at the point the rule specifies. No per-line-item rounding is performed. Day counts, decibel thresholds, and fit factors are integers and are not rounded.

### 2.10. Administrative Clock Control

An administrative, test-driving capability lets a `ClinicAdmin` set an employer's deterministic clock. The caller supplies the target `employer_id` and a `to_iso8601` date, and the system assigns that date to the employer's `current_date`, then runs the overdue re-evaluation described in §2.7 across that employer's invoices and increments the employer's `version`. This capability returns the updated employer. It is the only mechanism that advances an employer's clock.

## 3. Business Logic & Workflows

### 3.1. Establishing an Employer Account and Its Protocol

The lifecycle begins when a `ClinicAdmin` opens an **Employer** account by supplying the employer's `legal_name`, the operator id of the Medical Review Officer who will adjudicate this employer's regulated drug screens as `mro_user_id`, and optionally a `dot_regulated` flag (defaulting to false, indicating whether the employer operates positions regulated under federal DOT / 49 CFR Part 40 rules), the invoice payment terms `net_terms_days` (defaulting to 30), and an initial `current_date` (defaulting to 1970-01-01). A freshly created employer starts in `PROSPECT` status with `account_status` set accordingly, a zero `outstanding_balance_cents`, and the version-tracked audit fields. While an employer is in `PROSPECT`, it cannot yet host clinical work — encounter scheduling requires an active account.

A `ClinicAdmin` then drafts a testing **Protocol** for the employer. A protocol is created in `DRAFT` status against an `employer_id`, with an `effective_date` and a list of `panels`. Each panel is an object naming a `panel_code` (one of `PHYSICAL`, `DRUG_DOT`, `DRUG_NON_DOT`, `AUDIOMETRIC`, or `RESPIRATOR_FIT`), the `required_for_job_category` string that gates which workers the panel applies to, a `price_cents` amount (which must be zero or greater), and a `recheck_interval_days` value (zero or greater, where zero denotes a one-time panel with no recurring recheck). At most one protocol per employer may be `ACTIVE` at any time.

Activation, performed by a `ClinicAdmin`, moves a protocol from `DRAFT` to `ACTIVE` and is the pivotal setup event. Activation is permitted only when the protocol is currently `DRAFT`; otherwise it is rejected with `ERR_PROTOCOL_NOT_DRAFT`. Before activation succeeds, the protocol's panels must be non-empty (otherwise `ERR_PROTOCOL_EMPTY_PANELS`), no `panel_code` may appear more than once in the panel list (otherwise `ERR_DUPLICATE_PANEL_CODE`), and if the owning employer is DOT-regulated the panel list must include a `DRUG_DOT` panel (otherwise `ERR_DOT_PANEL_REQUIRED`). The activation request also carries `expected_employer_version` and is subject to the stale-employer-version rejection of §2.8. When activation succeeds, the protocol's `status` becomes `ACTIVE`; any other protocol for the same employer that was `ACTIVE` is cascaded to `RETIRED` (a retired protocol's own retirement side effects fire, and it is no longer selectable for new encounters, though encounters that already snapshotted it keep that snapshot); if the employer was in `PROSPECT`, it cascades to `ACTIVE`; and the employer's `version` increments by one. The transition of the prior active protocol to `RETIRED` also happens automatically whenever a newer protocol for the same employer is activated — a retired protocol simply ceases to be selectable while existing encounters retain their snapshotted `protocol_id`.

### 3.2. Employer Account Lifecycle and Closure

A `ClinicAdmin` governs the rest of the employer lifecycle. An `ACTIVE` employer may be suspended, which sets `account_status` to `SUSPENDED` and blocks new encounter scheduling for as long as it lasts; suspension requires the employer to be `ACTIVE`, otherwise `ERR_EMPLOYER_NOT_ACTIVE`. A `SUSPENDED` employer may be reactivated back to `ACTIVE`; reactivation requires the employer to be `SUSPENDED`, otherwise `ERR_EMPLOYER_NOT_SUSPENDED`.

Closing an account is the terminal step and is guarded by three preconditions evaluated together. The employer must be either `ACTIVE` or `SUSPENDED` (otherwise `ERR_EMPLOYER_NOT_CLOSABLE`); its `outstanding_balance_cents` must be exactly zero (otherwise `ERR_EMPLOYER_HAS_BALANCE`); and there must be no encounter for the employer in any of the in-flight states `SCHEDULED`, `IN_PROGRESS`, or `PENDING_RESULTS` (otherwise `ERR_OPEN_ENCOUNTERS_EXIST`). When all three hold, `account_status` becomes `CLOSED`, which is terminal. The promotion from `PROSPECT` to `ACTIVE` is never performed directly; it happens only as the cascade from a first protocol activation, and it is a no-op if the employer is already `ACTIVE`.

### 3.3. Registering Workers and Scheduling Encounters

A worker is registered under an employer by a `ClinicAdmin` or a `Clinician`, supplying the `employer_id`, the worker's `full_name`, a `job_category`, and a `dob` (date of birth). A new **Worker** starts with `hire_status` of `CANDIDATE`; this field later reflects the latest non-rescinded clearance determination on the worker, settling to `CLEARED` or `DISQUALIFIED` as encounters complete.

Scheduling an **Encounter**, also performed by a `ClinicAdmin` or `Clinician`, is where the four pipelines diverge. The caller supplies the billing `employer_id`, the `worker_id` of the worker to be seen, the `encounter_type` (one of `PHYSICAL`, `DRUG_SCREEN`, `INJURY`, or `SURVEILLANCE`), and, for every type except injury, the `panel_code` that selects which protocol panel applies. For an `INJURY` encounter the `panel_code` must be omitted; if a `panel_code` carrying one of the recognized panel-code values is nonetheless supplied for an `INJURY` encounter, that is treated as the encounter_type/panel_code consistency mismatch described below and rejected with `ERR_PANEL_NOT_IN_PROTOCOL` rather than as a body-shape error. At scheduling time the system snapshots the employer's currently `ACTIVE` protocol onto the encounter as `protocol_id`, pins the scheduling clinician's identity as `clinician_user_id`, and sets the encounter `status` to `SCHEDULED` with `billable_amount_cents` at 0 and `is_billed` false.

Several referential rules guard encounter creation. Scheduling requires the billing employer to be `ACTIVE`: an employer in `PROSPECT`, `SUSPENDED`, or `CLOSED` cannot host clinical work, and a scheduling request against such an employer is rejected with `ERR_EMPLOYER_NOT_ACTIVE`. This employer-status check is evaluated after the body-referenced foreign-key and body-shape checks but before the panel-consistency, job-category, DOT-eligibility, and surveillance-window business rules below. The `encounter_type` and `panel_code` must be mutually consistent and the chosen `panel_code` must be present in the employer's active protocol: an `INJURY` carries no panel code, a `PHYSICAL` must use the `PHYSICAL` panel, a `DRUG_SCREEN` must use either `DRUG_DOT` or `DRUG_NON_DOT`, and a `SURVEILLANCE` must use either `AUDIOMETRIC` or `RESPIRATOR_FIT`; a mismatch or a panel code absent from the active protocol is rejected with `ERR_PANEL_NOT_IN_PROTOCOL`. For every non-injury encounter, the worker's `job_category` must match the chosen panel's `required_for_job_category`, or the request is rejected with `ERR_JOB_CATEGORY_PANEL_MISMATCH` (this check is skipped for injury). A `DRUG_DOT` encounter may only be scheduled when the employer's `dot_regulated` is true; scheduling a DOT drug screen for a non-DOT employer is rejected with `ERR_DOT_NOT_ALLOWED`. For a `SURVEILLANCE` encounter, the system enforces a recheck window: if a prior `FINALIZED` surveillance exam of the same `exam_kind` exists for the same worker, and the number of days between that prior exam and the employer's `current_date` has not yet reached the panel's `recheck_interval_days`, the new encounter is rejected with `ERR_SURVEILLANCE_TOO_EARLY` as scheduled too early. The reference date of "that prior exam" is the employer's `current_date` captured at the moment the prior exam was finalized, and the elapsed day count is `current_date` minus that captured finalization date; the window is enforced only when the panel's `recheck_interval_days` is greater than zero (a `recheck_interval_days` of zero — a one-time panel — imposes no window and never triggers `ERR_SURVEILLANCE_TOO_EARLY`).

After an encounter is scheduled, a `Clinician` checks it in, advancing it from `SCHEDULED` to `IN_PROGRESS`. Check-in requires the encounter to be `SCHEDULED` (otherwise `ERR_ENCOUNTER_NOT_SCHEDULED`) and the employer to be `ACTIVE` (otherwise `ERR_EMPLOYER_NOT_ACTIVE`). For the three result-bearing types, the act of creating the matching result entity moves the encounter automatically from `IN_PROGRESS` to `PENDING_RESULTS`: creating a `DrugScreen` does this for a `DRUG_SCREEN` encounter, creating an `InjuryCase` does it for an `INJURY` encounter, and creating a `SurveillanceExam` does it for a `SURVEILLANCE` encounter. Result-entity creation therefore requires the parent encounter to be `IN_PROGRESS`; creating a `DrugScreen`, `InjuryCase`, or `SurveillanceExam` against an encounter in any other status is rejected with `ERR_ENCOUNTER_NOT_SCHEDULED`. A `PHYSICAL` encounter has no result entity and never enters `PENDING_RESULTS`; it goes from `IN_PROGRESS` directly to `COMPLETED`.

### 3.4. Completing, Cancelling, and Voiding Encounters

Completion is performed by a `Clinician` and takes two distinct forms; which form runs is selected by the encounter's current status, not by its `encounter_type`. An encounter in `IN_PROGRESS` follows the direct-completion path, and an encounter in `PENDING_RESULTS` follows the result-completion path; an encounter in any other status is treated by type, taking the direct-completion path's type error when it is `PHYSICAL` and the result-completion path's type error otherwise. A `PHYSICAL` encounter completes directly from `IN_PROGRESS`: this direct-completion path requires `encounter_type` to be `PHYSICAL` (otherwise `ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE`) and requires an `ISSUED` clearance to already exist for the encounter (otherwise `ERR_CLEARANCE_REQUIRED`). The three result-bearing types complete from `PENDING_RESULTS`: this result-completion path requires `encounter_type` to be one of `DRUG_SCREEN`, `SURVEILLANCE`, or `INJURY` (otherwise `ERR_ENCOUNTER_TYPE_NOT_RESULT_COMPLETE`), and additionally requires that the result entity has reached its settled state — for a `DRUG_SCREEN` the `DrugScreen.status` must be either `VERIFIED` or `CANCELLED` (otherwise `ERR_DRUG_SCREEN_NOT_VERIFIED`), for a `SURVEILLANCE` the `SurveillanceExam.status` must be `FINALIZED` (otherwise `ERR_EXAM_NOT_FINALIZED`), and for an `INJURY` the `InjuryCase.status` must be `CLOSED` (otherwise `ERR_INJURY_CASE_NOT_CLOSED`). On the result-completion path a `Clearance` in `ISSUED` status is also required, except for `INJURY` encounters, which carry no clearance; a missing clearance where one is required yields `ERR_CLEARANCE_REQUIRED`.

When an encounter reaches `COMPLETED`, its `billable_amount_cents` is set per the encounter-billing rule (described in §3.9) and, for every type that carries a clearance, the worker's `hire_status` is cascaded from that clearance's determination: a `FIT` determination sets the worker to `CLEARED`, a `NOT_FIT` determination sets the worker to `DISQUALIFIED`, and a `FIT_WITH_RESTRICTIONS` determination sets the worker to `CLEARED`. An `INJURY` encounter, which has no clearance, performs no such cascade.

An encounter may be cancelled by a `Clinician` while it is in `SCHEDULED` or `IN_PROGRESS` status (otherwise `ERR_ENCOUNTER_NOT_CANCELLABLE`); cancellation sets the `status` to `CANCELLED` and leaves `billable_amount_cents` at 0. A completed encounter may be voided by a `ClinicAdmin`, but only when the encounter is `COMPLETED` (otherwise `ERR_ENCOUNTER_NOT_VOIDABLE`) and its `is_billed` flag is false (otherwise `ERR_ENCOUNTER_ALREADY_BILLED`). Voiding sets `status` to `VOIDED`, resets `billable_amount_cents` to 0, cascades any `ISSUED` clearance on the encounter to `RESCINDED`, and — as a transitive consequence of that rescission — reverts the worker's `hire_status` to `CANDIDATE` if it had been set from the clearance now being rescinded.

### 3.5. The Drug-Screen Pipeline and Chain of Custody

A drug screen is the most intricate pipeline. After a `DRUG_SCREEN` encounter is checked in, a `Clinician` or `Collector` creates the **DrugScreen** by supplying the `encounter_id` and the collector's attestation `specimen_seal_intact` (whether the specimen seal was intact at lab receipt). On creation the screen starts in `AWAITING_COLLECTION`, derives `is_dot` as true exactly when the encounter's `panel_code` is `DRUG_DOT`, denormalizes the `employer_id` from the encounter for MRO routing, and moves the parent encounter to `PENDING_RESULTS`. The screen also tracks a `lab_result`, an `mro_verified_result`, an `mro_user_id`, and a `recollection_count` (which starts at 0).

Each step in the screen's journey is recorded as an append-only **CustodyEvent** carrying the `drug_screen_id`, a `step`, an optional `note`, the recording operator's `actor_user_id`, and a monotonic per-screen `seq` index that starts at 1 and defines custody ordering. A `Collector` appends custody events; the recognized `step` values are `COLLECT`, `SEAL`, `SHIP`, `LAB_RECEIVE`, `LAB_REPORT`, and `MRO_RECEIVE`. Of these, only `COLLECT`, `SEAL`, `SHIP`, and `LAB_RECEIVE` may be appended directly through `POST /clinic/custody-events`; the `LAB_REPORT` and `MRO_RECEIVE` events are emitted automatically as side effects of the record-lab-result and MRO-receive action endpoints, and a direct `POST /clinic/custody-events` carrying `step` of `LAB_REPORT` or `MRO_RECEIVE` is rejected with `ERR_CUSTODY_SEQUENCE_VIOLATION`. The canonical custody sequence is `COLLECT`, then optionally `SEAL` and `SHIP`, then `LAB_RECEIVE`. The very first custody step must be `COLLECT`, which moves an `AWAITING_COLLECTION` screen to `COLLECTED` and appends the event; a screen that is not `AWAITING_COLLECTION` for this step yields `ERR_DRUG_SCREEN_NOT_AWAITING_COLLECTION`, and a non-`COLLECT` first step is rejected with `ERR_CUSTODY_SEQUENCE_VIOLATION` as an out-of-order custody step. The first-step-must-be-`COLLECT` ordering check is evaluated before the per-step screen-state precondition, so a non-`COLLECT` first step yields `ERR_CUSTODY_SEQUENCE_VIOLATION` rather than the step's own state error. While the screen is `COLLECTED`, the optional `SEAL` and `SHIP` events may be recorded without changing the screen's status. The `LAB_RECEIVE` step advances a `COLLECTED` screen to `AT_LAB`; it requires the screen to be `COLLECTED` (otherwise `ERR_DRUG_SCREEN_NOT_COLLECTED`) and requires that the steps recorded so far form a valid prefix of the sequence `COLLECT`, `SEAL`, `SHIP`, `LAB_RECEIVE` — `SEAL` and `SHIP` are optional but may not appear after `LAB_RECEIVE`. Any custody step recorded out of this canonical order is rejected with `ERR_CUSTODY_SEQUENCE_VIOLATION`.

Once the specimen is at the lab, a `Clinician` records the lab result, advancing the screen from `AT_LAB` to `LAB_REPORTED`; this requires the screen to be `AT_LAB` (otherwise `ERR_DRUG_SCREEN_NOT_AT_LAB`) and a `lab_result` value of `NEGATIVE`, `NON_NEGATIVE`, or `REJECTED_FOR_TESTING`. Recording the lab result also appends a `LAB_REPORT` custody event.

### 3.6. MRO Review, Segregation of Duties, and the Recollection Cycle

The Medical Review Officer adjudicates the reported screen, and the integrity of that adjudication rests on two access rules enforced on every MRO action. First, the acting operator's `X-User-ID` must equal the owning employer's assigned `mro_user_id`; an operator who is not the assigned MRO is rejected with `ERR_MRO_NOT_ASSIGNED`. Second, for the receive and verify actions, the acting MRO's `X-User-ID` must differ from the encounter's pinned `clinician_user_id`; an MRO who is also the encounter's clinician is rejected with `ERR_SEGREGATION_OF_DUTIES`. The MRO-assignment check applies to MRO receive, MRO verify, and order-recollection; the segregation-of-duties check applies to MRO receive and MRO verify.

The MRO first receives the screen, advancing it from `LAB_REPORTED` to `MRO_REVIEW`; this requires the screen to be `LAB_REPORTED` (otherwise `ERR_DRUG_SCREEN_NOT_LAB_REPORTED`), and on success appends an `MRO_RECEIVE` custody event and pins the acting operator's id as the screen's `mro_user_id`.

From `MRO_REVIEW` the screen has three exits, all reserved to the MRO. Verifying with a non-cancelled determination supplies an `mro_verified_result` of `NEGATIVE`, `POSITIVE`, or `REFUSAL` and advances the screen to `VERIFIED`; it requires the screen to be `MRO_REVIEW` (otherwise `ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW`). The verified result must be consistent with the lab result: if `lab_result` is `NEGATIVE`, the `mro_verified_result` must be `NEGATIVE`, and if `lab_result` is `REJECTED_FOR_TESTING`, a verification to anything other than cancelled is inconsistent — either inconsistency is rejected with `ERR_MRO_RESULT_INCONSISTENT`. Verifying with a cancelled determination supplies `mro_verified_result` of `CANCELLED` and moves the screen to `CANCELLED`, recording `mro_verified_result` as `CANCELLED`; `CANCELLED` is a verified-equivalent terminal that satisfies encounter completion just as `VERIFIED` does. Ordering a recollection is the third exit and moves the screen from `MRO_REVIEW` to `RECOLLECT_ORDERED`; it requires the screen to be `MRO_REVIEW` (otherwise `ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW`), it is justified only when `specimen_seal_intact` is false or `lab_result` is `REJECTED_FOR_TESTING` (otherwise `ERR_RECOLLECTION_NOT_JUSTIFIED`), and it is permitted only while `recollection_count` is less than 2 (otherwise `ERR_RECOLLECTION_LIMIT_REACHED`). Ordering a recollection adds one to `recollection_count`.

Immediately after a recollection is ordered, the system automatically returns the screen from `RECOLLECT_ORDERED` to `AWAITING_COLLECTION`, resets both `lab_result` and `mro_verified_result` to null, and restarts the chain of custody so that fresh `COLLECT` and subsequent custody events are required. A screen may therefore loop from `AWAITING_COLLECTION` through `MRO_REVIEW` and back up to two times before the recollection limit halts further loops.

### 3.7. Injury Cases, OSHA Recordability, and Return-to-Work

An **InjuryCase** is created by a `Clinician` for an `INJURY` encounter, supplying the `encounter_id`, the `injury_date` (which must be on or before the employer's `current_date`; an `injury_date` later than `current_date` is rejected with `ERR_INVALID_REQUEST`), the `treatment_level` (one of `FIRST_AID`, `MEDICAL_TREATMENT`, `LOST_TIME`, `RESTRICTED_DUTY`, or `FATALITY`), and optionally `days_away` and `days_restricted` (each a calendar-day count of zero or greater, defaulting to 0). On creation the case starts in `OPEN`, denormalizes its `employer_id`, computes its OSHA recordability fields `is_osha_recordable` and `osha_column` (per §3.10), and moves the parent encounter to `PENDING_RESULTS`. An injury case may be reopened from `CLOSED` back to `OPEN` by a `Clinician`, provided the case is `CLOSED` (otherwise `ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN`) and the parent encounter is not yet `COMPLETED` or `VOIDED` (otherwise `ERR_ENCOUNTER_LOCKED`); each reopen permits a fresh chain of work-status notes.

Return-to-work is managed through **WorkStatus** notes, added by a `Clinician` against an `injury_case_id`. Each note carries a `disposition` (one of `FULL_DUTY`, `MODIFIED_DUTY`, or `OFF_WORK`), an optional `restriction_text` that is required when the disposition is `MODIFIED_DUTY`, and an inclusive validity window defined by `valid_from` and `valid_to` (where `valid_to` must be on or after `valid_from`). Each note denormalizes its `employer_id` and carries a `superseded` flag that starts false. Adding a note drives the case's state: from `OPEN`, a `MODIFIED_DUTY` or `OFF_WORK` disposition moves the case to `RTW_PENDING`, while a `FULL_DUTY` disposition moves it directly to `CLOSED`; from `RTW_PENDING`, a `FULL_DUTY` disposition moves the case to `CLOSED`. A `FULL_DUTY` note may therefore be added while the case is either `OPEN` or `RTW_PENDING`, and a `FULL_DUTY` note against a case in any other status (i.e. `CLOSED`) is rejected with `ERR_INJURY_CASE_NOT_OPEN`. A `MODIFIED_DUTY` or `OFF_WORK` note requires the case to be `OPEN`, otherwise `ERR_INJURY_CASE_NOT_OPEN`. (The `ERR_INJURY_CASE_NOT_RTW_PENDING` identifier is reserved in the catalogue for the RTW_PENDING precondition but is not reached by this work-status creation path.) Every work-status creation supersedes overlapping prior notes on the same case (per §3.11) and triggers recomputation of the case's `is_osha_recordable` and `osha_column`.

### 3.8. Surveillance Exams and Clearances

A **SurveillanceExam** is created by a `Clinician` for a `SURVEILLANCE` encounter, supplying the `encounter_id` and the measurements appropriate to the exam kind. The exam's `exam_kind` is derived from the encounter's `panel_code` — `AUDIOMETRIC` or `RESPIRATOR_FIT`. On creation the exam starts in `SCHEDULED`, denormalizes its `worker_id` and `employer_id` from the encounter, and moves the parent encounter to `PENDING_RESULTS`. The audiometric measurements are `baseline_threshold_db` and `current_threshold_db` (both in decibels); the respirator-fit measurements are `fit_factor` and a `respirator_class` of either `HALF_MASK` or `FULL_FACEPIECE`.

A `Clinician` records the exam, advancing it from `SCHEDULED` to `RECORDED` and computing its `outcome` (per §3.12). Recording requires the exam to be `SCHEDULED` (otherwise `ERR_EXAM_NOT_SCHEDULED`) and requires the measurements for the exam kind to be present: an `AUDIOMETRIC` exam needs both `baseline_threshold_db` and `current_threshold_db`, while a `RESPIRATOR_FIT` exam needs both `fit_factor` and `respirator_class`; absent measurements yield `ERR_EXAM_MISSING_MEASUREMENTS`. A recorded exam is finalized by a `Clinician`, moving it from `RECORDED` to `FINALIZED` and requiring the exam to be `RECORDED` (otherwise `ERR_EXAM_NOT_RECORDED`). A surveillance exam may be cancelled by a `Clinician` while it is `SCHEDULED` or `RECORDED` (otherwise `ERR_EXAM_NOT_CANCELLABLE`).

A **Clearance** records the fit-for-duty determination that gates encounter completion for the three clearance-bearing types. A `Clinician` issues a clearance against an `encounter_id` with a `determination` of `FIT`, `FIT_WITH_RESTRICTIONS`, or `NOT_FIT`, and a `restriction_text` that is required when the determination is `FIT_WITH_RESTRICTIONS`. A new clearance is `ISSUED` and denormalizes its `worker_id` and `employer_id` from the encounter. A clearance may be rescinded by a `Clinician`, moving it from `ISSUED` to the terminal `RESCINDED`; rescission requires the clearance to be `ISSUED` (otherwise `ERR_CLEARANCE_NOT_ISSUED`) and requires that the parent encounter is not yet `COMPLETED` (otherwise `ERR_ENCOUNTER_LOCKED`) — rescinding a clearance on a completed encounter happens only through the encounter-void cascade described in §3.4. A direct rescission reverts the worker's `hire_status` to `CANDIDATE` if that status had been set from this clearance.

### 3.9. Encounter Billing and Price Snapshotting

The billable amount of an encounter is fixed at the moment it completes. On reaching `COMPLETED`, an `INJURY` encounter has its `billable_amount_cents` set to 0; every other type has its `billable_amount_cents` set to the `price_cents` of the panel whose `panel_code` equals the encounter's `panel_code`, read from the protocol that was snapshotted onto the encounter at scheduling time. The snapshotted `protocol_id` is authoritative here — not the employer's current active protocol. If the employer activated a newer protocol that re-priced the same panel code after this encounter was scheduled, the encounter still bills at the snapshotted price; the snapshotted and current prices may legitimately diverge for the same `panel_code`. On a void, the encounter's `billable_amount_cents` is reset to 0. An encounter's `is_billed` flag becomes true once a non-voided invoice references it as a line item.

### 3.10. OSHA Recordability Determination

Whenever an injury case is created, whenever a work-status transition occurs, and whenever `treatment_level`, `days_away`, or `days_restricted` change, the system recomputes the case's `is_osha_recordable` boolean and its `osha_column` enum. The determination walks a fixed precedence top to bottom, and the first matching rule wins — this fixed order is essential. The rules are: if `treatment_level` is `FATALITY`, the case is recordable and `osha_column` is `DEATH`; otherwise, if `days_away` is at least 1, the case is recordable and `osha_column` is `DAYS_AWAY`; otherwise, if `days_restricted` is at least 1 or `treatment_level` is `RESTRICTED_DUTY`, the case is recordable and `osha_column` is `RESTRICTED_TRANSFER`; otherwise, if `treatment_level` is `MEDICAL_TREATMENT`, the case is recordable and `osha_column` is `OTHER_RECORDABLE`; otherwise, if `treatment_level` is `LOST_TIME` with `days_away` equal to 0, the case is recordable and `osha_column` is `OTHER_RECORDABLE`; otherwise — the remaining case, `treatment_level` of `FIRST_AID` — the case is not recordable and `osha_column` is `NOT_RECORDABLE`. Because precedence is strict, an injury with both at least 1 day away and at least 1 day restricted is logged under `DAYS_AWAY`, the more severe column, not under `RESTRICTED_TRANSFER`.

### 3.11. Work-Status Supersession

When a new work-status note is created on an injury case, it supersedes every existing non-superseded note on the same case whose inclusive validity window overlaps the new note's window. Two closed intervals overlap when the existing note's `valid_from` is on or before the new note's `valid_to` and the new note's `valid_from` is on or before the existing note's `valid_to`. Because the intervals are closed, two notes that merely touch at a single boundary day — where the existing note's `valid_to` equals the new note's `valid_from` — do overlap, and the existing note is superseded. Existing notes are evaluated in `created_at` ascending order, and each overlapping note has its `superseded` flag set to true. The new note itself is never superseded at the moment it is created.

### 3.12. Surveillance Outcome Determination

When a surveillance exam is recorded, its `outcome` is computed from the measurements. For an `AUDIOMETRIC` exam, the shift in hearing is the `current_threshold_db` minus the `baseline_threshold_db`; if that shift is at least 10 decibels the outcome is `STS` (a standard threshold shift), and otherwise — including a zero or negative shift — the outcome is `PASS`. For a `RESPIRATOR_FIT` exam, the required minimum fit factor depends on the respirator class: a `HALF_MASK` requires a fit factor of at least 100, and a `FULL_FACEPIECE` requires a fit factor of at least 500; if the measured `fit_factor` meets or exceeds the required minimum the outcome is `PASS`, and otherwise it is `FAIL`.

### 3.13. Invoicing, Payments, and the Employer Balance

A `ClinicAdmin` creates a **DRAFT Invoice** for an employer over a billing period, supplying the `employer_id`, an inclusive `period_start`, and an inclusive `period_end` (which must be on or after `period_start`). On draft creation the system selects the line items and computes the totals. Line-item selection includes every encounter for the employer that is `COMPLETED`, whose `is_billed` is false, whose `billable_amount_cents` is greater than 0, and whose completion date — the date portion of its `updated_at` at the moment it completed — falls within the inclusive period from `period_start` to `period_end`. Selected encounters are taken in `created_at` ascending order, and their ids are recorded as the invoice's `line_item_encounter_ids`. The `subtotal_cents` is the sum of `billable_amount_cents` over the selected encounters.

A volume discount keyed on the count of selected line items — not on the subtotal amount — is then applied. If the count is fewer than 5 the discount rate is zero; if the count is at least 5 but fewer than 10 the rate is five percent; if the count is 10 or more the rate is ten percent. The `discount_cents` is computed by multiplying `subtotal_cents` by the applicable rate and rounding that single product to whole cents using round-half-up; this rounding is performed exactly once, never per line item. The `total_cents` is then `subtotal_cents` minus `discount_cents` and is never negative. A draft invoice begins with `paid_cents` at 0; its `issue_date` and `due_date` remain null while it is `DRAFT`.

Issuing a draft invoice is performed by a `ClinicAdmin` and carries the `expected_employer_version` for the optimistic-concurrency check of §2.8. Issuance requires the invoice to be `DRAFT` (otherwise `ERR_INVOICE_NOT_DRAFT`) and requires `line_item_encounter_ids` to be non-empty (otherwise `ERR_INVOICE_NO_LINE_ITEMS`). On success the invoice's `status` becomes `ISSUED`, its `issue_date` is set to the employer's `current_date`, its `due_date` is computed as the issue date plus the employer's `net_terms_days`, each line-item encounter has its `is_billed` flag set to true, the employer's `outstanding_balance_cents` is recomputed, and the employer's `version` increments by one. A draft invoice that is never issued may instead be voided by a `ClinicAdmin`, which requires it to be `DRAFT` (otherwise `ERR_INVOICE_NOT_VOIDABLE`) and sets its `status` to `VOIDED`.

Payments are applied by a `ClinicAdmin` against an `amount_cents`. A payment is allowed only when the invoice is in a payable state — `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID` (otherwise `ERR_INVOICE_NOT_PAYABLE`) — and the amount must be positive and must not carry the running total past the invoice total: that is, `amount_cents` must be greater than 0 and the sum of the existing `paid_cents` and `amount_cents` must be at most `total_cents`, otherwise the payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. The payment adds `amount_cents` to `paid_cents`. If the new `paid_cents` is still below `total_cents` the invoice becomes `PARTIALLY_PAID`; if the new `paid_cents` equals `total_cents` the invoice becomes `PAID` (and this final settlement may happen as a single full payment directly from `ISSUED` as well). Every payment recomputes the employer's `outstanding_balance_cents`.

The employer's `outstanding_balance_cents` is, at all times, the sum over the employer's invoices in `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID` status of that invoice's `total_cents` minus its `paid_cents`. Invoices in `DRAFT`, `VOIDED`, or `PAID` status contribute nothing. This balance is recomputed on invoice issuance, on every payment, on void, and on the clock-driven overdue flips described in §2.7, and because it is a derived field its recomputation mutates the employer. As described in §2.7, advancing the clock past an invoice's `due_date` flips an `ISSUED` or `PARTIALLY_PAID` invoice to `OVERDUE` while leaving its `paid_cents` intact and keeping it counted in the outstanding balance.

## 4. Endpoint Definitions

All endpoints are mounted under the `/clinic` prefix, except the administrative clock-control endpoint. Endpoints that create a new resource return HTTP 201 with the created resource; endpoints that modify or transition an existing resource return HTTP 200 with the updated resource; list and read endpoints return HTTP 200. Request bodies, response shapes, and side effects for each endpoint are specified in the §3 workflow narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set` | Set an employer's deterministic current date; evaluate overdue flips | ClinicAdmin |
| POST | `/clinic/employers` | Create an employer account | ClinicAdmin |
| GET | `/clinic/employers` | List employers | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/employers/{employerId}` | Get an employer | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/employers/{employerId}/suspend` | Suspend an employer account | ClinicAdmin |
| POST | `/clinic/employers/{employerId}/reactivate` | Reactivate a suspended employer | ClinicAdmin |
| POST | `/clinic/employers/{employerId}/close` | Close an employer account | ClinicAdmin |
| POST | `/clinic/protocols` | Create a draft protocol with panels | ClinicAdmin |
| GET | `/clinic/protocols` | List protocols (filter by employer, status) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/protocols/{protocolId}` | Get a protocol | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/protocols/{protocolId}/activate` | Activate a draft protocol | ClinicAdmin |
| POST | `/clinic/workers` | Create a worker | ClinicAdmin, Clinician |
| GET | `/clinic/workers` | List workers (filter by employer, job category) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/workers/{workerId}` | Get a worker | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/encounters` | Schedule an encounter; snapshot the active protocol | ClinicAdmin, Clinician |
| GET | `/clinic/encounters` | List encounters (filter by employer, worker, protocol, status, type) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/encounters/{encounterId}` | Get an encounter | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/encounters/{encounterId}/check-in` | Check in an encounter | Clinician |
| POST | `/clinic/encounters/{encounterId}/complete` | Complete an encounter | Clinician |
| POST | `/clinic/encounters/{encounterId}/cancel` | Cancel an encounter | Clinician |
| POST | `/clinic/encounters/{encounterId}/void` | Void a completed, unbilled encounter | ClinicAdmin |
| POST | `/clinic/clearances` | Issue a fit-for-duty clearance | Clinician |
| GET | `/clinic/clearances` | List clearances (filter by encounter, employer, worker) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/clearances/{clearanceId}` | Get a clearance | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/clearances/{clearanceId}/rescind` | Rescind an issued clearance | Clinician |
| POST | `/clinic/drug-screens` | Create the drug screen for a drug-screen encounter | Clinician, Collector |
| GET | `/clinic/drug-screens` | List drug screens (filter by encounter, employer, status) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/drug-screens/{drugScreenId}` | Get a drug screen | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/custody-events` | Append a chain-of-custody event | Collector |
| GET | `/clinic/custody-events` | List custody events (filter by drug screen; ordered by seq) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/custody-events/{custodyEventId}` | Get a single custody event | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/drug-screens/{drugScreenId}/lab-result` | Record the lab result | Clinician |
| POST | `/clinic/drug-screens/{drugScreenId}/mro-receive` | MRO receives the screen | MRO |
| POST | `/clinic/drug-screens/{drugScreenId}/mro-verify` | MRO final determination | MRO |
| POST | `/clinic/drug-screens/{drugScreenId}/order-recollection` | MRO orders a recollection | MRO |
| POST | `/clinic/injury-cases` | Create the injury case for an injury encounter | Clinician |
| GET | `/clinic/injury-cases` | List injury cases (filter by encounter, employer, status) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/injury-cases/{injuryCaseId}` | Get an injury case | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/injury-cases/{injuryCaseId}/reopen` | Reopen a closed injury case | Clinician |
| POST | `/clinic/work-statuses` | Add a work-status / return-to-work note | Clinician |
| GET | `/clinic/work-statuses` | List work statuses (filter by injury case, employer) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/work-statuses/{workStatusId}` | Get a work status | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/surveillance-exams` | Create the surveillance exam for a surveillance encounter | Clinician |
| GET | `/clinic/surveillance-exams` | List surveillance exams (filter by encounter, employer, worker, status) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/surveillance-exams/{examId}` | Get a surveillance exam | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/surveillance-exams/{examId}/record` | Record measurements and compute outcome | Clinician |
| POST | `/clinic/surveillance-exams/{examId}/finalize` | Finalize a recorded exam | Clinician |
| POST | `/clinic/surveillance-exams/{examId}/cancel` | Cancel a surveillance exam | Clinician |
| POST | `/clinic/invoices` | Create a draft invoice; select line items and compute totals | ClinicAdmin |
| GET | `/clinic/invoices` | List invoices (filter by employer, status) | ClinicAdmin, Clinician, Collector, MRO |
| GET | `/clinic/invoices/{invoiceId}` | Get an invoice | ClinicAdmin, Clinician, Collector, MRO |
| POST | `/clinic/invoices/{invoiceId}/issue` | Issue a draft invoice (OCC on employer) | ClinicAdmin |
| POST | `/clinic/invoices/{invoiceId}/payments` | Apply a payment to an invoice | ClinicAdmin |
| POST | `/clinic/invoices/{invoiceId}/void` | Void a draft invoice | ClinicAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives that govern the operations they guard; the table below lists each error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_EMPLOYER_NOT_FOUND` | 404 |
| `ERR_PROTOCOL_NOT_FOUND` | 404 |
| `ERR_WORKER_NOT_FOUND` | 404 |
| `ERR_ENCOUNTER_NOT_FOUND` | 404 |
| `ERR_DRUG_SCREEN_NOT_FOUND` | 404 |
| `ERR_INJURY_CASE_NOT_FOUND` | 404 |
| `ERR_SURVEILLANCE_EXAM_NOT_FOUND` | 404 |
| `ERR_WORK_STATUS_NOT_FOUND` | 404 |
| `ERR_CLEARANCE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_CROSS_EMPLOYER_REFERENCE` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PANEL_NOT_IN_PROTOCOL` | 409 |
| `ERR_JOB_CATEGORY_PANEL_MISMATCH` | 409 |
| `ERR_MRO_RESULT_INCONSISTENT` | 409 |
| `ERR_RECOLLECTION_NOT_JUSTIFIED` | 409 |
| `ERR_STALE_EMPLOYER_VERSION` | 412 |
| `ERR_EMPLOYER_NOT_ACTIVE` | 409 |
| `ERR_EMPLOYER_NOT_SUSPENDED` | 409 |
| `ERR_EMPLOYER_NOT_CLOSABLE` | 409 |
| `ERR_EMPLOYER_HAS_BALANCE` | 409 |
| `ERR_OPEN_ENCOUNTERS_EXIST` | 409 |
| `ERR_PROTOCOL_NOT_DRAFT` | 409 |
| `ERR_PROTOCOL_EMPTY_PANELS` | 409 |
| `ERR_DUPLICATE_PANEL_CODE` | 409 |
| `ERR_DOT_PANEL_REQUIRED` | 409 |
| `ERR_ENCOUNTER_NOT_SCHEDULED` | 409 |
| `ERR_ENCOUNTER_NOT_CANCELLABLE` | 409 |
| `ERR_ENCOUNTER_NOT_VOIDABLE` | 409 |
| `ERR_ENCOUNTER_ALREADY_BILLED` | 409 |
| `ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE` | 409 |
| `ERR_ENCOUNTER_TYPE_NOT_RESULT_COMPLETE` | 409 |
| `ERR_CLEARANCE_REQUIRED` | 409 |
| `ERR_ENCOUNTER_LOCKED` | 409 |
| `ERR_DRUG_SCREEN_NOT_AWAITING_COLLECTION` | 409 |
| `ERR_DRUG_SCREEN_NOT_COLLECTED` | 409 |
| `ERR_DRUG_SCREEN_NOT_AT_LAB` | 409 |
| `ERR_DRUG_SCREEN_NOT_LAB_REPORTED` | 409 |
| `ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW` | 409 |
| `ERR_DRUG_SCREEN_NOT_VERIFIED` | 409 |
| `ERR_CUSTODY_SEQUENCE_VIOLATION` | 409 |
| `ERR_MRO_NOT_ASSIGNED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RECOLLECTION_LIMIT_REACHED` | 409 |
| `ERR_INJURY_CASE_NOT_OPEN` | 409 |
| `ERR_INJURY_CASE_NOT_RTW_PENDING` | 409 |
| `ERR_INJURY_CASE_NOT_CLOSED` | 409 |
| `ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN` | 409 |
| `ERR_EXAM_NOT_SCHEDULED` | 409 |
| `ERR_EXAM_NOT_RECORDED` | 409 |
| `ERR_EXAM_NOT_FINALIZED` | 409 |
| `ERR_EXAM_NOT_CANCELLABLE` | 409 |
| `ERR_EXAM_MISSING_MEASUREMENTS` | 409 |
| `ERR_SURVEILLANCE_TOO_EARLY` | 409 |
| `ERR_DOT_NOT_ALLOWED` | 409 |
| `ERR_CLEARANCE_NOT_ISSUED` | 409 |
| `ERR_INVOICE_NOT_DRAFT` | 409 |
| `ERR_INVOICE_NO_LINE_ITEMS` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 402 |

# Registered Apprenticeship Tracking API — Product Requirements Document

## 1. Introduction

Registered apprenticeship is a structured, employer-driven model in which a sponsoring organization commits to training a worker against a published occupational standard while the worker earns a progressively rising wage. This API is the system of record for that commitment as it is recognized by a Department-of-Labor-style registering authority. It captures the entire arc of a program — from the occupational standard and its wage-progression schedule, through the registration of individual apprentices under their supervising journeyworkers, the accumulation and review of on-the-job training hours and related classroom instruction, the demonstration of competency milestones, and finally the issuance of a completion certificate — while continuously enforcing the regulatory invariants that make a program "registered" rather than merely informal.

Three pressures shape every requirement that follows. First, **segregation of duties**: the party that logs training data is never the party that approves it, and the sponsor that builds a program can never self-certify a completion — only the registering agency may. Second, **journeyman-ratio capacity**: a single qualified journeyworker may supervise only a bounded number of apprentices, so registering a new apprentice is a slot-consuming act that must be serialized against concurrent registrations. Third, **auditable, dual-variant progression**: depending on whether a program is hours-based, competency-based, or hybrid, an apprentice's wage step and completion eligibility are computed from entirely different inputs, and every credited hour or attained milestone must trace cleanly back through wage step, wage snapshot, and eligibility. The remainder of this document specifies the contract that upholds these three pressures.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections live directly beneath the `/apprenticeship` mount; there are no nested ownership paths, and entities reference one another through foreign-key fields carried in request bodies.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When a syntactically valid request is attempted by a role that is not permitted to perform that operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles, spelled precisely as follows: `RegistrationAgency`, `Sponsor`, `TrainingCoordinator`, and `Apprentice`.

- The `RegistrationAgency` is the registering authority. It activates and archives programs, completes agreements (thereby issuing completion certificates), and pulls EEO reports. It deliberately cannot log or approve training data — that separation is the core of segregation of duties.
- The `Sponsor` is the sponsoring employer or association. It builds programs and their standards, manages journeyworkers and apprentices, creates and registers agreements, logs on-the-job hours and related instruction, and submits or resubmits milestone attainments. A sponsor cannot approve training data and cannot self-certify completion.
- The `TrainingCoordinator` is the operational reviewer. It approves and rejects on-the-job hours and milestone attainments, and records related instruction. It cannot register apprentices, build programs, or issue completion certificates.
- The `Apprentice` is the registrant. An apprentice may log their own on-the-job sessions for later approval and may read their own training data, but may not approve hours or alter agreements.

Identity binding differs by role and governs how `X-User-ID` relates to persisted data. When `X-User-Role` is `Sponsor`, `X-User-ID` is the `id` of the acting `Sponsor`; ownership checks on any resource that references a `Sponsor` compare the resource's sponsor foreign key to `X-User-ID`. When `X-User-Role` is `Apprentice`, `X-User-ID` is the `id` of the acting `Apprentice`; ownership checks on any resource that references an `Apprentice` compare the resource's apprentice foreign key to `X-User-ID`. When `X-User-Role` is `RegistrationAgency`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `issued_by_user_id` on a `CompletionCertificate` when a completion writes it) but does not compare it to any entity's `id`. When `X-User-Role` is `TrainingCoordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded where a transition demands it but never compared to an entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; it is refreshed on any change to the resource's properties.
- `version` (integer): a server-managed integer that begins at its initial value and increments by one with every modification to the resource. This is the field used for optimistic concurrency control (see §2.9).

Two resources are immutable artifacts and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. The first is the `CompletionCertificate`, which is created exactly once when an agreement completes and is never edited. The second is the `EEOReport`, which is a point-in-time snapshot. For both of these, do not expose an `updated_at` or a `version` field.

### 2.5. The Wage-Progression and Capacity Ledger

Several program-level and agreement-level counters are server-computed and must be kept consistent on every mutation that affects them, rather than supplied by clients. On a program, `active_agreement_count` is the number of agreements for that program currently in `REGISTERED`, `ACTIVE`, or `SUSPENDED`, and `available_apprentice_slots` is the remaining ratio capacity (see §2.6). On a journeyworker, `active_apprentice_count` is the number of agreements in `REGISTERED`, `ACTIVE`, or `SUSPENDED` that name that journeyworker as supervisor. On an agreement, `ojt_hours_completed`, `rti_hours_completed`, `milestones_attained_count`, `current_wage_step`, `current_hourly_wage_cents`, and `completion_eligible` are all derived values.

When a derived counter changes as a side effect of a transition, the owning resource is itself mutated: its `updated_at` is refreshed and, where it carries one, its `version` is incremented. This is what makes the program's slot accounting a serialization point for registration. The cascade chain triggered by crediting or removing on-the-job hours is strictly ordered: the hours total changes first, then the wage step is recomputed, then the hourly wage snapshot is recomputed from the new step, and finally completion eligibility is recomputed. The same downstream chain (wage step → wage snapshot → eligibility) is re-run whenever an approved milestone attainment changes the agreement's competency count.

### 2.6. Journeyman-Ratio Capacity

The journeyman ratio limits how many apprentices the qualified-and-probationary workforce of a sponsor can supervise on a given program, and it determines the `available_apprentice_slots` reported on that program. Capacity is recomputed whenever a program is activated, whenever an agreement is registered, completed, or cancelled, whenever a journeyworker is qualified or deactivated, and on every read of a program (so a `GET` of a program always reflects current capacity).

To compute it for a program and its owning sponsor, first count the sponsor's journeyworkers in `QUALIFIED` status and, separately, the sponsor's journeyworkers in `PROBATIONARY` status. The raw ratio capacity is the qualified count multiplied by the program's `journeyman_ratio`, plus the probationary count multiplied by the program's `journeyman_ratio` multiplied by a probationary weighting factor of one-half; this sum is then rounded down to a whole number. The order is fixed: form that weighted sum and floor it to obtain the ratio capacity, then subtract the program's `active_agreement_count`, then take the larger of zero and that difference. The result is `available_apprentice_slots`, never negative.

### 2.7. Precision and Rounding

Wage snapshots are stored in integer cents. Whenever `current_hourly_wage_cents` is recomputed, multiply the program's `base_journeyworker_wage_cents` by the `wage_pct` of the agreement's current wage step and round the product half-up to the nearest whole cent. Wage step values themselves are whole-number ordinals.

EEO completion rates and demographic distribution percentages have their own rules. The `completion_rate_pct` is rounded half-up to two decimal places. The `gender_distribution_pct` and `race_distribution_pct` maps are whole-percent integers produced by a largest-remainder allocation that always sums to exactly 100 when there is at least one apprentice in the cohort (see §3.8).

### 2.8. Nested Resource Retrieval and Referential Integrity

Although collections are flat, requests still carry resource identifiers — in the path for single-resource reads and state transitions, and in the body for creates. Path identifiers are validated first: if a path identifier does not correspond to an existing resource, the request is rejected with that resource's not-found error (for example `ERR_PROGRAM_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OJT_ENTRY_NOT_FOUND`, `ERR_ATTAINMENT_NOT_FOUND`, `ERR_JOURNEYWORKER_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_WAGE_STEP_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_RTI_RECORD_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_EEO_REPORT_NOT_FOUND`, or the generic `ERR_NOT_FOUND`) before any business rule runs.

On a create that carries foreign-key fields — `program_id`, `sponsor_id`, `apprentice_id`, `journeyworker_id`, `agreement_id`, or `milestone_id` — each referenced resource must exist; a dangling reference is rejected with the corresponding resource's not-found error. A malformed body, a missing required field, or a type or enum mismatch is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Optimistic Concurrency Control on Registration

Registering an apprentice consumes one journeyman-ratio slot and advances the program's `version`. To make slot consumption safe against stale reads, the registration action requires the client to supply `expected_program_version` as a non-optional field carrying the `version` of the parent `ApprenticeshipProgram` that the client last observed. The server compares `expected_program_version` to the program's current `version`. If another registration has advanced the program's `version` since the client read it — meaning the client's view of `available_apprentice_slots` is stale — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This stale-version check is evaluated before the business rules of registration, so a stale caller is turned away before any slot accounting is attempted. Registration is the only endpoint that takes a version field; no other operation accepts one.

### 2.10. Validation Ordering

When several conditions guard a single operation, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. The global order is: (1) presence and well-formedness of the `X-User-ID` and `X-User-Role` headers; (2) role permission for the operation; (3) existence of resources named in the path; (4) existence of foreign-key resources named in the body; (5) the optimistic-concurrency stale-version check on registration; (6) the target resource being in a legal state for the requested transition; and only then (7 and beyond) the operation-specific business rules described in §3, in the order those subsections set out. Pagination-bound checks apply to list endpoints and surface as `ERR_INVALID_PAGINATION`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Its Standards

A `Sponsor` is the root of every training structure. A sponsor record is created with its `legal_name`, its `ein` (an employer identification number in the form of two digits, a hyphen, then seven digits), and a `contact_email`. Sponsor creation is also available to the `RegistrationAgency`, reflecting that either party may onboard a sponsoring organization.

Against a sponsor, a `Sponsor` builds an **apprenticeship program** by supplying the owning `sponsor_id`, the O*NET-SOC `occupation_code` (for example `47-2111.00`), a human-readable `occupation_title`, the `completion_type`, the total `ojt_hours_required`, the total `rti_hours_required`, the fully-qualified journeyworker hourly wage in cents as `base_journeyworker_wage_cents`, and the `journeyman_ratio` — the maximum number of apprentices a single qualified journeyworker may supervise, which must be at least 1. The `completion_type` is one of `HOURS_BASED`, `COMPETENCY_BASED`, or `HYBRID`, and it is the switch that later selects which wage-step and completion variant is authoritative for every agreement under the program. A new program begins in `DRAFT` with `active_agreement_count` at 0 and `available_apprentice_slots` at 0.

While a program is still `DRAFT`, the sponsor populates its wage-progression schedule and its competency milestones. A **wage step** is added by supplying the owning `program_id`, a one-based `step_number` (which must be unique within the program), an `ojt_hours_threshold` — the cumulative approved on-the-job hours at or above which this step applies, which must be zero or greater — and a `wage_pct`, the fraction of the base journeyworker wage paid at this step (for example, 0.65). A **milestone** is added by supplying the owning `program_id`, a one-based `sequence` (unique within the program), a `title`, and an optional `required_for_completion` flag that defaults to true and marks whether attaining the competency is mandatory for competency-based completion. Attempting to create a second wage step with an existing `step_number` for the same program, or a second milestone with an existing `sequence`, is rejected with `ERR_DUPLICATE_RESOURCE`.

A program leaves `DRAFT` only when the `RegistrationAgency` activates it, moving `DRAFT → ACTIVE`. Activation is refused unless the program is in `DRAFT` (otherwise `ERR_PROGRAM_NOT_DRAFT`), at least one wage step exists (otherwise `ERR_NO_WAGE_STEPS`), and among those steps there is one whose `ojt_hours_threshold` is exactly zero — the entry-level base step (otherwise `ERR_NO_BASE_WAGE_STEP`). On activation the status becomes `ACTIVE`, `available_apprentice_slots` is recomputed from current capacity, and the program's `version` increments by one. A program reaches the end of its life when the `RegistrationAgency` archives it, moving `ACTIVE → ARCHIVED`; archiving requires the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`) and requires that no agreement for the program is currently in `REGISTERED`, `ACTIVE`, or `SUSPENDED` (otherwise `ERR_PROGRAM_HAS_OPEN_AGREEMENTS`); on success the status becomes `ARCHIVED` and the `version` increments by one.

### 3.2. The Workforce: Journeyworkers and Apprentices

Supervisors and registrants both belong to a sponsor. A `Sponsor` registers a **journeyworker** by supplying the employing `sponsor_id` and the worker's `full_name`; the journeyworker begins in `PROBATIONARY` status with `active_apprentice_count` at 0. A probationary journeyworker contributes only partial capacity (the one-half probationary weighting of §2.6) and may not yet supervise a registration, because registration requires a `QUALIFIED` supervisor. The sponsor promotes a worker `PROBATIONARY → QUALIFIED`; the promotion is refused unless the worker is `PROBATIONARY` (otherwise `ERR_JOURNEYWORKER_NOT_PROBATIONARY`). Once qualified, the worker's full ratio capacity becomes available on the sponsor's programs on the next capacity computation.

A journeyworker is retired to `INACTIVE` by the sponsor. The deactivation path depends on the current state. From `QUALIFIED`, deactivation requires the worker to be `QUALIFIED` (otherwise `ERR_JOURNEYWORKER_NOT_QUALIFIED`) and requires `active_apprentice_count` to be zero (otherwise `ERR_JOURNEYWORKER_HAS_APPRENTICES`); on success the status becomes `INACTIVE`. From `PROBATIONARY`, deactivation likewise requires `active_apprentice_count` to be zero (otherwise `ERR_JOURNEYWORKER_HAS_APPRENTICES`) and on success moves the worker to `INACTIVE`. In both cases a worker who still supervises any open agreement cannot be deactivated.

A `Sponsor` also creates each **apprentice**, capturing the sponsoring `sponsor_id`, the `full_name`, and the EEO/affirmative-action demographics. The `gender` is one of `MALE`, `FEMALE`, `NONBINARY`, or `UNDISCLOSED`. The `race_ethnicity` is one of `HISPANIC`, `WHITE`, `BLACK`, `ASIAN`, `NATIVE_AMERICAN`, `PACIFIC_ISLANDER`, `TWO_OR_MORE`, or `UNDISCLOSED`. Two affirmative-action flags, `is_veteran` and `has_disability`, default to false when omitted. These demographic fields are never recomputed; they are the raw material for the EEO reporting described in §3.8.

### 3.3. Forming and Registering an Agreement

The **apprentice agreement** is the cross-aggregate record that binds an apprentice, a supervising journeyworker, and a program together. A `Sponsor` drafts an agreement by supplying the `program_id` of the program being registered into, the `apprentice_id` of the registrant, the `journeyworker_id` of the supervising journeyworker, and a `start_date` (an ISO 8601 date that becomes the earliest valid date for any on-the-job session, instruction record, or milestone attainment). On creation the agreement begins in `DRAFT` with `current_wage_step` at 1, `ojt_hours_completed` at 0, `rti_hours_completed` at 0, and `milestones_attained_count` at 0; its `end_date` stays null while the agreement is open and `completion_eligible` is false.

At create time the system enforces sponsor scoping: the supervising journeyworker's `sponsor_id` and the apprentice's `sponsor_id` must both equal the program's `sponsor_id`. If either belongs to a different sponsor, the create is rejected with `ERR_SPONSOR_MISMATCH`.

Registration is the slot-consuming step, and it is where the journeyman ratio bites. A `Sponsor` registers a drafted agreement, advancing it `DRAFT → REGISTERED`. The transition is guarded, in order, by these conditions: the agreement must be in `DRAFT` (otherwise `ERR_AGREEMENT_NOT_DRAFT`); the parent program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`); the supervising journeyworker must be `QUALIFIED` (otherwise `ERR_JOURNEYWORKER_NOT_QUALIFIED`); the supplied `expected_program_version` must match the program's current `version`, checked ahead of the slot rule (otherwise `ERR_STALE_VERSION`, HTTP 412, as detailed in §2.9); and finally the program must have at least one free slot, meaning `available_apprentice_slots` is 1 or greater (otherwise `ERR_JOURNEYMAN_RATIO_EXCEEDED`). On success the agreement becomes `REGISTERED`, the program's `active_agreement_count` increases by one, the supervising journeyworker's `active_apprentice_count` increases by one, the program's `available_apprentice_slots` is recomputed from capacity, and the program's `version` increments by one — that version bump is precisely what invalidates any other caller's stale `expected_program_version`.

A registered agreement is moved into training by the sponsor, advancing `REGISTERED → ACTIVE`; this requires the agreement to be `REGISTERED` (otherwise `ERR_AGREEMENT_NOT_REGISTERED`). Training may be paused: the sponsor suspends an active agreement, moving `ACTIVE → SUSPENDED` (the agreement must be `ACTIVE`, otherwise `ERR_AGREEMENT_NOT_ACTIVE`). A suspended agreement still consumes its ratio slot — it continues to count toward `active_agreement_count` — so suspension does not free capacity. The sponsor reinstates a suspended agreement, moving `SUSPENDED → ACTIVE` (the agreement must be `SUSPENDED`, otherwise `ERR_AGREEMENT_NOT_SUSPENDED`).

Cancellation releases the slot. A `Sponsor` may cancel an agreement that is in `REGISTERED`, `ACTIVE`, or `SUSPENDED`; from any of those three states the agreement moves to `CANCELLED` (any other state yields `ERR_AGREEMENT_NOT_CANCELLABLE`). On cancellation the `end_date` is set to the cancellation date, the program's `active_agreement_count` decreases by one, the supervising journeyworker's `active_apprentice_count` decreases by one, and the program's `available_apprentice_slots` is recomputed.

### 3.4. Logging On-the-Job Training Hours

On-the-job training is recorded one session at a time. A `Sponsor` or the `Apprentice` themself logs a session by supplying the `agreement_id`, the `work_date` (an ISO 8601 date with no time component), a `start_time` and `end_time` expressed as minutes-from-midnight, and the `credited_hours` to apply toward the on-the-job requirement. A newly logged session begins in `PENDING`. The session window governs scheduling overlap; the credited amount is supplied independently and is what eventually accrues to the agreement.

Several checks guard a new on-the-job entry, and they surface distinct errors. The `work_date` must be on or after the agreement's `start_date`, or the entry is rejected with `ERR_DATE_BEFORE_AGREEMENT_START`. The time window must be well-formed: `start_time` must be strictly less than `end_time`, both must lie within 0 through 1440 inclusive, and `credited_hours` must be greater than zero; any violation yields `ERR_INVALID_TIME_RANGE`. The new window must not overlap any other on-the-job entry for the same apprentice on the same `work_date`; windows that merely touch at an endpoint — where one window's end equals the next window's start — are permitted, but any true overlap is rejected with `ERR_APPRENTICE_SESSION_OVERLAP`. Finally, the supervising journeyworker cannot be in two places at once: across all on-the-job entries supervised by the agreement's journeyworker on the same `work_date`, the new window must be separated from every existing window by at least the supervision buffer of fifteen minutes — there must be neither overlap nor a gap smaller than that buffer — or the entry is rejected with `ERR_JOURNEYWORKER_SUPERVISION_CONFLICT`.

A `TrainingCoordinator` — and only a coordinator, never the party that logged the session — reviews each pending entry. Approval moves an entry `PENDING → APPROVED` and requires the entry to be `PENDING` (otherwise `ERR_OJT_ENTRY_NOT_PENDING`) and, as a cross-entity guard, requires the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). On approval the entry's `credited_hours` are added to the agreement's `ojt_hours_completed`, and the cascade chain runs in order: the wage step is recomputed, the hourly wage snapshot is recomputed from the new step, and completion eligibility is recomputed. Rejection moves a pending entry `PENDING → REJECTED` (the entry must be `PENDING`, otherwise `ERR_OJT_ENTRY_NOT_PENDING`) and credits nothing.

Approval is reversible. A coordinator may reopen an approved entry for correction, moving it `APPROVED → PENDING` (the entry must be `APPROVED`, otherwise `ERR_OJT_ENTRY_NOT_APPROVED`). Reopening is the compensating action for approval: it subtracts the entry's `credited_hours` back out of the agreement's `ojt_hours_completed`, restoring the prior total, and then re-runs the identical downstream cascade — wage step, then wage snapshot, then completion eligibility — so the agreement's derived state never drifts.

### 3.5. Recording Related Instruction

Related technical instruction — the classroom complement to on-the-job work — is captured as immutable records. A `Sponsor` or a `TrainingCoordinator` records a session by supplying the `agreement_id`, a `course_code`, a `session_date`, and the `instruction_hours` delivered (a positive number). The record is created directly in `RECORDED` status and is never edited or transitioned thereafter. As a side effect of creation, the supplied `instruction_hours` are added to the agreement's `rti_hours_completed`, and the agreement's completion eligibility is recomputed to reflect the new instruction total.

### 3.6. Demonstrating Competency Milestones

Competency is evidenced through milestone attainments, which form the junction between an agreement and the program's milestones. A `Sponsor` submits an attainment by supplying the `agreement_id`, the `milestone_id` of the competency attained, and the `attained_on` date on which it was demonstrated. A new attainment begins in `SUBMITTED`. Two referential guards apply at submission: the referenced milestone must belong to the agreement's program — its `program_id` must match the agreement's `program_id`, otherwise `ERR_MILESTONE_PROGRAM_MISMATCH` — and the `attained_on` date must be on or after the agreement's `start_date`, otherwise `ERR_DATE_BEFORE_AGREEMENT_START`. Only one outstanding attainment may exist per agreement-and-milestone pair: a second `SUBMITTED` or `APPROVED` attainment for the same milestone on the same agreement is rejected with `ERR_DUPLICATE_RESOURCE`.

A `TrainingCoordinator` adjudicates each submission. Approval moves an attainment `SUBMITTED → APPROVED`, requiring the attainment to be `SUBMITTED` (otherwise `ERR_ATTAINMENT_NOT_SUBMITTED`) and the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). On approval the agreement's `milestones_attained_count` increases by one, after which the downstream cascade — wage step, wage snapshot, completion eligibility — is recomputed in that order. Rejection moves a submission `SUBMITTED → REJECTED`, requiring the attainment to be `SUBMITTED` (otherwise `ERR_ATTAINMENT_NOT_SUBMITTED`). A rejected attainment is not the end of the road: the sponsor resubmits it, moving `REJECTED → SUBMITTED` (the attainment must be `REJECTED`, otherwise `ERR_ATTAINMENT_NOT_REJECTED`), reopening the adjudication cycle.

### 3.7. Wage Steps, Eligibility, and Completion

The authoritative wage step for an agreement is recomputed every time approved on-the-job hours change or an approved milestone count changes, and the program's `completion_type` decides which rule applies. Consider the program's wage steps ordered by ascending `step_number`. For an `HOURS_BASED` program — and likewise for a `HYBRID` program — the current wage step is the highest `step_number` among all steps whose `ojt_hours_threshold` is less than or equal to the agreement's `ojt_hours_completed`; because the comparison is at-or-below, exactly meeting a threshold reaches that step, and if no step qualifies the step is 1. For a `COMPETENCY_BASED` program, the current wage step is the agreement's `milestones_attained_count` clamped into the range from 1 up to the highest `step_number` defined for the program — each approved milestone advances one step, with a floor of 1 and a ceiling at the top step. Whenever `current_wage_step` changes, `current_hourly_wage_cents` is recomputed by multiplying `base_journeyworker_wage_cents` by the selected step's `wage_pct` and rounding half-up to the nearest whole cent, per §2.7.

Completion eligibility, the boolean `completion_eligible`, is likewise variant-driven and recomputed on every approval, rejection, resubmission, or reopen that could change its inputs, as well as on every recorded instruction session. Define three conditions. The hours condition holds when the agreement's `ojt_hours_completed` is at least the program's `ojt_hours_required`. The instruction condition holds when the agreement's `rti_hours_completed` is at least the program's `rti_hours_required`. The competency condition holds when the count of `APPROVED` milestone attainments covering the program's milestones marked `required_for_completion` equals the total number of milestones that carry `required_for_completion` set to true — that is, every mandatory competency has an approved attainment. For an `HOURS_BASED` program, eligibility is the hours condition and the instruction condition both holding; milestones are ignored. For a `COMPETENCY_BASED` program, eligibility is the competency condition and the instruction condition both holding; the on-the-job hour total is ignored. For a `HYBRID` program, all three must hold: hours, instruction, and competency together.

Completion itself is reserved to the `RegistrationAgency`, never the sponsor — this is where self-certification is forbidden. The agency completes an active agreement, moving `ACTIVE → COMPLETED`; the agreement must be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`) and `completion_eligible` must already be true (otherwise `ERR_COMPLETION_REQUIREMENTS_NOT_MET`). On completion the agreement's status becomes `COMPLETED`, its `end_date` is set to the issuance date, the program's `active_agreement_count` decreases by one, the supervising journeyworker's `active_apprentice_count` decreases by one, and the program's `available_apprentice_slots` is recomputed. As a cascade, a `CompletionCertificate` is created exactly once for the agreement, snapshotting the moment of certification: it captures the certified agreement via `agreement_id`, the `program_id`, the program's `occupation_code` at issuance, the agreement's then-current on-the-job total as `certified_ojt_hours` and instruction total as `certified_rti_hours`, and the `issued_by_user_id` recording the `X-User-ID` of the issuing `RegistrationAgency` operator. Completion certificates are read-only artifacts thereafter and are discovered through the certificate listing channel.

### 3.8. EEO and Affirmative-Action Reporting

The registering authority and sponsors need point-in-time equity reports per program. A `RegistrationAgency` or `Sponsor` generates an **EEO report** by supplying the `program_id` and a `cohort_basis`, which is either `REGISTERED_COHORT` or `ACTIVE_COHORT` and selects the denominator for completion-rate computation. The report is an immutable snapshot recording the chosen `cohort_basis`, the `total_apprentices` denominator, the `completed_count`, the `completion_rate_pct`, the `gender_distribution_pct` and `race_distribution_pct` maps, and the `veteran_count` and `disability_count` tallies.

The `completed_count` is the number of the program's agreements in `COMPLETED`. The denominator depends on the cohort. Under `REGISTERED_COHORT` the `total_apprentices` denominator counts every agreement of the program whose status is not `DRAFT` — which includes `CANCELLED` agreements. Under `ACTIVE_COHORT` the denominator counts only agreements in `ACTIVE` or `COMPLETED`, excluding `CANCELLED`, `SUSPENDED`, and `REGISTERED`. The `completion_rate_pct` is the completed count divided by the denominator, multiplied by 100, rounded half-up to two decimal places; when the denominator is zero, the rate is exactly 0.

The two demographic distributions are computed over the distinct apprentices in the chosen cohort, deduplicated by `apprentice_id`, and each is a whole-percent breakdown — by `gender` for one map and by `race_ethnicity` for the other — that must sum to exactly 100. The allocation is by largest remainder, and the order of operations is pinned. Let N be the number of distinct cohort apprentices; if N is zero, every category percent is 0. Otherwise, for each category, first form its exact share as the category's count divided by N multiplied by 100, then round that share down to a whole number (floor it). Sum those floored values and subtract from 100 to find how many leftover percentage points remain. Distribute the leftover points one at a time to the categories with the largest fractional remainders (the exact share minus its floor), breaking ties by the category's declaration order in the enumeration (the `gender` ordering, or the `race_ethnicity` ordering). Computing each category's percentage with an independent round is the wrong order and may fail to sum to 100; floor first, then allocate the remainder. Finally, `veteran_count` is the number of cohort apprentices whose `is_veteran` is true, and `disability_count` is the number whose `has_disability` is true.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. State-transition operations and other modifications to existing resources, as well as all reads, return a `200 OK` status code. Request and response payloads for each operation are described in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/apprenticeship/sponsors` | Create a sponsor | RegistrationAgency, Sponsor |
| GET | `/apprenticeship/sponsors` | List sponsors | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/sponsors/{id}` | Get a sponsor | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/programs` | Create an apprenticeship program (DRAFT) | Sponsor |
| GET | `/apprenticeship/programs` | List programs (filterable by sponsor) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/programs/{id}` | Get a program (includes computed available slots) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/programs/{id}/activate` | Activate a program | RegistrationAgency |
| POST | `/apprenticeship/programs/{id}/archive` | Archive a program | RegistrationAgency |
| POST | `/apprenticeship/wage-steps` | Add a wage step to a program | Sponsor |
| GET | `/apprenticeship/wage-steps` | List wage steps (filterable by program) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/wage-steps/{id}` | Get a wage step | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/milestones` | Add a competency milestone to a program | Sponsor |
| GET | `/apprenticeship/milestones` | List milestones (filterable by program) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/milestones/{id}` | Get a milestone | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/journeyworkers` | Register a journeyworker (PROBATIONARY) | Sponsor |
| GET | `/apprenticeship/journeyworkers` | List journeyworkers (filterable by sponsor) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/journeyworkers/{id}` | Get a journeyworker | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/journeyworkers/{id}/qualify` | Promote journeyworker to QUALIFIED | Sponsor |
| POST | `/apprenticeship/journeyworkers/{id}/deactivate` | Deactivate a journeyworker | Sponsor |
| POST | `/apprenticeship/apprentices` | Create an apprentice with EEO demographics | Sponsor |
| GET | `/apprenticeship/apprentices` | List apprentices (filterable by sponsor) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/apprentices/{id}` | Get an apprentice | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/agreements` | Create an apprentice agreement (DRAFT) | Sponsor |
| GET | `/apprenticeship/agreements` | List agreements (filterable) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/agreements/{id}` | Get an agreement | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/agreements/{id}/register` | Register the agreement (consumes a ratio slot; OCC) | Sponsor |
| POST | `/apprenticeship/agreements/{id}/activate` | Activate a registered agreement | Sponsor |
| POST | `/apprenticeship/agreements/{id}/suspend` | Suspend an active agreement | Sponsor |
| POST | `/apprenticeship/agreements/{id}/reinstate` | Reinstate a suspended agreement | Sponsor |
| POST | `/apprenticeship/agreements/{id}/complete` | Complete the agreement and issue the certificate | RegistrationAgency |
| POST | `/apprenticeship/agreements/{id}/cancel` | Cancel an agreement (releases the ratio slot) | Sponsor |
| POST | `/apprenticeship/ojt-entries` | Log an on-the-job training session (PENDING) | Sponsor, Apprentice |
| GET | `/apprenticeship/ojt-entries` | List OJT entries (filterable by agreement, status) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/ojt-entries/{id}` | Get an OJT entry | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/ojt-entries/{id}/approve` | Approve OJT hours | TrainingCoordinator |
| POST | `/apprenticeship/ojt-entries/{id}/reject` | Reject a pending OJT entry | TrainingCoordinator |
| POST | `/apprenticeship/ojt-entries/{id}/reopen` | Reopen an approved OJT entry | TrainingCoordinator |
| POST | `/apprenticeship/rti-records` | Record related-instruction hours (RECORDED) | Sponsor, TrainingCoordinator |
| GET | `/apprenticeship/rti-records` | List RTI records (filterable by agreement) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/rti-records/{id}` | Get an RTI record | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/milestone-attainments` | Submit a milestone attainment (SUBMITTED) | Sponsor |
| GET | `/apprenticeship/milestone-attainments` | List milestone attainments (filterable) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/milestone-attainments/{id}` | Get a milestone attainment | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/milestone-attainments/{id}/approve` | Approve a milestone attainment | TrainingCoordinator |
| POST | `/apprenticeship/milestone-attainments/{id}/reject` | Reject a milestone attainment | TrainingCoordinator |
| POST | `/apprenticeship/milestone-attainments/{id}/resubmit` | Resubmit a rejected milestone attainment | Sponsor |
| GET | `/apprenticeship/certificates` | List completion certificates (filterable) | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| GET | `/apprenticeship/certificates/{id}` | Get a completion certificate | RegistrationAgency, Sponsor, TrainingCoordinator, Apprentice |
| POST | `/apprenticeship/eeo-reports` | Generate an EEO report snapshot | RegistrationAgency, Sponsor |
| GET | `/apprenticeship/eeo-reports` | List EEO reports (filterable by program) | RegistrationAgency, Sponsor, TrainingCoordinator |
| GET | `/apprenticeship/eeo-reports/{id}` | Get an EEO report snapshot | RegistrationAgency, Sponsor, TrainingCoordinator |

The list endpoints accept the optional query parameters described in §3: `sponsor_id`, `program_id`, `apprentice_id`, `journeyworker_id`, `agreement_id`, `milestone_id`, and `status` as filters where applicable, plus `limit` and `offset` for pagination.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_WAGE_STEP_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_JOURNEYWORKER_NOT_FOUND` | 404 Not Found |
| `ERR_APPRENTICE_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_OJT_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_RTI_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_ATTAINMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_EEO_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_DATE_BEFORE_AGREEMENT_START` | 422 Unprocessable Entity |
| `ERR_SPONSOR_MISMATCH` | 409 Conflict |
| `ERR_MILESTONE_PROGRAM_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_WAGE_STEPS` | 409 Conflict |
| `ERR_NO_BASE_WAGE_STEP` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_AGREEMENTS` | 409 Conflict |
| `ERR_JOURNEYWORKER_NOT_PROBATIONARY` | 409 Conflict |
| `ERR_JOURNEYWORKER_NOT_QUALIFIED` | 409 Conflict |
| `ERR_JOURNEYWORKER_HAS_APPRENTICES` | 409 Conflict |
| `ERR_AGREEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_REGISTERED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_OJT_ENTRY_NOT_PENDING` | 409 Conflict |
| `ERR_OJT_ENTRY_NOT_APPROVED` | 409 Conflict |
| `ERR_ATTAINMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ATTAINMENT_NOT_REJECTED` | 409 Conflict |
| `ERR_JOURNEYMAN_RATIO_EXCEEDED` | 409 Conflict |
| `ERR_COMPLETION_REQUIREMENTS_NOT_MET` | 409 Conflict |
| `ERR_APPRENTICE_SESSION_OVERLAP` | 409 Conflict |
| `ERR_JOURNEYWORKER_SUPERVISION_CONFLICT` | 409 Conflict |

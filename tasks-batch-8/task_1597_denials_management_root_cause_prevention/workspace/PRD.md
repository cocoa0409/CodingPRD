# Denials Management API — Product Requirements Document

## 1. Introduction

Every dollar a hospital writes off to a payer denial arrives with a paper trail: a remittance advice, an adjustment reason code, and a filing deadline after which the right to appeal lapses. Revenue-cycle teams lose recoverable money twice — first when valid appeals miss timely-filing windows, and again when the same registration, authorization, or coding mistakes keep generating new denials because nobody routed the failure back upstream. The Denials Management API exists to close both leaks.

This document specifies a system for a hospital revenue-cycle denials team. The platform records each remittance denial by its adjustment code, freezes its categorization at intake, and anchors a payer-specific appeal calendar to the remittance date. A computed priority score ranks the specialist work queue so that large balances and near deadlines surface first. Appeals move through payer-configurable levels with enforced timely-filing gates and required clinical attachments, and every outcome feeds trailing overturn-rate analytics by payer and by denial category. When a denial is judged preventable, the system routes a root-cause fix task to the responsible upstream department, monitors verified fixes for recurrence, and scores each department's prevention performance per period. Write-offs travel a two-tier approval hierarchy with strict segregation of duties, and a director-controlled logical clock drives the timely-filing expiry sweep so that lapsed denials convert into write-off requests deterministically.

All monetary figures are integer cents; all deadlines are calendar dates evaluated against a logical server clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/rcm` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles:

- `DenialsSpecialist` — works the denial queue: denial intake, triage, appeals, attachments, outcome recording, and write-off requests.
- `DenialsManager` — queue assignment, intake correction, root-cause task creation and verification, and first-tier write-off decisions.
- `RevenueCycleDirector` — payer, policy, and remittance-code catalog administration; scorecard governance; escalated write-off authority and rescission; prevention-program lifecycle; and control of the logical clock.
- `UpstreamOwner` — the upstream department fix owner (registration, authorization, or coding) who acknowledges root-cause tasks and marks fixes implemented.
- `ComplianceAuditor` — independent assurance; reverses mis-recorded appeal outcomes and is otherwise read-only.

A request missing either header, or carrying a role outside these five, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is restricted by role; an authenticated role attempting an operation outside its authorized set is rejected with `ERR_FORBIDDEN`. All five roles share read access to every retrieval and list endpoint in the API.

For all five roles — `DenialsSpecialist`, `DenialsManager`, `RevenueCycleDirector`, `UpstreamOwner`, and `ComplianceAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures an actor — for example `assigned_specialist_id` on a denial case, `implemented_by_user_id` on a root-cause task, or `requested_by_user_id` and `decided_by_user_id` on a write-off request — and segregation-of-duties checks compare these user-id strings for equality, but no ownership check ever compares `X-User-ID` against an entity's `id`.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The ranked work queue is the one exception and defines its own ordering in §2.10.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Date Semantics

The server does not consult wall-clock time. A single logical clock governs every timestamp the system records — `generated_at`, `submitted_at`, `outcome_recorded_at`, `verified_at`, and `decided_at` are all read from it — and every date comparison in this document uses the logical clock's current calendar date, referred to throughout as "today". At startup, before any clock-control call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z; it never defaults to real time.

A `RevenueCycleDirector` advances the logical clock to a supplied `to_iso8601` instant through a director-only clock-control capability. The response echoes the new `current_utc` and lists `expired_denial_ids`, the denials expired by the sweep described in §3.5. Advancing the clock is never a passive write: setting it triggers the timely-filing expiry sweep across all denial cases, processed in creation order with the oldest `created_at` first, and recomputes the queue priority of every denial that remains workable afterward.

Deadline semantics are date-granular. Filing deadlines such as `next_appeal_deadline`, period bounds such as `period_start_date` and `period_end_date`, program window bounds, task `due_date` values, and monitoring horizons are all ISO dates with no time component. Every timeliness comparison is made at whole-day granularity: an appeal submitted on its deadline date itself is timely, because the comparison asks whether the submission date is on or before the deadline date.

### 2.5. Common Resource Properties

Every primary resource — payers, appeal policies, remittance codes, denial cases, appeals, attachments, root-cause tasks, write-off requests, department scorecards, and prevention programs — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties, including recomputation of derived fields.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including mutations that only recompute derived fields; it underpins optimistic concurrency control.

The audit event is the single exception: a denial event carries only `id` and `created_at`. Events are immutable once written, so `updated_at` and `version` are absent from them by design (see §2.11).

All mutations are immediately consistent: a change applied by a request is visible in that request's own response body and in every subsequent read.

### 2.6. Monetary Values, Rates, and Rounding Discipline

All money in the system is integer cents. Fields whose names end in `_cents` — billed, denied, recovered, written-off, open-balance, outcome, requested, projected, recommended, and scorecard dollar counters — are exact integers and are never rounded; additions and subtractions on them are exact.

Derived scores and percentages are decimal quantities rounded half-up to exactly two decimal places: the queue `priority_score`, the per-row `overturn_rate_pct` in overturn analytics, and both prevention score variants all follow this rule. The finalize-time prevention score is rounded exactly once from unrounded component rates, and the analytics totals row is likewise rounded exactly once from unrounded pooled counts — it is never assembled by summing or averaging already-rounded cells.

Projected dollar figures produced by multiplying an exposure by a rate — `expected_recovery_cents` on the recovery projection and `projected_recovery_cents` on a write-off request — are rounded half-up to whole integer cents.

Rates compared against thresholds are used unrounded: the payer trailing overturn rate is compared against its floor exactly as computed, with no rounding applied before the comparison.

### 2.7. Optimistic Concurrency Control on Denial Writes

Two write operations on a denial case are guarded by optimistic concurrency control: assigning (or reassigning) a specialist to a denial, and correcting intake fields on a denial. Each of these requests must carry `expected_denial_case_version`, a non-optional input field holding the denial's `version` as the client last observed it. If the denial's current `version` no longer matches the supplied value — because a triage, an earlier assignment, a prior correction, or a cascaded update has advanced the version since the client last read the denial — the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The client's view of the queue entry is stale, and the rejection prevents it from overwriting state it has not observed. Endpoints other than these two do not take a version field.

### 2.8. Validation Order and Error Precedence

When a request violates several rules at once, the server evaluates the following gates in the order listed and returns the error from the first gate that fails — a lower-numbered gate always wins over a later one.

1. **Authentication.** `X-User-ID` and `X-User-Role` must be present and the role must be one of the five declared roles, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization.** The authenticated role must appear in the endpoint's authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint.
3. **Request schema.** Required fields must be present, types and enum memberships must be valid, and dates must be ISO-formatted; on denial intake the billed amount must be at least the denied amount and the denied amount must be positive; a policy `level_number` must lie in the 1-to-3 range; a scorecard `period_end_date` must be later than its `period_start_date`; a program `end_date` must be on or after its `start_date`; a program `target_reduction_pct` must lie between 0 and 100 inclusive. Violations are `ERR_VALIDATION` (400) on every mutating endpoint.
4. **Reference resolution.** Path identifiers resolve left-to-right, and body references — `payer_id`, `remittance_code_id`, `denial_case_id`, `appeal_id`, and `recurrence_of_task_id` — must resolve to existing resources. An unresolvable payer, denial, or appeal reference yields `ERR_PAYER_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND` respectively; any other unresolvable reference (appeal policy, remittance code, attachment, root-cause task, write-off request, scorecard, prevention program, or event) yields `ERR_NOT_FOUND`. All four are 404.
5. **Optimistic concurrency.** On the two OCC-guarded denial writes named in §2.7, `expected_denial_case_version` must equal the denial's current `version`, else `ERR_STALE_VERSION` (412).
6. **State preconditions.** The target resource must be in a from-state allowed for the attempted transition: denials report `ERR_DENIAL_INVALID_STATE`, appeals `ERR_APPEAL_INVALID_STATE`, root-cause tasks `ERR_TASK_INVALID_STATE`, write-off requests `ERR_WRITE_OFF_NOT_PENDING`, scorecards `ERR_SCORECARD_NOT_OPEN`, and payer status toggles or prevention-program transitions `ERR_INVALID_STATE` (all 409). Applies to every action endpoint and to the payer and denial update operations.
7. **Temporal business rules.** Timely filing at appeal submission (`ERR_TIMELY_FILING_EXPIRED`, 422), policy window overlap at policy creation (`ERR_POLICY_WINDOW_OVERLAP`, 409), program window overlap at program creation (`ERR_PROGRAM_WINDOW_OVERLAP`, 409), and closing a task while its monitoring window is still running (`ERR_MONITORING_WINDOW_ACTIVE`, 409).
8. **Referential business state.** Denial intake against an inactive payer (`ERR_PAYER_INACTIVE`, 409), appeal creation for a denial whose remittance code is not appealable (`ERR_CODE_NOT_APPEALABLE`, 422), and an invalid recurrence link at task creation (`ERR_INVALID_RECURRENCE_LINK`, 422).
9. **Segregation of duties and ownership.** Write-off approval by the requester, and task verification by the implementer, are `ERR_SEGREGATION_OF_DUTIES` (403); write-off revision by anyone other than the original requester is `ERR_NOT_REQUEST_OWNER` (403).
10. **Uniqueness and progression.** A duplicate `claim_number` at intake (`ERR_DUPLICATE_CLAIM_NUMBER`, 409), a second concurrently active appeal on one denial (`ERR_APPEAL_ALREADY_ACTIVE`, 409), no further appeal level available (`ERR_APPEAL_LEVEL_EXHAUSTED`, 422), missing required attachments at submission (`ERR_ATTACHMENT_REQUIREMENT_UNMET`, 422), an outcome amount that does not match the outcome kind (`ERR_OUTCOME_AMOUNT_INCONSISTENT`, 422), a second pending write-off request on one denial (`ERR_WRITE_OFF_ALREADY_PENDING`, 409), and a duplicate scorecard period (`ERR_DUPLICATE_SCORECARD_PERIOD`, 409).
11. **Fiscal gates**, applied in this sub-order: first the requested write-off amount must not exceed the system ceiling (`ERR_WRITE_OFF_EXCEEDS_CEILING`, 422); second it must not exceed the denial's open balance, checked at creation and revision and re-checked at approval (`ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`, 422); third, an escalated-tier request may be approved only by a `RevenueCycleDirector` (`ERR_APPROVAL_LIMIT_EXCEEDED`, 403).

### 2.9. Conserved Dollar and Fix-Count Invariants

Two conservation laws hold at all times, and every workflow in §3 is built to preserve them.

**Money conservation on a denial case.** At all times, `open_balance_cents`, `recovered_amount_cents`, and `written_off_cents` sum exactly to `denied_amount_cents`, in integer cents. Recording an appeal outcome and later reversing that same outcome form a compensating pair, and approving a write-off and later rescinding it form another: each pair must leave the recovered amount (respectively the written-off amount) and the open balance identical to their values before the pair ran. A cascade that runs to completion but leaves drift in these fields has violated the invariant.

**Fix-count conservation on a department scorecard.** A scorecard's `verified_fix_count` always equals the number of the department's root-cause tasks that are currently `VERIFIED` and whose verification event date falls inside the scorecard period. A verification adds one to the count and adds the linked denial's denied amount to `verified_linked_denied_cents`; a recurrence reopen subtracts one and subtracts that same amount. The pair must leave both figures identical to their pre-pair values. The recurrence counters — `recurrence_count` and `recurrence_linked_denied_cents` — accumulate separately and are not part of the conserved quantity.

### 2.10. Work-Queue Prioritization and Ranking

Every denial case carries a computed `priority_score` and a derived `queue_bucket` that drive the specialist work queue. Only denials in `QUEUED` or `IN_APPEAL` are workable; a denial in any other status has a `priority_score` of exactly 0.00 and a `queue_bucket` of `LOW`, and never appears in the queue.

The score for a workable denial is the sum of three components, rounded half-up to two decimal places:

- **Dollar component.** The denial's `open_balance_cents` divided by 10000, capped at 50 points.
- **Deadline component.** Let the days remaining be the number of whole days from today's logical date to `next_appeal_deadline`, never less than zero. When more than 30 days remain, the component is zero; otherwise it is 45 minus 1.5 points per day remaining, never below zero.
- **Level boost.** 5 points per appeal level reached, counting at most 2 levels — so a denial at `current_appeal_level` 1 gains 5 points, and one at level 2 or 3 gains 10.

The `queue_bucket` derives from the score with inclusive lower boundaries: `CRITICAL` at 70.00 or higher, `HIGH` at 50.00 or higher, `MEDIUM` at 25.00 or higher, and `LOW` below 25.00.

The score is recomputed on every event that can move it: intake, triage, assignment, intake correction, appeal creation, outcome recording and reversal, appeal withdrawal, logical-clock advancement, and write-off approval or rescission.

The ranked work queue available to `DenialsSpecialist` and `DenialsManager` contains exactly the workable denials, ordered by `priority_score` descending; ties break to the earlier `next_appeal_deadline`, and remaining ties break to the earlier `created_at`. Resource ids are never used for ranking. The queue accepts optional `assigned_specialist_id` and `queue_bucket` filters alongside the standard pagination parameters.

### 2.11. The Append-Only Denial Event Trail

Every significant occurrence in a denial's life appends an immutable **DenialEvent** to an audit trail. An event records `denial_case_id` (the denial it belongs to), an `event_type` drawn from a fixed vocabulary, the acting `actor_role` and `actor_user_id`, and a `detail` string — a deterministic summary that includes the key amounts and statuses of the occurrence, such as the `recovered_amount_cents` figure after an outcome. For clock sweeps and system cascades, `actor_role` and `actor_user_id` carry the literal string `system`. As noted in §2.5, events carry `id` and `created_at` only.

The `event_type` vocabulary is exactly: `INTAKE`, `TRIAGED`, `ASSIGNED`, `INTAKE_CORRECTED`, `APPEAL_CREATED`, `LETTER_GENERATED`, `APPEAL_SUBMITTED`, `OUTCOME_RECORDED`, `OUTCOME_REVERSED`, `APPEAL_WITHDRAWN`, `WRITE_OFF_REQUESTED`, `WRITE_OFF_APPROVED`, `WRITE_OFF_REJECTED`, `WRITE_OFF_REVISED`, `WRITE_OFF_RESCINDED`, `EXPIRED`, `TASK_AUTO_CREATED`, `TASK_CREATED`, `TASK_VERIFIED`, and `TASK_REOPENED`. Task-related events are recorded against the relevant denial: an auto-created or manually created task's event attaches to its originating denial, a verification event attaches to the task's linked denial, and a recurrence reopen event attaches to the new intake denial that triggered it.

The trail is queryable by every role, listable with optional `denial_case_id` and `event_type` filters, and each event is retrievable individually by id.

## 3. Business Logic & Workflows

### 3.1. Payer, Policy, and Remittance-Code Administration

A `RevenueCycleDirector` maintains the three reference catalogs on which every downstream workflow depends. Creating a **payer** requires a display `name`, a `plan_type` of `COMMERCIAL`, `MEDICARE`, `MEDICAID`, or `MANAGED_CARE`, and a positive `default_timely_filing_days` — the fallback filing window, in days, used for first-level appeals when no effective appeal policy exists for level 1. A new payer starts `ACTIVE` with `appeal_policy_review_required` set to false. The director may later update a payer's `default_timely_filing_days` or toggle its `status`; each such update increments the payer's `version`. Toggling follows a strict state machine: a payer moves `ACTIVE` → `INACTIVE` or `INACTIVE` → `ACTIVE`, and an attempt to toggle from any other starting state — that is, to deactivate an already-inactive payer or activate an already-active one — is rejected with `ERR_INVALID_STATE`. Setting a payer `INACTIVE` blocks new denial intake for that payer with `ERR_PAYER_INACTIVE`; denials already in flight are unaffected, and reactivation re-enables intake.

**Appeal policies** define the payer-specific appeal calendar. A policy names its owning `payer_id`, a `level_number` in the 1-to-3 range (three is the system's maximum appeal level), a positive `timely_filing_days` allowance for submissions at that level, an optional `response_window_days` (defaulting to 30 — the number of days the payer has to respond), an optional `required_attachment_types` list (defaulting to empty) naming the attachment document types that must be present before submission at that level, and an effective window from `effective_from` (inclusive) to `effective_to` (exclusive). Omitting `effective_to` makes the policy open-ended, covering every anchor date on or after `effective_from`. Windows are half-open: for a given payer and level, two policies' windows must never overlap, though adjacency is permitted — one policy's `effective_to` may equal the next policy's `effective_from`. A creation that would overlap an existing same-payer, same-level window fails with `ERR_POLICY_WINDOW_OVERLAP`.

**Remittance codes** classify why a payer denied. Registering a code takes a unique `code` string (for example, CO-16), a `category` of `REGISTRATION`, `AUTHORIZATION`, `CODING`, `CLINICAL_DOCUMENTATION`, `BILLING`, or `CONTRACTUAL`, a `default_department` of `REGISTRATION`, `AUTHORIZATION`, or `CODING` naming the upstream department that owns prevention for the code, an optional `appealable` flag (default true), and an optional free-text `description` (default empty). A code registered with `appealable` false still appears on denials for analytics, but any attempt to open an appeal on such a denial is rejected with `ERR_CODE_NOT_APPEALABLE`.

The payer record also carries the system-computed `appeal_policy_review_required` flag, rewritten on every outcome recording and every outcome reversal touching that payer. The computation considers all of the payer's appeals that have ever reached an outcome state — `OVERTURNED`, `PARTIALLY_OVERTURNED`, or `UPHELD` — with no date window. The trailing overturn rate is the count of fully overturned appeals plus one half the count of partially overturned appeals, divided by the number of resolved appeals. Once the resolved sample reaches at least 3 appeals, the flag is set to true when the rate is strictly below 0.30 and reset to false when the rate is 0.30 or higher — a rate of exactly 0.30 is not flagged. Below a sample of 3, the flag keeps whatever value it currently holds.

All three catalogs are listable and retrievable by every role. Payer listings accept optional `status` and `plan_type` filters; policy listings accept `payer_id` (the foreign-key reverse lookup of a payer's policies) and `level_number` filters; remittance-code listings accept `category` and `appealable` filters.

### 3.2. Denial Intake and Triage

A `DenialsSpecialist` records a new **denial case** with the payer's `claim_number` (unique across all denials — a duplicate is rejected with `ERR_DUPLICATE_CLAIM_NUMBER`), the hospital's `patient_account_number`, the `payer_id` and `remittance_code_id` references, a positive `billed_amount_cents`, a positive `denied_amount_cents` no greater than the billed amount, the `service_date`, and the `remittance_received_date` on which the remittance arrived. The referenced payer must be `ACTIVE`, per §2.8's ordering. At intake the denial's `category` is copied from the remittance code and frozen — later catalog edits never retroactively change a denial's category — its `status` begins at `RECEIVED`, and its `preventable_flag` reads false until triage sets it.

Intake derives the first filing deadline: `next_appeal_deadline` is the `remittance_received_date` plus the `timely_filing_days` of the payer's effective level-1 policy — the level-1 policy whose half-open window contains the remittance date — falling back to the payer's `default_timely_filing_days` when no level-1 policy covers that date. The dollar fields initialize with `recovered_amount_cents` and `written_off_cents` at zero, so `open_balance_cents` equals `denied_amount_cents`; throughout the denial's life, `recovered_amount_cents` is by definition the sum of `outcome_amount_cents` across the denial's appeals currently in `OVERTURNED` or `PARTIALLY_OVERTURNED`, and `written_off_cents` is by definition the sum of approved, non-rescinded write-off amounts, with the open balance always the denied amount minus these two sums; `current_appeal_level` starts at 0; `assigned_specialist_id` stays null until assignment; and because a fresh denial is not yet workable, its `priority_score` computes to 0.00 with a `queue_bucket` of `LOW`. An `INTAKE` event is appended to the denial's audit trail. Denial listings support the foreign-key reverse lookups `payer_id` and `remittance_code_id` plus `status`, `category`, `queue_bucket`, `assigned_specialist_id`, and `root_cause_department` filters.

**Triage** moves a denial from `RECEIVED` to `TRIAGED` and is performed by a `DenialsSpecialist`; attempting it from any other status yields `ERR_DENIAL_INVALID_STATE`. The specialist supplies a `preventable_flag` and may optionally override the `root_cause_department`; absent an override, the department defaults to the remittance code's `default_department`. Several effects then fan out. When an `OPEN` department scorecard for the chosen department covers today's logical date within its period, it absorbs the intake: `denial_count` increases by one and `denied_cents` by the denial's `denied_amount_cents`, and if the denial is preventable, `preventable_denial_count` increases by one and `preventable_denied_cents` by the same amount. A preventable denial additionally auto-creates a root-cause task in `OPEN` status with `task_type` `PROCESS_FIX`, the triaged department, and a `due_date` fourteen days after the triage date, appending a `TASK_AUTO_CREATED` event and raising the scorecard's `open_task_count` by one.

Triage also runs the **recurrence sweep** described fully in §3.7: among the department's `VERIFIED` tasks whose linked denial shares this denial's `category` and whose `monitoring_until_date` is today or later, the single task with the earliest `verified_at` (ties broken by the earlier `created_at`) flips back to `REOPENED`. Finally triage appends a `TRIAGED` event, increments the denial's `version`, and recomputes its queue priority.

### 3.3. Queue Assignment, Intake Correction, and Recovery Projection

A `DenialsManager` assigns workable denials to specialists. Assignment requires the denial to be in `TRIAGED` or `QUEUED` — anything else is `ERR_DENIAL_INVALID_STATE` — and carries the OCC guard of §2.7: the request includes `specialist_id` (the opaque user id of the `DenialsSpecialist` who will work the case) alongside `expected_denial_case_version`. A first assignment moves the denial `TRIAGED` → `QUEUED`; a later assignment on an already-`QUEUED` denial is a reassignment that leaves the status at `QUEUED` and simply replaces `assigned_specialist_id`. Both forms append an `ASSIGNED` event and increment the denial's `version` by one.

While a denial remains in `RECEIVED` or `TRIAGED`, the manager may correct intake mistakes — `billed_amount_cents`, `denied_amount_cents`, or `remittance_received_date` — through the OCC-guarded correction operation; corrections against a denial in any later status are rejected with `ERR_DENIAL_INVALID_STATE`. A correction recomputes `open_balance_cents`, recomputes `next_appeal_deadline` from the level-1 schedule when the remittance date changed, recomputes the queue priority, appends an `INTAKE_CORRECTED` event, and increments `version`.

To inform whether a denial is worth another appeal level, every role may read its **recovery projection**, a computed figure with an optional `variant` query parameter — `gross` (the default) or `net`. The projection rests on a trailing overturn rate for the denial's payer at a given level: across that payer's appeals at that level whose status is `OVERTURNED`, `PARTIALLY_OVERTURNED`, or `UPHELD`, divide the count of overturned appeals plus one half the count of partially overturned appeals by the number of resolved appeals at that level. The fallback ladder is deterministic: if no appeal has resolved at the target level, use the payer-wide rate across all levels; if the payer has no resolved appeals at all, use the default rate 0.50. The next level is the denial's `current_appeal_level` plus one, and the remaining levels are three minus the current level. The **gross** variant multiplies `open_balance_cents` by the rate at the next level and rounds half-up to whole cents. The **net** variant starts from the same product and subtracts 5000 cents of appeal processing cost per remaining level, flooring the result at zero; gross is therefore never less than net for identical data, and net is strictly smaller whenever at least one level remains. The projection is available for a denial in any non-terminal status, and the response reports `variant`, `expected_recovery_cents`, the `rate_applied`, and `remaining_levels`.

### 3.4. The Multi-Level Appeal Pipeline

A `DenialsSpecialist` opens the next **appeal** for a denial by supplying its `denial_case_id`. Creation evaluates its gates in §2.8's order: the denial must be in `QUEUED` or `IN_APPEAL` (else `ERR_DENIAL_INVALID_STATE`); its remittance code must be appealable (else `ERR_CODE_NOT_APPEALABLE`); no other appeal of the same denial may currently be in `DRAFT`, `LETTER_GENERATED`, or `SUBMITTED` (else `ERR_APPEAL_ALREADY_ACTIVE`); and a next level must exist — the request is rejected with `ERR_APPEAL_LEVEL_EXHAUSTED` when the next level would exceed the maximum of 3 or when no effective policy covers a level beyond the first. (Level 1 alone falls back to the payer's `default_timely_filing_days` when no level-1 policy exists, so a first appeal is possible even for a payer without policies.) The new appeal's `level_number` is the denial's `current_appeal_level` plus one, and its `previous_appeal_id` links to the appeal one level lower for the same denial — null on a first appeal. An appeal starts in `DRAFT`, with `letter_body`, `generated_at`, `submitted_at`, `response_due_date`, and `outcome_recorded_at` all null, `outcome_amount_cents` at zero, and `payer_response_code` and `reversal_reason` empty.

The first appeal moves its denial `QUEUED` → `IN_APPEAL`, setting `current_appeal_level` to 1 while leaving `next_appeal_deadline` unchanged — it already holds the level-1 deadline. Each further appeal, opened after an `UPHELD` or `PARTIALLY_OVERTURNED` outcome with balance remaining, keeps the denial in `IN_APPEAL` and raises `current_appeal_level` by one. Both forms append an `APPEAL_CREATED` event and recompute the denial's priority, where the level boost of §2.10 now applies. Appeal listings accept the foreign-key reverse lookups `denial_case_id` and `previous_appeal_id` plus `status` and `level_number` filters.

**Attachments** carry the clinical evidence. A specialist attaches a document to an appeal by supplying `appeal_id`, a `document_type` of `CLINICAL_NOTES`, `PHYSICIAN_LETTER`, `LAB_RESULTS`, `AUTH_RECORD`, `ITEMIZED_BILL`, or `REMITTANCE_COPY`, and a `file_reference` handle to the stored document; the parent appeal must be in `DRAFT` or `LETTER_GENERATED`, otherwise `ERR_APPEAL_INVALID_STATE`. An attachment begins `ACTIVE` with an empty `voided_reason`, and only `ACTIVE` attachments satisfy submission requirements. Voiding an attachment requires the attachment itself to be `ACTIVE` (else `ERR_INVALID_STATE`) and its parent appeal still in `DRAFT` or `LETTER_GENERATED` (else `ERR_APPEAL_INVALID_STATE`); the supplied `reason` is stored as `voided_reason`, the attachment moves `ACTIVE` → `VOIDED`, and any letter already generated for the parent appeal is left stale until regenerated. Attachment listings accept `appeal_id`, `document_type`, and `status` filters.

**Letter generation** moves an appeal `DRAFT` → `LETTER_GENERATED` (from any other state, `ERR_APPEAL_INVALID_STATE`). The composed `letter_body` is a deterministic template naming the denial's claim number, category, the appeal's level, and the denied amount, followed by a manifest of the appeal's `ACTIVE` attachments sorted by `document_type`; `generated_at` takes the logical clock's timestamp, and a `LETTER_GENERATED` event is appended. If the evidence set or wording needs rework, revising returns the appeal `LETTER_GENERATED` → `DRAFT` (again, `ERR_APPEAL_INVALID_STATE` from any other state), clearing `letter_body` and `generated_at` back to null.

**Submission** moves `LETTER_GENERATED` → `SUBMITTED` and enforces two gates in order. First, timeliness: the submission date must be on or before the denial's `next_appeal_deadline` at whole-day granularity, else `ERR_TIMELY_FILING_EXPIRED`. Second, completeness: every document type named in the effective policy's `required_attachment_types` — the policy for the appeal's level whose window contains the submission date — must be present among the appeal's `ACTIVE` attachment types, else `ERR_ATTACHMENT_REQUIREMENT_UNMET`; a policy created without requirements has an empty list, which any attachment set satisfies. On success `submitted_at` takes the logical timestamp, `response_due_date` becomes the submission date plus the effective policy's `response_window_days`, an `APPEAL_SUBMITTED` event is appended, and the parent denial's `version` increments by one.

**Outcome recording** applies only from `SUBMITTED` (else `ERR_APPEAL_INVALID_STATE`) and takes an `outcome`, a `recovered_amount_cents` figure, and an optional `payer_response_code`. The amount must match the outcome kind, else `ERR_OUTCOME_AMOUNT_INCONSISTENT`: `OVERTURNED` requires the recovered amount to equal the denial's current `open_balance_cents`; `PARTIALLY_OVERTURNED` requires it to be greater than zero and strictly less than the open balance; `UPHELD` requires it to be exactly zero. The appeal stores the amount as `outcome_amount_cents` (zero for `UPHELD`), stamps `outcome_recorded_at` from the logical clock, and keeps the payer's response code.

The denial-level cascade then differs by kind. An `OVERTURNED` outcome adds the recovered amount to the denial's `recovered_amount_cents`; the open balance thereby reaches zero and, provided nothing has been written off, the denial resolves `IN_APPEAL` → `RESOLVED_PAID` with `next_appeal_deadline` cleared to null. A `PARTIALLY_OVERTURNED` outcome adds its amount to `recovered_amount_cents` and, when the appeal's level is below the maximum of 3 and an effective policy covers the next level, sets `next_appeal_deadline` to the outcome date plus that next-level policy's `timely_filing_days` while the denial stays `IN_APPEAL`; with no next level available, the denial closes `IN_APPEAL` → `CLOSED_EXHAUSTED` and the deadline clears. An `UPHELD` outcome recovers nothing and follows the same fork: next-level policy present means the denial stays `IN_APPEAL` with the recomputed deadline, otherwise `CLOSED_EXHAUSTED` with a null deadline. All three kinds append an `OUTCOME_RECORDED` event, and all three feed the measurement layer: when an `OPEN` scorecard for the denial's `root_cause_department` covers the outcome date, its `recovered_cents` increases by the outcome amount, and the payer's trailing overturn rate and `appeal_policy_review_required` flag are recomputed per §3.1.

**Outcome reversal** is the compliance correction path, available only to a `ComplianceAuditor` and only from `OVERTURNED`, `PARTIALLY_OVERTURNED`, or `UPHELD` (else `ERR_APPEAL_INVALID_STATE`); it returns the appeal to `SUBMITTED`. The supplied `reason` is stored as `reversal_reason`, the denial's `recovered_amount_cents` decreases by the appeal's `outcome_amount_cents` (for an `UPHELD` appeal this reverses a zero amount), that field resets to zero, and `outcome_recorded_at` returns to null. If the reversal drops a `RESOLVED_PAID` denial back below full recovery, the denial reopens to `IN_APPEAL` with `next_appeal_deadline` set to today plus the effective next-level policy's `timely_filing_days`, falling back to the payer's `default_timely_filing_days`. If the denial had been `CLOSED_EXHAUSTED` and an effective next-level policy exists, it likewise returns to `IN_APPEAL` with the recomputed deadline; without such a policy the reversal does not by itself move the denial out of `CLOSED_EXHAUSTED`. A denial that never left `IN_APPEAL` keeps its status and existing deadline, changed only by the dollar correction. The reversal subtracts the amount from the matching `OPEN` scorecard's `recovered_cents`, recomputes the payer's trailing rate and review flag, and appends an `OUTCOME_REVERSED` event. Together, recording and reversal form the compensating pair pinned by §2.9.

**Withdrawal** abandons an appeal that has not been submitted: from `DRAFT` or `LETTER_GENERATED` (else `ERR_APPEAL_INVALID_STATE`) the appeal moves to its terminal `WITHDRAWN` state. The denial's `current_appeal_level` recomputes as the highest `level_number` among its non-`WITHDRAWN` appeals — zero when none remain — and when the recomputed level is zero the denial falls back `IN_APPEAL` → `QUEUED` with `next_appeal_deadline` unchanged, the level-1 deadline still governing. When other appeals remain active or resolved, the denial stays `IN_APPEAL` at the recomputed level. Either way the priority score recomputes and an `APPEAL_WITHDRAWN` event is appended.

### 3.5. Timely-Filing Expiry and the Clock Sweep

Advancing the logical clock (§2.4) sweeps every denial for lapsed filing rights, processing candidates in `created_at` ascending order. A denial in `QUEUED` whose `next_appeal_deadline` now lies before today expires: `QUEUED` → `CLOSED_EXPIRED`. A denial in `IN_APPEAL` expires the same way only when it additionally has no appeal currently in `DRAFT`, `LETTER_GENERATED`, or `SUBMITTED` — an in-flight appeal package shields the denial from expiry.

Each expiry runs a three-hop cascade. Hop one moves the denial to `CLOSED_EXPIRED`, clears its `next_appeal_deadline` to null, and appends an `EXPIRED` event. Hop two auto-creates a write-off request for the full `open_balance_cents` with `reason_code` `TIMELY_FILING_EXPIRED` and `requested_by_user_id` set to the literal string `system`, deriving the request's tier and initial status through the standard write-off computation of §3.6, and appends a `WRITE_OFF_REQUESTED` event. Hop three increments `expired_denial_count` and `auto_writeoff_request_count` on the `OPEN` scorecard for the denial's `root_cause_department` whose period contains the new clock date. After the sweep, the queue priority of every denial still in `QUEUED` or `IN_APPEAL` is recomputed against the new date. The clock-control response reports the resulting `current_utc` and the `expired_denial_ids` list.

### 3.6. Write-Off Requests and the Approval Hierarchy

When recovery looks uneconomic, a `DenialsSpecialist` requests a **write-off** against a denial's open balance, supplying `denial_case_id`, a positive `requested_amount_cents`, and a `reason_code` of `TIMELY_FILING_EXPIRED`, `SMALL_BALANCE`, `APPEALS_EXHAUSTED`, `CONTRACTUAL_ADJUSTMENT`, or `OTHER`. The creator's `X-User-ID` is stored as `requested_by_user_id`. A denial may carry at most one pending request — one in `PENDING_MANAGER` or `ESCALATED_DIRECTOR` — and a second attempt is rejected with `ERR_WRITE_OFF_ALREADY_PENDING`. The fiscal gates of §2.8 then apply in their pinned sub-order: an amount above the system ceiling of 10000000 cents fails with `ERR_WRITE_OFF_EXCEEDS_CEILING`, and only then an amount above the denial's current `open_balance_cents` fails with `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`.

Every created or revised request derives its economics in a fixed evaluation order that breaks the apparent cycle between tier and recovery. First, the gross exposure is the requested amount, already validated against ceiling and balance. Second, the `approval_tier` is `STANDARD` when the gross exposure is 2500000 cents or less and `ESCALATED` otherwise — the tier is always keyed on the gross exposure, never on the recommended amount. Third, a tier multiplier of 1.0 for `STANDARD` or 0.75 for `ESCALATED` is combined with the payer's overturn rate at the next appeal level, using exactly the rate and fallback ladder of the recovery projection in §3.3. Fourth, `projected_recovery_cents` is the gross exposure multiplied by that rate and the tier multiplier, rounded half-up to whole cents. Fifth, `recommended_writeoff_cents` is the gross exposure minus the projected recovery. The request's initial `status` is `PENDING_MANAGER` for the `STANDARD` tier and `ESCALATED_DIRECTOR` for the `ESCALATED` tier, with `decision_reason` empty until a decision is recorded, and a `WRITE_OFF_REQUESTED` event is appended. Write-off listings accept `denial_case_id` and `status` filters.

**Approval** decides a pending request and is itself gated in a fixed order. The request must be in `PENDING_MANAGER` or `ESCALATED_DIRECTOR`, else `ERR_WRITE_OFF_NOT_PENDING`. The denial must be in `QUEUED`, `IN_APPEAL`, `CLOSED_EXHAUSTED`, or `CLOSED_EXPIRED` — approving against a denial in any other status, including `RESOLVED_PAID`, fails with `ERR_DENIAL_INVALID_STATE`. The approver's `X-User-ID` must differ from `requested_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The requested amount is re-checked against the denial's current open balance, else `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`. Finally, authority: a `DenialsManager` may approve a `STANDARD`-tier request, while an `ESCALATED`-tier request requires a `RevenueCycleDirector`, else `ERR_APPROVAL_LIMIT_EXCEEDED`; a director may approve either tier. On approval the request snapshots the denial's current status into `denial_status_before`, stamps `decided_by_user_id` and `decided_at`, adds the approved amount to the denial's `written_off_cents`, and appends a `WRITE_OFF_APPROVED` event; the matching `OPEN` scorecard's `written_off_cents` increases by the same amount. When the approval brings the open balance to zero, the denial resolves to `RESOLVED_WRITTEN_OFF` — from `QUEUED` or `IN_APPEAL` this also clears `next_appeal_deadline` to null, while a denial approved out of `CLOSED_EXHAUSTED` or `CLOSED_EXPIRED` already has no deadline — and its queue priority recomputes. Note `decided_by_user_id` may also hold the literal string `system` when a decision is system-generated rather than operator-made.

**Rejection** is available to both `DenialsManager` and `RevenueCycleDirector` from either pending status (else `ERR_WRITE_OFF_NOT_PENDING`). The supplied `reason` is stored as `decision_reason`, `decided_by_user_id` and `decided_at` are stamped, and a `WRITE_OFF_REJECTED` event is appended.

**Revision** lets the original requester rework a rejected request. Only from `REJECTED` (else `ERR_WRITE_OFF_NOT_PENDING`), and only when the caller's `X-User-ID` equals `requested_by_user_id` (else `ERR_NOT_REQUEST_OWNER`), the specialist supplies a new `requested_amount_cents` that must again respect both the open balance and the 10000000-cent ceiling. The amount updates and the tier, `projected_recovery_cents`, and `recommended_writeoff_cents` are recomputed through the same fixed derivation; the request re-enters the pipeline at `PENDING_MANAGER` when the new tier is `STANDARD` or at `ESCALATED_DIRECTOR` when it is `ESCALATED`, appending a `WRITE_OFF_REVISED` event.

**Rescission** is the director-only compensating action for an approved request: only from `APPROVED` (else `ERR_WRITE_OFF_NOT_PENDING`), a `RevenueCycleDirector` supplies a `reason`, which is stored in `decision_reason`, and the request settles in its terminal `RESCINDED` status. The denial's `written_off_cents` decreases by the rescinded amount, `open_balance_cents` recomputes per §2.9, the scorecard's `written_off_cents` decreases by the same amount, and a `WRITE_OFF_RESCINDED` event is appended. The denial returns to exactly the status captured in `denial_status_before`: a denial restored to `QUEUED` regains its level-1 filing deadline in `next_appeal_deadline` and recomputes its priority; one restored to `IN_APPEAL` has its deadline rebuilt from the appeal-deadline schedule using the latest outcome date and likewise recomputes priority; one restored to `CLOSED_EXHAUSTED` or `CLOSED_EXPIRED` keeps a null deadline and simply rejoins the closed population.

### 3.7. Upstream Root-Cause Tasks and Recurrence Monitoring

Beyond the auto-created tasks of §3.2, a `DenialsManager` may manually route a **root-cause task** by supplying `denial_case_id`, a `task_type` of `PROCESS_FIX`, `TRAINING`, `SYSTEM_CONFIG`, or `DATA_QUALITY`, a `description` of what the upstream department must change, a `due_date`, and an optional `recurrence_of_task_id` linking the new task to a prior task it recurs. The task's `department` is copied from the denial's `root_cause_department`, the task opens in `OPEN` status with `reopened_count` at zero and `fix_summary` empty, the matching `OPEN` scorecard's `open_task_count` increases by one, and a `TASK_CREATED` event attaches to the denial. A supplied recurrence link must resolve — an unresolvable reference is a 404 under reference resolution — and must then point at a `VERIFIED` task in the same department and never at the new task itself; a self-referential, non-`VERIFIED`, or cross-department link is rejected with `ERR_INVALID_RECURRENCE_LINK`. Task listings accept the foreign-key reverse lookups `denial_case_id` and `recurrence_of_task_id` plus `department` and `status` filters.

An `UpstreamOwner` acknowledges a task, moving `OPEN` → `ACKNOWLEDGED` or `REOPENED` → `ACKNOWLEDGED` — from any other state, `ERR_TASK_INVALID_STATE`. The same role then marks the fix implemented from `ACKNOWLEDGED` (else `ERR_TASK_INVALID_STATE`), supplying a `fix_summary`; the server records the caller's `X-User-ID` as `implemented_by_user_id` and the task moves to `FIX_IMPLEMENTED`.

Verification belongs to a `DenialsManager` and enforces segregation of duties: the task must be `FIX_IMPLEMENTED` (else `ERR_TASK_INVALID_STATE`) and the verifier's `X-User-ID` must differ from `implemented_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). A successful verification stamps `verified_at` from the logical clock, sets `monitoring_until_date` to the verified date plus 90 days, and moves the task to `VERIFIED`. When an `OPEN` scorecard for the task's department covers the verify date, its `verified_fix_count` increases by one, its `verified_linked_denied_cents` increases by the linked denial's `denied_amount_cents`, and its `open_task_count` decreases by one; a `TASK_VERIFIED` event attaches to the linked denial.

A verified task stays under **recurrence monitoring** while today remains on or before its `monitoring_until_date`. When a newly triaged denial matches a monitored task — the task is `VERIFIED`, its monitoring window is still running, its department equals the new denial's `root_cause_department`, and its linked denial's category equals the new denial's `category` — the triage recurrence sweep flips the single best-matching task `VERIFIED` → `REOPENED`: best match means the earliest `verified_at`, with ties broken by the earlier `created_at`. The reopen increments `reopened_count` by one and clears `verified_at` and `monitoring_until_date` to null. On the scorecard, `verified_fix_count` decreases by one, `verified_linked_denied_cents` decreases by that task's denial's denied amount, `recurrence_count` increases by one, `recurrence_linked_denied_cents` increases by the *new* denial's denied amount, and `open_task_count` increases by one; the `TASK_REOPENED` event attaches to the new denial. Verify and reopen form the compensating pair pinned by §2.9's fix-count invariant.

Once monitoring has fully elapsed, a `DenialsManager` closes the task: from `VERIFIED` only (else `ERR_TASK_INVALID_STATE`), and only when today is later than `monitoring_until_date` — closing on or before that date fails with `ERR_MONITORING_WINDOW_ACTIVE`. `CLOSED` is terminal.

### 3.8. Prevention Scorecards, Programs, and Overturn Analytics

A `RevenueCycleDirector` opens a **department scorecard** by naming a `department` (`REGISTRATION`, `AUTHORIZATION`, or `CODING`), an inclusive `period_start_date`, and an exclusive `period_end_date` that must be later than the start. One scorecard per department and period start is allowed: a duplicate pair fails with `ERR_DUPLICATE_SCORECARD_PERIOD`. A scorecard begins `OPEN` with every counter at zero, and while `OPEN` its counters mutate — but only for events whose logical date falls within the period's half-open bounds. The counters are: `denial_count` and `denied_cents` for denials triaged into the department; `preventable_denial_count` and `preventable_denied_cents` for the preventable subset; `recovered_cents` for net recovered dollars from outcomes recorded in-period, with reversals subtracting; `written_off_cents` for net approved write-off dollars in-period, with rescissions subtracting; `expired_denial_count` and `auto_writeoff_request_count` fed by the expiry sweep; `verified_fix_count` and `verified_linked_denied_cents` from verifications, with recurrence reopens subtracting; `recurrence_count` and `recurrence_linked_denied_cents` accumulating recurrence events; and `open_task_count`, tracking the department's tasks currently in `OPEN`, `ACKNOWLEDGED`, `FIX_IMPLEMENTED`, or `REOPENED`. While `OPEN`, the scorecard's `prevention_score_incidence`, `prevention_score_financial`, and `score_tier` remain null — a retrieval of an open scorecard returns live counters with null scores. Scorecard listings accept `department` and `status` filters.

**Finalization** — from `OPEN` only, else `ERR_SCORECARD_NOT_OPEN` — freezes the counters and computes both score variants using the logical clock's date for overdue determination. A task is overdue when it sits in `OPEN`, `ACKNOWLEDGED`, `FIX_IMPLEMENTED`, or `REOPENED` with a `due_date` earlier than today; a task is open when it sits in those same four states regardless of its due date. Both variants start from 100 and subtract 50 times the recurrence rate, 30 times the preventable rate, and 20 times the overdue rate, clamping the result into the 0-to-100 range and rounding half-up to two decimal places; the component rates are never pre-rounded, and any rate with a zero denominator counts as 0.0. The **incidence** variant is count-weighted: its recurrence rate is `recurrence_count` divided by the sum of `verified_fix_count` and `recurrence_count`; its preventable rate is `preventable_denial_count` divided by `denial_count`; its overdue rate is the overdue task count divided by the open task count. The **financial** variant is dollar-weighted: its recurrence rate is `recurrence_linked_denied_cents` divided by the sum of `verified_linked_denied_cents` and `recurrence_linked_denied_cents`; its preventable rate is `preventable_denied_cents` divided by `denied_cents`; its overdue rate is the summed denied amounts of denials linked to overdue tasks divided by the summed denied amounts of denials linked to open tasks — so high-dollar denials dominate and the score can diverge from the incidence variant when amounts are skewed. The `score_tier` derives from the incidence score with inclusive lower boundaries: `EXCELLENT` at 90.00 or higher, `GOOD` at 75.00 or higher, `WATCH` at 60.00 or higher, and `CRITICAL` below 60.00. `FINALIZED` is terminal.

**Prevention programs** give each department's remediation efforts a governed window. The director creates one with a `department`, a `name`, an inclusive `start_date`, an inclusive `end_date` on or after the start, and a `target_reduction_pct` between 0 and 100 inclusive. Program windows are closed intervals, and per department they must not overlap — unlike appeal policies, touching endpoints do conflict, so a new program whose `start_date` equals an existing program's `end_date` is already an overlap and fails with `ERR_PROGRAM_WINDOW_OVERLAP`. A program begins `PLANNED`, the director activates it `PLANNED` → `ACTIVE`, and later completes it `ACTIVE` → `COMPLETED`; a transition from any other state is `ERR_INVALID_STATE`, and `COMPLETED` is terminal. Program listings accept `department` and `status` filters.

**Overturn analytics** report, for a required `group_by` of `payer` or `category`, how appeals have resolved. The row set covers appeals in `OVERTURNED`, `PARTIALLY_OVERTURNED`, or `UPHELD` whose `outcome_recorded_at` date falls within the optional `from_date` and `to_date` bounds — both inclusive, and either bound may be omitted to leave that side unbounded — grouped by the denial's payer or by the denial's frozen category. Every group with at least one resolved appeal contributes a row; a group that has denials but zero resolved appeals in the window still appears, with `resolved_count` zero and `overturn_rate_pct` null — never zero and never an error. Each row reports `resolved_count`, `overturned_count`, and `partial_count`, and computes `overturn_rate_pct` as 100 times the sum of fully overturned appeals plus one half the partially overturned appeals, divided by the resolved count, rounded half-up to two decimal places. The response carries `group_by`, the `rows` array, and a `totals` object whose percentage is computed from the unrounded aggregate counts pooled across all rows — 100 times the pooled overturned-plus-half-partial sum divided by the pooled resolved count, rounded half-up to two decimals in a single rounding — and is never the sum or average of the rounded per-row percentages.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, drive a state transition, or perform a computed read return `200 OK`. "All roles" in the table means every role named in §2.1. Request payloads, derived fields, and side effects for each operation are defined by the workflows in §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rcm/_clock/set_current_utc` | Set the server logical clock and run the timely-filing expiry sweep | RevenueCycleDirector |
| POST | `/rcm/payers` | Create a payer | RevenueCycleDirector |
| GET | `/rcm/payers` | List payers with optional filters | All roles |
| GET | `/rcm/payers/{id}` | Get a payer by id | All roles |
| PATCH | `/rcm/payers/{id}` | Update a payer's default filing window or toggle its status | RevenueCycleDirector |
| POST | `/rcm/payer-appeal-policies` | Create a payer appeal policy for a level with a non-overlapping half-open window | RevenueCycleDirector |
| GET | `/rcm/payer-appeal-policies` | List appeal policies with optional filters | All roles |
| GET | `/rcm/payer-appeal-policies/{id}` | Get an appeal policy by id | All roles |
| POST | `/rcm/remittance-codes` | Register a remittance adjustment code | RevenueCycleDirector |
| GET | `/rcm/remittance-codes` | List remittance codes with optional filters | All roles |
| POST | `/rcm/denial-cases` | Record a remittance denial at intake | DenialsSpecialist |
| GET | `/rcm/denial-cases` | List denial cases with optional filters | All roles |
| GET | `/rcm/denial-cases/{id}` | Get a denial case by id | All roles |
| PATCH | `/rcm/denial-cases/{id}` | Correct intake fields on an early-stage denial (OCC-guarded) | DenialsManager |
| POST | `/rcm/denial-cases/{id}/triage` | Triage a received denial: department, preventable flag, upstream routing, recurrence sweep | DenialsSpecialist |
| POST | `/rcm/denial-cases/{id}/assign` | Assign or reassign a triaged denial to a specialist (OCC-guarded) | DenialsManager |
| GET | `/rcm/denial-cases/{id}/recovery-projection` | Computed expected recovery under the gross or net variant | All roles |
| GET | `/rcm/work-queue` | Ranked work queue of workable denials | DenialsSpecialist, DenialsManager |
| POST | `/rcm/appeals` | Open the next appeal level for a denial | DenialsSpecialist |
| GET | `/rcm/appeals` | List appeals with optional filters | All roles |
| GET | `/rcm/appeals/{id}` | Get an appeal by id | All roles |
| POST | `/rcm/appeals/{id}/generate-letter` | Generate the deterministic appeal letter with attachment manifest | DenialsSpecialist |
| POST | `/rcm/appeals/{id}/revise` | Return a generated appeal to draft, clearing the letter | DenialsSpecialist |
| POST | `/rcm/appeals/{id}/submit` | Submit an appeal, enforcing timely filing and required attachments | DenialsSpecialist |
| POST | `/rcm/appeals/{id}/record-outcome` | Record the payer's decision with recovered dollars | DenialsSpecialist |
| POST | `/rcm/appeals/{id}/reverse-outcome` | Reverse a recorded outcome as a compensating correction | ComplianceAuditor |
| POST | `/rcm/appeals/{id}/withdraw` | Withdraw a draft or letter-generated appeal | DenialsSpecialist |
| POST | `/rcm/appeal-attachments` | Attach a clinical document to a draft or letter-generated appeal | DenialsSpecialist |
| GET | `/rcm/appeal-attachments` | List attachments with optional filters | All roles |
| GET | `/rcm/appeal-attachments/{id}` | Get an attachment by id | All roles |
| POST | `/rcm/appeal-attachments/{id}/void` | Void an attachment, excluding it from submission requirements | DenialsSpecialist |
| POST | `/rcm/root-cause-tasks` | Manually route an upstream fix task for a denial | DenialsManager |
| GET | `/rcm/root-cause-tasks` | List root-cause tasks with optional filters | All roles |
| GET | `/rcm/root-cause-tasks/{id}` | Get a root-cause task by id | All roles |
| POST | `/rcm/root-cause-tasks/{id}/acknowledge` | Upstream department acknowledges an open or reopened task | UpstreamOwner |
| POST | `/rcm/root-cause-tasks/{id}/implement-fix` | Mark the upstream fix implemented | UpstreamOwner |
| POST | `/rcm/root-cause-tasks/{id}/verify` | Verify an implemented fix (verifier must differ from implementer) | DenialsManager |
| POST | `/rcm/root-cause-tasks/{id}/close` | Close a verified task after its monitoring window has elapsed | DenialsManager |
| POST | `/rcm/write-off-requests` | Request a write-off against a denial's open balance | DenialsSpecialist |
| GET | `/rcm/write-off-requests` | List write-off requests with optional filters | All roles |
| GET | `/rcm/write-off-requests/{id}` | Get a write-off request by id | All roles |
| POST | `/rcm/write-off-requests/{id}/approve` | Approve a pending write-off request within the actor's tier authority | DenialsManager, RevenueCycleDirector |
| POST | `/rcm/write-off-requests/{id}/reject` | Reject a pending write-off request with a reason | DenialsManager, RevenueCycleDirector |
| POST | `/rcm/write-off-requests/{id}/revise` | Requester revises a rejected request with a new amount | DenialsSpecialist |
| POST | `/rcm/write-off-requests/{id}/rescind` | Director rescinds an approved write-off, restoring the denial | RevenueCycleDirector |
| POST | `/rcm/department-scorecards` | Open a prevention scorecard for a department and period | RevenueCycleDirector |
| GET | `/rcm/department-scorecards` | List department scorecards with optional filters | All roles |
| GET | `/rcm/department-scorecards/{id}` | Get a scorecard by id (live counters, null scores while open) | All roles |
| POST | `/rcm/department-scorecards/{id}/finalize` | Freeze the period and compute both prevention scores and the tier | RevenueCycleDirector |
| POST | `/rcm/prevention-programs` | Create a prevention program with a non-overlapping closed window | RevenueCycleDirector |
| GET | `/rcm/prevention-programs` | List prevention programs with optional filters | All roles |
| GET | `/rcm/prevention-programs/{id}` | Get a prevention program by id | All roles |
| POST | `/rcm/prevention-programs/{id}/activate` | Activate a planned program | RevenueCycleDirector |
| POST | `/rcm/prevention-programs/{id}/complete` | Complete an active program | RevenueCycleDirector |
| GET | `/rcm/analytics/overturn-rates` | Overturn-rate analytics grouped by payer or category with a pooled totals row | All roles |
| GET | `/rcm/denial-events` | List audit events with optional filters | All roles |
| GET | `/rcm/denial-events/{id}` | Get a single audit event by id | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_NOT_FOUND` | 404 Not Found |
| `ERR_DENIAL_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_DENIAL_INVALID_STATE` | 409 Conflict |
| `ERR_APPEAL_INVALID_STATE` | 409 Conflict |
| `ERR_TASK_INVALID_STATE` | 409 Conflict |
| `ERR_WRITE_OFF_NOT_PENDING` | 409 Conflict |
| `ERR_SCORECARD_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TIMELY_FILING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROGRAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MONITORING_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_PAYER_INACTIVE` | 409 Conflict |
| `ERR_CODE_NOT_APPEALABLE` | 422 Unprocessable Entity |
| `ERR_INVALID_RECURRENCE_LINK` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_REQUEST_OWNER` | 403 Forbidden |
| `ERR_DUPLICATE_CLAIM_NUMBER` | 409 Conflict |
| `ERR_APPEAL_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_APPEAL_LEVEL_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_ATTACHMENT_REQUIREMENT_UNMET` | 422 Unprocessable Entity |
| `ERR_OUTCOME_AMOUNT_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_WRITE_OFF_ALREADY_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_SCORECARD_PERIOD` | 409 Conflict |
| `ERR_WRITE_OFF_EXCEEDS_CEILING` | 422 Unprocessable Entity |
| `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE` | 422 Unprocessable Entity |
| `ERR_APPROVAL_LIMIT_EXCEEDED` | 403 Forbidden |

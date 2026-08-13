# Graduate Medical Education Residency Program API — Product Requirements Document

## 1. Introduction

Running an ACGME-accredited residency program is an exercise in continuous, auditable compliance. Sponsoring institutions must prove — to the ACGME Review Committee, to Medicare GME funding auditors, and to their own Graduate Medical Education Committee — that trainee headcount never exceeds the approved complement, that GME dollars never exceed the funded cap, that duty hours respect the 80-hour rolling average, the 8-hour rest minimum, and the one-day-off-in-seven rule, and that every remediation, probation, and dismissal decision followed a documented, conflict-free process. Today these obligations are tracked across spreadsheets, e-mail threads, and after-the-fact attestations, which makes annual survey season and citation responses a scramble.

This document specifies a single API that operates an entire residency program office: complement approval and funding-cap enforcement, academic-year and rotation-block scheduling, duty-hour logging with automated violation surveillance, moonlighting authorization whose hours fold back into the duty-hour aggregates, milestone evaluations and Clinical Competency Committee deliberation, procedure case-log tracking against graduation minimums, remediation and probation management with strict segregation of duties, and accreditation citation response workflow tied to the annual ACGME survey. The API is the system of record; every aggregate it reports is computed from the same rows against which enforcement decisions are made.

All resources are mounted under a flat `/residency-programs` namespace: every collection hangs directly off that prefix, and cross-references between aggregates are carried as identifiers in request bodies rather than as nested URL hierarchies. One architectural trait deserves emphasis up front: a resident carries two independent state dimensions — a lifecycle dimension (from `INCOMING` through `ACTIVE`, `ON_LEAVE`, and the terminal `GRADUATED`, `DISMISSED`, `TRANSFERRED`) and a standing dimension (`GOOD_STANDING`, `UNDER_REMEDIATION`, `ON_PROBATION`) — which evolve in parallel and gate different operations. Time itself is also part of the contract: the system runs on a logical clock that test-driving clients can advance, and that clock is what fires time-based state changes and stamps system-generated dates.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `DesignatedInstitutionalOfficial`, `ProgramDirector`, `ProgramCoordinator`, `Resident`, `FacultyEvaluator`, and `CCCChair`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to specific operations is further restricted by role: an attempt to perform an action outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Role identity semantics differ across the six roles and are contractual:

- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident` record; ownership checks on any resource that references a resident — duty-hour logs, procedure case logs, moonlighting requests — compare the resource's resident foreign-key field to `X-User-ID`. A resident-role call that targets a row whose resident reference differs from `X-User-ID` is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).
- When `X-User-Role` is `DesignatedInstitutionalOfficial`, `ProgramDirector`, `ProgramCoordinator`, `FacultyEvaluator`, or `CCCChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `recommended_by` on a probation case or `evaluator_id` on a milestone evaluation — but does not compare it to any entity's `id` for ownership purposes. Two segregation-of-duties rules do compare these opaque identifiers against recorded actor stamps: the Clinical Competency Committee finalize action forbids the chair from having evaluated the same period (`ERR_COMMITTEE_ROLE_CONFLICT`, HTTP 403), and dismissal confirmation must come from a different operator than the one who recommended it (`ERR_DISMISSAL_CONFIRMATION_CONFLICT`, HTTP 403). Both rules are detailed in §3.

Every read endpoint in the API admits all six roles. Write endpoints are restricted per §4.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The single exception is the schedule-block list, which is sorted by `block_index` ascending so that block capture by index is deterministic.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system does not consult wall-clock time. It maintains a logical clock whose value, before any client sets it, reads exactly `2026-08-01T00:00:00Z`. A test-driving capability — restricted to `ProgramCoordinator`, `ProgramDirector`, and `DesignatedInstitutionalOfficial` — advances the clock by accepting a `to_iso8601` timestamp and returns the new clock value in a `current_utc` field. Once set, the clock never falls back to wall-clock time.

The logical clock is load-bearing in three places. First, advancing the clock fires time-driven moonlighting transitions: an `APPROVED` moonlighting request whose `start_date` has been reached (and whose `end_date` has not) becomes `ACTIVE`, and any `APPROVED` or `ACTIVE` request whose `end_date` has been reached or passed becomes `COMPLETED` (§3.6). Second, system-stamped dates — a remediation plan's `start_date`, a citation's `received_date` — are taken from the logical clock at the moment of creation. Third, the "current week" used by compliance checks is the ISO week containing the logical clock reading. Throughout the system, an ISO week runs from Monday 00:00:00 UTC through Sunday 24:00:00 UTC.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, used for identity only, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T04:00:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation of the resource — including mutations caused by cascaded side effects of operations on other resources. Recomputation of derived fields (for example, a complement row's fill figures after a resident lifecycle event, or a program's `accreditation_status` after a citation event) is a mutation and therefore refreshes `updated_at` and increments `version` on the affected resource.

One entity is the exception: a milestone evaluation is immutable once submitted. It carries `id` and `created_at` only — it has no `updated_at` and no `version` field, and no operation modifies it after creation.

### 2.6. Precision, Rounding, and Calendar Conventions

All computed decimal quantities in the system (hours, census figures, response rates, weighted composites) are rounded half-up. Unless a rule states otherwise, the target precision is 2 decimal places; the milestone composite is the documented exception at 1 decimal place (§3.7). Monetary amounts are integer cents — budgets, stipends, and costs are expressed in cents, never in fractional dollars — and any multiplication or division that produces a fractional cent is rounded half-up to a whole cent at the step the rule names.

Calendar conventions are uniform. Date-only fields (hire dates, graduation dates, performed dates, academic-year boundaries, moonlighting date ranges, remediation windows) are carried as midnight-UTC timestamps. Ranges expressed with a start and an end are half-open: the start is inclusive and the end is exclusive. This applies to schedule blocks, academic years, and moonlighting requests alike, and it is why two moonlighting requests that merely touch — one ending on exactly the day another begins — do not overlap. A residency academic year always comprises exactly 13 blocks of 28 days, i.e. a span of exactly 364 days from its first day (inclusive) to the day after its last day (exclusive).

### 2.7. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, each keyed to the `version` of the entity being modified:

1. Updating a complement row requires the request to carry `expected_complement_approval_version`, the value of the complement row's `version` the client last observed. If the row's current `version` has advanced since then — because another writer edited the row, or because a resident lifecycle event recomputed its fill fields — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. Updating a rotation requires `expected_rotation_version` carrying the rotation's last observed `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Capacity, eligibility, and night-float decisions made against a stale read of the rotation are no longer well-founded, so the edit cannot proceed.
3. Regenerating the block diagram of an academic year requires `expected_academic_year_version` carrying the year's last observed `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Regeneration legitimately supersedes the existing thirteen blocks, and a writer holding an older version is acting on a superseded diagram.

These three `expected_..._version` fields are non-optional on their respective endpoints. The stale-version check runs before any business rule on the request (see the precedence pipeline in §2.8). Endpoints not listed above do not accept a version field at all.

### 2.8. Validation Order and Error Precedence

Every request is validated against an ordered pipeline, and the first failure wins — the server reports the earliest failing stage and does not evaluate later stages. The stages, in order, are:

1. **User context.** `X-User-ID` and `X-User-Role` are present and the role names one of the six declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to all endpoints.
2. **Request shape.** For endpoints with a request body: all required input fields are present, types match, and enum values fall within their declared sets (specialty, moonlighting type, case-log role, outcome, competency codes, and so on); otherwise `ERR_INVALID_REQUEST` (HTTP 400). This stage precedes even the role check.
3. **Role authorization.** The caller's role is listed among the endpoint's authorized roles; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
4. **Ownership and segregation of duties.** Resident-role calls may only touch rows whose resident foreign key equals `X-User-ID` (`ERR_OWNERSHIP_VIOLATION`, HTTP 403); the CCC finalize chair must not be one of the period's evaluators (`ERR_COMMITTEE_ROLE_CONFLICT`, HTTP 403); the dismissal confirmer must differ from the recommender (`ERR_DISMISSAL_CONFIRMATION_CONFLICT`, HTTP 403).
5. **Existence.** Every identifier referenced in the path and then in the body exists, validated left-to-right — path parameters first, then body fields in their declared input order; otherwise `ERR_NOT_FOUND` (HTTP 404).
6. **Optimistic concurrency.** On the three OCC-protected writes of §2.7, the `expected_..._version` must equal the parent's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412). This check runs before any business rule.
7. **State-machine preconditions.** The target resource's state machine must permit the transition; otherwise the transition-specific error (for example `ERR_RESIDENT_NOT_INCOMING`, `ERR_ACADEMIC_YEAR_NOT_ACTIVE`, `ERR_COMPLEMENT_NOT_SUBMITTED`, `ERR_LOG_NOT_SUBMITTED`, `ERR_VIOLATION_NOT_OPEN`, `ERR_MOONLIGHTING_NOT_APPROVABLE`, `ERR_CCC_NOT_IN_DELIBERATION`, `ERR_CASE_LOG_NOT_LOGGED`, `ERR_REMEDIATION_NOT_ACTIVE`, `ERR_PROBATION_NOT_ACTIVE`, `ERR_CITATION_NOT_DRAFTABLE`, `ERR_SURVEY_NOT_OPEN`), generally HTTP 409.
8. **Safety and regulatory gates.** Resident-safety and program-standing rules: duty-period length at most 28.00 hours (`ERR_SHIFT_LENGTH_VIOLATION`, HTTP 422); night-float assignments barred to residents `ON_PROBATION` (`ERR_PROBATION_NIGHT_FLOAT_BLOCKED`, HTTP 403); moonlighting creation and approval require `GOOD_STANDING` (`ERR_STANDING_BLOCKS_MOONLIGHTING`, HTTP 403); complement approval barred while the program is `PROBATIONARY` (`ERR_PROGRAM_PROBATIONARY`, HTTP 403).
9. **Temporal bounds.** The academic year spans exactly 364 days (`ERR_INVALID_YEAR_SPAN`, HTTP 422); duty-log and case-log dates fall inside an `ACTIVE` academic year of the program (`ERR_DATE_OUT_OF_ACTIVE_YEAR`, HTTP 422); a moonlighting `start_date` precedes its `end_date` (`ERR_INVALID_DATE_RANGE`, HTTP 422).
10. **Constraint satisfaction.** Uniqueness, capacity, quorum, and threshold rules — one survey per program-year, one open CCC review per resident-year-period, one case requirement per program-category, one approved complement per level triple, PGY eligibility, one assignment per resident per block, rotation capacity, log overlap, moonlighting overlap, the three-evaluation quorum, the graduation gates, the single-open-probation rule, complete six-competency rating sets, outcome enums, dismissal justification length, retire and year-close guards — each surfacing its specific error from §5.
11. **Cross-aggregate consistency.** Referenced entities belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`, HTTP 400); resident enrollment requires an approved complement for the level (`ERR_NO_APPROVED_COMPLEMENT`, HTTP 409).
12. **Fiscal gates, always last.** Complement headcount and funding-cap checks at resident activation (`ERR_COMPLEMENT_EXCEEDED` HTTP 409, `ERR_FUNDING_CAP_EXCEEDED` HTTP 402) are evaluated only after every other validation has passed.

### 2.9. Resource Addressing and Cross-Program Consistency

The API's topology is flat: all collections live directly under `/residency-programs`, and relationships are expressed through body-level identifiers — a payload containing a `program_id`, `resident_id`, or `academic_year_id` — rather than nested paths. When a request references multiple resources, the system validates existence in a strict left-to-right order: path identifiers first, then body identifiers in their declared input order, rejecting with `ERR_NOT_FOUND` at the first missing reference.

Because references cross aggregate boundaries freely, the system enforces same-program consistency as its own validation stage (§2.8, stage 11). A rotation assignment's resident, schedule block (via its academic year), and rotation must all belong to the same program; a milestone evaluation's or CCC review's academic year must belong to the same program as the resident; a survey's year must belong to its program. A mismatch is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Programs, Academic Years, and the Block Diagram

A `DesignatedInstitutionalOfficial` creates a residency program by supplying its display `name`, its `specialty` — one of `INTERNAL_MEDICINE`, `GENERAL_SURGERY`, `PEDIATRICS`, `EMERGENCY_MEDICINE`, or `OBSTETRICS_GYNECOLOGY` — and its `acgme_program_code`, which must be unique across all programs. The program's `accreditation_status` is computed, not entered: it starts at `CONTINUED` and thereafter derives from the program's unresolved serious citations (§3.9). The program list can be filtered by `specialty`.

Within a program, a `ProgramCoordinator` lays out an academic year by supplying the owning `program_id`, a `year_label` such as "2026-2027", a `start_date` (the first day of the year, as a date-only midnight-UTC timestamp), and an `end_date` (the day after the last day, exclusive). The span from `start_date` to `end_date` must equal exactly 364 days — thirteen 28-day blocks; any other span is rejected with `ERR_INVALID_YEAR_SPAN` (HTTP 422). Creating the year immediately generates thirteen `ScheduleBlock` rows for it, each stamped with the owning `academic_year_id`, a `block_index` from 1 through 13, and its own half-open date range: block *i* covers the 28 days beginning at `start_date` plus (i−1) × 28 days and ending at `start_date` plus i × 28 days. All thirteen blocks begin in `CURRENT` status, and the year itself begins in `PLANNING` status.

Activating a year — a `ProgramCoordinator` action — requires the year to be in `PLANNING` (otherwise `ERR_ACADEMIC_YEAR_NOT_PLANNING`, HTTP 409) and requires exactly thirteen `CURRENT` schedule blocks to exist for it, which creation guarantees and regeneration restores. Activation moves the year to `ACTIVE` and bumps its `version`. While a year is still `PLANNING`, the coordinator may regenerate its block diagram: this optimistic-concurrency-protected action (§2.7) marks every existing `CURRENT` block `SUPERSEDED`, creates thirteen fresh `CURRENT` blocks with `block_index` 1 through 13 laid out from the year's `start_date` by the same 28-day rule, and increments the year's `version` by 1. Attempting regeneration on a year that is no longer `PLANNING` fails with `ERR_ACADEMIC_YEAR_NOT_PLANNING`. Schedule blocks are read-only to clients; the block list is returned in `block_index` ascending order and may be filtered by `academic_year_id` and block `status` (`CURRENT` or `SUPERSEDED`). The year list may be filtered by `program_id` and year `status`.

Closing a year is the coordinator's end-of-year action and is deliberately guarded: the year must be `ACTIVE` (otherwise `ERR_ACADEMIC_YEAR_NOT_ACTIVE`), and there must be no duty-hour log in `SUBMITTED` status for any resident of the program — an institution cannot close its books while attestations are outstanding, and the attempt is rejected with `ERR_UNATTESTED_LOGS_EXIST` (HTTP 409). Closing moves the year to `CLOSED`, its terminal state, and bumps its `version`.

### 3.2. Complement Approvals and the GME Funding Cap

The complement is the program's ACGME-approved trainee ceiling, expressed one row per program, academic year, and post-graduate year level. A `ProgramDirector` creates a complement row with the owning `program_id`, the `academic_year_id` it applies to, the `pgy_level` it covers (an integer from 1 through 7), the number of `approved_positions` (zero or more), the `annual_funding_budget_cents` cap for that level and year (zero or more, in cents), and the `blended_stipend_cents` — the annual stipend per resident at that level, in cents, at least 1. The row starts in `DRAFT` status.

Two figures are computed at creation and on every subsequent edit. First, `resident_year_stipend_cents`: the blended stipend is divided by the thirteen blocks of the year, the per-block quotient is rounded half-up to a whole cent, and that per-block figure is then multiplied by thirteen. The rounding order is pinned — round per block first, then multiply — because the reverse order yields a different integer and is forbidden. For example, a blended stipend of 6,500,007 cents produces a per-block figure of round-half-up of 500,000.538…, i.e. 500,001 cents, and therefore a year stipend of 6,500,013 cents — not 6,500,007. Second, `effective_funded_positions`: the smaller of `approved_positions` and the whole number of resident-years the budget affords, computed as the floor of `annual_funding_budget_cents` divided by `resident_year_stipend_cents`.

Two further figures track consumption against the cap and are recomputed whenever a resident lifecycle event touches the row (activation, leave, return, transfer, graduation, dismissal) and whenever the row is read, so reads always reflect the current roster. `filled_headcount` counts the program's residents at the row's `pgy_level` whose `lifecycle_status` is `ACTIVE` or `ON_LEAVE`, with each such resident counting as a full 1 — the headcount variant used for the ACGME complement cap. `filled_funded_census` sums the same residents with a weight of 1.0 for `ACTIVE` and 0.5 for `ON_LEAVE`, carried at 2 decimal places — the funded-census variant, which deliberately diverges from headcount for identical rosters because a resident on leave consumes less funding while still occupying a position. The census cost consumed is the funded census multiplied by `resident_year_stipend_cents`, rounded half-up to whole cents.

The row's editorial lifecycle is a revision cycle. While the row is `DRAFT` or `REJECTED`, the `ProgramDirector` may edit `approved_positions`, `annual_funding_budget_cents`, or `blended_stipend_cents` — the edit is OCC-protected with `expected_complement_approval_version` (§2.7), recomputes both derived figures, and bumps the row's `version`; editing a row in any other status is rejected with `ERR_COMPLEMENT_NOT_EDITABLE` (HTTP 409). Submitting moves a `DRAFT` row to `SUBMITTED`, and a `REJECTED` row may be edited and submitted again through the same action; submitting from any other status fails with `ERR_COMPLEMENT_NOT_SUBMITTABLE` (HTTP 409).

Decision authority rests with the `DesignatedInstitutionalOfficial`, and approval runs its checks in the pipeline order of §2.8: the state precondition first — the row must be `SUBMITTED`, otherwise `ERR_COMPLEMENT_NOT_SUBMITTED` (HTTP 409) — then the program-standing gate — approval is barred while the program's `accreditation_status` is `PROBATIONARY`, surfacing `ERR_PROGRAM_PROBATIONARY` (HTTP 403) — and finally the uniqueness constraint — no other complement row for the same (program, academic year, PGY level) triple may already be `APPROVED` or `LOCKED`, otherwise `ERR_COMPLEMENT_ALREADY_APPROVED` (HTTP 409). Approval moves the row to `APPROVED`; rejection of a `SUBMITTED` row (same `ERR_COMPLEMENT_NOT_SUBMITTED` guard) moves it to `REJECTED`, reopening the revision cycle. Locking, also the DIO's, requires `APPROVED` (otherwise `ERR_COMPLEMENT_NOT_APPROVED`, HTTP 409) and moves the row to its terminal `LOCKED` state; a `LOCKED` row rejects both edits (`ERR_COMPLEMENT_NOT_EDITABLE`) and submission (`ERR_COMPLEMENT_NOT_SUBMITTABLE`). The complement list may be filtered by `program_id`, `academic_year_id`, and `status`.

### 3.3. Resident Enrollment and the Lifecycle Dimension

A resident record is two state machines in one body. The lifecycle dimension, `lifecycle_status`, runs `INCOMING` → `ACTIVE` → (`ON_LEAVE` → `ACTIVE`) → one of the terminal `GRADUATED`, `DISMISSED`, or `TRANSFERRED`. The standing dimension, `standing_status`, runs among `GOOD_STANDING`, `UNDER_REMEDIATION`, and `ON_PROBATION` and is recomputed from the resident's remediation and probation records rather than driven directly (§3.8). The two evolve independently: a resident can be `ACTIVE` and `ON_PROBATION` at once.

A `ProgramCoordinator` enrolls a resident by supplying the `program_id`, the `entry_academic_year_id` used for complement matching at activation, the `pgy_level` (1 through 7), `full_name`, `email`, `hire_date`, and `expected_graduation_date` (both date-only). Enrollment is a cross-aggregate decision: an `APPROVED` or `LOCKED` complement row must already exist for the (program, entry year, PGY level) triple, otherwise creation is rejected with `ERR_NO_APPROVED_COMPLEMENT` (HTTP 409). A new resident starts `INCOMING` with `GOOD_STANDING`. The resident list may be filtered by `program_id`, `entry_academic_year_id`, `lifecycle_status`, and `standing_status`.

Activation is the coordinator's matriculation action and the point where the quota core of the system bites. The resident must be `INCOMING` (otherwise `ERR_RESIDENT_NOT_INCOMING`, HTTP 409). Then — and only after every other validation stage has passed, per the pipeline of §2.8 — the two fiscal gates run against the matching complement row. The headcount gate: the row's `filled_headcount` plus 1 must not exceed `approved_positions`; a breach is `ERR_COMPLEMENT_EXCEEDED` (HTTP 409). The funding gate: the funded census after admitting the candidate — `filled_funded_census` plus a full 1.0 position — multiplied by `resident_year_stipend_cents` and rounded half-up to whole cents must not exceed `annual_funding_budget_cents`; a breach is `ERR_FUNDING_CAP_EXCEEDED` (HTTP 402). On success the resident becomes `ACTIVE` and the complement row's fill figures are recomputed (a mutation that refreshes the row's `updated_at` and increments its `version`, per §2.5).

Leave is managed by the `ProgramDirector`. Placing a resident on leave requires `ACTIVE` (otherwise `ERR_RESIDENT_NOT_ACTIVE`, HTTP 409) and moves them to `ON_LEAVE`; the complement recomputation leaves headcount unchanged but drops the funded census by 0.5. Returning from leave requires `ON_LEAVE` (otherwise `ERR_RESIDENT_NOT_ON_LEAVE`, HTTP 409), moves the resident back to `ACTIVE`, and recomputes the fill figures — but performs no fiscal re-check, because the slot stayed reserved while the resident was on leave.

Graduation is the `ProgramDirector`'s certification that training is complete, and it is gated on four conditions: the resident is `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`); their `standing_status` is `GOOD_STANDING` (`ERR_STANDING_NOT_CLEAR`, HTTP 409); every case requirement of the program evaluates to met for this resident (`ERR_CASE_REQUIREMENTS_UNMET`, HTTP 409; the requirement math lives in §3.7); and at least one CCC review for the resident has reached `FINALIZED` (`ERR_NO_FINALIZED_CCC_REVIEW`, HTTP 409). Graduation moves the resident to `GRADUATED` and recomputes the complement fill figures. Transfer, also a director action, moves a resident from `ACTIVE` or `ON_LEAVE` to `TRANSFERRED` — a resident in any other lifecycle state fails with `ERR_RESIDENT_NOT_ACTIVE` — and likewise recomputes the fill figures. Dismissal is never invoked directly on the resident: it is the terminal cascade of the probation process of §3.8, moving a resident from `ACTIVE` or `ON_LEAVE` to `DISMISSED` with the same recomputation.

Two computed reads serve program leadership. The duty-hour summary for a resident takes a `week_start` query parameter and returns, for the ISO week containing it: `resident_id`, `week_start`, `official_hours`, `projected_hours`, `rolling_4wk_avg_official`, `rolling_4wk_avg_projected`, and `attributed_moonlighting_hours` (the aggregates are defined in §3.5 and §3.6). The case-progress read returns `resident_id`, a `requirements` array with the per-requirement progress of §3.7, and an `all_met` flag that is exactly the graduation case-requirement gate.

### 3.4. The Rotation Catalog and Block Scheduling

The rotation catalog is maintained by the `ProgramCoordinator`. Creating a rotation takes the owning `program_id`, a `name` (ICU, Night Float, Ward Medicine, …), a `min_pgy_level` eligibility floor (1 through 7), a `max_residents_per_block` capacity (at least 1), and an optional `is_night_float` flag that defaults to false; the rotation starts `ACTIVE`. Editing an `ACTIVE` rotation — its `name`, `min_pgy_level`, `max_residents_per_block`, or `is_night_float` — is OCC-protected with `expected_rotation_version` (§2.7); a retired rotation accepts no edits and the attempt is rejected with `ERR_ROTATION_NOT_ACTIVE` (HTTP 409). Retiring a rotation likewise requires `ACTIVE` (same error) and is additionally barred while any assignment referencing the rotation is `PLANNED` or `CONFIRMED`, surfacing `ERR_ROTATION_HAS_OPEN_ASSIGNMENTS` (HTTP 409); retirement moves the rotation to its terminal `RETIRED` state. The rotation list may be filtered by `program_id` and `status`.

Planning a resident onto a rotation for a block is the scheduling core: the coordinator supplies the `resident_id`, the `schedule_block_id`, and the `rotation_id`, and the assignment is created in `PLANNED` status. Eight guards protect this creation, and they fire in the pipeline order of §2.8 — state preconditions before the safety bar, which precedes the eligibility and capacity constraints, with cross-program consistency checked after those. The block's academic year must be `ACTIVE` (`ERR_ACADEMIC_YEAR_NOT_ACTIVE`); since supersession happens only while a year is `PLANNING`, any `SUPERSEDED` block fails this same guard, so assignments always land on `CURRENT` blocks of an active year. The rotation must be `ACTIVE` (`ERR_ROTATION_NOT_ACTIVE`). The resident's `lifecycle_status` must be `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`). A resident whose standing is `ON_PROBATION` may not be placed on a night-float rotation — one whose `is_night_float` is true — and the attempt is rejected with `ERR_PROBATION_NIGHT_FLOAT_BLOCKED` (HTTP 403). The resident's `pgy_level` must be at least the rotation's `min_pgy_level` (`ERR_PGY_INELIGIBLE`, HTTP 422). A resident may hold at most one non-`CANCELLED` assignment in a given schedule block — unit-slot semantics; a second one is rejected with `ERR_BLOCK_ASSIGNMENT_CONFLICT` (HTTP 409). The rotation's capacity is enforced per block: when the number of non-`CANCELLED` assignments for the (rotation, block) pair has reached `max_residents_per_block`, further assignments are rejected with `ERR_ROTATION_CAPACITY_FULL` (HTTP 409). Finally, the resident, the block's year, and the rotation must all belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`, HTTP 400).

The assignment lifecycle itself is simple. Confirming requires `PLANNED` (otherwise `ERR_ASSIGNMENT_NOT_PLANNED`, HTTP 409) and moves the assignment to `CONFIRMED`. Completing requires `CONFIRMED` (otherwise `ERR_ASSIGNMENT_NOT_CONFIRMED`, HTTP 409) and moves it to `COMPLETED`. Cancelling is permitted from either `PLANNED` or `CONFIRMED` (otherwise `ERR_ASSIGNMENT_NOT_CANCELLABLE`, HTTP 409) and moves it to `CANCELLED`, freeing both the resident's block slot and the rotation's capacity. All three are coordinator actions, and `COMPLETED` and `CANCELLED` are terminal. The assignment list may be filtered by `resident_id`, `schedule_block_id`, `rotation_id`, and `status`.

### 3.5. Duty-Hour Logging and Violation Surveillance

Duty-hour surveillance is the compliance core of the system. A resident logs a duty period by supplying their own `resident_id` — which must equal `X-User-ID` when the caller's role is `Resident`, otherwise `ERR_OWNERSHIP_VIOLATION` (HTTP 403) — plus the `started_at` and `ended_at` timestamps. The start must fall inside an `ACTIVE` academic year of the resident's program (`ERR_DATE_OUT_OF_ACTIVE_YEAR`, HTTP 422); the end must be strictly after the start; and the implied duration must not exceed 28.00 hours (`ERR_SHIFT_LENGTH_VIOLATION`, HTTP 422). The new period must not overlap any other non-`VOID` log of the same resident (`ERR_LOG_TIME_OVERLAP`, HTTP 409). On acceptance the log's `duration_hours` is computed as the elapsed time from `started_at` to `ended_at` in hours, rounded half-up to 2 decimal places, and the log enters `SUBMITTED` status. The log list may be filtered by `resident_id` and `status`.

Attestation is the resident's own act and the trigger for surveillance. Attesting requires the log to be `SUBMITTED` (otherwise `ERR_LOG_NOT_SUBMITTED`, HTTP 409) and the caller to own the log (`ERR_OWNERSHIP_VIOLATION`). On attestation the log becomes `ATTESTED` and the system immediately runs the violation-detection pass described below, which may create violation rows and may cascade into automatic remediation. Voiding is the compensating action: either the owning resident or a `ProgramDirector` may void a log in `SUBMITTED` or `ATTESTED` status (otherwise `ERR_LOG_NOT_VOIDABLE`, HTTP 409), recording the supplied `void_reason`; the log moves to `VOID` and is excluded from all duty-hour aggregates, so an attest-then-void sequence leaves official hours unchanged.

The weekly aggregates are defined as follows. For a resident and an ISO week (Monday 00:00:00 UTC through Sunday 24:00:00 UTC), clinical hours are the sum of `duration_hours` over the resident's `ATTESTED` logs whose `started_at` falls within the week. Moonlighting attribution adds, for each of the resident's moonlighting requests in `APPROVED`, `ACTIVE`, or `COMPLETED` status whose half-open date range intersects the week, the request's `hours_per_week` multiplied by the number of calendar days of the range falling inside the week (one to seven) divided by seven — each request's weekly contribution rounded half-up to 2 decimal places before any summing. The official weekly figure is clinical hours plus attributed moonlighting hours. The rolling average is the sum of the official weekly figures over the window of four ISO weeks ending with the reference week, divided by four — the divisor stays four even when fewer than four of those weeks contain any data. The reference week is the current logical-clock week for checks and the summary read, and the attested log's own week for detection. The projected variant, used by the moonlighting headroom check and the projected fields of the summary, is identical except that it also counts `SUBMITTED` (unattested) logs in the clinical sum; for identical data it is therefore always greater than or equal to the official figure.

The detection pass runs immediately after a log transitions from `SUBMITTED` to `ATTESTED`, evaluates three rules, and creates at most one violation per rule per window. Let the newly attested log's start date be d. Under `HOURS_80_AVG`, the window is the four ISO weeks ending with the week containing d, the measured value is the official rolling average over that window rounded to 2 decimal places, and a violation is created with `threshold_value` 80.00 only when the average is strictly greater than 80.00 — an average of exactly 80.00 passes. Under `REST_8H`, the system finds the resident's `ATTESTED` log with the greatest `ended_at` strictly before the new log's `started_at` (ties broken by latest `created_at`); if such a previous log exists and the gap from its `ended_at` to the new log's `started_at` is strictly less than 8.00 hours — a gap of exactly 8.00 passes — a violation is created whose window runs from the previous log's `ended_at` to the new log's `started_at` inclusive, whose measured value is the gap in hours at 2 decimal places, and whose `threshold_value` is 8.00. Under `DAY_OFF_4_IN_28`, the window is the twenty-eight calendar dates from d−27 days through d inclusive; worked days are the distinct calendar dates in that window on which the resident has at least one `ATTESTED` log (by `started_at` date); days off are twenty-eight minus the worked days; and a violation is created with `threshold_value` 4 only when days off are strictly fewer than 4 — exactly 4 passes. Every violation row records the `resident_id`, the `duty_hour_log_id` of the attested log whose detection pass raised it, the `rule_code` (`HOURS_80_AVG`, `REST_8H`, or `DAY_OFF_4_IN_28`), the inclusive `window_start` and `window_end`, the `measured_value`, and the `threshold_value`. Deduplication applies: if an unresolved violation (one in `FLAGGED` or `ACKNOWLEDGED` status) already exists for the resident with the same `rule_code` and identical `window_start` and `window_end`, no new row is created.

The aftermath converts surveillance into discipline. If, after a detection pass, the count of unresolved violations for the resident within the current `ACTIVE` academic year reaches 3 or more and the resident has no `ACTIVE` remediation plan, the system automatically creates one: `trigger_source` `DUTY_HOUR_VIOLATIONS`, status `ACTIVE`, the goals text "Automatic remediation: repeated duty-hour violations", `start_date` taken from the logical clock, and `end_date` ninety days later. That creation fires the standing cascade of §3.8 — the resident drops to `UNDER_REMEDIATION` and the moonlighting sweep runs.

Violations have their own workflow. A new violation is `FLAGGED`. A `ProgramCoordinator` acknowledges a `FLAGGED` violation, moving it to `ACKNOWLEDGED`; acknowledging from any other status fails with `ERR_VIOLATION_NOT_OPEN` (HTTP 409). A `ProgramDirector` resolves a violation from either `FLAGGED` or `ACKNOWLEDGED` (same error otherwise), moving it to `RESOLVED` and recording the supplied `resolution_note`. A director may instead dismiss from either open status with a `justification` of at least ten characters — anything shorter is rejected with `ERR_JUSTIFICATION_REQUIRED` (HTTP 400) — moving the violation to `DISMISSED` with the justification recorded as its `resolution_note`. `RESOLVED` and `DISMISSED` are terminal; unresolved means `FLAGGED` or `ACKNOWLEDGED`. The violation list may be filtered by `resident_id`, `duty_hour_log_id`, and `status`.

### 3.6. Moonlighting Requests and Weekly Hour Attribution

A resident moonlights only with program approval, and the request itself is the resident's own document. Creating a request takes the resident's `resident_id` (again owned: it must equal `X-User-ID` for a caller in the `Resident` role, else `ERR_OWNERSHIP_VIOLATION`), the `type` (`INTERNAL` or `EXTERNAL`), the `site_name`, a half-open date range from `start_date` (inclusive) to `end_date` (exclusive), and the committed `hours_per_week`, which must lie between 1.00 and 24.00 inclusive with 2 decimal places. The resident must be `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`) and in `GOOD_STANDING` — creating a request while `UNDER_REMEDIATION` or `ON_PROBATION` is rejected with `ERR_STANDING_BLOCKS_MOONLIGHTING` (HTTP 403). The `start_date` must be strictly before the `end_date` (`ERR_INVALID_DATE_RANGE`, HTTP 422). The range must not overlap any other request of the same resident in `SUBMITTED`, `APPROVED`, or `ACTIVE` status (`ERR_MOONLIGHTING_OVERLAP`, HTTP 409) — and because ranges are half-open, an existing request whose `end_date` equals the new request's `start_date` (or vice versa) is adjacent, not overlapping, and is allowed. The request begins in `DRAFT`. The request list may be filtered by `resident_id` and `status`.

The resident submits a `DRAFT` request — from any other status, `ERR_MOONLIGHTING_NOT_SUBMITTABLE` (HTTP 409) — moving it to `SUBMITTED`. Decision authority sits with the `ProgramDirector`. Approval re-runs the gates in pipeline order: the request must be `SUBMITTED` (`ERR_MOONLIGHTING_NOT_APPROVABLE`, HTTP 409); the resident's standing must still be `GOOD_STANDING` (`ERR_STANDING_BLOCKS_MOONLIGHTING`) — note that a standing change between creation and approval is caught here; and the projected-hours headroom check must pass (`ERR_PROJECTED_HOURS_EXCEED_80`, HTTP 422). The headroom check has a pinned evaluation order, because the candidate request participates in the very aggregate that gates it: first, compute the resident's rolling projected average (the projected variant of §3.5, which counts `SUBMITTED` logs and attributes hours from requests in `APPROVED`, `ACTIVE`, or `COMPLETED`) over the four ISO weeks ending with the current clock week, excluding the candidate request itself; second, add the candidate's `hours_per_week` to that base exactly once; third, approve only if the resulting decision value is less than or equal to 80.00 — equality passes, anything greater is rejected. Denial moves a `SUBMITTED` request to `DENIED` (from any other status, `ERR_MOONLIGHTING_NOT_DENIABLE`, HTTP 409) and records the supplied `denial_reason` as the request's `decision_reason`. Withdrawal is the resident's own action from `DRAFT` or `SUBMITTED` (otherwise `ERR_MOONLIGHTING_NOT_WITHDRAWABLE`, HTTP 409) and moves the request to `WITHDRAWN`. `DENIED`, `WITHDRAWN`, `COMPLETED`, and `REVOKED` are terminal.

Two transitions belong to the clock rather than to any user. When the logical clock reaches an `APPROVED` request's `start_date` without yet reaching its `end_date`, the request becomes `ACTIVE`. When the clock reaches or passes the `end_date` of an `APPROVED` or an `ACTIVE` request, the request becomes `COMPLETED` — so a request whose entire window elapses before the clock is ever set inside it moves directly from `APPROVED` to `COMPLETED`. Both fire whenever the clock is advanced past the relevant boundary (§2.4).

Revocation is the `ProgramDirector`'s action on an `APPROVED` or `ACTIVE` request (from any other status, `ERR_MOONLIGHTING_NOT_REVOKABLE`, HTTP 409): the request moves to `REVOKED`, the supplied `revocation_reason` is recorded as its `decision_reason`, and its attributed hours drop out of the official and projected weekly aggregates. The same transition is fired by the system as the moonlighting sweep: whenever a resident's standing leaves `GOOD_STANDING` (§3.8), every one of the resident's requests in `APPROVED` or `ACTIVE` is revoked with `decision_reason` set to `STANDING_CHANGE`, and the weekly aggregates are recomputed without those hours. Requests merely `SUBMITTED` are left `SUBMITTED` by the sweep — but they can no longer be approved, because the standing gate at approval blocks them. Returning to `GOOD_STANDING` never reinstates a revoked request; the resident must re-apply.

### 3.7. Assessing Competence: Milestones, Case Logs, and the Clinical Competency Committee

Three instrument families feed the graduation gate of §3.3: faculty milestone evaluations, verified procedure case logs measured against program requirements, and the Clinical Competency Committee's official review.

A milestone evaluation is submitted by a `FacultyEvaluator` or a `ProgramDirector` for a `(resident_id, academic_year_id, reporting_period)` triple, where `reporting_period` is `H1` or `H2`; the academic year must belong to the same program as the resident (`ERR_CROSS_PROGRAM_REFERENCE`, HTTP 400). The payload's `competency_ratings` must contain exactly six entries, one for each of `PATIENT_CARE`, `MEDICAL_KNOWLEDGE`, `PROFESSIONALISM`, `COMMUNICATION`, `PRACTICE_BASED_LEARNING`, and `SYSTEMS_BASED_PRACTICE`, each with an integer level from 1 through 5; anything else is rejected with `ERR_INCOMPLETE_RATINGS` (HTTP 422). The server stamps the submission with `evaluator_id` taken from `X-User-ID` and `evaluator_role` copied from `X-User-Role` — `FACULTY` for a `FacultyEvaluator`, `PROGRAM_DIRECTOR` for a `ProgramDirector` — and that role matters later: a program director's ratings carry double weight in the composite. The evaluation is immutable from the moment of creation (§2.5: no `updated_at`, no `version`). The evaluation list may be filtered by `resident_id`, `academic_year_id`, and `reporting_period`.

Procedure case logs are the resident's own record. Logging a case takes the owning `resident_id` (resident-role callers must own it, `ERR_OWNERSHIP_VIOLATION`), the `rotation_id` the case was performed on, the `procedure_category` — one of `MAJOR_SURGERY`, `ENDOSCOPY`, `TRAUMA_CARE`, `DELIVERIES`, or `AMBULATORY_PROCEDURE` — the `performed_date` (date-only, and it must fall inside an `ACTIVE` academic year of the resident's program, else `ERR_DATE_OUT_OF_ACTIVE_YEAR`), and the resident's `role` in the case, `SURGEON` or `ASSIST`. The resident must be `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`). The log starts in `LOGGED` status. A `FacultyEvaluator` then adjudicates: verifying requires `LOGGED` (otherwise `ERR_CASE_LOG_NOT_LOGGED`, HTTP 409) and moves the log to `VERIFIED`, recomputing the resident's case progress for that category; rejecting likewise requires `LOGGED` (same error) and moves it to `REJECTED` with the supplied `rejection_reason` recorded as `decision_reason`. The resident may resubmit a `REJECTED` log — their own, `ERR_OWNERSHIP_VIOLATION` otherwise — returning it to `LOGGED` for another look; resubmission from any other status fails with `ERR_CASE_LOG_NOT_LOGGED`. Finally, a `ProgramDirector` may void a `VERIFIED` log (otherwise `ERR_CASE_LOG_NOT_VERIFIED`, HTTP 409), recording the `void_reason` as `decision_reason` and recomputing progress; voiding is the compensating action of verification, so a verify-then-void sequence leaves the verified counts unchanged. `VERIFIED` and `VOIDED` are terminal. The case-log list may be filtered by `resident_id`, `rotation_id`, `procedure_category`, and `status`.

Requirements are set per program by the `ProgramDirector`: a case requirement names the `program_id` and `procedure_category` — unique per program, with a duplicate rejected as `ERR_REQUIREMENT_EXISTS` (HTTP 409) — plus the `required_count` (at least 1), the minimum number of effective cases needed for graduation, and the `required_primary_count` (at least 0 and no more than `required_count`), the minimum that must be logged in the `SURGEON` role. Progress against a requirement is computed only from `VERIFIED` logs — `LOGGED`, `REJECTED`, and `VOIDED` never count. The verified primary count is the number of the resident's `VERIFIED` logs in the category with `role` `SURGEON`; the verified assist count is the same for `ASSIST`. The assist credit is the smaller of two figures: the assist count multiplied by 0.5, rounded half-up to 2 decimal places, and one quarter of the requirement's `required_count`, also rounded half-up to 2 decimal places. The effective case total is the verified primary count plus the assist credit, and the requirement is met exactly when the effective total is at least `required_count` and the verified primary count is at least `required_primary_count`. The cap makes progress non-linear: past one quarter of the requirement, additional `ASSIST` logs add nothing. The case-progress read of §3.3 exposes this per-requirement computation and the `all_met` conjunction that the graduation gate consumes.

The Clinical Competency Committee works through review records owned by the `CCCChair`. Opening a review for a `(resident_id, academic_year_id, reporting_period)` triple requires that the year belong to the resident's program (`ERR_CROSS_PROGRAM_REFERENCE`) and that no review for the same triple is still open — a non-`FINALIZED` review already existing for the triple is rejected with `ERR_CCC_REVIEW_EXISTS` (HTTP 409). The review begins `OPEN`. Beginning deliberation requires `OPEN` (otherwise `ERR_CCC_NOT_OPEN`, HTTP 409) and moves the review to `IN_DELIBERATION`; reopening returns an `IN_DELIBERATION` review to `OPEN` (otherwise `ERR_CCC_NOT_IN_DELIBERATION`, HTTP 409), and the open–deliberation cycle may repeat any number of times. Finalization requires `IN_DELIBERATION` (same `ERR_CCC_NOT_IN_DELIBERATION`) and then runs three more gates: at least three milestone evaluations must exist for the triple (`ERR_INSUFFICIENT_EVALUATIONS`, HTTP 409); segregation of duties forbids the chair from finalizing a review of a period they personally evaluated — the caller's `X-User-ID` must not equal the `evaluator_id` of any evaluation for the triple (`ERR_COMMITTEE_ROLE_CONFLICT`, HTTP 403); and the supplied `outcome` must be one of `SATISFACTORY`, `NEEDS_IMPROVEMENT`, or `UNSATISFACTORY` (`ERR_INVALID_OUTCOME`, HTTP 422). The committee's official `milestone_levels` must again cover exactly the six competencies with levels 1 through 5 (`ERR_INCOMPLETE_RATINGS`).

Finalization records the `outcome` and `milestone_levels`, moves the review to its terminal `FINALIZED` state, and computes the `composite_snapshot`: for each of the six competencies, over all milestone evaluations of the triple, each evaluation's level is weighted — 2.0 when its `evaluator_role` is `PROGRAM_DIRECTOR`, 1.0 when `FACULTY` — and the composite level is the sum of level-times-weight divided by the sum of weights, rounded half-up once, at the end, to 1 decimal place; the snapshot's keys are the six competency codes. The outcome then cascades. A `NEEDS_IMPROVEMENT` outcome creates a remediation plan with `trigger_source` `CCC_OUTCOME` and the `ccc_review_id` set, status `ACTIVE`, the goals text "Clinical Competency Committee remediation (outcome NEEDS_IMPROVEMENT)", `start_date` from the logical clock, and `end_date` ninety days later, firing the standing cascade of §3.8. An `UNSATISFACTORY` outcome creates a probation case with reason "CCC outcome UNSATISFACTORY" and status `ACTIVE`, firing the standing cascade, the moonlighting sweep, and a recomputation of the weekly hour aggregates. The review list may be filtered by `resident_id`, `academic_year_id`, and `status`.

### 3.8. Remediation, Probation, and the Standing Dimension

A resident's `standing_status` is never set directly; it is re-derived after every creation, completion, cancellation, lifting, recommendation, or confirmation touching the resident's remediation plans and probation cases. The derivation is a strict priority: `ON_PROBATION` when any probation case of the resident is `ACTIVE` or `DISMISSAL_RECOMMENDED`; otherwise `UNDER_REMEDIATION` when any remediation plan of the resident is `ACTIVE`; otherwise `GOOD_STANDING`. Whenever the recomputed value leaves `GOOD_STANDING`, the moonlighting sweep of §3.6 runs — every `APPROVED` or `ACTIVE` request revoked with `decision_reason` `STANDING_CHANGE` — and the weekly duty-hour aggregates are recomputed; when a resident already `UNDER_REMEDIATION` drops to `ON_PROBATION`, the sweep is a no-op because the requests were already revoked. Returning to `GOOD_STANDING` never reinstates revoked moonlighting. Note the entry precondition implied by this ordering: a move from `GOOD_STANDING` to `UNDER_REMEDIATION` presupposes that no probation case is `ACTIVE` or `DISMISSAL_RECOMMENDED`, since any such case would already hold the standing at `ON_PROBATION`.

A `ProgramDirector` opens a remediation plan manually by supplying the `resident_id`, the remediation `goals`, and the plan's `start_date` and `end_date`; the plan starts `ACTIVE` with `trigger_source` `MANUAL`, and the standing cascade fires immediately. Automatically created plans — from a CCC `NEEDS_IMPROVEMENT` outcome (§3.7) or from the duty-hour aftermath (§3.5) — instead carry system-authored goals text, take the logical-clock date as `start_date`, and set `end_date` exactly ninety days later; the `ccc_review_id` is set only for plans born of a committee outcome (`trigger_source` `CCC_OUTCOME`) and is otherwise null, and `trigger_source` is `MANUAL`, `CCC_OUTCOME`, or `DUTY_HOUR_VIOLATIONS` accordingly. Completing a plan requires it to be `ACTIVE` (otherwise `ERR_REMEDIATION_NOT_ACTIVE`, HTTP 409) and takes an `outcome` that must be `SUCCESS` or `FAILURE` (anything else, `ERR_INVALID_OUTCOME`, HTTP 422). Success moves the plan to `COMPLETED_SUCCESS` and recomputes standing — the resident returns to `GOOD_STANDING` only if no other plan is `ACTIVE` and no probation case is open. Failure moves the plan to `COMPLETED_FAILURE` and escalates: unless a probation case is already open for the resident, one is created with the `remediation_plan_id` set, the reason "Remediation plan failure", and status `ACTIVE`, driving the standing to `ON_PROBATION` and running the moonlighting sweep. Cancelling a plan — again requiring `ACTIVE` (`ERR_REMEDIATION_NOT_ACTIVE`) — moves it to `CANCELLED`, records the supplied `cancel_reason`, and recomputes standing on the same terms as success. `COMPLETED_SUCCESS`, `COMPLETED_FAILURE`, and `CANCELLED` are terminal. The plan list may be filtered by `resident_id`, `ccc_review_id`, and `status`.

Probation is the graver instrument. A `ProgramDirector` opens a case manually with the `resident_id` and a `reason`; the case starts `ACTIVE`, and only one open case — one in `ACTIVE` or `DISMISSAL_RECOMMENDED` — may exist per resident, with a second attempt rejected as `ERR_OPEN_PROBATION_EXISTS` (HTTP 409). Creation fires the standing cascade to `ON_PROBATION` and the moonlighting sweep. Lifting a case requires `ACTIVE` (otherwise `ERR_PROBATION_NOT_ACTIVE`, HTTP 409), moves it to `LIFTED`, and recomputes standing — the resident reaches `GOOD_STANDING` only when no remediation plan is `ACTIVE` and no other probation case is open. Recommending dismissal, likewise from `ACTIVE` (`ERR_PROBATION_NOT_ACTIVE`), moves the case to `DISMISSAL_RECOMMENDED` and records the acting director's `X-User-ID` in `recommended_by`.

Dismissal itself is split across two roles by design — a segregation of duties. The `DesignatedInstitutionalOfficial` confirms dismissal on a case in `DISMISSAL_RECOMMENDED` (otherwise `ERR_PROBATION_NOT_RECOMMENDED`, HTTP 409), and the confirming `X-User-ID` must differ from the recorded `recommended_by`; the same operator attempting to confirm their own recommendation is rejected with `ERR_DISMISSAL_CONFIRMATION_CONFLICT` (HTTP 403). On confirmation the case moves to its terminal `DISMISSED` state, and the cascade lands on the resident: `lifecycle_status` moves from `ACTIVE` or `ON_LEAVE` to `DISMISSED`, and the complement fill figures are recomputed. `LIFTED` and `DISMISSED` are the terminal states of the case. The case list may be filtered by `resident_id`, `remediation_plan_id`, and `status`.

### 3.9. Accreditation Citations and the Annual Survey

The program-level compliance mirror of §3.8 is the citation workflow. A `DesignatedInstitutionalOfficial` records a received citation with the `program_id`, the `citation_code` identifier (for example "IV.A.2"), the `severity` (`WARNING` or `SERIOUS`), the `area_code` — one of `DUTY_HOURS`, `EVALUATION`, `CASE_LOGS`, `SUPERVISION`, `RESPONSE_RATE`, or `OTHER` — and an informational `due_date` for the response. The server stamps the `received_date` from the logical clock, the citation opens in `OPEN` status, and the program's accreditation status is recomputed on the spot. Unresolved means every status except `RESOLVED`, and the program's computed `accreditation_status` derives from the unresolved serious set: with two or more unresolved `SERIOUS` citations the program is `PROBATIONARY`; with exactly one it is `CONTINUED_WITH_WARNING`; with none it is `CONTINUED`. Because the pipeline of §2.8 gates complement approval on this figure, a program that falls to `PROBATIONARY` cannot approve complement rows until its citations are worked down (`ERR_PROGRAM_PROBATIONARY`).

Responding is the `ProgramDirector`'s work; disposition is the DIO's. Drafting a response is allowed from `OPEN` or from `ESCALATED` (otherwise `ERR_CITATION_NOT_DRAFTABLE`, HTTP 409) — the latter is the re-response cycle after an escalated submission — and moves the citation to `RESPONSE_DRAFTED`, storing the supplied `response_text` and recomputing the program's accreditation status. Submitting the response requires `RESPONSE_DRAFTED` (otherwise `ERR_CITATION_RESPONSE_NOT_DRAFTED`, HTTP 409) and moves the citation to `RESPONSE_SUBMITTED`. From there the DIO either resolves the citation (requiring `RESPONSE_SUBMITTED`, otherwise `ERR_CITATION_NOT_RESOLVABLE`, HTTP 409), moving it to its terminal `RESOLVED` state with the `resolution_note` recorded and the program status recomputed — resolving the last unresolved `SERIOUS` citation drops the program back out of its warning or probationary band — or escalates it (same state requirement, otherwise `ERR_CITATION_NOT_ESCALATABLE`, HTTP 409), moving it to `ESCALATED` with the `escalation_reason` recorded and the program status recomputed. The citation list may be filtered by `program_id`, `annual_survey_id`, `status`, and `severity`.

The annual ACGME survey is the other citation source. A `ProgramCoordinator` creates the survey record for a `program_id` and `academic_year_id` — one survey per program per year, with a duplicate rejected as `ERR_SURVEY_EXISTS` (HTTP 409) — and it begins `OPEN`. Closing is the DIO's act and requires `OPEN` (otherwise `ERR_SURVEY_NOT_OPEN`, HTTP 409). The close payload carries the `resident_response_rate` and `faculty_response_rate`, each between 0.00 and 100.00 with 2 decimal places, and the `area_results` entries, each pairing an `area_code` with a `compliance_pct` in the same 0.00–100.00 range; any value outside its range is rejected with `ERR_INVALID_SURVEY_RATE` (HTTP 422). On close the survey moves to `CLOSED`, the computed `flagged_area_count` records how many `area_results` entries fell below 70.00 compliance, and the citation cascade fires. A `resident_response_rate` below 70.00 auto-creates a citation with `area_code` `RESPONSE_RATE`, severity `WARNING`, the survey's `annual_survey_id` set, and a `citation_code` of `SURVEY-RESPONSE_RATE-<year_label>`. A `faculty_response_rate` below 70.00 similarly auto-creates one coded `SURVEY-FACULTY-<year_label>`, again `RESPONSE_RATE` and `WARNING`. Each flagged area auto-creates a citation with that area's `area_code`, a `citation_code` of `SURVEY-<area_code>-<year_label>`, the survey's `annual_survey_id`, and a severity that depends on the breadth of the problem: `SERIOUS` when the `flagged_area_count` is 3 or more, otherwise `WARNING`. Auto-created citations open in `OPEN` status with `received_date` from the logical clock, and the close completes with a recomputation of the program's `accreditation_status` — which in turn gates complement approvals per §3.2. The survey list may be filtered by `program_id`, `academic_year_id`, and `status`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code; operations that read, modify, or act on an existing resource return `200 OK`. Read endpoints (GET) admit every declared role and are marked "Any" below; write endpoints admit only the roles listed. The complete request and response shapes of each operation are defined by the narratives of §3 rather than by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and fire time-driven transitions | ProgramCoordinator, ProgramDirector, DesignatedInstitutionalOfficial |
| POST | `/residency-programs` | Create a residency program | DesignatedInstitutionalOfficial |
| GET | `/residency-programs` | List residency programs | Any |
| GET | `/residency-programs/{id}` | Get one residency program | Any |
| POST | `/residency-programs/academic-years` | Create an academic year and its thirteen schedule blocks | ProgramCoordinator |
| GET | `/residency-programs/academic-years` | List academic years | Any |
| GET | `/residency-programs/academic-years/{id}` | Get one academic year | Any |
| POST | `/residency-programs/academic-years/{id}/activate` | Activate a `PLANNING` year | ProgramCoordinator |
| POST | `/residency-programs/academic-years/{id}/close` | Close an `ACTIVE` year | ProgramCoordinator |
| POST | `/residency-programs/academic-years/{id}/regenerate-blocks` | Supersede and regenerate the block diagram (OCC) | ProgramCoordinator |
| GET | `/residency-programs/schedule-blocks` | List schedule blocks in `block_index` order | Any |
| GET | `/residency-programs/schedule-blocks/{id}` | Get one schedule block | Any |
| POST | `/residency-programs/complement-approvals` | Create a `DRAFT` complement row | ProgramDirector |
| GET | `/residency-programs/complement-approvals` | List complement rows | Any |
| GET | `/residency-programs/complement-approvals/{id}` | Get one complement row | Any |
| PUT | `/residency-programs/complement-approvals/{id}` | Edit a `DRAFT` or `REJECTED` complement row (OCC) | ProgramDirector |
| POST | `/residency-programs/complement-approvals/{id}/submit` | Submit a `DRAFT` or `REJECTED` complement row | ProgramDirector |
| POST | `/residency-programs/complement-approvals/{id}/approve` | Approve a `SUBMITTED` complement row | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/complement-approvals/{id}/reject` | Reject a `SUBMITTED` complement row | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/complement-approvals/{id}/lock` | Lock an `APPROVED` complement row | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/residents` | Enroll a resident (`INCOMING`) | ProgramCoordinator |
| GET | `/residency-programs/residents` | List residents | Any |
| GET | `/residency-programs/residents/{id}` | Get one resident | Any |
| POST | `/residency-programs/residents/{id}/activate` | Activate an `INCOMING` resident (headcount and funding gates) | ProgramCoordinator |
| POST | `/residency-programs/residents/{id}/place-on-leave` | Move an `ACTIVE` resident to `ON_LEAVE` | ProgramDirector |
| POST | `/residency-programs/residents/{id}/return-from-leave` | Return an `ON_LEAVE` resident to `ACTIVE` | ProgramDirector |
| POST | `/residency-programs/residents/{id}/graduate` | Graduate an `ACTIVE` resident | ProgramDirector |
| POST | `/residency-programs/residents/{id}/transfer` | Transfer an `ACTIVE` or `ON_LEAVE` resident out | ProgramDirector |
| GET | `/residency-programs/residents/{id}/duty-hour-summary` | Duty-hour aggregates for the week containing `week_start` | Any |
| GET | `/residency-programs/residents/{id}/case-progress` | Per-requirement case progress and graduation gate | Any |
| POST | `/residency-programs/rotations` | Create a rotation (`ACTIVE`) | ProgramCoordinator |
| GET | `/residency-programs/rotations` | List rotations | Any |
| GET | `/residency-programs/rotations/{id}` | Get one rotation | Any |
| PUT | `/residency-programs/rotations/{id}` | Edit an `ACTIVE` rotation (OCC) | ProgramCoordinator |
| POST | `/residency-programs/rotations/{id}/retire` | Retire a rotation with no open assignments | ProgramCoordinator |
| POST | `/residency-programs/rotation-assignments` | Plan a resident onto a rotation for a block (`PLANNED`) | ProgramCoordinator |
| GET | `/residency-programs/rotation-assignments` | List rotation assignments | Any |
| GET | `/residency-programs/rotation-assignments/{id}` | Get one rotation assignment | Any |
| POST | `/residency-programs/rotation-assignments/{id}/confirm` | Move a `PLANNED` assignment to `CONFIRMED` | ProgramCoordinator |
| POST | `/residency-programs/rotation-assignments/{id}/complete` | Move a `CONFIRMED` assignment to `COMPLETED` | ProgramCoordinator |
| POST | `/residency-programs/rotation-assignments/{id}/cancel` | Cancel a `PLANNED` or `CONFIRMED` assignment | ProgramCoordinator |
| POST | `/residency-programs/duty-hour-logs` | Log a duty period (`SUBMITTED`) | Resident |
| GET | `/residency-programs/duty-hour-logs` | List duty-hour logs | Any |
| GET | `/residency-programs/duty-hour-logs/{id}` | Get one duty-hour log | Any |
| POST | `/residency-programs/duty-hour-logs/{id}/attest` | Attest a `SUBMITTED` log and run violation detection | Resident |
| POST | `/residency-programs/duty-hour-logs/{id}/void` | Void a `SUBMITTED` or `ATTESTED` log | Resident, ProgramDirector |
| GET | `/residency-programs/duty-hour-violations` | List duty-hour violations | Any |
| GET | `/residency-programs/duty-hour-violations/{id}` | Get one duty-hour violation | Any |
| POST | `/residency-programs/duty-hour-violations/{id}/acknowledge` | Move a `FLAGGED` violation to `ACKNOWLEDGED` | ProgramCoordinator |
| POST | `/residency-programs/duty-hour-violations/{id}/resolve` | Resolve an open violation | ProgramDirector |
| POST | `/residency-programs/duty-hour-violations/{id}/dismiss` | Dismiss an open violation with justification | ProgramDirector |
| POST | `/residency-programs/moonlighting-requests` | Create a `DRAFT` moonlighting request | Resident |
| GET | `/residency-programs/moonlighting-requests` | List moonlighting requests | Any |
| GET | `/residency-programs/moonlighting-requests/{id}` | Get one moonlighting request | Any |
| POST | `/residency-programs/moonlighting-requests/{id}/submit` | Submit a `DRAFT` request | Resident |
| POST | `/residency-programs/moonlighting-requests/{id}/approve` | Approve a `SUBMITTED` request (standing and headroom gates) | ProgramDirector |
| POST | `/residency-programs/moonlighting-requests/{id}/deny` | Deny a `SUBMITTED` request | ProgramDirector |
| POST | `/residency-programs/moonlighting-requests/{id}/withdraw` | Withdraw a `DRAFT` or `SUBMITTED` request | Resident |
| POST | `/residency-programs/moonlighting-requests/{id}/revoke` | Revoke an `APPROVED` or `ACTIVE` request | ProgramDirector |
| POST | `/residency-programs/milestone-evaluations` | Submit an immutable milestone evaluation | FacultyEvaluator, ProgramDirector |
| GET | `/residency-programs/milestone-evaluations` | List milestone evaluations | Any |
| GET | `/residency-programs/milestone-evaluations/{id}` | Get one milestone evaluation | Any |
| POST | `/residency-programs/ccc-reviews` | Open a CCC review | CCCChair |
| GET | `/residency-programs/ccc-reviews` | List CCC reviews | Any |
| GET | `/residency-programs/ccc-reviews/{id}` | Get one CCC review | Any |
| POST | `/residency-programs/ccc-reviews/{id}/begin-deliberation` | Move an `OPEN` review to `IN_DELIBERATION` | CCCChair |
| POST | `/residency-programs/ccc-reviews/{id}/finalize` | Finalize an `IN_DELIBERATION` review and fire outcome cascades | CCCChair |
| POST | `/residency-programs/ccc-reviews/{id}/reopen` | Return an `IN_DELIBERATION` review to `OPEN` | CCCChair |
| POST | `/residency-programs/procedure-case-logs` | Log a procedure case (`LOGGED`) | Resident |
| GET | `/residency-programs/procedure-case-logs` | List procedure case logs | Any |
| GET | `/residency-programs/procedure-case-logs/{id}` | Get one procedure case log | Any |
| POST | `/residency-programs/procedure-case-logs/{id}/verify` | Move a `LOGGED` case to `VERIFIED` | FacultyEvaluator |
| POST | `/residency-programs/procedure-case-logs/{id}/reject` | Move a `LOGGED` case to `REJECTED` | FacultyEvaluator |
| POST | `/residency-programs/procedure-case-logs/{id}/resubmit` | Return a `REJECTED` case to `LOGGED` | Resident |
| POST | `/residency-programs/procedure-case-logs/{id}/void` | Void a `VERIFIED` case | ProgramDirector |
| POST | `/residency-programs/case-requirements` | Define a case minimum for a program and category | ProgramDirector |
| GET | `/residency-programs/case-requirements` | List case requirements | Any |
| GET | `/residency-programs/case-requirements/{id}` | Get one case requirement | Any |
| POST | `/residency-programs/remediation-plans` | Open a remediation plan (`ACTIVE`) | ProgramDirector |
| GET | `/residency-programs/remediation-plans` | List remediation plans | Any |
| GET | `/residency-programs/remediation-plans/{id}` | Get one remediation plan | Any |
| POST | `/residency-programs/remediation-plans/{id}/complete` | Complete a plan with outcome `SUCCESS` or `FAILURE` | ProgramDirector |
| POST | `/residency-programs/remediation-plans/{id}/cancel` | Cancel a plan | ProgramDirector |
| POST | `/residency-programs/probation-cases` | Open a probation case (`ACTIVE`) | ProgramDirector |
| GET | `/residency-programs/probation-cases` | List probation cases | Any |
| GET | `/residency-programs/probation-cases/{id}` | Get one probation case | Any |
| POST | `/residency-programs/probation-cases/{id}/lift` | Lift an `ACTIVE` case | ProgramDirector |
| POST | `/residency-programs/probation-cases/{id}/recommend-dismissal` | Move an `ACTIVE` case to `DISMISSAL_RECOMMENDED` | ProgramDirector |
| POST | `/residency-programs/probation-cases/{id}/confirm-dismissal` | Confirm dismissal and dismiss the resident | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/accreditation-citations` | Record a received citation (`OPEN`) | DesignatedInstitutionalOfficial |
| GET | `/residency-programs/accreditation-citations` | List accreditation citations | Any |
| GET | `/residency-programs/accreditation-citations/{id}` | Get one accreditation citation | Any |
| POST | `/residency-programs/accreditation-citations/{id}/draft-response` | Draft a response (`OPEN` or `ESCALATED`) | ProgramDirector |
| POST | `/residency-programs/accreditation-citations/{id}/submit-response` | Submit a drafted response | ProgramDirector |
| POST | `/residency-programs/accreditation-citations/{id}/resolve` | Resolve a submitted citation | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/accreditation-citations/{id}/escalate` | Escalate a submitted citation | DesignatedInstitutionalOfficial |
| POST | `/residency-programs/annual-surveys` | Create the annual survey record (`OPEN`) | ProgramCoordinator |
| GET | `/residency-programs/annual-surveys` | List annual surveys | Any |
| GET | `/residency-programs/annual-surveys/{id}` | Get one annual survey | Any |
| POST | `/residency-programs/annual-surveys/{id}/close` | Close a survey, computing flagged areas and auto-creating citations | DesignatedInstitutionalOfficial |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_COMMITTEE_ROLE_CONFLICT` | 403 Forbidden |
| `ERR_DISMISSAL_CONFIRMATION_CONFLICT` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_YEAR_SPAN` | 422 Unprocessable Entity |
| `ERR_ACADEMIC_YEAR_NOT_PLANNING` | 409 Conflict |
| `ERR_ACADEMIC_YEAR_NOT_ACTIVE` | 409 Conflict |
| `ERR_UNATTESTED_LOGS_EXIST` | 409 Conflict |
| `ERR_NO_APPROVED_COMPLEMENT` | 409 Conflict |
| `ERR_COMPLEMENT_EXCEEDED` | 409 Conflict |
| `ERR_FUNDING_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_COMPLEMENT_NOT_EDITABLE` | 409 Conflict |
| `ERR_COMPLEMENT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_COMPLEMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_COMPLEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_COMPLEMENT_ALREADY_APPROVED` | 409 Conflict |
| `ERR_PROGRAM_PROBATIONARY` | 403 Forbidden |
| `ERR_RESIDENT_NOT_INCOMING` | 409 Conflict |
| `ERR_RESIDENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RESIDENT_NOT_ON_LEAVE` | 409 Conflict |
| `ERR_STANDING_NOT_CLEAR` | 409 Conflict |
| `ERR_CASE_REQUIREMENTS_UNMET` | 409 Conflict |
| `ERR_NO_FINALIZED_CCC_REVIEW` | 409 Conflict |
| `ERR_ROTATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROTATION_HAS_OPEN_ASSIGNMENTS` | 409 Conflict |
| `ERR_PGY_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PROBATION_NIGHT_FLOAT_BLOCKED` | 403 Forbidden |
| `ERR_BLOCK_ASSIGNMENT_CONFLICT` | 409 Conflict |
| `ERR_ROTATION_CAPACITY_FULL` | 409 Conflict |
| `ERR_CROSS_PROGRAM_REFERENCE` | 400 Bad Request |
| `ERR_ASSIGNMENT_NOT_PLANNED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DATE_OUT_OF_ACTIVE_YEAR` | 422 Unprocessable Entity |
| `ERR_SHIFT_LENGTH_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LOG_TIME_OVERLAP` | 409 Conflict |
| `ERR_LOG_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LOG_NOT_VOIDABLE` | 409 Conflict |
| `ERR_VIOLATION_NOT_OPEN` | 409 Conflict |
| `ERR_JUSTIFICATION_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_MOONLIGHTING_OVERLAP` | 409 Conflict |
| `ERR_STANDING_BLOCKS_MOONLIGHTING` | 403 Forbidden |
| `ERR_PROJECTED_HOURS_EXCEED_80` | 422 Unprocessable Entity |
| `ERR_MOONLIGHTING_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_MOONLIGHTING_NOT_APPROVABLE` | 409 Conflict |
| `ERR_MOONLIGHTING_NOT_DENIABLE` | 409 Conflict |
| `ERR_MOONLIGHTING_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_MOONLIGHTING_NOT_REVOKABLE` | 409 Conflict |
| `ERR_INCOMPLETE_RATINGS` | 422 Unprocessable Entity |
| `ERR_CCC_REVIEW_EXISTS` | 409 Conflict |
| `ERR_CCC_NOT_OPEN` | 409 Conflict |
| `ERR_CCC_NOT_IN_DELIBERATION` | 409 Conflict |
| `ERR_INSUFFICIENT_EVALUATIONS` | 409 Conflict |
| `ERR_INVALID_OUTCOME` | 422 Unprocessable Entity |
| `ERR_REQUIREMENT_EXISTS` | 409 Conflict |
| `ERR_CASE_LOG_NOT_LOGGED` | 409 Conflict |
| `ERR_CASE_LOG_NOT_VERIFIED` | 409 Conflict |
| `ERR_REMEDIATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_PROBATION_EXISTS` | 409 Conflict |
| `ERR_PROBATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROBATION_NOT_RECOMMENDED` | 409 Conflict |
| `ERR_CITATION_NOT_DRAFTABLE` | 409 Conflict |
| `ERR_CITATION_RESPONSE_NOT_DRAFTED` | 409 Conflict |
| `ERR_CITATION_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_CITATION_NOT_ESCALATABLE` | 409 Conflict |
| `ERR_SURVEY_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_SURVEY_RATE` | 422 Unprocessable Entity |
| `ERR_SURVEY_EXISTS` | 409 Conflict |

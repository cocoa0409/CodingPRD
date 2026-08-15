# Stunt Coordination & Set Safety Planning API — Product Requirements Document

## 1. Introduction

Stunt work is the most tightly supervised activity on a film or television set: every fire burn, high fall, vehicle gag, water sequence, pyrotechnic effect, aerial rig, and staged fight must be designed, risk-assessed, rehearsed, signed off by every affected department, insured, permitted, executed, and reviewed. This document specifies the Stunt Coordination & Set Safety Planning API, the system of record through which a stunt coordination team manages that entire lifecycle — sequence design and risk assessment documentation, performer qualification and rehearsal scheduling, safety meetings and department sign-off, equipment and rigging inspection with medic standby confirmation, insurance notification and special-equipment permits, adjustment pay and hazard-bump negotiation, incident reporting and production stoppage, and the post-stunt review that closes the loop on every executed sequence.

Two concerns shape every rule that follows. First, set safety is enforced structurally rather than by convention: readiness to execute is a gated, multi-party decision in which the coordinator who designed a sequence may not approve its risk assessment, sign its department sign-offs, or inspect equipment they registered. Second, the platform is audit-driven: all time-dependent rules — certification expiry, inspection currency, permit windows, stoppage cooldowns — are evaluated against a server-maintained logical clock rather than wall-clock time, and every state change is versioned so that stale client views are rejected deterministically instead of silently overwriting safety-critical decisions.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The platform recognizes exactly six roles: `ProductionExecutive`, `StuntCoordinator`, `SafetyOfficer`, `DepartmentHead`, `Performer`, and `EquipmentInspector`. A request missing either header, or naming a role outside these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among the roles authorized for the target endpoint (see §4) is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles, and what `X-User-ID` means for each:

- A `ProductionExecutive` owns the production lifecycle: creating the production, amending its budget, filing and acknowledging insurance, activating, stopping, lifting stoppages, wrapping, applying for and adjudicating permits, and advancing the logical clock. When `X-User-Role` is `ProductionExecutive`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `StuntCoordinator` designs sequences, authors risk assessments, registers performers and their certifications, schedules rehearsals and safety meetings, registers and retires equipment, calls takes, and negotiates hazard pay on the coordinator side. When `X-User-Role` is `StuntCoordinator`, `X-User-ID` is an opaque operator identifier; the server records it as `coordinator_user_id` on each sequence the coordinator creates, as `assessor_user_id` on each risk assessment they author, and as `registered_by_user_id` on each equipment item they register, and those attribution fields are what later owner-checks compare against.
- A `SafetyOfficer` approves or rejects risk assessments, chairs safety meetings, suspends and reinstates performers, revokes certifications and permits, voids rehearsal completions, investigates and closes incidents, opens and closes post-stunt reviews, and may stop the production. When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is an opaque operator identifier; the server records it as `chair_user_id` on meetings they start and as `reviewer_user_id` on reviews they open, but does not compare it to any entity's `id`.
- A `DepartmentHead` signs or refuses department sign-offs during meetings and may report incidents. When `X-User-Role` is `DepartmentHead`, `X-User-ID` is an opaque operator identifier recorded as `signer_user_id` on each signoff they decide.
- A `Performer` negotiates their own hazard-pay adjustments and otherwise reads. When `X-User-Role` is `Performer`, `X-User-ID` is the `id` of the acting StuntPerformer; on any write whose payload carries `performer_id`, ownership requires that field to equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- An `EquipmentInspector` records equipment inspections. When `X-User-Role` is `EquipmentInspector`, `X-User-ID` is an opaque operator identifier recorded as `inspector_user_id` on each inspection they file.

Certain follow-on actions are additionally restricted to the specific coordinator who owns the work: locking a sequence's design, marking it ready, reverifying readiness, the coordinator-side cancellation of a sequence, completing, marking missed, or cancelling its rehearsals, and completing or aborting its takes may only be performed by the coordinator whose `X-User-ID` matches the sequence's `coordinator_user_id`, and submitting or revising a risk assessment is restricted to its author. Any other coordinator attempting one of these actions is rejected with `ERR_NOT_RESOURCE_OWNER`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the server's logical clock (§2.5) rather than wall-clock time.
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
- The `message` provides a human-readable explanation of what went wrong. Failures below the API layer use the same envelope: a request to an undefined path is rejected with `ERR_NOT_FOUND` (HTTP 404), a defined path with an unsupported method with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure with `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Both must be integers — a non-integer value is rejected with `ERR_VALIDATION` (HTTP 400) — and an integer value outside the permitted range is clamped rather than rejected: a `limit` below 1 is raised to 1, a `limit` above 100 is lowered to 100, and an `offset` below 0 is raised to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by creation order (earliest created first); the single exception is the department-signoff listing, which sorts by `created_at` ascending with `department` ascending as the tie-break (see §3.4). The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Fields

Every persisted resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Mutable resources additionally carry `updated_at`, in the same format and refreshed on every change, and `version`, an integer that starts at 1 and increments by one on every mutation, whether the mutation arrives through a direct client write or through a system-driven cascade. Derived-field recomputation counts as a mutation: when a cascade or a compensating action alters a resource, that resource's `updated_at` refreshes and its `version` increments.

Two resources are immutable records and therefore carry only `id` and `created_at`: a Certification and an Inspection have neither `updated_at` nor `version`. A certification, once recorded, changes only through revocation; an inspection, once recorded, never changes at all.

### 2.5. The Logical Clock

All time-dependent evaluation — certification expiry, inspection currency, permit validity windows, rehearsal time gates, the stoppage cooldown — runs against a server-maintained logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time. A `ProductionExecutive` advances it through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; the supplied instant must be strictly greater than the current logical time, and any attempt to hold or turn the clock back is rejected with `ERR_CLOCK_NOT_FORWARD` (HTTP 422). Clock advancement is lazy in its effects: derived states such as performer qualification, inspection currency, and permit window coverage are re-evaluated against the logical clock whenever they are read or checked by a gated transition, not eagerly when the clock moves.

### 2.6. Optimistic Concurrency Control

Three write operations guard against stale client views with an explicit version field; no other endpoint accepts a version field.

First, creating a risk assessment requires `expected_sequence_version` in the payload, carrying the `version` of the target sequence as the client last observed it. If the sequence's current `version` differs, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because approving a new assessment supersedes the currently pinned one, creating from a stale sequence view risks superseding an assessment the client never saw; the rejection rests purely on the stale-version check.

Second, attempting a take likewise requires `expected_sequence_version` matching the sequence's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Between the coordinator's readiness read and the take attempt, another writer may have created a superseding risk assessment — which advances the sequence's `version` while the sequence legitimately remains `READY` — and the stale-version check is what rejects the take.

Third, amending a production's budget requires `expected_production_version` matching the production's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Budget amendments legitimately supersede one another while posture stays unchanged, so only the version check distinguishes a stale amendment.

The sequence `version` advances on risk-assessment creation, on assessment approval, and on every take attempt, which is precisely what makes these stale views detectable.

### 2.7. Evaluation Order of Request Validation

Structurally malformed requests — a missing required field, an unknown field (including any client-supplied computed or system-managed field), an invalid enum value, a non-positive amount, a request body that is not valid JSON or not a JSON object (an absent body is treated as an empty object), or an empty string where a required textual reason such as `reason` or `corrective_action` is demanded — fail with `ERR_VALIDATION` (HTTP 400). Requests that are structurally sound are then evaluated against the domain rule tiers below, in this order; the first failing tier determines the rejection.

1. Header presence and role validity: `X-User-ID` and `X-User-Role` must be present and the role must be one of the six declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Endpoint authorization and ownership: the role must be permitted for the endpoint (`ERR_FORBIDDEN_ROLE`), and `Performer`-role writes must own the payload's `performer_id` (`ERR_NOT_RESOURCE_OWNER`).
3. Existence of every identifier — path identifiers first, then body identifiers — validated left to right, with the first missing identifier producing the corresponding not-found error (`ERR_PRODUCTION_NOT_FOUND`, `ERR_SEQUENCE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_EXECUTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`).
4. Stale-version rejection on the three version-guarded writes of §2.6 (`ERR_STALE_VERSION`).
5. The production posture gate. Sequence creation, design lock, and cancellation; risk-assessment creation, submission, approval, rejection, and revision; performer registration; certification creation and revocation; equipment registration and retirement; permit application, grant, and denial; hazard-pay creation, counter, agreement, and withdrawal; budget amendment; and insurance filing and acknowledgement are permitted in `SETUP` or `ACTIVE` posture. Rehearsal scheduling, completion, missed-marking, cancellation, and voiding; safety-meeting scheduling, starting, completing, and adjourning; signoff signing and refusal; inspection recording; take attempts, completions, and aborts; marking ready and reverifying readiness; and review opening and closing require `ACTIVE` and are blocked while `STOPPED` (`ERR_PRODUCTION_STOPPED`) or in any other non-`ACTIVE` posture (`ERR_PRODUCTION_NOT_ACTIVE`). Incident reporting is permitted in `ACTIVE` or `STOPPED` only (`ERR_PRODUCTION_NOT_ACTIVE` otherwise). Lifting a stoppage requires `STOPPED` (`ERR_PRODUCTION_NOT_STOPPED` otherwise); activation additionally requires insurance on file (`ERR_INSURANCE_NOT_FILED`). An operation of the `SETUP`-or-`ACTIVE` group attempted in any other posture — including `STOPPED` — is rejected with `ERR_PRODUCTION_NOT_ACTIVE`.
6. Entity-level transition preconditions per §3 — including negotiation turn-taking and the round cap — rejected with the transition's declared error id (`ERR_SEQUENCE_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`, `ERR_PERFORMER_NOT_QUALIFIED`, `ERR_NO_VALID_CERTIFICATION`, `ERR_REHEARSAL_INVALID_STATE`, `ERR_MEETING_INVALID_STATE`, `ERR_SIGNOFF_ALREADY_DECIDED`, `ERR_PERMIT_INVALID_STATE`, `ERR_ADJUSTMENT_INVALID_STATE`, `ERR_NOT_YOUR_TURN`, `ERR_NEGOTIATION_EXHAUSTED`, `ERR_INCIDENT_INVALID_STATE`, `ERR_EXECUTION_INVALID_STATE`, `ERR_REVIEW_INVALID_STATE`, `ERR_EQUIPMENT_INVALID_STATE`, `ERR_INSURANCE_INVALID_STATE`).
7. Certification discipline and validity for rehearsal scheduling and completion (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`).
8. Risk gates: the screening-band/category match and the board-score threshold (`ERR_CATEGORY_SCORE_MISMATCH`, `ERR_RISK_SCORE_ABOVE_THRESHOLD`).
9. The readiness gates of §3.6, evaluated in their fixed order (`ERR_REHEARSAL_QUOTA_NOT_MET`, `ERR_MEDIC_STANDBY_NOT_CONFIRMED`, `ERR_MEETING_REQUIREMENT_UNSATISFIED`, `ERR_EQUIPMENT_NOT_READY`, `ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH`, `ERR_INSURANCE_NOT_ACKNOWLEDGED`).
10. Overlap and uniqueness constraints — performer rehearsal overlap, facility buffer overlap, take-number uniqueness, one open review per sequence, one open negotiation per sequence-and-performer pair, and well-formed time ranges (`ERR_REHEARSAL_CONFLICT`, `ERR_FACILITY_BUFFER_CONFLICT`, `ERR_DUPLICATE_TAKE_NUMBER`, `ERR_REVIEW_ALREADY_OPEN`, `ERR_NEGOTIATION_ALREADY_OPEN`, `ERR_INVALID_TIME_RANGE`).
11. Cross-production referential integrity and segregation of duties (`ERR_CROSS_PRODUCTION_REFERENCE`, `ERR_SEGREGATION_OF_DUTIES_VIOLATION`).
12. Clock-relative rules — future-only rehearsal starts, completion and missed-marking time gates, execution-time permit windows, the stoppage cooldown, and forward-only clock advancement (`ERR_REHEARSAL_IN_PAST`, `ERR_REHEARSAL_TIME_GATE`, `ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH`, `ERR_STOPPAGE_COOLDOWN`, `ERR_CLOCK_NOT_FORWARD`).
13. Hazard-bump bounds on proposed and countered percentages (`ERR_BUMP_OUT_OF_RANGE`).
14. The budget authority check at agreement time (`ERR_BUDGET_EXCEEDED`).

### 2.8. Safety Cascades and Version Propagation

Safety state flows downhill through a two-link cascade. A production-level stoppage pushes every `READY` sequence of that production into `SAFETY_HOLD` (link one to two), and each sequence so held cancels its `SCHEDULED` rehearsals and adjourns its `SCHEDULED` or `IN_SESSION` safety meetings (link two to three). The same pattern fires from equipment and permits: a failed inspection quarantines the item, retirement removes it from service, and a revocation invalidates permit coverage — in each case dependent `READY` sequences drop into `SAFETY_HOLD` with the sub-cascade detailed in §3.5. Approving a new risk assessment for a `READY` or held sequence likewise forces that sequence into `SAFETY_HOLD`. Sequences placed on hold never recover automatically: each must individually pass the readiness gate again (§3.6) before work resumes. Every resource touched by a cascade — the production, each held sequence, each cancelled rehearsal, each adjourned meeting — records the mutation per §2.4, and the production and each affected sequence increment their `version` by one, so clients holding earlier versions detect the change through the rules of §2.6.

### 2.9. Monetary Precision

All monetary amounts — budgets, day rates, adjustment bases and payouts, declared insurance exposure and premiums — are integer numbers of cents. Percentages in negotiation payloads (`requested_pct`, `current_pct`, `counter_pct`) are decimal fractions: 0.40 means forty percent. Every monetary computation rounds half up to whole cents, and rounding is applied per line before any summation: each adjustment line is individually rounded, and sums are taken over the rounded lines, never over unrounded intermediate products. Risk scoring, by contrast, uses pure integer arithmetic with no rounding at all.

### 2.10. Referential Integrity and Segregation of Duties

The resource topology is flat: every resource is addressed by its bare `id`, and relationships are carried by foreign-key fields in payloads rather than by URL nesting. Every identifier appearing in a path or a payload — `production_id`, `sequence_id`, `performer_id`, `equipment_id`, `meeting_id`, and each element of `required_equipment_ids` — must exist, and identifiers are validated left to right, so the first missing identifier determines the 404 rejection. Beyond existence, cross-production integrity is enforced: every foreign key in a payload must reference an entity belonging to the same production as the primary reference — an assessment's `production_id` must equal its sequence's production, rehearsal and meeting references must stay within one production, and every element of a sequence's `required_equipment_ids` must belong to that sequence's production — and a reference that crosses productions is rejected with `ERR_CROSS_PRODUCTION_REFERENCE` (HTTP 422).

Three segregation-of-duties walls are structural. The coordinator who authored a risk assessment may not approve it: an approval whose `X-User-ID` equals the assessment's `assessor_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The coordinator who created a sequence may not decide its department signoffs: a signature or refusal whose `X-User-ID` equals the sequence's `coordinator_user_id` is rejected the same way. And the coordinator who registered an equipment item may not inspect it: an inspection whose `X-User-ID` equals the item's `registered_by_user_id` is rejected the same way. Combined with the `Performer` ownership rule of §2.1, no safety-critical decision on this platform is single-handed.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Production: Budget, Insurance, and Activation

A `ProductionExecutive` opens a production by supplying a display `name` and a `total_budget_cents`, which must be a positive integer number of cents. The new production starts with `posture` `SETUP`, `insurance_status` `UNFILED`, `committed_pay_cents` zero, `stopped_at` and `stop_reason` null, and `version` 1. These two status fields are parallel state dimensions on one entity: `posture` walks `SETUP → ACTIVE → STOPPED → ACTIVE → WRAPPED`, while `insurance_status` walks `UNFILED → FILED → ACKNOWLEDGED`, and each evolves independently of the other.

The budget may be amended while the production is in `SETUP` or `ACTIVE`; because amendments legitimately supersede one another while posture stays unchanged, the amendment write is version-guarded per §2.6, carrying the new `total_budget_cents` alongside `expected_production_version`, and a successful amendment increments the production's `version` by one.

At any time, a computed production summary reports four figures: `committed_pay_cents`, `open_negotiation_exposure_cents`, `endorsement_premium_cents`, and `estimated_total_cost_cents`. The roll-up works on adjustment lines: each line is the adjustment's `base_amount_cents` multiplied by one plus its `current_pct`, rounded half up to whole cents. The rounding order is pinned — every line is rounded first and only then summed, never the reverse — so two lines of 133,507 cents each sum to 267,014 where a sum-then-round implementation would yield 267,013. `committed_pay_cents` sums those lines over the production's `AGREED` adjustments, `open_negotiation_exposure_cents` sums them over the production's `PROPOSED` and `COUNTERED` adjustments, and `estimated_total_cost_cents` is the committed pay plus the open negotiation exposure plus the endorsement premium.

Before the production can go active, the executive files an insurance notification declaring `declared_exposure_cents` — a non-negative integer number of cents, zero permitted — to the carrier. Filing computes `endorsement_premium_cents` as the declared exposure multiplied by a tiered rate, rounded half up to whole cents: two percent when the declared exposure is at most 100,000,000 cents, three percent when it is greater than 100,000,000 cents and at most 500,000,000 cents, and four percent when it exceeds 500,000,000 cents. Tier boundaries are inclusive downward, so an exposure of exactly 100,000,000 cents prices at two percent. Filing requires `insurance_status` `UNFILED` and moves it to `FILED` — from any other insurance state the filing is rejected with `ERR_INSURANCE_INVALID_STATE`. Recording the carrier's acknowledgement requires `FILED` and moves insurance to `ACKNOWLEDGED`, with the same error id guarding any other starting state.

Activation moves `posture` from `SETUP` to `ACTIVE` and is permitted only when insurance is `FILED` or `ACKNOWLEDGED`: an activation attempt with insurance still `UNFILED` is rejected with `ERR_INSURANCE_NOT_FILED`, and activation from any posture other than `SETUP` is rejected with `ERR_PRODUCTION_NOT_ACTIVE`; the posture check is evaluated first, so an attempt failing both is rejected with `ERR_PRODUCTION_NOT_ACTIVE`. Activation, filing, and acknowledgement each increment the production's `version` by one.

### 3.2. Designing a Sequence and the Risk Assessment Cycle

A `StuntCoordinator` drafts a sequence within a production by supplying the `production_id`, a display `name`, the `hazard_class` (one of `FIRE`, `HEIGHT`, `VEHICLE`, `WATER`, `PYRO`, `AERIAL`, `FIGHT`), the declared `risk_category` (one of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), the planned execution window `scheduled_execution_start` and `scheduled_execution_end` — the end must be strictly after the start, else `ERR_INVALID_TIME_RANGE` — and `required_equipment_ids`, an array of equipment item identifiers that may be empty; every element must reference an equipment item of the same production (`ERR_CROSS_PRODUCTION_REFERENCE` otherwise). Sequence creation is permitted in `SETUP` or `ACTIVE` posture. The new sequence starts `DRAFT` with `design_revision` 1, both rehearsal counters at zero, `coordinator_user_id` set to the creator, and `required_rehearsal_count`, `board_score`, `current_assessment_id`, and `medic_standby_required` all null until the design is locked.

Risk assessment is a cyclic, multi-round workflow. Any coordinator creates an assessment against a sequence with `production_id`, `sequence_id`, integer `severity_rating` and `likelihood_rating` (each from 1 to 5), optional `mitigation_notes` defaulting to an empty string, and the OCC field `expected_sequence_version` per §2.6. The payload's `production_id` must equal the sequence's production. Creation requires posture `SETUP` or `ACTIVE`, requires the sequence to be outside `EXECUTED`, `REVIEWED`, and `CANCELLED` (`ERR_SEQUENCE_INVALID_STATE` otherwise), starts the assessment in `DRAFT`, computes `screening_score` as `severity_rating` multiplied by `likelihood_rating` — an integer from 1 to 25 — records the creator as `assessor_user_id`, and increments the sequence's `version` by one.

Submitting moves the assessment `DRAFT → SUBMITTED` and is restricted to the assessment's author. Submission requires the sequence still outside `EXECUTED`, `REVIEWED`, and `CANCELLED` (`ERR_SEQUENCE_INVALID_STATE`), and enforces category consistency: the screening band of the `screening_score` must equal the sequence's declared `risk_category`, where `LOW` spans scores 1 through 5, `MEDIUM` spans 6 through 11, `HIGH` spans 12 through 19, and `CRITICAL` spans 20 through 25; a mismatch is rejected with `ERR_CATEGORY_SCORE_MISMATCH`.

A `SafetyOfficer` then decides. Approval moves `SUBMITTED → APPROVED` — from any other state it is rejected with `ERR_ASSESSMENT_INVALID_STATE` — and the approver must not be the author: an approver whose `X-User-ID` equals the assessment's `assessor_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Approval carries heavy side effects. If another assessment of the same sequence is currently `APPROVED`, that assessment becomes `SUPERSEDED` and the new assessment's `supersedes_assessment_id` points at it; `supersedes_assessment_id` is null otherwise. The sequence's `current_assessment_id` is re-pinned to the newly approved assessment and its `board_score` recomputed. The sequence's `version` increments by one, which is what drives stale-version rejection for assessment creation and take attempts. And if the sequence is `READY` or already in `SAFETY_HOLD`, its readiness is invalidated and it is forced to `SAFETY_HOLD`. Rejection moves `SUBMITTED → REJECTED` and records the supplied `reason` into `rejection_reason`, which is null at all other times. The author may then revise (`REJECTED → DRAFT`, else `ERR_ASSESSMENT_INVALID_STATE`), replacing `severity_rating`, `likelihood_rating`, and `mitigation_notes` with the payload values (`mitigation_notes` again defaulting to an empty string when omitted), recomputing `screening_score`, and clearing `rejection_reason`; the loop permits unlimited revision rounds, and the move `APPROVED → SUPERSEDED` only ever happens system-side, driven by the next approval.

Locking the design — `DRAFT → DESIGN_LOCKED`, owner coordinator only, posture `SETUP` or `ACTIVE`, with any other sequence state rejected as `ERR_SEQUENCE_INVALID_STATE` — is the gate that pins everything the later readiness checks rely on. It requires at least one `APPROVED` assessment of the sequence (absent that, `ERR_SEQUENCE_INVALID_STATE`), and it evaluates the board variant of the risk score on the most recently created `APPROVED` assessment: `severity_rating` multiplied by `likelihood_rating`, plus a hazard weight of 6 for `PYRO`, 5 for `FIRE`, 4 each for `HEIGHT`, `VEHICLE`, and `AERIAL`, 3 for `WATER`, and 2 for `FIGHT`, minus a mitigation credit of 3 when `mitigation_notes` is non-empty. Identical ratings can therefore pass screening yet fail the lock: a 3-by-4 `VEHICLE` assessment screens at 12 but boards at 16. If the board score reaches 26 or more, the lock is rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD`; a board score of at most 25 locks. The declared `risk_category` must then match the screening band of that pinned assessment, else `ERR_CATEGORY_SCORE_MISMATCH` — the board-score threshold is evaluated before the category-band match, so an attempt failing both is rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD`.

On a successful lock, `current_assessment_id` is pinned to that most recently created `APPROVED` assessment, `board_score` is stored, and two derived fields are computed. `required_rehearsal_count` is the category quota — 1 for `LOW`, 2 for `MEDIUM`, 3 for `HIGH`, 4 for `CRITICAL` — plus one additional rehearsal when any element of `required_equipment_ids` has `equipment_type` `PYRO_DEVICE` or `CRANE`. `medic_standby_required` is true exactly when the `risk_category` is `HIGH` or `CRITICAL` or the `hazard_class` is `FIRE`, `PYRO`, `VEHICLE`, or `WATER`. The sequence's `version` increments by one.

### 3.3. Performers, Certifications, and Rehearsal Practice

The coordinator registers performers with `production_id`, `first_name`, `last_name`, a positive `base_day_rate_cents`, and `union_status` (`SAG_AFTRA` or `NON_UNION`); a new performer starts `REGISTERED` with `completed_rehearsal_minutes` at zero.

Qualification is certification-driven. A certification record carries `performer_id`, a `discipline` drawn from the same seven values as `hazard_class`, a `level` of `BASIC`, `ADVANCED`, or `MASTER`, and the `issued_at` and `expires_at` timestamps; certification creation and revocation are permitted in `SETUP` or `ACTIVE` posture. A certification is valid exactly when `revoked` is false and `expires_at` lies strictly after the comparison instant — a certification expiring exactly at the comparison instant is already expired. The comparison instant depends on context: the current logical time for status derivation, reinstatement, and pay agreement; the rehearsal's own `scheduled_start` for rehearsal scheduling; and the current logical time again for rehearsal completion. A performer's effective status is derived lazily, at read time and at every gated transition: `SUSPENDED` when the stored status is `SUSPENDED`; otherwise `QUALIFIED` when at least one valid certification exists; otherwise `REGISTERED`. Adding a performer's first valid certification moves them `REGISTERED → QUALIFIED`, and when the last valid certification expires under the logical clock or is revoked, the performer drops back to `REGISTERED`.

A `SafetyOfficer` may suspend a performer — with a `reason` — only from `QUALIFIED` (`ERR_PERFORMER_NOT_QUALIFIED` otherwise), moving them to `SUSPENDED`, and may reinstate only from `SUSPENDED` (again `ERR_PERFORMER_NOT_QUALIFIED` otherwise), provided at least one valid certification exists at reinstatement time (else `ERR_NO_VALID_CERTIFICATION`). Revoking a certification — optionally with a `reason` — sets its `revoked` flag true; the record is otherwise immutable, and if no valid certification remains, a `QUALIFIED` performer drops to `REGISTERED`. Revoking an already-revoked certification succeeds idempotently, leaving the record revoked.

Rehearsals bind a performer to a sequence at a facility. Scheduling one requires posture `ACTIVE` and not `STOPPED`, the sequence in `DESIGN_LOCKED` or `READY` (`ERR_SEQUENCE_INVALID_STATE` otherwise), and a payload of `production_id`, `sequence_id`, `performer_id`, `facility`, `scheduled_start`, and `scheduled_end`. The start must lie strictly in the future of the logical clock (`ERR_REHEARSAL_IN_PAST`) and the end must be after the start (`ERR_INVALID_TIME_RANGE`); `duration_minutes` is computed as the whole minutes between the two. The performer must be `QUALIFIED` at scheduling (`ERR_PERFORMER_NOT_QUALIFIED`) and must hold a valid certification whose `discipline` equals the sequence's `hazard_class`, validity measured against the rehearsal's `scheduled_start` (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`). Finally, the performer overlap rule: across all sequences of the production, the performer must have no existing rehearsal in `SCHEDULED` or `COMPLETED` whose window overlaps the new one, where two windows overlap exactly when the new start falls before the existing end and the existing start falls before the new end; touching windows — one beginning precisely when the other ends — are allowed. A violation is rejected with `ERR_REHEARSAL_CONFLICT`. A new rehearsal starts `SCHEDULED`.

Completing a rehearsal (the owner coordinator of the sequence; `SCHEDULED → COMPLETED`) may not occur before `scheduled_start`: completion at or after the start is permitted, and an earlier attempt is rejected with `ERR_REHEARSAL_TIME_GATE`. Completion also re-checks that the performer is `QUALIFIED` at completion time (`ERR_PERFORMER_NOT_QUALIFIED`). Each completion feeds invariant I2: the sequence's `completed_rehearsal_count` increments by one, the sequence's `completed_rehearsal_minutes` grows by `duration_minutes`, and the performer's `completed_rehearsal_minutes` grows by the same amount.

Marking a rehearsal missed (owner coordinator) moves `SCHEDULED → MISSED` and requires the logical clock to be strictly past `scheduled_end`; marking at or before the end is rejected with `ERR_REHEARSAL_TIME_GATE`, and only a `SCHEDULED` rehearsal can be marked missed or cancelled (`ERR_REHEARSAL_INVALID_STATE` otherwise). Cancellation moves `SCHEDULED → CANCELLED` and also fires system-side when the sequence is cancelled or held through the stoppage cascade. A `SafetyOfficer` may void a `COMPLETED` rehearsal — from any other state, `ERR_REHEARSAL_INVALID_STATE` — recording the supplied `reason` into `void_reason` and running the compensating action for invariant I2: the sequence's `completed_rehearsal_count` decrements by one and both minute counters shrink by the rehearsal's `duration_minutes`.

### 3.4. Safety Meetings and Department Sign-Off

Safety meetings are the forum in which departments accept a locked design. Scheduling one requires posture `ACTIVE` and not `STOPPED`, a sequence in `DESIGN_LOCKED` or `READY`, and a payload of `production_id`, `sequence_id`, `facility`, `scheduled_start`, and `scheduled_end` with the end after the start (`ERR_INVALID_TIME_RANGE`). Creation pins the meeting's `design_revision` to the sequence's current `design_revision` — readiness later demands a completed meeting whose pinned revision equals the sequence's then-current revision, so any reshoot or deficiency loop invalidates older meetings. Creation also fans out one `PENDING` DepartmentSignoff row per required department: the base set is `CAMERA`, `ELECTRIC`, `GRIP`, and `STUNTS`; `MEDIC` is added when `medic_standby_required` is true; and `FIRE_SAFETY` is added when the sequence's `hazard_class` is `FIRE` or `PYRO`. Each signoff row references its meeting through `meeting_id`, carries its `department`, and starts with `signer_user_id`, `conditions`, `refusal_reason`, and `decided_at` all null. The meeting itself starts `SCHEDULED` with `chair_user_id` null until started.

Facilities are buffered resources. A new meeting conflicts with an existing meeting at the same facility — across all sequences of the production, considering only existing meetings in `SCHEDULED` or `IN_SESSION` — when the new meeting starts before thirty minutes after the existing meeting ends and the existing meeting starts before thirty minutes after the new meeting ends. The buffer is a symmetric 1,800 seconds on both sides, and a gap of exactly thirty minutes between the two windows is allowed; a violation is rejected with `ERR_FACILITY_BUFFER_CONFLICT`.

A `SafetyOfficer` starts the meeting (`SCHEDULED → IN_SESSION`; from any other state, `ERR_MEETING_INVALID_STATE`), which records the officer as `chair_user_id`; starting requires posture `ACTIVE` — `ERR_PRODUCTION_STOPPED` while stopped, `ERR_PRODUCTION_NOT_ACTIVE` in `SETUP`. While the meeting is `IN_SESSION`, each `DepartmentHead` decides their department's signoff. Signing with no `conditions` in the payload moves the row to `SIGNED`; signing with non-empty `conditions` moves it to `SIGNED_WITH_CONDITIONS` and records them; refusing — with a `reason`, recorded as `refusal_reason` — moves it to `REFUSED`. Every decision records `signer_user_id` and the `decided_at` timestamp. A signoff no longer `PENDING` rejects any further decision with `ERR_SIGNOFF_ALREADY_DECIDED`; decisions attempted while the meeting is not `IN_SESSION` are rejected with `ERR_MEETING_INVALID_STATE`; and a signer whose `X-User-ID` equals the sequence's `coordinator_user_id` — the coordinator may not sign off their own design — is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

Completing the meeting (`IN_SESSION → COMPLETED`) requires every signoff decided — `SIGNED`, `SIGNED_WITH_CONDITIONS`, or `REFUSED`; while any signoff remains `PENDING` the completion is rejected with `ERR_SIGNOFFS_PENDING`. A meeting containing a refusal still completes, but it does not satisfy the readiness gate of §3.6. Adjournment moves `SCHEDULED` or `IN_SESSION` to `ADJOURNED` (`ERR_MEETING_INVALID_STATE` from any other state), is available to the `SafetyOfficer` on demand, and also fires system-side on production stoppage and sequence cancellation. When listed, signoffs sort by `created_at` ascending with `department` ascending as the tie-break.

### 3.5. Equipment, Inspections, and Permits

Equipment registration — permitted in `SETUP` or `ACTIVE` — records `production_id`, `name`, `equipment_type` (one of `RIGGING`, `PYRO_DEVICE`, `VEHICLE`, `HARNESS`, `AIRBAG`, `CRANE`), `serial_number`, and a positive `inspection_interval_hours`. The item starts `IN_SERVICE` with `registered_by_user_id` set to the registering coordinator, `last_passed_inspection_at` null, and `inspection_current` false until the first passing inspection.

Inspections are recorded by an `EquipmentInspector` with `equipment_id`, an `outcome` of `PASSED`, `CONDITIONAL`, or `FAILED`, and optional `notes` defaulting to an empty string; `inspected_at` is stamped with the current logical time at creation. Recording an inspection requires posture `ACTIVE` and not `STOPPED`, and the inspector must not be the item's registrar — an inspector whose `X-User-ID` equals the item's `registered_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Inspection currency is recomputed whenever the item is read and at every gate that checks it: `last_passed_inspection_at` is the `inspected_at` of the most recent inspection with outcome `PASSED` or `CONDITIONAL`, taken chronologically by `inspected_at` with ties broken by `created_at` ascending, and null when no such inspection exists. `inspection_current` is true exactly when that timestamp exists and the moment `inspection_interval_hours` hours after it is still strictly in the future; at the exact instant the interval elapses, the inspection is already stale.

The three outcomes diverge sharply. `PASSED` updates `last_passed_inspection_at` and returns a `QUARANTINED` item to `IN_SERVICE`. `CONDITIONAL` updates `last_passed_inspection_at` but leaves the item's status unchanged — it does not lift a quarantine. `FAILED` does not update `last_passed_inspection_at` at all; instead it moves an `IN_SERVICE` item to `QUARANTINED`. Quarantine is a cascade source per §2.8: every `READY` sequence whose `required_equipment_ids` contains the failed item drops to `SAFETY_HOLD`, and each such sequence's `SCHEDULED` rehearsals are cancelled. Retirement is available from `IN_SERVICE` or `QUARANTINED` — from `RETIRED` it is rejected with `ERR_EQUIPMENT_INVALID_STATE` — and is terminal, triggering the same hold-and-rehearsal cascade for every `READY` sequence requiring the item.

Permits cover special equipment and effects work. Applying — in `SETUP` or `ACTIVE` posture — records `production_id`, `permit_type` (one of `PYROTECHNICS`, `CRANE_OPERATION`, `AERIAL_WORK`, `FIRE_EFFECTS`, `WATER_WORK`), the issuing `jurisdiction`, and the inclusive validity window `valid_from` through `valid_until`, with the end after the start (`ERR_INVALID_TIME_RANGE`); the application starts `APPLIED`. A `ProductionExecutive` grants (`APPLIED → GRANTED`) or denies (`APPLIED → DENIED`) the application, and either adjudication from any other state is rejected with `ERR_PERMIT_INVALID_STATE`. A `SafetyOfficer` revokes a `GRANTED` permit — with a `reason`, and from any other state `ERR_PERMIT_INVALID_STATE` — moving it to `REVOKED`, terminal. Revocation cascades: every `READY` sequence requiring that `permit_type` drops to `SAFETY_HOLD`, and the sub-cascade cancels each such sequence's `SCHEDULED` rehearsals and adjourns its `SCHEDULED` or `IN_SESSION` meetings.

### 3.6. The Readiness Gate and Safety Holds

Marking a sequence ready — `DESIGN_LOCKED → READY`, owner coordinator only, with any other sequence state rejected as `ERR_SEQUENCE_INVALID_STATE` — runs the full readiness gate. The production must be `ACTIVE`: while the production is stopped the rejection is `ERR_PRODUCTION_STOPPED`, and in any other posture it is `ERR_PRODUCTION_NOT_ACTIVE`. The remaining gates then evaluate in a fixed order, and the first failure determines the rejection:

1. Rehearsal quota: the sequence's `completed_rehearsal_count` must be at least its `required_rehearsal_count`, with exact equality passing, else `ERR_REHEARSAL_QUOTA_NOT_MET`.
2. Medic standby: when `medic_standby_required` is true, at least one `COMPLETED` safety meeting of this sequence pinned at the current `design_revision` must carry a `MEDIC` signoff in `SIGNED` or `SIGNED_WITH_CONDITIONS` — that meeting need not itself satisfy gate 3 — else `ERR_MEDIC_STANDBY_NOT_CONFIRMED`. This check is deliberately evaluated before the meeting-satisfaction gate, so a missing medic confirmation surfaces as its own error rather than being masked by the broader meeting failure.
3. Meeting satisfaction: there must exist a safety meeting of this sequence in `COMPLETED` status whose pinned `design_revision` equals the sequence's current `design_revision` and all of whose department signoffs stand in `SIGNED` or `SIGNED_WITH_CONDITIONS` — a meeting containing any `REFUSED` signoff does not qualify — else `ERR_MEETING_REQUIREMENT_UNSATISFIED`.
4. Equipment readiness: every element of `required_equipment_ids` must reference an item in `IN_SERVICE` status whose `inspection_current` is true; a quarantined, retired, never-inspected, or stale-inspected item fails with `ERR_EQUIPMENT_NOT_READY`.
5. Permit coverage: for each permit type required of the sequence there must exist a `GRANTED` permit of this production whose validity window covers the scheduled execution: `valid_from` at or before `scheduled_execution_start` and `valid_until` at or after `scheduled_execution_end`, else `ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH`. The required permit types are derived from the sequence's `hazard_class` together with the `equipment_type` of its required equipment: `hazard_class` `PYRO` requires `PYROTECHNICS`, `FIRE` requires `FIRE_EFFECTS`, `WATER` requires `WATER_WORK`, and `AERIAL` requires `AERIAL_WORK`, while `HEIGHT`, `VEHICLE`, and `FIGHT` require no hazard-driven permit; and a required equipment item of type `PYRO_DEVICE` requires `PYROTECHNICS` and one of type `CRANE` requires `CRANE_OPERATION`, while `RIGGING`, `VEHICLE`, `HARNESS`, and `AIRBAG` items require no equipment-driven permit. A sequence whose hazard class and required equipment yield no required permit type passes this gate with no permit at all.
6. Insurance acknowledgement: when the sequence's `risk_category` is `HIGH` or `CRITICAL`, the production's `insurance_status` must be `ACKNOWLEDGED`, else `ERR_INSURANCE_NOT_ACKNOWLEDGED`.

A successful gate increments the sequence's `version` by one.

Readiness is fragile by design. Four events force a `READY` sequence back into `SAFETY_HOLD`: the production stops; a required equipment item is quarantined or retired; a required permit is revoked; or a new risk assessment of the sequence is approved. The sub-cascades differ by trigger, as §3.5 and §3.8 detail: holds entered through production stoppage carry both rehearsal cancellation and meeting adjournment, holds from equipment carry rehearsal cancellation, holds from permit revocation carry both, and holds from assessment approval invalidate readiness without touching the schedule. Lifting a production stoppage does not restore readiness — held sequences remain held, and each must individually pass re-verification.

Re-verifying readiness — `SAFETY_HOLD → READY`, owner coordinator only — requires the sequence in `SAFETY_HOLD` (`ERR_SEQUENCE_INVALID_STATE` otherwise) and posture `ACTIVE` (`ERR_PRODUCTION_STOPPED` while stopped), then re-runs every mark-ready gate, in the same order and with the same error ids, against current state and the current `design_revision`. Success returns the sequence to `READY` and increments its `version` by one.

The first completed take moves a `READY` sequence to `EXECUTED` (§3.8), and the post-stunt review then moves it to `REVIEWED` or loops it back to `DESIGN_LOCKED`. Cancellation moves a sequence from `DRAFT`, `DESIGN_LOCKED`, `READY`, `SAFETY_HOLD`, or `EXECUTED` to `CANCELLED` — from `REVIEWED` or `CANCELLED` the attempt is rejected with `ERR_SEQUENCE_INVALID_STATE` — and is available to the owner coordinator and to a `ProductionExecutive`, optionally carrying a `reason`. Cancellation compensates everything downstream: the sequence's `SCHEDULED` rehearsals become `CANCELLED`, its `SCHEDULED` or `IN_SESSION` meetings become `ADJOURNED`, its `PROPOSED` or `COUNTERED` pay adjustments become `WITHDRAWN`, and its `AGREED` adjustments become `VOIDED` with the committed-pay compensation of §3.7. The sequence's `version` increments by one.

### 3.7. Hazard-Pay Negotiation and Committed Pay

Hazard pay is a two-party negotiation between a performer and the coordinator, conducted as offers and counter-offers on a PayAdjustment. Opening one takes `production_id`, `sequence_id`, `performer_id`, `adjustment_type` (`HAZARD_BUMP` or `STUNT_DOUBLE`), a positive `base_amount_cents`, and the `requested_pct` offered as a decimal fraction. Either side may open: when the caller's role is `Performer`, the payload's `performer_id` must equal `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`); the performer must be `QUALIFIED` (`ERR_PERFORMER_NOT_QUALIFIED`); the sequence must be outside `EXECUTED`, `REVIEWED`, and `CANCELLED` (`ERR_SEQUENCE_INVALID_STATE`); and at most one negotiation may be open — `PROPOSED` or `COUNTERED` — per sequence-and-performer pair (`ERR_NEGOTIATION_ALREADY_OPEN`). Creation is permitted in `SETUP` or `ACTIVE` posture. The new adjustment starts `PROPOSED` with `round_count` zero, `current_pct` equal to `requested_pct`, `proposer_by` and `last_offer_by` both recording which side opened (`PERFORMER` or `COORDINATOR`), and `final_amount_cents` and `payable_amount_cents` null until agreement. The same ownership rule governs the follow-on moves: on counter, agree, and withdraw, a `Performer`-role caller whose `X-User-ID` does not equal the adjustment's `performer_id` is rejected with `ERR_NOT_RESOURCE_OWNER`.

Every proposed or countered percentage is bounds-checked before it lands — at creation against `requested_pct` and at each counter against `counter_pct` — and a violation is rejected with `ERR_BUMP_OUT_OF_RANGE`. The bump in cents is the `base_amount_cents` multiplied by the percentage, rounded half up to whole cents. The floor is zero for a `NON_UNION` performer; for `SAG_AFTRA` it is the larger of ten percent of the base (rounded half up) and a union floor of 15,000 cents. The cap is the base multiplied by the category cap — fifteen percent for `LOW`, thirty-five percent for `MEDIUM`, sixty percent for `HIGH`, one hundred percent for `CRITICAL` — rounded half up to whole cents, plus a special-equipment surcharge of 25,000 cents when any element of the sequence's `required_equipment_ids` has `equipment_type` `PYRO_DEVICE` or `CRANE`. The bump is valid exactly when it falls at or between the floor and the cap, inclusively.

At creation the system also stores `provisional_estimate_cents`: the base, plus the bump at `requested_pct` rounded half up to whole cents, plus a take bonus of 50,000 cents for exactly one planned take. The provisional figure assumes one take and the opening percentage; the settled figures diverge once negotiation moves the percentage and more takes complete — a base of 200,000 cents at 0.40 estimates provisionally at 330,000 cents, yet pays 380,000 after two completed takes.

Countering submits a `counter_pct` and is strictly turn-based: the adjustment must stand in `PROPOSED` or `COUNTERED` (`ERR_ADJUSTMENT_INVALID_STATE` otherwise) and the caller's side must differ from `last_offer_by` — the side that made the last offer may not counter its own offer (`ERR_NOT_YOUR_TURN`). The state check is evaluated before the turn check, and the turn check before the round cap, so a counter by the wrong side at the cap is rejected with `ERR_NOT_YOUR_TURN` and does not exhaust the negotiation. The negotiation allows at most six rounds: a counter attempted while `round_count` is already 6 is rejected with `ERR_NEGOTIATION_EXHAUSTED`, and that failed attempt itself exhausts the negotiation, moving the adjustment to `EXPIRED` with no pay committed. A successful counter sets `current_pct` to `counter_pct`, increments `round_count` by one, flips `last_offer_by` to the caller's side, and lands the adjustment in `COUNTERED`; further counters cycle `COUNTERED → COUNTERED` under the same rules.

Agreement is the accepting side's move — again the side that did not make the last offer, with a self-acceptance rejected as `ERR_NOT_YOUR_TURN` — from `PROPOSED` or `COUNTERED` (`ERR_ADJUSTMENT_INVALID_STATE` otherwise); as with countering, the state check is evaluated before the turn check. Agreement re-checks that the performer is `QUALIFIED` (`ERR_PERFORMER_NOT_QUALIFIED`) and the sequence is outside `EXECUTED`, `REVIEWED`, and `CANCELLED` (`ERR_SEQUENCE_INVALID_STATE`), then runs the budget authority check, whose evaluation order is pinned to break the circularity between the reserve and the commitment the agreement itself creates. First, the production's `committed_pay_cents` is read as it stands before this agreement. Second, the reserve is computed as ten percent of the remaining headroom — `total_budget_cents` minus that pre-agreement committed pay — rounded half up to whole cents. Third, the available amount is the budget minus the pre-agreement committed pay minus the reserve. Fourth, the new line is the adjustment's `base_amount_cents` multiplied by one plus `current_pct`, rounded half up to whole cents. The new line must be at most the available amount — exact equality passes — else the agreement is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402). On success, `final_amount_cents` is computed as the base plus the bump at `current_pct` rounded half up, `payable_amount_cents` is initialized equal to `final_amount_cents` because no takes have completed yet, and the production's `committed_pay_cents` grows by `final_amount_cents` — invariant I1.

Withdrawing is the proposer's prerogative: from `PROPOSED` or `COUNTERED` (`ERR_ADJUSTMENT_INVALID_STATE` otherwise), the caller's side must equal `proposer_by` — the other side's withdrawal attempt is rejected with `ERR_NOT_YOUR_TURN` — moving the adjustment to `WITHDRAWN`. Sequence cancellation withdraws open adjustments system-side and voids agreed ones: the move `AGREED → VOIDED` subtracts `final_amount_cents` from the production's `committed_pay_cents`, the compensating action that keeps invariant I1 exact. That invariant holds at all times: a production's `committed_pay_cents` equals the sum of `final_amount_cents` over exactly its `AGREED` pay adjustments.

### 3.8. Takes, Incidents, Stoppages, and Post-Stunt Review

With a sequence `READY`, the owner coordinator attempts takes. Each attempt carries `production_id`, `sequence_id`, a `take_number` of at least 1, and the OCC field `expected_sequence_version` per §2.6; the sequence must stand in `READY` (`ERR_SEQUENCE_INVALID_STATE` otherwise), posture must be `ACTIVE` and not `STOPPED`, and `take_number` must be unique across all executions of the sequence regardless of their status — a reused number is rejected with `ERR_DUPLICATE_TAKE_NUMBER` even if the earlier take was aborted. At attempt time the permit and equipment gates are re-evaluated against the current logical instant rather than the scheduled window: every required permit type must have a `GRANTED` permit whose inclusive window contains the current instant (`ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH`), and every required equipment item must be `IN_SERVICE` with a current inspection (`ERR_EQUIPMENT_NOT_READY`). The attempt starts `ATTEMPTED` with `executed_at` stamped to the logical clock, `abort_reason` null, `safety_related` false, and the sequence's `version` increments by one.

Completing a take — `ATTEMPTED → COMPLETED`, with any other state rejected as `ERR_EXECUTION_INVALID_STATE` — has two side effects. If it is the sequence's first completed take, the sequence moves `READY → EXECUTED` and its `version` increments by one. And every `AGREED` pay adjustment of the sequence re-prices: `payable_amount_cents` becomes `final_amount_cents` plus 50,000 cents multiplied by the count of the sequence's `COMPLETED` executions — the actual completed take count, not the planned one.

Aborting a take (`ATTEMPTED → ABORTED`) records `abort_reason` and `safety_related` from the payload. When `safety_related` is true, the payload must also include `incident_severity` — its absence is rejected with `ERR_VALIDATION` — and the system auto-creates an incident in `REPORTED` status whose `severity` equals `incident_severity`, whose `sequence_id` is the take's sequence, whose `production_id` is the take's production, whose `occurred_at` is stamped to the current logical time, whose `description` equals the abort's `abort_reason`, and whose `reporter_user_id` is the aborting coordinator; if that severity is `SERIOUS` or `CRITICAL`, the production-stoppage cascade fires, the chain running from the abort to the incident to `STOPPED` to `SAFETY_HOLD`.

Anyone on set — `SafetyOfficer`, `StuntCoordinator`, `DepartmentHead`, or `ProductionExecutive` — may report an incident with `production_id`, an optional `sequence_id` (null for production-level incidents), a `severity` of `NEAR_MISS`, `MINOR`, `SERIOUS`, or `CRITICAL`, the `occurred_at` timestamp, and a `description`. Reporting is permitted in `ACTIVE` or `STOPPED` posture (`ERR_PRODUCTION_NOT_ACTIVE` in `SETUP` or `WRAPPED`), starts the incident `REPORTED`, and records the caller as `reporter_user_id`. Reporting a `SERIOUS` or `CRITICAL` incident while the production is `ACTIVE` stops the production exactly as a manual stoppage does. A manual stoppage — invoked by a `SafetyOfficer` or `ProductionExecutive` with a `reason` — requires posture `ACTIVE` (`ERR_PRODUCTION_NOT_ACTIVE` otherwise). Either path records `stopped_at` as the current logical time and `stop_reason` as the request's reason or the triggering incident's id, pushes every `READY` sequence of the production to `SAFETY_HOLD`, cancels those held sequences' `SCHEDULED` rehearsals, adjourns their `SCHEDULED` or `IN_SESSION` safety meetings, and increments the production's `version` by one.

The investigation workflow belongs to the `SafetyOfficer`: opening an investigation requires `REPORTED` (`ERR_INCIDENT_INVALID_STATE` otherwise) and moves the incident to `UNDER_INVESTIGATION`; closing requires `UNDER_INVESTIGATION` (again `ERR_INCIDENT_INVALID_STATE`) and a non-empty `corrective_action` — empty or missing, the close is rejected with `ERR_VALIDATION` — ending at `CLOSED`.

Lifting a stoppage is the `ProductionExecutive`'s exclusive call and carries three gates. The posture must be `STOPPED`, else `ERR_PRODUCTION_NOT_STOPPED`. No incident of the production may be open at `SERIOUS` or `CRITICAL` severity — open meaning `REPORTED` or `UNDER_INVESTIGATION` — else `ERR_SERIOUS_INCIDENTS_OPEN`. And the logical clock must have reached at least 86,400 seconds — twenty-four hours — past `stopped_at`, with exact equality passing; earlier attempts are rejected with `ERR_STOPPAGE_COOLDOWN`. Lifting returns the production to `ACTIVE` and increments its `version` by one, but sequences in `SAFETY_HOLD` stay held: each must re-verify individually per §3.6.

After execution, a `SafetyOfficer` opens a post-stunt review with `production_id` and `sequence_id`; the sequence must be `EXECUTED` (`ERR_SEQUENCE_INVALID_STATE` otherwise), at most one review may stand `OPEN` per sequence (`ERR_REVIEW_ALREADY_OPEN`), and the opener is recorded as `reviewer_user_id`. Closing a review requires it `OPEN` (`ERR_REVIEW_INVALID_STATE` otherwise) and supplies the `outcome` and the `findings`. The outcome drives the sequence, but only while the sequence still stands in `EXECUTED`: if the sequence has left `EXECUTED` since the review was opened — for example through cancellation — the review still closes and the outcome leaves the sequence unchanged. `ACCEPTED_AS_SHOT` moves the sequence `EXECUTED → REVIEWED`, terminal. `RESHOOT_REQUIRED` returns it `EXECUTED → DESIGN_LOCKED` with `design_revision` incremented by one — meetings and signoffs pinned to the old revision no longer satisfy readiness — while `current_assessment_id` is retained. `SAFETY_DEFICIENCY` likewise returns it to `DESIGN_LOCKED` with `design_revision` incremented, but additionally clears `current_assessment_id` and moves the previously pinned `APPROVED` assessment to `SUPERSEDED`, so a fresh assessment must be approved and the design re-locked before the sequence can be marked ready again. Each of these sequence moves increments the sequence's `version` by one.

Finally, when every sequence of the production stands in `REVIEWED` or `CANCELLED`, the `ProductionExecutive` wraps the production — `ACTIVE → WRAPPED`, terminal. A wrap attempt with any sequence outside those two states is rejected with `ERR_SEQUENCES_NOT_TERMINAL`, and a wrap from any posture other than `ACTIVE` is rejected with `ERR_PRODUCTION_NOT_ACTIVE`. Wrapping increments the production's `version` by one.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, decisions, and versioned amendments — return `200 OK`. Rows marked "All roles" accept any of the six authenticated roles. Request payloads, preconditions, and side effects are specified in §2 and §3 rather than repeated here; this table fixes only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the server logical clock (strictly forward only) | ProductionExecutive |
| POST | `/api/productions` | Create a production | ProductionExecutive |
| GET | `/api/productions` | List productions (paginated) | All roles |
| GET | `/api/productions/{id}` | Get a production | All roles |
| GET | `/api/productions/{id}/summary` | Computed roll-up: committed pay, open negotiation exposure, endorsement premium, estimated total cost | All roles |
| PATCH | `/api/productions/{id}/budget` | Amend the total budget (OCC-guarded) | ProductionExecutive |
| POST | `/api/productions/{id}/file-insurance` | File the insurance notification; computes the endorsement premium | ProductionExecutive |
| POST | `/api/productions/{id}/acknowledge-insurance` | Record the carrier's acknowledgement | ProductionExecutive |
| POST | `/api/productions/{id}/activate` | Activate the production (insurance must be filed or acknowledged) | ProductionExecutive |
| POST | `/api/productions/{id}/stop` | Manual production stoppage with the full safety cascade | SafetyOfficer, ProductionExecutive |
| POST | `/api/productions/{id}/lift-stoppage` | Lift a stoppage (open-incident and cooldown gates) | ProductionExecutive |
| POST | `/api/productions/{id}/wrap` | Wrap the production (all sequences must be terminal) | ProductionExecutive |
| POST | `/api/stunt-sequences` | Create a stunt sequence in `DRAFT` | StuntCoordinator |
| GET | `/api/stunt-sequences` | List sequences; filterable by `production_id`, `status`, `hazard_class`, `required_equipment_ids` membership | All roles |
| GET | `/api/stunt-sequences/{id}` | Get a sequence | All roles |
| POST | `/api/stunt-sequences/{id}/lock-design` | Lock the design: pin the latest approved assessment, compute board score, quota, medic requirement | StuntCoordinator |
| POST | `/api/stunt-sequences/{id}/mark-ready` | Run the full readiness gate; `DESIGN_LOCKED` to `READY` | StuntCoordinator |
| POST | `/api/stunt-sequences/{id}/reverify-readiness` | Re-run the readiness gates from `SAFETY_HOLD` to `READY` | StuntCoordinator |
| POST | `/api/stunt-sequences/{id}/cancel` | Cancel a non-terminal sequence, cascading to rehearsals, meetings, and pay adjustments | StuntCoordinator, ProductionExecutive |
| POST | `/api/risk-assessments` | Create a risk assessment in `DRAFT` for a sequence (OCC-guarded) | StuntCoordinator |
| GET | `/api/risk-assessments` | List risk assessments; filterable by `production_id`, `sequence_id`, `status`, `supersedes_assessment_id` | All roles |
| GET | `/api/risk-assessments/{id}` | Get a risk assessment | All roles |
| POST | `/api/risk-assessments/{id}/submit` | Submit for review (screening band must match the declared risk category) | StuntCoordinator |
| POST | `/api/risk-assessments/{id}/approve` | Approve; supersedes the prior approved assessment and may invalidate readiness | SafetyOfficer |
| POST | `/api/risk-assessments/{id}/reject` | Reject with a reason | SafetyOfficer |
| POST | `/api/risk-assessments/{id}/revise` | Revise a rejected assessment back to `DRAFT` with new ratings | StuntCoordinator |
| POST | `/api/performers` | Register a stunt performer (`REGISTERED`) | StuntCoordinator |
| GET | `/api/performers` | List performers; filterable by `production_id`, `status` | All roles |
| GET | `/api/performers/{id}` | Get a performer | All roles |
| POST | `/api/performers/{id}/suspend` | Suspend a `QUALIFIED` performer | SafetyOfficer |
| POST | `/api/performers/{id}/reinstate` | Reinstate a `SUSPENDED` performer (requires a valid certification) | SafetyOfficer |
| POST | `/api/certifications` | Add a certification to a performer (immutable record) | StuntCoordinator |
| GET | `/api/certifications` | List certifications; filterable by `performer_id`, `discipline` | All roles |
| GET | `/api/certifications/{id}` | Get a certification | All roles |
| POST | `/api/certifications/{id}/revoke` | Revoke a certification; the performer may lose `QUALIFIED` | SafetyOfficer |
| POST | `/api/rehearsals` | Schedule a rehearsal (performer overlap, certification discipline, and future-start checks) | StuntCoordinator |
| GET | `/api/rehearsals` | List rehearsals; filterable by `production_id`, `sequence_id`, `performer_id`, `status` | All roles |
| GET | `/api/rehearsals/{id}` | Get a rehearsal | All roles |
| POST | `/api/rehearsals/{id}/complete` | Mark a rehearsal completed (not before its start; performer must be qualified) | StuntCoordinator |
| POST | `/api/rehearsals/{id}/mark-missed` | Mark a rehearsal missed (only after its window has ended) | StuntCoordinator |
| POST | `/api/rehearsals/{id}/cancel` | Cancel a scheduled rehearsal | StuntCoordinator |
| POST | `/api/rehearsals/{id}/void-completion` | Void a completed rehearsal (compensating counter decrement) | SafetyOfficer |
| POST | `/api/safety-meetings` | Schedule a safety meeting; fans out pending signoffs for the required department set; pins the design revision | StuntCoordinator |
| GET | `/api/safety-meetings` | List safety meetings; filterable by `production_id`, `sequence_id`, `status` | All roles |
| GET | `/api/safety-meetings/{id}` | Get a safety meeting | All roles |
| POST | `/api/safety-meetings/{id}/start` | Start the meeting (the chair is recorded) | SafetyOfficer |
| POST | `/api/safety-meetings/{id}/complete` | Complete the meeting (no signoff may remain pending) | SafetyOfficer |
| POST | `/api/safety-meetings/{id}/adjourn` | Adjourn a scheduled or in-session meeting | SafetyOfficer |
| GET | `/api/department-signoffs` | List signoffs; filterable by `meeting_id`, `department`, `status`; sorted by creation then department | All roles |
| GET | `/api/department-signoffs/{id}` | Get a signoff | All roles |
| POST | `/api/department-signoffs/{id}/sign` | Sign a pending signoff during an in-session meeting; non-empty conditions yield `SIGNED_WITH_CONDITIONS` | DepartmentHead |
| POST | `/api/department-signoffs/{id}/refuse` | Refuse a pending signoff during an in-session meeting | DepartmentHead |
| POST | `/api/equipment` | Register an equipment item (`IN_SERVICE`; inspection not current until the first pass) | StuntCoordinator |
| GET | `/api/equipment` | List equipment; filterable by `production_id`, `status`, `equipment_type` | All roles |
| GET | `/api/equipment/{id}` | Get an equipment item (inspection currency recomputed against the logical clock) | All roles |
| POST | `/api/equipment/{id}/retire` | Retire equipment (terminal); ready sequences requiring it drop to `SAFETY_HOLD` | StuntCoordinator |
| POST | `/api/inspections` | Record an equipment inspection; failed quarantines, passed un-quarantines | EquipmentInspector |
| GET | `/api/inspections` | List inspections; filterable by `equipment_id`, `outcome` | All roles |
| GET | `/api/inspections/{id}` | Get an inspection | All roles |
| POST | `/api/permits` | Apply for a special-equipment permit | ProductionExecutive |
| GET | `/api/permits` | List permits; filterable by `production_id`, `permit_type`, `status` | All roles |
| GET | `/api/permits/{id}` | Get a permit | All roles |
| POST | `/api/permits/{id}/grant` | Grant an applied permit | ProductionExecutive |
| POST | `/api/permits/{id}/deny` | Deny an applied permit | ProductionExecutive |
| POST | `/api/permits/{id}/revoke` | Revoke a granted permit; ready sequences requiring it drop to `SAFETY_HOLD` | SafetyOfficer |
| POST | `/api/pay-adjustments` | Open a hazard-bump negotiation (bounds-checked; one open negotiation per sequence-and-performer pair) | Performer, StuntCoordinator |
| GET | `/api/pay-adjustments` | List pay adjustments; filterable by `production_id`, `sequence_id`, `performer_id`, `status` | All roles |
| GET | `/api/pay-adjustments/{id}` | Get a pay adjustment | All roles |
| POST | `/api/pay-adjustments/{id}/counter` | Counter-offer by the side that did not make the last offer (six-round cap) | Performer, StuntCoordinator |
| POST | `/api/pay-adjustments/{id}/agree` | Accept the standing offer (budget authority check; commits pay) | Performer, StuntCoordinator |
| POST | `/api/pay-adjustments/{id}/withdraw` | Withdraw an open negotiation (proposer side only) | Performer, StuntCoordinator |
| POST | `/api/incidents` | Report an incident; serious or critical severity triggers the production-stoppage cascade | SafetyOfficer, StuntCoordinator, DepartmentHead, ProductionExecutive |
| GET | `/api/incidents` | List incidents; filterable by `production_id`, `sequence_id`, `severity`, `status` | All roles |
| GET | `/api/incidents/{id}` | Get an incident | All roles |
| POST | `/api/incidents/{id}/open-investigation` | Open an investigation on a reported incident | SafetyOfficer |
| POST | `/api/incidents/{id}/close` | Close an investigated incident (requires a corrective action) | SafetyOfficer |
| POST | `/api/stunt-executions` | Attempt a take (OCC-guarded; sequence must be ready; permit window and equipment currency re-checked) | StuntCoordinator |
| GET | `/api/stunt-executions` | List executions; filterable by `production_id`, `sequence_id`, `status` | All roles |
| GET | `/api/stunt-executions/{id}` | Get an execution | All roles |
| POST | `/api/stunt-executions/{id}/complete` | Complete a take (first completion executes the sequence; agreed adjustments accrue take bonuses) | StuntCoordinator |
| POST | `/api/stunt-executions/{id}/abort` | Abort a take; safety-related aborts auto-create an incident | StuntCoordinator |
| POST | `/api/post-stunt-reviews` | Open a post-stunt review (sequence must be executed; at most one open review per sequence) | SafetyOfficer |
| GET | `/api/post-stunt-reviews` | List reviews; filterable by `production_id`, `sequence_id`, `status` | All roles |
| GET | `/api/post-stunt-reviews/{id}` | Get a review | All roles |
| POST | `/api/post-stunt-reviews/{id}/close` | Close the review with an outcome (drives the sequence's terminal or reshoot transition) | SafetyOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflow it guards; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_PRODUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_SEQUENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMER_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REHEARSAL_NOT_FOUND` | 404 Not Found |
| `ERR_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNOFF_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXECUTION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRODUCTION_STOPPED` | 409 Conflict |
| `ERR_PRODUCTION_NOT_STOPPED` | 409 Conflict |
| `ERR_SERIOUS_INCIDENTS_OPEN` | 409 Conflict |
| `ERR_INSURANCE_NOT_FILED` | 409 Conflict |
| `ERR_INSURANCE_INVALID_STATE` | 409 Conflict |
| `ERR_SEQUENCE_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_PERFORMER_NOT_QUALIFIED` | 409 Conflict |
| `ERR_NO_VALID_CERTIFICATION` | 409 Conflict |
| `ERR_REHEARSAL_INVALID_STATE` | 409 Conflict |
| `ERR_MEETING_INVALID_STATE` | 409 Conflict |
| `ERR_SIGNOFF_ALREADY_DECIDED` | 409 Conflict |
| `ERR_SIGNOFFS_PENDING` | 409 Conflict |
| `ERR_PERMIT_INVALID_STATE` | 409 Conflict |
| `ERR_ADJUSTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_YOUR_TURN` | 409 Conflict |
| `ERR_NEGOTIATION_EXHAUSTED` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_EXECUTION_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_EQUIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_REHEARSAL_CONFLICT` | 409 Conflict |
| `ERR_FACILITY_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_TAKE_NUMBER` | 409 Conflict |
| `ERR_REVIEW_ALREADY_OPEN` | 409 Conflict |
| `ERR_NEGOTIATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_STOPPAGE_COOLDOWN` | 409 Conflict |
| `ERR_SEQUENCES_NOT_TERMINAL` | 409 Conflict |
| `ERR_CERTIFICATION_MISSING_OR_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CATEGORY_SCORE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RISK_SCORE_ABOVE_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_REHEARSAL_QUOTA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_MEETING_REQUIREMENT_UNSATISFIED` | 422 Unprocessable Entity |
| `ERR_MEDIC_STANDBY_NOT_CONFIRMED` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_NOT_READY` | 422 Unprocessable Entity |
| `ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSURANCE_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_CROSS_PRODUCTION_REFERENCE` | 422 Unprocessable Entity |
| `ERR_REHEARSAL_IN_PAST` | 422 Unprocessable Entity |
| `ERR_REHEARSAL_TIME_GATE` | 422 Unprocessable Entity |
| `ERR_CLOCK_NOT_FORWARD` | 422 Unprocessable Entity |
| `ERR_BUMP_OUT_OF_RANGE` | 422 Unprocessable Entity |

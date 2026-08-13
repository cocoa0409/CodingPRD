# Regulatory Change Management API — Product Requirements Document

## 1. Introduction

A corporate compliance office lives or dies by its horizon. New rules, amendments, and supervisory guidance arrive continuously through federal registers, state bulletins, and international journals, and every item must be triaged for applicability, traced into the obligation register, assessed for business impact, remediated through the control estate, and evidenced to examiners. When that chain is managed in spreadsheets and inboxes, mandated deadlines slip silently, coverage gaps go unnoticed, and the board learns of its exposure only after the examiners do.

This document specifies the Regulatory Change Management API, the system of record for that entire chain. It governs regulatory feed ingestion and applicability triage, maintenance of the obligation register with tamper-evident published versions, assignment of impact assessments to business owners, gap analysis against current controls, implementation planning under mandated deadlines, policy and procedure updates with coordinated training rollouts, assembly of evidence packages for examiners, escalation of deadline breaches and zero-coverage obligations, and committee-level reporting. All resources are served under the `/compliance` prefix. Every mutation is recorded in a hash-chained audit trail, and all temporal behavior is driven by a controllable logical clock so that deadline postures, review staleness, and training windows are deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles: `ComplianceOfficer`, `ComplianceManager`, `BusinessOwner`, `BoardSecretary`, and `PlatformAdmin`. A request whose headers are missing, or whose `X-User-Role` value is not one of these five declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Each endpoint admits a declared set of roles; a caller whose role is not in that set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The five roles divide the compliance workload as follows. A `ComplianceOfficer` is the compliance-office analyst responsible for horizon intake, triage, the obligation register, controls, mappings, gap analysis, and policy drafting. A `ComplianceManager` handles assessment acceptance, plan and policy approval, evidence sealing, examiner submission, and escalation handling. A `BusinessOwner` executes assigned impact assessments and implementation plans and maintains evidence and training attestations. A `BoardSecretary` runs the committee reporting lifecycle. A `PlatformAdmin` operates the logical clock and verifies the audit chain. All five roles may use every read (list and detail) endpoint.

Identity semantics differ by role. When `X-User-Role` is `BusinessOwner`, `X-User-ID` is the `id` of the acting BusinessOwner record; ownership checks on any resource that references a BusinessOwner compare the resource's `business_owner_id` field to `X-User-ID`, and a mismatch on an owner-scoped action is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `ComplianceOfficer`, `ComplianceManager`, `BoardSecretary`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` on a regulatory change, `drafted_by_user_id` on a policy update, or `approved_by_user_id` on an implementation plan — but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1, a `limit` above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with resources sharing a `created_at` retaining their insertion order. The `meta` object of list responses carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Recomputation

All temporal reasoning in the system — deadlines, review staleness, training windows — runs on a server-held logical clock, never on wall-clock time. At server startup, before any clock call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `PlatformAdmin` advances the clock through an admin-only test-driving capability (`POST /compliance/_clock/set_current_utc`) whose request carries a `to_iso8601` timestamp; the response echoes the new clock value as `current_utc`. The setter performs no ordering validation — any parseable ISO 8601 timestamp becomes the clock verbatim, whether ahead of or behind its previous value.

Advancing the clock is a system-wide recomputation event. Every implementation plan still in `APPROVED` or `IN_EXECUTION` has its `deadline_posture` recomputed, and any plan thereby crossing into `OVERDUE` spawns a deadline-breach escalation, which in turn recomputes the owning business owner's open-escalation counter and suspension flag. A control's `effectiveness_factor` is derived on read against the current clock, so control reads reflect the new time immediately; the stored `covered_points` and `residual_gap_points` on gap analyses do not move on a clock advance — they are recomputed only by the triggers enumerated in §3.5. Each in-progress training rollout re-evaluates its `past_due` flag. The clock advance itself is recorded in the audit trail like any other mutation, against `entity_type` `LogicalClock` with `entity_id` `logical_clock`.

### 2.5. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID rendered as thirty-two lowercase hexadecimal characters without hyphens, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Timestamps taken from the logical clock render without a fractional part when they fall on a whole second (for example, `2026-08-01T00:00:00Z`) and with exactly three fractional digits otherwise.

Cascade-driven changes are mutations like any other: a triage verdict, a retriage pull-back, the assignment of an assessor, or the stamping of a confirmed `risk_tier` each advance the regulatory change's `version`; a recorded review or a policy approval, publication, or retraction each advance the control's `version`; a register publish advances the register's `version`. Where a single call mutates the same resource in several internal steps, `version` advances once per step rather than once per call: a gap analysis is born at `version` 2 (creation plus its initial score computation), confirming a gap advances it by two again (the final recompute and the confirmation stamping), and a plan approval or deadline extension that changes `deadline_posture` advances the plan's `version` by two.

Two resources are append-only snapshots and deviate from this contract. An ObligationRegisterVersion and an AuditEvent each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Precision, Rounding, and Hash Digests

Scores and percentages follow fixed precision rules so that independent implementations agree exactly. Residual gap arithmetic (`covered_points`, `residual_gap_points`) is carried at 2 decimal places with round-half-up. The confirmed impact rating raw value is kept at 1 decimal place, since its inputs are integers and the scope multiplier carries a single decimal. Training completion percentages, the SLA compliance percentage, and the compliance index are reported at 1 decimal place with round-half-up; for the compliance index, component shares are evaluated as exact rational numbers before any tier lookup, never as pre-rounded decimals. All datetimes are ISO 8601 UTC. Register checksums and audit-event hashes are SHA-256 hex strings, computed over the pipe-delimited concatenations described in §3.2 and §2.9 respectively.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each pinning the version of a parent entity the caller has previously read:

- Creating an impact assessment requires the request to carry `expected_regulatory_change_version`, the caller's last-observed `version` of the target regulatory change. If the change's current `version` has advanced beyond that value — for example because another officer triaged it again or assigned a different owner after the caller last read it — the create is rejected with `ERR_STALE_CHANGE_VERSION` (HTTP 412).
- Publishing a new obligation register version requires `expected_register_version` equal to the register's current `version`; a stale value is rejected with `ERR_STALE_REGISTER_VERSION` (HTTP 412).
- Approving a policy update requires `expected_control_version` equal to the target control's current `version`; a stale value is rejected with `ERR_STALE_CONTROL_VERSION` (HTTP 412).

These guards exist because the product deliberately permits sequential look-alike operations: a fresh assessment may supersede a prior non-terminal one without changing the change's status, a second register publish is legitimate whenever obligations have moved, and a second policy update for the same active control snapshots the next policy version. In each case a repeated call observes no blocking state field, so only the version comparison distinguishes a caller acting on an out-of-date read. Endpoints not listed above do not accept a version field at all. Within the §2.10 precedence, each version comparison fires at a fixed point: on assessment creation, immediately after the referenced change and owner have been resolved — ahead of the suspension, deadline, and applicability checks; on register publish, immediately after the request body is validated — before the empty-estate check; and on policy approval, only after the update's state precondition and the segregation-of-duties check have passed.

### 2.8. Segregation of Duties

Three workflow hand-offs are segregated at the individual-user level. The officer who triages or retriages a regulatory change must not be the officer who ingested it (the change's `created_by_user_id`). The officer who approves an obligation–control mapping must not be the officer who proposed it (`created_by_user_id` on the mapping versus the actor recorded as `approved_by_user_id`). The manager who approves a policy update must not be the officer who drafted it (`drafted_by_user_id` versus the actor recorded as `approved_by_user_id`). Any violation of these three separations is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

### 2.9. The Hash-Chained Audit Trail

Every mutating call — creations, state transitions, calls with cascade effects, clock advances — appends exactly one AuditEvent, for the primary mutated entity; entities touched only as cascade side effects of the same call (a superseded change, mapping retirements carried along by an obligation retirement, spawned or auto-resolved escalations, gap analyses created by an acceptance, a plan verified or a change closed by a seal) append no events of their own. An audit event carries a `sequence_number` strictly increasing from 1, which defines replay order; the `actor_user_id` and `actor_role` copied from the request headers; an `action` label combining the endpoint and transition (for example, `POST /compliance/impact-assessments/{id}/accept`); the primary mutated `entity_type` and `entity_id`; the logical clock value `occurred_at`; and a hash link: `prev_event_hash` holds the previous event's `event_hash`, with the literal string `GENESIS` standing in for the very first event. Each event's `event_hash` is the SHA-256 hex digest of the pipe-delimited concatenation of, in order: the previous event hash, the sequence number, the actor user id, the action label, the entity type, the entity id, and the occurred-at timestamp.

A `PlatformAdmin` can verify the whole chain through the audit-chain verification capability, which replays all events in ascending `sequence_number` order and recomputes each hash. The response reports `chain_valid` — false the moment any recomputed hash diverges from its stored value — together with the number of `events_checked`.

### 2.10. Validation Order and Error Precedence

When a request would fail several checks at once, the checks are evaluated in a fixed priority order and the earliest failing check determines the response, so an earlier failure masks later ones:

- Priority 1 — authentication context: missing headers or an unrecognized role yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
- Priority 2 — authorization: a caller whose role is not admitted by the endpoint yields `ERR_UNAUTHORIZED_ROLE` (403); for BusinessOwner-scoped actions, an `X-User-ID` that does not match the resource's `business_owner_id` yields `ERR_NOT_RESOURCE_OWNER` (403). Because ownership can only be evaluated once the resource carrying the owner reference has been located, the ownership check on owner-scoped actions fires immediately after the target resource resolves (for plan and package creation, once the referenced gap analysis or plan resolves) — an unresolvable identifier therefore yields `ERR_NOT_FOUND`, never `ERR_NOT_RESOURCE_OWNER`.
- Priority 2.5 — request-body shape: a missing required field, a type mismatch, an invalid enum member, or an unparseable datetime yields `ERR_INVALID_REQUEST` (400).
- Priority 3 — existence: path identifiers are validated left-to-right, then foreign keys carried in the body (`regulatory_change_id`, `business_owner_id`, `obligation_id`, `control_id`, `gap_analysis_id`, `implementation_plan_id`, `supersedes_change_id`); any miss yields `ERR_NOT_FOUND` (404).
- Priority 4 — state-machine preconditions of the attempted transition, yielding the 409 state family: `ERR_INVALID_STATE`, `ERR_PLAN_NOT_SUBMITTED`, `ERR_PLAN_NOT_COMPLETED`, `ERR_PACKAGE_SEALED`, `ERR_CHANGE_NOT_SUPERSEDABLE`.
- Priority 5 — segregation of duties and owner suspension: `ERR_SEGREGATION_OF_DUTIES_VIOLATION` or `ERR_OWNER_SUSPENDED` (both 403).
- Priority 6 — clock-relative temporal rules, yielding the 422 temporal family: `ERR_DEADLINE_IN_PAST`, `ERR_DEADLINE_EXCEEDS_MANDATE`, `ERR_TRAINING_WINDOW_TOO_SHORT`, `ERR_RETRACT_WINDOW_CLOSED`, `ERR_TRAINING_WINDOW_CLOSED`, `ERR_INVALID_EXTENSION`, `ERR_INVALID_REPORT_PERIOD`.
- Priority 7 — uniqueness and structural caps: duplicate codes, duplicate mappings, existing plans or packages, an empty register, overlapping report windows, conflicting rollout windows, or a change attempting to supersede itself yield the 409 constraint family, while exhausted extensions, unmet completion thresholds, and an empty evidence package yield `ERR_MAX_EXTENSIONS_REACHED`, `ERR_COMPLETION_THRESHOLD_NOT_MET` or `ERR_EXCEPTION_THRESHOLD_NOT_MET`, and `ERR_NO_ARTIFACTS` respectively (all 422 per §5).
- Priority 8 — cross-entity referential state: the referenced change is not `TRIAGED_APPLICABLE` (`ERR_CHANGE_NOT_TRIAGED_APPLICABLE`), an obligation is not `ACTIVE` (`ERR_OBLIGATION_NOT_ACTIVE`), a control is not `ACTIVE` (`ERR_CONTROL_NOT_ACTIVE`), or a gap analysis is not `CONFIRMED` (`ERR_GAP_NOT_CONFIRMED`) — all 409.

### 2.11. Existence Checks and Nested Resource Retrieval

For endpoints whose path contains multiple identifiers — the artifact removal path, for instance, addresses an evidence package and then one of its artifacts — identifiers are validated strictly left-to-right, and the request is rejected with `ERR_NOT_FOUND` (404) at the first identifier that does not resolve to an existing resource. A removal naming an unknown `artifactId` under a real package therefore fails on the artifact identifier only after the package itself has been located. Foreign-key references carried in a request body are checked only after all path identifiers have been resolved.

## 3. Business Logic & Workflows

This section walks the compliance lifecycle end to end — from horizon intake through triage, register maintenance, assessment, gap analysis, remediation planning, policy and training, evidence, and board reporting. Structural contracts live in §2; what follows is the operational narrative in which every rule, threshold, and cascade takes effect.

### 3.1. Horizon Intake and Triage of Regulatory Changes

A `ComplianceOfficer` ingests a regulatory change by supplying its `citation` (for example, "12 CFR Part 1005"), a `title`, a free-text `summary`, the `feed_source` — one of `FED_REGISTER`, `STATE_BULLETIN`, `INT_JOURNAL`, or `MANUAL_ENTRY` — the `jurisdiction` code (such as "US-FED", "US-CA", or "EU"), the issuing `regulator`, the `published_at` timestamp, the `effective_date` on which the regulation takes effect, and an analyst `severity_hint` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` that feeds the provisional risk rating. An optional `comment_deadline` records the close of the comment period. The new record enters as `PENDING_TRIAGE` with `applicability` set to `UNDETERMINED` and `triage_round` at zero, and `created_by_user_id` is stamped from the caller. The `triaged_by_user_id` and `business_owner_id` fields remain empty until a first triage and a first assessment respectively, `superseded_by_id` stays empty unless a newer revision supersedes the record, and `risk_tier` stays unset until an assessment is first accepted.

Ingestion can also revise history. When the payload carries a `supersedes_change_id`, the named change must exist (`ERR_NOT_FOUND`) and must still stand in `PENDING_TRIAGE` or `TRIAGED_NOT_APPLICABLE`; targeting a change in any other status is rejected on the creating call with `ERR_CHANGE_NOT_SUPERSEDABLE` (409), and a change may never name itself as the record it supersedes. On success the older change moves to `SUPERSEDED` — a terminal state — with its `superseded_by_id` pointing at the new record. Supersession is the only way a change leaves the triage stage without a verdict.

Triage itself is a verdict call carrying a `verdict` of `APPLICABLE` or `NOT_APPLICABLE` together with a free-text `rationale`. The change must currently be `PENDING_TRIAGE` (otherwise `ERR_INVALID_STATE`), and segregation of duties forbids the ingesting officer from triaging their own record (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). A verdict of `APPLICABLE` moves the change to `TRIAGED_APPLICABLE` and sets `applicability` to `APPLICABLE`; a verdict of `NOT_APPLICABLE` moves it to `TRIAGED_NOT_APPLICABLE` and sets `applicability` to `NOT_APPLICABLE`. Either way, the rationale is stored as `triage_rationale`, `triage_round` increments by one on every triage decision, `triaged_by_user_id` records the actor, the change's `version` advances by one, and the system computes a `provisional_risk_tier`. The provisional rating maps the analyst's `severity_hint` to a severity score — `LOW` counts 1, `MEDIUM` counts 2, `HIGH` counts 4, `CRITICAL` counts 5 — multiplies that score by an assumed likelihood of 3 and a scope multiplier fixed at 1.0, and tiers the resulting raw product as follows: below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at least 12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`.

A change ruled not applicable is not dead. A `ComplianceOfficer` — again, never the original ingester — may pull a `TRIAGED_NOT_APPLICABLE` change back into `PENDING_TRIAGE` by supplying a fresh `rationale`. This retriage resets `applicability` to `UNDETERMINED`, overwrites `triage_rationale` with the retriage rationale, leaves `triaged_by_user_id` unchanged, and advances the change's `version` by one. The cycle can repeat any number of times; a retriage pull-back is not a verdict, so the triage round counter is not advanced by it. Analysts can browse the backlog filtered by `status`, `jurisdiction`, `severity_hint`, or `business_owner_id`, and can trace revision chains through the `supersedes_change_id` and `superseded_by_id` filters.

### 3.2. The Obligation Register and Published Register Versions

Once a change stands `TRIAGED_APPLICABLE`, a `ComplianceOfficer` decomposes it into obligations. Creating an obligation takes a register-unique `obligation_code` (for example, "OBL-2026-001"), a `title`, the introducing `regulatory_change_id`, and a `criticality` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` — a value that drives both the requirement-point weighting used in gap analysis and the deadline mandate used in implementation planning. The referenced change must be `TRIAGED_APPLICABLE`, or creation fails with `ERR_CHANGE_NOT_TRIAGED_APPLICABLE`; the `obligation_code` is unique across all obligations ever created, and reuse is rejected with `ERR_DUPLICATE_OBLIGATION_CODE`. New obligations enter as `DRAFT`. The obligation list can be filtered by `regulatory_change_id`, `status`, or `criticality`.

Activation (`DRAFT` → `ACTIVE`) makes an obligation available for mapping and planning. Retirement (`ACTIVE` → `RETIRED`) is refused with `ERR_OBLIGATION_IN_USE` while the obligation still has a gap analysis in `OPEN` or `IN_REVIEW`, or any implementation plan that has not reached `VERIFIED` — plans in `DRAFT`, `SUBMITTED`, `REJECTED`, `APPROVED`, `IN_EXECUTION`, or `COMPLETED` all block retirement. A successful retirement also retires every currently `APPROVED` mapping of the obligation. Reinstatement (`RETIRED` → `ACTIVE`) takes a `rationale` and is always permitted from `RETIRED`, but it does not resurrect the mappings that retirement took down — coverage must be rebuilt explicitly with fresh mappings.

The ObligationRegister is a singleton: exactly one register row exists, auto-created when the server boots with a `current_version_number` of 0, a `version` of 1, and a `singleton_note` fixed at `SINGLETON`. Publishing the register is how the office cuts an official snapshot of the obligation estate. The publish call must carry `expected_register_version` matching the register's current `version` (see §2.7), and at least one obligation must be `ACTIVE` at publish time — publishing against an empty estate is rejected with `ERR_REGISTER_EMPTY`. A successful publish creates an ObligationRegisterVersion whose `version_number` is the register's current number plus one, so versions run sequentially from 1; whose `published_at` is the logical clock at publish; whose `obligation_codes` hold the `obligation_code` values of every `ACTIVE` obligation, sorted lexicographically in ascending byte-wise order — the sort key is always the business code, never the entity id; and whose `obligation_count` is the length of that snapshot. Its `register_checksum` is the SHA-256 hex digest of a string built from the literal letter v, the version number, a vertical bar, and the sorted codes joined by commas, in that order. Publishing then advances the register's `current_version_number` by one and increments the register's `version` by one. Prior snapshots remain browsable through the register-versions collection with the usual pagination.

### 3.3. Controls and Obligation–Control Coverage Mappings

A control is created with a globally unique `control_code` (for example, "CTL-AML-014"), a `title`, the `owner_department` that operates it, and a `review_frequency_days` cadence that must be greater than zero; an optional `last_reviewed_at` seeds the review history. Duplicate codes are rejected with `ERR_DUPLICATE_CONTROL_CODE`. Controls are born `ACTIVE` with `policy_version` 1, and the system derives two freshness readings for each: `next_review_due`, which is `last_reviewed_at` plus `review_frequency_days` and stays unset while the control has never been reviewed; and `effectiveness_factor`, which measures review staleness against the current logical clock — 1.0 when the last review was at most 90 days ago, 0.8 when it was between 91 and 180 days ago, and 0.5 when it was more than 180 days ago or never happened, the latter being the default before any review. Recording a review stamps `last_reviewed_at` to the current clock, recomputes `next_review_due` and `effectiveness_factor`, and increments the control's `version` by one. Because coverage moves when effectiveness moves, the same call also recomputes `covered_points` and `residual_gap_points` on every gap analysis in `OPEN` or `IN_REVIEW` whose obligation has an `APPROVED` mapping to the reviewed control. A control can be retired (`ACTIVE` → `RETIRED`, terminal) only while no mapping referencing it stands `PROPOSED` or `APPROVED`; otherwise the retirement is rejected with `ERR_CONTROL_IN_USE`. Controls can be browsed filtered by `status` or `owner_department`.

Coverage between the register and the control estate is expressed through obligation–control mappings. Proposing one takes the `obligation_id` and `control_id` plus a `coverage_weight` from 1 to 10 contributed while the mapping is approved. Both referenced records must be `ACTIVE` — failures surface as `ERR_OBLIGATION_NOT_ACTIVE` and `ERR_CONTROL_NOT_ACTIVE` respectively — and at most one non-terminal mapping may exist for a given obligation–control pair: a second mapping for the same pair while one stands `PROPOSED` or `APPROVED` is rejected with `ERR_DUPLICATE_MAPPING`. The proposal enters as `PROPOSED` with `created_by_user_id` stamped from the caller. Approval (`PROPOSED` → `APPROVED`) is segregated: the approving officer must differ from the proposer (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and the approver is recorded in `approved_by_user_id`. Rejection (`PROPOSED` → `REJECTED`) accepts an optional `reason`. An approved mapping can later be retired (`APPROVED` → `RETIRED`), which drops its coverage from that moment. Both approval and retirement immediately recompute `covered_points` and `residual_gap_points` on every gap analysis of the mapped obligation that is still in `OPEN` or `IN_REVIEW`. The mapping collection supports filters on `obligation_id`, `control_id`, and `status`.

### 3.4. Impact Assessments: Assignment, Scoring, and Acceptance

Business owners enter the system through registration by a `ComplianceOfficer`, which records their `name`, a free-form `department` label (such as "ENG" or "OPS"), and a contact `email`. Two workload counters are maintained on each owner and exposed on their detail read: `active_assessment_count`, the number of their assessments standing in `ASSIGNED`, `IN_PROGRESS`, `RETURNED`, or `SUBMITTED`; and `open_escalation_count`, the number of their escalations standing in `OPEN` or `ACKNOWLEDGED`. Both start at zero, and the derived `assignment_suspended` flag starts false.

With a change `TRIAGED_APPLICABLE`, a `ComplianceOfficer` assigns an impact assessment to a business owner by naming the `regulatory_change_id`, the assignee `business_owner_id`, and a `due_date` lying strictly after the current logical clock (`ERR_DEADLINE_IN_PAST`). The referenced change must indeed be `TRIAGED_APPLICABLE` (`ERR_CHANGE_NOT_TRIAGED_APPLICABLE`), and the request must carry `expected_regulatory_change_version` per §2.7 — a caller working from a stale view of the change fails with `ERR_STALE_CHANGE_VERSION` (412). Assignment is also gated on the assignee's standing: when an owner's `open_escalation_count` has reached three or more, their `assignment_suspended` flag is true and any new assignment to them is rejected with `ERR_OWNER_SUSPENDED` (403). Creation automatically supersedes any prior assessment of the same change that is still non-terminal — standing in `ASSIGNED`, `IN_PROGRESS`, `RETURNED`, or `SUBMITTED` — moving it to `SUPERSEDED` and pointing the new record's `supersedes_assessment_id` at it; the field stays empty when there was no predecessor. The change's `business_owner_id` is updated to the new assignee and the change's `version` advances by one. The new assessment enters as `ASSIGNED` with `return_count` at zero.

Work on the assessment belongs to the owner. Starting it (`ASSIGNED` → `IN_PROGRESS`) — or resuming it after a return (`RETURNED` → `IN_PROGRESS`) — requires the caller to be the assigned owner (`ERR_NOT_RESOURCE_OWNER`) and the assessment to stand in one of those two states (`ERR_INVALID_STATE` otherwise). Submitting is allowed only from `IN_PROGRESS` and carries the analytical payload: `likelihood_score` and `severity_score`, each an integer from 1 to 5; `affected_business_lines`, an integer of at least 1; and a free-text `findings_summary`. On submit, the confirmed impact rating is computed: the raw score is `likelihood_score` times `severity_score` times a scope multiplier that is 1.0 when exactly one business line is affected, 1.2 when two or three are affected, and 1.5 when four or more are affected, and it is kept at one decimal place. The `impact_tier` follows the same bands as the provisional rating — below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at least 12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`. Both `impact_rating_raw` and `impact_tier`, unset until this moment, are stored; `submitted_at` is stamped with the logical clock; and `sla_breached` becomes true exactly when the clock at submission is strictly after the `due_date`.

A `ComplianceManager` then dispositions the submission from `SUBMITTED`. Returning it (`SUBMITTED` → `RETURNED`) carries `comments` for the owner and increments `return_count`, feeding the revision loop that re-enters `IN_PROGRESS` through the start transition. Acceptance (`SUBMITTED` → `ACCEPTED`, a terminal state for the assessment) is the pivotal cascade. First, the change's `risk_tier` is set to the assessment's `impact_tier`, advancing the change's `version`. Second, for every `ACTIVE` obligation introduced by the change, a gap analysis is created in `OPEN` with its `requirement_points` snapshotted from the obligation's `criticality` as described in §3.5. Third, each newly created gap analysis immediately computes its `covered_points` and `residual_gap_points`, and any new gap whose residual equals its full requirement — zero effective coverage — on an obligation of `HIGH` or `CRITICAL` criticality spawns an escalation with `target_type` `OBLIGATION`, `trigger_rule` `ZERO_COVERAGE`, no business owner attached, and status `OPEN`. Assessments can be listed filtered by `regulatory_change_id`, `business_owner_id`, `status`, or `supersedes_assessment_id`.

### 3.5. Gap Analyses and the Residual Gap Score

A gap analysis binds one accepted assessment to one obligation: its `impact_assessment_id` records which acceptance spawned it, and its `obligation_id` records which obligation is under analysis. The `requirement_points` field freezes the obligation's criticality at creation — `LOW` weighs 4 points, `MEDIUM` 8, `HIGH` 16, and `CRITICAL` 32 — so a later change of heart about criticality does not rewrite history. Against that requirement the system maintains `covered_points`: the sum over the obligation's `APPROVED` mappings of each mapping's `coverage_weight` multiplied by its control's `effectiveness_factor` as evaluated at the current logical clock. Mappings in `PROPOSED`, `REJECTED`, or `RETIRED` contribute nothing. The `residual_gap_points` are the requirement minus the covered points, floored at zero so that a heavily covered obligation never shows a negative residual, and rounded half-up to two decimal places.

The residual score is live while the gap is being worked. It is computed at gap creation and recomputed whenever a mapping of the obligation is approved or retired and whenever a mapped control records a review — but only while the gap analysis stands in `OPEN` or `IN_REVIEW`; a clock advance by itself does not move a gap's stored scores (§2.4). A `ComplianceOfficer` moves a gap from `OPEN` to `IN_REVIEW` to signal active analysis, and confirming it (`IN_REVIEW` → `CONFIRMED`, the terminal state) recomputes coverage and residual one final time and then freezes both numbers permanently, stamping `confirmed_by_user_id` and `confirmed_at` from the actor and the clock. Only a `CONFIRMED` gap analysis can anchor an implementation plan. Gap analyses can be listed filtered by `impact_assessment_id`, `obligation_id`, or `status`.

### 3.6. Implementation Plans, Deadline Mandates, and Extensions

Remediating a confirmed gap begins when the responsible `BusinessOwner` drafts an implementation plan against it, supplying the `gap_analysis_id`, a `title`, and a `target_completion_date`. The gap must be `CONFIRMED` (`ERR_GAP_NOT_CONFIRMED`), at most one non-terminal plan may exist per gap analysis (`ERR_PLAN_ALREADY_EXISTS`), and the caller must be the business owner of the accepted assessment behind the gap (`ERR_NOT_RESOURCE_OWNER`). The plan denormalizes its `obligation_id`, its `regulatory_change_id`, and its `business_owner_id` from the gap and the assessment above it, and enters with `execution_status` `DRAFT` and `deadline_posture` `ON_TRACK`.

The target date is bounded on both sides. It must lie strictly after the current clock (`ERR_DEADLINE_IN_PAST`), and it must not exceed the mandated implementation deadline for the obligation's criticality (`ERR_DEADLINE_EXCEEDS_MANDATE`). The mandate counts from the gap analysis's `confirmed_at`, with the confirmation day itself treated as day zero and not counted, and the allowance is 180 days for a `LOW` obligation, 90 days for `MEDIUM`, 45 days for `HIGH`, and 15 days for `CRITICAL`. `CRITICAL` mandates count calendar days and are never adjusted for weekends. `LOW`, `MEDIUM`, and `HIGH` mandates count business days only — Monday through Friday — starting from the day after the confirmation day, and when the landing day falls on a Saturday or Sunday it rolls forward to the next Monday. Three worked anchors pin the convention: with a confirmation at 2026-08-01T00:00:00Z, a Saturday, a `CRITICAL` mandate of 15 calendar days lands on 2026-08-16T00:00:00Z, a `HIGH` mandate of 45 business days lands on 2026-10-02T00:00:00Z, and a `MEDIUM` mandate of 90 business days lands on 2026-12-04T00:00:00Z. Because the mandate counts from `confirmed_at`, the mandated deadline is defined only once the gap analysis stands `CONFIRMED`; the `ERR_DEADLINE_EXCEEDS_MANDATE` check does not apply to a gap analysis that is not `CONFIRMED`.

From draft, the plan runs an approval loop. Submitting (`DRAFT` → `SUBMITTED`, and `REJECTED` → `SUBMITTED` for the resubmission cycle) is the owner's action and stamps `submitted_by_user_id`. A `ComplianceManager` approves only a plan standing `SUBMITTED` — approving or rejecting in any other execution state is rejected with `ERR_PLAN_NOT_SUBMITTED` — and only while the underlying obligation is still `ACTIVE` (`ERR_OBLIGATION_NOT_ACTIVE`). Approval pins the register: `pinned_register_version_number`, unset until this moment, captures the register's `current_version_number`, `approved_by_user_id` records the manager, and the deadline posture is recomputed. Rejection carries a `reason` and hands the plan back to the owner for revision and resubmission. Once approved, the owner begins execution (`APPROVED` → `IN_EXECUTION`) and eventually marks completion (`IN_EXECUTION` → `COMPLETED`); late completion is allowed, and on completion the `deadline_posture` freezes at whatever value it last held, so the lateness remains visible on the record.

While a plan stands `APPROVED` or `IN_EXECUTION`, its `deadline_posture` rides the clock on a parallel axis to the execution status. Measuring the remaining window from the current logical clock to the `target_completion_date`: when the remaining window is strictly negative the posture is `OVERDUE` — a plan sitting exactly at its deadline is not overdue; when the window is from zero up to and including 14 days the posture is `AT_RISK`; when it is more than 14 days the posture is `ON_TRACK`. Plans in `DRAFT`, `SUBMITTED`, or `REJECTED` simply hold `ON_TRACK`, and plans in `COMPLETED` or `VERIFIED` keep their frozen value. Posture is recomputed when the clock advances, when the plan is approved, and when its deadline is extended. Crossing into `OVERDUE` — whether from `ON_TRACK` or from `AT_RISK` — spawns a deadline-breach escalation whenever the plan does not already have one standing in `OPEN` or `ACKNOWLEDGED`: `target_type` `IMPLEMENTATION_PLAN`, `trigger_rule` `DEADLINE_BREACH`, the plan's `business_owner_id` attached, `level` 1, status `OPEN`, and `opened_at` set to the clock. That creation recomputes the owner's `open_escalation_count`, and at three or more the owner's `assignment_suspended` flips to true.

When more time is genuinely needed, the owner requests an extension with a `new_target_completion_date` and a `rationale`. Extensions are available only while the plan stands `APPROVED` or `IN_EXECUTION` (`ERR_INVALID_STATE` otherwise); each plan allows at most two, so a request arriving when `extension_count` already stands at two is rejected with `ERR_MAX_EXTENSIONS_REACHED`; and the new target must lie strictly after the current target and no more than 90 days beyond it (`ERR_INVALID_EXTENSION`). A granted extension updates `target_completion_date`, increments `extension_count`, and recomputes the posture: an `OVERDUE` plan recovers to `AT_RISK` when the new remaining window falls within the 14-day band, or directly to `ON_TRACK` when it exceeds 14 days, and an `AT_RISK` plan returns to `ON_TRACK` on the same terms. Granting an extension also resolves every `OPEN` or `ACKNOWLEDGED` deadline-breach escalation standing on the plan, stamping `resolution_code` `EXTENSION_GRANTED`, and the owner's escalation counters are recomputed — lifting the suspension when the count drops back below three. Plans can be listed filtered by `gap_analysis_id`, `obligation_id`, `regulatory_change_id`, `business_owner_id`, `verification_evidence_id`, `execution_status`, or `deadline_posture`.

### 3.7. Policy Updates and Training Rollouts

Confirmed gaps are often remediated by changing policy. A `ComplianceOfficer` drafts a policy update against a control, supplying the `control_id`, a `title`, a `change_summary` describing what the policy or procedure change contains, and the `effective_date` on which the new policy takes effect — strictly after the current clock (`ERR_DEADLINE_IN_PAST`). The control must be `ACTIVE` (`ERR_CONTROL_NOT_ACTIVE`). An optional `implementation_plan_id` links the update to the plan it discharges; when given, that plan must stand in `APPROVED`, `IN_EXECUTION`, or `COMPLETED` (`ERR_INVALID_STATE` otherwise). The draft enters as `DRAFTING` with `drafted_by_user_id` stamped from the caller and `new_policy_version` unset.

Submitting moves the draft from `DRAFTING` to `PENDING_APPROVAL`, where a `ComplianceManager` dispositions it. Approval is segregated from drafting — the approver must not be the `drafted_by_user_id` officer (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) — and version-pinned per §2.7: the request must carry `expected_control_version` equal to the control's current `version`, failing with `ERR_STALE_CONTROL_VERSION` (412) when the control has moved since the approver last read it. A successful approval snapshots `new_policy_version` as the control's `policy_version` plus one, stamps `approved_by_user_id`, and increments the control's `version` by one. Rejection carries a `reason`, and a rejected draft returns to `DRAFTING` through revision — a cycle that may repeat as often as needed.

Publication is the point at which the control estate actually changes, moving the update from `APPROVED` to `PUBLISHED`. Publishing requires the update to stand `APPROVED`; it requires the `effective_date` to be at least seven days after the current clock — otherwise `ERR_TRAINING_WINDOW_TOO_SHORT`, because staff are guaranteed a minimum one-week training runway; and it requires the new rollout window to be clear of siblings: for the same control, no non-`CANCELLED` training rollout may have a window lying within seven days before or after the new window, which spans from the publish clock to the `effective_date` (`ERR_ROLLOUT_WINDOW_CONFLICT`). On publish, the control's `policy_version` becomes the snapshotted `new_policy_version` and the control's `version` increments again, `published_at` is stamped with the clock, and a training rollout is automatically created in `IN_PROGRESS` whose `policy_update_id` points back to the update, whose `control_id` is denormalized from it, and whose training window runs from `window_start` equal to the publish timestamp to `window_end` equal to the `effective_date`.

A published update can still be retracted, but only from `PUBLISHED` and only before it takes effect: once the logical clock reaches the `effective_date`, the retract window has closed (`ERR_RETRACT_WINDOW_CLOSED`). Retraction carries a `reason`, moves the update to its terminal `RETRACTED` state, and performs the compensating bookkeeping — the control's `policy_version` is restored to the snapshotted `new_policy_version` minus one, the control's `version` increments by one, and the update's in-flight training rollout is cancelled (`IN_PROGRESS` → `CANCELLED`).

The training rollout tracks attestations while `IN_PROGRESS`. The business line posts a `records` payload of attestation items, each carrying a `person_ref`, a `department`, and a `completed` flag; items are upserted keyed by `person_ref`, so re-posting the same person updates their record — refreshing its `updated_at` — and never duplicates it. Posting attestations to a rollout that no longer stands `IN_PROGRESS` is rejected with `ERR_INVALID_STATE`. Every upsert recomputes the roll-up: `assigned_count` is the number of distinct `person_ref` entries in `attestation_records`, `completed_count` is how many of those records are flagged complete, and `completion_pct` is a per-department rounded mean. For each department, the percentage complete is rounded half-up to one decimal place first; only then are those rounded department percentages averaged — unweighted, each department counting equally — with the mean itself rounded half-up to one decimal place; a rollout with no records reports 0.0. The pinned order matters: a rollout where one department completes 20 of 20 attestations and another completes 9 of 10 yields 95.0 — the mean of 100.0 and 90.0 — whereas pooling all persons before rounding would yield 96.7, a reading the system deliberately rejects. The rollout also tracks `past_due`, true when the logical clock has passed `window_end` while the rollout still stands `IN_PROGRESS`.

Closing a rollout has two doors. The owner completes it (`IN_PROGRESS` → `COMPLETED`) only when `completion_pct` has reached at least 95.0 (`ERR_COMPLETION_THRESHOLD_NOT_MET`) and the clock has not passed `window_end` (`ERR_TRAINING_WINDOW_CLOSED`). Alternatively, a `ComplianceManager` closes it with exceptions (`IN_PROGRESS` → `CLOSED_WITH_EXCEPTIONS`) once `completion_pct` is at least 80.0 (`ERR_EXCEPTION_THRESHOLD_NOT_MET`), recording an `exception_rationale`. Rollouts can be listed filtered by `policy_update_id`, `control_id`, or `status`.

### 3.8. Evidence Packages and Regulatory Change Closure

Examiners want proof, and the evidence package is its container. Once a plan stands `COMPLETED`, its owner opens a package for it by naming the `implementation_plan_id`; a plan that has not reached `COMPLETED` is rejected with `ERR_PLAN_NOT_COMPLETED`, at most one package may exist per plan (`ERR_PACKAGE_ALREADY_EXISTS`), and ownership is enforced through the plan (`ERR_NOT_RESOURCE_OWNER`). The package enters as `ASSEMBLING` with an empty `artifacts` list and an `artifact_count` of zero.

While the package is assembling, the owner attaches artifacts one at a time, each described by an `artifact_type` and a `uri`; the server mints an `artifact_id` for each item and stamps its `attached_at` with the logical clock, and a successful attachment answers 201. An artifact can be removed again by its `artifactId` while the package is still assembling — naming an unknown artifact identifier yields `ERR_NOT_FOUND`. Both attachment and removal are rejected with `ERR_PACKAGE_SEALED` once the package has left `ASSEMBLING`, and each such mutation refreshes `artifact_count`. Packages can be listed filtered by `implementation_plan_id` or `status`.

Sealing is a `ComplianceManager` action with two preconditions: the package must still stand `ASSEMBLING` (`ERR_PACKAGE_SEALED` otherwise), and it must hold at least one artifact (`ERR_NO_ARTIFACTS`). Sealing stamps `sealed_at` with the clock, renders the package immutable, and fires the two-link closure cascade. First, the plan behind the package moves from `COMPLETED` to `VERIFIED` with its `verification_evidence_id` pointing at the sealed package. Second, closure is re-evaluated for the plan's regulatory change: when every `ACTIVE` obligation introduced by that change has at least one implementation plan, and none of those obligations' plans remains in `DRAFT`, `SUBMITTED`, `REJECTED`, `APPROVED`, `IN_EXECUTION`, or `COMPLETED` — that is, every one of their plans has reached `VERIFIED` — the change itself moves from `TRIAGED_APPLICABLE` to its terminal `CLOSED` state. After sealing, the manager records delivery of the package to the examiner, moving it from `SEALED` to its terminal `SUBMITTED_TO_EXAMINER` state and storing the supplied `examiner_reference`.

### 3.9. Escalations, Owner Suspension, and Committee Reporting

Escalations are the system's pressure valve, and they are polymorphic: `target_type` is either `IMPLEMENTATION_PLAN` or `OBLIGATION`, and `target_id` addresses a plan or an obligation accordingly. Two trigger rules create them — `DEADLINE_BREACH` when a plan crosses into `OVERDUE` (§3.6), and `ZERO_COVERAGE` when an assessment acceptance exposes a fully uncovered `HIGH` or `CRITICAL` obligation (§3.4) — and only the deadline-breach kind carries a `business_owner_id`; zero-coverage escalations have none. Every escalation opens at `level` 1 in `OPEN` status with `opened_at` stamped from the clock, and `resolved_at` stays unset until resolution. A `ComplianceManager` acknowledges an open escalation (`OPEN` → `ACKNOWLEDGED`), and resolves one from either `OPEN` or `ACKNOWLEDGED` by supplying a `resolution_note`; resolution is terminal, moving the escalation to `RESOLVED`, and manual resolution stamps `resolution_code` `MANUAL_RESOLUTION` and `resolved_at` from the clock. Granted deadline extensions resolve deadline-breach escalations automatically with `resolution_code` `EXTENSION_GRANTED`, as §3.6 describes. Either flavor of resolution recomputes the affected owner's `open_escalation_count`, and `assignment_suspended` flips back to false the moment the count drops below three — restoring the owner's eligibility for new assessment assignments. Escalations can be listed filtered by `status`, `target_type`, `target_id`, `business_owner_id`, or `trigger_rule`.

Committee reporting belongs to the `BoardSecretary`. Creating a report names the `committee_name` — one of `BOARD_RISK_COMMITTEE`, `AUDIT_COMMITTEE`, or `EXECUTIVE_COMPLIANCE_COMMITTEE` — and a half-open reporting window running from `period_start` (inclusive) to `period_end` (exclusive). The end must lie strictly after the start (`ERR_INVALID_REPORT_PERIOD`), and windows of the same committee may never overlap — though adjacency, where one window starts exactly as another ends, is allowed (`ERR_REPORT_PERIOD_OVERLAP`). The report enters as `DRAFT` with `metrics` unset.

Finalizing the report freezes a five-key metrics snapshot computed at the finalize clock and stamps `finalized_at`. The `overdue_plan_count` key counts implementation plans not yet `VERIFIED` whose `deadline_posture` stands `OVERDUE`; `pending_triage_count` counts regulatory changes still `PENDING_TRIAGE` that were created before `period_end`; and `open_escalation_count` counts escalations standing in `OPEN` or `ACKNOWLEDGED`. From those three counts the `compliance_index` is derived in a pinned order — because the shares depend on the total, the tier weights are computed only after all three counts are final. If the three counts sum to zero, the index is exactly 100.0. Otherwise each count's share of the total is evaluated as an exact rational, and each share maps to a deduction weight: a share below one fifth deducts 10, a share of at least one fifth but below one half deducts 20, and a share of one half or more deducts 35. The `compliance_index` is 100 minus the sum of the three deductions, floored at zero, reported at one decimal place. The fifth key, `sla_compliance_pct`, measures assessment timeliness across the window: among impact assessments whose `submitted_at` falls inside the half-open window, it is the percentage with `sla_breached` false — 100 times the on-time count divided by the total in-window count, rounded half-up to one decimal place; when no assessment was submitted in the window, compliance is vacuous and the value is 100.0. Presenting (`FINALIZED` → `PRESENTED`) closes the lifecycle, and once a report is finalized its frozen metrics never move again. Reports can be listed filtered by `committee_name` or `status`, and the audit trail itself can be browsed filtered by `entity_type`, `entity_id`, or `actor_user_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: registering a business owner, ingesting a regulatory change, assigning an impact assessment, creating an obligation, a control, or a mapping, publishing a register version, drafting an implementation plan, a policy update, an evidence package, or a committee report, and attaching an artifact to a package. All reads and all other mutations — every state transition, attestation upsert, deadline extension, seal, and the artifact removal — return `200 OK`. The table below summarizes only the HTTP contract; request payloads, response bodies, and side effects are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/_clock/set_current_utc` | Set the logical clock and recompute clock-derived state | PlatformAdmin |
| POST | `/compliance/business-owners` | Register a business owner | ComplianceOfficer |
| GET | `/compliance/business-owners/{id}` | Get one business owner (computed counts included) | All roles |
| POST | `/compliance/regulatory-changes` | Ingest a regulatory change, optionally superseding an existing one | ComplianceOfficer |
| GET | `/compliance/regulatory-changes` | List regulatory changes with filters and pagination | All roles |
| GET | `/compliance/regulatory-changes/{id}` | Get one regulatory change | All roles |
| POST | `/compliance/regulatory-changes/{id}/triage` | Triage a pending change (APPLICABLE / NOT_APPLICABLE) | ComplianceOfficer |
| POST | `/compliance/regulatory-changes/{id}/retriage` | Pull a not-applicable change back into triage | ComplianceOfficer |
| POST | `/compliance/impact-assessments` | Assign an impact assessment to a business owner (OCC on the change) | ComplianceOfficer |
| GET | `/compliance/impact-assessments` | List impact assessments with filters and pagination | All roles |
| GET | `/compliance/impact-assessments/{id}` | Get one impact assessment | All roles |
| POST | `/compliance/impact-assessments/{id}/start` | Owner begins (or resumes after return) an assessment | BusinessOwner |
| POST | `/compliance/impact-assessments/{id}/submit` | Owner submits findings and scoring inputs | BusinessOwner |
| POST | `/compliance/impact-assessments/{id}/accept` | Accept a submitted assessment | ComplianceManager |
| POST | `/compliance/impact-assessments/{id}/return` | Return a submitted assessment for rework | ComplianceManager |
| GET | `/compliance/gap-analyses` | List gap analyses with filters and pagination | All roles |
| GET | `/compliance/gap-analyses/{id}` | Get one gap analysis | All roles |
| POST | `/compliance/gap-analyses/{id}/begin-review` | Move a gap analysis into review | ComplianceOfficer |
| POST | `/compliance/gap-analyses/{id}/confirm` | Confirm a gap analysis, freezing its residual score | ComplianceOfficer |
| POST | `/compliance/obligations` | Create an obligation register entry for an applicable change | ComplianceOfficer |
| GET | `/compliance/obligations` | List obligations with filters and pagination | All roles |
| GET | `/compliance/obligations/{id}` | Get one obligation | All roles |
| POST | `/compliance/obligations/{id}/activate` | Activate a drafted obligation | ComplianceOfficer |
| POST | `/compliance/obligations/{id}/retire` | Retire an active obligation (blocked while in use) | ComplianceOfficer |
| POST | `/compliance/obligations/{id}/reinstate` | Reinstate a retired obligation | ComplianceOfficer |
| POST | `/compliance/controls` | Create a compliance control | ComplianceOfficer |
| GET | `/compliance/controls` | List controls with filters and pagination | All roles |
| GET | `/compliance/controls/{id}` | Get one control | All roles |
| POST | `/compliance/controls/{id}/record-review` | Record a control review at the current logical clock | ComplianceOfficer |
| POST | `/compliance/controls/{id}/retire` | Retire a control (blocked while mapped) | ComplianceOfficer |
| POST | `/compliance/obligation-control-mappings` | Propose a mapping between an active obligation and an active control | ComplianceOfficer |
| GET | `/compliance/obligation-control-mappings` | List mappings with filters and pagination | All roles |
| GET | `/compliance/obligation-control-mappings/{id}` | Get one mapping | All roles |
| POST | `/compliance/obligation-control-mappings/{id}/approve` | Approve a proposed mapping (segregated from its creator) | ComplianceOfficer |
| POST | `/compliance/obligation-control-mappings/{id}/reject` | Reject a proposed mapping | ComplianceOfficer |
| POST | `/compliance/obligation-control-mappings/{id}/retire` | Retire an approved mapping, dropping its coverage | ComplianceOfficer |
| GET | `/compliance/obligation-register` | Get the singleton obligation register | All roles |
| POST | `/compliance/obligation-register/publish` | Publish a new register version snapshotting all ACTIVE obligations (OCC on the register) | ComplianceOfficer |
| GET | `/compliance/obligation-register-versions` | List published register versions | All roles |
| POST | `/compliance/implementation-plans` | Draft an implementation plan against a confirmed gap analysis | BusinessOwner |
| GET | `/compliance/implementation-plans` | List implementation plans with filters and pagination | All roles |
| GET | `/compliance/implementation-plans/{id}` | Get one implementation plan | All roles |
| POST | `/compliance/implementation-plans/{id}/submit` | Submit (or resubmit after rejection) a plan | BusinessOwner |
| POST | `/compliance/implementation-plans/{id}/approve` | Approve a submitted plan, pinning the current register version | ComplianceManager |
| POST | `/compliance/implementation-plans/{id}/reject` | Reject a submitted plan | ComplianceManager |
| POST | `/compliance/implementation-plans/{id}/begin-execution` | Start executing an approved plan | BusinessOwner |
| POST | `/compliance/implementation-plans/{id}/complete` | Mark an in-execution plan complete (late completion allowed) | BusinessOwner |
| POST | `/compliance/implementation-plans/{id}/extend-deadline` | Extend the plan deadline (max 2 extensions, 90 days each) | BusinessOwner |
| POST | `/compliance/policy-updates` | Draft a policy/procedure update for a control | ComplianceOfficer |
| GET | `/compliance/policy-updates` | List policy updates with filters and pagination | All roles |
| GET | `/compliance/policy-updates/{id}` | Get one policy update | All roles |
| POST | `/compliance/policy-updates/{id}/submit` | Submit a drafted policy update for approval | ComplianceOfficer |
| POST | `/compliance/policy-updates/{id}/approve` | Approve a policy update (OCC on the control; SoD vs drafter) | ComplianceManager |
| POST | `/compliance/policy-updates/{id}/reject` | Reject a pending policy update | ComplianceManager |
| POST | `/compliance/policy-updates/{id}/revise` | Return a rejected policy update to drafting | ComplianceOfficer |
| POST | `/compliance/policy-updates/{id}/publish` | Publish an approved policy update, spawning its training rollout | ComplianceManager |
| POST | `/compliance/policy-updates/{id}/retract` | Retract a published update before its effective date | ComplianceManager |
| GET | `/compliance/training-rollouts` | List training rollouts with filters and pagination | All roles |
| GET | `/compliance/training-rollouts/{id}` | Get one training rollout | All roles |
| POST | `/compliance/training-rollouts/{id}/attestations` | Bulk upsert attestation records keyed by person_ref | BusinessOwner |
| POST | `/compliance/training-rollouts/{id}/complete` | Complete a rollout when the 95.0 completion threshold is met within the window | BusinessOwner |
| POST | `/compliance/training-rollouts/{id}/close-with-exceptions` | Close a rollout with documented exceptions (80.0 threshold) | ComplianceManager |
| POST | `/compliance/evidence-packages` | Open an evidence package for a completed plan | BusinessOwner |
| GET | `/compliance/evidence-packages` | List evidence packages with filters and pagination | All roles |
| GET | `/compliance/evidence-packages/{id}` | Get one evidence package | All roles |
| POST | `/compliance/evidence-packages/{id}/artifacts` | Attach an artifact to an assembling package | BusinessOwner |
| DELETE | `/compliance/evidence-packages/{id}/artifacts/{artifactId}` | Remove an artifact while the package is still assembling | BusinessOwner |
| POST | `/compliance/evidence-packages/{id}/seal` | Seal the package (immutable afterwards), verifying the plan and possibly closing the change | ComplianceManager |
| POST | `/compliance/evidence-packages/{id}/submit-to-examiner` | Record submission of a sealed package to an examiner | ComplianceManager |
| GET | `/compliance/escalations` | List escalations with filters and pagination | All roles |
| GET | `/compliance/escalations/{id}` | Get one escalation | All roles |
| POST | `/compliance/escalations/{id}/acknowledge` | Acknowledge an open escalation | ComplianceManager |
| POST | `/compliance/escalations/{id}/resolve` | Manually resolve an escalation | ComplianceManager |
| POST | `/compliance/committee-reports` | Create a draft committee report for a half-open [start, end) period | BoardSecretary |
| GET | `/compliance/committee-reports` | List committee reports with filters and pagination | All roles |
| GET | `/compliance/committee-reports/{id}` | Get one committee report | All roles |
| POST | `/compliance/committee-reports/{id}/finalize` | Freeze the metrics snapshot on a draft report | BoardSecretary |
| POST | `/compliance/committee-reports/{id}/present` | Mark a finalized report as presented | BoardSecretary |
| GET | `/compliance/audit-events` | List audit events in replay order with filters and pagination | All roles |
| GET | `/compliance/audit-events/verify` | Recompute the hash chain over all events in sequence order | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_OWNER_SUSPENDED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PLAN_NOT_COMPLETED` | 409 Conflict |
| `ERR_PACKAGE_SEALED` | 409 Conflict |
| `ERR_CHANGE_NOT_SUPERSEDABLE` | 409 Conflict |
| `ERR_CHANGE_NOT_TRIAGED_APPLICABLE` | 409 Conflict |
| `ERR_OBLIGATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_OBLIGATION_IN_USE` | 409 Conflict |
| `ERR_CONTROL_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTROL_IN_USE` | 409 Conflict |
| `ERR_GAP_NOT_CONFIRMED` | 409 Conflict |
| `ERR_DUPLICATE_OBLIGATION_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CONTROL_CODE` | 409 Conflict |
| `ERR_DUPLICATE_MAPPING` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PACKAGE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_REGISTER_EMPTY` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ROLLOUT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_STALE_CHANGE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REGISTER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTROL_VERSION` | 412 Precondition Failed |
| `ERR_DEADLINE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_DEADLINE_EXCEEDS_MANDATE` | 422 Unprocessable Entity |
| `ERR_INVALID_EXTENSION` | 422 Unprocessable Entity |
| `ERR_MAX_EXTENSIONS_REACHED` | 422 Unprocessable Entity |
| `ERR_TRAINING_WINDOW_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_RETRACT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_TRAINING_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_COMPLETION_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_EXCEPTION_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_NO_ARTIFACTS` | 422 Unprocessable Entity |
| `ERR_INVALID_REPORT_PERIOD` | 422 Unprocessable Entity |

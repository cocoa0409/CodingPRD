# Pre-Employment Assessment API — Product Requirements Document

## 1. Introduction

Hiring decisions that rest on unstructured interviews and unvalidated tests are a legal and operational liability. This API serves a talent assessment team that must run pre-employment assessments and structured interviews under evidentiary discipline: every assessment instrument must carry current validation evidence, every interview guide must have a defensible competency rubric, every interviewer must be trained and calibrated before scoring, and every hiring decision must be documented with a quorum of submitted scorecards behind it. Layered on top of that discipline are the obligations that make this domain unforgiving — adverse impact analysis by candidate group under the four-fifths rule, accommodation requests that extend administration windows, retention windows after which candidate scores must be purged, and a chain-of-custody ledger for proprietary instrument content distributed by external vendors.

The system is mounted under `/talent` and is organized around a small number of cooperating aggregates. Vendors supply instruments; instruments accumulate validation evidence and move through a cyclic validation lifecycle. Interview guides carry weighted competency rubrics and form a self-referential revision chain in which approving a successor retires its predecessor. Hiring managers open requisitions, create assessment cycles that pin one instrument and one guide, invite candidates, and shepherd each candidate's assessment through scheduling, administration, and completion. Interviewers score completed sessions on guides they are calibrated for; compliance officers run adverse-impact snapshots, freeze and unfreeze cycles, adjudicate accommodations, void scorecards, and execute retention sweeps; decision officers — who are forbidden from having scored the same candidate — record the final, immutable hiring decision.

Two design commitments shape every workflow in this document. First, segregation of duties is structural: the administrator who authors a guide may not approve it, the interviewer who scores a candidate may not decide that candidate's outcome, and the manager who schedules an assessment may not approve its accommodations. Second, the platform runs on a logical clock rather than the wall clock, so that evidence expiry, calibration lapse, retention expiry, and every time-window gate are deterministic and testable. All datetimes in this document refer to that logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, if `X-User-Role` is not one of the declared roles, or if an entity-backed role's `X-User-ID` does not reference an existing instance of its backing entity, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the authenticated role is not listed among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Seven roles exist, spelled exactly as follows:

- `TalentAssessmentAdmin` — the talent assessment operations administrator. Configures vendors, instruments, evidence, interview guides, interviewers, and calibrations, and drives the logical clock. Deliberately excluded from scoring and decision duties. When `X-User-Role` is `TalentAssessmentAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `HiringManager` — owns requisitions and runs their cycles: creating, patching, activating, scoring, and closing cycles, inviting candidates, scheduling and completing sessions, completing assessments, and sending feedback. When `X-User-Role` is `HiringManager`, `X-User-ID` is an opaque operator identifier; it is recorded as `hiring_manager_id` on each requisition the manager creates, and ownership checks on that requisition and all of its child cycles compare the resource's `hiring_manager_id` to `X-User-ID`.
- `Interviewer` — an entity-backed role. When `X-User-Role` is `Interviewer`, `X-User-ID` is the `id` of the acting `Interviewer` entity; ownership checks on any resource that references an interviewer compare the resource's `interviewer_id` field to `X-User-ID`. Interviewers author scorecards only for their own sessions.
- `Candidate` — an entity-backed role. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` entity; ownership checks on any resource that references a candidate compare the resource's `candidate_id` field to `X-User-ID`. Candidates view their own assessments and decisions and file and withdraw their own accommodation requests.
- `DecisionOfficer` — documents hiring decisions and is forbidden by segregation of duties from having scored the same candidate. When `X-User-Role` is `DecisionOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded as `decided_by_user_id` on each decision.
- `ComplianceOfficer` — runs adverse-impact snapshots, freezes and unfreezes cycles, adjudicates accommodation requests, voids scorecards, and executes retention sweeps. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for it (for example, as `decided_by_user_id` on an adjudicated accommodation request or `executed_by_user_id` on a purge event) but does not compare it to any entity's `id`.
- `VendorRepresentative` — an entity-backed role. When `X-User-Role` is `VendorRepresentative`, `X-User-ID` is the `id` of the acting `AssessmentVendor` entity; ownership checks on vendor-scoped resources compare the vendor's `id` (or an instrument's `vendor_id`) to `X-User-ID`. Vendor representatives file validation evidence for their own vendor's instruments and record certified content destructions.

A failed ownership comparison — a hiring manager acting on another manager's requisition, an interviewer acting on another's session or scorecard, a candidate acting on another's assessment, a vendor representative acting on another vendor — is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100; the `offset` parameter defaults to 0. List responses are always sorted by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept domain filters, each matching the identically named field on the listed resource. Instruments may be filtered by `vendor_id` and `validation_status`; interview guides by `supersedes_guide_id` and `status`; cycles by `requisition_id`, `instrument_id`, `guide_id`, and `posture`; candidate assessments by `cycle_id`, `candidate_id`, and `admin_status`; calibration records by `interviewer_id`, `guide_id`, and `status`; interview sessions by `cycle_id`, `candidate_id`, `interviewer_id`, `guide_id`, and `status`; scorecards by `session_id`, `interviewer_id`, `candidate_id`, and `status`; and hiring decisions by `cycle_id` and `candidate_id`. These filters double as the reverse-lookup mechanism for parent-child relationships — a vendor's instruments, a cycle's assessments, an interviewer's sessions — since no separate "children of" endpoints exist beyond the few nested list routes noted in §4.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — assigned at creation and never reused. Alongside `id`, resources carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and a `version` integer. Every mutation of a resource increments its `version` by exactly one and refreshes its `updated_at`; creations set both timestamps to the logical-clock time of creation. The same rendering — ISO 8601 UTC with three fractional digits, and null when the field has no value — applies to every other datetime-valued field a resource or audit event carries: `terminated_at`, `validity_expires_at`, `filed_at`, `effective_from`, `effective_until`, `closed_at`, `scheduled_for`, `started_at`, `completed_at`, `retention_expires_at`, `purged_at`, `decided_at`, `trained_at`, `certified_at`, `scheduled_start`, `scheduled_end`, `submitted_at`, `voided_at`, `finalized_at`, `computed_at`, and the purge event's `retention_expires_at_snapshot`. The cycle's `administration_window_start` and `administration_window_end` are the two exceptions: they are rendered in the RFC 1123 HTTP-date form (for example, `Mon, 10 Aug 2026 00:00:00 GMT`).

Two resources are deliberately exempt from the full common-field set because they are append-only audit records. A content ledger event carries only `id` and `created_at` — both `updated_at` and `version` are absent — and the same is true of a retention purge event. Neither resource is ever mutated after creation.

### 2.5. The Logical Clock and Time-Materialized Transitions

The platform never reads the wall clock. A logical clock governs every time-based rule in this document — administration windows, evidence currency, retention expiry, the scorecard submission window, and calibration lapse all evaluate against it. At startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z.

An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Setting the clock materializes the automatic transitions that have fallen due: every instrument whose `validity_expires_at` is now strictly in the past transitions from `VALIDATED` to `EXPIRED` (at exact equality with `validity_expires_at` the instrument remains `VALIDATED`), and every calibration record whose `certified_at` lies more than 365 days in the past transitions from `CALIBRATED` to `LAPSED` (exactly 365 days after certification, the record remains `CALIBRATED` — the comparison is strictly greater). The capability responds with the new logical time as `now` together with the counts `instruments_expired` and `calibrations_lapsed` describing how many of each transition were materialized by that call. Automatic transitions that are event-driven rather than time-driven — a requisition becoming `FILLED`, a cycle becoming `DECIDED`, a superseded guide retiring, a session reverting on a voided scorecard — are not clock materializations; they fire at the moment the causing write occurs.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and no others are; endpoints not named here accept no version field.

The cycle update endpoint, `PATCH /talent/cycles/{id}` — updating a `SETUP` cycle's administration window, daily capacity, or pinned instrument or guide — requires the request to carry `expected_cycle_version`, a non-optional field holding the cycle `version` the client last observed. If that value no longer matches the cycle's current `version` — because another writer has modified the cycle since the client last read it — the update is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), and no field of the request is applied.

The guide revisions endpoint, `POST /talent/interview-guides/{id}/revisions` — creating a revision guide that supersedes an existing approved guide — requires the request to carry `expected_superseded_guide_version`, again non-optional, holding the superseded guide's `version` as the client last observed it. A supersede legitimately mutates the current head — it sets the superseded guide's `superseded_by_guide_id` and increments that guide's `version` by one — so a client whose observed version has been advanced by another writer is authoring against an out-of-date head and must re-read before revising; the create is rejected with `ERR_STALE_GUIDE_VERSION` (HTTP 412).

### 2.7. Precision, Rounding, and Score Representation

All computed scores and rates in this domain are rendered at four decimal places with round-half-up rounding: the candidate `composite_score`, the scorecard `weighted_total`, the per-group `selection_rate` and `impact_ratio`, the interviewer `calibration_index`, and the `composite_at_decision` snapshot. Where a calculation chains rounded quantities, the rounding order is part of the contract and is stated with the calculation itself — adverse-impact rates are rounded per group before any ratio is taken, and per-competency mean ratings are rounded before they are weighted. Counts, capacities, day-based windows, and committed minutes are integers. Datetime comparisons — window gates, retention gates, certification lapse — are evaluated at second precision.

### 2.8. Validation Priority and Error Ordering

A single request can violate several rules at once. When it does, the failure reported is the violated rule with the lowest priority number; this ordering is normative and is observable by clients. The tiers, from first-evaluated to last, are:

1. **Authentication** — presence and validity of `X-User-Role` and `X-User-ID`, including resolution of entity-backed identifiers (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the role is admitted by the endpoint (`ERR_FORBIDDEN`).
3. **Path resolution** — URL identifiers resolve to existing resources, left to right (`ERR_NOT_FOUND`).
4. **Body reference resolution** — foreign keys in the payload resolve, left to right in declared input order (`ERR_REFERENCED_ENTITY_NOT_FOUND`).
5. **Ownership** — the caller's ownership anchor matches (`ERR_OWNERSHIP_MISMATCH`).
6. **Generic state** — the target resource's own state admits the transition (`ERR_INVALID_STATE`).
7. **Dedicated state gates** — cycle posture (`ERR_CYCLE_NOT_ACTIVE`, `ERR_CYCLE_FROZEN`), requisition openness (`ERR_REQUISITION_NOT_OPEN`), candidate activity (`ERR_CANDIDATE_WITHDRAWN`), scorecard and session source states (`ERR_SCORECARD_NOT_DRAFT`, `ERR_SCORECARD_NOT_SUBMITTED`, `ERR_SESSION_NOT_COMPLETED`), assessment completion (`ERR_ASSESSMENT_NOT_COMPLETED`), accommodation pendency (`ERR_ACCOMMODATION_NOT_PENDING`), and vendor terminal lockdown (`ERR_ALREADY_TERMINAL`).
8. **Optimistic concurrency** — the two OCC checks of §2.6 (`ERR_STALE_CYCLE_VERSION`, `ERR_STALE_GUIDE_VERSION`).
9. **Business safety gates** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), interviewer calibration (`ERR_INTERVIEWER_NOT_CALIBRATED`), vendor and instrument and guide readiness (`ERR_VENDOR_NOT_ACTIVE`, `ERR_INSTRUMENT_NOT_VALIDATED`, `ERR_GUIDE_NOT_APPROVED`), and adverse-impact resolution (`ERR_ADVERSE_IMPACT_UNRESOLVED`).
10. **Business constraints** — uniqueness rules, rubric structure, double-booking, daily capacity, session duration, window ordering, ratings structure, the decision quorum, ledger and outstanding-copy floors, and the various "still open" blockers (for example `ERR_DUPLICATE_INVITATION`, `ERR_RUBRIC_WEIGHT_SUM`, `ERR_INTERVIEWER_DOUBLE_BOOKED`, `ERR_QUORUM_NOT_MET`, `ERR_CONTENT_LEDGER_NEGATIVE`, `ERR_SESSIONS_STILL_SCHEDULED`, `ERR_CYCLE_NOT_CLOSED`, `ERR_GUIDE_PINNED`).
11. **Temporal gates** — administration-window and duration-of-validity checks (`ERR_OUTSIDE_ADMINISTRATION_WINDOW`, `ERR_SESSION_NOT_ENDED`, `ERR_SCORECARD_WINDOW_CLOSED`, `ERR_RETENTION_EXPIRED`, `ERR_EVIDENCE_EXPIRED`).
12. **Guide version pinning** — the session's `guide_id` must equal the cycle's pinned guide (`ERR_GUIDE_VERSION_MISMATCH`).
13. **Evidence-type presence** — required evidence types entirely absent (`ERR_EVIDENCE_TYPE_MISSING`).
14. **Practice-score threshold** (`ERR_PRACTICE_SCORE_BELOW_THRESHOLD`).
15. **Extension-day range** (`ERR_EXTENSION_OUT_OF_RANGE`).
16. **Generic request shape and text lengths** — missing or malformed fields, invalid enum members, and the specific length-coded checks `ERR_RATIONALE_TOO_SHORT`, `ERR_FEEDBACK_TEXT_TOO_SHORT`, and `ERR_SCORE_OUT_OF_RANGE`, plus duplicate feedback (`ERR_FEEDBACK_ALREADY_SENT`); anything of this kind without a dedicated code is `ERR_INVALID_REQUEST`.
17. **Decision-finalized precondition on feedback** (`ERR_DECISION_NOT_FINALIZED`).

The practical consequence: an authentication failure masks everything beneath it, a stale-version rejection (tier 8) surfaces before any business-safety or constraint failure on the same request, and a too-short feedback text surfaces before a duplicate-feedback or missing-decision rejection. Rules sharing a tier are not further ordered.

### 2.9. Nested Resource Resolution

Many resources are addressed through their parents — an evidence record through its instrument, an accommodation request through its assessment, a cycle through its requisition. Path-template identifiers are resolved left to right: on a route such as a requisition's cycle collection, the requisition is resolved before anything nested beneath it, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in a request body are likewise resolved left to right in the order the endpoint declares them — a cycle-creation payload, for example, resolves `instrument_id` before `guide_id` — and the first unresolvable reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404). Both checks run before any state, safety, or business-constraint evaluation.

### 2.10. Ownership and Segregation of Duties

Four ownership anchors recur across the API. A requisition is owned through its `hiring_manager_id`, and that ownership extends to every child-cycle operation beneath it — activation, freezing aside (a compliance duty), scoring, closing, invitations, sessions, assessments, and feedback. An interviewer owns sessions and scorecards through `interviewer_id` and calibration records the same way. A candidate owns assessments through `candidate_id`, and accommodation requests inherit that ownership through their parent assessment. A vendor representative owns a vendor through the vendor's `id`, extending to its instruments' evidence and its content ledger. Any mismatch is `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

Segregation of duties is enforced by role separation in three places, two of which additionally carry an explicit check. The administrator who authored an interview guide may not approve it — the approver's `X-User-ID` must differ from the guide's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The officer recording a hiring decision must not have scored that candidate — the decider's `X-User-ID` must not equal the `interviewer_id` of any submitted scorecard counted toward that candidate's quorum, else the same `ERR_SEGREGATION_OF_DUTIES`. And the scheduling of assessments (a hiring-manager duty) is separated from the adjudication of accommodation requests (a compliance-officer duty) by the role model itself, so the person who controls the calendar never controls the accommodation outcome.

Entity-backed roles are likewise scoped on list endpoints. When an `Interviewer` lists calibration records, sessions, or scorecards and supplies the `interviewer_id` filter, the supplied value must equal their `X-User-ID`; when a `Candidate` lists sessions or decisions and supplies the `candidate_id` filter, it likewise must equal their `X-User-ID`; and a `Candidate` listing assessments must pass `candidate_id` equal to their own `X-User-ID`. A filter naming anyone else is `ERR_OWNERSHIP_MISMATCH`.

## 3. Business Logic & Workflows

### 3.1. Vendors and the Content Chain of Custody

A `TalentAssessmentAdmin` registers an assessment vendor with its legal `name` and an optional `security_clearance_tier` of `TIER_1`, `TIER_2`, or `TIER_3` (defaulting to `TIER_2` when omitted). A new vendor begins in `ACTIVE` status with a `content_copies_outstanding` ledger balance of zero. Reading a vendor — permitted for the administrator, a `ComplianceOfficer`, and the vendor's own representative — exposes the current ledger balance; a `VendorRepresentative` may read only the vendor whose `id` equals their `X-User-ID`.

Instrument content moves under a chain-of-custody ledger. Each ledger event names its parent vendor through the URL (recorded as `vendor_id`), carries a `direction` of either `DISTRIBUTE` (copies leave the vendor's vault to a client) or `DESTROY` (certified secure destruction), a positive integer `copies` count of at least one, and a chain-of-custody `note` of at least ten characters; the server stamps each event with the recorder's `X-User-ID` as `recorded_by_user_id`. The ledger is append-only. The vendor's `content_copies_outstanding` is the sum of `copies` over distribution events minus the sum over destruction events, and it may never go negative: a destruction event whose `copies` exceeds the current outstanding balance is rejected with `ERR_CONTENT_LEDGER_NEGATIVE` (HTTP 422). The conserved-quantity invariant is that distributing some number of copies and later destroying the same number returns the outstanding balance exactly to its prior value. Only the administrator may record a `DISTRIBUTE`, and only while the vendor is `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`); a `DESTROY` may be recorded by the administrator or by the vendor's own representative — the chain-of-custody segregation of duties, in which the admin distributes and the vendor confirms destruction — while the vendor is `ACTIVE` or `SUSPENDED`. Once a vendor is `TERMINATED`, every ledger, suspension, reinstatement, and termination attempt against it is rejected as `ERR_ALREADY_TERMINAL` (HTTP 409).

Suspending a vendor is the deepest cascade in the system, propagating three links outward. The vendor moves `ACTIVE` → `SUSPENDED`, and then: first, every instrument of that vendor whose `validation_status` is not `RETIRED` has its `vendor_suspended` flag set to true and its `version` incremented; second, every assessment cycle whose pinned `instrument_id` belongs to that flagged set and whose `posture` is `SETUP`, `ACTIVE`, or `SCORING` is forced into `FROZEN`, capturing the prior posture in `frozen_from_posture`, recording `frozen_reason` as `VENDOR_HOLD`, and incrementing the cycle's `version`; third, every interview session in those cycles still in `SCHEDULED` status is cancelled with `cancellation_reason` set to `VENDOR_HOLD` and its `version` incremented, and each such cancellation debits the affected interviewer's `committed_minutes_total` by the session's duration in minutes.

Reinstating a vendor unwinds only part of that cascade. The vendor returns `SUSPENDED` → `ACTIVE`; every instrument of the vendor has `vendor_suspended` cleared to false with a version increment; and every cycle frozen with `frozen_reason` of `VENDOR_HOLD` that references those instruments returns to the posture captured in its `frozen_from_posture`, with both frozen fields nulled and `version` incremented. The compensation is deliberately asymmetric: sessions cancelled by the suspension are not restored, and the debited committed minutes are not re-credited. A scheduler who still wants those interviews books them again.

Terminating a vendor is possible from `ACTIVE` or `SUSPENDED` and only when the content ledger has fully settled: a `content_copies_outstanding` balance above zero blocks termination with `ERR_CONTENT_COPIES_OUTSTANDING` (HTTP 422). Termination stamps `terminated_at` (null until then) and deliberately triggers no instrument or cycle cascade — instead, cycles referencing the vendor's instruments become un-activatable through the vendor-readiness gates described in §3.4.

### 3.2. Instruments and Validation Evidence

An administrator registers an instrument under a vendor by supplying the `vendor_id` (immutable once set), a vendor-scoped `code`, an `instrument_type` of `COGNITIVE_ABILITY`, `PERSONALITY`, `SKILLS_SIMULATION`, or `JOB_KNOWLEDGE`, a display `title`, an integer `max_score` of at least one, a `pass_floor` that is a non-negative integer strictly below `max_score`, and optionally `adverse_impact_monitor_enabled` (defaulting to true). The same `code` may not be registered twice under one vendor; a collision is `ERR_DUPLICATE_INSTRUMENT_CODE` (HTTP 409). The vendor must be `ACTIVE` at registration, else `ERR_VENDOR_NOT_ACTIVE`. A new instrument's `validation_status` begins at `DRAFT`, its `validity_expires_at` is null until its first validation, and its `vendor_suspended` flag begins false.

Validation evidence is filed against an instrument — by the administrator, or by a vendor representative whose `X-User-ID` equals the instrument's `vendor_id` — with an `evidence_type` of `CRITERION`, `CONTENT`, or `CONSTRUCT`, a `title`, an `issuer`, and a validity interval from `effective_from` to `effective_until`, where the end must be strictly later than the start. Filing stamps `filed_at` with the logical time, and filed evidence is immutable. At any moment, a piece of evidence counts as current when its `effective_from` is at or before the logical now and its `effective_until` is strictly after it — the interval is closed at the start and open at the end.

The instrument lifecycle is cyclic. Submitting for validation review moves `DRAFT` → `VALIDATION_REVIEW` and requires the vendor to be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`) and at least one evidence record of any type already filed (else `ERR_EVIDENCE_TYPE_MISSING`, HTTP 422). Validation itself moves `VALIDATION_REVIEW` → `VALIDATED` — or, later in the cycle, `REVALIDATION` → `VALIDATED` under the same rules — and demands, beyond an `ACTIVE` vendor, at least one current `CRITERION` record and at least one current `CONTENT` record. When a required type is entirely absent the failure is `ERR_EVIDENCE_TYPE_MISSING`; when records of the type exist but none is current, the failure is `ERR_EVIDENCE_EXPIRED` (HTTP 422). A successful validation sets `validity_expires_at` to the earliest `effective_until` among the currently valid `CRITERION` and `CONTENT` records — the instrument's validity dies with the first expiring pillar of evidence.

From there the instrument ages automatically: when the logical clock advances strictly beyond `validity_expires_at`, the instrument moves `VALIDATED` → `EXPIRED`, with no cascade to cycles — the gating is enforced at cycle creation and activation instead. An expired instrument may begin revalidation, moving `EXPIRED` → `REVALIDATION`, only when at least one `CRITERION` record has been filed strictly after `validity_expires_at` (its `filed_at` later than the expiry instant), else `ERR_EVIDENCE_TYPE_MISSING`; revalidation then re-enters the validation gate above, which recomputes `validity_expires_at` from the current evidence. Retirement is terminal and is admitted from `DRAFT`, `VALIDATION_REVIEW`, `REVALIDATION`, or `EXPIRED`, but only while no assessment cycle in a posture other than `CLOSED` references the instrument — otherwise the retire is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Interview Guides, Rubrics, and Revision Chains

Interview guides are the scoring contract of the structured interview. An administrator creates a root guide with a `title`, a `rubric_items` array, and an optional `scoring_mode` of `RAW` or `LENIENCY_ADJUSTED` (defaulting to `RAW`). The guide starts in `DRAFT`, its `created_by_user_id` records the creator's `X-User-ID`, and its `version_label` is 1. Each rubric item pairs a `competency_code` with a `weight` greater than zero and at most one, and a `scale_max` integer between 2 and 10 inclusive; competency codes must be unique within the guide, and the rubric must contain at least two items. Two structural checks guard this contract, and both are enforced at creation and again at the pilot transition: fewer than two items is `ERR_RUBRIC_TOO_FEW_ITEMS` (HTTP 400), and weights that do not sum to exactly 1.0000 compared at four decimal places are `ERR_RUBRIC_WEIGHT_SUM` (HTTP 400). The weight-sum check is repeated once more at approval.

A guide moves `DRAFT` → `PILOT` when it passes the rubric checks, and `PILOT` → `DRAFT` again through retraction when the pilot exposes problems. Approval moves `PILOT` → `APPROVED` and is where segregation of duties bites: the approver's `X-User-ID` must differ from the guide's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Approval also carries the revision-chain cascade — if the guide being approved declares a `supersedes_guide_id` and that predecessor is currently `APPROVED`, the predecessor automatically transitions `APPROVED` → `RETIRED` with its `version` incremented. The chain therefore holds at most one approved head per lineage.

Revisions enter through a dedicated supersede capability rather than through ordinary creation. Creating a revision of an existing guide requires the target to be `APPROVED` — otherwise `ERR_GUIDE_NOT_APPROVED` — and is optimistic-concurrency guarded per §2.6 with `expected_superseded_guide_version`. The payload carries the new `title`, the new `rubric_items`, and an optional `scoring_mode`; the new guide starts in `DRAFT` with `supersedes_guide_id` taken from the path, `created_by_user_id` from the caller, and `version_label` equal to the superseded guide's `version_label` plus one. The same write sets the superseded guide's `superseded_by_guide_id` to the new guide and increments the superseded guide's `version` by one — which is precisely the mutation the OCC field guards against losing.

Retirement of a guide by direct request is admitted from `DRAFT`, `PILOT`, or `APPROVED` but only while the guide's `pinned_cycle_count` — the number of assessment cycles pinning this guide whose posture is not `CLOSED` — is zero; a pinned guide refuses retirement with `ERR_GUIDE_PINNED` (HTTP 409). Supersede-approval is the one path that retires a guide regardless of pins: a guide still referenced by open cycles may be superseded, and approval of the successor retires it even so.

### 3.4. Requisitions and Assessment Cycles

A hiring manager opens a requisition with a job `title`, a `department`, an `openings_count` of at least one, and an optional `retention_days` — the score-retention window, defaulting to 730 days and bounded between 180 and 3650 days. The requisition starts `OPEN` with a `filled_count` of zero, and the creator's `X-User-ID` is recorded as `hiring_manager_id`, anchoring ownership of everything built beneath it. The `filled_count` is computed as the number of finalized hiring decisions with `decision` of `ADVANCE` across all of the requisition's cycles, and when an `ADVANCE` decision pushes it to meet or exceed `openings_count`, the requisition's `status` automatically becomes `FILLED`. Closing a requisition — from `OPEN` or `FILLED` — is an owner-only operation and requires every cycle of the requisition to have reached `CLOSED`; otherwise the close is refused with `ERR_CYCLE_NOT_CLOSED` (HTTP 409).

Beneath a requisition, the hiring manager creates an assessment cycle by pinning the two methodological pillars: an `instrument_id` and a `guide_id`, resolved in that order when the payload references are checked. The payload also carries a `label`, an `administration_window_start`, an `administration_window_end` that must be strictly later than the start (a reversal is `ERR_WINDOW_ORDER_INVALID`, HTTP 400), and an optional `max_sessions_per_day` — the aggregate interview capacity per UTC calendar day, defaulting to 8 and bounded between 1 and 100. Creation is gated on four cross-entity conditions, evaluated after ownership: the requisition must be `OPEN` (`ERR_REQUISITION_NOT_OPEN`), the instrument must be `VALIDATED` (`ERR_INSTRUMENT_NOT_VALIDATED`), the vendor must be `ACTIVE` with the instrument's `vendor_suspended` flag false (`ERR_VENDOR_NOT_ACTIVE`), and the guide must be `APPROVED` (`ERR_GUIDE_NOT_APPROVED`). A new cycle begins in `SETUP` posture, and creating it increments the pinned guide's `pinned_cycle_count` by one.

While a cycle remains in `SETUP`, its configuration can still be corrected. Such an update may revise `administration_window_start`, `administration_window_end`, `max_sessions_per_day`, or re-pin `instrument_id` or `guide_id`; it carries the OCC field `expected_cycle_version` per §2.6, increments the cycle's `version` by one on success, re-checks the window ordering when window fields change, and re-applies the readiness gates when a pin changes — a replacement instrument must be `VALIDATED` and a replacement guide `APPROVED`. Once the cycle has left `SETUP`, the same update is rejected with `ERR_INVALID_STATE`.

Activation moves `SETUP` → `ACTIVE` and is the densest gate in the system. After the ownership check, the gates evaluate in tier order: the requisition must still be `OPEN` (`ERR_REQUISITION_NOT_OPEN`); then the readiness tier — instrument `VALIDATED` (`ERR_INSTRUMENT_NOT_VALIDATED`), vendor `ACTIVE` and instrument not vendor-suspended (`ERR_VENDOR_NOT_ACTIVE`), guide `APPROVED` (`ERR_GUIDE_NOT_APPROVED`); and finally the temporal gate — the `administration_window_end` must not be in the past, so activating on the final day of the window is still valid and a window that has already closed is `ERR_OUTSIDE_ADMINISTRATION_WINDOW` (HTTP 422).

A compliance officer may freeze a cycle from `SETUP`, `ACTIVE`, or `SCORING`, supplying an optional `reason_note` and an optional `freeze_reason`; the reason defaults to `MANUAL` and may alternatively be recorded as `ADVERSE_IMPACT` to place a manual adverse-impact hold even before any final snapshot exists. Freezing captures the prior posture in `frozen_from_posture` and stores the `frozen_reason`; outside a freeze, both fields are null. Unfreezing returns the cycle to exactly the posture captured in `frozen_from_posture` — `SETUP`, `ACTIVE`, or `SCORING` — and clears both frozen fields. It requires a `resolution_note` of at least twenty characters (`ERR_INVALID_REQUEST`), and two reason-specific gates: unfreezing an `ADVERSE_IMPACT` hold requires at least one `FINAL` adverse-impact snapshot to exist for the cycle, else `ERR_ADVERSE_IMPACT_UNRESOLVED` (HTTP 422) — so a manual hold placed before any snapshot cannot be lifted until a final snapshot has been computed — and unfreezing a `VENDOR_HOLD` requires the vendor to be `ACTIVE` with the instrument's suspension flag cleared, else `ERR_VENDOR_NOT_ACTIVE`.

Posture gates every child operation of a cycle, and two distinct error codes keep the failure modes distinguishable: when the posture is `FROZEN`, posture-gated child operations fail with `ERR_CYCLE_FROZEN` (HTTP 409); when the posture is simply the wrong stage, they fail with `ERR_CYCLE_NOT_ACTIVE` (HTTP 409). Invitations are admitted while the posture is `SETUP` or `ACTIVE`; scheduling, starting, completing, and rescheduling assessments, booking and completing sessions, and approving accommodations require `ACTIVE`; scorecard authoring and submission admit `ACTIVE` or `SCORING`; adverse-impact snapshots admit `ACTIVE`, `SCORING`, `DECIDED`, or `FROZEN`.

When interviews are done, the hiring manager begins scoring, moving `ACTIVE` → `SCORING`; the transition requires zero sessions still in `SCHEDULED` within the cycle, else `ERR_SESSIONS_STILL_SCHEDULED` (HTTP 409). The cycle then advances `SCORING` → `DECIDED` automatically at the moment every candidate assessment in the cycle with `admin_status` of `COMPLETED` has a finalized hiring decision — the count of hiring decisions in the cycle equals the count of completed assessments.

Closing a cycle is admitted from any non-terminal posture — `SETUP`, `ACTIVE`, `FROZEN`, `SCORING`, or `DECIDED` — and runs a three-link cascade. First, every candidate assessment in the cycle whose `admin_status` is `INVITED`, `SCHEDULED`, `ACCOMMODATION_HOLD`, or `IN_PROGRESS` moves to `CANCELLED`, with its `feedback_status` moving `NOT_SENT` → `NOT_APPLICABLE` where still unsent, and its `version` incremented. Second, each such cancellation decrements the cycle's `active_candidate_count` by one and cancels that candidate's still-`SCHEDULED` interview sessions in the cycle with `cancellation_reason` of `CYCLE_CLOSED`, debiting each affected interviewer's committed minutes. Third, the retention anchor is recomputed for every completed assessment in the cycle that has no finalized decision: its `retention_expires_at` becomes the cycle's `closed_at` plus the requisition's `retention_days`. The close stamps `closed_at` on the cycle itself (null until the cycle closes).

Two computed counters summarize a cycle at rest: `active_candidate_count`, the number of its candidate assessments whose `admin_status` is neither `CANCELLED` nor `PURGED`, and `decisions_finalized_count`, the number of hiring decisions recorded in the cycle.

### 3.5. Candidates, Invitations, and Accommodations

A candidate is registered — by a hiring manager or an administrator — with a globally unique `external_ref` (an external ATS reference; a collision is `ERR_DUPLICATE_CANDIDATE_REF`, HTTP 409), a `full_name`, a contact `email`, and a self-identified `group_code` of `GROUP_A`, `GROUP_B`, `GROUP_C`, `GROUP_D`, or `UNDISCLOSED` that feeds adverse-impact analysis. Candidates begin `ACTIVE`.

Inviting a candidate into a cycle creates a candidate assessment in `INVITED` status and increments the cycle's `active_candidate_count`. The cycle's posture must be `SETUP` or `ACTIVE` (a frozen cycle answers `ERR_CYCLE_FROZEN`, any other wrong stage `ERR_CYCLE_NOT_ACTIVE`), the candidate must still be `ACTIVE` (`ERR_CANDIDATE_WITHDRAWN`), the inviting manager must own the requisition, the new assessment's `accommodation_extension_days` begins at zero, and the pairing of cycle and candidate must be new — a second invitation of the same candidate into the same cycle is `ERR_DUPLICATE_INVITATION` (HTTP 409), with the `candidate_id` recorded on the new assessment alongside the `cycle_id` taken from the path.

From `INVITED`, the manager schedules the assessment by supplying a `scheduled_for` instant, moving it to `SCHEDULED`; the cycle must be `ACTIVE`. Starting the assessment moves `SCHEDULED` → `IN_PROGRESS` and stamps `started_at`; completion moves `IN_PROGRESS` → `COMPLETED`, stamps `completed_at`, accepts the `raw_score`, and computes the `composite_score`. Both start and complete enforce the effective administration window: the logical now must lie within the closed interval from the cycle's `administration_window_start` through the effective end, where the effective end is the cycle's `administration_window_end` extended by the assessment's accumulated `accommodation_extension_days`. The interval is closed at both ends, so starting or completing at exactly the effective end instant is valid; outside it, the failure is `ERR_OUTSIDE_ADMINISTRATION_WINDOW`. Completion additionally requires the `raw_score` to lie between zero and the instrument's `max_score` inclusive, else `ERR_SCORE_OUT_OF_RANGE` (HTTP 400). The `composite_score` is non-null exactly while the assessment is `COMPLETED`, and is nulled again if the assessment is later purged.

A scheduled candidate who never presents may be marked no-show, moving `SCHEDULED` → `NO_SHOW`, only once the logical now is strictly later than `scheduled_for`; the mark also moves `feedback_status` from `NOT_SENT` to `NOT_APPLICABLE`. Cancelling an assessment — by the hiring manager, by the candidate themselves, or by a cascade — is admitted from `INVITED`, `SCHEDULED`, `ACCOMMODATION_HOLD`, or `IN_PROGRESS`, and each cancellation decrements the parent cycle's `active_candidate_count` by one, moves an unsent `feedback_status` to `NOT_APPLICABLE`, cancels the candidate's still-`SCHEDULED` interview sessions in that cycle (the `cancellation_reason` recording the trigger: `MANUAL`, `CANDIDATE_WITHDRAWN`, or `CYCLE_CLOSED`), debiting committed minutes accordingly, and moves any still-`PENDING` accommodation requests on the assessment to `WITHDRAWN`.

Withdrawal of the candidate altogether — by the candidate (whose `X-User-ID` must equal the candidate's `id`) or by a hiring manager — moves the candidate `ACTIVE` → `WITHDRAWN` and fans the same cascade across every cycle: each of the candidate's assessments in `INVITED`, `SCHEDULED`, `ACCOMMODATION_HOLD`, or `IN_PROGRESS` is cancelled with the count decrement and unsent-feedback flip; each of the candidate's `SCHEDULED` sessions anywhere is cancelled with `cancellation_reason` of `CANDIDATE_WITHDRAWN` and the minutes debit; and every `PENDING` accommodation request on those assessments is withdrawn. Inviting or withdrawing an already-`WITHDRAWN` candidate fails with `ERR_CANDIDATE_WITHDRAWN` (HTTP 409).

Accommodation requests belong to the candidate. Filing one — against the candidate's own assessment, so `candidate_id` must equal `X-User-ID` — supplies a `request_type` of `EXTENDED_TIME`, `ALTERNATE_FORMAT`, `SCREEN_READER`, or `OTHER`, a `justification` of at least twenty characters, and a `requested_extension_days` between 1 and 30; the request begins `PENDING`, and an assessment may carry at most one `PENDING` request at a time, a second one drawing `ERR_PENDING_ACCOMMODATION_EXISTS` (HTTP 409).

Adjudication belongs to the compliance officer, and approval is the interesting branch. Approving requires the request still `PENDING` (`ERR_ACCOMMODATION_NOT_PENDING`, HTTP 409), the parent assessment in `INVITED`, `SCHEDULED`, or `ACCOMMODATION_HOLD` (any other administration state is `ERR_INVALID_STATE`), and the cycle in `ACTIVE` posture. The officer supplies `approved_extension_days` — at least one and at most the `requested_extension_days`, else `ERR_EXTENSION_OUT_OF_RANGE` (HTTP 400) — and a `decision_note`; the server records both, along with the officer's `X-User-ID` as `decided_by_user_id` and the logical time as `decided_at`. These checks evaluate in priority order: the assessment's state first, then pendency and posture together at the dedicated-state tier, and the extension-day range last. Approval adds `approved_extension_days` to the assessment's `accommodation_extension_days`, and if the assessment was `SCHEDULED` it moves automatically to `ACCOMMODATION_HOLD` — the old slot can no longer be trusted, and the assessment must be rescheduled before it can start. An approval landing while the assessment is still `INVITED` is a deliberate no-op on status: the extension days accumulate, but the assessment stays `INVITED`. Rescheduling moves `ACCOMMODATION_HOLD` → `SCHEDULED` with a fresh `scheduled_for`, again requiring the cycle `ACTIVE` and the manager's ownership. Denial moves `PENDING` → `DENIED`, keeps the same pendency gate, requires a `decision_note` of at least ten characters, and records the same decision fields without touching the assessment. Withdrawal of a request — by the candidate whose assessment it is, or by cascade when the candidate withdraws — moves `PENDING` → `WITHDRAWN`.

### 3.6. Interview Sessions, Scorecards, and Calibration

Interviewers are registered by an administrator with a `full_name`, a work `email`, and a `department`; each begins with a `committed_minutes_total` of zero. That counter is a conserved workload ledger: it equals the sum, over all of the interviewer's sessions currently in `SCHEDULED`, of each session's duration in whole minutes. Booking a session credits the duration; any cancellation of a scheduled session — manual, vendor cascade, candidate withdrawal, cycle close, or assessment cancellation — debits the same duration, so booking a session and then cancelling it returns `committed_minutes_total` to exactly its prior value. An interviewer may read their own record, with `interviewer_id`-scoped ownership on reads and on the calibration and session lists.

Booking an interview session inside a cycle is a hiring-manager operation carrying `candidate_id`, `interviewer_id`, `guide_id`, `scheduled_start`, and `scheduled_end`, and it runs the longest gauntlet of checks in the system. In priority order: ownership of the parent requisition first; then the cycle's posture must be `ACTIVE` (frozen answering `ERR_CYCLE_FROZEN`, other wrong stages `ERR_CYCLE_NOT_ACTIVE`) and the candidate's assessment in that cycle must have reached `COMPLETED` (else `ERR_ASSESSMENT_NOT_COMPLETED`, HTTP 409); then the safety gate — the interviewer must hold a `CALIBRATED` calibration record for the cycle's pinned guide, else `ERR_INTERVIEWER_NOT_CALIBRATED` (HTTP 422); then the constraint tier — the session must last at least fifteen minutes and at most four hours (240 minutes) with `scheduled_end` strictly after `scheduled_start`, else `ERR_SESSION_DURATION_INVALID` (HTTP 400); the interviewer must not be double-booked, judged on half-open intervals so that a conflict exists exactly when the new session starts before an existing `SCHEDULED`, `COMPLETED`, or `SCORED` session of the same interviewer ends and ends after that existing session starts — a new session starting at the precise instant an existing one ends is adjacent and allowed — else `ERR_INTERVIEWER_DOUBLE_BOOKED` (HTTP 409); and the cycle's daily capacity, an aggregate rather than a pairwise rule, under which the count of the cycle's sessions falling on the UTC calendar day of the new `scheduled_start` with status `SCHEDULED`, `COMPLETED`, or `SCORED` must remain below `max_sessions_per_day`, the booking that would push the count past the cap being rejected with `ERR_CYCLE_DAILY_CAPACITY_EXCEEDED` (HTTP 409) even when it overlaps nothing; then the temporal gate — the session must fit inside the closed administration window, `scheduled_start` no earlier than `administration_window_start` and `scheduled_end` no later than `administration_window_end`, else `ERR_OUTSIDE_ADMINISTRATION_WINDOW`; and finally the version pin — the supplied `guide_id` must equal the cycle's pinned `guide_id`, else `ERR_GUIDE_VERSION_MISMATCH` (HTTP 422), which is how the system guarantees a cycle is scored against exactly the rubric it was created with. A booked session begins `SCHEDULED` with its `cycle_id` taken from the path, and the booking credits the interviewer's committed minutes by the session's duration.

Completing a session moves `SCHEDULED` → `COMPLETED`, requires the cycle `ACTIVE`, requires the logical now to be at or after `scheduled_end` — earlier is `ERR_SESSION_NOT_ENDED` (HTTP 422) — and stamps `completed_at`. Cancelling a session moves `SCHEDULED` → `CANCELLED` with a `cancellation_reason` of `MANUAL` for a direct manager cancellation, or `VENDOR_HOLD`, `CANDIDATE_WITHDRAWN`, or `CYCLE_CLOSED` when a cascade drives it, and always debits the committed minutes. `CANCELLED` is fully terminal. `SCORED` is terminal for scoring purposes but not for correction, as the scorecard lifecycle below shows.

Scorecards are authored per session. Creating one requires the session `COMPLETED` (else `ERR_SESSION_NOT_COMPLETED`, HTTP 409), the cycle in `ACTIVE` or `SCORING` posture, and the caller to be the session's own interviewer — the scorecard's `interviewer_id` and `candidate_id` are copied from the session, and ownership demands the session's `interviewer_id` equal `X-User-ID`. The payload carries `ratings` and an `overall_recommendation` of `STRONG_YES`, `YES`, `NO`, or `STRONG_NO`. The `ratings` array must contain at least one item (an empty array is `ERR_RATINGS_EMPTY`, HTTP 400); each item pairs a `competency_code` with a `rating`; every code must exist in the pinned guide's rubric and appear at most once within the scorecard (a foreign or duplicated code is `ERR_RATING_COMPETENCY_MISMATCH`, HTTP 400); and each `rating` is an integer from 1 up to that rubric item's `scale_max` (out of range is `ERR_RATING_OUT_OF_RANGE`, HTTP 400). Partial coverage is allowed — an interviewer may rate a subset of the rubric, and the composite renormalizes over the covered weights. A session carries at most one non-`VOIDED` scorecard; a second live scorecard is `ERR_DUPLICATE_SCORECARD` (HTTP 409). New scorecards are `DRAFT`.

Submitting is the author's own act and moves `DRAFT` → `SUBMITTED`. The source-state check is `ERR_SCORECARD_NOT_DRAFT` (HTTP 409) for anything not `DRAFT`; ownership requires the scorecard's `interviewer_id` to equal `X-User-ID`; the session must still be `COMPLETED`; the cycle must be `ACTIVE` or `SCORING`; and the logical now must be no later than seventy-two hours after the session's `completed_at` — the boundary is inclusive, and a submission later than that is `ERR_SCORECARD_WINDOW_CLOSED` (HTTP 422). Submission stamps `submitted_at` and computes the `weighted_total` as the sum, over the rated competencies, of each item's `weight` multiplied by its `rating` and divided by its `scale_max`, rounded half-up to four decimal places. Three side effects follow: the session moves `COMPLETED` → `SCORED`; the candidate assessment's `composite_score` is recomputed per the composite formula of §3.8; and the `calibration_index` is recomputed for the author's calibration record and for every other interviewer holding a `SUBMITTED` scorecard on the same candidate in the same cycle, since the panel means have shifted — any `CALIBRATED` record whose recomputed index falls below 0.5000 lapses.

Voiding is the compensation path and belongs to the compliance officer. The scorecard must be `SUBMITTED` (else `ERR_SCORECARD_NOT_SUBMITTED`, HTTP 409), no finalized hiring decision may yet exist for that candidate in that cycle (else `ERR_DECISION_ALREADY_FINALIZED`), and the officer supplies a `void_reason` of at least twenty characters (`ERR_INVALID_REQUEST`). Voiding stamps `voided_at`, stores the reason, moves the session `SCORED` → `COMPLETED`, recomputes the assessment's `composite_score` — which becomes null when no submitted scorecards remain and no `raw_score` is present, and otherwise re-runs the formula over the remaining submitted set — and recomputes the affected interviewers' calibration indices.

Calibration records bind an interviewer to a guide. An administrator creates one by naming a `guide_id`; the record starts `TRAINED` with `trained_at` stamped, and at most one record per interviewer-guide pair may be open — that is, in `TRAINED` or `CALIBRATED` — at a time, a duplicate drawing `ERR_DUPLICATE_CALIBRATION` (HTTP 409). Certification moves `TRAINED` → `CALIBRATED`, requires the guide to be `PILOT` or `APPROVED` (else `ERR_GUIDE_NOT_APPROVED`), and requires a `practice_score` of at least 0.7000 — the boundary is inclusive, exactly 0.7000 passes, anything below is `ERR_PRACTICE_SCORE_BELOW_THRESHOLD` (HTTP 422); certification stamps `certified_at` and stores the score. Lapse arrives by two roads: the logical clock moving strictly more than 365 days past `certified_at` (equality keeps the record `CALIBRATED`), or a recomputed `calibration_index` dropping below 0.5000. Retraining a `LAPSED` interviewer is modeled as creating a fresh calibration record for the same guide; the lapsed record remains queryable as history.

The `calibration_index` itself is a panel-deviation agreement index, null until the interviewer has at least one `SUBMITTED` scorecard on the record's guide. To compute it, consider every submitted, non-voided scorecard the interviewer has authored on sessions whose `guide_id` equals the record's guide, and within each, every rated competency. A competency contributes a deviation only when peers exist — other interviewers with submitted scorecards for the same candidate in the same cycle who rated that competency — in which case the deviation is the interviewer's `rating` minus the mean of the peers' ratings for that competency. With no such pairs at all, the index is null. Otherwise the mean of the absolute deviations over all pairs is taken, and the scale is the largest `scale_max` in the guide's rubric minus one. For a guide whose `scoring_mode` is `RAW`, the index is one minus the ratio of the mean absolute deviation to the scale, that ratio capped at one, rounded half-up to four decimal places. For `LENIENCY_ADJUSTED`, the same base index is multiplied by one minus half of a leniency term, where the leniency term is the absolute difference between the interviewer's own mean rating across the pairs and the cohort mean across all ratings in the pairs (the interviewer included), divided by the scale and capped at one; identical scorecard data therefore yields a strictly lower index whenever the interviewer drifts from the cohort mean. Every recompute applies the lapse side effect: a `CALIBRATED` record whose index falls below 0.5000 becomes `LAPSED`.

### 3.7. Adverse Impact Monitoring

A compliance officer computes and persists an adverse-impact snapshot for a cycle by supplying a `snapshot_type` of `PROVISIONAL` or `FINAL`. The cycle's posture must be `ACTIVE`, `SCORING`, `DECIDED`, or `FROZEN` — a snapshot against a cycle in any other posture is `ERR_CYCLE_NOT_ACTIVE`. The snapshot is immutable once computed, is stamped with the logical time as `computed_at`, and persists its full result in `group_breakdowns`, `highest_rate_group_code`, and `flagged`.

The computation walks the four disclosed groups — `GROUP_A`, `GROUP_B`, `GROUP_C`, and `GROUP_D`. The applicant set differs by variant: a `PROVISIONAL` snapshot counts a cycle's candidate assessments whose `admin_status` is `SCHEDULED`, `ACCOMMODATION_HOLD`, `IN_PROGRESS`, `COMPLETED`, or `NO_SHOW` (the `INVITED`, `CANCELLED`, and `PURGED` are excluded, since those candidates were never presented or were removed before presentation), while a `FINAL` snapshot counts only assessments whose `admin_status` is `COMPLETED`. Candidates whose `group_code` is `UNDISCLOSED` are excluded from every denominator and reported as a separate breakdown entry whose `excluded_reason` is `UNDISCLOSED`. Within each group, the breakdown entry records the group's `applicants` count and its `selected` count; for `PROVISIONAL` snapshots the selected count comprises finalized `ADVANCE` decisions plus — as projected selections for candidates not yet decided — completed assessments whose `composite_score` is at least 0.7000, while for `FINAL` snapshots only finalized `ADVANCE` decisions count.

Two pinned rules govern the arithmetic. First, any group with fewer than 2 applicants is excluded from comparison entirely: its `selection_rate` and `impact_ratio` are null and its `excluded_reason` is `INSUFFICIENT_N`. Second, rounding order is pinned — each included group's `selection_rate` is its `selected` divided by its `applicants`, rounded half-up to four decimal places first; the impact ratio then divides those already-rounded rates and is itself rounded half-up to four decimal places. Dividing unrounded values would yield different fourth-decimal results and is not the contract.

With per-group rates in hand, the highest selection rate among included groups anchors the comparison. The `highest_rate_group_code` is the group attaining that maximum, with ties broken toward the group with more `applicants` and further ties broken by ascending `group_code` lexicographic order — never by any identifier. When the maximum rate is exactly zero, every included group's `impact_ratio` is null with `excluded_reason` of `NO_SELECTIONS`, `flagged` is false, and `highest_rate_group_code` is null. Otherwise each included group's `impact_ratio` is its rounded `selection_rate` divided by the rounded maximum rate, rounded half-up to four decimals, and `flagged` is true exactly when some included group's `impact_ratio` is strictly below the four-fifths threshold of 0.8000 — an impact ratio of exactly 0.8000 does not flag the snapshot. Excluded groups carry null rates and ratios with their `excluded_reason` set; included groups carry a null `excluded_reason`.

The consequence of a flag depends on the variant and on configuration. A flagged `FINAL` snapshot taken while the cycle is `ACTIVE` or `SCORING` freezes the cycle — posture to `FROZEN`, `frozen_from_posture` capturing the prior posture, `frozen_reason` of `ADVERSE_IMPACT` — but only when the cycle's instrument has `adverse_impact_monitor_enabled` set to true; with monitoring disabled, a flagged final snapshot is recorded without disturbing the cycle. A cycle frozen for adverse impact can be unfrozen only once at least one `FINAL` snapshot exists for it, per the unfreeze gate in §3.4.

### 3.8. Composite Scores, Hiring Decisions, and Candidate Feedback

The candidate's `composite_score` blends the interview panel with the instrument result. Its inputs are the submitted, non-voided scorecards for that candidate within the same cycle whose sessions were run on the cycle's pinned guide — drafts and voided scorecards never contribute — together with the assessment's `raw_score` and the instrument's `pass_floor` and `max_score`. For each competency in the pinned guide's rubric, the ratings it received across those scorecards are averaged, the per-competency mean rounded half-up to four decimal places. The coverage is the sum of the rubric weights of competencies that received at least one rating; when coverage is zero the guide component is zero, and otherwise the guide component is the sum over rated competencies of each item's `weight` multiplied by its rounded mean and divided by its `scale_max`, all divided by the coverage — partial panels are thus renormalized over the covered weights only. The assessment component clamps the raw result into the unit interval: the `raw_score` minus `pass_floor`, divided by `max_score` minus `pass_floor`, forced to zero below and to one above. The composite is six-tenths of the guide component plus four-tenths of the assessment component, rounded half-up to four decimal places, and it is recomputed at assessment completion and again on every scorecard submission or void for the same candidate and cycle.

A decision officer documents the hiring decision for a candidate in a cycle by supplying the `candidate_id`, a `decision` of `ADVANCE`, `HOLD`, or `REJECT`, and a `rationale` of at least fifty characters (`ERR_RATIONALE_TOO_SHORT`, HTTP 400). The gates evaluate in priority order: the requisition must still be `OPEN` (`ERR_REQUISITION_NOT_OPEN`); the candidate's assessment in the cycle must be `COMPLETED` (`ERR_ASSESSMENT_NOT_COMPLETED`); segregation of duties forbids the officer's `X-User-ID` from equalling the `interviewer_id` of any submitted scorecard counted toward the candidate's quorum (`ERR_SEGREGATION_OF_DUTIES`); a second decision for the same candidate in the same cycle is `ERR_DECISION_ALREADY_FINALIZED`; and the quorum must be met (`ERR_QUORUM_NOT_MET`, HTTP 422) before the rationale length is even examined.

The quorum gate has a pinned evaluation order that matters exactly when scorecards are voided. First, the evaluated sessions are gathered: the candidate's interview sessions in the cycle whose status is `COMPLETED` or `SCORED` — note that voiding a scorecard reverts its session from `SCORED` back to `COMPLETED`, so the session remains in this set. Second, the required count is fixed as the larger of 2 and the smaller of 3 and the number of evaluated sessions. Third, the submitted count is taken: submitted, non-voided scorecards on those evaluated sessions. Fourth, the quorum is met exactly when the submitted count is at least the required count — an exact tie passes. Because the session set is fixed before the submitted count is read, voiding a scorecard shrinks the submitted count without shrinking the requirement, so a decision that was about to pass can become blocked without any session changing state.

A created decision is always `FINALIZED` — decisions are born final and never transition. The record captures the officer's `X-User-ID` as `decided_by_user_id`, a four-decimal snapshot of the assessment's `composite_score` as `composite_at_decision`, the required and submitted quorum counts as `quorum_required_at_decision` and `quorum_submitted_at_decision`, and the logical creation time as `finalized_at`. Its side effects ripple outward: the cycle's `decisions_finalized_count` increments; the assessment's `retention_expires_at` is anchored to `finalized_at` plus the requisition's `retention_days`; an `ADVANCE` decision increments the requisition's `filled_count` and, at the moment that count reaches `openings_count`, flips the requisition to `FILLED`; and when the decision completes the set — every `COMPLETED` assessment in a `SCORING` cycle now decided — the cycle advances automatically to `DECIDED`.

Candidate feedback is the last write in the lifecycle. Sending feedback moves the assessment's `feedback_status` from `NOT_SENT` to `SENT`; the parallel feedback dimension evolves independently of `admin_status`. Five preconditions guard it, evaluated in priority order: the assessment must be `COMPLETED` (`ERR_ASSESSMENT_NOT_COMPLETED`); the retention window must still be open, meaning `retention_expires_at` is either not yet set or the logical now is at or before it — exactly at expiry still passes, later is `ERR_RETENTION_EXPIRED` (HTTP 422); the `feedback_text` must be at least twenty characters (`ERR_FEEDBACK_TEXT_TOO_SHORT`, HTTP 400); the `feedback_status` must still be `NOT_SENT`, a second send drawing `ERR_FEEDBACK_ALREADY_SENT` (HTTP 409); and a finalized hiring decision must exist for that candidate in that cycle, else `ERR_DECISION_NOT_FINALIZED` (HTTP 409). The feedback dimension's other transition is automatic: when an assessment moves to `CANCELLED`, `NO_SHOW`, or `PURGED`, an unsent `feedback_status` becomes `NOT_APPLICABLE`, while feedback already `SENT` remains `SENT` even through a purge.

### 3.9. Retention and Score Purging

Retention runs on anchors. An assessment's `retention_expires_at` is its anchor plus the requisition's `retention_days`, where the anchor is the `finalized_at` of the candidate's finalized decision in that cycle when one exists, otherwise the cycle's `closed_at` once the cycle is `CLOSED`, and otherwise null — an assessment with no anchor is not yet purgeable. The two consumers of this timestamp compare it differently by design: the feedback gate is inclusive, permitting feedback at the exact expiry instant, while the purge gate is strict, purging only when the logical now is strictly later than `retention_expires_at` — at exact expiry the record is still retained.

The retention sweep is a compliance-officer capability that purges every candidate assessment meeting three conditions: `admin_status` of `COMPLETED`, a non-null `retention_expires_at`, and a logical now strictly beyond it. Each purged assessment moves `COMPLETED` → `PURGED`; its `raw_score`, `composite_score`, and `completed_at` are nulled and `purged_at` is stamped; an unsent `feedback_status` flips to `NOT_APPLICABLE` while a sent one is untouched. The purge then redacts the interview record: every scorecard for that candidate in that cycle has `redacted` (initially false on every scorecard) set to true, its `ratings` and `weighted_total` nulled, and its `version` incremented. A retention purge event is appended per purged assessment, recording the assessment's `id` as `candidate_assessment_id`, the `event_type` of `ASSESSMENT_PURGED`, the executing officer's `X-User-ID` as `executed_by_user_id`, and an audit copy of the assessment's `retention_expires_at` at purge time as `retention_expires_at_snapshot`; these events remain queryable through the assessment's purge-events list after the purge. Finally, the cycle's `active_candidate_count` decrements by one for each purged assessment. The sweep responds with a summary object carrying `purged_count` and the array `purged_assessment_ids`.

## 4. Endpoint Definitions

All endpoints live under the `/talent` prefix. Endpoints that create a new resource respond with HTTP 201 and the created resource; all other successful operations — reads, updates, state transitions, and action invocations — respond with HTTP 200 and the affected resource (or the summary object where one is defined). Request payloads, preconditions, and side effects for each operation are specified in §2 and §3; this table is the routing index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /talent/vendors | Register an assessment vendor | TalentAssessmentAdmin |
| GET | /talent/vendors/{id} | Read a vendor, including the content ledger balance | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative |
| GET | /talent/vendors/{id}/instruments | List the instruments of a vendor | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative, HiringManager |
| GET | /talent/vendors/{id}/content-ledger-events | List the content ledger events of a vendor | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative |
| POST | /talent/vendors/{id}/suspend | Suspend a vendor, cascading to instruments, cycles, and sessions | TalentAssessmentAdmin |
| POST | /talent/vendors/{id}/reinstate | Reinstate a suspended vendor, unfreezing vendor-hold cycles | TalentAssessmentAdmin |
| POST | /talent/vendors/{id}/terminate | Terminate a vendor once its content ledger has settled | TalentAssessmentAdmin |
| POST | /talent/vendors/{id}/content-ledger-events | Append a content chain-of-custody event | TalentAssessmentAdmin, VendorRepresentative |
| POST | /talent/instruments | Register an instrument under a vendor | TalentAssessmentAdmin |
| GET | /talent/instruments | List instruments, with filters | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative, HiringManager |
| GET | /talent/instruments/{id} | Read an instrument | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative, HiringManager |
| POST | /talent/instruments/{id}/submit-validation-review | Move an instrument from DRAFT to VALIDATION_REVIEW | TalentAssessmentAdmin |
| POST | /talent/instruments/{id}/validate | Move an instrument from VALIDATION_REVIEW or REVALIDATION to VALIDATED | TalentAssessmentAdmin |
| POST | /talent/instruments/{id}/begin-revalidation | Move an EXPIRED instrument to REVALIDATION | TalentAssessmentAdmin |
| POST | /talent/instruments/{id}/retire | Retire an instrument while no non-CLOSED cycle references it | TalentAssessmentAdmin |
| POST | /talent/instruments/{id}/evidence | File validation evidence for an instrument | TalentAssessmentAdmin, VendorRepresentative |
| GET | /talent/instruments/{id}/evidence | List the evidence of an instrument | TalentAssessmentAdmin, ComplianceOfficer, VendorRepresentative |
| POST | /talent/interview-guides | Create a root interview guide in DRAFT | TalentAssessmentAdmin |
| POST | /talent/interview-guides/{id}/revisions | Create a revision guide superseding the APPROVED guide {id} | TalentAssessmentAdmin |
| GET | /talent/interview-guides | List interview guides, with filters | TalentAssessmentAdmin, HiringManager, Interviewer, ComplianceOfficer, DecisionOfficer |
| GET | /talent/interview-guides/{id} | Read an interview guide | TalentAssessmentAdmin, HiringManager, Interviewer, ComplianceOfficer, DecisionOfficer |
| POST | /talent/interview-guides/{id}/pilot | Move a guide from DRAFT to PILOT | TalentAssessmentAdmin |
| POST | /talent/interview-guides/{id}/retract | Move a guide from PILOT back to DRAFT | TalentAssessmentAdmin |
| POST | /talent/interview-guides/{id}/approve | Move a guide from PILOT to APPROVED, retiring any superseded head | TalentAssessmentAdmin |
| POST | /talent/interview-guides/{id}/retire | Retire a guide while no non-CLOSED cycle pins it | TalentAssessmentAdmin |
| POST | /talent/requisitions | Create a requisition owned by the calling manager | HiringManager |
| GET | /talent/requisitions/{id} | Read a requisition | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer |
| POST | /talent/requisitions/{id}/close | Close a requisition once all its cycles are CLOSED | HiringManager |
| POST | /talent/requisitions/{id}/cycles | Create an assessment cycle pinning an instrument and a guide | HiringManager |
| GET | /talent/cycles | List assessment cycles, with filters | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, Interviewer |
| GET | /talent/cycles/{id} | Read a cycle, including posture and computed counts | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, Interviewer |
| PATCH | /talent/cycles/{id} | Update a SETUP cycle's window, capacity, or pins; OCC-guarded | HiringManager |
| POST | /talent/cycles/{id}/activate | Move a cycle from SETUP to ACTIVE through the cross-entity gates | HiringManager |
| POST | /talent/cycles/{id}/freeze | Freeze a cycle from SETUP, ACTIVE, or SCORING | ComplianceOfficer |
| POST | /talent/cycles/{id}/unfreeze | Return a FROZEN cycle to its captured posture | ComplianceOfficer |
| POST | /talent/cycles/{id}/begin-scoring | Move a cycle from ACTIVE to SCORING once no sessions remain scheduled | HiringManager |
| POST | /talent/cycles/{id}/close | Close a cycle from any non-terminal posture, cascading cancellations | HiringManager |
| POST | /talent/cycles/{id}/invitations | Invite a candidate into a cycle | HiringManager |
| POST | /talent/cycles/{id}/sessions | Book a structured interview session in a cycle | HiringManager |
| POST | /talent/cycles/{id}/decisions | Record a finalized hiring decision after the quorum gates | DecisionOfficer |
| POST | /talent/cycles/{id}/adverse-impact-snapshots | Compute and persist an adverse-impact snapshot | ComplianceOfficer |
| GET | /talent/cycles/{id}/adverse-impact-snapshots | List the snapshots of a cycle | ComplianceOfficer, TalentAssessmentAdmin, HiringManager |
| POST | /talent/candidates | Register a candidate | HiringManager, TalentAssessmentAdmin |
| GET | /talent/candidates/{id} | Read a candidate | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, Candidate |
| POST | /talent/candidates/{id}/withdraw | Withdraw a candidate, cascading cancellations | Candidate, HiringManager |
| GET | /talent/assessments | List candidate assessments, with filters | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, Candidate |
| GET | /talent/assessments/{id} | Read a candidate assessment | HiringManager, TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, Candidate |
| POST | /talent/assessments/{id}/schedule | Move an assessment from INVITED to SCHEDULED | HiringManager |
| POST | /talent/assessments/{id}/start | Move an assessment from SCHEDULED to IN_PROGRESS | HiringManager |
| POST | /talent/assessments/{id}/complete | Move an assessment from IN_PROGRESS to COMPLETED with its raw score | HiringManager |
| POST | /talent/assessments/{id}/mark-no-show | Move a SCHEDULED assessment to NO_SHOW | HiringManager |
| POST | /talent/assessments/{id}/cancel | Cancel a non-terminal assessment, cascading sessions and accommodations | HiringManager, Candidate |
| POST | /talent/assessments/{id}/reschedule | Move an assessment from ACCOMMODATION_HOLD back to SCHEDULED | HiringManager |
| POST | /talent/assessments/{id}/feedback | Send candidate feedback | HiringManager |
| POST | /talent/assessments/{id}/accommodation-requests | File an accommodation request on one's own assessment | Candidate |
| GET | /talent/assessments/{id}/accommodation-requests | List the accommodation requests of an assessment | Candidate, ComplianceOfficer, HiringManager, TalentAssessmentAdmin |
| GET | /talent/assessments/{id}/purge-events | List the retention purge events of an assessment | ComplianceOfficer, TalentAssessmentAdmin |
| GET | /talent/accommodation-requests/{id} | Read an accommodation request | ComplianceOfficer, Candidate, HiringManager, TalentAssessmentAdmin |
| POST | /talent/accommodation-requests/{id}/approve | Approve a PENDING accommodation request | ComplianceOfficer |
| POST | /talent/accommodation-requests/{id}/deny | Deny a PENDING accommodation request | ComplianceOfficer |
| POST | /talent/accommodation-requests/{id}/withdraw | Withdraw one's own PENDING accommodation request | Candidate |
| POST | /talent/interviewers | Register an interviewer | TalentAssessmentAdmin |
| GET | /talent/interviewers/{id} | Read an interviewer, including committed minutes | TalentAssessmentAdmin, Interviewer, HiringManager, ComplianceOfficer |
| POST | /talent/interviewers/{id}/calibrations | Create a TRAINED calibration record for a guide | TalentAssessmentAdmin |
| GET | /talent/calibrations | List calibration records, with filters | TalentAssessmentAdmin, Interviewer, ComplianceOfficer, HiringManager |
| GET | /talent/calibrations/{id} | Read a calibration record, including its computed index | TalentAssessmentAdmin, Interviewer, ComplianceOfficer, HiringManager |
| POST | /talent/calibrations/{id}/certify | Move a calibration record from TRAINED to CALIBRATED | TalentAssessmentAdmin |
| GET | /talent/sessions | List interview sessions, with filters | TalentAssessmentAdmin, HiringManager, Interviewer, ComplianceOfficer, DecisionOfficer, Candidate |
| GET | /talent/sessions/{id} | Read an interview session | TalentAssessmentAdmin, HiringManager, Interviewer, ComplianceOfficer, DecisionOfficer, Candidate |
| POST | /talent/sessions/{id}/complete | Move a session from SCHEDULED to COMPLETED at or after its end | HiringManager |
| POST | /talent/sessions/{id}/cancel | Cancel a SCHEDULED session | HiringManager |
| POST | /talent/sessions/{id}/scorecards | Create a DRAFT scorecard for a COMPLETED session | Interviewer |
| GET | /talent/scorecards | List scorecards, with filters | TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, HiringManager, Interviewer |
| GET | /talent/scorecards/{id} | Read a scorecard | TalentAssessmentAdmin, ComplianceOfficer, DecisionOfficer, HiringManager, Interviewer |
| POST | /talent/scorecards/{id}/submit | Submit a DRAFT scorecard within its submission window | Interviewer |
| POST | /talent/scorecards/{id}/void | Void a SUBMITTED scorecard before any finalized decision | ComplianceOfficer |
| GET | /talent/decisions | List hiring decisions, with filters | DecisionOfficer, HiringManager, ComplianceOfficer, TalentAssessmentAdmin, Candidate |
| GET | /talent/decisions/{id} | Read a hiring decision | DecisionOfficer, HiringManager, ComplianceOfficer, TalentAssessmentAdmin, Candidate |
| GET | /talent/adverse-impact-snapshots/{id} | Read a persisted adverse-impact snapshot | ComplianceOfficer, TalentAssessmentAdmin |
| POST | /talent/retention-sweeps | Purge every assessment past its retention deadline | ComplianceOfficer |
| POST | /talent/_clock/set_current_utc | Advance the logical clock, materializing due automatic transitions | TalentAssessmentAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are specified in the workflow narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_ENTITY_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_CYCLE_NOT_ACTIVE | 409 |
| ERR_CYCLE_FROZEN | 409 |
| ERR_REQUISITION_NOT_OPEN | 409 |
| ERR_CYCLE_NOT_CLOSED | 409 |
| ERR_CANDIDATE_WITHDRAWN | 409 |
| ERR_ASSESSMENT_NOT_COMPLETED | 409 |
| ERR_SESSION_NOT_COMPLETED | 409 |
| ERR_SESSION_NOT_ENDED | 422 |
| ERR_SESSIONS_STILL_SCHEDULED | 409 |
| ERR_SCORECARD_NOT_DRAFT | 409 |
| ERR_SCORECARD_NOT_SUBMITTED | 409 |
| ERR_ACCOMMODATION_NOT_PENDING | 409 |
| ERR_FEEDBACK_ALREADY_SENT | 409 |
| ERR_DECISION_NOT_FINALIZED | 409 |
| ERR_DECISION_ALREADY_FINALIZED | 409 |
| ERR_STALE_CYCLE_VERSION | 412 |
| ERR_STALE_GUIDE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_INTERVIEWER_NOT_CALIBRATED | 422 |
| ERR_VENDOR_NOT_ACTIVE | 422 |
| ERR_INSTRUMENT_NOT_VALIDATED | 422 |
| ERR_GUIDE_NOT_APPROVED | 422 |
| ERR_GUIDE_PINNED | 409 |
| ERR_GUIDE_VERSION_MISMATCH | 422 |
| ERR_ADVERSE_IMPACT_UNRESOLVED | 422 |
| ERR_DUPLICATE_INSTRUMENT_CODE | 409 |
| ERR_DUPLICATE_CANDIDATE_REF | 409 |
| ERR_DUPLICATE_INVITATION | 409 |
| ERR_DUPLICATE_SCORECARD | 409 |
| ERR_DUPLICATE_CALIBRATION | 409 |
| ERR_PENDING_ACCOMMODATION_EXISTS | 409 |
| ERR_RUBRIC_WEIGHT_SUM | 400 |
| ERR_RUBRIC_TOO_FEW_ITEMS | 400 |
| ERR_RATINGS_EMPTY | 400 |
| ERR_RATING_COMPETENCY_MISMATCH | 400 |
| ERR_RATING_OUT_OF_RANGE | 400 |
| ERR_SCORE_OUT_OF_RANGE | 400 |
| ERR_SESSION_DURATION_INVALID | 400 |
| ERR_WINDOW_ORDER_INVALID | 400 |
| ERR_EXTENSION_OUT_OF_RANGE | 400 |
| ERR_RATIONALE_TOO_SHORT | 400 |
| ERR_FEEDBACK_TEXT_TOO_SHORT | 400 |
| ERR_INTERVIEWER_DOUBLE_BOOKED | 409 |
| ERR_CYCLE_DAILY_CAPACITY_EXCEEDED | 409 |
| ERR_QUORUM_NOT_MET | 422 |
| ERR_CONTENT_LEDGER_NEGATIVE | 422 |
| ERR_CONTENT_COPIES_OUTSTANDING | 422 |
| ERR_OUTSIDE_ADMINISTRATION_WINDOW | 422 |
| ERR_SCORECARD_WINDOW_CLOSED | 422 |
| ERR_RETENTION_EXPIRED | 422 |
| ERR_EVIDENCE_TYPE_MISSING | 422 |
| ERR_EVIDENCE_EXPIRED | 422 |
| ERR_PRACTICE_SCORE_BELOW_THRESHOLD | 422 |

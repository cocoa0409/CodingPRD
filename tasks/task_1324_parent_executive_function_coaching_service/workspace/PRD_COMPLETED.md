# Parent Executive Function Coaching API — Product Requirements Document

## 1. Introduction

A parent and executive-function coaching practice serving students with ADHD and related needs operates on a delicate chain of trust: a household enrolls, a student is assessed, a coach drafts a plan, the family accepts it, sessions are delivered against prepaid credit packages, and — only with the family's explicit, scoped consent — progress is coordinated with teachers and clinicians. Between sessions, accountability check-ins keep momentum; over time, progress snapshots decide whether the plan is working or needs revision. Behind the scenes, the practice must enforce coach caseload caps and supervision ratios, run cancellation and no-show policies that convert missed sessions into fees, and keep every family's ledger internally consistent to the cent.

This document specifies the API that backs that practice. It defines the household account (Family) as the billing and consent anchor, the Client (student) as the subject of coaching, the CoachingPlan as the unit of clinical work, and the Package as the prepaid instrument that funds individual sessions and group workshops. It also defines the practice's governance layer: supervision records that gate whether a coach may accept new plans, a logical clock that every deadline and window reads, and a daily operations sweep that expires packages, lapses check-ins, expires consents, and recomputes supervisory posture.

Readers should treat §2 as the system's fixed contract — envelopes, pagination, identifiers, concurrency, precision, and cross-cutting governance — and §3 as the narrative workflow layer where business rules live in context. §4 and §5 provide the endpoint and error catalogues; the trigger conditions for each error are intentionally distributed through §2 and §3 rather than repeated in the catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `PracticeAdmin`, `Coach`, `FamilyMember`, and `ExternalContact`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role, and this binding drives every ownership check in the system:

- When `X-User-Role` is `PracticeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`; a practice administrator enjoys a superset of visibility across all resources.
- When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; ownership checks on any resource that references a `Coach` compare the resource's coach foreign-key field — a plan's `coach_id`, a session's `coach_id`, a note's `author_coach_id`, or a supervision record's `supervisor_coach_id`, as the relevant transition requires — to `X-User-ID`.
- When `X-User-Role` is `FamilyMember`, `X-User-ID` is the `id` of the acting `Family`; ownership checks compare the path family's `id`, or the `family_id` of the family that owns the path resource, to `X-User-ID`.
- When `X-User-Role` is `ExternalContact`, `X-User-ID` is the `id` of the acting `CoordinationContact`; the caller may only read the shared-notes view of its own contact record.

A caller passing authentication and role checks but failing one of these entity-backed ownership comparisons is rejected with `ERR_FORBIDDEN_SCOPE`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both parameters may be omitted independently.

Unless an endpoint states otherwise, every list is sorted by `created_at` in ascending order. Because every timestamp reads the logical clock of §2.4, records created between clock advances share an identical `created_at`; wherever this document orders records by creation — every list response and every rule in §3 that speaks of creation order, of the earliest-created record, or of the record created last — such `created_at` ties are broken by insertion sequence: the record the server stored first counts as the earlier-created one. The `meta` object of a list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Operations Sweep

All time-dependent behavior in the system — deadlines, expiry instants, cancellation notice windows, rolling measurement windows, and the thirty-day supervision window — reads a single server-side logical clock, never wall-clock time. At startup, before any administrative intervention, the logical clock holds exactly `2026-08-01T00:00:00Z`; it must not silently fall back to real time. A `PracticeAdmin` may advance the clock through an admin-only test-driving capability that sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; this mutation touches no entity, but every subsequent read and sweep evaluates time-dependent rules against the new instant.

A second administrative capability runs the practice's daily operations sweep as a single ordered checkpoint. The sweep executes six steps in a fixed sequence: first, every `ACTIVE` package whose expiry instant has been reached or passed is moved to `EXPIRED` if it still holds remaining credits, or to `EXHAUSTED` if none remain; second, every check-in still `PENDING` whose grace window has fully elapsed is moved to `MISSED` and the owning client's streak is reset; third, every `ACTIVE` consent grant whose expiry has been reached is moved to `EXPIRED` with its note-sealing cascade; fourth, every coach's supervision posture is recomputed; fifth, every plan posture is recomputed; sixth, every family's billing status is recomputed. The sweep returns a summary with `packages_expired`, `packages_exhausted`, `checkins_missed`, `consents_expired`, and `coaches_recomputed` counts. Each entity the sweep mutates has its own `version` incremented and its `updated_at` refreshed.

### 2.5. Common Resource Properties

Every primary resource — Family, Client, Coach, IntakeAssessment, CoachingPlan, Goal, Package, Session, CheckIn, CoordinationContact, ConsentGrant, CoordinationNote, Workshop, WorkshopEnrollment, and SupervisionRecord — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations driven by cascades and sweeps.

The one exception is the ProgressSnapshot, an append-only measurement record: it carries `id` and `created_at` only. Both `updated_at` and `version` are absent from snapshots, because a snapshot is never mutated after it is written.

### 2.6. Monetary Precision and the Family Ledger

All monetary values are integer cents. Every rounding step in the system uses the round-half-up method, and every monetary result is stored as an integer number of cents; no field ever carries fractional cents. Where a formula multiplies a rounded intermediate (for example, a rounded per-unit rate) by a quantity, the multiplication operates on the already-rounded integer.

Each Family maintains four lifetime ledger counters, all initialized to zero at account creation and recomputed as money moves: `total_charged_cents` (package purchases, cancellation and no-show fees, and money-billed workshop enrollments), `total_refunded_cents` (package refunds and workshop money refunds), and `total_paid_cents` (payments received from the family). The fourth counter is derived: the family's `outstanding_balance_cents` must always equal its `total_charged_cents` minus its `total_refunded_cents` minus its `total_paid_cents`. This identity, known as INV-MONEY, is an invariant the server re-establishes after every ledger mutation; it is never permitted to drift.

From the outstanding balance the system derives the family's `billing_status`, which takes one of two values, `CURRENT` or `DELINQUENT`. The family is `DELINQUENT` if and only if its `outstanding_balance_cents` is strictly greater than 20000 cents; an outstanding balance of exactly 20000 cents remains `CURRENT`. The delinquency status is recomputed after every ledger mutation, but the automatic suspension consequence is deliberately narrow: only a cancellation-fee or no-show-fee charge can trigger it. When such a fee leaves the family's outstanding balance strictly above 20000 cents and the family is `ACTIVE`, the family is automatically moved to `SUSPENDED`, and every `ACTIVE` coaching plan of every client of the family has its posture recomputed to `SCHEDULING_BLOCKED`. Package purchases and workshop money charges are prepaid and never trigger auto-suspension on their own.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, because each of them legitimately destroys prior work and therefore must not be executed from a stale view.

Creating a coaching plan for a client requires the request body to carry `expected_client_version`, holding the `version` of the Client as the caller last observed it. If another writer has advanced the client's `version` since that observation — for any reason — the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412). The guard exists because plan creation supersedes the client's existing non-terminal plans, so a writer holding a stale view of the client must re-read before drafting.

Creating a consent grant for a family requires the request body to carry `expected_family_version`, holding the `version` of the Family as the caller last observed it. A mismatch with the family's current `version` is rejected with `ERR_STALE_FAMILY_VERSION` (HTTP 412). The guard exists because creating a consent for a contact that already holds a non-terminal grant supersedes that grant and seals notes shared under it.

No other endpoint accepts a version field; optimistic concurrency applies only to these two creation paths.

### 2.8. Nested Resource Retrieval and Validation Priority

The API is mounted under the `/api` prefix. Many resources are addressed through nested paths — a client beneath a family, a session beneath a plan. For any such request the system validates identifiers sequentially, left to right: the first path identifier that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no further identifiers or body-referenced ids are examined. Body-referenced ids (such as a `coach_id`, `intake_id`, `package_id`, or `contact_id` supplied in a payload) are likewise checked for existence.

When several validation rules could reject the same request, the server evaluates them in a strict priority order, and the first failure wins — later checks never mask earlier ones. The order is: authentication headers first (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then entity-backed ownership (`ERR_FORBIDDEN_SCOPE`); then existence of every path and body-referenced id, left to right (`ERR_NOT_FOUND`); then request shape — required fields present, enum members valid, ranges valid (`ERR_VALIDATION`); then the two optimistic-concurrency checks (`ERR_STALE_CLIENT_VERSION` before `ERR_STALE_FAMILY_VERSION`); then the family status gate (`ERR_FAMILY_NOT_ACTIVE`); then the client status gate (`ERR_CLIENT_NOT_ACTIVE`); then the plan status gate (`ERR_PLAN_NOT_ACTIVE`); then intake approval (`ERR_INTAKE_NOT_APPROVED`); then package status (`ERR_PACKAGE_NOT_ACTIVE`); then workshop status (`ERR_WORKSHOP_NOT_OPEN`); then the generic state-machine from-state rule (`ERR_INVALID_STATE`); then the aggregate state gates (for example `ERR_GOALS_NOT_RESOLVED`, `ERR_PLAN_HAS_OPEN_SESSIONS`, `ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES`, `ERR_CLIENT_HAS_ACTIVE_PLAN`, `ERR_COACH_HAS_ACTIVE_PLANS`, `ERR_FAMILY_DELINQUENT`, `ERR_FAMILY_NO_CLIENTS`, `ERR_PACKAGE_NOT_REFUNDABLE`, `ERR_ENROLLMENT_NOT_DROPPABLE`, `ERR_CONSENT_EXPIRED`); then consent existence (`ERR_CONSENT_NOT_ACTIVE`) followed by consent scope coverage (`ERR_CONSENT_SCOPE_INSUFFICIENT`); then cadence windows (`ERR_CADENCE_WINDOW_VIOLATION`); then temporal rules (`ERR_SESSION_IN_PAST` and its siblings); then coach schedule conflicts (`ERR_COACH_DOUBLE_BOOKED` and `ERR_COACH_BUFFER_CONFLICT`); then credential and segregation rules (`ERR_CREDENTIAL_INSUFFICIENT`, `ERR_SELF_SUPERVISION`, `ERR_DUPLICATE_ENROLLMENT`); then referential linkage (`ERR_CONTACT_NOT_LINKED`, `ERR_INTAKE_CLIENT_MISMATCH`, `ERR_TRACK_MISMATCH`); then credit availability (`ERR_NO_CREDITS_AVAILABLE`); then caseload capacity (`ERR_CASELOAD_CAP_REACHED`); and finally the supervision-deficit gate (`ERR_COACH_SUPERVISION_DEFICIT`).

Within this ordering, a state transition requested for a from-state the machine does not permit — including any write against a terminal state — is rejected with `ERR_INVALID_STATE`.

### 2.9. Coach Caseloads and Supervision Governance

The practice segregates clinical oversight from plan delivery. Every coach holds a `credential_level` of `ASSOCIATE`, `CERTIFIED`, or `SUPERVISOR`, and the level determines two capacities. A coach's `caseload_cap` is 12 for an `ASSOCIATE`, 20 for a `CERTIFIED` coach, and 28 for a `SUPERVISOR`. A coach's `active_caseload` is the count of coaching plans with status `ACTIVE` naming that coach; it is recomputed by the system whenever a plan is accepted, completed, terminated, or superseded.

Supervision is tracked on SupervisionRecord rows. A supervision record names a `supervisor_coach_id` that must differ from the supervisee's `coach_id` — an attempt to make a coach their own supervisor is rejected with `ERR_SELF_SUPERVISION` — and the named supervisor must hold `credential_level` `SUPERVISOR`, otherwise the creation is rejected with `ERR_CREDENTIAL_INSUFFICIENT`. Records move from `SCHEDULED` to `HELD` only at the hand of the named supervisor (segregation of duties: the supervisee cannot mark their own record), and from `HELD` to `VERIFIED` only at the hand of a `PracticeAdmin`; either non-terminal state may instead be moved to `CANCELLED` by a `PracticeAdmin`. Verification stamps `verified_at` and anchors the rolling thirty-day window.

The supervision requirement is recomputed in a pinned, non-circular order whenever a plan is accepted, completed, terminated, or superseded, whenever a record is verified, whenever the daily sweep slides the window, and whenever a coach is reactivated. First the system counts `active_caseload`; then it derives `required_supervision_hours` as the whole-hour floor of the caseload divided by the credential's divisor — 2 for an `ASSOCIATE`, 4 for a `CERTIFIED` coach, 6 for a `SUPERVISOR`; then it sums `verified_supervision_hours_30d`, the hours of records in `VERIFIED` status whose `verified_at` falls within the inclusive window from thirty days before now through now; finally it compares the two. When the verified hours are strictly less than the required hours, an `AVAILABLE` coach flips to `SUPERVISION_DEFICIT`; when the deficit clears, a `SUPERVISION_DEFICIT` coach returns to `AVAILABLE`. Crucially, the deficit gates only new plan acceptance: plans already `ACTIVE` under a deficit coach keep running, and posture recomputation never blocks scheduling on the deficit alone. Acceptance of a new plan while the coach sits in `SUPERVISION_DEFICIT` is rejected with `ERR_COACH_SUPERVISION_DEFICIT`; acceptance when the coach's `active_caseload` has reached or exceeded the `caseload_cap` is rejected with `ERR_CASELOAD_CAP_REACHED` — at exactly the cap is a rejection, since the caseload must be strictly below the cap.

A `PracticeAdmin` may move a coach to `INACTIVE` only when the coach's `active_caseload` is zero, failing which the request is rejected with `ERR_COACH_HAS_ACTIVE_PLANS`; deactivation triggers a posture recompute for the coach's `DRAFT` and `PROPOSED` plans. Reactivating an `INACTIVE` coach back to `AVAILABLE` immediately re-runs the supervision requirement, so the coach may flip straight into `SUPERVISION_DEFICIT`.

### 2.10. Consent and Confidentiality Model

Coordination with schools and clinicians is governed by explicit, scoped consent. A `CoordinationNote` carries a `topic` from a three-tier sensitivity ladder: `PROGRESS`, `GOALS`, or `PLAN_DETAIL`. A `ConsentGrant` carries a `scope` from a matching ladder: `PROGRESS_ONLY` covers notes whose topic is `PROGRESS`; `GOALS_AND_PROGRESS` covers notes with topic `PROGRESS` or `GOALS`; `FULL_PLAN` covers all three topics. Sharing a note therefore requires three things, each with its own rejection: an `ACTIVE` consent grant must exist pairing the note's client's family with the target contact (`ERR_CONSENT_NOT_ACTIVE` when none exists); the grant's scope must cover the note's topic per the ladder (`ERR_CONSENT_SCOPE_INSUFFICIENT`); and the contact must belong to the same family as the note's client (`ERR_CONTACT_NOT_LINKED`). The grant and the note must also both be in the right states — the note must be `FINALIZED` and the contact must be `ACTIVE`, else `ERR_INVALID_STATE`.

When the consent covering a share leaves `ACTIVE` — revoked by the family, expired by the sweep, superseded by a fresh grant, or destroyed by contact deactivation or family closure — every note shared under it is moved to `SEALED`, the terminal state, and immediately disappears from the external contact's shared-notes view.

## 3. Business Logic & Workflows

### 3.1. Household Onboarding, Family Lifecycle, and the Ledger

A practice administrator opens an account by creating a Family with an `account_name` and a `primary_email`; the household begins in `INTAKE` status with all four ledger counters at zero. Students are then registered under the household: creating a Client requires a `full_name`, a `date_of_birth`, and a coaching `track` of `INDIVIDUAL`, `GROUP`, or `HYBRID`, and the client also begins in `INTAKE`. The family's `id` binds every child resource back to the household — the client record's `family_id`, and later every package, contact, and consent.

Moving a family from `INTAKE` to `ACTIVE` is an administrator action with one precondition: at least one client must exist under the family, or the transition is rejected with `ERR_FAMILY_NO_CLIENTS`. Activation, like every family transition, increments the family's `version` by one. From `ACTIVE`, an administrator may suspend the family (moving it to `SUSPENDED`), which forces a posture recompute that drives every `ACTIVE` plan of every client of the family to `SCHEDULING_BLOCKED`; the system may also suspend the family automatically when a cancellation or no-show fee pushes the outstanding balance over the delinquency line, per §2.6. Reinstating a `SUSPENDED` family to `ACTIVE` requires the family's `outstanding_balance_cents` to be no more than 20000 cents — a balance strictly above the threshold is rejected with `ERR_FAMILY_DELINQUENT` — and reinstatement recomputes the posture of all `ACTIVE` plans of the family's clients.

Closing a family is permitted from either `ACTIVE` or `SUSPENDED`, but only when the household carries no live commitments: no coaching plan of any client may be `ACTIVE`, no package may be `ACTIVE`, and no workshop enrollment of any client may be `ENROLLED` or `WAITLISTED`. Any violation is rejected with `ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES`. The closure cascade is deep: every client in `INTAKE`, `ACTIVE`, or `PAUSED` is discharged to `DISCHARGED`; every `ACTIVE` coordination contact is deactivated to `INACTIVE`; every consent grant in `PENDING_SIGNATURE` or `ACTIVE` is moved to `REVOKED`, and notes in `SHARED` status under those grants are sealed.

A family pays down its balance by recording a payment of `amount_cents` through the family's payment capability, a `FamilyMember` action. The payment adds to `total_paid_cents`, recomputes the outstanding balance and `billing_status`, and increments the family's `version` by one. A payment may clear `DELINQUENT` back to `CURRENT`, but it never un-suspends the family — only the administrator's explicit reinstatement transition does that.

Clients themselves have a small lifecycle. A client moves from `INTAKE` to `ACTIVE` automatically the first time one of its plans is accepted. An administrator may pause an `ACTIVE` client to `PAUSED`, which recomputes the posture of the client's `ACTIVE` plan to `SCHEDULING_BLOCKED`, and may resume a `PAUSED` client back to `ACTIVE` provided the family is `ACTIVE` — otherwise `ERR_FAMILY_NOT_ACTIVE` — again recomputing the plan's posture. Discharge, moving a client from `ACTIVE` or `PAUSED` to the terminal `DISCHARGED`, is refused while any plan of the client remains `ACTIVE` (`ERR_CLIENT_HAS_ACTIVE_PLAN`); on discharge, every session of the client's plans still in `SCHEDULED` attendance is moved to `CANCELLED_EARLY` with its billing moved to `RETURNED`, and each affected package's `reserved_count` is decremented by one per released session, releasing the reservations.

### 3.2. Intake Assessment and the Revision Loop

Before any plan exists, the family completes an intake assessment for the student. Creating an IntakeAssessment takes the family's `presenting_concerns` in free text and a `baseline_score`, an executive-function score between 0 and 100 inclusive; a score outside that range is rejected with `ERR_VALIDATION`. The assessment starts in `DRAFT`.

The workflow is a supervised cycle. A family member moves the assessment from `DRAFT` to `SUBMITTED`, which requires `presenting_concerns` to be non-empty and `baseline_score` to be present, failing which the submission is rejected with `ERR_VALIDATION`. A coach then moves it from `SUBMITTED` to `UNDER_REVIEW`. From review there are two exits. Approval — the transition to the terminal `APPROVED` state — may only be performed by a coach holding `credential_level` `CERTIFIED` or `SUPERVISOR`; an `ASSOCIATE` attempting approval is rejected with `ERR_CREDENTIAL_INSUFFICIENT`. Alternatively, the coach may send the assessment back by moving it to `NEEDS_REVISION`, a transition that requires the coach to supply `review_notes`; the notes are stored on the assessment. The family then moves a `NEEDS_REVISION` assessment back to `DRAFT` to edit and resubmit; the `review_notes` are retained for the family's reference, and the cycle may repeat without limit.

### 3.3. Coaching Plans: Drafting, Acceptance, and Supersession

A coach begins a plan for a client by supplying the `coach_id` of the plan's primary coach, an `intake_id` referencing the assessment that justifies the work, a `cadence` of `WEEKLY` or `BIWEEKLY`, and the OCC field `expected_client_version` described in §2.7. Creation enforces a chain of guards: the client must not be `DISCHARGED`; the referenced intake must belong to the same client as the path — a mismatch is rejected with `ERR_INTAKE_CLIENT_MISMATCH` — and must already be `APPROVED`, else `ERR_INTAKE_NOT_APPROVED`; the named coach must not be `INACTIVE`, else `ERR_INVALID_STATE`. The new plan starts in `DRAFT` and is stamped with a `revision_number` equal to one plus the count of pre-existing plans for the client. Creation is destructive to stale drafts: any existing plan of the client in `DRAFT` or `PROPOSED` is moved to `SUPERSEDED` by the system — goals of a superseded draft are not carried anywhere, since carrying happens only on the supersession of an `ACTIVE` plan — and the client's `version` increments by one.

The coach then shapes the draft with goals (§3.4) and, when ready, moves the plan from `DRAFT` to `PROPOSED`. Proposal is guarded by four checks: the acting coach must be the plan's `coach_id` (`ERR_FORBIDDEN_SCOPE`); the plan must hold at least one goal in `SET` or `IN_PROGRESS` (`ERR_GOALS_NOT_RESOLVED`); the referenced intake must be `APPROVED` (`ERR_INTAKE_NOT_APPROVED`); and the plan's coach must not be `INACTIVE` (`ERR_INVALID_STATE`).

A `PROPOSED` plan awaits the family's decision. The family may send it back — moving it to `DRAFT` to request changes — provided the acting family owns the plan's client's family, else `ERR_FORBIDDEN_SCOPE`; the revision loop may repeat. Or the family may accept the plan, moving it to `ACTIVE`. Acceptance enforces its own ordered set of gates: family ownership (`ERR_FORBIDDEN_SCOPE`); the family must be `ACTIVE` (`ERR_FAMILY_NOT_ACTIVE`); the client must be in `INTAKE` or `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`); the coach must not be `INACTIVE` (`ERR_INVALID_STATE`); the coach must not be in `SUPERVISION_DEFICIT` (`ERR_COACH_SUPERVISION_DEFICIT`); and the coach's `active_caseload` must be strictly below the `caseload_cap` (`ERR_CASELOAD_CAP_REACHED` when the caseload already equals or exceeds the cap).

Acceptance fires the plan's largest cascade. The plan stamps `activated_at` with the current instant and recomputes its posture. If the client already has another plan in `ACTIVE`, that plan is moved to `SUPERSEDED`; its goals still in `SET` or `IN_PROGRESS` are moved to `CARRIED_FORWARD` with `carried_to_plan_id` pointing at the newly accepted plan and `resolved_at` stamped; and its sessions still `SCHEDULED` are moved to `CANCELLED_EARLY` with billing `RETURNED`, each releasing one reservation from the funding package's `reserved_count`. The client moves from `INTAKE` to `ACTIVE` if not already active, and the client's `active_plan_id` is set to the newly accepted plan. The coach's `active_caseload` is recomputed upward by one, and the supervision requirement re-runs — possibly flipping the coach from `AVAILABLE` to `SUPERVISION_DEFICIT` after the fact, which does not undo the acceptance.

While a plan is `ACTIVE`, only one plan per client may hold that status, and the client's `active_plan_id` always names it. The plan's `posture` is a computed field with two values: the plan is `SCHEDULABLE`, or it is `SCHEDULING_BLOCKED` when any of four conditions holds — the family is not `ACTIVE`, the client is not `ACTIVE`, the plan's coach is `INACTIVE`, or the family holds no package of track `INDIVIDUAL` in `ACTIVE` status whose `credits_remaining` minus `reserved_count` is at least 1. The plan's `revision_recommended` flag starts false and is set by progress measurement (§3.6).

A plan concludes in one of three ways. A coach may move an `ACTIVE` plan to `COMPLETED` provided the acting coach is the plan's `coach_id` (`ERR_FORBIDDEN_SCOPE`), every goal of the plan has reached a terminal state — `ACHIEVED`, `DROPPED`, or `CARRIED_FORWARD` — else `ERR_GOALS_NOT_RESOLVED`, and no session remains in `SCHEDULED` attendance, else `ERR_PLAN_HAS_OPEN_SESSIONS`. Completion clears the client's `active_plan_id` to null and recomputes the coach's caseload downward by one with the supervision recompute. Termination — moving an `ACTIVE` plan to `TERMINATED` — may be performed by either a family member of the owning household or a practice administrator, has no preconditions, and fires its own cascade: every session still `SCHEDULED` is moved to `CANCELLED_EARLY` with billing `RETURNED` and the per-session reservation release; every goal in `SET` or `IN_PROGRESS` is moved to `DROPPED` with `resolved_at` stamped; the client's `active_plan_id` is cleared; and the coach's caseload and supervision posture are recomputed.

### 3.4. Goals Within a Plan

Goals are the plan's unit of intent. A coach adds a goal to a plan by supplying a `title` and a `target_date`; the goal record's `plan_id` binds it to the owning plan, whose `status` must be `DRAFT`, `PROPOSED`, or `ACTIVE`. A goal begins in `SET`.

A coach moves a goal from `SET` to `IN_PROGRESS` while the owning plan is `DRAFT`, `PROPOSED`, or `ACTIVE` — against any other plan state the request is rejected with `ERR_INVALID_STATE`. Marking achievement, moving a goal from `SET` or `IN_PROGRESS` to `ACHIEVED`, requires the owning plan to be `ACTIVE`, else `ERR_PLAN_NOT_ACTIVE`, and stamps `resolved_at`. Dropping a goal, moving it from `SET` or `IN_PROGRESS` to `DROPPED`, is permitted while the plan is `DRAFT`, `PROPOSED`, or `ACTIVE` and likewise stamps `resolved_at`. The fourth terminal state, `CARRIED_FORWARD`, is never requested directly: it is assigned by the system when a goal in `SET` or `IN_PROGRESS` belongs to an `ACTIVE` plan that is superseded, in which case `carried_to_plan_id` is set to the superseding plan and `resolved_at` is stamped.

### 3.5. Packages: Tiered Pricing, Credits, and Refunds

A household funds coaching by purchasing credit packages. An administrator purchases a Package for a family by supplying a `track` of `INDIVIDUAL` or `GROUP` and a `credits_total` of at least 1; the family must be `ACTIVE`, else `ERR_FAMILY_NOT_ACTIVE`. The purchase is priced by a five-step tiered algorithm whose results are frozen on the package row.

Step one computes the per-credit unit gross: the tier rate is 15000 cents per credit when `credits_total` is 8 or fewer, 13500 cents per credit when `credits_total` is from 9 to 16 inclusive, and 12000 cents per credit when `credits_total` is 17 or more; this rate is then multiplied by the track multiplier — 1.00 for `INDIVIDUAL`, 0.60 for `GROUP` — and the product is rounded half-up to an integer number of cents, yielding `unit_gross_cents`. Step two multiplies the rounded unit gross by `credits_total` to form a subtotal. Step three applies the sibling discount: when the family has at least 2 clients whose status is `INTAKE`, `ACTIVE`, or `PAUSED` at purchase time, the subtotal is multiplied by 0.90 and rounded half-up again — a 10 percent discount. Step four adds a flat materials fee of 2500 cents, which is never discounted, producing `price_paid_cents`. Step five derives the `per_credit_value_cents`, the provisional per-credit value, as `price_paid_cents` divided by `credits_total`, rounded half-up. Because the provisional per-credit value is rounded before any multiplication that uses it, the pinned order matters: round the per-credit value first, then multiply.

The purchase adds `price_paid_cents` to the family's `total_charged_cents`, runs the delinquency recomputation (which, being a prepaid charge, never auto-suspends), and increments the family's `version` by one. The package records `purchased_at` from the logical clock and computes `expires_at` as exactly 180 days after purchase.

A package tracks four credit counters: `credits_total` as purchased; `credits_consumed`, incremented by completed sessions and by group workshop enrollments funded on credit; `credits_forfeited`, incremented by late-cancelled and no-show sessions; and `reserved_count`, the number of sessions currently holding a `RESERVED` billing state against the package. The derived `credits_remaining` must always equal `credits_total` minus `credits_consumed` minus `credits_forfeited` — the INV-CREDITS identity — and a reservation never decrements `credits_remaining`; it merely raises `reserved_count`.

Packages age through system transitions. When `credits_remaining` reaches zero after a consume or forfeit mutation, an `ACTIVE` package moves to `EXHAUSTED`, and the posture of every `ACTIVE` plan of the family's clients is recomputed — to `SCHEDULING_BLOCKED` when no other `ACTIVE` individual-track package with an available credit exists. An exhausted package can revive: when a returned group enrollment credit (an enrollment drop or workshop cancellation against the exhausted package) decrements `credits_consumed` by one and lifts `credits_remaining` above zero, the package moves from `EXHAUSTED` back to `ACTIVE` and the family's plan postures are recomputed. The daily sweep expires packages: an `ACTIVE` package whose `expires_at` has been reached moves to `EXPIRED` when it still holds remaining credits — sessions already `RESERVED` against it stay reserved but no new reservations are permitted, and the family's plan postures recompute — but when the expired package has zero credits remaining it routes to `EXHAUSTED` instead of `EXPIRED`, again recomputing postures.

A package read exposes a provisional refundable value — the PROVISIONAL variant of the refund calculation — equal to `credits_remaining` multiplied by the rounded `per_credit_value_cents`. This estimate ignores clawback and therefore differs from the final amount whenever the sibling discount applied or the per-credit division had a remainder. The actual refund — the FINAL variant — runs when an administrator refunds a package in `ACTIVE` or `EXPIRED` status (refund from `EXHAUSTED` or `REFUNDED` is rejected with `ERR_PACKAGE_NOT_REFUNDABLE`; the family must not be `CLOSED`, else `ERR_FAMILY_NOT_ACTIVE`). The final refund is `price_paid_cents` minus the sum of `credits_consumed` and `credits_forfeited` multiplied by `unit_gross_cents`, floored at zero — used credits are re-priced at the gross unit rate, clawing back any sibling discount, and the materials fee is never refunded. The resulting `refund_cents` is stamped on the package, the package moves to the terminal `REFUNDED` state, and the family's `total_refunded_cents` increases by that amount. Any sessions still `RESERVED` against the refunded package are moved to `CANCELLED_EARLY` with billing `RETURNED` and their reservations released; the INV-CREDITS identity is no longer enforced once the package is refunded. The family's plan postures and `billing_status` are then recomputed — a refund may itself clear a `DELINQUENT` status.

### 3.6. Sessions: Scheduling Gates and the Cancellation Policy

Sessions are scheduled under an `ACTIVE` plan by the plan's coach, supplying the `package_id` of the individual-track package that will fund the session, a `scheduled_start`, and a `scheduled_end`. Request shape requires the end to be strictly after the start and the duration to be no more than 120 minutes (`ERR_VALIDATION` on range violations). The start must also lie strictly in the future at creation — a start at or before now is rejected with `ERR_SESSION_IN_PAST` — but under the §2.8 ordering this is a temporal rule evaluated after the cadence window below, not with request shape, so a start that violates both the cadence window and the strict-future rule draws `ERR_CADENCE_WINDOW_VIOLATION`. The session's `coach_id` is copied from the plan's coach at creation.

Scheduling enforces a battery of business gates, all evaluated under the priority order of §2.8. The family must be `ACTIVE` (`ERR_FAMILY_NOT_ACTIVE`) and the client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`); the plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`). The named package must be `ACTIVE` — an `EXPIRED`, `EXHAUSTED`, or `REFUNDED` package is rejected with `ERR_PACKAGE_NOT_ACTIVE` — and its track must be `INDIVIDUAL`, since individual sessions cannot draw group credits (`ERR_TRACK_MISMATCH`). The package must hold at least one available credit: `credits_remaining` minus `reserved_count` must be at least 1, else `ERR_NO_CREDITS_AVAILABLE`.

Two temporal checks follow. The cadence window anchors on the most recent session of the plan whose attendance is `SCHEDULED`, `COMPLETED`, or `NO_SHOW` — cancelled sessions, early or late, never reset the cadence anchor, and ties break toward the session created last. For a `WEEKLY` cadence, the first session of the plan must start within 14 days of the plan's `activated_at` (a start on the activation instant itself up to and including day 14 is acceptable), and each subsequent session must start at least 4 days and at most 10 days after the anchor, both bounds inclusive, compared to the exact second. For a `BIWEEKLY` cadence, the first-session window is the same 14 days, and subsequent gaps must be at least 11 days and at most 17 days, both inclusive. A violation of either window is rejected with `ERR_CADENCE_WINDOW_VIOLATION`. The conflict checks then protect the coach's calendar. Rule A is a half-open overlap against the coach's other `SCHEDULED` sessions: a conflict exists when the new session starts before an existing session ends and ends after that session starts — rejected with `ERR_COACH_DOUBLE_BOOKED` — while strictly back-to-back adjacency, where one session's end equals the other's start, is allowed. Rule B is a buffered overlap against every `OPEN` or `LOCKED` workshop the same coach facilitates: a conflict exists when the new session starts less than 15 minutes after the workshop's end or ends less than 15 minutes before the workshop's start — rejected with `ERR_COACH_BUFFER_CONFLICT` — while leaving exactly 15 minutes clear is allowed because the comparison is strict.

A successfully created session starts with `attendance_state` `SCHEDULED` and `billing_state` `RESERVED`, raises the funding package's `reserved_count` by one, and recomputes the plan's posture. The two state dimensions then evolve in parallel.

Completion is a coach action — the acting coach must be the session's `coach_id`, else `ERR_FORBIDDEN_SCOPE` — and requires the session to have started: completing before `scheduled_start` is rejected with `ERR_SESSION_NOT_STARTED`. Completion moves attendance to `COMPLETED`, billing from `RESERVED` to `CONSUMED`, stamps `resolved_at`, increments the package's `credits_consumed` by one while decrementing `reserved_count` by one, recomputes the package's status (which may flip `ACTIVE` to `EXHAUSTED`), and recomputes the plan's posture.

Cancellation is governed by the notice the family or coach gives, measured from now to `scheduled_start` in exact seconds. A cancellation attempted at or after the start is rejected with `ERR_SESSION_ALREADY_STARTED`. Notice of at least 24 hours — exactly 24 hours to the second qualifies — is free: the session moves to `CANCELLED_EARLY`, billing moves from `RESERVED` to `RETURNED`, `cancellation_fee_cents` is zero, the package's `reserved_count` falls by one, and the package status and plan posture recompute. Notice under 24 hours moves the session to `CANCELLED_LATE` and billing to `FORFEITED`: the package's `credits_forfeited` rises by one, `reserved_count` falls by one, and the package status recomputes. The fee tier splits inside the late window: notice of at least 4 hours but under 24 hours — exactly 4 hours qualifies for the half tier — charges 50 percent of the package's `per_credit_value_cents`, rounded half-up (the per-credit value was already rounded at purchase, and the fee rounds again); notice under 4 hours charges the full `per_credit_value_cents`. The fee is added to the family's `total_charged_cents`, and the delinquency cascade of §2.6 applies: if the fee leaves the family strictly over the threshold while `ACTIVE`, the family is auto-suspended and its plans' postures block scheduling.

A no-show is the coach's mirror of the full-fee tier: the acting coach must be the session's `coach_id` (`ERR_FORBIDDEN_SCOPE`), the session must have started (`ERR_SESSION_NOT_STARTED`), and the session moves to `NO_SHOW` with billing `FORFEITED`, `cancellation_fee_cents` equal to the full `per_credit_value_cents`, `resolved_at` stamped, the package's `credits_forfeited` incremented and `reserved_count` decremented, and both the package-exhaustion and family-delinquency cascades applied. Cancellation and no-show fees are the only charges that can trigger automatic suspension.

System cascades — plan supersession or termination, client discharge, package refund — cancel scheduled sessions through the same early-cancellation path: attendance `CANCELLED_EARLY`, billing `RETURNED`, reservations released, no fee.

### 3.7. Between-Session Accountability: Check-Ins

A coach creates an accountability check-in under an `ACTIVE` plan by supplying a `due_at` deadline, which must lie strictly in the future at creation. The check-in begins in `PENDING`.

The family submits against the check-in with an optional `outcome_note`. Submission requires the owning plan to be `ACTIVE`, else `ERR_PLAN_NOT_ACTIVE`, and the timing decides the outcome. Submitting at or before `due_at` — the boundary is inclusive — moves the check-in to `SUBMITTED_ON_TIME`, stamps `submitted_at`, and increments the client's `checkin_streak` by one. Submitting after `due_at` but no later than 72 hours past it moves the check-in to `SUBMITTED_LATE`, stamps `submitted_at`, and resets the client's `checkin_streak` to zero. Once more than 72 hours have elapsed since `due_at`, submission is rejected with `ERR_CHECKIN_EXPIRED`, and the daily sweep will already have moved such a check-in to `MISSED`, likewise resetting the streak to zero. A coach may acknowledge a submitted check-in — from either `SUBMITTED_ON_TIME` or `SUBMITTED_LATE` into the terminal `ACKNOWLEDGED` state — provided the acting coach is the owning plan's `coach_id`, else `ERR_FORBIDDEN_SCOPE`. `MISSED` and `ACKNOWLEDGED` are terminal.

### 3.8. Progress Measurement and the Revision Trigger

A coach captures a client's progress by taking a progress snapshot; the acting coach must coach the client's currently `ACTIVE` plan. Each snapshot writes one immutable ProgressSnapshot row containing both measurement variants, and the client's denormalized indices are refreshed from it.

The snapshot's rolling variant covers a 28-day window ending at the snapshot instant: `window_end` is the snapshot time and `window_start` is exactly 28 days earlier, both ends inclusive. Within that window, `goals_considered` counts the client's terminal goals whose `resolved_at` falls in the window, and `goals_achieved` counts the subset in `ACHIEVED`; `checkins_considered` counts check-ins that left `PENDING` — submitted, or resolved `MISSED` — with their resolution timestamp in the window, and `checkins_on_time` counts the subset whose status is `SUBMITTED_ON_TIME` or `ACKNOWLEDGED` and whose `submitted_at` is at or before the check-in's `due_at`. The goal rate is `goals_achieved` divided by `goals_considered`; the check-in rate is `checkins_on_time` divided by `checkins_considered`. When both denominators are zero the index is null; when exactly one is zero the index is the other rate multiplied by 100 and rounded half-up — the full weight renormalizes onto the present component; otherwise the index is 100 times the weighted blend — six-tenths of the goal rate plus four-tenths of the check-in rate — rounded half-up to an integer between 0 and 100. This value is stored as the snapshot's `rolling_index` and copied onto the client as `rolling_progress_index`, which remains null until the first snapshot exists.

The same underlying rows feed a second variant, `cumulative_index`, computed over all goals and check-ins of the client's current `ACTIVE` plan regardless of timestamp, with the same weights, null-handling, and rounding; it is null when the client has no active plan or no data, and it is copied onto the client as `cumulative_progress_index`. Because the variants share components, the two numbers differ exactly when some event lies outside the rolling window.

After the snapshot is stored, a side rule runs: when the two most recent snapshots of the client, ordered by creation ascending, both hold a non-null `rolling_index` strictly below 40, the `ACTIVE` plan's `revision_recommended` flag is set to true — two consecutive low readings are the practice's signal to revise the plan.

### 3.9. Coordination with Schools and Clinicians

A family registers the outside adults in the student's life as coordination contacts, supplying a `name`, an `organization`, a `contact_type` of `SCHOOL` or `CLINICIAN`, and an `email`. A contact begins `ACTIVE`. A family member of the owning household may later deactivate a contact to the terminal `INACTIVE` state — acting for another household is rejected with `ERR_FORBIDDEN_SCOPE` — which fires a depth-2 cascade: every consent grant naming that contact in `PENDING_SIGNATURE` or `ACTIVE` moves to `REVOKED`, and every coordination note shared to that contact is sealed.

Consent is granted per contact. Creating a consent grant supplies the `contact_id` of the recipient, a `scope` from the ladder in §2.10, an `expires_at` that must lie strictly in the future at creation, and the OCC field `expected_family_version` per §2.7. The contact must belong to the path family, else `ERR_CONTACT_NOT_LINKED`. The new grant begins in `PENDING_SIGNATURE`. Creation supersedes: any prior non-terminal grant for the same contact moves to `SUPERSEDED`, and when the superseded grant was `ACTIVE`, the note-sealing cascade runs over the notes shared under it. The family's `version` increments by one.

A family member signs a pending grant — moving it from `PENDING_SIGNATURE` to `ACTIVE` — provided the family owns the grant (`ERR_FORBIDDEN_SCOPE`) and the grant has not yet reached its `expires_at`; signing at or after expiry is rejected with `ERR_CONSENT_EXPIRED`. Signing stamps `signed_at`. A family member may revoke a grant from either `PENDING_SIGNATURE` or `ACTIVE`; revoking an active grant seals every note in `SHARED` status that was shared to the grant's contact. The daily sweep moves an `ACTIVE` grant to `EXPIRED` once now reaches `expires_at`, with the same sealing cascade.

Coaches author the substance of coordination as notes under a client. Creating a note supplies a `topic` from the three-tier ladder and a free-text `body`; the note's `author_coach_id` is set from the acting coach's identity, and the note begins in `DRAFT`. Only the author may finalize a note — moving it from `DRAFT` to `FINALIZED`, with anyone else rejected by `ERR_FORBIDDEN_SCOPE`. Only the author may share a finalized note, supplying the target `contact_id`; sharing enforces the full consent gate of §2.10 — the note must be `FINALIZED` and the contact `ACTIVE` (`ERR_INVALID_STATE`), an `ACTIVE` grant must exist for the note's family and the contact (`ERR_CONSENT_NOT_ACTIVE`), the grant's scope must cover the note's `topic` (`ERR_CONSENT_SCOPE_INSUFFICIENT`), and the contact must belong to the same family as the note's client (`ERR_CONTACT_NOT_LINKED`). A successful share moves the note to `SHARED` and stamps `shared_with_contact_id` and `shared_at`.

Thereafter the note's visibility is a pure function of consent. An external contact reads exactly the notes whose `shared_with_contact_id` names that contact and whose status remains `SHARED`, in creation order; the moment the covering consent leaves `ACTIVE` — revoked, expired, superseded, destroyed by contact deactivation, or destroyed by family closure — the note moves to the terminal `SEALED` state and vanishes from that view. Finalized-but-never-shared notes can also be sealed by the family-closure cascade.

### 3.10. Group Workshops: Enrollment, Waitlists, and Refund Cascades

The group track runs through workshops. An administrator creates a Workshop with a `title`, the facilitating `coach_id`, a `capacity` of at least 1, a `window_start` and `window_end` with the end strictly after the start, and a `price_cents` of zero or more, the money price per enrollment when billing is in money. The workshop begins in `DRAFT`, tracks its `seats_taken` as the count of enrollments in `ENROLLED` status, and is opened by an administrator when the facilitating coach is not `INACTIVE` (`ERR_INVALID_STATE`) and the `window_start` lies strictly in the future (`ERR_SESSION_IN_PAST`).

An `OPEN` workshop accepts enrollments. A family member enrolls a student by supplying the `client_id`; the family must be `ACTIVE` (`ERR_FAMILY_NOT_ACTIVE`), the client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`), and the client's track must be `GROUP` or `HYBRID` — an `INDIVIDUAL`-track student is rejected with `ERR_TRACK_MISMATCH`. The workshop must be `OPEN` for both enrollment and drops, else `ERR_WORKSHOP_NOT_OPEN`. A duplicate — any existing non-terminal enrollment for the same workshop and client — is rejected with `ERR_DUPLICATE_ENROLLMENT`. When a seat is free (`seats_taken` below `capacity`), the enrollment begins `ENROLLED`; otherwise it begins `WAITLISTED` with a `waitlist_position` assigned one-based among waitlisted entries by creation ascending, and a `billing_source` of `NONE` while it waits.

Every enrollment record carries the `workshop_id` of the workshop it occupies a seat in, and its `status` — `ENROLLED`, `WAITLISTED`, `DROPPED`, or `REFUNDED` — tracks its place in the roster lifecycle. Billing for a seat follows a waterfall. The system looks among the family's packages for one with track `GROUP`, status `ACTIVE`, and at least one credit remaining, preferring the package with the earliest `expires_at` and breaking ties toward the earliest created. When such a candidate exists, the enrollment's `billing_source` is `PACKAGE_CREDIT`, the package's `credits_consumed` rises by one with a status recompute, and `charged_cents` is zero. When no candidate exists, the enrollment bills in money: `billing_source` is `MONEY`, `charged_cents` equals the workshop's `price_cents`, and the amount is added to the family's `total_charged_cents` with the delinquency recomputation — which, being prepaid, never auto-suspends.

A family may drop an enrollment while the workshop remains `OPEN`; acting for another family's enrollment is rejected with `ERR_FORBIDDEN_SCOPE`, and dropping an already `DROPPED` or `REFUNDED` enrollment is rejected with `ERR_ENROLLMENT_NOT_DROPPABLE`. A waitlisted drop carries no refund — the family was never charged — clears the position, and recomputes the remaining positions by creation ascending. An enrolled drop refunds by source: a money-billed enrollment refunds `charged_cents` into the family's `total_refunded_cents` when the drop occurs no later than 7 days before the workshop's `window_start` — the boundary is inclusive — and refunds nothing inside that window; a credit-billed enrollment always returns one credit to the family 's group package when that package is `ACTIVE` — decrementing `credits_consumed` and raising `credits_remaining` — regardless of the refund window, and returns nothing when the package is no longer active. The drop decrements `seats_taken` by one and then promotes the waitlist: the earliest-created `WAITLISTED` enrollment moves to `ENROLLED`, its position clears, its billing is computed by the same waterfall, `seats_taken` rises by one, and positions recompute.

Workshop administration completes the lifecycle. Locking an `OPEN` workshop moves it to `LOCKED` and freezes the roster: enrollment creation and drops are rejected with `ERR_INVALID_STATE` while locked. Completing a `LOCKED` workshop requires now to have reached `window_end`, else `ERR_WORKSHOP_WINDOW_NOT_ENDED`, and drops every remaining waitlisted enrollment. Cancelling — from either `OPEN` or `LOCKED` — runs the refund cascade: every `ENROLLED` enrollment moves to `REFUNDED`, refunding money-billed enrollments into the family's `total_refunded_cents` and returning one credit for credit-billed enrollments when the group's package is `ACTIVE` (else no compensation), while every `WAITLISTED` enrollment moves to `DROPPED`.

### 3.11. Supervision Records in Practice

Section 2.9 defines the governance; the workflow is short. An administrator schedules a supervision record for a coach by naming the `supervisor_coach_id`, a `scheduled_at` time, and the `hours` credited, which must be greater than zero. The record begins `SCHEDULED`. The named supervisor — and only the named supervisor, enforcing the segregation of duties — moves it to `HELD`. An administrator then either verifies it, moving it to the terminal `VERIFIED` state, stamping `verified_at`, recomputing the coach's `verified_supervision_hours_30d`, and re-running the supervision requirement (which may clear a `SUPERVISION_DEFICIT` back to `AVAILABLE`); or cancels it from `SCHEDULED` or `HELD` into the terminal `CANCELLED` state. Every caseload change, verification, window slide, and coach reactivation re-runs the requirement in the pinned order of §2.9, keeping the deficit flag honest without ever disturbing plans already in flight.

## 4. Endpoint Definitions

Operations that create a new resource — a family, client, coach, intake, plan, goal, package, session, check-in, snapshot, contact, consent, note, workshop, enrollment, supervision record, or payment — return `201 Created`. Operations that modify an existing resource in place, including all state transitions, cancellations, completions, acknowledgements, shares, refunds, drops, clock control, and the daily sweep, return `200 OK`. All endpoints are mounted under the `/api` prefix, and all enforce the validation priority of §2.8.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock to `to_iso8601` | PracticeAdmin |
| POST | `/api/admin/run-daily-sweep` | Run the ordered daily operations sweep | PracticeAdmin |
| POST | `/api/families` | Create a household account in `INTAKE` | PracticeAdmin |
| GET | `/api/families/{id}` | Read a family with ledger counters and `billing_status` | PracticeAdmin, FamilyMember |
| GET | `/api/families` | Paginated family list | PracticeAdmin |
| POST | `/api/families/{id}/transition` | Family status transition per §1.2 (`to_state` of `ACTIVE`, `SUSPENDED`, or `CLOSED`) | PracticeAdmin |
| POST | `/api/families/{id}/payments` | Record a payment of `amount_cents`; recomputes balance and delinquency | FamilyMember |
| POST | `/api/families/{id}/clients` | Register a student under a family | PracticeAdmin, FamilyMember |
| GET | `/api/families/{id}/clients` | List clients of a family | PracticeAdmin, FamilyMember |
| GET | `/api/clients/{id}` | Read a client with progress indices and streak | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/clients/{id}/transition` | Client status transition (`to_state` of `PAUSED`, `ACTIVE`, or `DISCHARGED`) | PracticeAdmin |
| POST | `/api/coaches` | Create a coach in `AVAILABLE` | PracticeAdmin |
| GET | `/api/coaches/{id}` | Read a coach with caseload counters and supervision posture | PracticeAdmin, Coach |
| GET | `/api/coaches` | Paginated coach list | PracticeAdmin |
| POST | `/api/coaches/{id}/transition` | Coach status transition (`to_state` of `INACTIVE` or `AVAILABLE`) | PracticeAdmin |
| GET | `/api/coaches/{id}/plans` | Plans coached by this coach | PracticeAdmin, Coach |
| GET | `/api/coaches/{id}/sessions` | Sessions coached by this coach | PracticeAdmin, Coach |
| GET | `/api/coaches/{id}/notes` | Coordination notes authored by this coach | PracticeAdmin, Coach |
| GET | `/api/coaches/{id}/workshops` | Workshops facilitated by this coach | PracticeAdmin, Coach |
| POST | `/api/clients/{id}/intakes` | Create an intake assessment in `DRAFT` | FamilyMember, PracticeAdmin |
| GET | `/api/clients/{id}/intakes` | Intakes of a client | PracticeAdmin, Coach, FamilyMember |
| GET | `/api/intakes/{id}` | Read one intake | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/intakes/{id}/transition` | Intake workflow transition (`to_state` of `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `NEEDS_REVISION`, or `DRAFT`); `NEEDS_REVISION` requires `review_notes` | Coach, FamilyMember |
| GET | `/api/intakes/{id}/plans` | Plans referencing this intake | PracticeAdmin, Coach |
| POST | `/api/clients/{id}/plans` | Create a plan draft (OCC via `expected_client_version`); supersedes non-terminal plans | Coach |
| GET | `/api/clients/{id}/plans` | Plans of a client in all statuses | PracticeAdmin, Coach, FamilyMember |
| GET | `/api/plans/{id}` | Read one plan with posture and `revision_recommended` | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/plans/{id}/transition` | Plan transition (`to_state` of `PROPOSED`, `DRAFT`, `ACTIVE`, `COMPLETED`, or `TERMINATED`) | Coach, FamilyMember, PracticeAdmin |
| POST | `/api/plans/{id}/goals` | Add a goal to a plan | Coach |
| GET | `/api/plans/{id}/goals` | Goals of a plan | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/goals/{id}/transition` | Goal transition (`to_state` of `IN_PROGRESS`, `ACHIEVED`, or `DROPPED`) | Coach |
| POST | `/api/families/{id}/packages` | Purchase a credit package; tiered pricing frozen at purchase | PracticeAdmin |
| GET | `/api/families/{id}/packages` | Packages of a family | PracticeAdmin, FamilyMember |
| GET | `/api/packages/{id}` | Read one package with provisional refund value | PracticeAdmin, FamilyMember, Coach |
| POST | `/api/packages/{id}/refund` | Refund an `ACTIVE` or `EXPIRED` package at the final refund value | PracticeAdmin |
| GET | `/api/packages/{id}/sessions` | Sessions funded by this package | PracticeAdmin, Coach |
| POST | `/api/plans/{id}/sessions` | Schedule a session under an `ACTIVE` plan; reserves one package credit | Coach |
| GET | `/api/plans/{id}/sessions` | Sessions of a plan | PracticeAdmin, Coach, FamilyMember |
| GET | `/api/sessions/{id}` | Read one session, both state dimensions | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/sessions/{id}/complete` | Mark a scheduled session completed | Coach |
| POST | `/api/sessions/{id}/cancel` | Cancel a scheduled session; notice tier decides fee | FamilyMember, Coach |
| POST | `/api/sessions/{id}/mark-no-show` | Mark a started session as no-show at the full fee tier | Coach |
| POST | `/api/plans/{id}/checkins` | Create an accountability check-in under an `ACTIVE` plan | Coach |
| GET | `/api/plans/{id}/checkins` | Check-ins of a plan | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/checkins/{id}/submit` | Family submits a check-in; on-time boundary inclusive | FamilyMember |
| POST | `/api/checkins/{id}/acknowledge` | Coach acknowledges a submitted check-in | Coach |
| POST | `/api/clients/{id}/progress-snapshots` | Compute and store a snapshot with both index variants | Coach |
| GET | `/api/clients/{id}/progress-snapshots` | Snapshots of a client in creation order | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/families/{id}/contacts` | Register a school or clinician contact | FamilyMember |
| GET | `/api/families/{id}/contacts` | Contacts of a family | PracticeAdmin, FamilyMember |
| GET | `/api/contacts/{id}` | Read one coordination contact | PracticeAdmin, FamilyMember |
| POST | `/api/contacts/{id}/transition` | Contact transition (`to_state` of `INACTIVE`); cascades consent revocation and note sealing | FamilyMember |
| POST | `/api/families/{id}/consents` | Create a consent grant in `PENDING_SIGNATURE` (OCC via `expected_family_version`) | FamilyMember |
| GET | `/api/families/{id}/consents` | Consents of a family | PracticeAdmin, FamilyMember |
| GET | `/api/contacts/{id}/consents` | Consents naming this contact | PracticeAdmin, FamilyMember |
| POST | `/api/consents/{id}/transition` | Consent transition (`to_state` of `ACTIVE` or `REVOKED`) | FamilyMember |
| POST | `/api/clients/{id}/notes` | Coach authors a coordination note in `DRAFT` | Coach |
| GET | `/api/clients/{id}/notes` | Notes about a client, practice-side view | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/notes/{id}/transition` | Note transition (`to_state` of `FINALIZED`); author only | Coach |
| POST | `/api/notes/{id}/share` | Share a finalized note with a contact under the consent gate | Coach |
| GET | `/api/contacts/{id}/shared-notes` | Consent-limited external view of unsealed shared notes | ExternalContact, PracticeAdmin |
| POST | `/api/workshops` | Create a workshop in `DRAFT` | PracticeAdmin |
| GET | `/api/workshops/{id}` | Read a workshop with `seats_taken` | PracticeAdmin, Coach, FamilyMember |
| GET | `/api/workshops` | Paginated workshop list | PracticeAdmin, Coach, FamilyMember |
| POST | `/api/workshops/{id}/transition` | Workshop transition (`to_state` of `OPEN`, `LOCKED`, `COMPLETED`, or `CANCELLED`) | PracticeAdmin |
| POST | `/api/workshops/{id}/enrollments` | Enroll a client; seat or waitlist, billing waterfall | FamilyMember |
| GET | `/api/workshops/{id}/enrollments` | Enrollments of a workshop in creation order | PracticeAdmin, Coach, FamilyMember |
| GET | `/api/clients/{id}/enrollments` | Workshop enrollments of a client | PracticeAdmin, FamilyMember |
| POST | `/api/enrollments/{id}/drop` | Drop an enrollment; refund per rules; promotes waitlist head | FamilyMember |
| POST | `/api/coaches/{id}/supervision-records` | Schedule a supervision record; supervisor must differ and hold `SUPERVISOR` | PracticeAdmin |
| GET | `/api/coaches/{id}/supervision-records` | Supervision records of a coach | PracticeAdmin, Coach |
| POST | `/api/supervision-records/{id}/transition` | Supervision transition (`to_state` of `HELD`, `VERIFIED`, or `CANCELLED`) | PracticeAdmin, Coach |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_SCOPE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_CLIENT_VERSION` | 412 |
| `ERR_STALE_FAMILY_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FAMILY_NOT_ACTIVE` | 409 |
| `ERR_FAMILY_NO_CLIENTS` | 409 |
| `ERR_FAMILY_DELINQUENT` | 409 |
| `ERR_FAMILY_HAS_ACTIVE_DEPENDENCIES` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_HAS_ACTIVE_PLAN` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PLAN_HAS_OPEN_SESSIONS` | 409 |
| `ERR_GOALS_NOT_RESOLVED` | 409 |
| `ERR_INTAKE_NOT_APPROVED` | 409 |
| `ERR_INTAKE_CLIENT_MISMATCH` | 422 |
| `ERR_PACKAGE_NOT_ACTIVE` | 409 |
| `ERR_PACKAGE_NOT_REFUNDABLE` | 409 |
| `ERR_NO_CREDITS_AVAILABLE` | 422 |
| `ERR_TRACK_MISMATCH` | 422 |
| `ERR_CASELOAD_CAP_REACHED` | 422 |
| `ERR_COACH_SUPERVISION_DEFICIT` | 422 |
| `ERR_COACH_HAS_ACTIVE_PLANS` | 409 |
| `ERR_COACH_DOUBLE_BOOKED` | 409 |
| `ERR_COACH_BUFFER_CONFLICT` | 409 |
| `ERR_CADENCE_WINDOW_VIOLATION` | 422 |
| `ERR_SESSION_IN_PAST` | 422 |
| `ERR_SESSION_ALREADY_STARTED` | 422 |
| `ERR_SESSION_NOT_STARTED` | 422 |
| `ERR_CHECKIN_EXPIRED` | 422 |
| `ERR_CONSENT_NOT_ACTIVE` | 409 |
| `ERR_CONSENT_EXPIRED` | 409 |
| `ERR_CONSENT_SCOPE_INSUFFICIENT` | 422 |
| `ERR_CONTACT_NOT_LINKED` | 422 |
| `ERR_WORKSHOP_NOT_OPEN` | 409 |
| `ERR_WORKSHOP_WINDOW_NOT_ENDED` | 422 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_ENROLLMENT_NOT_DROPPABLE` | 409 |
| `ERR_SELF_SUPERVISION` | 422 |
| `ERR_CREDENTIAL_INSUFFICIENT` | 403 |

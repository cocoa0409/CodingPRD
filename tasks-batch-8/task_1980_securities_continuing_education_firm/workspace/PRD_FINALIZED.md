# Securities Continuing Education & Firm Element API — Product Requirements Document

## 1. Introduction

A broker-dealer's training department operates at the intersection of several continuing-education regimes, each with its own clock and its own consequences for falling behind. Every registered representative carries a regulatory element obligation that recurs by cycle and comes with a firm completion deadline, a grace period, and — beyond the grace period — a lapse that deactivates the rep's registration until cured. Alongside it, the firm element requires an annual needs analysis that drives a published training plan, a tally of certified hours against a computed requirement, and a closing attestation personally executed by the rep. New product offerings may not be sold until each covered rep completes product-specific training, and representatives who also hold state insurance licenses must satisfy state CE hour requirements within each renewal period, with limited carryover of excess credit from the period just closed.

This API is the system of record for that entire operation. It administers the representative roster and each rep's registration standing; governs training content through a segregated author-versus-approver workflow; schedules instructor-led sessions against shared rooms and firm-wide blackout windows; tracks every enrollment from creation through start, completion, retake, cancellation, void, and expiry; and enforces every deadline through an explicit, operator-run enforcement sweep evaluated against a controllable logical clock rather than the host wall clock. Non-completion is never a passive report here: when a regulatory assignment lapses, the representative's registration flips to an inactive state and every selling certification that depends on that registration is suspended until the deficiency is cured.

Every consequential action — approvals, rejections, retirements, completions, voids, attestations, lapses, cures, launches, suspensions, reinstatements, plan publications and closures, and each enforcement run itself — is captured in an append-only audit evidence log that compliance staff and auditors can query. The remainder of this document specifies the system-wide contracts (Section 2), the business workflows in narrative form (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and cross-cutting principles that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles: `TrainingAdmin`, `ComplianceOfficer`, `RegisteredRep`, and `Auditor`. A request whose headers are missing, or whose `X-User-Role` is not one of these four declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted on the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `RegisteredRep`, `X-User-ID` is the `id` of the acting Representative record; ownership checks on any resource that references a representative compare the resource's rep field — or, for an attestation, the parent plan's rep field — to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_REQUIRED` (HTTP 403). When `X-User-Role` is `TrainingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `author_user_id` on training content) but never compares it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier; the server may record it (for example, as `approved_by_user_id` when content is approved) but never compares it to any entity's `id`. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque read-only identifier with no write privileges anywhere in the system.

Segregation of duties is structural, not advisory. The operator who authors a piece of training content can never be the one who approves it. A registered representative attests only their own annual attestation and acts only on their own enrollments. Only a `ComplianceOfficer` may void a completed enrollment, terminate a registration, run the enforcement sweep, or set the logical clock.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Every timestamp the server emits is rendered in this same format — ISO 8601 UTC with exactly three fractional digits — including resource `created_at` and `updated_at` values, workflow stamps such as `due_at`, `lapse_after`, `expires_at`, `completed_at`, `start_at`, `end_at`, `period_start`, `period_end`, `launched_at`, `certified_at`, `attested_at`, `published_at`, `closed_at`, and `needs_analysis_completed_at`, and the clock endpoint's `current_utc`; since the logical clock keeps one-second precision, every timestamp stamped from it renders with `.000` fractional digits (for example, `2026-11-29T00:00:00.000Z`).
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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, so a client can always determine how many records exist in total and whether further pages remain.

### 2.4. The Logical Clock and Deadline Enforcement

The server maintains its own logical clock. Before it has ever been set, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to the host machine's wall clock. Every timestamp the system derives — `created_at` values, assignment deadlines, enrollment expiry instants, session windows, license period boundaries, and every overdue-or-lapsed comparison — is computed against this logical clock.

A compliance-only, test-driving capability advances or sets the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Setting the clock mutates no entity: moving time forward does not by itself expire enrollments, deliver sessions, mark assignments overdue, or lapse licenses. Deadline effects materialize only when the enforcement sweep is run.

The enforcement sweep is a `ComplianceOfficer`-only operation that evaluates all pending deadline transitions in one epoch, in a pinned order: sessions first, then enrollments, then assignments, then licenses. Its response body reports how many records moved in each phase — `sessions_marked_delivered`, `enrollments_expired`, `assignments_marked_overdue`, `assignments_lapsed`, and `licenses_lapsed` — and the run itself is recorded in the audit log as an `ENFORCEMENT_SWEEP_RUN` event. All timestamp comparisons in the system are made at one-second precision.

### 2.5. Common Resource Properties

Every primary resource in the system — representatives, training content, course sessions, enrollments, regulatory assignments, firm element plans, annual attestations, product offerings, product certifications, state CE licenses, and blackout windows — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, read from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by a cascade from some other operation.

The audit log is the single exception. An audit event carries only `id` and `created_at` alongside its evidence fields; because the log is append-only and entries are never modified, `updated_at` and `version` are absent from it.

### 2.6. Request Validation Order and Referential Integrity

The API is flat: every resource is a top-level collection, and relationships between records travel in request bodies and list filters rather than in nested URL paths. Each endpoint path therefore contains at most one resource identifier — one of `repId`, `contentId`, `sessionId`, `enrollmentId`, `assignmentId`, `planId`, `attestationId`, `productId`, `certId`, `licenseId`, or `windowId` — and that identifier must resolve to an existing record.

Every incoming request is evaluated against an ordered validation chain, and the first failing check determines the response; later checks are not evaluated once an earlier one has failed. The evaluation order is:

1. **Identity headers.** `X-User-ID` and `X-User-Role` are present and the role is one of the four declared roles, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to every endpoint.
2. **Role authorization.** The caller's role is listed among the endpoint's permitted roles, otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403). This applies to every endpoint.
3. **Existence.** The path identifier resolves to an existing resource, and then any foreign keys carried in the request body — `rep_id`, `content_id`, `session_id`, `required_training_content_id` — resolve to existing resources; the first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404).
4. **Request shape.** Required fields are present, enum values are valid, a completion `score` lies between 0 and 100 inclusive, an enrollment create carries exactly one of `content_id` or `session_id`, a void's `justification` is at least ten characters long, and similar shape rules hold — violations yield `ERR_INVALID_REQUEST` (HTTP 400). Window sanity is checked at the same stage: a session, blackout, license period, or renewal window whose end is not strictly later than its start yields `ERR_WINDOW_INVALID` (HTTP 400).
5. **Optimistic concurrency.** For the two endpoints that take a version field (see §2.7), the expected version must match the parent's current `version`, otherwise `ERR_STALE_VERSION` (HTTP 412). This is evaluated after existence and shape, but before any business-state check.
6. **Target-state guards.** The resource's current status must permit the requested transition — the content, enrollment, session, plan, attestation, product, and certification state guards of Section 3, each with its own 409 error.
7. **Registration standing.** Operations that deliver training or open obligations require the representative's `registration_status` to be `ACTIVE`; an `INACTIVE_CE` rep yields `ERR_REGISTRATION_INACTIVE` (HTTP 409) and a `TERMINATED` rep yields `ERR_REGISTRATION_TERMINATED` (HTTP 409).
8. **Segregation of duties and ownership.** A content approver must differ from the content's author (`ERR_SOD_AUTHOR_CANNOT_APPROVE`, HTTP 403); a `RegisteredRep` may act only on their own enrollments and own attestation (`ERR_OWNERSHIP_REQUIRED`, HTTP 403); publishing a plan requires its needs analysis to have been recorded first (`ERR_NEEDS_ANALYSIS_MISSING`, HTTP 409).
9. **Uniqueness.** Duplicate identity checks — `crd_number`, content `code`, `product_code`, one license per state per rep, at most one open assignment per rep, at most one published-or-closed plan per rep and year, and no duplicate active enrollment for the same rep and content — each with its own 409 error.
10. **Referential preconditions.** A state CE license may be created only for a rep flagged as insurance-licensed (`ERR_REP_NOT_INSURANCE_LICENSED`, HTTP 409); an enrollment's session must belong to the referenced or derived content (`ERR_INVALID_REQUEST`).
11. **Temporal conflicts and expiry.** Room overlap (`ERR_ROOM_CONFLICT`), blackout intersection (`ERR_BLACKOUT_CONFLICT`), and enrollment expiry (`ERR_ENROLLMENT_EXPIRED`) are evaluated here, each HTTP 409.
12. **Capacity, fiscal, and final business gates.** Session seat availability (`ERR_SESSION_FULL`), plan close eligibility (`ERR_PLAN_HOURS_UNMET`), the retake budget (`ERR_MAX_ATTEMPTS_REACHED`), and reinstatement preconditions (`ERR_REINSTATEMENT_BLOCKED`) close the chain, each HTTP 409.

### 2.7. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency field, and in both cases the field is mandatory, not optional.

A `POST /firm-element-plans` request must carry `expected_representative_version` holding the `version` of the target representative as the client last observed it. Creating a plan supersedes any existing draft for the same rep and year and bumps the representative's `version`, so a client holding a stale view must re-read before writing: if `expected_representative_version` does not match the representative's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

A `PUT /contents/{contentId}` request must carry `expected_content_version` holding the content's `version` as the client last observed it. An edit bumps the content's `version` and, for rejected content, returns it to `DRAFT`; if `expected_content_version` does not match the content's current `version`, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. Clients that need read-modify-write safety anywhere else rely on the deterministic state guards described in Section 3.

### 2.8. Credit-Hour Precision and Rounding

Credit hours are decimal quantities. A course's `credit_hours` is greater than zero and carries at most two decimal places. All persisted hour aggregations on plans and licenses — certified, projected, strict, effective, carried — are stored at two decimal places using round-half-up rounding. The firm element requirement computed at plan publish is a whole number of hours and needs no rounding.

Hours reported to a state regulator follow a stricter, pinned rule: each completed course's hours are first rounded half up to the nearest half hour, and only then are the per-course values summed into `reported_hours`. Seat counts on sessions are integers. Timestamp comparisons (deadlines, expiry, period boundaries) are evaluated at one-second precision, with boundary inclusivity exactly as each rule in Section 3 states.

### 2.9. Audit Evidence

The system maintains an append-only audit evidence log. Each entry records an `event_type`, the polymorphic subject of the event as an `entity_type` plus `entity_id` pair, the acting party as `actor_user_id` and `actor_role`, and a human-readable `detail` capturing the evidence (for example, the from-and-to states or the amounts involved). The subject reference is deliberately not a constrained foreign key: audit entries must survive the lifecycle of whatever record they describe, so `entity_type` and `entity_id` are plain strings.

The `event_type` of an entry is one of `CONTENT_APPROVED`, `CONTENT_REJECTED`, `CONTENT_RETIRED`, `ENROLLMENT_COMPLETED`, `ENROLLMENT_VOIDED`, `ATTESTATION_ATTESTED`, `ATTESTATION_VOIDED`, `ASSIGNMENT_LAPSED`, `ASSIGNMENT_COMPLETED`, `REGISTRATION_STATUS_CHANGED`, `PRODUCT_LAUNCHED`, `CERTIFICATION_STATUS_CHANGED`, `ENFORCEMENT_SWEEP_RUN`, `PLAN_PUBLISHED`, `PLAN_CLOSED`, or `PLAN_REOPENED`. For events driven by the enforcement sweep rather than by a human request, `actor_user_id` and `actor_role` are recorded as `system`.

The log is queryable through a dedicated list endpoint restricted to the `Auditor` and `ComplianceOfficer` roles, filterable by `entity_type`, `entity_id`, and `event_type`. Entries are never updated and never deleted.

### 2.10. Cascades and Atomic Side Effects

Many operations in this domain do more than flip one record's status. Lapsing an assignment deactivates a registration; voiding a completion can reopen a closed plan and void its attestation; retiring content cancels sessions and suspends certifications. The system applies every such side effect atomically within the triggering request: either the primary transition and all of its cascades commit together, or the request fails and nothing changes. There are no deferred or eventually-consistent effects anywhere in the API.

Each record touched by a cascade is independently mutated: its own `updated_at` is refreshed and its own `version` is incremented, so downstream optimistic-concurrency checks observe the change. Terminal, non-credit enrollment states — `CANCELLED`, `EXPIRED`, `VOIDED`, and `FAILED` — are excluded from every hour aggregation in the system, which is what makes cascades like cancellation and voiding automatically subtract their hours from plans and licenses.

## 3. Business Logic & Workflows

### 3.1. Registering Representatives and Managing Registration Standing

A `TrainingAdmin` registers a new representative by supplying the rep's `crd_number`, `full_name`, `email`, `role_tier`, `insurance_licensed` flag, and `resident_state_code`, with an optional `prior_year_excess_hours` carrying firm element excess credit forward from the prior plan year. The `crd_number` must be unique across all representatives; a second registration with an existing number is rejected with `ERR_DUPLICATE_CRD_NUMBER`. The `role_tier` is either `RR` or `PRINCIPAL` and drives the rep's firm element base hours (see §3.6). The `insurance_licensed` flag records whether the rep also holds a state insurance license, which determines whether state CE licenses may be registered for them (see §3.8). When omitted, `prior_year_excess_hours` defaults to zero; it may never be negative.

Every new representative begins with `registration_status` set to `ACTIVE`. From there the value is system-managed across three states — `ACTIVE`, `INACTIVE_CE`, and `TERMINATED` — and it gates almost everything the rep can do: enrollment creation, starting, completing, and reattempting coursework, as well as the creation of regulatory assignments and firm element plans, all require the rep to be `ACTIVE`. An operation attempted for an `INACTIVE_CE` rep is rejected with `ERR_REGISTRATION_INACTIVE`; for a `TERMINATED` rep, with `ERR_REGISTRATION_TERMINATED`.

Termination is a `ComplianceOfficer` action available from either `ACTIVE` or `INACTIVE_CE`; terminating an already-`TERMINATED` rep is rejected with `ERR_REGISTRATION_TERMINATED`. Termination cascades broadly: every enrollment of the rep in `ENROLLED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED`, releasing any session seats those enrollments held; every product certification in `PENDING_TRAINING` or `CERTIFIED` moves to `SUSPENDED` with `suspended_reason` set to `REGISTRATION_TERMINATED`; every annual attestation still `PENDING` is `VOIDED`; and a `REGISTRATION_STATUS_CHANGED` audit event is recorded. `TERMINATED` is final — no transition leaves it. The representative roster list can be filtered by `registration_status`.

The reverse journey — `INACTIVE_CE` back to `ACTIVE` — is never performed directly. It happens only as the cure cascade of a lapsed regulatory assignment being completed, described in §3.5.

### 3.2. Training Content: Authoring, Approval, and Retirement

Training content is the atom of the whole CE operation. A `TrainingAdmin` authors a course by supplying a unique `code`, a `title`, a `ce_category` of `REGULATORY_ELEMENT`, `FIRM_ELEMENT`, `PRODUCT`, or `STATE_INSURANCE`, a `delivery_format` of `ELEARNING` or `INSTRUCTOR_LED`, the `credit_hours` awarded on completion (greater than zero, at most two decimal places), and the `min_passing_score` — a whole number between 0 and 100 inclusive that a completion `score` must meet or exceed to pass. Reusing an existing course code is rejected with `ERR_DUPLICATE_CONTENT_CODE`. New content starts in `DRAFT`, and the server records the author's `X-User-ID` as `author_user_id` — the segregation-of-duties anchor used at approval time. The `content_status` lifecycle runs `DRAFT` → `PENDING_APPROVAL` → `APPROVED`, with a rejection-and-rework loop and a terminal `RETIRED`.

While content is in `DRAFT` or `REJECTED`, the author may edit it; edits against content in any other status are rejected with `ERR_CONTENT_NOT_EDITABLE`. An edit must carry `expected_content_version` per §2.7, and may revise the `title`, `credit_hours`, or `min_passing_score`. Every accepted edit increments the content's `version`. Editing content that sits in `DRAFT` leaves it in `DRAFT` (a same-state edit); editing content that sits in `REJECTED` returns it to `DRAFT` and clears both `rejection_reason` and `approved_by_user_id`, resetting the rework loop. Submitting moves content from `DRAFT` to `PENDING_APPROVAL`; submitting content in any other status is rejected with `ERR_CONTENT_NOT_EDITABLE`.

Approval belongs to a `ComplianceOfficer` and requires the content to be in `PENDING_APPROVAL` — approving or rejecting content in any other status is rejected with `ERR_CONTENT_NOT_PENDING_APPROVAL`. The approver's `X-User-ID` must differ from the content's `author_user_id`; an author attempting to approve their own course is rejected with `ERR_SOD_AUTHOR_CANNOT_APPROVE`. A successful approval stamps `approved_by_user_id` with the approver's identity and writes a `CONTENT_APPROVED` audit event. A rejection carries a `reason` in the request, which is recorded as the content's `rejection_reason`, and writes a `CONTENT_REJECTED` event; from `REJECTED`, the only way forward is the rework edit described above.

Only `APPROVED` content can do work in the system: enrolling, starting, completing, or reattempting coursework against content that is not `APPROVED` is rejected with `ERR_CONTENT_NOT_APPROVED`; an instructor-led session may be scheduled only for `APPROVED` content; and a product may launch only while its required training content is `APPROVED`.

Retirement is the content endgame. A `ComplianceOfficer` may retire content that is `APPROVED`; retiring content in any other status is rejected with `ERR_CONTENT_NOT_RETIRABLE`. Retirement is a cascade: every enrollment in the content that is `ENROLLED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED` (session-linked ones release their seats); every still-`SCHEDULED` session of the content moves to `CANCELLED`; and every product certification in `CERTIFIED` whose product's `required_training_content_id` is this content moves to `SUSPENDED` with `suspended_reason` set to `CONTENT_RETIRED`. A `CONTENT_RETIRED` audit event completes the action. `RETIRED` is terminal. The content catalogue list can be filtered by `ce_category` and `content_status`.

### 3.3. Scheduling Delivery: Sessions, Rooms, and Blackout Windows

Instructor-led delivery happens through course sessions. A `TrainingAdmin` schedules a session by supplying the `content_id` of the course being delivered, a `room_name`, the `start_at` and `end_at` instants, and a seat `capacity` of at least one. The referenced content must exist and be `APPROVED`, otherwise `ERR_CONTENT_NOT_APPROVED`. The session window must end strictly after it starts, otherwise `ERR_WINDOW_INVALID`; for overlap purposes `start_at` is inclusive and `end_at` is exclusive.

Two scheduling conflict rules protect the calendar. First, rooms cannot be double-booked: a new session conflicts with an existing one when both share the same `room_name`, the existing session has not been `CANCELLED`, and each session starts strictly before the other ends — because the end instant is exclusive, back-to-back sessions, where one starts exactly when the other ends, do not conflict. A violating request is rejected with `ERR_ROOM_CONFLICT`. Second, a `ComplianceOfficer` may declare firm-wide training blackout windows, each carrying a `label` plus `start_at` and `end_at` forming a closed interval — both endpoints inclusive — whose end must be strictly after its start (`ERR_WINDOW_INVALID`). A session conflicts with a blackout window when the session's `start_at` is at or before the blackout's `end_at` and the blackout's `start_at` is at or before the session's `end_at`; because the blackout interval is closed, merely touching a blackout boundary already conflicts, and the scheduling request is rejected with `ERR_BLACKOUT_CONFLICT`.

A new session starts in `SCHEDULED` with `available_seats` equal to its `capacity`. Seat accounting is a conserved invariant: `available_seats` always equals `capacity` minus the number of enrollments linked to the session that are in `ENROLLED`, `IN_PROGRESS`, or `COMPLETED`; enrollments in `FAILED`, `CANCELLED`, `EXPIRED`, or `VOIDED` hold no seat. The invariant must hold after every mutation — in particular, an enroll-then-cancel pair on the same session returns `available_seats` to exactly its pre-enrollment value.

A `TrainingAdmin` may cancel a session while it is `SCHEDULED`; cancelling a session in any other status is rejected with `ERR_SESSION_NOT_SCHEDULED`. Cancelling a session cascades to its linked enrollments in `ENROLLED` or `IN_PROGRESS`, moving each to `CANCELLED` and releasing their seats. Sessions are never marked as held by hand: when the enforcement sweep runs, every `SCHEDULED` session whose `end_at` has been reached or passed by the logical clock moves to `DELIVERED`. Both `DELIVERED` and `CANCELLED` are terminal for a session. The session list can be filtered by `content_id` and `session_status`.

### 3.4. Enrollment Delivery Tracking: Start, Completion, Retake, and Void

An enrollment records one representative's pursuit of one course. A `TrainingAdmin` creates it by supplying the `rep_id` of the enrolled rep plus exactly one of `content_id` or `session_id`: supplying neither, or both, is rejected with `ERR_INVALID_REQUEST`. The delivery format of the course governs which identifier is lawful. For `ELEARNING` content, the enrollment references the content directly through `content_id` and a `session_id` is forbidden; for `INSTRUCTOR_LED` content, a `session_id` is required and the enrolled content is derived from the session — a `content_id` may accompany it, but if it does not match the session's content the request is rejected with `ERR_INVALID_REQUEST`. Creation further requires the rep to be `ACTIVE` (per §3.1's registration guard), the content to be `APPROVED` (`ERR_CONTENT_NOT_APPROVED`), and — when session-linked — the session to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`) with at least one seat still free, meaning the session's active seat holders are fewer than its `capacity` (`ERR_SESSION_FULL`). Finally, the rep must not already hold an active enrollment for the same content: a second enrollment for the same `rep_id` and content while one exists in `ENROLLED` or `IN_PROGRESS` is rejected with `ERR_DUPLICATE_ENROLLMENT`.

A new enrollment starts in `ENROLLED` with `attempt_count` at zero and an expiry of `expires_at` set ninety days after creation. When session-linked, creation consumes a seat per the invariant of §3.3.

The rep drives the delivery lifecycle personally. Starting an enrollment — available only to the `RegisteredRep` whose `X-User-ID` matches the enrollment's `rep_id`, otherwise `ERR_OWNERSHIP_REQUIRED` — moves it from `ENROLLED` to `IN_PROGRESS`. Starting requires the rep to be `ACTIVE`, the logical clock to be no later than `expires_at` (a request exactly at `expires_at` is still valid; a later one is rejected with `ERR_ENROLLMENT_EXPIRED`), the content to be `APPROVED`, and, for session-linked enrollments, the session still to be `SCHEDULED`. Starting an enrollment that is not in `ENROLLED` is rejected with `ERR_ENROLLMENT_INVALID_STATE`.

Completing an enrollment is the same rep's act of recording a `score`, an integer from 0 to 100. Completion requires the enrollment to be `IN_PROGRESS` (otherwise `ERR_ENROLLMENT_INVALID_STATE`), with the same ownership, registration-standing, expiry, and content-approval guards as starting. When the `score` meets or exceeds the content's `min_passing_score`, the enrollment moves to `COMPLETED`: `attempt_count` increments by one, `last_score` records the score, and `completed_at` is stamped from the logical clock. When the `score` falls short, the enrollment moves to `FAILED` instead — `attempt_count` still increments and `last_score` is still recorded, but no credit hours accrue anywhere. The retake cycle lets a rep recover: reattempting a `FAILED` enrollment returns it to `ENROLLED` and recomputes `expires_at` as a fresh ninety-day window from that moment, but only while `attempt_count` is still below three — once three attempts have been recorded, reattempt is rejected with `ERR_MAX_ATTEMPTS_REACHED`. Reattempting an enrollment in any state other than `FAILED` is rejected with `ERR_ENROLLMENT_INVALID_STATE`, and the same ownership, registration-standing, and content-approval guards apply.

A passing completion is where credit flows outward, and the cascade depends on the content's `ce_category`:

- For `FIRM_ELEMENT` content, the system recomputes the progress hours of the matching firm element plan — the plan owned by the same rep whose `plan_year` equals the calendar year of the new `completed_at` and whose status is `PLAN_PUBLISHED` or `CLOSED` (see §3.6).
- For `REGULATORY_ELEMENT` content, the fulfillment selector of §3.5 runs: the rep's open assignment, if any, is marked `COMPLETED` with this enrollment recorded as its `enrollment_id`, and the registration-restoration cascade fires when appropriate.
- For `PRODUCT` content, every certification of this rep in `PENDING_TRAINING` whose product's `required_training_content_id` is the completed content moves to `CERTIFIED`, with `enrollment_id` and `certified_at` set and a `CERTIFICATION_STATUS_CHANGED` event written.
- For `STATE_INSURANCE` content, the rep's state CE license hour counters are recomputed per §3.8.

In all four cases an `ENROLLMENT_COMPLETED` audit event is written.

Cancellation is a `TrainingAdmin` action available while an enrollment is `ENROLLED` or `IN_PROGRESS` — cancelling from any other state is rejected with `ERR_ENROLLMENT_INVALID_STATE` — and the same transition also fires as part of the session-cancel, content-retire, and termination cascades. Cancellation releases the session seat when the enrollment was session-linked, and since `CANCELLED` rows are excluded from every hour aggregation, any hours the enrollment contributed disappear: cancelling an `IN_PROGRESS` enrollment drops its credit hours from the matching plan's `projected_hours`.

Voiding is the audit-correction path, reserved for a `ComplianceOfficer` and applicable only to a `COMPLETED` enrollment (otherwise `ERR_ENROLLMENT_INVALID_STATE`). The request must carry a `justification` of at least ten characters (`ERR_INVALID_REQUEST`). Voiding reverses everything the completion caused, category by category. A session-linked void releases the seat. For `FIRM_ELEMENT` content, the matching plan's hours are recomputed; if that plan was `CLOSED` and the recomputed `certified_hours` now fall below its `required_hours`, the plan reopens — `CLOSED` back to `PLAN_PUBLISHED`, with `closed_at` cleared — and its annual attestation, if `ATTESTED`, is `VOIDED`; `PLAN_REOPENED` and `ATTESTATION_VOIDED` events are written. For `STATE_INSURANCE` content, the license's hour counters are recomputed. For `REGULATORY_ELEMENT` content, if a `COMPLETED` assignment names this enrollment in its `enrollment_id`, that assignment is reverted according to the current logical clock: at or before its `due_at` it returns to `ASSIGNED`; later than `due_at` but not later than `lapse_after` it becomes `OVERDUE`; strictly later than `lapse_after` it becomes `LAPSED`, and that fresh lapse re-runs the registration cascade — the rep moves to `INACTIVE_CE` and their `CERTIFIED` certifications are suspended with `suspended_reason` set to `REGISTRATION_INACTIVE`. Either way the assignment's `enrollment_id` and `completed_at` are cleared. For `PRODUCT` content, a `CERTIFIED` certification that this enrollment fulfilled moves to `SUSPENDED` with `suspended_reason` set to `TRAINING_VOIDED`. The enrollment itself lands in `VOIDED`, and an `ENROLLMENT_VOIDED` event is recorded.

Finally, enrollments expire. When the enforcement sweep runs, every enrollment in `ENROLLED` or `IN_PROGRESS` whose `expires_at` is strictly earlier than the logical clock moves to `EXPIRED`, releasing its session seat if it held one; an enrollment whose `expires_at` exactly equals the clock remains valid. `CANCELLED`, `EXPIRED`, and `VOIDED` are terminal enrollment states. The enrollment list can be filtered by `rep_id`, `content_id`, `session_id`, and `enrollment_status`.

### 3.5. Regulatory Element Assignments and Registration Enforcement

The regulatory element is administered as one assignment per cycle. A `TrainingAdmin` assigns a cycle by supplying the `rep_id` of an `ACTIVE` representative and the `cycle_year`. A rep may hold at most one open assignment at a time: creating one while the rep already has an assignment in `ASSIGNED`, `OVERDUE`, or `LAPSED` is rejected with `ERR_OPEN_ASSIGNMENT_EXISTS`. The assignment clock starts at creation — `due_at` is exactly 120 days after creation, and `lapse_after` is a further 30 days beyond that — and the new assignment begins in `ASSIGNED`.

Deadline classification is the sweep's job. An `ASSIGNED` assignment whose `due_at` is earlier than the logical clock, while the clock has not yet passed `lapse_after`, moves to `OVERDUE`. An assignment in `ASSIGNED` or `OVERDUE` once the clock is strictly later than `lapse_after` moves to `LAPSED`, and lapsing is the most consequential automated transition in the system: the representative's `registration_status` flips from `ACTIVE` to `INACTIVE_CE` (recorded as `REGISTRATION_STATUS_CHANGED`), that registration flip in turn moves every one of the rep's product certifications in `CERTIFIED` to `SUSPENDED` with `suspended_reason` set to `REGISTRATION_INACTIVE` (each recorded as `CERTIFICATION_STATUS_CHANGED`), and an `ASSIGNMENT_LAPSED` event is written. While `INACTIVE_CE`, the rep is locked out of training delivery and new obligations per the registration guard of §3.1.

Fulfillment arrives through coursework. When a rep completes an enrollment in `REGULATORY_ELEMENT` content, the system selects the assignment that enrollment fulfills: among the rep's assignments in `ASSIGNED`, `OVERDUE`, or `LAPSED`, the one with the earliest `due_at` wins, with ties broken by the earliest `created_at`. Because creation forbids a second open assignment, there is at most one candidate in practice; if the candidate set is empty, the completion still succeeds and simply touches no assignment. The selected assignment moves to `COMPLETED` with `enrollment_id` and `completed_at` set, and an `ASSIGNMENT_COMPLETED` event is written. Completion at or before `due_at` counts as on time — the boundary is inclusive, so finishing exactly at `due_at` is on time — while completion after `due_at` but not later than `lapse_after` is a late completion within grace, and completion after `lapse_after` is a cure of an already-lapsed assignment.

Curing a lapse reverses the damage, but only once the rep is fully clear: when the completed assignment had been `LAPSED` and no other `LAPSED` assignment remains for the rep, the representative's `registration_status` returns from `INACTIVE_CE` to `ACTIVE` (again recorded as `REGISTRATION_STATUS_CHANGED`), and each certification that was suspended with reason `REGISTRATION_INACTIVE` returns to `CERTIFIED` — but only where the product is still `LAUNCHED` and its required training content is still `APPROVED`; certifications whose product or content no longer qualifies remain suspended and must go through reinstatement (§3.7). `COMPLETED` is terminal for an assignment. The assignment list can be filtered by `rep_id`, `assignment_status`, and `enrollment_id`.

### 3.6. Firm Element Plans, Needs Analysis, and the Annual Attestation

The firm element is planned per representative per calendar year. A `TrainingAdmin` opens a plan by supplying the `rep_id` of an `ACTIVE` representative, the `plan_year`, and — per the optimistic-concurrency rule of §2.7 — the `expected_representative_version` matching the rep's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Creation bumps the representative's `version` by one, which is exactly why the OCC field exists. Two plans for the same rep and year cannot both be live: if a plan in `NEEDS_ANALYSIS` already exists for the same rep and `plan_year`, the new plan supersedes it, moving the old draft to `SUPERSEDED`; if instead a `PLAN_PUBLISHED` or `CLOSED` plan already exists for that rep and year, the create is rejected with `ERR_DUPLICATE_PLAN_YEAR`. A new plan begins in `NEEDS_ANALYSIS`, with `certified_hours` and `projected_hours` starting at zero and `required_hours` unset until publish.

Before a plan can be published, its needs analysis must be on record. While the plan is in `NEEDS_ANALYSIS` — otherwise the request is rejected with `ERR_PLAN_NOT_NEEDS_ANALYSIS` — a `TrainingAdmin` records the analysis by supplying an `analysis_document_ref` and free-text `analysis_notes`; the server stores them as the plan's `needs_analysis_document_ref` and `needs_analysis_notes` and stamps `needs_analysis_completed_at` from the logical clock. Recording the analysis is a same-state operation and may be repeated to refine it while the plan remains a draft.

Publishing moves the plan from `NEEDS_ANALYSIS` to `PLAN_PUBLISHED`. It requires the needs analysis to have been completed — publishing without it is rejected with `ERR_NEEDS_ANALYSIS_MISSING` — and it is the moment the year's requirement is fixed. The computation runs in a pinned order: begin with the tier base, 12 hours for a rep whose `role_tier` is `RR` or 16 hours for `PRINCIPAL`; add a product surcharge of 2 hours per product launched during the plan year, counting products in `LAUNCHED` or `WITHDRAWN` status whose `launched_at` falls within `plan_year`, and counting at most 3 such products; subtract the rep's `prior_year_excess_hours`; and if the result would fall below 6 hours, the requirement is 6. The result is a whole number of hours, stored as the plan's `required_hours` at publish and never recomputed afterward, however the world changes later. Publishing also stamps `published_at`, recomputes the plan's progress hours once, creates the plan's annual attestation in `PENDING` with its `rep_id` copied from the plan, and writes a `PLAN_PUBLISHED` event.

Progress against the requirement is tracked in two variants, both recomputed on every enrollment mutation — creation, start, completion, cancellation, void, or expiry — and on any content retirement that cancels one of the rep's `FIRM_ELEMENT` enrollments. The plan's `certified_hours` is the sum of `credit_hours` over the rep's `COMPLETED`, non-voided enrollments in `FIRM_ELEMENT` content whose `completed_at` falls in the calendar year `plan_year`. The plan's `projected_hours` is `certified_hours` plus the `credit_hours` of the rep's `IN_PROGRESS` `FIRM_ELEMENT` enrollments; because in-progress rows carry no `completed_at`, the plan-year filter applies only to completed rows, and `projected_hours` is therefore always at least `certified_hours`. Both values are held at two decimal places, rounded half up, and `CANCELLED`, `EXPIRED`, `VOIDED`, and `FAILED` enrollments never contribute to either. The certified variant governs close eligibility, attestation gating, and reopen checks; the projected variant is a readiness projection surfaced when the plan is read.

Closing the plan is the year's sign-off: a `TrainingAdmin` may close a plan that is `PLAN_PUBLISHED` — otherwise `ERR_PLAN_NOT_PUBLISHED` — only once its `certified_hours` are at least its `required_hours`; closing short of the requirement is rejected with `ERR_PLAN_HOURS_UNMET`. Closing stamps `closed_at` and writes a `PLAN_CLOSED` event. Once the plan is `CLOSED`, the rep personally executes the annual attestation: the `RegisteredRep` whose identity matches the plan's `rep_id` (otherwise `ERR_OWNERSHIP_REQUIRED`) attests while the attestation is `PENDING` (otherwise `ERR_ATTESTATION_NOT_PENDING`) and the plan is `CLOSED` (otherwise `ERR_PLAN_NOT_CLOSED`), supplying the `attestation_statement`; the server records the statement and stamps `attested_at`, moves the attestation to `ATTESTED`, and writes an `ATTESTATION_ATTESTED` event.

The reopen loop keeps closed plans honest. If a `COMPLETED` enrollment crediting a `CLOSED` plan is later voided and the recomputed `certified_hours` drop below `required_hours`, the plan reopens from `CLOSED` back to `PLAN_PUBLISHED`, its `closed_at` is cleared, an attestation in `ATTESTED` on that plan is `VOIDED`, and `PLAN_REOPENED` and `ATTESTATION_VOIDED` events are written. Attestations are also voided outright — from `PENDING`, with no event of their own — when the rep's registration is terminated. `VOIDED` is terminal for an attestation, and `SUPERSEDED` is terminal for a plan. The plan list can be filtered by `rep_id`, `plan_year`, and `plan_status`; the attestation list by `rep_id`, `plan_id`, and `attestation_status`.

### 3.7. Product Offerings and Selling Certifications

Product-specific training gates the sale of new offerings. A `ComplianceOfficer` registers a product by supplying a unique `product_code` — a duplicate is rejected with `ERR_DUPLICATE_PRODUCT_CODE` — a `name`, and the `required_training_content_id` of the product-specific course that gates selling. A new offering begins in `PROPOSED`.

Launching is the trigger that creates training obligations across the roster. A `ComplianceOfficer` may launch a product in `PROPOSED` — launching from any other status is rejected with `ERR_PRODUCT_NOT_PROPOSED` — and only while the content named by `required_training_content_id` is `APPROVED`, otherwise `ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED`. Launching stamps `launched_at`, writes a `PRODUCT_LAUNCHED` event, and fans out: one product certification in `PENDING_TRAINING` is created for every representative whose `registration_status` is `ACTIVE` at that moment, processed in `created_at` ascending order with `crd_number` ascending as the tie-break. Representatives in `INACTIVE_CE` or `TERMINATED` receive no certification.

Each certification then tracks whether its rep may sell the product, moving among `PENDING_TRAINING`, `CERTIFIED`, and `SUSPENDED`. When the rep completes an enrollment whose content is the product's `required_training_content_id`, the matching certification moves from `PENDING_TRAINING` to `CERTIFIED`, with `enrollment_id` and `certified_at` set and a `CERTIFICATION_STATUS_CHANGED` event written. Certifications are pulled back to `SUSPENDED` by five distinct cascades, each leaving its cause in `suspended_reason`: a registration lapse or a void-driven lapse suspends `CERTIFIED` certifications with `REGISTRATION_INACTIVE`; termination suspends certifications in either `PENDING_TRAINING` or `CERTIFIED` with `REGISTRATION_TERMINATED`; retiring the required content suspends `CERTIFIED` certifications with `CONTENT_RETIRED`; withdrawing the product suspends certifications in either `PENDING_TRAINING` or `CERTIFIED` with `PRODUCT_WITHDRAWN`; and voiding the fulfilling enrollment suspends a `CERTIFIED` certification with `TRAINING_VOIDED`. Withdrawal itself is a `ComplianceOfficer` action on a `LAUNCHED` product — withdrawing from any other status is rejected with `ERR_PRODUCT_NOT_LAUNCHED` — and leaves the product in `WITHDRAWN`, which is terminal.

Reinstatement is the controlled way back. A `ComplianceOfficer` may reinstate a certification that is `SUSPENDED` — otherwise `ERR_CERTIFICATION_NOT_SUSPENDED` — and only when all three gates hold: the representative's `registration_status` is `ACTIVE`, the product is `LAUNCHED`, and the certification's `enrollment_id` is set and names an enrollment that is `COMPLETED` whose content is still `APPROVED`. Failing any of those gates rejects the request with `ERR_REINSTATEMENT_BLOCKED`. A successful reinstatement returns the certification to `CERTIFIED`, clears `suspended_reason`, and writes a `CERTIFICATION_STATUS_CHANGED` event. Reinstatement also happens automatically, without an explicit request, as part of the registration-restoration cascade of §3.5 — but only for certifications suspended with reason `REGISTRATION_INACTIVE` whose product is `LAUNCHED` and whose required content is `APPROVED`. The product catalogue list can be filtered by `product_status` and `required_training_content_id`; the certification list by `rep_id`, `product_id`, `enrollment_id`, and `cert_status`.

### 3.8. State Insurance CE Licenses and Carryover

Representatives who also hold state insurance licenses carry a separate CE obligation per licensing state. A `TrainingAdmin` registers a state CE license for a rep by supplying the `rep_id`, the two-letter `state_code`, the `required_hours` for each renewal period (greater than zero), and the current renewal window as `period_start` and `period_end`. The rep must be flagged `insurance_licensed`, otherwise `ERR_REP_NOT_INSURANCE_LICENSED`; a rep may hold only one license per state, otherwise `ERR_DUPLICATE_LICENSE_STATE`; and the window's `period_end` must be strictly later than its `period_start`, otherwise `ERR_WINDOW_INVALID`. For hour-counting purposes the window is half-open: completions count when `completed_at` is on or after `period_start` and strictly before `period_end`. A new license begins in `ACTIVE` with `carried_excess_hours` at zero and its hour counters at zero.

Three hour counters track the license, each recomputed whenever one of the rep's `STATE_INSURANCE` enrollments completes or is voided, and once more at renewal. `earned_hours_strict` is the sum of `credit_hours` over the rep's `COMPLETED`, non-voided `STATE_INSURANCE` enrollments whose `completed_at` falls inside the current window. `earned_hours_effective` is `earned_hours_strict` plus the carried excess, with the carried portion capped at 6 hours — carried credit beyond six hours never counts. `reported_hours` covers the same window set as `earned_hours_strict` but rounds per course before summing: each course's `credit_hours` is rounded half up to the nearest half hour — equivalently, the hours are doubled, rounded half up to a whole number, then halved — and the per-course values are then summed exactly. The order is pinned and not interchangeable with rounding the total: two courses of 1.25 hours each report 3.0 hours (each rounds to 1.5), whereas summing first and rounding would yield 2.5 and is non-conforming. All three counters are held at two decimal places, rounded half up.

The strict and effective variants answer different questions. `earned_hours_strict` is the raw display of current-window work and the basis for computing carryover at renewal. `earned_hours_effective` is the compliance measure: when the enforcement sweep runs and finds the logical clock strictly later than a license's `period_end` while `earned_hours_effective` remains below `required_hours`, the license moves from `ACTIVE` to `LAPSED`. A license whose effective hours meet the requirement survives the sweep untouched, as does any license whose period has not yet ended.

Renewal rolls the license forward and is available from either `ACTIVE` or `LAPSED`. A `TrainingAdmin` renews by supplying `new_period_start` and `new_period_end`, which must end strictly after it begins (`ERR_WINDOW_INVALID`). Before the window is replaced, the carryover is computed from the closing window: `carried_excess_hours` becomes the smaller of 6 hours and the positive part of `earned_hours_strict` minus `required_hours` — zero when the rep earned no more than required. The window is then replaced by the new period, the hour counters are recomputed against it, and the license lands in `ACTIVE`. The license list can be filtered by `rep_id`, `state_code`, and `license_status`.

### 3.9. Running the Enforcement Sweep

The enforcement sweep is the single checkpoint where deadlines bite. A `ComplianceOfficer` runs it against the current logical clock, and it evaluates four phases in a pinned order — sessions, then enrollments, then assignments, then licenses — applying every transition whose preconditions the clock has reached.

In the session phase, each `SCHEDULED` session whose `end_at` is at or before the clock becomes `DELIVERED`. In the enrollment phase, each enrollment in `ENROLLED` or `IN_PROGRESS` whose `expires_at` is strictly earlier than the clock becomes `EXPIRED`, releasing any session seat it held; an enrollment expiring exactly at the clock survives. In the assignment phase, `ASSIGNED` assignments past `due_at` but not past `lapse_after` become `OVERDUE`, and assignments past `lapse_after` become `LAPSED` with the full registration-and-certification cascade of §3.5. In the license phase, each `ACTIVE` license whose `period_end` is strictly earlier than the clock and whose `earned_hours_effective` is below its `required_hours` becomes `LAPSED`.

The sweep's response reports, in order, how many records each phase moved: `sessions_marked_delivered`, `enrollments_expired`, `assignments_marked_overdue`, `assignments_lapsed`, and `licenses_lapsed`. An `ENFORCEMENT_SWEEP_RUN` audit event closes the epoch, and every audit entry the sweep's cascades generate — lapses, registration changes, certification suspensions — is recorded with `actor_user_id` and `actor_role` set to `system` rather than to the operator who ran it. Remember that the sweep is the only clock-driven actor in the system: setting the logical clock to a future instant changes no record until a sweep is run.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including state transitions, cascades, and counter updates — return a `200 OK`. The table below is a routing summary only; the full request and response semantics of each operation are defined by the narratives of Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/representatives` | Register a representative | TrainingAdmin |
| GET    | `/representatives` | List representatives | Any |
| GET    | `/representatives/{repId}` | Get one representative | Any |
| POST   | `/representatives/{repId}/terminate` | Terminate a registration (cancels enrollments, suspends certifications, voids pending attestations) | ComplianceOfficer |
| POST   | `/contents` | Author training content (starts in DRAFT) | TrainingAdmin |
| GET    | `/contents` | List content | Any |
| GET    | `/contents/{contentId}` | Get one content | Any |
| PUT    | `/contents/{contentId}` | Edit content in DRAFT/REJECTED (optimistic concurrency; REJECTED returns to DRAFT) | TrainingAdmin |
| POST   | `/contents/{contentId}/submit` | Submit content for approval | TrainingAdmin |
| POST   | `/contents/{contentId}/approve` | Approve content (approver must differ from author) | ComplianceOfficer |
| POST   | `/contents/{contentId}/reject` | Reject content with a reason | ComplianceOfficer |
| POST   | `/contents/{contentId}/retire` | Retire approved content (cancels non-terminal enrollments and sessions; suspends dependent certifications) | ComplianceOfficer |
| POST   | `/sessions` | Schedule an instructor-led session (content must be APPROVED; room and blackout conflict checks) | TrainingAdmin |
| GET    | `/sessions` | List sessions | Any |
| GET    | `/sessions/{sessionId}` | Get one session | Any |
| POST   | `/sessions/{sessionId}/cancel` | Cancel a scheduled session (cancels linked non-terminal enrollments) | TrainingAdmin |
| POST   | `/enrollments` | Enroll a representative (exactly one of content or session reference) | TrainingAdmin |
| GET    | `/enrollments` | List enrollments | Any |
| GET    | `/enrollments/{enrollmentId}` | Get one enrollment | Any |
| POST   | `/enrollments/{enrollmentId}/start` | Rep starts own enrollment | RegisteredRep |
| POST   | `/enrollments/{enrollmentId}/complete` | Rep completes own enrollment with a score (pass triggers credit cascades) | RegisteredRep |
| POST   | `/enrollments/{enrollmentId}/cancel` | Cancel a non-terminal enrollment | TrainingAdmin |
| POST   | `/enrollments/{enrollmentId}/reattempt` | Retake a failed enrollment (at most three attempts; fresh validity window) | RegisteredRep |
| POST   | `/enrollments/{enrollmentId}/void` | Void a completed enrollment as audit correction (reverses hours, certifications, assignments) | ComplianceOfficer |
| POST   | `/regulatory-assignments` | Assign a regulatory element cycle (one open assignment per rep) | TrainingAdmin |
| GET    | `/regulatory-assignments` | List assignments | Any |
| GET    | `/regulatory-assignments/{assignmentId}` | Get one assignment | Any |
| POST   | `/firm-element-plans` | Create an annual firm element plan (optimistic concurrency on the representative; supersedes a draft for the same rep and year) | TrainingAdmin |
| GET    | `/firm-element-plans` | List plans | Any |
| GET    | `/firm-element-plans/{planId}` | Get one plan | Any |
| POST   | `/firm-element-plans/{planId}/needs-analysis` | Record the annual needs analysis for a draft plan | TrainingAdmin |
| POST   | `/firm-element-plans/{planId}/publish` | Publish the plan (computes required hours; spawns a PENDING attestation) | TrainingAdmin |
| POST   | `/firm-element-plans/{planId}/close` | Close a published plan once certified hours meet the requirement | TrainingAdmin |
| GET    | `/attestations` | List attestations | Any |
| GET    | `/attestations/{attestationId}` | Get one attestation | Any |
| POST   | `/attestations/{attestationId}/attest` | Rep attests own annual attestation (plan must be CLOSED) | RegisteredRep |
| POST   | `/products` | Register a product offering (starts in PROPOSED) | ComplianceOfficer |
| GET    | `/products` | List products | Any |
| GET    | `/products/{productId}` | Get one product | Any |
| POST   | `/products/{productId}/launch` | Launch a product (requires APPROVED training content; fans out PENDING_TRAINING certifications to ACTIVE reps) | ComplianceOfficer |
| POST   | `/products/{productId}/withdraw` | Withdraw a launched product (suspends its certifications) | ComplianceOfficer |
| GET    | `/product-certifications` | List certifications | Any |
| GET    | `/product-certifications/{certId}` | Get one certification | Any |
| POST   | `/product-certifications/{certId}/reinstate` | Reinstate a suspended certification | ComplianceOfficer |
| POST   | `/state-ce-licenses` | Register a state insurance CE license for a rep | TrainingAdmin |
| GET    | `/state-ce-licenses` | List licenses | Any |
| GET    | `/state-ce-licenses/{licenseId}` | Get one license | Any |
| POST   | `/state-ce-licenses/{licenseId}/renew` | Roll the license to a new renewal period (computes carryover from the closing window) | TrainingAdmin |
| POST   | `/blackout-windows` | Declare a training blackout window (closed interval) | ComplianceOfficer |
| GET    | `/blackout-windows` | List blackout windows | Any |
| GET    | `/blackout-windows/{windowId}` | Get one blackout window | Any |
| POST   | `/enforcement/sweep` | Run the deadline-enforcement epoch against the logical clock | ComplianceOfficer |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock (mutates no entity by itself) | ComplianceOfficer |
| GET    | `/audit-events` | Query the append-only audit evidence log | Auditor, ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions under which each error is raised are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_REQUIRED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_WINDOW_INVALID` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTENT_NOT_PENDING_APPROVAL` | 409 Conflict |
| `ERR_CONTENT_NOT_EDITABLE` | 409 Conflict |
| `ERR_CONTENT_NOT_RETIRABLE` | 409 Conflict |
| `ERR_CONTENT_NOT_APPROVED` | 409 Conflict |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ENROLLMENT_EXPIRED` | 409 Conflict |
| `ERR_MAX_ATTEMPTS_REACHED` | 409 Conflict |
| `ERR_SESSION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_REGISTRATION_INACTIVE` | 409 Conflict |
| `ERR_REGISTRATION_TERMINATED` | 409 Conflict |
| `ERR_PLAN_NOT_NEEDS_ANALYSIS` | 409 Conflict |
| `ERR_NEEDS_ANALYSIS_MISSING` | 409 Conflict |
| `ERR_PLAN_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PLAN_HOURS_UNMET` | 409 Conflict |
| `ERR_PLAN_NOT_CLOSED` | 409 Conflict |
| `ERR_ATTESTATION_NOT_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_CRD_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_CONTENT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_PRODUCT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE_STATE` | 409 Conflict |
| `ERR_OPEN_ASSIGNMENT_EXISTS` | 409 Conflict |
| `ERR_REP_NOT_INSURANCE_LICENSED` | 409 Conflict |
| `ERR_ROOM_CONFLICT` | 409 Conflict |
| `ERR_BLACKOUT_CONFLICT` | 409 Conflict |
| `ERR_PRODUCT_NOT_PROPOSED` | 409 Conflict |
| `ERR_PRODUCT_NOT_LAUNCHED` | 409 Conflict |
| `ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED` | 409 Conflict |
| `ERR_CERTIFICATION_NOT_SUSPENDED` | 409 Conflict |
| `ERR_REINSTATEMENT_BLOCKED` | 409 Conflict |
| `ERR_SOD_AUTHOR_CANNOT_APPROVE` | 403 Forbidden |

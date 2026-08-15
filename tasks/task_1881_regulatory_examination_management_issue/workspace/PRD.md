# Regulatory Exam Management API — Product Requirements Document

## 1. Introduction

A bank's regulatory affairs office lives in the space between its supervisors and its own remediation teams. When an agency such as the OCC, the FDIC, or a state regulator opens an examination, the office must coordinate the first-day letter and its dozens of document requests, log every examiner meeting, capture informal findings before they harden into formal Matters Requiring Attention, drive remediation plans through approval and execution, and ultimately prove to the regulator — and to the bank's own board — that each finding has been closed with sufficient evidence. Today this work is scattered across spreadsheets and shared drives, and the cost of a missed first-day item, an unescalated repeat finding, or a closure approved by the same officer who performed the remediation is measured in ratings downgrades and formal enforcement actions.

This document specifies the Regulatory Exam Management API, a single system of record for the full examination arc: scheduling and first-day-letter response coordination, quality-controlled document submissions, examiner meeting logs and informal finding capture, MRA/MRIA remediation planning with milestone tracking, validation evidence and closure adjudication under segregation of duties, repeat-finding risk scoring with board-level escalation, and immutable board reporting snapshots backed by a regulator commitment log. All endpoints are mounted under `/regulatory-exams`. The audience is the engineering team implementing the service; every behavioral rule below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. Five roles exist, spelled exactly as follows: `PlatformAdmin`, `RegulatoryAffairsManager`, `RemediationOwner`, `ComplianceReviewer`, and `BoardReporter`. A request whose headers are missing or malformed, or whose role string is not one of the five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated caller whose role is not permitted to invoke the requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles divide the work along a strict segregation-of-duties model. A `PlatformAdmin` is the system operator: it seeds regulator agencies, bank officers, and compliance reviewers, and it alone drives the logical clock. A `RegulatoryAffairsManager` runs the examination lifecycle itself — scheduling, issuing the first-day letter, advancing fieldwork and findings, opening remediation, closing or cancelling the examination, logging meetings and informal findings, filing formal issues, and recording regulator commitments. A `RemediationOwner` is the bank officer accountable for execution: document submissions, remediation plans, milestones, and validation evidence. A `ComplianceReviewer` is the independent checker: submission quality control, plan approval, evidence sufficiency, and closure adjudication. A `BoardReporter` generates and finalizes board reporting snapshots. Read endpoints across the entire surface are shared by all five roles; each write endpoint is restricted to the single role named in §4.

Identity is interpreted per role. When `X-User-Role` is `RemediationOwner`, `X-User-ID` is the `id` of the acting `BankOfficer`; ownership checks on any resource that references a `BankOfficer` — a remediation plan's `owner_user_id`, a validation evidence record's `submitted_by_user_id`, a commitment's `committed_by_user_id` — compare that field to `X-User-ID`. When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is the `id` of the acting `ComplianceReviewer`; the server records it as `reviewed_by_user_id` on closure requests the reviewer adjudicates, and segregation-of-duties comparisons evaluate it. When `X-User-Role` is `PlatformAdmin`, `RegulatoryAffairsManager`, or `BoardReporter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.

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

Every list endpoint accepts two query parameters. `limit` controls the page size: it defaults to 10, and any value from 1 up to and including 100 is accepted. `offset` controls how many records are skipped and defaults to 0. List responses are always sorted by `created_at` in ascending order — the oldest record first. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` reports whether additional records exist beyond the returned page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` minted by the server as a bare UUID — no type prefix, no human-readable slug. With one exception noted below, every resource also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and a `version` integer that starts at 1 and increments by exactly one on every mutation of that resource; `updated_at` refreshes to the mutation instant on the same occasions. The exception is the commitment log: a `CommitmentLogEntry` is an append-only record and carries only `id` and `created_at`. It has no `updated_at` and no `version` — once written, a commitment entry is never modified in place; its only later change is the `fulfilled_at` stamp described in §3.8, which is itself an immutable write-once field.

### 2.5. The Logical Clock

All date-sensitive behavior in this system — overdue detection, posture recalculation, business-day arithmetic — reads from a server-maintained logical clock, never from the real wall clock. Before any operator intervention the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Advancing the clock is a system event: it fires every clock-driven transition described in §3.8 (issues and milestones whose due dates have been crossed move to `OVERDUE`) and recomputes `overdue_item_count` and `posture` on every affected examination.

### 2.6. Date Arithmetic, Business-Day Counting, and Numeric Precision

Timestamps in requests and responses are ISO 8601 UTC. Computations that produce a pure date — the first-day-letter due date of §3.2 — have date granularity with no time component. Business-day counting treats Monday through Friday as business days and Saturday and Sunday as non-business days. Risk scoring is expressed in integer basis points; the one multiplication in that scoring — the repeat-finding weighting of §3.5 — rounds half up to a whole basis point before its product enters any sum. Counts and day spans are integers. Wherever a threshold comparison appears in this document, its inclusivity is stated explicitly, and those statements are normative: boundary values behave exactly as written.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to a parent entity's `version`. First, filing an issue against an examination (`POST /regulatory-exams/examinations/{id}/issues`) requires the request to carry `expected_examination_version`, the examination `version` the client last observed; this captures the case where another writer has filed an issue, modified the first-day-item roster, or transitioned the exam since the client's last read, leaving the client's view of the findings baseline stale. Second, adding a milestone to a remediation plan (`POST /regulatory-exams/remediation-plans/{id}/milestones`) requires `expected_plan_version`, the client-observed `version` of the plan; a client holding a stale plan view would otherwise interleave `sequence_index` values against a milestone roster that has already mutated. Third, approving a closure request (`POST /regulatory-exams/closure-requests/{id}/approve`) requires `expected_issue_version`, the client-observed `version` of the parent issue, which advances whenever the issue's state, evidence linkage, or escalation flag changes; approving against a stale version would silently close a materially different issue than the reviewer inspected.

In all three cases the expected-version field is non-optional, and a mismatch with the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named above take no version field at all — closure rejection, for example, carries only a `rejection_reason`.

### 2.8. Nested Retrieval and Referential Integrity

Paths that descend through a resource hierarchy are validated left to right: each path segment must resolve to an existing resource before the next is examined, and the first segment that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). Beyond path segments, every payload field whose name ends in `_id` is a reference that must point to an existing resource of the correct type and, where the resource lives inside an examination hierarchy, must belong to the same examination ancestry as the rest of the request. A reference that dangles — or that points into a different examination's subtree — is rejected with `ERR_INVALID_REFERENCE` (HTTP 422).

### 2.9. Request Evaluation Pipeline

When several checks could apply to one request, the server evaluates them in a single fixed order, and the first failing check determines the error response. The order is:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is recognized — otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Authorization.** The caller's role is permitted on this endpoint per §4 — otherwise `ERR_UNAUTHORIZED` (HTTP 403). Applies to every endpoint.
3. **Existence.** Every path-referenced resource exists — otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to every endpoint.
4. **State-machine preconditions.** The target resource's current state permits the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints. When the target already rests in a terminal state (`CLOSED`, `CANCELLED`, `SUBMITTED`, `WAIVED`, `ACCEPTED`, `REJECTED`, `FINALIZED`, `COMPLETE`, `SUPERSEDED`, `SUFFICIENT`, `INSUFFICIENT`, or `APPROVED`), the rejection instead carries `ERR_ALREADY_TERMINAL` (HTTP 409).
5. **Segregation of duties.** The reviewer must not be the owner of the issue's active remediation plan — otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Applies to exactly two operations: approving a closure request and rejecting a closure request.
6. **Reviewer certification.** The reviewer must hold `certification_level` `L3` when the underlying issue is an MRIA — otherwise `ERR_CERTIFICATION_INSUFFICIENT` (HTTP 422). Applies to exactly two operations: approving a remediation plan and approving a closure request.
7. **Optimistic concurrency.** The expected-version field matches the parent's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412). Applies to exactly the three operations named in §2.7.
8. **Examination schedule overlap.** The new examination's scheduled window must not overlap a live examination for the same agency — otherwise `ERR_EXAM_SCHEDULE_OVERLAP` (HTTP 422). Applies to examination creation only.
9. **Meeting date collision.** No `FINALIZED` meeting on the same examination may share the new meeting's UTC calendar date — otherwise `ERR_MEETING_DATE_CONFLICT` (HTTP 422). Applies to examiner-meeting creation only.
10. **Date-range sanity.** `scheduled_end_date` must be strictly after `scheduled_start_date`, and `reporting_period_end` must be on or after `reporting_period_start` — otherwise `ERR_INVALID_DATE_RANGE` (HTTP 400). Applies to examination creation and board-report generation.
11. **Uniqueness.** `agency_code` globally unique; `request_ref` unique within its examination; `issue_ref` unique within its examination; `sequence_index` unique within its plan — otherwise `ERR_DUPLICATE_KEY` (HTTP 409). Applies to agency creation, first-day-item creation, issue filing, and milestone creation.
12. **Referential integrity.** Every `_id` reference resolves to an existing resource of the correct type within the required ancestry — otherwise `ERR_INVALID_REFERENCE` (HTTP 422). Applies to every write carrying foreign-key fields.
13. **Posture gating.** A `FROZEN` examination accepts no new document submissions; a `RESTRICTED` or `FROZEN` examination accepts no new first-day items — otherwise `ERR_EXAM_POSTURE_FROZEN` (HTTP 422). Applies to submission creation and first-day-item creation.
14. **Request shape.** All required fields are present, enum values are valid, and arrays declared non-empty are non-empty — otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to every endpoint.

The ordering is observable behavior. A closure approval attempted by the plan's owner with a stale issue version, for instance, surfaces `ERR_SEGREGATION_OF_DUTIES`, because the segregation check (step 5) precedes the concurrency check (step 7); and a badly shaped payload against a resource in the wrong state surfaces `ERR_INVALID_STATE`, because state (step 4) precedes shape (step 14).

### 2.10. Segregation of Duties and Reviewer Certification

Two safety gates cut across the review workflow and deserve emphasis beyond their pipeline positions. The segregation-of-duties rule prohibits a `ComplianceReviewer` from adjudicating a closure request — in either direction, approval or rejection — when that reviewer's own `id` equals the `owner_user_id` of the issue's currently `ACTIVE` remediation plan. The comparison is the acting reviewer's identity against the recorded plan owner; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The rule guards exactly those two closure operations: document-submission quality control is not segregation-gated, and any active reviewer may QC any submission.

The certification gate reserves MRIA adjudication for the most senior reviewers. Whenever the underlying issue carries `classification` `MRIA`, the acting reviewer's `certification_level` must be `L3`; for an `MRA`, any of `L1`, `L2`, or `L3` suffices. The gate applies to remediation-plan approval and to closure-request approval, and a shortfall is rejected with `ERR_CERTIFICATION_INSUFFICIENT` (HTTP 422). A reviewer whose `active` flag is false may not perform any review action at all, and symmetrically a plan may not name an `owner_user_id` whose officer record is inactive, nor may a new examination be linked to an agency whose `active` flag is false.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Regulatory Cast: Agencies, Officers, and Reviewers

Before any examination can be scheduled, a `PlatformAdmin` provisions the cast. Registering a regulator agency captures its `agency_code` — a short code of one to twenty characters such as OCC or FDIC that must be globally unique and can never change after creation — together with the agency's full legal `agency_name` and its `jurisdiction`, one of `FEDERAL`, `STATE`, or `FOREIGN`. A duplicate `agency_code` is rejected with `ERR_DUPLICATE_KEY`. Two numeric policies ride on the agency record and shape everything downstream: `escalation_threshold_days`, an integer no smaller than 1 and no larger than 730 — an agency may demand board escalation after as little as a single overdue day or grant as much as two years of runway — and `repeat_finding_multiplier_bp`, an integer between 10,000 and 40,000 basis points, where 10,000 acts as a neutral 1.0x weight and 40,000 quadruples the severity of repeat findings. The `active` flag defaults to true; an agency that has been deactivated may not be linked to new examinations, though its history remains readable. Agency listings filter by `jurisdiction` and `active`.

Bank officers are registered with a `full_name`, a unique `email`, a business `officer_role_title` such as CRO or BSA Officer, and an `active` flag that defaults to true. An officer whose `active` flag is false cannot be assigned to new remediation plans. Officer listings filter by `active`. Compliance reviewers are registered with the same `full_name` and unique `email` shape, plus a `certification_level` of `L1`, `L2`, or `L3` that governs the MRIA gate of §2.10, and an `active` flag defaulting to true; inactive reviewers cannot perform reviews. Reviewer listings filter by `certification_level` and `active`.

### 3.2. Scheduling an Examination and the First-Day Letter

A `RegulatoryAffairsManager` opens the lifecycle by scheduling an examination: the payload names the supervising `agency_id`, a business `exam_cycle_code` such as 2026-SAFETY-Q3, an `exam_type` of `SAFETY_SOUNDNESS`, `COMPLIANCE`, `IT`, `TRUST`, or `SPECIALTY`, and the planned fieldwork window `scheduled_start_date` through `scheduled_end_date`. The end date must fall strictly after the start date — an equal pair is already invalid — with violations rejected as `ERR_INVALID_DATE_RANGE`. Scheduling also enforces exclusivity of the regulator's attention: for the same agency, the new window must not overlap any existing examination whose status is anything other than `CANCELLED` or `CLOSED`. Overlap is judged on half-open intervals — the windows collide when the new examination starts before the incumbent ends and the incumbent starts before the new one ends — so two windows that merely touch, one ending on the very day the other begins, do not collide. A genuine collision is rejected with `ERR_EXAM_SCHEDULE_OVERLAP`.

A freshly scheduled examination lands in `SCHEDULED` with `posture` `NORMAL`, an `overdue_item_count` of zero, and a `repeat_finding_risk_score_bp` of zero. Creation also computes the `first_day_letter_due_date` by counting ten business days forward from the scheduled start: when `scheduled_start_date` falls on a business day, that day itself counts as day one; when it falls on a Saturday or Sunday, the following Monday becomes day one. Counting then advances calendar day by calendar day, incrementing the count only on business days, until the count reaches ten — that tenth business day is the due date, inclusive. An examination starting on a Monday, for example, is due on the Friday of the following week.

Should the examination be called off before work begins, the manager may cancel it from `SCHEDULED` to `CANCELLED` by supplying a non-empty `cancelled_reason`; the reason is immutable once recorded, and `CANCELLED` is terminal. Otherwise, once the manager has composed the first-day roster — at least one first-day item must exist — issuing the first-day letter moves the examination `SCHEDULED` → `FIRST_DAY_ISSUED`.

Each first-day-letter item is added to the examination with a `request_ref` (the regulator's document-request reference number, unique within its examination — duplicates draw `ERR_DUPLICATE_KEY`), a narrative `description` of the requested documents, and the regulator-imposed `due_date`. Items begin `PENDING`. Two constraints guard item creation: the examination's `posture` must be `NORMAL`, because a `RESTRICTED` or `FROZEN` examination accepts no new first-day items (`ERR_EXAM_POSTURE_FROZEN`), and every addition recomputes the parent examination's `overdue_item_count` and bumps the examination's `version` by one. Item listings filter by `status`; examination listings filter by `agency_id`, `status`, and `posture`. Every lifecycle transition on the examination itself — issuance, fieldwork, findings, remediation, closure, cancellation — likewise increments the examination's `version` by exactly one and refreshes its `updated_at`.

### 3.3. Document Submissions and Quality Control

Answering a first-day item is the `RemediationOwner`'s job. Each submission names the `first_day_item_id` it answers and carries a `document_manifest`: a non-empty array of document descriptor objects, each with `doc_id`, `title`, `page_count`, and `sha256`. An empty manifest is rejected with `ERR_INVALID_REQUEST`, and the whole submission is refused with `ERR_EXAM_POSTURE_FROZEN` whenever the examination's `posture` has degraded to `FROZEN` — a frozen examination accepts no further submissions until posture relaxes. The server stamps each accepted submission with its `submission_round`, computed as the count of prior submissions against the same item plus one, and stores `page_count_total`, the sum of every manifest entry's `page_count`, computed once at creation. New submissions enter quality control as `PENDING_REVIEW`, and creating one bumps both the parent item's `version` and the examination's `version` by one.

Quality control belongs to the `ComplianceReviewer`. Acceptance is deliberately strict: the submission must still be `PENDING_REVIEW`, its parent item must still be `PENDING`, the examination must be in `FIRST_DAY_ISSUED` or `FIELDWORK`, and the examination's `posture` must not be `FROZEN`; any shortfall is rejected with `ERR_INVALID_STATE`. When acceptance lands, the submission moves `PENDING_REVIEW` → `ACCEPTED`, and the acceptance cascades: the parent item transitions `PENDING` → `SUBMITTED` with its `submitted_at` stamped at that moment, the examination's `overdue_item_count` and `posture` are recomputed — acceptance of an overdue item may relax a `FROZEN` or `RESTRICTED` posture — and the `version` of the submission, the item, and the examination each increments by one. Rejection requires a non-empty `quality_reject_reason` and moves the submission `PENDING_REVIEW` → `REJECTED`, bumping only the submission's own `version`; the item stays `PENDING`, and the owner is expected to answer with a later round. Submission listings filter by `quality_status`.

The regulator may also excuse an item outright. Waiving a `PENDING` item — a `RegulatoryAffairsManager` action requiring a non-empty `waived_reason` — moves it to the terminal `WAIVED` state, recomputes the examination's overdue count and posture just as an acceptance would, and bumps both the item's and the examination's `version`. Once every first-day item stands `SUBMITTED` or `WAIVED`, beginning fieldwork moves the examination `FIRST_DAY_ISSUED` → `FIELDWORK`; attempting it with any item still `PENDING` fails the state check with `ERR_INVALID_STATE`.

### 3.4. Fieldwork: Examiner Meetings and Informal Findings

During fieldwork the `RegulatoryAffairsManager` logs every examiner meeting: the payload names the `examination_id`, the logical `meeting_date`, the `attendees` array — which must include at least one examiner and at least one bank officer, else `ERR_INVALID_REQUEST` — and narrative `minutes_summary`. Meetings are born `DRAFT`. One calendar rule applies at logging time: two meetings on the same examination may not share a UTC calendar date once one of them is `FINALIZED`. Unlike the interval-overlap arithmetic of exam scheduling, this is a point collision at the date grain — the same calendar day is a conflict regardless of hour — and a collision is rejected with `ERR_MEETING_DATE_CONFLICT`.

Finalizing the minutes is the manager's seal: the meeting must be `DRAFT`, its `minutes_summary` must be non-empty, and the examination must be in `FIELDWORK` or `FINDINGS_DELIVERED`. Finalization moves the meeting `DRAFT` → `FINALIZED`, bumps its `version`, and renders it immutable thereafter. Only a `FINALIZED` meeting may carry informal findings; capturing one against a still-`DRAFT` meeting is rejected with `ERR_INVALID_STATE`. Each informal finding records the `examiner_meeting_id` of the session at which it surfaced, the narrative `finding_text`, and the examiner's expressed `severity_hint` of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL`. A finding's `promoted_issue_id` stays null until the finding is later promoted into a formal issue, at which point it links to that issue permanently. When at least one meeting has been finalized, delivering findings moves the examination `FIELDWORK` → `FINDINGS_DELIVERED`. Meeting listings filter by `examination_id` and `status`.

### 3.5. Formal Issues, Repeat-Finding Detection, and Risk Scoring

Formal findings arrive as issues. Filing one is a `RegulatoryAffairsManager` action against an examination and is concurrency-guarded per §2.7: the payload must carry `expected_examination_version` alongside the regulator's `issue_ref` (unique within its examination — duplicates draw `ERR_DUPLICATE_KEY`), a `classification` of `MRA` or `MRIA`, a `severity` of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL`, and the regulator-imposed remediation `due_date`. An issue filed in response to an informal finding carries that finding's `informal_finding_id`, and filing sets the finding's `promoted_issue_id` to the new issue; an issue filed directly from a regulator letter simply omits the field. Issues are born `OPEN`. Filing an issue bumps the examination's `version` by one and triggers two computations.

The first computation decides whether the finding is a repeat. The `issue_ref` is normalized by stripping whitespace, uppercasing, and dropping any trailing revision suffix of the form "-R" followed by digits — so MRA-2026-07-R2 normalizes to MRA-2026-07. The new issue's `is_repeat_finding` is true if and only if there exists a different, already `CLOSED` issue, on any examination belonging to the same agency as the new issue's examination, whose normalized reference equals the new issue's normalized reference and whose `closed_at` falls strictly before the new issue's `created_at`. When several prior closures match, the one with the latest `closed_at` is the one considered; a tie on the exact same millisecond is broken in favor of the lexicographically smaller prior `issue_ref`.

The second computation refreshes the examination's repeat-finding risk, stored on `repeat_finding_risk_score_bp` and recomputed whenever an issue is created, closed, or marked `OVERDUE`, as well as whenever posture is recalculated. Every issue in the scoring set contributes a base severity weight in basis points: `LOW` contributes 2,500, `MODERATE` 5,000, `HIGH` 7,500, and `CRITICAL` 10,000. When the issue's `is_repeat_finding` flag is true, that base is multiplied by the agency's `repeat_finding_multiplier_bp` divided by 10,000, with the product rounded half up to a whole basis point before it enters the sum. The score comes in two variants. The forward-looking variant — the one stored on the examination and snapshotted into board reports while the examination is in `REMEDIATION` or any earlier stage — sums contributions over issues standing `OPEN`, `REMEDIATION_PLANNED`, `IN_PROGRESS`, `OVERDUE`, or `VALIDATION_SUBMITTED`, deliberately excluding `CLOSED` issues, and adds a per-issue surcharge for each `OVERDUE` issue of 25 basis points per whole day overdue, the surcharge capped at 5,000 basis points per issue. The grand total is capped at 100,000 basis points. The historical variant — used by the cross-exam trend read of §3.9 — sums only issues standing `CLOSED`, `OVERDUE`, or `VALIDATION_SUBMITTED`, capturing resolved exposure, and adds no overdue surcharge: a closed issue contributes its final-severity base, with the repeat multiplier where applicable, and nothing more.

With at least one issue on the books, opening remediation moves the examination `FINDINGS_DELIVERED` → `REMEDIATION`. Issue listings on an examination filter by `status` and `classification`.

### 3.6. Remediation Plans and Milestones

Every issue is answered by a remediation plan drafted by a `RemediationOwner`. The payload names the accountable `owner_user_id` — the `id` of a `BankOfficer`, and an inactive officer may not be named — together with the `root_cause_narrative` and a `corrective_action_summary`. Each plan names its `issue_id`, and the server stamps it with a `plan_version`: a one-based superseding index computed as the count of prior plans on the same issue plus one. Creating a plan bumps the parent issue's `version` by one. A plan's life runs `DRAFT` → `SUBMITTED` → `APPROVED` → `ACTIVE` → `COMPLETE`, with a `REJECTED` branch that loops back to `DRAFT` and a `SUPERSEDED` terminal state for displaced plans.

Submitting a plan requires it to be `DRAFT`, to have at least one milestone, and to belong to an issue still standing `OPEN`, `REMEDIATION_PLANNED`, `IN_PROGRESS`, or `OVERDUE`; submission stamps `submitted_at` and moves the plan to `SUBMITTED`. Approval belongs to the `ComplianceReviewer` and carries the certification gate of §2.10 — `L3` when the issue is an MRIA — plus one exclusivity rule: no other plan for the same issue may currently be `ACTIVE`, or the approval is rejected with `ERR_INVALID_STATE`. Approval stamps `approved_at`, moves the plan `SUBMITTED` → `APPROVED`, and — when the issue is still `OPEN` — walks the issue `OPEN` → `REMEDIATION_PLANNED`; both the plan's and the issue's `version` increment. Rejection requires a non-empty `rejection_reason` and moves the plan to `REJECTED`, from which the owner may revise it straight back to `DRAFT` for another attempt. Activation moves an `APPROVED` plan to `ACTIVE` provided the issue stands `REMEDIATION_PLANNED`, `IN_PROGRESS`, or `OVERDUE`. Activation is also the displacement mechanism: when a newer plan — one with a higher `plan_version` for the same issue — becomes `ACTIVE`, the previously `ACTIVE` plan transitions automatically to `SUPERSEDED`, and its milestones still sitting `PENDING` are frozen, treated as `OVERDUE`-equivalent and accepting no further transitions. An `ACTIVE` plan completes itself: the moment every one of its milestones stands `COMPLETE` — and there is at least one — the plan moves `ACTIVE` → `COMPLETE`.

Milestones decompose the plan. Each milestone names the `remediation_plan_id` it belongs to, and adding one is concurrency-guarded per §2.7 with `expected_plan_version`; the payload carries a `milestone_name`, a `due_date`, and optionally a `sequence_index`. The sequence index is a strictly increasing integer, at least 1, unique within its plan. When the payload omits it, the server assigns the highest existing index on the plan plus one — or 1 when the plan has none yet; when the payload supplies an index already in use on that plan, the create is rejected with `ERR_DUPLICATE_KEY`. Milestone creation is order-sensitive: when two creations land against the same plan, the request with the earlier `created_at` is processed first, and because timestamps carry millisecond precision a true tie is practically impossible — but should two records land on the same millisecond, the request whose `milestone_name` sorts lexicographically earlier wins. Milestone listings filter by `status`.

Work flows through the milestones in sequence order. Starting a milestone requires it to be `PENDING`, requires its parent plan to be `ACTIVE` — a start or completion attempted while the plan is anything else is rejected with `ERR_NO_ACTIVE_PLAN` — and requires every milestone with a smaller `sequence_index` on the same plan to stand `IN_PROGRESS` or `COMPLETE`; an earlier milestone still `PENDING`, or lapsed into `OVERDUE`, blocks the start with `ERR_INVALID_STATE`. A successful start moves the milestone `PENDING` → `IN_PROGRESS` and ripples upward: if the issue stands `REMEDIATION_PLANNED` it advances to `IN_PROGRESS`, and if the issue stands `OVERDUE` the start resumes it to `IN_PROGRESS` with its `escalated_to_board` flag left exactly as it was. Starting bumps the `version` of the milestone, the plan, and the issue by one each. Completing a milestone requires it to be `IN_PROGRESS`; completion stamps `completed_at`, re-evaluates whether the parent plan has earned its `ACTIVE` → `COMPLETE` transition, and bumps the milestone's and plan's `version`. For a milestone, `OVERDUE` is terminal — there is no path back once the clock has crossed its due date, as §3.8 describes.

### 3.7. Validation Evidence and Closure Adjudication

When the remediation work is done, the `RemediationOwner` assembles proof. Submitting validation evidence against an issue names the `issue_id`, an `evidence_type` of `DOCUMENT_PACKAGE`, `TEST_RESULTS`, `INTERNAL_AUDIT_REPORT`, or `THIRD_PARTY_ATTESTATION`, an `artifact_manifest` array whose entries each carry `artifact_id`, `name`, and `sha256`, and the `submitted_by_user_id` of the officer submitting. Evidence is born with `review_status` `PENDING`, and its creation bumps the issue's `version`. A `ComplianceReviewer` then judges it: marking it sufficient moves `PENDING` → `SUFFICIENT`, while marking it insufficient requires non-empty `review_notes` and moves `PENDING` → `INSUFFICIENT`. Both judgments are terminal, and evidence listings filter by `review_status`.

With sufficient evidence in hand, the owner submits the issue for closure validation. Three preconditions guard that submission, and any failure is rejected with `ERR_ISSUE_NOT_CLOSABLE`: the issue must stand `IN_PROGRESS`; the payload's `validation_evidence_id` must reference evidence whose `review_status` is `SUFFICIENT` on this same issue; and every milestone of the issue's `ACTIVE` plan must stand `COMPLETE`. A successful submission moves the issue `IN_PROGRESS` → `VALIDATION_SUBMITTED` and springs a closure request into existence: `PENDING`, stamped with a `request_round` equal to the count of prior closure requests on this issue plus one, carrying the payload's `validation_evidence_id` and the owner's `closure_narrative` asserting the issue is remediated. The submission also re-evaluates the examination's automatic advance — the examination moves `REMEDIATION` → `VALIDATION` on its own the moment at least one issue exists and every issue stands `VALIDATION_SUBMITTED` or `CLOSED` — and bumps both the issue's and the examination's `version`.

Adjudicating the closure request is the `ComplianceReviewer`'s final gate. Approval requires the request to be `PENDING`, the certification gate of §2.10 when the issue is an MRIA, the referenced evidence to still stand `SUFFICIENT` at decision time (a lapsed linkage fails with `ERR_INVALID_STATE`), the segregation-of-duties check against the active plan's owner, and the concurrency token `expected_issue_version` per §2.7. Approval records the caller as `reviewed_by_user_id`, moves the request `PENDING` → `APPROVED`, and cascades decisively: the issue moves `VALIDATION_SUBMITTED` → `CLOSED` with `closed_at` stamped, the examination's risk score is recomputed — closed issues drop out of the forward-looking set — and the `version` of the closure request, the issue, and the examination each increments by one. Rejection requires a non-empty `rejection_reason`, runs the same segregation check, records the same `reviewed_by_user_id`, and moves the request `PENDING` → `REJECTED` while the issue loops back `VALIDATION_SUBMITTED` → `IN_PROGRESS` for further work — with the `version` of the closure request, the issue, and the examination each incrementing by one, exactly as an approval would; the next validation submission on that issue then opens a fresh closure request with the next `request_round`. This revision loop may cycle as many times as the evidence requires.

### 3.8. Overdue Escalation, Posture, and the Commitment Log

The logical clock of §2.5 is the system's enforcement arm. When the clock advances past an issue's `due_date` while the issue still stands `OPEN`, `REMEDIATION_PLANNED`, or `IN_PROGRESS`, the issue transitions automatically to `OVERDUE`; issues already `VALIDATION_SUBMITTED` or `CLOSED` are untouched by the clock. Marking an issue overdue recomputes the examination's `repeat_finding_risk_score_bp`, bumps both the issue's and the examination's `version`, and consults the escalation rule: if the issue's `is_repeat_finding` is true, or if the whole days it has been overdue have reached the agency's `escalation_threshold_days` — a span exactly equal to the threshold qualifies — the issue's `escalated_to_board` flag is set true and stays set even if work later resumes. Milestones face the same reckoning on a finer grain: a milestone standing `PENDING` or `IN_PROGRESS` whose `due_date` falls strictly behind the logical date transitions to `OVERDUE`, recomputes the examination's posture, and bumps the milestone's and the examination's `version`.

Posture itself is recomputed whenever the overdue-item count changes, an issue turns `OVERDUE`, a milestone turns `OVERDUE`, or an overdue stretch crosses the escalation threshold. The recomputation derives three quantities in a fixed order: first the `overdue_item_count`, the number of the examination's first-day items still `PENDING` whose `due_date` falls strictly before the current logical date — an item due on the current date is not yet overdue; second, the maximum whole days any `OVERDUE` issue on the examination has been overdue, measured from its `due_date` to the current logical date, or zero when no issue is overdue; third, whether any milestone anywhere beneath the examination — on any plan of any of its issues — currently stands `OVERDUE`. The examination is `FROZEN` when the overdue-item count reaches three (exactly three qualifies) or when the longest issue-overdue stretch reaches the escalation threshold; otherwise it is `RESTRICTED` when at least one first-day item is overdue or any milestone stands overdue; otherwise it is `NORMAL`. The gates of §2.9 give posture its teeth: `FROZEN` blocks new document submissions, and `RESTRICTED` or `FROZEN` blocks new first-day items, both rejected with `ERR_EXAM_POSTURE_FROZEN`, while accepted submissions and waivers shrink the overdue set and can relax posture back down.

Alongside the remediation machinery runs the commitment log, the bank's record of promises made to the regulator. Recording a commitment — a `RegulatoryAffairsManager` action — captures the `commitment_text`, the `committed_by_user_id` of the officer making the promise, and the `due_date` by which it must be honored; the server stamps `committed_at` at creation and bumps the examination's `version`. Per §2.4 the entry itself carries no `version` and no `updated_at`: it is append-only and immutable. The only later event is fulfillment, which stamps `fulfilled_at` — null while the commitment stands open — and again bumps the examination's `version`. Commitments bind the end of the lifecycle: closing the examination, moving it `VALIDATION` → `CLOSED`, requires every issue on the examination to stand `CLOSED` — any straggler draws `ERR_OPEN_ISSUES_REMAIN` — and requires every commitment on the examination to have a non-null `fulfilled_at`, with an outstanding promise drawing `ERR_COMMITMENT_OUTSTANDING`.

### 3.9. Board Reporting and Portfolio-Wide Queries

The `BoardReporter` turns an examination's live state into a board-grade snapshot. Generating a report names the `examination_id` and an inclusive reporting window from `reporting_period_start` to `reporting_period_end`; an end earlier than the start is rejected with `ERR_INVALID_DATE_RANGE`. At generation time the server freezes four measurements into the report: `open_issue_count`, the issues on this examination whose status is anything other than `CLOSED`; `overdue_issue_count`, those standing `OVERDUE`; `escalated_issue_count`, those whose `escalated_to_board` flag is true; and `total_repeat_finding_risk_bp`, the examination's stored forward-looking risk score at that instant. Generation bumps the examination's `version`. A report is born `DRAFT` and finalizing it moves `DRAFT` → `FINALIZED`, after which it is immutable; report listings filter by `examination_id` and `status`.

Beyond per-examination reads, the surface answers portfolio questions through filtered listings. The historical variant of the risk score is exposed per examination as `historical_risk_bp` together with the `contributing_issue_ids` that fed it. Informal findings list across meetings, filterable by `promoted_issue_id` to trace which finding became which issue; issues list across examinations, filterable by `informal_finding_id` for the reverse trace. Remediation plans list portfolio-wide filterable by `owner_user_id`, validation evidence by `submitted_by_user_id`, closure requests by `validation_evidence_id` or `reviewed_by_user_id`, and commitments by `committed_by_user_id` — together these give the board and the audit committee a reverse-reachability path from any person or artifact to everything it touches.

## 4. Endpoint Definitions

All endpoints live under the `/regulatory-exams` mount. Operations that create a new resource respond with 201; operations that modify, transition, or merely read a resource respond with 200. Where the Authorized Role(s) column reads "All roles", every one of the five roles defined in §2.1 may call the endpoint. The table deliberately omits request and response bodies: the workflow narratives of §3 carry the full contract for each operation.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /regulatory-exams/agencies | Create a regulator agency | PlatformAdmin |
| GET | /regulatory-exams/agencies | List agencies | All roles |
| GET | /regulatory-exams/agencies/{id} | Fetch a single agency | All roles |
| POST | /regulatory-exams/officers | Register a bank officer | PlatformAdmin |
| GET | /regulatory-exams/officers | List bank officers | All roles |
| GET | /regulatory-exams/officers/{id} | Fetch a bank officer | All roles |
| POST | /regulatory-exams/reviewers | Register a compliance reviewer | PlatformAdmin |
| GET | /regulatory-exams/reviewers | List compliance reviewers | All roles |
| GET | /regulatory-exams/reviewers/{id} | Fetch a compliance reviewer | All roles |
| POST | /regulatory-exams/examinations | Schedule a new examination | RegulatoryAffairsManager |
| GET | /regulatory-exams/examinations | List examinations with filters | All roles |
| GET | /regulatory-exams/examinations/{id} | Fetch an examination | All roles |
| POST | /regulatory-exams/examinations/{id}/issue-first-day-letter | Issue the first-day letter (SCHEDULED → FIRST_DAY_ISSUED) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/begin-fieldwork | Begin fieldwork (FIRST_DAY_ISSUED → FIELDWORK) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/deliver-findings | Deliver findings (FIELDWORK → FINDINGS_DELIVERED) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/open-remediation | Open remediation (FINDINGS_DELIVERED → REMEDIATION) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/close | Close the examination (VALIDATION → CLOSED) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/cancel | Cancel a scheduled examination (SCHEDULED → CANCELLED) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examinations/{id}/first-day-items | Add a first-day-letter item to an examination | RegulatoryAffairsManager |
| GET | /regulatory-exams/examinations/{id}/first-day-items | List first-day items for an examination | All roles |
| GET | /regulatory-exams/first-day-items/{id} | Fetch a single first-day item | All roles |
| POST | /regulatory-exams/first-day-items/{id}/waive | Waive a PENDING first-day item | RegulatoryAffairsManager |
| POST | /regulatory-exams/first-day-items/{id}/submissions | Submit a document package against a first-day item | RemediationOwner |
| GET | /regulatory-exams/first-day-items/{id}/submissions | List submissions for a first-day item | All roles |
| GET | /regulatory-exams/document-submissions/{id} | Fetch a single document submission | All roles |
| POST | /regulatory-exams/document-submissions/{id}/accept | QC-accept a PENDING_REVIEW submission | ComplianceReviewer |
| POST | /regulatory-exams/document-submissions/{id}/reject | QC-reject a PENDING_REVIEW submission | ComplianceReviewer |
| POST | /regulatory-exams/examiner-meetings | Log an examiner meeting | RegulatoryAffairsManager |
| GET | /regulatory-exams/examiner-meetings | List examiner meetings | All roles |
| GET | /regulatory-exams/examiner-meetings/{id} | Fetch a meeting | All roles |
| POST | /regulatory-exams/examiner-meetings/{id}/finalize | Finalize meeting minutes (immutable thereafter) | RegulatoryAffairsManager |
| POST | /regulatory-exams/examiner-meetings/{id}/informal-findings | Capture an informal finding on a meeting | RegulatoryAffairsManager |
| GET | /regulatory-exams/examiner-meetings/{id}/informal-findings | List informal findings captured at a meeting | All roles |
| GET | /regulatory-exams/informal-findings/{id} | Fetch an informal finding | All roles |
| GET | /regulatory-exams/informal-findings | List informal findings portfolio-wide, filterable by promoted issue | All roles |
| POST | /regulatory-exams/examinations/{id}/issues | File a formal MRA/MRIA issue (OCC-guarded) | RegulatoryAffairsManager |
| GET | /regulatory-exams/examinations/{id}/issues | List issues for an examination | All roles |
| GET | /regulatory-exams/issues | List issues portfolio-wide, filterable by origin finding | All roles |
| GET | /regulatory-exams/issues/{id} | Fetch an issue | All roles |
| POST | /regulatory-exams/issues/{id}/submit-validation | Submit an issue for closure validation; spawns a closure request | RemediationOwner |
| POST | /regulatory-exams/issues/{id}/remediation-plans | Create a remediation plan for an issue | RemediationOwner |
| GET | /regulatory-exams/issues/{id}/remediation-plans | List remediation plans for an issue | All roles |
| GET | /regulatory-exams/remediation-plans | List remediation plans portfolio-wide, filterable by owner | All roles |
| GET | /regulatory-exams/remediation-plans/{id} | Fetch a remediation plan | All roles |
| POST | /regulatory-exams/remediation-plans/{id}/submit | Submit a DRAFT plan | RemediationOwner |
| POST | /regulatory-exams/remediation-plans/{id}/approve | Approve a SUBMITTED plan (L3 required for MRIA issues) | ComplianceReviewer |
| POST | /regulatory-exams/remediation-plans/{id}/reject | Reject a SUBMITTED plan | ComplianceReviewer |
| POST | /regulatory-exams/remediation-plans/{id}/revise | Return a REJECTED plan to DRAFT | RemediationOwner |
| POST | /regulatory-exams/remediation-plans/{id}/activate | Activate an APPROVED plan, superseding any other ACTIVE plan on the issue | RemediationOwner |
| POST | /regulatory-exams/remediation-plans/{id}/milestones | Add a milestone to a plan (OCC-guarded) | RemediationOwner |
| GET | /regulatory-exams/remediation-plans/{id}/milestones | List milestones on a plan | All roles |
| GET | /regulatory-exams/remediation-milestones/{id} | Fetch a milestone | All roles |
| POST | /regulatory-exams/remediation-milestones/{id}/start | Start a PENDING milestone | RemediationOwner |
| POST | /regulatory-exams/remediation-milestones/{id}/complete | Complete an IN_PROGRESS milestone | RemediationOwner |
| POST | /regulatory-exams/issues/{id}/validation-evidence | Submit validation evidence for an issue | RemediationOwner |
| GET | /regulatory-exams/issues/{id}/validation-evidence | List evidence for an issue | All roles |
| GET | /regulatory-exams/validation-evidence | List validation evidence portfolio-wide, filterable by submitting officer | All roles |
| GET | /regulatory-exams/validation-evidence/{id} | Fetch a single evidence record | All roles |
| POST | /regulatory-exams/validation-evidence/{id}/mark-sufficient | Mark PENDING evidence SUFFICIENT | ComplianceReviewer |
| POST | /regulatory-exams/validation-evidence/{id}/mark-insufficient | Mark PENDING evidence INSUFFICIENT | ComplianceReviewer |
| GET | /regulatory-exams/issues/{id}/closure-requests | List closure requests for an issue | All roles |
| GET | /regulatory-exams/closure-requests | List closure requests portfolio-wide, filterable by evidence or reviewer | All roles |
| GET | /regulatory-exams/closure-requests/{id} | Fetch a closure request | All roles |
| POST | /regulatory-exams/closure-requests/{id}/approve | Approve a PENDING closure request; closes the parent issue (OCC-guarded on the issue) | ComplianceReviewer |
| POST | /regulatory-exams/closure-requests/{id}/reject | Reject a PENDING closure request; returns the issue to IN_PROGRESS | ComplianceReviewer |
| POST | /regulatory-exams/board-reports | Generate a board report snapshot for an examination | BoardReporter |
| GET | /regulatory-exams/board-reports | List board reports | All roles |
| GET | /regulatory-exams/board-reports/{id} | Fetch a board report | All roles |
| POST | /regulatory-exams/board-reports/{id}/finalize | Finalize a DRAFT report | BoardReporter |
| POST | /regulatory-exams/examinations/{id}/commitments | Record a regulator commitment (append-only) | RegulatoryAffairsManager |
| GET | /regulatory-exams/examinations/{id}/commitments | List commitments for an examination | All roles |
| GET | /regulatory-exams/commitments | List commitments portfolio-wide, filterable by committing officer | All roles |
| GET | /regulatory-exams/commitments/{id} | Fetch a commitment | All roles |
| POST | /regulatory-exams/commitments/{id}/fulfill | Mark a commitment fulfilled | RegulatoryAffairsManager |
| GET | /regulatory-exams/examinations/{id}/risk-history | Historical-variant repeat-finding risk trend for the examination | All roles |
| POST | /regulatory-exams/_clock/set_current_utc | Set the logical clock; fires clock-driven transitions | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is described.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_CERTIFICATION_INSUFFICIENT | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_EXAM_SCHEDULE_OVERLAP | 422 |
| ERR_MEETING_DATE_CONFLICT | 422 |
| ERR_INVALID_DATE_RANGE | 400 |
| ERR_DUPLICATE_KEY | 409 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_EXAM_POSTURE_FROZEN | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ISSUE_NOT_CLOSABLE | 422 |
| ERR_NO_ACTIVE_PLAN | 422 |
| ERR_COMMITMENT_OUTSTANDING | 422 |
| ERR_OPEN_ISSUES_REMAIN | 422 |

# Medical Staff Privileging API — Product Requirements Document

## 1. Introduction

A hospital's medical staff office carries one of the heaviest compliance burdens in the organization: every practitioner's right to treat patients must be granted, measured, renewed, and — when necessary — curtailed under rules that regulators, accreditors, and courts will later audit line by line. This document specifies the Medical Staff Privileging API, a system that manages the complete credentialing lifecycle of a medical staff: initial appointment applications with primary source verification, delineation of clinical privileges against specialty criteria, focused and ongoing professional practice evaluation (FPPE and OPPE), the biennial reappointment cycle with expirable-credential tracking, temporary, emergency, and disaster privileging, adverse action processing under a fair-hearing plan, National Practitioner Data Bank (NPDB) querying and reporting, and the committee-to-board governance pipeline that ratifies every consequential decision. All resources are mounted under the `/mso` prefix.

Three design commitments shape every workflow that follows. First, an audit-grade trail: each materialized record carries identity, timestamps, and a mutation version, and consequential counts and scores are maintained as derived fields reconciled at the moment the underlying facts change. Second, segregation of duties: the actor who proposes an adverse action may not sit on its hearing panel, the committee voters who endorse an agenda item may not cast its board vote, and a practitioner answers for their own case alone. Third, clock-driven automation: a single logical clock — never the wall clock — governs credential lapses, grant expirations, hearing deadlines, term boundaries, and expiry-risk scoring, so that every time-based behavior is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. The system recognizes exactly seven roles: `MedicalStaffCoordinator`, `CredentialsCommitteeChair`, `MedicalExecutiveCommitteeChair`, `BoardMember`, `DepartmentChief`, `Practitioner`, and `HearingOfficer`. A request that omits either header, or carries a role value outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose declared role is not authorized for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `MedicalStaffCoordinator`, `CredentialsCommitteeChair`, `MedicalExecutiveCommitteeChair`, `BoardMember`, or `HearingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a MEC voter's identifier is appended to an agenda item's `mec_voter_ids` when supplied as `voter_id`, and the board voter's identifier is captured as `board_voter_id` at ratification or decline — but it is never compared to any entity's `id`; the board segregation check compares the acting board member's identifier against recorded voter strings, not against member records.

When `X-User-Role` is `DepartmentChief` or `Practitioner`, `X-User-ID` is the `id` of the acting `MedicalStaffMember`; ownership checks on any resource that references a `MedicalStaffMember` compare the resource's foreign-key field to `X-User-ID`. This is what allows the system to verify that a chief withdrawing a case is the case's `proposed_by_member_id`, that a practitioner requesting a hearing is the case's `subject_member_id`, and that a practitioner relinquishing a grant is that grant's holder.

The seven roles, in brief: a `MedicalStaffCoordinator` is the medical staff office's operations staffer, running applications, verifications, delineations, metrics, credentials, NPDB filings, and the logical clock. A `CredentialsCommitteeChair` chairs the credentials committee — granting waivers, recording committee votes, activating temporary privileges, and finalizing performance reviews. A `MedicalExecutiveCommitteeChair` endorses adverse cases and committee-approved items and reinstates suspended members. A `BoardMember` holds final ratification authority on behalf of the hospital's governing board. A `DepartmentChief` proposes adverse action cases and may withdraw them. A `Practitioner` is a medical staff member acting on their own behalf — requesting fair hearings and relinquishing their own grants. A `HearingOfficer` presides over fair hearings — seating panels, convening hearings, rendering decisions, and processing recusals.

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items returned in one page; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip before the page begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest record first.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Each list endpoint additionally accepts optional filter parameters scoped to its resource. The specialty-criteria list filters by `specialty_code` and `privilege_line`; the member list by `membership_status` and `privilege_posture`; the application list by `member_id`, `application_status`, `application_kind`, and `supersedes_application_id`; the verification-item list by `application_id` and `item_status`; the delineation list by `application_id` and `delineation_status`; the privilege-grant list by `member_id`, `delineation_id`, and `grant_status`; the performance-review list by `member_id`, `privilege_grant_id`, `review_status`, and `review_kind`; the metric list by `review_id` and `metric_status`; the credential list by `member_id`, `credential_kind`, `credential_status`, and `supersedes_credential_id`; the temporary-privilege list by `member_id`, `sponsor_member_id`, `temp_status`, and `temp_kind`; the adverse-action-case list by `subject_member_id`, `case_status`, `proposed_by_member_id`, and `linked_review_id`; the hearing-panel list by `case_id`, `panel_member_id`, and `panel_status`; the NPDB report list by `member_id`, `case_id`, `report_kind`, and `report_status`; and the agenda-item list by `item_kind`, `committee_status`, `ref_application_id`, `ref_delineation_id`, and `ref_case_id`.

### 2.4. Common Resource Properties and the Audit Trail

Every primary resource — medical staff members, specialty criteria, applications, verification items, delineations, privilege grants, performance reviews, performance metrics, expirable credentials, temporary privileges, adverse action cases, hearing panels, and committee agenda items — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including mutations driven by automatic cascades and derived-field reconciliation.

One resource deviates from this convention. An NPDB report is an immutable filing record and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Because cascades mutate parents and related aggregates, the audit trail moves with them: any reconciliation that changes a resource — a recomputed score, an incremented counter, an automatic state flip — also refreshes that resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock

All time-dependent behavior in the system reads from a single logical clock, never from the wall clock. Before any clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default that never falls back to wall-clock time.

A coordinator-only, test-driving capability advances the logical clock to a supplied instant, given in the request body as `to_iso8601`; the response echoes the new reading as `current_utc`. Advancing the clock is a system-wide event: the credential expiry risk window is recomputed for every member, and every lapse and expiration cascade armed by the new reading fires — credentials lapse, grants expire or suspend, temporary privileges expire, appointment terms close out, and hearing deadlines elapse.

### 2.6. Precision, Rounding, and Score Arithmetic

Every score and risk value in the system — delineation satisfaction scores, normalized metric values, per-domain averages, composite review scores, and credential expiry risk scores — is carried at exactly 2 decimal places using the round-half-up method. Rounding is never deferred or approximated; wherever this document states a multi-step computation, the stated rounding points are part of the specification.

Two pinned ordering rules deserve emphasis. For review composites, rounding happens per domain first: each domain's average is rounded half-up to 2 decimal places before the weighted cross-domain sum is taken and rounded again. For metric normalization, the normalized value is rounded half-up to 2 decimal places first and only then clamped into the range from 0.00 to 100.00 inclusive — the clamp is applied after rounding, not before.

### 2.7. Optimistic Concurrency Control

Two creation operations are guarded by optimistic concurrency control, and both reject stale writers with the same error: `ERR_STALE_VERSION`, HTTP 412.

Creating an appointment application requires the request body to carry `expected_member_version`, holding the applicant member record's `version` as the client last observed it. If the member's current `version` has advanced beyond that value — because another writer has just submitted a superseding application, or because the member's term has been ratified forward — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from filing against a member snapshot it has not observed.

Requesting a privilege delineation works the same way one level down. The request body must carry `expected_application_version`, matching the parent application's current `version`. If the application's version has advanced since the client last read it — the application may have been advanced to committee review or withdrawn by another writer — the delineation creation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than attaching a new delineation to a stale snapshot.

No other endpoint accepts a version field. The OCC check on these two operations runs early in the request's validation order, ahead of state-machine and business checks, as described in §2.9.

### 2.8. Membership Standing and Privilege Posture: Two Parallel Axes

A member's standing is tracked on two independent axes that evolve in parallel. The first axis, `membership_status`, records legal standing in the medical staff and moves among `APPLICANT`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, and `LAPSED`; a freshly created member record begins at `APPLICANT`, and `TERMINATED` and `LAPSED` are terminal. The second axis, `privilege_posture`, is a derived summary of what the member may actually exercise right now, taking values `NONE`, `FULL`, `PARTIAL`, and `EMERGENCY_ONLY`; it is recomputed from the state of the member's privilege grants, expirable credentials, and temporary privileges rather than being set directly. A new member's posture is `NONE`.

Posture recomputation is triggered by every event that changes what the member holds: grant creation, activation, suspension, reinstatement, revocation, relinquishment, and expiry; credential lapse, renewal, and revocation; and temporary-privilege activation, expiry, and early termination. Certain outcomes are pinned by name. When membership is revoked or lapses, posture falls to `NONE`. When every privilege line is suspended, posture falls to `NONE` — or to `EMERGENCY_ONLY` if the member still holds an active temporary privilege. When a temporary privilege is activated for a member whose posture was `NONE`, the posture rises to `EMERGENCY_ONLY`.

Two derived counters ride alongside the axes and are reconciled by the same events. `active_privilege_line_count` is the number of the member's privilege grants currently in `ACTIVE` status, maintained by grant and suspension side effects. `credential_expiry_risk_score` is the output of the credential expiry risk calculation in §3.6 and drives the auto-suspension flag described there. The member record also carries `sod_exclusion_tags`, an array of case identifiers naming the adverse action cases from whose hearing-panel duty this member is excluded — because the member proposed the case or is its subject.

### 2.9. Validation Order and Rejection Priority

Every request is validated against a fixed priority ladder, and a request that fails an earlier rung is never evaluated against a later one — the first failing rung determines the error returned. The ladder runs:

1. **Authentication context.** Both headers present and the role value recognized — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization.** The declared role is permitted for the target operation — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. **Existence.** Every referenced resource exists: path identifiers are validated left to right, then foreign keys carried in the body — `ERR_NOT_FOUND` (404). For nested paths, the first missing identifier from the left is the one reported.
4. **Optimistic concurrency.** On the two guarded creation operations (creating an application, requesting a delineation), the `expected_*_version` field must match the parent entity's current `version` — `ERR_STALE_VERSION` (412).
5. **State-machine legality.** The target entity must sit in a from-state of the requested transition — `ERR_INVALID_STATE` (409) and the transition-specific state errors.
6. **Segregation of duties.** Board-voter conflict, panelist exclusion, proposer-only withdrawal, subject-only hearing requests, holder-only relinquishment — `ERR_SOD_BOARD_CONFLICT` and its sibling 403 errors.
7. **Safety gates.** Primary-source waiver bans, sponsor qualification, case-subject identity — `ERR_PRIMARY_SOURCE_NOT_WAIVABLE` and its sibling 403 errors, applying to waiver, temporary-privilege activation, and hearing requests.
8. **Temporal windows.** The reappointment window (`ERR_OUTSIDE_REAPPOINTMENT_WINDOW`), the hearing-request deadline (`ERR_HEARING_REQUEST_LATE`), temporary-privilege window caps (`ERR_TEMP_WINDOW_TOO_LONG`), buffered overlap (`ERR_TEMP_OVERLAP`), and metric collection windows (`ERR_METRIC_OUTSIDE_WINDOW`) — all 409, applying to submission, hearing requests, temporary-privilege activation, grant creation, and metric creation.
9. **Structural constraints.** Verification items must exist before submission (`ERR_NO_VERIFICATION_ITEMS`); delineations must be evaluated before committee advancement (`ERR_DELINEATIONS_UNEVALUATED`); metric weights must sum exactly at finalization (`ERR_WEIGHT_SUM_INVALID`); same-domain metrics must carry equal weight (`ERR_METRIC_WEIGHT_DOMAIN_MISMATCH`); quorum must be satisfied (`ERR_COMMITTEE_QUORUM_UNMET`, `ERR_HEARING_QUORUM_UNMET`); duplicate MEC votes are refused (`ERR_DUPLICATE_MEC_VOTE`) — all 409, applying to submission, committee advancement, finalization, metric creation, hearing convening, committee voting, and MEC endorsement.
10. **Cross-reference coherence.** The requested privilege line must be defined for the member's specialty (`ERR_PRIVILEGE_LINE_UNKNOWN`), a superseded application must belong to the same member (`ERR_PRIVILEGE_LINE_UNKNOWN`), a sponsor must not be the recipient (`ERR_SELF_SPONSOR`), and an agenda item's kind must agree with which reference field is populated (`ERR_AGENDA_REF_MISMATCH`) — all 422, applying to delineation creation, application creation, temporary-privilege creation, and agenda-item creation.
11. **Input shape.** Required fields present, enum values valid, minimum string lengths met, and start-before-end datetime ordering respected — `ERR_INVALID_REQUEST` (400), applying to every endpoint.

The ordering is observable. A request carrying both a stale version and an illegal target state surfaces the stale-version rejection; a request with an unknown privilege line and a malformed body surfaces the referential error; a request with a missing header never reaches authorization at all.

### 2.10. Segregation of Duties

Consequential decisions in this system are deliberately split across roles and individuals, and the barriers are enforced mechanically rather than by convention.

Hearing-panel exclusion travels with the member record. When a practitioner requests a fair hearing on an adverse action case, the case's `id` is appended to the `sod_exclusion_tags` of both the subject and the proposer. Any member whose `sod_exclusion_tags` contain a case's `id` is barred from being seated on that case's hearing panel — the seating attempt is rejected with `ERR_PANELIST_SOD_EXCLUDED` (403) — and a panelist who later acquires the tag (for example, by becoming the proposer of a related case) is automatically flipped from `SEATED` to `DISQUALIFIED`.

Voting separation guards the governance pipeline. Every MEC endorsement records the voter's identifier in the agenda item's `mec_voter_ids`, and a board member whose `X-User-ID` appears in that list may not cast the board ratification or decline vote on the same item — the attempt is rejected with `ERR_SOD_BOARD_CONFLICT` (403).

Ownership checks close the remaining loops. A case may be withdrawn only by the department chief whose member record matches the case's `proposed_by_member_id` (`ERR_NOT_CASE_PROPOSER`, 403); a hearing may be requested only by the practitioner who is the case's `subject_member_id` (`ERR_NOT_CASE_SUBJECT`, 403); and a grant may be relinquished only by the practitioner who holds it (`ERR_NOT_GRANT_HOLDER`, 403).

### 2.11. Interval Semantics: Half-Open Terms and Closed Emergency Windows

Two different interval conventions coexist in this system, and confusing them changes behavior at the boundaries.

Half-open intervals — inclusive at the start, exclusive at the end — govern privilege grants, review measurement windows, and the reappointment window. A privilege grant is in force over `[effective_from, effective_until)`: it expires the instant the clock reaches `effective_until`, and back-to-back grants are permitted, so one grant's `effective_from` may equal another's `effective_until`. A performance review measures data collected over `[period_start, period_end)`. The reappointment submission window opens exactly 180 days before the member's `current_term_end` and closes at `current_term_end` itself.

Closed intervals — inclusive at both ends — govern temporary privileges: a temporary privilege is exercisable over `[window_start, window_end]` and remains active at exactly `window_end`, expiring only once the clock moves strictly past it.

Across all datetime pairs, the start must be strictly earlier than the end; a request whose start equals or follows its end is rejected as `ERR_INVALID_REQUEST` (400).

## 3. Business Logic & Workflows

### 3.1. Practitioner Intake: Specialty Criteria, Member Records, and the Application File

Everything the system decides about privileges traces back to **SpecialtyCriteria**, the rulebook rows maintained by a `MedicalStaffCoordinator`. Each row is keyed by a `specialty_code` — unique across all criteria rows in the hospital instance — together with a named `privilege_line` within that specialty (for example, a catheterization line within cardiology). The row pins the line's bar: `min_training_months` of accredited training, `min_case_volume_24mo` documented cases in the trailing twenty-four months, a `required_board_cert` flag marking whether an unexpired board-certification credential is mandatory, the `fppe_case_count` of proctored cases a grant must accumulate before it matures, and a `volume_tier_table` — an array of tier rows, each carrying a `tier_name`, a `min_cases` threshold, and a `score_multiplier`, ordered ascending by `min_cases` — that the delineation evaluation in §3.3 walks to score documented volume.

A practitioner enters the system when a coordinator creates their **MedicalStaffMember** record from a `full_name`, an `npdb_subject_id` (the identifier later used on NPDB queries and reports), and a `primary_specialty_code` that resolves which specialty criteria apply to them. The record is born with `membership_status` `APPLICANT`, `privilege_posture` `NONE`, an `active_privilege_line_count` of zero, a `credential_expiry_risk_score` of zero, and empty `sod_exclusion_tags`. The two term fields — `current_term_start` and `current_term_end` — remain unset until the member's first board ratification stamps the start of a two-year appointment term.

Against that record, a coordinator opens an **AppointmentApplication**, supplying the `member_id`, an `application_kind` of `INITIAL` or `REAPPOINTMENT`, the OCC field `expected_member_version` described in §2.7, and optionally a `supersedes_application_id`. The supersede reference is self-referential: it may name an earlier, still-pending application of the same member, and a reference to another member's application is rejected as incoherent with `ERR_PRIVILEGE_LINE_UNKNOWN` (422). Creating the application increments the member's `version` by one — a supersede marker that makes any concurrent writer's stale member snapshot detectable. The new application starts in `DRAFT`, with `verification_complete_count` and `verification_required_count` both zero and `submitted_at` unset.

### 3.2. Primary Source Verification and the NPDB Query Gate

While an application sits in `DRAFT`, the coordinator builds its verification file by attaching **VerificationItem** rows, each carrying the parent `application_id`, an `item_kind` — one of `MEDICAL_SCHOOL`, `RESIDENCY`, `BOARD_CERT`, `STATE_LICENSE`, `DEA`, `MALPRACTICE_HISTORY`, `WORK_HISTORY`, `NPDB_QUERY`, or `REFERENCES` — and an `is_primary_source` flag marking whether the item must be verified directly with the issuing source. Each item begins in `PENDING`, with `requested_at` and `verified_at` unset, and each addition recomputes the application's `verification_required_count`.

Submission by the coordinator moves the application `DRAFT` → `SUBMITTED` under four guards. The application must still be in `DRAFT` (`ERR_APPLICATION_NOT_IN_DRAFT`); at least one verification item must exist (`ERR_NO_VERIFICATION_ITEMS`); for an `INITIAL` application, no other application of the same member may be in flight — that is, in `SUBMITTED`, `PSV_IN_PROGRESS`, `PSV_COMPLETE`, `COMMITTEE_REVIEW`, or `BOARD_REVIEW` — unless the new application's `supersedes_application_id` names that in-flight application (`ERR_PENDING_APPLICATION_EXISTS`); and for a `REAPPOINTMENT` application, the clock must fall inside the reappointment window defined in §2.11 and §3.4 (`ERR_OUTSIDE_REAPPOINTMENT_WINDOW`). A successful submission stamps `submitted_at` with the current clock, auto-transitions every `PENDING` verification item to `REQUESTED` with `requested_at` stamped, and increments both the application's `version` and the member's `version` by one.

From there, verification proceeds item by item. Recording receipt of a response moves an item `REQUESTED` → `RECEIVED`; the same action also re-receives an item from `DISCREPANCY` after clarification, so the `RECEIVED` ↔ `DISCREPANCY` cycle is permitted — any other source state is rejected with `ERR_VERIFICATION_NOT_REQUESTED`. The first item to reach `RECEIVED` automatically flips the parent application from `SUBMITTED` to `PSV_IN_PROGRESS`, with verification counts recomputed.

Verifying an item moves it `RECEIVED` → `VERIFIED`, requires the item to be in `RECEIVED` (`ERR_VERIFICATION_NOT_RECEIVED`), and stamps `verified_at`; `VERIFIED` is a terminal state for the item. One additional gate guards the NPDB item kind: an item whose `item_kind` is `NPDB_QUERY` may be verified only when a filed NPDB report exists for the member whose `report_kind` matches the application — `QUERY_INITIAL` for an `INITIAL` application, `QUERY_REAPPOINTMENT` for a `REAPPOINTMENT` application — with `report_status` in `SUBMITTED` or `ACKNOWLEDGED`; without it, verification is rejected with `ERR_NPDB_QUERY_MISSING`. Each verification increments the application's `verification_complete_count`, and the moment that count reaches `verification_required_count` with no item remaining in `PENDING`, `REQUESTED`, `RECEIVED`, or `DISCREPANCY`, the application advances automatically from `PSV_IN_PROGRESS` to `PSV_COMPLETE`, ready for committee advancement.

Discrepancies interrupt that march. Flagging a discrepancy requires a `RECEIVED` item (`ERR_VERIFICATION_NOT_RECEIVED`) and a `discrepancy_note` of at least ten characters (`ERR_INVALID_REQUEST`); the item moves to `DISCREPANCY`, and while any item sits in `DISCREPANCY` the application is blocked from reaching `PSV_COMPLETE`.

Waiver is a `CredentialsCommitteeChair` prerogative. An item in `REQUESTED` or `RECEIVED` may be waived — any other state is rejected with `ERR_VERIFICATION_NOT_WAIVABLE` — and the waiver demands a `waiver_justification` of at least twenty characters (`ERR_INVALID_REQUEST`). One safety gate is absolute: an item that is both primary-source (`is_primary_source` true) and of `item_kind` `NPDB_QUERY` cannot be waived at all, and the attempt is rejected with `ERR_PRIMARY_SOURCE_NOT_WAIVABLE` (403). Waived items are excluded from `verification_required_count`, which is recomputed on every waiver.

Withdrawal remains available early in the lifecycle: a coordinator may withdraw an application from `DRAFT`, `SUBMITTED`, or `PSV_IN_PROGRESS` — attempting it from `COMMITTEE_REVIEW` or later is rejected with `ERR_APPLICATION_NOT_WITHDRAWABLE`. Withdrawal lands the application in the terminal `WITHDRAWN` state and sweeps every still-open verification item to `WAIVED` with `waiver_justification` recorded as "application withdrawn".

### 3.3. Privilege Delineation and Criteria Evaluation

A **PrivilegeDelineation** is a request for one named privilege line, riding on an application. The coordinator creates it with the parent `application_id`, the requested `privilege_line`, the applicant-attested `documented_training_months` and `documented_cases_24mo`, and the OCC field `expected_application_version` described in §2.7; creating a delineation increments the parent application's `version` by one. The requested line must be defined in the specialty criteria for the member's `primary_specialty_code` — an unknown line is rejected with `ERR_PRIVILEGE_LINE_UNKNOWN` (422). The delineation starts in `REQUESTED`, with `satisfaction_tier` and `satisfaction_score` unset until evaluation.

Evaluation by a coordinator requires the delineation to still be in `REQUESTED` (`ERR_DELINEATION_NOT_EVALUABLE`) and the parent application to be in `SUBMITTED`, `PSV_IN_PROGRESS`, or `PSV_COMPLETE` (`ERR_APPLICATION_NOT_IN_REVIEW`) — evaluation after committee advancement is too late. The evaluation computes satisfaction in a pinned sequence:

1. **Mandatory gate.** The applicant's `documented_training_months` must be at least the criteria's `min_training_months`; and when the criteria's `required_board_cert` flag is set, the member must hold an expirable credential whose `credential_kind` is `BOARD_CERT`, whose `credential_status` is `CURRENT`, and whose `expires_on` lies strictly after the current clock instant. Failing either condition fails the gate.
2. **Volume gate.** The applicant's `documented_cases_24mo` must be at least the criteria's `min_case_volume_24mo`.
3. **Tier selection.** The criteria's `volume_tier_table` is walked in ascending `min_cases` order, and the selected tier is the last tier whose `min_cases` is at most the documented case volume. When the volume falls below even the first tier's `min_cases`, no tier qualifies and the tier is `UNMET`.
4. **Base score.** The selected tier's `score_multiplier` is multiplied by the documented case volume capped at one thousand cases — volumes above the cap contribute no further base score.
5. **Training bonus.** The excess of `documented_training_months` over `min_training_months`, capped above at twenty-four months and never allowed below zero, is multiplied by one-half point per excess month.
6. **Satisfaction score.** `satisfaction_score` is the base score plus the training bonus, rounded half-up to 2 decimal places, and `satisfaction_tier` records the selected tier's name.

The delineation lands in `CRITERIA_MET` only when the mandatory gate passes, the volume gate passes, and the selected tier is not `UNMET`; otherwise it lands in `CRITERIA_UNMET`, with `satisfaction_tier` pinned to `UNMET` whenever any mandatory criterion fails.

Both outcomes wait on governance. When the parent application is ultimately ratified, every `CRITERIA_MET` delineation on it flips automatically to `GRANTED` and spawns a privilege grant as described in §3.4 and §3.5, while every `CRITERIA_UNMET` delineation flips to `DENIED`. Both are terminal.

### 3.4. Committee Deliberation: Agendas, Votes, Endorsement, and Ratification

Governance moves through the **CommitteeAgendaItem**. Each item carries an `item_kind` — `APPLICATION_APPROVAL`, `PRIVILEGE_GRANT`, `ADVERSE_ACTION`, or `POLICY_CHANGE` — and exactly the reference field its kind implies: `ref_application_id` for an application approval, `ref_delineation_id` for a privilege grant, `ref_case_id` for an adverse action. A kind inconsistent with the populated reference is rejected with `ERR_AGENDA_REF_MISMATCH` (422). Items are created by a coordinator or the credentials committee chair, and one is also created automatically — in `AGENDA`, for `APPLICATION_APPROVAL`, if none exists yet for the application — when an application advances to committee review. Every item starts with `committee_votes_for` and `committee_votes_against` at zero, an empty `mec_voter_ids` list, and `board_voter_id` unset. Its `quorum_required` is computed at creation: for an `ADVERSE_ACTION` item it is the output of the hearing quorum determination in §3.8; for every other kind it is the fixed committee quorum of 3.

Advancement to committee is the chair's act and carries two preconditions: the application must have reached `PSV_COMPLETE` (`ERR_PSV_NOT_COMPLETE`), and every delineation riding on it must already sit in `CRITERIA_MET` or `CRITERIA_UNMET` — an unevaluated delineation blocks the move with `ERR_DELINEATIONS_UNEVALUATED`. Success moves the application `PSV_COMPLETE` → `COMMITTEE_REVIEW` and auto-creates the agenda item just described.

Committee voting by the chair accepts a vote batch of `votes_for` and `votes_against`, which increment `committee_votes_for` and `committee_votes_against` respectively. The item must be in `AGENDA` or `DEFERRED` (`ERR_ITEM_NOT_VOTABLE`), and the batch must push a tally to quorum: if, after applying the batch, `committee_votes_for` has reached `quorum_required`, the item moves to `COMMITTEE_APPROVED`; if instead `committee_votes_against` has reached `quorum_required`, it moves to `COMMITTEE_REJECTED`; a batch that reaches neither threshold is rejected with `ERR_COMMITTEE_QUORUM_UNMET`. For an `ADVERSE_ACTION` item there is one more readiness gate: the referenced case must be in `HEARING_HELD` or `MEC_ENDORSED` (`ERR_CASE_NOT_READY_FOR_COMMITTEE`). A rejected `APPLICATION_APPROVAL` item leaves its linked application in `COMMITTEE_REVIEW`, where it remains re-agendable.

Scheduling latitude exists around the vote: the chair may defer an item — `AGENDA` → `DEFERRED`, rejected from any other state with `ERR_ITEM_NOT_DEFERRABLE` — and may later return it to the agenda, `DEFERRED` → `AGENDA`, rejected from any other state with `ERR_ITEM_NOT_REAGENDABLE`; the `AGENDA` ↔ `DEFERRED` cycle is unrestricted. Grant suspensions also push open `PRIVILEGE_GRANT` items to `DEFERRED`, per §3.6.

MEC endorsement by a `MedicalExecutiveCommitteeChair` requires the item in `COMMITTEE_APPROVED` (`ERR_ITEM_NOT_COMMITTEE_APPROVED`). The call carries a `voter_id`, which is appended to the item's `mec_voter_ids`; a `voter_id` already present in that list may not vote twice and is rejected with `ERR_DUPLICATE_MEC_VOTE`. Endorsement moves the item to `MEC_ENDORSED`, and for an `APPLICATION_APPROVAL` item the linked application automatically advances `COMMITTEE_REVIEW` → `BOARD_REVIEW`.

Board action is the final word, exercised by a `BoardMember` and guarded twice: the item must be in `MEC_ENDORSED` (`ERR_ITEM_NOT_MEC_ENDORSED`), and the acting board member's `X-User-ID` must not appear in the item's `mec_voter_ids` (`ERR_SOD_BOARD_CONFLICT`, 403). Either way, the item records the actor as `board_voter_id`. Ratification moves the item to `BOARD_RATIFIED` and cascades by kind: an `APPLICATION_APPROVAL` ratification approves the application (the cascade below); a `PRIVILEGE_GRANT` ratification flips the delineation to `GRANTED` and creates the privilege grant; an `ADVERSE_ACTION` ratification decides the case per the hearing outcome in §3.8. Declination moves the item to `BOARD_DECLINED` and, for an `APPLICATION_APPROVAL` item, denies the application.

Approval of an application — `BOARD_REVIEW` → `APPROVED`, automatic on ratification — is the richest cascade in the system. The application's `version` increments, and the member's `version` increments with it. For an `INITIAL` application, the member's `membership_status` moves `APPLICANT` → `ACTIVE` and posture is recomputed from the freshly created grants. For a `REAPPOINTMENT` application, the member's `current_term_start` is stamped with the ratification instant and `current_term_end` is recomputed by calendar arithmetic as exactly two years later, in UTC — the term is always two calendar years. In both cases, every `CRITERIA_MET` delineation on the application flips to `GRANTED` and spawns a **PrivilegeGrant** in `PROVISIONAL` whose `effective_until` equals the member's `current_term_end`; each such grant creation itself increments the member's `active_privilege_line_count` by one and recomputes `privilege_posture`. Delineations in `CRITERIA_UNMET` flip to `DENIED` without further effect.

Denial — `BOARD_REVIEW` → `DENIED`, automatic on declination — copies the deciding agenda item's recorded rationale into the application's `decision_reason`. For an `INITIAL` application the member simply remains `APPLICANT`. For a `REAPPOINTMENT` application the system additionally auto-creates an **AdverseActionCase** of `case_kind` `DENIAL_OF_REAPPOINTMENT` referencing the member — which itself schedules a `hearing_request_deadline` per §3.8.

The reappointment window closes the loop on timing. A `REAPPOINTMENT` application may be submitted only inside the half-open window that opens exactly 180 days before the member's `current_term_end` and closes at `current_term_end`: submission at the opening instant is inside the window, while submission exactly at `current_term_end` is outside it — too late — and is rejected with `ERR_OUTSIDE_REAPPOINTMENT_WINDOW`. If the clock passes `current_term_end` while a reappointment application still sits in `BOARD_REVIEW`, the application expires automatically — `BOARD_REVIEW` → `EXPIRED` — and the member lapses with it: `membership_status` falls to `LAPSED`, every `ACTIVE` grant expires at the term boundary, and posture is recomputed. More generally, whenever the clock passes `current_term_end` with no approved reappointment in place, an `ACTIVE` member moves to `LAPSED`, all their `ACTIVE` grants move to `EXPIRED`, and posture falls to `NONE`.

### 3.5. Privilege Grants and Focused/Ongoing Performance Evaluation

A **PrivilegeGrant** is the exercisable artifact: it records the holding `member_id`, the source `delineation_id`, and the `privilege_line` copied from the delineation at grant time, and it runs over the half-open interval `[effective_from, effective_until)` — at creation, a non-temporary grant's `effective_until` must equal the member's `current_term_end`, keeping every line co-terminous with the appointment term. Grants are born `PROVISIONAL`, with `fppe_cases_completed` at zero and `suspension_reason` unset.

Maturation is evidence-driven. When a grant's `fppe_cases_completed` reaches the `fppe_case_count` required by the specialty criteria for its line, the grant flips automatically `PROVISIONAL` → `ACTIVE`, and the member's `active_privilege_line_count` and `privilege_posture` are recomputed. Expiry is clock-driven: the instant the clock reaches `effective_until`, an `ACTIVE` grant moves to `EXPIRED`, with the same recomputation. Relinquishment is the practitioner's own act — the grant must be in `PROVISIONAL` or `ACTIVE` (`ERR_GRANT_NOT_RELINQUISHABLE`) and the acting practitioner must be the grant's holder (`ERR_NOT_GRANT_HOLDER`, 403) — landing the grant in the terminal `RELINQUISHED` state, again with member counts and posture recomputed. Suspension and revocation arrive through the cascades of §3.6 and §3.8.

Oversight of a grant runs through the **PerformanceReview**. A coordinator opens one with the subject `member_id`, the `privilege_grant_id` under review, a `review_kind` of `FPPE` or `OPPE`, and the measurement window `period_start` to `period_end` — a half-open interval. The review begins in `COLLECTING`, with `metric_count` and `retracted_metric_count` at zero, `provisional_composite_score`, `final_composite_score`, and `outcome` all unset.

During collection the coordinator attaches **PerformanceMetric** rows, each naming the parent `review_id`, a `metric_domain` — `CLINICAL_QUALITY`, `PATIENT_SAFETY`, `DOCUMENTATION`, `CITIZENSHIP`, or `UTILIZATION` — a `raw_value`, the domain's `domain_weight` within the composite, the `collected_at` instant, and optionally a `passed_fppe_case` flag (defaulting to false) marking a passed proctored FPPE case. Two structural guards apply at intake: `collected_at` must fall inside the review's measurement window `[period_start, period_end)` (`ERR_METRIC_OUTSIDE_WINDOW`), and all metrics of the review that share a domain must carry the same `domain_weight` (`ERR_METRIC_WEIGHT_DOMAIN_MISMATCH`). Each attachment computes the metric's `normalized_value` and recomputes the review's counters; retraction by a coordinator flips a metric from `ACTIVE` to `RETRACTED` and recomputes `metric_count` and `retracted_metric_count` again. While a grant is suspended, its reviews in `COLLECTING` or `EVALUATION` stay open but new metric recording on them is blocked.

Normalization maps each raw value into a comparable scale. For `CLINICAL_QUALITY`, the normalized value is one hundred minus five times the raw value; for `PATIENT_SAFETY`, one hundred minus eight times the raw value; for `DOCUMENTATION` and `CITIZENSHIP`, the raw value passes through unchanged; for `UTILIZATION`, one hundred minus twice the absolute difference between the raw value and eighty-five. Each result is rounded half-up to 2 decimal places and then clamped into the range 0.00 to 100.00 inclusive — the clamp follows the rounding, per §2.6.

Closing collection — a coordinator's act — moves the review `COLLECTING` → `EVALUATION`; the review must still be collecting (`ERR_REVIEW_NOT_COLLECTING`) and must hold at least one active metric, so a review whose `metric_count` is zero is rejected with `ERR_NO_METRICS`.

Computing the provisional result — again the coordinator — requires `EVALUATION` (`ERR_REVIEW_NOT_EVALUABLE`) and produces `provisional_composite_score` under the provisional variant of the composite calculation. Aggregation is pinned: first, within each domain, the `normalized_value`s of the review's `ACTIVE` metrics are averaged and the average is rounded half-up to 2 decimal places; then the composite is the sum over domains of each rounded domain score multiplied by that domain's `domain_weight`, itself rounded half-up to 2 decimal places. The provisional variant is boundary-inclusive: a metric whose `collected_at` equals `period_end` exactly is included, while retracted metrics are always excluded.

Finalization belongs to the `CredentialsCommitteeChair` and requires `PROVISIONAL_RESULT` (`ERR_REVIEW_NOT_PROVISIONAL`). One structural gate stands in front of it: the `domain_weight`s of the review's active metrics must sum to exactly 1.000, else `ERR_WEIGHT_SUM_INVALID`. Finalization computes `final_composite_score` under the final variant — identical to the provisional aggregation except that metrics collected at exactly `period_end` are excluded, honoring the strict half-open window; the same data can therefore yield a different composite — and derives the review's `outcome` by threshold: a final composite of at least 70.00 is `SATISFACTORY`; at least 50.00 but below 70.00 is `MARGINAL`; below 50.00 is `UNSATISFACTORY`. The boundary is inclusive upward — exactly 70.00 is `SATISFACTORY` — and the comparison always reads the rounded value, so a raw aggregate of 49.995 is first rounded to 50.00 and therefore lands in `MARGINAL`, not below the line.

Finalization cascades outward in two directions. When an `OPPE` review lands `UNSATISFACTORY`, the system auto-proposes an **AdverseActionCase** of `case_kind` `RESTRICTION` whose `linked_review_id` references this review — the first cascade link from performance data into the adverse-action track. When an `FPPE` review lands `SATISFACTORY` or `MARGINAL`, each metric on the review flagged `passed_fppe_case` increments the underlying grant's `fppe_cases_completed` by one — and if that count thereby reaches the criteria's `fppe_case_count`, the grant flips `PROVISIONAL` → `ACTIVE` with the recomputations described above. Finally, the chair may close a finalized review — `FINAL_RESULT` → `CLOSED`, the terminal state; attempting closure from any other state is rejected with `ERR_INVALID_STATE`.

### 3.6. Expirable Credentials, Expiry Risk, and the Suspension Cascade

Licensure lives in the **ExpirableCredential**. A coordinator registers one with the holding `member_id`, a `credential_kind` — `STATE_LICENSE`, `DEA`, `BOARD_CERT`, `MALPRACTICE_INSURANCE`, or `ACLS` — the issuer-assigned `credential_number`, the `issued_on` date, the `expires_on` instant, and optionally a `supersedes_credential_id` chaining the row to the credential it replaces. The row begins `CURRENT`, and registering it recomputes the member's expiry risk.

The risk score looks forward from the logical clock. For each of the member's credentials in `CURRENT` status, the system computes the whole days remaining until expiry — the elapsed seconds between the clock and `expires_on`, divided by the eighty-six thousand four hundred seconds in a day, rounded down. A credential already past its expiry contributes one hundred points; one expiring in thirty days or fewer contributes fifty points; one expiring in more than thirty but no more than ninety days contributes twenty-five points; anything further out contributes nothing. Contributions from `STATE_LICENSE` and `MALPRACTICE_INSURANCE` credentials are then multiplied by one-and-a-half. The contributions sum into `credential_expiry_risk_score`, rounded half-up to 2 decimal places, and a score at or above the suspension threshold of 75.00 flags the member for the auto-suspension cascade below. The score recomputes on every clock advance and on every credential creation, renewal, revocation, or lapse.

A retroactive read serves auditors: the same calculation can be evaluated as of a past instant supplied as `as_of`, considering only credentials whose `issued_on` is on or before that instant and measuring days-to-expiry from it rather than from the current clock. The computed read returns the score as `risk_score` together with the `variant` under which it was produced; the same credentials can legitimately yield different scores under the live and chronological variants.

Lapse is automatic: the instant the clock reaches `expires_on`, a `CURRENT` credential moves to `LAPSED`. That single flip is the second cascade link. The member's risk score recomputes; and when the lapsed kind is `STATE_LICENSE`, `BOARD_CERT`, or `MALPRACTICE_INSURANCE`, every `ACTIVE` privilege grant of the member whose specialty criteria require that kind moves to `SUSPENDED`, with `suspension_reason` recording the lapsed `credential_kind`. Each suspended grant decrements the member's `active_privilege_line_count` by one, and `privilege_posture` is recomputed — falling to `NONE` when every line is suspended, or to `EMERGENCY_ONLY` when a temporary privilege still stands. The suspension reaches sideways as well: performance reviews on the suspended grant that sit in `COLLECTING` or `EVALUATION` stay open but have metric recording blocked, and any open `PRIVILEGE_GRANT` agenda items referencing the underlying delineation move to `DEFERRED`.

Revocation is the deliberate counterpart: the `CredentialsCommitteeChair` may revoke a credential only while it is `CURRENT` (`ERR_CREDENTIAL_NOT_CURRENT`), landing it in the terminal `REVOKED` state and firing exactly the same cascade as a lapse.

Renewal repairs the damage. A coordinator renews a credential only from `LAPSED` (`ERR_CREDENTIAL_NOT_LAPSED`), supplying a new `credential_number`, `issued_on`, and `expires_on`; the new expiry must lie strictly after the current clock (`ERR_CREDENTIAL_EXPIRY_PAST`, 400). Renewal writes a fresh `CURRENT` row whose `supersedes_credential_id` points at the old row, which itself moves to the terminal `RENEWED` state — the renewal chain is thus self-referential across rows. The reinstatement cascade follows: every grant of the member sitting in `SUSPENDED` whose `suspension_reason` matches the renewed credential's kind moves back to `ACTIVE`, its `suspension_reason` is cleared, the member's `active_privilege_line_count` is incremented accordingly, posture is recomputed, and the risk score recomputes once more.

### 3.7. Temporary, Emergency, and Disaster Privileges

A **TemporaryPrivilege** covers the gap between full credentialing and urgent need. A coordinator requests one with the recipient `member_id`, a sponsoring `sponsor_member_id`, a `temp_kind` of `TEMPORARY`, `EMERGENCY`, or `DISASTER`, the `privilege_line` to be exercised, and the exercise window `window_start` through `window_end` — a closed interval, inclusive at both ends, per §2.11. Self-sponsorship is incoherent: a `sponsor_member_id` equal to the recipient's `member_id` is rejected with `ERR_SELF_SPONSOR` (422). A `DISASTER` request must carry a `disaster_declaration_ref` naming the external disaster declaration (`ERR_DISASTER_REF_REQUIRED`, 400); for the other kinds it stays empty. The request lands in `PENDING_SPONSOR`.

Activation belongs to the `CredentialsCommitteeChair` and is guarded five-deep, in the validation order of §2.9. The request must still be `PENDING_SPONSOR` (`ERR_TEMP_NOT_PENDING`). The sponsor must be qualified — a member whose `membership_status` is `ACTIVE` and whose `privilege_posture` is `FULL` (`ERR_SPONSOR_NOT_QUALIFIED`, 403). The recipient must be eligible — `membership_status` in `APPLICANT` or `ACTIVE` (`ERR_MEMBER_NOT_ELIGIBLE`). The window must fit its kind's cap: at most twenty-four hours for `EMERGENCY`, at most seventy-two hours for `DISASTER`, at most one hundred twenty days for `TEMPORARY` (`ERR_TEMP_WINDOW_TOO_LONG`). And the window must not collide with the member's existing active temporary privileges (`ERR_TEMP_OVERLAP`), under the buffered-overlap rule below. A successful activation moves the request to `ACTIVE` and recomputes the recipient's `privilege_posture` — a member whose posture was `NONE` rises to `EMERGENCY_ONLY`.

The overlap rule buffers the existing windows, never the candidate. For a candidate window from `window_start` to `window_end` and each existing `ACTIVE` temporary privilege of the same member, the existing window is extended by one day on both ends, and a conflict exists when the candidate's start falls on or before the buffered end and the buffered start falls on or before the candidate's end. Consequently, a candidate beginning exactly one day after an existing window ends still conflicts — it sits inside the buffer — while one beginning two days after does not. This is deliberately stricter than the half-open grant semantics of §2.11, where back-to-back intervals are permitted.

Expiry and early termination close the lifecycle. Because the window is closed, an active temporary privilege expires automatically — `ACTIVE` → `EXPIRED` — only once the clock moves strictly past `window_end`. The chair may instead terminate it early, `ACTIVE` → `TERMINATED_EARLY`, rejected from any other state with `ERR_TEMP_NOT_ACTIVE`. Either ending recomputes the member's `privilege_posture`.

### 3.8. Adverse Action, Fair Hearings, and NPDB Reporting

When professional practice evaluation or other evidence warrants curtailment, a `DepartmentChief` proposes an **AdverseActionCase**, naming the `subject_member_id`, their own member record as `proposed_by_member_id`, a `case_kind` of `SUSPENSION`, `REVOCATION`, `DENIAL_OF_REAPPOINTMENT`, or `RESTRICTION`, and — for a `RESTRICTION` — the `restriction_days` length (defaulting to zero); a `linked_review_id` may reference the OPPE review that evidenced the case. Creation stamps `proposed_at` and schedules the `hearing_request_deadline` as `proposed_at` plus the hearing-request window — a fixed number of days configured for the installation, the same window later used to extend the deadline on remand. The case opens in `PROPOSED`. Its `npdb_reportable` flag is derived rather than asserted: a case whose kind is `SUSPENSION`, `REVOCATION`, or `DENIAL_OF_REAPPOINTMENT` becomes reportable upon reaching `FINAL_ADVERSE`, while a `RESTRICTION` case is reportable only when its `restriction_days` exceeds thirty days.

MEC endorsement by a `MedicalExecutiveCommitteeChair` moves the case `PROPOSED` → `MEC_ENDORSED`, requiring both that the case still be proposed (`ERR_CASE_NOT_PROPOSED`) and that the subject's `membership_status` be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`). The proposing chief retains an exit: withdrawal is permitted from `PROPOSED` or `MEC_ENDORSED` — beyond that, `ERR_CASE_NOT_WITHDRAWABLE` — and only by the chief whose member record matches `proposed_by_member_id` (`ERR_NOT_CASE_PROPOSER`, 403), landing the case in the terminal `WITHDRAWN` state.

Once endorsed, the fair-hearing clock runs. The subject — and only the subject, a `Practitioner` whose identity matches `subject_member_id` (`ERR_NOT_CASE_SUBJECT`, 403) — may request a hearing while the case is in `MEC_ENDORSED` (from any other state, `ERR_CASE_NOT_ENDORSED`) and while the clock has not passed `hearing_request_deadline` (`ERR_HEARING_REQUEST_LATE`); the request stamps `hearing_requested_at`, moves the case to `HEARING_REQUESTED`, and appends the case's `id` to the `sod_exclusion_tags` of both subject and proposer — the segregation-of-duties cascade of §2.10. Silence is a waiver: if the clock passes `hearing_request_deadline` with no hearing requested, a case in `MEC_ENDORSED` moves automatically to `FINAL_ADVERSE`, carrying the same finalization side effects as an upheld hearing.

A hearing needs a panel, seated by the `HearingOfficer`. Each **HearingPanel** row names the `case_id`, the `panel_member_id`, and a `panel_role` of `CHAIR` or `MEMBER`, and is stamped `seated_at` into the initial `SEATED` state. Seating is refused when the panelist's `sod_exclusion_tags` already contain the case's `id` (`ERR_PANELIST_SOD_EXCLUDED`, 403) or when the case is not in `MEC_ENDORSED`, `HEARING_REQUESTED`, `REMANDED`, or `HEARING_HELD` (`ERR_INVALID_STATE`). Each seating grows the case's seated history and recomputes its quorum. Recusal moves a seated panelist to `RECUSED` — attempted on anyone not `SEATED`, it is rejected with `ERR_PANELIST_NOT_SEATED` — and disqualification is automatic: a seated panelist whose member record later acquires the case's `id` in `sod_exclusion_tags` flips to `DISQUALIFIED`. Both removals re-evaluate quorum for the case.

Quorum is determined so that departures cannot silently lower the bar. The denominator is the total number of panel rows ever seated for the case, counting `SEATED`, `RECUSED`, and `DISQUALIFIED` rows alike — evaluation order is pinned denominator-first from row history, which breaks the circular dependency between quorum and the currently eligible pool. `quorum_required` is the larger of three and the result of halving that total, rounded up to a whole number. The eligible panel is the set of rows still `SEATED` whose panelist is not excluded for the case, and quorum is met when the eligible count reaches `quorum_required`. Convening the hearing — the `HearingOfficer`'s act — requires the case in `HEARING_REQUESTED` (`ERR_CASE_NOT_IN_HEARING`) and a satisfied quorum (`ERR_HEARING_QUORUM_UNMET`), moving the case to `HEARING_HELD`.

Decision takes a single input, `decision`, and branches three ways from `HEARING_HELD` (from any other state, `ERR_CASE_NOT_HEARD`). A `decision` of `UPHELD` lands the case in `FINAL_ADVERSE`; `OVERTURNED` lands it in `FINAL_NO_ACTION`; `REMAND` lands it in `REMANDED`; any other value is rejected as `ERR_INVALID_REQUEST`. The three outcomes carry asymmetric weight. `FINAL_ADVERSE` spawns an NPDB report of `report_kind` `REPORT_ADVERSE_ACTION` when the case is `npdb_reportable`, with `submission_deadline` set thirty days from the final-adverse instant; it moves the member's `membership_status` to `SUSPENDED` for a `SUSPENSION` case or to `TERMINATED` for `REVOCATION` or `DENIAL_OF_REAPPOINTMENT`; for `REVOCATION` it additionally revokes every `ACTIVE` and `PROVISIONAL` grant of the member — each such revocation spawns its own `REPORT_ADVERSE_ACTION` filing with a thirty-day deadline — and drives `privilege_posture` to `NONE`; and it flips the case's `ADVERSE_ACTION` agenda item to `COMMITTEE_APPROVED` if that item still sits in `AGENDA`. The member-level cascades match: suspension drives posture to `NONE` and every `ACTIVE` grant to `SUSPENDED`, while termination revokes or expires all grants and drives posture to `NONE`. `FINAL_NO_ACTION`, by contrast, produces no NPDB report and leaves the member untouched. `REMANDED` extends the hearing-request deadline to the remand instant plus the hearing-request window, and the loop `HEARING_HELD` → `REMANDED` → `HEARING_REQUESTED` → `HEARING_HELD` is permitted — the subject may re-request the hearing under the same guards, so the case must be in `REMANDED` (any other state draws `ERR_CASE_NOT_ENDORSED`) and the clock must not have passed the extended `hearing_request_deadline` (`ERR_HEARING_REQUEST_LATE`), with `hearing_requested_at` stamped anew on each request.

Reinstatement is the way back from suspension, exercised by a `MedicalExecutiveCommitteeChair`. The member must be in `SUSPENDED` (`ERR_MEMBER_NOT_SUSPENDED`) and must have no open adverse action case — none in `PROPOSED`, `MEC_ENDORSED`, `HEARING_REQUESTED`, `HEARING_HELD`, or `REMANDED` (`ERR_OPEN_CASE_EXISTS`). Success moves `membership_status` back to `ACTIVE`, recomputes `privilege_posture`, and increments the member's `version`.

NPDB obligations close the loop with the federal data bank. A coordinator files an **NpdbReport** with the subject `member_id`, a `report_kind` — `QUERY_INITIAL` or `QUERY_REAPPOINTMENT` for the queries that gate verification in §3.2, or `REPORT_ADVERSE_ACTION`, `REPORT_CORRECTION`, `REPORT_VOID` for reportable events — and, for every `REPORT_*` kind, the source `case_id` (`ERR_NPDB_CASE_REQUIRED`, 400); query kinds carry no case reference. A filing opens in `SUBMITTED` status with `submitted_at` stamped and `is_late` false. Deadlines are inherited by kind: a `REPORT_ADVERSE_ACTION` filing's `submission_deadline` is the triggering event's instant plus thirty days; a `REPORT_CORRECTION` or `REPORT_VOID` inherits the deadline of the report it corrects or voids; `QUERY_*` kinds carry no deadline at all. Timeliness is strict at the boundary: `is_late` is true when `submitted_at` is strictly later than `submission_deadline`, while a filing exactly at its deadline is on time — and a report created late lands directly in `LATE` with `is_late` set, rather than passing through `SUBMITTED` cleanly.

Two dispositions remain. Acknowledgment by a coordinator moves a report from `SUBMITTED` or `LATE` to the terminal `ACKNOWLEDGED` (`ERR_NPDB_NOT_ACKNOWLEDGEABLE` from any other state). Voiding is the chair's correction mechanism: a report in `SUBMITTED` or `LATE` may be voided (`ERR_NPDB_NOT_VOIDABLE` otherwise), but never without a replacement — the voiding call must carry `correction_report_id` identifying a `REPORT_CORRECTION` report for the same `case_id`, created in the same request batch, and a void without that correction is rejected with `ERR_CORRECTION_REQUIRED`. A voided report lands in the terminal `VOIDED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. Request bodies, response payloads, and side effects for each operation are specified by the narratives of §2 and §3; this table fixes only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mso/_clock/set_current_utc` | Set the logical clock to a supplied instant | MedicalStaffCoordinator |
| POST | `/mso/specialty-criteria` | Create specialty criteria | MedicalStaffCoordinator |
| GET | `/mso/specialty-criteria` | List specialty criteria | Any |
| GET | `/mso/specialty-criteria/{id}` | Get one specialty criteria | Any |
| POST | `/mso/members` | Create a medical staff member record (applicant) | MedicalStaffCoordinator |
| GET | `/mso/members` | List members | Any |
| GET | `/mso/members/{id}` | Get one member | Any |
| POST | `/mso/members/{id}/reinstate` | Reinstate a SUSPENDED member to ACTIVE | MedicalExecutiveCommitteeChair |
| GET | `/mso/members/{id}/credential-risk` | Computed read of credential expiry risk, optionally as of a past timestamp | MedicalStaffCoordinator, CredentialsCommitteeChair, MedicalExecutiveCommitteeChair |
| POST | `/mso/applications` | Create an application (INITIAL or REAPPOINTMENT); OCC on the member's version | MedicalStaffCoordinator |
| GET | `/mso/applications` | List applications | Any |
| GET | `/mso/applications/{id}` | Get one application | Any |
| POST | `/mso/applications/{id}/submit` | Submit an application (DRAFT → SUBMITTED) | MedicalStaffCoordinator |
| POST | `/mso/applications/{id}/advance-to-committee` | Advance a PSV_COMPLETE application to COMMITTEE_REVIEW | CredentialsCommitteeChair |
| POST | `/mso/applications/{id}/withdraw` | Withdraw an application | MedicalStaffCoordinator |
| POST | `/mso/verification-items` | Attach a verification item to an application | MedicalStaffCoordinator |
| GET | `/mso/verification-items` | List verification items | Any |
| GET | `/mso/verification-items/{id}` | Get one verification item | Any |
| POST | `/mso/verification-items/{id}/mark-received` | Mark an item RECEIVED (or re-receive from DISCREPANCY) | MedicalStaffCoordinator |
| POST | `/mso/verification-items/{id}/verify` | Verify a RECEIVED item | MedicalStaffCoordinator |
| POST | `/mso/verification-items/{id}/flag-discrepancy` | Flag a discrepancy on a RECEIVED item | MedicalStaffCoordinator |
| POST | `/mso/verification-items/{id}/waive` | Waive a verification item | CredentialsCommitteeChair |
| POST | `/mso/delineations` | Request a privilege delineation on an application; OCC on the application's version | MedicalStaffCoordinator |
| GET | `/mso/delineations` | List delineations | Any |
| GET | `/mso/delineations/{id}` | Get one delineation | Any |
| POST | `/mso/delineations/{id}/evaluate` | Evaluate a delineation against specialty criteria | MedicalStaffCoordinator |
| GET | `/mso/privilege-grants` | List privilege grants | Any |
| GET | `/mso/privilege-grants/{id}` | Get one privilege grant | Any |
| POST | `/mso/privilege-grants/{id}/relinquish` | Holder relinquishes a grant | Practitioner |
| POST | `/mso/performance-reviews` | Open an FPPE or OPPE review | MedicalStaffCoordinator |
| GET | `/mso/performance-reviews` | List performance reviews | Any |
| GET | `/mso/performance-reviews/{id}` | Get one performance review | Any |
| POST | `/mso/performance-reviews/{id}/close-collection` | Close data collection (COLLECTING → EVALUATION) | MedicalStaffCoordinator |
| POST | `/mso/performance-reviews/{id}/compute-provisional` | Compute the provisional composite (EVALUATION → PROVISIONAL_RESULT) | MedicalStaffCoordinator |
| POST | `/mso/performance-reviews/{id}/finalize` | Finalize the review and derive its outcome (PROVISIONAL_RESULT → FINAL_RESULT) | CredentialsCommitteeChair |
| POST | `/mso/performance-reviews/{id}/close` | Close a finalized review (FINAL_RESULT → CLOSED) | CredentialsCommitteeChair |
| POST | `/mso/performance-metrics` | Attach a metric to a review | MedicalStaffCoordinator |
| GET | `/mso/performance-metrics` | List performance metrics | Any |
| GET | `/mso/performance-metrics/{id}` | Get one performance metric | Any |
| POST | `/mso/performance-metrics/{id}/retract` | Retract a metric | MedicalStaffCoordinator |
| POST | `/mso/expirable-credentials` | Register an expirable credential | MedicalStaffCoordinator |
| GET | `/mso/expirable-credentials` | List expirable credentials | Any |
| GET | `/mso/expirable-credentials/{id}` | Get one expirable credential | Any |
| POST | `/mso/expirable-credentials/{id}/renew` | Renew a LAPSED credential, creating its successor row | MedicalStaffCoordinator |
| POST | `/mso/expirable-credentials/{id}/revoke` | Revoke a CURRENT credential | CredentialsCommitteeChair |
| POST | `/mso/temporary-privileges` | Request a temporary, emergency, or disaster privilege | MedicalStaffCoordinator |
| GET | `/mso/temporary-privileges` | List temporary privileges | Any |
| GET | `/mso/temporary-privileges/{id}` | Get one temporary privilege | Any |
| POST | `/mso/temporary-privileges/{id}/activate` | Activate a pending temporary privilege | CredentialsCommitteeChair |
| POST | `/mso/temporary-privileges/{id}/terminate` | Terminate an active temporary privilege early | CredentialsCommitteeChair |
| POST | `/mso/adverse-action-cases` | Propose an adverse action case | DepartmentChief |
| GET | `/mso/adverse-action-cases` | List adverse action cases | Any |
| GET | `/mso/adverse-action-cases/{id}` | Get one adverse action case | Any |
| POST | `/mso/adverse-action-cases/{id}/endorse` | MEC endorses a proposed case | MedicalExecutiveCommitteeChair |
| POST | `/mso/adverse-action-cases/{id}/withdraw` | Proposer withdraws the case | DepartmentChief |
| POST | `/mso/adverse-action-cases/{id}/request-hearing` | Subject requests a fair hearing | Practitioner |
| POST | `/mso/adverse-action-cases/{id}/hold-hearing` | Convene the hearing (quorum check) | HearingOfficer |
| POST | `/mso/adverse-action-cases/{id}/decide` | Render the hearing decision (UPHELD, OVERTURNED, or REMAND) | HearingOfficer |
| POST | `/mso/hearing-panels` | Seat a hearing panelist | HearingOfficer |
| GET | `/mso/hearing-panels` | List hearing panel seats | Any |
| GET | `/mso/hearing-panels/{id}` | Get one hearing panel seat | Any |
| POST | `/mso/hearing-panels/{id}/recuse` | Recuse a seated panelist | HearingOfficer |
| POST | `/mso/npdb-reports` | File an NPDB query or report | MedicalStaffCoordinator |
| GET | `/mso/npdb-reports` | List NPDB reports | Any |
| GET | `/mso/npdb-reports/{id}` | Get one NPDB report | Any |
| POST | `/mso/npdb-reports/{id}/acknowledge` | Acknowledge a submitted report | MedicalStaffCoordinator |
| POST | `/mso/npdb-reports/{id}/void` | Void a report, naming its replacement correction | CredentialsCommitteeChair |
| POST | `/mso/agenda-items` | Create an agenda item (also auto-created by application advancement) | MedicalStaffCoordinator, CredentialsCommitteeChair |
| GET | `/mso/agenda-items` | List agenda items | Any |
| GET | `/mso/agenda-items/{id}` | Get one agenda item | Any |
| POST | `/mso/agenda-items/{id}/committee-vote` | Record a committee vote batch | CredentialsCommitteeChair |
| POST | `/mso/agenda-items/{id}/defer` | Defer an agenda item | CredentialsCommitteeChair |
| POST | `/mso/agenda-items/{id}/reagenda` | Return a deferred item to the agenda | CredentialsCommitteeChair |
| POST | `/mso/agenda-items/{id}/mec-endorse` | MEC endorses a committee-approved item | MedicalExecutiveCommitteeChair |
| POST | `/mso/agenda-items/{id}/board-ratify` | Board ratifies an MEC-endorsed item | BoardMember |
| POST | `/mso/agenda-items/{id}/board-decline` | Board declines an MEC-endorsed item | BoardMember |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_NO_VERIFICATION_ITEMS` | 409 Conflict |
| `ERR_PENDING_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_OUTSIDE_REAPPOINTMENT_WINDOW` | 409 Conflict |
| `ERR_PSV_NOT_COMPLETE` | 409 Conflict |
| `ERR_DELINEATIONS_UNEVALUATED` | 409 Conflict |
| `ERR_APPLICATION_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_VERIFICATION_NOT_REQUESTED` | 409 Conflict |
| `ERR_VERIFICATION_NOT_RECEIVED` | 409 Conflict |
| `ERR_VERIFICATION_NOT_WAIVABLE` | 409 Conflict |
| `ERR_PRIMARY_SOURCE_NOT_WAIVABLE` | 403 Forbidden |
| `ERR_NPDB_QUERY_MISSING` | 409 Conflict |
| `ERR_DELINEATION_NOT_EVALUABLE` | 409 Conflict |
| `ERR_PRIVILEGE_LINE_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_GRANT_NOT_RELINQUISHABLE` | 409 Conflict |
| `ERR_NOT_GRANT_HOLDER` | 403 Forbidden |
| `ERR_REVIEW_NOT_COLLECTING` | 409 Conflict |
| `ERR_NO_METRICS` | 409 Conflict |
| `ERR_REVIEW_NOT_EVALUABLE` | 409 Conflict |
| `ERR_REVIEW_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_WEIGHT_SUM_INVALID` | 409 Conflict |
| `ERR_METRIC_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_METRIC_WEIGHT_DOMAIN_MISMATCH` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_LAPSED` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_CURRENT` | 409 Conflict |
| `ERR_CREDENTIAL_EXPIRY_PAST` | 400 Bad Request |
| `ERR_TEMP_NOT_PENDING` | 409 Conflict |
| `ERR_TEMP_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPONSOR_NOT_QUALIFIED` | 403 Forbidden |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_TEMP_WINDOW_TOO_LONG` | 409 Conflict |
| `ERR_TEMP_OVERLAP` | 409 Conflict |
| `ERR_DISASTER_REF_REQUIRED` | 400 Bad Request |
| `ERR_SELF_SPONSOR` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_PROPOSED` | 409 Conflict |
| `ERR_CASE_NOT_ENDORSED` | 409 Conflict |
| `ERR_CASE_NOT_IN_HEARING` | 409 Conflict |
| `ERR_CASE_NOT_HEARD` | 409 Conflict |
| `ERR_CASE_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_NOT_CASE_PROPOSER` | 403 Forbidden |
| `ERR_NOT_CASE_SUBJECT` | 403 Forbidden |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_HEARING_REQUEST_LATE` | 409 Conflict |
| `ERR_HEARING_QUORUM_UNMET` | 409 Conflict |
| `ERR_PANELIST_NOT_SEATED` | 409 Conflict |
| `ERR_PANELIST_SOD_EXCLUDED` | 403 Forbidden |
| `ERR_OPEN_CASE_EXISTS` | 409 Conflict |
| `ERR_MEMBER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_NPDB_NOT_ACKNOWLEDGEABLE` | 409 Conflict |
| `ERR_NPDB_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CORRECTION_REQUIRED` | 409 Conflict |
| `ERR_NPDB_CASE_REQUIRED` | 400 Bad Request |
| `ERR_ITEM_NOT_VOTABLE` | 409 Conflict |
| `ERR_COMMITTEE_QUORUM_UNMET` | 409 Conflict |
| `ERR_CASE_NOT_READY_FOR_COMMITTEE` | 409 Conflict |
| `ERR_ITEM_NOT_DEFERRABLE` | 409 Conflict |
| `ERR_ITEM_NOT_REAGENDABLE` | 409 Conflict |
| `ERR_ITEM_NOT_COMMITTEE_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_MEC_VOTE` | 409 Conflict |
| `ERR_ITEM_NOT_MEC_ENDORSED` | 409 Conflict |
| `ERR_SOD_BOARD_CONFLICT` | 403 Forbidden |
| `ERR_AGENDA_REF_MISMATCH` | 422 Unprocessable Entity |

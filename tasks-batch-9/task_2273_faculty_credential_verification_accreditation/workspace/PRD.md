# Faculty Credential Accreditation API — Product Requirements Document

## 1. Introduction

Every regional and programmatic accreditor asks a university the same deceptively simple question: for each course you taught last term, can you prove the person standing in front of the students was qualified to be there? Answering it today is a manual archaeology project. Terminal degrees live in paper dossiers, official transcripts arrive months after a contract has already been signed, foreign degrees need an outside agency to say what they are equivalent to, and the handful of instructors who qualify on documented professional experience rather than on a diploma are justified in narrative memos that nobody can aggregate. When the accreditor arrives and names three unqualified assignments, the roster office has no systematic way to show what changed, who decided it, and whether the program's faculty are collectively adequate.

This document specifies the Faculty Credential Accreditation API — the system of record for the university accreditation and faculty roster office. It carries a discipline taxonomy, academic programs and terms; it collects credential records, official transcripts and foreign credential evaluations; it decides, for every faculty-to-section assignment, whether the instructor is qualified and, if not, exactly which exception the accreditor will read; it generates per-term, per-program faculty rosters with exceptions flagged and certifies them; it gates adjunct, clinical and full-time contract issuance behind a verified dossier; it tracks ongoing professional development; and it drives the accreditor review, findings and remediation negotiation to a close.

Two design commitments shape everything that follows. First, **segregation of duties is structural, not advisory**: the analyst who verified a faculty member's credentials may not be the analyst who decides that faculty member's tested-experience justification, and the liaison who certifies a roster may not be a user who decided any justification counted inside it. Second, **every derived number is reconciled in the response of the request that caused it**. When a credential is repudiated, the faculty dossier, the affected course assignments, the covering rosters, the owning programs and any open accreditor reviews all move in the same transaction, and the client sees the result immediately. There is no eventual consistency and no background sweep.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting principles that hold for every endpoint in the system. Where a rule here and a workflow narrative in §3 discuss the same field, they reinforce rather than contradict each other.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the capacity in which they act. A request whose `X-User-ID` header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any routing, existence or shape checking happens. A request whose `X-User-Role` header is missing, or whose value is not among the roles authorized for the endpoint being called, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403) — a missing role header is treated as an unauthorized role, never as a malformed request.

The system recognizes exactly seven roles:

- `SystemAdmin` — institutional reference-data owner. Maintains the discipline taxonomy, the program catalogue and the logical clock. Never touches credential decisions, rosters or reviews.
- `RegistrarOfficer` — faculty roster office clerk. Owns faculty records, credential filing, official transcript collection and separation. Files evidence but never judges it.
- `CredentialAnalyst` — credential evaluator. Verifies, rejects and repudiates credentials, orders and completes foreign credential evaluations, re-verifies remediating assignments, decides tested-experience justifications and verifies professional development.
- `ProgramDean` — dean of one academic program. Owns that program's sections, assignments, justifications, rosters and contracts.
- `Instructor` — a faculty member acting for themselves. Countersigns their own contract, logs their own professional development, and reads only their own records.
- `AccreditationLiaison` — accreditation office liaison. Generates and certifies rosters, decides program launches, and files remediation responses to the accreditor.
- `AccreditorReviewer` — external accreditor representative. Schedules reviews, drives review status, issues findings, and closes or sanctions.

Two roles are **entity-backed**, meaning `X-User-ID` is not an arbitrary operator string but the primary key of a stored row:

- When `X-User-Role` is `ProgramDean`, `X-User-ID` is the `id` of the acting `Program`; ownership checks on any resource that references a `Program` compare the resource's program foreign-key field to `X-User-ID`. For a section, that is the section's `program_id`; for an assignment, a justification or a withdrawal, it is the `program_id` of the assignment's section; for a contract void, it is the `home_program_id` of the contracted faculty member; for a roster, it is the roster's `program_id`.
- When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `FacultyMember`; ownership checks compare the resource's `faculty_member_id` to `X-User-ID`.

The other five roles — `SystemAdmin`, `RegistrarOfficer`, `CredentialAnalyst`, `AccreditationLiaison` and `AccreditorReviewer` — carry an **opaque** identity: `X-User-ID` is an operator identifier not tied to any persisted entity. The server records it where an audit trail demands it (as `verified_by_user_id` on a `CredentialRecord`, as `decided_by_user_id` on a `TestedExperienceJustification`, and as `certified_by_user_id` on a `FacultyRoster`) but never compares it to any entity's `id`. Opaque roles therefore skip the ownership rule entirely.

An entity-backed role that addresses a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This rule guards eighteen operations: `POST /programs/{programId}/launch-review`, `POST /course-sections`, `POST /course-assignments`, `POST /course-assignments/{assignmentId}/remediation`, `POST /course-assignments/{assignmentId}/withdrawal`, `POST /tested-experience-justifications`, `POST /tested-experience-justifications/{justificationId}`, `POST /tested-experience-justifications/{justificationId}/status`, `POST /tested-experience-justifications/{justificationId}/revision`, `POST /faculty-rosters`, `POST /faculty-contracts`, `POST /faculty-contracts/{contractId}/void`, `POST /faculty-contracts/{contractId}/countersignature`, `POST /pd-records`, `GET /faculty-members/{facultyMemberId}`, `GET /faculty-members/{facultyMemberId}/credential-records`, `GET /faculty-contracts/{contractId}` and `GET /pd-records/{pdRecordId}`. On `POST /programs/{programId}/launch-review`, ownership means `X-User-ID` equals the `programId` path parameter. On `POST /faculty-rosters` the check applies only when the caller is a `ProgramDean`; an `AccreditationLiaison` may open a roster for any program.

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100. `offset` is the number of rows to skip; it defaults to 0 and may not be negative. A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filter before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. The Logical Clock

There is no wall-clock read anywhere in this system. A single **logical clock** is the only source of "now" for every temporal rule: the contract issuance window, the accreditor lockout window, accreditor response due dates, professional-development activity dating, and the rolling professional-development cycle. The clock is settable by a `SystemAdmin` through a test-driving capability that accepts a `current_utc` instant, and readable by every role except `Instructor`. Until it is set for the first time, the clock reads `2026-08-01T00:00:00Z`, and both the set and the read capability report the resulting instant as `current_utc`.

Setting the clock mutates no stored row. Values that depend on the clock — most visibly the professional-development cycle — are re-derived when they are next read or next written, not eagerly rewritten across the database.

Where a rule speaks of "the clock date", it means the calendar date of the logical clock instant in UTC, compared against date-only fields such as `start_date`, `window_start_date` or `activity_date`.

### 2.5. Record Identity, Audit Fields and Pinned Snapshots

Every resource in this system is a root collection row addressed by its own identifier, and every one of them carries the same four system-managed properties:

- `id` (string) — a server-minted UUID with no type prefix.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, recording first creation.
- `updated_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations the client did not directly request.
- `version` (integer) — an integer that increments by exactly 1 on every mutation of the row.

All thirteen entity types — `DisciplineTaxonomy`, `Program`, `Term`, `FacultyMember`, `CredentialRecord`, `CredentialEvaluation`, `CourseSection`, `CourseAssignment`, `TestedExperienceJustification`, `FacultyRoster`, `FacultyContract`, `ProfessionalDevelopmentRecord` and `AccreditorReview` — carry all four. There is no entity in this system that omits `updated_at` or `version`.

Because derived fields are reconciled server-side, a row's `version` advances for reasons the caller never asked for. When an analyst repudiates a credential, the affected faculty member, their course assignments, the rosters covering those assignments, the owning programs and any open accreditor reviews each have `updated_at` refreshed and `version` incremented by 1, in the same request. §2.11 describes the shape of those cascades; §3 states each one concretely.

Two fields deliberately freeze a `version` rather than tracking it. `FacultyContract.credential_snapshot_version` pins the `version` of the `FacultyMember` as it stood at issuance, and `FacultyContract.dossier_snapshot_status` pins that faculty member's `dossier_status` at issuance (always `VERIFIED`, since issuance requires it). Neither is ever rewritten, so an auditor can see at a glance that the credential evidence moved after the contract was cut.

### 2.6. Numeric Precision

Three precision regimes coexist and must not be mixed up:

- **Scores and ratios are carried to 4 decimal places, rounded half up.** This covers `CourseAssignment.alignment_score`, `TestedExperienceJustification.tested_experience_score`, `Program.adequacy_ratio` and `FacultyRoster.adequacy_ratio_snapshot`.
- **Risk indices are carried to 2 decimal places, rounded half up.** Both `AccreditorReview.preliminary_risk_index` and `AccreditorReview.risk_index` are rounded independently, each to 2 decimal places.
- **Money is integer cents throughout.** `CredentialEvaluation.fee_cents`, `Program.credential_budget_cents`, `Program.budget_reserved_cents`, `Program.budget_spent_cents` and each `share_cents` inside `allocation_shares` are whole numbers of cents. Fee computation applies half-up rounding to whole cents exactly once, at the point stated in §3.3; per-share allocation floors rather than rounds, and reconciles with a residual pass so that shares always re-sum to the fee exactly.

Credit hours are handled as numbers; the per-term load ceiling is compared in whole credit hours. Professional-development contact hours are summed as a number carried to 1 decimal place, rounded half up.

### 2.7. Optimistic Concurrency on Section and Faculty Writes

Two write operations require the client to prove it has observed the current state of a parent row before it may attach a child to it. These are the only two version-bearing inputs in the system; no other endpoint accepts a version field, and supplying one elsewhere is not part of the contract.

**Creating a course assignment.** A `POST /course-assignments` request must carry `expected_section_version`, a non-optional field holding the client's last observed `version` of the target `CourseSection`. If that value does not equal the section's current `version`, the create is rejected with `ERR_STALE_SECTION_VERSION` (HTTP 412). The section's `version` advances whenever another writer names an instructor of record for it — which legitimately supersedes the incumbent assignment — so a stale value means the client's view of who currently holds the section is out of date.

**Issuing a faculty contract.** A `POST /faculty-contracts` request must carry `expected_faculty_version`, a non-optional field holding the client's last observed `version` of the target `FacultyMember`. If that value does not equal the faculty member's current `version`, the issuance is rejected with `ERR_STALE_FACULTY_VERSION` (HTTP 412). A faculty member's `version` advances on every dossier movement — verification, repudiation, evaluation completion, contract supersession — so a stale value means the credentialing evidence the dean relied upon is no longer the evidence of record.

Both writes also advance their parent: creating an assignment increments the `CourseSection.version`, and issuing a contract increments the `FacultyMember.version`. A client that wants to issue two contracts, or attach two assignments to one section, must therefore re-read the parent between the two calls.

### 2.8. Path Resolution and Reference Integrity

Identifiers in a request path are resolved strictly left to right, and the first one that does not resolve determines the response. A request to `GET /faculty-members/{facultyMemberId}/credential-records` whose `facultyMemberId` does not exist fails with `ERR_FACULTY_NOT_FOUND` before any credential record is looked at; a request to `GET /course-sections/{sectionId}/course-assignments` whose `sectionId` does not exist fails with `ERR_SECTION_NOT_FOUND`. Each entity has its own 404 code: `ERR_DISCIPLINE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_CREDENTIAL_RECORD_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_JUSTIFICATION_NOT_FOUND`, `ERR_ROSTER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PD_RECORD_NOT_FOUND` and `ERR_REVIEW_NOT_FOUND`.

Foreign keys carried in a request body are resolved after every path identifier has resolved, and among themselves they are checked in the order the endpoint declares its fields. A create request carrying two unresolvable references therefore reports the 404 belonging to the *first declared* one. `ERR_ROSTER_NOT_FOUND` additionally covers the case where an operation needs a program's anchor roster and no roster of the required status exists at all.

### 2.9. The Discipline Taxonomy and Alignment Scoring

The `DisciplineTaxonomy` is a forest: each node may name one `parent_discipline_id`, or leave it null to be a root. **Only one level of parenthood is ever honored.** A grandparent discipline is treated as unrelated to its grandchild by the alignment rule; it never earns the parent score.

**Discipline alignment score.** Given a *source* discipline (the discipline of a credential, or of a professional-development activity) and a *target* discipline (the discipline of a course section, or of a program), the alignment score is determined by the first of these cases that applies:

1. If the source and the target are the same discipline node, the score is 1.0000.
2. Otherwise, if the source is the target's parent, or the target is the source's parent, the score is 0.7100.
3. Otherwise, if the source has a non-null parent and that parent is the same node as the target's parent — that is, the two are siblings — the score is 0.6500.
4. Otherwise, if the first two characters of the source's `code` equal the first two characters of the target's `code`, the score is 0.4000.
5. Otherwise, the score is 0.0000.

The result is carried to 4 decimal places, rounded half up.

Alignment **passes** when the score is at or above 0.70. The two constants either side of that line were chosen deliberately: a parent-or-child relationship scores 0.7100 and therefore passes, while a sibling relationship scores 0.6500 and therefore fails. A shared two-character code prefix, at 0.4000, never passes on its own.

This one rule is consumed in two places: it decides whether a credential's discipline aligns with a course section's discipline during qualification determination, and it decides whether a professional-development activity counts as discipline-relevant for its owner's home program.

### 2.10. Rejection Precedence: The Validation Ladder

When a single request violates more than one rule, the response is determined by exactly one of them. Checks are evaluated in the strict order below; **the first violated check produces the response and no later check is evaluated.** This ordering is part of the contract, not an implementation detail — several pairs of rules were placed on opposite ends of the ladder precisely so that the reported error is predictable.

1. `X-User-ID` present and non-empty → otherwise `ERR_UNAUTHENTICATED` (401). Applies to every request.
2. `X-User-Role` present and authorized for the endpoint → otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every request.
3. For an entity-backed role, `X-User-ID` owns the addressed resource → otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to the eighteen operations listed in §2.1; opaque roles skip it.
4. Request body and query parameters satisfy the declared shape — required fields present, types correct, enum literals known, numeric bounds respected, dates well formed, arrays non-null → otherwise `ERR_INVALID_REQUEST` (400). Applies to every request. This is the code for a `limit` outside 1 through 100, a negative `offset`, non-positive `credit_hours`, a negative `page_count`, a `meeting_start_minute` or `meeting_end_minute` outside 0 through 1440, a `min_terminal_ratio` outside 0 through 1, an unknown enum literal, and an evaluation completion that omits any member of the equivalency triplet.
5. Every identifier in the request path resolves → otherwise the entity's own 404 code. Applies to every path-parameterised endpoint.
6. Every foreign-key identifier in the request body resolves → otherwise the referenced entity's 404 code, checked in field-declaration order. Applies to every write endpoint carrying foreign keys.
7. `expected_section_version` equals the current `CourseSection.version` → otherwise `ERR_STALE_SECTION_VERSION` (412). Applies to assignment creation.
8. `expected_faculty_version` equals the current `FacultyMember.version` → otherwise `ERR_STALE_FACULTY_VERSION` (412). Applies to contract issuance.
9. The requested state transition exists for the entity's current state → otherwise `ERR_INVALID_STATE` (409). Applies to every state-transition endpoint. Idempotency is **not** granted: repeating a trigger that already fired fails, because the second attempt is no longer a legal transition out of the new state. This code also covers terminal-state lockdown, sanctioning a review whose `response_round` is below 2, approving the launch of a substantive-change program without an accepted substantive-change review, verifying a credential whose transcript has not been requested, and certifying a roster while the program has a review demanding remediation.
10. The affected section's term permits the operation → otherwise `ERR_TERM_LOCKED` (409). Assignment mutations require the term to be `OPEN` or `ROSTER_LOCKED`; section creation requires `PLANNING` or `OPEN`; roster generation and certification require `OPEN` or `ROSTER_LOCKED`. `CLOSED` forbids everything. Applies to `POST /course-sections`, `POST /course-assignments`, `POST /course-assignments/{assignmentId}/remediation`, `POST /course-assignments/{assignmentId}/reverification`, `POST /course-assignments/{assignmentId}/withdrawal`, `POST /faculty-rosters/{rosterId}/generate` and `POST /faculty-rosters/{rosterId}/certification`. **This check outranks the teaching-block conflict check at rung 24** — a request that is both in a closed term and double-booked reports the term lock.
11. The `FacultyRoster` covering the affected section's program and term is not `CERTIFIED` → otherwise `ERR_ROSTER_CERTIFIED` (409). Applies to `POST /course-assignments`, `POST /course-assignments/{assignmentId}/remediation`, `POST /course-assignments/{assignmentId}/reverification`, `POST /course-assignments/{assignmentId}/withdrawal`, `POST /faculty-members/{facultyMemberId}/separation` and `POST /terms/{termId}/status`.
12. The affected program has no accreditor review in `IN_PROGRESS`, `FINDINGS_ISSUED` or `REMEDIATION_REQUIRED` whose fully closed window contains the clock date → otherwise `ERR_ACCREDITOR_REVIEW_LOCKOUT` (403). Applies to `POST /course-assignments`, `POST /course-assignments/{assignmentId}/withdrawal` and `POST /credential-evaluations`. **This check outranks the credential budget ceiling at rung 35** — an over-budget order placed during a review window reports the lockout.
13. Segregation of duties on `X-User-ID` → otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /tested-experience-justifications/{justificationId}/decision` and `POST /faculty-rosters/{rosterId}/certification`.
14. The referenced faculty member's `appointment_status` is not `SEPARATED` → otherwise `ERR_FACULTY_SEPARATED` (409). Applies to `POST /course-assignments`, `POST /faculty-contracts`, `POST /faculty-contracts/{contractId}/countersignature`, `POST /credential-records` and `POST /pd-records`.
15. The referenced faculty member's `appointment_status` is `CREDENTIALED_ELIGIBLE` or `CONTRACTED` → otherwise `ERR_FACULTY_NOT_APPOINTABLE` (409). Applies to assignment creation only.
16. The referenced faculty member's `dossier_status` is `VERIFIED` → otherwise `ERR_DOSSIER_NOT_VERIFIED` (409). Applies to contract issuance only. **This check outranks the contract issuance window at rung 28.**
17. The referenced credential record has `is_foreign_institution` set to true → otherwise `ERR_NOT_FOREIGN_CREDENTIAL` (422). Applies to evaluation ordering only.
18. A node's `parent_discipline_id` is neither its own `id` nor any ancestor that would close a cycle → otherwise `ERR_DISCIPLINE_CYCLE` (422). Applies to discipline creation and discipline update.
19. `DisciplineTaxonomy.code` is unique, compared as an exact case-sensitive match → otherwise `ERR_DUPLICATE_DISCIPLINE_CODE` (409). Applies to discipline creation and discipline update.
20. `Term.code` is unique, compared as an exact case-sensitive match → otherwise `ERR_DUPLICATE_TERM_CODE` (409). Applies to term creation.
21. `FacultyMember.email` is unique, compared as an exact case-sensitive match → otherwise `ERR_DUPLICATE_FACULTY_EMAIL` (409). Applies to faculty creation and faculty update.
22. No existing assignment shares the same section and faculty member with a status other than `SUPERSEDED` or `WITHDRAWN` → otherwise `ERR_DUPLICATE_ASSIGNMENT` (409). Applies to assignment creation.
23. No existing roster for the same program and term is in `DRAFT` or `GENERATED` → otherwise `ERR_DUPLICATE_ROSTER` (409). Applies to roster creation.
24. The faculty member has no teaching-block conflict with the target section → otherwise `ERR_TEACHING_BLOCK_CONFLICT` (409). Applies to assignment creation. Reported only once rung 10 is satisfied.
25. The new review window does not touch or overlap a non-terminal review window of the same program → otherwise `ERR_REVIEW_WINDOW_OVERLAP` (409). Applies to review scheduling.
26. The faculty member's existing credit hours in that term plus the new section's `credit_hours` do not exceed the ceiling for their `employment_class` → otherwise `ERR_TERM_LOAD_EXCEEDED` (409). Applies to assignment creation.
27. Date and minute intervals are correctly ordered → otherwise `ERR_INVALID_WINDOW` (422). Applies to `POST /terms`, `POST /course-sections`, `POST /accreditor-reviews` and `POST /accreditor-reviews/{reviewId}/status`.
28. The clock date is strictly before the contracted term's `start_date` → otherwise `ERR_CONTRACT_WINDOW_CLOSED` (422). Applies to contract issuance. Reported only once rung 16 is satisfied.
29. The clock date is on or before the review's `response_due_date` → otherwise `ERR_RESPONSE_WINDOW_CLOSED` (422). Applies to response filing.
30. `activity_date` is on or before the clock date → otherwise `ERR_PD_DATE_IN_FUTURE` (422). Applies to professional-development logging.
31. `supervisor_attestation_on_file` is true → otherwise `ERR_ATTESTATION_MISSING` (422). Applies to the justification decision endpoint, and only on the approve arm.
32. `documented_years_experience` is at least 3 **and** `tested_experience_score` is at least 0.70 → otherwise `ERR_TESTED_EXPERIENCE_INSUFFICIENT` (422). Applies to the justification decision endpoint, and only on the approve arm.
33. `certification_readiness` is `READY` → otherwise `ERR_ROSTER_NOT_READY` (409). Applies to roster certification and to term status changes; on the term endpoint the rule reads that every roster of the term must already be `CERTIFIED` or `SUPERSEDED` before the term may close.
34. `Program.adequacy_status` is `ADEQUATE` **and** `Program.unqualified_assignment_count` is 0 → otherwise `ERR_PROGRAM_ADEQUACY_INSUFFICIENT` (409). Applies to `POST /programs/{programId}/launch-decision` and `POST /accreditor-reviews/{reviewId}/status`.
35. On the billed program, `budget_reserved_cents` plus `budget_spent_cents` plus the freshly computed evaluation fee is at most `credential_budget_cents` → otherwise `ERR_CREDENTIAL_BUDGET_EXCEEDED` (422). Applies to evaluation ordering. Reported only once rung 12 is satisfied.

### 2.11. Derived-Field Reconciliation and Transitive Cascades

Many of the most important fields in this system are not written by clients at all. `FacultyMember.dossier_status`, `deficiency_codes`, `highest_verified_degree_level`, `assigned_credit_hours`, `pd_hours_current_cycle` and `pd_compliant`; every snapshot count on a `FacultyRoster` together with its `blocking_reason_codes` and `certification_readiness`; `Program.adequacy_ratio`, `adequacy_status`, `adequacy_term_id`, `unqualified_assignment_count`, `budget_reserved_cents` and `budget_spent_cents`; `CourseAssignment.qualification_basis`, `exception_code` and `alignment_score`; `CourseSection.instructor_of_record_id`; and every risk field on an `AccreditorReview` — all of these are **derived**, re-computed by the server from the underlying evidence whenever that evidence moves.

Reconciliation propagates upward through a fixed dependency chain: credential evidence determines a faculty dossier; a dossier and a section's requirements determine an assignment's verdict; assignment verdicts determine a roster snapshot; a roster snapshot determines a program's adequacy; a program's adequacy determines whether an open accreditor review may stay in a submitted-response state. A single request may therefore travel the whole chain. Three named cascades recur throughout §3:

- **Cascade A**, five hops deep, fires when a verified credential is repudiated: dossier, assignments, rosters, programs, reviews.
- **Cascade B**, three hops deep, fires when a tested-experience justification is approved: assignment, roster, program. Its rejecting sibling fires nothing at all.
- **Cascade C**, three hops deep, fires when a faculty member is separated: assignments, load ledger and instructor-of-record mirrors, then rosters and programs.

Two rules bound the blast radius. A `CERTIFIED` roster freezes its assignment set, so cascade hops skip assignments the roster has frozen. And a roster's `generation_epoch` advances **only** on an explicit generate call; a snapshot recompute triggered by a cascade rebuilds every other snapshot field but leaves `generation_epoch` alone.

### 2.12. Conserved Ledgers

Two quantities in this system are conserved: after any sequence of operations, each equals a fresh recomputation from first principles. Implementations that maintain them incrementally must produce exactly the same number as implementations that recompute them.

**The teaching-load ledger.** `FacultyMember.assigned_credit_hours` is the sum of `CourseSection.credit_hours` over that faculty member's assignments whose `status` is none of `SUPERSEDED` or `WITHDRAWN` and whose section belongs to a term whose `status` is not `CLOSED`. Creating an assignment adds exactly the section's `credit_hours`; withdrawing one, superseding one, separating the faculty member, or closing the term removes exactly the same amount. Note what stays in the ledger: an `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS` assignment still occupies the seat and still counts. Only supersession, withdrawal and term closure remove hours.

**The credential-evaluation budget ledger.** On each `Program`, `budget_reserved_cents` is the sum of `fee_cents` over evaluations billed to that program whose `status` is `ORDERED` or `IN_REVIEW`, and `budget_spent_cents` is the sum of the `share_cents` allocated to that program across all evaluations whose `status` is `COMPLETED`. Ordering an evaluation reserves; completing it releases the reservation and converts it into allocated spend; voiding it releases the reservation with no residue at all, returning `budget_reserved_cents` to its exact pre-order value and leaving `budget_spent_cents` untouched. For every completed evaluation the allocated shares re-sum to `fee_cents` exactly — no cent is invented and none is lost.

One asymmetry is intentional and worth stating plainly: the budget ceiling is checked only against the **billed** program, while completion may spread `share_cents` onto other programs whose ceilings were never consulted. A non-billed program's committed total can therefore be pushed above its own `credential_budget_cents` by someone else's evaluation, and only its own next order attempt is rejected.

## 3. Business Logic & Workflows

### 3.1. Institutional Reference Data: Disciplines, Programs and Terms

Before any faculty member can be credentialed, a `SystemAdmin` must lay down the reference data the accreditor's rules are written against.

A discipline node is created with a CIP-style `code`, a human-readable `name`, an optional `parent_discipline_id`, an optional `min_graduate_credit_hours` that defaults to 18 and may not be negative, and a `required_terminal_degree_level` of either `MASTERS` or `DOCTORATE` naming the terminal degree the accreditor expects for work in that discipline. Codes must be unique across the taxonomy; a collision is rejected with `ERR_DUPLICATE_DISCIPLINE_CODE`. A node may later be updated — `name`, `parent_discipline_id`, `min_graduate_credit_hours` and `required_terminal_degree_level` are all mutable — but `code` is immutable once set. Neither creation nor update may point a node at itself or close a loop in the forest; either attempt yields `ERR_DISCIPLINE_CYCLE`. Re-parenting a node changes alignment for every score computed *after* the change; scores already persisted on existing assignments are not rewritten. Nodes are listable, filterable by `parent_discipline_id` (which is how the self-referential children of a node are reached), by `code` and by `required_terminal_degree_level`.

A program is created with a `name`, a `discipline_id` naming its home discipline, and a `degree_level` drawn from `CERTIFICATE`, `ASSOCIATE`, `BACHELORS`, `MASTERS` and `DOCTORATE`. Two of its inputs are **feature flags** that silently change how every downstream number is computed. `qualification_policy` is either `DEGREE_FIELD` or `COURSEWORK_18` and selects which variant of the qualification verdict applies to the program's sections (§3.4). `adequacy_basis` is either `HEADCOUNT` or `CREDIT_HOUR_COVERAGE` and selects which variant of faculty adequacy is persisted onto the program (§3.6). Creation also takes `min_terminal_ratio`, the adequacy ratio at or above which the program counts as adequate, which defaults to 0.75 and must lie between 0 and 1 inclusive; `is_substantive_change`, defaulting to false, marking the program as a substantive-change filing that needs accreditor pre-approval before launch; and `credential_budget_cents`, a non-negative ceiling on foreign-credential-evaluation spending charged to the program. A freshly created program starts with `launch_status` `PLANNING`, `adequacy_ratio` 0.0, `adequacy_status` `INSUFFICIENT`, `unqualified_assignment_count` 0, `adequacy_term_id` null, and both `budget_reserved_cents` and `budget_spent_cents` at 0. Programs are listable and filterable by `discipline_id`, `adequacy_term_id`, `launch_status`, `adequacy_status`, `qualification_policy` and `adequacy_basis`.

The launch gate is a small branching lifecycle on `launch_status`. A `ProgramDean` submitting their own program for faculty-adequacy review supplies a `term_id`, moving the program `PLANNING → ADEQUACY_REVIEW`; the same submission also drives the revision loop `ADEQUACY_DENIED → ADEQUACY_REVIEW` after a denied program has remediated. Either way, a roster must already exist for that program and term with `status` `GENERATED` or `CERTIFIED`, otherwise the request fails with `ERR_ROSTER_NOT_FOUND`. On success, faculty adequacy is recomputed from that roster and written onto `adequacy_ratio`, `adequacy_status`, `adequacy_term_id` and `unqualified_assignment_count`, and the program's `version` increments by 1. An `AccreditationLiaison` then decides, supplying a `decision` of `APPROVE` or `DENY` and an optional `rationale`. Approval moves `ADEQUACY_REVIEW → APPROVED_TO_LAUNCH` and requires both that `adequacy_status` is `ADEQUATE` and that `unqualified_assignment_count` is 0 — otherwise `ERR_PROGRAM_ADEQUACY_INSUFFICIENT` — and, when `is_substantive_change` is true, additionally requires an accreditor review of type `SUBSTANTIVE_CHANGE` already in `CLOSED_ACCEPTED` for that program, absent which the request is rejected with `ERR_INVALID_STATE`. Denial moves `ADEQUACY_REVIEW → ADEQUACY_DENIED` with no preconditions. `APPROVED_TO_LAUNCH` is terminal. Both decisions increment the program's `version` by 1.

Adequacy is also readable without persisting anything. The adequacy read takes a required `term_id` and an optional `basis_override`, and returns `program_id`, `term_id`, the `basis_applied`, the `numerator` and `denominator` that produced the ratio, the resulting `adequacy_ratio` and `adequacy_status`, the `unqualified_assignment_count`, and the `roster_id` of the anchor roster it read. Supplying `basis_override` recomputes under the other variant and writes nothing — this is how an operator observes the `HEADCOUNT` and `CREDIT_HOUR_COVERAGE` divergence side by side.

A term is created by a `SystemAdmin` or `RegistrarOfficer` with a `code` such as 2026FA, a `start_date` giving the first instructional day, an `end_date` giving the last, and a `census_date` naming the official enrollment census day. All three are date-only ISO 8601 values, and they must satisfy `start_date` at or before `census_date`, and `census_date` at or before `end_date`; a violation is `ERR_INVALID_WINDOW`. Codes are unique across all terms, with a collision reported as `ERR_DUPLICATE_TERM_CODE`. Terms are listable and filterable by `status` and `code`.

A `RegistrarOfficer` drives the term through `PLANNING → OPEN → ROSTER_LOCKED → CLOSED`, naming the destination as `to_status`. Locking the roster is what stops the term's course sections from multiplying: while a term is `ROSTER_LOCKED`, new section creation is rejected with `ERR_TERM_LOCKED`, though assignment remediation, reverification, withdrawal and all roster work remain permitted. The registrar may reverse a premature lock with `ROSTER_LOCKED → OPEN`, but only while no roster of that term has reached `CERTIFIED`; a certified roster blocks the reversal with `ERR_ROSTER_CERTIFIED`. Closing the term, `ROSTER_LOCKED → CLOSED`, demands that **every** roster carrying that `term_id` already be `CERTIFIED` or `SUPERSEDED`, failing which the close is rejected with `ERR_ROSTER_NOT_READY`. Closure has a ledger consequence: for every faculty member holding an assignment in that term, `assigned_credit_hours` is recomputed and the term's hours drop out of it, since closed terms leave the ledger set, and each such faculty member's `version` increments by 1. Each of the four transitions increments the term's own `version` by 1. `CLOSED` is terminal.

### 3.2. Building the Faculty Dossier

A `RegistrarOfficer` creates a faculty member with a `full_name`, an institutional `email` that must be unique across all faculty (a collision is `ERR_DUPLICATE_FACULTY_EMAIL`), an `employment_class` of `FULL_TIME`, `ADJUNCT`, `CLINICAL` or `GRADUATE_ASSISTANT`, and a `home_program_id` naming the program that owns the appointment. The new row begins with two independent state dimensions on the same record: `dossier_status` at `INCOMPLETE` and `appointment_status` at `PROSPECT`. It also begins with `deficiency_codes` empty, `highest_verified_degree_level` null, `assigned_credit_hours` 0, `pd_hours_current_cycle` 0 and `pd_compliant` false. Faculty are listable and filterable by `home_program_id`, `employment_class`, `dossier_status`, `appointment_status` and `pd_compliant`; the registrar may also update `full_name`, `email`, `employment_class` and `home_program_id`, which re-runs professional-development compliance because the required-hours threshold follows `employment_class`, and increments the faculty member's `version` by 1. Re-homing a faculty member does **not** retroactively rewrite `discipline_relevant` on their existing professional-development records.

**The two dimensions are genuinely independent, and this is the pivot of the whole design.** `dossier_status` describes the credential evidence: `INCOMPLETE`, `UNDER_REVIEW`, `VERIFIED` or `DEFICIENT`. `appointment_status` describes the employment relationship: `PROSPECT`, `CREDENTIALED_ELIGIBLE`, `CONTRACTED` or `SEPARATED`. A dossier going bad never demotes an appointment — an already `CONTRACTED` instructor whose credential is later repudiated stays `CONTRACTED`, and that pairing of a contracted appointment with a deficient dossier is precisely the exception the accreditor reads.

Credentials are filed one row at a time by the registrar. A credential record names its owning `faculty_member_id`, the `degree_level` as claimed — `NON_DEGREE_GRADUATE`, `BACHELORS`, `MASTERS` or `DOCTORATE`, where `NON_DEGREE_GRADUATE` is how a block of graduate coursework short of a degree is recorded — a `discipline_id` for the degree or the coursework block, the `conferring_institution` name, an optional `is_foreign_institution` flag defaulting to false, and an optional `graduate_credit_hours_in_discipline` defaulting to 0 and never negative, recording the graduate credit hours the official transcript shows in that discipline. Nothing may be filed against a separated faculty member: `ERR_FACULTY_SEPARATED` guards it. A new record begins with `verification_status` `PENDING`, `transcript_status` `NOT_REQUESTED`, `verified_by_user_id` null, and both `effective_degree_level` and `effective_discipline_id` null. Records are listable and filterable by `faculty_member_id`, `discipline_id`, `effective_discipline_id`, `verification_status`, `transcript_status` and `is_foreign_institution`, and a per-faculty sub-resource listing returns one faculty member's whole evidence set ordered by `created_at` ascending — an `Instructor` may read only their own.

Official transcript collection is its own state dimension on the record, advanced by the registrar by naming a `transcript_status`. From `NOT_REQUESTED` the registrar may move to `REQUESTED`, to `UNOFFICIAL_ONLY`, or straight to `OFFICIAL_RECEIVED`. From `REQUESTED` the permitted destinations are `UNOFFICIAL_ONLY` and `OFFICIAL_RECEIVED`. From `UNOFFICIAL_ONLY` the only destination is `OFFICIAL_RECEIVED`, which is terminal for this dimension. Every transition except `NOT_REQUESTED → REQUESTED` re-runs the dossier recompute for the owning faculty member and increments both the record's and the faculty member's `version` by 1; landing on `UNOFFICIAL_ONLY` is what puts `TRANSCRIPT_NOT_OFFICIAL` into the dossier's deficiency list, and reaching `OFFICIAL_RECEIVED` is what takes it out again. The plain `NOT_REQUESTED → REQUESTED` step only increments the record's `version` by 1.

A `CredentialAnalyst` then judges the record, supplying a `decision` of `VERIFY`, `REJECT` or `REPUDIATE` together with an optional `note`. `PENDING → VERIFIED` requires the transcript to have reached `UNOFFICIAL_ONLY` or `OFFICIAL_RECEIVED`; verifying a record whose transcript is still `NOT_REQUESTED` is rejected with `ERR_INVALID_STATE`. `PENDING → REJECTED` has no precondition and takes the record out of the evidence set entirely. `VERIFIED → REPUDIATED` is how a credential that turns out to be false is retracted. `REJECTED` and `REPUDIATED` are both terminal. All three decisions stamp `verified_by_user_id` with the acting `X-User-ID` — the value segregation of duties will later compare against — re-run the dossier recompute, and increment the record's and the faculty member's `version` by 1.

**Dossier recompute.** Whenever credential evidence moves — a record is filed, a transcript advances, a verification decision lands, or a foreign evaluation completes — `deficiency_codes`, `dossier_status` and `highest_verified_degree_level` are re-derived from scratch in a single pass over the faculty member's entire evidence set. Codes never depend on each other. Let the **live** set be every credential record of that faculty member whose `verification_status` is not `REJECTED`. Then `deficiency_codes` is rebuilt as an empty list and appended to in exactly this declared order:

1. `NO_CREDENTIAL_ON_FILE`, when the live set is empty.
2. `TRANSCRIPT_NOT_OFFICIAL`, when at least one live record whose `verification_status` is not `REPUDIATED` has a `transcript_status` other than `OFFICIAL_RECEIVED`.
3. `FOREIGN_EVALUATION_INCOMPLETE`, when at least one live record whose `verification_status` is not `REPUDIATED` has `is_foreign_institution` true and has no evaluation that is both `COMPLETED` and carries an `equivalency_verdict` of `EQUIVALENT`.
4. `CREDENTIAL_REPUDIATED`, when at least one live record has `verification_status` `REPUDIATED` and no later-created live record — comparing `created_at` ascending — carries the same `degree_level` and `discipline_id` pair. A replacement credential of the same level in the same discipline therefore cures the repudiation; a replacement of a different level or discipline does not.

The resulting list is de-duplicated, and it is empty exactly when the dossier is verified. `dossier_status` is then chosen by the first matching case: `INCOMPLETE` when the live set is empty; `UNDER_REVIEW` when any live record is still `PENDING`; `VERIFIED` when `deficiency_codes` came out empty; and `DEFICIENT` otherwise. **A pending record outranks any deficiency** — a faculty member with one pending record and `TRANSCRIPT_NOT_OFFICIAL` already in their deficiency list is `UNDER_REVIEW`, not `DEFICIENT`, and that is exactly what makes the cure path `DEFICIENT → UNDER_REVIEW → VERIFIED` reachable after a repudiation. Alongside this, `highest_verified_degree_level` is set to the greatest effective degree level over the records whose `verification_status` is `VERIFIED`, ranking `NON_DEGREE_GRADUATE` below `BACHELORS`, below `MASTERS`, below `DOCTORATE`, and set to null when there are no verified records. Finally, if the dossier came out `VERIFIED` and `appointment_status` is still `PROSPECT`, the appointment is promoted to `CREDENTIALED_ELIGIBLE` in the same request.

Reading the dossier dimension as a state machine: filing the faculty member's first live record moves `INCOMPLETE → UNDER_REVIEW`. A verification, transcript or evaluation event that empties the deficiency list moves `UNDER_REVIEW → VERIFIED`. A recompute that finds no pending record but a non-empty deficiency list moves `UNDER_REVIEW → DEFICIENT`. A repudiation, or an officially-received record losing its foreign-evaluation support, moves `VERIFIED → DEFICIENT`, adding `CREDENTIAL_REPUDIATED` or `FOREIGN_EVALUATION_INCOMPLETE` and leaving `appointment_status` untouched. Filing a replacement record in `PENDING` moves `DEFICIENT → UNDER_REVIEW`. Curing the deficiency outright — an evaluation completing as `EQUIVALENT`, or a transcript upgraded to `OFFICIAL_RECEIVED` — moves `DEFICIENT → VERIFIED` and again promotes a `PROSPECT` appointment to `CREDENTIALED_ELIGIBLE`. Every one of these moves increments the faculty member's `version` by 1.

**Cascade A: what repudiation costs.** Repudiating a verified credential is the deepest single operation in the system, and every hop is visible in the response.

- *Hop 1* — the dossier recompute described above runs for the record's faculty member: `CREDENTIAL_REPUDIATED` enters `deficiency_codes` and `dossier_status` moves `VERIFIED → DEFICIENT`.
- *Hop 2* — because the dossier became `DEFICIENT`, every course assignment of that faculty member whose `status` is `PENDING_VERIFICATION` or `VERIFIED_QUALIFIED`, whose section's term is not `CLOSED`, and whose covering roster is not `CERTIFIED`, moves to `EXCEPTION_FLAGGED` with `exception_code` set to `DOSSIER_DEFICIENT`. `assigned_credit_hours` does not change — those assignments still occupy load.
- *Hop 3* — because those assignments changed status, the roster snapshot is recomputed on every `GENERATED` roster that includes them: `flagged_exception_count` rises, `blocking_reason_codes` gains both `DOSSIER_DEFICIENT` and `EXCEPTIONS_OUTSTANDING`, and `certification_readiness` becomes `BLOCKED`. `generation_epoch` is **not** advanced.
- *Hop 4* — because those rosters recomputed, each affected program has `adequacy_ratio`, `adequacy_status`, `adequacy_term_id` and `unqualified_assignment_count` rewritten from the roster snapshot.
- *Hop 5* — because a program's adequacy fields were rewritten and the program is no longer clean — either `adequacy_status` is not `ADEQUATE` or `unqualified_assignment_count` is above 0 — every accreditor review of that program sitting in `RESPONSE_SUBMITTED` returns to `REMEDIATION_REQUIRED`, its risk metrics are recomputed against the current anchor roster, and `response_due_date` is reset to the clock date plus that tier's response days. `response_round` is left exactly as it was.

The credential record, the faculty member, and every touched assignment, roster, program and review each have `version` incremented by 1. `appointment_status` is deliberately not touched anywhere in cascade A.

### 3.3. Foreign Credential Evaluation and What It Costs

A credential from outside the accreditor's jurisdiction does not count on its own. It counts only once an evaluation agency has said what it is equivalent to, and that verdict has been recorded as `COMPLETED` and `EQUIVALENT`.

A `CredentialAnalyst` orders an evaluation by naming the `credential_record_id`, the `billed_program_id` whose budget will carry the cost, the `evaluator_agency`, the `page_count` of foreign transcript submitted (a non-negative integer), and a `service_level` of `STANDARD` or `EXPEDITED`. Only foreign credentials may be sent out: ordering against a record whose `is_foreign_institution` is false is rejected with `ERR_NOT_FOREIGN_CREDENTIAL`. Ordering is also blocked while the billed program is under an on-site review window, with `ERR_ACCREDITOR_REVIEW_LOCKOUT`, and that lockout is reported ahead of any budget problem. Evaluations are listable and filterable by `credential_record_id`, `billed_program_id`, `equivalency_discipline_id`, `status` and `service_level`.

**The fee.** `fee_cents` is computed at order time and frozen forever; `page_count` cannot be edited afterwards, so the fee can never drift. The computation proceeds in this exact order:

1. The first 4 pages are free. Billable pages are the `page_count` minus 4, or zero if that would be negative.
2. Billable pages are then priced through three nested brackets. The first 8 billable pages cost 240 cents each. The next 12 billable pages cost 180 cents each. Every billable page beyond those first 20 costs 120 cents each. The page charge is the sum of the three bracket amounts.
3. A base fee of 9,000 cents is added to the page charge, and because the record is a foreign credential, a further foreign-institution surcharge of 2,500 cents is added. That total is the subtotal.
4. The subtotal is multiplied by 1.45 when `service_level` is `EXPEDITED`, and by 1.00 when it is `STANDARD`. The product is rounded half up to a whole number of cents. This is the only rounding step in the fee, and it happens **before** the floor and the cap.
5. The rounded amount is then raised to a floor of 15,000 cents if it falls below that, and lowered to a cap of 95,000 cents if it exceeds that. The result is `fee_cents`.

Ordering reserves that exact amount: the billed program's `budget_reserved_cents` increases by `fee_cents` and its `version` increments by 1. The reservation is checked against the ceiling first — the sum of the billed program's `budget_reserved_cents`, its `budget_spent_cents` and the freshly computed fee must not exceed its `credential_budget_cents`, or the order is rejected with `ERR_CREDENTIAL_BUDGET_EXCEEDED`. Because the fee is computed before the ceiling is tested, the ceiling is always tested against the exact amount that would be frozen. The new evaluation lands in `status` `ORDERED`, with `equivalency_degree_level`, `equivalency_discipline_id` and `equivalency_verdict` all null and `allocation_shares` empty.

The analyst drives the evaluation by naming a `to_status`. `ORDERED → IN_REVIEW` changes nothing financially — both `ORDERED` and `IN_REVIEW` reserve — and increments the evaluation's `version` by 1. `IN_REVIEW → COMPLETED` requires the full equivalency triplet in the body: `equivalency_degree_level`, `equivalency_discipline_id` and `equivalency_verdict` must all be present, or the request is rejected with `ERR_INVALID_REQUEST`, and `equivalency_discipline_id` must resolve to a real discipline node or the request fails with `ERR_DISCIPLINE_NOT_FOUND`. The verdict is one of `EQUIVALENT`, `PARTIAL` or `NOT_EQUIVALENT`, and **only `EQUIVALENT` makes the underlying credential count.** Either of `ORDERED → VOIDED` and `IN_REVIEW → VOIDED` abandons the evaluation. `COMPLETED` and `VOIDED` are both terminal.

Completion does four things beyond the status change. The billed program's `budget_reserved_cents` decreases by `fee_cents`, releasing the reservation. The cost allocation described below runs, writing `allocation_shares` and increasing each receiving program's `budget_spent_cents` by its own `share_cents`. When the verdict is `EQUIVALENT`, the underlying credential record's `effective_degree_level` is rewritten to the agency's `equivalency_degree_level` and its `effective_discipline_id` to the agency's `equivalency_discipline_id` — for a domestic record, or a foreign record without a completed equivalent verdict, the effective level and discipline simply mirror the claimed `degree_level` and `discipline_id`. And the dossier recompute runs, so `FOREIGN_EVALUATION_INCOMPLETE` leaves `deficiency_codes` when the verdict is `EQUIVALENT`, potentially moving `dossier_status` to `VERIFIED`. The evaluation, the credential record, the faculty member and every touched program each have `version` incremented by 1.

Voiding is the compensating path and leaves no residue: the billed program's `budget_reserved_cents` decreases by `fee_cents`, returning it to its exact pre-order value, and `budget_spent_cents` is untouched. The evaluation's and the program's `version` each increment by 1.

**Cost allocation.** A completed evaluation's frozen fee is split across every program whose teaching load the credentialed faculty member actually carries — not only the program that was billed. For each program, `weight_credit_hours` is the sum of `CourseSection.credit_hours` over that faculty member's assignments whose `status` is neither `SUPERSEDED` nor `WITHDRAWN` and whose section belongs to that program and to a term whose `status` is not `CLOSED`. Programs whose weight comes out as zero are dropped. If no program is left with any weight, `allocation_shares` is a single entry naming the `billed_program_id`, a `weight_credit_hours` of 0 and a `share_cents` equal to the whole fee. Otherwise, each surviving program's provisional share is the fee multiplied by that program's weight, divided by the total weight, then **floored** to a whole cent — never rounded independently, because independent rounding would lose or invent cents. The residual is the fee minus the sum of the floored shares. The surviving programs are then ordered by `weight_credit_hours` descending, and where weights tie, by the program's `created_at` ascending; one cent is handed to the first program in that order, one to the second, and so on until the residual is exhausted, wrapping around the same order should the residual exceed the number of programs. `allocation_shares` records each entry as a program identifier, its `weight_credit_hours` and its final `share_cents`, in the order the shares were allocated, and the shares always re-sum to `fee_cents` exactly.

### 3.4. Course Sections, Assignments and the Qualification Verdict

A `ProgramDean` builds out a term by creating sections of their own program. A section carries a `course_code` such as JOUR-201, a `title`, the `program_id` — which must equal `X-User-ID` — the `term_id`, a `discipline_id` naming the discipline the instructor must align to, a `course_level` of `LOWER_DIVISION`, `UPPER_DIVISION`, `GRADUATE` or `DOCTORAL`, a positive `credit_hours` figure which is the unit of the faculty load ledger, and a `delivery_mode` of `IN_PERSON`, `ONLINE_SYNC` or `ONLINE_ASYNC`. Sections may only be created while their term is `PLANNING` or `OPEN`; a `ROSTER_LOCKED` or `CLOSED` term rejects creation with `ERR_TERM_LOCKED`.

Meeting geometry is where the conflict rules get their inputs. `building_code` names the building the section meets in and must be supplied unless `delivery_mode` is `ONLINE_ASYNC`, in which case it may be left null; online delivery conventionally carries the building code `ONLINE`. `meeting_days` is an array drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT` and `SUN`, and must be the empty array when `delivery_mode` is `ONLINE_ASYNC`. `meeting_start_minute` and `meeting_end_minute` express the meeting block as minutes from local midnight, and may be null only when `delivery_mode` is `ONLINE_ASYNC`; a start lies in 0 through 1439 and an end lies above the start and at most 1440. The end is the **exclusive** upper bound of the block. A start at or after the end is rejected with `ERR_INVALID_WINDOW`, while a minute value outside the permitted range is a shape violation reported as `ERR_INVALID_REQUEST`. A new section begins with `instructor_of_record_id` null. Sections are listable and filterable by `program_id`, `term_id`, `discipline_id`, `instructor_of_record_id`, `course_level` and `delivery_mode`.

Assigning an instructor is the busiest write in the system. The dean supplies the `course_section_id`, the `faculty_member_id`, an `assignment_role` of either `INSTRUCTOR_OF_RECORD` or `CO_INSTRUCTOR`, and the `expected_section_version` guard described in §2.7. The section's `program_id` must equal `X-User-ID`. Beyond the version guard, five domain checks stand between the request and a new assignment, and §2.10 fixes the order in which they are reported. The term must permit assignment mutations, meaning `OPEN` or `ROSTER_LOCKED`, or the request fails with `ERR_TERM_LOCKED`. The covering roster must not be `CERTIFIED`, or the request fails with `ERR_ROSTER_CERTIFIED`. The program must not be inside an accreditor lockout window, or the request fails with `ERR_ACCREDITOR_REVIEW_LOCKOUT`. The faculty member must not be `SEPARATED` (`ERR_FACULTY_SEPARATED`) and must be `CREDENTIALED_ELIGIBLE` or `CONTRACTED` (`ERR_FACULTY_NOT_APPOINTABLE`) — a `PROSPECT` who has never been credentialed at all cannot be put in front of students, whereas a formerly credentialed instructor whose dossier has *since* gone `DEFICIENT` passes this check and simply receives a flagged assignment instead. That asymmetry is the entire point of keeping the two faculty dimensions independent. And the same instructor may not be attached to the same section twice while a prior assignment survives in any status other than `SUPERSEDED` or `WITHDRAWN`, which is `ERR_DUPLICATE_ASSIGNMENT`.

**Teaching-block conflict.** A new assignment is compared against the faculty member's other assignments in the *same* term whose `status` is neither `SUPERSEDED` nor `WITHDRAWN`. Two sections conflict only when they share at least one entry in `meeting_days`. Meeting intervals are half-open — they run from `meeting_start_minute` up to but not including `meeting_end_minute`. A buffer of 15 minutes applies when the two sections' `building_code` values differ, modelling the travel time between buildings, and a buffer of 0 applies when they match. Given that buffer, the two sections conflict when the new section's start is earlier than the other's end plus the buffer **and** the other's start is earlier than the new section's end plus the buffer. Consequently, back-to-back sections in the *same* building, where one ends exactly as the other begins, do not conflict, while back-to-back sections in *different* buildings do. Any section whose `delivery_mode` is `ONLINE_ASYNC` is exempt on either side and never conflicts with anything. A conflict is reported as `ERR_TEACHING_BLOCK_CONFLICT`, but only once the term-lock check has already passed.

**Per-term load.** Each `employment_class` carries a per-term credit-hour ceiling: a `FULL_TIME` faculty member may carry 15 credit hours in a term, a `CLINICAL` one 12, an `ADJUNCT` one 9, and a `GRADUATE_ASSISTANT` one 6. The faculty member's existing hours in that term — the sum of `credit_hours` over their ledger-set assignments restricted to that term — plus the new section's `credit_hours` must not exceed that ceiling. This is an aggregate rule: each individual assignment may be perfectly legal while the collective load is not. Exceeding it is `ERR_TERM_LOAD_EXCEEDED`.

Once the checks pass, the assignment is created and the qualification verdict is decided **immediately**, so the create response already carries a settled `status`, `qualification_basis`, `exception_code` and `alignment_score`. `assigned_credit_hours` for that faculty member increases by the section's `credit_hours`. When the new `assignment_role` is `INSTRUCTOR_OF_RECORD` and the section already had an instructor of record, the incumbent assignment moves to `SUPERSEDED` — from whichever of `PENDING_VERIFICATION`, `VERIFIED_QUALIFIED`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS` it was in — has its `superseded_by_assignment_id` set to the new assignment's identifier, and gives back its hours: the superseded instructor's `assigned_credit_hours` decreases by exactly that section's `credit_hours`. The section's `instructor_of_record_id` re-points to the new assignment's `faculty_member_id`. When the superseded assignment was `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`, the owning program's `unqualified_assignment_count` decreases by 1; when it was anything other than `PENDING_VERIFICATION`, the covering `GENERATED` roster recomputes; and when it was `REMEDIATION_IN_PROGRESS`, any justification backing it that sits in `SUBMITTED` or `UNDER_REVIEW` moves to `WITHDRAWN`. The section's `version` increments by 1 as the concurrency parent, as do the faculty member's, any superseded assignment's, and the covering roster's and owning program's where they were touched. Assignments are listable and filterable by `course_section_id`, `faculty_member_id`, `superseded_by_assignment_id`, `status`, `exception_code` and `qualification_basis`, with a per-section sub-resource listing ordered by `created_at` ascending.

**The qualification verdict.** This determination runs on assignment creation, on every roster generation, on reverification, and inside cascade A's second hop. It reads the section's `course_level` and `discipline_id`; the `required_terminal_degree_level` and `min_graduate_credit_hours` of that section discipline; the owning program's `qualification_policy` as the variant selector; every credential record of the assigned faculty member together with each record's `verification_status`, `transcript_status`, `is_foreign_institution`, effective level, effective discipline and `graduate_credit_hours_in_discipline`; those records' evaluations with their `status` and `equivalency_verdict`; and the faculty member's `dossier_status`.

Degree levels are ranked `NON_DEGREE_GRADUATE` lowest, then `BACHELORS`, then `MASTERS`, then `DOCTORATE` highest. The course's own requirement is a master's degree when `course_level` is `LOWER_DIVISION` or `UPPER_DIVISION`, and a doctorate when it is `GRADUATE` or `DOCTORAL`. The **required rank** is the higher of that course requirement and the section discipline's `required_terminal_degree_level`, so a discipline demanding a doctorate raises the bar even for a lower-division section.

The evidence set is then narrowed twice. The **official set** is the records whose `verification_status` is `VERIFIED` and whose `transcript_status` is `OFFICIAL_RECEIVED`. The **eligible set** is the official set minus every record that has `is_foreign_institution` true and no evaluation that is both `COMPLETED` and `EQUIVALENT`. A record's effective level and discipline are its `effective_degree_level` and `effective_discipline_id` when those are non-null — which is exactly when a completed equivalent foreign evaluation wrote them — and otherwise its claimed `degree_level` and `discipline_id`.

Two independent tests then run against the eligible set. The **degree test** passes when at least one eligible record has an effective degree level at or above the required rank *and* an alignment score, between that record's effective discipline and the section's `discipline_id`, of at least 0.70. The **coursework test** sums `graduate_credit_hours_in_discipline` over exactly those eligible records whose effective discipline aligns with the section discipline at 0.70 or above, and passes when that sum reaches the section discipline's `min_graduate_credit_hours` — 18 hours by default.

Which tests count is the feature flag's decision:

- Under `DEGREE_FIELD`, the credential test is the degree test alone. Accumulated graduate coursework is ignored entirely, and `qualification_basis` can never come out as `COURSEWORK_18_HOUR`. A passing verdict records `qualification_basis` `TERMINAL_DEGREE`.
- Under `COURSEWORK_18`, the credential test passes when *either* the degree test or the coursework test passes. The degree test is consulted first, so a faculty member who satisfies both records `TERMINAL_DEGREE`; one who fails the degree test but reaches the coursework threshold records `COURSEWORK_18_HOUR`. That basis is deliberately **excluded** from the adequacy numerator described in §3.6.

Independently of the verdict, `alignment_score` is written as the greatest alignment score between any eligible record's effective discipline and the section's discipline, or 0.0000 when the eligible set is empty. It is informational and carries no gating power of its own.

The assignment is `qualified` — moving `PENDING_VERIFICATION → VERIFIED_QUALIFIED`, with `qualification_basis` set and `exception_code` null — when the credential test passes **and** the faculty member's `dossier_status` is `VERIFIED`. Otherwise it moves `PENDING_VERIFICATION → EXCEPTION_FLAGGED`, `qualification_basis` is set to `NONE`, the owning program's `unqualified_assignment_count` increases by 1, and `exception_code` is chosen by the **first matching** rule in this precedence list:

1. `NO_OFFICIAL_TRANSCRIPT`, when the official set is empty.
2. `FOREIGN_EVALUATION_MISSING`, when the official set is non-empty but the eligible set is empty.
3. `DEGREE_LEVEL_INSUFFICIENT`, when the credential test failed and `alignment_score` is at least 0.70.
4. `DISCIPLINE_MISALIGNED`, when the credential test failed and `alignment_score` is below 0.70.
5. `DOSSIER_DEFICIENT`, when the credential test passed, so that the only remaining defect is the dossier itself.

The two policies diverge visibly. Consider a faculty member holding a verified, officially-transcripted, domestic master's degree in a *sibling* discipline of the section — aligning at 0.6500, below the pass line — plus a verified, officially-transcripted, domestic `NON_DEGREE_GRADUATE` record in the section's own discipline showing 18 graduate credit hours, with a `VERIFIED` dossier. Under `DEGREE_FIELD` the assignment is not qualified: `qualification_basis` is `NONE` and `exception_code` is `DEGREE_LEVEL_INSUFFICIENT`. Under `COURSEWORK_18` the same evidence qualifies with `qualification_basis` `COURSEWORK_18_HOUR` and no exception code. In both cases `alignment_score` is 1.0000, because the coursework record matches the section discipline exactly — and that is precisely why the `DEGREE_FIELD` arm reports `DEGREE_LEVEL_INSUFFICIENT` rather than `DISCIPLINE_MISALIGNED`. The aligned credential simply is not a degree. `DISCIPLINE_MISALIGNED` would require the alignment score to be below 0.70, which is what happens when the faculty member holds only the sibling-discipline master's.

**Remediation and re-verification.** A flagged assignment is not a dead end. A `ProgramDean` opens remediation on their own program's assignment, moving `EXCEPTION_FLAGGED → REMEDIATION_IN_PROGRESS` and supplying a `remediation_action` of `REASSIGN_PENDING`, `TESTED_EXPERIENCE_PENDING` or `CREDENTIAL_UPDATE_PENDING`, plus an optional `note`. The term must be `OPEN` or `ROSTER_LOCKED` (`ERR_TERM_LOCKED`) and the covering roster must not be `CERTIFIED` (`ERR_ROSTER_CERTIFIED`). The covering `GENERATED` roster recomputes, and although `flagged_exception_count` does not change — a remediating assignment is still an exception — the row now begins to count toward the exception-persistence term of the accreditor risk index. The assignment's `version` increments by 1.

A `CredentialAnalyst` then re-runs the determination on a remediating assignment, taking no request body at all. When the evidence now passes, or when an `APPROVED` tested-experience justification exists for the assignment, the assignment moves `REMEDIATION_IN_PROGRESS → VERIFIED_QUALIFIED`: `qualification_basis` becomes `TERMINAL_DEGREE`, `COURSEWORK_18_HOUR` or `TESTED_EXPERIENCE` as appropriate, and both `exception_code` and `remediation_action` are cleared to null. The covering `GENERATED` roster recomputes with `flagged_exception_count` down by 1 — but `adequacy_ratio_snapshot` rises only when the basis is something other than `TESTED_EXPERIENCE` — and the owning program's `unqualified_assignment_count` decreases by 1. This closes the cycle `VERIFIED_QUALIFIED → EXCEPTION_FLAGGED → REMEDIATION_IN_PROGRESS → VERIFIED_QUALIFIED`. When the determination still fails and no approved justification exists, the assignment instead moves `REMEDIATION_IN_PROGRESS → EXCEPTION_FLAGGED`, `remediation_action` is cleared to null, `exception_code` is recomputed, and the covering roster recomputes. Either way `alignment_score` is rewritten and the assignment's `version` increments by 1.

A dean may also withdraw one of their own assignments outright, supplying an optional `reason`, from any of `PENDING_VERIFICATION`, `VERIFIED_QUALIFIED`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS` to `WITHDRAWN`. All four preconditions apply: the term must be `OPEN` or `ROSTER_LOCKED`, the covering roster must not be `CERTIFIED`, and the program must not be inside an accreditor lockout window. Withdrawal is the compensating path for the load ledger — `assigned_credit_hours` decreases by exactly the section's `credit_hours`, restoring the pre-creation value — and the section's `instructor_of_record_id` resets to null when this row held it. Withdrawing a flagged or remediating assignment additionally decreases the owning program's `unqualified_assignment_count` by 1; withdrawing anything other than a `PENDING_VERIFICATION` row recomputes the covering `GENERATED` roster and rewrites the owning program; and withdrawing a remediating row moves any `SUBMITTED` or `UNDER_REVIEW` justification backing it to `WITHDRAWN`. The assignment and every touched row have `version` incremented by 1. Both `SUPERSEDED` and `WITHDRAWN` are terminal.

Finally, an assignment can be flagged after it was already clean. Cascade A's second hop and a fresh roster generation that re-runs the determination against changed evidence both drive `VERIFIED_QUALIFIED → EXCEPTION_FLAGGED`, provided the covering roster is not `CERTIFIED` — a certified roster refuses the move with `ERR_ROSTER_CERTIFIED`. The `exception_code` is set (`DOSSIER_DEFICIENT` on the cascade path), the owning program's `unqualified_assignment_count` increases by 1, and the covering `GENERATED` roster recomputes.

### 3.5. Tested Experience as an Alternative Path

Some genuinely qualified instructors do not hold the diploma the accreditor's default rule wants — a working broadcast journalist teaching a production course, a board-certified nurse teaching clinical practice. For these the accreditor accepts **tested experience**, documented in a narrative backed by alternative credentials, and decided by a credential analyst who was not involved in verifying that faculty member's credentials.

A `ProgramDean` drafts a justification against a flagged assignment of their own program, supplying the `course_assignment_id`, a `narrative`, an `alternative_credential_codes` array of documented alternative-credential strings, a `documented_years_experience` figure of discipline-relevant professional experience that may not be negative, an `industry_certification_level` of `NONE`, `PRACTITIONER`, `ADVANCED` or `BOARD_CERTIFIED`, and an optional `supervisor_attestation_on_file` flag that defaults to false. The justification is created in `DRAFT` with `tested_experience_score` already computed, `decided_by_user_id` null and `decision_rationale` null. While it remains a draft the dean may edit `narrative`, `alternative_credential_codes`, `documented_years_experience`, `industry_certification_level` and `supervisor_attestation_on_file`, and the score is recomputed on every edit with the `version` incrementing by 1. Justifications are listable and filterable by `course_assignment_id`, `status` and `industry_certification_level`.

**The score.** `tested_experience_score` is a weighted blend of three factors, carried to 4 decimal places and rounded half up:

- The **years factor** is `documented_years_experience` divided by 8, capped at 1.0 — eight years of documented experience earns full credit, and more than eight earns no extra.
- The **certification factor** is read off `industry_certification_level`: 0.00 for `NONE`, 0.50 for `PRACTITIONER`, 0.75 for `ADVANCED` and 1.00 for `BOARD_CERTIFIED`.
- The **codes factor** is the count of `alternative_credential_codes` divided by 4, capped at 1.0. Only distinct values count, and four distinct codes reach the cap.

The score is the years factor times 0.50, plus the certification factor times 0.30, plus the codes factor times 0.20. Eight years, `PRACTITIONER` certification and a single alternative credential code therefore land at exactly 0.7000; the same profile with no codes at all lands at 0.6500; six years with `ADVANCED` certification and three codes reaches 0.7500; and two years with `BOARD_CERTIFIED` certification and four codes reaches only 0.6250.

The dean submits the justification by naming a `to_status` of `SUBMITTED`, moving `DRAFT → SUBMITTED`. The backed assignment must be in `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`, or the submission is rejected with `ERR_INVALID_STATE`, and `tested_experience_score` is recomputed from the current field values as part of the transition. The same `to_status` input carries a value of `WITHDRAWN`, which is legal from either `DRAFT` or `SUBMITTED`.

A `CredentialAnalyst` takes the submission under review, moving `SUBMITTED → UNDER_REVIEW` with no preconditions and no body. The analyst then decides, supplying a `decision` of `APPROVE` or `REJECT` together with a required `decision_rationale`. Both arms stamp `decided_by_user_id` with the acting `X-User-ID` and store the rationale, and both are subject to **segregation of duties**: the acting user must not appear as `verified_by_user_id` on *any* credential record belonging to the backed assignment's faculty member. An analyst who verified so much as one of that faculty member's credentials is rejected with `ERR_SEGREGATION_OF_DUTIES`, and this check is evaluated ahead of the attestation and score checks.

The approve arm additionally demands two things. `supervisor_attestation_on_file` must be true, or the decision fails with `ERR_ATTESTATION_MISSING` — a signed supervisor attestation is a hard precondition and no score compensates for its absence. And `documented_years_experience` must be at least 3 **while** `tested_experience_score` is at least 0.70, or the decision fails with `ERR_TESTED_EXPERIENCE_INSUFFICIENT`. Both thresholds are inclusive: exactly three years is enough, and a score of exactly 0.7000 is approvable. Neither check applies on the reject arm; a rejection needs no attestation and no minimum score.

**Cascade B: approve and reject are not symmetric.** An approval moves the justification `UNDER_REVIEW → APPROVED` and fires three hops. *Hop 1* — the backed assignment moves to `VERIFIED_QUALIFIED` with `qualification_basis` `TESTED_EXPERIENCE`, `exception_code` null and `remediation_action` null. *Hop 2* — because that assignment left the exception set, the covering `GENERATED` roster's snapshot recomputes: `flagged_exception_count` decreases by 1, while `adequacy_ratio_snapshot` does **not** rise, because `TESTED_EXPERIENCE` is excluded from the qualified numerator. *Hop 3* — because the roster snapshot changed, the program's `adequacy_ratio`, `adequacy_status` and `unqualified_assignment_count` are rewritten, and `blocking_reason_codes` may well retain `ADEQUACY_BELOW_MINIMUM`, leaving `certification_readiness` at `BLOCKED` even though the roster now has zero exceptions. The justification, the assignment, the roster and the program each have `version` incremented by 1.

A rejection moves the justification `UNDER_REVIEW → REJECTED` and fires **nothing**. The backed assignment is not touched — it stays in `REMEDIATION_IN_PROGRESS` or `EXCEPTION_FLAGGED` exactly as it was — and no roster and no program recomputes. Only the justification's own `version` increments by 1.

A rejected justification is not dead either. Resubmission is not the route back: the dean re-opens it instead through a revision capability that moves `REJECTED → DRAFT` and resets both `decided_by_user_id` and `decision_rationale` to null, incrementing the `version` by 1. From `DRAFT` the dean can add credentials and submit again. Every dean-driven transition on a justification — submitting, withdrawing, editing, revising — requires `X-User-ID` to equal the `program_id` of the backed assignment's section, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. `APPROVED` and `WITHDRAWN` are terminal, and a justification sitting in `UNDER_REVIEW` is moved to `WITHDRAWN` by the system when its backed assignment is superseded or withdrawn.

### 3.6. Roster Generation, Certification and Program Adequacy

The faculty roster is the artifact the accreditor actually reads: one row per faculty-to-section assignment for a given program in a given term, with exceptions flagged and a headline adequacy figure.

A roster is opened in `DRAFT` by an `AccreditationLiaison` or by the owning `ProgramDean`, naming the `program_id` and `term_id`; a dean's `program_id` must equal `X-User-ID`. Only one live roster per program-term pair is allowed: if a roster for the same pair already exists in `DRAFT` or `GENERATED`, the create is rejected with `ERR_DUPLICATE_ROSTER`. A `CERTIFIED` roster, by contrast, is not a duplicate — it moves to `SUPERSEDED`, which is terminal, and the assignments it had frozen become mutable again. The new roster begins with `generation_epoch` 0, every snapshot count at 0, `adequacy_ratio_snapshot` 0.0, `certification_readiness` `BLOCKED`, `blocking_reason_codes` empty, and both `certified_at` and `certified_by_user_id` null. Rosters are listable and filterable by `program_id`, `term_id`, `status` and `certification_readiness`.

Generation is the liaison's reconciliation loop, and it is deliberately repeatable: `DRAFT → GENERATED` and `GENERATED → GENERATED` are both legal, and each call requires the term to be `OPEN` or `ROSTER_LOCKED` or fails with `ERR_TERM_LOCKED`. Every call increments `generation_epoch` by exactly 1 — and generation is the *only* thing that does; snapshot recomputes triggered by cascades leave it alone. Generation re-decides the roster's assignments: every included assignment in `PENDING_VERIFICATION` is put through the qualification determination, every `EXCEPTION_FLAGGED` assignment is re-evaluated and returns to `VERIFIED_QUALIFIED` when the evidence now passes, and `REMEDIATION_IN_PROGRESS` assignments are left strictly alone. The snapshot is then rebuilt, the program's `adequacy_ratio`, `adequacy_status`, `adequacy_term_id` and `unqualified_assignment_count` are rewritten, and the roster's `version`, each re-decided assignment's `version` and the program's `version` each increment by 1.

**The roster snapshot.** The **included set** for a roster is every course assignment whose section's `program_id` and `term_id` match the roster's and whose `status` is neither `SUPERSEDED` nor `WITHDRAWN`. From that set:

- `total_assignment_count` is the number of included assignments.
- `distinct_faculty_count` is the number of distinct `faculty_member_id` values across them.
- `flagged_exception_count` is the number of included assignments whose `status` is `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`.
- `terminal_qualified_headcount` is the number of distinct `faculty_member_id` values across the included assignments whose `status` is `VERIFIED_QUALIFIED` and whose `qualification_basis` is `TERMINAL_DEGREE`.
- `credit_hours_total` is the sum of `CourseSection.credit_hours` over the included assignments.
- `credit_hours_terminal_qualified` is that same sum restricted to included assignments whose `status` is `VERIFIED_QUALIFIED` and whose `qualification_basis` is `TERMINAL_DEGREE`.
- `adequacy_ratio_snapshot` is the adequacy ratio computed under the program's own `adequacy_basis`, carried to 4 decimal places and rounded half up.

`blocking_reason_codes` is then rebuilt from empty and appended to in exactly this declared order: `EXCEPTIONS_OUTSTANDING`, when any included assignment is in `PENDING_VERIFICATION`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`; then `ADEQUACY_BELOW_MINIMUM`, when `adequacy_ratio_snapshot` is below the program's `min_terminal_ratio`; then `DOSSIER_DEFICIENT`, when any included faculty member's `dossier_status` is `INCOMPLETE` or `DEFICIENT`. `certification_readiness` is `READY` when that list came out empty and `BLOCKED` otherwise — equivalently, `READY` requires zero flagged exceptions, an `adequacy_ratio_snapshot` at or above `min_terminal_ratio`, and a `VERIFIED` dossier for every included faculty member. Note the consequence for an empty roster: with no included assignments every count is zero, `adequacy_ratio_snapshot` is 0.0000, and because 0.0000 falls below any positive `min_terminal_ratio`, `blocking_reason_codes` holds `ADEQUACY_BELOW_MINIMUM`. An empty roster is `BLOCKED`, never trivially `READY`.

The roster's included set is also directly readable: an entries capability returns the included assignments ordered by `created_at` ascending, with each row's `exception_code` visible, and an `only_flagged` switch that when true restricts the result to `EXCEPTION_FLAGGED` and `REMEDIATION_IN_PROGRESS` rows.

**Program faculty adequacy.** This is the share of the program's teaching load carried by terminal-degree-qualified faculty, and it is the number substantive-change and new-program review turns on. Over the anchor roster's included set, the **terminal** subset is those included assignments whose `status` is `VERIFIED_QUALIFIED` and whose `qualification_basis` is `TERMINAL_DEGREE`. The program's `adequacy_basis` flag then picks how the two sides of the ratio are measured:

- Under `HEADCOUNT`, the denominator is the count of distinct `faculty_member_id` values over the included set and the numerator is the count of distinct `faculty_member_id` values over the terminal subset. One terminal-degree instructor teaching a single one-credit-hour section counts exactly as much as an unqualified instructor teaching four four-credit-hour sections.
- Under `CREDIT_HOUR_COVERAGE`, the denominator is the sum of `CourseSection.credit_hours` over the included set and the numerator is that same sum over the terminal subset.

The ratio is the numerator divided by the denominator, carried to 4 decimal places and rounded half up, and it is 0.0000 whenever the denominator is 0 — division never errors. `adequacy_status` is then `ADEQUATE` when the ratio is at or above `min_terminal_ratio`; otherwise `AT_RISK` when the ratio is at or above `min_terminal_ratio` less a band of 0.15; otherwise `INSUFFICIENT`. Alongside the ratio, `unqualified_assignment_count` is set to the number of included assignments whose `status` is `PENDING_VERIFICATION`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`.

The two bases diverge on the same roster. Take a roster with two faculty members: the first `VERIFIED_QUALIFIED` on the basis of a terminal degree, teaching a one-credit-hour section; the second `VERIFIED_QUALIFIED` on the basis of eighteen graduate credit hours, teaching a four-credit-hour section; with `min_terminal_ratio` at 0.60. Under `HEADCOUNT` the ratio is one faculty member out of two, or 0.5000, which sits at or above 0.60 less 0.15 and therefore reads `AT_RISK`. Under `CREDIT_HOUR_COVERAGE` the ratio is one credit hour out of five, or 0.2000, which falls below 0.45 and therefore reads `INSUFFICIENT`. Both `TESTED_EXPERIENCE` and `COURSEWORK_18_HOUR` assignments sit in the denominator but never in the numerator, which is why a roster with zero outstanding exceptions can still be `INSUFFICIENT`.

**Certification.** An `AccreditationLiaison` certifies a `READY` roster, moving `GENERATED → CERTIFIED` and optionally supplying an `attestation_note`. Four preconditions apply. `certification_readiness` must be `READY`, or the request fails with `ERR_ROSTER_NOT_READY`. The term must be `OPEN` or `ROSTER_LOCKED`, or it fails with `ERR_TERM_LOCKED`. The program must have no accreditor review sitting in `REMEDIATION_REQUIRED`, or it fails with `ERR_INVALID_STATE`. And segregation of duties applies: the acting `X-User-ID` must not appear as `decided_by_user_id` on any tested-experience justification whose backed assignment is included in this roster, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. On success, `certified_at` is stamped with the logical clock instant and `certified_by_user_id` with the acting `X-User-ID`, the roster's `version` increments by 1, and every included assignment becomes immutable — remediation, reverification and withdrawal against it are all thereafter rejected with `ERR_ROSTER_CERTIFIED`, as is attaching a new assignment to any of its sections.

### 3.7. Contracting the Faculty, and Separating Them

Credentialing must precede contracting. A `ProgramDean` issues a contract for a faculty member whose `home_program_id` equals `X-User-ID`, naming the `faculty_member_id`, the `term_id`, the `employment_class` the contract commits to, a positive `contract_credit_hours`, and the `expected_faculty_version` guard from §2.7. The submitted `employment_class` must equal the faculty member's own current `employment_class`; a mismatch is a shape violation reported as `ERR_INVALID_REQUEST`.

Three domain checks then apply in a fixed order that matters. A separated faculty member cannot be contracted at all (`ERR_FACULTY_SEPARATED`). Then `dossier_status` must be `VERIFIED`, or the issuance fails with `ERR_DOSSIER_NOT_VERIFIED` — this is the gate that stops adjunct and clinical faculty from being hired ahead of their credentialing, and it applies identically to every employment class. Only once the dossier gate is satisfied is the timing checked: the clock date must be **strictly before** the contracted term's `start_date`, or the issuance fails with `ERR_CONTRACT_WINDOW_CLOSED`. A dean who tries to contract an unverified faculty member into an already-started term is told about the dossier, not the calendar.

A new contract lands in `ISSUED` with `issued_at` stamped from the logical clock, `countersigned_at` null, `dossier_snapshot_status` pinned at `VERIFIED` and `credential_snapshot_version` pinned to the faculty member's `version` at that instant. Any earlier contract for the same faculty member and term moves to `SUPERSEDED`, which is terminal, with its own `version` incrementing by 1. The faculty member's `version` also increments by 1 as the concurrency parent. Contracts are listable and filterable by `faculty_member_id`, `term_id`, `status` and `employment_class`, and an `Instructor` may read only their own.

Countersignature is the instructor's own act. An `Instructor` whose `X-User-ID` equals the contract's `faculty_member_id` countersigns an `ISSUED` contract, moving it `ISSUED → COUNTERSIGNED` and simultaneously moving the faculty member's appointment `CREDENTIALED_ELIGIBLE → CONTRACTED`. The contract must still be `ISSUED`, or the request fails with `ERR_INVALID_STATE`, and the faculty member must not be `SEPARATED`, or it fails with `ERR_FACULTY_SEPARATED`. `countersigned_at` is stamped from the logical clock, and both the contract's and the faculty member's `version` increment by 1.

Voiding is the compensating path, available to the owning dean — `X-User-ID` must equal the faculty member's `home_program_id` — from either `ISSUED` or `COUNTERSIGNED`, with an optional `reason`. `VOIDED` is terminal. When the void leaves no other contract of that faculty member in `ISSUED` or `COUNTERSIGNED`, the appointment reverts `CONTRACTED → CREDENTIALED_ELIGIBLE` — **never** to `PROSPECT`, because the credentialing that earned eligibility has not been undone. Voiding a contract while another live contract remains changes only the contract. The contract's `version`, and the faculty member's where the appointment moved, increment by 1.

Separation is the terminal move on the appointment dimension, performed by a `RegistrarOfficer` with an optional `reason`. It is legal from `PROSPECT`, `CREDENTIALED_ELIGIBLE` or `CONTRACTED`, and `SEPARATED` is terminal — nothing may afterwards be attached to a separated faculty member. From `PROSPECT` the separation has no preconditions and no cascade beyond incrementing the faculty member's `version` by 1. From `CREDENTIALED_ELIGIBLE` or `CONTRACTED`, one precondition guards it: none of the faculty member's assignments in `PENDING_VERIFICATION`, `VERIFIED_QUALIFIED`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS` may belong to a program-term pair whose roster is `CERTIFIED`, or the separation is rejected with `ERR_ROSTER_CERTIFIED`. You cannot make a certified roster wrong by walking a faculty member out of the building.

**Cascade C**, identical from either `CREDENTIALED_ELIGIBLE` or `CONTRACTED`, then fires in three hops. *Hop 1* — every assignment of that faculty member in `PENDING_VERIFICATION`, `VERIFIED_QUALIFIED`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS` moves to `WITHDRAWN`. *Hop 2* — because those assignments left the ledger set, `assigned_credit_hours` becomes 0, and every section whose `instructor_of_record_id` pointed at this faculty member resets it to null. *Hop 3* — because assignments were withdrawn, the snapshot recomputes on every `GENERATED` roster that included them and each affected program is rewritten. Separately, every `ISSUED` or `COUNTERSIGNED` contract of that faculty member moves to `VOIDED`. The faculty member and every touched row have `version` incremented by 1.

### 3.8. Documenting Ongoing Professional Development

Accreditors expect faculty to stay current in the discipline they teach, and they expect the institution to be able to prove it. A professional-development activity is logged either by the `Instructor` themselves — whose `faculty_member_id` must equal `X-User-ID` — or by a `RegistrarOfficer` on their behalf. The record names the `faculty_member_id`, the `discipline_id` of the activity, an `activity_type` of `CONFERENCE`, `CERTIFICATION`, `COURSEWORK`, `INDUSTRY_PLACEMENT` or `PUBLICATION`, a positive `contact_hours` figure, and an `activity_date` giving the date-only ISO 8601 day the activity concluded. Development cannot be logged before it happens: an `activity_date` after the clock date is rejected with `ERR_PD_DATE_IN_FUTURE`. Nothing may be logged against a separated faculty member either (`ERR_FACULTY_SEPARATED`).

At creation the record's `discipline_relevant` flag is computed once and frozen: it is true when the activity's `discipline_id` aligns, at a score of 0.70 or above, with the discipline of the faculty member's home program — which under §2.9 means the same discipline node or a direct parent-or-child relationship. Re-homing the faculty member later does not rewrite it. The record lands in `status` `SUBMITTED`, and `pd_hours_current_cycle` is not touched yet, because only verified activity counts. Records are listable and filterable by `faculty_member_id`, `discipline_id`, `status`, `activity_type` and `discipline_relevant`; an `Instructor` may read only their own.

A `CredentialAnalyst` then judges the record by naming a `to_status`. `SUBMITTED → VERIFIED` admits it to the compliance window and re-runs the compliance calculation for the faculty member, rewriting `pd_hours_current_cycle` and `pd_compliant`, with both the record's and the faculty member's `version` incrementing by 1. `SUBMITTED → REJECTED` keeps the record permanently out of the window and leaves `pd_hours_current_cycle` unchanged, incrementing only the record's `version` by 1. Both `VERIFIED` and `REJECTED` are terminal.

**The rolling compliance cycle.** Compliance is anchored on a deterministically chosen term so that no wall-clock read is ever needed. The **anchor term** is the term whose `status` is `OPEN` with the greatest `end_date`, breaking ties by the earlier `created_at`; if no term is `OPEN`, it is the term with the greatest `end_date` over all terms, again breaking ties by the earlier `created_at`. When no term exists at all, `pd_hours_current_cycle` is 0 and `pd_compliant` is false. The **cycle window** runs from three years — 1,095 days — before the anchor term's `end_date` up to that `end_date`, and it is fully closed on both ends, so an activity concluding exactly on either boundary counts. A record is relevant when its `status` is `VERIFIED`, its `activity_date` falls inside that window, and its `discipline_id` aligns with the home program's discipline at 0.70 or above. `pd_hours_current_cycle` is the sum of `contact_hours` over the relevant records, carried to 1 decimal place and rounded half up.

`pd_compliant` is then true when `pd_hours_current_cycle` reaches the requirement for the faculty member's `employment_class`: 40 hours for `FULL_TIME`, 30 for `CLINICAL`, 20 for `ADJUNCT` and 10 for `GRADUATE_ASSISTANT`. Because the requirement follows the employment class, re-classifying a faculty member can flip `pd_compliant` without any new activity being logged — which is why updating a faculty member re-runs this calculation. Advancing the logical clock can also change the answer, because a newly-`OPEN` term can become the anchor and shift the window; the compliance figures are re-derived when the faculty member is next read.

### 3.9. Accreditor Review, Findings and the Remediation Negotiation

An `AccreditorReviewer` schedules a review by naming the `program_id`, a `review_type` of `SUBSTANTIVE_CHANGE`, `COMPREHENSIVE` or `FOCUSED_FOLLOWUP`, and a `window_start_date` and `window_end_date` giving the on-site review window as date-only ISO 8601 values. The window is **fully closed on both ends**, and windows of non-terminal reviews of the same program may not collide: comparing against reviews of that program whose `status` is neither `CLOSED_ACCEPTED` nor `CLOSED_SANCTION`, a collision exists when the new window's start is on or before the other's end and the other's start is on or before the new window's end. Two windows that merely *touch* at a single date therefore do collide, and the offender is rejected with `ERR_REVIEW_WINDOW_OVERLAP`. This is deliberately the opposite endpoint convention from the half-open teaching-block rule of §3.4. A window whose `window_start_date` falls after its `window_end_date` is rejected with `ERR_INVALID_WINDOW`. A new review lands in `SCHEDULED` with `finding_count` 0, `response_round` 0, `unqualified_assignment_ids` empty, `preliminary_risk_index` and `risk_index` 0.0, `risk_tier` `LOW`, and both `response_due_date` and `response_narrative` null. Reviews are listable and filterable by `program_id`, `status`, `review_type` and `risk_tier`.

The reviewer drives the lifecycle by naming a `to_status`, with an optional `note`. `SCHEDULED → IN_PROGRESS` is legal only once the clock date has reached `window_start_date`; attempting it earlier is rejected with `ERR_INVALID_WINDOW`. Going in progress starts the **evidence freeze**: while the clock date lies inside the review's fully closed window and the review sits in `IN_PROGRESS`, `FINDINGS_ISSUED` or `REMEDIATION_REQUIRED`, the program cannot take new course assignments, cannot withdraw existing ones, and cannot have credential evaluations billed to it — all three are rejected with `ERR_ACCREDITOR_REVIEW_LOCKOUT`. Closing the review ends the lockout.

Issuing findings is where the review forks. The reviewer supplies a `finding_count` — a non-negative integer captured verbatim as the number of findings the accreditor is recording — and an optional `narrative`. A roster with `status` `GENERATED` or `CERTIFIED` must exist for the program, or the request is rejected with `ERR_ROSTER_NOT_FOUND`. The **anchor roster** is that program's roster in `GENERATED` or `CERTIFIED` with the greatest `created_at`. Both arms write `unqualified_assignment_ids` — the identifiers of the anchor roster's assignments in `PENDING_VERIFICATION`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`, ordered by their `created_at` ascending — along with `finding_count`, `preliminary_risk_index`, `risk_tier`, `risk_index` and `response_due_date`, all computed from the state observed **before** any remediation cascade runs.

`finding_count` alone selects the branch, and it is deliberately independent of how many unqualified assignments the roster has: an accreditor may record documentation findings against a roster with zero unqualified assignments, or record none at all against a roster full of them.

- When `finding_count` is above 0, the review moves `IN_PROGRESS → REMEDIATION_REQUIRED`. Every listed assignment currently in `EXCEPTION_FLAGGED` moves to `REMEDIATION_IN_PROGRESS` with `remediation_action` set to `REASSIGN_PENDING`. The anchor roster then recomputes — `flagged_exception_count` is unchanged, because a remediating assignment is still an exception — and the program is rewritten. The review's `version` and each touched assignment's, roster's and program's `version` increment by 1.
- When `finding_count` is 0, the review moves `IN_PROGRESS → FINDINGS_ISSUED`. Risk metrics and `response_due_date` are written exactly as above, from the tier the index selects. **No remediation cascade fires** — this is the clean-review branch — and only the review's `version` increments by 1.

**The risk index.** Four factors are measured over the anchor roster's included assignments — those in the program and the anchor roster's term whose `status` is neither `SUPERSEDED` nor `WITHDRAWN`:

- The **unqualified share** is the count of included assignments in `PENDING_VERIFICATION`, `EXCEPTION_FLAGGED` or `REMEDIATION_IN_PROGRESS`, divided by the total number of included assignments; it is 0 when there are no included assignments.
- The **dossier share** is the count of distinct faculty on those assignments whose `dossier_status` is `INCOMPLETE` or `DEFICIENT`, divided by the number of distinct faculty; it is 0 when there are none.
- The **exception-persistence share** is the count of included assignments in `REMEDIATION_IN_PROGRESS` divided by the total number of included assignments; it is 0 when there are no included assignments.
- The **adequacy gap** is 0 when the program's `min_terminal_ratio` is 0, or when the roster's `adequacy_ratio_snapshot` already reaches `min_terminal_ratio`. Otherwise it is `min_terminal_ratio` minus `adequacy_ratio_snapshot`, divided by `min_terminal_ratio`, capped at 1.

`preliminary_risk_index` is 100 multiplied by the weighted sum of those four — the unqualified share weighted 0.40, the dossier share 0.25, the exception-persistence share 0.20 and the adequacy gap 0.15 — rounded half up to 2 decimal places. All four factors are read from the state that existed **before** the findings remediation cascade moved any `EXCEPTION_FLAGGED` assignment into `REMEDIATION_IN_PROGRESS`.

`risk_tier` is then selected from `preliminary_risk_index` **and from nothing else**: `LOW` when it is below 30, `MODERATE` when it is below 60, and `HIGH` otherwise. `risk_index` is `preliminary_risk_index` multiplied by the tier's multiplier — 1.00 for `LOW`, 1.10 for `MODERATE`, 1.25 for `HIGH` — rounded half up to 2 decimal places and then capped at 100.00. `response_due_date` is the clock date plus the tier's response allowance: 90 days for `LOW`, 60 for `MODERATE`, 30 for `HIGH`.

The single-pass tier selection is the point of the design and worth working through. Take an anchor roster with 4 included assignments of which 3 are unqualified — one of those already remediating — across 2 distinct faculty of whom 1 is deficient, with `adequacy_ratio_snapshot` 0.3000 against a `min_terminal_ratio` of 0.60. The unqualified share is 0.75, the dossier share 0.5, the exception-persistence share 0.25 and the adequacy gap 0.5, giving a `preliminary_risk_index` of 55.00. That selects `MODERATE`, so `risk_index` becomes 60.50 and the response allowance is 60 days — with the clock at 2026-08-01, a `response_due_date` of 2026-09-30. Observe that `risk_index` of 60.50 is at or above the `HIGH` floor, and yet `risk_tier` stays `MODERATE` and the window stays 60 days. Re-deriving the tier from `risk_index` would wrongly produce `HIGH` and a 30-day window.

Once a review demands remediation, the `AccreditationLiaison` answers. Filing the response supplies a required `response_narrative` and moves `REMEDIATION_REQUIRED → RESPONSE_SUBMITTED`, permitted up to and including `response_due_date` — submitting exactly on the due date is allowed, and submitting after it is rejected with `ERR_RESPONSE_WINDOW_CLOSED`. `response_round` increases by 1, the narrative is stored, and the review's `version` increments by 1.

The reviewer then has three ways out of `RESPONSE_SUBMITTED`. Bouncing the response back, `RESPONSE_SUBMITTED → REMEDIATION_REQUIRED`, has no preconditions; it recomputes the risk metrics against the current anchor roster and resets `response_due_date` to the clock date plus the freshly selected tier's response days, while **leaving `response_round` exactly as it is**. The negotiation can therefore run an unbounded number of rounds. Accepting, `RESPONSE_SUBMITTED → CLOSED_ACCEPTED`, requires the program to be clean — `adequacy_status` `ADEQUATE` and `unqualified_assignment_count` 0 — or it is rejected with `ERR_PROGRAM_ADEQUACY_INSUFFICIENT`. Sanctioning, `RESPONSE_SUBMITTED → CLOSED_SANCTION`, is available only from a `response_round` of at least 2, so a program gets at least two attempts before a sanction is possible; an earlier attempt is rejected with `ERR_INVALID_STATE`. A clean review in `FINDINGS_ISSUED` also closes directly with `FINDINGS_ISSUED → CLOSED_ACCEPTED`, under the same program-cleanliness requirement. Both `CLOSED_ACCEPTED` and `CLOSED_SANCTION` are terminal, both end the lockout, and both increment the review's `version` by 1. Sanctioning deliberately does **not** touch `Program.launch_status` — sanction handling is a separate governance process outside this API.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Every other operation — reading, listing, driving a state machine, or otherwise modifying an existing resource — returns `200 OK`. Where a table row lists "All except Instructor", the authorized roles are `SystemAdmin`, `RegistrarOfficer`, `CredentialAnalyst`, `ProgramDean`, `AccreditationLiaison` and `AccreditorReviewer`; where it lists "All roles", `Instructor` is included as well, subject to the ownership restriction of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the service's logical clock, the only source of "now" | SystemAdmin |
| GET | `/_clock` | Read the current logical clock instant | All except Instructor |
| POST | `/disciplines` | Create a discipline taxonomy node | SystemAdmin |
| POST | `/disciplines/{disciplineId}` | Update a discipline node's mutable fields | SystemAdmin |
| GET | `/disciplines/{disciplineId}` | Read one discipline node | All except Instructor |
| GET | `/disciplines` | List discipline nodes | All except Instructor |
| POST | `/programs` | Create an academic program with its two policy flags | SystemAdmin |
| GET | `/programs/{programId}` | Read one program with live adequacy and budget fields | All except Instructor |
| GET | `/programs` | List programs | All except Instructor |
| GET | `/programs/{programId}/adequacy` | Computed adequacy read, optionally under the other basis | All except Instructor |
| POST | `/programs/{programId}/launch-review` | Submit the program for faculty-adequacy review | ProgramDean |
| POST | `/programs/{programId}/launch-decision` | Approve or deny the program launch | AccreditationLiaison |
| POST | `/terms` | Create a term in `PLANNING` | SystemAdmin, RegistrarOfficer |
| GET | `/terms/{termId}` | Read one term | All except Instructor |
| GET | `/terms` | List terms | All except Instructor |
| POST | `/terms/{termId}/status` | Drive the term lifecycle | RegistrarOfficer |
| POST | `/faculty-members` | Create a faculty member | RegistrarOfficer |
| POST | `/faculty-members/{facultyMemberId}` | Update a faculty member's identity fields | RegistrarOfficer |
| GET | `/faculty-members/{facultyMemberId}` | Read one faculty member with both state dimensions | All roles |
| GET | `/faculty-members` | List faculty members | All except Instructor |
| POST | `/faculty-members/{facultyMemberId}/separation` | Separate a faculty member | RegistrarOfficer |
| POST | `/credential-records` | File a credential for a faculty member | RegistrarOfficer |
| GET | `/credential-records/{credentialRecordId}` | Read one credential record with its effective level | All except Instructor |
| GET | `/credential-records` | List credential records | All except Instructor |
| GET | `/faculty-members/{facultyMemberId}/credential-records` | List one faculty member's credential evidence set | All roles |
| POST | `/credential-records/{credentialRecordId}/transcript` | Advance official transcript collection | RegistrarOfficer |
| POST | `/credential-records/{credentialRecordId}/verification` | Verify, reject or repudiate a credential | CredentialAnalyst |
| POST | `/credential-evaluations` | Order a foreign-credential evaluation, freezing its fee | CredentialAnalyst |
| GET | `/credential-evaluations/{evaluationId}` | Read one evaluation with its fee and allocation shares | All except Instructor |
| GET | `/credential-evaluations` | List credential evaluations | All except Instructor |
| POST | `/credential-evaluations/{evaluationId}/status` | Drive the evaluation lifecycle | CredentialAnalyst |
| POST | `/course-sections` | Create a section of the dean's own program | ProgramDean |
| GET | `/course-sections/{sectionId}` | Read one section with its instructor-of-record mirror | All except Instructor |
| GET | `/course-sections` | List course sections | All except Instructor |
| POST | `/course-assignments` | Assign a faculty member to a section and decide qualification | ProgramDean |
| GET | `/course-assignments/{assignmentId}` | Read one assignment with its qualification verdict | All except Instructor |
| GET | `/course-assignments` | List course assignments | All except Instructor |
| GET | `/course-sections/{sectionId}/course-assignments` | List one section's assignments | All except Instructor |
| POST | `/course-assignments/{assignmentId}/remediation` | Open remediation on a flagged assignment | ProgramDean |
| POST | `/course-assignments/{assignmentId}/reverification` | Re-run the qualification verdict on a remediating assignment | CredentialAnalyst |
| POST | `/course-assignments/{assignmentId}/withdrawal` | Withdraw an assignment | ProgramDean |
| POST | `/tested-experience-justifications` | Draft a tested-experience justification | ProgramDean |
| POST | `/tested-experience-justifications/{justificationId}` | Edit a draft justification's evidence fields | ProgramDean |
| GET | `/tested-experience-justifications/{justificationId}` | Read one justification with its score and decision trail | All except Instructor |
| GET | `/tested-experience-justifications` | List tested-experience justifications | All except Instructor |
| POST | `/tested-experience-justifications/{justificationId}/status` | Submit or withdraw a justification | ProgramDean |
| POST | `/tested-experience-justifications/{justificationId}/review` | Take a submitted justification under review | CredentialAnalyst |
| POST | `/tested-experience-justifications/{justificationId}/decision` | Approve or reject a justification | CredentialAnalyst |
| POST | `/tested-experience-justifications/{justificationId}/revision` | Re-open a rejected justification for revision | ProgramDean |
| POST | `/faculty-rosters` | Open a draft roster for a program and term | AccreditationLiaison, ProgramDean |
| GET | `/faculty-rosters/{rosterId}` | Read one roster with its snapshot and readiness | All except Instructor |
| GET | `/faculty-rosters` | List faculty rosters | All except Instructor |
| GET | `/faculty-rosters/{rosterId}/entries` | Read the roster's included assignment set | All except Instructor |
| POST | `/faculty-rosters/{rosterId}/generate` | Generate or regenerate the roster | AccreditationLiaison |
| POST | `/faculty-rosters/{rosterId}/certification` | Certify a ready roster and freeze its assignments | AccreditationLiaison |
| POST | `/faculty-contracts` | Issue a contract for a credentialed faculty member | ProgramDean |
| GET | `/faculty-contracts/{contractId}` | Read one contract with its pinned credential snapshot | All roles |
| GET | `/faculty-contracts` | List faculty contracts | All except Instructor |
| POST | `/faculty-contracts/{contractId}/countersignature` | Countersign one's own issued contract | Instructor |
| POST | `/faculty-contracts/{contractId}/void` | Void an issued or countersigned contract | ProgramDean |
| POST | `/pd-records` | Log a professional development activity | Instructor, RegistrarOfficer |
| GET | `/pd-records/{pdRecordId}` | Read one professional development record | All roles |
| GET | `/pd-records` | List professional development records | All except Instructor |
| POST | `/pd-records/{pdRecordId}/status` | Verify or reject a professional development record | CredentialAnalyst |
| POST | `/accreditor-reviews` | Schedule an accreditor review over a closed date window | AccreditorReviewer |
| GET | `/accreditor-reviews/{reviewId}` | Read one review with its risk metrics and response state | All except Instructor |
| GET | `/accreditor-reviews` | List accreditor reviews | All except Instructor |
| POST | `/accreditor-reviews/{reviewId}/status` | Drive the review lifecycle | AccreditorReviewer |
| POST | `/accreditor-reviews/{reviewId}/findings` | Issue findings against the program's anchor roster | AccreditorReviewer |
| POST | `/accreditor-reviews/{reviewId}/response` | File the remediation response | AccreditationLiaison |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DISCIPLINE_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_TERM_NOT_FOUND` | 404 Not Found |
| `ERR_FACULTY_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_EVALUATION_NOT_FOUND` | 404 Not Found |
| `ERR_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_JUSTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ROSTER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PD_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_SECTION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FACULTY_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TERM_LOCKED` | 409 Conflict |
| `ERR_ROSTER_CERTIFIED` | 409 Conflict |
| `ERR_ACCREDITOR_REVIEW_LOCKOUT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_FACULTY_SEPARATED` | 409 Conflict |
| `ERR_FACULTY_NOT_APPOINTABLE` | 409 Conflict |
| `ERR_DOSSIER_NOT_VERIFIED` | 409 Conflict |
| `ERR_NOT_FOREIGN_CREDENTIAL` | 422 Unprocessable Entity |
| `ERR_DISCIPLINE_CYCLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DISCIPLINE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_TERM_CODE` | 409 Conflict |
| `ERR_DUPLICATE_FACULTY_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_DUPLICATE_ROSTER` | 409 Conflict |
| `ERR_TEACHING_BLOCK_CONFLICT` | 409 Conflict |
| `ERR_REVIEW_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TERM_LOAD_EXCEEDED` | 409 Conflict |
| `ERR_ATTESTATION_MISSING` | 422 Unprocessable Entity |
| `ERR_TESTED_EXPERIENCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_ROSTER_NOT_READY` | 409 Conflict |
| `ERR_PROGRAM_ADEQUACY_INSUFFICIENT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_CONTRACT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PD_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_BUDGET_EXCEEDED` | 422 Unprocessable Entity |

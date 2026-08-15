# Curriculum Approval Catalog API — Product Requirements Document

## 1. Introduction

Every academic year, a university's faculty senate faces the same grinding problem: hundreds of curriculum proposals — new courses, revisions to existing courses, and course deactivations — must be shepherded from a sponsoring faculty member through departmental, committee, senate, and registrar review, and the resulting changes must land, exactly once, in the correct published catalog edition. Today this process lives in email threads and shared spreadsheets; prerequisite chains break silently, catalog numbers are double-assigned, and accreditor notification obligations are discovered after the fact.

This document specifies the Curriculum Approval & Catalog Publication API, the system of record for that workflow. It governs proposal submission and multi-stage routing, prerequisite and corequisite dependency validation with cycle detection, credit-hour workload justification, the substantive-change scoring that drives state/accreditor notification, effective-term assignment and catalog freeze scheduling, cross-listing agreements between departments, deactivation teach-out planning, and the freeze-publish-archive lifecycle of catalog editions. The API is mounted under the top-level path prefix `/curriculum`.

The design treats time as a first-class input: proposal windows, term freezes, and edition freezes are all gated on a server-maintained logical clock rather than wall-clock time, so that registrars can rehearse an entire academic year deterministically. Every mutation is visible in its own response, and every governance decision is preserved in an append-only audit trail.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role string outside the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed in the target endpoint's authorized role set is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles:

- `FacultyProposer` — a faculty member who authors and shepherds curriculum proposals. When `X-User-Role` is `FacultyProposer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server copies it into a proposal's `proposer_id` at creation and thereafter compares that stored field against `X-User-ID` for ownership checks.
- `DepartmentChair` — the chair of a department. When `X-User-Role` is `DepartmentChair`, `X-User-ID` is the `id` of the acting `Department`; ownership checks on any resource that references a `Department` compare the resource's department foreign-key field to `X-User-ID`.
- `CurriculumCommittee` — a faculty senate curriculum committee reviewer. When `X-User-Role` is `CurriculumCommittee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as the decision's `actor_id` but does not compare it to any entity's `id`.
- `FacultySenate` — a faculty senate reviewer. When `X-User-Role` is `FacultySenate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded on decisions exactly as for `CurriculumCommittee`.
- `Registrar` — the registrar operator responsible for terms, departments, course import, editions, final approval, accreditor notification, activation, teach-out completion, and the logical clock. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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
- A request to an unknown path, or carrying an unsupported method on a known path, surfaces as `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` envelope of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource — departments, terms, courses, proposals, requisite links, cross-listings, teach-out plans, catalog editions, and catalog entries — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on any modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one with every mutation of the resource, including mutations caused by cascade side effects originating on a different resource.

The decision log is the sole exception. A `DecisionRecord` is an append-only audit entry carrying only `id` and `created_at` from the common set; both `updated_at` and `version` are absent on decision records, because an audit row, once written, is never modified.

### 2.5. The Logical Clock

All time-gated behavior in the system — proposal submission windows, term freeze actions, and every other rule that asks "what time is it" — is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A registrar-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; from that point on, every subsequent time-gated validation evaluates against the new logical now. The clock never falls back to wall-clock time, before or after any set call. A `to_iso8601` value without an explicit offset is read as UTC — here and wherever an instant is supplied — and the set call returns the supplied value verbatim as `current_utc`. Record and envelope timestamps (`created_at`, `updated_at`, `api_request_timestamp`) always read wall-clock UTC; the logical clock governs only time-gated rule evaluation and the `notification_sent_at` stamp.

### 2.6. Optimistic Concurrency Control

Two write operations guard against lost updates through optimistic concurrency control, and each names its own expected-version field.

Editing a draft or returned proposal requires the request to carry `expected_proposal_version`, holding the value of the proposal's `version` the client last observed. If the supplied value does not equal the proposal's current `version`, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting a document it has not observed.

Editing a term's dates requires the request to carry `expected_term_version`, holding the term's last-observed `version`. A mismatch against the term's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not accept an expected-version field.

### 2.7. Nested Resource Retrieval

Requests that target nested resources are validated left-to-right along the path. Each templated identifier is resolved in turn, and the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource; later segments are never consulted. The same rule applies to identifiers referenced inside a request body — a body-supplied foreign key such as `target_course_id`, `requested_effective_term_id`, `owning_department_id`, `introduced_in_term_id`, `last_enrolled_term_id`, `home_course_id`, `partner_course_id`, `effective_term_id`, or a requisite's `requisite_course_id` that does not resolve is a body-validation failure rather than a path failure and surfaces as `ERR_VALIDATION` (HTTP 400).

### 2.8. Validation Ordering

When several validation rules fail on the same request, the reported error follows a fixed priority order so that failures are never masked arbitrarily. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, left-to-right path resolution (`ERR_NOT_FOUND`); fourth, request-body shape and completeness — a body that is not a JSON object, a field outside the endpoint's accepted set, a missing or null required field, or a mistyped value, as well as type-specific submit completeness, date ordering, array length, and foreign-key existence — is `ERR_VALIDATION`, with an explicit null on an optional field treated as if the field were absent; fifth, resource-level ownership (`ERR_NOT_RESOURCE_OWNER`); sixth, whether the requested transition exists from the resource's current state (`ERR_INVALID_STATE`); seventh, stage-role matching on committee decisions (`ERR_FORBIDDEN`); eighth, segregation of duties (`ERR_SELF_APPROVAL_FORBIDDEN`); and only then the business rules in their own order — accreditor notification pending (`ERR_ACCREDITOR_NOTIFICATION_PENDING`), the proposal submission window (`ERR_PROPOSAL_WINDOW_CLOSED`), freeze dates not yet reached (`ERR_FREEZE_DATE_NOT_REACHED`), terms not locked (`ERR_TERM_NOT_LOCKED`), teach-out commitment (`ERR_TEACH_OUT_NOT_COMMITTED`), requisite target activity (`ERR_REQUISITE_TARGET_INACTIVE`), prerequisite cycles (`ERR_REQUISITE_CYCLE`), self-requisites (`ERR_SELF_REQUISITE`), course-number holds (`ERR_COURSE_NUMBER_HELD`), term date overlap (`ERR_TERM_DATE_OVERLAP`), term sequence conflicts (`ERR_TERM_SEQUENCE_CONFLICT`), edition window conflicts (`ERR_EDITION_WINDOW_CONFLICT`), duplicate cross-listings (`ERR_CROSS_LISTING_EXISTS`), empty learning outcomes (`ERR_LEARNING_OUTCOMES_REQUIRED`), and finally the credit-hour workload check (`ERR_CREDIT_HOUR_MISMATCH`). A consequence worth internalizing: a malformed body always surfaces as `ERR_VALIDATION` before any ownership question is examined, and an ownership failure always surfaces before any wrong-state question. The expected-version check of §2.6 sits after body validation: on the term edit it runs before the overlap rule, and on the proposal edit it runs after the ownership and state checks.

### 2.9. Numbers, Hours, and Money

The substantive-change score and all teach-out arithmetic use integer arithmetic with no rounding. The credit-hour workload check computes credits to exactly one decimal place using round-half-up, and its tolerance comparison is inclusive. Teach-out costs are exact integer counts of cents — no floating-point money anywhere in the system — and the rounding order in the sectioning calculation is pinned: each cohort is rounded up to a whole section count individually, and only then are sections summed. Term completion indices are integers; the ceiling used in the enrollment-driven estimate is exact integer division rounding up.

## 3. Business Logic & Workflows

### 3.1. Academic Groundwork: Departments, Terms, and the Catalog Frame

Before any proposal can move, a `Registrar` lays the academic groundwork. Departments are registered with a `dept_name`, the set of `subject_codes` the department owns (for example `['CS','CSE']`), and the `college` the department belongs to. A department's `id` matters beyond bookkeeping: it is the identity anchor for chairs, since a `DepartmentChair` caller's `X-User-ID` is a department `id`.

Terms are created with a `term_code` such as `2026FA`, an `academic_year` label such as `2026-2027` that later ties terms to catalog editions, a `sequence_index` giving the term its monotonic position, the dates `classes_start_date` and `classes_end_date`, and the two freeze instants `proposal_freeze_at` and `catalog_freeze_at`. Three shape rules are enforced at creation and on every subsequent edit: `classes_end_date` must be strictly later than `classes_start_date`; `proposal_freeze_at` must be at or before `catalog_freeze_at`; and `sequence_index` must be unique across all terms, with a duplicate rejected as `ERR_TERM_SEQUENCE_CONFLICT`.

Terms occupy time under a **half-open interval** convention: a term covers the period starting at `classes_start_date` and running up to but not including `classes_end_date` (the end date is the day after the last day of classes). A new or edited term conflicts with an existing one when its start falls before the other's end and its end falls after the other's start; because the intervals are half-open, pure adjacency — one term's `classes_end_date` exactly equal to another's `classes_start_date` — is not a conflict. Any genuine overlap is rejected with `ERR_TERM_DATE_OVERLAP`. A registrar may revise a term's four date fields after creation, whatever the term's lifecycle status; that edit re-validates both the overlap rule and the date-ordering rules, and is OCC-guarded as described in §2.6.

A term's lifecycle is `OPEN_FOR_PROPOSALS → PROPOSAL_FROZEN → CATALOG_FROZEN`, the last being terminal. Freezing proposals for a term is permitted only once the logical clock has reached that term's `proposal_freeze_at`; attempted earlier, the action is rejected with `ERR_FREEZE_DATE_NOT_REACHED`. Freezing the catalog similarly requires the logical clock to have reached `catalog_freeze_at`, with the same rejection otherwise. Each successful freeze increments the term's `version`. A term also exposes the computed `scheduled_proposal_count`, the number of proposals whose assigned effective term is this one and whose status is either `APPROVED` or `EFFECTIVE`.

### 3.2. The Course Record and the Direct Import Path

A **Course** is the catalog's unit of record. Its descriptive payload consists of a `subject_code`, a `course_number` string such as `101`, a `title`, the `credit_hours` the course carries, `contact_hours_per_week`, `out_of_class_hours_per_week`, and a non-empty `learning_outcomes` array for active courses. Each course is anchored to an `owning_department_id` and records the `introduced_in_term_id` in which it first takes effect. Two system-maintained fields round out the record: `prerequisite_summary`, the `SUBJ NUM` codes of the requisite courses of the course's active prerequisite links in the order those links were created, joined with a single comma and no spaces (empty string when the course has none), and `last_published_edition_id`, which stays null until a catalog entry for the course is published.

A course's status follows `ACTIVE → DEACTIVATING → INACTIVE`. The normal way a course enters the catalog is through an approved new-course proposal (§3.4), but the registrar can also import a course directly: providing `subject_code`, `course_number`, `title`, `credit_hours`, `contact_hours_per_week`, `out_of_class_hours_per_week`, `learning_outcomes`, `owning_department_id`, and `introduced_in_term_id` places the course straight into `ACTIVE` status. This import path is how the initial catalog is loaded, and it enforces the same course-number uniqueness rule as the proposal pipeline — an attempt to import a number already held is rejected with `ERR_COURSE_NUMBER_HELD`, and an empty `learning_outcomes` array on import is rejected with `ERR_VALIDATION`.

### 3.3. Drafting and Editing a Proposal

The **Proposal** is the vehicle for every curriculum change, and its `proposal_type` is one of `NEW_COURSE`, `COURSE_CHANGE`, or `DEACTIVATION`. A `FacultyProposer` creates a proposal in `DRAFT` status by supplying the `proposal_type`, the sponsoring `proposer_department_id`, and the `requested_effective_term_id` naming the term the proposer asks the change to take effect in. At creation the server copies the caller's `X-User-ID` into `proposer_id`, which becomes the ownership anchor for all later author operations.

The remaining payload depends on type. New-course and change proposals carry `proposed_subject_code`, `proposed_title`, `proposed_credit_hours`, `contact_hours_per_week`, `out_of_class_hours_per_week`, and `learning_outcomes`; new-course proposals additionally carry `proposed_course_number`. The `target_course_id` is required for `COURSE_CHANGE` and `DEACTIVATION` and must be null for `NEW_COURSE`; that requirement binds at submission (§3.4), so a change or deactivation draft may be created with `target_course_id` still null. A free-text `justification` may accompany any proposal. Deactivation proposals alone carry `declared_remaining_cohorts`, the number of enrolled cohorts still needing the course, which must be at least zero; a `declared_remaining_cohorts` supplied on a new-course or change proposal, or a negative value, is rejected with `ERR_VALIDATION`. The `proposed_requisites` array — each entry an object naming a `requisite_course_id` and a `requisite_type` of `PREREQUISITE` or `COREQUISITE` — defaults to an empty array when omitted. The computed `substantive_change_score` and `accreditor_notification_required` fields are null until submission, `effective_term_id` is null until registrar approval, and `notification_sent_at` is null until the registrar records a notification.

While a proposal sits in `DRAFT` or `RETURNED`, its author may revise the proposed payload — the subject code, number, title, credit and workload hours, outcomes, justification, requisites, declared cohorts, requested term, and even the sponsoring department. That edit is OCC-guarded through `expected_proposal_version` as described in §2.6, and is rejected with `ERR_INVALID_STATE` once the proposal has left those two states.

### 3.4. Submission: The Gate into Committee Review

Submission moves a proposal from `DRAFT` — or, on resubmission, from `RETURNED` — into `DEPT_REVIEW`, and every check below re-runs on every resubmission. Only the author may submit: a caller whose `X-User-ID` does not equal the stored `proposer_id` is rejected with `ERR_NOT_RESOURCE_OWNER`.

The window check comes first among the business rules: the term named by `requested_effective_term_id` must be in `OPEN_FOR_PROPOSALS` and the logical clock must be strictly before that term's `proposal_freeze_at`, otherwise the submission is rejected with `ERR_PROPOSAL_WINDOW_CLOSED`. Type-specific completeness is enforced as body validation: a `NEW_COURSE` submission must carry `proposed_subject_code`, `proposed_course_number`, `proposed_title`, `proposed_credit_hours`, `contact_hours_per_week`, and `out_of_class_hours_per_week`; a `COURSE_CHANGE` must carry `target_course_id` plus that same proposed set; a `DEACTIVATION` must carry `target_course_id` and a `declared_remaining_cohorts` of at least zero. For change and deactivation proposals the target course must be `ACTIVE`, else `ERR_INVALID_STATE`.

Two content rules guard academic quality. When `learning_outcomes` is present but an empty array on a new-course or change submission, the rejection is `ERR_LEARNING_OUTCOMES_REQUIRED` (an absent field is caught earlier as `ERR_VALIDATION`). And the **credit-hour workload check** verifies that the proposed credits are consistent with the stated workload: the weekly contact hours plus the weekly out-of-class hours are multiplied by the 15 weeks of a term and divided by the 45 Carnegie hours per credit, the result rounded half-up to one decimal place, and the submission passes only if the absolute difference between `proposed_credit_hours` and that computed figure is no more than 0.5 — a tolerance that includes the boundary. A shortfall beyond tolerance is rejected with `ERR_CREDIT_HOUR_MISMATCH`.

For a new course, the proposed combination of subject code and course number must be free. The combination is considered held when any course in `ACTIVE` or `DEACTIVATING` status already carries it, or when another in-flight proposal — one in `DEPT_REVIEW`, `COMMITTEE_REVIEW`, `SENATE_REVIEW`, `REGISTRAR_REVIEW`, or `APPROVED` — holds it; a conflict is rejected with `ERR_COURSE_NUMBER_HELD`.

Each entry in `proposed_requisites` is screened: the named requisite course must exist and be `ACTIVE` (a reference to a non-active course is rejected with `ERR_REQUISITE_TARGET_INACTIVE`), and no entry may name the proposal's own target course as its requisite (rejected with `ERR_SELF_REQUISITE`).

When submission succeeds, several things happen atomically. One **RequisiteLink** is created per `proposed_requisites` entry, each in `PROPOSED` status, in payload order (link `created_at` ascending preserves that order), and each link records the creating `proposal_id`. The proposal's provisional substantive-change score is computed and stored along with the notification flag (§3.6). For a new course, a hold is placed on the proposed subject-code and course-number pair. A `DecisionRecord` with action `SUBMIT` is appended, capturing `from_status` `DRAFT` (or `RETURNED`) and `to_status` `DEPT_REVIEW`, and the proposal's `version` increments.

### 3.5. The Committee Gauntlet: Approvals, Returns, Rejections, Withdrawals

From `DEPT_REVIEW` onward, a proposal advances through a fixed approval chain, each stage gated to its own role class: `DepartmentChair` decides at `DEPT_REVIEW`, `CurriculumCommittee` at `COMMITTEE_REVIEW`, `FacultySenate` at `SENATE_REVIEW`, and `Registrar` at `REGISTRAR_REVIEW`. A role listed on the decisions endpoint but mismatched to the proposal's current stage is rejected with `ERR_FORBIDDEN`.

Every decision call names an `action` and may carry a free-text `rationale`; the decisions endpoint accepts exactly `APPROVE`, `RETURN`, `REJECT`, `NOTIFY`, and `REASSIGN_TERM`, and any other action string is rejected with `ERR_VALIDATION`. Approval, return, and reject at the department stage require an additional ownership check: the acting chair's `X-User-ID` must equal the proposal's `proposer_department_id`, otherwise `ERR_NOT_RESOURCE_OWNER`. Approval moves the proposal one stage forward — `DEPT_REVIEW → COMMITTEE_REVIEW`, `COMMITTEE_REVIEW → SENATE_REVIEW`, `SENATE_REVIEW → REGISTRAR_REVIEW` — appending a `DecisionRecord` with action `APPROVE` and the appropriate from/to statuses and incrementing `version` at each hop.

**Segregation of duties** applies to every approve, return, and reject decision at every stage: the acting user's `X-User-ID` must not equal the proposal's `proposer_id` under raw string equality, and a violation is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. A proposer who happens to chair their own department still cannot approve their own proposal.

Return and reject are the committee's corrective instruments, available at each of the four review stages under the same stage-role and segregation rules. A return sends the proposal to `RETURNED` — from `DEPT_REVIEW`, from `COMMITTEE_REVIEW`, from `SENATE_REVIEW`, or from `REGISTRAR_REVIEW` — while a reject terminates it in `REJECTED`. Both actions strip the proposal's in-flight scaffolding: every requisite link the proposal created that is still `PROPOSED` becomes `REMOVED`, and for a new-course proposal the held subject-code/number pair is released. A returned proposal is not dead; its author may edit it and resubmit, at which point the full submission battery runs again and fresh links are created — the links removed at return stay removed.

The author may also withdraw at any point before a terminal state. Withdrawal from `DRAFT` simply appends the `WITHDRAW` record. Withdrawal from `RETURNED` releases the number hold — which in practice is a no-op, since nothing is held while `RETURNED`. Withdrawal from any review stage removes the proposal's `PROPOSED` links and releases the number hold. Withdrawal from `APPROVED` releases the number hold and drops the effective term's `scheduled_proposal_count` by one, but leaves the proposal's `PROPOSED` links in place. Every withdrawal requires authorship (else `ERR_NOT_RESOURCE_OWNER`), lands the proposal in the terminal `WITHDRAWN` state, and increments `version`.

### 3.6. Scoring Substantive Change and Notifying the Accreditor

The **substantive-change score** is an integer from 0 to 100 that estimates how materially a proposal alters the curriculum, and it drives the accreditor-notification obligation. It is computed twice under two variants, and the same proposal can legitimately score lower at the first computation and cross the notification threshold only at the second.

Both variants begin from a base determined by `proposal_type`: 20 for `NEW_COURSE`, 10 for `COURSE_CHANGE`, and 30 for `DEACTIVATION`. A change proposal then adds 25 points when its credit shift is large — that is, when the absolute difference between `proposed_credit_hours` and the target course's current `credit_hours`, divided by the target's current `credit_hours`, reaches at least a 0.25 ratio (a target whose current `credit_hours` is zero never triggers this factor). Both variants then add the prerequisite factor: 10 points per `proposed_requisites` entry of type `PREREQUISITE` for which no already-`ACTIVE` requisite link connects the target course to that same requisite course, with the total contribution capped at 20 points. This prerequisite factor is payload-known, so it is counted identically in both variants.

The provisional variant — computed at submission — stops there. The final variant, recomputed as the proposal moves `SENATE_REVIEW → REGISTRAR_REVIEW` and overwriting both stored fields, adds two more factors that only post-submission state can determine: 15 points when any cross-listing in `PENDING`, `HOME_APPROVED`, `PARTNER_APPROVED`, or `ACTIVE` status touches the target course on either side, and 20 points when the proposal is a `DEACTIVATION` whose `declared_remaining_cohorts` exceeds zero.

Whenever the stored score reaches at least the notification threshold of 50, `accreditor_notification_required` is set to true; below 50 it is false. A proposal flagged as requiring notification cannot complete registrar approval until the notification has actually been recorded: the registrar's approval is rejected with `ERR_ACCREDITOR_NOTIFICATION_PENDING` while `notification_sent_at` remains null. Recording the notification is a registrar self-loop on `REGISTRAR_REVIEW` — a decision with action `NOTIFY` — valid only while the flag is true and no notification has yet been sent; a repeated notification after one has been sent is rejected with `ERR_INVALID_STATE`. A successful notification stamps `notification_sent_at` with the current logical time, appends a `DecisionRecord` whose `from_status` and `to_status` are both `REGISTRAR_REVIEW`, and increments `version`.

### 3.7. Registrar Approval, Term Assignment, and Activation

The registrar's approval is the proposal's final gate, and it carries one extra payload field: the `effective_term_id` naming the term the change will take effect in. A missing or unresolvable term reference is a body-validation failure. Two business preconditions then apply, in order: the notification obligation of §3.6 must be satisfied, and for a `DEACTIVATION` proposal whose `declared_remaining_cohorts` exceeds zero, a teach-out plan serving this proposal must already exist in `COMMITTED`, `IN_PROGRESS`, or `COMPLETE` status — otherwise the approval is rejected with `ERR_TEACH_OUT_NOT_COMMITTED`. On success the proposal's `effective_term_id` is set, the chosen term's `scheduled_proposal_count` increments by one, a `DecisionRecord` is appended with the action `APPROVE` and the assigned term captured in its denormalized `recorded_term_id`, and the proposal lands in `APPROVED`.

While `APPROVED`, the registrar may reassign the effective term by supplying a different `effective_term_id`; supplying the term already assigned, or a term that does not exist, is `ERR_VALIDATION`. Reassignment decrements the old term's `scheduled_proposal_count` by one, increments the new term's by one, re-points the proposal, appends the corresponding decision record with the new term in `recorded_term_id`, and increments `version`.

**Activation** — the transition from `APPROVED` to `EFFECTIVE` — is where the proposal's payload becomes catalog reality. Activation requires the assigned effective term to be locked, meaning its status is `PROPOSAL_FROZEN` or `CATALOG_FROZEN`; activating against an unlocked term is rejected with `ERR_TERM_NOT_LOCKED`. For a new course, the proposed subject-code/number pair is re-checked for uniqueness at this moment — the hold taken at submission does not exempt the activation-time check — and a conflict surfaces as `ERR_COURSE_NUMBER_HELD`.

The effects fan out by proposal type. A `NEW_COURSE` activation materializes a course in `ACTIVE` status, built from the proposed payload, with its `introduced_in_term_id` set to the effective term and its `owning_department_id` set to the proposal's `proposer_department_id`, and the proposal's pending links are re-pointed so their `course_id` references the newly created course. A `COURSE_CHANGE` activation overwrites the target course's `title`, `credit_hours`, `contact_hours_per_week`, `out_of_class_hours_per_week`, and `learning_outcomes` from the proposed payload, incrementing the target course's `version`. In both cases the proposal's `PROPOSED` links are then flipped to `ACTIVE` one at a time in link-creation order, and before each flip the **prerequisite cycle check** runs: the active prerequisite graph is the set of links with status `ACTIVE` and type `PREREQUISITE`, plus any links of this same proposal already activated earlier in the batch; the candidate link closes a cycle if its course end is reachable from its requisite end following graph edges from a course to its requisite. `COREQUISITE` links never participate — neither as candidates nor as traversal edges. If any candidate would close a cycle, the entire activation aborts with `ERR_REQUISITE_CYCLE`. Each link that activates recomputes the `prerequisite_summary` of the course carrying the requirement and increments that course's `version`. (At activation the link's `requisite_course_id` is never null — requisite courses are existing active courses by submit-time validation — and a null `course_id`, which occurs only for a new-course proposal's links, resolves to the just-created course before the check.)

A `DEACTIVATION` activation instead moves the target course `ACTIVE → DEACTIVATING` and fires the widest cascade in the system. The course's committed teach-out plan moves `COMMITTED → IN_PROGRESS`. Every active requisite link that names the deactivated course as its requisite becomes `REMOVED`, and each such removal recomputes `prerequisite_summary` and increments `version` on the dependent course at the link's other end. Every active link the deactivated course itself carries as its `course_id` likewise becomes `REMOVED`. And every catalog entry for the deactivated course still in `STAGED` status becomes `EXCLUDED`. The deactivation activation never stages a new catalog entry.

For new-course and change activations, one **CatalogEntry** is staged in `STAGED` status — snapshotting the course's `subject_code`, `course_number`, `title`, and `credit_hours` at that moment, and recording the originating `proposal_id` — into the edition selected by matching the effective term's `academic_year` against editions still in `DRAFT` status (at most one such edition can exist, per the edition-uniqueness rules of §3.10). If no matching draft edition exists, no entry is staged. Every activation appends the `ACTIVATE` decision record and increments the proposal's `version`, leaving the proposal in the terminal `EFFECTIVE` state.

### 3.8. Deactivation and the Teach-Out Plan

A deactivation with students still in the pipeline owes them a **TeachOutPlan**, created by the proposing faculty member against their own `DEACTIVATION` proposal in a one-to-one relationship. The plan may be created while the proposal is in any status; attempting one against a non-`DEACTIVATION` proposal is rejected with `ERR_VALIDATION`, and attempting a second plan for the same proposal is rejected with `ERR_INVALID_STATE`. The plan records the owning `proposal_id` and the denormalized `course_id`, and its author supplies `enrolled_cohort_count`, a `cohort_sizes` array with one enrollment size per cohort, and the `last_enrolled_term_id` naming the last term in which any cohort is enrolled. Body validation requires the cohort-count arithmetic to agree with the proposal: `enrolled_cohort_count` must equal the proposal's `declared_remaining_cohorts`, the length of `cohort_sizes` must equal `enrolled_cohort_count`, and every size must be at least one.

At creation the plan computes an **enrollment-driven** estimate of when teach-out finishes and stores it as `provisional_completion_sequence`: the `sequence_index` of the last-enrolled term plus the cohort count divided by the per-term drain rate of 2 cohorts, the division rounded up to a whole number. Three cohorts whose last enrollment sits at sequence index 3 therefore estimate completion at index 5.

The plan begins in `DRAFT` and is committed by the chair of the sponsoring department — a caller whose `X-User-ID` does not equal the proposal's `proposer_department_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. Committing recomputes completion under the **catalog-driven** variant and stores it as `committed_completion_sequence`: the `sequence_index` of the proposal's requested effective term plus the catalog policy of 4 teach-out terms. For the same plan with a requested effective term at sequence index 4, the committed value is 8 — a deliberately different answer from the same inputs, because it reflects catalog policy rather than enrollment reality. Committing also computes the teach-out's sectioning cost and stores it as `resource_cost_cents`: for each cohort in `cohort_sizes` — all of them, with no status filtering, since every cohort runs to completion — the cohort size is divided by the section capacity of 15 students and rounded up to a whole section count; the sections are then summed across cohorts and multiplied by the per-section cost of 400000 cents. The rounding order is pinned and non-interchangeable: rounding per cohort before summing is the specified behavior, so cohorts of 16 and 9 students require 2 plus 1, that is 3 sections, costing 1200000 cents — whereas summing first would wrongly yield 2 sections. Both computed fields are null until commit; the commit increments the plan's `version`.

When the owning deactivation proposal activates, the committed plan moves `COMMITTED → IN_PROGRESS` automatically. Finally, the registrar completes an in-progress plan; completion from any other state is rejected with `ERR_INVALID_STATE`. Completing the plan cascades the linked course from `DEACTIVATING` to `INACTIVE`, which in turn excludes the course's `INCLUDED` catalog entries in editions still in `DRAFT` or `FROZEN` status, recomputing `included_entry_count` on each affected edition. The completion increments the plan's `version`, and the course's transition increments the course's `version`.

### 3.9. Cross-Listing Agreements Between Departments

A **CrossListing** lets two departments teach the same course content under both subject codes. The requesting — home — department's chair creates the agreement by naming `home_course_id` and `partner_course_id`; the caller must chair the home course's owning department, else `ERR_NOT_RESOURCE_OWNER`. The two courses must differ — a self-pairing is rejected as `ERR_VALIDATION` — must both be `ACTIVE` — otherwise `ERR_INVALID_STATE` — and must belong to different departments, a same-department pairing likewise being `ERR_VALIDATION`. The system denormalizes `home_department_id` and `partner_department_id` from the courses' owning departments at creation. Only one non-terminal listing may exist per unordered course pair: if a listing for the same pair already exists in `PENDING`, `HOME_APPROVED`, `PARTNER_APPROVED`, or `ACTIVE` status, creation is rejected with `ERR_CROSS_LISTING_EXISTS`.

Approval is a two-sided handshake with no fixed order. From `PENDING`, the home chair's approval — identified by `X-User-ID` matching `home_department_id` — moves the listing to `HOME_APPROVED` and stamps `home_approved_by`; the partner chair's approval moves it to `PARTNER_APPROVED` and stamps `partner_approved_by`. Whichever side approved first, the second side's approval moves the listing to `ACTIVE`, provided both courses are still `ACTIVE` — approving a listing whose courses are no longer both active is rejected with `ERR_INVALID_STATE`. A side may also walk back its own approval: rescinding from `HOME_APPROVED` (by the home chair) or from `PARTNER_APPROVED` (by the partner chair) returns the listing to `PENDING` and clears that side's approval stamp to null. Either side's chair may reject the listing from `PENDING`, `HOME_APPROVED`, or `PARTNER_APPROVED`, optionally attaching a `rationale` (accepted but not persisted anywhere); rejection lands the listing in the terminal `REJECTED` state. Every side determination is derived from the caller's `X-User-ID` against the two denormalized department ids — a caller matching neither side is rejected with `ERR_NOT_RESOURCE_OWNER` — and every state change increments the listing's `version`.

### 3.10. Catalog Editions: Freeze, Publish, Archive

The **CatalogEdition** is the published snapshot of an academic year. The registrar creates one in `DRAFT` status with an `edition_label` such as `2026-2027 Catalog`, an `academic_year`, an `included_entry_count` initialized to 0, and the closed interval `year_start_date` to `year_end_date` covering the year — both ends inclusive, so `year_end_date` must be at or after `year_start_date`. Editions obey three window rules, all enforced with `ERR_EDITION_WINDOW_CONFLICT`: their closed intervals may not overlap (because both ends are inclusive, even a single shared day is a conflict); whenever any non-`ARCHIVED` edition exists, the new edition's `year_start_date` must be exactly the day after the latest non-`ARCHIVED` edition's `year_end_date`, so the published record is gap-free; and `academic_year` must be unique among editions not in `ARCHIVED` status.

Freezing an edition moves it `DRAFT → FROZEN` and is permitted only when every term sharing the edition's `academic_year` has reached `CATALOG_FROZEN`; otherwise the freeze is rejected with `ERR_TERM_NOT_LOCKED`. The freeze runs the snapshot sweep over the edition's entries in entry-creation order: each `STAGED` entry whose course is `ACTIVE` or `DEACTIVATING` becomes `INCLUDED`, while an entry whose course is `INACTIVE` becomes `EXCLUDED`; entries in other statuses are untouched. The sweep then sets the edition's `included_entry_count` to the number of its `INCLUDED` entries, and increments the edition's `version`.

Publishing moves the edition `FROZEN → PUBLISHED` and cascades in two hops. First, every `INCLUDED` entry in the edition becomes `PUBLISHED`; second, each newly published entry stamps its course's `last_published_edition_id` with this edition's `id` and increments that course's `version`. Publication simultaneously retires the old record in an archive arm: the previously `PUBLISHED` edition, if any, becomes `ARCHIVED`, and every entry in that archived edition still in `PUBLISHED` status becomes `ARCHIVED`. The newly published edition's `version` increments.

A catalog entry's own lifecycle is therefore `STAGED → INCLUDED → PUBLISHED → ARCHIVED`, with `EXCLUDED` as a terminal branch reachable from `STAGED` (a deactivation cascade, or a freeze sweep finding its course inactive) and from `INCLUDED` (its course reaching `INACTIVE` while its edition is still in `DRAFT` or `FROZEN`, which recomputes the edition's `included_entry_count`). Each entry mutation increments the entry's `version`.

### 3.11. The Decision Log and Browsing Surfaces

Every action taken on a proposal — submit, approve, return, reject, withdraw, notify, reassign-term, and activate — is preserved as an immutable `DecisionRecord`. Each record carries the `proposal_id` it belongs to, the `action` (one of `SUBMIT`, `APPROVE`, `RETURN`, `REJECT`, `WITHDRAW`, `NOTIFY`, `REASSIGN_TERM`, `ACTIVATE`), the proposal's `from_status` and `to_status` around the action (identical for the `NOTIFY` and `REASSIGN_TERM` self-loops), the acting `actor_role` and `actor_id` copied from the request headers, the optional `rationale`, and the `recorded_term_id` holding a denormalized audit copy of the term supplied with approve and reassign actions — null for all other actions and deliberately not a live foreign key. A proposal's decision log is retrievable in chronological order.

The read surface mirrors the write surface. Proposals are listed with optional filters on `target_course_id`, `requested_effective_term_id`, `effective_term_id`, `proposer_department_id`, `proposer_id`, and `status`. Courses are listed with filters on `owning_department_id`, `introduced_in_term_id`, `last_published_edition_id`, `status`, `subject_code`, and `course_number`. The links touching a course on either side — as the course carrying the requirement or as the requisite — are listed together with optional filters on `requisite_type` and `status`, while a proposal's own created links are listed separately with an optional `status` filter. A course's cross-listings, in either the home or partner seat, are listed with an optional `status` filter. Teach-out plans are listed with filters on `proposal_id`, `course_id`, `last_enrolled_term_id`, and `status`. Catalog entries are listed with filters on `edition_id`, `course_id`, `proposal_id`, and `status`. All of these lists follow the pagination and sorting contract of §2.3, and all read endpoints are open to every authenticated role.

## 4. Endpoint Definitions

Operations that create a new resource — a department, term, course, proposal, teach-out plan, cross-listing, or catalog edition — return `201 Created`. Operations that modify an existing resource, including all state-transition and decision actions, return `200 OK`. The clock-setting capability returns `200 OK`. Action endpoints documented with no request-body fields — submit, withdraw, activate, teach-out commit and complete, cross-listing approve and rescind, and edition freeze and publish — reject a body carrying any field with `ERR_VALIDATION`, while the two term-freeze actions ignore the request body entirely.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/curriculum/_clock/set_current_utc` | Set the server's logical clock | Registrar |
| POST | `/curriculum/departments` | Register a department | Registrar |
| POST | `/curriculum/terms` | Create a term | Registrar |
| GET | `/curriculum/terms/{id}` | Fetch one term | Any |
| PATCH | `/curriculum/terms/{id}` | Edit term dates (OCC-guarded) | Registrar |
| POST | `/curriculum/terms/{id}/freeze-proposals` | Freeze a term's proposal window | Registrar |
| POST | `/curriculum/terms/{id}/freeze-catalog` | Freeze a term's catalog | Registrar |
| POST | `/curriculum/courses` | Import a course directly into ACTIVE | Registrar |
| GET | `/curriculum/courses` | List courses with filters | Any |
| GET | `/curriculum/courses/{id}` | Fetch one course | Any |
| GET | `/curriculum/courses/{id}/requisites` | List requisite links touching a course | Any |
| GET | `/curriculum/courses/{id}/cross-listings` | List cross-listings for a course | Any |
| POST | `/curriculum/proposals` | Create a DRAFT proposal | FacultyProposer |
| GET | `/curriculum/proposals` | List proposals with filters | Any |
| GET | `/curriculum/proposals/{id}` | Fetch one proposal | Any |
| PUT | `/curriculum/proposals/{id}` | Edit a DRAFT/RETURNED proposal (OCC-guarded) | FacultyProposer |
| POST | `/curriculum/proposals/{id}/submit` | Submit a proposal into DEPT_REVIEW | FacultyProposer |
| POST | `/curriculum/proposals/{id}/withdraw` | Withdraw a proposal | FacultyProposer |
| POST | `/curriculum/proposals/{id}/decisions` | Record a committee/registrar decision | DepartmentChair, CurriculumCommittee, FacultySenate, Registrar |
| GET | `/curriculum/proposals/{id}/decisions` | List a proposal's decision log | Any |
| GET | `/curriculum/proposals/{id}/requisites` | List links created by a proposal | Any |
| POST | `/curriculum/proposals/{id}/activate` | Activate an APPROVED proposal | Registrar |
| POST | `/curriculum/proposals/{id}/teach-out-plan` | Create the teach-out plan for a DEACTIVATION proposal | FacultyProposer |
| GET | `/curriculum/teach-out-plans` | List teach-out plans with filters | Any |
| GET | `/curriculum/teach-out-plans/{id}` | Fetch one teach-out plan | Any |
| POST | `/curriculum/teach-out-plans/{id}/commit` | Commit a teach-out plan | DepartmentChair |
| POST | `/curriculum/teach-out-plans/{id}/complete` | Complete a teach-out plan | Registrar |
| POST | `/curriculum/cross-listings` | Request a cross-listing | DepartmentChair |
| POST | `/curriculum/cross-listings/{id}/approve` | Approve the acting chair's side | DepartmentChair |
| POST | `/curriculum/cross-listings/{id}/reject` | Reject a cross-listing | DepartmentChair |
| POST | `/curriculum/cross-listings/{id}/rescind` | Rescind an own-side approval | DepartmentChair |
| POST | `/curriculum/editions` | Create a DRAFT catalog edition | Registrar |
| POST | `/curriculum/editions/{id}/freeze` | Freeze an edition and run the snapshot sweep | Registrar |
| POST | `/curriculum/editions/{id}/publish` | Publish an edition and archive its predecessor | Registrar |
| GET | `/curriculum/catalog-entries` | List catalog entries with filters | Any |
| GET | `/curriculum/catalog-entries/{id}` | Fetch one catalog entry | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 |
| `ERR_ACCREDITOR_NOTIFICATION_PENDING` | 409 |
| `ERR_TEACH_OUT_NOT_COMMITTED` | 409 |
| `ERR_PROPOSAL_WINDOW_CLOSED` | 409 |
| `ERR_FREEZE_DATE_NOT_REACHED` | 409 |
| `ERR_TERM_NOT_LOCKED` | 409 |
| `ERR_REQUISITE_TARGET_INACTIVE` | 422 |
| `ERR_REQUISITE_CYCLE` | 422 |
| `ERR_SELF_REQUISITE` | 422 |
| `ERR_COURSE_NUMBER_HELD` | 409 |
| `ERR_TERM_DATE_OVERLAP` | 409 |
| `ERR_TERM_SEQUENCE_CONFLICT` | 409 |
| `ERR_EDITION_WINDOW_CONFLICT` | 409 |
| `ERR_CROSS_LISTING_EXISTS` | 409 |
| `ERR_LEARNING_OUTCOMES_REQUIRED` | 422 |
| `ERR_CREDIT_HOUR_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INTERNAL` | 500 |

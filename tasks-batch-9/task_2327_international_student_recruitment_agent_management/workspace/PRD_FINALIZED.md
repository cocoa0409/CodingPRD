# International Agent Management API — Product Requirements Document

## 1. Introduction

A university's international recruitment office does not recruit alone. It contracts commissioned agencies across dozens of countries, and each of those relationships carries a regulatory tail: beneficial ownership must be disclosed and screened before a single student is touched, the agent relationship must be disclosed to the prospective student and acknowledged by them, per-enrollment incentive compensation is lawful for internationally recruited students and prohibited for domestically recruited ones, and commissions earned on a student who never reaches the enrollment census must be recovered rather than quietly written off. Today this work is spread across contract binders, spreadsheets of milestone payments, and an inbox of fraud tips. Nothing reconciles, and the office cannot answer the two questions its auditors ask most often: *what did we pay this agency, and what did we know about them when we paid it?*

This document specifies the International Agent Management API, the system of record that replaces that patchwork. It governs the full arc of an agency relationship — due-diligence vetting, contract negotiation and countersignature, territory and rate-card assignment, disclosure to the student, document verification and fraud detection, milestone commission accrual with clawback on withdrawal, integrity incident adjudication, performance scorecards, and finally termination with orderly transition of in-flight student files to a successor agency or to in-house custody.

Two design commitments shape everything that follows. First, an agency's *due-diligence* standing and its *integrity* standing are separate dimensions that move independently: a fully cleared agency can be on probation, and an agency under re-screening can be in good standing. Second, money is a conserved quantity. Every cent of commission is an addressable ledger row with a state, every reversal is a compensating row that points at the row it reverses, and the agency-level balances are always recomputed from those rows rather than incremented in place. All date-sensitive and expiry-sensitive behaviour is driven by a server-controlled logical clock so that the entire lifecycle — including multi-year contract terms and 365-day risk decay windows — is exercisable deterministically.

## 2. Global Specifications & System-Wide Principles

The whole API is mounted under the `/recruitment` prefix, with one exception noted in §2.5. This section defines the contracts that hold for every endpoint underneath it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role is not permitted for the endpoint — or not permitted for the particular action variant being requested — the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are:

- **`RecruitmentOfficer`** — international recruitment office staff. Onboards agencies, creates programs, drafts contracts, assigns territories and rate cards, issues disclosures, decides admissions, and runs performance scorecards.
- **`ComplianceOfficer`** — the due-diligence and integrity authority. Clears or rejects agencies, countersigns contracts, requests amendments, suspends and reinstates contracts, adjudicates documents and integrity incidents, moves compliance posture, and terminates contracts.
- **`AgencyOwner`** — the recruitment agency acting on its own file. Signs its contract, creates student applications, uploads supporting documents, and submits applications.
- **`Registrar`** — the registrar office, which records enrollment facts: milestone registrations and withdrawals.
- **`FinanceOfficer`** — the commission disbursement authority, which approves, pays and voids ledger entries.
- **`Applicant`** — the prospective student. Holds no read access whatsoever; the acknowledgement token issued with the agent-relationship disclosure is this role's only capability.

Identity semantics differ by role, and they matter because ownership checks depend on them. When `X-User-Role` is `AgencyOwner`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any resource that references an `Agency` compare the resource's foreign-key field to `X-User-ID`. Concretely, the comparison target is the `Agency` reachable from the target resource: the agency's own `id` for agency-scoped endpoints, `agency_id` on an `AgentContract`, `agency_id` on a `StudentApplication`, and — for a document — the `agency_id` of the `StudentApplication` the document hangs from. A mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403).

When `X-User-Role` is `RecruitmentOfficer`, `ComplianceOfficer`, `Registrar`, `FinanceOfficer` or `Applicant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `created_by_user_id` and `compliance_approved_by_user_id` on a contract, `verified_by_user_id` on a document, `resolved_by_user_id` on an incident, and `approved_by_user_id` and `paid_by_user_id` on a ledger entry — but never compares it to any entity's `id`. The one signature field written from an `AgencyOwner`'s identity, `agency_signed_by_user_id`, therefore holds an `Agency` `id`.

One endpoint splits authorization by action rather than by path: issuing an agent-relationship disclosure requires `RecruitmentOfficer` or `AgencyOwner`, while acknowledging it requires `Applicant`. A role that is permitted on the endpoint but not on the requested action still receives `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` is the number of items skipped before the window begins; it defaults to 0 and may be no smaller than 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a structural failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the size of the full filtered result set, not the size of the returned page, and `has_more` is true exactly when items remain beyond the current window.

### 2.4. Resource Identity and Mutation Bookkeeping

All resources carry an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource.

`FileTransition` is the sole exception. A file-transition record is an immutable audit stamp written by a cascade and never edited afterwards, so it exposes only `id` and `created_at`: it has neither an `updated_at` field nor a `version` field.

Bookkeeping applies to *derived* mutations exactly as it applies to client-driven ones. When a document verification outcome recomputes an agency's risk scores, when a milestone accrual recomputes an application's net commission, or when a cascade moves a territory assignment out of `ACTIVE`, each touched resource independently refreshes its own `updated_at` and increments its own `version`. A single client request therefore routinely advances the `version` of several resources, and clients must expect that.

### 2.5. The Logical Clock and the Epoch Sweep

Every date, expiry, decay and window rule in this specification reads a server-controlled **logical clock** rather than wall-clock time. The clock starts at the fixed default `2026-08-01T00:00:00Z` and never falls back to real time. It is moved by an operator-driven capability, mounted outside the `/recruitment` prefix at `/_clock/set_current_utc`, which accepts a single `to_iso8601` instant and is available to `RecruitmentOfficer` and `ComplianceOfficer`.

Setting the clock is not a passive assignment; it runs an **epoch sweep** that brings every time-driven state machine up to date, in one pass:

- Every `AgentContract` in `ACTIVE` or `SUSPENDED` whose `term_end_date` is now strictly earlier than the current logical-clock date moves to `EXPIRED`. When such a contract was `ACTIVE`, each of its territory assignments still in `ACTIVE` also moves to `EXPIRED` with `released_on` set to the current logical-clock date.
- Every `TerritoryAssignment` still in `ACTIVE` whose `end_date` is on or before the current logical-clock date moves to `EXPIRED`, with `released_on` set to the current logical-clock date.
- Every `TrainingCertification` still in `VALID` whose `expires_on` is on or before the current logical-clock date moves to `EXPIRED`.
- Every `Agency` with at least one `CONFIRMED` integrity incident has both of its risk figures recomputed against the new incident ages, which may escalate its compliance posture and cascade onward exactly as an in-band recompute would.

The response reports the new clock instant as `current_utc`, rendered like every other instant in this API as an ISO 8601 UTC instant with three fractional digits regardless of how the request spelled `to_iso8601`, together with four counters describing what the sweep touched: `expired_contract_count`, `expired_assignment_count`, `expired_certification_count` and `risk_recomputed_agency_count`.

### 2.6. Parallel State Dimensions and Cascade Propagation

Two entities in this domain carry two independent state dimensions each, and treating either pair as a single lifecycle produces wrong behaviour.

An `Agency` has a `vetting_state` — the due-diligence dimension, valued `DRAFT`, `SCREENING`, `INFO_REQUESTED`, `CLEARED` or `REJECTED`, beginning at `DRAFT`, with `REJECTED` terminal — and a `compliance_posture` — the integrity dimension, valued `GOOD_STANDING`, `WATCH`, `PROBATION`, `SUSPENDED` or `DEBARRED`, beginning at `GOOD_STANDING`, with `DEBARRED` terminal. The two run independently: every combination of the two dimensions is reachable except that neither terminal can be left. Automatic movement along the integrity dimension is driven by risk-score bands and always escalates; de-escalation is always a manual compliance action.

A `StudentApplication` likewise has a `status` — the admission and enrollment milestone dimension — and a `disclosure_state` — the agent-relationship disclosure dimension. These also evolve independently; submission is the only transition that reads both dimensions at once.

Cascades in this system are multi-hop and must be followed to their end. Confirming document fraud, for example, files an incident, recomputes agency risk, may escalate posture, and a posture escalation may suspend contracts, and each suspended contract releases its active territories and invalidates disclosures on draft applications. Every hop mutates its own resource with the bookkeeping described in §2.4. Where this document says a cascade "runs", it means the whole chain runs inside the originating request, before the response is produced.

### 2.7. Resolution Order for Path and Body Identifiers

Path identifiers are resolved strictly left to right, and the first identifier that names nothing produces the 404 for the whole request. A request naming an assignment under a contract that does not exist therefore fails with `ERR_CONTRACT_NOT_FOUND` and never with `ERR_ASSIGNMENT_NOT_FOUND`. The nine resolution failures are `ERR_AGENCY_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND` and `ERR_TRANSITION_NOT_FOUND`, all HTTP 404. A territory assignment identifier resolves only *under* the contract named earlier in the path; an assignment that exists but belongs to a different contract is `ERR_ASSIGNMENT_NOT_FOUND`.

Foreign keys supplied in a request body are resolved after path identifiers and after structural validation, and they raise the same 404 family. This applies to `agency_id`, `program_id`, `application_id`, `document_id` and `successor_agency_id` wherever they appear as body fields — that is, on agency-scoped contract drafting, application creation, integrity incident filing, and contract termination.

Because every entity in this domain is addressed by its own top-level collection, parents are named by foreign-key fields in request bodies rather than by deep URL nesting. Ledger entries, file transitions and documents are all reachable directly by their own identifiers.

### 2.8. Monetary Units, Basis Points and Rounding Discipline

Money is always an integer number of cents. There is no decimal currency type anywhere in this API, and no cent value is ever stored or returned with a fractional part.

Commission rates are expressed in **basis points**: one basis point is one ten-thousandth of the base, so a rate is converted to money by multiplying the base by the basis-point figure and dividing by 10,000. Rate fields are integers.

Three rounding rules apply, and each is pinned:

- **Commission amounts.** A milestone accrual is computed from the tuition base and the effective basis points, rounded half up to whole cents, and only then clamped against the schedule's per-milestone cent ceiling. The cap is applied *after* rounding, never before.
- **Risk scores.** Both risk figures are rounded half up to two decimal places, with the rounding applied once to the completed sum, and the rounded result is then clamped at a maximum of 100.00.
- **Scorecard rates.** Each component rate on a performance scorecard is rounded half up to four decimal places first, and the weighted composite is then computed from those already-rounded rates and rounded half up to four decimal places again. Weighting the unrounded rates and rounding once is explicitly *not* the rule and yields different numbers.

Clawback proration follows a related two-step discipline described with the withdrawal workflow: the proration percentage is rounded before it is applied, each entry's reversal is rounded to whole cents individually, and any total is the sum of those already-rounded per-entry values rather than a single rounding of summed raw products.

### 2.9. Version Pinning and Optimistic Concurrency Control

This system uses two distinct version mechanisms, and they should not be confused.

**Version pinning** freezes a snapshot of a moving parent onto a child at a decision moment: the disclosure template version pinned on an application when the disclosure is issued, the contract and rate card pinned on an application when it is submitted, and the performance tier pinned onto each ledger entry at its milestone event date. Pinning is described where each workflow needs it.

**Optimistic concurrency control** guards two write endpoints against a client acting on a parent it has not re-read. In both cases the version field is a required input, not an optional one, and a mismatch is rejected before any side effect runs.

A `POST /recruitment/contracts/{id}/commission-schedules` request must carry `expected_contract_version` holding the client's last observed `version` of the target `AgentContract`. If that value does not equal the contract's current `version`, the append is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The protection is meaningful because a rate card legitimately tiles onto the trailing edge of the previously latest card: a writer holding a stale view of the contract would append after a card it never saw, so the check forces it to re-read the tiling frontier first. Note also that a successful append itself increments the contract's `version` by one, so a client adding two cards in sequence must re-read between them.

A `POST /recruitment/applications/{id}/milestones` request must carry `expected_application_version` holding the client's last observed `version` of the target `StudentApplication`. If that value does not equal the application's current `version`, the registration is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). Milestone registration is an append onto a record that many other actors move — disclosure re-issue, document verification and clawback recomputation all advance the application's `version` — so the registrar must prove it is acting on the version against which it evaluated milestone ordering.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.10. Segregation of Duties

Two decisions in this system may not be taken twice by the same person, and the enforcement compares `X-User-ID` against a previously recorded identity.

A contract's countersignature is barred to its drafter: when a `ComplianceOfficer` approves a contract that is awaiting compliance review, the acting `X-User-ID` must differ from the contract's `created_by_user_id`. A commission payment is barred to its approver: when a `FinanceOfficer` pays an entry, the acting `X-User-ID` must differ from that entry's `approved_by_user_id`. Both failures return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.11. Validation Precedence

When several checks could fail on the same request, the outcome is determined by a fixed global precedence. Lower-numbered groups are evaluated first, and the first failing check produces the response; later checks are never reached and never mask an earlier one. The order is:

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`.
2. Role permitted for the endpoint and for the requested action variant — `ERR_UNAUTHORIZED`.
3. `AgencyOwner` scope: `X-User-ID` matches the `Agency` reachable from the target resource — `ERR_AGENCY_SCOPE_VIOLATION`.
4. Structural validity of the body and query string: required fields present, enum values in range, dates in ISO 8601 `YYYY-MM-DD` form, integers within their declared bounds, `limit` between 1 and 100, `offset` at least 0 — `ERR_INVALID_REQUEST`.
5. Path identifier resolution, left to right — the 404 family of §2.7.
6. Body foreign-key resolution — the same 404 family.
7. Optimistic concurrency checks — `ERR_STALE_CONTRACT_VERSION` or `ERR_STALE_APPLICATION_VERSION`.
8. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.
9. State-machine legality, in this internal order: vetting action legality (`ERR_INVALID_VETTING_STATE`); contract and posture action legality including the requirement that an application's pinned contract be `ACTIVE` where required (`ERR_INVALID_CONTRACT_STATE`, `ERR_INVALID_POSTURE_ACTION`); application status legality (`ERR_INVALID_APPLICATION_STATE`); document verification-state legality (`ERR_INVALID_DOCUMENT_STATE`); ledger entry and incident state legality (`ERR_INVALID_ENTRY_STATE`, `ERR_INVALID_INCIDENT_STATE`); milestone ordering (`ERR_MILESTONE_OUT_OF_ORDER`); disclosure-state legality (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); disclosure template staleness (`ERR_DISCLOSURE_VERSION_STALE`); acknowledgement token match (`ERR_DISCLOSURE_TOKEN_INVALID`).
10. Business-safety gates, in this internal order: vetting cleared (`ERR_AGENCY_NOT_CLEARED`); compliance posture (`ERR_AGENCY_POSTURE_BLOCKED`); training currency (`ERR_TRAINING_LAPSED`); verified identity document (`ERR_IDENTITY_DOCUMENT_UNVERIFIED`); fraud hold (`ERR_FRAUD_HOLD_ACTIVE`); incentive-compensation prohibition (`ERR_INCENTIVE_COMPENSATION_PROHIBITED`); due-diligence checklist completeness (`ERR_DUE_DILIGENCE_INCOMPLETE`); training score sufficiency (`ERR_TRAINING_SCORE_INSUFFICIENT`).
11. Referential business gates, in this internal order: territory coverage (`ERR_TERRITORY_NOT_COVERED`); rate-card effectiveness (`ERR_SCHEDULE_NOT_EFFECTIVE`); successor eligibility (`ERR_SUCCESSOR_NOT_ELIGIBLE`).
12. Temporal and geometric gates, in this internal order: territory exclusivity geometry (`ERR_TERRITORY_EXCLUSIVITY_CONFLICT`); non-exclusive capacity (`ERR_TERRITORY_CAPACITY_EXCEEDED`); rate-card overlap (`ERR_SCHEDULE_INTERVAL_CONFLICT`); rate-card gap (`ERR_SCHEDULE_GAP`); window coherence (`ERR_TERM_WINDOW_INVALID`); milestone and withdrawal dating (`ERR_MILESTONE_DATE_INVALID`); census date reached (`ERR_CENSUS_DATE_NOT_REACHED`); persistence date reached (`ERR_PERSISTENCE_DATE_NOT_REACHED`); future dates disallowed (`ERR_FUTURE_DATE_NOT_ALLOWED`).
13. Remaining structural business constraints, in this internal order: amendment limit (`ERR_AMENDMENT_LIMIT_REACHED`); uniqueness (`ERR_DUPLICATE_RESOURCE`); exclusivity permission (`ERR_EXCLUSIVITY_NOT_PERMITTED`).
14. Fiscal ceilings, in this internal order: annual commission cap (`ERR_COMMISSION_CAP_EXCEEDED`); unsettled clawback liability (`ERR_CLAWBACK_LIABILITY_UNSETTLED`).

The practical consequence worth internalising: an agency-scope violation is reported even when the body is malformed, a stale version is reported even when the requested transition is illegal, and a posture block surfaces before any territory or rate-card geometry is examined.

## 3. Business Logic & Workflows

### 3.1. Agency Onboarding, Due Diligence and Agent Training

A `RecruitmentOfficer` opens a relationship by registering the agency with its registered `legal_name` — between 1 and 200 characters and never blank — and its `home_country_code`, the ISO-3166 alpha-2 country of registration, given as exactly two uppercase letters. The four due-diligence checklist items may be supplied at registration or filled in later: `ownership_disclosed` and `sanctions_screen_passed` are booleans that both default to false, while `beneficial_owner_count` and `reference_check_count` are non-negative integers that both default to 0. A newly registered agency begins in `DRAFT` on the due-diligence dimension and `GOOD_STANDING` on the integrity dimension, with `rolling_risk_score` and `lifetime_risk_score` both at 0.00, `confirmed_incident_count`, `reviewed_document_count`, `confirmed_fraud_document_count`, `net_earned_commission_cents` and `clawback_liability_cents` all at 0, `current_tier` at `UNRATED`, and `last_posture_reason` unset.

Checklist fields remain editable while due diligence is in flight. A `RecruitmentOfficer`, or the agency itself acting as `AgencyOwner`, may revise `legal_name`, `ownership_disclosed`, `beneficial_owner_count`, `sanctions_screen_passed` and `reference_check_count`; `home_country_code` is fixed at registration. Editing bumps the agency's `version`.

The due-diligence dimension is driven by six named actions, each supplied as an `action` value alongside an optional `note`. `SUBMIT_FOR_SCREENING`, taken by a `RecruitmentOfficer`, moves `DRAFT → SCREENING`. A `ComplianceOfficer` may push `SCREENING → INFO_REQUESTED` with `REQUEST_INFO`, and the officer who gathers the missing material returns `INFO_REQUESTED → SCREENING` with `RESUBMIT`; this loop may repeat without limit. `CLEAR` moves `SCREENING → CLEARED`, `REJECT` moves `SCREENING → REJECTED`, and `RE_SCREEN` moves `CLEARED → SCREENING` for periodic re-diligence. Any action that is not defined from the agency's current `vetting_state` is rejected with `ERR_INVALID_VETTING_STATE`; each successful action increments the agency's `version`.

Clearing carries the substantive gate. Beyond requiring the agency to be in `SCREENING`, `CLEAR` demands that the checklist be complete: `ownership_disclosed` must be true, `sanctions_screen_passed` must be true, `beneficial_owner_count` must be at least 1, and `reference_check_count` must be at least 2. Any shortfall is `ERR_DUE_DILIGENCE_INCOMPLETE`. Clearing additionally requires that the agency's integrity standing not be `SUSPENDED` or `DEBARRED`.

`REJECT` is the destructive end of the dimension. Along with the state change, every one of that agency's contracts still in `DRAFT`, `PENDING_AGENCY_SIGNATURE` or `PENDING_COMPLIANCE_REVIEW` is driven to `TERMINATED` with `termination_reason_code` recorded as `NON_RENEWAL`. Contracts that had already reached `ACTIVE` or beyond are not touched by rejection.

Agent training is recorded against the agency as a certification. A `RecruitmentOfficer` or `ComplianceOfficer` records a completed module by supplying the `module_code` — one of `PROGRAM_ACCURACY`, `PROHIBITED_CLAIMS` or `VISA_INTEGRITY` — an assessment `score` between 0 and 100, and the `issued_on` date. A score below 80 is refused with `ERR_TRAINING_SCORE_INSUFFICIENT`, and an `issued_on` later than the current logical-clock date is refused with `ERR_FUTURE_DATE_NOT_ALLOWED`. An agency may hold at most one certification in `VALID` status per module; a second live record for the same module is `ERR_DUPLICATE_RESOURCE`.

Validity is derived, not supplied. `expires_on` is `issued_on` advanced by the module's validity period: one full year for `PROGRAM_ACCURACY`, half a year — 180 days — for `PROHIBITED_CLAIMS`, and one full year for `VISA_INTEGRITY`, where a full year is 365 days. A certification is lapsed the moment the current logical-clock date reaches `expires_on`, so the boundary day itself is already lapsed; the epoch sweep moves such a record from `VALID` to `EXPIRED`. A certification may instead be pulled to `REVOKED` with a `revoked_reason` when a prohibited-claim incident is confirmed, as described in §3.8. Certifications can be listed for an agency and filtered by `module_code` and by `status`.

### 3.2. Programs and the Contract Negotiation Cycle

Programs are the commission base. A `RecruitmentOfficer` creates one with a `code` that is unique across programs and between 2 and 32 characters, a display `name`, a `level` of either `UNDERGRADUATE` or `POSTGRADUATE`, the published `annual_tuition_cents` as a strictly positive integer, and three dates. `term_start_date` is when teaching begins. `census_date` is the enrollment census, which must be on or after `term_start_date`; a withdrawal strictly before it triggers full commission recovery. `persistence_check_date` is the earliest date student persistence may be confirmed and must be strictly after `census_date`. Two optional switches complete the record: `commission_eligible`, which defaults to true and when false suppresses ledger entries entirely for milestones on this program, and `max_commission_bps`, a program-level ceiling on effective basis points per milestone that defaults to 1000 and must lie between 0 and 5000. A duplicate `code` is `ERR_DUPLICATE_RESOURCE`; an incoherent date set — a census before term start, or a persistence check not strictly after the census — is `ERR_TERM_WINDOW_INVALID`.

A contract is drafted by a `RecruitmentOfficer` naming the `agency_id`, an office-assigned `contract_ref` that must be unique across contracts, an `exclusivity_model` of either `EXCLUSIVE_ALLOWED` or `NON_EXCLUSIVE_ONLY`, the inclusive `term_start_date` and `term_end_date` bounds of the contract term with the end strictly after the start, and an `annual_commission_cap_cents` ceiling that must be strictly positive. The new contract lands in `DRAFT` with `disclosure_template_version` at 1, `amendment_round` at 0, `created_by_user_id` set to the drafting officer's `X-User-ID`, and `agency_signed_by_user_id`, `compliance_approved_by_user_id`, `terminated_on`, `termination_reason_code` and `suspension_reason` all unset. An agency may hold at most one contract that is still live — that is, in `DRAFT`, `PENDING_AGENCY_SIGNATURE`, `PENDING_COMPLIANCE_REVIEW`, `ACTIVE` or `SUSPENDED` — and a second one is `ERR_DUPLICATE_RESOURCE`.

Negotiation runs through six lifecycle actions, each named by an `action` value, optionally accompanied by a `note` and by a `revised_annual_commission_cap_cents` figure carrying the office's proposed ceiling. Neither `note` nor `revised_annual_commission_cap_cents` participates in any precondition or cascade; they travel with the action as context. An action that is not defined from the contract's current `status` is rejected with `ERR_INVALID_CONTRACT_STATE`, and every successful action increments the contract's `version`.

`SEND_FOR_SIGNATURE`, taken by a `RecruitmentOfficer`, moves `DRAFT → PENDING_AGENCY_SIGNATURE`. It requires that the agency's due-diligence dimension be in `SCREENING`, `INFO_REQUESTED` or `CLEARED` — a `DRAFT` or `REJECTED` agency cannot have paper sent out — and that at least one rate card already exist on the contract, absent which the request fails with `ERR_SCHEDULE_NOT_EFFECTIVE`.

`AGENCY_SIGN` moves `PENDING_AGENCY_SIGNATURE → PENDING_COMPLIANCE_REVIEW` and is reserved to the `AgencyOwner` whose `X-User-ID` equals the contract's `agency_id`. The signing identity is stamped into `agency_signed_by_user_id`.

`COMPLIANCE_APPROVE` moves `PENDING_COMPLIANCE_REVIEW → ACTIVE` and is the countersignature. It requires an acting `X-User-ID` different from `created_by_user_id`, an agency whose due-diligence dimension has actually reached `CLEARED` — otherwise `ERR_AGENCY_NOT_CLEARED` — and an integrity standing of either `GOOD_STANDING` or `WATCH`, with `PROBATION`, `SUSPENDED` or `DEBARRED` refused as `ERR_AGENCY_POSTURE_BLOCKED`. The approving identity is stamped into `compliance_approved_by_user_id`.

`REQUEST_AMENDMENT` is the revert branch: a `ComplianceOfficer` sends `PENDING_COMPLIANCE_REVIEW → DRAFT`. It increments `amendment_round`, increments `disclosure_template_version`, and clears `agency_signed_by_user_id` so the agency must sign the revised paper again. It also reaches into the student files: every application of that agency whose `disclosure_state` is `ISSUED` is driven to `INVALIDATED`. Deliberately, an application whose disclosure is already `ACKNOWLEDGED` keeps that state — it is *not* invalidated — but because the contract's template version has advanced while the application's pinned version has not, the application has become version-stale and will fail at submission with `ERR_DISCLOSURE_VERSION_STALE` until the disclosure is re-issued and re-acknowledged. At most three amendment rounds are permitted: the revert requires `amendment_round` to be strictly below 3, so a fourth attempt is refused with `ERR_AMENDMENT_LIMIT_REACHED`.

`SUSPEND` moves `ACTIVE → SUSPENDED` and records a `suspension_reason`. Suspension has two cascade hops of its own: every territory assignment on that contract still in `ACTIVE` is `RELEASED` with `released_on` set to the current logical-clock date, and every application of that agency that is still in `DRAFT` and whose `disclosure_state` is either `ISSUED` or `ACKNOWLEDGED` is driven to `INVALIDATED`. Note the asymmetry with amendment: suspension does invalidate an acknowledged disclosure, but only on applications that have not yet been submitted. The same `ACTIVE → SUSPENDED` transition also occurs as a system cascade when the agency's integrity standing escalates to `PROBATION`, `SUSPENDED` or `DEBARRED`, with the same two hops.

`REINSTATE` moves `SUSPENDED → ACTIVE` and clears `suspension_reason`. It requires the agency's due-diligence dimension to be `CLEARED`, its integrity standing to be `GOOD_STANDING` or `WATCH`, and the current logical-clock date to be no later than the contract's `term_end_date`. Reinstatement restores the contract only — territory assignments released by the suspension are gone for good and must be re-created if the agency is to recruit in those countries again.

Contracts also leave the negotiation graph without anyone asking. When the logical clock advances strictly past `term_end_date`, a contract in `ACTIVE` or in `SUSPENDED` moves to `EXPIRED`; the `ACTIVE` case additionally expires that contract's still-`ACTIVE` territory assignments as described in §2.5. `TERMINATED` and `EXPIRED` are both terminal.

### 3.3. Territory Assignments and Commission Rate Cards

**Territory geometry.** A `RecruitmentOfficer` grants a contract the right to recruit in a country by creating a territory assignment with the `country_code` as exactly two uppercase letters, an `exclusivity` of either `EXCLUSIVE` or `NON_EXCLUSIVE`, and a half-open date window: `start_date` is inclusive, `end_date` is exclusive and must be strictly after `start_date` — an `end_date` on or before `start_date` is a window-coherence failure refused with `ERR_TERM_WINDOW_INVALID` rather than a structural one — so the occupied interval runs from `start_date` up to but not including `end_date`. The assignment is created in `ACTIVE` with `released_on` unset. An `EXCLUSIVE` request is permitted only when the contract's `exclusivity_model` is `EXCLUSIVE_ALLOWED`; on a `NON_EXCLUSIVE_ONLY` contract it is refused with `ERR_EXCLUSIVITY_NOT_PERMITTED`. The requested window must also lie inside the contract's own term, from `term_start_date` through `term_end_date`, or the request fails with `ERR_TERM_WINDOW_INVALID`.

Occupancy is computed only from assignments still in `ACTIVE`; rows in `RELEASED` or `EXPIRED` contribute neither occupancy nor any lingering shadow. An assignment occupies a given instant when its status is `ACTIVE` and the instant falls at or after `start_date` and strictly before `end_date`. An `EXCLUSIVE` assignment additionally casts a **cool-off shadow**: its shadow ends 30 days after its `end_date`, whereas a `NON_EXCLUSIVE` assignment's shadow ends exactly at its `end_date`. The shadow of an assignment covers instants from `start_date` up to but not including that shadow end.

Two geometric gates guard creation. The exclusivity gate says that an `EXCLUSIVE` request requires zero `ACTIVE` assignments of either kind overlapping its interval and no `EXCLUSIVE` cool-off shadow reaching into that interval, while a `NON_EXCLUSIVE` request must not intersect the interval of an `ACTIVE` `EXCLUSIVE` assignment extended by the 30-day cool-off; either failure is `ERR_TERRITORY_EXCLUSIVITY_CONFLICT`. The capacity gate says that at every instant of the requested interval the number of `ACTIVE` `NON_EXCLUSIVE` assignments for that country must remain at most three, so a request that would create a fourth concurrent non-exclusive occupant at any instant is `ERR_TERRITORY_CAPACITY_EXCEEDED`.

The same geometry is readable directly. Given a `country_code` and an `at_date`, a `RecruitmentOfficer` or `ComplianceOfficer` can obtain `exclusive_active_count` — the number of `ACTIVE` `EXCLUSIVE` assignments in that country occupying that instant — `non_exclusive_active_count` for the non-exclusive equivalent, `exclusive_cooloff_until` — the latest cool-off end among the country's `ACTIVE` `EXCLUSIVE` assignments, or null when there are none — and `exclusive_slot_available`, which is true exactly when `exclusive_active_count` is zero, `non_exclusive_active_count` is zero, and either `exclusive_cooloff_until` is null or the requested instant falls at or after it. The response echoes the `country_code` and `at_date` it was asked about. Assignments may be listed per contract and filtered by `country_code` and `status`.

A `RecruitmentOfficer` or `ComplianceOfficer` may release an assignment early, moving `ACTIVE → RELEASED` with `released_on` set to the current logical-clock date. Release is immediate and total: the country's exclusive-slot occupancy drops at once and no cool-off buffer survives a release, so the freed slot is available the same day. Cascade-driven release from contract suspension or termination behaves identically, while clock-driven expiry moves `ACTIVE → EXPIRED` with the same `released_on` stamp. `RELEASED` and `EXPIRED` are both terminal.

**Rate cards.** Commission rates live on a `CommissionSchedule`, a rate card that a `RecruitmentOfficer` appends to a contract. Each card declares a half-open effectiveness window — `effective_from` inclusive, `effective_to` exclusive and strictly after `effective_from`, and no later than the contract's `term_end_date` — four milestone rates in basis points, each between 0 and 2000: `deposit_rate_bps` payable when the deposit is paid, `enrollment_rate_bps` payable at enrollment, `census_rate_bps` payable when the census is confirmed, and `persistence_rate_bps` payable when persistence is confirmed. Three ceilings complete the card: `rate_cap_bps`, between 0 and 2000, caps the base rate plus any tier bonus for a single milestone; `per_milestone_cap_cents`, strictly positive, is an absolute cent ceiling on a single milestone accrual; and `clawback_window_days`, strictly positive, sets the prorated-clawback window measured in days after each milestone event date. The server assigns `version_no` itself as the 1-based sequence number of the card in creation order within the contract, so the first card on a contract is 1 and each subsequent card is one higher.

Cards must tile the contract term exactly — no overlap and no gap. The first card on a contract must begin precisely on the contract's `term_start_date`, and every later card must begin precisely where the latest existing card ended. A card whose `effective_from` is earlier than the greatest existing `effective_to` on the contract — or a first card that does not start on `term_start_date` — is rejected with `ERR_SCHEDULE_INTERVAL_CONFLICT`. A card whose `effective_from` is later than that greatest existing `effective_to`, leaving an uncovered stretch, is rejected with `ERR_SCHEDULE_GAP`. A window falling outside the contract term is `ERR_TERM_WINDOW_INVALID`. Because the tiling frontier is the thing a client must not misread, this append is the concurrency-guarded write described in §2.9 and carries `expected_contract_version`; the successful append increments the contract's `version` by one. Cards may be listed for a contract in tiling order.

### 3.4. The Student File: Disclosure, Submission and Admission Decisions

An `AgencyOwner` opens a student file by naming the `agency_id` — which must be its own — the `program_id` applied to, an office-assigned `student_ref` unique across all applications, the `student_residence_country` as exactly two uppercase letters, and the boolean `student_us_person` recording whether the prospective student is a US citizen or permanent resident. A duplicate `student_ref` is `ERR_DUPLICATE_RESOURCE`. Creation is refused with `ERR_AGENCY_POSTURE_BLOCKED` when the agency's integrity standing is `SUSPENDED` or `DEBARRED`.

At creation the server classifies the recruitment origin once and never again. When `student_residence_country` is `US`, or `student_us_person` is true, `recruitment_origin` is `DOMESTIC`; in every other case it is `INTERNATIONAL`. The classification reads only those two client-supplied fields and is never re-derived afterwards, because it gates incentive-compensation eligibility for the entire life of the file. The new application sits in `status` `DRAFT` and `disclosure_state` `NOT_ISSUED`, with `custody_agency_id` initialised to the recruiting `agency_id`, `pinned_contract_id`, `pinned_schedule_id`, `disclosure_template_version`, `disclosure_ack_token`, `disclosure_acknowledged_at`, `submitted_on`, `tier_snapshot_at_submission`, `deposit_paid_on`, `enrolled_on`, `census_confirmed_on`, `persisted_on`, `withdrawn_on` and `withdrawal_reason` all unset, `projected_commission_cents` and `net_commission_cents` at 0, and `integrity_hold` false. `agency_id` is immutable: it is the recruiting agency of record and drives commission attribution forever, whereas `custody_agency_id` is the agency currently holding the file and may be reassigned by a termination cascade, with a null value meaning the file is held in-house.

**Disclosing the agent relationship.** Before a student's application can be submitted, the university's relationship with the agency must be disclosed to that student and acknowledged by them. Issuing the disclosure is available to a `RecruitmentOfficer` or to the `AgencyOwner`, and is requested by an `action` of `ISSUE`. It requires the application's `disclosure_state` to be `NOT_ISSUED` or `INVALIDATED` and its `status` to still be `DRAFT`, and it requires the agency to hold a contract in `PENDING_AGENCY_SIGNATURE`, `PENDING_COMPLIANCE_REVIEW` or `ACTIVE` — the disclosure text is a function of contract paper, so a disclosure cannot precede paper existing. Issuance pins that contract's `disclosure_template_version` onto the application's own `disclosure_template_version` field and mints a single-use `disclosure_ack_token`. Re-issuing from `INVALIDATED` follows the identical rule set: `INVALIDATED → ISSUED` re-pins the template version and replaces the previous token with a fresh one, discarding the old token. The `NOT_ISSUED → ISSUED → ACKNOWLEDGED → INVALIDATED → ISSUED` cycle may repeat without limit; the disclosure dimension has no terminal state.

Acknowledgement is the `Applicant`'s act and only the `Applicant`'s: with an `action` of `ACKNOWLEDGE`, the student presents `ack_token`, which must equal the application's current `disclosure_ack_token`, and the application moves `ISSUED → ACKNOWLEDGED` with `disclosure_acknowledged_at` stamped from the logical-clock instant. A wrong or superseded token is refused with `ERR_DISCLOSURE_TOKEN_INVALID` (HTTP 403). A disclosure action that is illegal from the current `disclosure_state` — acknowledging something never issued, or issuing over a live acknowledgement — is `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, and a disclosure action attempted on an application whose `status` has moved beyond `DRAFT` is `ERR_INVALID_APPLICATION_STATE`.

Invalidation is never a client action; it is always a system cascade. A disclosure in `ISSUED` is driven to `INVALIDATED` when the contract's amendment is requested, when the contract is suspended, or when the contract is terminated. A disclosure in `ACKNOWLEDGED` is driven to `INVALIDATED` by contract suspension for applications still in `DRAFT`, and by contract termination for applications whose files are transitioned. In both cases `disclosure_ack_token` is cleared, so a fresh issuance is required before the student can acknowledge again.

**Submission.** Submission is the `AgencyOwner`'s act and the single most heavily gated transition in the system, moving `status` `DRAFT → SUBMITTED`. It takes no request body at all; everything it needs it reads from state. Eleven conditions must hold: the application is in `DRAFT`; its `disclosure_state` is `ACKNOWLEDGED`; its pinned `disclosure_template_version` equals the `disclosure_template_version` of the agency's contract that is currently in `ACTIVE`; the agency's due-diligence dimension is `CLEARED`; the agency has exactly one contract in `ACTIVE`, and that contract is the one pinned; the agency's integrity standing is `GOOD_STANDING` or `WATCH`; certifications in `VALID` status exist for *both* the `PROGRAM_ACCURACY` and the `PROHIBITED_CLAIMS` modules; at least one supporting document of `doc_type` `PASSPORT` on this application has reached `verification_state` `VERIFIED`; `integrity_hold` is false; a territory assignment in `ACTIVE` exists on the pinned contract whose `country_code` equals the application's `student_residence_country` and whose window covers the current date, meaning `start_date` is at or before the current date and `end_date` is strictly after it; and a rate card on the pinned contract covers the current date in the same half-open sense, with `effective_from` at or before it and `effective_to` strictly after it.

Each failure has its own code: a non-`DRAFT` application is `ERR_INVALID_APPLICATION_STATE`; an unacknowledged disclosure is `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`; a template version behind the active contract's is `ERR_DISCLOSURE_VERSION_STALE`; an uncleared agency is `ERR_AGENCY_NOT_CLEARED`; a blocked integrity standing, or the absence of a contract in `ACTIVE`, is `ERR_AGENCY_POSTURE_BLOCKED` and `ERR_INVALID_CONTRACT_STATE` respectively; a missing or lapsed `PROGRAM_ACCURACY` or `PROHIBITED_CLAIMS` certification is `ERR_TRAINING_LAPSED`, where lapsed means the current logical-clock date has reached `expires_on` and where a `REVOKED` record never counts; the absence of a verified passport is `ERR_IDENTITY_DOCUMENT_UNVERIFIED`; a live fraud hold is `ERR_FRAUD_HOLD_ACTIVE`; an uncovered residence country is `ERR_TERRITORY_NOT_COVERED`; and the absence of an effective rate card is `ERR_SCHEDULE_NOT_EFFECTIVE`.

When all eleven hold, submission does four things beyond the state change. It stamps `submitted_on` with the current logical-clock date. It pins `pinned_contract_id` to the sole contract in `ACTIVE` and `pinned_schedule_id` to the rate card effective on that date — and those two pins, not the currently effective records, are what every later milestone accrual reads. It resolves the agency's performance tier as of `submitted_on` and freezes it into `tier_snapshot_at_submission`. And it computes and freezes `projected_commission_cents`, the provisional forward-looking projection described in §3.6.

**Admission decisions.** A `RecruitmentOfficer` decides a submitted application by supplying a `decision` and an optional `note`. A `decision` of `ADMIT` moves `SUBMITTED → ADMITTED` and additionally requires `integrity_hold` to be false, so a document flagged after submission blocks admission with `ERR_FRAUD_HOLD_ACTIVE`. A `decision` of `DENY` moves `SUBMITTED → DENIED` and carries no such requirement — a denial is always allowed to proceed. `DENIED` is terminal, as are `PERSISTED` and `WITHDRAWN`. A decision requested from any status other than `SUBMITTED` is `ERR_INVALID_APPLICATION_STATE`.

Applications may be listed and filtered on `agency_id`, `custody_agency_id`, `program_id`, `pinned_contract_id`, `pinned_schedule_id`, `status`, `disclosure_state` and `recruitment_origin`.

### 3.5. Document Intake, Fraud Signals and Verification Outcomes

Supporting documents are uploaded by the `AgencyOwner` against a specific `application_id`. Each upload declares a `doc_type` — one of `PASSPORT`, `TRANSCRIPT`, `FINANCIAL_PROOF`, `ENGLISH_TEST` or `SPONSOR_LETTER` — a `content_hash` between 1 and 128 characters serving as the content digest, the `issuer_name` as declared by the agency, and optionally `declared_signals`, an array of verification signals reported by the intake screen drawn from `ISSUER_UNVERIFIED`, `TRANSCRIPT_ANOMALY`, `TRANSLATION_MISMATCH` and `DATE_INCONSISTENCY`, defaulting to the empty list. Upload is refused with `ERR_AGENCY_POSTURE_BLOCKED` when the agency's integrity standing is `SUSPENDED` or `DEBARRED`.

At upload the server derives the document's own signal set and scores it. `fraud_signals` is the declared set plus, when applicable, the additional signal `HASH_DUPLICATE`: that signal is added when some other document already recorded carries the identical `content_hash` and belongs to a *different* application of the *same* agency. Documents of the same application never trigger the duplicate signal against each other, and matches across agencies are ignored; the comparison spans every one of the agency's documents regardless of their verification state.

`fraud_index` is then the sum of the weights of the distinct signals in `fraud_signals`, capped at 100. `HASH_DUPLICATE` weighs 45, `ISSUER_UNVERIFIED` weighs 25, `TRANSCRIPT_ANOMALY` weighs 20, `TRANSLATION_MISMATCH` weighs 15, and `DATE_INCONSISTENCY` weighs 10, and the index is always a whole number between 0 and 100. A document whose index reaches 60 is auto-flagged at upload: it lands in `verification_state` `FLAGGED` rather than `PENDING`, and the owning application's `integrity_hold` is set to true, which recomputes the agency's `reviewed_document_count`. The boundary is inclusive on the flagging side — an index of exactly 60 flags, and 59 does not. Documents can be read individually, including their computed signal set, index and verification state, and listed per application filtered by `doc_type` and `verification_state`.

Verification is the `ComplianceOfficer`'s exclusive act, expressed as an `outcome` with an optional `note`. The dimension is a fork-join: `PENDING` forks to either `VERIFIED` or `FLAGGED` with different side effects, and `FLAGGED` forks again to either `CLEARED` or `CONFIRMED_FRAUD`. An outcome that is not defined from the document's current `verification_state` — for instance `CLEARED` on a `PENDING` document, or `VERIFIED` on a `FLAGGED` one — is refused with `ERR_INVALID_DOCUMENT_STATE`. Every recorded outcome stamps `verified_by_user_id` with the acting officer's `X-User-ID` and increments the document's `version`. `CONFIRMED_FRAUD` is terminal.

An `outcome` of `VERIFIED` moves `PENDING → VERIFIED` and is permitted only when the document's `fraud_index` is strictly below 60 — a document the intake screen already auto-flagged cannot be waved through in one step. Verification recomputes the agency's `reviewed_document_count` and recomputes the agency's risk figures.

An `outcome` of `FLAGGED` moves `PENDING → FLAGGED`, sets the owning application's `integrity_hold` to true, and likewise recomputes the agency's `reviewed_document_count` and risk figures.

An `outcome` of `CLEARED` moves `FLAGGED → CLEARED` and lifts the hold conditionally: `integrity_hold` returns to false only when no *other* document on that same application remains in `FLAGGED` or `CONFIRMED_FRAUD`. If a sibling document is still flagged, the hold stays. Clearing recomputes the agency's risk figures.

An `outcome` of `CONFIRMED_FRAUD` moves `FLAGGED → CONFIRMED_FRAUD` and opens the deepest cascade in the system, five hops long. First, an integrity incident is appended automatically, with `category` `DOCUMENT_FRAUD`, `severity` `HIGH`, `source` `DOCUMENT_REVIEW`, `status` already `CONFIRMED`, `occurred_on` set to the current logical-clock date, and both `document_id` and `application_id` populated from the document under review. Second, the agency's `confirmed_fraud_document_count`, `rolling_risk_score` and `lifetime_risk_score` are recomputed, which may escalate its integrity standing. Third, an escalation that reaches `PROBATION` or `SUSPENDED` suspends the agency's contracts that are in `ACTIVE`. Fourth, each suspended contract releases its territory assignments still in `ACTIVE` and invalidates the disclosures on that agency's `DRAFT` applications. Throughout, the owning application's `integrity_hold` stays true — confirming fraud never lifts a hold.

### 3.6. Enrollment Milestones, Tier Resolution and Commission Accrual

Once an application is admitted, the registrar's office records enrollment facts. Milestone registration is exclusive to the `Registrar` and takes a `milestone`, the `event_date` on which the fact occurred, and the concurrency field `expected_application_version` described in §2.9. The milestone chain is strictly ordered — `ADMITTED → DEPOSIT_PAID → ENROLLED → CENSUS_CONFIRMED → PERSISTED` — and only the immediate successor of the application's current `status` may be registered. Registering `CENSUS_CONFIRMED` on an application still in `DEPOSIT_PAID`, or re-registering a milestone already recorded, is refused with `ERR_MILESTONE_OUT_OF_ORDER`.

Dates are policed per milestone, and each successful registration stamps its own event-date field. `DEPOSIT_PAID` requires an `event_date` at or after `submitted_on` and at or before the current logical-clock date, and stamps `deposit_paid_on`. `ENROLLED` requires an `event_date` at or after `deposit_paid_on` and at or before the current logical-clock date, and stamps `enrolled_on`. `CENSUS_CONFIRMED` requires an `event_date` at or after `enrolled_on` and at or before the current logical-clock date, and stamps `census_confirmed_on`. `PERSISTED` requires an `event_date` at or after `census_confirmed_on` and at or before the current logical-clock date, and stamps `persisted_on`. A date before its predecessor's date, or later than the current logical-clock date, is `ERR_MILESTONE_DATE_INVALID`. Two further program-driven gates apply on top: a `CENSUS_CONFIRMED` `event_date` earlier than the program's `census_date` is refused with `ERR_CENSUS_DATE_NOT_REACHED`, and a `PERSISTED` `event_date` earlier than the program's `persistence_check_date` is refused with `ERR_PERSISTENCE_DATE_NOT_REACHED`.

**Resolving the tier.** Commission pricing depends on the agency's performance tier, and the tier is resolved from performance scorecards by a rule pinned specifically to break an apparent circularity — a scorecard's quality index depends on document review outcomes, a ledger entry's amount depends on the scorecard tier, and the scorecard cohort depends on applications that carry ledger entries. The cycle is cut by only ever reading scorecards whose scoring window closed *strictly before* the event date being priced, and by never recomputing an existing scorecard. Concretely: take that agency's scorecards whose `period_end_date` is strictly earlier than the event date in question, with no status filter because scorecards have no lifecycle of their own; if there are none, the tier is `UNRATED`; otherwise order the candidates by `period_end_date` descending and break ties by `created_at` descending — never by identifier — and take the `tier` of the first. A tier confers a basis-point bonus: `PLATINUM` adds 150 basis points, `GOLD` adds 75, `STANDARD` adds nothing, `WATCH` *subtracts* 100, and `UNRATED` adds nothing.

**Pricing a milestone.** Each milestone registration appends one ledger entry, unless one of two gates suppresses it: if the program's `commission_eligible` is false, no entry is created at all, and if the pinned contract's `status` is `TERMINATED` or `EXPIRED`, no entry is created at all. When an entry is created, it copies `contract_id` from the application's `pinned_contract_id`, `schedule_id` from its `pinned_schedule_id`, and `application_id` from the application, with `kind` set to `ACCRUAL`, `milestone` set to the milestone registered, `milestone_event_date` set to the `event_date`, `state` set to `ACCRUED`, `parent_entry_id` left unset, and `tier_snapshot` set to the tier resolved by the rule above *at that entry's own `milestone_event_date`* — not at the submission date.

The amount is then built in a fixed order. The base rate is the pinned rate card's field for this milestone: `deposit_rate_bps` for `DEPOSIT_PAID`, `enrollment_rate_bps` for `ENROLLED`, `census_rate_bps` for `CENSUS_CONFIRMED`, and `persistence_rate_bps` for `PERSISTED`. The tier bonus for `tier_snapshot` is added to that base. `effective_bps` is then the greater of zero and the smallest of three quantities: the base plus bonus, the pinned card's `rate_cap_bps`, and the program's `max_commission_bps` — so a negative `WATCH` adjustment can never drive the effective rate below zero, and neither ceiling can be exceeded. The raw amount is the program's `annual_tuition_cents` multiplied by `effective_bps` and divided by 10,000; `amount_cents` is that raw amount rounded half up to whole cents and then, and only then, capped at the pinned card's `per_milestone_cap_cents`. Rates come exclusively from the pinned rate card, never from whichever card happens to be effective on the event date.

One more field is stamped at creation: `incentive_comp_prohibited` is true exactly when the producing application's `recruitment_origin` is `DOMESTIC`, and false otherwise. A domestic-origin entry is still created and still carries its computed `amount_cents`; what it cannot do is ever be approved, as §3.7 explains.

**The two entitlement figures.** Every application exposes two commission numbers computed by different rules, and their divergence is the point. `projected_commission_cents` is the *provisional forward-looking* figure, frozen at submission and never recomputed: it is the sum of the four milestone amounts for `DEPOSIT_PAID`, `ENROLLED`, `CENSUS_CONFIRMED` and `PERSISTED`, each priced by the rule above using the pinned rate card and the single frozen `tier_snapshot_at_submission`, each rounded independently before being added. It assumes full progression all the way to persistence and ignores clawback, forfeiture and non-progression entirely. `net_commission_cents` is the *final chronological* figure, recomputed after every accrual, clawback, forfeiture and void: it is the sum of `amount_cents` over that application's `ACCRUAL` entries whose `state` is `ACCRUED`, `APPROVED` or `PAID`, minus the sum of `amount_cents` over its `CLAWBACK` entries whose `state` is `CLAWED_BACK`. Entries in `FORFEITED` or `VOID` contribute to neither sum. Because each accrual used the tier resolved at its *own* event date, a tier change between submission and a milestone makes the final figure diverge from the projection even when every milestone is eventually reached.

Both figures are readable side by side on a per-application computed view, which reports `provisional_projection_cents` mirroring `projected_commission_cents`, `final_net_cents` mirroring `net_commission_cents`, and `variant_delta_cents` as the provisional projection minus the final net. The same view echoes the frozen `tier_snapshot_at_submission` and `pinned_schedule_id`, and reports `accrued_entry_count` and `clawback_entry_count` for the application.

Every milestone registration therefore recomputes the application's `net_commission_cents` and the agency's `net_earned_commission_cents`, and increments the application's `version` by one.

### 3.7. Withdrawal, Clawback and Ledger Disposition

**Withdrawal.** A `Registrar` records a student withdrawal by supplying the `withdrawal_date` and a free-text `reason`, stamped onto `withdrawn_on` and `withdrawal_reason`. Withdrawal is permitted from `SUBMITTED`, `ADMITTED`, `DEPOSIT_PAID`, `ENROLLED` and `CENSUS_CONFIRMED`; from any other status it is `ERR_INVALID_APPLICATION_STATE`. The `withdrawal_date` must lie at or after `submitted_on` and at or before the current logical-clock date, or the request is `ERR_MILESTONE_DATE_INVALID`. In all cases the application moves to the terminal `WITHDRAWN` and its `version` increments.

The clawback ledger runs on every withdrawal, whatever the originating status. From `SUBMITTED` and from `ADMITTED` there are no accruals yet, so it produces no rows — but it still runs, and this symmetry matters for implementers: there is no special-cased "early withdrawal" path. From `DEPOSIT_PAID`, `ENROLLED` and `CENSUS_CONFIRMED` the cascade has four hops: the ledger appends reversal rows and moves each reversed accrual to `CLAWED_BACK`; the application's `net_commission_cents`, the agency's `net_earned_commission_cents` and the agency's `clawback_liability_cents` are recomputed; and if the agency's total clawback amount divided by its total lifetime accrual amount reaches 0.25 — a quarter of everything ever accrued having been reversed — and its integrity standing is `GOOD_STANDING`, that standing escalates to `WATCH`.

**How a reversal is computed.** The reversible set is that application's `ACCRUAL` entries whose `state` is `ACCRUED`, `APPROVED` or `PAID`; entries already in `FORFEITED`, `VOID` or `CLAWED_BACK` are skipped. The reversible entries are processed in order of `milestone_event_date` ascending, with ties broken by `created_at` ascending.

For each entry the proration percentage is determined first. If the `withdrawal_date` falls strictly before the program's `census_date`, the percentage is the whole of it — 1.0000 — because a student who leaves before the enrollment census was never really enrolled. Otherwise the age of the accrual is the number of days from that entry's `milestone_event_date` to the `withdrawal_date`. If that age is at most the pinned rate card's `clawback_window_days`, the percentage is the window length minus the age, divided by the window length, rounded half up to four decimal places — so a reversal on the day of the milestone recovers everything and a reversal on the last day of the window recovers almost nothing. If the age exceeds the window, the percentage is 0.0000 and nothing is recovered.

The entry's reversal is then its `amount_cents` multiplied by that percentage, rounded half up to whole cents — rounded *per entry*, never once at the end. When the resulting figure is greater than zero, a reversal row is appended with `kind` `CLAWBACK` and `state` `CLAWED_BACK`, its `parent_entry_id` pointing at the accrual it reverses, and its `milestone`, `milestone_event_date`, `tier_snapshot` and `effective_bps` copied verbatim from that parent. If the parent accrual's `state` was `PAID` — meaning the money had already left the institution — the reversal amount is added to the agency's `clawback_liability_cents`. The parent accrual then moves to `CLAWED_BACK`. Any total clawback figure is the sum of these already-rounded per-entry values; summing the raw products and rounding once is explicitly not the rule and produces a different total.

**The agency-level balances.** Both agency aggregates are always recomputed in full from ledger rows, never adjusted incrementally. `net_earned_commission_cents` is the sum of `amount_cents` over every `ACCRUAL` entry reachable from the agency through its contracts whose `state` is `ACCRUED`, `APPROVED` or `PAID`, minus the sum of `amount_cents` over every such `CLAWBACK` entry whose `state` is `CLAWED_BACK`; `FORFEITED` and `VOID` accruals are excluded from both sums. `clawback_liability_cents` is the sum of `amount_cents` over the agency's `CLAWBACK` entries in `CLAWED_BACK` whose parent accrual was in `PAID` at the time the clawback was written. Neither figure is windowed: all periods, all contracts. Recomputation is triggered by every ledger state change, every accrual append, and the ledger hop of contract termination.

**Disposition.** Ledger entries are moved by the `FinanceOfficer` alone, through an `action` with an optional `note`. `ACCRUED` is the initial state; `PAID`, `CLAWED_BACK`, `FORFEITED` and `VOID` are all terminal. A disposition that is not defined from the entry's current `state` is `ERR_INVALID_ENTRY_STATE`.

An `action` of `APPROVE` moves `ACCRUED → APPROVED` and stamps `approved_by_user_id`. It carries five substantive conditions beyond the state check. The entry's `incentive_comp_prohibited` must be false: no per-enrollment incentive compensation may ever be approved for an application whose `recruitment_origin` is `DOMESTIC`, and the attempt is refused with `ERR_INCENTIVE_COMPENSATION_PROHIBITED` — permanently, since the classification never changes, leaving `VOID` as the only exit from `ACCRUED` for such an entry. The producing application's `status` must be neither `WITHDRAWN` nor `DENIED`. The entry's contract must be in `ACTIVE`, or the request is `ERR_INVALID_CONTRACT_STATE`. The agency's integrity standing must be `GOOD_STANDING` or `WATCH`, or the request is `ERR_AGENCY_POSTURE_BLOCKED`. Finally the annual ceiling applies: the sum of `amount_cents` over that contract's `ACCRUAL` entries already in `APPROVED` or `PAID`, plus this entry's own `amount_cents`, must not exceed the contract's `annual_commission_cap_cents`, and a breach is `ERR_COMMISSION_CAP_EXCEEDED`.

An `action` of `PAY` moves `APPROVED → PAID` and stamps `paid_by_user_id`. It requires an acting `X-User-ID` different from the entry's `approved_by_user_id` per §2.10, an agency integrity standing that is not `SUSPENDED` and not `DEBARRED`, and an agency `clawback_liability_cents` of exactly zero — no further money leaves the institution while unrecovered money is outstanding, and an attempt against a non-zero liability is `ERR_CLAWBACK_LIABILITY_UNSETTLED`.

An `action` of `VOID` is available from either `ACCRUED` or `APPROVED`, moves the entry to `VOID`, records a `void_reason`, and recomputes both the application's `net_commission_cents` and the agency's `net_earned_commission_cents`.

Two more entry states are reachable only by cascade. `CLAWED_BACK` is reached from `ACCRUED`, `APPROVED` or `PAID` when a withdrawal's clawback ledger yields a reversal amount greater than zero for that entry, as above. `FORFEITED` is reached from `ACCRUED` or `APPROVED` when contract termination selects the entry, as described in §3.9; forfeiture records a `void_reason` and recomputes the same two balances. Entries may be listed and filtered on `contract_id`, `application_id`, `schedule_id`, `parent_entry_id`, `kind`, `milestone` and `state`.

### 3.8. Integrity Adjudication, Risk Scoring and Compliance Posture

**Filing an incident.** A `RecruitmentOfficer` or `ComplianceOfficer` files an integrity incident against an `agency_id`, optionally tying it to an `application_id` and further to a `document_id` — the attachment is deliberately layered, so an incident may name an agency alone, an agency and an application, or an agency, an application and one specific document. The filing declares a `category` of `DOCUMENT_FRAUD`, `PROHIBITED_CLAIM`, `DISCLOSURE_FAILURE` or `MISREPRESENTATION`; a `severity` band of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`; the `occurred_on` date on which the conduct took place, which may not be later than the current logical-clock date and is refused with `ERR_FUTURE_DATE_NOT_ALLOWED` if it is; and a `source` describing the reporting channel, one of `STUDENT_COMPLAINT`, `DOCUMENT_REVIEW`, `AUDIT` or `PARTNER_REPORT`. The incident lands in `status` `REPORTED` and contributes nothing to risk until it is adjudicated. Incidents may be listed and filtered on `agency_id`, `application_id`, `document_id`, `category` and `status`.

**Adjudication.** Only a `ComplianceOfficer` adjudicates, supplying an `outcome` with an optional `note`; `CONFIRMED` and `DISMISSED` are both terminal, and an incident already in either is refused with `ERR_INVALID_INCIDENT_STATE`. Both outcomes stamp `resolved_by_user_id` from the acting `X-User-ID` and increment the incident's `version`.

An `outcome` of `CONFIRM` moves `REPORTED → CONFIRMED` and recomputes the agency's `confirmed_incident_count`, `rolling_risk_score` and `lifetime_risk_score`, which may escalate its integrity standing and cascade onward into contract suspension. Confirmation of a `PROHIBITED_CLAIM` carries an additional consequence: every certification of that agency whose `module_code` is `PROHIBITED_CLAIMS` and whose `status` is `VALID` is driven to `REVOKED` with `revoked_reason` recorded as `CONFIRMED_PROHIBITED_CLAIM`. Because a valid prohibited-claims certification is a submission precondition, confirming a prohibited claim immediately stops that agency from submitting new applications until it re-certifies.

An `outcome` of `DISMISS` moves `REPORTED → DISMISSED`. A dismissed incident makes no risk contribution: the agency's scores are recomputed and, absent any other change, come back unchanged.

**Risk scoring.** Two risk figures are maintained on every agency from the same underlying data, and only incidents in `CONFIRMED` contribute — those in `REPORTED` or `DISMISSED` never do. Severity carries a weight: `LOW` weighs 5, `MEDIUM` weighs 15, `HIGH` weighs 30, and `CRITICAL` weighs 50. Both figures also carry a document-quality term: the fraud rate is zero when the agency's `reviewed_document_count` is zero, and otherwise is `confirmed_fraud_document_count` divided by `reviewed_document_count`, where the reviewed count spans documents on all of that agency's applications whose `verification_state` is `VERIFIED`, `FLAGGED`, `CONFIRMED_FRAUD` or `CLEARED`, the fraud count spans those in `CONFIRMED_FRAUD`, and no date window applies to either. Forty points are allocated to that term.

`rolling_risk_score` is the age-decayed figure and it is the one that drives posture. It considers only confirmed incidents whose age — the number of days from `occurred_on` to the current logical-clock date — is at most 365. Each such incident contributes its severity weight multiplied by a decay factor determined by that same age: full weight, a factor of 1.00, while the age is at most 90 days; three quarters, a factor of 0.75, while the age is more than 90 days and at most 180 days; and half, a factor of 0.50, for anything older within the 365-day window. Those contributions are summed, forty multiplied by the fraud rate is added, the total is rounded half up to two decimal places once, and the result is clamped to a maximum of 100.00.

`lifetime_risk_score` is the undecayed cumulative figure. It considers every confirmed incident with no window at all and applies no decay, so each contributes its full severity weight; forty multiplied by the fraud rate is added, the total is rounded half up to two decimal places once, and the result is clamped to a maximum of 100.00. On identical data the lifetime figure is therefore always greater than or equal to the rolling one, and compliance uses that gap when weighing a for-cause termination. Both figures are exposed side by side on a per-agency computed view, together with `lifetime_minus_rolling_delta` — the lifetime figure minus the rolling figure, to two decimal places — the three counts `confirmed_incident_count`, `reviewed_document_count` and `confirmed_fraud_document_count`, and `posture_band`, the band the rolling figure currently falls in: `GOOD_STANDING` below 40.00, `WATCH` from 40.00, `PROBATION` from 65.00, and `SUSPENDED` from 85.00.

**Posture movement.** Automatic escalation reads the rolling figure only, and it only ever escalates — a falling score never de-escalates anything on its own. After any risk recompute, a rolling figure at or above 85.00 targets `SUSPENDED`, at or above 65.00 but below 85.00 targets `PROBATION`, and at or above 40.00 but below 65.00 targets `WATCH`; below 40.00 the standing is left as it is. A performance scorecard whose `tier` comes out as `WATCH` also escalates a `GOOD_STANDING` agency to `WATCH`, and the clawback-ratio rule of §3.7 does the same.

A `ComplianceOfficer` may also move posture by hand, supplying an `action` and a mandatory `reason`; every posture change, manual or automatic, records the reason into `last_posture_reason` and increments the agency's `version`. An action not defined from the agency's current `compliance_posture`, or whose de-escalation risk-score precondition fails, is refused with `ERR_INVALID_POSTURE_ACTION`.

- `PLACE_ON_WATCH` moves `GOOD_STANDING → WATCH`.
- `PLACE_ON_PROBATION` moves `WATCH → PROBATION`, and also `GOOD_STANDING → PROBATION` directly — a single recompute can jump two bands, so the direct hop is legal. Either way, the probation transition suspends every contract of that agency that is in `ACTIVE`, recording `POSTURE_PROBATION` as each contract's `suspension_reason`, which in turn releases those contracts' active territories and invalidates their `DRAFT` applications' disclosures.
- `SUSPEND` moves an agency in `GOOD_STANDING`, `WATCH` or `PROBATION` to `SUSPENDED`; every contract of that agency in `ACTIVE` or already in `SUSPENDED` ends up in `SUSPENDED`.
- `REINSTATE` is the de-escalation and it lands on `WATCH`, never on `GOOD_STANDING`: from `PROBATION` or from `SUSPENDED` the agency returns to `WATCH`, and only when `rolling_risk_score` is strictly below 65.00. The `WATCH → PROBATION → WATCH` cycle may therefore repeat.
- `CLEAR_WATCH` moves `WATCH → GOOD_STANDING`, and only when `rolling_risk_score` is strictly below 40.00.

`DEBARRED` is reached only one way — by terminating a contract for cause — and it is terminal. From `GOOD_STANDING`, `WATCH` or `PROBATION`, a for-cause termination drives the agency to `DEBARRED`, records the reason into `last_posture_reason`, increments its `version`, and suspends every *other* contract of that agency that is in `ACTIVE` with `AGENCY_DEBARRED` as the `suspension_reason`.

### 3.9. Performance Scorecards, Termination and Student-File Transition

**Scoring a period.** A `RecruitmentOfficer` scores an agency over a closed window by supplying `period_start_date` and `period_end_date`. The window must be coherent — the start no later than the end, and the end no later than the current logical-clock date — or the run is refused with `ERR_TERM_WINDOW_INVALID`. Scorecards are immutable once written and are never recomputed, which is what makes them safe to read as pricing inputs.

Cohort membership is decided by submission date: the cohort is that agency's applications whose `submitted_on` is set and falls within the window inclusive of both endpoints. Applications still in `DRAFT`, having no `submitted_on`, are excluded. Enrollment and persistence, by contrast, are counted for cohort members whenever they happened, even after the window closed. `submitted_count` is the size of the cohort; `enrolled_count` is how many cohort members have an `enrolled_on` recorded; `persisted_count` is how many have a `persisted_on` recorded. Two document counts are taken over the cohort's documents: `reviewed_document_count` counts those in `VERIFIED`, `FLAGGED`, `CONFIRMED_FRAUD` or `CLEARED`, and `flagged_document_count` counts those in `FLAGGED` or `CONFIRMED_FRAUD`.

Three rates follow, each rounded half up to four decimal places. `yield_rate` is `enrolled_count` divided by `submitted_count`, or 0.0000 when the cohort is empty. `persistence_rate` is `persisted_count` divided by `enrolled_count`, or 0.0000 when nobody enrolled. `quality_index` is one minus `flagged_document_count` divided by `reviewed_document_count`, or 1.0000 when no document was ever reviewed — an agency with nothing reviewed is given the benefit of the doubt on quality. `composite_score` is then built from the *already-rounded* rates, with `yield_rate` weighted 0.45, `persistence_rate` weighted 0.35 and `quality_index` weighted 0.20: the three weighted terms are added together and that weighted sum is rounded half up to four decimal places. The three weights total 1.00, so a perfect agency scores 1.0000.

`tier` is the band of `composite_score`: `PLATINUM` at or above 0.8500, `GOLD` at or above 0.7000 but below 0.8500, `STANDARD` at or above 0.5000 but below 0.7000, and `WATCH` below 0.5000 — except that an empty cohort forces `UNRATED` regardless of any score. Writing a scorecard also refreshes the agency's `current_tier`, which is the `tier` of that agency's scorecard with the greatest `period_end_date`, ties broken by `created_at` descending, and `UNRATED` when the agency has no scorecard at all. Finally `posture_action_applied` records what the scorecard did to the agency's standing: `ESCALATED_TO_WATCH` when the resulting `tier` is `WATCH` and the agency was in `GOOD_STANDING`, and `NONE` in every other case. Scorecards may be listed per agency and filtered by `tier`.

**Termination.** Only a `ComplianceOfficer` terminates, and termination is permitted from `ACTIVE` and from `SUSPENDED`; from any other status it is `ERR_INVALID_CONTRACT_STATE`. The request carries a `reason_code` of `FOR_CAUSE`, `CONVENIENCE` or `NON_RENEWAL`, an `effective_date`, a mandatory `transition_note` documenting the handover, and optionally a `successor_agency_id` nominating who inherits the in-flight student files. The `effective_date` is stamped into `terminated_on` and the reason into `termination_reason_code`.

A nominated successor is vetted before anything moves. `successor_agency_id`, when provided, must name a *different* agency, whose `vetting_state` is `CLEARED`, whose `compliance_posture` is `GOOD_STANDING` or `WATCH`, and which holds at least one contract in `ACTIVE`. Naming the terminated agency itself, an uncleared agency, a blocked one, or one with no active contract is refused with `ERR_SUCCESSOR_NOT_ELIGIBLE`. Omitting the field is always allowed and means in-house custody.

Termination then runs a four-hop cascade, identically whether the contract was `ACTIVE` or `SUSPENDED`:

1. Every territory assignment on the contract still in `ACTIVE` is `RELEASED`.
2. Every application whose `custody_agency_id` is the terminated contract's agency and whose `status` is `DRAFT`, `SUBMITTED`, `ADMITTED` or `DEPOSIT_PAID` has its `custody_agency_id` reassigned to `successor_agency_id`, or to null when the field was omitted, has its `disclosure_state` driven to `INVALIDATED`, and gets one file-transition record appended. Applications already at `ENROLLED` or beyond, and those in a terminal status, are not transitioned. Each file-transition record captures the `application_id`, the `from_agency_id` that held custody before the move, the `to_agency_id` that holds it after — null for in-house — the `trigger_contract_id` of the terminated contract whose cascade produced it, a `reason_code` of `TERMINATION_FOR_CAUSE`, `TERMINATION_CONVENIENCE` or `TERMINATION_NON_RENEWAL` mirroring the termination reason, the `application_status_at_transition` observed at the moment of the move, and `disclosure_reset`, which is always true because the transition necessarily invalidates the prior agent-relationship disclosure. File-transition records may be listed and filtered on `application_id`, `from_agency_id`, `to_agency_id`, `trigger_contract_id` and `reason_code`.
3. Ledger entries are selected for forfeiture. The candidates are that contract's `ACCRUAL` entries whose `state` is `ACCRUED` or `APPROVED`, processed in order of `milestone_event_date` ascending with ties broken by `created_at` ascending. If the `reason_code` is `FOR_CAUSE`, every candidate is forfeited — nothing vests when the university terminates for cause. Otherwise a candidate is kept exactly when its producing application's `status` is `ENROLLED`, `CENSUS_CONFIRMED` or `PERSISTED`, because enrollment is what vests a commission, and every other candidate is forfeited. Each forfeiture records a `void_reason` formed by prefixing the reason code with `TERMINATION_` — `TERMINATION_FOR_CAUSE`, `TERMINATION_CONVENIENCE` or `TERMINATION_NON_RENEWAL`. Entries already in `PAID` are never forfeited; paid money is recovered only through the withdrawal clawback ledger. Entries in `CLAWED_BACK`, `FORFEITED` or `VOID` are left untouched.
4. The agency's `net_earned_commission_cents` is recomputed in full from the surviving rows.

When the `reason_code` is `FOR_CAUSE`, one further consequence follows: the agency's `compliance_posture` moves to `DEBARRED`, which itself suspends that agency's other contracts in `ACTIVE` as described in §3.8.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence — registering an agency, creating a program, drafting a contract, appending a rate card or a territory assignment, opening a student file, uploading a document, filing an incident, or running a scorecard — return `201 Created`. Every other operation, including all state transitions, all dispositions, all computed reads, all list and detail reads, and the logical-clock capability, returns `200 OK`. Request bodies, response bodies and side effects are specified in §2 and §3; the table below fixes only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/recruitment/agencies` | Register a prospective recruitment agency | RecruitmentOfficer |
| GET | `/recruitment/agencies/{id}` | Read one agency, including both risk figures and both ledger aggregates | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, Registrar, AgencyOwner |
| GET | `/recruitment/agencies` | List agencies with filtering and pagination | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer |
| PATCH | `/recruitment/agencies/{id}` | Update due-diligence checklist fields on an agency not yet cleared | RecruitmentOfficer, AgencyOwner |
| POST | `/recruitment/agencies/{id}/vetting` | Drive the due-diligence dimension | RecruitmentOfficer, ComplianceOfficer |
| POST | `/recruitment/agencies/{id}/posture-actions` | Manual compliance-posture action | ComplianceOfficer |
| GET | `/recruitment/agencies/{id}/risk-profile` | Computed read of both risk variants side by side | RecruitmentOfficer, ComplianceOfficer |
| POST | `/recruitment/agencies/{id}/training-certifications` | Record completion of a training module | RecruitmentOfficer, ComplianceOfficer |
| GET | `/recruitment/agencies/{id}/training-certifications` | List an agency's certifications | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/recruitment/agencies/{id}/scorecards` | Run the performance scorecard over a closed window | RecruitmentOfficer |
| GET | `/recruitment/agencies/{id}/scorecards` | List an agency's scorecards | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/recruitment/programs` | Create a program with its tuition base and milestone dates | RecruitmentOfficer |
| GET | `/recruitment/programs/{id}` | Read one program | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, Registrar, AgencyOwner |
| POST | `/recruitment/contracts` | Draft a contract for an agency | RecruitmentOfficer |
| GET | `/recruitment/contracts/{id}` | Read one contract | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| GET | `/recruitment/contracts` | List contracts filtered by agency and status | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| POST | `/recruitment/contracts/{id}/lifecycle` | Negotiation and suspension actions | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/recruitment/contracts/{id}/terminate` | Terminate a contract and transition in-flight student files | ComplianceOfficer |
| POST | `/recruitment/contracts/{id}/territory-assignments` | Assign a recruitment territory for a half-open date interval | RecruitmentOfficer |
| GET | `/recruitment/contracts/{id}/territory-assignments` | List the territories of one contract | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/recruitment/contracts/{id}/territory-assignments/{assignment_id}/release` | Release a territory assignment immediately | RecruitmentOfficer, ComplianceOfficer |
| POST | `/recruitment/contracts/{id}/commission-schedules` | Append the next rate card; concurrency-guarded on the contract version | RecruitmentOfficer |
| GET | `/recruitment/contracts/{id}/commission-schedules` | List the rate cards of one contract in tiling order | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| GET | `/recruitment/territory-occupancy` | Computed read of territory occupancy for one country at one instant | RecruitmentOfficer, ComplianceOfficer |
| POST | `/recruitment/applications` | Create a draft student application | AgencyOwner |
| GET | `/recruitment/applications/{id}` | Read one application | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, Registrar, AgencyOwner |
| GET | `/recruitment/applications` | List applications by their foreign keys and status | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, Registrar, AgencyOwner |
| POST | `/recruitment/applications/{id}/disclosure` | Issue or acknowledge the agent-relationship disclosure | RecruitmentOfficer, AgencyOwner, Applicant |
| POST | `/recruitment/applications/{id}/submit` | Submit the application through the eleven-precondition gate | AgencyOwner |
| POST | `/recruitment/applications/{id}/decision` | Admissions decision on a submitted application | RecruitmentOfficer |
| POST | `/recruitment/applications/{id}/milestones` | Register the next enrollment milestone; concurrency-guarded on the application version | Registrar |
| POST | `/recruitment/applications/{id}/withdraw` | Record a student withdrawal and run the clawback ledger | Registrar |
| GET | `/recruitment/applications/{id}/commission-projection` | Computed read of both entitlement variants side by side | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| POST | `/recruitment/applications/{id}/documents` | Upload a supporting document and score its fraud signals | AgencyOwner |
| GET | `/recruitment/applications/{id}/documents` | List the documents of one application | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| GET | `/recruitment/documents/{id}` | Read one supporting document | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/recruitment/documents/{id}/verification` | Record a verification outcome | ComplianceOfficer |
| POST | `/recruitment/integrity-incidents` | File an integrity incident against an agency | RecruitmentOfficer, ComplianceOfficer |
| GET | `/recruitment/integrity-incidents/{id}` | Read one incident | RecruitmentOfficer, ComplianceOfficer |
| GET | `/recruitment/integrity-incidents` | List incidents with filtering and pagination | RecruitmentOfficer, ComplianceOfficer |
| POST | `/recruitment/integrity-incidents/{id}/resolution` | Adjudicate an incident | ComplianceOfficer |
| GET | `/recruitment/commission-entries/{id}` | Read one ledger entry | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| GET | `/recruitment/commission-entries` | List ledger entries with filtering and pagination | RecruitmentOfficer, ComplianceOfficer, FinanceOfficer, AgencyOwner |
| POST | `/recruitment/commission-entries/{id}/disposition` | Approve, pay or void a ledger entry | FinanceOfficer |
| GET | `/recruitment/file-transitions/{id}` | Read one student-file transition record | RecruitmentOfficer, ComplianceOfficer |
| GET | `/recruitment/file-transitions` | List student-file transition records | RecruitmentOfficer, ComplianceOfficer, AgencyOwner |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the epoch sweep | RecruitmentOfficer, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_AGENCY_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_AGENCY_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_TRANSITION_NOT_FOUND` | 404 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_INVALID_VETTING_STATE` | 409 |
| `ERR_INVALID_CONTRACT_STATE` | 409 |
| `ERR_INVALID_POSTURE_ACTION` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_DOCUMENT_STATE` | 409 |
| `ERR_INVALID_ENTRY_STATE` | 409 |
| `ERR_INVALID_INCIDENT_STATE` | 409 |
| `ERR_MILESTONE_OUT_OF_ORDER` | 409 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 409 |
| `ERR_DISCLOSURE_VERSION_STALE` | 409 |
| `ERR_DISCLOSURE_TOKEN_INVALID` | 403 |
| `ERR_AGENCY_NOT_CLEARED` | 422 |
| `ERR_AGENCY_POSTURE_BLOCKED` | 422 |
| `ERR_TRAINING_LAPSED` | 422 |
| `ERR_TRAINING_SCORE_INSUFFICIENT` | 422 |
| `ERR_IDENTITY_DOCUMENT_UNVERIFIED` | 422 |
| `ERR_FRAUD_HOLD_ACTIVE` | 422 |
| `ERR_INCENTIVE_COMPENSATION_PROHIBITED` | 422 |
| `ERR_DUE_DILIGENCE_INCOMPLETE` | 422 |
| `ERR_TERRITORY_NOT_COVERED` | 422 |
| `ERR_SCHEDULE_NOT_EFFECTIVE` | 422 |
| `ERR_SUCCESSOR_NOT_ELIGIBLE` | 422 |
| `ERR_TERRITORY_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_TERRITORY_CAPACITY_EXCEEDED` | 409 |
| `ERR_SCHEDULE_INTERVAL_CONFLICT` | 409 |
| `ERR_SCHEDULE_GAP` | 409 |
| `ERR_TERM_WINDOW_INVALID` | 422 |
| `ERR_MILESTONE_DATE_INVALID` | 422 |
| `ERR_CENSUS_DATE_NOT_REACHED` | 422 |
| `ERR_PERSISTENCE_DATE_NOT_REACHED` | 422 |
| `ERR_FUTURE_DATE_NOT_ALLOWED` | 422 |
| `ERR_AMENDMENT_LIMIT_REACHED` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_EXCLUSIVITY_NOT_PERMITTED` | 422 |
| `ERR_COMMISSION_CAP_EXCEEDED` | 422 |
| `ERR_CLAWBACK_LIABILITY_UNSETTLED` | 422 |

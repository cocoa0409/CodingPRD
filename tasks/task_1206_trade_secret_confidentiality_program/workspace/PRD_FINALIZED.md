# Trade Secret & Confidentiality Program API — Product Requirements Document

## 1. Introduction

Trade secrets lose their legal protection the moment a court decides their owner failed to take "reasonable measures" to keep them secret. For a corporate IP counsel office, that standard is unforgiving: protection must be documented before it is needed, confidentiality obligations must be tracked counterparty by counterparty, departing employees must be walked through a defensible offboarding gauntlet, and every third-party disclosure must leave a marked, hashed, sealed copy behind. When misappropriation is suspected, the difference between a credible demand letter and an embarrassing one is the quality of the records produced under pressure.

This document specifies the Trade Secret & Confidentiality Program API, the system of record for that entire discipline. It governs the trade-secret asset register and the reasonable-measures documentation attached to each asset; the full lifecycle of NDAs and their obligations; employee onboarding acknowledgments, training currency, and need-to-know access provisioning; third-party disclosure approval with version-pinned risk scoring; exit interviews, departing-employee forensic reviews, and demand letters; and litigation readiness through preservation notices, sealed evidence, and clean-desk audits. All resources are mounted under a flat `/api` namespace — sixteen peer resource types joined by references rather than nested ownership — and every deadline, expiry, and trailing-window rule in the system is evaluated against a single controllable logical clock, so that counsel and security operations can rehearse time-driven behavior deterministically rather than wait for the calendar.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The program recognizes six roles, spelled exactly as follows: `IPCounsel`, `SeniorCounsel`, `HRPartner`, `SecurityOfficer`, `Employee`, and `CounterpartyRep`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted for the target endpoint — or for the specific transition requested on that endpoint — is rejected with `ERR_UNAUTHORIZED_ROLE`.

The four staff roles carry opaque identities. When `X-User-Role` is `IPCounsel`, `SeniorCounsel`, `HRPartner`, or `SecurityOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `implemented_by_user_id` on a measure, `verified_by_user_id` on a verified measure, `approved_by_user_id` on a grant or letter, `drafted_by_user_id` on a letter, or `reviewed_by_counsel_id` on a forensic review) but it never compares that value to any entity's `id`.

The two self-service roles are entity-backed. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an employee — an acknowledgment's `employee_id`, a disclosure request's `requester_employee_id`, a grant's `employee_id`, a training assignment's `employee_id` — compare that field to `X-User-ID`. When `X-User-Role` is `CounterpartyRep`, `X-User-ID` is the `id` of the acting `Counterparty`, and ownership checks compare the NDA's `counterparty_id` to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Both appear on every list endpoint described in §3 and §4.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity and Common Properties

All sixteen resource types in this program — SecretAsset, ReasonableMeasure, Counterparty, NdaAgreement, NdaObligation, Employee, Acknowledgment, ExitInterview, AccessGrant, DisclosureRequest, ForensicReview, DemandLetter, PreservationNotice, EvidenceItem, TrainingAssignment, and CleanDeskAudit — carry the same four system-managed properties:

- **`id` (string):** a server-minted UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by one on every mutation of the resource. Two write operations additionally mutate a *parent* resource's version as part of their own semantics — updating an asset's descriptive record increments the asset's `version` by one, and recording an amendment against an NDA increments the superseded NDA's `version` by one — because both are the points where optimistic concurrency is enforced (§2.6).

### 2.5. The Program Clock and the Scheduled Sweep

Time in this system is logical, not wall-clock. Before any operator touches it, the server clock reads exactly `2026-05-01T00:00:00Z`. An `IPCounsel` operator may advance it through an admin-only test-driving capability that accepts a target instant `to_iso8601` and answers with the echoed `now_iso8601`; every deadline, expiry, window, and trailing-period rule in this document evaluates against that logical clock. A computed program-status read returns the `current_policy_version` (which starts at the string `"v1"` at server initialization), the current clock as `now_iso8601`, and per-entity status `counts`.

Clock-driven transitions never fire on their own. They run inside an explicit, ops-run checkpoint — the program sweep, available to `IPCounsel` and `SecurityOfficer` — which advances all due transitions in one fixed class order: first NDAs expire, then obligations go overdue, then grants expire, then training assignments go overdue, then acknowledgments expire, and finally demand letters go ignored. Within each class, rows are processed in `created_at` ascending order. The sweep response reports how many rows moved in each class: `ndas_expired`, `obligations_overdue`, `grants_expired`, `trainings_overdue`, `acks_expired`, and `letters_ignored`.

Every clock comparison the sweep performs is strict. An NDA whose `expiry_date` equals the current clock stays `ACTIVE`; an obligation whose `due_at` equals the current clock stays `PENDING`; a training assignment whose `due_at` equals the current clock stays `ASSIGNED`; a grant whose `expires_at` equals the current clock is not yet expired; an acknowledgment is expired only when the clock has passed its `due_at`; and a demand letter is ignored only when the clock has passed its `response_deadline`.

### 2.6. Optimistic Concurrency Control

Two write operations in the program are guarded by optimistic concurrency control, and both use the same mechanism: the request must carry the client-observed `version` of the parent resource, and if that value does not match the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating a SecretAsset's descriptive record requires the non-optional field `expected_asset_version`, carrying the asset version the client last read. Because a descriptive update on a `REGISTERED` asset is otherwise legitimate for any later writer, the stale view — not any state precondition — is the only thing that can reject it. Creating an amendment NDA against an existing agreement requires the non-optional field `expected_superseded_nda_version`, carrying the version of the NDA being superseded; if that agreement's version has advanced since the client last observed it — a breach-allegation loop recorded in the meantime, for instance — the amendment is refused, because amendment legitimately supersedes the prior agreement and a stale basis must not silently do so. Endpoints not named here do not take a version field.

### 2.7. Reasonable-Measures Scoring and the Protection Posture

Every asset carries two computed scores and a computed posture, all recomputed whenever a measure of that asset changes state, when the asset is registered, and when the asset is retired. Each measure has a `weight_points` constant determined by its `measure_type`: a `POLICY` measure weighs 10 points, `TRAINING` 10, `PHYSICAL` 15, `CONTRACTUAL` 20, and `TECHNICAL` 25. Each measure also has a `points_effective` value: its weight multiplied by 1.0 while `VERIFIED`, by 0.6 while `IMPLEMENTED`, and by 0 in any other status (`PLANNED`, `LAPSED`, or `ABANDONED`).

The operational variant, `score_operational`, sums `points_effective` across all of the asset's measures — verified measures count at full weight, implemented-but-unverified measures count at sixty percent, and everything else counts zero. The documentary variant, `score_documentary`, sums the weight of `VERIFIED` measures only: implemented-but-unverified measures are not court-presentable, so identical rows always yield a documentary score equal to or lower than the operational one. Both scores are rounded half-up to two decimal places (all weights are integers, so products are exact and the rounding is a representation rule). The posture derivation uses the operational variant alone: `protection_posture` is `STRONG` when the operational score reaches 70 or more, `ADEQUATE` when it is at least 40 but below 70, and `DEFICIENT` below 40.

The two variants answer different questions. The operational score drives the posture and every gate that reads the posture — disclosure approval above all — while the documentary score exists for litigation-readiness reporting (§3.1).

### 2.8. Counterparty Exposure and Risk Tiering

Each counterparty carries two computed exposure indexes and a computed `risk_tier`. The indexes accumulate integer points from three event types: each obligation of the counterparty's NDAs currently in `ESCALATED` status contributes 25 points when its `escalated_at` timestamp falls inside the trailing 365-day window; each obligation currently `OVERDUE` contributes 10 points, counted at the present moment with no window applied; and each disclosure under one of the counterparty's NDAs that has reached `EXECUTED` contributes 5 points when its execution time falls inside the trailing window. The window is the closed interval from 365 days before the current clock through the current clock, inclusive at both ends — an event exactly 365 days old still counts.

The trailing variant, `exposure_index_trailing`, is the sum of those in-window points, capped at 100. The lifetime variant, `exposure_index_lifetime`, applies the same point values with no time window at all: every escalated obligation and every executed disclosure counts regardless of age, so once any event is older than a year the lifetime index reads equal to or higher than the trailing one. Points are integers; no rounding is involved. The `risk_tier` derives from the trailing variant alone: `LOW` below 30 points, `MEDIUM` from 30 up to but not including 60, and `HIGH` at 60 or more — so an index of exactly 30 is `MEDIUM` and exactly 60 is `HIGH`. Indexes and tier are recomputed on every obligation escalation, fulfillment, waiver, or overdue transition, on NDA termination and expiry, on disclosure execution, on counterparty state changes, and as part of the sweep.

### 2.9. Segregation of Duties and Ownership Discipline

The program enforces a strict segregation-of-duties model: the actor who performs one side of a controlled step may not perform the other. A measure's implementer may not verify it; a demand letter's drafter may not approve it; a disclosure's requester may not approve it; and a grant's requester may not approve it. Each such attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. Ownership rules are the mirror image: an employee signs only their own acknowledgment, completes only their own training assignments, and submits or withdraws only their own disclosure requests; a counterparty representative executes NDAs and fulfills obligations only for their own organization; and an employee may request an access grant only for themself. Violations are rejected with `ERR_OWNERSHIP_REQUIRED`.

### 2.10. Cascades, Ordering, and Referential Consistency

One business event frequently mutates many rows, and every such cascade is immediate: the mutation and all of its downstream effects are visible in the same response and in any subsequent read. Whenever a single transition touches many rows of the same entity type — retiring an asset and abandoning its measures, barring a counterparty and terminating its NDAs, publishing a policy and superseding signed acknowledgments, lapsing linked measures from an audit — the affected rows are processed in `created_at` ascending order, never by `id`.

Derived fields are reconciled, never stored stale. When a child row changes in a way that feeds a parent's computed field — a measure transition feeding an asset's scores and posture, an obligation transition feeding an NDA's obligation counts and a counterparty's exposure indexes, a grant transition feeding an asset's `active_grant_count`, a training transition feeding an employee's `training_current` — the parent is recomputed as part of the same operation.

Resource addressing is flat under `/api`, so most requests carry exactly one path identifier, occasionally followed by a fixed action segment. Every identifier in a request must resolve: path ids are validated before body identifiers, and a body foreign key that names a nonexistent asset, employee, NDA, obligation, review, letter, notice, evidence item, training assignment, audit, measure, disclosure, or counterparty is rejected with `ERR_NOT_FOUND` (HTTP 404). Existence always outranks state and business rules (§2.12).

### 2.11. Precision, Rounding, and Monetary Conventions

Economic exposure and damages are integer cents, never fractional: `exposure_estimate_cents` is a non-negative integer, and letter damages are computed and stored as whole cents (§3.7 pins the rounding order). The two reasonable-measures scores are rounded half-up to two decimal places. The disclosure risk score is rounded half-up to one decimal place, and its final variant is clamped to the range from 0 through 100 before rounding. Counterparty exposure points are integers with no rounding. Datetimes are compared and stored at second precision; calendar arithmetic (survival periods, anchoring windows, validity windows) uses calendar months or whole days as each rule states. Datetime fields that the server stamps at the current clock or computes — for example `terminated_at`, `sealed_at`, `issued_at`, `signed_at`, `completed_at`, `fulfilled_at`, `escalated_at`, `notice_given_at`, `departed_at`, `conducted_at`, an anchored or auto-assigned `due_at`, `response_deadline`, and `confidentiality_end` — are rendered in the same ISO 8601 UTC form with exactly three fractional digits as `created_at` and `updated_at` (§2.4).

### 2.12. Validation Priority

When a single request violates several rules, the error surfaced is the one from the earliest applicable category below — lower numbers win. First (1) authentication: `X-User-Role` and `X-User-ID` present and the role declared, else `ERR_UNAUTHENTICATED`. Second (2) role authorization, including per-transition role gates such as crown-jewel grant approval requiring `IPCounsel` and letter approval requiring `SeniorCounsel`, else `ERR_UNAUTHORIZED_ROLE`. Third (3) ownership and segregation-of-duties identity rules, else `ERR_OWNERSHIP_REQUIRED` or `ERR_SEGREGATION_OF_DUTIES`. Fourth (4) existence of every path id and body foreign key, else `ERR_NOT_FOUND`. Fifth (5) optimistic-concurrency version matches, else `ERR_STALE_VERSION`. Sixth (6) state-machine preconditions: the transition must be defined from the current state and entity-level state gates must hold, else `ERR_INVALID_STATE`. Seventh (7) classification, need-to-know, and preservation safety gates, else `ERR_NEED_TO_KNOW_VIOLATION`, `ERR_CLASSIFICATION_CEILING_EXCEEDED`, `ERR_POSTURE_DEFICIENT`, `ERR_PRESERVATION_HOLD_ACTIVE`, `ERR_DISCLOSURE_RISK_TOO_HIGH`, or `ERR_ENDORSEMENT_REQUIRED`. Eighth (8) time-window rules, else `ERR_DATE_ORDER`, `ERR_EXPIRY_IN_PAST`, `ERR_REVIEW_WINDOW_EXPIRED`, `ERR_NDA_WINDOW_OVERLAP`, `ERR_AUDIT_WINDOW_CONFLICT`, or `ERR_INTERVIEW_OVERLAP`. Ninth (9) referenced-entity state gates — NDA active, counterparty active, pinned versions current, acknowledgment signed on the current policy, exit interview certified, grants cleared, reviews concluded — else `ERR_NDA_NOT_ACTIVE`, `ERR_COUNTERPARTY_NOT_ACTIVE`, `ERR_STALE_REFERENCE`, `ERR_ACK_REQUIRED`, `ERR_POLICY_VERSION_STALE`, `ERR_EXIT_INTERVIEW_NOT_CERTIFIED`, `ERR_ACTIVE_GRANTS_REMAIN`, or `ERR_REVIEW_NOT_CONCLUDED`. Tenth (10) aggregate and field-constraint rules — training currency, measure evidence, marking evidence, findings arithmetic, claim lines, hash format, email uniqueness — else `ERR_TRAINING_NOT_CURRENT`, `ERR_MEASURE_EVIDENCE_REQUIRED`, `ERR_MARKING_EVIDENCE_REQUIRED`, `ERR_INVALID_HASH`, `ERR_INVALID_REQUEST`, or `ERR_DUPLICATE_EMAIL`.

## 3. Business Logic & Workflows

### 3.1. The Secret Asset Register and Its Reasonable Measures

Counsel opens the register by drafting a **SecretAsset** with a human-readable `title`, a `description` that characterizes the secret without containing any secret content itself, a `classification` of `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`, or `CROWN_JEWEL` (in ascending sensitivity), the accountable `owner_department`, and an `exposure_estimate_cents` — a non-negative integer estimate of the economic exposure if the asset is misappropriated, which later feeds demand-letter damages. New assets start in `DRAFT` with both scores at zero, `protection_posture` of `DEFICIENT`, and an `active_grant_count` of zero. Registration — moving the asset from `DRAFT` to `REGISTERED` — requires that a `classification` be set and triggers the first recomputation of both score variants and the posture. The register can be browsed with filters on `classification`, `status`, or `protection_posture`.

Descriptive upkeep is an OCC-guarded write (§2.6): the caller presents `expected_asset_version` together with any of `title`, `description`, `classification`, or `exposure_estimate_cents`. A successful update increments the asset's `version` by one. Changing `classification` is deliberately consequential — disclosure requests that pinned the asset at submission now hold a stale pin and will fail re-validation at approval time (§3.5). A litigation-readiness posture report, available to counsel, returns the asset's `id`, both `score_operational` and `score_documentary`, the `protection_posture`, and a per-measure breakdown carrying each measure's `weight_points` and `points_effective`.

An asset may be suspended and reactivated freely: `REGISTERED → SUSPENDED → REGISTERED` is an unrestricted loop, but while `SUSPENDED` the asset refuses new access-grant requests and new disclosure drafts. Retirement is the guarded exit. Moving `REGISTERED → RETIRED` (or `SUSPENDED → RETIRED`) requires three conditions: the asset's `active_grant_count` must be zero, otherwise `ERR_ACTIVE_GRANTS_REMAIN`; no disclosure request for the asset may sit in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED`, otherwise `ERR_INVALID_STATE`; and no preservation notice in `DRAFT`, `ISSUED`, or `ACTIVE` may list the asset in its `asset_ids`, otherwise `ERR_PRESERVATION_HOLD_ACTIVE`. Retiring cascades: every measure of the asset in `PLANNED`, `IMPLEMENTED`, `VERIFIED`, or `LAPSED` moves to `ABANDONED` in `created_at` ascending order, and both score variants are recomputed to zero along with the posture. `RETIRED` is terminal.

**ReasonableMeasure** rows are the evidentiary spine of the register. A `SecurityOfficer` or `IPCounsel` documents a measure against an `asset_id` with a `measure_type` of `POLICY`, `TRAINING`, `PHYSICAL`, `CONTRACTUAL`, or `TECHNICAL`, a `title`, and optionally an `evidence_uri` pointing at documentary evidence; the row starts `PLANNED` and the parent asset's scores and posture recompute. The measures collection is filterable by `asset_id`, `status`, and `measure_type`.

Marking a measure implemented — `PLANNED → IMPLEMENTED` — requires a non-empty `evidence_uri`, otherwise `ERR_MEASURE_EVIDENCE_REQUIRED`, and requires the parent asset to be in `DRAFT` or `REGISTERED`, otherwise `ERR_INVALID_STATE`; the transition stamps `implemented_by_user_id` with the actor's `X-User-ID` and recomputes the measure's `points_effective` plus the parent scores and posture. Verification — `IMPLEMENTED → VERIFIED` — is counsel's step and enforces segregation of duties: the verifier's `X-User-ID` must differ from `implemented_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; success stamps `verified_by_user_id` and recomputes. A measure lapses either by deliberate counsel action or as audit fallout (§3.9): `VERIFIED → LAPSED` and `IMPLEMENTED → LAPSED` both zero its effective points and recompute the parent's scores and posture, and if that recompute drops the asset's posture to `DEFICIENT`, every disclosure request for that asset sitting in `UNDER_REVIEW` is returned to `RETURNED` in `created_at` ascending order. Lapsed measures can be remediated through the loop `LAPSED → IMPLEMENTED → VERIFIED`; re-implementation carries the same evidence and asset-state preconditions as the original implementation and re-stamps `implemented_by_user_id`. Measures in `PLANNED` or `LAPSED` may also be abandoned outright, recomputing the parent's scores; `ABANDONED` is terminal.

### 3.2. Counterparties, NDAs, and Obligation Tracking

A **Counterparty** is registered with its `legal_name` and a `counterparty_type` of `VENDOR`, `PARTNER`, `CUSTOMER`, or `CONSULTANT`; it starts `ACTIVE` with both exposure indexes at zero and `risk_tier` of `LOW`. The counterparties list accepts `status` and `risk_tier` filters. Suspending a counterparty (`ACTIVE → SUSPENDED`) blocks the drafting of new NDAs for it and blocks new disclosure requests referencing it, and the loop back to `ACTIVE` restores both. Barring — `ACTIVE → BARRED` or `SUSPENDED → BARRED` — is the decisive break: every NDA of the counterparty in `DRAFT`, `SENT`, `EXECUTED`, `ACTIVE`, or `BREACH_ALLEGED` is terminated with its `terminated_at` stamped at the current clock, processed in `created_at` ascending order; each of those terminations anchors its still-open return obligations (see below); and every disclosure request governed by one of those NDAs in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` is rejected outright, moving to `REJECTED`. The counterparty's exposure indexes and `risk_tier` recompute as part of the cascade. `BARRED` is terminal.

An **NdaAgreement** is drafted by counsel with the signing `counterparty_id`, a `template_version`, the `governing_law` string, an `effective_date` and `expiry_date` bounding the agreement window, a `survival_months` confidentiality tail of zero or more whole months, and a `classification_ceiling` — the highest asset classification shareable under the agreement, again one of `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`, or `CROWN_JEWEL`. The expiry must fall strictly after the effective date, otherwise `ERR_DATE_ORDER`, and `survival_months` must not be negative. Windows are closed intervals: the new window may not overlap any other non-terminal NDA of the same counterparty — one in `DRAFT`, `SENT`, `EXECUTED`, `ACTIVE`, or `BREACH_ALLEGED` — with touching boundary dates counting as overlap, otherwise `ERR_NDA_WINDOW_OVERLAP`. Drafting also requires the counterparty to be `ACTIVE`, otherwise `ERR_COUNTERPARTY_NOT_ACTIVE`. A fresh agreement starts in `DRAFT` with `supersedes_id` unset, and the NDAs list can be filtered by `counterparty_id`, `supersedes_id`, or `status`.

Amendment is the one sanctioned exception to the overlap rule. Creating an amendment against an existing agreement — an OCC-guarded write presenting `expected_superseded_nda_version` alongside fresh `template_version`, `governing_law`, `effective_date`, `expiry_date`, `survival_months`, and `classification_ceiling` — requires the target to be in `ACTIVE` or `BREACH_ALLEGED`, otherwise `ERR_INVALID_STATE`. The new agreement starts in `DRAFT` with its `supersedes_id` pointing at the target; the superseded agreement's `version` increments by one, since amendment linkage is itself a mutation of the parent; and the amendment's window may overlap the agreement it supersedes, though no other non-terminal NDA of the same counterparty.

The NDA lifecycle runs `DRAFT → SENT → EXECUTED → ACTIVE`. Sending is counsel's step; execution belongs to the counterparty's representative, whose `X-User-ID` must equal the agreement's `counterparty_id`, otherwise `ERR_OWNERSHIP_REQUIRED`. Activation is counsel's step, and activating an amendment cascades: the agreement named by `supersedes_id` moves to `SUPERSEDED`. From `ACTIVE`, counsel may record a breach allegation — `ACTIVE → BREACH_ALLEGED` — and later close an unfounded allegation by returning `BREACH_ALLEGED → ACTIVE`; the loop touches neither obligations nor disclosures. Termination is available from either `ACTIVE` or `BREACH_ALLEGED` (a founded allegation): it stamps `terminated_at` at the current clock, anchors every still-open return obligation, and recomputes the counterparty's exposure indexes and tier. Expiry is the sweep's work: an agreement still `ACTIVE` once the clock is strictly later than its `expiry_date` moves to `EXPIRED`, anchors its open return obligations against the expiry date, and likewise recomputes exposure. The computed `confidentiality_end` — `expiry_date` plus `survival_months` calendar months — records how long confidentiality outlives the agreement. `SUPERSEDED`, `TERMINATED`, and `EXPIRED` are terminal.

Each agreement tracks four computed obligation counters: `obligations_total_count` over all of its obligations, `obligations_open_count` over those in `PENDING`, `OVERDUE`, or `ESCALATED`, `obligations_fulfilled_count`, and `obligations_waived_count`. The open, fulfilled, and waived buckets always sum to the total; fulfilling or waiving moves a row between buckets without changing the total.

An **NdaObligation** is added to an agreement with its `nda_id`, an `obligation_type` of `NON_DISCLOSURE`, `NON_USE`, `RETURN_OR_DESTROY`, `NO_REVERSE_ENGINEERING`, or `AUDIT_RIGHT`, and an optional `due_at`; return-or-destroy rows are always created with `due_at` empty and receive their deadline only when the parent agreement ends. Obligations start `PENDING`, and the parent NDA's counters recompute on creation and on every transition. Obligation tracking works by counterparty as well as by agreement: the obligations list filters by `nda_id`, `counterparty_id`, `status`, or `obligation_type`.

Fulfillment belongs to the counterparty's representative — from `PENDING`, `OVERDUE`, or `ESCALATED` alike — with the same ownership rule as execution: `X-User-ID` must equal the parent NDA's `counterparty_id`, otherwise `ERR_OWNERSHIP_REQUIRED`. Fulfilling stamps `fulfilled_at` at the current clock and recomputes both the NDA's counters and the counterparty's exposure. Counsel may waive a `PENDING` or `OVERDUE` obligation, which recomputes the NDA's counters; `FULFILLED` and `WAIVED` are terminal. The sweep moves a `PENDING` obligation to `OVERDUE` once the clock is strictly later than a non-empty `due_at`, recomputing exposure; counsel escalates an `OVERDUE` obligation to `ESCALATED`, stamping `escalated_at` and recomputing exposure again. The anchoring rule closes the loop: when an agreement terminates, each of its `PENDING` return-or-destroy obligations with an empty `due_at` receives `terminated_at` plus thirty days; when it expires, the same rows receive `expiry_date` plus thirty days.

### 3.3. Employee Onboarding, Policy Acknowledgment, and Training Currency

An **HRPartner** onboards an **Employee** record with `full_name`, `email`, `department`, `role_title`, an `access_clearance` of `STANDARD`, `ELEVATED`, or `PRIVILEGED`, and the `hired_at` timestamp. Email is unique across employees; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. Creation cascades immediately: a fresh **Acknowledgment** for the employee is issued at the program's current policy version, and a `BASIC_TS` **TrainingAssignment** is auto-assigned with its `due_at` set thirty days after `hired_at`. New employees start in `PREBOARDING`, and the employees list filters by `department`, `status`, or `access_clearance`.

The acknowledgment is the preboarding gate. Each **Acknowledgment** carries the `employee_id`, the `policy_version` stamped from the program's `current_policy_version` at issuance, and a computed `due_at` ten days after creation; it starts `PENDING` with `signed_at` empty. Signing belongs to the employee themself — `X-User-ID` must equal the acknowledgment's `employee_id`, otherwise `ERR_OWNERSHIP_REQUIRED` — and only an acknowledgment whose `policy_version` still matches the program's current version can be signed, otherwise `ERR_POLICY_VERSION_STALE`; signing stamps `signed_at` and moves the row to `SIGNED`. Activation of the employee — `PREBOARDING → ACTIVE` — requires a `SIGNED` acknowledgment on the current policy version to exist, otherwise `ERR_ACK_REQUIRED`. When an acknowledgment lapses unsigned, HR may manually issue a fresh `PENDING` one for the `employee_id`, again stamped at the current policy version and due ten days out. The acknowledgments list filters by `employee_id`, `status`, or `policy_version`.

Policy republication is the program-level cascade that keeps acknowledgments honest. Publishing requires a `new_version` that differs from the `current_policy_version`, otherwise `ERR_INVALID_REQUEST`. On publish, every `SIGNED` acknowledgment whose `policy_version` differs from the new version moves to `SUPERSEDED` in `created_at` ascending order; `PENDING` rows are deliberately left in place at the old version, where they become unsignable via `ERR_POLICY_VERSION_STALE` and eventually expire through the sweep. For every employee in `PREBOARDING`, `ACTIVE`, or `NOTICE` — again in `created_at` ascending order — a fresh `PENDING` acknowledgment is created at the new version, due ten days from the publish moment. The publish response reports the new `current_policy_version`, the `superseded_count`, and the `reissued_count`. The sweep moves any `PENDING` acknowledgment past its `due_at` to `EXPIRED`; `SUPERSEDED` and `EXPIRED` are terminal.

Training assignments are HR-administered rows with an `employee_id`, a `module` of `BASIC_TS`, `CLEAN_DESK`, or `ADVANCED_IP`, and a `due_at`; they start `ASSIGNED` with `completed_at` empty, the list filters by `employee_id`, `module`, or `status`, and creating one recomputes the employee's `training_current` immediately. Completion belongs to the employee themself from `ASSIGNED`, `OVERDUE`, or `ESCALATED` — `X-User-ID` must equal the assignment's `employee_id`, otherwise `ERR_OWNERSHIP_REQUIRED` — and stamps `completed_at`. The sweep moves an `ASSIGNED` row to `OVERDUE` once the clock is strictly later than `due_at`; HR may escalate an `OVERDUE` row to `ESCALATED` or excuse an `ASSIGNED` or `OVERDUE` row to `EXCUSED`. `COMPLETED` and `EXCUSED` are terminal.

Every one of these transitions recomputes the employee's `training_current` flag. That flag is true exactly when two conditions hold: the employee has no training assignment in `OVERDUE` or `ESCALATED` status, and at least one `COMPLETED` `BASIC_TS` assignment exists whose `completed_at` lies within the trailing 365 days. A completion older than a year stops counting, so currency decays on its own as the clock advances.

### 3.4. Need-to-Know Access Provisioning

Access to a registered asset is provisioned per employee, per asset, on a need-to-know basis. An **Employee** requests an **AccessGrant** by naming themself as `employee_id` — `X-User-ID` must equal it, otherwise `ERR_OWNERSHIP_REQUIRED` — together with the target `asset_id`, a written `justification`, and an `expires_at`. The expiry must fall later than the current clock and no more than 365 days out, otherwise `ERR_EXPIRY_IN_PAST`. Creation stamps `requester_user_id` from the caller and starts the grant in `REQUESTED`. Three creation-time gates apply: the asset must be `REGISTERED` and the employee `ACTIVE`, each otherwise `ERR_INVALID_STATE`; and the employee's `access_clearance` must meet the asset's classification requirement — `STANDARD` clearance covers `INTERNAL` and `CONFIDENTIAL` assets, `RESTRICTED` assets require `ELEVATED`, and `CROWN_JEWEL` assets require `PRIVILEGED` — otherwise `ERR_NEED_TO_KNOW_VIOLATION`. The grants list filters by `employee_id`, `asset_id`, or `status`.

Approval is the control point, performed by a `SecurityOfficer` or `IPCounsel` with five checks. If the asset's classification is `CROWN_JEWEL`, only an `IPCounsel` may approve, otherwise `ERR_UNAUTHORIZED_ROLE`. The asset must still be `REGISTERED` and the employee still `ACTIVE`, each otherwise `ERR_INVALID_STATE`. The employee's `training_current` must be true, otherwise `ERR_TRAINING_NOT_CURRENT`. And the approver's `X-User-ID` must differ from `requester_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Approving stamps `approved_by_user_id` and adds one to the asset's `active_grant_count`. Denial — `REQUESTED → DENIED` — is unconditional and terminal.

Provisioning turns approval into live access: `APPROVED → PROVISIONED` is a `SecurityOfficer` step allowed only while the grant's `expires_at` has not passed — a grant whose expiry equals the current clock may still be provisioned — otherwise `ERR_INVALID_STATE`. A provisioned grant may be suspended and reinstated (`PROVISIONED → SUSPENDED → PROVISIONED`) by security; reinstatement carries the same not-yet-expired gate. Revocation — from `APPROVED`, `PROVISIONED`, or `SUSPENDED` — is available to security or counsel and subtracts one from the asset's `active_grant_count`. The sweep expires `APPROVED` and `PROVISIONED` grants once the clock is strictly later than `expires_at`, each decrementing the count by one.

The count itself obeys a compensating invariant: it tallies the asset's grants in `APPROVED`, `PROVISIONED`, or `SUSPENDED` status. A forward approval paired with its compensating revocation returns the count to its prior value; suspending and reinstating never move it; denial never entered it; and sweep-driven expiry of an approved or provisioned grant is the only other decrement. `DENIED`, `REVOKED`, and `EXPIRED` are terminal.

### 3.5. Third-Party Disclosure: Approval, Marking, and Execution

Sharing a secret with a counterparty is the program's most heavily gated workflow. An employee drafts a **DisclosureRequest** naming the `asset_id` to disclose, the governing `nda_id`, the business `purpose`, a `marking_protocol` of `STAMPED_CONFIDENTIAL`, `ORAL_WITH_FOLLOWUP`, or `ENCRYPTED_DELIVERY`, and a `planned_disclosure_date`. Creation stamps `requester_employee_id` from the caller's `X-User-ID` — which must therefore be an employee id — and requires the asset to be `REGISTERED`, otherwise `ERR_INVALID_STATE`. Drafts start in `DRAFT`, and the disclosures list filters by `asset_id`, `nda_id`, `requester_employee_id`, or `status`.

Submitting — `DRAFT → SUBMITTED` — belongs to the requester alone (`ERR_OWNERSHIP_REQUIRED` otherwise) and additionally requires the requester's employee record to be in `PREBOARDING`, `ACTIVE`, or `NOTICE`, otherwise `ERR_INVALID_STATE`. Submission pins the world: `pinned_asset_version` captures the asset's current `version`, `pinned_nda_version` captures the NDA's current `version`, and `risk_score_provisional` is computed for the requester's own visibility. The provisional score is the classification base — 10 for `INTERNAL`, 30 for `CONFIDENTIAL`, 60 for `RESTRICTED`, 90 for `CROWN_JEWEL` — minus the marking credit for the chosen protocol: 10 for `STAMPED_CONFIDENTIAL`, 0 for `ORAL_WITH_FOLLOWUP`, 20 for `ENCRYPTED_DELIVERY`. No counterparty tier multiplier applies at this stage; the result is rounded half-up to one decimal place.

Counsel moves a submission into review — `SUBMITTED → UNDER_REVIEW` — only while the referenced NDA is `ACTIVE`, otherwise `ERR_NDA_NOT_ACTIVE`; the counterparty is `ACTIVE`, otherwise `ERR_COUNTERPARTY_NOT_ACTIVE`; and the NDA's `classification_ceiling` is at least as sensitive as the asset's classification on the ascending `INTERNAL`-to-`CROWN_JEWEL` scale, otherwise `ERR_CLASSIFICATION_CEILING_EXCEEDED`. A senior counsel may endorse a request while it sits in `UNDER_REVIEW`, setting `senior_endorsed` to true; endorsement from any other state is not possible.

Approval — `UNDER_REVIEW → APPROVED` — re-validates everything, because time may have passed since submission. The asset's `protection_posture` must be `ADEQUATE` or `STRONG`, otherwise `ERR_POSTURE_DEFICIENT`. The asset's current `version` must still equal `pinned_asset_version` and the NDA's current `version` must still equal `pinned_nda_version`, otherwise `ERR_STALE_REFERENCE`; this is the intended serialization point that makes descriptive asset edits and NDA amendments visible to the approver. The NDA must still be `ACTIVE` and the counterparty still `ACTIVE`, carrying the same `ERR_NDA_NOT_ACTIVE` and `ERR_COUNTERPARTY_NOT_ACTIVE` codes as the review step. The approver's `X-User-ID` must differ from the requester's, otherwise `ERR_SEGREGATION_OF_DUTIES`.

Approval also computes `risk_score_final`, the enforcement value: the classification base multiplied by the counterparty's current tier multiplier — 1.0 for `LOW`, 1.25 for `MEDIUM`, 1.5 for `HIGH` — minus the marking credit, clamped to the range 0 through 100, and rounded half-up to one decimal place. Identical request data therefore produces a different number whenever the counterparty is no longer `LOW`. Two routing thresholds apply to the final score: a final score of 80 or more requires `senior_endorsed` to be true, otherwise `ERR_ENDORSEMENT_REQUIRED`; and a final score of 95 or more forbids approval outright with `ERR_DISCLOSURE_RISK_TOO_HIGH`.

Rejection (`UNDER_REVIEW → REJECTED`) is unconditional and terminal. Returning (`UNDER_REVIEW → RETURNED`) sends the request back for revision, and the requester reopens it — `RETURNED → DRAFT` — which clears both pins to empty and resets `senior_endorsed` to false, so the loop `DRAFT → SUBMITTED → UNDER_REVIEW → RETURNED → DRAFT` always re-pins and re-scores on the next pass. The requester may also withdraw from `DRAFT`, `SUBMITTED`, or `RETURNED`; `WITHDRAWN` is terminal.

Execution is the evidentiary payoff. Moving `APPROVED → EXECUTED` requires a non-empty `marking_evidence_uri` and a `marking_sha256` of exactly 64 lowercase hexadecimal characters, otherwise `ERR_MARKING_EVIDENCE_REQUIRED`, and it must happen no later than thirty days after the `planned_disclosure_date` — once the clock passes that point the approval is stale and execution fails with `ERR_INVALID_STATE`. Executing seals the marked copy: an **EvidenceItem** is created directly in `SEALED` status with `source` of `MARKED_COPY`, its `disclosure_id` set to this request, its `review_id` empty, its `sha256` taken from `marking_sha256`, and `sealed_at` stamped at the current clock. The counterparty's exposure indexes and `risk_tier` then recompute, because an executed disclosure contributes exposure points (§2.8).

### 3.6. Departure Management, Exit Interviews, and Forensic Review

Giving notice moves an employee `ACTIVE → NOTICE` and requires a `departure_type` of `VOLUNTARY` or `INVOLUNTARY` in the payload, otherwise `ERR_INVALID_REQUEST`; the transition stamps `notice_given_at` and stores the type. An involuntary notice auto-creates a **ForensicReview** for the employee in `OPENED` with `trigger_reason` of `INVOLUNTARY_DEPARTURE`. Notice deliberately does *not* revoke access grants: revocation remains an explicit security or counsel action, which keeps the departure gate below reachable and meaningful.

The exit interview is the employee-facing checkpoint. HR schedules an **ExitInterview** with the `employee_id` and a window bounded by `scheduled_start` and `scheduled_end`; the end must fall strictly after the start, otherwise `ERR_DATE_ORDER`, and the employee must be `ACTIVE` or `NOTICE`, otherwise `ERR_INVALID_STATE`. Windows are half-open intervals for overlap purposes: a new interview whose window overlaps another `SCHEDULED` or `CONDUCTED` interview of the same employee is rejected with `ERR_INTERVIEW_OVERLAP`, while one starting exactly when another ends is permitted. Interviews start in `SCHEDULED`, and the list filters by `employee_id` or `status`.

Conducting the interview — `SCHEDULED → CONDUCTED` — stamps `conducted_at`. A no-show — `SCHEDULED → NO_SHOW` — increments `no_show_count`, which starts at zero, by one, and from `NO_SHOW` the interview can be rescheduled back to `SCHEDULED` with a fresh window (subject to the same overlap check against the employee's other `SCHEDULED` or `CONDUCTED` interviews), or escalated once `no_show_count` reaches at least two, otherwise `ERR_INVALID_STATE`. Between conducting and certifying, HR records two flags on the interview: `return_certification`, the employee's certification that all materials were returned, and `obligations_reiterated`, counsel's reiteration of surviving NDA obligations; both default to false and are set through the interview's update. Certification — `CONDUCTED → CERTIFIED` — requires both flags true, otherwise `ERR_INVALID_REQUEST`. An interview may also be cancelled from `SCHEDULED` or `NO_SHOW`; `CERTIFIED` and `CANCELLED` are terminal.

Departure itself — `NOTICE → DEPARTED` — carries a triple gate: a `CERTIFIED` exit interview must exist for the employee, otherwise `ERR_EXIT_INTERVIEW_NOT_CERTIFIED`; no access grant may remain in `REQUESTED`, `APPROVED`, `PROVISIONED`, or `SUSPENDED`, otherwise `ERR_ACTIVE_GRANTS_REMAIN`; and every forensic review of the employee must have concluded in `CLOSED_NO_ACTION` or `ESCALATED`, otherwise `ERR_REVIEW_NOT_CONCLUDED`. Success stamps `departed_at`; `DEPARTED` is terminal.

Forensic reviews may also be opened manually by HR or counsel with an `employee_id` and a `trigger_reason` of `VOLUNTARY_DEPARTURE`, `INVOLUNTARY_DEPARTURE`, `POLICY`, or `LITIGATION`. Manual opening is allowed while the employee is `ACTIVE` or `NOTICE`, or after departure within a ninety-day window: if the employee is `DEPARTED` and the clock has moved more than 90 days past `departed_at`, creation is rejected with `ERR_REVIEW_WINDOW_EXPIRED`. The reviews list filters by `employee_id`, `status`, or `trigger_reason`.

The review lifecycle belongs first to security: `OPENED → IMAGING`, then `IMAGING → FINDINGS_DRAFTED`, the latter requiring at least one evidence item attached to the review in `COLLECTED` or `SEALED` status, otherwise `ERR_INVALID_STATE`. While the review is in `IMAGING` or `FINDINGS_DRAFTED`, security records findings through the review's update: `exfil_indicator_count`, the number of exfiltration indicators found, defaulting to zero, and `findings_notes`, the narrative, defaulting to empty. Counsel then takes over: `FINDINGS_DRAFTED → COUNSEL_REVIEW` stamps `reviewed_by_counsel_id` with the counsel's `X-User-ID`, and counsel may kick the review back to `FINDINGS_DRAFTED` — the `FINDINGS_DRAFTED ↔ COUNSEL_REVIEW` loop — or close it. Closing with no action (`COUNSEL_REVIEW → CLOSED_NO_ACTION`) ends the matter; escalating (`COUNSEL_REVIEW → ESCALATED`) requires at least one exfiltration indicator on record, otherwise `ERR_INVALID_STATE`. Both `CLOSED_NO_ACTION` and `ESCALATED` are terminal, and only an `ESCALATED` review can seed a demand letter (§3.7).

### 3.7. Demand Letters and the Path to Litigation

When a forensic review escalates, counsel drafts a **DemandLetter** against it. Drafting requires the source `forensic_review_id` to name a review in `ESCALATED` status, otherwise `ERR_INVALID_STATE`; the letter denormalizes its target `employee_id` from the review and stamps `drafted_by_user_id` from the caller. The payload carries `claim_lines` — a non-empty array of entries, each pairing an `asset_id` with a `claim_type` of `CEASE_AND_DESIST`, `RETURN_OF_PROPERTY`, or `PRESERVATION`; an empty array is `ERR_INVALID_REQUEST`, and every referenced asset must exist, otherwise `ERR_NOT_FOUND`, though the asset may be in any status — and `response_deadline_days`, a positive integer of days the recipient has to respond. New letters start in `DRAFTED`, and the letters list filters by `forensic_review_id`, `employee_id`, or `status`.

The letter's `damages_estimate_cents` is computed at drafting with a pinned rounding order. For each claim line, the referenced asset's `exposure_estimate_cents` is multiplied by the claim-type factor — 0.30 for `CEASE_AND_DESIST`, 0.20 for `RETURN_OF_PROPERTY`, 0.15 for `PRESERVATION` — and that product is rounded half-up to whole cents first; the damages estimate is then the sum of the per-line rounded amounts, taken in request order. The alternative order — summing raw products and rounding once — is explicitly not used: an asset with an exposure of 10,001 cents carrying all three claim types yields 3,000 plus 2,000 plus 1,500, totaling 6,500 cents, never the 6,501 that sum-then-round would produce.

Approval enforces segregation of duties: moving `DRAFTED → COUNSEL_APPROVED` is a `SeniorCounsel` step whose `X-User-ID` must differ from `drafted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, and it stamps `approved_by_user_id`. Issuing — `COUNSEL_APPROVED → ISSUED`, again senior counsel — stamps `issued_at` at the current clock and computes `response_deadline` as `issued_at` plus `response_deadline_days` days. Counsel records the recipient's acknowledgment (`ISSUED → ACKNOWLEDGED`) and eventual compliance (`ACKNOWLEDGED → COMPLIED`). The sweep ignores a letter in `ISSUED` or `ACKNOWLEDGED` once the clock is strictly later than `response_deadline`, moving it to `IGNORED`.

Litigation is the escalation off an ignored letter: `IGNORED → LITIGATION`, a senior-counsel step, auto-creates a **PreservationNotice** directly in `ISSUED` status whose `legal_matter_ref` is the prefix `AUTO:` followed by the letter's `id`, whose `review_ids` contains the source forensic review, whose `asset_ids` collects the claim-line asset ids, and whose `employee_ids` contains the letter's target employee. Counsel may instead withdraw a letter from `DRAFTED` or `COUNSEL_APPROVED`; `COMPLIED`, `LITIGATION`, and `WITHDRAWN` are terminal.

### 3.8. Preservation Holds and Evidence Custody

A **PreservationNotice** is the litigation-hold instrument, created by counsel with a `legal_matter_ref` and three optional scope arrays: `asset_ids`, `employee_ids`, and `review_ids`, each of which may be empty at creation. Notices start in `DRAFT`, and the list filters by `status`. Issuing a notice — `DRAFT → ISSUED` — requires at least one of the three arrays to be non-empty, otherwise `ERR_INVALID_REQUEST`; activation — `ISSUED → ACTIVE` — is then unconditional.

While a notice is live, it freezes what it covers. Any notice in `DRAFT`, `ISSUED`, or `ACTIVE` listing an asset blocks that asset's retirement with `ERR_PRESERVATION_HOLD_ACTIVE` (§3.1). Evidence release is narrower: an item whose `review_id` is listed in a notice in `ISSUED` or `ACTIVE` cannot be released, likewise `ERR_PRESERVATION_HOLD_ACTIVE`, and the same block applies to an item whose `disclosure_id` chains to a covered review. Release of the notice itself — `ACTIVE → RELEASED` — is a `SeniorCounsel` step forbidden while any demand letter in `LITIGATION` references a review in the notice's `review_ids`, otherwise `ERR_INVALID_STATE`. `RELEASED` is terminal.

An **EvidenceItem** is collected by security into a review with `review_id`, a `source` of `FORENSIC_IMAGE`, `EMAIL_EXPORT`, `ACCESS_LOG`, `DEVICE_IMAGE`, or `MARKED_COPY`, a `sha256` content hash, and a non-negative `byte_size`. The hash must be exactly 64 lowercase hexadecimal characters, otherwise `ERR_INVALID_HASH`. Every item ultimately carries exactly one owner pointer: `review_id` for items collected into a review, or `disclosure_id` for the sealed marked copy that disclosure execution stamps (§3.5) — `disclosure_id` is never accepted as input, and an item that would carry neither or both is rejected with `ERR_INVALID_REQUEST`. Items start in `COLLECTED`, and the list filters by `review_id`, `disclosure_id`, or `status`.

Sealing — `COLLECTED → SEALED` — is a security step that stamps `sealed_at`; a sealed item's content fields are no longer modifiable. Release — `SEALED → RELEASED` — is counsel's step and carries the preservation blocks described above. `RELEASED` is terminal.

### 3.9. Clean-Desk Audits and Remediation

The clean-desk audit closes the loop between physical inspection and the reasonable-measures register. Security schedules a **CleanDeskAudit** for a `department` with a window bounded by `window_start` and `window_end`; the end must fall strictly after the start, otherwise `ERR_DATE_ORDER`. Departments are buffered resources: a new audit is rejected with `ERR_AUDIT_WINDOW_CONFLICT` when the department already has a non-terminal audit — one in `SCHEDULED`, `CONDUCTED`, `REPORTED`, or `REMEDIATING` — within the required seven-day buffer. Audits start in `SCHEDULED`, and the list filters by `department` or `status`.

Conducting the audit — `SCHEDULED → CONDUCTED` — records `findings_count` and `critical_findings` in the payload alongside `linked_measure_ids`; the totals must satisfy `findings_count` at least `critical_findings` and both non-negative, otherwise `ERR_INVALID_REQUEST`. When critical findings exist, the conduct step cascades: every measure whose `id` appears in `linked_measure_ids` and whose status is `IMPLEMENTED` or `VERIFIED` moves to `LAPSED` in `created_at` ascending order, each lapse recomputes its asset's scores and posture as in §3.1, and any asset whose posture drops to `DEFICIENT` returns its `UNDER_REVIEW` disclosure requests to `RETURNED`. Both finding counters stay empty until this transition sets them.

Reporting — `CONDUCTED → REPORTED` — publishes the results. What happens next forks on criticality. An audit with zero critical findings closes directly: `REPORTED → CLOSED` requires `critical_findings` of zero, otherwise `ERR_INVALID_STATE`. An audit with critical findings must remediate first: `REPORTED → REMEDIATING` requires `critical_findings` greater than zero, otherwise `ERR_INVALID_STATE`, and the eventual close — `REMEDIATING → CLOSED` — presents `resolved_critical_count` and requires it to equal `critical_findings` exactly, otherwise `ERR_INVALID_STATE`; that count stays empty until the close sets it. An audit may be cancelled while still `SCHEDULED`; `CLOSED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all lifecycle state transitions, descriptive updates, endorsements, signing, publishing, sweeping, and the clock setter — return `200 OK`. State-transition endpoints accept a `to_status` field naming the desired target state, plus any transition-specific payload fields described in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | IPCounsel |
| GET | `/api/program/status` | Program status: policy version, clock, per-entity counts | IPCounsel, SeniorCounsel, HRPartner, SecurityOfficer |
| POST | `/api/program/policy/publish` | Publish a new confidentiality policy version | IPCounsel |
| POST | `/api/program/sweep` | Run all clock-driven transitions in fixed order | IPCounsel, SecurityOfficer |
| POST | `/api/assets` | Register a trade secret asset | IPCounsel |
| GET | `/api/assets` | List assets | IPCounsel, SeniorCounsel, SecurityOfficer |
| GET | `/api/assets/{id}` | Get one asset | IPCounsel, SeniorCounsel, SecurityOfficer |
| PATCH | `/api/assets/{id}` | Update asset descriptive fields (OCC-guarded) | IPCounsel |
| POST | `/api/assets/{id}/state` | Asset lifecycle transition | IPCounsel |
| GET | `/api/assets/{id}/posture-report` | Litigation-readiness posture report | IPCounsel, SeniorCounsel |
| POST | `/api/measures` | Document a reasonable measure for an asset | SecurityOfficer, IPCounsel |
| GET | `/api/measures` | List measures | IPCounsel, SeniorCounsel, SecurityOfficer |
| GET | `/api/measures/{id}` | Get one measure | IPCounsel, SeniorCounsel, SecurityOfficer |
| POST | `/api/measures/{id}/state` | Measure lifecycle transition | SecurityOfficer, IPCounsel |
| POST | `/api/counterparties` | Register a counterparty | IPCounsel |
| GET | `/api/counterparties` | List counterparties | IPCounsel, SeniorCounsel, SecurityOfficer |
| GET | `/api/counterparties/{id}` | Get one counterparty | IPCounsel, SeniorCounsel, SecurityOfficer |
| POST | `/api/counterparties/{id}/state` | Counterparty lifecycle transition | IPCounsel |
| POST | `/api/ndas` | Draft an NDA | IPCounsel |
| POST | `/api/ndas/{id}/amendments` | Create an amendment NDA superseding this one (OCC-guarded) | IPCounsel |
| GET | `/api/ndas` | List NDAs | IPCounsel, SeniorCounsel |
| GET | `/api/ndas/{id}` | Get one NDA | IPCounsel, SeniorCounsel |
| POST | `/api/ndas/{id}/state` | NDA lifecycle transition | IPCounsel, CounterpartyRep |
| POST | `/api/obligations` | Add an obligation to an NDA | IPCounsel |
| GET | `/api/obligations` | List obligations | IPCounsel, SeniorCounsel, CounterpartyRep |
| GET | `/api/obligations/{id}` | Get one obligation | IPCounsel, SeniorCounsel, CounterpartyRep |
| POST | `/api/obligations/{id}/state` | Obligation lifecycle transition | IPCounsel, CounterpartyRep |
| POST | `/api/employees` | Onboard an employee record | HRPartner |
| GET | `/api/employees` | List employees | HRPartner, IPCounsel, SecurityOfficer |
| GET | `/api/employees/{id}` | Get one employee | HRPartner, IPCounsel, SecurityOfficer, Employee |
| POST | `/api/employees/{id}/state` | Employee lifecycle transition | HRPartner |
| POST | `/api/acknowledgments` | Issue a fresh acknowledgment for an employee | HRPartner |
| GET | `/api/acknowledgments` | List acknowledgments | HRPartner, IPCounsel, Employee |
| GET | `/api/acknowledgments/{id}` | Get one acknowledgment | HRPartner, IPCounsel, Employee |
| POST | `/api/acknowledgments/{id}/sign` | Employee signs their own acknowledgment | Employee |
| POST | `/api/exit-interviews` | Schedule an exit interview | HRPartner |
| GET | `/api/exit-interviews` | List exit interviews | HRPartner, IPCounsel |
| GET | `/api/exit-interviews/{id}` | Get one exit interview | HRPartner, IPCounsel |
| PATCH | `/api/exit-interviews/{id}` | Set interview certification flags | HRPartner |
| POST | `/api/exit-interviews/{id}/state` | Exit interview lifecycle transition | HRPartner |
| POST | `/api/grants` | Employee requests need-to-know access to an asset | Employee |
| GET | `/api/grants` | List access grants | SecurityOfficer, IPCounsel, Employee |
| GET | `/api/grants/{id}` | Get one access grant | SecurityOfficer, IPCounsel, Employee |
| POST | `/api/grants/{id}/state` | Access grant lifecycle transition | SecurityOfficer, IPCounsel |
| POST | `/api/disclosures` | Draft a third-party disclosure request | Employee |
| GET | `/api/disclosures` | List disclosure requests | IPCounsel, SeniorCounsel, Employee |
| GET | `/api/disclosures/{id}` | Get one disclosure request | IPCounsel, SeniorCounsel, Employee |
| POST | `/api/disclosures/{id}/endorse` | Senior counsel endorses an under-review disclosure | SeniorCounsel |
| POST | `/api/disclosures/{id}/state` | Disclosure lifecycle transition | Employee, IPCounsel |
| POST | `/api/forensic-reviews` | Open a forensic review for an employee | HRPartner, IPCounsel |
| GET | `/api/forensic-reviews` | List forensic reviews | IPCounsel, SeniorCounsel, SecurityOfficer, HRPartner |
| GET | `/api/forensic-reviews/{id}` | Get one forensic review | IPCounsel, SeniorCounsel, SecurityOfficer, HRPartner |
| PATCH | `/api/forensic-reviews/{id}` | Record findings fields on a review | SecurityOfficer |
| POST | `/api/forensic-reviews/{id}/state` | Forensic review lifecycle transition | SecurityOfficer, IPCounsel |
| POST | `/api/demand-letters` | Draft a demand letter from an escalated review | IPCounsel |
| GET | `/api/demand-letters` | List demand letters | IPCounsel, SeniorCounsel |
| GET | `/api/demand-letters/{id}` | Get one demand letter | IPCounsel, SeniorCounsel |
| POST | `/api/demand-letters/{id}/state` | Demand letter lifecycle transition | SeniorCounsel, IPCounsel |
| POST | `/api/preservation-notices` | Create a preservation notice | IPCounsel |
| GET | `/api/preservation-notices` | List preservation notices | IPCounsel, SeniorCounsel |
| GET | `/api/preservation-notices/{id}` | Get one preservation notice | IPCounsel, SeniorCounsel |
| POST | `/api/preservation-notices/{id}/state` | Preservation notice lifecycle transition | IPCounsel, SeniorCounsel |
| POST | `/api/evidence-items` | Collect an evidence item into a review | SecurityOfficer |
| GET | `/api/evidence-items` | List evidence items | SecurityOfficer, IPCounsel, SeniorCounsel |
| GET | `/api/evidence-items/{id}` | Get one evidence item | SecurityOfficer, IPCounsel, SeniorCounsel |
| POST | `/api/evidence-items/{id}/state` | Evidence item lifecycle transition | SecurityOfficer, IPCounsel |
| POST | `/api/training-assignments` | Assign a training module to an employee | HRPartner |
| GET | `/api/training-assignments` | List training assignments | HRPartner, IPCounsel, Employee |
| GET | `/api/training-assignments/{id}` | Get one training assignment | HRPartner, IPCounsel, Employee |
| POST | `/api/training-assignments/{id}/state` | Training assignment lifecycle transition | Employee, HRPartner |
| POST | `/api/clean-desk-audits` | Schedule a clean-desk audit for a department | SecurityOfficer |
| GET | `/api/clean-desk-audits` | List clean-desk audits | SecurityOfficer, IPCounsel |
| GET | `/api/clean-desk-audits/{id}` | Get one clean-desk audit | SecurityOfficer, IPCounsel |
| POST | `/api/clean-desk-audits/{id}/state` | Clean-desk audit lifecycle transition | SecurityOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DATE_ORDER` | 422 |
| `ERR_EXPIRY_IN_PAST` | 422 |
| `ERR_REVIEW_WINDOW_EXPIRED` | 422 |
| `ERR_NDA_WINDOW_OVERLAP` | 409 |
| `ERR_AUDIT_WINDOW_CONFLICT` | 409 |
| `ERR_INTERVIEW_OVERLAP` | 409 |
| `ERR_NEED_TO_KNOW_VIOLATION` | 403 |
| `ERR_CLASSIFICATION_CEILING_EXCEEDED` | 409 |
| `ERR_POSTURE_DEFICIENT` | 409 |
| `ERR_PRESERVATION_HOLD_ACTIVE` | 409 |
| `ERR_DISCLOSURE_RISK_TOO_HIGH` | 409 |
| `ERR_ENDORSEMENT_REQUIRED` | 409 |
| `ERR_NDA_NOT_ACTIVE` | 409 |
| `ERR_COUNTERPARTY_NOT_ACTIVE` | 409 |
| `ERR_STALE_REFERENCE` | 409 |
| `ERR_ACK_REQUIRED` | 409 |
| `ERR_POLICY_VERSION_STALE` | 409 |
| `ERR_EXIT_INTERVIEW_NOT_CERTIFIED` | 409 |
| `ERR_ACTIVE_GRANTS_REMAIN` | 409 |
| `ERR_REVIEW_NOT_CONCLUDED` | 409 |
| `ERR_TRAINING_NOT_CURRENT` | 409 |
| `ERR_MEASURE_EVIDENCE_REQUIRED` | 422 |
| `ERR_MARKING_EVIDENCE_REQUIRED` | 422 |
| `ERR_INVALID_HASH` | 422 |

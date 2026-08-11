# Physician Onboarding & Practice Ramp API — Product Requirements Document

## 1. Introduction

Health systems invest heavily in physician recruitment, yet the months between a signed offer and a fully ramped practice are where that investment is won or lost. Credentialing stalls, training slips, panels open late, guarantee advances drift away from collections, and by the time leadership notices a disengaged new hire the first-year retention decision has often already been made. The Physician Onboarding & Practice Ramp API exists to make that entire corridor — from first contact with a prospect through the end of the income-guarantee ramp term — a single, observable, rule-governed workflow.

This document specifies a system that coordinates six cooperating functions centered on one onboarding case per physician: recruiting and contract negotiation, licensure and payer-enrollment credentialing along a dependency graph, EHR training and note-template building, schedule construction and panel opening, referral marketing and community introduction, and income-guarantee bookkeeping with ramp-milestone attestation. A derived readiness gate ties the credential, training, and practice dimensions together so that a patient panel can open only when every dimension is genuinely ready, and a mentorship program with structured first-year check-ins feeds a weighted retention-risk score that leadership can act on before risk becomes attrition. The API is mounted under `/onboarding`, with a small operator surface for driving the logical clock that every temporal rule in the domain consults.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: who may call what, how responses are shaped, how time works, and in what order the server validates a request.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, a caller whose role is not listed on the target operation — or who fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares nine roles. `Recruiter` owns physician registration, case opening, and offer drafting, extension, and withdrawal. `ContractAdministrator` executes accepted offers, a step deliberately segregated from recruiting. `CredentialingSpecialist` registers credential items and moves them through document submission, verification, and filing. `PracticeManager` runs training scheduling and signoff, schedule templates, panel operations, referral marketing, and ramp-milestone reporting. `FinanceAnalyst` owns the income guarantee — activation, reconciliation, repayments — and attests reported milestones. `OnboardingDirector` approves or rejects filed credential items, assigns mentors, completes mentorships, orders retention-risk snapshots, marks staff physicians active, and separates physicians. `Physician` is the onboarding doctor, who negotiates and accepts offers and completes their own training modules. `MentorPhysician` is an active physician recording first-year check-ins. `SystemOperator` drives the logical clock and the daily epoch sweep.

When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting Physician; ownership checks on any resource that references a Physician compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Physician` caller may counter, accept, or decline only an offer belonging to their own case chain, and may complete only training modules of their own case's plan. When `X-User-Role` is `MentorPhysician`, `X-User-ID` is likewise the `id` of the acting Physician, and the caller may record check-ins only on mentorship assignments whose `mentor_physician_id` equals `X-User-ID`; a mentor touching another mentor's assignment is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `Recruiter`, `ContractAdministrator`, `CredentialingSpecialist`, `PracticeManager`, `FinanceAnalyst`, `OnboardingDirector`, or `SystemOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` or `verified_by_user_id` on a CredentialItem, where it anchors segregation of duties — but it does not compare the value to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0.

Unless a list explicitly states otherwise, list endpoints return resources sorted by `created_at` in ascending order. The response `meta` object of a list endpoint carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Epoch Sweep

Time in this domain is not wall-clock time. The server maintains a logical clock whose startup default is exactly 2026-05-01T00:00:00Z and which never falls back to wall-clock time; every date and datetime comparison in the domain — offer expiry, credential expiry, start-date gates, reporting windows — reads this clock. A `SystemOperator` may set the logical clock to a supplied instant by providing `to_iso8601`; the capability responds with the resulting `current_utc`.

A second operator capability, the daily epoch sweep, advances time-driven state in a pinned order. First it expires credential items whose `expires_on` is earlier than the current logical date, running the full dependency cascade described in §3.3. Second it expires offers still in `EXTENDED` or `COUNTERED` whose `expires_at` lies in the past. Third it lapses ramp milestones still `PENDING` whose reporting window has closed, as described in §3.8. The sweep reports the identifiers it touched as `expired_credential_ids`, `expired_offer_ids`, and `lapsed_milestone_ids`.

### 2.5. Common Resource Properties

Every primary resource — Physician, OnboardingCase, Offer, CredentialItem, TrainingPlan, TrainingModule, ScheduleTemplate, Panel, ReferralCampaign, CampaignEvent, IncomeGuarantee, RampMilestone, and MentorshipAssignment — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource.

Two resources are exceptions. A CheckIn and a RetentionRiskSnapshot are point-in-time records: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

### 2.6. Parallel Case Dimensions and the Derived Posture Gate

An OnboardingCase is not governed by a single status. Its `case_status` moves from `IN_PROGRESS` at creation to `HIRED` when the panel opens and finally to `SEPARATED`, but alongside it three parallel dimensions evolve independently, and a fourth derived field gates the go-live decision.

The credential dimension, `credential_status`, starts at `NOT_STARTED` when the case has no credential items, becomes `IN_PROGRESS` once any item exists, reaches `COMPLETE` when every required item type has an `APPROVED` item and no item is `BLOCKED`, `EXPIRED`, or `LAPSED`, and falls to `BLOCKED` whenever any item is `BLOCKED`, `EXPIRED`, or `LAPSED`. When more than one definition could apply, the precedence is fixed: `BLOCKED` wins over `COMPLETE`, which wins over `IN_PROGRESS`, which wins over `NOT_STARTED`.

The training dimension, `training_status`, mirrors the case's training plan: `NOT_STARTED` while no plan exists, `IN_PROGRESS` while the plan is `PLANNED`, `IN_PROGRESS`, or `AWAITING_SIGNOFF`, and `COMPLETE` once the plan is `COMPLETE`. The practice dimension, `practice_status`, is `PLANNING` while the case has no `ACTIVE` schedule template, `BUILDING` while at least one template is `ACTIVE` but the case's `weekly_active_minutes` remains below the specialty requirement, and `READY` once `weekly_active_minutes` meets that requirement.

Above all three sits `posture`, the derived go-live gate. A case with no `EXECUTED` offer is `PRE_CONTRACT`. Once an offer executes, the case is `CREDENTIALING` while `credential_status` is anything other than `COMPLETE`; it advances to `RAMP_PREP` when the credential dimension is complete but training or practice is not yet done; and it reaches `GO_LIVE_READY` only when `credential_status` is `COMPLETE`, `training_status` is `COMPLETE`, and `practice_status` is `READY` at the same time. Opening the panel puts the case into `LIVE`. A case whose panel has been frozen does not stay `LIVE`: its posture is recomputed from the three component dimensions, landing back on `GO_LIVE_READY`, `RAMP_PREP`, or `CREDENTIALING` as the components dictate.

The case also carries derived counters that other subsections define in detail: `weekly_active_minutes`, `attained_milestone_count`, `missed_milestone_count`, `latest_risk_score`, `latest_risk_band` (one of `LOW`, `MODERATE`, `HIGH`, `CRITICAL`, or null before any snapshot), and `at_risk`, which is true exactly when `latest_risk_band` is `HIGH` or `CRITICAL` and is also forced true the moment a `CRISIS` check-in is recorded.

### 2.7. Cascading Consistency and Resource Versioning

Writes in this system rarely touch one resource alone. A child mutation that changes one of the case's derived dimensions — a credential approval, a template activation, a training signoff, a milestone attestation — recomputes the affected dimension and the case's `posture` in the same transaction. Each such reconciliation mutates the OnboardingCase itself: its `updated_at` refreshes and its `version` increments. Offer and credential workflows increment the case's `version` on every step as well, and the provisioning and closure cascades described in §3 update several resources atomically. Server-initiated transitions — bubble-ups from a module to its plan, dependency cascades through the credential graph, panel freezes, epoch-sweep expirations — are applied by the server without any explicit client request on the affected resource, and each affected resource's own `version` increments independently. Case-version propagation is broad by design: registering or acting on credential items, drafting and negotiating offers, drafting/activating/retiring schedule templates, opening, freezing, and unfreezing the panel, creating a referral campaign, signing off a training plan, scheduling or completing a module, attesting a milestone, creating a mentorship assignment, recording a check-in, and persisting a retention snapshot each increment the case's `version`, as §3 notes at each step. Clients that cache a case should treat its `version` as advancing on nearly every workflow step, which is precisely what the optimistic concurrency rules below rely on.

### 2.8. Optimistic Concurrency Control

Two write endpoints are protected by optimistic concurrency control on the parent OnboardingCase, and both use the same field name and the same rejection. The offer-creation endpoint (`POST /onboarding/offers`) requires the request to carry `expected_onboarding_case_version`, the case `version` the client last observed. If the case's current `version` no longer matches — for example because another writer has executed an amendment that legitimately superseded the prior executed offer and advanced the case — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than letting the stale reader act on a case it has not observed. The mentorship-assignment creation endpoint (`POST /onboarding/mentorship-assignments`) applies the identical rule: the request must carry `expected_onboarding_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Because creating an assignment legitimately supersedes the currently `ACTIVE` one, this check prevents a stale reader from silently displacing a mentor it never saw. Endpoints not listed here do not take a version field at all.

### 2.9. Validation Order and Error Precedence

Every request is evaluated against an ordered series of checks, and the first failing check rejects the request and masks all later ones. The order is fixed:

1. Authentication context: `X-User-ID` and `X-User-Role` are present and the role is declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Endpoint authorization: the role is listed on the endpoint, else `ERR_FORBIDDEN` (HTTP 403).
3. Entity-backed ownership: a `Physician` caller acts only on their own case chain (offer counter, accept, and decline, and training-module completion), and a `MentorPhysician` caller acts only on assignments whose `mentor_physician_id` equals their `X-User-ID`, else `ERR_FORBIDDEN` (HTTP 403).
4. Existence: path and body identifiers resolve, validated left-to-right (physician, then case, then child), else the resource-specific 404 catalogued in §2.10.
5. Request body schema: required fields are present, enum members are valid, dates parse, `start_minute` precedes `end_minute`, `start_date` is not after `end_date`, and amounts are not negative, else `ERR_VALIDATION` (HTTP 400).
6. State preconditions: the target resource's state permits the transition, else the resource-specific 409 (`ERR_OFFER_NOT_EXTENDABLE`, `ERR_NEGOTIATION_NOT_OPEN`, `ERR_OFFER_NOT_ACCEPTED`, `ERR_ITEM_NOT_SUBMITTED`, `ERR_ITEM_NOT_VERIFIED`, `ERR_ITEM_NOT_FILED`, `ERR_MODULE_NOT_SCHEDULED`, `ERR_TEMPLATE_NOT_DRAFT`, `ERR_TEMPLATE_NOT_ACTIVE`, `ERR_PANEL_NOT_OPEN`, `ERR_PANEL_NOT_FROZEN`, `ERR_CAMPAIGN_NOT_ACTIVE`, `ERR_EVENT_NOT_PLANNED`, `ERR_GUARANTEE_NOT_DRAFT`, `ERR_GUARANTEE_NOT_ACTIVE`, `ERR_MILESTONE_NOT_PENDING`, `ERR_MILESTONE_NOT_REPORTED`, `ERR_MENTORSHIP_NOT_ACTIVE`) with `ERR_INVALID_STATE` (HTTP 409) as the generic fallback for transitions without a more specific error.
7. Segregation of duties: on credential verification, the verifier must differ from the submitter of record, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). On that operation the state precondition is evaluated first, so an item that was never submitted surfaces `ERR_ITEM_NOT_SUBMITTED` rather than the segregation error.
8. Linked-entity state gates, checked when planning a campaign event, attesting a milestone, opening or unfreezing a panel, or creating a mentorship assignment: the campaign must be `ACTIVE` for event creation (`ERR_CAMPAIGN_NOT_ACTIVE`), the guarantee must be `ACTIVE` for attestation (`ERR_GUARANTEE_NOT_ACTIVE`), the case posture and component readiness must hold for panel open and unfreeze (`ERR_POSTURE_NOT_READY`), and the mentor rules are pinned in order — mentor is not the mentee (`ERR_MENTOR_IS_MENTEE`), then mentor is an `ACTIVE` physician (`ERR_MENTOR_NOT_ACTIVE_PHYSICIAN`), then specialty match (`ERR_MENTOR_SPECIALTY_MISMATCH`).
9. Temporal rules, checked on offer execute, accept, and counter, on guarantee activation, panel opening, milestone reporting, template activation, and event creation: the proposed start date must clear the credential critical path (`ERR_START_DATE_BEFORE_CREDENTIAL_ETA`), the offer must not be at or past `expires_at` (`ERR_OFFER_EXPIRED`), the logical clock must have reached the start date or start month (`ERR_START_DATE_NOT_REACHED`), the milestone reporting window must still be open (`ERR_REPORTING_WINDOW_CLOSED`), and schedule and event windows must not overlap their siblings (`ERR_TEMPLATE_OVERLAP`, `ERR_EVENT_WINDOW_OVERLAP`).
10. Structural rules: one case per physician (`ERR_DUPLICATE_CASE`), one non-terminal offer per case (`ERR_ACTIVE_OFFER_EXISTS`), amendments only while the guarantee is `DRAFT` and every milestone `PENDING` (`ERR_AMENDMENT_WINDOW_CLOSED`), dependency items approved before filing (`ERR_ITEM_DEPENDENCY_NOT_APPROVED`), negotiation rounds within the limit (`ERR_NEGOTIATION_ROUND_LIMIT`), check-ins unique-then-ordered — an already-recorded `day_marker` yields `ERR_CHECKIN_ALREADY_RECORDED`, checked first, and a non-recorded marker that is not the immediate next yields `ERR_CHECKIN_OUT_OF_ORDER` — and five check-ins before mentorship completion (`ERR_CHECKINS_INCOMPLETE`).
11. Fiscal and capacity rules, checked last: campaign budget (`ERR_CAMPAIGN_BUDGET_EXCEEDED`), panel capacity (`ERR_PANEL_CAPACITY_EXCEEDED`), the census floor (`ERR_NEGATIVE_CENSUS`), and the repayment ceiling (`ERR_REPAYMENT_EXCEEDS_OUTSTANDING`).

### 2.10. Resolving Resource Identifiers

Identifiers supplied in a path or a body are validated left-to-right — physician first, then case, then the child resource — and the request is rejected immediately with the 404 corresponding to the first identifier that does not resolve. The catalogue is resource-specific: `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CREDENTIAL_ITEM_NOT_FOUND`, `ERR_TRAINING_PLAN_NOT_FOUND`, `ERR_TRAINING_MODULE_NOT_FOUND`, `ERR_SCHEDULE_TEMPLATE_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_CAMPAIGN_EVENT_NOT_FOUND`, `ERR_GUARANTEE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_MENTORSHIP_NOT_FOUND`, and `ERR_SNAPSHOT_NOT_FOUND`, all HTTP 404. A request naming a well-formed child under a non-existent case therefore fails with `ERR_CASE_NOT_FOUND` before the child is ever consulted.

### 2.11. Units, Precision, and Rounding

All money in the system is carried as integer cents — salaries, bonuses, guarantee amounts, campaign budgets, event costs, collections, draws, repayments — and never as floating-point currency. The one fractional money operation, the missed-milestone penalty multiplication of §3.8, rounds half-up to whole cents. Retention-risk component values are rounded to exactly 2 decimal places, round half-up, before weighting, and each weighted term is likewise rounded to 2 decimal places half-up before the terms are summed; summing raw terms and rounding once at the end is explicitly not the contract. Schedule arithmetic is in whole minutes from midnight, credential service-level expectations and the start-date buffer are in whole days over ISO dates, and wRVU comparisons are integer comparisons.

## 3. Business Logic & Workflows

### 3.1. Recruiting, Registration, and Case Opening

A `Recruiter` begins the pipeline by registering a physician prospect with a `full_name`, a primary `specialty`, a contact `email`, and a `hire_type`. The specialty is one of `FAMILY_MEDICINE`, `INTERNAL_MEDICINE`, `CARDIOLOGY`, `ORTHOPEDICS`, or `PEDIATRICS`, and it is not decorative: it constrains mentor matching in §3.9 and fixes the required weekly clinic minutes in §3.5. The `hire_type` is one of `NEW_GRAD`, `EXPERIENCED`, or `LEADERSHIP` and drives the required training modules and template quotas of §3.4. Email addresses are unique per physician. A newly registered physician has `status` `PROSPECT`. The physician directory can be listed with optional `specialty` and `status` filters.

When a prospect is ready to proceed, a `Recruiter` opens an onboarding case by supplying the `physician_id` and a desired `target_start_date`; the target date is recorded for information only and does not gate anything. Exactly one case may exist per physician — a second attempt is rejected with `ERR_DUPLICATE_CASE` (HTTP 409). Creating the case cascades to the physician, whose `status` moves from `PROSPECT` to `ONBOARDING` with a version increment. A new case starts with `case_status` `IN_PROGRESS` and `posture` `PRE_CONTRACT`; its three parallel dimensions sit at `credential_status` `NOT_STARTED`, `training_status` `NOT_STARTED`, and `practice_status` `PLANNING`; `weekly_active_minutes`, `attained_milestone_count`, and `missed_milestone_count` are zero; `actual_start_date`, `latest_risk_score`, and `latest_risk_band` are null; and `at_risk` is false. Cases can be listed with optional `physician_id`, `posture`, and `case_status` filters.

Not every physician in the directory is an onboarding hire. An `OnboardingDirector` may mark a pre-existing staff physician active so that it can serve as a mentor; the mark-active action requires the physician to be in `PROSPECT` and is rejected with `ERR_INVALID_STATE` otherwise, moving the physician `PROSPECT` → `ACTIVE` with a version increment.

### 3.2. Offer Negotiation and Contract Execution

With a case open, a `Recruiter` drafts an offer carrying the `onboarding_case_id`, the full term sheet — `base_salary_cents`, `signing_bonus_cents`, `guarantee_monthly_cents`, `guarantee_term_months`, `panel_capacity`, `proposed_start_date`, and `expires_at` — and, because creation is concurrency-checked, the `expected_onboarding_case_version` described in §2.8. The guarantee term runs from 1 to 24 months and the panel capacity must be at least 1; values outside those bounds fail schema validation with `ERR_VALIDATION`. A new offer starts in `DRAFT` with `negotiation_round` 0, and its creation increments the case's `version`.

A case may hold at most one non-terminal offer at a time: drafting a second offer while a `DRAFT`, `EXTENDED`, `COUNTERED`, or `ACCEPTED` offer still exists is rejected with `ERR_ACTIVE_OFFER_EXISTS` (HTTP 409). The one exception is the amendment path — drafting against a case that already has an `EXECUTED` offer is an amendment, and it is permitted only while the case's income guarantee is still `DRAFT` and every ramp milestone is still `PENDING`; otherwise the create is rejected with `ERR_AMENDMENT_WINDOW_CLOSED` (HTTP 409).

Negotiation is a cyclic machine. A `Recruiter` extends a `DRAFT` offer, moving it to `EXTENDED`, and may later re-extend a `COUNTERED` offer back to `EXTENDED` with revised terms — any term fields supplied on the re-extension overwrite the prior terms. Extending from any other state is rejected with `ERR_OFFER_NOT_EXTENDABLE`. The physician answers an `EXTENDED` offer with a counter, optionally attaching a `physician_note`, which moves the offer `EXTENDED` → `COUNTERED` and increments `negotiation_round`. Four checks guard the counter: negotiation must be open (the offer is `EXTENDED`, else `ERR_NEGOTIATION_NOT_OPEN`), the logical clock must be earlier than `expires_at` (else `ERR_OFFER_EXPIRED`), the caller must be the physician of the offer's case (else `ERR_FORBIDDEN`), and the negotiation-round limit applies: at most five counters, so the fifth counter — the one moving round 4 to 5 — succeeds and the sixth is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422).

Acceptance is the physician's: from either `EXTENDED` or `COUNTERED` the physician accepts the current terms, moving the offer to `ACCEPTED`. The same negotiation-open, expiry, and ownership checks apply — an offer outside `EXTENDED`/`COUNTERED` yields `ERR_NEGOTIATION_NOT_OPEN`, a clock at or past `expires_at` yields `ERR_OFFER_EXPIRED`, and another physician's offer yields `ERR_FORBIDDEN`. A physician may instead decline from `EXTENDED` or `COUNTERED`, optionally with a `physician_note`, ending the offer at `DECLINED`; the same ownership and negotiation-open checks apply. A `Recruiter` may withdraw an offer with an optional `reason` from `DRAFT`, `EXTENDED`, `COUNTERED`, or `ACCEPTED`, ending it at `WITHDRAWN`; withdrawing from any other state — an already `EXECUTED` offer, for instance — is rejected with `ERR_INVALID_STATE`. Offers left in `EXTENDED` or `COUNTERED` whose `expires_at` falls behind the logical clock are flipped to `EXPIRED` by the epoch sweep of §2.4. Every one of these steps increments both the offer's `version` and the case's `version`.

Execution belongs to the `ContractAdministrator`, segregated from recruiting. The offer must be `ACCEPTED` (else `ERR_OFFER_NOT_ACCEPTED`), and the `proposed_start_date` must clear the credential critical path: it may not be earlier than the current logical date plus the critical path's remaining days plus the fixed fourteen-day start-date buffer computed in §3.3, or execution fails with `ERR_START_DATE_BEFORE_CREDENTIAL_ETA` (HTTP 422). On success the offer becomes `EXECUTED`, the case's `actual_start_date` is locked to the `proposed_start_date`, and the case's `posture` is recomputed — normally landing on `CREDENTIALING`, unless credentialing already happens to be `COMPLETE`.

Execution provisions the entire downstream apparatus. When no earlier executed offer exists on the case, the server creates: an IncomeGuarantee in `DRAFT` whose `monthly_guarantee_cents` and `term_months` are copied from the offer's `guarantee_monthly_cents` and `guarantee_term_months` and whose `start_month` is the calendar month of the `proposed_start_date`; a TrainingPlan in `PLANNED` with its required modules auto-created; a Panel in `NOT_OPEN` whose `capacity` comes from the offer's `panel_capacity`; and one RampMilestone in `PENDING` per guarantee month, `month_offset` running from 1 through the term, each with its target taken from the ramp curve of §3.8. When an earlier `EXECUTED` offer does exist, execution is an amendment instead: the earlier offer cascades to `SUPERSEDED`, the still-`DRAFT` guarantee has its `monthly_guarantee_cents` and `term_months` overwritten from the new offer, and the panel's `capacity` is overwritten — no new guarantee, training plan, panel, or milestones are created. In both branches the offer and case versions increment. Offers can be listed with optional `onboarding_case_id` and `status` filters.

### 3.3. Credentialing and the Dependency Graph

A `CredentialingSpecialist` builds the case's credential portfolio item by item. Registering an item takes the `onboarding_case_id`, an `item_type`, and a `document_ref`, plus three conditional inputs: `payer_code`, required if and only if the item type is `PAYER_ENROLLMENT_MEDICARE` or `PAYER_ENROLLMENT_COMMERCIAL`; `expires_on`, the date the underlying credential lapses, required for `STATE_LICENSE` and `DEA_REGISTRATION`; and `depends_on_item_ids`, an array of prerequisite item identifiers that defaults to empty and must reference items that already exist — because dependencies must pre-exist, the dependency graph is acyclic by construction. The full type enumeration is `STATE_LICENSE`, `DEA_REGISTRATION`, `BOARD_CERTIFICATION`, `PAYER_ENROLLMENT_MEDICARE`, `PAYER_ENROLLMENT_COMMERCIAL`, and `HOSPITAL_PRIVILEGES`; the first three of these — state license, DEA registration, and Medicare enrollment — are the required types for credential completeness. A new item starts `PENDING`, its registration increments the case's `version`, and the first item on a case moves `credential_status` from `NOT_STARTED` to `IN_PROGRESS`. Items can be listed with `onboarding_case_id`, `item_type`, and `status` filters, and a `depends_on_item_ids` filter returns the items whose dependency array contains the given identifier.

The pipeline runs `PENDING` → `DOCS_SUBMITTED` → `VERIFIED` → `FILED` → `APPROVED`. A `CredentialingSpecialist` submits documents for an item in `PENDING` or `REJECTED` — submitting from any other state is rejected with `ERR_INVALID_STATE` — which moves the item to `DOCS_SUBMITTED`, records the caller's `X-User-ID` as `submitted_by_user_id`, and refreshes `document_ref` when a new one is supplied. Verification, also by a `CredentialingSpecialist` and optionally annotated with a `verification_note`, requires the item to be `DOCS_SUBMITTED`; that state precondition is evaluated first, so a premature verify surfaces `ERR_ITEM_NOT_SUBMITTED`. Immediately after the state check, segregation of duties is enforced: the verifier's `X-User-ID` must differ from the item's `submitted_by_user_id`, else the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). A successful verify records the caller as `verified_by_user_id` and moves the item to `VERIFIED`. Filing, optionally carrying a `filing_ref`, requires `VERIFIED` (else `ERR_ITEM_NOT_VERIFIED`) and additionally requires every item named in `depends_on_item_ids` to be `APPROVED` (else `ERR_ITEM_DEPENDENCY_NOT_APPROVED`), moving the item to `FILED`. Approval belongs to the `OnboardingDirector`, requires `FILED` (else `ERR_ITEM_NOT_FILED`), and moves the item to `APPROVED` — at which point the restore rule below fires, and the case's `credential_status` and `posture` are recomputed. Each pipeline step increments the item's `version` and the case's `version`.

Rejection is the graph-shaking event. An `OnboardingDirector` may reject, with a mandatory `reason`, an item in `DOCS_SUBMITTED`, `VERIFIED`, or `FILED`; rejecting from any other state — a still-`PENDING` item, for instance — is rejected with `ERR_INVALID_STATE`. The rejection moves the item to `REJECTED` and cascades along the dependency edges: every dependent item in `PENDING`, `DOCS_SUBMITTED`, `VERIFIED`, or `FILED` records its current status in `blocked_from_status` and becomes `BLOCKED`, while every dependent already `APPROVED` becomes `LAPSED`, transitively through their own dependents until the graph settles. A `REJECTED` item can re-enter the pipeline through document submission, which is the resubmission loop `REJECTED` → `DOCS_SUBMITTED`.

Time works on the portfolio as well. The epoch sweep flips any item in `PENDING`, `DOCS_SUBMITTED`, `VERIFIED`, `FILED`, or `APPROVED` whose `expires_on` is earlier than the current logical date to `EXPIRED`, and expiry runs the same dependency cascade: direct dependents still in flight record `blocked_from_status` and become `BLOCKED`, direct dependents in `APPROVED` become `LAPSED`, and a dependent flipped by either rule triggers the same rule on its own dependents until no more flips occur. Then the case's `credential_status` is recomputed — it becomes `BLOCKED` whenever any item is `BLOCKED`, `EXPIRED`, or `LAPSED` — and `posture` is recomputed from the components; if the case's panel is `OPEN` and the recomputed posture has fallen below `GO_LIVE_READY`, the panel freezes, moving `OPEN` → `FROZEN` as described in §3.6.

Blocking is recoverable. The moment every item a `BLOCKED` item depends on is `APPROVED` again — most commonly because an approval elsewhere in the graph completes the set — the blocked item returns to exactly the status it recorded in `blocked_from_status`, whether that was `PENDING`, `DOCS_SUBMITTED`, `VERIFIED`, or `FILED`, and `blocked_from_status` is cleared. The four restore hops behave identically; only the recorded origin differs.

The credential critical path converts this graph into a date gate. Every item type carries a service-level expectation in whole days: ninety days for `STATE_LICENSE`, forty-five for `DEA_REGISTRATION`, thirty for `BOARD_CERTIFICATION`, sixty for `PAYER_ENROLLMENT_MEDICARE`, seventy-five for `PAYER_ENROLLMENT_COMMERCIAL`, and fifty for `HOSPITAL_PRIVILEGES`. An `APPROVED` item contributes zero remaining days; an item in any other status — including `EXPIRED` or `LAPSED`, which must be reworked — contributes its full expectation. The critical path length is the greatest total of remaining days accumulated along any dependency chain following `depends_on_item_ids`, considering every item of the case regardless of status. The earliest legal start date is the current logical date plus the critical path length plus the fixed fourteen-day buffer; a case with no credential items at all has a critical path of zero and an earliest start date simply fourteen days out. The figure is recomputed whenever any credential item changes status, and it is the gate that offer execution in §3.2 enforces.

### 3.4. EHR Training and Note-Template Signoff

Offer execution auto-creates the case's training plan in `PLANNED` — exactly one plan per case — and with it the required modules. Every physician must complete three required modules, `EHR_FUNDAMENTALS`, `ORDER_ENTRY`, and `NOTE_TEMPLATES`; a `NEW_GRAD` hire has a fourth, `BILLING`, so `required_module_count` is 4 for `NEW_GRAD` and 3 otherwise. The plan also pins `templates_required`, the number of EHR note templates the physician must build inside `NOTE_TEMPLATES`: 5 for a `NEW_GRAD`, 3 otherwise. Once the plan exists, the case's `training_status` reads `IN_PROGRESS` and stays there through `PLANNED`, `IN_PROGRESS`, and `AWAITING_SIGNOFF` until signoff makes it `COMPLETE`. Plans can be listed with `onboarding_case_id` and `status` filters.

A `PracticeManager` may add elective modules to the plan by supplying the `training_plan_id`, a `module_code` from the same four-value enumeration — module codes are unique within a plan — and a `required` flag that defaults to false; required modules gate plan signoff while electives do not. New modules start `NOT_STARTED`. Modules are listed ordered by `module_code` ascending rather than by creation time, so indexed access is deterministic, with optional `training_plan_id`, `status`, and `module_code` filters.

Scheduling is the `PracticeManager`'s lever: a module in `NOT_STARTED` or `FAILED` moves to `SCHEDULED` with its `scheduled_on` date set, and scheduling from any other state is rejected with `ERR_INVALID_STATE`. The `FAILED` → `SCHEDULED` hop is the retake cycle. The first time any module of a plan is scheduled, the plan bubbles up from `PLANNED` to `IN_PROGRESS`.

Completion belongs to the physician — specifically the physician of the plan's case, with other callers rejected with `ERR_FORBIDDEN`. The module must be `SCHEDULED`, else `ERR_MODULE_NOT_SCHEDULED`. The completion payload carries a `score` from 0 to 100 and, for the template module, a `templates_built_count`. The pass mark is 80: a score of at least 80 — exactly 80 passes — moves the module to `COMPLETED` with the `score` and any `templates_built_count` recorded, while a score of 79 or below moves it to `FAILED` with the score recorded; a failing score is a state outcome, not an error, and the module can be re-scheduled. The `NOTE_TEMPLATES` module adds a second gate: completing it requires `templates_built_count` to be at least the plan's `templates_required`, otherwise the completion is rejected with `ERR_TEMPLATES_INSUFFICIENT` (HTTP 422) and no transition occurs. When every module with `required` set to true has reached `COMPLETED`, the plan bubbles up from `IN_PROGRESS` to `AWAITING_SIGNOFF`.

Signoff closes the loop: a `PracticeManager` signs off a plan that is `AWAITING_SIGNOFF` — any other plan state is rejected with `ERR_PLAN_NOT_AWAITING_SIGNOFF` — moving the plan to `COMPLETE`, setting the case's `training_status` to `COMPLETE`, and recomputing the case's `posture`.

### 3.5. Schedule Construction and Weekly Capacity

The practice dimension is built out of weekly schedule templates. A `PracticeManager` drafts a template with the `onboarding_case_id`, a `weekday` from 1 (Monday) through 7 (Sunday), a `start_minute` and `end_minute` in minutes from midnight, and a `block_type` of `CLINIC`, `PROCEDURE`, `OR`, or `ADMIN`. The block is a half-open interval: `start_minute` is the inclusive lower bound (0 through 1439) and `end_minute` the exclusive upper bound (1 through 1440), so the start must precede the end; violations fail schema validation with `ERR_VALIDATION`. A new template is a `DRAFT`, its drafting increments the case's `version`, and it contributes nothing until activated. Templates can be listed with `onboarding_case_id`, `weekday`, and `status` filters.

Activation, by a `PracticeManager`, requires `DRAFT` (else `ERR_TEMPLATE_NOT_DRAFT`) and enforces the no-overlap rule against the case's other `ACTIVE` templates on the same weekday. Two half-open blocks overlap exactly when one's start falls before the other's end and the other's start falls before the one's end; blocks that merely touch — one's `end_minute` equal to the other's `start_minute` — are allowed. A conflicting activation is rejected with `ERR_TEMPLATE_OVERLAP` (HTTP 422). On success the template becomes `ACTIVE` and the case's practice numbers are recomputed.

The case's `weekly_active_minutes` is the sum, over its `ACTIVE` templates whose `block_type` is `CLINIC`, `PROCEDURE`, or `OR`, of each block's length — its `end_minute` minus its `start_minute`; `ADMIN` blocks never count. Each specialty fixes a required weekly total: 1,200 minutes for `FAMILY_MEDICINE`, 1,200 for `INTERNAL_MEDICINE` (the two twenty-hour requirements), 1,100 for `PEDIATRICS`, 1,000 for `CARDIOLOGY`, and 900 for `ORTHOPEDICS`. Meeting the requirement exactly is sufficient: `practice_status` is `READY` when `weekly_active_minutes` is at least the requirement, `BUILDING` when at least one `ACTIVE` template exists but the total falls short, and `PLANNING` when nothing is `ACTIVE` at all. Every activation and retirement recomputes `weekly_active_minutes`, `practice_status`, and `posture` together.

Retirement is the mirror action: a `PracticeManager` retires an `ACTIVE` template — retiring from any other state is rejected with `ERR_TEMPLATE_NOT_ACTIVE` — moving it to `RETIRED` and recomputing the same numbers. When retirement pulls `weekly_active_minutes` below the specialty requirement, `practice_status` drops from `READY` to `BUILDING`, and if the case's panel is `OPEN` at that moment the practice drop freezes it: the panel moves `OPEN` → `FROZEN` and the case's posture leaves `LIVE`, per the panel rules of §3.6.

### 3.6. Panel Operations: Opening, Freezing, and Census

Offer execution auto-creates the case's panel — exactly one per case — in `NOT_OPEN`, with `capacity` copied from the executing offer's `panel_capacity`, `current_size` at 0, and `opened_at` null. Panels can be listed with `onboarding_case_id` and `status` filters.

Opening the panel is the go-live act, performed by a `PracticeManager` and guarded by three checks: the panel must be `NOT_OPEN` (else `ERR_PANEL_NOT_OPEN`), the case's `posture` must be `GO_LIVE_READY` (else `ERR_POSTURE_NOT_READY`), and the logical clock's date must have reached the case's `actual_start_date` (else `ERR_START_DATE_NOT_REACHED`, HTTP 422). A successful open stamps `opened_at` with the logical clock, sets the case's `posture` to `LIVE`, moves the physician `ONBOARDING` → `ACTIVE`, moves the case `IN_PROGRESS` → `HIRED`, and increments the versions of panel, case, and physician alike.

An open panel can be frozen two ways. A `PracticeManager` may freeze it manually — the panel must be `OPEN`, else `ERR_PANEL_NOT_OPEN` — and the server freezes it automatically when a credential expiry (§3.3) or a template retirement (§3.5) knocks a readiness component out from under a live case. Either way the panel moves `OPEN` → `FROZEN` and the case's posture is recomputed from its components, leaving `LIVE` for `RAMP_PREP` or `CREDENTIALING` as the dimensions dictate. Unfreezing, also a `PracticeManager` action, requires the panel to be `FROZEN` (else `ERR_PANEL_NOT_FROZEN`) and every readiness component to hold again — `credential_status` `COMPLETE`, `training_status` `COMPLETE`, `practice_status` `READY`, and the logical clock at or past the `actual_start_date` — else `ERR_POSTURE_NOT_READY`; on success the panel returns to `OPEN` and posture becomes `LIVE`.

While the panel is `OPEN`, a `PracticeManager` maintains its census through signed adjustments carrying a `delta`. The `current_size` is a ledger: it equals the sum of all applied adjustment deltas plus the referrals flowed in from held campaign events per §3.7. Adjustments are bounded on both sides — the result may reach the panel's `capacity` exactly, but one patient beyond it is rejected with `ERR_PANEL_CAPACITY_EXCEEDED` (HTTP 422), and a result below zero is rejected with `ERR_NEGATIVE_CENSUS` (HTTP 422). Adjustments apply only while the panel is `OPEN`; against any other panel state the request is rejected with `ERR_PANEL_NOT_OPEN`. The ledger is compensating: an adjustment of +x followed by one of −x leaves `current_size` unchanged.

### 3.7. Referral Marketing and Community Events

Practice ramp has a demand side as well. A `PracticeManager` creates a referral campaign for the case with an `onboarding_case_id`, a `name`, and a `budget_cents` that may not be negative; the campaign starts in `DRAFT` with `spent_cents` and `referrals_attributed` at zero, and creation increments the case's `version`. The manager then activates the campaign (`DRAFT` → `ACTIVE`) and eventually completes it (`ACTIVE` → `COMPLETED`); activation or completion from the wrong state is rejected with `ERR_INVALID_STATE`. Campaigns can be listed with `onboarding_case_id` and `status` filters.

Events are planned inside an `ACTIVE` campaign — planning against a campaign in any other state is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`. Each event carries the `campaign_id`, an `event_type` of `COMMUNITY_TALK`, `REFERRAL_DINNER`, `MEDIA`, or `OPEN_HOUSE`, a `start_date` and `end_date` forming a closed window (the start may not fall after the end, else `ERR_VALIDATION`), a non-negative `cost_cents`, and a `venue`. Two checks guard creation, in a pinned order: first the window check — the closed window from `start_date` through `end_date` may not share any single date with any non-`CANCELLED` sibling event of the same campaign, and because the intervals are closed, even adjacent dates conflict — with violations rejected as `ERR_EVENT_WINDOW_OVERLAP` (HTTP 422); then the budget check, described next. A created event is `PLANNED`, and its `cost_cents` is immediately debited into the campaign's `spent_cents`.

The campaign's `spent_cents` is a strict ledger: it always equals the sum of `cost_cents` over the campaign's events in `PLANNED` or `HELD`. The budget gate at creation therefore asks whether `spent_cents` plus the new event's `cost_cents` stays within `budget_cents`; if it would exceed the budget, creation is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 422). Cancelling a `PLANNED` event — from any other state, cancellation is rejected with `ERR_EVENT_NOT_PLANNED` — moves it to `CANCELLED` and refunds its `cost_cents` from `spent_cents`, so a create followed by a cancel of the same event leaves the ledger unchanged.

When an event actually happens, a `PracticeManager` marks it held and records `referrals_generated`; the event must be `PLANNED`, else `ERR_EVENT_NOT_PLANNED`. Holding moves the event to `HELD`, adds `referrals_generated` into the campaign's `referrals_attributed`, and — when the case's panel is `OPEN` — flows the referrals into the census. That inflow respects capacity: if adding the referrals would push `current_size` beyond `capacity`, the hold is rejected with `ERR_PANEL_CAPACITY_EXCEEDED`; otherwise `current_size` grows by `referrals_generated`. Events can be listed with `campaign_id`, `status`, and `event_type` filters.

### 3.8. Income Guarantee and Ramp Milestones

The income guarantee is the financial spine of the ramp. Created in `DRAFT` at offer execution with terms copied from the offer and `start_month` set to the year-and-month of the `actual_start_date` — milestone `month_offset` 1 maps to that month — it begins with `months_reconciled`, `total_advanced_cents`, `projected_total_draw_cents`, `forgiveness_accrued_cents`, `total_repaid_cents`, and `outstanding_balance_cents` all at zero. A `FinanceAnalyst` activates it once the logical clock's date has reached the first day of `start_month`: activating from a state other than `DRAFT` is rejected with `ERR_GUARANTEE_NOT_DRAFT`, and activating before that first day with `ERR_START_DATE_NOT_REACHED`. Activation matters because the guarantee's `ACTIVE` status is the gate for milestone attestation. Guarantees can be listed with `onboarding_case_id` and `status` filters.

The ramp milestones are the guarantee's months made manifest: one per term month, created `PENDING` at execution, `month_offset` running from 1 through the term. Each month's `target_wrvu` comes from the standard ramp curve — 100, 150, 200, 250, 300, 350, 400, 420, 440, 460, 480, and 500 wRVUs for month offsets one through twelve respectively. Milestones are listed ordered by `month_offset` ascending rather than by creation time, with optional `onboarding_case_id`, `status`, and `month_offset` filters.

Each month moves through a reporting protocol. A `PracticeManager` reports actual production for a `PENDING` milestone — reporting from any other state is rejected with `ERR_MILESTONE_NOT_PENDING` — supplying `actual_wrvu` and `collections_cents`. The reporting window closes fifteen days after the month's end: a report dated after month end plus the fifteen-day grace period is rejected with `ERR_REPORTING_WINDOW_CLOSED` (HTTP 422). A successful report records both figures and moves the milestone to `REPORTED`.

Attestation belongs to the `FinanceAnalyst`. The milestone must be `REPORTED` (else `ERR_MILESTONE_NOT_REPORTED`) and the case's guarantee must be `ACTIVE` (else `ERR_GUARANTEE_NOT_ACTIVE`). Attestation computes `attained` as the threshold test of whether `actual_wrvu` reached `target_wrvu` — exact equality attains — moves the milestone to `ATTESTED`, and then cascades: the guarantee's draws are recomputed chronologically and `total_advanced_cents` updated; `forgiveness_accrued_cents` and `outstanding_balance_cents` are recomputed in the pinned order below; the case's `attained_milestone_count` and `missed_milestone_count` are updated; and the versions of milestone, guarantee, and case all increment. A milestone still `PENDING` when its reporting window closes is flipped to `LAPSED` by the epoch sweep, increments the case's `missed_milestone_count`, and — per the draw rules — counts as a full monthly draw with no forgiveness at the next recompute. On the case, `attained_milestone_count` counts `ATTESTED` milestones whose `attained` is true, while `missed_milestone_count` counts `ATTESTED` milestones whose `attained` is false plus every `LAPSED` one.

The draw calculation runs over the term months in ascending `month_offset` order and comes in two variants. For an `ATTESTED` month, the collection credit is the month's `collections_cents` capped at 1,800,000 cents (eighteen thousand dollars); if the month was attained the credit is that capped amount, and if it was missed the credit is the capped amount reduced by a ten-percent penalty, rounded half-up to whole cents. The month's draw is then the `monthly_guarantee_cents` minus the credit, floored at zero — collections can reduce the advance to nothing but never below. For a `LAPSED` month, the draw is the full `monthly_guarantee_cents`: no collection credit, no forgiveness. Months still `PENDING` or `REPORTED` are unreconciled and contribute nothing to the actual totals. The ACTUAL variant total, `total_advanced_cents`, is the sum of the draws over reconciled months only. The PROJECTED variant, `projected_total_draw_cents`, takes that actual total and adds one full `monthly_guarantee_cents` for every unreconciled term month — assuming zero future collections — so identical data yields a strictly larger projected total whenever any term month remains unreconciled. Forgiveness accrues at 100,000 cents (one thousand dollars) per attained month: `forgiveness_accrued_cents` is that amount times the number of `ATTESTED` months with `attained` true. The `outstanding_balance_cents` is then the total advanced minus `total_repaid_cents` minus the accrued forgiveness, floored at zero. The evaluation order is pinned — chronological draws first, then forgiveness from the attained count, then the outstanding balance from the three ledger totals — and a repayment is always validated against the outstanding balance computed before that repayment is applied.

Repayments and reconciliation close the loop. A `FinanceAnalyst` posts a repayment with an `amount_cents`; if the amount exceeds the outstanding balance computed before this repayment, the posting is rejected with `ERR_REPAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422), otherwise `total_repaid_cents` grows by `amount_cents` and the outstanding balance is recomputed. A `FinanceAnalyst` may also ask the server to reconcile the guarantee, which recomputes the draws from reconciled months in chronological order; `months_reconciled` counts the term months whose milestone is `ATTESTED` or `LAPSED`, and when that count reaches `term_months` the guarantee moves `ACTIVE` → `SETTLED` with its outstanding balance final. Reconciliation against a guarantee that is not `ACTIVE` is rejected with `ERR_GUARANTEE_NOT_ACTIVE`. Physician separation also settles the guarantee, per §3.9.

### 3.9. Mentorship, First-Year Check-Ins, and Retention Risk

An `OnboardingDirector` assigns each case a mentor by creating a mentorship assignment with the `onboarding_case_id`, the `mentor_physician_id`, and — because creation is concurrency-checked — the `expected_onboarding_case_version` of §2.8. The mentor rules are pinned in a fixed evaluation order: first, the mentor may not be the mentee, else `ERR_MENTOR_IS_MENTEE` (HTTP 422); second, the `mentor_physician_id` must reference an `ACTIVE` physician — the pool the mark-active action of §3.1 feeds — else `ERR_MENTOR_NOT_ACTIVE_PHYSICIAN`; third, the mentor's specialty must match the mentee's, else `ERR_MENTOR_SPECIALTY_MISMATCH`. At most one assignment is `ACTIVE` per case: creating a new one supersedes the previous `ACTIVE` assignment, moving it to `SUPERSEDED`. A fresh assignment starts `ACTIVE` with `checkins_recorded` at 0 and `escalated` false, and its creation increments the case's `version`. Assignments can be listed with `onboarding_case_id`, `mentor_physician_id`, and `status` filters.

The mentor — and only that mentor, since a `MentorPhysician` caller acts solely on assignments whose `mentor_physician_id` equals their own `X-User-ID`, with violations rejected as `ERR_FORBIDDEN` — records the five first-year check-ins. Each check-in names the `mentorship_id` implicitly through the assignment being acted on, a `day_marker` of `D30`, `D90`, `D180`, `D270`, or `D365`, a `sentiment` of `POSITIVE`, `NEUTRAL`, `CONCERN`, or `CRISIS`, and optional free-form `notes`; the server stamps `occurred_on` from the logical clock at recording time. The assignment must be `ACTIVE`, else `ERR_MENTORSHIP_NOT_ACTIVE`. Markers must be recorded strictly in ascending order and at most once each, and the two ordering failures are distinct and checked in a fixed sequence: a `day_marker` already present on the assignment is rejected with `ERR_CHECKIN_ALREADY_RECORDED` (HTTP 409), and only if the marker is new does the server check that it is the immediate next marker in the `D30`-through-`D365` sequence, rejecting a skip with `ERR_CHECKIN_OUT_OF_ORDER` (HTTP 422). Each recorded check-in increments the assignment's `checkins_recorded` and the case's `version`. A `CRISIS` sentiment does more: it sets the assignment's `escalated` flag true and forces the case's `at_risk` true immediately, regardless of any computed score. Check-ins of an assignment are listed in `day_marker` order. Once all five markers are recorded, an `OnboardingDirector` may complete the assignment — it must be `ACTIVE` (else `ERR_MENTORSHIP_NOT_ACTIVE`), and completing before all five check-ins exist is rejected with `ERR_CHECKINS_INCOMPLETE` (HTTP 422) — moving it to `COMPLETED`.

Retention risk is quantified through snapshots. An `OnboardingDirector` requests a snapshot for a case by naming the `onboarding_case_id` and a `variant` of `TRAILING` or `LEADING`; the case must have an `EXECUTED` offer — so that a panel and milestones exist — otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Each snapshot computes four component risks, each on a 0-to-100 scale. The `milestone_risk` differs by variant: `TRAILING` takes the attested months that were missed as a share of all attested months, expressed as a percentage, and is 0 when no month is attested; `LEADING` instead divides the missed attested months plus the unreconciled months already due by the months due — the term months whose reporting window has closed by the logical clock — and is 0 when no month is due. The `panel_risk` compares the census with a ramp expectation: the case's current month offset is the number of months elapsed since `start_month`, never less than 1, and the expected fill is the panel's `capacity` multiplied by the fill-curve point for that month — ten, eighteen, twenty-six, thirty-four, forty-two, fifty, fifty-eight, sixty-five, seventy-one, seventy-seven, eighty-two, and eighty-five percent for months one through twelve — except that `LEADING` uses the following month's curve point, projecting next-month expectations. The risk is the shortfall of `current_size` below the expected fill as a percentage of the expected fill, never negative, and 0 when the expected fill is zero. The `sentiment_risk` is the mean, over every check-in recorded on every mentorship assignment of the case regardless of assignment status, of the sentiment mapping — `POSITIVE` scores 0, `NEUTRAL` 40, `CONCERN` 70, `CRISIS` 100 — and defaults to 50 when no check-in has been recorded. The `schedule_risk` is the shortfall of the case's `weekly_active_minutes` below its specialty's required weekly minutes, as a percentage of that requirement, never negative.

The composite `score` weights the components: 0.35 for milestone risk, 0.25 for panel risk, 0.25 for sentiment risk, and 0.15 for schedule risk. The rounding order is pinned per §2.11 — each component value is rounded to two decimal places half-up before weighting, then each weighted term is rounded to two decimal places half-up, and only then are the four terms summed; summing the raw weighted terms and rounding once at the end is a different number and is not the contract. The `risk_band` maps the score with inclusive lower bounds: at least 75 is `CRITICAL`, at least 50 is `HIGH`, at least 25 is `MODERATE`, and anything lower is `LOW`. Because `TRAILING` uses only attested history and the current month's fill expectation while `LEADING` counts unreconciled elapsed months as missed and projects the next month's fill, identical underlying data yields a different score under the two variants. Persisting a snapshot updates the case's `latest_risk_score` and `latest_risk_band` — both null until the first snapshot exists — sets `at_risk` true exactly when the new band is `HIGH` or `CRITICAL`, and increments the case's `version`. Snapshots can be listed with `onboarding_case_id` and `variant` filters.

Separation ends the story. An `OnboardingDirector` separates a physician, optionally recording a `separation_reason`; the physician must be `ACTIVE`, and separating from any other state is rejected with `ERR_INVALID_STATE` — an onboarding case that never reached go-live therefore cannot be separated through this action, since its physician is not yet `ACTIVE`. Separation moves the physician `ACTIVE` → `SEPARATED` and cascades across the case: the panel, if `OPEN` or `FROZEN`, moves to `CLOSED` (a `NOT_OPEN` or already `CLOSED` panel is untouched); any `ACTIVE` mentorship assignment moves to `COMPLETED`; an `ACTIVE` income guarantee moves to `SETTLED` with its outstanding balance becoming final; any `ACTIVE` referral campaign moves to `COMPLETED`; and the case's `case_status` becomes `SEPARATED` with its `version` incremented. `SEPARATED` is terminal for both the physician and the case.

## 4. Endpoint Definitions

Operations that create a new resource — a physician, a case, an offer, a credential item, an elective module, a template, a campaign, an event, a repayment, an assignment, a check-in, a snapshot — return `201 Created`. Operations that modify an existing resource or drive one of its state transitions return `200 OK`. Read endpoints are open to every declared role; the table marks them "Any". The table is a summary only: request fields, side effects, and the exact rejection conditions for each operation are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/onboarding/physicians` | Register a physician prospect | Recruiter |
| GET | `/onboarding/physicians/{id}` | Fetch one physician | Any |
| GET | `/onboarding/physicians` | List physicians, ordered by `created_at` ascending | Any |
| POST | `/onboarding/physicians/{id}/separate` | Separate an `ACTIVE` physician; cascades close the panel, complete mentorship and campaign, settle the guarantee | OnboardingDirector |
| POST | `/onboarding/physicians/{id}/mark-active` | Mark a pre-existing staff physician (`PROSPECT`, no onboarding case) as `ACTIVE` so it can serve as a mentor | OnboardingDirector |
| POST | `/onboarding/onboarding-cases` | Open an onboarding case for a physician (one per physician) | Recruiter |
| GET | `/onboarding/onboarding-cases/{id}` | Fetch one case with its computed posture fields | Any |
| GET | `/onboarding/onboarding-cases` | List cases, ordered by `created_at` ascending | Any |
| POST | `/onboarding/offers` | Draft an offer (OCC on the case version; a create while an `EXECUTED` offer exists is an amendment and requires the guarantee `DRAFT` and all milestones `PENDING`) | Recruiter |
| GET | `/onboarding/offers/{id}` | Fetch one offer | Any |
| GET | `/onboarding/offers` | List offers, ordered by `created_at` ascending | Any |
| POST | `/onboarding/offers/{id}/extend` | Extend a `DRAFT` offer or re-extend a `COUNTERED` offer with revised terms (negotiation cycle hop) | Recruiter |
| POST | `/onboarding/offers/{id}/counter` | Physician counters an `EXTENDED` offer; the fifth counter succeeds, the sixth is rejected | Physician |
| POST | `/onboarding/offers/{id}/accept` | Physician accepts the current terms | Physician |
| POST | `/onboarding/offers/{id}/execute` | Contract administrator executes an `ACCEPTED` offer; validates the start date against the credential critical path and provisions guarantee, training plan, panel, and ramp milestones | ContractAdministrator |
| POST | `/onboarding/offers/{id}/withdraw` | Recruiter withdraws a non-terminal offer | Recruiter |
| POST | `/onboarding/offers/{id}/decline` | Physician declines an extended offer | Physician |
| POST | `/onboarding/credential-items` | Register a credential item (licensure, DEA, payer enrollment, etc.) with optional dependency edges | CredentialingSpecialist |
| GET | `/onboarding/credential-items/{id}` | Fetch one credential item | Any |
| GET | `/onboarding/credential-items` | List credential items, ordered by `created_at` ascending; the `depends_on_item_ids` filter returns items whose dependency array contains the given id | Any |
| POST | `/onboarding/credential-items/{id}/submit-docs` | Submit credential documents; records the caller as `submitted_by_user_id` (segregation anchor); allowed from `PENDING` and `REJECTED` | CredentialingSpecialist |
| POST | `/onboarding/credential-items/{id}/verify` | Verify submitted documents; the verifier must differ from the submitter (segregation of duties, checked after the state precondition) | CredentialingSpecialist |
| POST | `/onboarding/credential-items/{id}/file` | File the verified item with the authority or payer; all dependency items must be `APPROVED` | CredentialingSpecialist |
| POST | `/onboarding/credential-items/{id}/approve` | Approve a filed item; restores dependents whose dependencies are now fully `APPROVED`; recomputes `credential_status` and posture | OnboardingDirector |
| POST | `/onboarding/credential-items/{id}/reject` | Reject an item in flight; dependents block (non-terminal) or lapse (`APPROVED`) | OnboardingDirector |
| GET | `/onboarding/training-plans/{id}` | Fetch one training plan | Any |
| GET | `/onboarding/training-plans` | List training plans, ordered by `created_at` ascending | Any |
| POST | `/onboarding/training-plans/{id}/signoff` | Practice manager signs off an `AWAITING_SIGNOFF` plan | PracticeManager |
| POST | `/onboarding/training-modules` | Add an elective module to a plan (required modules are auto-created at offer execution) | PracticeManager |
| GET | `/onboarding/training-modules/{id}` | Fetch one module | Any |
| GET | `/onboarding/training-modules` | List modules of a plan, ordered by `module_code` ascending (deterministic for indexed access) | Any |
| POST | `/onboarding/training-modules/{id}/schedule` | Schedule a `NOT_STARTED` or `FAILED` module (`FAILED` → `SCHEDULED` is the retake cycle) | PracticeManager |
| POST | `/onboarding/training-modules/{id}/complete` | Physician completes a scheduled module; a score of at least 80 completes, below fails (retake allowed); `NOTE_TEMPLATES` additionally requires enough built templates | Physician |
| POST | `/onboarding/schedule-templates` | Draft a weekly schedule block (half-open interval from `start_minute` to `end_minute`) | PracticeManager |
| GET | `/onboarding/schedule-templates/{id}` | Fetch one template | Any |
| GET | `/onboarding/schedule-templates` | List templates, ordered by `created_at` ascending | Any |
| POST | `/onboarding/schedule-templates/{id}/activate` | Activate a draft; half-open overlap against `ACTIVE` templates of the same case and weekday (touching boundaries allowed); recomputes weekly minutes and `practice_status` | PracticeManager |
| POST | `/onboarding/schedule-templates/{id}/retire` | Retire an active template; if minutes fall below the requirement, `practice_status` drops and an `OPEN` panel freezes | PracticeManager |
| GET | `/onboarding/panels/{id}` | Fetch one panel | Any |
| GET | `/onboarding/panels` | List panels, ordered by `created_at` ascending | Any |
| POST | `/onboarding/panels/{id}/open` | Open the panel; requires posture `GO_LIVE_READY` and the start date reached; flips the physician `ACTIVE` and the case `HIRED`/`LIVE` | PracticeManager |
| POST | `/onboarding/panels/{id}/freeze` | Freeze an open panel | PracticeManager |
| POST | `/onboarding/panels/{id}/unfreeze` | Unfreeze when component readiness holds again | PracticeManager |
| POST | `/onboarding/panels/{id}/census-adjustments` | Apply a signed census delta while `OPEN`; the result must stay within zero and `capacity` (exactly `capacity` succeeds) | PracticeManager |
| POST | `/onboarding/referral-campaigns` | Create a referral marketing / community introduction campaign | PracticeManager |
| GET | `/onboarding/referral-campaigns/{id}` | Fetch one campaign | Any |
| GET | `/onboarding/referral-campaigns` | List campaigns, ordered by `created_at` ascending | Any |
| POST | `/onboarding/referral-campaigns/{id}/activate` | Activate a draft campaign | PracticeManager |
| POST | `/onboarding/referral-campaigns/{id}/complete` | Complete an active campaign | PracticeManager |
| POST | `/onboarding/campaign-events` | Plan a campaign event; closed-interval date overlap with any non-`CANCELLED` sibling event is rejected (adjacency conflicts); the budget is checked after the overlap check | PracticeManager |
| GET | `/onboarding/campaign-events/{id}` | Fetch one event | Any |
| GET | `/onboarding/campaign-events` | List events, ordered by `created_at` ascending | Any |
| POST | `/onboarding/campaign-events/{id}/hold` | Mark the event held and record attributed referrals; referrals flow into the `OPEN` panel census | PracticeManager |
| POST | `/onboarding/campaign-events/{id}/cancel` | Cancel a planned event; refunds `cost_cents` to the campaign (compensating action) | PracticeManager |
| GET | `/onboarding/income-guarantees/{id}` | Fetch one guarantee with its ACTUAL and PROJECTED draw fields | Any |
| GET | `/onboarding/income-guarantees` | List guarantees, ordered by `created_at` ascending | Any |
| POST | `/onboarding/income-guarantees/{id}/activate` | Activate the guarantee on or after the first day of `start_month` | FinanceAnalyst |
| POST | `/onboarding/income-guarantees/{id}/reconcile` | Recompute draws from reconciled months in chronological order; `SETTLED` when every term month is `ATTESTED` or `LAPSED` | FinanceAnalyst |
| POST | `/onboarding/income-guarantees/{id}/repayments` | Post a repayment against the outstanding balance (validated against the outstanding computed before this repayment) | FinanceAnalyst |
| GET | `/onboarding/ramp-milestones/{id}` | Fetch one milestone | Any |
| GET | `/onboarding/ramp-milestones` | List milestones, ordered by `month_offset` ascending (deterministic for indexed access) | Any |
| POST | `/onboarding/ramp-milestones/{id}/report` | Report actual production for a `PENDING` milestone inside its reporting window | PracticeManager |
| POST | `/onboarding/ramp-milestones/{id}/attest` | Attest a `REPORTED` milestone; requires the guarantee `ACTIVE`; computes attainment and cascades the guarantee draw recompute | FinanceAnalyst |
| POST | `/onboarding/mentorship-assignments` | Assign a mentor (OCC on the case version); supersedes any currently `ACTIVE` assignment of the case | OnboardingDirector |
| GET | `/onboarding/mentorship-assignments/{id}` | Fetch one assignment | Any |
| GET | `/onboarding/mentorship-assignments` | List assignments, ordered by `created_at` ascending | Any |
| POST | `/onboarding/mentorship-assignments/{id}/complete` | Complete an `ACTIVE` assignment after all five first-year check-ins | OnboardingDirector |
| POST | `/onboarding/mentorship-assignments/{id}/check-ins` | Mentor records the next first-year check-in; markers ascend `D30` through `D365`, each at most once; `CRISIS` escalates and flags the case at risk | MentorPhysician |
| GET | `/onboarding/mentorship-assignments/{id}/check-ins` | List check-ins of an assignment in `day_marker` order (`D30` through `D365`) | Any |
| POST | `/onboarding/retention-snapshots` | Compute and persist a retention risk snapshot (`TRAILING` or `LEADING` variant); requires the case to have an `EXECUTED` offer | OnboardingDirector |
| GET | `/onboarding/retention-snapshots/{id}` | Fetch one snapshot | Any |
| GET | `/onboarding/retention-snapshots` | List snapshots, ordered by `created_at` ascending | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock; the startup default is exactly 2026-05-01T00:00:00Z and the clock never falls back to wall-clock time | SystemOperator |
| POST | `/_ops/run_epoch` | Run the daily sweep in pinned order: expire credential items past `expires_on` with the full dependency cascade, then expire `EXTENDED`/`COUNTERED` offers past `expires_at`, then lapse `PENDING` milestones whose reporting window has closed | SystemOperator |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PHYSICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_MODULE_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_PANEL_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_GUARANTEE_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_MENTORSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_CASE` | 409 Conflict |
| `ERR_ACTIVE_OFFER_EXISTS` | 409 Conflict |
| `ERR_AMENDMENT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OFFER_NOT_EXTENDABLE` | 409 Conflict |
| `ERR_NEGOTIATION_NOT_OPEN` | 409 Conflict |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 422 Unprocessable Entity |
| `ERR_OFFER_NOT_ACCEPTED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_START_DATE_BEFORE_CREDENTIAL_ETA` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ITEM_NOT_VERIFIED` | 409 Conflict |
| `ERR_ITEM_NOT_FILED` | 409 Conflict |
| `ERR_ITEM_DEPENDENCY_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_MODULE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_TEMPLATES_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_AWAITING_SIGNOFF` | 409 Conflict |
| `ERR_TEMPLATE_NOT_DRAFT` | 409 Conflict |
| `ERR_TEMPLATE_NOT_ACTIVE` | 409 Conflict |
| `ERR_TEMPLATE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_POSTURE_NOT_READY` | 409 Conflict |
| `ERR_START_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_PANEL_NOT_OPEN` | 409 Conflict |
| `ERR_PANEL_NOT_FROZEN` | 409 Conflict |
| `ERR_PANEL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_CENSUS` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 Conflict |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EVENT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_EVENT_NOT_PLANNED` | 409 Conflict |
| `ERR_GUARANTEE_NOT_DRAFT` | 409 Conflict |
| `ERR_GUARANTEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_REPAYMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_MILESTONE_NOT_PENDING` | 409 Conflict |
| `ERR_REPORTING_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_MILESTONE_NOT_REPORTED` | 409 Conflict |
| `ERR_MENTOR_NOT_ACTIVE_PHYSICIAN` | 422 Unprocessable Entity |
| `ERR_MENTOR_SPECIALTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MENTOR_IS_MENTEE` | 422 Unprocessable Entity |
| `ERR_MENTORSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_CHECKINS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CHECKIN_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_CHECKIN_ALREADY_RECORDED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |

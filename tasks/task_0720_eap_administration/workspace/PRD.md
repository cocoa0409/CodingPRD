# EAP Administration API — Product Requirements Document

## 1. Introduction

The EAP Administration API is the system of record for operating an Employee Assistance Program on behalf of contracting employers. It models the full arc of an EAP engagement: an employer signs a contract that funds a finite pool of counseling sessions; employees and their dependents are enrolled against benefit plans; clinical cases are opened per presenting issue and draw down a per-issue session allotment; a 24/7 crisis line intakes and triages callers under a service-level agreement; network providers deliver counseling and submit claims that are adjudicated against an annual reimbursement budget; and the employer receives only aggregate, anonymized utilization reporting that never exposes the identity of any individual who sought help.

Two tensions run through every workflow and shape the rules below. The first is **confidentiality**: the same data that a care coordinator needs in order to help an employee is data the employer must never see, so the program enforces a strict firewall between operational PII and the employer's aggregate view. The second is **finite funding**: sessions are capped both per issue and per program year, reimbursement is bounded by an annual budget, and work-life referrals are capped per employee per year, so nearly every mutating operation must reconcile against one or more of these ledgers before it is allowed to proceed. The remainder of this document specifies the contracts, lifecycles, and calculations that hold these tensions in balance.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted under the `/eap` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If the `X-User-Role` header is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `ProgramAdmin`, `CareCoordinator`, `CrisisCounselor`, `Provider`, and `Employer`. A `ProgramAdmin` is the EAP program operator who manages contracts, plans, eligibility, claim adjudication, and reporting. A `CareCoordinator` is the clinical case manager who opens cases, authorizes funding, schedules sessions, and manages referrals. A `CrisisCounselor` staffs the 24/7 crisis line and intakes, triages, escalates, and resolves crisis contacts. A `Provider` is a network counselor who works referrals and sessions and submits claims. An `Employer` is the employer-side HR viewer.

Four of the five roles carry an **opaque identity**: when `X-User-Role` is `ProgramAdmin`, `CareCoordinator`, `CrisisCounselor`, or `Employer`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier for audit purposes but never compares it to any entity's `id`. The `Provider` role is **entity-backed**: when `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` record, and ownership checks on any resource that references a provider compare that resource's provider foreign key against `X-User-ID`. In particular, a provider may act on a referral only when the referral's assigned provider is the acting provider.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by each resource's creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a common set of server-managed fields. Each such resource has an `id`, a system-generated UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits stamped at creation; an `updated_at` timestamp of the same format, refreshed on every mutation; and a `version`, an integer that begins at 1 on creation and increments by one with every subsequent mutation. These common fields are present on employer contracts, benefit plans, employees, dependents, cases, counseling sessions, providers, referrals, crisis contacts, claims, and wellness activities.

The `UtilizationReport` resource is the sole exception: a utilization report carries only an `id` and a `created_at`. It has neither an `updated_at` nor a `version`, because a report is an immutable snapshot of a window and is never mutated after it is built.

All time in the system is governed by a single **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it remains at that value and never falls back to real time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant. Every timestamp the system stamps itself — a crisis contact's intake time, a triage time, and all relative comparisons such as session scheduling and SLA evaluation — reads from this logical clock.

### 2.5. Nested Resource Retrieval and Referential Integrity

When a request targets a resource by an identifier in its path, or references other resources by foreign keys in its body, the system validates existence left-to-right and rejects the first missing reference with `ERR_NOT_FOUND` (HTTP 404). A path identifier is checked before the body is examined, and within the body, parent references are checked before the rules that depend on them. This ordering guarantees that an operation never partially applies against a non-existent container.

Beyond mere existence, several creates must satisfy cross-foreign-key consistency, enforced with `ERR_REFERENTIAL_MISMATCH` (HTTP 409). When enrolling an employee, the supplied `plan_id` must name a benefit plan that belongs to the supplied `contract_id`. When submitting a claim, the counseling session named by `session_id` must trace, through its case, to the same contract named by the claim's `contract_id`. When creating a referral, the requested specialty must be resolvable against the provider network. These referential checks apply specifically to employee enrollment, claim submission, and referral creation.

### 2.6. Validation Ordering

When several checks could each reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence of all path and foreign-key resources (`ERR_NOT_FOUND`), then request well-formedness — required fields present, enum values valid, and numeric constraints satisfied (`ERR_INVALID_REQUEST`, HTTP 422). After well-formedness comes cross-foreign-key consistency (`ERR_REFERENTIAL_MISMATCH`), then the legality of the requested state transition for the target's current state (`ERR_INVALID_STATE`, HTTP 409), then the optimistic-concurrency version check (`ERR_STALE_CONTRACT_VERSION`, HTTP 412), and then the confidentiality firewall (`ERR_CONFIDENTIALITY_BLOCKED`, HTTP 403). Domain-specific business rules — crisis safety, temporal scheduling rules, and the fiscal caps described later — are evaluated after these foundational checks. Where two business rules of the same kind could both apply to one request, the more specific guidance in the relevant workflow subsection of §3 governs their relative order.

### 2.7. The Confidentiality Firewall

The program draws a hard line between operational personal data and the employer's view. An `Employer` may read contract-level and aggregate data — contracts, plans, contract utilization, and utilization reports — but is categorically barred from reading any resource that carries individual personal information. Specifically, an `Employer` attempting to read an employee, a dependent, a case, or a counseling session is rejected with `ERR_CONFIDENTIALITY_BLOCKED`. This block is distinct from a generic authorization failure: it expresses that the data exists but is confidential, not that the role is unknown or the route is forbidden in general. The employee `full_name`, the dependent `full_name`, and all clinical detail on cases and sessions are the protected payloads this firewall exists to shield.

### 2.8. Hierarchical Consistency and Cascades

Several operations mutate more than one resource. Whenever a contract leaves its `ACTIVE` state by being suspended or terminated, a revoke cascade fires across that contract's funded work. Likewise, revoking a single case cancels its scheduled sessions and rejects their pending claims. In every such cascade, each entity that is actually mutated has its `updated_at` refreshed and, where it carries a `version`, its `version` incremented. The precise hops of each cascade are specified in the workflow subsections of §3; the principle here is that the system, not the client, drives these secondary mutations to keep funding, scheduling, and claim records mutually consistent.

### 2.9. Optimistic Concurrency Control on Contracts

Two classes of operation draw on or alter an employer contract's funding posture and are therefore guarded by optimistic concurrency control keyed on the contract's `version`.

First, **authorizing a case** must carry an `expected_contract_version` field whose value equals the funding contract's current `version`. Authorization snapshots the per-issue allotment from the contract and consumes against the annual cap, so it must act on a current view of the contract. If another writer has advanced the contract's `version` since the client last read it — for example by suspending, reinstating, or terminating the contract, each of which bumps the version and may have changed committed-session totals through a revoke cascade — the authorize is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), preventing funding from being drawn against a contract the client has not actually observed.

Second, **suspending a contract** must carry an `expected_contract_version` matching the contract's current `version`. If another writer has already reinstated or terminated the contract (each bumping the version) since the client's last read, the suspend is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) because the writer's view is stale. The same `expected_contract_version` field, with the same stale-version rejection under `ERR_STALE_CONTRACT_VERSION`, also guards reinstating and terminating a contract. Endpoints not named here do not take a contract version field and are not subject to this check.

### 2.10. Funding, Caps, and Monetary Precision

All monetary amounts in the system are integer cents — the contracted session rate, the annual reimbursement budget, the provider copay, billed amounts, and computed reimbursements are all whole numbers of cents. There is no fractional-cent arithmetic; the only rounding step in any monetary calculation is an explicit floor applied at the out-of-network reduction stage described in §3.

Contract utilization is the one ratio the system reports, and it is rounded to four decimal places using the round-half-up convention. Counts — cases, distinct employees, issue-breakdown cells, session tallies — are exact integers. Report cells and whole reports that fall below the configured anonymity floor are not rounded but suppressed, as detailed in §3.

The program enforces four distinct funding ceilings, each surfaced at the operation that would breach it: the annual session cap at the program-year level, the per-issue allotment at the case level, the work-life referral cap at the employee-and-plan level, and the annual reimbursement budget at claim adjudication. The numeric thresholds behind these ceilings live on the contract and plan, and the exact arithmetic that tests them is specified in the relevant workflow subsections.

## 3. Business Logic & Workflows

### 3.1. The Employer Contract: Funding Envelope and Lifecycle

Everything the program funds hangs off an **EmployerContract**, created by a `ProgramAdmin`. At creation the operator supplies the `employer_name`, the `sessions_per_issue` granted to each opened case (which must be at least 1 and at most 12), the `annual_session_cap` that bounds funded sessions across the whole program year (at least 1), the `session_rate_cents` reimbursed per in-network session (zero or more), and the `annual_reimbursement_budget_cents` that bounds total provider reimbursement across the year (zero or more). Two further fields are optional: `crisis_sla_minutes`, the maximum minutes from crisis intake to triage disposition before the SLA is breached (at least 1, defaulting to 15), and `reporting_min_cohort`, the k-anonymity floor below which aggregate report cells are suppressed (at least 1, defaulting to 5). A new contract begins with `status` of `ACTIVE`, `sessions_committed` of zero, `utilization_rate` of zero, and `version` of 1.

A contract exposes two computed funding figures. The `sessions_committed` count is the number of counseling sessions in `SCHEDULED` or `COMPLETED` status across every case of the contract — this is what the annual cap is measured against. The `utilization_rate` is `sessions_committed` divided by the `annual_session_cap`, rounded to four decimal places half-up. By default, and when a contract is fetched, this committed figure counts both scheduled and completed sessions (the forward-looking basis). The contract may also be examined on a **verified** basis, which counts only `COMPLETED` sessions and excludes those merely `SCHEDULED`, yielding a rate less than or equal to the committed rate; the basis is chosen by a `basis` query value of either committed (the default) or verified.

A `ProgramAdmin` moves a contract through its lifecycle. From `ACTIVE`, the contract may be suspended (to `SUSPENDED`), or terminated (to `TERMINATED`). From `SUSPENDED`, it may be reinstated (back to `ACTIVE`) or terminated (to `TERMINATED`). `TERMINATED` is terminal. Each of these four transitions requires the matching `expected_contract_version` and increments the contract's `version` by one. Suspension and termination both fire the revoke cascade described in §3.4: every case on the contract whose `funding_status` is `AUTHORIZED` is driven to `REVOKED`, and each such revocation cancels that case's `SCHEDULED` sessions and decrements `sessions_committed` accordingly. Reinstatement bumps the version but does **not** restore previously revoked cases — revocation is permanent, and a reinstated contract starts fresh from its surviving state.

### 3.2. Benefit Plans, Enrollment, and Eligibility

A **BenefitPlan** is created under a contract by a `ProgramAdmin`, who supplies the owning `contract_id` and a member-facing `name`. Two plan parameters are optional at creation: `worklife_referrals_per_year`, the maximum work-life, legal, or financial referrals fundable per employee per program year under the plan (zero or more, defaulting to 3), and `copay_cents`, the member copay per counseling session that is subtracted from contract reimbursement on each claim (zero or more, defaulting to 0). A plan is born in `DRAFT` status and must be published — moving it to `PUBLISHED` — before any employee can be assigned to it. Plans may eventually be `RETIRED`.

Enrolling an **Employee** is a `ProgramAdmin` action that supplies the sponsoring `contract_id`, the assigned `plan_id`, the employee's `full_name`, and an `external_ref` payroll reference. The chosen plan must belong to the named contract, and it must already be `PUBLISHED`; enrolling against an unpublished plan is rejected with `ERR_PLAN_NOT_PUBLISHED`. The `external_ref` must be unique within the contract; a collision is rejected with `ERR_DUPLICATE_EXTERNAL_REF`. A newly enrolled employee has `eligibility_status` of `ELIGIBLE`. Each employee also exposes a computed `worklife_referrals_used` count, defined as the number of that employee's referrals whose `referral_type` is `WORKLIFE`, `LEGAL`, or `FINANCIAL` and whose status is neither `CANCELLED` nor `DENIED`, accumulated within the current program year.

A `ProgramAdmin` may change an employee's `eligibility_status` to `ELIGIBLE`, `GRACE`, or `INELIGIBLE`. When the new status is `GRACE`, a `grace_until` instant is set; while the logical clock is at or before `grace_until`, an employee pending ineligibility retains grace coverage, and `grace_until` is otherwise null. Eligibility matters at case authorization: only an employee whose status is `ELIGIBLE` or `GRACE` may have a case authorized, and an `INELIGIBLE` employee causes authorization to fail with `ERR_EMPLOYEE_INELIGIBLE`.

A **Dependent** is added to an employee by a `ProgramAdmin` or a `CareCoordinator`, who supply the sponsoring `employee_id`, the dependent's `full_name`, and the `relationship`, which is one of `SPOUSE`, `CHILD`, or `OTHER`. A dependent begins `ELIGIBLE`. A dependent's eligibility mirrors the sponsor but may be revoked independently, so a dependent's own `eligibility_status` may be `ELIGIBLE` or `INELIGIBLE`.

### 3.3. Opening and Funding a Case

A **Case** represents one presenting issue for one subject and is opened by a `CareCoordinator`, who supplies the funding `contract_id`, the sponsoring `employee_id` whose benefit funds the case, the `presenting_issue` — one of `STRESS`, `RELATIONSHIP`, `SUBSTANCE`, `GRIEF`, `FINANCIAL_STRESS`, or `OTHER` — and, when the subject is a dependent rather than the employee, an optional `dependent_id`. If a `dependent_id` is supplied, it must be a dependent of the named `employee_id`; otherwise the open is rejected with `ERR_DEPENDENT_NOT_UNDER_EMPLOYEE`. A case carries two parallel state dimensions. The clinical dimension, `clinical_status`, runs `INTAKE` → `OPEN` → `CLOSED`. The funding dimension, `funding_status`, runs `PENDING`, `AUTHORIZED`, `EXHAUSTED`, and `REVOKED`. A new case starts at `clinical_status` of `INTAKE` and `funding_status` of `PENDING`.

Authorizing a case is the moment funding is committed, and it is performed by a `CareCoordinator` carrying the `expected_contract_version`. Authorization is permitted only when the case's `clinical_status` is `INTAKE`; a case that is already `CLOSED` cannot be authorized. Three further conditions must hold. The funding contract's `status` must be `ACTIVE`, or the request fails with `ERR_CONTRACT_NOT_ACTIVE`. The sponsoring employee's `eligibility_status` must be `ELIGIBLE` or `GRACE`, or the request fails with `ERR_EMPLOYEE_INELIGIBLE`. And the annual cap must have room: the contract's current `sessions_committed` plus the contract's `sessions_per_issue` must be less than or equal to the contract's `annual_session_cap`, or the request fails with `ERR_ANNUAL_CAP_EXCEEDED`. On success, the case snapshots its `session_allotment` from the contract's `sessions_per_issue` at that moment, its `funding_status` advances to `AUTHORIZED`, and its `clinical_status` advances in lockstep from `INTAKE` to `OPEN`.

A case tracks two computed session figures. The `sessions_used` count is the number of counseling sessions on the case in `SCHEDULED` or `COMPLETED` status. The `sessions_remaining` figure is the larger of zero and the difference between `session_allotment` and `sessions_used`, and it is zero whenever `funding_status` is `EXHAUSTED`.

A `CareCoordinator` closes a case clinically, moving `clinical_status` from `OPEN` to `CLOSED`. A case may not be closed while it still has any session in `SCHEDULED` status; the attempt is rejected with `ERR_CASE_HAS_OPEN_SESSIONS`. Closing the clinical dimension does not force the funding dimension to any terminal value — `funding_status` retains whatever value it held (`AUTHORIZED` or `EXHAUSTED`) at the time of closure.

### 3.4. Revocation and the Cascade Ledger

Funding can be withdrawn from a case in two ways, and both run the same downstream cleanup. A `ProgramAdmin` may directly revoke a case, and the contract-level suspend and terminate operations of §3.1 revoke cases as a cascade. A case may be revoked from either `AUTHORIZED` or `EXHAUSTED`, and in both situations revocation is permitted only while the case's `clinical_status` is not `CLOSED`. Driving a case to `REVOKED` performs three cascade hops in sequence: every counseling session on the case that is in `SCHEDULED` status is moved to `CANCELLED`; each such cancelled session decrements the funding contract's `sessions_committed`, keeping the annual-cap ledger in sync; and any claim that referenced one of those sessions and stood in `SUBMITTED` or `UNDER_REVIEW` status is moved to `REJECTED`. When a case is revoked from `EXHAUSTED`, no sessions remain in `SCHEDULED` to cancel because the allotment was already fully consumed, so the cascade simply finds nothing to undo. Every entity touched by these hops has its `updated_at` refreshed and, where applicable, its `version` incremented.

### 3.5. Scheduling and Running Counseling Sessions

A **CounselingSession** is scheduled on a case by a `CareCoordinator`, who supplies the delivering counselor via `provider_id`, the `scheduled_for` start time, and an optional `duration_minutes` (at least 30 and at most 120, defaulting to 50). The session's owning `case_id` comes from the case being scheduled against. A new session begins in `SCHEDULED` status, and scheduling one recomputes the case's `sessions_used`; when that count reaches the case's `session_allotment`, the case's `funding_status` advances from `AUTHORIZED` to `EXHAUSTED`, its `sessions_remaining` is set to zero, and any further scheduling attempt on that case is rejected with `ERR_ALLOTMENT_EXHAUSTED`.

Scheduling is guarded by several rules in addition to the allotment ceiling. The `scheduled_for` instant must be at or after the logical clock's current value; back-dated scheduling is rejected with `ERR_SESSION_IN_PAST`. A provider's sessions may not overlap in time: if the chosen provider already holds a `SCHEDULED` session whose interval — from its start through its start plus its planned duration — overlaps the newly requested interval, the request is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. Separately, and at a coarser granularity, a single case may not hold two `SCHEDULED` sessions that fall on the same UTC calendar day; this same-day collision, distinct from the provider's minute-level overlap, is rejected with `ERR_CASE_SAME_DAY_SESSION`.

A scheduled session is advanced by a `CareCoordinator` or a `Provider` to one of `COMPLETED`, `NO_SHOW`, or `CANCELLED` via a `to_status` value. Cancelling a session frees the allotment slot it held, which in turn lowers the case's `sessions_used` and the contract's `sessions_committed` for any session that had been counted.

### 3.6. The Crisis Line: Intake, Triage, and SLA

A **CrisisContact** is opened on the 24/7 line by a `CrisisCounselor`, who supplies the `contract_id` under which the call arrived, the caller-reported `severity` — one of `LOW`, `MODERATE`, `HIGH`, or `IMMINENT` — and, for a non-anonymous caller, an optional `employee_id`. At creation the contact's `opened_at` is stamped from the logical clock, its `status` is `OPEN`, and its `disposition` is null.

A `CrisisCounselor` triages an open contact, supplying a `disposition` of `SELF_HELP`, `ROUTINE_REFERRAL`, `URGENT_REFERRAL`, or `EMERGENCY_DISPATCH`. Triage moves `status` from `OPEN` to `TRIAGED`, stamps `triaged_at` from the clock, records the chosen disposition, and evaluates the SLA. The SLA is the elapsed time from `opened_at` to `triaged_at` measured in whole minutes; `sla_breached` is true only when that elapsed figure is strictly greater than the contract's `crisis_sla_minutes`, so an elapsed time exactly equal to the SLA is within bounds and not a breach. When a contact has not yet been triaged, `sla_breached` is computed against the elapsed minutes from `opened_at` to the clock's current value, and a fetch of a crisis contact recomputes this figure.

From `TRIAGED`, the contact forks. It may be **escalated** by a `CrisisCounselor` — moving `status` to `ESCALATED` — but only when its recorded disposition is `URGENT_REFERRAL` or `EMERGENCY_DISPATCH`; an escalation attempt on any other disposition is rejected with `ERR_DISPOSITION_NOT_ESCALATABLE`. Escalation supplies a `required_specialty` and, as a side effect, creates a `CLINICAL` referral in `REQUESTED` status with a provider auto-selected by the selection policy. Alternatively, a triaged contact may be **resolved** directly by a `CrisisCounselor` — moving `status` to `RESOLVED` — but only when its disposition is `SELF_HELP` or `ROUTINE_REFERRAL`; a direct-resolve attempt on any other disposition is rejected with `ERR_DISPOSITION_NOT_RESOLVABLE`. An escalated contact is later resolved by a `CrisisCounselor` from `ESCALATED` to `RESOLVED` with no further disposition restriction. Overriding the direct-resolve branch entirely, a contact whose intake `severity` was `IMMINENT` can never be resolved directly out of triage; it must be escalated first, and any direct-resolve attempt on it is rejected with `ERR_IMMINENT_REQUIRES_ESCALATION`.

### 3.7. The Provider Network and Referrals

A **Provider** is registered by a `ProgramAdmin`, who supplies the counselor's `full_name`, an optional `network_status` of `IN_NETWORK` or `OUT_OF_NETWORK` (defaulting to `IN_NETWORK`), the `specialties` list of presenting-issue values the provider handles, and an optional `accepting` flag indicating whether the provider currently takes new referrals (defaulting to true). A provider exposes a computed `active_referral_count`, the number of referrals to that provider currently in `REQUESTED` or `ACCEPTED` status, used as the load-balancing input for selection.

A **Referral** is created by a `CareCoordinator`, who supplies the `employee_id` the referral is for, the `referral_type` — one of `CLINICAL`, `WORKLIFE`, `LEGAL`, or `FINANCIAL` — a `required_specialty` to match against the provider pool, and, when the referral arises from a clinical case, an optional `case_id` (left null for standalone work-life referrals). On creation the server auto-selects a provider, the referral's `status` becomes `REQUESTED`, the chosen provider is recorded in `provider_id`, and that provider's `active_referral_count` rises by one. For a `WORKLIFE`, `LEGAL`, or `FINANCIAL` referral, the work-life cap is enforced before the referral is created: the employee's `worklife_referrals_used` plus one must be less than or equal to the plan's `worklife_referrals_per_year`, or the create is rejected with `ERR_WORKLIFE_CAP_EXCEEDED`. A referral that an administrator explicitly denies, or that is rejected at creation for cap reasons, lands in `DENIED` status.

**Provider selection** runs at referral creation and at reassignment. The candidate pool is every provider whose `accepting` flag is true, whose `network_status` is `IN_NETWORK`, whose `specialties` include the referral's required specialty, and whose `id` is not the excluded provider (the just-declined provider on a reassignment). If the candidate pool is empty after these filters, the operation fails with `ERR_NO_PROVIDER_AVAILABLE`. Otherwise the server picks the candidate with the lowest `active_referral_count`; ties are broken by the earliest provider `created_at`, and the provider `id` is never used as a tie-breaker.

The referral lifecycle proceeds as follows. From `REQUESTED`, the assigned provider may **accept** (to `ACCEPTED`) or **decline** (to `DECLINED`); in both cases the acting provider must be the referral's assigned provider, or the action is rejected with `ERR_NOT_ASSIGNED_PROVIDER`. Acceptance leaves the provider's `active_referral_count` unchanged, since an `ACCEPTED` referral still counts toward load. Declining clears the referral's `provider_id` to null, decrements that provider's `active_referral_count`, and makes the referral eligible for re-selection. A `CareCoordinator` then **reassigns** a declined referral, returning it from `DECLINED` to `REQUESTED` by selecting a new provider through the selection policy with the just-declined provider excluded; if no provider is selectable, the reassign fails with `ERR_NO_PROVIDER_AVAILABLE`, and on success the newly selected provider's `active_referral_count` rises by one. From `ACCEPTED`, the assigned provider **completes** the referral (to `COMPLETED`), which lowers that provider's `active_referral_count` by one. From `REQUESTED`, a `CareCoordinator` may instead **cancel** the referral (to `CANCELLED`). The terminal referral states are `COMPLETED`, `CANCELLED`, and `DENIED`.

### 3.8. Claims: Submission, Adjudication, and the Reimbursement Budget

A **Claim** is submitted by a `Provider` for a completed session, supplying the payer `contract_id`, the `session_id` being claimed, and the provider-billed amount `billed_cents` (zero or more). The session's case must trace to the same contract named on the claim. At most one live claim may exist per session: if a non-`REJECTED` claim already exists for the same `session_id`, the submission is rejected with `ERR_CLAIM_ALREADY_CLAIMED`. The claim records the payee `provider_id` from the session and begins in `SUBMITTED` status. The claim's `status` moves through the cycle `SUBMITTED`, `UNDER_REVIEW`, and then either `APPROVED` or `REJECTED`; a rejected claim may be resubmitted as `RESUBMITTED` and re-enter review, and an approved claim is paid as `PAID`, which is terminal.

At submission the system computes the claim's **provisional** reimbursement, `provisional_cents`, looking forward from the submitted figures alone and ignoring any remaining-budget pressure. The computation walks the session-to-provider-to-contract-to-plan chain. It starts from the contract's `session_rate_cents` as the in-network base. If the payee provider's `network_status` is `OUT_OF_NETWORK`, that base is reduced to seventy percent by multiplying it by seven and then taking the floor of the result divided by ten — this floor is the only rounding step in the calculation. The reimbursable gross is then the smaller of the submitted `billed_cents` and that (possibly reduced) base, so the program never reimburses above the contracted base. Finally, `provisional_cents` is the larger of zero and that gross minus the plan's `copay_cents`.

A `ProgramAdmin` adjudicates claims. **Review** moves a claim from `SUBMITTED` (or from `RESUBMITTED`) to `UNDER_REVIEW`, and is permitted only when the session named by `session_id` is `COMPLETED`; otherwise it fails with `ERR_SESSION_NOT_COMPLETED`. Review locks the already-computed `provisional_cents` for adjudication. **Approval** moves a claim from `UNDER_REVIEW` to `APPROVED` and requires that the contract's `status` be `ACTIVE`, failing otherwise with `ERR_CONTRACT_NOT_ACTIVE`. At approval the system computes the claim's **final** reimbursement, `final_cents`, by reconciling against the annual reimbursement budget already committed. It sums the `final_cents` of all claims of the same contract that are already in `APPROVED` or `PAID` status, processed in ascending `created_at` order and excluding the claim now being approved, to find how much budget is already spent. The remaining budget is the larger of zero and the contract's `annual_reimbursement_budget_cents` minus that spent total. The claim's `final_cents` is then the smaller of its `provisional_cents` and that remaining budget, so the final figure may be less than the provisional figure when the remaining budget is the binding constraint, and equal to it otherwise.

**Rejection** moves a claim from `UNDER_REVIEW` to `REJECTED` and leaves `final_cents` null. **Resubmission** is performed by the `Provider` on a `REJECTED` claim, supplying a corrected `billed_cents`; it moves the claim to `RESUBMITTED` and recomputes `provisional_cents` from the corrected amount, re-entering the adjudication cycle. **Payment** moves a claim from `APPROVED` to `PAID`, the terminal state. Until a claim is approved, its `final_cents` is null.

### 3.9. Wellness Activities and Anonymized Reporting

A **WellnessActivity** is logged for an employee by a `ProgramAdmin` or a `CareCoordinator`, who supply the participant's `employee_id`, the `activity_type` — one of `SCREENING`, `WEBINAR`, `CHALLENGE`, or `COACHING` — the `points` earned (at least 0 and at most 100), and the `completed_on` date the activity was finished. Wellness activities are a flat log with no further lifecycle.

A **UtilizationReport** is built for a contract by a `ProgramAdmin` or an `Employer`, who supply the reporting window via `period_start` and `period_end`. The window is half-open and must be non-empty: `period_start` must be strictly earlier than `period_end`, or the build is rejected with `ERR_INVALID_WINDOW`. The report counts only cases whose creation falls within the half-open window — at or after `period_start` and strictly before `period_end`. Within that window the report computes `total_cases`, the count of cases, and `distinct_employees`, the count of distinct sponsoring employees across those cases, which serves as the k-anonymity denominator.

Anonymization is applied in two tiers against the contract's `reporting_min_cohort` floor. If the window's `distinct_employees` is below `reporting_min_cohort`, the whole report is suppressed: `suppressed` is true and the `issue_breakdown` is rendered with every cell set to the sentinel value of -1. Otherwise `suppressed` is false, and the report builds `issue_breakdown` as a map from each `presenting_issue` value to its case count within the window — but each cell is itself checked against the floor: if the number of distinct employees behind a given issue cell is below `reporting_min_cohort`, that cell is replaced by the -1 sentinel while the cells that pass the floor show their true counts. A report is immutable once built and can be fetched or listed thereafter.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, including state transitions and the logical-clock control, return `200 OK`. The clock-setting endpoint returns `200 OK` and no resource body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eap/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/eap/contracts` | Create an employer contract | ProgramAdmin |
| GET | `/eap/contracts` | List employer contracts | ProgramAdmin |
| GET | `/eap/contracts/{id}` | Get a contract (committed utilization) | ProgramAdmin, Employer |
| GET | `/eap/contracts/{id}/utilization` | Get contract utilization (committed or verified) | ProgramAdmin, Employer |
| POST | `/eap/contracts/{id}/suspend` | Suspend a contract (OCC; revoke cascade) | ProgramAdmin |
| POST | `/eap/contracts/{id}/reinstate` | Reinstate a suspended contract (OCC) | ProgramAdmin |
| POST | `/eap/contracts/{id}/terminate` | Terminate a contract (OCC; revoke cascade) | ProgramAdmin |
| POST | `/eap/contracts/{id}/reports` | Build an anonymized utilization report | ProgramAdmin, Employer |
| GET | `/eap/reports` | List utilization reports | ProgramAdmin, Employer |
| GET | `/eap/reports/{id}` | Get a utilization report | ProgramAdmin, Employer |
| POST | `/eap/plans` | Create a benefit plan under a contract | ProgramAdmin |
| GET | `/eap/plans` | List benefit plans | ProgramAdmin, Employer |
| GET | `/eap/plans/{id}` | Get a benefit plan | ProgramAdmin, Employer |
| POST | `/eap/plans/{id}/publish` | Publish a draft plan | ProgramAdmin |
| POST | `/eap/employees` | Enroll an employee | ProgramAdmin |
| GET | `/eap/employees` | List employees | ProgramAdmin, CareCoordinator |
| GET | `/eap/employees/{id}` | Get an employee (confidentiality-gated) | ProgramAdmin, CareCoordinator |
| POST | `/eap/employees/{id}/eligibility` | Set employee eligibility | ProgramAdmin |
| POST | `/eap/dependents` | Add a dependent to an employee | ProgramAdmin, CareCoordinator |
| GET | `/eap/dependents` | List dependents | ProgramAdmin, CareCoordinator |
| GET | `/eap/dependents/{id}` | Get a dependent | ProgramAdmin, CareCoordinator |
| POST | `/eap/cases` | Open a counseling case | CareCoordinator |
| GET | `/eap/cases` | List cases | ProgramAdmin, CareCoordinator |
| GET | `/eap/cases/{id}` | Get a case (confidentiality-gated) | ProgramAdmin, CareCoordinator |
| POST | `/eap/cases/{id}/authorize` | Authorize case funding (OCC) | CareCoordinator |
| POST | `/eap/cases/{id}/revoke` | Revoke a case's funding | ProgramAdmin |
| POST | `/eap/cases/{id}/close` | Close a case clinically | CareCoordinator |
| POST | `/eap/cases/{id}/sessions` | Schedule a counseling session | CareCoordinator |
| GET | `/eap/sessions` | List counseling sessions | ProgramAdmin, CareCoordinator |
| GET | `/eap/sessions/{id}` | Get a counseling session | ProgramAdmin, CareCoordinator |
| POST | `/eap/sessions/{id}/status` | Advance a session's status | CareCoordinator, Provider |
| POST | `/eap/providers` | Register a network provider | ProgramAdmin |
| GET | `/eap/providers` | List providers | ProgramAdmin, CareCoordinator |
| GET | `/eap/providers/{id}` | Get a provider | ProgramAdmin, CareCoordinator, Provider |
| POST | `/eap/referrals` | Create a referral (auto-selects provider) | CareCoordinator |
| GET | `/eap/referrals` | List referrals | ProgramAdmin, CareCoordinator, Provider |
| GET | `/eap/referrals/{id}` | Get a referral | ProgramAdmin, CareCoordinator, Provider |
| POST | `/eap/referrals/{id}/accept` | Provider accepts a referral | Provider |
| POST | `/eap/referrals/{id}/decline` | Provider declines a referral | Provider |
| POST | `/eap/referrals/{id}/reassign` | Reassign a declined referral | CareCoordinator |
| POST | `/eap/referrals/{id}/complete` | Mark an accepted referral complete | Provider |
| POST | `/eap/referrals/{id}/cancel` | Cancel a requested referral | CareCoordinator |
| POST | `/eap/crisis-contacts` | Open a crisis contact | CrisisCounselor |
| GET | `/eap/crisis-contacts` | List crisis contacts | ProgramAdmin, CrisisCounselor |
| GET | `/eap/crisis-contacts/{id}` | Get a crisis contact (recomputes SLA) | ProgramAdmin, CrisisCounselor |
| POST | `/eap/crisis-contacts/{id}/triage` | Record triage disposition | CrisisCounselor |
| POST | `/eap/crisis-contacts/{id}/escalate` | Escalate a triaged contact | CrisisCounselor |
| POST | `/eap/crisis-contacts/{id}/resolve` | Resolve a triaged or escalated contact | CrisisCounselor |
| POST | `/eap/claims` | Submit a claim for a completed session | Provider |
| GET | `/eap/claims` | List claims | ProgramAdmin, Provider |
| GET | `/eap/claims/{id}` | Get a claim | ProgramAdmin, Provider |
| POST | `/eap/claims/{id}/review` | Move a claim to under review | ProgramAdmin |
| POST | `/eap/claims/{id}/approve` | Approve a claim (computes final cents) | ProgramAdmin |
| POST | `/eap/claims/{id}/reject` | Reject a claim under review | ProgramAdmin |
| POST | `/eap/claims/{id}/resubmit` | Resubmit a rejected claim | Provider |
| POST | `/eap/claims/{id}/pay` | Pay an approved claim | ProgramAdmin |
| POST | `/eap/wellness-activities` | Log a wellness activity | ProgramAdmin, CareCoordinator |
| GET | `/eap/wellness-activities` | List wellness activities | ProgramAdmin, CareCoordinator |
| GET | `/eap/wellness-activities/{id}` | Get a wellness activity | ProgramAdmin, CareCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REFERENTIAL_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_CONFIDENTIALITY_BLOCKED` | 403 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_EMPLOYEE_INELIGIBLE` | 409 |
| `ERR_ANNUAL_CAP_EXCEEDED` | 409 |
| `ERR_ALLOTMENT_EXHAUSTED` | 409 |
| `ERR_WORKLIFE_CAP_EXCEEDED` | 409 |
| `ERR_CASE_HAS_OPEN_SESSIONS` | 409 |
| `ERR_SESSION_NOT_COMPLETED` | 409 |
| `ERR_SESSION_IN_PAST` | 422 |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 |
| `ERR_CASE_SAME_DAY_SESSION` | 409 |
| `ERR_NO_PROVIDER_AVAILABLE` | 409 |
| `ERR_NOT_ASSIGNED_PROVIDER` | 403 |
| `ERR_DISPOSITION_NOT_ESCALATABLE` | 409 |
| `ERR_DISPOSITION_NOT_RESOLVABLE` | 409 |
| `ERR_IMMINENT_REQUIRES_ESCALATION` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_PLAN_NOT_PUBLISHED` | 409 |
| `ERR_DEPENDENT_NOT_UNDER_EMPLOYEE` | 409 |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 |
| `ERR_CLAIM_ALREADY_CLAIMED` | 409 |

# Interconnection Queue API — Product Requirements Document

## 1. Introduction

Grid operators and utilities face a structural bottleneck: distributed energy resources — solar farms, wind plants, battery installations, and hybrid facilities — cannot reach commercial operation until each one passes through a formal interconnection study queue. That queue is today managed in spreadsheets and email threads, with deposit receipts reconciled by hand, cluster study costs allocated inconsistently, and withdrawal-triggered restudies tracked nowhere at all. The result is opaque queue positions, disputed cost allocations, and missed agreement deadlines that stall gigawatts of clean generation.

This document specifies the Interconnection Queue API, a system that administers the full interconnection study lifecycle on behalf of an ISO or utility. It governs how developers join a cluster study group during an application window, how deposits are assessed and forfeited, how readiness evidence is reviewed, how the cluster impact study is scoped, cost-shared, published, and reopened on withdrawal, how interconnection agreements are issued, extended, and executed against hard deadlines, and how operating-limit conditions and public transparency statistics are recorded. Every rule herein — from the half-open application-window semantics to the residual reconciliation in cost allocation — is binding on the implementation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a value the server cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the caller is authenticated, the role must also be authorized for the specific endpoint; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly four roles, spelled as follows: `Developer`, `QueueAdministrator`, `StudyEngineer`, and `Regulator`.

When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `Developer` entity; ownership checks on any resource that references a `Developer` compare the resource's foreign-key field to `X-User-ID`. In practice this means a `Developer` caller may only act on projects whose `developer_id` equals their `X-User-ID` — for child resources such as deposit ledger entries, milestone submissions, and agreements, ownership is resolved through the parent project. A `Developer` caller who touches a project belonging to someone else is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403).

When `X-User-Role` is `QueueAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. The same holds for `X-User-Role` equal to `StudyEngineer` and for `X-User-Role` equal to `Regulator` — both are opaque operator identifiers with no entity-backed ownership semantics. The `Regulator` role is read-only across the entire API.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the list and defaults to 0. All list endpoints sort their results by `created_at` ascending, earliest first. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource carries a system-minted `id`, formatted as a bare UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources — specifically `Developer`, `ClusterGroup`, `Project`, `MilestoneSubmission`, `Study`, `CostShare`, and `InterconnectionAgreement` — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on any mutation, and `version`, an integer that starts at its initial value and increments by one on every mutation of the resource. Two resource kinds are deliberately lighter: `DepositTransaction` and `CurtailmentLimit` and `TransparencyReport` carry only `id` and `created_at` — `updated_at` and `version` are absent from them entirely, because a ledger entry, an operating-limit record, and a published snapshot are immutable once written.

### 2.5. Monetary Precision and Rounding

All money in the system is expressed in integer cents. Deposit requirements, ledger amounts, study totals, and cost-share allocations are all rounded to zero decimal places using round-half-up. Where a calculation has multiple additive components, each component is rounded half-up to integer cents first and only then summed — the order is pinned and must not be reversed. Capacity figures in MW are plain numbers and are never rounded.

### 2.6. The Logical Clock

Several deadlines in this domain are clock-relative: an agreement must be executed within ninety days of issuance, an extension must be requested at least thirty days before the current target commercial operation date, and commercial operation must be declared no later than the (possibly extended) target date. All such comparisons are made against the server's **logical clock**, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit clock-setting call, every deadline evaluation uses this default. A `QueueAdministrator`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant, after which all deadline evaluations use the new value. Timestamp comparisons at deadline boundaries are inclusive: an execute attempt arriving at the exact deadline timestamp is permitted.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in this API is guarded by optimistic concurrency control: the issuance or re-issuance of an interconnection agreement against a project. That request must carry `expected_project_version`, holding the client's last observed `version` of the target `Project`. If the value does not match the project's current `version` — for example because another writer has advanced the project since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a project state it has not observed. No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.8. Nested Resource Retrieval and Validation Order

Requests that address nested resources — a deposit ledger under a project, a study under a cluster group — have their path identifiers validated left to right. The first identifier that does not resolve to an existing resource determines the 404 error: a missing developer yields `ERR_DEVELOPER_NOT_FOUND`, a missing cluster group `ERR_CLUSTER_GROUP_NOT_FOUND`, a missing project `ERR_PROJECT_NOT_FOUND`, a missing study `ERR_STUDY_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`, a missing milestone submission `ERR_MILESTONE_SUBMISSION_NOT_FOUND`, and a missing transparency report `ERR_TRANSPARENCY_REPORT_NOT_FOUND` — each at HTTP 404, and always in path order before any business rule is consulted.

Across the whole request pipeline, validation categories run in a fixed priority order. First, the presence and validity of the user-context headers is checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the role's permission for the endpoint is checked (`ERR_INSUFFICIENT_PERMISSIONS`). Third, resource existence along path and body identifiers is verified left to right (the 404 family above). Fourth, for `Developer`-scoped writes, resource ownership is enforced (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`). Fifth, the optimistic-concurrency check on `expected_project_version` is applied where that field is required (`ERR_STALE_VERSION`). Sixth, state preconditions of the target resource are evaluated (the state-rejection family, all HTTP 409). Seventh, clock-relative deadline rules fire (`ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED`, `ERR_EXTENSION_WINDOW_MISSED`, `ERR_COD_DEADLINE_PASSED`). Eighth, cross-entity state requirements are checked — agreement issuance requires the cluster study to be published or finalized (`ERR_STUDY_NOT_PUBLISHED`), and agreement execution requires the study finalized (`ERR_STUDY_NOT_FINALIZED`). Ninth, structural business constraints are enforced (capacity, window-overlap, uniqueness, and conflict errors, plus `ERR_INVALID_REQUEST` for malformed inputs). Tenth and last, the deposit-ledger fiscal check runs (`ERR_DEPOSIT_OVERPAYMENT`, HTTP 422). Where two rules from different categories could both fire on the same request, the earlier category's error wins.

### 2.9. Queue Capacity, Windows, and Intervals

A cluster group admits projects only while its application window is open in a structural sense — that is, while the cluster remains in `FORMING`. The window is half-open: `application_window_open` marks the inclusive start and `application_window_close` the exclusive end, and the close must be strictly later than the open, otherwise creation fails with `ERR_INVALID_WINDOW` (HTTP 400). Within a single `region`, the application windows of any two clusters that are not both closed may not overlap; adjacency — one cluster's close exactly equal to another's open — is permitted because of the half-open semantics. An overlapping window is rejected with `ERR_CLUSTER_WINDOW_OVERLAP` (HTTP 409).

A cluster's `capacity_mw` bounds the total nameplate it will study: at project creation, the cluster's `committed_mw` plus the new project's `capacity_mw` must not exceed the cluster's `capacity_mw`, or creation fails with `ERR_CLUSTER_CAPACITY_EXCEEDED` (HTTP 409). Curtailment effective intervals, by contrast, are **closed** intervals: `effective_start` through `effective_end` inclusive, with the end strictly after the start (`ERR_INVALID_WINDOW` otherwise). Two limits on the same project with the same `limit_type` must have disjoint effective intervals — and because the intervals are closed, touching endpoints count as overlap, triggering `ERR_CURTAILMENT_WINDOW_OVERLAP` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Onboarding Developers and Standing Up a Cluster

Before any project exists, a `QueueAdministrator` onboards an interconnection customer by providing the organization's `legal_name`, its `contact_email`, and a `developer_type` of `IPP`, `UTILITY_SCALE`, or `COMMUNITY`. The resulting `Developer` record is the identity anchor for everything the customer later does.

A `QueueAdministrator` also stands up each cluster study group by naming it (`name`), fixing its ISO `region`, declaring the half-open application window via `application_window_open` and `application_window_close`, and capping the study scope with `capacity_mw`, which must be greater than zero. A new cluster begins in `FORMING` with `committed_mw` initialized to zero. The `committed_mw` figure is read-only and is reconciled incrementally: it rises by a project's `capacity_mw` whenever a project is created into the cluster, and falls by the same amount whenever a member withdraws — so creating and then withdrawing the same project leaves `committed_mw` exactly unchanged, and at any moment it equals the sum of `capacity_mw` over member projects whose status is anything other than `WITHDRAWN`.

### 3.2. Entering the Queue: Projects, Deposits, and Position Assignment

A `Developer` submits an interconnection request into a specific cluster by supplying a payload containing the `developer_id`, the target `cluster_group_id`, a `project_name`, a `technology` of `SOLAR`, `WIND`, `STORAGE`, or `HYBRID`, the `capacity_mw` nameplate (greater than zero and at most 500), a `service_type` of `ENERGY_ONLY` or `CAPACITY`, and the `point_of_interconnection` identifying the substation or feeder. The owning developer for this creation is taken from the request body's `developer_id`, which must equal the caller's `X-User-ID`. The cluster must still be `FORMING`; otherwise the submission is rejected with `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`. The capacity check of §2.9 applies here.

At creation, the system assesses the study deposit and stamps it onto the read-only `deposit_required_cents`. The assessment has two variants, and the variant is selected first: if the `technology` is `STORAGE` and the `capacity_mw` is at most five MW, the project follows the **EXPEDITED** track and its required deposit is a flat 300000 cents, regardless of capacity or service type. Every other project follows the **STANDARD** track: the first twenty MW of nameplate are billed at 100000 cents per MW, any nameplate beyond twenty MW is billed at 250000 cents per MW, and the resulting base is then multiplied by 1.0 for `ENERGY_ONLY` service or by 1.2 for `CAPACITY` service, with the product rounded half-up to whole cents. Concretely, an identical five-MW `ENERGY_ONLY` project would owe 500000 cents under STANDARD but pays only 300000 cents under EXPEDITED — the divergence between the two tracks is intentional. The new project's `status` field lands in `SUBMITTED` with `deposit_posted_cents` at zero, `queue_position` null, and `readiness_satisfied` false; `status` thereafter tracks the project's position along the lifecycle from submission through commercial operation or withdrawal.

From `SUBMITTED`, the developer posts funds against the deposit ledger. Each posting carries an `amount_cents` and appends a ledger entry whose `tx_type` is `DEPOSIT`, whose `project_id` ties it to the project, and whose `balance_after_cents` records the running `deposit_posted_cents` immediately after the entry is applied; the project's `deposit_posted_cents` rises by the posted amount. Deposits are accepted only while the project is in `SUBMITTED` or `QUEUED`; a posting at any other time is rejected with `ERR_PROJECT_NOT_ACCEPTING_DEPOSITS`. A deposit that would push `deposit_posted_cents` above `deposit_required_cents` is refused with `ERR_DEPOSIT_OVERPAYMENT` (HTTP 422) — overpayment is never booked. The moment a deposit makes the cumulative `deposit_posted_cents` reach or exceed `deposit_required_cents` while the project is still `SUBMITTED`, the system automatically promotes the project from `SUBMITTED` to `QUEUED` and assigns its queue position: one greater than the maximum `queue_position` among the non-withdrawn members of the same cluster, or position one when the project is the first. Positions are integers, dense, and unique within the cluster.

### 3.3. Readiness: Milestone Evidence and Review

A queued project must prove site and technical readiness before it can be studied. The developer submits evidence by indicating a `milestone_type` — `SITE_CONTROL` or `TECHNICAL_DATA` — together with an `evidence_uri` pointing at the document. Both milestone types are required. A submission is accepted only while the project is in `SUBMITTED` or `QUEUED`; later it is rejected with `ERR_PROJECT_NOT_ACCEPTING_MILESTONES`. At most one submission per project and `milestone_type` may be live at once — that is, in `PENDING_REVIEW` or `ACCEPTED`; a duplicate attempt fails with `ERR_MILESTONE_SUBMISSION_CONFLICT`.

Every new submission starts in `PENDING_REVIEW`, with its `review_note` null until a review takes place. A `QueueAdministrator` then reviews it with a `decision` of `ACCEPTED` or `REJECTED`, optionally attaching a `review_note` that is recorded on the submission at review time; reviewing a submission that is no longer pending is refused with `ERR_MILESTONE_NOT_PENDING_REVIEW`. Acceptance has a cascade: when every required milestone type for the project has an `ACCEPTED` submission, the project's `readiness_satisfied` flips to true, and if the project is `QUEUED` at that moment it advances automatically to `READY`. Rejection records the note and moves the submission to `REJECTED`, from which the owning developer may resubmit fresh evidence: the resubmission supplies a new `evidence_uri`, which replaces the old one, clears the recorded `review_note` back to null, and returns the submission to `PENDING_REVIEW`. Resubmitting a submission that is not currently `REJECTED` is refused with `ERR_MILESTONE_NOT_REJECTED`, and only the developer who owns the parent project may resubmit it.

### 3.4. Scoping the Cluster Study and Allocating Its Cost

Once at least one member of a `FORMING` cluster has reached `READY`, a `StudyEngineer` scopes the cluster impact study by declaring its `total_cost_cents`, which must be greater than zero. Scoping enforces three gates in the cluster's context: the cluster must still be `FORMING` (otherwise `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`), no study may yet exist for the cluster — at most one `Study` ever exists per `ClusterGroup`, and an attempt to scope a cluster that already has a study draws `ERR_STUDY_ALREADY_EXISTS` — and at least one member must be `READY`, else `ERR_NO_READY_PROJECTS`. When more than one of these gates is armed by the same request, §2.8's category priority decides the rejection: the `FORMING` requirement is a state precondition (category six) and is evaluated before the one-study uniqueness constraint (category nine). Because a successful scoping moves the cluster from `FORMING` to `STUDY_UNDERWAY` and no transition returns a cluster to `FORMING`, a second scoping attempt on an already-scoped cluster is rejected with `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`; `ERR_STUDY_ALREADY_EXISTS` is the rejection only when a study already exists while the cluster is still `FORMING`.

Scoping is a harsh gate. The study is created in `IN_PROGRESS`; the cluster advances from `FORMING` to `STUDY_UNDERWAY`; every member in `READY` moves to `IN_STUDY`; and every member still in `SUBMITTED` or `QUEUED` is automatically withdrawn for lack of readiness. That automatic withdrawal follows the early forfeiture band described in §3.7, and — because the study has only just been created — it triggers no restudy cascade. For each project entering `IN_STUDY`, a `CostShare` row is created under the **PROVISIONAL** basis — each row carries the `study_id` of the study and the `project_id` of the member bearing the share: each included member's `allocated_cents` is the study's total cost multiplied by the member's `capacity_mw` and divided by the sum of `capacity_mw` across the included set, rounded half-up to integer cents.

Cost allocation has a precise definition that applies at scoping, at results publication, and at every withdrawal-triggered recomputation. The included set is the member projects of the study's cluster whose status is one of `IN_STUDY`, `STUDY_COMPLETE`, `RESTUDY_REQUIRED`, `AGREEMENT_PENDING`, or `AGREEMENT_EXECUTED`; withdrawn projects are excluded, and any cost-share row belonging to a withdrawn project has its `allocated_cents` set to zero. Under the FINAL basis — used at results publication and at every later recomputation — each included member's share is the sum of two components: an equal headcount component of half the total cost divided by the number of included members, and a capacity component of half the total cost multiplied by the member's `capacity_mw` and divided by the total included capacity. Each component is rounded half-up to integer cents first, and the two rounded components are then summed. After either variant runs, a residual reconciliation restores the invariant that all shares sum exactly to the study total: the difference between the total and the summed shares is added to the included project with the largest `capacity_mw`, with ties broken by earliest `created_at`. The read-only `basis` field on each `CostShare` — `PROVISIONAL` or `FINAL` — records which formula most recently produced its `allocated_cents`. The two variants genuinely differ: for a total of 1000000 cents over members of ten and thirty MW, PROVISIONAL allocates 250000 and 750000 cents, while FINAL allocates 375000 and 625000 cents.

### 3.5. Publishing, Reopening, and Finalizing the Study

When engineering work concludes, the `StudyEngineer` publishes results. Publication requires the study to be `IN_PROGRESS`; acting on a study in any other state is rejected with `ERR_STUDY_INVALID_STATE`. Publication moves the study from `IN_PROGRESS` to `RESULTS_PUBLISHED`, advances every included member in `IN_STUDY` to `STUDY_COMPLETE`, advances every included member in `RESTUDY_REQUIRED` back to `STUDY_COMPLETE`, and recomputes all cost shares under the FINAL basis, flipping each row's `basis` to `FINAL`.

A study whose results have been published is not necessarily finished. If a member withdraws while the cluster study is in `RESULTS_PUBLISHED`, the study automatically reopens from `RESULTS_PUBLISHED` back to `IN_PROGRESS`, and every sibling member sitting in `STUDY_COMPLETE` is demoted to `RESTUDY_REQUIRED` — remaining an included member for the next cost recomputation, which then reruns over the surviving included set under the current basis. The same cascade applies when a member withdraws while the study is still `IN_PROGRESS`: cost shares are recomputed over the remaining included members and the withdrawn project's row is zeroed, though in that case there is no published result to reopen and no `STUDY_COMPLETE` sibling to demote.

Finalization is the point of no return. The `StudyEngineer` finalizes a study that is in `RESULTS_PUBLISHED` — again, any other state draws `ERR_STUDY_INVALID_STATE` — which moves the study to `FINALIZED`, advances the cluster from `STUDY_UNDERWAY` to `STUDY_COMPLETE`, and locks the cost shares: later withdrawals neither reopen the study nor reallocate costs. A finalized study also unblocks agreement execution, as the next subsection describes.

### 3.6. Interconnection Agreements: Issuance, Extension, Execution

Once a project is `STUDY_COMPLETE` and the cluster study is in `RESULTS_PUBLISHED` or `FINALIZED`, a `QueueAdministrator` issues an interconnection agreement. Issuance supplies the `target_cod` — the target commercial operation date, which must be strictly after the issuance timestamp — the `max_injection_mw` operating limit, which must be greater than zero and no more than the project's `capacity_mw`, an optional `curtailment_hours_cap` annual cap that defaults to zero and where zero means firm service, and the OCC guard `expected_project_version`. If the project's state is not `STUDY_COMPLETE` — and the re-issuance exception below does not apply — the request is rejected with `ERR_PROJECT_NOT_STUDY_COMPLETE`; if the study has not reached `RESULTS_PUBLISHED` or `FINALIZED`, with `ERR_STUDY_NOT_PUBLISHED`; and if the client's `expected_project_version` does not match the project's current `version`, with `ERR_STALE_VERSION` (HTTP 412), exactly as §2.7 specifies. A successful issuance creates the agreement in `ISSUED`, stamps `issued_at` from the logical clock, computes the read-only `execution_deadline` as exactly ninety days after `issued_at`, initializes `extension_count` to zero, moves the project from `STUDY_COMPLETE` to `AGREEMENT_PENDING`, and increments the project's `version` by one.

Re-issuance exists for the expired-agreement path. If the project is already `AGREEMENT_PENDING` and every agreement it has ever received has reached `EXPIRED`, a `QueueAdministrator` may issue a fresh agreement under the same OCC guard and the same study-state requirement; the new agreement is created `ISSUED` with its own ninety-day deadline, and the project's `version` again increments by one. If any prior agreement is still live (not `EXPIRED`), the attempt fails with `ERR_PROJECT_NOT_STUDY_COMPLETE`.

The developer executes an issued agreement before its deadline. Execution requires the agreement to be `ISSUED` (otherwise `ERR_AGREEMENT_NOT_ISSUED`), requires the acting developer to own the parent project, requires the logical clock to be no later than the `execution_deadline` — with equality at the exact deadline timestamp permitted — and requires the cluster study to be `FINALIZED` (otherwise `ERR_STUDY_NOT_FINALIZED`). A successful execution moves the agreement from `ISSUED` to `EXECUTED` and the project from `AGREEMENT_PENDING` to `AGREEMENT_EXECUTED`. A late attempt is doubly consequential: the agreement itself transitions from `ISSUED` to `EXPIRED` — this expiry is materialized lazily, at the moment the late execute attempt arrives — the attempt is rejected with `ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED`, and the project remains `AGREEMENT_PENDING`, eligible for the re-issuance path above.

After execution, the developer may request commercial-operation-date extensions. An extension replaces the `target_cod` with a `new_target_cod` and increments `extension_count` by one. Three constraints guard it: the agreement must be `EXECUTED` (otherwise `ERR_AGREEMENT_NOT_EXECUTED`); `extension_count` must still be below the maximum of two, or the request fails with `ERR_EXTENSION_LIMIT_REACHED`; and the request must arrive at least thirty days before the current `target_cod` — a request inside that window is rejected with `ERR_EXTENSION_WINDOW_MISSED`. The `new_target_cod` itself must be strictly after the current `target_cod` and no more than 365 days beyond it; anything outside that range is `ERR_INVALID_REQUEST`.

### 3.7. Withdrawal, Forfeiture, and the Restudy Cascade

A project may be withdrawn by its owning developer or by a `QueueAdministrator` from any non-terminal state. Withdrawal from `COMMERCIAL_OPERATION` or from `WITHDRAWN` itself is not permitted; the attempt is rejected with `ERR_PROJECT_NOT_WITHDRAWABLE` (HTTP 409).

Every withdrawal runs the deposit forfeiture schedule against the project's ledger. The forfeited percentage depends on the project's status at the moment of withdrawal: from `SUBMITTED`, `QUEUED`, or `READY` the system forfeits ten percent of `deposit_posted_cents`; from `IN_STUDY`, `STUDY_COMPLETE`, or `RESTUDY_REQUIRED` it forfeits fifty percent; from `AGREEMENT_PENDING` or `AGREEMENT_EXECUTED` it forfeits one hundred percent. The forfeited amount is rounded half-up to whole cents, and the remainder is refunded. When `deposit_posted_cents` is greater than zero, the system appends a `FORFEIT` ledger entry for the forfeited amount and — only when the refund portion is itself greater than zero — a `REFUND` entry for the remainder; either way `deposit_posted_cents` falls to zero, and each new entry's `balance_after_cents` records the running balance as usual. Withdrawal also subtracts the project's `capacity_mw` from the cluster's `committed_mw` and compacts the queue: every non-withdrawn member of the same cluster whose `queue_position` was greater than the withdrawn project's position decrements by exactly one, keeping positions dense from one to the surviving count. Any `ISSUED` agreement belonging to the withdrawing project transitions to `EXPIRED`.

The study-state consequences depend on timing. A withdrawal at scoping time — the automatic readiness enforcement of §3.4 — triggers no restudy cascade, because the study has only just been created. A withdrawal while the cluster study is `IN_PROGRESS` recomputes cost shares over the remaining included members and zeroes the withdrawn project's row. A withdrawal while the study is `RESULTS_PUBLISHED` additionally reopens the study to `IN_PROGRESS` and demotes every sibling in `STUDY_COMPLETE` to `RESTUDY_REQUIRED` before the recomputation runs. A withdrawal after the study is `FINALIZED` leaves the study and its locked shares untouched. A project in `RESTUDY_REQUIRED` completes the cycle when the reopened study next publishes results, returning to `STUDY_COMPLETE` with shares again computed under the FINAL basis.

### 3.8. Commercial Operation, Operating Limits, and Cluster Closure

A developer whose project has reached `AGREEMENT_EXECUTED` declares commercial operation at the current logical clock time. The declaration requires the project to be `AGREEMENT_EXECUTED` (otherwise `ERR_PROJECT_NOT_READY_FOR_OPERATION`) and requires the clock to be no later than the `target_cod` as extended by any granted extensions — a declaration after that date is rejected with `ERR_COD_DEADLINE_PASSED`. Success moves the project to the terminal `COMMERCIAL_OPERATION` state and bubbles upward: if the cluster is `STUDY_COMPLETE` and, counting this declaration, every member project now sits in a terminal state — `WITHDRAWN` or `COMMERCIAL_OPERATION` — the cluster closes, moving from `STUDY_COMPLETE` to `CLOSED`. That same bubble-up check runs whenever a member reaches a terminal state, so the final withdrawal in an otherwise-finished cluster closes it too.

Operating-limit conditions are recorded once a project is `AGREEMENT_EXECUTED` or in `COMMERCIAL_OPERATION`; earlier attempts are rejected with `ERR_PROJECT_NOT_ACCEPTING_CURTAILMENT_LIMITS`. A `QueueAdministrator` records each condition with a `limit_type` of `SEASONAL`, `EMERGENCY`, or `ECONOMIC`, a `max_output_mw` ceiling that must be greater than zero and no more than the project's `capacity_mw`, the closed effective interval from `effective_start` through `effective_end` inclusive (with the end strictly after the start, else `ERR_INVALID_WINDOW`), and the `curtailment_hours_per_year` allowed under the limit, which must be at least zero. The disjointness rule of §2.9 applies per project and `limit_type`, with touching endpoints counting as overlap (`ERR_CURTAILMENT_WINDOW_OVERLAP`).

### 3.9. Transparency Reporting

For public accountability, a `QueueAdministrator` publishes an immutable transparency snapshot for a reporting period identified by a unique `reporting_period` label such as `2026-Q3`; a label already in use is rejected with `ERR_REPORTING_PERIOD_CONFLICT`. At creation, the snapshot counts and totals over all projects regardless of cluster: `queued_project_count` is the number of projects whose status is one of `SUBMITTED`, `QUEUED`, `READY`, `IN_STUDY`, `STUDY_COMPLETE`, `RESTUDY_REQUIRED`, `AGREEMENT_PENDING`, or `AGREEMENT_EXECUTED`; `queued_mw` is the sum of `capacity_mw` over that same set; `withdrawn_project_count` is the number of projects in `WITHDRAWN`; and `commercial_operation_project_count` is the number in `COMMERCIAL_OPERATION`. Once created, the snapshot never changes.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a developer, standing up a cluster, submitting a project, posting a deposit ledger entry, submitting milestone evidence, scoping a study, issuing an agreement, requesting an extension, recording a curtailment limit, publishing a transparency snapshot — return `201 Created`. Operations that modify an existing resource in place — milestone review and resubmission, results publication, finalization, execution, withdrawal, declaration of commercial operation, and the clock-setting capability — return `200 OK`. All other retrievals return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/interconnection/developers` | Onboard a new interconnection customer | QueueAdministrator |
| GET | `/interconnection/developers/{id}` | Get a developer | Developer, QueueAdministrator, StudyEngineer, Regulator |
| GET | `/interconnection/developers/{id}/projects` | List projects owned by a developer (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/cluster-groups` | Create a cluster study group with an application window | QueueAdministrator |
| GET | `/interconnection/cluster-groups/{id}` | Get a cluster group | Developer, QueueAdministrator, StudyEngineer, Regulator |
| GET | `/interconnection/cluster-groups/{id}/projects` | List member projects of a cluster (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| GET | `/interconnection/cluster-groups/{id}/studies` | List studies of a cluster (array of length 0 or 1) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/projects` | Submit a new interconnection request into a cluster | Developer |
| GET | `/interconnection/projects/{id}` | Get a project | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/projects/{id}/deposits` | Post deposit funds; auto-promotes to QUEUED when the required amount is reached | Developer |
| GET | `/interconnection/projects/{id}/deposits` | List the deposit ledger of a project (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/projects/{id}/milestone-submissions` | Submit readiness milestone evidence | Developer |
| GET | `/interconnection/projects/{id}/milestone-submissions` | List milestone submissions of a project (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/milestone-submissions/{id}/review` | Accept or reject a pending milestone submission | QueueAdministrator |
| POST | `/interconnection/milestone-submissions/{id}/resubmit` | Resubmit evidence for a rejected milestone | Developer |
| POST | `/interconnection/cluster-groups/{id}/studies` | Scope the cluster impact study; enforces readiness and creates PROVISIONAL cost shares | StudyEngineer |
| GET | `/interconnection/studies/{id}` | Get a study | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/studies/{id}/publish-results` | Publish study results; members complete the study and shares recompute under FINAL | StudyEngineer |
| POST | `/interconnection/studies/{id}/finalize` | Finalize the study; locks cost shares and advances the cluster | StudyEngineer |
| GET | `/interconnection/studies/{id}/cost-shares` | List cost shares of a study (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| GET | `/interconnection/projects/{id}/cost-shares` | List cost shares borne by a project (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/projects/{id}/agreements` | Issue (or re-issue after expiry) an interconnection agreement; OCC-guarded | QueueAdministrator |
| GET | `/interconnection/projects/{id}/agreements` | List agreements of a project (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/agreements/{id}/execute` | Developer executes an issued agreement before its deadline | Developer |
| POST | `/interconnection/agreements/{id}/extensions` | Request a commercial-operation-date extension | Developer |
| POST | `/interconnection/projects/{id}/withdraw` | Withdraw a project from the queue; forfeiture, compaction, restudy cascade | Developer, QueueAdministrator |
| POST | `/interconnection/projects/{id}/declare-commercial-operation` | Declare commercial operation at the current logical clock time | Developer |
| POST | `/interconnection/projects/{id}/curtailment-limits` | Record a curtailment/operating-limit condition with a closed effective interval | QueueAdministrator |
| GET | `/interconnection/projects/{id}/curtailment-limits` | List curtailment limits of a project (paginated) | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/interconnection/transparency-reports` | Publish an immutable transparency snapshot of queue statistics | QueueAdministrator |
| GET | `/interconnection/transparency-reports/{id}` | Get a transparency report | Developer, QueueAdministrator, StudyEngineer, Regulator |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock | QueueAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_DEVELOPER_NOT_FOUND` | 404 Not Found |
| `ERR_CLUSTER_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSPARENCY_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS` | 409 Conflict |
| `ERR_CLUSTER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CLUSTER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STUDY_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NO_READY_PROJECTS` | 409 Conflict |
| `ERR_STUDY_INVALID_STATE` | 409 Conflict |
| `ERR_STUDY_NOT_PUBLISHED` | 409 Conflict |
| `ERR_STUDY_NOT_FINALIZED` | 409 Conflict |
| `ERR_PROJECT_NOT_ACCEPTING_DEPOSITS` | 409 Conflict |
| `ERR_DEPOSIT_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_ACCEPTING_MILESTONES` | 409 Conflict |
| `ERR_MILESTONE_SUBMISSION_CONFLICT` | 409 Conflict |
| `ERR_MILESTONE_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_MILESTONE_NOT_REJECTED` | 409 Conflict |
| `ERR_PROJECT_NOT_STUDY_COMPLETE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ISSUED` | 409 Conflict |
| `ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_EXECUTED` | 409 Conflict |
| `ERR_EXTENSION_LIMIT_REACHED` | 409 Conflict |
| `ERR_EXTENSION_WINDOW_MISSED` | 409 Conflict |
| `ERR_COD_DEADLINE_PASSED` | 409 Conflict |
| `ERR_PROJECT_NOT_READY_FOR_OPERATION` | 409 Conflict |
| `ERR_PROJECT_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_PROJECT_NOT_ACCEPTING_CURTAILMENT_LIMITS` | 409 Conflict |
| `ERR_CURTAILMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REPORTING_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

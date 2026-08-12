# BC/DR Program API — Product Requirements Document

## 1. Introduction

Enterprise resilience offices carry a difficult mandate: prove, continuously and to an audit standard, that the organization can survive the loss of a data center, a critical vendor, or a key workforce location. In practice that proof is assembled from scattered spreadsheets — business impact analyses with stale recovery objectives, recovery plans whose assumptions drift away from the latest analysis, exercise reports nobody reconciles against capability claims, and attestation letters signed on faith. This document specifies the Business Continuity & Disaster Recovery (BC/DR) Program API, a single system of record that replaces those spreadsheets with a governed, versioned, and fully traceable program model.

The API covers the full resilience cycle. Business impact analyses establish recovery time and recovery point objectives per process and are scored for criticality under a dual-variant scoring regime that freezes once approved. Recovery plans are authored against those analyses, gated at approval by committed-objective checks, and kept honest by an automatic adoption mechanism that re-pins plans to newly approved analyses. Alternate sites, third-party vendors, and recovery capabilities are registered alongside, exercised on a calendar of tabletop and failover tests, and measured by validation runs whose results either prove capability or open remediation gaps. A crisis communication module maintains notification trees and tracks activations from fan-out through acknowledgement. Finally, regulatory and customer attestations capture a signed, immutable readiness snapshot — gated by a computed readiness score — that can later be revoked only by a different officer than the signer.

Two design commitments shape everything that follows. First, **segregation of duties**: the person who performs a sensitive step is systematically forbidden from being the person who performed the preceding step, and the system knows every actor as a registered contact. Second, **derived truth over declared truth**: criticality scores, continuity scores, exercise results, readiness scores, gap pressure, freshness labels, and acknowledgement coverage are all computed by the server from recorded evidence under pinned evaluation orders, never accepted as client input. Where the rest of this document is silent, treat the server-computed reading as authoritative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, time, resource identity, precision, concurrency control, retrieval order, and the precedence among validation layers. Everything here applies uniformly across the API, which is mounted under the `/resilience` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting individual, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or whose role value does not name one of the declared roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly ten roles, spelled exactly as follows: `ResilienceAdmin`, `BIAAnalyst`, `PlanAuthor`, `PlanApprover`, `RiskCommittee`, `ExerciseOfficer`, `SiteCoordinator`, `VendorManager`, `CrisisOfficer`, and `AttestationSigner`. Read endpoints are shared across the program — every role may call every list and detail retrieval. Write and action endpoints are segregated: process registry administration, dependency-graph maintenance, contact registration, alternate-site retirement, and the program clock belong to `ResilienceAdmin`; BIA authoring and submission to `BIAAnalyst`; plan drafting, section editing, finding remediation, capability registration, and gap progression to `PlanAuthor`; plan approval, rejection, and retirement to `PlanApprover`; BIA decisions, finding verification and rejection, gap closure and risk acceptance, and attestation revocation to `RiskCommittee`; exercise scheduling and execution, finding recording, and validation-run recording to `ExerciseOfficer`; site registration and reservation management to `SiteCoordinator`; vendor and assessment management to `VendorManager`; communication-tree maintenance, activations, and notification acknowledgement to `CrisisOfficer`; and attestation creation and signing to `AttestationSigner`.

Role identity is resolved in two distinct ways. When `X-User-Role` is `ResilienceAdmin`, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity: the server may record it in audit narratives but never compares it to any entity's `id`. For every other role — `BIAAnalyst`, `PlanAuthor`, `PlanApprover`, `RiskCommittee`, `ExerciseOfficer`, `SiteCoordinator`, `VendorManager`, `CrisisOfficer`, and `AttestationSigner` — the identity is entity-backed: `X-User-ID` is the `id` of the acting `Contact`, and wherever a workflow performs an ownership or segregation-of-duties comparison (for example, against a `decided_by_contact_id`, an `owner_contact_id`, a `created_by_contact_id`, or a `signed_by_contact_id` recorded on a resource), the comparison is made between that stored contact reference and the `X-User-ID` header value. When such a comparison is required and the supplied `X-User-ID` does not identify an existing `Contact`, the request is rejected with `ERR_UNAUTHORIZED`.

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

Endpoints returning collections accept two query parameters. The `limit` parameter sets the maximum number of items returned in one page: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0.

Unless a subsection states otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program Clock and Time-Derived Fields

All temporal reasoning in the system — overdue flags, freshness labels, exercise recency windows, contract-expiry comparisons — is evaluated against a **logical server clock**, never against wall-clock time. Before any administrative intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never silently falls back to real time. A `ResilienceAdmin` may advance the program clock through a test-driving capability that accepts a `to_iso8601` instant and sets the server's current UTC time to it; the response echoes the new logical time as `current_utc`. Setting the clock is a mutation with system-wide reach: every time-derived field in the program — the `overdue` flag on every open gap, the `validation_freshness` label of every recovery capability, and the exercise-recency leg of every attestation readiness computation — is recomputed against the new instant. Clients should treat a clock set as a full recalculation event and re-read any derived values they depend on.

### 2.5. Common Resource Properties

Most resources in the system share a standard quartet of system-managed fields. The `id` is a server-minted UUID with no type prefix of any kind. The `created_at` timestamp records creation as an ISO 8601 UTC instant with three fractional digits. The `updated_at` timestamp refreshes on every mutation of the resource. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation — including mutations performed by the server itself as a side effect of another operation, such as a cascade or an adoption re-pin.

Two resource families deliberately break this convention. A `Dependency` edge and a `Notification` record each carry only `id` and `created_at`: both `updated_at` and `version` are absent from these resources, and clients must not expect them. A related nuance applies to validation runs: when a newer run supersedes an older recorded run, the superseded row's `updated_at` refreshes to mark the event, but the supersede does not increment the superseded run's `version` — only the resources the cascade mutates (the capability, and any gap it creates) take version bumps.

### 2.6. Cascading Consistency and Aggregate Refresh

The resilience model is a graph, and the server — not the client — is responsible for keeping it consistent. When one operation changes a fact that other resources derive from, every dependent resource is reconciled inside the same request: approving a business impact analysis re-pins the governing analysis of draft plans, recomputes capability-to-target compliance and draft assessments' RTO checks, and retires the previously approved analysis; approving a recovery plan force-retires the previously approved plan of the same process; exiting a vendor or retiring a site flips the capabilities that referenced it into a gap state and opens a remediation gap per flipped capability. Each resource touched by such a cascade takes its own `updated_at` refresh and `version` increment, independently of the resource the client addressed. Wherever §3 says an action "recomputes" or "refreshes" a derived value, that refresh happens synchronously and its results are visible in the response and in every subsequent read.

### 2.7. Numeric Precision and Rounding

Financial and scoring values follow strict precision rules so that two honest implementations never diverge on arithmetic. Monetary amounts — a site's `monthly_cost`, an analysis's `impact_financial_per_hour` — are expressed in USD and rounded to exactly 2 decimal places using round-half-up. The business impact criticality score is likewise rounded half-up to 2 decimal places. Vendor continuity scores and attestation readiness scores are integers; the readiness score applies its floor at the final step only, and the continuity score floors its provisional weighted blend. Site utilization percentages use one decimal place with round-half-up, computed per reservation first and then summed (§3.5 pins this order). Activation acknowledgement coverage is a whole-percent integer, rounded half-up. All comparison boundaries in scoring and target checks are inclusive: a measured value exactly equal to its target passes.

### 2.8. Optimistic Concurrency Control

Two write endpoints in the system are guarded by optimistic concurrency control, and only those two. Updating a recovery plan requires the request to carry `expected_plan_version`, holding the plan `version` the author last observed; if the plan's current `version` has advanced since then — most commonly because a BIA approval's adoption refresh re-pinned the plan's governing analysis in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Rescheduling an exercise likewise requires `expected_exercise_version`, and a mismatch with the exercise's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the canonical case is another officer having already rescheduled the same exercise. The `expected_plan_version` and `expected_exercise_version` fields are non-optional on their respective endpoints. No other endpoint in the API takes a version field.

### 2.9. Nested Resource Retrieval and Identifier Validation

Requests that address nested resources are validated strictly left to right along the path: the system confirms the leftmost path identifier first, and the first identifier that does not resolve to an existing resource determines the error. A request for a section of a non-existent plan fails with `ERR_PLAN_NOT_FOUND` before the section identifier is ever examined; a request for a notification under a non-existent activation fails with `ERR_ACTIVATION_NOT_FOUND` first. Each path variable has its own dedicated not-found error: `contactId` maps to `ERR_CONTACT_NOT_FOUND`, `processId` (and the `{id}` segment of process sub-collection routes) to `ERR_PROCESS_NOT_FOUND`, `biaId` to `ERR_BIA_NOT_FOUND`, `planId` to `ERR_PLAN_NOT_FOUND`, `sectionId` to `ERR_SECTION_NOT_FOUND`, `dependencyId` to `ERR_DEPENDENCY_NOT_FOUND`, `thirdPartyId` to `ERR_VENDOR_NOT_FOUND`, `assessmentId` to `ERR_ASSESSMENT_NOT_FOUND`, `siteId` to `ERR_SITE_NOT_FOUND`, `reservationId` to `ERR_RESERVATION_NOT_FOUND`, `exerciseId` to `ERR_EXERCISE_NOT_FOUND`, `findingId` to `ERR_FINDING_NOT_FOUND`, `capabilityId` to `ERR_CAPABILITY_NOT_FOUND`, `runId` to `ERR_RUN_NOT_FOUND`, `gapId` to `ERR_GAP_NOT_FOUND`, `nodeId` to `ERR_NODE_NOT_FOUND`, `activationId` to `ERR_ACTIVATION_NOT_FOUND`, `notificationId` to `ERR_NOTIFICATION_NOT_FOUND`, and `attestationId` to `ERR_ATTESTATION_NOT_FOUND`.

The same discipline applies to foreign keys supplied in request bodies rather than in the path. A payload naming a `process_id` that does not exist fails with `ERR_PROCESS_NOT_FOUND`; the mapping is one-to-one by field, so `plan_id` maps to `ERR_PLAN_NOT_FOUND`, `third_party_id` to `ERR_VENDOR_NOT_FOUND`, `site_id` to `ERR_SITE_NOT_FOUND`, `capability_id` to `ERR_CAPABILITY_NOT_FOUND`, `exercise_id` to `ERR_EXERCISE_NOT_FOUND`, `finding_id` to `ERR_FINDING_NOT_FOUND`, `parent_node_id` to `ERR_NODE_NOT_FOUND`, and any contact reference such as `owner_contact_id` or `created_by_contact_id` to `ERR_CONTACT_NOT_FOUND`. All not-found rejections carry HTTP 404.

### 2.10. Validation Precedence and Request Integrity

A single request can violate several rules at once, and the order in which checks are applied is part of the contract. The layers are evaluated in this fixed sequence, and the first failing layer wins:

1. **Authentication** — presence of `X-User-Role` and `X-User-ID` and a declared role name, failing as `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is listed for the endpoint, and entity-backed identities resolve to a real `Contact` wherever a comparison is required, failing as `ERR_UNAUTHORIZED`.
3. **Path existence** — left-to-right identifier resolution per §2.9, failing with the corresponding `ERR_*_NOT_FOUND`.
4. **Body reference existence** — foreign keys in the payload resolve, failing with the field's own `ERR_*_NOT_FOUND`.
5. **Request shape** — required fields present (a missing one is `ERR_INVALID_REQUEST`, HTTP 400); enum values in their declared domain, positive integers where positivity is required, window ends strictly after window starts, and non-negative recovery objectives (`ERR_VALIDATION`, HTTP 400); an analysis whose `mtpd_hours` is below its `rto_target_hours` fails as `ERR_MTPD_BELOW_RTO` (HTTP 422).
6. **State legality** — the target resource is in a state from which the invoked transition exists, terminal states are locked, and state-guarded writes are honored (BIAs editable only while `DRAFT` or `REJECTED`, plans and assessments only while `DRAFT`, exercises only while `SCHEDULED`, sections only while their plan is `DRAFT`, findings only on a `COMPLETED` exercise), failing as `ERR_INVALID_STATE` (HTTP 409).
7. **Segregation of duties** — the four guarded confrontations of §2.11, failing as `ERR_SOD_VIOLATION` (HTTP 403).
8. **Operational safety** — the process must be `ACTIVE` for an analysis submission, plan submission, exercise creation, or activation creation (`ERR_PROCESS_NOT_ACTIVE`, HTTP 409); the vendor must be `ACTIVE` at assessment finalization (`ERR_VENDOR_NOT_ACTIVE`, HTTP 409); a standalone validation run must be able to resolve its targets (`ERR_CAPABILITY_TARGETS_UNKNOWN`, HTTP 422); an exercise's plan must be `APPROVED` at scheduling, rescheduling, and completion (`ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`, HTTP 409); an attestation may be signed only when its readiness clears the gate (`ERR_READINESS_BELOW_THRESHOLD`, HTTP 422).
9. **Uniqueness and structural constraints** — the duplicate rules of §2.11 (`ERR_DUPLICATE`, HTTP 409); required plan sections at submission (`ERR_REQUIRED_SECTION_MISSING`, HTTP 422); dependency-graph acyclicity (`ERR_DEPENDENCY_CYCLE`, HTTP 422, and `ERR_DEPENDENCY_SELF_LOOP`, HTTP 422); communication-tree integrity (`ERR_TREE_ROOT_EXISTS` and `ERR_NODE_HAS_ACTIVE_CHILDREN`, HTTP 409; `ERR_COMM_TREE_CYCLE`, HTTP 422).
10. **Activation and acknowledgement gating** — approved-plan presence (`ERR_NO_APPROVED_PLAN`, HTTP 422), one live activation per process (`ERR_ACTIVATION_ALREADY_ACTIVE`, HTTP 409), severity-to-criterion compatibility (`ERR_CRITERION_NOT_ALLOWED`, HTTP 422), acknowledgement token match (`ERR_ACK_TOKEN_MISMATCH`, HTTP 403), and acknowledgement only once (`ERR_NOTIFICATION_ALREADY_ACKED`, HTTP 409).
11. **Retirement and remediation guards** — open-item checks for process retirement (`ERR_PROCESS_HAS_OPEN_ITEMS`, HTTP 409), site retirement (`ERR_SITE_HAS_ACTIVE_RESERVATIONS`, HTTP 409), plan retirement (`ERR_PLAN_HAS_ACTIVE_EXERCISE` and `ERR_PLAN_HAS_LIVE_ACTIVATION`, HTTP 409), and capability remediation (`ERR_CAPABILITY_HAS_OPEN_GAPS`, HTTP 409).
12. **Temporal and capacity rules** — site capacity (`ERR_SITE_CAPACITY_EXCEEDED`, HTTP 422), same-process reservation overlap (`ERR_SITE_WINDOW_OVERLAP`, HTTP 409), failover-exercise window disjointness (`ERR_EXERCISE_WINDOW_OVERLAP`, HTTP 409), and site contract currency (`ERR_SITE_CONTRACT_EXPIRED`, HTTP 422).
13. **Plan approval target checks** — governing analysis approved (`ERR_PLAN_TARGETS_UNAPPROVED_BIA`, HTTP 422), committed recovery time within target (`ERR_PLAN_EXCEEDS_BIA_RTO`, HTTP 422), and committed recovery point within target (`ERR_PLAN_EXCEEDS_BIA_RPO`, HTTP 422), in that order within the approval evaluation.
14. **Cross-reference consistency** — a finding's process must be the exercise's process, an exercise's plan must belong to the exercise's process, and a capability's reference must match its type; these fail as `ERR_VALIDATION`, with HTTP 422 on the capability and finding creation routes.
15. **Stale-version rejection** — the optimistic-concurrency comparisons of §2.8, failing as `ERR_STALE_VERSION` (HTTP 412).

Within an endpoint that layers several of these checks, lower-numbered layers mask higher-numbered ones: for example, an approval attempted by the wrong role on a plan in the wrong state fails authorization, not state legality, and a stale plan version surfaces only after every other approval gate has passed.

### 2.11. Segregation of Duties and Uniqueness Invariants

Four sensitive transitions are segregation-of-duties guarded, each comparing the acting contact in `X-User-ID` against a recorded counterpart and rejecting equality with `ERR_SOD_VIOLATION` (HTTP 403). The contact deciding a business impact analysis must differ from the contact recorded in that analysis's `decided_by_contact_id` (which is empty until the first decision, so a first decision is never self-blocked). The contact finalizing a vendor assessment must differ from the vendor's `owner_contact_id`. The contact releasing a seat reservation must differ from the reservation's `created_by_contact_id`. The contact revoking an attestation must differ from its `signed_by_contact_id`.

Uniqueness is enforced across the registry as follows, each violation failing with `ERR_DUPLICATE` (HTTP 409): a vendor's `name` is globally unique; a site's `name` is globally unique; a contact's `email` is globally unique; among analyses of one process that are not `SUPERSEDED`, the `cycle_label` is unique per process; among plans of one process that are not `RETIRED`, the author-declared `version_no` is unique per process; within one plan, a section's `order_index` is unique; and within one communication tree, the triple of `tree_label`, `parent_node_id`, and `order_index` is unique among sibling nodes.

## 3. Business Logic & Workflows

The workflows below are organized along the program's natural arc: registry first, then analysis, planning, vendors, sites, exercises, capabilities, crisis communication, and attestation. Rules that belong to several workflows are stated once where they bite hardest and cross-referenced elsewhere.

### 3.1. The Process Registry and the Dependency Graph

Everything in the program hangs off a **business process**. Before that, though, the office registers its people: a `ResilienceAdmin` records each committee member, owner, and signer as a **contact** with a `full_name`, an `email` (unique per §2.11 and usable as a list filter), a `role_title`, and an `active_flag` that defaults to true and marks whether the contact is currently addressable. Every contact reference elsewhere in this document — owners, requesters, signers, deciders — resolves to one of these registered contacts.

A `ResilienceAdmin` registers a process with a `name`, the owning `business_unit`, the accountable `owner_contact_id` (a reference to a registered contact, used later for segregation-of-duties reasoning), and a `criticality_tier` of `TIER_1`, `TIER_2`, or `TIER_3`. A new process begins life in `DRAFT`. The administrator may update the process's `name`, `business_unit`, `owner_contact_id`, or `criticality_tier` at any time before retirement — that is, in any non-terminal state — and each update increments the process's `version`. The registry can be browsed through list filters on `business_unit`, `criticality_tier`, `status`, and `owner_contact_id`, in addition to the standard `limit` and `offset` paging.

Activation is the first lifecycle step: activating a process moves it from `DRAFT` to `ACTIVE`, and only an `ACTIVE` process can accept new analyses, plan submissions, exercises, or crisis activations (the detail lives in the respective subsections; the rejection is always `ERR_PROCESS_NOT_ACTIVE`). Suspending moves `ACTIVE` to `SUSPENDED`: the process's plans and analyses remain readable, but no new BIA and no new Plan may be created for a suspended process. Resuming returns `SUSPENDED` to `ACTIVE`. Each of these transitions fails with `ERR_INVALID_STATE` if the process is not in the required source state, and each increments `version`.

Retirement is the guarded, terminal move from `ACTIVE` to `RETIRED`, and it is refused with `ERR_PROCESS_HAS_OPEN_ITEMS` while any of four conditions holds: a plan of the process is `APPROVED`; an analysis of the process is `SUBMITTED`; an exercise of the process is `SCHEDULED` or `IN_PROGRESS`; or an activation of the process is `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED`. When retirement does proceed, it cascades: every plan of the process still in `DRAFT` or `IN_REVIEW` moves to `RETIRED` with a `version` increment on each, and every analysis still in `DRAFT` or `REJECTED` moves to `SUPERSEDED`, likewise with a `version` increment on each. The process's own `version` increments as well.

Processes do not stand alone; they depend on one another. A `ResilienceAdmin` records a directed edge between two processes by supplying `from_process_id` and `to_process_id` (the upstream and downstream ends respectively, and they must differ), a `dependency_type` of `DATA`, `STAFF`, `FACILITY`, `VENDOR`, or `SYSTEM`, a `criticality` of `HIGH`, `MEDIUM`, or `LOW`, and an optional free-text `notes`. The graph is kept acyclic at all times: an edge whose two ends are the same process is rejected with `ERR_DEPENDENCY_SELF_LOOP`, and an edge that would close a directed cycle is rejected with `ERR_DEPENDENCY_CYCLE`. Edges may be deleted when they no longer reflect reality, and the collection may be filtered by `from_process_id`, `to_process_id`, or `dependency_type`. Because an edge is an immutable fact about structure, a dependency carries only `id` and `created_at` — no `updated_at` and no `version`, per §2.5.

From this graph the server derives each process's **blast radius** on demand. Walking edges in their declared direction, starting at the target process, the server collects every process reachable by a directed path — the target itself excluded — and reports the size of that set as `blast_radius` together with the member identifiers in `process_ids`. The member list is ordered by the `created_at` of the edge through which each process was first discovered, earliest first; because edge creation timestamps carry millisecond resolution and edges are created sequentially, no tie-breaking ever arises. All dependency rows count toward the walk regardless of their `criticality`, and processes at the fringe count regardless of their own `status`.

### 3.2. Business Impact Analysis and Criticality Scoring

A `BIAAnalyst` opens a **business impact analysis** for a process by supplying the `process_id`, a `cycle_label` naming the analysis cycle (for example, a fiscal half-year; the label must be unique per process among analyses that are not `SUPERSEDED`), and the core objectives: `rto_target_hours` and `rpo_target_hours` in whole hours, plus `mtpd_hours`, the maximum tolerable period of disruption. The tolerable period must be at least the recovery time target; an analysis whose `mtpd_hours` falls below its `rto_target_hours` is rejected with `ERR_MTPD_BELOW_RTO`. Impact is declared along four axes: `impact_financial_per_hour` in USD (rounded to 2 decimal places), and `impact_regulatory`, `impact_reputational`, and `impact_operational`, each one of `NONE`, `LOW`, or `HIGH`. When a peak trading window materially changes the impact, the analyst sets `peak_period_flag` and must then supply `peak_start_month` and `peak_end_month`, each an integer from 1 to 12; a missing month while the flag is set is a shape error under §2.10. A new analysis starts in `DRAFT`, and its `decided_by_contact_id` remains empty until a first decision is recorded.

Every analysis carries a server-computed `criticality_score` under a **dual-variant regime** tracked by `score_variant`. While the analysis is `DRAFT`, `SUBMITTED`, or `REJECTED`, the variant is `PROVISIONAL` and the score recomputes on creation and on every update. The computation is a weighted blend: the financial leg is `impact_financial_per_hour` divided by ten thousand — deliberately uncapped — and contributes with weight 45; the regulatory leg maps `NONE` to 0, `LOW` to 1, and `HIGH` to 2 and contributes with weight 25; the peak leg contributes 1 when `peak_period_flag` is set and 0 otherwise, weighted 20; and the operational leg maps like the regulatory leg, weighted 10. The raw total is rounded half-up to 2 decimal places. Note that `impact_reputational` is recorded for governance and reporting but does not enter the weighted score.

The `FINAL` variant is computed exactly once, at the moment the analysis becomes `APPROVED`: the same raw total is taken, and if the owning process's `criticality_tier` is `TIER_1` the raw total is first grown by a fifteen percent uplift before rounding; other tiers keep the provisional formula. The result is rounded half-up to 2 decimal places and then frozen — identical inputs afterwards yield the frozen value, never a recomputed one, and a rejected-then-resubmitted analysis keeps recomputing under `PROVISIONAL` until it is finally approved.

An analyst submits an analysis for decision by moving it `DRAFT` → `SUBMITTED`; the referenced process must be `ACTIVE` at that moment, else `ERR_PROCESS_NOT_ACTIVE`. A `REJECTED` analysis may be revised and re-submitted along the same guarded transition — the source state may be `DRAFT` or `REJECTED`, and any other source fails with `ERR_INVALID_STATE`. While in `DRAFT` or `REJECTED`, the analyst may still update the analysis's mutable fields — `cycle_label`, `rto_target_hours`, `rpo_target_hours`, `mtpd_hours`, `peak_period_flag`, `peak_start_month`, `peak_end_month`, `impact_financial_per_hour`, `impact_regulatory`, `impact_reputational`, and `impact_operational` — each update recomputing the provisional score and incrementing `version`; updates in any other state are refused with `ERR_INVALID_STATE`.

Decisions belong to the `RiskCommittee`, which records a `decision` of either approval or rejection. Segregation of duties applies per §2.11: the deciding contact must differ from the current `decided_by_contact_id`, with `ERR_SOD_VIOLATION` on a match. A rejection moves `SUBMITTED` → `REJECTED`, records the acting contact into `decided_by_contact_id`, and increments `version`; the score stays `PROVISIONAL`. An approval moves `SUBMITTED` → `APPROVED` and is the heaviest single operation in the analysis workflow. It records `decided_by_contact_id`, flips `score_variant` to `FINAL` with the score frozen, and increments the analysis's `version`. It then fires three cascades. First, the **supersede hop**: the previously `APPROVED` analysis of the same process, if one exists, moves `APPROVED` → `SUPERSEDED` with its own `version` increment — its score remains `FINAL` and readable, and plans pinned to it keep their pin until the second cascade reaches them. Second, the **adoption refresh**: every plan of the same process in `DRAFT` or `IN_REVIEW` whose `target_bia_id` resolves to a different analysis than the newly approved one is re-pinned to the newly approved analysis, with `last_adoption_check_cycle` set to the approved analysis's `cycle_label` and a `version` increment per re-pinned plan. Third, the **recalculation refresh**: every recovery capability of the process recomputes its `meets_bia` against the new analysis's targets, and every assessment of the process still in `DRAFT` recomputes its `meets_required_rto` against the new analysis's `rto_target_hours`. Analysts and committee members can browse the analysis ledger filtered by `process_id`, `status`, `cycle_label`, or `decided_by_contact_id`.

### 3.3. Recovery Plans, Sections, and the Adoption Pin

A `PlanAuthor` drafts a **recovery plan** for a process by supplying the `process_id`, a `title`, an author-declared integer `version_no` (unique per process among plans that are not `RETIRED`, enforced as `ERR_DUPLICATE`), a `strategy_type` of `ACTIVE_ACTIVE`, `WARM_SITE`, `COLD_SITE`, or `MANUAL_WORKAROUND`, and the plan's commitments: `rto_committed_hours` and `rpo_committed_hours`. The plan starts in `DRAFT`. At creation the server pins the plan's governing analysis, `target_bia_id`: the process's latest `APPROVED` analysis if one exists, else its latest `SUBMITTED` one, else the pin stays empty. The pin is thereafter maintained by the adoption refresh described in §3.2, and `last_adoption_check_cycle` records the cycle label of the most recent automatic refresh. Plans may be listed with filters on `process_id`, `status`, `target_bia_id`, and `supersedes_plan_id`.

A plan is structured into **sections**, each created under its plan with a `section_type` drawn from `SCOPE`, `RECOVERY_STRATEGY`, `DEPENDENCY_MAP`, `COMMS_PLAN`, `SITE_STRATEGY`, `WORKFORCE_STRATEGY`, `VALIDATION_STRATEGY`, and `ATTESTATION_MAP`, plus a free-text `content` body and an integer `order_index` that must be unique within the plan. The server derives a `required_flag` on each section: it is true for `RECOVERY_STRATEGY`, `DEPENDENCY_MAP`, and `COMMS_PLAN` — the three sections that gate plan submission — and false for the rest. Sections may be created, edited (their `content` and `order_index`), or deleted only while the owning plan is in `DRAFT`; attempts against a plan in any other state are refused with `ERR_INVALID_STATE`, and a section edit increments that section's `version`.

While the plan is in `DRAFT`, the author may revise its `title`, `strategy_type`, `rto_committed_hours`, or `rpo_committed_hours`. This update is one of the two optimistic-concurrency-guarded writes in the system: the request must carry `expected_plan_version` matching the plan's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The canonical stale read is the adoption refresh — a BIA approval that re-pinned `target_bia_id` and bumped the plan's `version` while the author was still editing their old copy. A successful update increments `version`.

Submission by the author moves the plan `DRAFT` → `IN_REVIEW` and is gated by two checks beyond state: the referenced process must be `ACTIVE` (`ERR_PROCESS_NOT_ACTIVE`), and the plan must carry at least the three required sections — a `RECOVERY_STRATEGY`, a `DEPENDENCY_MAP`, and a `COMMS_PLAN` — or the submission fails with `ERR_REQUIRED_SECTION_MISSING`.

Approval belongs to the `PlanApprover` and evaluates its checks in order. The plan must be `IN_REVIEW` (`ERR_INVALID_STATE`). Its `target_bia_id` must be non-empty and must resolve to an analysis currently in `APPROVED`; otherwise approval fails with `ERR_PLAN_TARGETS_UNAPPROVED_BIA` — a plan pinned to a merely `SUBMITTED` analysis, or to nothing, cannot be approved. The plan's `rto_committed_hours` must not exceed the target analysis's `rto_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RTO`), and its `rpo_committed_hours` must not exceed the target analysis's `rpo_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RPO`). On success the server records `approved_version_no` equal to the plan's `version_no`, increments the plan's `version`, and makes the plan the process's activatable plan for future crisis activations. Approval also fires the **supersede cascade**: if another plan of the same process is currently `APPROVED`, that plan moves `APPROVED` → `RETIRED` with a `version` increment, and the newly approved plan records the retired plan's identifier in `supersedes_plan_id`. Notably, the supersede cascade retires the prior plan even while exercises still reference it; those exercises are stranded and will later fail completion, as §3.6 describes.

The approver may instead return the plan to the author, moving `IN_REVIEW` → `DRAFT` with no further ceremony. Retirement is possible manually from `DRAFT` — unconditionally — or from `APPROVED`, where two guards apply to the manual action: no exercise referencing the plan may be `SCHEDULED` or `IN_PROGRESS` (`ERR_PLAN_HAS_ACTIVE_EXERCISE`), and no activation of the plan's process may be `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED` (`ERR_PLAN_HAS_LIVE_ACTIVATION`). A plan in `IN_REVIEW` can reach `RETIRED` only through the process-retirement cascade of §3.1, never through a direct action.

### 3.4. Third-Party Continuity and Assessments

Vendors enter the program through the `VendorManager`, who onboards a third party with a globally unique `name`, a `service_category` describing what the vendor provides, a `criticality_rating` of `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`, and an `owner_contact_id` naming the accountable vendor owner — a reference that later anchors segregation of duties. A new vendor starts in `ONBOARDING` and becomes assessable only after activation moves it to `ACTIVE`. Suspension (`ACTIVE` → `SUSPENDED`) and re-activation (`SUSPENDED` → `ACTIVE`) are available as vendor standing changes; each of these transitions requires its stated source state (`ERR_INVALID_STATE` otherwise) and increments the vendor's `version`. The vendor list supports filtering by `status`, `criticality_rating`, and `owner_contact_id`.

Exit is the terminal move to `EXITED`, available from either `ACTIVE` or `SUSPENDED`, and it carries a cascade the resilience office cares deeply about. Assessments of the vendor that are still in `DRAFT` remain readable but can no longer be finalized — any finalize attempt against a non-`ACTIVE` vendor fails with `ERR_VENDOR_NOT_ACTIVE`. More sharply, every recovery capability whose `capability_type` is `VENDOR_FAILOVER` and whose `capability_ref_id` points at the exiting vendor flips from `VALIDATED` to `GAP_IDENTIFIED` if it is currently `VALIDATED`, and each flip auto-creates a remediation gap: `gap_type` of `CAPABILITY`, the capability recorded in `capability_id`, severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days from the exit moment. Each flipped capability takes a `version` increment; the vendor's own `version` increments too.

**Continuity assessments** are the vendor-scored evidence. Creating one requires the `third_party_id` of the vendor, the `process_id` of the dependent process, an `assessment_type` of `INITIAL`, `ANNUAL`, or `EVENT_DRIVEN`, the vendor-attested capabilities `assessed_rto_hours` and `assessed_rpo_hours`, the fallback requirements `rto_required_hours` and `rpo_required_hours`, and an optional `evidence_doc_ref` pointing at supporting artifacts. The assessment starts in `DRAFT` with `finalized_by_contact_id` empty, and the server immediately computes two derived fields.

The first is `continuity_score`, an integer from 0 to 100 computed under the same dual-variant discipline as the BIA score. The required targets are resolved from the process's latest `APPROVED` analysis — latest meaning the approval-ordered read, tie-broken by the analysis's `updated_at` most recent first and then `created_at` most recent first — and only when the process has no `APPROVED` analysis at all do the fallback inputs `rto_required_hours` and `rpo_required_hours` apply. The recovery-time component starts at 100 and loses ten points for every hour by which `assessed_rto_hours` exceeds the required recovery time (shortfalls never add points), clamped between 0 and 100. The recovery-point component starts at 100 and loses five points per hour of `assessed_rpo_hours` excess, likewise clamped. The provisional score is the floor of the blend that weights the recovery-time component at sixty percent and the recovery-point component at forty percent. While the assessment is `DRAFT` the variant is `PROVISIONAL` and the score recomputes on every update; the `VendorManager` may revise `assessed_rto_hours`, `assessed_rpo_hours`, `rto_required_hours`, `rpo_required_hours`, and `evidence_doc_ref` in that window, each update recomputing and incrementing `version`. At finalization the `FINAL` variant is computed exactly once: an `EVENT_DRIVEN` assessment takes a fifteen-point discount off the provisional value, floored at zero, and `INITIAL` and `ANNUAL` assessments keep the provisional value; the score then freezes permanently.

The second derived field is `meets_required_rto`, a boolean that is true exactly when `assessed_rto_hours` is no greater than the resolved required recovery time — the boundary is inclusive, so an attested capability equal to the requirement passes.

Finalization moves the assessment `DRAFT` → `FINALIZED` under three guards: the assessment must be `DRAFT` (`ERR_INVALID_STATE`), the referenced vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), and the acting contact must differ from the vendor's `owner_contact_id` (`ERR_SOD_VIOLATION`). Finalization freezes the `FINAL` score, records the acting contact in `finalized_by_contact_id`, and increments the assessment's `version`. When the finalized assessment's `meets_required_rto` is false, the server opens a remediation gap on the assessment's process: `gap_type` `CAPABILITY` with `capability_id` and `finding_id` both empty, severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days out. That new gap immediately counts toward the gap-backlog aggregates of §3.7. Assessments are listable by `third_party_id`, `process_id`, or `status`, and per-vendor assessment history is also exposed as a sub-collection of the vendor.

### 3.5. Alternate Sites and Seat Reservations

Alternate recovery sites are registered by the `SiteCoordinator` with a globally unique `name`, a `site_type` of `HOT`, `WARM`, `COLD`, or `WORK_AREA_RECOVERY`, a `region` code, the total bookable `capacity_seats`, the contract expiry `contracted_through` as an ISO 8601 UTC instant, and the `monthly_cost` in USD rounded to 2 decimal places. A site enters service immediately in `ACTIVE`. Sites may be browsed with filters on `site_type`, `region`, and `status`.

A reservation books seats against a site's capacity for a window. Creation supplies the `site_id`, the reserving `process_id`, a `purpose` of `EXERCISE` or `INCIDENT`, the `seats_reserved` count, the occupation window `starts_at` (inclusive) and `ends_at` (exclusive, and strictly after the start), and the `created_by_contact_id` of the requester. A reservation is born `CONFIRMED` and immediately consumes capacity. Three temporal guards apply at creation. The window must lie within the site's contract: an `ends_at` later than the site's `contracted_through` is rejected with `ERR_SITE_CONTRACT_EXPIRED`. Aggregate capacity must hold: the seats of all `CONFIRMED` reservations of the site whose half-open windows overlap the new window, plus the new reservation's `seats_reserved`, must not exceed the site's `capacity_seats`, else `ERR_SITE_CAPACITY_EXCEEDED`. And a single process may not double-book: a `CONFIRMED` reservation may not overlap — under the same half-open window semantics — another `CONFIRMED` reservation of the same process on the same site, else `ERR_SITE_WINDOW_OVERLAP`. Reservations can be listed filtered by `site_id`, `process_id`, `status`, or `created_by_contact_id`, and per-site history is exposed as a sub-collection of the site.

Release ends a booking: a `SiteCoordinator` moves `CONFIRMED` → `RELEASED`, the reserved seats free against the site's capacity effective immediately, and the reservation's `version` increments. Segregation of duties applies — the releasing contact must differ from the `created_by_contact_id` on the reservation, with `ERR_SOD_VIOLATION` on a match. Release from any other state fails `ERR_INVALID_STATE`.

Two reads keep the site portfolio honest. The utilization read answers, at a probe instant supplied as the optional `probe_at` query parameter, how full a site is. Occupants are the site's `CONFIRMED` reservations whose half-open window contains the probe instant — start inclusive, end exclusive; `RELEASED` reservations never count. The arithmetic order is pinned: each occupying reservation's percentage is computed first as its `seats_reserved` divided by the site's `capacity_seats`, times one hundred, rounded half-up to one decimal place, and only then are the per-reservation percentages summed and the total rounded half-up to one decimal place as `utilization_pct`. Summing seats first and rounding once is a different computation and is not this one. The response reports `capacity_seats`, the summed `reserved_seats`, `utilization_pct`, and the effective `probe_at`. Retirement is the site's terminal move from `ACTIVE` to `RETIRED`, refused with `ERR_SITE_HAS_ACTIVE_RESERVATIONS` while any reservation of the site is `CONFIRMED`. Retiring a site cascades to capabilities: every recovery capability of `capability_type` `SITE` whose `capability_ref_id` is this site flips from `VALIDATED` to `GAP_IDENTIFIED` when currently `VALIDATED`, each flip auto-creating a `CAPABILITY` gap with severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days hence; each flipped capability takes a `version` increment, and the site's own `version` increments.

### 3.6. Exercises and Findings

Exercises are the program's proving ground. An `ExerciseOfficer` schedules one by supplying the `process_id` under test, the `plan_id` to be exercised, an `exercise_type` of `TABLETOP` or `FAILOVER`, and the window `scheduled_start` to `scheduled_end` (end strictly after start). Three referrals are checked at scheduling. The process must be `ACTIVE` (`ERR_PROCESS_NOT_ACTIVE`). The plan must belong to the same process as the exercise — a cross-process pairing is rejected with `ERR_VALIDATION` — and the plan must be `APPROVED` at scheduling time, else `ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`. For `FAILOVER` exercises only, an exclusivity rule applies: the failover windows of one process must be strictly disjoint under closed-interval semantics, meaning touching endpoints already count as overlap; a colliding schedule is rejected with `ERR_EXERCISE_WINDOW_OVERLAP`. A scheduled exercise starts in `SCHEDULED`, and the server derives `requires_capability_check` as true exactly when the `exercise_type` is `FAILOVER` — this flag drives the completion cascade below. `TABLETOP` exercises face no window-exclusivity rule. The exercise calendar can be filtered by `process_id`, `plan_id`, `status`, `exercise_type`, and `validation_run_id`.

Rescheduling updates `scheduled_start` and `scheduled_end` and is allowed only while the exercise is `SCHEDULED` (`ERR_INVALID_STATE` otherwise). It is the second of the two optimistic-concurrency-guarded writes: the request must carry `expected_exercise_version` equal to the exercise's current `version`, and a mismatch — typically because another officer rescheduled first — is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful reschedule re-checks the failover window-disjointness rule (`ERR_EXERCISE_WINDOW_OVERLAP`) and increments `version`.

Starting moves `SCHEDULED` → `IN_PROGRESS`. Cancellation moves an exercise from either `SCHEDULED` or `IN_PROGRESS` to `CANCELLED` — terminal, no further transitions — and any other source state fails `ERR_INVALID_STATE`.

Completion is the consequential transition, `IN_PROGRESS` → `COMPLETED`. The officer declares a `completion_outcome` of `MET`, `MISSED`, or `PARTIAL`, and records the observed `achieved_rto_hours` and `achieved_rpo_hours`. Completion re-verifies the plan: the referenced plan must still be `APPROVED` at completion time, and because a plan-approval supersede cascade may have retired it mid-exercise, a retired plan fails completion with `ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`. The server then derives the exercise `result`, computed exactly once and frozen. The plan's committed targets are read at completion time. If `achieved_rto_hours` exceeds the plan's `rto_committed_hours`, or `achieved_rpo_hours` exceeds the plan's `rpo_committed_hours`, the result is `MISSED` regardless of the declared outcome — measured reality outranks declaration. If both measured values are within their committed targets (equality passes, the boundary is inclusive), then a declared `MET` yields `MET`, and any other declared outcome is honored as declared — `PARTIAL` or `MISSED`.

When the completed exercise is a `FAILOVER` (that is, `requires_capability_check` is true), completion additionally fires the **validation cascade**. The server looks among the process's recovery capabilities of `capability_type` `SITE` whose status is `UNPROVEN`, `VALIDATED`, or `GAP_IDENTIFIED`, picks the oldest by `created_at` (timestamps are unique, so no tie-break is needed), and — only if that pool is non-empty — records a validation run with `method` `FAILOVER`, the run's `exercise_id` pointing back to this exercise, its `capability_id` set to the chosen capability, and its `measured_rto_hours` and `measured_rpo_hours` copied from the exercise's achieved values. The exercise's `validation_run_id` is pinned to the created run (it stays empty when the pool was empty and no run was created). The new run immediately evaluates its own result under the rules of §3.7 and fires the capability cascade described there — capability status flips, proven values refresh, a gap opens on failure, freshness recomputes — with both the exercise's and the capability's `version` incrementing.

**Findings** capture what went wrong. An officer records one against a `COMPLETED` exercise — creation against an exercise in any other state fails with `ERR_INVALID_STATE` — supplying the `exercise_id`, the affected `process_id` (which must equal the exercise's process, else `ERR_VALIDATION` with HTTP 422), a `severity` of `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`, a narrative `description`, a remediation `due_date`, and optionally a `root_cause` (which may also be filled in later at verification time). A finding opens in `OPEN` with `verified_by_contact_id` empty, and the ledger supports filters on `exercise_id`, `process_id`, `severity`, `status`, and `verified_by_contact_id`.

Remediation is a `PlanAuthor` action moving `OPEN` → `REMEDIATING`, and it auto-creates a remediation gap: `gap_type` `FINDING`, `finding_id` pointing at this finding, `capability_id` empty, `severity` and `due_date` copied from the finding, state `OPEN`; the finding's `version` increments. Disposition belongs to the `RiskCommittee`. Verification moves `REMEDIATING` → `VERIFIED`, records the acting contact in `verified_by_contact_id`, and closes the remediation gap: the gap whose `finding_id` is this finding moves to `CLOSED` with `closed_by_contact_id` set to the same acting contact, and that closure refreshes the gap-backlog aggregates — the process's overdue-gap flags recompute and every recovery capability of the process recomputes `validation_freshness`, with the gap's and each affected capability's `version` incrementing. Rejection instead moves `REMEDIATING` → `REJECTED` with an optional `rejected_reason`, and the remediation gap moves to `ACCEPTED_RISK` rather than `CLOSED`, with the same aggregate refresh. A finding's linked gaps are also exposed as a sub-collection.

### 3.7. Recovery Capabilities, Validation Runs, and Gaps

A **recovery capability** is a claim that a process can actually recover by some means. A `PlanAuthor` registers one with the `process_id`, a `capability_type` of `SITE`, `WORKFORCE`, `DATA_RESTORE`, or `VENDOR_FAILOVER`, and a `capability_ref_id` whose meaning depends on the type: for `SITE` it must reference an existing alternate site, for `VENDOR_FAILOVER` an existing third party, and for the other two types it is an opaque label. A reference of the wrong kind is rejected with `ERR_VALIDATION` (HTTP 422 on creation). A new capability starts `UNPROVEN`, with `proven_rto_hours` and `proven_rpo_hours` empty, `last_validation_run_id` empty, and `validation_freshness` set to `NEVER`. The capability register can be filtered by `process_id`, `capability_type`, `status`, `validation_freshness`, `capability_ref_id`, and `last_validation_run_id`.

**Validation runs** are the measurements that prove or disprove the claim. An `ExerciseOfficer` records a standalone run with the `capability_id`, the observed `measured_rto_hours` and `measured_rpo_hours`, a `method` of `FAILOVER`, `SIMULATION`, or `COMPONENT_TEST`, and an `evidence_ref` pointing at the artifacts. A run is born `RECORDED` and immediately computes its `result`. The targets are resolved in a strict order: the latest `APPROVED` analysis of the capability's process supplies `rto_target_hours` and `rpo_target_hours` if such an analysis exists; otherwise the process's `APPROVED` plan supplies its `rto_committed_hours` and `rpo_committed_hours`; if neither exists, a standalone run cannot be evaluated at all and its creation is rejected with `ERR_CAPABILITY_TARGETS_UNKNOWN` (HTTP 422). When the run instead arises from the failover completion cascade of §3.6 and targets are unresolvable, the failure is silent by design — no run is created, and the exercise's `validation_run_id` stays empty. With targets resolved, the result is `GAP_IDENTIFIED` when `measured_rto_hours` exceeds the target recovery time or `measured_rpo_hours` exceeds the target recovery point, and `VALIDATED` otherwise — equality to the target passes on both legs.

Recording a run fires the capability cascade. At most one run per capability is `RECORDED` at any time: the prior `RECORDED` run, if any, moves to `SUPERSEDED` — it remains queryable but no longer drives anything, and per §2.5 this system transition refreshes its `updated_at` without incrementing its `version`. The capability's `last_validation_run_id` is set to the new run. On a `VALIDATED` result, the capability moves to `VALIDATED` from whichever of `UNPROVEN`, `GAP_IDENTIFIED`, or `REMEDIATED` it occupied, and `proven_rto_hours` and `proven_rpo_hours` are refreshed from the measured values of the capability's current `RECORDED` run; when the latest run is a `GAP_IDENTIFIED`, the proven values instead keep whatever the last `VALIDATED` measurements established. On a `GAP_IDENTIFIED` result, the capability moves to `GAP_IDENTIFIED` and the server opens a capability gap — `gap_type` `CAPABILITY`, the capability in `capability_id`, `finding_id` empty — and records that gap's identifier in the run's `gap_created_id` (empty when the result is `VALIDATED`). Either way, `meets_bia` is recomputed and `validation_freshness` re-evaluated, and the capability's `version` increments. Runs can be listed with filters on `capability_id`, `exercise_id`, `result`, `status`, and `gap_created_id`, and both per-capability and per-exercise run histories are exposed as sub-collections.

Two booleans-and-labels complete the capability picture. `meets_bia` is true exactly when proven values exist and both are no greater than the targets of the process's latest `APPROVED` analysis; when the process has no approved analysis it is false. `validation_freshness` is `NEVER` when the capability has no validation runs at all, `STALE` when the latest `RECORDED` run is older than twelve months against the program clock or when any gap linked to the capability is overdue, and `CURRENT` otherwise.

A capability in `GAP_IDENTIFIED` can be marked remediated by a `PlanAuthor`, moving it to `REMEDIATED` — but only when every gap whose `capability_id` is this capability has reached a terminal state, `CLOSED` or `ACCEPTED_RISK`; open work blocks the transition with `ERR_CAPABILITY_HAS_OPEN_GAPS`. Remediation recomputes `validation_freshness` and increments `version`. The capability state graph then cycles on evidence alone: the next `VALIDATED` run lifts `REMEDIATED` (or `GAP_IDENTIFIED`) back to `VALIDATED` with proven values refreshed, and the next `GAP_IDENTIFIED` run drops `REMEDIATED` to `GAP_IDENTIFIED` again — both are system transitions, and each refreshes `last_validation_run_id`, recomputes freshness, and increments `version`.

**Gaps** are the remediation backlog itself. Beyond the auto-created gaps of the vendor-exit, site-retirement, assessment-finalization, finding-remediation, and validation-run cascades, a `PlanAuthor` may register one manually with the `process_id`, an optional `finding_id`, a `severity`, a `description`, and a `due_date`. The server derives `gap_type`: `FINDING` when a `finding_id` is present, `CAPABILITY` otherwise — and for a manually created capability-style gap the `capability_id` stays empty. Creation refreshes the process's gap-backlog aggregates. A gap's `overdue` flag is computed: true exactly when the gap is `OPEN` or `IN_PROGRESS` and the program clock reads strictly after the `due_date` — a gap due exactly now is not yet overdue. The backlog can be filtered by `process_id`, `capability_id`, `finding_id`, `status`, `severity`, and `closed_by_contact_id`.

Gap work flows through a small lifecycle. Starting work moves `OPEN` → `IN_PROGRESS`; reopening moves `IN_PROGRESS` → `OPEN`, the revision loop for work that stalls. Both are `PlanAuthor` actions, both require their stated source state (`ERR_INVALID_STATE`), and each increments the gap's `version`. Resolution belongs to the `RiskCommittee` and comes in two flavors, each reachable from either `OPEN` or `IN_PROGRESS` (any other source fails `ERR_INVALID_STATE`). Closing moves the gap to `CLOSED` and records the acting contact in `closed_by_contact_id`; risk acceptance moves it to `ACCEPTED_RISK`. Both resolutions refresh the gap-backlog aggregates — overdue flags recompute and every recovery capability of the same process recomputes `validation_freshness`, incrementing the affected capabilities' `version`. One non-cascade is deliberate: closing a finding-linked gap does **not** verify the finding — verification is the separate, guarded transition of §3.6, and a gap closed out from under a `REMEDIATING` finding leaves the finding where it was.

The backlog's pressure is a computed read per process. Each gap in `OPEN` or `IN_PROGRESS` contributes a severity weight — 4 for `CRITICAL`, 3 for `HIGH`, 2 for `MEDIUM`, 1 for `LOW` — doubled when the gap is overdue under the strict reading above; `CLOSED` and `ACCEPTED_RISK` gaps contribute nothing. The `pressure_score` is the sum of these contributions, and if any overdue gap has severity `CRITICAL`, the entire sum is then doubled. The read returns the `pressure_score` alongside the `open_gap_count` and `overdue_gap_count` that fed it. This same recomputation is what the "gap-backlog aggregates refresh" side effects throughout this section and §3.6 refer to.

### 3.8. Crisis Communication Trees and Activations

The crisis module maintains one notification tree per process. A `CrisisOfficer` builds trees node by node: each comm node carries a `tree_label` (nodes sharing a label form one tree; by convention a process's tree is labelled by prefixing its name), the notified party's `contact_name` and `role_title`, a `parent_node_id` that is empty for the tree root and otherwise references another node in the same tree, an integer `order_index` fixing sibling order, a `channel` of `PHONE`, `EMAIL`, or `SMS`, an `ack_deadline_minutes` budget within which acknowledgement is due after activation, and an `active_flag` (defaulting to true) that controls whether the node participates in fan-outs. Structural integrity is enforced at write time: exactly one root — one node with an empty `parent_node_id` — may exist per `tree_label`, and a second is rejected with `ERR_TREE_ROOT_EXISTS`; re-parenting a node in a way that would make the node its own ancestor is rejected with `ERR_COMM_TREE_CYCLE`; sibling order is unique, so a colliding (`tree_label`, `parent_node_id`, `order_index`) triple fails with `ERR_DUPLICATE`; and a node may be deactivated — `active_flag` set false — only when every child node is already inactive, else `ERR_NODE_HAS_ACTIVE_CHILDREN`. Node updates touching `contact_name`, `role_title`, `parent_node_id`, `order_index`, `channel`, `ack_deadline_minutes`, or `active_flag` re-run the applicable structural checks and increment the node's `version`. Comm nodes carry no lifecycle states of their own — only these structural mutations — and the tree can be browsed filtered by `tree_label`, `parent_node_id`, or `active_flag`.

When crisis strikes, the `CrisisOfficer` **activates** the tree for a process, supplying the `process_id`, a `declared_severity` of `SEV1`, `SEV2`, or `SEV3`, an `activation_criterion` of `CRITERION_A`, `CRITERION_B`, or `CRITERION_C`, and a free-text `criterion_justification`. Three gates apply, beyond the process needing to be `ACTIVE` (`ERR_PROCESS_NOT_ACTIVE`). The process must have an `APPROVED` plan, else `ERR_NO_APPROVED_PLAN`. No other activation of the same process may be live — in `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED` — else `ERR_ACTIVATION_ALREADY_ACTIVE`. And the declared severity must permit the requested criterion under a fixed mapping: `SEV1` permits `CRITERION_A` and `CRITERION_B`; `SEV2` permits `CRITERION_A` only; `SEV3` permits no criterion at all, so any request with `SEV3` is rejected with `ERR_CRITERION_NOT_ALLOWED`.

A successful activation starts in `ACTIVE` and immediately performs its fan-out. The server pins `plan_id` to the process's currently `APPROVED` plan, computes `expected_notifications` as the count of distinct comm nodes whose `tree_label` equals the process's tree label (the literal prefix `TREE_` prepended to the process's `name`) and whose `active_flag` is true — a node reachable over several channels still counts once — and creates one notification per such node in tree order: breadth-first, with siblings taken in ascending `order_index` at each level. Each notification is created in `SENT` with its `channel` copied from the node, its `sent_at` stamped from the program clock, its `acked_at` empty, and a per-notification `ack_token` minted for the acknowledgement handshake. The activation's `notified_count` tracks notifications in `SENT` or `ACKED`, its `acked_count` those in `ACKED`, and its `escalation_level` records escalation depth — zero for the initial cascade. As soon as fan-out completes, the moment `notified_count` reaches `expected_notifications`, the activation auto-advances `ACTIVE` → `ALL_NOTIFIED` with `escalation_level` held at zero and a `version` increment. The empty-tree guard is explicit: an activation over a tree with zero active nodes fans out nothing, passes straight through `ALL_NOTIFIED`, and — because zero acknowledgements already equal zero expected — lands immediately in `ACKNOWLEDGED`, reporting zero coverage.

Acknowledgement is the recipient-side handshake, performed by the `CrisisOfficer` presenting the notification's `ack_token`. The token must match the one minted at fan-out (`ERR_ACK_TOKEN_MISMATCH` on a mismatch), the notification must still be `SENT` (`ERR_NOTIFICATION_ALREADY_ACKED` on a repeat), and the owning activation must still be in `ACTIVE` or `ALL_NOTIFIED` — acknowledgements against a deactivated or completed activation fail with `ERR_INVALID_STATE`. A valid acknowledgement stamps `acked_at` from the program clock, moves the notification `SENT` → `ACKED`, and increments the activation's `acked_count`; when that count reaches `expected_notifications`, the activation auto-advances `ALL_NOTIFIED` → `ACKNOWLEDGED`, stamps `acknowledged_at` with the current program time, and increments its `version`. Notifications carry only `id` and `created_at` per §2.5 and can be listed filtered by `activation_id`, `comm_node_id`, or `status`; the activation's notification set is also exposed as a sub-collection, and a notification detail read reveals its `ack_token`.

The activation read model reports **acknowledgement coverage**: zero percent when `expected_notifications` is zero, otherwise the `acked_count` divided by `expected_notifications`, scaled to a percentage and rounded half-up to a whole number. Counters are maintained incrementally by fan-out and acknowledgement, and the coverage is derived on read. Activations can be listed with filters on `process_id`, `status`, `declared_severity`, `plan_id`, and `deactivated_by_contact_id`. Stand-down is the terminal transition: the `CrisisOfficer` deactivates from any of `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED` — any other state fails `ERR_INVALID_STATE` — moving the activation to `DEACTIVATED`, recording the acting contact in `deactivated_by_contact_id`, and incrementing `version`. Deactivation performs no retro-acknowledgement: notifications still pending remain in `SENT` forever after.

### 3.9. Attestations and Readiness

The program's outward face is the **attestation**: a signed statement that a process was resilient over a coverage period. An `AttestationSigner` creates one with the `process_id`, an `attestation_type` of `REGULATORY` or `CUSTOMER`, and the coverage window `period_start` to `period_end` (end strictly after start); an optional `signer_declaration` may be supplied at creation but only matters at signing. The attestation starts in `DRAFT` with `signed_by_contact_id` empty, and the server computes its `readiness_score`. While the attestation remains in `DRAFT`, every detail read recomputes the score against the live program state, so the draft always reflects current readiness. The ledger can be filtered by `process_id`, `attestation_type`, `status`, and `signed_by_contact_id`, and a process's attestation history is exposed as a sub-collection.

Readiness is a strict top-to-bottom computation over the attestation's process, and the evaluation order is pinned because the gap counts feed the points, the points feed the subtotal, and the multiplier keys on a gap count. First, for every gap of the process in `OPEN` or `IN_PROGRESS`, the `overdue` flag is settled: overdue exactly when the program clock reads strictly after the gap's `due_date`. Second, the plan leg contributes 40 points when an `APPROVED` plan exists for the process, and 0 otherwise. Third, the capability base is 25 when the process has at least one recovery capability and every one of them is in `VALIDATED` or `REMEDIATED`; otherwise 0. Fourth, the overdue count is the number of gaps settled overdue in step one. Fifth, the capability leg contributes the capability base minus ten points per overdue gap, floored at zero. Sixth, the exercise leg looks at the process's most recent `COMPLETED` exercise — ranked by `scheduled_end` latest first, ties broken by `created_at` latest first — and contributes 25 points when that exercise's `result` is `MET` and its `scheduled_end` lies within the 365 days preceding the current program time; 10 points when that exercise exists, is within the same 365-day window, and its result is `PARTIAL` or `MISSED`; and 0 otherwise. Seventh, the subtotal is the sum of the plan, capability, and exercise legs. Eighth, the open count is the number of the process's gaps in `OPEN` or `IN_PROGRESS` that are not overdue. Ninth, the multiplier is 0.8 when that open count is greater than zero, and 1.0 when it is zero. Tenth and last, the `readiness_score` is the subtotal multiplied by the multiplier, capped at 100, and floored to an integer — the floor applying only at this final step.

Signing converts the draft into evidence. The `AttestationSigner` signs with `signer_declaration` set to true — an absent or false declaration fails with `ERR_INVALID_REQUEST` — and the readiness gate must clear: the `readiness_score` at signing time must be at least 70, or the signing is rejected with `ERR_READINESS_BELOW_THRESHOLD` (HTTP 422). The attestation must of course be in `DRAFT` (`ERR_INVALID_STATE`). A successful signing records the acting contact in `signed_by_contact_id`, increments `version`, and captures the `snapshot_payload`: an immutable JSON record of the readiness inputs at the signing instant — the approved plan's identity and version, the capability states, the open-gap counts, and the exercise recency. Later mutations anywhere in the program never rewrite the snapshot; it is the permanent answer to "what did the signer see".

Revocation is the only way out, and it is deliberately not the signer's call. A `RiskCommittee` member revokes a `SIGNED` attestation — any other source state fails `ERR_INVALID_STATE` — optionally recording a `revoked_reason`. Segregation of duties applies per §2.11: the revoking contact must differ from the `signed_by_contact_id`, with `ERR_SOD_VIOLATION` on a match. Revocation moves the attestation to its terminal `REVOKED` state and increments `version`; the snapshot, once captured, remains attached and unchanged.

## 4. Endpoint Definitions

All endpoints are mounted under the `/resilience` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or compute against an existing resource return HTTP 200; deletion endpoints return HTTP 204 with no body. Every write and action endpoint returns the created or updated resource in the envelope's `data` field unless its row below says otherwise. Request payloads, derived fields, and side effects are defined by the workflows in §3 — the table is a routing summary, not a schema. "All roles" in the authorization column means every role listed in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/resilience/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | ResilienceAdmin |
| POST | `/resilience/contacts` | Register a contact (committee member, owner, signer) | ResilienceAdmin |
| GET | `/resilience/contacts` | List contacts | All roles |
| GET | `/resilience/contacts/{contactId}` | Get a contact | All roles |
| POST | `/resilience/processes` | Create a business process (starts DRAFT) | ResilienceAdmin |
| GET | `/resilience/processes` | List processes with filters | All roles |
| GET | `/resilience/processes/{processId}` | Get a process | All roles |
| PUT | `/resilience/processes/{processId}` | Update process fields (any non-terminal state) | ResilienceAdmin |
| POST | `/resilience/processes/{processId}/activate` | Activate a draft process | ResilienceAdmin |
| POST | `/resilience/processes/{processId}/suspend` | Suspend an active process | ResilienceAdmin |
| POST | `/resilience/processes/{processId}/resume` | Resume a suspended process | ResilienceAdmin |
| POST | `/resilience/processes/{processId}/retire` | Retire an active process, cascading to non-terminal plans and analyses | ResilienceAdmin |
| GET | `/resilience/processes/{id}/bias` | Analyses of a process | All roles |
| GET | `/resilience/processes/{id}/plans` | Plans of a process | All roles |
| GET | `/resilience/processes/{id}/recovery-capabilities` | Recovery capabilities of a process | All roles |
| GET | `/resilience/processes/{id}/attestations` | Attestations of a process | All roles |
| GET | `/resilience/processes/{id}/blast-radius` | Computed downstream blast radius of a process | All roles |
| GET | `/resilience/processes/{id}/gap-pressure` | Computed gap-backlog pressure of a process | All roles |
| POST | `/resilience/bias` | Create a business impact analysis (DRAFT, provisional score computed) | BIAAnalyst |
| GET | `/resilience/bias` | List analyses | All roles |
| GET | `/resilience/bias/{biaId}` | Get an analysis | All roles |
| PUT | `/resilience/bias/{biaId}` | Update an analysis (DRAFT or REJECTED only); recomputes the provisional score | BIAAnalyst |
| POST | `/resilience/bias/{biaId}/submit` | Submit an analysis for decision (DRAFT or REJECTED to SUBMITTED) | BIAAnalyst |
| POST | `/resilience/bias/{biaId}/decide` | Committee decision: approval triggers supersede, adoption, and recalculation cascades | RiskCommittee |
| POST | `/resilience/plans` | Create a recovery plan (DRAFT); governing analysis pinned per the adoption rule | PlanAuthor |
| GET | `/resilience/plans` | List plans | All roles |
| GET | `/resilience/plans/{planId}` | Get a plan | All roles |
| PUT | `/resilience/plans/{planId}` | Update plan fields (DRAFT only); OCC-guarded via `expected_plan_version` | PlanAuthor |
| POST | `/resilience/plans/{planId}/submit` | Submit a plan for review (requires the three required sections) | PlanAuthor |
| POST | `/resilience/plans/{planId}/approve` | Approve a plan (target-analysis and committed-objective gates; supersede cascade) | PlanApprover |
| POST | `/resilience/plans/{planId}/reject` | Return a plan under review to draft | PlanApprover |
| POST | `/resilience/plans/{planId}/retire` | Retire a plan (guarded from APPROVED) | PlanApprover |
| GET | `/resilience/plans/{id}/sections` | Sections of a plan | All roles |
| POST | `/resilience/plans/{id}/sections` | Add a section to a plan (plan DRAFT only) | PlanAuthor |
| GET | `/resilience/plans/{id}/sections/{sectionId}` | Get a plan section | All roles |
| PUT | `/resilience/plans/{id}/sections/{sectionId}` | Update a plan section (plan DRAFT only) | PlanAuthor |
| DELETE | `/resilience/plans/{id}/sections/{sectionId}` | Delete a plan section (plan DRAFT only) | PlanAuthor |
| POST | `/resilience/dependencies` | Create a process-to-process dependency edge (acyclicity enforced) | ResilienceAdmin |
| GET | `/resilience/dependencies` | List dependency edges | All roles |
| GET | `/resilience/dependencies/{dependencyId}` | Get a dependency edge | All roles |
| DELETE | `/resilience/dependencies/{dependencyId}` | Delete a dependency edge | ResilienceAdmin |
| POST | `/resilience/third-parties` | Onboard a third party (ONBOARDING) | VendorManager |
| GET | `/resilience/third-parties` | List third parties | All roles |
| GET | `/resilience/third-parties/{thirdPartyId}` | Get a third party | All roles |
| POST | `/resilience/third-parties/{thirdPartyId}/activate` | Activate a vendor (from ONBOARDING or SUSPENDED) | VendorManager |
| POST | `/resilience/third-parties/{thirdPartyId}/suspend` | Suspend a vendor | VendorManager |
| POST | `/resilience/third-parties/{thirdPartyId}/exit` | Exit a vendor, cascading VENDOR_FAILOVER capabilities to gap state | VendorManager |
| GET | `/resilience/third-parties/{id}/assessments` | Assessments of a third party | All roles |
| POST | `/resilience/assessments` | Create a continuity assessment (DRAFT, provisional score computed) | VendorManager |
| GET | `/resilience/assessments` | List assessments | All roles |
| GET | `/resilience/assessments/{assessmentId}` | Get an assessment | All roles |
| PUT | `/resilience/assessments/{assessmentId}` | Update a draft assessment; recomputes the provisional score | VendorManager |
| POST | `/resilience/assessments/{assessmentId}/finalize` | Finalize an assessment (segregation-of-duties guarded); freezes the score and may open a gap | VendorManager |
| POST | `/resilience/alternate-sites` | Register an alternate site (ACTIVE) | SiteCoordinator |
| GET | `/resilience/alternate-sites` | List alternate sites | All roles |
| GET | `/resilience/alternate-sites/{siteId}` | Get an alternate site | All roles |
| POST | `/resilience/alternate-sites/{siteId}/retire` | Retire a site (requires no confirmed reservations); cascades SITE capabilities to gap state | ResilienceAdmin |
| GET | `/resilience/alternate-sites/{id}/reservations` | Reservations of a site | All roles |
| GET | `/resilience/alternate-sites/{id}/utilization` | Computed seat utilization at a probe instant | All roles |
| POST | `/resilience/site-reservations` | Reserve site seats for a window (capacity, overlap, and contract checks) | SiteCoordinator |
| GET | `/resilience/site-reservations` | List reservations | All roles |
| GET | `/resilience/site-reservations/{reservationId}` | Get a reservation | All roles |
| POST | `/resilience/site-reservations/{reservationId}/release` | Release a reservation (releaser differs from creator) | SiteCoordinator |
| POST | `/resilience/exercises` | Schedule an exercise (SCHEDULED); failover windows of a process are strictly disjoint | ExerciseOfficer |
| GET | `/resilience/exercises` | List exercises | All roles |
| GET | `/resilience/exercises/{exerciseId}` | Get an exercise | All roles |
| PUT | `/resilience/exercises/{exerciseId}` | Reschedule a SCHEDULED exercise; OCC-guarded via `expected_exercise_version` | ExerciseOfficer |
| POST | `/resilience/exercises/{exerciseId}/start` | Start a scheduled exercise | ExerciseOfficer |
| POST | `/resilience/exercises/{exerciseId}/complete` | Complete an exercise; derives the result and fires the failover validation cascade | ExerciseOfficer |
| POST | `/resilience/exercises/{exerciseId}/cancel` | Cancel a scheduled or in-progress exercise | ExerciseOfficer |
| GET | `/resilience/exercises/{id}/findings` | Findings of an exercise | All roles |
| GET | `/resilience/exercises/{id}/validation-runs` | Validation runs produced by an exercise (zero or one) | All roles |
| POST | `/resilience/findings` | Record a finding on a COMPLETED exercise (OPEN) | ExerciseOfficer |
| GET | `/resilience/findings` | List findings | All roles |
| GET | `/resilience/findings/{findingId}` | Get a finding | All roles |
| POST | `/resilience/findings/{findingId}/remediate` | Begin remediation; auto-creates a remediation gap | PlanAuthor |
| POST | `/resilience/findings/{findingId}/verify` | Verify a remediation; closes the remediation gap and refreshes aggregates | RiskCommittee |
| POST | `/resilience/findings/{findingId}/reject` | Reject a remediation; the remediation gap becomes accepted risk | RiskCommittee |
| GET | `/resilience/findings/{id}/gaps` | Gaps linked to a finding | All roles |
| POST | `/resilience/recovery-capabilities` | Register a recovery capability (UNPROVEN, freshness NEVER) | PlanAuthor |
| GET | `/resilience/recovery-capabilities` | List recovery capabilities | All roles |
| GET | `/resilience/recovery-capabilities/{capabilityId}` | Get a recovery capability | All roles |
| POST | `/resilience/recovery-capabilities/{capabilityId}/mark-remediated` | Mark a gapped capability remediated (all its gaps must be terminal) | PlanAuthor |
| GET | `/resilience/recovery-capabilities/{id}/validation-runs` | Validation runs of a capability | All roles |
| GET | `/resilience/recovery-capabilities/{id}/gaps` | Gaps of a capability | All roles |
| POST | `/resilience/validation-runs` | Record a standalone validation run; computes the result and fires the capability cascade | ExerciseOfficer |
| GET | `/resilience/validation-runs` | List validation runs | All roles |
| GET | `/resilience/validation-runs/{runId}` | Get a validation run | All roles |
| POST | `/resilience/gaps` | Manually register a gap (OPEN) | PlanAuthor |
| GET | `/resilience/gaps` | List gaps | All roles |
| GET | `/resilience/gaps/{gapId}` | Get a gap | All roles |
| POST | `/resilience/gaps/{gapId}/start` | Begin work on a gap | PlanAuthor |
| POST | `/resilience/gaps/{gapId}/reopen` | Return an in-progress gap to open | PlanAuthor |
| POST | `/resilience/gaps/{gapId}/close` | Close a gap; refreshes gap-backlog aggregates | RiskCommittee |
| POST | `/resilience/gaps/{gapId}/accept-risk` | Accept the risk of a gap; refreshes gap-backlog aggregates | RiskCommittee |
| POST | `/resilience/comm-nodes` | Add a node to a crisis communication tree (one root per tree; cycle-free) | CrisisOfficer |
| GET | `/resilience/comm-nodes` | List communication-tree nodes | All roles |
| GET | `/resilience/comm-nodes/{nodeId}` | Get a communication-tree node | All roles |
| PUT | `/resilience/comm-nodes/{nodeId}` | Update a node (re-parent cycle check; deactivation requires inactive children) | CrisisOfficer |
| POST | `/resilience/activations` | Activate the crisis tree for a process; fans out one notification per active node | CrisisOfficer |
| GET | `/resilience/activations` | List activations | All roles |
| GET | `/resilience/activations/{activationId}` | Get an activation with counters and acknowledgement coverage | All roles |
| POST | `/resilience/activations/{activationId}/deactivate` | Stand down an activation (from any non-terminal state) | CrisisOfficer |
| GET | `/resilience/activations/{id}/notifications` | Notifications of an activation | All roles |
| GET | `/resilience/notifications` | List notifications | All roles |
| GET | `/resilience/notifications/{notificationId}` | Get a notification (includes its acknowledgement token) | All roles |
| POST | `/resilience/notifications/{notificationId}/ack` | Acknowledge a notification (token-checked); may complete the activation | CrisisOfficer |
| POST | `/resilience/attestations` | Create an attestation for a coverage period (DRAFT) | AttestationSigner |
| GET | `/resilience/attestations` | List attestations | All roles |
| GET | `/resilience/attestations/{attestationId}` | Get an attestation (readiness recomputed on read while DRAFT) | All roles |
| POST | `/resilience/attestations/{attestationId}/sign` | Sign an attestation (readiness gate); captures the immutable snapshot | AttestationSigner |
| POST | `/resilience/attestations/{attestationId}/revoke` | Revoke a signed attestation (revoker differs from signer) | RiskCommittee |

## 5. Error Code Catalogue

The catalogue below fixes the machine-readable `error_id` values and their HTTP status codes. The conditions that raise each error are defined where they arise in §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_CONTACT_NOT_FOUND | 404 |
| ERR_PROCESS_NOT_FOUND | 404 |
| ERR_BIA_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_SECTION_NOT_FOUND | 404 |
| ERR_DEPENDENCY_NOT_FOUND | 404 |
| ERR_VENDOR_NOT_FOUND | 404 |
| ERR_ASSESSMENT_NOT_FOUND | 404 |
| ERR_SITE_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_EXERCISE_NOT_FOUND | 404 |
| ERR_FINDING_NOT_FOUND | 404 |
| ERR_CAPABILITY_NOT_FOUND | 404 |
| ERR_RUN_NOT_FOUND | 404 |
| ERR_GAP_NOT_FOUND | 404 |
| ERR_NODE_NOT_FOUND | 404 |
| ERR_ACTIVATION_NOT_FOUND | 404 |
| ERR_NOTIFICATION_NOT_FOUND | 404 |
| ERR_ATTESTATION_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALIDATION | 400 |
| ERR_MTPD_BELOW_RTO | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_PROCESS_NOT_ACTIVE | 409 |
| ERR_VENDOR_NOT_ACTIVE | 409 |
| ERR_CAPABILITY_TARGETS_UNKNOWN | 422 |
| ERR_PLAN_NOT_APPROVED_FOR_EXERCISE | 409 |
| ERR_READINESS_BELOW_THRESHOLD | 422 |
| ERR_REQUIRED_SECTION_MISSING | 422 |
| ERR_DUPLICATE | 409 |
| ERR_DEPENDENCY_CYCLE | 422 |
| ERR_DEPENDENCY_SELF_LOOP | 422 |
| ERR_TREE_ROOT_EXISTS | 409 |
| ERR_COMM_TREE_CYCLE | 422 |
| ERR_NODE_HAS_ACTIVE_CHILDREN | 409 |
| ERR_ACK_TOKEN_MISMATCH | 403 |
| ERR_NOTIFICATION_ALREADY_ACKED | 409 |
| ERR_CRITERION_NOT_ALLOWED | 422 |
| ERR_NO_APPROVED_PLAN | 422 |
| ERR_ACTIVATION_ALREADY_ACTIVE | 409 |
| ERR_PROCESS_HAS_OPEN_ITEMS | 409 |
| ERR_SITE_HAS_ACTIVE_RESERVATIONS | 409 |
| ERR_PLAN_HAS_ACTIVE_EXERCISE | 409 |
| ERR_PLAN_HAS_LIVE_ACTIVATION | 409 |
| ERR_CAPABILITY_HAS_OPEN_GAPS | 409 |
| ERR_SITE_WINDOW_OVERLAP | 409 |
| ERR_SITE_CAPACITY_EXCEEDED | 422 |
| ERR_EXERCISE_WINDOW_OVERLAP | 409 |
| ERR_SITE_CONTRACT_EXPIRED | 422 |
| ERR_PLAN_TARGETS_UNAPPROVED_BIA | 422 |
| ERR_PLAN_EXCEEDS_BIA_RTO | 422 |
| ERR_PLAN_EXCEEDS_BIA_RPO | 422 |
| ERR_STALE_VERSION | 412 |

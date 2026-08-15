# Contract Redlining Playbook API — Product Requirements Document

## 1. Introduction

In-house contracts teams live in the gap between standard terms and negotiated reality. Every counterparty redline forces the same questions — is this clause protected, what fallback positions are approved, who must sign off on this deviation, and how long has this deal been sitting with legal — and today those answers are scattered across email threads, shared drives, and individual memory. The result is inconsistent positions, unrecorded approvals, and no reliable way to reconstruct who agreed to what, when, and under which authority.

This document specifies the Contract Redlining Playbook API, the system of record for an in-house contracts team's negotiation discipline. The API governs the full arc of a deal: a clause library with canonical texts and ordered fallback positions maintained under a versioned playbook; intake triage that classifies each request by contract type, value tier, and counterparty risk and routes it to accountable owners; automated deviation detection that scores every counterparty edit against the playbook and escalates non-standard terms to the right approver; ordered signature routing with per-signatory authority ceilings; and, upon execution, the extraction of obligations into a repository alongside cycle-time and bottleneck analytics that show where deals stall.

Three design constraints shape everything that follows. First, segregation of duties is structural, not customary: the analyst who drafts a negotiation can never approve its deviations, and escalation paths are enforced by the server rather than by convention. Second, negotiations are long-lived and touched by many parties, so optimistic concurrency guards the handful of writes where a stale view could silently overwrite another participant's decision. Third, time is a first-class input — signature windows open and close, obligations mature at fixed offsets, and cycle times accumulate — so the server runs on a logical clock that operators can advance deterministically, and every time-driven transition fires off that clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly seven roles, spelled as follows: `ContractAnalyst`, who files intake, runs triage, opens rounds and deviations, and withdraws their own drafts; `BusinessOwner`, the default business owner who approves operational-fallback deviations; `LegalCounsel`, the general counsel who approves most deviations, finalizes redlining, and creates signature packets; `FinanceController`, who approves COMMERCIAL deviations on high-value contracts; `ChiefCounsel`, who publishes playbooks, retires clauses, and is the final approver on escalated and high-severity deviations; `Signatory`, who executes signature packets within an authority ceiling; and `OpsAdmin`, the platform operator who manages users, contract types, and the logical clock, and creates counterparties.

When `X-User-Role` is `ContractAnalyst`, `BusinessOwner`, `LegalCounsel`, `FinanceController`, `ChiefCounsel`, or `Signatory`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` — such as `submitted_by_user_id` on an intake request, `drafter_user_id` on a negotiation, or `assigned_approver_id` on a deviation — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `OpsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it does not compare it to any entity's `id`. The persisted `User` record stores its capacity in `primary_role`, whose values are the upper-case spellings `CONTRACT_ANALYST`, `BUSINESS_OWNER`, `LEGAL_COUNSEL`, `FINANCE_CONTROLLER`, `CHIEF_COUNSEL`, `SIGNATORY`, and `OPS_ADMIN`, corresponding one-to-one with the header role names above.

A request missing either header, or carrying a malformed header, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). An `X-User-ID` that does not resolve to a `User` row whose `status` is `ACTIVE` is rejected with `ERR_USER_NOT_FOUND` (HTTP 401); a deactivated account therefore cannot act. A caller whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). These three checks run first, in this order, ahead of every other validation (see §2.8).

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so clients can page deterministically through playbooks, clauses, negotiations, deviations, and every other collection.

### 2.4. Common Resource Properties

Primary resources — playbooks, clause templates, contract types, counterparties, users, intake requests, negotiations, deviations, and signature packets — share a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by cascades from other entities.

Audit records that are immutable once written — a `TriageDecision`, a `NegotiationRound`, an `ApprovalDecision`, and an `Obligation` — carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these four entity types, because nothing about them ever changes after creation.

### 2.5. The Logical Clock and Time-Driven Expiry

All server-side timestamps are drawn from a logical clock, not the wall clock. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. An admin-only test-driving capability, restricted to `OpsAdmin`, advances the logical clock to a supplied `to_iso8601` instant and returns the confirmed time as `now_iso8601`.

Advancing the clock is not a passive readjustment: it fires the system's time-driven transitions. In particular, when the logical clock moves past a signature packet's `signature_window_closes_at` while that packet is still unsigned or only partially signed, the packet expires automatically (see §3.8). Signature-window enforcement, execution-timestamp validation, cycle-time measurement, and obligation due dates all read from the same logical clock, so a test harness can walk an entire negotiation from intake to expiry deterministically.

### 2.6. Monetary Values, Value Tiers, and Numeric Precision

All monetary amounts in the system are integer cents — `contract_value_cents`, the tier thresholds on a contract type, `can_sign_above_cents`, and the per-signatory `authority_cap_cents` — and are compared as integers with no floating-point involvement. Value-tier boundaries are inclusive on the upper bound of each tier and exclusive on the lower bound of the next: a contract valued exactly at a tier's threshold belongs to that tier.

Risk scores are integers between 0 and 100 inclusive, produced by the weighted scoring rule in §3.5 and capped by the clause's severity ceiling. Durations — `cycle_time_seconds`, `round_duration_seconds`, and every analytics aggregate — are integer seconds. Obligation due dates are computed in whole days of 86,400 seconds each and stored as ISO 8601 datetimes at second precision.

### 2.7. Optimistic Concurrency Control

Three write operations operate on state that other participants may have advanced since the client last read it, and each therefore demands an explicit expected-version field as a non-optional member of the request body. These are the only endpoints that take a version field; no other endpoint accepts one.

- Opening a negotiation against a routed intake request requires `expected_intake_request_version`, carrying the client's last observed `version` of that intake request. If the intake request's current `version` has moved past the supplied value — because another writer cancelled it or already opened the negotiation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an intake it has not re-read.
- Casting an approval decision on a deviation requires `expected_negotiation_version`, carrying the approver's last observed `version` of the parent negotiation. Any intervening mutation — a new round opened, another deviation decided, an escalation re-resolving the assigned approver — advances the negotiation's `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than letting the decision land on a negotiation state the approver never saw.
- Creating a signature packet likewise requires `expected_negotiation_version` matching the negotiation's current `version`. A prior packet creation by another counsel legitimately supersedes the caller's view of negotiation state, so a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Validation Pipeline and Check Ordering

Every request passes through a fixed validation pipeline, and checks are applied in ascending priority order: the first failing check determines the error returned, and later checks are not evaluated. The pipeline begins, in order, with (1) header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), (2) user resolution against an `ACTIVE` `User` row (`ERR_USER_NOT_FOUND`), (3) role permission on the endpoint (`ERR_FORBIDDEN_FOR_ROLE`), (4) left-to-right resolution of path-template identifiers (`ERR_NOT_FOUND`, see §2.9), and (5) existence of every foreign key referenced in the request body — `clause_template_id`, `playbook_id`, `contract_type_id`, `counterparty_id`, `default_business_owner_id`, `default_legal_counsel_id`, and `drafter_user_id` — with an unresolvable reference rejected as `ERR_FOREIGN_KEY_NOT_FOUND` (HTTP 422).

Domain-specific guards then run in their own numbered order. Where several guards share one endpoint, the relative ordering is part of the contract: on intake triage, the sanctioned-counterparty guard fires ahead of the generic state guard, so a sanctioned counterparty surfaces as `ERR_COUNTERPARTY_SANCTIONED` rather than being masked by a state error. On negotiation opening, the intake's state is confirmed first (`ERR_INVALID_STATE_TRANSITION`), then the referenced playbook's `ACTIVE` status (`ERR_PLAYBOOK_NOT_ACTIVE`), and only then the expected-version comparison (`ERR_STALE_VERSION`). On a deviation decision, the order is state validity, then version freshness, then segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), then approver-role sufficiency (`ERR_INSUFFICIENT_APPROVER_ROLE`), then escalation eligibility (`ERR_SEVERITY_NOT_ESCATABLE`), and finally body completeness such as a missing `decision_rationale` (`ERR_INVALID_REQUEST`). On packet signing, the signatory's authority ceiling is checked first (`ERR_SIGNATORY_AUTHORITY_EXCEEDED`), then the signature window (`ERR_SIGNATURE_WINDOW_VIOLATION`), then signing order (`ERR_SIGNATORY_OUT_OF_ORDER`). On deviation creation, foreign-key resolution precedes the duplicate-deviation guard (`ERR_DEVIATION_ALREADY_OPEN`), which in turn precedes the fallback-index range check (`ERR_FALLBACK_INDEX_OUT_OF_RANGE`). On round closure, the round's `OPEN` state is confirmed before the blocking-deviation tally is consulted. Body-completeness checks such as a required free-text field are enforced last in the numbered sequence on the endpoints that declare them.

### 2.9. Nested Resource Retrieval

Most workflow resources are addressed through nested paths — a deviation, for instance, is addressed as `/negotiations/{negotiationId}/deviations/{deviationId}`, and a signature packet as `/negotiations/{negotiationId}/signature-packets/{packetId}`. The server validates every identifier in such a path in strict left-to-right order — playbook before clause, intake request before negotiation, negotiation before round, deviation, or packet — and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request naming a non-existent negotiation therefore fails on the negotiation identifier before the server ever looks at the deviation or packet beneath it, and the same ordering applies to the clause-under-playbook and round-under-negotiation hierarchies. The path-template identifiers used throughout the API are `playbookId`, `clauseId`, `typeId`, `counterpartyId`, `userId`, `intakeRequestId`, `negotiationId`, `roundId`, `deviationId`, `packetId`, `triageDecisionId`, `decisionId`, and `obligationId`.

### 2.10. Segregation of Duties and Approval Authority

Approval authority in this system is a ladder, not a flat pool. The approver ladder runs, from lowest to highest, `LEGAL_COUNSEL`, then `BUSINESS_OWNER`, then `FINANCE_CONTROLLER`, then `CHIEF_COUNSEL`; a decision is valid only when the acting approver's `primary_role` meets or exceeds the deviation's computed `required_approver_role`, and a shortfall is rejected with `ERR_INSUFFICIENT_APPROVER_ROLE` (HTTP 403). Escalation always moves upward, and an escalation lands exclusively on `CHIEF_COUNSEL`.

Segregation of duties is enforced between drafting and approval: the user recorded as a negotiation's `drafter_user_id` may record and withdraw deviations but may never cast an approval decision on them, and any attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). Withdrawal is the mirror image of this rule — only the drafter may withdraw a deviation, and anyone else is rejected with `ERR_NOT_DRAFTER` (HTTP 403).

Signing authority is likewise quantified rather than assumed. Each user's `can_sign_above_cents` is an authority ceiling: the user may execute a contract only when the ceiling is strictly greater than the negotiation's `contract_value_cents`, and a ceiling exactly equal to the contract value is not sufficient. A breach is rejected with `ERR_SIGNATORY_AUTHORITY_EXCEEDED` (HTTP 403).

### 2.11. Derived Counters and Cross-Entity Consistency

The server maintains a family of derived counters that keep parent resources consistent with their children, and every cascade that changes one of these counters is a mutation of the affected entity: its `updated_at` refreshes and its `version` increments by one.

A playbook's `clause_count` is the number of its clause templates whose `status` is not `RETIRED`; it rises by one when a clause is created and falls by one when a clause is retired, and each change bumps the playbook's `version`. A playbook's `active_negotiation_count` and a counterparty's `active_negotiation_count` each tally the negotiations referencing them whose `draft_status` is neither `EXECUTED` nor `ABORTED`; both increment when a negotiation is opened and decrement when it is executed or aborted. A counterparty's `last_executed_at` tracks the most recent execution timestamp and remains null until the first execution completes.

On a negotiation, `open_deviation_count` tallies its deviations in `OPEN`, `IN_REVIEW`, or `ESCALATED` status, while `blocking_deviation_count` tallies only those in `OPEN` or `ESCALATED` — the subset that gates round advancement and finalization. `total_rounds` counts the negotiation's rounds, `current_round_index` tracks the latest round number (zero until the first round opens), and each round's `clause_change_count` records how many deviations were detected during it. These counters move together with the operations described in §3: recording, deciding, withdrawing, and superseding deviations; opening and closing rounds; aborting; and recording execution.

## 3. Business Logic & Workflows

### 3.1. Building and Governing the Playbook Library

Every negotiation in the system is measured against a playbook, so the library comes first. A `ChiefCounsel` — or an `OpsAdmin` acting on the platform's behalf — creates a playbook by supplying a `name`; the new playbook starts in `DRAFT` status with `published_at` null and both derived counters at zero. While in `DRAFT`, the playbook is a workspace: it cannot anchor a negotiation yet, and it carries no publication timestamp.

Clause templates are the playbook's substance. A `ChiefCounsel` adds a clause by providing a stable machine key in `clause_key`, unique within the owning playbook — values such as `LIMITATION_OF_LIABILITY` or `GOVERNING_LAW` — together with a `category` of `RISK`, `COMMERCIAL`, `OPERATIONAL`, or `REGULATORY`, the canonical `standard_text`, and an ordered array of up to three `fallback_positions` in which index 0 is the most-preferred fallback and order matters; an empty array declares that no fallback is permitted at all. Each clause also declares its governance in two fields: `approver_role_required`, the minimum role that must approve a deviation against the clause — one of `LEGAL_COUNSEL`, `FINANCE_CONTROLLER`, `BUSINESS_OWNER`, or `CHIEF_COUNSEL` — and `deviation_severity_cap`, the maximum severity an ordinary approver may clear, one of `LOW`, `MEDIUM`, or `HIGH`. Every clause starts in `ACTIVE` status. Each addition increments the parent playbook's `clause_count` by one and, because the parent has changed, bumps the playbook's `version` as well.

Publication moves a playbook from `DRAFT` to `ACTIVE` and is restricted to `ChiefCounsel`. Two guards apply, evaluated in this order: a playbook with no clause templates at all cannot publish (`ERR_PLAYBOOK_EMPTY`), and a playbook whose clause templates have all been retired likewise cannot publish (`ERR_PLAYBOOK_NO_ACTIVE_CLAUSES`) — at least one child must be `ACTIVE`. On successful publication the server stamps `published_at` with the current logical-clock time and increments the playbook's `version`. Clause listings, whether reached through the parent playbook or through the flat clause collection, may be filtered by `status`, `category`, and `playbook_id`; the playbook list itself accepts a `status` filter.

Retirement flows the other way. Retiring a clause — again a `ChiefCounsel` operation — requires, first, that the clause currently be `ACTIVE`, second that the parent playbook be `ACTIVE` (`ERR_PLAYBOOK_NOT_ACTIVE`), and third that no deviation in `OPEN`, `IN_REVIEW`, or `ESCALATED` status still references the clause (`ERR_CLAUSE_HAS_OPEN_DEVIATIONS`). A retired clause moves `ACTIVE → RETIRED`, a transition from which it never returns; the playbook's `clause_count` decrements by one and its `version` increments.

Deprecation retires the playbook itself. From `ACTIVE`, a `ChiefCounsel` may deprecate a playbook only when no negotiation still references it — that is, when its `active_negotiation_count` is exactly zero — and a referenced playbook refuses to go away with `ERR_PLAYBOOK_IN_USE`. From `DRAFT`, deprecation is unconditional: an unused draft may be discarded at any time. Either way the playbook lands in `DEPRECATED` — `ACTIVE → DEPRECATED` from a published playbook, `DRAFT → DEPRECATED` from an unpublished one — its `version` increments, and `DEPRECATED` is terminal: a deprecated playbook can never be restored to any earlier status.

### 3.2. Contract Types, Counterparties, and the User Directory

Three bodies of reference data give triage its vocabulary. An `OpsAdmin` creates a contract type with a unique machine `code` — `NDA`, `MSA`, `SOW`, `DPA`, `RESA`, and the like — plus a human `display_name`. The contract type carries the value-tier ladder as three thresholds in integer cents: `low_value_threshold_cents`, the inclusive upper bound of the `LOW` tier; `mid_value_threshold_cents`, the inclusive upper bound of `MID`; and `high_value_threshold_cents`, the inclusive upper bound of `HIGH`. The three must be strictly ascending — the mid threshold strictly greater than the low, the high strictly greater than the mid — and a creation that violates this ordering is rejected with `ERR_THRESHOLDS_NOT_MONOTONIC` (HTTP 422). Two further thresholds shape approvals downstream: `auto_approve_below_cents`, below which fallback-only deviations approve automatically — a value of 0 disables auto-approval entirely — and `requires_chief_counsel_above_cents`, at or above which every deviation on the contract requires `CHIEF_COUNSEL` regardless of any clause's severity cap. Routing defaults come from `default_business_owner_id` and `default_legal_counsel_id`, both of which must resolve to existing users at creation time (`ERR_FOREIGN_KEY_NOT_FOUND`). A contract type starts `ACTIVE`; an `OpsAdmin` may retire it — `ACTIVE → RETIRED` — only while no negotiation referencing it remains outside `EXECUTED` or `ABORTED`, otherwise `ERR_CONTRACT_TYPE_IN_USE`, and `RETIRED` is terminal. The contract-type list may be filtered by `status`, `default_business_owner_id`, or `default_legal_counsel_id`.

Counterparties are the other half of the risk picture. An `OpsAdmin` or `ContractAnalyst` registers one with its registered `legal_name` and a `jurisdiction` code; the optional `risk_tier` accepts `LOW`, `STANDARD`, `HIGH_RISK`, or `SANCTIONED` and defaults to `STANDARD` when omitted. Thereafter the counterparty's record accumulates two system-maintained facts: `active_negotiation_count`, the number of its negotiations not yet in `EXECUTED` or `ABORTED`, and `last_executed_at`, the timestamp of its most recent execution, null until the first one completes. Counterparty listings may be filtered by `risk_tier`.

Users round out the directory. An `OpsAdmin` creates each user with a unique login `email`, a `display_name`, and a `primary_role` drawn from the seven upper-case values enumerated in §2.1. The optional `can_sign_above_cents` field is the user's signatory authority ceiling — the user may execute only contracts whose value is strictly less than this ceiling — and it defaults to 0, which, because the authority comparison is strict, means the user cannot sign anything at all. A user starts `ACTIVE` and may later be `DEACTIVATED`, at which point the account no longer authenticates (§2.1). User listings may be filtered by `primary_role` and `status`.

### 3.3. Intake Submission, Value Tiering, and Triage Routing

A deal enters the system as an intake request. A `ContractAnalyst` or `BusinessOwner` files it with the `submitted_by_user_id` of the filer, the `contract_type_id` and `counterparty_id` it concerns, the stated `contract_value_cents` — which must be an integer greater than zero — and the requested `effective_date`. Every referenced foreign key must resolve (`ERR_FOREIGN_KEY_NOT_FOUND`). The new request lands in `PENDING_TRIAGE` with its computed fields — `routing_bucket`, `assigned_owner_id`, `assigned_legal_id`, and `triage_decision_id` — still null.

Triage is a `ContractAnalyst` action and runs two guards before any classification: the referenced contract type must be `ACTIVE` (`ERR_CONTRACT_TYPE_INACTIVE`), and the counterparty must not be `SANCTIONED` — a sanctioned counterparty is refused outright with `ERR_COUNTERPARTY_SANCTIONED` (HTTP 409), and this refusal is evaluated ahead of the generic state check so it is never masked by one. Only an intake still in `PENDING_TRIAGE` may be triaged; any other state is an `ERR_INVALID_STATE_TRANSITION`.

Classification begins with the value tier. The intake's `contract_value_cents` is compared against the contract type's thresholds with each tier's upper bound inclusive: a value at or below `low_value_threshold_cents` is tier `LOW`; otherwise a value at or below `mid_value_threshold_cents` is `MID`; otherwise a value at or below `high_value_threshold_cents` is `HIGH`; anything above all three is `VERY_HIGH`.

The routing bucket is then derived by a first-match-wins cascade, evaluated in exactly this order. A `SANCTIONED` counterparty never routes — triage has already refused it above. A `HIGH_RISK` counterparty routes to `EXECUTIVE` at any contract value. A `VERY_HIGH` value tier likewise routes to `EXECUTIVE`. A `HIGH` tier routes to `ELEVATED`. A `MID` tier routes to `STANDARD`. A `LOW` tier whose value is strictly less than the contract type's `auto_approve_below_cents` routes to `SELF_SERVE`. Anything remaining routes to `STANDARD`.

A supervisor-flagged analyst may override the computed bucket by including `override_routing_bucket` in the triage request: the override may shift the bucket up by exactly one level — `SELF_SERVE` to `STANDARD`, `STANDARD` to `ELEVATED`, `ELEVATED` to `EXECUTIVE` — and may never shift it down.

Every triage run persists an append-only `TriageDecision` capturing the intake request's `intake_request_id`, the `decided_at` timestamp, the computed `routing_bucket` and `value_tier`, a `counterparty_risk` snapshot of the counterparty's tier at decision time, a human-readable `rationale` tracing the derivation, and `decided_by` — `SYSTEM` for a straight computation or `ANALYST_OVERRIDE` when the override was used. The intake request then absorbs the outcome: its `routing_bucket` copies the decision's, `assigned_owner_id` becomes the contract type's `default_business_owner_id`, `assigned_legal_id` becomes its `default_legal_counsel_id`, `triage_decision_id` points at the new decision record, and the status advances `PENDING_TRIAGE → ROUTED`. Triage decisions are retrievable per intake request or through the flat decision collection filtered by `intake_request_id`.

Two early exits exist for requests that should not proceed. While still `PENDING_TRIAGE`, an analyst may reject the request, but only with a `rejection_reason` supplied — its absence is an `ERR_INVALID_REQUEST` — landing the request in `REJECTED`. Cancellation is quieter: from either `PENDING_TRIAGE` or `ROUTED`, an analyst may cancel with no further preconditions, landing in `CANCELLED`. Both reject and cancel increment the intake request's `version`, and `REJECTED`, `CANCELLED`, and `NEGOTIATION_OPENED` are the request's three terminal states. Intake listings may be filtered by `status`, `routing_bucket`, `submitted_by_user_id`, `contract_type_id`, `counterparty_id`, `assigned_owner_id`, `assigned_legal_id`, or `triage_decision_id`.

### 3.4. Opening a Negotiation and Running Redlining Rounds

A routed intake request becomes a live negotiation through a single guarded act by a `ContractAnalyst`. The request body names the `playbook_id` whose clause library will govern the deal and the `drafter_user_id` of the analyst or counsel opening the negotiation — the same person who will later be barred from approving its deviations — plus the optimistic-concurrency field `expected_intake_request_version`. The guards run in a fixed order: the intake must currently be `ROUTED` (`ERR_INVALID_STATE_TRANSITION`), the referenced playbook must be `ACTIVE` (`ERR_PLAYBOOK_NOT_ACTIVE`), and the supplied version must match the intake request's current `version` (`ERR_STALE_VERSION`, HTTP 412). Body references resolve first, of course — an unknown playbook or drafter is an `ERR_FOREIGN_KEY_NOT_FOUND`.

Opening succeeds as a bundle of side effects. The new negotiation records its `intake_request_id`; pins `playbook_id` and snapshots the playbook's current `version` into `playbook_version_at_pin` for later staleness detection; seeds `contract_value_cents` from the intake's stated value; copies `contract_type_id` and `counterparty_id` across; takes `business_owner_id` and `legal_counsel_id` from the triage assignments; and stores the body's `drafter_user_id`. The intake request advances to `NEGOTIATION_OPENED` with its `version` incremented, while the counterparty's and the playbook's `active_negotiation_count` each increment by one — the deal is now counted against both.

A negotiation is not one state machine but three parallel dimensions on one entity. The `draft_status` dimension — `OPEN`, `REDLINING`, `AWAITING_COUNTERSIGN`, `EXECUTED`, `ABORTED` — advances through rounds and execution. The `approval_status` dimension — starting at `NO_DEVIATIONS` — is derived from the fate of the negotiation's deviations. The `signature_status` dimension — starting at `NOT_STARTED` — is driven entirely by signature packets. A fresh negotiation reads `OPEN` / `NO_DEVIATIONS` / `NOT_STARTED`, with `current_round_index` at 0, `open_deviation_count` and `blocking_deviation_count` at 0, `total_rounds` at 0, and `cycle_time_seconds` at 0 until execution. Its terminal configurations are `EXECUTED` on the draft dimension — paired with `APPROVED_WITH_DEVIATIONS` or `NO_DEVIATIONS` on the approval dimension and `EXECUTION_RECORDED` on the signature dimension — or `ABORTED` on the draft dimension, which freezes the other two. Negotiation listings may be filtered by `intake_request_id`, `playbook_id`, `contract_type_id`, `counterparty_id`, `business_owner_id`, `legal_counsel_id`, `drafter_user_id`, `draft_status`, `approval_status`, or `signature_status`.

Redlining proceeds in rounds. A `ContractAnalyst` opens the first round with a free-text `change_summary`; this requires `current_round_index` still at 0 and no other round currently `OPEN` — a second simultaneous round is refused with `ERR_ROUND_ALREADY_OPEN`, and the state guard is evaluated before the already-open guard. The round is created in `OPEN` status with `round_index` 1, `opened_at` set to the current logical time, and `opened_by_user_id` recording the actor; while the round remains open, its `closed_at`, `closed_by_user_id`, and `round_duration_seconds` stay null. The negotiation's draft dimension moves `OPEN → REDLINING`, `current_round_index` and `total_rounds` become 1, and the negotiation's `version` increments. Round indexes increase monotonically and are unique within their negotiation.

Closing a round and opening the next is the `REDLINING → REDLINING` cycle. Closure requires the current round to be `OPEN` (otherwise `ERR_INVALID_STATE_TRANSITION`) and `blocking_deviation_count` to be exactly zero — any deviation still in `OPEN` or `ESCALATED` blocks the close with `ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE`. A clean close stamps the round's `closed_at`, records `closed_by_user_id`, computes `round_duration_seconds` as the elapsed seconds from open to close, and moves the round to `CLOSED`; the next round then opens with `round_index` one higher, `current_round_index` and `total_rounds` each increment, and the negotiation's `version` increments again. Round listings — nested or flat — may be filtered by `status`, `opened_by_user_id`, `closed_by_user_id`, and, on the flat collection, `negotiation_id`.

Aborting is the draft dimension's emergency exit, and its blast radius depends on how far the deal has come. From `OPEN`, a `ContractAnalyst` abort withdraws every deviation in `OPEN`, `IN_REVIEW`, or `ESCALATED`. From `REDLINING`, the same action additionally supersedes any round still `OPEN` — stamping its `closed_at` — and stamps `resolved_at` on each withdrawn deviation. Either way, the counterparty's and playbook's `active_negotiation_count` each decrement by one and the negotiation's `version` increments. Aborting from `AWAITING_COUNTERSIGN` belongs to `LegalCounsel` and is covered in §3.8.

### 3.5. Recording Deviations: Severity, Risk, and Approver Resolution

Deviations are how counterparty redlines enter the system. During an open round, a `ContractAnalyst` or `LegalCounsel` records one against a negotiation by supplying the `clause_template_id` being deviated, the counterparty's `proposed_text`, and a `fallback_index` — a zero-based index into the clause template's `fallback_positions`, or -1 to declare the proposed text non-standard, outside every approved fallback. The record captures the `round_id` of the round in which it was detected, stamps `opened_at`, and starts in `OPEN` status with `resolved_at` null and `cycle_time_seconds` unset until resolution. After foreign-key resolution, two creation guards apply in order. First, at most one deviation per clause may be live on a negotiation: if a deviation for the same (negotiation, clause) pair currently sits in `ESCALATED`, creation is refused outright with `ERR_DEVIATION_ALREADY_OPEN`; if instead the prior deviation is in `OPEN` or `IN_REVIEW`, the new record supersedes it — the prior moves to `SUPERSEDED` with its `resolved_at` stamped, and the open and blocking counts decrement for the superseded record and increment for the new one, a net change of zero. Second, the fallback index must address a real position: any non-negative index when the clause has no fallback positions configured, or an index greater than or equal to the number of positions, is rejected with `ERR_FALLBACK_INDEX_OUT_OF_RANGE` (HTTP 422).

Severity falls out of the index. A `fallback_index` of -1 yields severity `NON_STANDARD`. A valid index — 0 through the last configured position — yields `FALLBACK`, with index 0 denoting the most-preferred fallback. The remaining enumeration value, `STANDARD`, exists for completeness: a clause used verbatim produces no deviation row at all, so `STANDARD` is never assigned to a stored deviation and contributes zero in scoring.

Each deviation carries a computed `risk_score`, an integer from 0 to 100, built from five additive components. Severity contributes 0 for `STANDARD`, 10 for `FALLBACK`, or 30 for `NON_STANDARD`. The clause's category contributes 0 for `OPERATIONAL`, 5 for `COMMERCIAL`, 15 for `REGULATORY`, or 20 for `RISK`. The contract's value tier contributes 0 for `LOW`, 5 for `MID`, 15 for `HIGH`, or 25 for `VERY_HIGH`. The counterparty's risk tier contributes 0 for `LOW`, 5 for `STANDARD`, or 15 for `HIGH_RISK` — a `SANCTIONED` counterparty never reaches scoring, having been refused at triage. Finally, lateness costs two points per completed round: the round penalty is the negotiation's `current_round_index` minus one, multiplied by 2, so a first-round deviation pays nothing and each subsequent round adds two points. The sum of these five components is then capped according to the clause's `deviation_severity_cap`: 30 when the cap is `LOW`, 60 when `MEDIUM`, and 100 when `HIGH`. The deviation's `risk_score` is the lesser of that cap and the computed sum, and the score is recomputed if the deviation is later escalated.

Approver resolution then decides who must clear the deviation, computed as an ordered ladder of raises. The starting point is the clause's `approver_role_required`. If the severity is `NON_STANDARD` and the clause's `deviation_severity_cap` is `HIGH`, the requirement rises to `CHIEF_COUNSEL` and the deviation's `escalated_to_chief_counsel` flag is set true. Independently, if the negotiation's `contract_value_cents` is greater than or equal to the contract type's `requires_chief_counsel_above_cents`, the requirement likewise rises to `CHIEF_COUNSEL` with the flag set — high-value deals route to the top regardless of clause caps. Next, if the severity is anything other than `STANDARD`, the contract value is at least the contract type's `high_value_threshold_cents`, and the clause's category is `COMMERCIAL`, the requirement rises to `FINANCE_CONTROLLER` — unless it already stands at `CHIEF_COUNSEL`, which is never lowered. Finally, if the clause's category is `OPERATIONAL`, the severity is `FALLBACK`, and the requirement still sits at `LEGAL_COUNSEL`, it rises to `BUSINESS_OWNER`. The outcome lands in the deviation's `required_approver_role`, and the server resolves `assigned_approver_id` to a user holding that role. The `escalated_to_chief_counsel` flag begins false and turns true only when the requirement is raised to `CHIEF_COUNSEL` beyond the clause's own cap — by either of the two raises above or by a manual escalation (§3.6).

One shortcut bypasses human review entirely. When the negotiation's value is strictly less than the contract type's `auto_approve_below_cents` and the severity is `FALLBACK`, the deviation is auto-approved: the system moves it directly from `OPEN` to `APPROVED` with no human decision. A contract type whose `auto_approve_below_cents` is 0 disables this path, since no positive value is strictly less than zero.

Creation ripples outward. The first deviation recorded on a negotiation flips the approval dimension from `NO_DEVIATIONS` to `DEVIATIONS_PENDING`; `open_deviation_count` and `blocking_deviation_count` each increment; and the negotiation's `version` increments. Deviation listings — nested or flat — may be filtered by `status`, `severity`, `clause_template_id`, `round_id`, `assigned_approver_id`, and, on the flat collection, `negotiation_id`.

### 3.6. Reviewing and Deciding Deviations

Review begins when an approver picks up an `OPEN` deviation. Beginning review is open to `LegalCounsel`, `BusinessOwner`, `FinanceController`, and `ChiefCounsel`, but two conditions gate it: the actor must be the deviation's `assigned_approver_id` — or hold the `CHIEF_COUNSEL` role, which may step into any review — otherwise `ERR_NOT_ASSIGNED_APPROVER` (HTTP 403), and the parent negotiation's `draft_status` must be `REDLINING` (`ERR_INVALID_STATE_TRANSITION`). Beginning review moves the deviation `OPEN → IN_REVIEW` and increments the negotiation's `version`.

The decision itself is cast with a `decision` of `APPROVE`, `REJECT`, `ESCALATE`, or `ABSTAIN`, an optional `decision_rationale`, and the mandatory optimistic-concurrency field `expected_negotiation_version`. The guards run in the order fixed by §2.8: the deviation must be in a state that permits the decision (`ERR_INVALID_STATE_TRANSITION`); the supplied version must match the negotiation's current `version` (`ERR_STALE_VERSION`); the actor must be the assigned approver and must not be the negotiation's `drafter_user_id`, segregation of duties being absolute (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); the actor's `primary_role` must meet or exceed the deviation's `required_approver_role` on the approver ladder (`ERR_INSUFFICIENT_APPROVER_ROLE`); an `ESCALATE` decision faces the escalatability guard (`ERR_SEVERITY_NOT_ESCATABLE`); and body completeness comes last, with `decision_rationale` required on `REJECT` and `ESCALATE` (`ERR_INVALID_REQUEST`). Every decision persists an `ApprovalDecision` audit row recording the `deviation_id`, the `decided_by_user_id`, the `decision`, the `decision_rationale`, the `decided_at` timestamp, and a `snapshot_clause_version` capturing the clause template's `version` as observed at decision time, so later staleness audits can tell exactly which clause text the approver saw. Decision listings may be filtered by `decided_by_user_id`, and the flat decision collection additionally by `deviation_id`.

Approval moves the deviation `IN_REVIEW → APPROVED`. The server stamps `resolved_at`, computes the deviation's `cycle_time_seconds` as the elapsed seconds from `opened_at` to resolution, decrements the negotiation's `open_deviation_count` and `blocking_deviation_count` by one each, recomputes the approval dimension, and increments the negotiation's `version`. When the count of open deviations thereby falls from above zero to exactly zero with at least one deviation `APPROVED` and none `REJECTED`, the approval dimension settles at `APPROVED_WITH_DEVIATIONS`.

Rejection moves it `IN_REVIEW → REJECTED` with the same resolution stamping and count decrements, but the approval dimension hardens to `BLOCKED`: a rejected deviation is a wall across the deal. The wall comes down only when the drafter withdraws the rejected record, as described below.

Escalation is the third path, and it is deliberately asymmetric. Moving `IN_REVIEW → ESCALATED` requires the same assigned-approver and segregation guards, a mandatory `decision_rationale`, and one extra clause-level gate: a clause whose `deviation_severity_cap` is `LOW` cannot be escalated at all — its deviations must be approved or rejected on the spot, and the attempt is refused with `ERR_SEVERITY_NOT_ESCATABLE` (HTTP 409). A successful escalation records the decision row, sets the deviation's `escalated_to_chief_counsel` flag true, sets its `required_approver_role` to `CHIEF_COUNSEL`, recomputes its `risk_score`, and re-resolves `assigned_approver_id` to the user holding `primary_role` `CHIEF_COUNSEL` with the lowest active deviation load, ties broken in favor of the earliest-created user account. The negotiation's `version` increments; an `ESCALATED` deviation still counts as open and still blocks round advancement.

Once escalated, only the chief can finish it. A `ChiefCounsel` who is the assigned approver — and who is not the drafter — casts `APPROVE` or `REJECT` against the escalated deviation with the same version guard. Approval moves `ESCALATED → APPROVED` with resolution stamping and both count decrements; rejection moves `ESCALATED → REJECTED`, requires `decision_rationale`, decrements both counts, and drives the approval dimension to `BLOCKED`. Each path increments the negotiation's `version`.

Withdrawal belongs to the drafter alone. A `ContractAnalyst` whose user id matches the negotiation's `drafter_user_id` — anyone else hears `ERR_NOT_DRAFTER` — may withdraw a deviation while the negotiation's `draft_status` is `OPEN` or `REDLINING` (`ERR_INVALID_STATE_TRANSITION` beyond that). Withdrawing from `OPEN` or `IN_REVIEW` lands the deviation in `WITHDRAWN`, stamps `resolved_at`, decrements both deviation counts, recomputes the approval dimension, and increments the negotiation's `version`. Withdrawing from `REJECTED` is how a blocked deal gets unstuck: the approval dimension is recomputed and moves from `BLOCKED` to `DEVIATIONS_PENDING` if other open deviations remain, to `NO_DEVIATIONS` if no deviations remain at all, or to `APPROVED_WITH_DEVIATIONS` if only approved deviations remain. The system-driven approval transitions complete the picture: the first deviation created on a negotiation moves `NO_DEVIATIONS → DEVIATIONS_PENDING`; any rejection moves `DEVIATIONS_PENDING → BLOCKED`; and the withdrawal paths above move `BLOCKED` back to `DEVIATIONS_PENDING` or `NO_DEVIATIONS`.

### 3.7. Finalizing Redlining and the Playbook Staleness Guard

When the markup is done, a `LegalCounsel` finalizes redlining, moving the draft dimension `REDLINING → AWAITING_COUNTERSIGN`. Three preconditions guard the move, in this order. The approval dimension must already be settled at `NO_DEVIATIONS` or `APPROVED_WITH_DEVIATIONS` — finalizing with anything still pending or blocked is refused with `ERR_DEVIATIONS_UNRESOLVED` (HTTP 409). The current round must still be `OPEN`, and it is closed as part of this transition with the same stamping as an ordinary round close. And the playbook must not have drifted: the negotiation's `playbook_version_at_pin` must equal the playbook's current `version`, proof that the clause library the deal was measured against is the library as it stands today.

Drift happens — a clause retired or added mid-negotiation bumps the playbook's `version` — and the system offers one deliberate escape hatch. If the finalize request carries `playbook_staleness_override` set to true, the staleness check is waived and the negotiation proceeds against the pinned snapshot it knows; without the override, a drifted playbook is rejected with `ERR_PLAYBOOK_STALE` (HTTP 409). A successful finalize increments the negotiation's `version` and leaves the signature dimension free to begin.

### 3.8. Signature Routing, Execution, and Abort Paths

Execution begins with a signature packet. Once a negotiation stands at `AWAITING_COUNTERSIGN` — any earlier draft state is an `ERR_INVALID_STATE_TRANSITION` — a `LegalCounsel` creates the packet with an ordered `signatories` array, each entry naming a `user_id`, its `order_index` in the routing sequence, and an `authority_cap_cents` ceiling; a `signature_window_opens_at` and `signature_window_closes_at` bracketing the valid signing interval, with the close strictly later than the open; and the mandatory `expected_negotiation_version`, rejected with `ERR_STALE_VERSION` when it no longer matches. Only one packet may be live at a time: an existing packet in `ROUTING`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED` blocks creation of another with `ERR_SIGNATURE_PACKET_ALREADY_ACTIVE`. The new packet starts in `ROUTING` with an empty `signed_record`, the negotiation's signature dimension moves `NOT_STARTED → ROUTING`, and the negotiation's `version` increments.

Signing is sequential and triple-guarded, with the guards evaluated in this order. First, authority: the signing user's `can_sign_above_cents` must be strictly greater than the negotiation's `contract_value_cents` — equality fails — else `ERR_SIGNATORY_AUTHORITY_EXCEEDED`. Second, the window: the current logical time must fall within the closed interval from `signature_window_opens_at` to `signature_window_closes_at`, else `ERR_SIGNATURE_WINDOW_VIOLATION`. Third, order: the signer must be the signatory at the smallest `order_index` not yet present in `signed_record`, else `ERR_SIGNATORY_OUT_OF_ORDER`. Each accepted signature appends an entry of `user_id`, `signed_at`, and `signature_hash` — the latter a SHA-256 hash over the concatenation of the signer's user identifier and the signing timestamp — to the packet's append-only `signed_record`. The first signature moves the packet `ROUTING → PARTIALLY_SIGNED`; middle signatures hold it at `PARTIALLY_SIGNED`; and the signature that completes coverage of every listed signatory moves it `PARTIALLY_SIGNED → FULLY_SIGNED` and lifts the negotiation's signature dimension to `FULLY_SIGNED`.

Two ways out exist before execution. A `LegalCounsel` may void a packet only while its `signed_record` is still empty — once any signature has landed, voiding is refused with `ERR_SIGNATURE_ALREADY_STARTED` — moving the packet to `VOIDED` and returning the negotiation's signature dimension to `NOT_STARTED`. And time itself voids: when the logical clock advances past `signature_window_closes_at` without completion, a packet in `ROUTING` or `PARTIALLY_SIGNED` moves automatically to `EXPIRED`, and the negotiation's signature dimension likewise returns to `NOT_STARTED`, freeing counsel to cut a fresh packet.

Recording execution is the deal's finish line, performed by a `Signatory`. The packet must stand at `FULLY_SIGNED` — anything less is `ERR_SIGNATURE_INCOMPLETE` — the supplied `execution_timestamp` must fall within the signature window (`ERR_SIGNATURE_WINDOW_VIOLATION`), and every signer in `signed_record` is re-verified for authority, each `can_sign_above_cents` strictly greater than the final `contract_value_cents` (`ERR_SIGNATORY_AUTHORITY_EXCEEDED`). Success is a wide cascade: the packet moves to `EXECUTION_RECORDED`; the negotiation's draft dimension moves `AWAITING_COUNTERSIGN → EXECUTED` and its signature dimension to `EXECUTION_RECORDED`; `cycle_time_seconds` is computed as the execution timestamp minus the negotiation's `created_at`, in seconds; the counterparty's `last_executed_at` is set to the execution timestamp; the counterparty's and playbook's `active_negotiation_count` each decrement by one; obligation extraction runs (§3.9); and the negotiation's `version` increments.

Abort remains available until the ink is final. From `AWAITING_COUNTERSIGN`, a `LegalCounsel` may abort only while no packet has reached `FULLY_SIGNED` or `EXECUTION_RECORDED` — a signed deal cannot be un-signed, and the attempt is refused with `ERR_SIGNATURE_ALREADY_FINAL`. A permitted abort voids every packet in `ROUTING` or `PARTIALLY_SIGNED`, decrements both active-negotiation counters, increments the negotiation's `version`, and settles the draft dimension at terminal `ABORTED` with approval and signature frozen. Packet listings may be filtered by `status`, and the flat packet collection additionally by `negotiation_id`.

### 3.9. Obligation Extraction and Negotiation Analytics

Execution is not the end of the work; it is the start of the commitments. When execution is recorded, the server extracts one `Obligation` per `APPROVED` deviation and one per clause template used as standard text with no deviation created. Each obligation records its `negotiation_id` and `clause_template_id`, the `obligation_text` — the final approved text, whether standard, fallback, or approved non-standard — and an `extraction_source` marking which: `STANDARD_TEXT` for an undeviated clause, `FALLBACK_POSITION` for an approved deviation whose severity was `FALLBACK`, or `APPROVED_DEVIATION` for one whose severity was `NON_STANDARD`. An `owner_role` of `BUSINESS_OWNER`, `LEGAL_COUNSEL`, or `FINANCE_CONTROLLER` is assigned from the clause's category, and `extracted_at` is stamped from the logical clock.

Maturity is arithmetic, not judgment. The obligation's `due_offset_days` — supplied as input — counts days forward from the intake request's `effective_date`, and the `due_date` is exactly that many 86,400-second days after the effective date, stored at second precision. One clamp applies: for a clause whose category is `REGULATORY`, the due date is capped at a maximum of thirty days after the effective date regardless of the offset supplied. Obligation listings — nested under the negotiation or flat — may be filtered by `owner_role`, `extraction_source`, `clause_template_id`, and, on the flat collection, `negotiation_id`.

Analytics close the loop, and both reports are restricted to `LegalCounsel`, `FinanceController`, `ChiefCounsel`, and `OpsAdmin`. The cycle-time report takes a required `from_iso` and `to_iso` bracketing a half-open window — inclusive of the start instant, exclusive of the end — plus an optional `contract_type_id` filter and an optional `cohort` selector. For a single negotiation, cycle time is the execution timestamp minus `created_at`, in integer seconds. The default cohort is every negotiation whose draft dimension is `EXECUTED` and whose execution instant falls inside the window, optionally narrowed to one contract type. Percentiles use the nearest-rank method: sort the cohort's cycle times ascending, take the rank as the ceiling of the percentile divided by 100 and multiplied by the cohort size, and pick the value at that one-based rank — an empty cohort yields null. The report returns `cohort_size`, `p50_seconds`, `p90_seconds`, `p99_seconds`, and `mean_seconds`. The alternate cohort scopes the same math to negotiations still in flight — those whose draft dimension is neither `EXECUTED` nor `ABORTED` — measured provisionally as the current server time minus `created_at`; aborted negotiations are excluded from all percentile math in either cohort.

The bottleneck report takes the same `from_iso`, `to_iso`, and optional `contract_type_id` window and attributes consumed time to the phase that consumed it. `legal_review_seconds` sums, over every deviation resolved within the window that was never escalated, the seconds from `opened_at` to `resolved_at`. `escalated_seconds` sums the same span over deviations whose `escalated_to_chief_counsel` flag is true. `drafter_rework_seconds` sums `round_duration_seconds` over the rounds that produced at least one deviation — those with `clause_change_count` greater than zero. `signature_wait_seconds` sums, over packets that reached `EXECUTION_RECORDED`, the seconds from `signature_window_opens_at` to the last `signed_at` in the record. The phase holding the strictly greatest total is reported as `primary_bottleneck`; ties are broken in the fixed order `escalated_seconds`, then `legal_review_seconds`, then `drafter_rework_seconds`, then `signature_wait_seconds`.

## 4. Endpoint Definitions

Operations that create a new resource — a playbook, clause template, contract type, counterparty, user, intake request, negotiation, round, deviation, or signature packet — return `201 Created`. Operations that modify an existing resource or drive a state transition — publish, deprecate, retire, triage, reject, cancel, close, finalize, abort, begin-review, decide, withdraw, sign, record-execution, void — together with all reads, return `200 OK`. Endpoints marked "All roles" admit any of the seven roles defined in §2.1. Request bodies, side effects, and preconditions are specified in the §3 narratives referenced by each description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | OpsAdmin |
| POST | `/playbooks` | Create a Playbook in `DRAFT` | ChiefCounsel, OpsAdmin |
| GET | `/playbooks` | List Playbooks | All roles |
| GET | `/playbooks/{playbookId}` | Get a Playbook | All roles |
| POST | `/playbooks/{playbookId}/publish` | Publish a Playbook (`DRAFT → ACTIVE`) | ChiefCounsel |
| POST | `/playbooks/{playbookId}/deprecate` | Deprecate a Playbook | ChiefCounsel |
| GET | `/playbooks/{playbookId}/clauses` | List ClauseTemplates under a Playbook | All roles |
| POST | `/playbooks/{playbookId}/clauses` | Create a ClauseTemplate under a Playbook | ChiefCounsel |
| GET | `/playbooks/{playbookId}/clauses/{clauseId}` | Get a ClauseTemplate | All roles |
| POST | `/playbooks/{playbookId}/clauses/{clauseId}/retire` | Retire a ClauseTemplate | ChiefCounsel |
| POST | `/contract-types` | Create a ContractType | OpsAdmin |
| GET | `/contract-types` | List ContractTypes | All roles |
| GET | `/contract-types/{typeId}` | Get a ContractType | All roles |
| POST | `/contract-types/{typeId}/retire` | Retire a ContractType | OpsAdmin |
| POST | `/counterparties` | Create a Counterparty | OpsAdmin, ContractAnalyst |
| GET | `/counterparties` | List Counterparties | All roles |
| GET | `/counterparties/{counterpartyId}` | Get a Counterparty | All roles |
| POST | `/users` | Create a User | OpsAdmin |
| GET | `/users` | List Users | All roles |
| GET | `/users/{userId}` | Get a User | All roles |
| POST | `/intake-requests` | Submit an intake request for triage | ContractAnalyst, BusinessOwner |
| GET | `/intake-requests` | List IntakeRequests | All roles |
| GET | `/intake-requests/{intakeRequestId}` | Get an IntakeRequest | All roles |
| POST | `/intake-requests/{intakeRequestId}/triage` | Run triage; create TriageDecision and route | ContractAnalyst |
| GET | `/intake-requests/{intakeRequestId}/triage-decisions` | List TriageDecisions for an IntakeRequest | All roles |
| POST | `/intake-requests/{intakeRequestId}/reject` | Reject an intake request at triage | ContractAnalyst |
| POST | `/intake-requests/{intakeRequestId}/cancel` | Cancel an intake request | ContractAnalyst |
| POST | `/intake-requests/{intakeRequestId}/open-negotiation` | Open a Negotiation from a `ROUTED` intake | ContractAnalyst |
| GET | `/negotiations` | List Negotiations | All roles |
| GET | `/negotiations/{negotiationId}` | Get a Negotiation | All roles |
| POST | `/negotiations/{negotiationId}/rounds` | Open a new NegotiationRound | ContractAnalyst |
| GET | `/negotiations/{negotiationId}/rounds` | List NegotiationRounds of a Negotiation | All roles |
| GET | `/negotiations/{negotiationId}/rounds/{roundId}` | Get a NegotiationRound | All roles |
| POST | `/negotiations/{negotiationId}/rounds/{roundId}/close` | Close a round (requires no blocking deviations) | ContractAnalyst |
| POST | `/negotiations/{negotiationId}/finalize-redlining` | Finalize redlining; move to `AWAITING_COUNTERSIGN` | LegalCounsel |
| POST | `/negotiations/{negotiationId}/abort` | Abort a negotiation in any non-terminal state | ContractAnalyst, LegalCounsel |
| POST | `/negotiations/{negotiationId}/deviations` | Record a deviation against the playbook | ContractAnalyst, LegalCounsel |
| GET | `/negotiations/{negotiationId}/deviations` | List Deviations for a Negotiation | All roles |
| GET | `/negotiations/{negotiationId}/deviations/{deviationId}` | Get a Deviation | All roles |
| POST | `/negotiations/{negotiationId}/deviations/{deviationId}/begin-review` | Begin review on an `OPEN` deviation | LegalCounsel, BusinessOwner, FinanceController, ChiefCounsel |
| POST | `/negotiations/{negotiationId}/deviations/{deviationId}/decide` | Cast an approval decision (`APPROVE`/`REJECT`/`ESCALATE`) | LegalCounsel, BusinessOwner, FinanceController, ChiefCounsel |
| GET | `/negotiations/{negotiationId}/deviations/{deviationId}/decisions` | List ApprovalDecisions for a Deviation | All roles |
| POST | `/negotiations/{negotiationId}/deviations/{deviationId}/withdraw` | Drafter withdraws a deviation | ContractAnalyst |
| POST | `/negotiations/{negotiationId}/signature-packets` | Create a SignaturePacket | LegalCounsel |
| GET | `/negotiations/{negotiationId}/signature-packets` | List SignaturePackets of a Negotiation | All roles |
| GET | `/negotiations/{negotiationId}/signature-packets/{packetId}` | Get a SignaturePacket | All roles |
| POST | `/negotiations/{negotiationId}/signature-packets/{packetId}/sign` | Signatory signs the packet | Signatory |
| POST | `/negotiations/{negotiationId}/signature-packets/{packetId}/record-execution` | Record execution after all signatories signed | Signatory |
| POST | `/negotiations/{negotiationId}/signature-packets/{packetId}/void` | Void an unsigned packet | LegalCounsel |
| GET | `/negotiations/{negotiationId}/obligations` | List Obligations extracted from a Negotiation | All roles |
| GET | `/clauses` | List ClauseTemplates (flat) | All roles |
| GET | `/clauses/{clauseId}` | Get a ClauseTemplate by id (flat) | All roles |
| GET | `/triage-decisions` | List TriageDecisions (flat) | All roles |
| GET | `/triage-decisions/{triageDecisionId}` | Get a TriageDecision by id (flat) | All roles |
| GET | `/rounds` | List NegotiationRounds (flat) | All roles |
| GET | `/rounds/{roundId}` | Get a NegotiationRound by id (flat) | All roles |
| GET | `/deviations` | List Deviations (flat) | All roles |
| GET | `/deviations/{deviationId}` | Get a Deviation by id (flat) | All roles |
| GET | `/approval-decisions` | List ApprovalDecisions (flat) | All roles |
| GET | `/approval-decisions/{decisionId}` | Get an ApprovalDecision by id (flat) | All roles |
| GET | `/signature-packets` | List SignaturePackets (flat) | All roles |
| GET | `/signature-packets/{packetId}` | Get a SignaturePacket by id (flat) | All roles |
| GET | `/obligations` | List Obligations (flat) | All roles |
| GET | `/obligations/{obligationId}` | Get an Obligation | All roles |
| GET | `/analytics/cycle-time` | Cycle-time percentiles across executed negotiations | LegalCounsel, FinanceController, ChiefCounsel, OpsAdmin |
| GET | `/analytics/bottlenecks` | Bottleneck attribution across phases | LegalCounsel, FinanceController, ChiefCounsel, OpsAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the §2 and §3 narratives where the guarded workflow lives; this table is the canonical identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_USER_NOT_FOUND` | 401 Unauthorized |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FOREIGN_KEY_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_PLAYBOOK_EMPTY` | 409 Conflict |
| `ERR_PLAYBOOK_NO_ACTIVE_CLAUSES` | 409 Conflict |
| `ERR_PLAYBOOK_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAYBOOK_IN_USE` | 409 Conflict |
| `ERR_PLAYBOOK_STALE` | 409 Conflict |
| `ERR_CLAUSE_HAS_OPEN_DEVIATIONS` | 409 Conflict |
| `ERR_CONTRACT_TYPE_IN_USE` | 409 Conflict |
| `ERR_CONTRACT_TYPE_INACTIVE` | 409 Conflict |
| `ERR_THRESHOLDS_NOT_MONOTONIC` | 422 Unprocessable Entity |
| `ERR_COUNTERPARTY_SANCTIONED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DEVIATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_FALLBACK_INDEX_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE` | 409 Conflict |
| `ERR_DEVIATIONS_UNRESOLVED` | 409 Conflict |
| `ERR_ROUND_ALREADY_OPEN` | 409 Conflict |
| `ERR_NOT_ASSIGNED_APPROVER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_INSUFFICIENT_APPROVER_ROLE` | 403 Forbidden |
| `ERR_NOT_DRAFTER` | 403 Forbidden |
| `ERR_SEVERITY_NOT_ESCATABLE` | 409 Conflict |
| `ERR_SIGNATORY_OUT_OF_ORDER` | 409 Conflict |
| `ERR_SIGNATORY_AUTHORITY_EXCEEDED` | 403 Forbidden |
| `ERR_SIGNATURE_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_SIGNATURE_INCOMPLETE` | 409 Conflict |
| `ERR_SIGNATURE_ALREADY_STARTED` | 409 Conflict |
| `ERR_SIGNATURE_ALREADY_FINAL` | 409 Conflict |
| `ERR_SIGNATURE_PACKET_ALREADY_ACTIVE` | 409 Conflict |

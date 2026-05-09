# Flight Delay Claims API — Product Requirements Document

## 1. Introduction

Aviation passengers buy travel-disruption insurance precisely so that nothing about a six-hour delay or a same-day cancellation should require them to file paperwork; in the world this product targets, claims are born from event streams, not from passenger phone calls. This document specifies the back-office system that an insurer operates to ingest multi-source flight status feeds (airline, airport, aviation-authority), reconcile them into authoritative flight outcomes, automatically match passengers to policy holders, evaluate eligibility under complex policy clauses (delay-cause exclusions, waiting periods, basis of measurement), compute tiered or actual-loss compensation, and finally dispatch payouts in batches that respect segregation of duties, reinsurance arrangements, and reserve accounting.

The product is mounted under the URL prefix `/insurers` and operates as a single-tenant API per insurer. Every entity is scoped to its parent insurer and inherits the test-driven logical clock that simulates real-time progression. The benchmark is intentionally designed so that an implementer who reads only this document — and never the underlying scaffold — can reconstruct the full behavioural specification: monetary precision, parallel-axis state machines, multi-source quorum tie-breaks, two-variant calculations, reinsurance waterfalls, and audit obligations all live in the prose below rather than in any structured table.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (other than the unauthenticated health probe) carries two HTTP headers: `X-User-ID` identifying the calling principal, and `X-User-Role` identifying the role under which the call is made. If either header is missing or empty the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is well-formed but does not have authority to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The roles recognised by this system are exactly: `ClaimsAdmin`, `PolicyAdmin`, `ClaimsReviewer`, `ClaimsApprover`, `BatchApprover`, `BatchExecutor`, `PayoutOperator`, `Auditor`, `system`, and `Any`. The pseudo-role `Any` is the authenticated read-only fallback used by GET endpoints that any authenticated principal may invoke. The pseudo-role `system` is the automated actor used internally for sweeps, quorum-driven flight transitions, and the auto-transition of payout batches into `SETTLED`.

All ten roles use opaque user identifiers — that is, when `X-User-Role` is `ClaimsAdmin`, `PolicyAdmin`, `ClaimsReviewer`, `ClaimsApprover`, `BatchApprover`, `BatchExecutor`, `PayoutOperator`, `Auditor`, `system`, or `Any`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records it where a state-machine transition explicitly demands it (for example, as `assigned_reviewer_id`, `assigned_approver_id`, `payout_operator_id`, `assigned_batch_approver_id`, or `assigned_batch_executor_id`) but does not compare it against any entity's `id`.

Segregation of duties is enforced even when a role check passes: a claim's reviewer cannot also approve it; a claim's approver cannot also be the payout operator who settles it; a per-claim approver cannot serve as the batch approver for a batch containing that claim; and a batch approver cannot also be the batch executor for the same batch. Any caller whose `X-User-ID` would breach one of these prohibitions is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and accepts any non-negative integer. List results are sorted by `created_at` in ascending order. The `meta` object on a list response carries `limit`, `offset`, `total_count` (the total number of rows the filter would yield ignoring pagination), and `has_more` (true when more pages remain after the current one).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries an `id` that is a server-minted UUID without a type prefix and a `created_at` timestamp recorded as ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (refreshed on every mutation) and an integer `version` field that begins at 1 and increments by exactly 1 on every successful mutation. The append-only entities — `FlightStatusEvent`, `ReinsuranceAllocation`, `ReserveAdjustment`, `AuditLog`, and `OutboxEvent` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from their representations because these rows are never modified after creation.

Mutating endpoints accept an optional `version` field in the request body. When the caller supplies a `version`, the server compares it to the resource's current `version` before applying the change; on mismatch the request is rejected with `ERR_INVALID_STATE` (HTTP 409). When the caller omits `version`, the optimistic-concurrency check is skipped and the change is applied unconditionally. After a successful mutation the `version` is incremented and `updated_at` is refreshed.

### 2.5. Hierarchical Path Resolution and Tenant Scoping

Resources are accessed through nested URL paths anchored at an insurer (`/insurers/{insurerId}/...`). Path parameters are validated strictly left-to-right: the insurer must exist before the policy is checked, the policy before the claim, and so on. The first parameter in the chain that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404). Every body-referenced foreign key (`policy_id`, `ticket_id`, `flight_id`, `claim_id`, `resolved_policy_id`) must reside within the same insurer; cross-tenant references are also rejected with `ERR_NOT_FOUND`. Malformed bodies — missing required fields, type errors, negative durations — return `ERR_INVALID_REQUEST` (HTTP 400).

Validation order is fixed and deterministic: header presence first (priority 1), then RBAC (priority 2), then path-parameter existence (priority 3), then body-referenced existence (priority 4), then segregation of duties (priority 5, deliberately placed before state checks because SoD is a regulatory hard-stop), then state guards (priority 6), then cross-entity preconditions such as flight finalization, policy activeness, and batch approval (priority 7), then waiting period (priority 8), then delay-cause exclusion (priority 9), then below-threshold delay (priority 10), then quota exhaustion (priority 11), then ticket binding status (priority 12), then event idempotency (priority 13), then same-flight batching (priority 14), then reserve invariant integrity (priority 15). When more than one rule could fire, the lower priority number takes precedence.

### 2.6. Monetary Precision and Time Representation

All monetary fields are stored as integer cents in the insurer's `currency` (an ISO-4217 code such as EUR or USD). Cent values never round in display; intermediate arithmetic that produces fractional cents is truncated by floor (i.e., the integer part discarding the remainder), and any explicit residue produced by pro-ration is allocated by the rules described in §3 rather than left as a rounding error. The reinsurance waterfall is exact and performs no rounding at all.

Time is represented in two complementary forms. ISO 8601 UTC strings (with three fractional digits) carry `created_at` and `updated_at`. Domain time — flight schedules, ticket boundaries, policy effective windows, the simulated clock — is carried as integer epoch milliseconds in fields named `..._epoch_ms`. The simulated clock is `Insurer.now_epoch_ms`, which begins at 0 on insurer creation and only advances when a `ClaimsAdmin` calls the test-clock advance capability with either `delta_ms` (a non-negative increment) or `to_epoch_ms` (an absolute target). No other operation moves the clock.

The root tenant entity is the insurer itself, created with a display `name` and a `currency` (the ISO-4217 code). On insurer creation, the system initialises both `now_epoch_ms` and `total_outstanding_reserve_cents` to zero.

### 2.7. Multi-Source Flight Status Quorum and Cause Classification

Flight status feeds arrive from three independent sources: `AIRLINE`, `AIRPORT`, and `AVIATION_AUTHORITY`. Each `FlightStatusEvent` carries a `source`, a `source_event_id` (the originating system's idempotency key), a `reported_status` drawn from `ON_TIME`, `DELAYED`, `CANCELLED`, `DIVERTED`, or `RETURNED`, optional `reported_actual_departure_epoch_ms` and `reported_actual_arrival_epoch_ms` timestamps, an optional `reported_cause` drawn from `WEATHER`, `ATC`, `SECURITY`, `AIRLINE`, or `OTHER`, the source's wall-clock `report_epoch_ms`, and the `ingested_epoch_ms` that the server stamps from `Insurer.now_epoch_ms` when the row is recorded. The triple `(insurer_id, source, source_event_id)` is unique; a duplicate event is rejected with `ERR_DUPLICATE_EVENT` (HTTP 409).

Quorum is evaluated whenever a new event is ingested for a flight whose `status` is `SCHEDULED` or `ACTIVE`. Group the events whose `ingested_epoch_ms` falls within the most recent event's quorum window — that window has a length of 30 minutes — by their `reported_status`. A quorum exists for a particular reported status when at least two distinct sources report it, and at least one of those distinct sources is `AIRLINE` or `AVIATION_AUTHORITY`. When two reported-status values both reach quorum simultaneously, the system prefers whichever quorum-completing event has the larger `ingested_epoch_ms`; if those are equal, the most-disruptive status wins, where the disruption ordering is `CANCELLED` first, then `DIVERTED`, then `RETURNED`, then `LANDED`, then `ON_TIME`.

Once a flight reaches a terminal state, the system computes its `classified_cause` from the events that contributed to the quorum. Tally the `reported_cause` values, treating any null `reported_cause` as `OTHER`, and pick the mode (the most-frequent value). Ties are broken first by source priority — `AVIATION_AUTHORITY` outranks `AIRPORT`, which outranks `AIRLINE` — and then, among the tied highest-priority sources, by the latest `ingested_epoch_ms`. The result is recorded on the flight as `classified_cause`.

### 2.8. Reserve Accounting Principle

Each policy carries a `reserve_balance_cents` figure that captures the optimistic exposure: the sum of `estimated_payout_cents` over claims whose `payout_status` is `PAYABLE` or `EXECUTING` and whose `review_status` is `APPROVED`. Approval debits the reserve; settlement releases it; reversal rebuilds it. Each adjustment is journaled into an immutable `ReserveAdjustment` ledger entry whose `delta_cents` is signed (positive on debit, negative on release) and whose `balance_after_cents` records the policy's `reserve_balance_cents` after the adjustment is applied; the `reason` enum on the entry takes one of `APPROVE_DEBIT`, `SETTLE_RELEASE`, `REJECT_RELEASE`, or `REVERSE_REBUILD`. The insurer-level rollup `total_outstanding_reserve_cents` is the sum of `reserve_balance_cents` across all `ACTIVE` policies of the insurer.

A pessimistic view of the same exposure is exposed as a separate read-only computation that includes claims whose `review_status` is `UNDER_REVIEW` (and whose `payout_status` is not `PAID`) in addition to the optimistic set. Whenever a policy has at least one `UNDER_REVIEW` claim with a computed gross payout, the pessimistic figure exceeds the optimistic figure; when every in-flight claim is already `APPROVED`, the two are equal. The pessimistic value is never persisted.

The reserve invariant — that `Policy.reserve_balance_cents` equals the sum of `estimated_payout_cents` over the `PAYABLE`-or-`EXECUTING`-and-`APPROVED` claim set — must hold at all times. A drift between the stored value and the recomputed value is reported as `ERR_RESERVE_DRIFT` (HTTP 409) when integrity is checked.

### 2.9. Idempotency, Concurrency, and Saga Discipline

The payout pipeline is a saga: a claim's reserve is debited at approval, the banking dispatch is emitted at execution, the reserve is released at settlement, and reversal compensates by rebuilding both reserve and quota. Concurrent operations on the same resource serialize first-writer-wins. Two simultaneous reviews or approvals on the same claim, or an approve-and-reject race, resolve to a single transition and the loser receives `ERR_INVALID_STATE` (HTTP 409) on observing the new state. Two simultaneous dispatches on the same payout batch resolve to one entry into `EXECUTING`, and the loser receives `ERR_BATCH_ALREADY_DISPATCHED` (HTTP 409). Two concurrent ingests of the same `(insurer_id, source, source_event_id)` triple persist exactly one event; the duplicate is rejected idempotently with `ERR_DUPLICATE_EVENT` (HTTP 409). Two concurrent settlements of the same claim release the reserve exactly once; the second receives `ERR_INVALID_STATE` (HTTP 409). When a claim approval races a parent-policy termination, whichever transaction wins on `Policy.status` is the survivor: if the policy reaches `TERMINATED` first, the approve attempt is rejected with `ERR_POLICY_INACTIVE` (HTTP 409); otherwise the approve commits. Two concurrent resolutions of the same `ManualReviewCase` serialize so that exactly one wins; the loser receives `ERR_INVALID_STATE` (HTTP 409).

### 2.10. Audit Trail and Outbox

Every state change, payout record, reserve adjustment, and downstream event emission is journalled into the immutable `AuditLog`. Each entry carries a `subject_type` enum (`CLAIM`, `PAYOUT_BATCH`, `POLICY`, or `FLIGHT`), a `subject_id`, an `action` (`STATUS_CHANGE`, `PAYOUT_RECORDED`, `RESERVE_ADJUSTED`, or `EXTERNAL_EVENT_EMITTED`), the `actor_role` (one of the roles named in §2.1, or `system`), the `actor_id` (an opaque user identifier), and a `details` JSON object with the from/to states, monetary amounts, or other contextual data.

Downstream synchronisation is performed through an outbox. Each `OutboxEvent` carries a `target_system` (`PAYMENT`, `BANKING`, `AIRLINE`, or `POLICY_ADMIN`), a string `event_type` such as `CLAIM_PAID`, `BATCH_DISPATCHED`, or `RESERVE_RELEASED`, a `subject_type` and `subject_id` referencing the originating domain entity, an arbitrary `payload`, and a `dispatch_status` of `PENDING`, `DELIVERED`, or `FAILED`. External systems acknowledge delivery via the mark-delivered capability, which transitions a `PENDING` event to `DELIVERED` idempotently.

## 3. Business Logic & Workflows

### 3.1. Policy Lifecycle and Coverage Configuration

A `PolicyAdmin` (or a `ClaimsAdmin`) creates a policy by supplying the `policy_holder_name` and `policy_holder_doc_id` (the travel-document identifier that ticket-matching keys off), the inclusive coverage start `effective_from_epoch_ms` and the exclusive coverage end `effective_to_epoch_ms` (which must be strictly greater than `effective_from_epoch_ms`), an optional `waiting_period_ms` (the gap between coverage start and the ticket's scheduled departure, defaulting to 0), the `delay_basis` (which pins whether eligibility and tiering measure delay against scheduled departure or scheduled arrival, taking the value `DEPARTURE` or `ARRIVAL`), the `payout_mode` (`FIXED` for the tier-table compensation or `ACTUAL_LOSS` for proportional reimbursement), an optional `reimbursement_rate_bps` in basis points (defaulting to 0; ignored when `payout_mode` is `FIXED`), an optional `deductible_cents` applied once per claim (defaulting to 0), the `policy_limit_cents` ceiling on net payout per claim, the `claim_quota_total_cents` lifetime aggregate quota for paid claims under this policy, and an optional `excluded_delay_causes` array drawn from `WEATHER`, `ATC`, `SECURITY`, `AIRLINE`, and `OTHER`.

A new policy starts with `status` set to `ACTIVE` and with `claim_quota_used_cents` and `reserve_balance_cents` initialised to zero. The two stored balances are kept in lockstep with claim-state changes, and the never-negative invariant `claim_quota_used_cents <= claim_quota_total_cents` must hold at all times. A `PolicyAdmin` can suspend the policy (transitioning `status` to `SUSPENDED`, supplying a `reason` in the request body) so that no new claim approvals are admitted, or terminate it (transitioning `status` to `TERMINATED`). When an approval attempt finds the parent policy in `SUSPENDED` or `TERMINATED`, the request is rejected with `ERR_POLICY_INACTIVE` (HTTP 409).

The pessimistic risk view is a read-only computation over a single policy: it returns three values — the `optimistic_reserve_cents` (matching the stored `reserve_balance_cents`), the `pessimistic_reserve_cents` (the variant that also counts `UNDER_REVIEW` claims as exposure), and the `claim_quota_remaining_cents` (the difference between `claim_quota_total_cents` and `claim_quota_used_cents`).

### 3.2. Flight Records and Multi-Source Status Reconciliation

A flight record is born when a `ClaimsAdmin` or `PolicyAdmin` registers it with the airline's `carrier_code` (the IATA code such as LH), the `flight_number`, the IATA `origin_airport` and `destination_airport`, and the immutable scheduled times `scheduled_departure_epoch_ms` and `scheduled_arrival_epoch_ms`. The combination `(insurer_id, carrier_code, flight_number, scheduled_departure_epoch_ms)` is unique within an insurer. A new flight begins with `status` of `SCHEDULED`. List queries against the flight collection accept the optional filters `carrier_code`, `flight_number`, `status`, and `scheduled_departure_after_epoch_ms`.

The system automatically advances a flight from `SCHEDULED` to `ACTIVE` when the simulated clock first reaches the scheduled-departure boundary minus thirty minutes — that is, when `Insurer.now_epoch_ms` is at least `scheduled_departure_epoch_ms - 1800000` — provided no terminal-status event has yet been ingested for the flight. This advance is evaluated by the system sweep capability rather than synchronously on every clock tick.

A flight finalises when the multi-source quorum described in §2.7 is reached for one of `LANDED`, `CANCELLED`, `DIVERTED`, or `RETURNED`. From either `SCHEDULED` or `ACTIVE`, an `ON_TIME` or `DELAYED` quorum-bearing event drives the flight into `LANDED` (with `actual_arrival_epoch_ms` set to the agreed actual arrival from the quorum events); a `CANCELLED` event drives it into `CANCELLED` (with both `actual_departure_epoch_ms` and `actual_arrival_epoch_ms` set to null, treated as an infinite delay sentinel); a `DIVERTED` event from `ACTIVE` drives it into `DIVERTED` (with `actual_arrival_epoch_ms` set to the diverted-airport arrival); a `RETURNED` event from `ACTIVE` drives it into `RETURNED` (with `actual_arrival_epoch_ms` set to the return-to-origin arrival). Every terminal transition computes the `classified_cause` per §2.7 and triggers a recomputation of segment eligibility for every ticket bound to the flight.

A finalised flight may be archived by a `ClaimsAdmin` (or by the system sweep, when `Insurer.now_epoch_ms - scheduled_arrival_epoch_ms` exceeds 90 days). Archive is permitted only if no claim referencing the flight is in `PENDING_MATCH`, `MATCHED`, `UNDER_REVIEW`, or `APPROVED` review status. On success, `archived_at_epoch_ms` is stamped from `Insurer.now_epoch_ms` and the flight transitions to `ARCHIVED`. The single archival precondition applies uniformly to flights coming from `LANDED`, `CANCELLED`, `DIVERTED`, or `RETURNED`.

### 3.3. Tickets, Auto-Matching, and Manual Review

A `PolicyAdmin` ingests tickets one at a time. Required input is the `passenger_name` as printed, the `passenger_doc_id` used for matching, the `pnr_code` booking record locator, and the `flight_id` of an existing flight in the same insurer; the optional `policy_id` short-circuits auto-matching and binds directly. Without an explicit `policy_id`, the system performs auto-matching: if exactly one `ACTIVE` policy in the insurer has `policy_holder_doc_id` equal to `passenger_doc_id`, the ticket is bound to that policy with `status` set to `ATTACHED` and `scheduled_departure_epoch_ms` and `scheduled_arrival_epoch_ms` snapshotted from the flight. If no policy matches, the ticket is recorded with `status` set to `UNMATCHED` and a `ManualReviewCase` is opened with `failure_reason` set to `NO_POLICY_FOUND`. If more than one policy matches, the ticket is recorded with `status` set to `UNMATCHED` and a `ManualReviewCase` is opened with `failure_reason` set to `DUPLICATE_BINDING`. Other recognised values for `failure_reason` include `DOC_ID_MISMATCH`, `NAME_MISMATCH`, and `POLICY_INACTIVE`. Ticket uniqueness is enforced on the pair `(insurer_id, pnr_code)` whenever the ticket's `status` is `ATTACHED` or `CHANGED`; a duplicate is rejected with `ERR_DUPLICATE_PNR` (HTTP 409). When a referenced flight does not exist within the insurer, the ingest is rejected with `ERR_FLIGHT_NOT_FOUND` (HTTP 404).

A passenger whose itinerary changes is captured by the `ATTACHED → CHANGED` revision: the `PolicyAdmin` provides a new `flight_id` and the ticket re-snapshots its scheduled departure and scheduled arrival from the new flight; this fails with `ERR_FLIGHT_NOT_FOUND` if the new flight cannot be resolved, and with `ERR_TICKET_LOCKED_BY_CLAIM` if any claim referencing the ticket is currently in `UNDER_REVIEW` or `APPROVED` review status. A subsequent confirm operation by the same role transitions the ticket back from `CHANGED` to `ATTACHED` with no further side effects, allowing multiple change-confirm rounds. A refund operation by a `PolicyAdmin` drives the ticket from `ATTACHED` (or `CHANGED`) into `REFUNDED`, and is rejected with `ERR_TICKET_LOCKED_BY_CLAIM` if a claim referencing this ticket is in `APPROVED`, `EXECUTING`, or `PAID`. When a refund succeeds and the ticket was in `ATTACHED`, any claim referencing it that is still in early review drives that claim's `review_status` to `REJECTED` with `rejection_reason` set to `DUPLICATE`; refunds from `CHANGED` perform no such cascade. A ticket may also drift to `UNMATCHED` automatically at ingest when the passenger document does not match any active policy, in which case a `ManualReviewCase` records the failure.

A `ClaimsReviewer` resolves manual-review cases. The case carries an `assigned_reviewer_id` (an opaque user identifier), the originating `ticket_id`, the `failure_reason` enum noted above, and an optional `candidate_policy_ids` array suggesting partial matches for reviewer reference. Each case begins in `OPEN`. The bind resolution accepts a chosen `resolved_policy_id` and, if that policy is `ACTIVE`, binds the ticket to it (the ticket's `policy_id` becomes `resolved_policy_id` and `status` settles to `ATTACHED`); the case transitions to `RESOLVED_BIND`, and any claim that references this ticket and is still pending its match advances to `MATCHED`. If the chosen policy is `SUSPENDED` or `TERMINATED`, bind is rejected with `ERR_POLICY_INACTIVE`. The reject resolution transitions the case to `RESOLVED_REJECT`, drives the ticket to `UNMATCHED`, and rejects any pending claim referencing this ticket (`review_status` to `REJECTED`, `rejection_reason` set to `MATCHING_FAILED`). The bind resolution additionally requires that the ticket's status is in `ATTACHED` or `CHANGED`. Concurrent resolutions on the same case serialize first-writer-wins; the loser receives `ERR_INVALID_STATE`.

### 3.4. Claim Creation, Matching, and the Two-Axis Lifecycle

A claim covers one or more tickets under a single policy. A `ClaimsReviewer` or `PolicyAdmin` creates the claim by submitting `ticket_ids` — at least one entry, all referencing the same parent policy. On creation, one `ClaimSegment` is materialised per ticket, each carrying the `ticket_id` and a `flight_id` pulled from that ticket. A new claim begins with `review_status` set to `PENDING_MATCH` and `payout_status` set to `NOT_PAYABLE`; these are two parallel axes that advance independently. If every supplied ticket is in `ATTACHED` or `CHANGED` and is bound to this same policy, the system promotes `review_status` directly to `MATCHED` (either because the ticket's `passenger_doc_id` equals the policy's `policy_holder_doc_id`, or because a `ManualReviewCase` has previously bound the ticket to this policy); otherwise the claim stays in `PENDING_MATCH`. When matching fails outright and no manual review is opened — or when a referenced ticket is `REFUNDED` — the claim is automatically driven to `REJECTED` with `rejection_reason` set to `MATCHING_FAILED`.

The review axis advances via a sequence of operator actions. A `ClaimsReviewer` submits a matched claim for review, providing an `assigned_reviewer_id` in the request body that the server records on the claim. Submission requires that every segment's flight is finalised (i.e., its `status` is one of `LANDED`, `CANCELLED`, `DIVERTED`, or `RETURNED` — otherwise `ERR_FLIGHT_NOT_FINALIZED`), that the ticket's `scheduled_departure_epoch_ms` is at least `policy.effective_from_epoch_ms + policy.waiting_period_ms` (otherwise `ERR_WAITING_PERIOD_NOT_MET`), and that every referenced ticket has `status` in `ATTACHED` or `CHANGED` (otherwise `ERR_TICKET_NOT_BOUND`; tickets in `REFUNDED` or `UNMATCHED` block submission). A successful submission advances `review_status` from `MATCHED` to `UNDER_REVIEW`, and at that moment the system computes for each segment the `delay_minutes_used`, the `eligibility` (one of `ELIGIBLE`, `EXCLUDED_CAUSE`, `WAITING_PERIOD`, `DELAY_BELOW_THRESHOLD`, or `TICKET_NOT_BOUND`), the `tier_selected`, and the `gross_segment_payout_cents` per the rules in §3.5 and §3.6.

The reviewer may request resubmission at any time while the claim is `UNDER_REVIEW`. Returning the claim to `MATCHED` is a cyclic transition: it is restricted to the user whose `X-User-ID` equals the recorded `assigned_reviewer_id`, clears the `assigned_reviewer_id`, and allows the reviewer to gather new evidence and resubmit later. The same reviewer may revisit the cycle multiple times.

A `ClaimsApprover` advances a claim from `UNDER_REVIEW` to `APPROVED` by supplying an `assigned_approver_id` in the request body (which must equal the caller's `X-User-ID`). Approval requires every segment's `eligibility` to be exactly `ELIGIBLE` — any non-eligible segment yields `ERR_CLAIM_NOT_ELIGIBLE` with the offending reason carried as a hint — and requires that approving the claim would not cause `policy.claim_quota_used_cents + estimated_payout_cents` to exceed `policy.claim_quota_total_cents` (otherwise `ERR_QUOTA_EXHAUSTED`). The approver's `X-User-ID` must differ from the claim's `assigned_reviewer_id` (otherwise `ERR_SOD_VIOLATION`). On approval the system pins `estimated_payout_cents` (the sum of eligible-segment `gross_segment_payout_cents` reduced by `policy.deductible_cents` floored at 0 and capped at `policy.policy_limit_cents`, per §3.6), increases `policy.reserve_balance_cents` by that amount, appends a `ReserveAdjustment` with `reason` `APPROVE_DEBIT` and a positive `delta_cents` equal to the pinned amount, automatically flips `payout_status` from `NOT_PAYABLE` to `PAYABLE`, and writes an `AuditLog` entry. A reject from `UNDER_REVIEW` (issued by a `ClaimsReviewer` or a `ClaimsApprover`) requires a `rejection_reason` in the request body drawn from `EXCLUDED_CAUSE`, `WAITING_PERIOD`, `DELAY_BELOW_THRESHOLD`, or `MANUAL_DENY`; reserve is unaffected and an `AuditLog` entry is written. The set of possible final values for `rejection_reason` is `EXCLUDED_CAUSE`, `WAITING_PERIOD`, `DELAY_BELOW_THRESHOLD`, `QUOTA_EXHAUSTED`, `MATCHING_FAILED`, `MANUAL_DENY`, or `DUPLICATE`.

The payout axis is gated by review approval. While `review_status` is below `APPROVED`, `payout_status` remains pinned at `NOT_PAYABLE`. Approval flips it to `PAYABLE`. Subsequent advances belong to the batch lifecycle (§3.8 and §3.9).

### 3.5. Eligibility — Causes, Waiting Periods, and Below-Threshold Delays

Eligibility is computed per segment when the claim enters `UNDER_REVIEW`. Three exclusion checks compete with the simple "the delay was long enough" path. First, when the parent policy's `excluded_delay_causes` contains the flight's `classified_cause`, the segment's `eligibility` is set to `EXCLUDED_CAUSE`. Second, when the ticket's `scheduled_departure_epoch_ms` is less than `policy.effective_from_epoch_ms + policy.waiting_period_ms`, the segment's `eligibility` is set to `WAITING_PERIOD`. Third, when the segment's underlying ticket has `status` `REFUNDED` or `UNMATCHED` at evaluation time, the segment's `eligibility` is set to `TICKET_NOT_BOUND`. Fourth, when the computed `delay_minutes_used` falls below the lowest-tier threshold of 60 minutes, the segment's `eligibility` is set to `DELAY_BELOW_THRESHOLD`. A segment that survives all four checks is recorded as `ELIGIBLE`. Approval rejects a claim with any non-`ELIGIBLE` segment.

The two delay-related gates surface as distinct error identifiers. A claim whose review submission attempt happens before the waiting period has been met fails at submit time with `ERR_WAITING_PERIOD_NOT_MET`. A claim whose computed delay is below threshold fails approval with `ERR_CLAIM_NOT_ELIGIBLE` (the `rejection_reason` hint is `DELAY_BELOW_THRESHOLD`). A claim whose flight cause is excluded by policy fails approval with `ERR_CLAIM_NOT_ELIGIBLE` (hint `EXCLUDED_CAUSE`). All three error identifiers reach the caller with HTTP 409.

### 3.6. Delay Duration, Tiered Compensation, and the Two Payout Variants

The `delay_minutes_used` for a segment is computed in two distinct variants pinned by the parent policy's `delay_basis`. When `delay_basis` is `DEPARTURE`, the system uses the scheduled-versus-actual departure: if the flight's `status` is `CANCELLED`, the `delay_minutes_used` takes the infinity sentinel value of 99,999,999 (treated as the highest tier); otherwise the value is the integer floor of the difference `(actual_departure_epoch_ms - scheduled_departure_epoch_ms) / 60000` — that is, the number of whole minutes between scheduled and actual departure, with millisecond remainders discarded. When `delay_basis` is `ARRIVAL`, the system uses the scheduled-versus-actual arrival: if the flight's `status` is `CANCELLED`, the `delay_minutes_used` takes the infinity sentinel; if the flight's `status` is `RETURNED`, the value also takes the infinity sentinel (return-to-origin is treated as full cancellation for arrival accounting); otherwise the value is the integer floor of `(actual_arrival_epoch_ms - scheduled_arrival_epoch_ms) / 60000`. The two variants can produce different minute values for the same flight whenever the flight makes up time in air or loses time on arrival; a single flight can land in `TIER_A` under one basis and `TIER_B` under the other.

Tier selection uses inclusive lower bounds. When `delay_minutes_used` is at least 360 minutes (or equals the infinity sentinel), `tier_selected` is `TIER_C` and the tier amount is 60,000 cents (six hundred euros). When `delay_minutes_used` is at least 180 but less than 360, `tier_selected` is `TIER_B` and the tier amount is 25,000 cents (two hundred fifty euros). When `delay_minutes_used` is at least 60 but less than 180, `tier_selected` is `TIER_A` and the tier amount is 10,000 cents (one hundred euros). When `delay_minutes_used` is below 60, `tier_selected` is `NONE`, the tier amount is 0, and the segment's `eligibility` is set to `DELAY_BELOW_THRESHOLD`.

The per-segment `gross_segment_payout_cents` then depends on the policy's `payout_mode`. Under `FIXED`, the gross segment payout equals the tier amount in cents. Under `ACTUAL_LOSS`, the gross segment payout is the integer floor of `claimed_actual_loss_cents * reimbursement_rate_bps / 10000` (basis points are out of ten thousand), and that result is then capped above by the tier amount — i.e., the smaller of the floored expense-times-rate and the tier-amount in cents. Under `FIXED`, the field `claimed_actual_loss_cents` is ignored regardless of what the segment recorded.

The claim-level `estimated_payout_cents` (pinned at approval) and the claim-level `final_payout_cents` (pinned at settlement) share an identical accounting algorithm with one strict ordering rule: per-segment gross amounts are summed first, then the deductible is applied once, then the cap is applied. Concretely, sum `gross_segment_payout_cents` over only those segments whose `eligibility` is `ELIGIBLE`; subtract `policy.deductible_cents`, clamping at zero; then take the smaller of that result and `policy.policy_limit_cents`. The deductible is applied exactly once per claim, never per segment. The result is the value pinned to `estimated_payout_cents` at approval and to `final_payout_cents` at settlement; the two are equal in the absence of intervening corrections.

At settlement, the per-segment `final_segment_payout_cents` is then pro-rated. For each `ELIGIBLE` segment, the per-segment final amount is the integer floor of `gross_segment_payout_cents * capped_total / sum_of_eligible_gross_payouts`, where `capped_total` is the claim-level pinned amount described above and `sum_of_eligible_gross_payouts` is the un-deducted sum used in step one. If the un-deducted sum is zero, every per-segment final amount is zero. Any residue between `capped_total` and the sum of the per-segment final amounts is allocated to the segment with the largest `gross_segment_payout_cents`; ties are broken by selecting the segment whose `id` is lexicographically smallest. Per-segment gross amounts are floor-rounded once, at the segment level, before they are summed; do not recompute by summing raw expenses and then multiplying by the rate, as that path can produce a different cents result under `ACTUAL_LOSS`.

### 3.7. Reserve, Quota, and the Reinsurance Waterfall

When a claim is approved, the optimistic reserve `reserve_balance_cents` rises by `estimated_payout_cents` and a `ReserveAdjustment` of `reason` `APPROVE_DEBIT` is appended with positive `delta_cents`. When the claim eventually settles into `PAID`, the system pins `final_payout_cents` to the previously-pinned `estimated_payout_cents`, computes `final_segment_payout_cents` per segment by the pro-ration above, decreases the policy's `reserve_balance_cents` by the previously-debited amount, increases `claim_quota_used_cents` by `final_payout_cents`, and appends a `ReserveAdjustment` of `reason` `SETTLE_RELEASE` with the corresponding negative `delta_cents`. When a reviewer or approver rejects an `UNDER_REVIEW` claim, no reserve change is journalled — the claim never reached `APPROVED` so no debit ever happened — but for rejections that follow a prior reserve hold (the rare path where reserve was held and then released), a `ReserveAdjustment` of `reason` `REJECT_RELEASE` documents the release. When a `ClaimsAdmin` reverses a `PAID` claim, the system increases `reserve_balance_cents` by `final_payout_cents`, decreases `claim_quota_used_cents` by the same amount, appends a `ReserveAdjustment` of `reason` `REVERSE_REBUILD`, and emits an `OutboxEvent` to the banking system for the clawback. Reversal is only permitted from `PAID`.

The reinsurance waterfall is computed at settlement and produces exactly one `ReinsuranceAllocation` row per claim. The waterfall has a circular shape — primary first, reinsurer next, primary excess on top — so evaluation is pinned in this order. First, `primary_first` is the smaller of `final_payout_cents` and the primary retention (set at 50,000 cents, i.e., five hundred euros). Second, the reinsurer absorbs the layer above retention up to the reinsurer cap (set at 30,000 cents, i.e., three hundred euros) — that is, `reinsurer_share_cents` equals the smaller of "the remainder after primary retention" (clamped at zero if negative) and the reinsurer cap. Third, `primary_excess` absorbs whatever remains beyond the reinsurer layer — that is, the larger of zero and `final_payout_cents - primary_first - reinsurer_share_cents`. Fourth, `primary_share_cents` equals `primary_first + primary_excess`. The allocation invariant is exact: `primary_share_cents + reinsurer_share_cents` must equal `pinned_total_cents`, which itself equals the claim's `final_payout_cents` at the moment of settlement. No rounding is performed in this calculation.

### 3.8. Same-Flight Batch Construction and Approval

A payout batch groups together same-flight claims that are ready for execution. A `BatchApprover` (or a `ClaimsAdmin`) creates the batch by supplying the binding `flight_id` and a `claim_ids` array — every claim referenced must already be in `review_status` `APPROVED` and `payout_status` `PAYABLE`, and every such claim must have at least one segment whose `flight_id` equals the batch's `flight_id` (otherwise `ERR_BATCH_FLIGHT_MISMATCH`). On creation, every included claim's `payout_batch_id` is set, and the batch's `total_planned_payout_cents` is frozen as the sum of `estimated_payout_cents` over the included claims. The batch begins with `review_phase` `STAGED` and `execution_phase` `PENDING`; `total_settled_payout_cents` is initialised to zero and `exception_claim_ids` is initialised to the empty array.

The batch's review phase is independent of its execution phase. A `BatchApprover` advances the review phase by approving — supplying an `assigned_batch_approver_id` in the request body, which the server records on the batch — provided every claim in the batch is still in `review_status` `APPROVED` (otherwise `ERR_CLAIM_NOT_APPROVED`) and provided the batch approver's `X-User-ID` does not equal any of the per-claim `assigned_approver_id` values across the batch (otherwise `ERR_SOD_VIOLATION`). Approval transitions `review_phase` from `STAGED` to `APPROVED` and leaves `execution_phase` unchanged at `PENDING`. Alternatively, a `BatchApprover` rejects the staged batch — which transitions `review_phase` from `STAGED` to `REJECTED`, leaves each child claim's `payout_status` at `PAYABLE` (reserves are not released because the per-claim `review_status` is still `APPROVED`), and accepts a `reason` in the request body. An audit-log entry is written for both outcomes.

### 3.9. Batch Execution, Per-Claim Settlement, and Exception Handling

Execution is the second axis of the batch state machine and depends on review approval. A `BatchExecutor` begins execution by supplying an `assigned_batch_executor_id` in the request body that must equal the caller's `X-User-ID` and must differ from the recorded `assigned_batch_approver_id` (otherwise `ERR_SOD_VIOLATION`). Execution requires `review_phase` to be `APPROVED` (otherwise `ERR_BATCH_NOT_APPROVED`). On success, `execution_phase` advances from `PENDING` to `EXECUTING`, every child claim whose `payout_status` is `PAYABLE` is moved to `EXECUTING` (the per-claim `payout_operator_id` is also recorded as the executor's `X-User-ID`, with the additional segregation check that this operator id cannot equal the per-claim `assigned_approver_id`), and an `OutboxEvent` is emitted for each claim with `target_system` `BANKING` and `event_type` `BATCH_DISPATCHED` carrying the claim id and amount in its payload. Two operators racing to execute the same batch resolve to one `EXECUTING` transition; the loser receives `ERR_BATCH_ALREADY_DISPATCHED`.

A claim's `EXECUTING` state is resolved per-claim. A `PayoutOperator` (or the system) marks the claim as paid once banking confirms, advancing the per-claim `payout_status` from `EXECUTING` to `PAID`. Settlement pins `final_payout_cents`, computes per-segment `final_segment_payout_cents` by the pro-ration in §3.6, decreases `policy.reserve_balance_cents` by the previously held amount, increases `policy.claim_quota_used_cents` by `final_payout_cents`, appends the corresponding `ReserveAdjustment` with `reason` `SETTLE_RELEASE`, computes one `ReinsuranceAllocation` row per §3.7, updates the parent batch's `total_settled_payout_cents` by adding the just-settled amount, emits three `OutboxEvent` rows with `target_system` taking the values `PAYMENT`, `POLICY_ADMIN`, and `AIRLINE` and `event_type` `CLAIM_PAID` for each, and writes an `AuditLog` entry with `action` `PAYOUT_RECORDED`. When every child claim of the batch has reached `PAID` or `REVERSED` and `exception_claim_ids` is empty, the batch's `execution_phase` automatically transitions to `SETTLED`. Two concurrent settlements of the same claim resolve to one `PAID` transition; the loser receives `ERR_INVALID_STATE`.

Banking dispatch may fail. A `PayoutOperator` (or the system) marks a failure with the mark-exception capability, supplying an optional `reason` in the request body. The per-claim `payout_status` reverts from `EXECUTING` back to `PAYABLE`, the claim id is appended to the parent batch's `exception_claim_ids`, and the batch's `execution_phase` advances to `EXCEPTIONS` if it was previously `EXECUTING`. The `EXCEPTIONS` branch isolates failed dispatches without halting the `SETTLED` transition for the rest. A `BatchExecutor` re-dispatches only the exception claims with the retry-exceptions capability, which clears `exception_claim_ids`, transitions the per-claim `payout_status` from `PAYABLE` back to `EXECUTING` for each formerly excepted claim, and returns the batch's `execution_phase` from `EXCEPTIONS` to `EXECUTING`.

A `ClaimsAdmin` may reverse a `PAID` claim by advancing `payout_status` from `PAID` to `REVERSED` (with `X-User-Role` of `ClaimsAdmin`). Reversal increases `policy.reserve_balance_cents` by `final_payout_cents`, decreases `policy.claim_quota_used_cents` by the same amount, appends a `ReserveAdjustment` of `reason` `REVERSE_REBUILD` with `delta_cents` equal to a positive `final_payout_cents`, emits an `OutboxEvent` with `target_system` `BANKING` and `event_type` `CLAIM_REVERSED`, and writes an `AuditLog` entry.

### 3.10. Maintenance — Clock, Sweep, Invariants, and Outbox Acknowledgement

The simulated clock advances only when a `ClaimsAdmin` calls the test-clock advance capability with either a non-negative `delta_ms` (an increment from the current `now_epoch_ms`) or an absolute `to_epoch_ms`. The advance call updates `Insurer.now_epoch_ms` and leaves any pending state transitions to be evaluated by the next sweep. The system sweep capability evaluates `SCHEDULED → ACTIVE` transitions, `LANDED|CANCELLED|DIVERTED|RETURNED → ARCHIVED` transitions for old flights (those whose `Insurer.now_epoch_ms - scheduled_arrival_epoch_ms` exceeds 90 days), and `EXECUTING → SETTLED` transitions for batches whose claims have all reached terminal payout states with no pending exceptions; it returns a summary report containing the number of flights advanced, the number of batches settled, and the number of claims auto-rejected. A sweep may also append `AuditLog` entries as a result of these advances.

The invariant-check capability recomputes every policy's `reserve_balance_cents` and `claim_quota_used_cents` from the underlying claim ledger and reports any drift. Its response carries an `ok` boolean and a `drift` array whose entries name the affected `policy_id`, the `expected` recomputation, and the `observed` stored value. When drift is detected, the response surfaces `ERR_RESERVE_DRIFT` so that audit observers (the `Auditor` and `ClaimsAdmin` roles) can act. The outbox mark-delivered capability is used by external integrations to acknowledge that an event has been received downstream; it transitions a row's `dispatch_status` from `PENDING` to `DELIVERED` and is idempotent under repeated calls.

## 4. Endpoint Definitions

The API is rooted at `/insurers`. Endpoints that create a new persisted resource respond with HTTP 201; endpoints that retrieve, list, or modify an existing resource respond with HTTP 200. Successful responses follow the success envelope of §2.2; failures follow the error envelope of §2.2 and use the error identifiers of §5. The summary table below intentionally omits request bodies, response bodies, and side effects — all of which are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/insurers` | Create an insurer (root tenant) | `ClaimsAdmin` |
| GET | `/insurers/{insurerId}` | Get insurer | `Any` |
| POST | `/insurers/{insurerId}/_clock/advance` | Advance the test clock by `delta_ms` or to absolute `to_epoch_ms` | `ClaimsAdmin` |
| POST | `/insurers/{insurerId}/_sweep/run` | Trigger system sweep | `ClaimsAdmin`, `system` |
| POST | `/insurers/{insurerId}/_invariant/check` | Recompute and verify reserve and quota invariants | `ClaimsAdmin`, `Auditor` |
| POST | `/insurers/{insurerId}/policies` | Create a policy | `PolicyAdmin`, `ClaimsAdmin` |
| GET | `/insurers/{insurerId}/policies/{policyId}` | Get policy | `Any` |
| GET | `/insurers/{insurerId}/policies/{policyId}/risk_view` | Pessimistic-reserve view | `PolicyAdmin`, `ClaimsAdmin`, `Auditor` |
| POST | `/insurers/{insurerId}/policies/{policyId}/suspend` | Suspend a policy | `PolicyAdmin` |
| POST | `/insurers/{insurerId}/policies/{policyId}/terminate` | Terminate a policy | `PolicyAdmin` |
| POST | `/insurers/{insurerId}/tickets` | Ingest a ticket and auto-match to a policy | `PolicyAdmin` |
| GET | `/insurers/{insurerId}/tickets/{ticketId}` | Get ticket | `Any` |
| POST | `/insurers/{insurerId}/tickets/{ticketId}/change` | Mark ticket as `CHANGED` | `PolicyAdmin` |
| POST | `/insurers/{insurerId}/tickets/{ticketId}/confirm` | Confirm a `CHANGED` ticket back to `ATTACHED` | `PolicyAdmin` |
| POST | `/insurers/{insurerId}/tickets/{ticketId}/refund` | Mark ticket as `REFUNDED` | `PolicyAdmin` |
| POST | `/insurers/{insurerId}/flights` | Create a flight | `ClaimsAdmin`, `PolicyAdmin` |
| GET | `/insurers/{insurerId}/flights/{flightId}` | Get a flight | `Any` |
| GET | `/insurers/{insurerId}/flights` | List flights with filters `carrier_code`, `flight_number`, `status`, `scheduled_departure_after_epoch_ms` | `Any` |
| POST | `/insurers/{insurerId}/flights/{flightId}/events` | Ingest a multi-source `FlightStatusEvent` | `ClaimsAdmin`, `system` |
| POST | `/insurers/{insurerId}/flights/{flightId}/archive` | Manually archive a finalised flight | `ClaimsAdmin` |
| GET | `/insurers/{insurerId}/manual_review/{caseId}` | Get a manual review case | `ClaimsReviewer`, `ClaimsAdmin` |
| POST | `/insurers/{insurerId}/manual_review/{caseId}/resolve_bind` | Resolve a manual-review case by binding the ticket to a chosen policy | `ClaimsReviewer` |
| POST | `/insurers/{insurerId}/manual_review/{caseId}/resolve_reject` | Reject a manual-review case | `ClaimsReviewer` |
| POST | `/insurers/{insurerId}/policies/{policyId}/claims` | Create a claim covering one or more tickets | `ClaimsReviewer`, `PolicyAdmin` |
| GET | `/insurers/{insurerId}/claims/{claimId}` | Get a claim (includes segments) | `Any` |
| GET | `/insurers/{insurerId}/claims` | List claims with filters `policy_id`, `flight_id`, `review_status`, `payout_status` | `Any` |
| POST | `/insurers/{insurerId}/claims/{claimId}/submit_review` | Submit the claim for review | `ClaimsReviewer` |
| POST | `/insurers/{insurerId}/claims/{claimId}/return_to_match` | Return the claim to `MATCHED` for resubmission | `ClaimsReviewer` |
| POST | `/insurers/{insurerId}/claims/{claimId}/approve` | Approve the claim | `ClaimsApprover` |
| POST | `/insurers/{insurerId}/claims/{claimId}/reject` | Reject a claim under review | `ClaimsReviewer`, `ClaimsApprover` |
| POST | `/insurers/{insurerId}/claims/{claimId}/settle` | Mark claim as `PAID` after banking confirmation | `PayoutOperator`, `system` |
| POST | `/insurers/{insurerId}/claims/{claimId}/mark_exception` | Mark in-flight payout as failed | `PayoutOperator`, `system` |
| POST | `/insurers/{insurerId}/claims/{claimId}/reverse` | Admin reverses a paid claim | `ClaimsAdmin` |
| POST | `/insurers/{insurerId}/payout_batches` | Create a `STAGED` batch from `PAYABLE` same-flight claims | `BatchApprover`, `ClaimsAdmin` |
| GET | `/insurers/{insurerId}/payout_batches/{batchId}` | Get payout batch | `Any` |
| POST | `/insurers/{insurerId}/payout_batches/{batchId}/approve` | Approve a staged batch | `BatchApprover` |
| POST | `/insurers/{insurerId}/payout_batches/{batchId}/reject` | Reject a staged batch | `BatchApprover` |
| POST | `/insurers/{insurerId}/payout_batches/{batchId}/execute` | Begin execution of an approved batch | `BatchExecutor` |
| POST | `/insurers/{insurerId}/payout_batches/{batchId}/retry_exceptions` | Retry only the exception claims | `BatchExecutor` |
| GET | `/insurers/{insurerId}/audit_logs` | List audit log entries with filters `subject_type`, `subject_id`, `action` | `Auditor`, `ClaimsAdmin` |
| GET | `/insurers/{insurerId}/outbox_events` | List outbox events with filters `target_system`, `dispatch_status`, `subject_id` | `ClaimsAdmin`, `Auditor` |
| POST | `/insurers/{insurerId}/outbox_events/{eventId}/mark_delivered` | External system confirms delivery | `ClaimsAdmin`, `system` |

## 5. Error Code Catalogue

Trigger conditions for each error are documented in §2 and §3 narratives; this table provides only the identifier and HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FLIGHT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FLIGHT_NOT_FINALIZED` | 409 |
| `ERR_POLICY_INACTIVE` | 409 |
| `ERR_BATCH_NOT_APPROVED` | 409 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_BATCH_FLIGHT_MISMATCH` | 409 |
| `ERR_BATCH_ALREADY_DISPATCHED` | 409 |
| `ERR_TICKET_NOT_BOUND` | 409 |
| `ERR_TICKET_LOCKED_BY_CLAIM` | 409 |
| `ERR_WAITING_PERIOD_NOT_MET` | 409 |
| `ERR_CLAIM_NOT_ELIGIBLE` | 409 |
| `ERR_QUOTA_EXHAUSTED` | 409 |
| `ERR_RESERVE_DRIFT` | 409 |
| `ERR_DUPLICATE_EVENT` | 409 |
| `ERR_DUPLICATE_PNR` | 409 |

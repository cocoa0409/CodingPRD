# FCRA Credit Report Disputes API — Product Requirements Document

## 1. Introduction

The Fair Credit Reporting Act establishes a tightly choreographed dialogue among three parties — the consumer, the credit bureau, and the original information furnisher — and a single mistake in that dialogue (a missed deadline, a reaged delinquency, an unverified deletion left as "verified") translates directly into measurable consumer harm and statutory exposure. This API encodes that dialogue as a state-driven workflow on top of a logical test clock, so every regulatory deadline (the bureau's thirty-day investigation window, the optional fifteen-day extension when the consumer supplies additional information, the furnisher's reverification window, the seven-year reage horizon) is enforceable against a deterministic notion of "today" rather than wall-clock time.

The system spans the full dispute lifecycle and the surrounding controls that consumers exercise over their credit files. Consumers submit disputes through either the online or mail channel with supporting documentation; the bureau forwards each dispute to the responsible furnisher, reconciles the response (or the absence of one) into a written result notice, and grants a free credit report whenever the outcome changed the underlying tradeline. Around this central pipeline, the API also governs CFPB escalation (including the cycle in which CFPB acceptance forces the bureau to reopen the investigation under a fresh clock), credit freezes that block new hard inquiries entirely, and creditor-controlled credit locks that perform the same blocking function under consumer convenience semantics.

This document specifies the entity model, the state machines, the calculations, the validation priorities, and the role-based access rules that together make the workflow auditable. Where business rules and statutory requirements diverge from a purely mechanical interpretation — most visibly in the reage prohibition, the "no response means delete" rule, and the frivolous-dispute threshold — the document states the regulatory intent so that implementations preserve consumer protection even at the cost of operator convenience.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` identifies the principal's operational capacity. If either header is missing, malformed, or unrecognizable, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the headers are present but the named role is not permitted for the endpoint (or, for resources scoped to a consumer, the acting `X-User-ID` does not match the resource's owning `consumer_id`), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles, spelled here precisely as they must appear in `X-User-Role`:

- `Consumer` — the end consumer acting on their own credit identity.
- `BureauOperator` — staff of Equifax, Experian, or TransUnion running the investigation pipeline.
- `Furnisher` — the original creditor or information furnisher that seeded a tradeline or that requests a hard pull.
- `CFPBOperator` — staff of the Consumer Financial Protection Bureau handling regulatory complaints.
- `PlatformAdmin` — operator of the bench platform itself, responsible for seeding consumers, reports, and furnishers, and for driving the test clock and the daily sweep.

The interpretation of `X-User-ID` is role-dependent and matters for ownership checks. When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer`; any resource scoped to a consumer (the consumer's disputes, credit reports, regulatory complaints, freezes, and locks) compares its `consumer_id` to `X-User-ID` for ownership, and a mismatch surfaces as `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `Furnisher`, `X-User-ID` is the `id` of the acting `Furnisher`; tradeline rows and hard inquiries the furnisher owns or initiates are compared by `furnisher_id` (or `requesting_furnisher_id`) to `X-User-ID`. When `X-User-Role` is `BureauOperator`, `CFPBOperator`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` is the maximum number of items returned in a single response; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items skipped before the page begins and defaults to 0. Unless an endpoint explicitly states otherwise, list responses are sorted by the resource's `created_at` timestamp in ascending order. The pagination state itself surfaces in the response's `meta` object as `limit`, `offset`, `total_count`, and `has_more`. Any request whose body is structurally malformed — wrong JSON shape, wrong field types, or values that are not parseable into the documented types — is rejected with `ERR_INVALID_REQUEST` regardless of which endpoint received it.

### 2.4. The Logical Clock and Day-Stamped Fields

This system does not depend on wall-clock time. A monotonically advancing logical clock measured in whole days is the sole reference for every deadline, every reage check, and every "today" semantics. The current clock value is exposed for inspection as the integer field `day` on the clock-read endpoint described in §4. A test-driving capability accepts a positive integer `days` argument and advances the logical clock by that many days; advancing the clock does not by itself fire any deadlines — the daily sweep described in §3 is the only mechanism that materializes deadline-driven side effects, and it must be invoked explicitly. Many entity fields therefore carry day-valued integers rather than timestamps: `submitted_day`, `deadline_day`, `forwarded_day`, `reverification_deadline_day`, `response_day`, `issued_day`, `placed_day`, `lifted_day`, `locked_at_day`, `inquiry_day`, `filed_day`, `last_pulled_day`, `original_dofd_day`, and `reported_dofd_day`. Each is the integer value of the logical clock's `day` at the moment the corresponding event was recorded.

### 2.5. Common Resource Properties

Most top-level resources — `Consumer`, `CreditReport`, `TradelineItem`, `Furnisher`, `Dispute`, `RegulatoryComplaint`, `CreditFreeze`, and `CreditLock` — carry the standard four system-managed fields:

- `id` (string): a unique server-minted identifier formatted as a UUID. The system uses raw UUIDs without any type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits indicating when the resource was first created (e.g., `2025-05-24T10:30:00.123Z`).
- `updated_at` (string): an ISO 8601 UTC timestamp updated whenever any property of the resource changes, whether through a direct request or through a server-driven cascade or recompute (such as a posture recalculation, a FICO recompute, or a `free_reports_remaining` adjustment).
- `version` (integer): a monotonically increasing counter that increments by one on every mutation, including server-driven mutations. The version is the basis for optimistic concurrency control as described in §2.6.

A small number of supporting resources are append-only audit records that carry only `id` and `created_at` — both `updated_at` and `version` are absent on them because they are never mutated after creation. These are `FurnisherInquiry`, `ResultNotice`, and `HardInquiry`. Any reference in §3 to "updating" one of these entities (for example, recording the furnisher's response on a `FurnisherInquiry`) describes a request that occurs while the inquiry is being initially populated by the bureau workflow, not a mutation after the fact.

### 2.6. Optimistic Concurrency Control

Any endpoint that mutates a specific resource accepts an optional `version` field in the request body. When the client includes `version`, the server compares it to the resource's current `version`; if the two do not match, the request is rejected with `ERR_INVALID_STATE_TRANSITION` because the resource has moved on since the client last read it. When the client omits `version`, the server processes the mutation without an OCC check and is responsible only for the request's intrinsic preconditions. OCC governs all state-machine transitions described in §3 as well as direct property edits.

### 2.7. Nested Resource Retrieval and Path Validation

The API expresses ownership through URL hierarchy. When an endpoint path contains more than one resource identifier (for example, a path with both a `consumerId` and a `disputeId`, or both a `creditReportId` and a `tradelineItemId`), the server validates each identifier in strict left-to-right order. The first identifier that does not correspond to an existing resource produces an immediate `ERR_NOT_FOUND` response, and no further identifiers in the path are examined. Body-referenced foreign keys (for example, a `credit_report_id` or a `tradeline_item_id` in a dispute submission, a `dispute_id` in a regulatory complaint, or a `parent_complaint_id` on a refile) must exist and must belong to the same `Consumer` indicated by the path; if a body foreign key points to another consumer's resource, the request is rejected with `ERR_CROSS_CONSUMER_REFERENCE`.

### 2.8. Hierarchical Consistency and Derived-Field Propagation

Several fields on parent resources are derived from the state of their children, and the server is responsible for keeping them coherent without operator intervention. When a `Dispute` is created, transitions, or closes, the affected `CreditReport`'s `posture` is recomputed; when a `CreditFreeze` is placed or lifted, the same recomputation runs for the matching `(consumer_id, bureau)` report. When a `TradelineItem` mutates (because a dispute closed as `CLOSED_UPDATED` or `CLOSED_DELETED`), the owning `CreditReport`'s `fico_score` is recomputed using the procedure in §3. When a dispute closes as `CLOSED_UPDATED` or `CLOSED_DELETED` with an actual change to the tradeline, the owning `Consumer`'s `free_reports_remaining` is incremented per §3. Every such server-driven mutation bumps the affected resource's `updated_at` and increments its `version` exactly as a client-driven mutation would.

### 2.9. The Reage Prohibition

A central FCRA protection that pervades several endpoints is the reage prohibition: under no circumstances may a tradeline's `reported_dofd_day` be moved later than its current value. Verified corrections may move `reported_dofd_day` earlier (because the true date of first delinquency turned out to be earlier than what was reported), but any attempt to push it later — whether requested by the consumer as a `CORRECT_DOFD` action or arriving as a furnisher's response with a `new_dofd_day` later than the currently reported value — is rejected with `ERR_REAGE_PROHIBITED`. The `original_dofd_day` recorded at tradeline creation is immutable and exists precisely to preserve the historical anchor used in this comparison.

### 2.10. Calculation Precision

Two calculations described in §3 produce integer-valued fields. The FICO score uses a single round-half-up application after the final weighted multiplication and additive shift, producing an integer that is then clamped to the inclusive range from 300 to 850. The dispute risk score is computed entirely in integer arithmetic and requires no rounding step; its result is clamped to the inclusive range from 0 to 100. All other day-valued integers in the system are exact by construction because they are derived from the logical clock, which is itself an integer.

### 2.11. Daily Sweep Semantics

A platform-driven sweep capability runs the deadline-materialization step that the logical clock alone cannot perform. When invoked, it walks every `FurnisherInquiry` whose `response` is still `PENDING` and whose `reverification_deadline_day` is strictly less than the current clock `day`; for each such inquiry, the `response` is set to `NO_RESPONSE` and the parent `Dispute` advances to `RESULTS_PENDING` along the system-driven arm of its state machine. Bureau operators do not need to run this sweep; it exists so that tests can deterministically drive what would otherwise be cron-scheduled bureau back-office automation. The clock-advance capability never runs the sweep implicitly — clock advancement and sweep execution are two distinct test-driving operations.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Consumers, Furnishers, and Credit Reports

Onboarding the parties is the first step in any session. A `PlatformAdmin` creates a `Consumer` by supplying the consumer's `full_name`, last four digits of social security number as `ssn_last4` (which must be exactly four digits), and contact `email` (which must be unique across all consumers). On creation, the server initializes the consumer's `free_reports_remaining` counter to 1 — the statutory annual free report — and leaves `freeze_pin` as null because no freeze has been placed yet. The `freeze_pin` is server-minted later, on the consumer's first credit freeze; once minted, the same PIN persists across subsequent freezes and lifts for that consumer.

In parallel, a `PlatformAdmin` registers each `Furnisher` by supplying its `legal_name` and immutable `ecoa_code`. A newly registered furnisher's `status` begins at `ACTIVE`; a `PlatformAdmin` may later move it to `SUSPENDED` but this transition is not part of the consumer-facing workflow.

A `PlatformAdmin` then creates one `CreditReport` per bureau for the consumer by supplying the `bureau`, which must be one of the three values `EQUIFAX`, `EXPERIAN`, or `TRANSUNION`. On creation, the server seeds the report with `status` of `ACTIVE`, `posture` of `OPEN`, a `fico_score` of 300, and a null `last_pulled_day` (the report has never been pulled). The seeded score of 300 is the lower bound of the FICO range; subsequent recomputation per §3.5 will revise it as tradelines accumulate.

Either a `PlatformAdmin` or a `Furnisher` populates the report with tradelines. Each `TradelineItem` is added under its `credit_report_id` and the request specifies the owning `furnisher_id`, the furnisher-side `account_ref` (which must be unique per `(credit_report_id, furnisher_id)`), the `original_dofd_day` (a non-negative integer day value), the `balance_cents` (a non-negative integer representing the reported balance in cents), and the initial `payment_status` from the enumeration `CURRENT`, `LATE_30`, `LATE_60`, `LATE_90`, `CHARGE_OFF`, `COLLECTION`, or `DELETED`. On creation, the server copies `original_dofd_day` into `reported_dofd_day`, sets `verification_status` to `UNVERIFIED`, and immediately recomputes the owning report's `fico_score` per §3.5.

### 3.2. Dispute Submission and the Investigation Clock

A `Consumer` submits a dispute through the consumer-scoped dispute submission endpoint, providing the `credit_report_id` of the target report (which also fixes the bureau the dispute is filed against), the `tradeline_item_id` of the specific tradeline being challenged, the channel of submission as `channel` (either `ONLINE` or `MAIL`, immutable after submission), and an array of `supporting_documents`. Each document descriptor in the array is an object carrying a `kind` label and the document's `sha256` digest. The supporting-documents array must be non-empty at submission; an empty or missing array is rejected with `ERR_NO_SUPPORTING_DOCUMENTS`, and the same code is reused when the bureau later attempts to open the investigation without documents on file. The submission also names a `requested_action` from the enumeration `CORRECT_BALANCE`, `CORRECT_STATUS`, `DELETE_ITEM`, or `CORRECT_DOFD`, and a `requested_payload` object whose contents are specific to the action — for example, `{new_balance_cents}` for `CORRECT_BALANCE` or `{new_dofd_day}` for `CORRECT_DOFD`.

Submission is gated by several rules that fire in priority order. The submission must include supporting documents (priority 11, `ERR_NO_SUPPORTING_DOCUMENTS`). The submitted body's `credit_report_id` and `tradeline_item_id` must reference resources belonging to the same consumer named in the path; otherwise `ERR_CROSS_CONSUMER_REFERENCE`. The system then computes the provisional variant of the dispute risk score (see §3.6) and applies the frivolous-dispute threshold: if the consumer has already submitted more than three disputes against the same `tradeline_item_id` in the trailing 365 logical days, the submission is rejected with `ERR_FRIVOLOUS_DISPUTE`. Finally, the system enforces the uniqueness rule that at most one `Dispute` may be in a non-terminal status (anything other than `CLOSED_VERIFIED`, `CLOSED_UPDATED`, `CLOSED_DELETED`, or `CLOSED_DISMISSED`) per `TradelineItem` — a second attempt is rejected with `ERR_DUPLICATE_ACTIVE_DISPUTE`. When two consumers race two submissions for the same tradeline simultaneously, this same rule serializes them: the first writer wins on `(consumer_id, tradeline_item_id)` when the existing dispute is in a non-terminal status and the loser receives `ERR_DUPLICATE_ACTIVE_DISPUTE`.

On successful submission, the new `Dispute` is created with `status` of `RECEIVED`, `submitted_day` set to the current clock `day`, `additional_info_accepted` initialized to false, `investigation_outcome` initialized to `PENDING`, and a null `result_notice_id`. The investigation clock is set by computing `deadline_day` as `submitted_day` plus thirty — the FCRA base window. The provisional dispute risk score is evaluated and persisted; see §3.6 for its formula.

Once received, a dispute moves into investigation only when a `BureauOperator` opens it. Opening the investigation transitions the dispute from `RECEIVED` to `UNDER_INVESTIGATION`. Before the transition fires, three preconditions are checked: the target `CreditReport`'s `posture` must not be `FROZEN` (otherwise `ERR_REPORT_FROZEN` — FCRA does not freeze the dispute process itself, but this system requires the consumer to lift the freeze first so that subsequent recomputation is meaningful); the dispute's `supporting_documents` must still be non-empty (otherwise `ERR_NO_SUPPORTING_DOCUMENTS`); and the dispute must not breach the frivolous threshold from priority 12 (otherwise `ERR_FRIVOLOUS_DISPUTE`). On the transition, the bureau auto-creates exactly one `FurnisherInquiry` for the dispute, with the inquiry's `forwarded_day` set to the current clock `day` and the inquiry's `response` set to `PENDING`. The system then recomputes the report's `posture` per §3.7; with an active dispute now on the report, the posture becomes `RESTRICTED`.

While the dispute is `UNDER_INVESTIGATION`, the consumer may submit additional information by invoking the additional-info action, which is a self-loop from `UNDER_INVESTIGATION` back to `UNDER_INVESTIGATION`. The request body re-supplies a `supporting_documents` array containing the new descriptors. The action is rejected if `additional_info_accepted` is already true (a second extension is `ERR_INVALID_STATE_TRANSITION`) or if the current clock `day` has already passed `deadline_day` (`ERR_DISPUTE_DEADLINE_PASSED`). On acceptance, `additional_info_accepted` is set to true and `deadline_day` is rewritten to `submitted_day` plus forty-five — the FCRA fifteen-day extension on top of the original thirty.

### 3.3. Furnisher Reverification and the Sweep

Once the bureau has opened an investigation, the single `FurnisherInquiry` carries the reverification window. The inquiry's `reverification_deadline_day` is set to its `forwarded_day` plus twenty-five — twenty-five logical days regardless of whether the dispute itself has been extended to forty-five days. This twenty-five-day furnisher window is intentionally independent of the consumer's extension; an extension affects only the bureau's own `deadline_day`.

The furnisher response can arrive in one of two ways. A `BureauOperator` records a real furnisher response by invoking the furnisher-response action, supplying a `response` value from the enumeration `VERIFIED`, `UPDATED`, or `DELETED` and a `response_payload` object whose shape mirrors the dispute's `requested_action` (for example, `{new_balance_cents}` when the action was `CORRECT_BALANCE` or `{new_dofd_day}` when the action was `CORRECT_DOFD`). The operator action is rejected if the inquiry's `response` is no longer `PENDING`, if the current clock `day` is strictly greater than the inquiry's `reverification_deadline_day` (`ERR_FURNISHER_LATE` — the deadline is inclusive of the operator response on the deadline day itself), or if the current clock `day` is past the dispute's `deadline_day` (`ERR_DISPUTE_DEADLINE_PASSED`). The reage prohibition also fires here: if the furnisher's `response_payload` carries a `new_dofd_day` strictly greater than the tradeline's current `reported_dofd_day`, the request is rejected with `ERR_REAGE_PROHIBITED`. On acceptance, the system records the supplied `response` on the inquiry, stamps `response_day` with the current clock `day`, stores the `response_payload`, and advances the dispute from `UNDER_INVESTIGATION` to `RESULTS_PENDING`.

If the furnisher fails to respond, the system-driven arm of the state machine handles the silence. The daily sweep, invoked by a `PlatformAdmin`, walks every `FurnisherInquiry` whose `response` is still `PENDING` and whose `reverification_deadline_day` is strictly less than the current clock `day`. For each match, the sweep sets the inquiry's `response` to `NO_RESPONSE` and advances the parent dispute from `UNDER_INVESTIGATION` to `RESULTS_PENDING`. Under FCRA, an unverified item must be deleted, so a `NO_RESPONSE` outcome is treated identically to a furnisher-supplied `DELETED` response when the bureau later issues the result notice. When a furnisher response races the sweep on the deadline day, the deadline boundary is inclusive of the operator: if the operator request reaches the server when `clock.day` is still less than or equal to `reverification_deadline_day`, the operator wins and the inquiry records the real response; otherwise the sweep's `NO_RESPONSE` stands and the late operator request is rejected with `ERR_FURNISHER_LATE`.

### 3.4. Result Notices and Tradeline Mutation

A dispute in `RESULTS_PENDING` is resolved by a `BureauOperator` who issues the written result notice. The same issue-result-notice operation drives three distinct destination states depending on the furnisher's `response`, and each branch must be implemented with equal care because each produces a different combination of side effects.

The first branch fires when the furnisher's `response` was `VERIFIED`. The dispute transitions to `CLOSED_VERIFIED`. The system creates a `ResultNotice` with `outcome` of `VERIFIED`, `free_report_granted` set to false (no change occurred, so no remedial free report is issued), an `issued_day` stamped from the current clock `day`, a `delivery_channel` that mirrors the dispute's original `channel`, and a human-readable `summary`. The tradeline's `verification_status` is updated to `VERIFIED` but no other tradeline field changes. The report's `posture` is recomputed; if no other disputes remain active, the posture returns to `OPEN`. The pre-transition guard also verifies that the current clock `day` does not exceed the dispute's `deadline_day` (`ERR_DISPUTE_DEADLINE_PASSED`).

The second branch fires when the furnisher's `response` was `UPDATED`. The dispute transitions to `CLOSED_UPDATED`. Before the transition commits, the reage prohibition runs one more time for the `CORRECT_DOFD` case: if the dispute's `requested_action` is `CORRECT_DOFD`, the proposed `new_dofd_day` must be less than or equal to the tradeline's current `reported_dofd_day`, otherwise `ERR_REAGE_PROHIBITED`. On the transition, the furnisher's `response_payload` is applied to the tradeline — `balance_cents`, `payment_status`, or `reported_dofd_day` updates as appropriate — and `verification_status` is set to `UPDATED`. The owning report's `fico_score` is then recomputed per §3.5. The system creates a `ResultNotice` with `outcome` of `UPDATED`, `free_report_granted` set to true, the matching `issued_day`, the mirrored `delivery_channel`, and a `summary` of the changes; the consumer's `free_reports_remaining` is then bumped per the free-report-grant calculation in §3.6. The report's `posture` is recomputed at the end.

The third branch fires when the furnisher's `response` was `DELETED` or `NO_RESPONSE` — the bureau-only resolution path that handles both an explicit furnisher deletion and an unverified silence. The dispute transitions to `CLOSED_DELETED`. The tradeline's `payment_status` is set to `DELETED` and its `verification_status` is set to `DELETED`; the owning report's `fico_score` is then recomputed per §3.5. The system creates a `ResultNotice` with `outcome` of `DELETED`, `free_report_granted` set to true, the matching `issued_day`, the mirrored `delivery_channel`, and a `summary`; the consumer's `free_reports_remaining` is bumped per the free-report-grant calculation in §3.6. The report's `posture` is recomputed at the end.

A separate operator action handles the frivolous-dispute path. A `BureauOperator` may dismiss a dispute as frivolous directly from the `RECEIVED` state — without forwarding it to a furnisher — provided the dispute is the fourth or later submission by the same consumer on the same `tradeline_item_id` within the trailing 365 logical days. The dispute transitions from `RECEIVED` to `CLOSED_DISMISSED`. The system writes `investigation_outcome` of `DISMISSED_FRIVOLOUS`, creates a `ResultNotice` with `outcome` of `DISMISSED_FRIVOLOUS` and `free_report_granted` of false, and recomputes the report's `posture`. The `summary`, `issued_day`, and `delivery_channel` are populated as above.

Two simultaneous resolution paths on the same dispute serialize on the `Dispute.status` row. A bureau operator's issue-result-notice request and a sweep that flips the same dispute's furnisher response to `NO_RESPONSE` cannot both commit: exactly one wins, and the loser is rejected with `ERR_INVALID_STATE_TRANSITION` because the dispute has already left `RESULTS_PENDING` by the time the loser's request acquires the row.

The issued result notice can be fetched separately under a result-notice retrieval endpoint, returning the persisted `dispute_id`, `issued_day`, `delivery_channel`, `outcome`, `free_report_granted`, and `summary`.

### 3.5. The FICO Calculation

The `CreditReport.fico_score` is a weighted score over the report's owned tradelines, recomputed on every `TradelineItem` mutation (whether through a dispute closure or a direct change) and on demand for the projected-FICO endpoint described later in this subsection. The calculation runs over a working set T defined as the report's owned tradelines whose `payment_status` is not `DELETED`; a tradeline marked `DELETED` is excluded entirely.

Each tradeline in T is assigned a payment score derived from its `payment_status`: `CURRENT` contributes 100, `LATE_30` contributes 70, `LATE_60` contributes 40, `LATE_90` contributes 20, `CHARGE_OFF` contributes 0, and `COLLECTION` contributes 0. The payment-history component is the arithmetic mean of these per-item payment scores. If T is empty after the deletion exclusion, the payment-history component is defined to be 100 rather than undefined.

The utilization component is derived from the total balance carried across T. First, compute the total balance as the sum of `balance_cents` across every tradeline in T. The denominator for the utilization ratio is the count of tradelines in T multiplied by 1,000,000 cents (a nominal per-item credit limit of $10,000), with a floor of 1 on the denominator to avoid division by zero when T is empty. Compute the utilization percentage as the total balance divided by that denominator, multiplied by 100, with the result capped at 100. The utilization score is then 100 minus the utilization percentage, with a floor of 0. If T is empty, the utilization score is defined to be 100.

Three further components contribute. The age component is held constant at 100 in this version of the system (the scenario does not yet model account age). The mix component is 50 when T contains exactly one item — penalizing single-item portfolios for lack of mix — and 100 otherwise. The recent-inquiries component is derived from the count of `HardInquiry` records on this report whose `outcome` is `ACCEPTED`; the inquiries score is 100 minus 20 times that count, with a floor of 0.

These five components are combined with fixed weights: the payment-history component carries weight 0.35, the utilization component carries weight 0.30, the age component carries weight 0.15, the mix component carries weight 0.10, and the recent-inquiries component carries weight 0.10. Each component is multiplied by its weight as a floating-point value; the five weighted contributions are summed as floating-point; the sum is then multiplied by 5.5 and shifted by adding 300; the resulting value is rounded half-up exactly once, at the very end. No per-component rounding is permitted — alternative orderings (such as rounding each weighted component to an integer before summing) would diverge from the canonical score by ±1 in many cases and are not accepted. After the single final rounding, the result is clamped to the inclusive range from 300 to 850.

The FICO calculation has two variants. The final variant is what is persisted to `CreditReport.fico_score` on every `CLOSED_*` dispute transition; it uses only post-transition (committed) tradeline state with the actual furnisher response applied. If the in-flight dispute closed `VERIFIED`, the targeted tradeline is unchanged; if it closed `DISMISSED_FRIVOLOUS`, the targeted tradeline is also unchanged. The provisional variant is what a consumer sees when invoking the projected-FICO retrieval against a report that currently has at least one dispute in a non-terminal status: the calculation simulates the in-flight dispute resolving in the consumer's favor by applying the dispute's `requested_payload` to the targeted tradeline as if the furnisher had responded `UPDATED`, or — when the `requested_action` is `DELETE_ITEM` — by treating the targeted tradeline as if its `payment_status` were `DELETED`. The provisional variant always includes the in-flight dispute's projected outcome, even when no `FurnisherInquiry` response yet exists. Both variants apply the same rounding and clamping rule described above.

### 3.6. The Dispute Risk Score and the Free-Report Grant

Two further calculations attach to consumer behavior. The dispute risk score is a consumer-scoped metric that summarizes recent dispute activity. Its inputs are: the count of disputes the consumer has submitted in the trailing 365 logical days; the count of those that closed as `CLOSED_DISMISSED`; the count of those that have ever transitioned through `ESCALATED`; and a boolean indicating whether the dispute in question carries any supporting documents. The raw score is computed by adding twice the trailing-365 dispute count, plus five times the trailing-365 dismissed count, plus three times the trailing-365 escalated count, and then subtracting one when supporting documents are present (and adding zero when they are absent). The raw score is multiplied by 10. The result is then clamped to the inclusive range from 0 to 100. All arithmetic is integer; no rounding is required. The dispute risk score also has two variants. The provisional variant is computed when a dispute is submitted, before the new dispute row is committed; it excludes the dispute currently being submitted from the trailing-365 counts and is used by the frivolous-threshold check at submission time. The final variant is computed on each subsequent transition of the now-committed dispute and is what surfaces on the consumer-risk retrieval endpoint.

The free-report grant is the FCRA-mandated remedy when a dispute outcome actually changed the tradeline. Three inputs interact non-linearly: the dispute's `outcome` (the grant fires only when the outcome is `UPDATED` or `DELETED`), whether the tradeline was actually mutated (the grant fires only when an `UPDATED` outcome actually changed `balance_cents`, `payment_status`, or `reported_dofd_day`, or when a `DELETED` outcome actually flipped `payment_status` to `DELETED`), and whether the consumer currently has any `CreditFreeze` in `ACTIVE` status (which selects the grant tier). When both the outcome gate and the change gate are satisfied, the grant size is two reports for a consumer with any active freeze and one report otherwise — the rationale being that a frozen consumer recovering from identity theft earns double credit per successful dispute change. The new value of `free_reports_remaining` is the existing value plus the tier-selected grant, capped at the inclusive maximum of 12. When either gate fails, `free_reports_remaining` is unchanged.

### 3.7. The Posture Calculation

Each `CreditReport` carries a `posture` field with three possible values, recomputed every time a dispute or freeze that affects the report changes state. The calculation evaluates two counts. The first count is the number of disputes on this report whose `status` is one of `RECEIVED`, `UNDER_INVESTIGATION`, `RESULTS_PENDING`, or `ESCALATED`. The second count is the number of `CreditFreeze` rows for this consumer and this bureau whose `status` is `ACTIVE`. If the active-freezes count is greater than zero, the posture is `FROZEN`. Otherwise, if the active-disputes count is at least one, the posture is `RESTRICTED`. Otherwise — that is, only when the active-disputes count is exactly zero — the posture is `OPEN`. The boundary between `RESTRICTED` and `OPEN` is precise: a single active dispute is enough to flip the posture to `RESTRICTED`, and the posture returns to `OPEN` only when no non-terminal disputes remain.

### 3.8. The Deadline Day Calculation

The deadline-day field on a `Dispute` carries three potentially circular dependencies (its own value, the `additional_info_accepted` flag, and the furnisher's `reverification_deadline_day`), and the system breaks the cycle by pinning a strict evaluation order. Step one: compute the base deadline as `submitted_day` plus thirty — the FCRA base window of thirty days. Step two: if `additional_info_accepted` is true and the step-one base had not yet expired at the moment additional info was accepted (that is, the current clock `day` at acceptance was less than or equal to the step-one base), the extended deadline is `submitted_day` plus forty-five (thirty plus a fifteen-day extension); otherwise the extended deadline equals the step-one base. Step three: `reverification_deadline_day` is independently computed as `forwarded_day` plus twenty-five and does not move when the bureau's deadline is extended — the furnisher response window is twenty-five logical days regardless of any consumer extension. Step four: on the CFPB reopen cascade described in §3.10, the dispute's `deadline_day` is set to the current clock `day` plus thirty (a fresh investigation clock independent of `submitted_day`) and `additional_info_accepted` is reset to false.

### 3.9. Result Notice Retrieval and Free Report Consumption

A consumer who needs to read the issued result notice does so by retrieving the result-notice resource scoped under the consumer and the dispute; the response carries `dispute_id`, `issued_day`, `delivery_channel`, `outcome`, `free_report_granted`, and the human-readable `summary`. The bureau operator and the platform admin may read the same notice.

A consumer consumes a free report by invoking the pull-free action on a specific `CreditReport`. The system rejects the action when the consumer's `free_reports_remaining` is at or below zero, returning `ERR_NO_FREE_REPORTS_REMAINING`. On success, the system decrements `free_reports_remaining` by one and stamps `last_pulled_day` with the current clock `day`. The action does not by itself mutate the report's `posture` or `fico_score`; those derive from disputes and tradelines.

### 3.10. Regulatory Escalation to CFPB

A consumer dissatisfied with a closed dispute may escalate it by filing a regulatory complaint. The escalation action is the create-regulatory-complaint operation on the consumer; the request body carries the `dispute_id` of the dispute being escalated, an optional `parent_complaint_id` that must be supplied if and only if this is a refile of a previously `REJECTED` complaint, an `agency` that defaults to `CFPB` (the only value supported in this version), and a free-form consumer `narrative` between 1 and 4,000 characters long. The dispute must currently be in `CLOSED_VERIFIED` or `CLOSED_DISMISSED`; if it is in any other state, the escalation is rejected with `ERR_NOT_ESCALATABLE`. At most one open regulatory complaint may exist per dispute — "open" meaning the complaint's `status` is either `FILED` or `UNDER_REVIEW`. A second open complaint is rejected with `ERR_COMPLAINT_ALREADY_OPEN`, which is also the loser's error when two consumers race two complaint creations against the same dispute. A refile is permitted only via `parent_complaint_id` after the parent has been moved to `REJECTED`.

On successful filing, a `RegulatoryComplaint` is created with `status` of `FILED`, `filed_day` stamped from the current clock `day`, and the supplied `narrative` recorded. As a side effect of the filing, the underlying dispute transitions to `ESCALATED` (from `CLOSED_VERIFIED` or `CLOSED_DISMISSED`).

A `CFPBOperator` then resolves the complaint along one of two arms. The accept action transitions the complaint from `FILED` to `UNDER_REVIEW` and triggers the dispute-reopen cascade: the underlying dispute transitions from `ESCALATED` back to `UNDER_INVESTIGATION`; a fresh `FurnisherInquiry` is auto-created (with its own `forwarded_day` of the current clock `day` and `response` of `PENDING`); the dispute's `deadline_day` is reset to the current clock `day` plus thirty; and `additional_info_accepted` is reset to false. The reject action transitions the complaint from `FILED` directly to `REJECTED` and produces no side effects on the dispute. The resolve action transitions the complaint from `UNDER_REVIEW` to `RESOLVED`, but only when the underlying dispute is once again in one of the four terminal `CLOSED_*` states (so that the reopened investigation has actually been closed out); otherwise the resolve attempt is rejected with `ERR_DISPUTE_NOT_RECLOSED`.

### 3.11. Credit Freezes and Credit Locks

A consumer protects their credit file by placing a `CreditFreeze` for a specific `bureau`. On placement, the freeze's `status` is set to `ACTIVE`, its `placed_day` is stamped from the current clock `day`, and its `lifted_day` is left null. If this is the consumer's first freeze across any bureau, the system mints a `freeze_pin` on the `Consumer` and that PIN persists for all future freeze lifts. At most one `ACTIVE` `CreditFreeze` may exist per `(consumer_id, bureau)` pair; a second placement is rejected with `ERR_FREEZE_ALREADY_ACTIVE`, which is also the loser's error when two placements race in parallel. The placement also triggers a posture recomputation on the matching `CreditReport` per §3.7, flipping it to `FROZEN`.

A consumer lifts a freeze by supplying the previously minted `freeze_pin` in the request body's `pin` field. If the supplied `pin` does not equal the consumer's `freeze_pin`, the lift is rejected with `ERR_INVALID_FREEZE_PIN`. On success, the freeze's `status` flips to `LIFTED` and its `lifted_day` is stamped from the current clock `day`; the matching report's posture is then recomputed per §3.7 (typically returning to `OPEN` or `RESTRICTED` depending on whether any disputes remain active).

The credit lock is the consumer-convenience parallel to the freeze. A consumer engages a `CreditLock` for a specific `bureau`; on engagement, `status` is set to `LOCKED` and `locked_at_day` is stamped from the current clock `day`. At most one `LOCKED` `CreditLock` may exist per `(consumer_id, bureau)` pair; a second engagement is rejected with `ERR_LOCK_ALREADY_ACTIVE`. Unlike a freeze, a lock has no PIN: the consumer simply unlocks (transitioning the lock from `LOCKED` to `UNLOCKED`) or relocks (transitioning from `UNLOCKED` back to `LOCKED`) at will. The lock does not influence posture; it only gates hard inquiries.

### 3.12. Hard Inquiries

A `Furnisher` requests a hard pull against a specific `CreditReport` by invoking the hard-inquiry action on that report; the request body carries the `requesting_furnisher_id`. On request, the system creates a `HardInquiry` with `credit_report_id` of the targeted report, the supplied `requesting_furnisher_id`, an `inquiry_day` stamped from the current clock `day`, and one of three `outcome` values. If the matching `(consumer_id, bureau)` pair carries an `ACTIVE` `CreditFreeze`, the outcome is `BLOCKED_FREEZE` and the request is rejected with `ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE`. Otherwise, if the matching pair carries a `LOCKED` `CreditLock`, the outcome is `BLOCKED_LOCK` and the request is rejected with `ERR_HARD_INQUIRY_BLOCKED_BY_LOCK`. Only when neither a freeze nor a lock is in effect does the outcome record as `ACCEPTED`, and only `ACCEPTED` hard inquiries contribute to the inquiries score in the FICO calculation per §3.5.

### 3.13. Validation Priority Ordering

When multiple validation rules apply to the same endpoint, the system evaluates them in the strict priority order numbered below so that the highest-priority failure mode surfaces first and lower-priority checks are not even attempted. The order is: (1) `X-User-ID` and `X-User-Role` header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role authorization for the endpoint and consumer-scoped ownership of the resource (`ERR_FORBIDDEN_FOR_ROLE`); (3) existence of every path-segment identifier evaluated left to right (`ERR_NOT_FOUND`); (4) existence of body-referenced foreign keys belonging to the same consumer (`ERR_CROSS_CONSUMER_REFERENCE`); (5) the target resource being in a state from which the requested transition is allowed (`ERR_INVALID_STATE_TRANSITION`); (6) the report's `posture` not being `FROZEN` for start-investigation (`ERR_REPORT_FROZEN`); (7) the reage prohibition at result-notice issuance (`ERR_REAGE_PROHIBITED`); (8) the reage prohibition at furnisher-response recording (`ERR_REAGE_PROHIBITED`); (9) the dispute-deadline window for furnisher-response, issue-result-notice, and additional-info (`ERR_DISPUTE_DEADLINE_PASSED`); (10) the furnisher-reverification window (`ERR_FURNISHER_LATE`); (11) supporting documents present at submission and at start-investigation (`ERR_NO_SUPPORTING_DOCUMENTS`); (12) the frivolous-dispute threshold (`ERR_FRIVOLOUS_DISPUTE`); (13) at most one active dispute per tradeline (`ERR_DUPLICATE_ACTIVE_DISPUTE`); (14) freeze and lock gating of hard inquiries (`ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE` or `ERR_HARD_INQUIRY_BLOCKED_BY_LOCK`); (15) the freeze-lift PIN check (`ERR_INVALID_FREEZE_PIN`); (16) the escalation eligibility rule (`ERR_NOT_ESCALATABLE`); (17) at most one open regulatory complaint per dispute (`ERR_COMPLAINT_ALREADY_OPEN`); (18) at most one active freeze per `(consumer_id, bureau)` (`ERR_FREEZE_ALREADY_ACTIVE`); (19) at most one locked lock per `(consumer_id, bureau)` (`ERR_LOCK_ALREADY_ACTIVE`); (20) the annual free-report cap requiring `free_reports_remaining` to be strictly greater than zero (`ERR_NO_FREE_REPORTS_REMAINING`).

The boundary cases that follow from this ordering deserve special attention. A start-investigation attempt against a report whose `posture` is `FROZEN` and whose dispute also lacks supporting documents surfaces as `ERR_REPORT_FROZEN` (priority 6) and never reaches the supporting-documents check (priority 11). A regulatory-complaint creation against a `Dispute` that is both not in a `CLOSED_*` state and already has an open complaint surfaces as `ERR_NOT_ESCALATABLE` (priority 16) before the per-dispute uniqueness check (priority 17). An issue-result-notice attempt that is both past `deadline_day` and would violate the reage prohibition surfaces as `ERR_REAGE_PROHIBITED` (priority 7) ahead of `ERR_DISPUTE_DEADLINE_PASSED` (priority 9).

### 3.14. Report Archival

A `PlatformAdmin` archives a `CreditReport` by invoking the archive action on the report. The transition is from `ACTIVE` to `ARCHIVED` and is rejected if any `Dispute` on the report is in a non-terminal state (anything other than `CLOSED_VERIFIED`, `CLOSED_UPDATED`, `CLOSED_DELETED`, or `CLOSED_DISMISSED`), in which case `ERR_REPORT_HAS_OPEN_DISPUTES` is returned. There are no side effects beyond the status flip itself; archived reports remain readable but are no longer subject to further dispute submission.

## 4. Endpoint Definitions

All endpoints share the response-envelope conventions in §2.2. Operations that create new stand-alone resources or add a new distinct resource to a collection return a `201 Created`; operations that modify an existing resource — including state-machine transitions and consumed-action operations — return a `200 OK`. The 4xx status code returned alongside an error response is determined by the error code per §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/consumers` | Create a Consumer | PlatformAdmin |
| GET    | `/consumers/{consumerId}` | Get a Consumer | Consumer, PlatformAdmin |
| GET    | `/consumers/{consumerId}/risk` | Get the consumer's final-variant dispute risk score | Consumer, PlatformAdmin |
| POST   | `/furnishers` | Register a Furnisher | PlatformAdmin |
| GET    | `/furnishers/{furnisherId}` | Get a Furnisher | PlatformAdmin, BureauOperator, Furnisher |
| POST   | `/consumers/{consumerId}/credit_reports` | Create a CreditReport for a bureau | PlatformAdmin |
| GET    | `/consumers/{consumerId}/credit_reports/{creditReportId}` | Get a CreditReport (committed) | Consumer, PlatformAdmin |
| GET    | `/consumers/{consumerId}/credit_reports/{creditReportId}/projected_fico` | Compute the provisional FICO assuming all open disputes resolve in the consumer's favor | Consumer |
| POST   | `/consumers/{consumerId}/credit_reports/{creditReportId}/pull_free` | Consume a free-report grant and stamp last_pulled_day | Consumer |
| POST   | `/consumers/{consumerId}/credit_reports/{creditReportId}/archive` | Archive a CreditReport | PlatformAdmin |
| POST   | `/credit_reports/{creditReportId}/tradeline_items` | Add a TradelineItem | PlatformAdmin, Furnisher |
| GET    | `/credit_reports/{creditReportId}/tradeline_items/{tradelineItemId}` | Get a TradelineItem | Consumer, PlatformAdmin, BureauOperator, Furnisher |
| POST   | `/consumers/{consumerId}/disputes` | Submit a Dispute | Consumer |
| GET    | `/consumers/{consumerId}/disputes/{disputeId}` | Get a Dispute | Consumer, BureauOperator, PlatformAdmin |
| POST   | `/consumers/{consumerId}/disputes/{disputeId}/start_investigation` | Open the bureau investigation on a Dispute | BureauOperator |
| POST   | `/consumers/{consumerId}/disputes/{disputeId}/additional_info` | Submit additional supporting information (extends deadline to 45 days) | Consumer |
| POST   | `/consumers/{consumerId}/disputes/{disputeId}/furnisher_response` | Record the furnisher's reverification response | BureauOperator |
| POST   | `/consumers/{consumerId}/disputes/{disputeId}/issue_result_notice` | Issue the written result notice and close the dispute | BureauOperator |
| POST   | `/consumers/{consumerId}/disputes/{disputeId}/dismiss_frivolous` | Dismiss a frivolous Dispute without forwarding | BureauOperator |
| GET    | `/consumers/{consumerId}/disputes/{disputeId}/result_notice` | Fetch the issued ResultNotice | Consumer, BureauOperator, PlatformAdmin |
| POST   | `/consumers/{consumerId}/regulatory_complaints` | File a CFPB regulatory complaint escalating a Dispute | Consumer |
| GET    | `/regulatory_complaints/{complaintId}` | Get a RegulatoryComplaint | Consumer, CFPBOperator, PlatformAdmin |
| POST   | `/regulatory_complaints/{complaintId}/accept` | CFPB accepts the complaint, reopening the underlying Dispute | CFPBOperator |
| POST   | `/regulatory_complaints/{complaintId}/reject` | CFPB rejects the complaint | CFPBOperator |
| POST   | `/regulatory_complaints/{complaintId}/resolve` | CFPB marks the complaint resolved | CFPBOperator |
| POST   | `/consumers/{consumerId}/credit_freezes` | Place a CreditFreeze | Consumer |
| GET    | `/consumers/{consumerId}/credit_freezes/{freezeId}` | Get a CreditFreeze | Consumer, PlatformAdmin |
| POST   | `/consumers/{consumerId}/credit_freezes/{freezeId}/lift` | Lift a CreditFreeze with the PIN | Consumer |
| POST   | `/consumers/{consumerId}/credit_locks` | Engage a CreditLock | Consumer |
| POST   | `/consumers/{consumerId}/credit_locks/{lockId}/unlock` | Unlock a CreditLock | Consumer |
| POST   | `/consumers/{consumerId}/credit_locks/{lockId}/relock` | Relock a CreditLock | Consumer |
| POST   | `/credit_reports/{creditReportId}/hard_inquiries` | Furnisher requests a hard pull | Furnisher |
| POST   | `/_clock/advance` | Advance the logical clock by `days` (test-driving) | PlatformAdmin |
| GET    | `/_clock` | Read the current clock `day` | PlatformAdmin, Consumer, BureauOperator, Furnisher, CFPBOperator |
| POST   | `/_sweep/run` | Run the daily sweep (materializes furnisher-deadline non-responses) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_FREEZE_PIN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_NO_SUPPORTING_DOCUMENTS` | 422 Unprocessable Entity |
| `ERR_CROSS_CONSUMER_REFERENCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_DISPUTE` | 409 Conflict |
| `ERR_FRIVOLOUS_DISPUTE` | 409 Conflict |
| `ERR_DISPUTE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_FURNISHER_LATE` | 409 Conflict |
| `ERR_REAGE_PROHIBITED` | 409 Conflict |
| `ERR_REPORT_FROZEN` | 409 Conflict |
| `ERR_REPORT_HAS_OPEN_DISPUTES` | 409 Conflict |
| `ERR_NOT_ESCALATABLE` | 409 Conflict |
| `ERR_COMPLAINT_ALREADY_OPEN` | 409 Conflict |
| `ERR_DISPUTE_NOT_RECLOSED` | 409 Conflict |
| `ERR_FREEZE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_LOCK_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE` | 409 Conflict |
| `ERR_HARD_INQUIRY_BLOCKED_BY_LOCK` | 409 Conflict |
| `ERR_NO_FREE_REPORTS_REMAINING` | 409 Conflict |

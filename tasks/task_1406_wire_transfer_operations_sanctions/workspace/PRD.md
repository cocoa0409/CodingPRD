# Wire Transfer Operations & Sanctions Screening API — Product Requirements Document

## 1. Introduction

A bank's wire room is where irreversible money meets reversible mistakes. Every outgoing payment crosses three desks before the network accepts it — an operator who keys the instruction, an approver pair who certify it, and a sanctions desk that answers for every name on the payment — and a fourth and fifth desk wait downstream for the wires that go wrong: fraud response and investigations. This document specifies the Wire Transfer Operations & Sanctions Screening API, the system of record for that room. It governs payment initiation with threshold-driven callback verification, dual approval under strict segregation of duties, cutoff-time processing keyed to an explicit ops-day calendar, sanctions and watchlist hit disposition with tiered authority, straight-through-processing exception repair, recall and return negotiation with beneficiary banks, fraud holds with customer confirmation, fee assessment with correspondent charge allocation, and investigations with a bounded tracer loop.

Two design commitments shape everything that follows. First, every wire carries **two independent state dimensions**: a processing status that walks from initiation toward execution, and a screening status that answers the sanctions question in parallel. The two dimensions evolve on separate triggers and intersect only at well-defined gates — a wire may not be released until its screening dimension says `CLEAR`, no matter how clean its processing dimension looks. Second, segregation of duties is enforced structurally, not procedurally: the operator who initiated a wire can never approve it, two distinct approvers must each leave an approval record, sanctions disposition authority is split by hit tier between a screener and a compliance officer, and no single actor can both hold a wire for fraud and clear that hold without a recorded customer outcome. Auditors and regulators read everything through an append-only log; nobody edits the past.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_AUTH`. A request whose role is not permitted for the target endpoint — including disposition-tier mismatches on sanctions hits, where the permitted role depends on the hit's current state — is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly ten roles, spelled as follows: `WireOpsAdmin`, `WireOperator`, `WireApprover`, `SanctionsScreener`, `ComplianceOfficer`, `FraudAnalyst`, `RepairSpecialist`, `WireInvestigator`, `BeneficiaryBank`, and `Auditor`.

For every role in this system, `X-User-ID` is an **opaque operator identifier** — it is not the `id` of any persisted entity, and the server never compares it against an entity's `id`. The server does, however, record the actor's `X-User-ID` onto resources where a workflow attributes an action: it is stored as `initiated_by` on a wire at initiation, as `approver_user_id` on each approval record (and mirrored into the wire's `first_approved_by` and `second_approved_by` as approvals accumulate), as `decided_by` on a sanctions hit at disposition, as `placed_by` on a fraud hold at placement, and as `opened_by` on an investigation at opening. These attributions, plus the `actor_user_id` and `actor_role` captured on every audit entry, are the segregation-of-duties evidence trail; none of them confer ownership semantics on any entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Audit Trail

Every primary resource — customers, accounts, beneficiaries, business dates, wires, approval records, callback verification cases, sanctions hits, fraud holds, recall requests, fee assessments, correspondent charges, investigations, and tracer messages — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every mutation, usable for optimistic concurrency control.

The audit log is the deliberate exception. An `AuditLogEntry` is append-only evidence: it carries `id` and `created_at` only, and has **no** `updated_at` and **no** `version` field, because an audit record is never mutated after it is written. Each entry records the `actor_user_id` and `actor_role` of the actor, an `action` label such as `wire.approve` or `sanctions.release`, the `entity_type` and `entity_id` of the affected resource (the latter serving identity only, carrying no business semantics), a `wire_id` whenever the action concerns a wire (null otherwise), and a free-text `detail` field that includes before/after states. Entries are ordered by creation time when listed, and may be filtered by `wire_id` or `entity_type`.

### 2.5. The Logical Clock, Lazy Expiry, and the Ops-Day Posture

The server evaluates every time window in this document — callback verification windows, fraud-hold confirmation windows, recall response windows, and the trailing thirty-day velocity window — against a **logical clock**, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `WireOpsAdmin` may advance it by supplying a target instant via `to_iso8601`; the clock is then pinned at that instant and never falls back to wall-clock time. Test-driving the clock is an administrator-only capability and returns the current logical instant as `current_utc`.

Expiry is enforced **lazily**: the system does not run a background sweeper. Instead, whenever an expirable case — a callback verification case, a fraud hold, or a recall request — or its parent wire is accessed, the system first compares the current logical time against the case's deadline and, if the deadline has been reached, applies the auto-resolution transition before answering. The boundary is strict in every case: *at or after* the deadline instant, the window is closed.

Overlaid on the clock is the ops-day calendar. A **BusinessDate** record represents one operations day, identified by a unique `business_date` in ISO `YYYY-MM-DD` form, and walks a three-state posture machine: `OPEN`, then `CUTOFF_PASSED`, then `CLOSED`. Only an `OPEN` date may have its cutoff closed — attempting to close the cutoff on a date in any other posture is rejected with `ERR_CUTOFF_ALREADY_PASSED`. From the moment a date's cutoff passes, no wire may be submitted or released against that date; the rejection code is `ERR_CUTOFF_PASSED`. Closing the day itself is the end-of-day reconciliation step: it requires the date to be in `CUTOFF_PASSED` and requires that no wire carry that `value_date` in any non-terminal processing status (`INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `APPROVED`, `RELEASING`, or `REPAIR`); either violation is rejected with `ERR_INVALID_STATE`. Both cutoff closure and day closure are audit-logged.

### 2.6. Reservation Accounting and the Daily Outgoing Limit

Each account enforces a business-day cap on executed outgoing principal through two running aggregates. `daily_reserved_cents` is the sum of `amount_cents` over the account's wires dated to the current business date whose `reservation_active` flag is true — money committed but not yet released. `daily_released_cents` is the sum of `amount_cents` over the account's wires dated to the current business date that have reached `EXECUTED`. Both aggregates start at zero when an account is opened, and `daily_outgoing_limit_cents` — a strictly positive integer supplied when the account is created — caps the executed tally.

The reservation lifecycle is exact. Submission creates a reservation: the wire's `reservation_active` becomes true and the wire's `amount_cents` is added to the ordering account's `daily_reserved_cents`. Release converts the reservation: at the moment the release call dispatches to the network, the reservation is deactivated and the same `amount_cents` moves from `daily_reserved_cents` into `daily_released_cents`, so principal counts exactly once against the limit on the current business date. Any path that ends a wire before execution — rejection, cancellation from `PENDING_APPROVAL` or `REPAIR`, or a sanctions confirmation that rejects the wire — releases the reservation by subtracting the wire's `amount_cents` (the current, post-repair amount where a repair changed it) from `daily_reserved_cents` and setting `reservation_active` to false.

The limit check itself fires inside the release call, at the dispatch boundary. Let the account's available headroom be `daily_outgoing_limit_cents` minus `daily_released_cents`. Execution proceeds if and only if the available headroom is greater than or equal to the wire's `amount_cents`. The boundary is inclusive: headroom exactly equal to the wire's principal is allowed, while headroom one cent short rejects the entire release with `ERR_DAILY_LIMIT_EXCEEDED`. A failed check aborts the release **atomically**: the wire remains in `APPROVED`, its reservation stays active, and the account's `daily_reserved_cents` is left unchanged, so the operator can remediate the limit and release again without re-keying anything.

### 2.7. Optimistic Concurrency Control on Wire Writes

Three write endpoints against a wire carry a mandatory optimistic-concurrency field, and no other endpoint in the API takes a version field. Approving a wire, releasing a wire, and repairing a wire each require the request body to include `expected_wire_version`, carrying the wire's `version` as the client last observed it. If the value does not equal the wire's current `version` — because another writer has meanwhile acted on the wire (a first approval recorded, a repair submitted, a cancellation, a hold placed, or a screening-driven rejection) — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This stale-view check is evaluated immediately after existence and request-schema checks and **before** any state or business rule, so a client acting on a superseded view learns about the staleness even when a business gate would also have failed. Endpoints not named here do not accept a version field at all.

### 2.8. Validation Order Across the API

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the first failure determines the error returned. The order, from first to last, is: (1) header presence — `ERR_MISSING_AUTH`; (2) role authorization, including the disposition-tier split on sanctions hits — `ERR_FORBIDDEN_ROLE`; (3) existence of every path identifier, validated left-to-right, and of every body-supplied foreign reference such as `ordering_account_id`, `beneficiary_id`, `wire_id`, or `investigation_id` — `ERR_NOT_FOUND`; (4) request-body schema conformance — required fields present, types correct, enum values in their declared domains, amount fields strictly positive, unknown keys rejected — `ERR_INVALID_REQUEST`; then the business rules in their stated relative order — (5) cross-aggregate beneficiary/account consistency on wire creation (`ERR_BENEFICIARY_ACCOUNT_MISMATCH`), (6) account and beneficiary active-status gates on wire creation (`ERR_ACCOUNT_INACTIVE` / `ERR_BENEFICIARY_INACTIVE`), (7) the frozen-customer initiation gate (`ERR_CUSTOMER_FROZEN`), (8) the submit-time cutoff gate (`ERR_CUTOFF_PASSED`), (9) the optimistic-concurrency stale-view check (`ERR_STALE_VERSION`), (10) the generic state precondition on action endpoints (`ERR_INVALID_STATE`), (11) the callback-verification gate on submit (`ERR_CALLBACK_NOT_VERIFIED`), (12) segregation of duties on approval (`ERR_SOD_APPROVER_MISMATCH`), (13) hit-resolved state on dispositions (`ERR_HIT_ALREADY_RESOLVED`), (14) the hold gate (`ERR_WIRE_ON_HOLD`), (15) the screening gate on release (`ERR_SANCTIONS_NOT_CLEARED`), (16) the release-time cutoff gate (`ERR_CUTOFF_PASSED`), (17) the daily-limit check (`ERR_DAILY_LIMIT_EXCEEDED`), then the temporal windows — (18) callback record (`ERR_CALLBACK_WINDOW_EXPIRED`), (19) fraud-hold confirmation (`ERR_FRAUD_HOLD_WINDOW_EXPIRED`), (20) recall respond (`ERR_RECALL_EXPIRED`) — then the recall lifecycle rules — (21) `ERR_RECALL_ALREADY_RESOLVED`, (22) `ERR_RECALL_NOT_RETURNED`, (23) `ERR_RECALL_AMOUNT_EXCEEDS`, (24) `ERR_RECALL_IN_PROGRESS` — then the repair and tracer caps — (25) `ERR_REPAIR_LIMIT_EXCEEDED`, (26) `ERR_TRACER_LIMIT_EXCEEDED` — then the cutoff-closure posture (`ERR_CUTOFF_ALREADY_PASSED`), and finally the settlement gates on customer close and unfreeze (`ERR_CUSTOMER_NOT_SETTLED` / `ERR_CUSTOMER_STILL_FROZEN`), account close (`ERR_ACCOUNT_NOT_SETTLED`), and beneficiary retire (`ERR_BENEFICIARY_IN_USE`). One consequence worth internalizing: a release attempted against a wire that is simultaneously on hold, unscreened, past cutoff, and over the daily limit surfaces `ERR_WIRE_ON_HOLD`, because the hold gate outranks the others.

### 2.9. Nested Resource Retrieval and Path Validation

Requests that target a resource nested under another in the URL — for example a wire-scoped collection such as the callbacks, sanctions hits, fraud holds, charges, fees, or approvals of a specific wire — validate path identifiers strictly left-to-right. The first identifier in the path that does not correspond to an existing resource determines the `ERR_NOT_FOUND` rejection; the server does not proceed to validate later identifiers or body content against a request whose container does not exist. The same existence-first discipline applies to foreign references supplied in a request body: a body that names a non-existent account, beneficiary, wire, or investigation is rejected with `ERR_NOT_FOUND` at the existence priority, ahead of any schema or business rule.

### 2.10. Money, Precision, and Rounding

All monetary values in this system are integers denominated in **cents**: wire principal (`amount_cents`), account aggregates, fee components, and charge amounts are all whole-cent integers, and all arithmetic is integer arithmetic with no decimal representation at any point. Where a calculation must take a fractional share of a cent-denominated amount — the beneficiary-pays share of a base fee, or the bank-absorbed share of a deducted-from-principal charge — the product is rounded **half-up to whole cents per line** before any summation. Rounding is never deferred to a final total: each charge line is rounded independently, then the rounded lines are summed. The currency domain of the system is USD only, recorded as the string `USD` on accounts and wires.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Relationship: Customers, Accounts, and Beneficiaries

A `WireOpsAdmin` onboards a customer by registering its `legal_name`, a `risk_rating` of `LOW`, `MEDIUM`, or `HIGH`, and an optional `high_risk_jurisdiction` flag that defaults to false and feeds the geographic component of the wire risk score. A customer is born `ACTIVE` and walks the lifecycle `ACTIVE → FROZEN → ACTIVE` or `ACTIVE → CLOSED`; the timestamp `frozen_at` records when the customer entered `FROZEN`, is null while the customer is `ACTIVE`, and is cleared back to null on unfreeze. Freezing a customer is an administrator action that sets `frozen_at` and writes an audit entry, and it also happens automatically when a fraud hold on one of the customer's wires resolves as confirmed fraud. Unfreezing requires the customer to be `FROZEN` and requires that no `OPEN` fraud hold remain on any wire ordered by any account of the customer — otherwise the request is rejected with `ERR_CUSTOMER_STILL_FROZEN`. Closing a customer requires `ACTIVE` status and requires that no wire in a non-terminal processing status exist on any of the customer's accounts; the rejection code is `ERR_CUSTOMER_NOT_SETTLED`.

Accounts are opened by an administrator against an existing customer, naming the owning `customer_id`, an `account_number` that must be unique across all accounts, an optional `currency` that defaults to `USD`, and the strictly positive `daily_outgoing_limit_cents`. An account opens `ACTIVE` with both daily aggregates zeroed. An administrator may mark an `ACTIVE` account `DORMANT` — any other starting state is `ERR_INVALID_STATE` — and a dormant account reactivates to `ACTIVE` automatically the first time one of its wires reaches `EXECUTED`. Closing an account requires `ACTIVE` status, requires that no non-terminal wire reference the account, and requires `daily_reserved_cents` to be zero; violations are `ERR_ACCOUNT_NOT_SETTLED`.

A `WireOperator` or an administrator registers a **beneficiary** against a customer — the originator who will be allowed to pay this counterparty — supplying the beneficiary's `name` and its bank's `bank_name` (both of which are screened text on subsequent wires), the beneficiary `account_number`, and the ISO-3166 alpha-2 `country_code` of the beneficiary bank. A beneficiary is born `ACTIVE` with `first_used_at` null; that timestamp is stamped the first time a wire paying this beneficiary on any account of the owning customer reaches `EXECUTED`, and it drives the new-beneficiary component of the risk score. Retiring a beneficiary moves it from `ACTIVE` to its terminal `RETIRED` status; it requires `ACTIVE` status and that no wire in a non-terminal status reference it, else `ERR_BENEFICIARY_IN_USE`. Customer, account, and beneficiary resources are individually retrievable and listable — the customer list filters by `status`, the account list by `customer_id` or `status`, the beneficiary list by `customer_id` or `status` — and an account roster or beneficiary roster for one customer can be read through the customer.

### 3.2. Initiating a Wire: Thresholds, Callbacks, and the Cross-Aggregate Gate

A `WireOperator` initiates a wire by naming the debit account through `ordering_account_id`, the payee through `beneficiary_id`, the principal `amount_cents` (strictly positive), the payment rail `method` — one of `Fedwire`, `SWIFT`, or `CHIPS` — and a free-text `purpose`. Three optional knobs refine the instruction: `currency` (defaulting to `USD`), `priority` (`NORMAL` by default, or `SAME_DAY` for an expedited dispatch that later attracts a surcharge), and `charge_mode` (`OUR` by default, or `BENEFICIARY_REMUNERATION`, which activates the beneficiary-pays fee share on `SWIFT` wires). The initiator's identity is stamped onto the wire as `initiated_by`, and initiation is audit-logged.

Wire creation enforces a fixed gauntlet before any state is assigned, evaluated in the validation order of §2.8: the beneficiary's owning `customer_id` must equal the ordering account's `customer_id` — a cross-aggregate consistency rule whose violation is `ERR_BENEFICIARY_ACCOUNT_MISMATCH`; both the ordering account and the beneficiary must be `ACTIVE`, else `ERR_ACCOUNT_INACTIVE` or `ERR_BENEFICIARY_INACTIVE` respectively; and the ordering customer must be `ACTIVE` — a `FROZEN` or `CLOSED` customer cannot initiate new wires, rejected as `ERR_CUSTOMER_FROZEN`.

The callback requirement is decided at creation by principal size alone. A wire whose `amount_cents` is at least one million dollars — one hundred million cents, with the boundary inclusive so that exactly $1,000,000.00 requires a callback — has its computed `requires_callback` flag set true and enters `CALLBACK_PENDING` rather than `INITIATED`; its `callback_status` becomes `PENDING`, and the system opens a `CallbackVerification` case in `OPEN` status stamped with `opened_at` at creation and an `expires_at` exactly four hours later. A wire below the threshold enters `INITIATED` with `callback_status` `NONE` and no case. The four-hour window is strict: at or after `expires_at`, an `OPEN` case auto-expires under the lazy-expiry rule of §2.5, and expiry cancels the wire, resets its `callback_status` to `NONE`, and writes an audit entry.

While the case is `OPEN`, the operator records outcomes against it, each recording carrying the reached `contact_name`, the `contact_phone` used, and an `outcome` of `CONFIRMED`, `DENIED`, or `UNREACHABLE`. Recording is only possible while the case is `OPEN` (else `ERR_INVALID_STATE`) and strictly before `expires_at` — at or after the deadline the attempt is rejected with `ERR_CALLBACK_WINDOW_EXPIRED`, because the case has in fact already auto-expired. A `CONFIRMED` outcome resolves the case at `resolved_at`, moves it to `CONFIRMED`, and sets the wire's `callback_status` to `VERIFIED`. A `DENIED` outcome resolves the case as `DENIED` and is fatal to the wire: the wire transitions to `CANCELLED`, its `callback_status` resets to `NONE`, and the denial is audit-logged. An `UNREACHABLE` outcome is explicitly non-terminal: the case remains `OPEN` and retryable until the window lapses. Separately, an operator who cancels the wire while its case is still `OPEN` supersedes the case — it transitions to `SUPERSEDED` — as part of the cancellation.

### 3.3. Submission, Screening, and the Risk Score

Submission moves a wire from `INITIATED` — or from `CALLBACK_PENDING` once verification is satisfied — into `PENDING_APPROVAL`. The operator names the intended ops day through `business_date`, which must identify an existing business-date record (an unknown date fails at the existence priority with `ERR_NOT_FOUND`) and that date must be `OPEN`; a date in `CUTOFF_PASSED` or `CLOSED` rejects the submission with `ERR_CUTOFF_PASSED`. The named date is stamped onto the wire as its computed `value_date`.

Two more gates guard submission from the `CALLBACK_PENDING` side. The wire's `callback_status` must be `VERIFIED` — or `WAIVED`, as described next — otherwise the submission is rejected with `ERR_CALLBACK_NOT_VERIFIED`. The waiver path exists for low-risk relationships only: a request carrying `waive_callback` set to true is honored when the ordering customer's `risk_rating` is `LOW`, sets the wire's `callback_status` to `WAIVED`, and is recorded in the audit log; the same flag on a wire for a customer of any other risk rating is rejected with `ERR_INVALID_REQUEST`.

Every submission runs sanctions screening and computes the wire's `risk_score`, an integer from 0 to 100 that is recomputed identically at every repair. The score is the sum of five components, clamped into the 0–100 range after summation. The amount band contributes nothing when the principal is below one million dollars, 25 points when the principal is at least one million dollars but below five million dollars, and 40 points when it is at least five million dollars. The geographic component contributes 20 points when the ordering customer's `high_risk_jurisdiction` flag is set, and nothing otherwise. The watchlist component contributes 15 points per unresolved sanctions hit — hits in `OPEN` or `ESCALATED` status at scoring time — capped at 30 points. The velocity component contributes 15 points when the sum of `amount_cents` over this account's wires that reached `EXECUTED` within the trailing thirty days — the window includes executions whose `executed_at` falls at or after thirty days before the current logical instant and at or before the current instant — is strictly greater than ten million dollars, and nothing otherwise. The behavior component contributes 10 points when the ordering account is `DORMANT`, and a further 10 points when the beneficiary is new.

The new-beneficiary term has two readings, and the wire's rail chooses between them. By default the term is taken when the beneficiary record's `first_used_at` is still null. When the wire travels by `SWIFT`, the cross-border convention applies instead: the term is taken whenever the beneficiary's **bank** — identified by the combination of `bank_name` and `country_code` — has never appeared on a prior `EXECUTED` wire of this account, even if this beneficiary record's `first_used_at` is already set. The two readings diverge exactly on wires whose beneficiary record is reused but whose bank is new to the account, and vice versa.

Screening moves the wire's `screening_status` from `NOT_SCREENED` to `CLEAR` when no unresolved sanctions hit exists for the wire and the computed `risk_score` is below fifty. It moves to `REVIEW` when an unresolved hit exists **or** the score is at least fifty — the threshold is inclusive at fifty. So that every `REVIEW` has a uniform disposition path, a risk-driven review with no party match creates one synthetic hit naming the `INTERNAL_WATCH` list, with the literal text `RISK_THRESHOLD` as its `matched_party`, the wire's `risk_score` as its `match_score`, and `OPEN` status. Hits otherwise record which watchlist matched — `OFAC_SDN`, `INTERNAL_WATCH`, or `EU_CONSOLIDATED` — the party text that matched in `matched_party` (beneficiary name, bank, or ordering customer), and the screening engine's `match_score` from 0 to 100. One further intersection with the processing dimension: when screening lands a wire in `REVIEW` while the wire is already `APPROVED` and carrying no hold, the wire's `hold_reason_code` is set to `SANCTIONS_HOLD`; an existing `FRAUD_HOLD` is never overwritten.

A successful submission finishes by stamping `value_date`, activating the reservation (§2.6), and incrementing the wire's `version` by one.

### 3.4. Dual Approval, Repair, and the Segregation of Duties

Approval is a two-step accumulation on the wire rather than a status walk on any record. While a wire sits in `PENDING_APPROVAL`, a `WireApprover` records an approval; each such call requires `expected_wire_version` per §2.7, and a stale view is rejected with `ERR_STALE_VERSION` before any other business rule runs. Two segregation-of-duties constraints then apply to the actor: the approver must not be the wire's `initiated_by`, and the approver must not already hold a non-superseded approval record for this wire's current repair round. Either violation is rejected with `ERR_SOD_APPROVER_MISMATCH`. A valid first approval creates an `ApprovalRecord` in its `RECORDED` state with `sequence` `FIRST`, stamps the wire's `first_approved_by` with the actor, and increments the wire's `version`. A valid second approval — by a different approver who is likewise neither the initiator nor the first approver — creates the `SECOND` record, stamps `second_approved_by`, transitions the wire from `PENDING_APPROVAL` to `APPROVED`, and increments the wire's `version`. Every record captures the wire's `wire_id`, its `sequence` step, its `approver_user_id`, and its `decided_at` timestamp, and starts with `superseded` false; once recorded, an approval record is immutable evidence — it is never edited, only superseded by a later resubmission. An approver may instead reject a wire pending approval, supplying a `reason`; rejection moves the wire to `REJECTED`, releases its reservation back to the account, and is audit-logged.

Straight-through-processing exceptions are handled by a `RepairSpecialist`. Repairing a wire — allowed only from `PENDING_APPROVAL`, and only while the wire's `repair_attempts` count is below two, with a third attempt rejected as `ERR_REPAIR_LIMIT_EXCEEDED` — moves the wire to `REPAIR`, increments `repair_attempts`, applies the corrected fields supplied in the payload (any of `beneficiary_id`, `amount_cents`, `method`, or `purpose`), and carries the mandatory `expected_wire_version`. When the repair changes `amount_cents`, the account's `daily_reserved_cents` is re-based by the delta — the new amount minus the old — while `reservation_active` stays true, so the reservation tracks the corrected principal. Repair always re-runs screening: `screening_status` is reset to `NOT_SCREENED` and then re-evaluated to `CLEAR` or `REVIEW`, and the `risk_score` is recomputed by the same five-component rule as at submission. The wire's `version` increments and the repair is audit-logged.

Resubmission returns a repaired wire to the approval pipeline, moving it from `REPAIR` back to `PENDING_APPROVAL`. Resubmission invalidates the prior round's approvals: every approval record from the prior round is marked `superseded` true and stops counting toward dual approval, and the wire's `first_approved_by` and `second_approved_by` reset to null, so a fresh `FIRST`/`SECOND` pair is required. Resubmission is audit-logged. A wire in `REPAIR` may alternatively be cancelled by an operator, which releases the reservation at its current amount and writes the cancellation to the audit log.

### 3.5. Release and Atomic Execution

Release is the moment money moves, and it is the most heavily gated operation in the system. A `WireOperator` releases a wire with `expected_wire_version` per §2.7. In the fixed validation order, the release checks: the wire must be `APPROVED` (any other state is `ERR_INVALID_STATE`); the wire must carry no hold — `hold_reason_code` must be null — else `ERR_WIRE_ON_HOLD`; the wire's `screening_status` must be `CLEAR`, else `ERR_SANCTIONS_NOT_CLEARED`; and the business date of the wire's `value_date` must still be `OPEN` — a date that has passed cutoff or closed rejects with `ERR_CUTOFF_PASSED`.

A wire that clears the gates transitions `APPROVED → RELEASING`, and the network dispatch happens immediately within the same call. At the dispatch boundary the daily-limit check of §2.6 runs: if the account's available headroom is below the wire's principal, the release aborts atomically with `ERR_DAILY_LIMIT_EXCEEDED` — the wire returns to `APPROVED` with its reservation still active and the account's reserved tally unchanged. On success the wire reaches `EXECUTED`: `executed_at` is stamped, the reservation converts into the released tally, a `DORMANT` ordering account reactivates to `ACTIVE`, the beneficiary's `first_used_at` is stamped on its first execution, the wire's `version` increments, and execution is audit-logged as `wire.execute`.

Execution also finalizes the wire's money fields. The fee assessment runs in its `FINAL` variant (§3.7): a new `FeeAssessment` of `kind` `FINAL` is created in `OPEN` status, any prior `OPEN` `PROVISIONAL` assessment on the wire is marked `SUPERSEDED`, and every still-`POSTED` correspondent charge whose `source` is `PROVISIONAL_ESTIMATE` is likewise marked `SUPERSEDED`. The wire's `fee_assessed_cents` is set to that final assessment's total, and its `net_principal_cents` is computed as the wire's `amount_cents` minus the sum of the amounts of `POSTED` charges whose `charge_type` is `DEDUCTED_FROM_PRINCIPAL`. Both fields are null until execution.

Cancellation is the counterpart available to an operator at almost every pre-terminal stage, and each stage carries its own compensation. From `INITIATED`, cancellation simply moves the wire to `CANCELLED` and writes the audit entry. From `CALLBACK_PENDING`, cancellation additionally supersedes the still-`OPEN` callback case and resets `callback_status` to `NONE`. From `PENDING_APPROVAL` or from `REPAIR`, cancellation releases the reservation. From `APPROVED`, cancellation is allowed only while the wire carries no hold — a held wire cannot be cancelled directly, because the hold's own disposition is what cancels it; the attempt is rejected with `ERR_WIRE_ON_HOLD`. Every cancellation path is audit-logged as `wire.cancel`.

### 3.6. Sanctions Disposition: A Two-Tier Desk

Dispositions are role-partitioned by hit tier. A `SanctionsScreener` may disposition only `OPEN` hits; a hit in `ESCALATED` status is beyond screener authority, and a screener's attempt to release or confirm it is rejected with `ERR_FORBIDDEN_ROLE`. A `ComplianceOfficer` is required for `ESCALATED` hits — only a compliance officer may disposition one. In both tiers, a hit already in `RELEASED_FALSE_POSITIVE` or `CONFIRMED` is terminal, and any further disposition attempt is rejected with `ERR_HIT_ALREADY_RESOLVED`. Releasing and confirming additionally require the hit's wire to be in `PENDING_APPROVAL`, `REPAIR`, or `APPROVED`; any other wire state is `ERR_INVALID_STATE`. Escalation, by contrast, is the screener's hand-off and requires only that the hit be `OPEN`.

A release disposition — the screener judging the match a false positive, with a `rationale` recorded on the request — moves the hit to `RELEASED_FALSE_POSITIVE`, stamps `decided_by` and `decided_at`, and is audit-logged as `sanctions.release`. When the released hit was the wire's **last unresolved hit**, the wire's `screening_status` transitions from `REVIEW` to `CLEAR`, and if the wire's `hold_reason_code` was `SANCTIONS_HOLD`, the hold is cleared to null. An `ESCALATED` hit remains unresolved for this purpose: it still blocks `CLEAR` until it is itself dispositioned by a compliance officer, whose release has the same wire-level effects.

A confirm disposition — again with a `rationale` — moves the hit to `CONFIRMED` and drives the wire's `screening_status` to `CONFIRMED_HIT`. Confirmation is fatal to a wire still in the pipeline: if the wire's status is `PENDING_APPROVAL` or `REPAIR`, the wire transitions to `REJECTED`, its reservation is released back to the account with `reservation_active` set false, its `hold_reason_code` is cleared to null, and the confirmation is audit-logged as `sanctions.confirm`. A compliance officer confirming an `ESCALATED` hit produces the same compensation: wire rejected, reservation released, hold cleared.

For test-driving purposes, a `SanctionsScreener` may attach a deterministic party-match hit to a wire by supplying `wire_id`, `matched_list`, `matched_party`, and `match_score`; the hit is created in `OPEN` status, and if the wire has already been submitted its `screening_status` is recomputed immediately — becoming `REVIEW` while the hit is unresolved — with `SANCTIONS_HOLD` set when the wire is `APPROVED` and unheld. This simulation capability does not exist in the production workflow; it exists so that screening behavior can be exercised deterministically.

### 3.7. Fees and Correspondent Charges

Correspondent charges are posted against a wire by an operator or administrator, each naming the `correspondent_name`, a `charge_type` declaring who contractually bears the charge (`OUR`, `BENEFICIARY`, or `DEDUCTED_FROM_PRINCIPAL`), a strictly positive `amount_cents`, and a `source` of `PROVISIONAL_ESTIMATE` or `ACTUAL_ADVICE`. A charge is born `POSTED`. The provenance is gated by the wire's stage: an estimate may be posted only while the wire is in `INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `REPAIR`, or `APPROVED`, and an actual advice may be posted only while the wire is in `PENDING_APPROVAL`, `REPAIR`, `APPROVED`, `EXECUTED`, or `RECALLED`; posting outside the allowed window is `ERR_INVALID_STATE`. Charges whose lifecycle ends — `SUPERSEDED` or `CANCELLED` — never participate in any fee math.

Fee assessment has two variants sharing one pinned evaluation order; each component is computed independently, then the components are summed. First, the base fee is read from the payment rail: twenty-five dollars for `Fedwire`, thirty-five dollars for `SWIFT`, and eighteen dollars for `CHIPS` — recorded as `base_fee_cents`. Second, the priority surcharge is ten dollars when the wire's `priority` is `SAME_DAY` and zero for `NORMAL`, recorded as `priority_fee_cents`. Third, the beneficiary-pays share `beneficiary_share_cents` applies only when the wire's `method` is `SWIFT` **and** its `charge_mode` is `BENEFICIARY_REMUNERATION`: it is forty percent of the base fee, rounded half-up to whole cents; under any other combination it is zero. Fourth, the bank-absorbed correspondent share `correspondent_share_cents` is the sum over the wire's `POSTED` charge rows of a per-charge amount: for a charge of type `DEDUCTED_FROM_PRINCIPAL`, half the charge amount rounded half-up to whole cents; for a charge of type `OUR`, the full charge amount; for a charge of type `BENEFICIARY`, zero. Each charge's product is rounded half-up individually before summation. Fifth, `total_fee_cents` is the sum of the base fee, the priority surcharge, the beneficiary share, and the correspondent share — and the total is **not** rounded again; the pinned order is per-line rounding, then summation, and rounding only the final sum is a rejected alternative.

The variants differ only in which charges enter the fourth component. The `PROVISIONAL` variant — a pre-execution estimate, and the only kind allowed while the wire is not yet `EXECUTED` or `RECALLED` — restricts its input set to charges whose `source` is `PROVISIONAL_ESTIMATE`, excluding actual advices. The `FINAL` variant — produced automatically at execution and again on any post-execution re-assessment — restricts its input set to charges whose `source` is `ACTUAL_ADVICE`, excluding estimates (which execution has in any case superseded). Either variant may also be produced on demand by an operator or administrator supplying a `kind`: a `PROVISIONAL` request requires the wire to be in `INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `REPAIR`, or `APPROVED`, and a `FINAL` request requires `EXECUTED` or `RECALLED`; mismatches are `ERR_INVALID_STATE`. Every assessment records its four components and total, its `kind`, and a lifecycle `status` starting at `OPEN`.

An `OPEN` assessment may be billed by an operator, but only when the linked wire is `EXECUTED` or `RECALLED` — billing otherwise is `ERR_INVALID_STATE` — moving the assessment to `BILLED` and writing an audit entry. An administrator may instead waive an `OPEN` assessment, moving it to `WAIVED` with its own audit entry. A wire's fees and charges are listable individually, each ordered by creation time, and a single assessment is retrievable on its own.

### 3.8. Fraud Holds and the Customer Confirmation Window

A `FraudAnalyst` places a fraud hold on a wire that is `APPROVED` and currently unheld — any other wire state is `ERR_INVALID_STATE`, and a wire already carrying a hold rejects the placement with `ERR_WIRE_ON_HOLD`. The placement names a `reason_code` — one of `ACCOUNT_TAKEOVER`, `VELOCITY`, `MULE_SUSPECT`, or `PHISHING` — and an analyst `note`; it stamps the wire's `hold_reason_code` to `FRAUD_HOLD`, creates the hold in `OPEN` status with `placed_by` recording the analyst, and opens a customer confirmation window whose length is recorded on the hold as `confirmation_window_hours` — twenty-four hours — with `expires_at` set exactly twenty-four hours after placement. Placement is audit-logged as `fraud.hold_place`. A held wire is frozen in place: it cannot be released and cannot be cancelled while the hold stands.

The hold resolves through customer confirmation. While the hold is `OPEN` and strictly before `expires_at` — an attempt at or after the deadline is `ERR_FRAUD_HOLD_WINDOW_EXPIRED`, because the window has already auto-lapsed the hold — the analyst records a `confirmation` outcome. `LEGITIMATE` clears the hold: it moves to `CLEARED` with `resolution` `CUSTOMER_CONFIRMED`, the wire's `hold_reason_code` returns to null, and the wire remains `APPROVED`, eligible again for release; the clearing is audit-logged as `fraud.cleared`. `FRAUDULENT` confirms the hold: it moves to `CONFIRMED_FRAUD` with `resolution` `CUSTOMER_DENIED`, the wire transitions to `CANCELLED` with its hold cleared, the ordering customer transitions to `FROZEN` with `frozen_at` stamped, and the confirmation is audit-logged as `fraud.confirmed`.

Window lapse is the third resolution path. At or after `expires_at`, an `OPEN` hold auto-resolves as `CONFIRMED_FRAUD` with `resolution` `AUTO_LAPSED`, evaluated lazily on any access to the hold or its wire per §2.5. The auto-lapse carries the full confirmation compensation: the wire is cancelled and the ordering customer is frozen. The hold's `resolution` field reads `NONE` until any of the three terminal paths lands.

### 3.9. Recalls: Negotiating with the Beneficiary Bank

After execution, an operator may open a recall against the wire — the wire must be `EXECUTED` — supplying the `wire_id`, a `reason` of `DUPLICATE`, `FRAUD`, `ERROR_AMOUNT`, or `ERROR_BENEFICIARY`, and the `amount_to_recall_cents` sought, which must be strictly positive and no greater than the wire's `amount_cents`; an out-of-range amount is `ERR_RECALL_AMOUNT_EXCEEDS`. Only one non-terminal recall may exist per wire at a time — a second attempt while one is in flight is `ERR_RECALL_IN_PROGRESS`. A recall is born `REQUESTED` with `beneficiary_bank_response` `NONE`.

The negotiation then alternates between the two banks. The originating operator dispatches the recall to the beneficiary bank; dispatch requires `REQUESTED` status (else `ERR_INVALID_STATE`), moves the recall to `SENT_TO_BENEFICIARY_BANK`, sets `response_due_at` exactly seventy-two hours out, and is audit-logged as `recall.send`. The counterparty — acting in the `BeneficiaryBank` role, whose write authority extends to this one action — records its answer by supplying a `response` of `FUNDS_RETURNED` or `FUNDS_DECLINED`. Responding requires the recall to be in `SENT_TO_BENEFICIARY_BANK` — acting on a terminal recall is `ERR_RECALL_ALREADY_RESOLVED`, while acting on one still merely `REQUESTED` is `ERR_INVALID_STATE` — and requires the response strictly before `response_due_at`, with a late answer rejected as `ERR_RECALL_EXPIRED`. A valid response stamps `beneficiary_bank_response` from the payload, records `responded_at`, and moves the recall to `BENEFICIARY_RESPONDED`. The seventy-two-hour window is strict and lazily enforced: at or after `response_due_at`, an unanswered recall auto-expires to `EXPIRED` on any access, writes the `recall.expired` audit entry, and — critically — leaves the wire's status untouched: the recall dies, the payment stays `EXECUTED`.

Two terminal paths follow a response. When the beneficiary bank returned the funds, the originating operator completes the recall: completion requires `BENEFICIARY_RESPONDED` status (a terminal recall again yields `ERR_RECALL_ALREADY_RESOLVED`) and requires `beneficiary_bank_response` to be `FUNDS_RETURNED`, else `ERR_RECALL_NOT_RETURNED`. Completion moves the recall to `COMPLETED`, transitions the wire from `EXECUTED` to `RECALLED`, books the recall compensation, and writes `recall.complete`. The compensation accounting conserves an invariant established at execution: the wire's `amount_cents` always equals its `net_principal_cents` plus the sum of the amounts of `POSTED` charges of type `DEDUCTED_FROM_PRINCIPAL` measured at the moment of execution, and that equality still holds after recall completion. The booking itself compares the recovered `amount_to_recall_cents` against the wire's `net_principal_cents`: when the bank recovered more than the principal it originally credited the beneficiary — because correspondent deductions meant less than the full principal left the building — the positive difference is booked as correspondent loss recovery; when the recovery falls short, the unrecovered remainder is booked as recall loss. Completion does not auto-waive any `OPEN` fee assessment on the wire; assessments continue on their own lifecycle. When the beneficiary bank declined, the originating operator instead accepts the refusal: declining requires `BENEFICIARY_RESPONDED` and a `FUNDS_DECLINED` answer (a mismatch is `ERR_INVALID_STATE`), moves the recall to `DECLINED`, and writes `recall.declined`.

### 3.10. Investigations and the Tracer Loop

A `WireInvestigator` opens an investigation against any wire — in any status — by supplying the `wire_id`, a `type` of `TRACER`, `NON_RECEIPT`, or `VALUE_DISPUTE`, and an investigator `note`. The investigation is born `OPEN` with `tracer_count` zero and a system-set `max_tracers` of three, and `opened_by` records the investigator.

The investigation runs a cyclic send-and-answer loop. From `OPEN`, dispatching an outbound tracer — supplying the message `body` — requires `tracer_count` to be below `max_tracers`, with a fourth dispatch rejected as `ERR_TRACER_LIMIT_EXCEEDED`. Each dispatch creates a `TracerMessage` with `direction` `OUTBOUND`, assigns it a `sequence_no` equal to the count of existing tracer messages for the investigation plus one (so numbering starts at one), increments `tracer_count`, and moves the investigation to `AWAITING_RESPONSE`. From `AWAITING_RESPONSE`, registering the counterparty's reply — again supplying a `body` — creates an `INBOUND` tracer message with the next `sequence_no`, does **not** consume any of the tracer budget, and returns the investigation to `OPEN`, where another dispatch becomes possible. An investigation may be resolved from `OPEN`, moving to `RESOLVED`, or closed without resolution from either `OPEN` or `AWAITING_RESPONSE`, moving to `CLOSED`; acting from any other state is `ERR_INVALID_STATE`. An investigation's tracer thread is listable in `sequence_no` ascending order.

### 3.11. Reading the Room: Aggregation, Audit, and the Wire Summary

Read access is broad by design: every internal role, plus the auditor, may read customers, accounts, beneficiaries, business dates, wires, approval records, callbacks, sanctions hits, fraud holds, charges, fees, recalls, investigations, and tracer messages. The `BeneficiaryBank` role is the sole exception — its read access is limited to recalls, the one workflow where it is a party. The audit log itself is readable by a `WireOpsAdmin`, an `Auditor`, or a `ComplianceOfficer` only.

The wire list supports filtering by `ordering_account_id`, `beneficiary_id`, processing `status`, `screening_status`, or `value_date`; the recall list by `wire_id` or `status`; the investigation list by `wire_id` or `status`. A wire's approval history — current round and superseded rounds together — is listable in creation order, and reading a callback case or a fraud hold or a recall evaluates its lazy expiry before answering, so reads observe the same deadlines as writes.

For an operator console, the wire summary is a computed read that assembles, in one document, the wire itself plus its `approvals` count (non-superseded records of the current repair round), `open_hits`, `open_holds`, `recalls`, `open_fees`, and the live `reserved_cents` amount. It is a read-only projection: it mutates nothing and takes no inputs beyond the path.

## 4. Endpoint Definitions

The API is mounted under the `/wire-ops` prefix. Operations that create a new resource — a customer, account, beneficiary, business date, wire, fraud hold, recall, correspondent charge, fee assessment, investigation, or tracer message, or the simulated-hit test hook — return `201 Created`. Operations that act on an existing resource without creating a new one — submits, approvals, rejections, releases, cancels, repairs, resubmits, dispositions, confirmations, lifecycle transitions, and the clock setter — return `200 OK`. Reads return `200 OK`. All resources are addressable by their `id` path parameter.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wire-ops/_clock/set_current_utc` | Set the server's logical clock | WireOpsAdmin |
| POST | `/wire-ops/_screening/simulate` | Attach a deterministic party-match hit to a wire | SanctionsScreener |
| POST | `/wire-ops/customers` | Register a customer | WireOpsAdmin |
| GET | `/wire-ops/customers` | List customers | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/customers/{id}` | Get a customer | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/customers/{id}/freeze` | Freeze a customer | WireOpsAdmin |
| POST | `/wire-ops/customers/{id}/unfreeze` | Unfreeze a customer | WireOpsAdmin |
| POST | `/wire-ops/customers/{id}/close` | Close a customer | WireOpsAdmin |
| GET | `/wire-ops/customers/{id}/accounts` | List accounts of a customer | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/customers/{id}/beneficiaries` | List beneficiaries registered by a customer | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/accounts` | Open an account | WireOpsAdmin |
| GET | `/wire-ops/accounts` | List accounts | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/accounts/{id}` | Get an account | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/accounts/{id}/mark-dormant` | Mark an account dormant | WireOpsAdmin |
| POST | `/wire-ops/accounts/{id}/close` | Close an account | WireOpsAdmin |
| POST | `/wire-ops/beneficiaries` | Register a beneficiary | WireOperator, WireOpsAdmin |
| GET | `/wire-ops/beneficiaries` | List beneficiaries | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/beneficiaries/{id}` | Get a beneficiary | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/beneficiaries/{id}/retire` | Retire a beneficiary | WireOperator, WireOpsAdmin |
| POST | `/wire-ops/business-dates` | Open a business date (ops day) | WireOpsAdmin |
| GET | `/wire-ops/business-dates` | List business dates | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/business-dates/{id}` | Get a business date | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/business-dates/{id}/close-cutoff` | Close the wire cutoff for an OPEN business date | WireOpsAdmin |
| POST | `/wire-ops/business-dates/{id}/close-day` | Close a business date after cutoff (end-of-day reconciliation) | WireOpsAdmin |
| POST | `/wire-ops/wires` | Initiate a wire transfer | WireOperator |
| GET | `/wire-ops/wires` | List wires | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/wires/{id}` | Get a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/wires/{id}/submit` | Submit an initiated (or callback-cleared) wire into the approval pipeline | WireOperator |
| POST | `/wire-ops/wires/{id}/approve` | Record one approval of the dual approval (first or second) | WireApprover |
| POST | `/wire-ops/wires/{id}/reject` | Reject a wire pending approval | WireApprover |
| POST | `/wire-ops/wires/{id}/release` | Release an approved, clear, unheld wire to the network; execution and fee finalization happen atomically | WireOperator |
| POST | `/wire-ops/wires/{id}/cancel` | Cancel a wire in INITIATED, CALLBACK_PENDING, PENDING_APPROVAL, REPAIR, or unheld APPROVED | WireOperator |
| POST | `/wire-ops/wires/{id}/repair` | STP exception repair: correct wire fields, force re-screening and risk recompute | RepairSpecialist |
| POST | `/wire-ops/wires/{id}/resubmit` | Return a repaired wire to the approval pipeline; prior approvals are superseded | RepairSpecialist |
| POST | `/wire-ops/wires/{id}/fraud-holds` | Place a fraud hold on an APPROVED wire | FraudAnalyst |
| GET | `/wire-ops/wires/{id}/approvals` | List approval records for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/wires/{id}/callbacks` | List callback verification cases for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/callbacks/{id}` | Get a callback verification case (lazy expiry evaluated) | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/callbacks/{id}/record` | Record the callback outcome | WireOperator |
| GET | `/wire-ops/wires/{id}/sanctions-hits` | List sanctions hits for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor, ComplianceOfficer |
| GET | `/wire-ops/sanctions-hits/{id}` | Get a sanctions hit | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor, ComplianceOfficer |
| POST | `/wire-ops/sanctions-hits/{id}/release` | Disposition a hit as false positive (screener for OPEN hits; compliance officer for ESCALATED) | SanctionsScreener, ComplianceOfficer |
| POST | `/wire-ops/sanctions-hits/{id}/confirm` | Disposition a hit as a true match (screener for OPEN hits; compliance officer for ESCALATED) | SanctionsScreener, ComplianceOfficer |
| POST | `/wire-ops/sanctions-hits/{id}/escalate` | Escalate an OPEN hit for compliance decision | SanctionsScreener |
| GET | `/wire-ops/wires/{id}/fraud-holds` | List fraud holds for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/fraud-holds/{id}` | Get a fraud hold (lazy lapse evaluated) | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/fraud-holds/{id}/customer-confirm` | Record the customer confirmation outcome for a fraud hold | FraudAnalyst |
| POST | `/wire-ops/recalls` | Open a recall/return request against an EXECUTED wire | WireOperator |
| GET | `/wire-ops/recalls` | List recalls | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor, BeneficiaryBank |
| GET | `/wire-ops/recalls/{id}` | Get a recall (lazy expiry evaluated) | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor, BeneficiaryBank |
| POST | `/wire-ops/recalls/{id}/send` | Dispatch the recall to the beneficiary bank | WireOperator |
| POST | `/wire-ops/recalls/{id}/respond` | Beneficiary bank records its answer | BeneficiaryBank |
| POST | `/wire-ops/recalls/{id}/complete` | Complete a recall after funds returned; wire becomes RECALLED and compensation booked | WireOperator |
| POST | `/wire-ops/recalls/{id}/decline` | Originating bank accepts beneficiary bank's refusal | WireOperator |
| POST | `/wire-ops/wires/{id}/charges` | Post a correspondent charge against a wire | WireOperator, WireOpsAdmin |
| GET | `/wire-ops/wires/{id}/charges` | List correspondent charges for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/wires/{id}/fees/assess` | Run fee assessment on demand (PROVISIONAL pre-execution or FINAL re-run post-execution) | WireOperator, WireOpsAdmin |
| GET | `/wire-ops/wires/{id}/fees` | List fee assessments for a wire | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/fees/{id}` | Get a fee assessment | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/fees/{id}/bill` | Bill an OPEN fee assessment (wire must be EXECUTED or RECALLED) | WireOperator |
| POST | `/wire-ops/fees/{id}/waive` | Waive an OPEN fee assessment | WireOpsAdmin |
| POST | `/wire-ops/investigations` | Open an investigation (tracer, non-receipt, value dispute) on a wire | WireInvestigator |
| GET | `/wire-ops/investigations` | List investigations | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/investigations/{id}` | Get an investigation | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| POST | `/wire-ops/investigations/{id}/tracers` | Dispatch an outbound tracer message | WireInvestigator |
| POST | `/wire-ops/investigations/{id}/respond` | Register the counterparty's reply; investigation returns to OPEN | WireInvestigator |
| POST | `/wire-ops/investigations/{id}/resolve` | Resolve an open investigation | WireInvestigator |
| POST | `/wire-ops/investigations/{id}/close` | Close an open or awaiting investigation without resolution | WireInvestigator |
| GET | `/wire-ops/investigations/{id}/tracers` | List tracer messages of an investigation, ordered by sequence number | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |
| GET | `/wire-ops/audit-logs` | List audit log entries (append-only), ordered by creation time | WireOpsAdmin, Auditor, ComplianceOfficer |
| GET | `/wire-ops/audit-logs/{id}` | Get a single audit log entry | WireOpsAdmin, Auditor, ComplianceOfficer |
| GET | `/wire-ops/wires/{id}/summary` | Computed read: wire with approval count, open hits, open holds, recalls, open fees, and live reservation amount | WireOpsAdmin, WireOperator, WireApprover, SanctionsScreener, FraudAnalyst, RepairSpecialist, WireInvestigator, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BENEFICIARY_ACCOUNT_MISMATCH` | 422 |
| `ERR_ACCOUNT_INACTIVE` | 409 |
| `ERR_BENEFICIARY_INACTIVE` | 409 |
| `ERR_CUSTOMER_FROZEN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CALLBACK_NOT_VERIFIED` | 409 |
| `ERR_CALLBACK_WINDOW_EXPIRED` | 409 |
| `ERR_SOD_APPROVER_MISMATCH` | 409 |
| `ERR_HIT_ALREADY_RESOLVED` | 409 |
| `ERR_WIRE_ON_HOLD` | 409 |
| `ERR_SANCTIONS_NOT_CLEARED` | 409 |
| `ERR_CUTOFF_PASSED` | 409 |
| `ERR_DAILY_LIMIT_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RECALL_EXPIRED` | 409 |
| `ERR_RECALL_ALREADY_RESOLVED` | 409 |
| `ERR_RECALL_NOT_RETURNED` | 409 |
| `ERR_RECALL_AMOUNT_EXCEEDS` | 422 |
| `ERR_RECALL_IN_PROGRESS` | 409 |
| `ERR_REPAIR_LIMIT_EXCEEDED` | 409 |
| `ERR_TRACER_LIMIT_EXCEEDED` | 409 |
| `ERR_FRAUD_HOLD_WINDOW_EXPIRED` | 409 |
| `ERR_CUSTOMER_STILL_FROZEN` | 409 |
| `ERR_CUSTOMER_NOT_SETTLED` | 409 |
| `ERR_ACCOUNT_NOT_SETTLED` | 409 |
| `ERR_BENEFICIARY_IN_USE` | 409 |
| `ERR_CUTOFF_ALREADY_PASSED` | 409 |

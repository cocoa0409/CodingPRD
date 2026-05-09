# Insurance Claims API — Product Requirements Document

## 1. Introduction

Property and casualty insurers handle a continuous stream of loss reports across multiple intake channels — web portals, mobile apps, contact-centre phone lines, and broker agents — and each report must be reconciled against the policy that backs it, investigated by a credentialed adjuster, reviewed for approval by an independent reviewer, paid out through a banking integration, and then audited end-to-end. The Insurance Claims API codifies this workflow so that claim handling remains consistent regardless of the operator who picks it up, while still enforcing the controls — segregation of duties between adjusters and reviewers, anti-fraud signals that gate auto-approval, blacklisting of repair shops that show collusion patterns, and reversible compensating actions when a bank settlement fails — that protect both the insurer and the insured from over- or under-payment.

The system is event-driven and immediately consistent: every state change on a claim, every review decision, every payout movement, and every fraud flag emits an audit log entry, and downstream calculations (gross payout, net payout, fraud score, repair-shop trust decay) are recomputed at the moment a triggering transition occurs rather than on read. This document specifies the resources, lifecycles, calculations, validations, role permissions, and error contracts that an implementation must satisfy. The behaviour described here is the complete contract; the test suite that grades a candidate implementation derives every assertion from these requirements.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. Requests missing or malformed in either header are rejected with `ERR_AUTH_REQUIRED`. The system recognises five roles, spelled exactly as follows: `Customer`, `Adjuster`, `Reviewer`, `PayoutOfficer`, and `PlatformAdmin`. A request whose `X-User-Role` is not one of these values, or whose role is not authorised for the targeted endpoint, is rejected with `ERR_FORBIDDEN`.

Two test-driving control endpoints — the simulated clock advance and the bank event drivers under `/_events/*` — additionally require an `X-Admin-Token` header that matches the deployment's configured admin secret; a missing or wrong token on those endpoints also yields `ERR_FORBIDDEN`.

The five roles relate to `X-User-ID` as follows:

- When `X-User-Role` is `Adjuster`, `X-User-ID` is the `id` of the acting `Adjuster` entity. Ownership checks on any resource that references an `Adjuster` (notably `Investigation.adjuster_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is an opaque insured-party identifier not tied to any persisted entity. The server records it on `Claim.claimant_id` at intake and on `Appeal.requestor_id` at appeal creation, and it compares it to those fields for ownership checks (a customer may only act on a claim where `Claim.claimant_id` equals `X-User-ID`, may only appeal as the original claimant, and may only intake a claim against a `Policy` whose `insured_party_id` equals `X-User-ID`); the server does not compare `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `Reviewer`, `X-User-ID` is an opaque reviewer identifier. The server records it on `ReviewDecision.reviewer_id` whenever a decision is filed and uses it to enforce segregation of duties (described in §3), but does not match it against any entity's `id`.
- When `X-User-Role` is `PayoutOfficer`, `X-User-ID` is an opaque operator identifier. The server records the actor on each `AuditLogEntry` via `actor_id` and `actor_role`, but does not match it against any persisted entity.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque administrator identifier. The server records it on audit log entries originating from admin actions but does not match it against any persisted entity. For automated, system-driven side effects (auto-approval, bank settle/fail cascades, clock-advance sweeps) the server records `actor_id = "system"` on the resulting audit entries.

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

Endpoints that return collections accept two query parameters: `limit` and `offset`. The `limit` parameter is the maximum number of items to return; it defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and must not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, list responses are sorted by `created_at` in ascending order. The `meta` object on list responses always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Top-level resources whose lifecycles include modification — `Policy`, `Adjuster`, `RepairShop`, `Claim`, `Investigation`, `Appeal`, and `Payout` — carry four system-managed fields:

- `id`: a server-minted UUID; the API does not use type-prefixed identifiers, so the value is a bare UUID string with no entity prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set at row creation and never modified afterwards.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource (including derived fields whose change is the result of a side-effect cascade described in §3).
- `version`: an integer that starts at 1 on creation and increments by 1 on every persisted mutation of the resource.

Three resources are append-only or single-shot and therefore omit both `updated_at` and `version`: `EstimateLineItem`, `ReviewDecision`, `FraudFlag`, and `AuditLogEntry`. These rows carry only `id` and `created_at`.

The `Claim` entity additionally exposes the human-readable `claim_number`. This identifier is server-minted on intake in the form `CLM-YYYYMMDD-NNNN`, where `YYYYMMDD` is the UTC date on which the claim was created and `NNNN` is a zero-padded four-digit decimal sequence equal to one plus the count of claims already created with the same UTC `created_at` date. The first claim of a given UTC date receives sequence `0001`. The sequence resets to `0001` at the start of each new UTC date. `claim_number` is unique across the system.

### 2.5. Hierarchical Consistency, Cascades, and Audit Logging

Many mutations in the claims domain produce cascading effects across more than one resource. Whenever a `Claim` changes status, the server records an `AuditLogEntry` whose `event_type` is `STATUS_CHANGE` and whose `from_state` and `to_state` capture the transition, alongside `actor_id` (the `X-User-ID` of the caller, or the literal string `"system"` for clock-driven and event-driven cascades), `actor_role`, and a structured `payload` describing the event. Review decisions emit `event_type` `REVIEW_DECISION`; appeal decisions emit `APPEAL_DECISION`; payout creation, bank settlement, bank failure, and subrogation each emit `PAYOUT_EVENT`; fraud flag insertion emits `FRAUD_FLAG_ADDED`.

Every mutation that touches a resource carrying `version` also refreshes the resource's `updated_at` and increments `version` by one. When a single user-initiated operation cascades into multiple resources — for example, submit-for-review mutates the `Claim`, completes the `Investigation`, may decay a `RepairShop`'s trust score and possibly blacklist it — every affected resource has its own `updated_at` refreshed and its own `version` incremented independently.

Path-referenced resources are validated left-to-right. For a request such as the appeal-decision endpoint, the server first verifies that the `Claim` named by the leading path segment exists, then that the `Appeal` named by the subsequent segment exists and belongs to that claim; the first identifier that fails resolution causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or any business rule is evaluated.

### 2.6. Policy Validity, Reporting Window, and Idempotency at Intake

All claim intake checks are evaluated in a strict priority sequence. Authentication runs first, followed by authorisation, followed by existence of path-referenced resources, followed by the requirement that the `Claim` (or other action target) be in the correct state for the requested action; then the domain checks specific to intake apply in this order: the referenced `Policy` must exist and have `status` equal to `ACTIVE` (a non-active policy yields `ERR_POLICY_INACTIVE`); the supplied `loss_date` must lie at or after the policy's `effective_from` and strictly before `effective_to` (otherwise `ERR_LOSS_OUTSIDE_POLICY_PERIOD`); the number of whole days between `loss_date` and the server-stamped `reported_at` must be at most the policy's `reporting_window_days` (otherwise `ERR_REPORTING_WINDOW_EXCEEDED`); and the combination of `claimant_id` and `idempotency_key` must not already exist for any claim created in the previous 24 hours (otherwise `ERR_DUPLICATE_CLAIM_INTAKE`). Generic body validation (missing fields, wrong types, out-of-range values) returns `ERR_VALIDATION_FAILED` and is the lowest-priority check. This ordering is observable: when two checks would both reject, the higher-priority error code is the one returned.

The `Policy` provides three financial inputs that drive every payout calculation downstream — `coverage_limit_cents`, `deductible_cents`, and `coinsurance_ratio` — and one administrative input that drives the time-window check, `reporting_window_days`. The `coinsurance_ratio` is stored to four decimal places and falls within zero and one inclusive. The `reporting_window_days` is at least 1, and when omitted at policy creation it defaults to 30 days. The `coverage_limit_cents` and `deductible_cents` values are non-negative integers in cents; the `policy_number` is a unique uppercase alphanumeric string of length between 8 and 24 characters inclusive.

### 2.7. Segregation of Duties

The system enforces a strict separation between the operator who investigates a claim and the operator who decides on it. At primary-review time, the `X-User-ID` recording the decision must differ from the `Investigation.adjuster_id` of the claim's investigation; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. At secondary-review time (during an appeal), the `X-User-ID` recording the appeal decision must differ from both the `Investigation.adjuster_id` and the `reviewer_id` recorded on the primary `ReviewDecision` row; both kinds of overlap also yield `ERR_SEGREGATION_OF_DUTIES`. The check is performed against the actor's identity for the operation under evaluation, and it applies to both manual primary review and the appeal-decision endpoint.

### 2.8. Monetary Precision and Calculation Order

All monetary fields on the API surface — `coverage_limit_cents`, `deductible_cents`, `claimed_amount_cents`, `assessed_loss_cents`, `salvage_value_cents`, `subrogation_recovery_cents`, `gross_payout_cents`, `net_payout_cents`, `amount_cents` on estimate lines, and `amount_cents` on payouts — are integers expressed in cents. The `coinsurance_ratio` is the only decimal financial input; it is stored at four decimal places. Wherever a calculation multiplies a cent value by `coinsurance_ratio`, the multiplication is performed once in floating-point arithmetic and the result is rounded to integer cents using the "round half up" rule before any subsequent step is applied. The `fraud_score` and `trust_score` values are floats in the range zero to one inclusive, stored at two decimal places, again using "round half up" applied exactly once at the rounding step described in §3.

### 2.9. Anti-Fraud Hold and Coverage Limit Guards

When a claim is submitted for review, the `Claim.fraud_score` is recomputed. If that score reaches or exceeds 0.80, the transition out of `UNDER_INVESTIGATION` is blocked and the server returns `ERR_FRAUD_HOLD`; clearing the hold requires manual intervention outside the auto path. Two additional guards run at the same point: the computed `gross_payout_cents` must not exceed the policy's `coverage_limit_cents` (otherwise `ERR_COVERAGE_LIMIT_EXCEEDED`, a sanity guard against direct mutation), and at subrogation time the sum of `salvage_value_cents` and `subrogation_recovery_cents` must not exceed `gross_payout_cents` (otherwise `ERR_NEGATIVE_NET_PAYOUT`).

### 2.10. Optimistic Concurrency Control

Modification endpoints for the reference-data resources — the policy update endpoint, the adjuster update endpoint, and the repair-shop update endpoint — accept an optional `version` field in the request body. When `version` is present, the server compares it to the resource's current `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server processes the mutation without performing the OCC check. On a successful mutation, `version` increments by 1 and `updated_at` refreshes. The OCC mechanism is offered only on these three reference-data updates; lifecycle transitions on `Claim`, `Investigation`, `Appeal`, and `Payout` are controlled by their state machines and the concurrency rules described in §3 (idempotency, first-writer-wins on uniqueness constraints, and first-writer-wins on state transitions).

### 2.11. Repair Shop Trust and Blacklisting

A `RepairShop` carries a `trust_score` that begins at 1.00 on creation and decays as repair-shop-collusion fraud signals accumulate against the shop. Decay events are processed when a claim is submitted for review; the canonical decay algorithm is described in §3. Whenever decay drives the `trust_score` strictly below 0.40, the shop's `status` automatically transitions from `ACTIVE` to `BLACKLISTED`. Any new estimate line referencing a `BLACKLISTED` shop is rejected with `ERR_REPAIR_SHOP_BLACKLISTED`. The blacklist threshold and the per-flag decay step are domain constants — never raised by an admin override (the admin update endpoint can lower or freeze status but cannot raise `trust_score`).

## 3. Business Logic & Workflows

### 3.1. Filing a Claim

A `Customer` initiates intake by submitting a payload that names the underlying policy via `policy_id`, declares an intake channel through `report_channel` (one of `WEB`, `MOBILE`, `PHONE`, or `AGENT`), supplies a client-generated `idempotency_key` for duplicate suppression, supplies the `loss_date` at which the loss occurred, supplies a free-text `incident_description`, and states a `claimed_amount_cents` strictly greater than zero. The customer may also supply `salvage_value_cents` upfront if salvage is already known; if omitted, salvage defaults to 0. The server stamps `reported_at` from its own clock at the moment intake completes, mints a `claim_number` according to the `CLM-YYYYMMDD-NNNN` rule described in §2.4, and writes the row in `INTAKE` status. The `claimant_id` on the new claim is the `X-User-ID` of the calling customer.

Filing is governed by the validation cascade laid out in §2.6 — inactive policy, loss date outside the policy period, reporting window exceeded, and idempotency collisions all surface their respective errors before any other business rule. A simultaneous race in which two requests arrive with the same `claimant_id` and same `idempotency_key` within the 24-hour window is serialised so that exactly one row is persisted; the loser is rejected with `ERR_DUPLICATE_CLAIM_INTAKE`. The successful response includes the new claim's `id`, allowing the customer to begin polling for status, request the provisional payout estimate, or — once denied — eventually file an appeal.

A read-only provisional payout estimate is available for any of the customer's own claims in the form of an estimate-retrieval capability. The estimate uses the `estimate_at_intake` variant of the gross-payout calculation described in §3.5: it computes a what-if gross-payout figure from the customer's stated `claimed_amount_cents` rather than the adjuster's later `assessed_loss_cents`, and it does not subtract `salvage_value_cents` or `subrogation_recovery_cents`. The estimate is informational only and does not transition any state.

### 3.2. Investigation, Loss Assessment, and Estimates

Once a claim is in `INTAKE`, an `Adjuster` opens an investigation by providing the `adjuster_id` of the assigned investigator. Opening an investigation transitions the claim from `INTAKE` to `UNDER_INVESTIGATION` and creates an `Investigation` row in `OPEN` status whose `claim_id` references the parent claim. Two operational guards apply at this point: the underlying policy's `status` must be `ACTIVE` and the assigned `Adjuster.specialty` must equal the policy's `coverage_type` (`AUTO`, `PROPERTY`, or `LIABILITY`); a specialty mismatch is rejected with `ERR_ADJUSTER_SPECIALTY_MISMATCH`. The adjuster's roster `status` itself must be `ACTIVE` (not `SUSPENDED`). Two simultaneous attempts to open an investigation against the same claim serialise on the claim's transition out of `INTAKE`; the loser is rejected with `ERR_INVESTIGATION_ALREADY_OPEN`.

While the investigation is open, the same adjuster updates the case file. Damage photographs are recorded on `photo_urls` (a non-empty list of valid http or https URLs); the adjuster's confirmation that supporting documents are genuine is recorded on `document_authenticity_passed`, which defaults to false on creation; and the adjuster's final loss assessment is recorded on `assessed_loss_cents`. The adjuster also appends repair-shop quotes as estimate line items, each carrying its parent `investigation_id`, a `repair_shop_id`, a free-text `description`, and a positive `amount_cents`. An estimate that references a `RepairShop` whose `status` is `BLACKLISTED` is rejected with `ERR_REPAIR_SHOP_BLACKLISTED`.

If the investigation needs to be unwound, the assigning adjuster — and only that adjuster — may reject it. Rejection moves the `Investigation.status` to `REJECTED` and reverts the parent claim from `UNDER_INVESTIGATION` back to `INTAKE`, clearing `Claim.review_path` so that a fresh investigation can be reopened later. Both transitions are recorded in the audit log.

### 3.3. Submitting for Review

Submission for review is the most consequential transition in the system. The acting adjuster requests the move from `UNDER_INVESTIGATION` to `UNDER_REVIEW`, and the server runs the following preconditions in turn: the claim must be in `UNDER_INVESTIGATION`, the corresponding `Investigation` must be in `OPEN`, the investigation's `photo_urls` must contain at least one URL (otherwise `ERR_PHOTOS_REQUIRED`), the investigation's `document_authenticity_passed` must be true (otherwise `ERR_DOCUMENT_AUTHENTICITY_FAILED`), and at least one `EstimateLineItem` must exist for the investigation (otherwise `ERR_ESTIMATE_REQUIRED`).

When the preconditions hold, the server runs the calculations described in §3.5 in this exact order: gross payout, then net payout (in its `at_approval` variant, where `subrogation_recovery_cents` is treated as zero), then fraud score, then the review-path assignment. The freshly-computed `gross_payout_cents` must not exceed the policy's `coverage_limit_cents`; a violation is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED`. The freshly-computed `fraud_score` must be strictly less than 0.80; reaching or exceeding that ceiling is rejected with `ERR_FRAUD_HOLD`. Side effects on success are: `Investigation.status` is set to `COMPLETED`; `Claim.assessed_loss_cents` is copied from `Investigation.assessed_loss_cents`; `Claim.gross_payout_cents` and `Claim.net_payout_cents` are written; `Claim.fraud_score` is written; if any `FraudFlag` row with `signal` equal to `REPAIR_SHOP_COLLUSION` is associated with this claim, the corresponding `RepairShop.trust_score` is decayed (and the shop is blacklisted if the new score drops below 0.40); and finally `Claim.review_path` is set to `AUTO` or `MANUAL` according to the threshold rule below.

Two intake parameters drive the review-path decision but do not appear in the submission payload itself — `claimed_amount_cents` was supplied at filing time, and `fraud_score` is derived from previously recorded `FraudFlag` rows. The decision is: `Claim.review_path` becomes `AUTO` if and only if `claimed_amount_cents` is at most 200,000 cents (that is, two thousand dollars or less) and `fraud_score` is strictly less than 0.30; otherwise `Claim.review_path` becomes `MANUAL`. The cascade depth here is three levels — the act of submission causes a trust-score decay, which in turn causes a status change to `BLACKLISTED` once the score drops below the threshold — so an implementation must propagate `updated_at` and `version` changes across all three resources affected.

### 3.4. Primary Review: Auto-Approval and Manual Decisions

After submission, the claim is in `UNDER_REVIEW` with `review_path` set to either `AUTO` or `MANUAL`. When the path is `AUTO`, the server itself records a primary review decision through the same decision-recording capability used for manual reviews, but with the actor recorded as `system`: a `ReviewDecision` row is written with `review_level` set to `PRIMARY` and `outcome` set to `APPROVE`, the claim moves from `UNDER_REVIEW` to `APPROVED`, and the audit log captures both the `REVIEW_DECISION` event and the `STATUS_CHANGE`.

When the path is `MANUAL`, a `Reviewer` records the decision by supplying an `outcome` (`APPROVE` or `DENY`) and a written `rationale`. The reviewer's `X-User-ID` is recorded on the new row's `reviewer_id` field at `review_level` `PRIMARY`, and the server stamps `decided_at`. Approval moves the claim to `APPROVED`; denial moves it to `DENIED` and copies the reviewer's `rationale` into the claim's `denial_reason`. Both outcomes write a `ReviewDecision` row, both refresh the claim's audit log, and both increment `Claim.version`. The reviewer recording the decision must not be the same person as the assigned adjuster (segregation of duties); a violation surfaces as `ERR_SEGREGATION_OF_DUTIES`. If two reviewers race to decide the same claim, exactly one wins; the loser is rejected with `ERR_INVALID_STATE` because, by the time the loser's transaction observes the claim, it has already left `UNDER_REVIEW`.

### 3.5. Calculations

The system maintains four pinned calculations (gross payout, net payout, fraud score, and review-path assignment) and one shop-side decay calculation. Each is described below in business prose; constants live in §2 or in the surrounding workflow narrative.

**Gross payout.** The gross payout is computed in integer cents in this exact sequence. First, take the assessed loss in cents (the value of `Claim.assessed_loss_cents` at submission, or `Claim.claimed_amount_cents` for the read-only `estimate_at_intake` variant). Subtract the policy's `deductible_cents` from the assessed loss; if the result is negative, treat it as zero — this is the "after deductible" amount. Multiply that amount by the policy's `coinsurance_ratio` (a four-decimal float between zero and one inclusive) to obtain a raw insurer-share figure in floating-point cents. Round that raw figure to integer cents using the "round half up" rule, performing this rounding exactly once and only at this step. Finally, compare the rounded insurer-share cents against the policy's `coverage_limit_cents` and take the smaller of the two; that result is the `gross_payout_cents`. The `final_at_review` variant — pinned into `Claim.gross_payout_cents` at submission — uses `assessed_loss_cents`; the `estimate_at_intake` variant — exposed only through the read-only estimate retrieval — uses `claimed_amount_cents` instead, and its result is informational only. Salvage and subrogation are not subtracted at this step in either variant.

**Net payout.** The net payout is also in integer cents. It equals the `gross_payout_cents` minus `salvage_value_cents` minus `subrogation_recovery_cents`; if that subtraction would yield a negative number, the result is clamped to zero. The calculation runs at the moment any of those three inputs changes: at the submit-for-review transition (its `at_approval` variant, where `subrogation_recovery_cents` is treated as zero so the outcome equals `gross_payout_cents` minus `salvage_value_cents`), at any appeal that overturns a denial (a recomputation against the latest figures), and after each subrogation post (its `post_recovery` variant, where the gross is unchanged and only the net moves). The compensating invariant — that `gross_payout_cents` minus `salvage_value_cents` minus `subrogation_recovery_cents` equals `net_payout_cents` — must hold at all times.

**Fraud score.** The fraud score is a weighted, capped value in the range zero to one inclusive, stored to two decimal places. First, retrieve every `FraudFlag` row associated with this claim and group their `severity` contributions by the flag's `signal`. Sum the severities for `signal` `DUPLICATE_PATTERN` to obtain the pattern subtotal; sum the severities for `signal` `REPAIR_SHOP_COLLUSION` to obtain the collusion subtotal; sum the severities for `signal` `DOCUMENT_FORGERY` to obtain the forgery subtotal; sum the severities for `signal` `RAPID_RESUBMISSION` to obtain the rapid-resubmission subtotal. Cap each of the four subtotals at 1.00 individually before any weighted combination — the per-signal cap is applied first. Then form the weighted sum: 0.30 times the capped pattern subtotal, plus 0.30 times the capped collusion subtotal, plus 0.30 times the capped forgery subtotal, plus 0.10 times the capped rapid-resubmission subtotal. Round the weighted sum to two decimal places using "round half up" exactly once at this step, and finally clamp the rounded value to the inclusive range zero to one. The result is the new `Claim.fraud_score`. The lookback horizon for pattern signals is 90 days. The auto-fraud gate used by the review-path rule is 0.30: a `fraud_score` strictly below 0.30 is eligible for the auto path.

**Review-path assignment.** This rule consumes the freshly-pinned `claimed_amount_cents` and `fraud_score` and writes `Claim.review_path`. The path becomes `AUTO` if and only if `claimed_amount_cents` is less than or equal to the auto-approval threshold of 200,000 cents (that is, 2,000 dollars) AND `fraud_score` is strictly less than the auto-fraud gate of 0.30; otherwise the path becomes `MANUAL`. The threshold comparison on `claimed_amount_cents` is inclusive (a value equal to the threshold still routes to `AUTO`); the fraud gate is exclusive (a `fraud_score` exactly equal to 0.30 routes to `MANUAL`).

**Repair-shop trust decay.** A repair shop's `trust_score` decays whenever a claim that holds at least one `FraudFlag` of `signal` `REPAIR_SHOP_COLLUSION` against that shop is submitted for review. The canonical (state-mutating) algorithm — the `per_flag` variant — iterates over the matching collusion flags for that shop on that claim in chronological order by `created_at`, and applies one decay step per flag: each step subtracts 0.20 from the current `trust_score`, with the result clamped at no lower than 0.00. With N collusion flags on the same shop in a single submission, the `trust_score` therefore decreases by N times 0.20 (clamped at 0.00). After all steps, if the new `trust_score` is strictly less than the blacklist threshold of 0.40, `RepairShop.status` automatically transitions to `BLACKLISTED`. The decay is recorded to two decimal places. A second, read-only `pattern_threshold` variant is exposed only via the repair-shop retrieval capability when the caller passes a `projection` query parameter equal to `pattern_threshold`: in that variant, the server checks whether the shop has accumulated three or more collusion flags within the 90-day lookback, and if so projects the trust score as the smaller of the current `trust_score` and 0.20 — a single aggregate cap rather than one decay per flag. The `pattern_threshold` variant never mutates state. With three collusion flags on a shop currently at 1.00, the canonical `per_flag` variant yields 0.40 (1.00 − 3 × 0.20) while the `pattern_threshold` variant yields 0.20 — different results for identical inputs by design.

### 3.6. Disbursement: Payouts, Bank Settlement, and Reversal

Once a claim reaches `APPROVED` and its `net_payout_cents` is strictly greater than zero, a `PayoutOfficer` may create a payout against the claim. Creation establishes a single `Payout` row in `PENDING` status whose `claim_id` references the parent claim and whose `amount_cents` is a snapshot of the claim's current `net_payout_cents`. Two simultaneous payout-creation requests for the same claim serialise on the per-claim uniqueness constraint; the loser is rejected with `ERR_PAYOUT_ALREADY_EXISTS`. Creation also moves the claim from `APPROVED` to `PAID` and records the audit log event.

After creation, the payout is awaiting bank settlement. The system exposes two test-driving control capabilities — a bank-settle event and a bank-fail event — that drive the asynchronous settlement outcome. Bank settlement transitions the payout from `PENDING` to `SETTLED`, stamps the payout's `settled_at` and a server-generated `bank_reference`, and cascades the claim from `PAID` to `CLOSED`. The cascade depth is three levels: payout creation produces a `PENDING` payout, the bank-settle event marks the payout `SETTLED`, and the same event automatically advances the claim to `CLOSED`. A policy event sync (`POLICY_CLAIM_CLOSED`) is written to the event log on closure.

A bank failure is the compensating path. When the bank-fail event fires on a `PENDING` payout, the payout transitions to `REVERSED` and the claim reverts from `PAID` back to `APPROVED` so that a new payout attempt can be made; the claim's `gross_payout_cents` and `net_payout_cents` are deliberately left unchanged because only the payout row reverses. A bank-fail event followed by another payout creation for the same claim is allowed (the first payout is in `REVERSED` and no longer counts toward the per-claim uniqueness constraint).

After a payout has settled, third-party recoveries may continue to arrive. The `PayoutOfficer` records each recovery with a positive `amount_cents`; the server adds it to `Claim.subrogation_recovery_cents`, recomputes `Claim.net_payout_cents` in its `post_recovery` variant (gross stays fixed; net drops by the new recovery), and writes an audit `PAYOUT_EVENT`. The original `Payout.amount_cents` is not retroactively altered — recoveries are bookkeeping entries, not payment reversals. Recording a recovery requires the claim to be in `PAID` status with the underlying payout in `SETTLED`; if a bank-fail event has just flipped the claim back to `APPROVED`, a racing subrogation post is rejected with `ERR_INVALID_STATE`. A recovery that, taken together with `salvage_value_cents`, would push their combined sum above `gross_payout_cents` (and therefore push net below zero) is rejected with `ERR_NEGATIVE_NET_PAYOUT`.

### 3.7. Appeals

A customer whose claim has reached `DENIED` may file exactly one appeal by submitting their `grounds` for reconsideration. The appeal capability is restricted to the original claimant (the appeal's `requestor_id` is set from the caller's `X-User-ID` and must equal `Claim.claimant_id`). Filing creates an `Appeal` row in `SUBMITTED` status, which the server immediately auto-advances to `UNDER_RECONSIDERATION` as a side effect of creation; the parent claim transitions from `DENIED` to `APPEALED`. Two simultaneous appeal-creation attempts on the same denied claim serialise on the per-claim uniqueness constraint; the loser is rejected with `ERR_APPEAL_ALREADY_EXISTS`.

Before the secondary review concludes, the customer may withdraw an appeal that is still in `SUBMITTED` (the brief window before the auto-advance), which moves the appeal to `WITHDRAWN` and reverts the claim from `APPEALED` back to `DENIED`. Withdrawal is restricted to the `requestor_id`; another customer cannot withdraw someone else's appeal.

Secondary review is performed by a `Reviewer` who supplies an `outcome` of either `OVERTURN` or `UPHOLD` together with a written `rationale`. The acting reviewer's `X-User-ID` must differ from `Investigation.adjuster_id` AND must differ from the `reviewer_id` of the primary `ReviewDecision` row for this claim (segregation of duties at the secondary level); a violation in either direction is rejected with `ERR_SEGREGATION_OF_DUTIES`. The server populates the appeal's `secondary_reviewer_id` from the actor and stamps the appeal's `final_decision_recorded_at`. An `OVERTURN` outcome writes a new `ReviewDecision` row with `review_level` `SECONDARY` and `outcome` `APPROVE`, transitions the appeal to `OVERTURNED`, transitions the claim from `APPEALED` to `APPROVED`, and recomputes `Claim.gross_payout_cents` and `Claim.net_payout_cents` against the latest figures. An `UPHOLD` outcome writes a `ReviewDecision` row with `review_level` `SECONDARY` and `outcome` `DENY`, transitions the appeal to `UPHELD_DENIAL`, and transitions the claim from `APPEALED` directly to `CLOSED` (denial is final — no second appeal is permitted because each claim is allowed at most one appeal).

### 3.8. Fraud Flagging and Audit Retrieval

A `PlatformAdmin` adds a fraud flag against a claim by supplying the `signal` (`DUPLICATE_PATTERN`, `REPAIR_SHOP_COLLUSION`, `DOCUMENT_FORGERY`, or `RAPID_RESUBMISSION`), the `severity` (a value in the inclusive range zero to one), and — for the collusion signal — the implicated `repair_shop_id`. Adding a flag emits an audit `FRAUD_FLAG_ADDED` event. The flag itself does not immediately recompute `Claim.fraud_score` or decay the shop's `trust_score`; both happen at the next submit-for-review event for the affected claim, which is the point at which the canonical fraud-score and trust-decay calculations run.

The audit log for any claim is retrievable by `Reviewer` and `PlatformAdmin` callers and ordered by `created_at` ascending. Filtering by `event_type` is supported, as is pagination via `limit` and `offset`. Each entry exposes `claim_id`, `actor_id`, `actor_role`, `event_type`, `from_state`, `to_state`, and the structured `payload` whose contents depend on the event (for example, a `REVIEW_DECISION` payload includes the outcome and reviewer; a `PAYOUT_EVENT` payload includes the amounts and bank reference; a `FRAUD_FLAG_ADDED` payload includes the signal and severity).

### 3.9. Reference Data and Test-Driving Controls

The system's reference data — policies, adjusters, and repair shops — is administered by a `PlatformAdmin`. A new `Policy` is created with the exact fields described in §2.6 (`policy_number`, `insured_party_id`, `coverage_type`, `coverage_limit_cents`, `deductible_cents`, `coinsurance_ratio`, `effective_from`, `effective_to`, and an optional `reporting_window_days`); the policy's `status` is automatically set to `ACTIVE` on creation, and may later be moved to `SUSPENDED`, `EXPIRED`, or `CANCELLED` via the policy update capability that accepts an optional `status` and an optional `version` for OCC.

A new `Adjuster` is created with `full_name`, a unique `license_number`, and a `specialty` of `AUTO`, `PROPERTY`, or `LIABILITY`; the adjuster's roster `status` defaults to `ACTIVE` and may be moved to `SUSPENDED` via the adjuster update capability. A new `RepairShop` is created with a `name` and a unique `tax_id`; the shop starts at `trust_score` 1.00 and `status` `ACTIVE`. The repair-shop update capability accepts `status` (and the optional `version` for OCC), but admin overrides cannot raise `trust_score` — only the canonical decay calculation moves it downward.

The system exposes three test-driving control capabilities for use during automated testing only. An admin-only clock-advance capability accepts a target `to_iso8601` instant and advances the simulated server clock to that instant; subsequent transitions whose preconditions depend on time (most notably the reporting-window check) observe the advanced clock. An admin-only bank-settle capability accepts a `payout_id` and drives the corresponding `Payout` from `PENDING` to `SETTLED`, cascading the claim from `PAID` to `CLOSED`. An admin-only bank-fail capability also accepts a `payout_id` and drives the payout to `REVERSED`, reverting the claim from `PAID` to `APPROVED`. All three control capabilities require the `X-Admin-Token` header in addition to the standard auth headers.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (a policy, an adjuster, a repair shop, a claim, an investigation, an estimate line item, a primary review decision, a payout, an appeal, a secondary review decision, or a fraud flag) return HTTP `201 Created`. Operations that modify an existing resource — including state transitions on a claim, on an investigation, on an appeal, or on a payout, and the test-driving control capabilities — return HTTP `200 OK`. Reads return `200 OK`. Errors carry the HTTP status given in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST   | `/policies` | Create a Policy | PlatformAdmin |
| GET    | `/policies/{id}` | Get a Policy | PlatformAdmin, Customer, Adjuster, Reviewer, PayoutOfficer |
| PATCH  | `/policies/{id}` | Suspend, expire, or reactivate a policy | PlatformAdmin |
| POST   | `/adjusters` | Create an Adjuster | PlatformAdmin |
| GET    | `/adjusters` | List adjusters with optional filters | PlatformAdmin, Reviewer |
| PATCH  | `/adjusters/{id}` | Update adjuster status | PlatformAdmin |
| POST   | `/repair-shops` | Create a RepairShop | PlatformAdmin |
| GET    | `/repair-shops/{id}` | Get a RepairShop (optional `projection=pattern_threshold` returns a what-if projected `trust_score`) | PlatformAdmin, Adjuster, Reviewer |
| PATCH  | `/repair-shops/{id}` | Manually update a repair shop | PlatformAdmin |
| POST   | `/claims` | Intake a new claim | Customer |
| GET    | `/claims/{id}` | Get a claim | Customer, Adjuster, Reviewer, PayoutOfficer, PlatformAdmin |
| GET    | `/claims` | List claims with optional filters | Customer, Adjuster, Reviewer, PayoutOfficer, PlatformAdmin |
| GET    | `/claims/{id}/estimate` | Read-only provisional payout estimate | Customer, Adjuster, Reviewer, PlatformAdmin |
| POST   | `/claims/{id}/investigations` | Open investigation; assign adjuster | Adjuster |
| PATCH  | `/claims/{id}/investigations/{inv_id}` | Update investigation fields | Adjuster |
| POST   | `/claims/{id}/investigations/{inv_id}/estimates` | Append a repair-shop estimate line item | Adjuster |
| POST   | `/claims/{id}/investigations/{inv_id}/reject` | Reject the investigation; revert claim to INTAKE | Adjuster |
| POST   | `/claims/{id}/submit-for-review` | Submit for review; runs calculations and transitions claim to UNDER_REVIEW | Adjuster |
| POST   | `/claims/{id}/decisions` | Record a primary review decision | Reviewer |
| POST   | `/claims/{id}/payouts` | Create a payout for an APPROVED claim | PayoutOfficer |
| GET    | `/claims/{id}/payouts` | Get the payout for a claim | Customer, PayoutOfficer, Reviewer, PlatformAdmin |
| POST   | `/claims/{id}/subrogations` | Record a third-party recovery against a PAID claim | PayoutOfficer |
| POST   | `/claims/{id}/appeals` | Customer appeals a denial | Customer |
| DELETE | `/claims/{id}/appeals/{appeal_id}` | Customer withdraws an appeal | Customer |
| POST   | `/claims/{id}/appeals/{appeal_id}/decisions` | Secondary reviewer records final appeal decision | Reviewer |
| POST   | `/claims/{id}/fraud-flags` | Add a fraud flag | PlatformAdmin |
| GET    | `/claims/{id}/audit-log` | Return the audit log for this claim | Reviewer, PlatformAdmin |
| POST   | `/_clock/advance` | Advance the simulated server clock | PlatformAdmin |
| POST   | `/_events/bank-settle` | Drive bank settlement event for a PENDING payout | PlatformAdmin |
| POST   | `/_events/bank-fail` | Drive bank failure event for a PENDING payout | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_INTAKE` | 409 Conflict |
| `ERR_POLICY_INACTIVE` | 422 Unprocessable Entity |
| `ERR_LOSS_OUTSIDE_POLICY_PERIOD` | 422 Unprocessable Entity |
| `ERR_REPORTING_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ADJUSTER_SPECIALTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REPAIR_SHOP_BLACKLISTED` | 422 Unprocessable Entity |
| `ERR_PHOTOS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ESTIMATE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DOCUMENT_AUTHENTICITY_FAILED` | 422 Unprocessable Entity |
| `ERR_FRAUD_HOLD` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_NET_PAYOUT` | 422 Unprocessable Entity |
| `ERR_APPEAL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PAYOUT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_INVESTIGATION_ALREADY_OPEN` | 409 Conflict |

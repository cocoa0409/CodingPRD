# Commercial General Liability API — Product Requirements Document

## 1. Introduction

This document specifies the Commercial General Liability (CGL) administration platform — a multi-carrier system that governs the full back-office lifecycle of a CGL program, from policy issuance through claims handling, certificate management, and the year-end premium audit that reconciles what was estimated against what actually happened. Each carrier (an **insurer**) operates as an isolated tenant: its insureds, certificate holders, policies, claims, endorsements, certificates, audits, and loss runs are scoped to it, and no reference may cross a carrier boundary.

The platform's defining tension is the reconciliation between *estimated* and *audited* premium computed on identical rating mechanics, layered over the *aggregate-limit erosion* model that the General Liability form imposes. A policy is bound on an exposure estimate, claims erode two separate aggregate buckets as losses are incurred, and at expiry an auditor enumerates the real exposure and settles the difference. Coverage itself is gated differently depending on whether the policy is written on an occurrence or a claims-made trigger, and the issuance of a Certificate of Insurance to a third party must respect both the live aggregate health of the policy and the additional-insured endorsements that back it. Because erosion math depends on a consistent view of remaining limits, the platform uses optimistic concurrency on the policy so that a financial posting computed against a stale view of remaining room is rejected rather than silently corrupting the ledger.

This API serves five operational roles — carrier administrators, underwriters, claims adjusters, premium auditors, and the certificate holders who consume coverage evidence — each with a distinct slice of the workflow. The remainder of this document defines the global contract every endpoint obeys, the business logic that drives each lifecycle, the endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_USER_CONTEXT`. When a well-identified user invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles: `InsurerAdmin`, `Underwriter`, `ClaimsAdjuster`, `PremiumAuditor`, and `CertificateHolder`. The `InsurerAdmin` is the carrier operations superuser — it provisions insurers, insureds, and certificate holders, advances the business clock, schedules and disputes audits, and reads everything. The `Underwriter` owns the policy issuance lifecycle, additional-insured endorsements, and certificates. The `ClaimsAdjuster` owns claims and the financial transactions that drive aggregate erosion. The `PremiumAuditor` owns premium audits, their exposure records, and audit finalization. The `CertificateHolder` is a third party with read-only reach into the data relevant to its certificates.

Four of these roles — `InsurerAdmin`, `Underwriter`, `ClaimsAdjuster`, and `PremiumAuditor` — carry an **opaque** identity: for these, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may accept and record it, but it does not compare it to the `id` of any stored resource when deciding access. The `CertificateHolder` role, by contrast, is **entity-backed**: when `X-User-Role` is `CertificateHolder`, `X-User-ID` is the `id` of the acting `CertificateHolder` record, and any ownership check on a resource that references a certificate holder compares that resource's `certificate_holder_id` to `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — insurers, insureds, certificate holders, policies, additional-insured endorsements, certificates of insurance, claims, premium audits, exposure records, and loss runs — carries a server-managed `id`, a string formatted as a UUID with no type prefix. Each also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured when the resource is first created.

Most of these resources additionally carry an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and a `version` (an integer that starts at its initial value and increments by one on every mutation of the resource). The single exception is the **ClaimTransaction**: a claim transaction is an immutable ledger entry, so it carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`. When a transaction is posted, it is the parent `Claim` and the governing `Policy` whose `updated_at` and `version` advance, never the transaction itself.

Derived fields are first-class resource state. When a posting recomputes a claim's `incurred_cents` and `recognized_incurred_cents`, or cascades into a policy's `general_aggregate_remaining_cents`, `products_aggregate_remaining_cents`, or `posture`, those writes are mutations of the owning resource: each refreshes that resource's `updated_at` and increments its `version`.

### 2.5. The Insurer Business Clock

Time in this system is not wall-clock time; it is a per-insurer logical clock. Each `Insurer` carries a `current_date` that begins at `2026-01-01T00:00:00.000Z` when the carrier is created and advances only when an administrator explicitly moves it forward. Advancing the clock supplies a target instant as `to_iso8601`; the new value must be at or after the present `current_date`, and an attempt to move it backward is rejected with `ERR_CLOCK_NOT_MONOTONIC`.

The clock is the trigger for time-based state changes. Whenever the clock advances, every `IN_FORCE` policy whose `expiration_date` is at or before the new `current_date` transitions to `EXPIRED`, and that expiry cascades — see §2.6 and §3 for the downstream certificate effects. All date comparisons that define a policy period treat the period as half-open: the `effective_date` is included and the `expiration_date` is the exclusive upper bound.

### 2.6. Hierarchical Consistency and Cascades

The platform applies all erosion, posture, reconciliation, and expiry effects atomically, inside the request that triggers them. A single operation frequently mutates more than one resource, and every secondary effect is part of the contract:

- When the clock advance expires an `IN_FORCE` policy, every `ISSUED` Certificate of Insurance on that policy is simultaneously moved from `ISSUED` to `EXPIRED`.
- When a policy is cancelled from `IN_FORCE`, every `ACTIVE` additional-insured endorsement on it is moved to `VOID` and every `ISSUED` certificate on it is moved to `REVOKED`.
- When an additional-insured endorsement leaves `ACTIVE` — either because it is voided or because a newer endorsement supersedes it — every `ISSUED` certificate that points at that endorsement is moved to `REVOKED`.
- When a claim transaction is posted, the claim's incurred figures are recomputed, the policy's two aggregate-remaining figures are recomputed, and the policy's `posture` is re-derived, all in the same request.
- When a premium audit finalizes or waives, the parent policy is driven to `AUDIT_CLOSED` and its `audited_premium_cents` is written.

Each resource a cascade touches is independently mutated: its `updated_at` is refreshed and its `version` is incremented. The policy `version` in particular advances on bind, activate, cancel, clock-driven expiry, every claim transaction, every claim close/deny/reopen, and material audit finalization — this monotonic counter is the basis of the optimistic-concurrency contract in §2.8.

### 2.7. Aggregate-Limit Erosion and Policy Posture

A CGL policy carves its incurred losses into two independently conserved buckets. The **General Aggregate** caps non-products losses and the **Products/Completed-Operations Aggregate** is a separate bucket; products losses never erode the general aggregate and vice versa. A claim's bucket is fixed at creation: a claim whose `loss_type` is `PRODUCTS_COMPLETED_OPS` lands in the `PRODUCTS` bucket and every other loss type lands in `GENERAL`, recorded on the claim's `aggregate_bucket`.

After any change to a claim's incurred figure, the system re-derives how much of each claim's loss is actually *recognized* against the aggregates, and from that derives the policy's aggregate-health gate, its `posture`. Posture is a computed dimension that evolves independently of the policy's `status`; the two move on separate axes. The precise erosion and posture formulas are given in §3.5 and §3.6 as part of the claims workflow.

### 2.8. Optimistic Concurrency on the Policy

Two write paths can act on a policy whose remaining-limit state another writer may have changed since the caller last read it, and both are guarded by optimistic concurrency keyed on the policy's `version`.

The first is posting a claim transaction. Because a transaction's erosion math is evaluated against the aggregate room the adjuster observed, a transaction must carry `expected_policy_version` equal to the policy's current `version` at the moment it is posted. If a prior transaction — on this claim or any sibling claim under the same policy — has since eroded an aggregate and advanced the policy's `version`, the adjuster's view of remaining room is stale and the post is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). The one exception is the very first `RESERVE_SET` that opens a claim: that posting has no prior observation to pin, so `expected_policy_version` is omitted on it and supplied on every subsequent transaction.

The second is finalizing a premium audit. Finalization writes the policy's `audited_premium_cents` and drives the policy to `AUDIT_CLOSED`, and it must carry `expected_policy_version` matching the policy's current `version`. If a late claim transaction has advanced the policy's `version` since the auditor computed the net adjustment, the figure was computed against a policy state that no longer holds, and the finalize is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). No endpoint other than these two takes a policy-version field.

### 2.9. Monetary Precision and Premium Rating

All monetary amounts in the system are stored and returned as whole integer cents — limits, premiums, reserves, payments, recoveries, aggregate-remaining figures, and adjustments alike. There are no fractional cents and no floating-point money.

Premium rating itself follows a fixed order that both the estimated and audited computations share, so that the two are exactly reconcilable. The rate, `rate_per_unit_cents`, is expressed in cents per one thousand dollars of basis exposure. To rate a given basis exposure, the whole-dollar basis is divided by one thousand and the quotient is reduced to a whole number by discarding any remainder (any partial thousand is dropped before multiplying, never rounded), then multiplied by the rate. This truncate-then-multiply order is mandatory and identical in both directions. The full formulas appear in §3.2 (estimated) and §3.8 (audited).

### 2.10. Reference Integrity and Path Validation

Foreign keys carried in a request body — among them `insurer_id`, `insured_id`, `policy_id`, `certificate_holder_id`, `additional_insured_endorsement_id`, `claim_id`, and `premium_audit_id` — must resolve to an existing resource within the same insurer. A body foreign key that does not resolve, or that points at a resource belonging to a different carrier, is rejected with `ERR_REFERENCE_NOT_FOUND`.

When a request addresses resources through the URL path, each path segment's identifier is validated left to right, and the first identifier that does not name an existing resource yields `ERR_NOT_FOUND` before any later segment or body rule is evaluated.

### 2.11. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication comes first: a missing or malformed user context (`ERR_MISSING_USER_CONTEXT`) is detected before anything else, then role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Next the system confirms that every path-addressed resource exists (`ERR_NOT_FOUND`), then that every body foreign key resolves within the insurer (`ERR_REFERENCE_NOT_FOUND`). Only then is the target resource's state checked to confirm the requested transition is legal from its current state (`ERR_INVALID_STATE`). Business constraints — structural, temporal, fiscal, safety, and the like — are evaluated after the state gate, and the optimistic-concurrency check on the policy version runs last among the body checks. Where a single workflow has its own internal ordering among business rules, that ordering is stated alongside the workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Carrier Setup: Insurers, Insureds, and Certificate Holders

A carrier tenant is created as an `Insurer` with a legal `name` and a five-digit NAIC company code, `naic_code`. At creation the carrier may optionally supply an `audit_waiver_threshold_cents`; if omitted, this defaults to fifty thousand cents (five hundred dollars), and it governs whether a year-end audit is small enough to waive (see §3.8). The insurer's `current_date` is initialized to `2026-01-01T00:00:00.000Z` as described in §2.5.

Under a carrier, an administrator or underwriter registers a **Named Insured** — the First Named Insured on a policy — with its parent `insurer_id`, a `legal_name`, a Federal Employer ID Number `fein`, and a `primary_basis` declaring whether the insured's exposure is rated on `PAYROLL` or on `SALES`. A `fein` must be unique within the carrier; a repeat is rejected with `ERR_DUPLICATE_FEIN`.

Separately, an administrator or underwriter registers a **Certificate Holder** — a landlord, general contractor, or other party that will receive evidence of coverage — with its `insurer_id`, a `holder_name`, and a mailing `address`. Certificate holders are the parties named on additional-insured endorsements and on certificates of insurance, and a `CertificateHolder`-role user reads only the data tied to its own holder record.

### 3.2. Drafting and Binding a Policy

An `Underwriter` drafts a **Policy** against an insured by supplying the `insurer_id`, the `insured_id` of the First Named Insured, a `policy_number` unique within the carrier (a repeat is rejected with `ERR_DUPLICATE_POLICY_NUMBER`), the `coverage_trigger` (`OCCURRENCE` or `CLAIMS_MADE`), an optional `retroactive_date`, the `effective_date` and `expiration_date` bounding the policy period, the `each_occurrence_limit_cents`, the `general_aggregate_limit_cents`, the `products_aggregate_limit_cents`, the rating inputs `premium_basis` (`PAYROLL` or `SALES`), `rate_per_unit_cents`, and `minimum_premium_cents`, and the `estimated_exposure_units` — the estimated basis exposure in whole dollars at binding. A freshly created policy is `DRAFT`. Apart from resolving `insurer_id` and `insured_id` (§2.10) and enforcing `policy_number` uniqueness, draft creation does not validate the presence or value of these supplied fields: any field omitted at draft is simply stored as null, and the trigger-dependent and structural checks above — including those that consult `coverage_trigger` — are enforced only at bind, never at create.

Binding the policy advances it from `DRAFT` to `BOUND` and is the moment the estimated premium is computed. Before the bind is allowed, four structural conditions are checked. A claims-made policy must carry a non-null `retroactive_date` that is on or before its `effective_date`; if it is missing or later than the effective date, the bind is rejected with `ERR_RETRO_DATE_REQUIRED`. An occurrence policy must carry a null `retroactive_date`; supplying one is rejected with `ERR_RETRO_DATE_NOT_ALLOWED`. The `effective_date` must be strictly before the `expiration_date`, else `ERR_INVALID_POLICY_PERIOD`. And the `products_aggregate_limit_cents` must be no greater than the `general_aggregate_limit_cents`, else `ERR_AGGREGATE_LIMIT_INVALID`.

On a successful bind, the system computes the **estimated premium** and stores it in `estimated_premium_cents`. The basis is the policy's `estimated_exposure_units` in whole dollars; this is divided by one thousand and reduced to a whole number by discarding any remainder, then multiplied by `rate_per_unit_cents` to produce a raw premium. The stored `estimated_premium_cents` is the greater of that raw figure and the policy's `minimum_premium_cents` — the policy never bills below its minimum floor. Binding also initializes `general_aggregate_remaining_cents` to `general_aggregate_limit_cents` and `products_aggregate_remaining_cents` to `products_aggregate_limit_cents`, sets `posture` to `HEALTHY`, and increments the policy's `version`. Until a policy is bound, its `estimated_premium_cents`, `audited_premium_cents`, both aggregate-remaining figures, and `posture` are null.

### 3.3. Activating, Expiring, and Cancelling a Policy

A `BOUND` policy is activated into force by an `Underwriter`, moving it from `BOUND` to `IN_FORCE`. Activation is permitted only once the insurer's `current_date` has reached the policy's `effective_date`; an attempt before then is rejected with `ERR_POLICY_NOT_YET_EFFECTIVE`. Activation increments the policy `version`.

A policy leaves force in one of two ways. It expires automatically when the insurer clock advances to or past its `expiration_date`, moving from `IN_FORCE` to `EXPIRED` and cascading its issued certificates to `EXPIRED` as described in §2.6, with the policy `version` advancing. Alternatively an `Underwriter` cancels it. Cancelling a `BOUND` policy moves it straight to `CANCELLED` with no further effects beyond the version bump. Cancelling an `IN_FORCE` policy is blocked while any claim on it is still live — that is, in `OPEN`, `RESERVED`, `PAID`, or `REOPENED` — and such an attempt is rejected with `ERR_OPEN_CLAIMS_BLOCK_CANCEL`; when permitted, cancellation moves the policy to `CANCELLED`, voids every `ACTIVE` endorsement on it, revokes every `ISSUED` certificate on it, and increments the version. `CANCELLED` and `AUDIT_CLOSED` are the policy's terminal states.

### 3.4. Additional-Insured Endorsements and Certificates of Insurance

An `Underwriter` adds an **Additional Insured Endorsement** to a policy by supplying the `policy_id`, the `certificate_holder_id` of the party being added, an ISO `form_number`, and an `ai_effective_date` on which the additional-insured status begins. The `form_number` is one of `CG2010` (ongoing operations), `CG2037` (completed operations), or `CG2010_2037` (both); from it the system derives the endorsement's `scope` — `ONGOING_OPS`, `COMPLETED_OPS`, or `BOTH` respectively. The `ai_effective_date` must fall within the policy period, at or after the `effective_date` and strictly before the `expiration_date`; otherwise the request is rejected with `ERR_AI_DATE_OUTSIDE_PERIOD`. A new endorsement is born `ACTIVE`. If an `ACTIVE` endorsement already exists for the same `certificate_holder_id` on the same policy, creating the newer one moves the prior one from `ACTIVE` to `SUPERSEDED`, and any `ISSUED` certificate pointing at the superseded endorsement is revoked. An `Underwriter` may also explicitly void an endorsement, moving it from `ACTIVE` to `VOID`; voiding likewise revokes any `ISSUED` certificate that points at it. `SUPERSEDED` and `VOID` are terminal endorsement states.

A **Certificate of Insurance** is drafted by an `Underwriter` with the `policy_id`, the recipient `certificate_holder_id`, an optional `additional_insured_endorsement_id` (null for a purely informational certificate), and a `names_as_additional_insured` boolean that defaults to false and declares whether the certificate asserts the holder is an additional insured. A drafted certificate is `DRAFT`.

Issuing a certificate moves it from `DRAFT` to `ISSUED` and freezes a snapshot of the policy's coverage onto it. Issuance is gated by three conditions. The policy must be `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`. The policy's `posture` must not be `EXHAUSTED`, else `ERR_POLICY_EXHAUSTED`. And if `names_as_additional_insured` is true, the certificate must reference, through its `additional_insured_endorsement_id`, an endorsement that is currently `ACTIVE` and whose `certificate_holder_id` equals the certificate's own `certificate_holder_id`; if no such active matching endorsement backs the assertion, issuance is rejected with `ERR_AI_ENDORSEMENT_MISSING`. On issuance the system sets `issue_date` to the insurer's `current_date`, freezes `snapshot_each_occurrence_cents` from the policy's `each_occurrence_limit_cents`, and freezes `snapshot_general_aggregate_remaining_cents` from the policy's then-current `general_aggregate_remaining_cents`. An `Underwriter` may later revoke an issued certificate, moving it from `ISSUED` to `REVOKED`. Beyond explicit revocation, a certificate also reaches `REVOKED` through the cascade when its policy is cancelled or its backing endorsement leaves `ACTIVE`, and reaches `EXPIRED` through the cascade when its policy expires. `REVOKED` and `EXPIRED` are terminal certificate states.

### 3.5. Opening Claims and the Coverage Trigger Test

A `ClaimsAdjuster` opens a **Claim** against a policy with the `policy_id`, a `claimant_name`, a `loss_type` (`BODILY_INJURY`, `PROPERTY_DAMAGE`, or `PRODUCTS_COMPLETED_OPS`), an `occurrence_date` on which the loss occurred, and a `reported_date` on which it was first reported to the carrier. The claim is born `OPEN`, its `aggregate_bucket` is fixed from the loss type as described in §2.7, and its `incurred_cents` and `recognized_incurred_cents` begin at zero.

A claim's financial life begins with its first reserve. Posting the opening `RESERVE_SET` transaction moves the claim from `OPEN` to `RESERVED`, and it is at this first reserve that the **coverage trigger test** is applied. Two preconditions gate it: the policy must be `IN_FORCE` (else `ERR_POLICY_NOT_IN_FORCE`), and coverage must apply under the trigger test. The policy period is the half-open interval running from the `effective_date` inclusive to the `expiration_date` exclusive.

For an `OCCURRENCE` policy, coverage requires only that the `occurrence_date` fall at or after the `effective_date` and strictly before the `expiration_date`; the `reported_date` and `retroactive_date` are not consulted. If the occurrence falls outside that window, the reserve is rejected with `ERR_OCCURRENCE_OUTSIDE_PERIOD`.

For a `CLAIMS_MADE` policy the test is different and the same occurrence-and-report pair can be covered under one trigger yet excluded under the other. Two conditions must hold, and they are checked in this order. First, the `occurrence_date` must be at or after the policy's `retroactive_date`; if the occurrence predates the retroactive date the reserve is rejected with `ERR_CLAIM_BEFORE_RETRO_DATE`. Only if that passes is the second condition checked: the `reported_date` must fall within the policy period, at or after the `effective_date` and strictly before the `expiration_date`, and otherwise the reserve is rejected with `ERR_OCCURRENCE_OUTSIDE_PERIOD`. The retroactive-date check therefore always precedes the reported-in-period check.

### 3.6. Claim Transactions, Incurred Amounts, and Aggregate Erosion

A claim's financial position is built up from a ledger of **claim transactions**, each posted against a `claim_id` with a `txn_type`, a positive `amount_cents`, and an optional `memo`. The four transaction types are `RESERVE_SET` (establish or raise reserve), `RESERVE_RELEASE` (release reserve), `PAYMENT` (pay the claimant), and `RECOVERY` (recover from a third party). Every transaction is stamped with a monotonic per-claim `posted_sequence`, the first posted transaction on a claim being sequence one; this pins replay order even though the incurred sum itself is order-independent. The `amount_cents` must be a positive integer, else `ERR_INVALID_AMOUNT`. A `RESERVE_RELEASE` may not exceed the claim's current open reserve and a `RECOVERY` may not exceed the claim's cumulative payments; either overrun is rejected with `ERR_RELEASE_EXCEEDS_RESERVE`.

Each transaction advances the claim's state along its lifecycle. The opening `RESERVE_SET` takes the claim from `OPEN` (or from `REOPENED`) to `RESERVED`. While `RESERVED`, further `RESERVE_SET`, `RESERVE_RELEASE`, and `RECOVERY` postings keep the claim `RESERVED`. A `PAYMENT` moves the claim from `RESERVED` to `PAID`. Once `PAID`, additional `PAYMENT`, `RESERVE_SET`, `RESERVE_RELEASE`, and `RECOVERY` postings are still permitted and leave the claim `PAID`. Every posting after the opening reserve must satisfy the optimistic-concurrency rule of §2.8, carrying an `expected_policy_version` that matches the policy's current `version` or being rejected with `ERR_STALE_POLICY_VERSION`.

After every posting the claim's `incurred_cents` is recomputed. The open reserve is the sum of all `RESERVE_SET` amounts minus the sum of all `RESERVE_RELEASE` amounts, and is itself floored at zero. The incurred figure is then the open reserve plus the sum of all `PAYMENT` amounts minus the sum of all `RECOVERY` amounts, with the whole figure floored at zero. The recompute is then cascaded into aggregate erosion and posture.

**Aggregate erosion** decides how much of each claim's incurred loss is actually charged against the policy's two aggregate buckets, and writes each claim's `recognized_incurred_cents`. It considers every non-`DENIED` claim of the policy (a `DENIED` claim contributes zero), processed in a fixed order: ascending by the `posted_sequence` of each claim's first `RESERVE_SET`, and where that ties, ascending by the claim's `created_at`. For each claim in that order, its incurred amount is first capped at the policy's `each_occurrence_limit_cents` to yield a per-occurrence-capped figure. The claim then draws against the remaining room in its own bucket — the bucket's limit (`general_aggregate_limit_cents` for `GENERAL` claims, `products_aggregate_limit_cents` for `PRODUCTS` claims) less the recognized amounts already accumulated for that bucket in this pass. The amount recognized for the claim is the per-occurrence-capped figure or the remaining bucket room, whichever is smaller, and never less than zero; that recognized amount is added to the running total for its bucket and stored as the claim's `recognized_incurred_cents`. The per-occurrence cap is therefore always applied before the aggregate cap. After all claims are processed, `general_aggregate_remaining_cents` is the general limit less the total recognized in the `GENERAL` bucket (floored at zero) and `products_aggregate_remaining_cents` is the products limit less the total recognized in the `PRODUCTS` bucket (floored at zero). The two buckets are conserved entirely separately.

**Posture** is then re-derived from the two remaining figures. If both `general_aggregate_remaining_cents` and `products_aggregate_remaining_cents` are zero, the posture is `EXHAUSTED`. Otherwise, if either bucket's remaining amount has fallen to one quarter or less of that bucket's limit — that is, the general remaining is at or below one quarter of `general_aggregate_limit_cents`, or the products remaining is at or below one quarter of `products_aggregate_limit_cents`, where the one-quarter threshold is computed by multiplying the limit by one and dividing by four and discarding any remainder — the posture is `IMPAIRED`. At exactly one quarter remaining the policy is impaired. Otherwise the posture is `HEALTHY`. Each of these recomputes mutates the policy, advancing its `version` and `updated_at`.

### 3.7. Closing, Denying, and Reopening Claims

A claim is closed by a `ClaimsAdjuster` only when its net open reserve — total `RESERVE_SET` less total `RESERVE_RELEASE` — is exactly zero; a non-zero open reserve blocks the close with `ERR_OPEN_RESERVE_REMAINS`. Closing is permitted from `RESERVED` or from `PAID`, moves the claim to `CLOSED`, and cascades aggregate erosion and posture, since released reserve room may return to the aggregates. The close increments the policy `version`.

A claim may instead be denied, but only if it has never carried a `PAYMENT` transaction; an attempt to deny a claim that has been paid is rejected with `ERR_PAID_CLAIM_CANNOT_DENY`. Denial is reachable from `OPEN` and from `RESERVED` (a `PAID` claim is structurally blocked from denial by the no-payment rule). Denial moves the claim to `DENIED` and, because a denied claim contributes nothing to erosion, drops its `recognized_incurred_cents` to zero and cascades aggregate erosion and posture so that the general or products room it had consumed returns to the policy. Denial increments the policy `version`. `CLOSED` and `DENIED` are the claim's terminal states, except that a closed claim may be reopened.

Reopening a `CLOSED` claim is permitted only while the policy is `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`; it moves the claim from `CLOSED` to `REOPENED` and increments the policy `version`. A reopened claim re-enters its financial life through a fresh `RESERVE_SET`, which — subject to the optimistic-concurrency check — moves it from `REOPENED` back to `RESERVED` and resumes erosion.

### 3.8. Premium Audits, Exposure Records, and Reconciliation

After a policy has expired, the carrier reconciles the estimate against reality through a **Premium Audit**. A `PremiumAuditor` or `InsurerAdmin` schedules an audit on a policy with the `policy_id` and an `audit_basis` (`PAYROLL` or `SALES`) that must equal the policy's `premium_basis`; a mismatch is rejected with `ERR_AUDIT_BASIS_MISMATCH`. A scheduled audit is `SCHEDULED`, its `audited_exposure_units` begins at zero, its `computed_audited_premium_cents` and `net_adjustment_cents` are null, and its `revision_round` is zero.

A `PremiumAuditor` starts the audit, moving it from `SCHEDULED` to `IN_PROGRESS`; starting requires that the policy be `EXPIRED`, else `ERR_POLICY_NOT_AUDITABLE`. While in progress, the auditor records one **Exposure Record** per ISO classification, each carrying the parent `premium_audit_id`, a `class_code`, and the actual audited basis in whole dollars for that class, `basis_amount_units`. The audit's `audited_exposure_units` is maintained as the order-independent sum of `basis_amount_units` across all its exposure records.

Completing the audit moves it from `IN_PROGRESS` to `COMPLETED` and requires at least one exposure record, else `ERR_NO_EXPOSURE_RECORDS`. On completion the **audited premium** is computed on exactly the same mechanics as the estimated premium so the two reconcile: the summed `audited_exposure_units` is divided by one thousand, reduced to a whole number by discarding any remainder, and multiplied by the policy's `rate_per_unit_cents`; the resulting raw figure is then taken as the greater of itself and the policy's `minimum_premium_cents`, and stored as `computed_audited_premium_cents`. The `net_adjustment_cents` is this computed audited premium minus the policy's `estimated_premium_cents` — a positive figure is additional premium owed by the insured, a negative figure is return premium owed to the insured.

A completed audit is finalized by a `PremiumAuditor`, and finalization auto-branches on the size of the adjustment relative to the carrier's waiver threshold. If the absolute value of `net_adjustment_cents` is at or below the insurer's `audit_waiver_threshold_cents`, the audit is waived: it moves from `COMPLETED` to `WAIVED`, the policy is driven to `AUDIT_CLOSED`, and the policy's `audited_premium_cents` is set equal to its `estimated_premium_cents` (the estimate stands, no adjustment). If instead the absolute value of the adjustment strictly exceeds the waiver threshold, the audit is finalized: it moves from `COMPLETED` to `FINALIZED`, the policy is driven to `AUDIT_CLOSED`, the policy's `audited_premium_cents` is set to the audit's `computed_audited_premium_cents`, and the policy `version` is incremented. The finalize request must carry `expected_policy_version` matching the policy's current `version` per §2.8, failing with `ERR_STALE_POLICY_VERSION` when a late transaction has moved the policy on.

A completed audit need not finalize immediately. An `InsurerAdmin` may dispute it, moving it from `COMPLETED` to `DISPUTED`, and a `PremiumAuditor` may then reopen the disputed audit, moving it from `DISPUTED` back to `IN_PROGRESS`; reopening increments the audit's `revision_round` by one and clears `computed_audited_premium_cents` and `net_adjustment_cents` so they are recomputed on the next completion. This dispute-and-revise cycle may repeat. `FINALIZED` and `WAIVED` are the audit's terminal states.

### 3.9. Loss Run Snapshots

Any operational role — administrator, underwriter, adjuster, or auditor — may generate a **Loss Run**, an immutable point-in-time snapshot of a policy's claim experience taken at the insurer's current clock. Generation captures `as_of_date` from the insurer's `current_date` and includes exactly those claims of the policy whose `reported_date` is at or before that cutoff. Over the included claims the snapshot records `total_incurred_cents` as the sum of their `incurred_cents`, `general_incurred_cents` as the incurred sum over those in the `GENERAL` bucket, `products_incurred_cents` as the incurred sum over those in the `PRODUCTS` bucket, `claim_count` as the number of included claims, and `open_claim_count` as the number of included claims not in `CLOSED` or `DENIED`. A `DENIED` claim is still counted in `claim_count` but contributes zero incurred. Once written, a loss run is frozen — later changes to the underlying claims never mutate an existing snapshot.

The reading surface across all of these workflows is broad: single resources and their collections — insureds, certificate holders, policies, endorsements, certificates, claims, claim transactions, premium audits, exposure records, and loss runs — are retrievable, with list endpoints filterable by the relevant foreign keys and, where noted, by `status`, by `loss_type`, by `txn_type`, by `class_code`, or by `insured_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions that bind, activate, cancel, issue, revoke, close, deny, reopen, start, complete, dispute, reopen, finalize, and advance the clock — return a `200 OK` status code. (The single exception among "child-creating" actions: posting a claim transaction creates a new transaction resource and returns `201 Created`.)

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/insurers` | Create an insurer (carrier tenant) | InsurerAdmin |
| GET | `/insurers/{insurerId}` | Get an insurer | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, CertificateHolder |
| POST | `/insurers/{insurerId}/clock` | Advance the insurer business clock | InsurerAdmin |
| POST | `/insureds` | Create a Named Insured | InsurerAdmin, Underwriter |
| GET | `/insureds/{insuredId}` | Get a Named Insured | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| GET | `/insureds` | List Named Insureds | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| POST | `/certificate-holders` | Create a certificate holder | InsurerAdmin, Underwriter |
| GET | `/certificate-holders/{holderId}` | Get a certificate holder | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, CertificateHolder |
| GET | `/certificate-holders` | List certificate holders | InsurerAdmin, Underwriter, PremiumAuditor |
| POST | `/policies` | Create a draft policy | Underwriter |
| GET | `/policies/{policyId}` | Get a policy | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, CertificateHolder |
| GET | `/policies` | List policies | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| POST | `/policies/{policyId}/bind` | Bind a draft policy | Underwriter |
| POST | `/policies/{policyId}/activate` | Activate a bound policy into force | Underwriter |
| POST | `/policies/{policyId}/cancel` | Cancel a policy | Underwriter |
| POST | `/endorsements` | Add an additional-insured endorsement | Underwriter |
| GET | `/endorsements/{endorsementId}` | Get an endorsement | InsurerAdmin, Underwriter, CertificateHolder, ClaimsAdjuster, PremiumAuditor |
| GET | `/endorsements` | List endorsements | InsurerAdmin, Underwriter, CertificateHolder, ClaimsAdjuster, PremiumAuditor |
| POST | `/endorsements/{endorsementId}/void` | Void an endorsement | Underwriter |
| POST | `/certificates` | Create a draft certificate of insurance | Underwriter |
| GET | `/certificates/{certificateId}` | Get a certificate of insurance | InsurerAdmin, Underwriter, CertificateHolder, ClaimsAdjuster, PremiumAuditor |
| GET | `/certificates` | List certificates of insurance | InsurerAdmin, Underwriter, CertificateHolder, ClaimsAdjuster, PremiumAuditor |
| POST | `/certificates/{certificateId}/issue` | Issue (snapshot) a certificate | Underwriter |
| POST | `/certificates/{certificateId}/revoke` | Revoke an issued certificate | Underwriter |
| POST | `/claims` | Open a claim against a policy | ClaimsAdjuster |
| GET | `/claims/{claimId}` | Get a claim | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| GET | `/claims` | List claims | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| POST | `/claims/{claimId}/transactions` | Post a financial transaction on a claim | ClaimsAdjuster |
| GET | `/claim-transactions/{transactionId}` | Get a single claim transaction | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| GET | `/claim-transactions` | List claim transactions in posted order | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| POST | `/claims/{claimId}/close` | Close a claim | ClaimsAdjuster |
| POST | `/claims/{claimId}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/claims/{claimId}/reopen` | Reopen a closed claim | ClaimsAdjuster |
| POST | `/audits` | Schedule a premium audit on an expired policy | PremiumAuditor, InsurerAdmin |
| GET | `/audits/{auditId}` | Get a premium audit | InsurerAdmin, Underwriter, PremiumAuditor |
| GET | `/audits` | List audits | InsurerAdmin, Underwriter, PremiumAuditor |
| POST | `/audits/{auditId}/start` | Start the audit | PremiumAuditor |
| POST | `/audits/{auditId}/exposure-records` | Record an audited exposure line | PremiumAuditor |
| GET | `/exposure-records/{exposureRecordId}` | Get an exposure record | InsurerAdmin, Underwriter, PremiumAuditor |
| GET | `/exposure-records` | List exposure records | InsurerAdmin, Underwriter, PremiumAuditor |
| POST | `/audits/{auditId}/complete` | Complete the audit | PremiumAuditor |
| POST | `/audits/{auditId}/dispute` | Dispute a completed audit | InsurerAdmin |
| POST | `/audits/{auditId}/reopen` | Reopen a disputed audit for revision | PremiumAuditor |
| POST | `/audits/{auditId}/finalize` | Finalize a completed audit (auto-branches waived vs finalized) | PremiumAuditor |
| POST | `/policies/{policyId}/loss-runs` | Generate an immutable loss-run snapshot | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor |
| GET | `/loss-runs/{lossRunId}` | Get a loss-run snapshot | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, CertificateHolder |
| GET | `/loss-runs` | List loss-run snapshots | InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor, CertificateHolder |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FEIN` | 409 Conflict |
| `ERR_DUPLICATE_POLICY_NUMBER` | 409 Conflict |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RETRO_DATE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RETRO_DATE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_INVALID_POLICY_PERIOD` | 422 Unprocessable Entity |
| `ERR_AGGREGATE_LIMIT_INVALID` | 422 Unprocessable Entity |
| `ERR_POLICY_NOT_YET_EFFECTIVE` | 409 Conflict |
| `ERR_POLICY_NOT_IN_FORCE` | 409 Conflict |
| `ERR_OPEN_CLAIMS_BLOCK_CANCEL` | 409 Conflict |
| `ERR_OCCURRENCE_OUTSIDE_PERIOD` | 409 Conflict |
| `ERR_CLAIM_BEFORE_RETRO_DATE` | 409 Conflict |
| `ERR_RELEASE_EXCEEDS_RESERVE` | 422 Unprocessable Entity |
| `ERR_OPEN_RESERVE_REMAINS` | 409 Conflict |
| `ERR_PAID_CLAIM_CANNOT_DENY` | 409 Conflict |
| `ERR_AI_ENDORSEMENT_MISSING` | 409 Conflict |
| `ERR_AI_DATE_OUTSIDE_PERIOD` | 422 Unprocessable Entity |
| `ERR_POLICY_EXHAUSTED` | 409 Conflict |
| `ERR_POLICY_NOT_AUDITABLE` | 409 Conflict |
| `ERR_AUDIT_BASIS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_EXPOSURE_RECORDS` | 409 Conflict |
| `ERR_STALE_POLICY_VERSION` | 412 Precondition Failed |

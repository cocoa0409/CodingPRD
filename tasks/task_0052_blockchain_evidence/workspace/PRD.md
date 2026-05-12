# Blockchain Evidence Preservation API — Product Requirements Document

## 1. Introduction

The Blockchain Evidence Preservation API is the backbone service for a regulated digital-evidence platform whose purpose is to anchor file fingerprints onto public and consortium blockchains, issue tamper-resistant certificates that testify to those anchors, and — when a matter escalates — package the same evidence for delivery to a court, procuratorate, or arbitration tribunal. The system is built for customers whose pain point is the inability to prove, after the fact, that a digital artefact existed in a specific form at a specific moment; a Trusted Timestamp Authority returns the moment, the chosen blockchain returns the form, and the platform binds the two into a single auditable record. Across this lifecycle the service must remain both operationally robust (failures on one chain are retried; notarization arrives asynchronously; clock-driven sweeps revoke artefacts whose retention window has passed) and fiscally disciplined (every anchor and every judicial seal is priced, debited from a prepaid wallet, and reflected in the customer's invoice).

A second design driver is heterogeneity: evidence is preserved either one item at a time or aggregated through a Merkle tree into a single on-chain transaction, fees vary by evidence type and retention period (with a volume discount when many items share an anchor), and downstream judicial cooperation imposes its own pricing multiplier per receiving authority. Because the platform sits between paying customers, notary offices, judicial officers, and the chain adapters themselves, the API must define crisp ownership semantics, deterministic ordering for fee debits, and a small set of test-driving endpoints that simulate the asynchronous behaviour of the outside world. The remainder of this document defines those semantics in detail.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must include two mandatory authentication headers: `X-User-ID`, which carries the caller's user identifier, and `X-User-Role`, which carries the caller's operational capacity. Missing or empty headers are rejected with `ERR_AUTH_REQUIRED`. Once authenticated, the caller must hold the role permitted by the target endpoint's role list (see §4); a mismatch is rejected with `ERR_PERMISSION_DENIED`.

The system recognises four roles, spelled exactly as follows:

- `Customer` — the end user that submits evidence, pays for preservation, and reads its own certificates. The `Customer` role is entity-backed by the `Customer` aggregate. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (`Evidence`, `Batch`, `Recharge`, `Invoice`, and read access on owned `Certificate`, `JudicialPackage`, and `TimestampNotarization` rows) compare the resource's `customer_id` (or, for indirect references, the `customer_id` of the linked `Evidence`) to `X-User-ID`. A `Customer` that calls a `Customer`-restricted endpoint with a body whose owner does not match `X-User-ID` is rejected with `ERR_PERMISSION_DENIED`.
- `NotaryOfficer` — notary-office staff attaching notarized timestamps on behalf of customers. When `X-User-Role` is `NotaryOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on `AuditLog.actor_id` but never compares it to any entity's `id`.
- `JudicialOfficer` — judicial-authority operators who prepare, seal, and deliver judicial packages. When `X-User-Role` is `JudicialOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditLog.actor_id` but performs no ownership comparison.
- `PlatformAdmin` — platform operators who bootstrap customers, simulate chain callbacks, run sweeps, and read audit logs. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditLog.actor_id` but performs no ownership comparison.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 with no upper bound beyond the available row count. List endpoints return rows sorted by their `created_at` timestamp in ascending order unless explicitly stated otherwise.

The pagination block surfaces in `meta` as four fields — `limit`, `offset`, `total_count`, and `has_more` — on every list response regardless of whether the caller supplied the parameters.

### 2.4. Common Resource Properties and Versioning

Most primary resources — `Customer`, `Evidence`, `OnChainTx`, `Batch`, `Certificate`, `JudicialPackage`, and `Invoice` — share a system-managed set of fields:

- `id` (string): a server-minted UUID. The identifier carries no type prefix; the resource's URL path is the sole indication of its kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at insertion.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation that changes any persisted field on the resource.
- `version` (integer): a system-managed counter that begins at 1 and increments by exactly 1 on every mutation. Updates to computed columns that the system itself populates as side-effects (for example, debiting `wallet_balance_cents` on a `Customer`, setting `confirmed_at` on an `Evidence`, or pinning `total_fee_cents` on a `Batch`) are themselves mutations that bump `updated_at` and `version`.

Four entities are append-only ledger rows or single-payload records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: `FeeAccount`, `TimestampNotarization`, `VerificationReport`, `Recharge`, and `AuditLog`. For these rows, callers must not expect a `version` field to be returned and must not send one on any mutation request.

### 2.5. Optimistic Concurrency Control

Any mutation endpoint that targets an existing resource by its identifier accepts an optional `version` field in its request body. When the caller supplies a `version`, the server compares it to the resource's currently stored `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When the caller omits the field, the server applies the mutation without an OCC check. OCC applies to resources that carry a `version` (see §2.4); rows that intentionally lack the field cannot be guarded by it.

### 2.6. Nested Resource Retrieval

When a path contains multiple identifiers — for instance, the Merkle proof lookup path that nests an `evidence_id` underneath a batch identifier — the server validates path resources from left to right. The first missing identifier yields `ERR_NOT_FOUND` with no further checks performed. If every path identifier resolves, the server then performs role-based authorisation (§2.1) and finally body-level validation in priority order (§2.10).

### 2.7. Monetary Values, Hash Encoding, and Precision

Every monetary amount in the system — `wallet_balance_cents`, `amount_cents`, `per_evidence_fee_cents`, `total_fee_cents`, `surcharge_cents`, `total_cents`, `lifetime_recharge_cents`, and `lifetime_deduction_cents` — is an integer number of cents. There are no fractional cents in storage or in API responses. All fee computations are performed in integer cents using the half-up rounding rule at every prescribed rounding step; no other rounding mode is permitted. `wallet_balance_cents` is a non-negative integer; any operation that would drive it below zero must fail before any mutation is committed.

File fingerprints are hex-encoded digests. Both `SHA256` and `SM3` produce 64-character lowercase hex strings, and `file_hash` must match that exact length and alphabet for the declared `hash_algorithm`; a mismatch is rejected with `ERR_HASH_FORMAT_INVALID`. On-chain fields that copy the same hash (`anchored_hash`, `merkle_root`, `hash_snapshot`, `recomputed_hash`, `on_chain_hash`) follow the same hex convention but are populated by the system rather than the caller.

### 2.8. Blockchain Anchoring and Confirmation Thresholds

The platform supports four target chains, identified by the `chain_id` enumeration whose only legal values are `ETHEREUM`, `FABRIC`, `BSN`, and `COSMOS`. Each chain has a fixed confirmation threshold that governs when an `OnChainTx` is treated as `CONFIRMED`: `ETHEREUM` requires 12 confirmations, `FABRIC` requires 1, `BSN` requires 5, and `COSMOS` requires 6. The system never overrides these thresholds — a `confirmations` value reported below the threshold for the relevant `chain_id` must keep the transaction in `SUBMITTED` and the upstream `Evidence` or `Batch` in `SUBMITTING`. When the threshold is reached or exceeded, the `OnChainTx` flips to `CONFIRMED` and cascades to the upstream entity per the state-machine rules in §3.

### 2.9. Hierarchical Consistency and Cascades

Every mutation in this system runs through a single side-effect pipeline. A primary state transition (for example, an `Evidence` going from `SUBMITTING` to `CONFIRMED`) refreshes the primary's `updated_at` and bumps its `version`, then applies all declared side-effects: secondary entities mutated as part of the cascade (the `Customer.wallet_balance_cents` debit, the `FeeAccount.lifetime_deduction_cents` increment, every member `Evidence` whose status flips during a batch confirmation) each receive their own `updated_at` refresh and `version` bump. Audit-log entries are appended for the cascaded events as well as the primary one. Cascade ordering for the chain confirmation pipeline is: `OnChainTx` flips first, then the linked `Evidence` or `Batch` confirms (which in the batch case also flips every member `Evidence`), then the fee debit and ledger increment, then audit entries.

### 2.10. Validation Priority Order

Multiple validation rules can guard the same endpoint. When more than one rule could fire on a single request, the server evaluates them in this strict order and returns the first failure:

1. Header presence (`ERR_AUTH_REQUIRED`).
2. Role authorisation against the endpoint's role list (`ERR_PERMISSION_DENIED`).
3. When the caller's `X-User-Role` is `Customer`, ownership of the targeted resource: for `POST /evidences/{id}/submit`, `POST /evidences/{id}/resubmit`, `POST /batches`, `POST /batches/{id}/submit`, `POST /recharges`, and `POST /invoices` (when the body's scope owner is keyed by `customer_id`), `X-User-ID` must equal the resource's or body's `customer_id`. Mismatches return `ERR_PERMISSION_DENIED`.
4. Path resource existence, validated left-to-right (`ERR_NOT_FOUND`).
5. `Customer.id` referenced inside the request body exists, on `POST /evidences`, `POST /batches`, `POST /recharges`, and `POST /invoices` (`ERR_CUSTOMER_NOT_FOUND`).
6. Target entity is in a state that admits the requested transition (`ERR_INVALID_STATE`).
7. Linked `Evidence.status` is `CONFIRMED` on `POST /certificates` and on `POST /judicial-packages/{id}/seal` (`ERR_EVIDENCE_NOT_CONFIRMED`).
8. `file_hash` format matches `hash_algorithm` on `POST /evidences` (`ERR_HASH_FORMAT_INVALID`).
9. Every member evidence in a batch belongs to the same customer and is in `PENDING` with a null `batch_id` at batch creation (`ERR_BATCH_MEMBER_INVALID`).
10. `Batch.evidence_count` is at least 2 and at most 1000, inclusive of both endpoints, on `POST /batches` (`ERR_BATCH_SIZE_OUT_OF_RANGE`).
11. `storage_period_days` is exactly one of 30, 90, 365, or 1095 on `POST /evidences` (`ERR_PERIOD_INVALID`).
12. `Evidence.submission_attempts` is strictly less than 3 on `POST /evidences/{id}/resubmit` (`ERR_RESUBMIT_LIMIT_EXCEEDED`).
13. The target `Evidence` of a chain confirmation already has a `TimestampNotarization` attached; missing notarization rejects the confirmation cascade with `ERR_TIMESTAMP_REQUIRED`.
14. `JudicialPackage.case_number` is non-empty and the linked `Certificate` exists with `status` equal to `ISSUED` at seal time (`ERR_CERTIFICATE_REQUIRED`).
15. Certificate download and judicial-package creation are rejected once `Evidence.expires_at` has passed (`ERR_EVIDENCE_EXPIRED`). Verification itself is still permitted after expiry and returns a `VerificationReport` whose `outcome` is `EXPIRED`.
16. On `POST /invoices` with `scope` of `BILLING_PERIOD`, `period_start` is at or before `period_end` and `period_end` is at or before the server's current time (`ERR_PERIOD_INVALID`).
17. `Customer.wallet_balance_cents` is at least the forward-looking preservation fee quote on submit and resubmit (`ERR_INSUFFICIENT_BALANCE`).
18. `Customer.wallet_balance_cents` is at least the forward-looking batch fee quote (subtotal already including the volume discount) on batch submit (`ERR_INSUFFICIENT_BALANCE`).
19. `Customer.wallet_balance_cents` is at least the forward-looking judicial surcharge quote on judicial seal (`ERR_INSUFFICIENT_BALANCE`).
20. The pair `(customer_id, idempotency_key)` is unique across `Evidence` rows when `idempotency_key` is present on `POST /evidences` (`ERR_DUPLICATE_IDEMPOTENCY_KEY`).
21. `external_payment_ref` is globally unique across `Recharge` rows on `POST /recharges` and the same uniqueness is re-enforced on `POST /_events/payment` (`ERR_DUPLICATE_PAYMENT_REF`).
22. On any mutation endpoint, a `version` value supplied in the body matches the stored `version` (`ERR_VERSION_CONFLICT`).

A generic body-shape failure that none of the rules above match — a missing required field, a wrong JSON type, a malformed UUID — is rejected with `ERR_VALIDATION_FAILED` at HTTP 422.

### 2.11. Concurrency and Serialization

The platform serialises critical operations through first-writer-wins guards on the row being mutated. Two simultaneous `POST /evidences/{id}/submit` calls on the same `PENDING` `Evidence` serialise on the `Evidence.status` transition; exactly one creates an `OnChainTx` and bumps `submission_attempts`, and the loser receives `ERR_INVALID_STATE` (HTTP 409). The same guarantee applies to two simultaneous `POST /evidences/{id}/resubmit` calls on the same `FAILED` `Evidence`: the winner advances `FAILED → SUBMITTING` and creates the next `OnChainTx` attempt; the loser receives `ERR_INVALID_STATE`. Two simultaneous seals of the same `DRAFT` `JudicialPackage` likewise serialise on `JudicialPackage.status`; the loser receives `ERR_INVALID_STATE`.

Two payment events arriving with the same `external_payment_ref` are deduplicated by the unique constraint on `Recharge.external_payment_ref`: the wallet is credited at most once, and the second event is rejected with `ERR_DUPLICATE_PAYMENT_REF`. Two `POST /evidences` requests with the same `(customer_id, idempotency_key)` are deduplicated similarly: only the first creates a row, the second receives `ERR_DUPLICATE_IDEMPOTENCY_KEY`. When a wallet debit races a refund-style void on an `Invoice` and the would-be result drops below zero, the operation that drives the balance negative fails with `ERR_INSUFFICIENT_BALANCE` (HTTP 402); the system holds a row lock on `Customer.wallet_balance_cents` for the duration of the critical section so reads inside the section observe the locked value.

### 2.12. Audit Trail

Every state-changing operation in this system appends a row to the audit log. Each `AuditLog` row records the `actor_role` (one of `Customer`, `JudicialOfficer`, `NotaryOfficer`, `PlatformAdmin`, or `system` for cascades the platform performs autonomously), the `actor_id` (the value of `X-User-ID` at request time, or null for `system` events), the `event_type` (one of `EVIDENCE_SUBMITTED`, `EVIDENCE_CONFIRMED`, `EVIDENCE_FAILED`, `EVIDENCE_RESUBMITTED`, `BATCH_CONFIRMED`, `CERTIFICATE_ISSUED`, `JUDICIAL_SEALED`, `JUDICIAL_DELIVERED`, `FEE_DEBITED`, `RECHARGE_COMPLETED`, or `INVOICE_ISSUED`), the `target_entity` (one of `Evidence`, `Batch`, `OnChainTx`, `Certificate`, `JudicialPackage`, `FeeAccount`, `Recharge`, or `Invoice`), the `target_id` of the affected entity, and a `detail` JSON object that captures the before/after snapshot of the key field deltas. The audit log is append-only; entries are never updated or deleted.

## 3. Business Logic & Workflows

### 3.1. Customer onboarding, wallet, and recharge

The platform's life begins when a `PlatformAdmin` bootstraps a `Customer` record carrying an `email` (RFC 5322 syntax, unique across active customers) and a `display_name` that will later be printed on issued certificates. A successful bootstrap pairs the newly-minted customer with a `FeeAccount` ledger whose `lifetime_recharge_cents` and `lifetime_deduction_cents` both start at zero; both columns are append-style running totals that the system maintains automatically. The customer's `wallet_balance_cents` likewise starts at zero, the `status` column starts at `ACTIVE`, and a `SUSPENDED` customer is not permitted to submit new evidence.

To put credit on a wallet, the `Customer` opens a recharge by providing the target `customer_id`, the `amount_cents` (at least 100 cents and at most 10 000 000 cents), and the `external_payment_ref` that the upstream payment system will use as its idempotency anchor. The recharge is created in `PENDING`. Later, the `PlatformAdmin` delivers a payment event simulating the bank callback; when the event payload status is success and its `external_payment_ref` matches a `PENDING` `Recharge`, the recharge advances to `COMPLETED`, the customer's `wallet_balance_cents` is credited by `amount_cents`, the `FeeAccount.lifetime_recharge_cents` is incremented by the same amount, and an audit row of `event_type` `RECHARGE_COMPLETED` is appended. A payment event whose payload status is failure transitions the same recharge to `FAILED` without crediting anything.

### 3.2. Capturing an evidence record

Evidence preservation begins with `Customer` registration of the fingerprint. The customer chooses the `evidence_type` (one of `DOCUMENT`, `IMAGE`, `VIDEO`, `CODE_REPOSITORY`, or `DATASET`), the `storage_period_days` (one of 30, 90, 365, or 1095), the `hash_algorithm` (`SHA256` or `SM3`), and submits the precomputed `file_hash` as a 64-character hex string. The target blockchain is selected through `chain_id`. The customer may optionally include the raw bytes through `original_data_b64`; when this field is null only the hash is retained. An optional `idempotency_key` makes the submission safe to retry on the wire — the pair `(customer_id, idempotency_key)` is unique per customer when the key is present, and a duplicate submission is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY`. The newly created `Evidence` starts in `PENDING`, with `submission_attempts` at zero and `per_evidence_fee_cents`, `batch_id`, `confirmed_at`, and `expires_at` all null.

A submitted but unanchored `Evidence` is not yet on the chain. Before anchoring, however, a `TimestampNotarization` must be attached: the customer (or, on the customer's behalf, a `NotaryOfficer`) creates the notarization by naming the `evidence_id`, choosing a `tsa_provider` from `RFC3161_TSA_A`, `RFC3161_TSA_B`, or `NOTARY_OFFICE`, and supplying a `notary_office_id` when, and only when, the provider is the notary office. The platform completes the notarization asynchronously via the notary callback, which populates `trusted_time` (the authoritative ISO 8601 instant returned by the TSA) and `tsa_token` (the opaque proof of issuance). Exactly one `TimestampNotarization` exists per `Evidence`; the uniqueness constraint sits on `evidence_id`. The verify capability — calling the notarization-verify operation as `Customer`, `JudicialOfficer`, or `PlatformAdmin` — is a read-side, idempotent check that recomputes the TSA token against the evidence's hash without changing any state.

### 3.3. The single-evidence anchoring lifecycle

Once notarization is attached, a `Customer` initiates anchoring, transitioning the evidence from `PENDING` to `SUBMITTING`. Three preconditions guard the transition: the `Customer.status` is `ACTIVE`, the evidence carries a null `batch_id` (single-evidence path; batch-bound evidences must use the batch flow in §3.5), and `Customer.wallet_balance_cents` is at least the forward-looking preservation fee quote computed for this evidence. A successful transition creates a fresh `OnChainTx` with `evidence_id` set to this evidence, `batch_id` left null, `anchored_hash` copied from the evidence's `file_hash`, `status` initialised to `SUBMITTED`, and `attempt_index` set to `Evidence.submission_attempts` plus one. The evidence's `submission_attempts` increments by one and an audit row of type `EVIDENCE_SUBMITTED` is appended.

The forward-looking preservation fee quote, used both to enforce the balance precondition above and to estimate the customer's exposure, is computed as follows. The base price is selected from the per-type table: `DOCUMENT` is 200 cents, `IMAGE` is 300 cents, `VIDEO` is 800 cents, `CODE_REPOSITORY` is 500 cents, and `DATASET` is 1000 cents. The base is then multiplied by the period multiplier: 30 days uses 1.00, 90 days uses 2.50, 365 days uses 8.00, and 1095 days uses 20.00. A flat 50-cent surcharge is added when `original_data_b64` is not null; the surcharge is zero when the field is null. The result is rounded half-up to a whole number of cents in a single final step. The quote is optimistic in the sense that no batch discount applies (the single-evidence path never receives one) and no judicial surcharge is folded in.

The anchored transaction lives in the `SUBMITTED` state until the chain reports back. A `PlatformAdmin` simulates that report through the chain-confirm operation, which carries the `tx_id` of the latest `OnChainTx`, a `block_height`, and a count of `confirmations` observed. When the reported `confirmations` reaches or exceeds the chain's threshold (12 for `ETHEREUM`, 1 for `FABRIC`, 5 for `BSN`, 6 for `COSMOS`), the `OnChainTx` flips to `CONFIRMED` with `block_height` and `confirmations` recorded. The platform then cascades into the upstream evidence: provided the `Evidence` still has its `TimestampNotarization` attached (a missing notarization at this point rejects the cascade with `ERR_TIMESTAMP_REQUIRED`), the evidence advances from `SUBMITTING` to `CONFIRMED`. The cascade sets `Evidence.confirmed_at` to the server's current time, sets `Evidence.expires_at` to `confirmed_at` plus the product of `storage_period_days` and 86 400 seconds, computes the chronological per-evidence fee (the same formula as the forward-looking quote, since there is no per-evidence discount logic), assigns the result to `Evidence.per_evidence_fee_cents`, debits `Customer.wallet_balance_cents` by that amount, increments `FeeAccount.lifetime_deduction_cents` by the same amount, and appends two audit rows: one with `event_type` `EVIDENCE_CONFIRMED` and one with `event_type` `FEE_DEBITED`.

A simulated chain failure delivered through the chain-fail capability, which carries a `tx_id` and a free-text `reason`, flips the same `OnChainTx` to `FAILED` with no `block_height` or `confirmations` change beyond what was already there, and cascades the upstream evidence from `SUBMITTING` to `FAILED`. No fee is debited on failure. An audit row of type `EVIDENCE_FAILED` is appended; balance and ledger columns are not touched.

A `FAILED` evidence is recoverable via resubmission. The `Customer` invokes the resubmit operation, which transitions the evidence from `FAILED` back to `SUBMITTING`. Two preconditions hold: `Evidence.submission_attempts` is strictly less than 3 (the system permits at most three submissions in total for a single evidence; a fourth attempt is rejected with `ERR_RESUBMIT_LIMIT_EXCEEDED`), and `Customer.wallet_balance_cents` is still at least the forward-looking preservation fee quote. The resubmission creates a new `OnChainTx` with `attempt_index` equal to `Evidence.submission_attempts` plus one and otherwise mirroring the original anchor structure, increments `submission_attempts`, and appends an audit row of type `EVIDENCE_RESUBMITTED`.

### 3.4. Expiry, sweeps, and revocation cascades

Once an evidence reaches `CONFIRMED`, its retention window starts ticking. The `expires_at` column captures the moment after which the evidence is considered expired. A `PlatformAdmin` runs the expiry sweep capability, which advances every `CONFIRMED` evidence whose `expires_at` is at or before the server's current time into the terminal `EXPIRED` state. Two cascades fire from this transition. The evidence's linked `Certificate`, if any, flips to `REVOKED`; downstream readers must treat a `REVOKED` certificate as no longer valid. Any `JudicialPackage` whose `evidence_id` matches and whose `status` is still `DRAFT` flips to `REJECTED` — no fee refund is issued because no fee has been debited for a `DRAFT` package yet. A `JudicialPackage` whose `status` is already `SEALED` or `DELIVERED` at the moment of expiry is *not* automatically cascaded: the judicial channel decides whether to revoke. The clock-advance capability allows a `PlatformAdmin` to advance the server's logical clock to a supplied `to_iso8601` instant; expiry-related logic uses this clock when it is set.

### 3.5. Batched anchoring through Merkle aggregation

A `Customer` who has many `PENDING` evidences may bundle them into a `Batch` for a single on-chain anchor. The customer opens a batch by sending the `customer_id`, the target `chain_id`, and the ordered list of member evidence identifiers as `evidence_ids`. At creation time, every member evidence must belong to the same `Customer`, must be in `PENDING`, and must currently carry a null `batch_id`; any member that fails these checks rejects the batch with `ERR_BATCH_MEMBER_INVALID`. The system pins `Batch.evidence_count` from the supplied list — the count is bounded by at least 2 and at most 1000 inclusive, and a count outside that range rejects the batch with `ERR_BATCH_SIZE_OUT_OF_RANGE`. The system then computes the `Batch.merkle_root` over the member `file_hash` values in their submission order, sets each member's `batch_id` to this batch's `id`, and leaves the batch in `PENDING` with `total_fee_cents` and `submission_attempts` initialised to null and zero respectively.

Submitting the batch transitions it from `PENDING` to `SUBMITTING`. The transition's preconditions are that `Batch.evidence_count` is at least 2, every member `Evidence` is still `PENDING` with `batch_id` pointing to this batch, and `Customer.wallet_balance_cents` is at least the forward-looking batch fee quote. The batch fee quote is the same as the final fee calculation (see below) and already includes the volume discount — that is, the quote is *not* the un-discounted subtotal. On a successful transition, the system recomputes `Batch.merkle_root` over the member `file_hash` values in submission order (in case the members have not yet been materially mutated, this matches the value pinned at creation), creates a single `OnChainTx` whose `batch_id` is this batch, whose `evidence_id` is null, whose `anchored_hash` is the Merkle root, whose `attempt_index` is `Batch.submission_attempts` plus one, and whose `status` starts at `SUBMITTED`. Every member `Evidence.status` flips from `PENDING` to `SUBMITTING` as part of the cascade. `Batch.submission_attempts` increments by one.

The batch fee is computed by a two-step rounding protocol: round-per-line first, then sum, then apply the discount, then round once more. Concretely, the system walks the member evidences in submission order and computes each member's per-line cents by selecting `BASE_FEE_BY_TYPE` from `evidence_type` (`DOCUMENT` 200, `IMAGE` 300, `VIDEO` 800, `CODE_REPOSITORY` 500, `DATASET` 1000), multiplying by the period multiplier matching `storage_period_days` (30 → 1.00, 90 → 2.50, 365 → 8.00, 1095 → 20.00), adding 50 cents when that member's `original_data_b64` is not null and zero otherwise, then rounding half-up to a whole number of cents. The subtotal is the sum of these per-line cents. The discount rate is the highest tier that the batch's `evidence_count` meets or exceeds: 20% when at least 100, 15% when at least 50, 10% when at least 10, 5% when at least 2, and 0% otherwise; the floor for the lowest tier is at least 2 because a single-member batch is rejected upstream by the size validation. The batch total is the subtotal multiplied by one minus the discount rate, then rounded half-up to a whole number of cents in one final step. A sum-then-round variant — adding the unrounded per-line amounts and rounding only at the very end — is explicitly *not* used and will produce a different number for many member compositions; do not implement it.

The batch's `OnChainTx` follows the same chain-confirm / chain-fail flow as a single-evidence anchor, gated by the same threshold per `chain_id`. On confirmation, the batch advances from `SUBMITTING` to `CONFIRMED` provided every member `Evidence` has a `TimestampNotarization` attached. The cascade flips every member evidence to `CONFIRMED`, sets each member's `confirmed_at` to the server's current time and each member's `expires_at` to `confirmed_at` plus the product of that member's own `storage_period_days` and 86 400 seconds, pins `Batch.total_fee_cents` to the value the batch fee formula returns, debits the customer's `wallet_balance_cents` exactly once by that total, increments `FeeAccount.lifetime_deduction_cents` by the same amount, and appends audit rows of `event_type` `BATCH_CONFIRMED` and `FEE_DEBITED`. A failure cascade through chain-fail flips the batch from `SUBMITTING` to `FAILED`, flips every member `Evidence` to `FAILED`, debits nothing, and refunds nothing. A test caller can request the Merkle inclusion path for any member evidence — read-only output that proves a single member belongs to the aggregated root.

### 3.6. Certificate issuance and download

Once an evidence reaches `CONFIRMED`, a `Customer` (or, for administrative replays, a `PlatformAdmin`) issues a `Certificate` against it. The issuance payload carries the `evidence_id` and a `template_code` selecting the visual style — exactly one of `STANDARD`, `PREMIUM`, or `JUDICIAL`. The new certificate is created in `ISSUED`, with the system populating `verification_code` (a 12-character uppercase alphanumeric handle, globally unique, suitable for a public verification UI), `embedded_timestamp` copied from the linked `TimestampNotarization.trusted_time`, `tx_hash_ref` copied from the confirmed `OnChainTx.tx_hash`, `chain_id` copied from the evidence, `hash_snapshot` copied from `Evidence.file_hash` at issuance time, and an audit row of type `CERTIFICATE_ISSUED`. Issuance against a non-`CONFIRMED` evidence is rejected with `ERR_EVIDENCE_NOT_CONFIRMED`.

The certificate may be downloaded as a `format` of `pdf`, `png`, or `json`. The download capability is read-only for `Customer`, `JudicialOfficer`, and `PlatformAdmin`, but it is blocked once `Evidence.expires_at` has passed: an expired download attempt rejects with `ERR_EVIDENCE_EXPIRED` at HTTP 410. The `Certificate.status` is `ISSUED` until revocation. Two distinct paths revoke a certificate: an admin-only revocation capability flips the status from `ISSUED` to `REVOKED` directly; and the expiry sweep cascade described in §3.4 also flips a still-`ISSUED` certificate to `REVOKED`. A `Certificate` whose linked evidence is referenced by a `SEALED` but not-yet-`DELIVERED` `JudicialPackage` is intentionally *not* auto-cascaded by sweeps — the judicial channel is responsible for that decision.

### 3.7. Judicial issuance: preparation, sealing, and delivery

A `JudicialOfficer` prepares evidence for delivery to a court, procuratorate, or arbitration tribunal by opening a `JudicialPackage` in `DRAFT`. The preparation payload carries the `evidence_id`, a court-assigned `case_number` (non-empty, at most 64 characters), a structured `party_info` JSON object with plaintiff and defendant records, an `authority_code` from `COURT_BJ`, `COURT_SH`, `COURT_GZ`, `COURT_SZ`, `PROCURATORATE`, or `ARBITRATION`, and a boolean `include_original_data` (default false) selecting whether the evidence's `original_data_b64` payload is bundled into the issued package. The `JudicialPackage` is created in `DRAFT` with `official_seal_id`, `delivered_at`, and `surcharge_cents` all null. Preparing a package against an evidence whose `expires_at` has passed is rejected with `ERR_EVIDENCE_EXPIRED`.

Sealing the package — the `DRAFT` to `SEALED` transition — is the only judicial step that costs money. The transition's preconditions are that the linked `Evidence.status` is `CONFIRMED`, the linked `Certificate.status` is `ISSUED` (a missing or `REVOKED` certificate rejects the seal with `ERR_CERTIFICATE_REQUIRED`), the linked `TimestampNotarization` exists, and `Customer.wallet_balance_cents` is at least the forward-looking judicial surcharge quote. The judicial surcharge — both the quote and the actual debit, which match because no per-package discount applies — is computed as follows: start with a base surcharge of 5000 cents, add 1500 cents when `include_original_data` is true and zero when it is false, then multiply the sum by the authority multiplier (`COURT_BJ` and `COURT_SH` are 1.20, `COURT_GZ` and `COURT_SZ` are 1.10, `PROCURATORATE` is 1.00, and `ARBITRATION` is 0.90), and round the result half-up to a whole number of cents in one final step. A successful seal mints a fresh `official_seal_id`, assigns the surcharge to `JudicialPackage.surcharge_cents`, debits the customer's `wallet_balance_cents` by that amount, increments `FeeAccount.lifetime_deduction_cents` by the same amount, and appends audit rows of `event_type` `JUDICIAL_SEALED` and `FEE_DEBITED`.

Delivery is the `SEALED` to `DELIVERED` transition. A `JudicialOfficer` records the delivery directly, or the platform delivers the same transition via the judicial acknowledgement event that names the affected `judicial_package_id`. The transition sets `JudicialPackage.delivered_at` to the server's current time and appends an audit row of type `JUDICIAL_DELIVERED`. A package whose linked evidence expires while the package is still in `DRAFT` is cascaded to `REJECTED` per §3.4; a package already in `SEALED` or `DELIVERED` is not.

### 3.8. Forensic verification and report generation

Any `Customer`, `JudicialOfficer`, or `PlatformAdmin` may run a forensic verification by submitting the `evidence_id` together with a fresh `file_hash` derived from re-hashing the file under suspicion. The platform recomputes against the supplied bytes (the `recomputed_hash`), compares against the chain-of-record hash (the `on_chain_hash` read back from the `OnChainTx.anchored_hash` for a single anchor, or from the Merkle proof path for a batch anchor), confirms whether the linked `Certificate` is currently `ISSUED` and the chain proof verifies (`certificate_valid`), flags tamper detection (`tamper_detected` is true when `recomputed_hash` is not equal to `on_chain_hash` or when the chain proof fails to verify), and writes a `VerificationReport` whose `outcome` summarises the result.

The `outcome` is exactly one of five enumerated values: `VERIFIED` when the hashes match, the certificate is `ISSUED`, and the chain proof verifies; `TAMPERED` when the recomputed and on-chain hashes diverge or the chain proof fails; `EXPIRED` when the evidence's `expires_at` has passed (verification is *still* permitted after expiry — only certificate downloads and judicial preparation are blocked — so verification of an expired evidence runs to completion and returns this outcome); `REVOKED` when the linked certificate is `REVOKED` but the underlying hashes still match; and `UNAVAILABLE` when on-chain data cannot be read back. The verification report is append-only and is identified by its own `id` together with the `evidence_id` it bears.

### 3.9. Invoicing and billing windows

A `Customer` (or, on the customer's behalf, a `PlatformAdmin`) issues an `Invoice` by selecting a billing window via `scope`. The three legal values are `SINGLE_EVIDENCE`, `SINGLE_BATCH`, and `BILLING_PERIOD`. When `scope` is `SINGLE_EVIDENCE`, the body carries `scope_ref_id` set to the `id` of a `CONFIRMED` `Evidence`; `Invoice.total_cents` is pinned to that evidence's `per_evidence_fee_cents`. When `scope` is `SINGLE_BATCH`, the body carries `scope_ref_id` set to the `id` of a `CONFIRMED` `Batch`; `Invoice.total_cents` is pinned to that batch's `total_fee_cents`. When `scope` is `BILLING_PERIOD`, the body omits `scope_ref_id`, supplies inclusive `period_start` and `period_end` timestamps, and the invoice's `total_cents` is the sum of every fee debited for this `customer_id` whose timestamp falls inside the closed interval `[period_start, period_end]`: each `CONFIRMED` `Evidence` contributes its `per_evidence_fee_cents` at its `confirmed_at`; each `CONFIRMED` `Batch` contributes its `total_fee_cents` at its `confirmed_at`; and each `SEALED` `JudicialPackage` contributes its `surcharge_cents` at the moment of sealing (taken as the `updated_at` of that package while its status equals `SEALED`). Events landing exactly at `period_start` and exactly at `period_end` are both included — the interval is closed on both ends. Period validation requires `period_start` at or before `period_end` and `period_end` at or before the server's current clock; a violation rejects with `ERR_PERIOD_INVALID`. An invoice whose scope is `SINGLE_EVIDENCE` against a non-`CONFIRMED` evidence — whose `per_evidence_fee_cents` would be null — is rejected with `ERR_INVOICE_SCOPE_INVALID`.

All `Invoice` rows are created in the `ISSUED` state and may be `VOIDED` administratively. Issuance also appends an audit row of `event_type` `INVOICE_ISSUED`. No further rounding is applied to `total_cents` because every input is already an integer number of cents.

### 3.10. Platform operations and asynchronous event delivery

The platform's outside world arrives through a small set of test-driving capabilities reserved for `PlatformAdmin`. The clock-advance capability writes the server's logical clock to a supplied `to_iso8601` instant; both `Invoice` period validation and the expiry sweep consult this clock. The chain-confirm capability simulates a chain callback, naming the affected `tx_id` and reporting the observed `block_height` and `confirmations`, then cascading the upstream evidence or batch per §3.3 and §3.5. The chain-fail capability simulates a chain rejection, naming the affected `tx_id` and a free-text `reason`, then cascading the upstream evidence or batch into `FAILED`. The expiry sweep capability flips every `CONFIRMED` evidence whose `expires_at` has passed into `EXPIRED` and cascades certificate revocation and draft-judicial rejection per §3.4. The payment event capability completes a `Recharge` when its body carries the matching `external_payment_ref` and a status of success, or fails it on a status of failure. The judicial acknowledgement capability drives a named `JudicialPackage` from `SEALED` to `DELIVERED`. The notary callback capability completes a named `TimestampNotarization` by supplying the values for `trusted_time` and `tsa_token`; the callback identifies the notarization to update via `timestamp_notarization_id`.

A `PlatformAdmin` may also list audit events with optional filters for `event_type`, `target_entity`, and `target_id`, paginated through `limit` and `offset`. The platform's listing endpoints — for example the evidence listing operation — accept similar optional filters; the evidence list specifically accepts `status` and `customer_id` query parameters in addition to pagination.

## 4. Endpoint Definitions

Operations that create a new top-level resource return `201 Created`. Operations that mutate an existing resource — state transitions, simulated chain callbacks, payment events, sweeps, clock-advance — return `200 OK`. List and read operations also return `200 OK`. The summary table below lists every endpoint exposed by the API; the request body, the response body, and the side-effects of each operation are described narratively in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Bootstrap a customer and pair a fee account ledger. | PlatformAdmin |
| GET | `/customers/{id}` | Read a customer including wallet balance. | Customer, PlatformAdmin |
| POST | `/recharges` | Open a PENDING recharge against the external payment system. | Customer |
| GET | `/recharges/{id}` | Read a recharge. | Customer, PlatformAdmin |
| POST | `/evidences` | Create an evidence record in PENDING. | Customer |
| GET | `/evidences/{id}` | Read an evidence. | Customer, JudicialOfficer, PlatformAdmin |
| GET | `/evidences` | List evidences filtered by status and customer. | Customer, PlatformAdmin |
| POST | `/evidences/{id}/submit` | Anchor an evidence: PENDING to SUBMITTING. | Customer |
| POST | `/evidences/{id}/resubmit` | Retry a failed evidence: FAILED to SUBMITTING. | Customer |
| POST | `/timestamp-notarizations` | Attach a TSA or notary timestamp to an evidence. | Customer, NotaryOfficer |
| GET | `/timestamp-notarizations/{id}` | Read a notarization including its TSA token. | Customer, NotaryOfficer, JudicialOfficer, PlatformAdmin |
| POST | `/timestamp-notarizations/{id}/verify` | Verify the TSA token against the evidence hash. | Customer, JudicialOfficer, PlatformAdmin |
| POST | `/batches` | Create a batch over PENDING evidences. | Customer |
| GET | `/batches/{id}` | Read a batch. | Customer, PlatformAdmin |
| POST | `/batches/{id}/submit` | Anchor a batch: PENDING to SUBMITTING. | Customer |
| GET | `/batches/{id}/proof/{evidence_id}` | Read the Merkle inclusion path for a member evidence. | Customer, JudicialOfficer, PlatformAdmin |
| POST | `/certificates` | Issue a certificate for a CONFIRMED evidence. | Customer, PlatformAdmin |
| GET | `/certificates/{id}` | Read certificate metadata. | Customer, JudicialOfficer, PlatformAdmin |
| GET | `/certificates/{id}/download` | Download a certificate rendition. | Customer, JudicialOfficer, PlatformAdmin |
| POST | `/certificates/{id}/revoke` | Administratively revoke a certificate. | PlatformAdmin |
| POST | `/verifications` | Run forensic verification and write a report. | Customer, JudicialOfficer, PlatformAdmin |
| POST | `/judicial-packages` | Prepare a DRAFT judicial package. | JudicialOfficer |
| GET | `/judicial-packages/{id}` | Read a judicial package. | JudicialOfficer, PlatformAdmin |
| POST | `/judicial-packages/{id}/seal` | Seal a judicial package: DRAFT to SEALED. | JudicialOfficer |
| POST | `/judicial-packages/{id}/deliver` | Deliver a judicial package: SEALED to DELIVERED. | JudicialOfficer |
| POST | `/invoices` | Issue an invoice over a single evidence, batch, or period. | Customer, PlatformAdmin |
| GET | `/invoices/{id}` | Read an invoice. | Customer, PlatformAdmin |
| GET | `/audit-logs` | List audit events. | PlatformAdmin |
| POST | `/_clock/advance` | Advance the server's logical clock. | PlatformAdmin |
| POST | `/_chain/confirm` | Simulate a chain confirmation for the latest transaction. | PlatformAdmin |
| POST | `/_chain/fail` | Simulate a chain failure for the latest transaction. | PlatformAdmin |
| POST | `/_sweep/run` | Run the expiry sweep over CONFIRMED evidences. | PlatformAdmin |
| POST | `/_events/payment` | Deliver an external payment event for a recharge. | PlatformAdmin |
| POST | `/_events/judicial-ack` | Deliver a judicial-authority delivery acknowledgement. | PlatformAdmin |
| POST | `/_events/notary-callback` | Deliver a notary office attachment callback. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_PERMISSION_DENIED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EVIDENCE_NOT_CONFIRMED` | 409 Conflict |
| `ERR_HASH_FORMAT_INVALID` | 422 Unprocessable Entity |
| `ERR_BATCH_MEMBER_INVALID` | 422 Unprocessable Entity |
| `ERR_BATCH_SIZE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_RESUBMIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_TIMESTAMP_REQUIRED` | 409 Conflict |
| `ERR_CERTIFICATE_REQUIRED` | 409 Conflict |
| `ERR_EVIDENCE_EXPIRED` | 410 Gone |
| `ERR_INSUFFICIENT_BALANCE` | 402 Payment Required |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 Conflict |
| `ERR_DUPLICATE_PAYMENT_REF` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_INVOICE_SCOPE_INVALID` | 422 Unprocessable Entity |
| `ERR_VALIDATION_FAILED` | 422 Unprocessable Entity |

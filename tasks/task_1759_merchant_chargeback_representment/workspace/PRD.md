# Merchant Chargeback Representment API — Product Requirements Document

## 1. Introduction

Card networks hold acquirers accountable for the dispute behavior of their merchant portfolios. When an issuer files a chargeback, the acquirer must debit the merchant, notify it within a defined window, assemble compelling evidence mapped to the network's reason code, and re-present the case before a hard network deadline — all while ratio-monitoring programs watch the merchant's monthly chargeback rate and can enroll a breaching merchant into an excessive-chargeback program with escalating monthly fines. This document specifies the acquirer-side API that operates that end-to-end representment workflow as the system of record for cases, money, and compliance state.

The API covers merchant onboarding with per-merchant rolling reserves, network case ingestion and deadline management, evidence packet assembly under the networks' single-cure allowance, fee pass-through under segregation of duties, holdbacks for high-risk merchants, a monthly ratio sweep that drives program enrollment, remediation plans and exit review, prevention-alert deflection, education assignments, and win-rate analytics. Four roles share the surface under a segregation-of-duties model: `AcquirerOps` operates network-facing ingestion and operations tooling, `MerchantUser` acts on behalf of a single merchant, `RiskOfficer` governs suspension, reserves, and program administration, and `FinanceOps` controls fee money movement. All resources are served under the `/acquirer` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity. A request missing either header, or carrying an empty value in one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles — `AcquirerOps`, `MerchantUser`, `RiskOfficer`, and `FinanceOps` — and each endpoint admits a declared subset of them (§4). An authenticated caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity binds to resources as follows. When `X-User-Role` is `MerchantUser`, `X-User-ID` is the `id` of the acting `Merchant`; ownership checks on any merchant-scoped resource compare the resource's `merchant_id` field to `X-User-ID`, and a mismatch is answered as if the resource did not exist (§2.7). When `X-User-Role` is `AcquirerOps`, `RiskOfficer`, or `FinanceOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `assessed_by_user_id` or `waived_by_user_id` on a `FeeAssessment`, or as `reviewed_by_user_id` on a `RemediationPlan` — but it is never compared to any entity's `id`. Fees assessed automatically by the system itself carry the literal value `system` in `assessed_by_user_id`.

`AcquirerOps` is the network-operations operator: it onboards merchants, manages reason-code rules, ingests settlement files, chargeback cases, and prevention alerts, posts network outcomes, and runs the monthly sweep and the logical clock. `MerchantUser` is the merchant-side operator: it accepts liability, uploads and withdraws evidence, assembles and submits representments, actions prevention alerts, drafts and submits remediation plans, and completes education assignments — always scoped to its own merchant. `AcquirerOps` may also upload evidence and assemble or submit representments on behalf of a merchant. `RiskOfficer` administers merchant suspension and reinstatement, reserve policy and reserve release, program enrollment and exit review, and remediation-plan review. `FinanceOps` assesses manual fees, waives fees under segregation of duties, and settles fees. All four roles may use every read (list and get) endpoint.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending; entries created within the same timestamp keep their creation order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` changes on any modification of the resource's properties. The `version` field is an integer that increments by one on every modification, including modifications made by cascades originating on another resource, and it anchors the optimistic-concurrency rules of §2.8.

Three record types are immutable once created and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: a `ReasonCodeRule` (configuration versioned by creating successor rules, never by update), a `ReserveLedgerEntry` (an append-only event log with no update or delete), and a `RatioSnapshot` (immutable once posted). All other entities — merchants, transactions, chargebacks, evidence items, representments, fee assessments, reserve accounts, program enrollments, remediation plans, prevention alerts, and education assignments — carry the full common set.

### 2.5. The Logical Clock and Inclusive Deadlines

All system-stamped instants in the API — receipt times, submission times, decision times, snapshot times, assignment and completion times — are read from a single logical clock, never from the wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An `AcquirerOps`-only test-driving capability sets the clock to any supplied `to_iso8601` instant (ISO 8601 UTC), moving it forward or backward, and returns the resulting `current_utc`. Every clock set fires the expiry sweeps: any `OPEN` prevention alert whose `response_due_at` has passed becomes `EXPIRED`, and any chargeback still in `RECEIVED` or `MERCHANT_NOTIFIED` whose `representment_due_at` has passed becomes `EXPIRED` with the cascades described in §3.5.

All three deadline types in the system are inclusive: the guarded action remains allowed while the current time is on or before the deadline, and is rejected — or the entity auto-expires at the next clock set — once the current time is strictly after it. Deadline arithmetic is performed at second precision on ISO 8601 UTC instants.

### 2.6. Monetary Precision, Basis Points, and Rounding

All monetary amounts in the API are integer cents; no fractional cents exist anywhere. All chargeback ratios and win rates are integer basis points (ten-thousandths). Rounding, wherever a computation produces a fraction, is round half up. One ordering rule is pinned for the rolling reserve: each per-transaction hold is rounded to whole cents first, and account balances are then folded from those individually rounded entries — rounding only at the aggregate level is not permitted (§3.3). Program fine amounts and the win-rate computation likewise round half up, to whole cents and to integer basis points respectively.

### 2.7. Existence Validation and Merchant Data Hiding

Requests that address nested resources are validated left to right along the path: the first identifier that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404), and identifiers referenced in the request body are checked after the path identifiers. A `MerchantUser` that touches a merchant-scoped resource whose `merchant_id` differs from its `X-User-ID` is answered with `ERR_NOT_FOUND` as well — existence is hidden, never surfaced as a permission failure. The same hiding applies to list scoping: when a `MerchantUser` lists merchants, transactions, or chargebacks, the result is force-scoped to the caller's own merchant regardless of any filter supplied.

### 2.8. Optimistic Concurrency Control

Two writes are guarded by optimistic concurrency control, and both reject a stale client view with `ERR_STALE_VERSION` (HTTP 412). Creating a representment requires the request to carry `expected_chargeback_version` equal to the target chargeback's current `version`; if the chargeback's version has advanced since the client last observed it — for example because another writer created a packet that superseded a returned-for-cure packet under the cure rule — the create is rejected, preventing the client from assembling a packet against a case state it has not observed. Patching a merchant's reserve policy requires `expected_merchant_version` equal to the merchant's current `version`; because a reserve-policy write blindly overwrites the prior policy values, a write based on a stale read would silently discard the effects of an intervening update, including its reserve-target recompute. No endpoint other than these two accepts a version field.

### 2.9. Validation Priority Order

When a request would fail several checks at once, the rejection surfaced is governed by a fixed priority order, evaluated from first to last:

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and non-empty (`ERR_UNAUTHENTICATED`, 401).
2. Role authorization — the role is permitted on this endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. Existence — path identifiers resolve left to right, then body-referenced identifiers resolve, with `MerchantUser` cross-merchant access hidden as not-found (`ERR_NOT_FOUND`, 404).
4. Optimistic concurrency — on the two OCC-guarded writes, the expected parent version matches (`ERR_STALE_VERSION`, 412).
5. State permissibility — the target or guarding entity is in a state that permits the operation (`ERR_INVALID_CASE_STATE`, `ERR_INVALID_REPRESENTMENT_STATE`, `ERR_INVALID_FEE_STATE`, `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_PLAN_STATE`, `ERR_ALERT_NOT_OPEN`, `ERR_ASSIGNMENT_NOT_OPEN`, `ERR_TRANSACTION_NOT_CHARGEBACKABLE`, `ERR_TRANSACTION_NOT_REFUNDABLE`; all 409).
6. Compliance gates — merchant suspension on merchant-side actions (`ERR_MERCHANT_SUSPENDED`, 409), merchant active for transaction ingest (`ERR_MERCHANT_NOT_ACTIVE`, 409), segregation of duties on fee waiver (`ERR_SEGREGATION_OF_DUTIES`, 403), and the program reserve lock (`ERR_PROGRAM_RESERVE_LOCK`, 409).
7. Uniqueness and structural constraints — `ERR_DUPLICATE_NETWORK_CASE`, `ERR_DUPLICATE_EXTERNAL_REF`, `ERR_TRANSACTION_HAS_OPEN_CHARGEBACK`, `ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION`, `ERR_RULE_WINDOW_OVERLAP`, `ERR_ENROLLMENT_WINDOW_OVERLAP`, `ERR_EMPTY_EVIDENCE_PACKET`, `ERR_EVIDENCE_NOT_ATTACHABLE`, `ERR_REPRESENTMENT_ALREADY_OPEN`, `ERR_CURE_LIMIT_EXCEEDED` (all 409).
8. Deadline gates — `ERR_REPRESENTMENT_DEADLINE_PASSED` and `ERR_ACCEPT_WINDOW_PASSED` (both 409), remembering that deadlines are inclusive.
9. Referential completeness — a governing reason-code rule must cover the case (`ERR_REASON_CODE_RULE_NOT_FOUND`, 422), and a submitted packet must satisfy compelling-evidence completeness (`ERR_EVIDENCE_INCOMPLETE`, 422).
10. Funds gates — a reserve release must produce a positive release amount (`ERR_NO_RELEASABLE_FUNDS`, 409).
11. Payload shape — required fields present, types valid (`ERR_INVALID_REQUEST`, 400), and enum fields carrying declared members (`ERR_INVALID_ENUM`, 400).

Payload-shape validation deliberately ranks last: a request that is both malformed and unauthenticated is answered as unauthenticated, and a request that is both malformed and state-invalid is answered with the state error.

## 3. Business Logic & Workflows

### 3.1. Merchant Onboarding, Suspension, and Reserve Policy

An `AcquirerOps` operator onboards a merchant by supplying its `legal_name` and `merchant_category_code` — the ISO 18245 four-digit MCC — together with three optional risk controls. The `risk_tier` is `STANDARD` by default; setting it to `HIGH_RISK` arms the per-chargeback reserve holdback described in §3.5. The `reserve_mode` selects the reserve-target algorithm and defaults to `FIXED_TIER`, the alternative being `EXPOSURE_BASED` (§3.3). The `reserve_rate_bps` is the share of each settled sale held into the rolling reserve, expressed in basis points: it defaults to 500 (that is, 5.00%) and must lie between 0 and 10000 inclusive. A new merchant starts in `ACTIVE` status with `clearing_balance_cents` at zero, and onboarding cascades to create its 1:1 `ReserveAccount` with `held_cents` and `target_cents` both zero. The merchant's `current_count_ratio_bps` is null until the first ratio snapshot is posted for it (§3.9). Merchants can be listed with `status` and `risk_tier` filters; a `MerchantUser` listing or reading merchants sees only its own record.

Suspension is a `RiskOfficer` action that moves the merchant `ACTIVE` → `SUSPENDED` and bumps its `version`; reinstatement moves it `SUSPENDED` → `ACTIVE` with another version bump. While a merchant is `SUSPENDED`, every merchant-side action is rejected with `ERR_MERCHANT_SUSPENDED` — evidence upload, representment creation and submission, chargeback acceptance, prevention-alert action, remediation-plan creation and submission, and education completion — and new transaction ingest for the merchant is rejected with `ERR_MERCHANT_NOT_ACTIVE`.

A `RiskOfficer` may patch a merchant's reserve policy, supplying `reserve_rate_bps` and/or `reserve_mode`; the write blindly overwrites the prior policy values. This is one of the two OCC-guarded writes of §2.8: the request must carry `expected_merchant_version`, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful patch bumps the merchant's `version` by one. The patch also recomputes the reserve account's `target_cents` under the newly written policy; a target recomputation never creates ledger entries by itself.

### 3.2. Reason-Code Rules and Effective-Window Governance

Every chargeback is governed by a `ReasonCodeRule`: the acquirer's configuration of what a given network reason code demands. An `AcquirerOps` operator creates a rule with its `network` (`VISA` or `MASTERCARD`), the network-assigned `reason_code` (for example `10.4` for a VISA fraud claim or `4853` for a Mastercard cardholder dispute), a `category` of `FRAUD`, `AUTHORIZATION`, `PROCESSING_ERROR`, or `CONSUMER_DISPUTE`, and the `required_evidence_types` checklist that a representment packet must satisfy (§3.6). The rule also carries the two deadline parameters — `merchant_response_days`, the calendar days from notification within which the merchant may accept liability, and `representment_days`, the calendar days from receipt that fix the network's hard representment deadline, each at least 1 — and the `chargeback_fee_cents`, the per-case fee auto-assessed to the merchant at receipt, which may be zero but not negative. Rules can be listed filtered by `network` and `reason_code`.

Rules are immutable configuration: there is no update or delete. Versioning is expressed by creating a new rule for the same (`network`, `reason_code`) pair with an adjacent effective window. Each rule's window runs from `effective_from` (inclusive) to `effective_to` (exclusive); a null `effective_to` is open-ended. Windows of the same (`network`, `reason_code`) pair are half-open and must not overlap — adjacency is allowed — and an overlapping creation is rejected with `ERR_RULE_WINDOW_OVERLAP`. At chargeback ingest, exactly one rule whose half-open window covers the case's `received_at` must exist for the case's (`network`, `reason_code`); otherwise ingest fails with `ERR_REASON_CODE_RULE_NOT_FOUND` (§3.5).

### 3.3. Settlement Ingestion and the Rolling Reserve

Transaction ingestion books a settled card sale. `AcquirerOps` supplies the `merchant_id`, a merchant-scoped `external_ref` (an ARN-style reference, unique within that merchant — a duplicate is rejected with `ERR_DUPLICATE_EXTERNAL_REF`), the `network`, the sale `amount_cents` (strictly positive), and the `occurred_at` sale timestamp, which later drives both the ratio denominator month and the reserve hold's maturity. Ingest requires the merchant to be `ACTIVE`, failing with `ERR_MERCHANT_NOT_ACTIVE` otherwise. The new transaction starts in `SETTLED` status. Each ingestion credits the merchant's `clearing_balance_cents` by the sale amount net of the per-transaction reserve hold, posts the hold to the reserve ledger, and recomputes the reserve account's `held_cents` and `target_cents`. A batch variant exists for settlement files: given a `merchant_id`, `network`, `count`, `amount_cents`, `occurred_at`, and `external_ref_prefix`, it creates `count` identical transactions whose `external_ref` is the prefix followed by a hyphen and a zero-padded four-digit sequence number running from 0001 up to `count`, applying the same per-transaction side effects in ascending sequence order, and reports `created_count`, `first_external_ref`, and `last_external_ref`. Transactions can be listed filtered by `merchant_id` and `status`, with the merchant force-scoping of §2.7 applied to `MerchantUser` callers.

The per-transaction hold is the sale's `amount_cents` multiplied by the merchant's `reserve_rate_bps` and divided by ten thousand, rounded half-up to a whole cent — rounded per transaction first, before any aggregation; a hold that rounds to zero posts no entry. The hold lands as a `ReserveLedgerEntry` of `entry_type` `HOLD` with `source_kind` `TRANSACTION_SETTLEMENT`, the `source_id` set to the transaction's id, and a `release_eligible_at` maturity exactly 90 days after the sale's `occurred_at`. The ledger is append-only: every entry carries its `reserve_account_id`, an `entry_type` of `HOLD`, `RELEASE`, or `FORFEIT`, a strictly positive `amount_cents`, a `source_kind` drawn from `TRANSACTION_SETTLEMENT`, `CHARGEBACK_RECEIPT`, `CHARGEBACK_WON`, `CHARGEBACK_LOST`, and `SCHEDULED_RELEASE`, a `source_id` naming the originating transaction or chargeback (null for `SCHEDULED_RELEASE`), and a `release_eligible_at` that is null for case-bound entries — holds sourced from `CHARGEBACK_RECEIPT` never mature. An account's `held_cents` is the fold of its ledger: the sum of all `HOLD` amounts minus the sum of all `RELEASE` amounts minus the sum of all `FORFEIT` amounts, and it is never negative by construction. Reserve accounts can be listed filtered by `merchant_id` as a reverse lookup for the merchant's 1:1 account, and the ledger itself is readable per account.

The reserve `target_cents` is computed in one of two variants selected by the merchant's `reserve_mode`. Both start from the rate floor: the merchant's `reserve_rate_bps` multiplied by the merchant's trailing ninety-day sales total and divided by ten thousand, rounded half-up to whole cents, where the trailing window is closed on both ends — transactions with `occurred_at` on or after the instant ninety days before now and on or before now count. Under `FIXED_TIER`, the target equals this floor and open exposure is ignored. Under `EXPOSURE_BASED`, the target is the greater of the rate floor and two times the merchant's open exposure, where open exposure is the sum of `amount_cents` over the merchant's chargebacks whose `case_status` is `RECEIVED`, `MERCHANT_NOTIFIED`, `REPRESENTED`, or `PRE_ARBITRATION` and whose `funds_status` is `MERCHANT_DEBITED`. The target is recomputed on transaction ingest, on any chargeback funds-axis transition, on a reserve-policy patch, and at the monthly sweep; each recomputation stamps `last_recomputed_at` and never creates ledger entries by itself.

Release of matured funds is a `RiskOfficer` capability. It is blocked outright while any program enrollment of the merchant is `ACTIVE` or in `REMEDIATION` — the compliance lock outranks funds availability and rejects with `ERR_PROGRAM_RESERVE_LOCK`. Otherwise the release amount follows a waterfall: the matured pool is the sum of all `HOLD` entries whose `source_kind` is `TRANSACTION_SETTLEMENT` and whose `release_eligible_at` is on or before now, minus the sum of all prior `RELEASE` entries whose `source_kind` is `SCHEDULED_RELEASE`; case-bound entries never enter the matured pool. The releasable amount is the matured pool floored at zero, and the release amount is the smaller of that releasable amount and the excess of `held_cents` over `target_cents`, the excess likewise floored at zero. If the release amount is not positive, the release is rejected with `ERR_NO_RELEASABLE_FUNDS`. Otherwise a `RELEASE` entry with `source_kind` `SCHEDULED_RELEASE` is posted for the release amount, `held_cents` is refolded, and the merchant's `clearing_balance_cents` increases by the released amount.

### 3.4. Prevention Alerts and Chargeback Deflection

Networks offer pre-dispute alerts that let a merchant deflect a chargeback before it exists. `AcquirerOps` ingests an alert by supplying the `transaction_id` of the sale the network flagged and an `alert_type` of `FRAUD_ALERT`, `DISPUTE_ALERT`, or `REFUND_OPPORTUNITY`; the alert's `merchant_id` is derived from the referenced transaction. A new alert is `OPEN`, stamped with `received_at` at ingest, and its `response_due_at` is exactly 72 hours later — the response window. Alerts can be listed filtered by `merchant_id`, `transaction_id`, and `status`.

While an alert is `OPEN`, a `MerchantUser` may action it in one of two ways, subject to ownership (§2.7) and to the merchant being `ACTIVE` (else `ERR_MERCHANT_SUSPENDED`). An `action` of `REFUND` additionally requires the referenced transaction to still be `SETTLED` — otherwise the request fails with `ERR_TRANSACTION_NOT_REFUNDABLE` — and performs the deflection: the transaction moves `SETTLED` → `REFUNDED`, the merchant's `clearing_balance_cents` decreases by the transaction's full `amount_cents` to fund the refund, and the alert becomes `ACTIONED_REFUND`; because a refunded sale can no longer be charged back, the case never reaches receipt. An `action` of `DISMISS` simply closes the alert as `DISMISSED` with no money movement. Because the response window is enforced by the expiry sweep rather than at action time, an alert whose `response_due_at` has passed is flipped to `EXPIRED` at the next clock set, and a late action then fails the state check with `ERR_ALERT_NOT_OPEN`.

### 3.5. Chargeback Receipt, Notification, and Merchant Acceptance

Chargeback ingestion books a network case against a merchant. `AcquirerOps` supplies the `merchant_id`, the `transaction_external_ref` of the disputed sale, the network-assigned `network_case_id`, the `reason_code`, and the disputed `amount_cents`. Ingest resolves the disputed transaction within the merchant's scope from the (`merchant_id`, `transaction_external_ref`) pair, recording the outcome on the case as `transaction_id`. The checks, in their governing order: the transaction must be `SETTLED` — a sale refunded through alert deflection is no longer chargebackable and fails with `ERR_TRANSACTION_NOT_CHARGEBACKABLE`; the merchant must be `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`); the `network_case_id` must be globally unique across all chargebacks (else `ERR_DUPLICATE_NETWORK_CASE`); the transaction must have no other chargeback in an open state — `RECEIVED`, `MERCHANT_NOTIFIED`, `REPRESENTED`, or `PRE_ARBITRATION` — else `ERR_TRANSACTION_HAS_OPEN_CHARGEBACK`; the disputed amount must be strictly positive and no greater than the transaction's `amount_cents`, partial chargebacks being allowed, else `ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION`; and a governing reason-code rule whose effective window covers the receipt instant must exist (else `ERR_REASON_CODE_RULE_NOT_FOUND`, 422). Chargebacks can be listed filtered by `merchant_id`, `transaction_id`, and `case_status`, again with merchant force-scoping for `MerchantUser`.

A freshly ingested case opens on two independent axes. On the lifecycle axis, `case_status` starts at `RECEIVED`; on the money axis, `funds_status` starts at `MERCHANT_DEBITED`. The case stamps `received_at` from the logical clock, computes `representment_due_at` as exactly `representment_days` calendar days after `received_at` (the network hard deadline, inclusive), copies its `network` from the disputed transaction, and initializes `recredited_cents` to zero and `is_ratio_counted` to true. Receipt then moves money: the merchant's `clearing_balance_cents` decreases by the disputed `amount_cents` (the receipt debit), the transaction flips `SETTLED` → `CHARGED_BACK`, and a `CHARGEBACK_FEE` fee assessment for the rule's `chargeback_fee_cents` is auto-created with `assessed_by_user_id` set to the literal `system` (§3.8). For a `HIGH_RISK` merchant there is a further cascade: a reserve `HOLD` entry for the full disputed amount is posted with `source_kind` `CHARGEBACK_RECEIPT`, the case's id as `source_id`, and a null `release_eligible_at` — case-bound holds never mature — followed by a refold of `held_cents`; the receipt also recomputes `target_cents`, because the new case joins the open-exposure set. `STANDARD` merchants see no reserve ledger activity at receipt.

Notification is an `AcquirerOps` action that moves the case `RECEIVED` → `MERCHANT_NOTIFIED`, stamps `merchant_notified_at` from the logical clock, computes `merchant_response_due_at` as exactly `merchant_response_days` calendar days after `merchant_notified_at`, and bumps the case `version`. Acceptance is the merchant's alternative to fighting: a `MerchantUser` owning the case may accept liability while the case is `MERCHANT_NOTIFIED`, provided the merchant is `ACTIVE` (else `ERR_MERCHANT_SUSPENDED`), no representment packet of this case is currently `ASSEMBLED` or `SUBMITTED` (else `ERR_REPRESENTMENT_ALREADY_OPEN`), and the current time is on or before `merchant_response_due_at` — the accept window is inclusive, and a late accept fails with `ERR_ACCEPT_WINDOW_PASSED`. Acceptance moves the case to the terminal `MERCHANT_ACCEPTED` state, sets `funds_status` to `DEBIT_FINAL` (the receipt debit stands), keeps `is_ratio_counted` true, and bumps the `version`.

If neither acceptance nor submission happens in time, the expiry sweep closes the case: when the clock is set past `representment_due_at`, a case still in `RECEIVED` or `MERCHANT_NOTIFIED` becomes `EXPIRED` (terminal), its `funds_status` becomes `DEBIT_FINAL`, any `ASSEMBLED` packet of the case is superseded — its attached evidence returning to `DRAFT` — the reserve target is recomputed, and the case `version` bumps. Notify, accept, reverse, and the pre-arbitration actions each permit only the states shown in their transitions; invoking one from any other state fails with `ERR_INVALID_CASE_STATE`.

### 3.6. Evidence Assembly and the Representment Packet

Compelling evidence accumulates as `EvidenceItem` records. A `MerchantUser` (for its own cases) or an `AcquirerOps` operator acting on the merchant's behalf uploads an item by supplying the `chargeback_id`, an `evidence_type` of `RECEIPT`, `AVS_MATCH`, `CVV_MATCH`, `DELIVERY_PROOF`, `SIGNED_AGREEMENT`, `REFUND_PROOF`, `PRIOR_TXN_HISTORY`, `IP_DEVICE_LOG`, or `CARDHOLDER_COMMUNICATION`, and an opaque `document_uri` locating the uploaded document. Upload is only meaningful while the case is being fought: the chargeback must be in `MERCHANT_NOTIFIED` or `REPRESENTED`, and upload at any other point of the lifecycle fails with `ERR_INVALID_CASE_STATE`; a suspended merchant's uploads fail with `ERR_MERCHANT_SUSPENDED`. A new item starts in `DRAFT`. The owning `MerchantUser` may withdraw a `DRAFT` item, moving it to the terminal `WITHDRAWN` state; items attached to a live packet cannot be withdrawn. Evidence items can be listed filtered by `chargeback_id` and `status`.

Packet assembly creates a `Representment` from a `chargeback_id`, an ordered `evidence_item_ids` list, and the OCC token `expected_chargeback_version` (§2.8). The checks unfold in priority order: the expected version must match the chargeback's current `version` (else `ERR_STALE_VERSION`, 412); the case must be in `MERCHANT_NOTIFIED` or `REPRESENTED` (else `ERR_INVALID_CASE_STATE`); the merchant must be `ACTIVE` (else `ERR_MERCHANT_SUSPENDED`); no other packet of this case may be `ASSEMBLED` or `SUBMITTED` (else `ERR_REPRESENTMENT_ALREADY_OPEN` — an in-flight packet is caught here, before the cure check); when the case is `REPRESENTED`, the latest non-`SUPERSEDED` packet must be a `RETURNED_FOR_CURE` packet with `cure_count` below 1, the network allowing at most one cure per packet lineage (else `ERR_CURE_LIMIT_EXCEEDED`); the `evidence_item_ids` list must be non-empty (else `ERR_EMPTY_EVIDENCE_PACKET`); and every listed id must resolve to an evidence item of this chargeback currently in `DRAFT` (else `ERR_EVIDENCE_NOT_ATTACHABLE`).

Assembly succeeds into the `ASSEMBLED` state with several side effects. The new packet's `cure_count` is 0 when the case was `MERCHANT_NOTIFIED` — a first packet — and otherwise one more than the superseded packet's `cure_count`. A prior `RETURNED_FOR_CURE` packet becomes `SUPERSEDED`, and its attached evidence returns to `DRAFT`; each evidence item named in the new packet moves `DRAFT` → `ATTACHED`. Assembly is also case activity: the chargeback's `version` bumps by one, which is the write the OCC rule serializes. An item remains `ATTACHED` while referenced by a non-superseded packet and returns to `DRAFT` whenever that packet is superseded — evidence attachment is cyclic, `DRAFT` → `ATTACHED` → `DRAFT`.

Submission sends an `ASSEMBLED` packet to the network; submitting a packet in any other state fails with `ERR_INVALID_REPRESENTMENT_STATE`. A submitting `MerchantUser` must own the parent chargeback (ownership mismatch is hidden as `ERR_NOT_FOUND`), the merchant must be `ACTIVE` (else `ERR_MERCHANT_SUSPENDED`), and the current time must be on or before the case's `representment_due_at` — the deadline is inclusive, and a late submit fails with `ERR_REPRESENTMENT_DEADLINE_PASSED`. Finally the packet must satisfy compelling-evidence completeness: every type listed in the governing rule's `required_evidence_types` must be covered by at least one `ATTACHED` item of this packet, else the submit fails with `ERR_EVIDENCE_INCOMPLETE` (422). A successful submit stamps `submitted_at`, bumps the chargeback's `version`, and — on the first submission for the case — moves the chargeback `MERCHANT_NOTIFIED` → `REPRESENTED`; a resubmission after a cure finds the case already `REPRESENTED` and leaves it there.

### 3.7. Network Outcomes, the Pre-Arbitration Cycle, and Reversal

The network's decision arrives through `AcquirerOps` posting an `outcome` on a packet; the packet must be `SUBMITTED`, and posting an outcome for a packet in any other state fails with `ERR_INVALID_REPRESENTMENT_STATE`. Four outcomes exist. An `outcome` of `WON` moves the packet `SUBMITTED` → `WON`, sets its `won_amount_cents` to the chargeback's full `amount_cents`, and stamps `decided_at`. An `outcome` of `PARTIAL_WON` requires a `won_amount_cents` strictly greater than zero and strictly less than the chargeback's `amount_cents` — a missing or out-of-range value fails with `ERR_INVALID_REQUEST` — records that amount, and stamps `decided_at`. An `outcome` of `LOST` moves the packet to `LOST` and stamps `decided_at`. An `outcome` of `RETURNED_FOR_CURE` keeps the case open: it is allowed only while the packet's `cure_count` is below 1 (else `ERR_CURE_LIMIT_EXCEEDED`), moves the packet to `RETURNED_FOR_CURE`, leaves `decided_at` null, keeps the chargeback in `REPRESENTED` with the cure window open, and bumps the chargeback's `version`. `WON`, `PARTIAL_WON`, `LOST`, and `SUPERSEDED` are the packet's terminal states; a `RETURNED_FOR_CURE` packet awaits its successor, which supersedes it at assembly time (§3.6).

A decided win cascades to the chargeback, which moves `REPRESENTED` → `DECIDED_WON`: `funds_status` becomes `FUNDS_RETURNED`, `recredited_cents` records the returned amount — the full `amount_cents` on a `WON`, the recorded `won_amount_cents` on a `PARTIAL_WON` — and the merchant's `clearing_balance_cents` increases by `recredited_cents` as the re-credit lands. For a `HIGH_RISK` merchant the receipt holdback is unwound: a `RELEASE` entry for the disputed amount posts with `source_kind` `CHARGEBACK_WON` and the case as `source_id`, `held_cents` is refolded, and `target_cents` is recomputed because the case leaves the open-exposure set; the case `version` bumps. A loss moves the case `REPRESENTED` → `DECIDED_LOST` (terminal): `funds_status` becomes `DEBIT_FINAL` with no money movement — the receipt debit stands — and for a `HIGH_RISK` merchant the holdback is forfeited through a `FORFEIT` entry with `source_kind` `CHARGEBACK_LOST`, followed by the `held_cents` refold, the target recompute, and the version bump.

`DECIDED_WON` is not terminal, because the issuer may escalate: `AcquirerOps` can move a won case to `PRE_ARBITRATION`, which re-debits the merchant — `funds_status` returns to `MERCHANT_DEBITED`, `clearing_balance_cents` decreases by `recredited_cents` to reverse the win re-credit — and, for a `HIGH_RISK` merchant, restores the holdback with a fresh case-bound `HOLD` entry (`source_kind` `CHARGEBACK_RECEIPT`, null maturity), refolds `held_cents`, and recomputes the target; the case `version` bumps. The pre-arbitration decision then arrives through `AcquirerOps` posting a `decision`: a `decision` of `WON` returns the case `PRE_ARBITRATION` → `DECIDED_WON` with `funds_status` `FUNDS_RETURNED`, re-crediting `recredited_cents` to clearing and releasing the holdback again through a `CHARGEBACK_WON` release entry; a `decision` of `LOST` moves the case to the terminal `DECIDED_LOST` with `funds_status` `DEBIT_FINAL`, `recredited_cents` staying as recorded while the pre-arbitration re-debit stands, and the holdback forfeited through a `CHARGEBACK_LOST` entry. Both branches refold `held_cents`, recompute the target, and bump the version — the lifecycle axis cycles `DECIDED_WON` → `PRE_ARBITRATION` → `DECIDED_WON` or `DECIDED_LOST` until the network lets the case rest.

Reversal is the network or issuer undoing the case entirely, available to `AcquirerOps` while the case is `RECEIVED`, `MERCHANT_NOTIFIED`, or `REPRESENTED`. The case becomes `REVERSED` (terminal) with `funds_status` `NOT_DEBITED`: the merchant's `clearing_balance_cents` increases by the full disputed `amount_cents` as a compensating credit for the receipt debit, any `ASSEMBLED`, `SUBMITTED`, or `RETURNED_FOR_CURE` packet is superseded with its attached evidence returning to `DRAFT`, and `is_ratio_counted` flips to false so the case drops out of the posted-basis ratio numerator (§3.9). Two subtleties deserve emphasis: the auto-assessed `CHARGEBACK_FEE` is not auto-waived — network fees survive reversal — and for a `HIGH_RISK` merchant the receipt holdback is unwound through a `RELEASE` entry whose `source_kind` is `CHARGEBACK_WON`, exactly as a won case would unwind it, followed by the `held_cents` refold and target recompute. The case `version` bumps with the reversal.

### 3.8. Fee Pass-Through, Waiver, and Settlement

Fees flow to merchants as `FeeAssessment` records of three kinds. A `CHARGEBACK_FEE` is system-assessed at chargeback receipt for the governing rule's `chargeback_fee_cents`, with the originating case recorded in `chargeback_id`. A `PROGRAM_FINE` is system-assessed by the monthly sweep with the originating enrollment recorded in `enrollment_id` (§3.9). An `ARBITRATION_FEE` is the only kind a human may create: a `FinanceOps` operator assesses one by supplying the `merchant_id`, the `kind`, a strictly positive `amount_cents`, and optionally the `chargeback_id` or `enrollment_id` it relates to; requesting any other kind through the manual endpoint is rejected with `ERR_INVALID_REQUEST`. For system-assessed fees the reference fields are system-derived — `chargeback_id` for a `CHARGEBACK_FEE`, `enrollment_id` for a `PROGRAM_FINE`, null otherwise — and `assessed_by_user_id` is the literal `system`; for a manual assessment it records the assessing `FinanceOps` user's `X-User-ID`. Every fee starts `ASSESSED`, with `settled_at` and `waived_at` null and `waived_by_user_id` null until the corresponding event. Fees can be listed filtered by `merchant_id`, `chargeback_id`, `enrollment_id`, and `status`.

Two terminal resolutions exist, both `FinanceOps` actions and both requiring the fee to still be `ASSESSED` — acting on a fee in any other state fails with `ERR_INVALID_FEE_STATE`. Settlement collects the fee from the merchant's clearing: `clearing_balance_cents` decreases by the fee's `amount_cents`, `settled_at` is stamped, and the fee becomes `SETTLED`. Waiver forgives the fee with no money movement, moving it `ASSESSED` → `WAIVED` while recording `waived_by_user_id` and `waived_at`, under a segregation-of-duties rule: whenever the fee's `assessed_by_user_id` is a real user rather than the literal `system`, the waiving user's `X-User-ID` must differ from it — a `FinanceOps` operator cannot waive a fee they assessed themselves, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). System-assessed fees are exempt from the segregation check and may be waived by any `FinanceOps` operator.

### 3.9. The Monthly Sweep, Program Enforcement, and Win-Rate Analytics

Once a month per merchant and network, an `AcquirerOps` operations checkpoint posts the ratio snapshots for a supplied `period_month` (format YYYY-MM), optionally restricted to a single `merchant_id`. A snapshot is posted for every merchant × network combination with any sales or chargeback activity in that month; a repeat sweep of an already-posted (merchant, network, `period_month`) triple skips it. Each snapshot records the `sales_count` — the merchant's transactions on that network with `occurred_at` inside the month, of any status — and their `sales_amount_cents` total; the `chargeback_count`, the posted-basis numerator of chargebacks with `received_at` inside the month whose `case_status` is not `REVERSED` at sweep time; and the `gross_chargeback_count`, the gross-basis numerator that includes `REVERSED` cases. Both ratios are computed the same way: ten thousand times the numerator divided by the denominator, rounded half-up to an integer basis point — except that a zero denominator with a positive numerator yields the sentinel value of 100,000 basis points, and zero activity in both yields zero. The posted-basis result lands in `count_ratio_bps`, the gross-basis result in `gross_count_ratio_bps`, so a reversed case still inflates the gross figure; `computed_at` stamps the sweep instant, and snapshots are immutable once posted. Each swept merchant's `current_count_ratio_bps` refreshes to the `count_ratio_bps` of its most recent posted snapshot by `period_month` (breaking any tie by the latest `computed_at`), remaining null while no snapshot exists; snapshots are readable per merchant, optionally filtered to one `period_month`. The checkpoint response tallies `snapshots_created`, `snapshots_skipped`, `enrollments_created`, and `fines_assessed`, and each swept merchant's reserve `target_cents` is recomputed as part of the run.

Threshold evaluation follows each snapshot on the posted basis, per network. For `VISA`, the excessive tier `VDMP_EXCESSIVE` matches when `count_ratio_bps` is at least 180 and `chargeback_count` is at least 10; the standard tier `VDMP_STANDARD` matches at a `count_ratio_bps` of at least 90 with a `chargeback_count` of at least 5. For `MASTERCARD`, `HECM` matches at a `count_ratio_bps` of at least 300 with a `chargeback_count` of at least 10, and `ECM` matches at least 150 with at least 10. Boundaries are inclusive, the higher tier wins when both match, and when no tier matches nothing happens — no enrollment, no counter change. If an `ACTIVE` or `REMEDIATION` enrollment already exists for the merchant and network, an over-threshold month increments its `months_over_count` by one while an under-threshold month leaves it unchanged. If none exists and a tier matches, a `ProgramEnrollment` is created in `ACTIVE` status with `enrolled_month` set to the swept month and `months_over_count` at 1.

A `RiskOfficer` may also enroll a merchant manually — an audit-driven path supplying `merchant_id`, `network`, `program_code`, and `enrolled_month` — subject to a month-overlap rule: enrollment month ranges are closed intervals from `enrolled_month` to `exited_month` per (`merchant_id`, `network`, `program_code`) triple and must not overlap, so even re-enrollment in the prior exit month itself conflicts and is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`. The `program_code` values are `VDMP_STANDARD`, `VDMP_EXCESSIVE`, `ECM`, and `HECM`; the naming family — `VDMP_*` for VISA-originated programs, `ECM` and `HECM` for MASTERCARD-originated ones — is a convention only and is not enforced as a cross-field validation. Enrollments can be listed filtered by `merchant_id` and `status`.

Every enrollment creation cascades to merchant education: two `EducationAssignment` records are created for the merchant with `assigned_reason` `PROGRAM_ENROLLMENT` and an `enrollment_ref` naming the triggering enrollment — an informational reference, not a navigable foreign key. The assigned `module_code` pair depends on the program family: `VDMP_*` enrollments assign `CHARGEBACK_BASICS` plus `EVIDENCE_BEST_PRACTICE`, while `ECM` and `HECM` enrollments assign `CHARGEBACK_BASICS` plus `FRAUD_PREVENTION`. Each assignment starts `ASSIGNED`, stamped with `assigned_at`, and the owning `MerchantUser` completes it — while the merchant is `ACTIVE` and the assignment still `ASSIGNED`, else `ERR_MERCHANT_SUSPENDED` or `ERR_ASSIGNMENT_NOT_OPEN` respectively — moving it to `COMPLETED` with `completed_at` stamped. A merchant's assignments are listed under the merchant, filterable by `status`.

Program fines follow a pinned evaluation order within the sweep: the snapshot is posted and its ratio computed first; the enrollment's `months_over_count` is then incremented for an over-threshold month; and the fine is computed from the already-incremented count. The fine is the program's base amount — 250,000 cents for `VDMP_STANDARD` and `ECM`, 500,000 cents for `VDMP_EXCESSIVE` and `HECM` — multiplied by a tiered multiplier of the month count: face value for the first three months, one and a half times for months four through six, and double from the seventh month onward, with the result rounded half-up to whole cents. The fine lands as a `PROGRAM_FINE` `FeeAssessment` carrying the `enrollment_id` and `assessed_by_user_id` `system`. Enrollments in `REMEDIATION` are not fined: once a remediation plan is approved, fine assessment stops while the enrollment remains in `REMEDIATION`.

Remediation itself runs on `RemediationPlan` records. The owning `MerchantUser` drafts a plan for an `ACTIVE` or `REMEDIATION` enrollment — drafting against an `EXITED` enrollment fails with `ERR_INVALID_ENROLLMENT_STATE` — supplying a non-empty `root_cause_codes` list drawn from `FRAUD_GAP`, `FULFILLMENT_GAP`, `CUSTOMER_SERVICE_GAP`, and `POLICY_GAP`, plus a non-empty `corrective_actions` list of free-text descriptions; at most one plan per enrollment may be `DRAFT` or `SUBMITTED` at a time, and creating a second open plan fails with `ERR_INVALID_PLAN_STATE`. A new plan starts `DRAFT`; submission moves `DRAFT` → `SUBMITTED` and is also the path that resubmits a `RETURNED` plan — submitting from any other state fails with `ERR_INVALID_PLAN_STATE`. A `RiskOfficer` then reviews a `SUBMITTED` plan (reviewing a plan in any other state fails with `ERR_INVALID_PLAN_STATE`) with a `decision`: `APPROVE` moves the plan to its terminal `APPROVED` state and the parent enrollment `ACTIVE` → `REMEDIATION`, while `RETURN` moves the plan to `RETURNED`, from which the merchant may edit and resubmit — the review cycle `SUBMITTED` → `RETURNED` → `SUBMITTED` repeats until approval. Either review records the reviewing user in `reviewed_by_user_id` and captures the optional `decision_note`. An enrollment's plans are listed under the enrollment as a reverse lookup.

Exit from a program is a `RiskOfficer` exit-review supplying the `exited_month`, permitted from `ACTIVE` or `REMEDIATION` — an already-`EXITED` enrollment rejects the review with `ERR_INVALID_ENROLLMENT_STATE`. Two exit criteria must both hold, else the review fails with `ERR_EXIT_CRITERIA_NOT_MET`: an `APPROVED` remediation plan must exist for the enrollment, and at least three posted snapshots must exist for the merchant and network with the three most recent by `period_month` all strictly below the program threshold. A successful review moves the enrollment to `EXITED` and records the supplied `exited_month`.

The win-rate analytics read closes the loop for both acquirer and merchant. It computes over decided representments only — those in `WON`, `PARTIAL_WON`, or `LOST`, joined to their chargebacks and filtered by the optional `merchant_id`, `reason_code`, and `network` parameters, while `ASSEMBLED`, `SUBMITTED`, `RETURNED_FOR_CURE`, and `SUPERSEDED` packets are excluded — and reports `decided_count`, `won_count`, `partial_win_count`, `lost_count`, and `win_rate_bps`. The win rate counts a partial win as half a win: it is ten thousand times the sum of full wins plus half the partial wins, divided by the number of decided representments, rounded half-up to an integer basis point. When the filtered set contains no decided representments, `win_rate_bps` is null.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, modify, or transition an existing resource return `200 OK`. Request bodies, side effects, and preconditions are defined by the workflows of §3; the table below fixes only the HTTP contract and the admitted roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/acquirer/merchants` | Onboard a merchant; auto-creates its 1:1 reserve account | AcquirerOps |
| GET | `/acquirer/merchants` | List merchants with pagination and filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/merchants/{id}` | Get one merchant | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| PATCH | `/acquirer/merchants/{id}/reserve-policy` | OCC-guarded reserve policy update; recomputes the reserve target | RiskOfficer |
| POST | `/acquirer/merchants/{id}/suspend` | Suspend a merchant | RiskOfficer |
| POST | `/acquirer/merchants/{id}/reinstate` | Reinstate a suspended merchant | RiskOfficer |
| POST | `/acquirer/reason-code-rules` | Create a reason-code rule version with a half-open effective window | AcquirerOps |
| GET | `/acquirer/reason-code-rules` | List reason-code rules with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/transactions` | Ingest one settled card sale | AcquirerOps |
| POST | `/acquirer/transactions/batch` | Batch settlement-file ingest of identical sales | AcquirerOps |
| GET | `/acquirer/transactions` | List transactions with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/transactions/{id}` | Get one transaction | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/chargebacks` | Ingest a network chargeback case with its receipt debit cascade | AcquirerOps |
| GET | `/acquirer/chargebacks` | List chargebacks with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/chargebacks/{id}` | Get one chargeback | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/chargebacks/{id}/notify` | Notify the merchant; open the response window | AcquirerOps |
| POST | `/acquirer/chargebacks/{id}/accept` | Merchant accepts liability within the response window | MerchantUser |
| POST | `/acquirer/chargebacks/{id}/reverse` | Network reversal / issuer withdrawal with compensating credit | AcquirerOps |
| POST | `/acquirer/chargebacks/{id}/pre-arbitration` | Issuer escalates a won case to pre-arbitration | AcquirerOps |
| POST | `/acquirer/chargebacks/{id}/pre-arbitration/outcome` | Network decision on a pre-arbitration case | AcquirerOps |
| POST | `/acquirer/evidence-items` | Upload a compelling-evidence document for a case | MerchantUser, AcquirerOps |
| GET | `/acquirer/evidence-items` | List evidence items with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/evidence-items/{id}` | Get one evidence item | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/evidence-items/{id}/withdraw` | Withdraw a DRAFT evidence item | MerchantUser |
| POST | `/acquirer/representments` | Assemble a representment packet from DRAFT evidence (OCC-guarded) | MerchantUser, AcquirerOps |
| GET | `/acquirer/representments` | List representments with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/representments/{id}` | Get one representment | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/representments/{id}/submit` | Submit the packet to the network before the inclusive deadline | MerchantUser, AcquirerOps |
| POST | `/acquirer/representments/{id}/network-outcome` | Post the network decision on a submitted packet | AcquirerOps |
| POST | `/acquirer/fee-assessments` | Manual fee assessment, restricted to ARBITRATION_FEE | FinanceOps |
| GET | `/acquirer/fee-assessments` | List fee assessments with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/fee-assessments/{id}` | Get one fee assessment | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/fee-assessments/{id}/waive` | Waive an ASSESSED fee under segregation of duties | FinanceOps |
| POST | `/acquirer/fee-assessments/{id}/settle` | Settle an ASSESSED fee by collecting it from clearing | FinanceOps |
| GET | `/acquirer/reserve-accounts` | List reserve accounts (reverse lookup for the merchant's 1:1 account) | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/reserve-accounts/{id}` | Get one reserve account | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/reserve-accounts/{id}/release` | Release matured settlement holds down to the reserve target | RiskOfficer |
| GET | `/acquirer/reserve-accounts/{id}/ledger-entries` | List the append-only reserve ledger of an account | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/merchants/{id}/ratio-snapshots` | List posted ratio snapshots of a merchant | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/program-enrollments` | Manual, audit-driven program enrollment | RiskOfficer |
| GET | `/acquirer/program-enrollments` | List program enrollments with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/program-enrollments/{id}` | Get one program enrollment | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/program-enrollments/{id}/exit-review` | Exit-review decision against the exit criteria | RiskOfficer |
| GET | `/acquirer/program-enrollments/{id}/remediation-plans` | List remediation plans of an enrollment | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/remediation-plans` | Draft a remediation plan for an open enrollment | MerchantUser |
| POST | `/acquirer/remediation-plans/{id}/submit` | Submit a DRAFT plan or resubmit a RETURNED plan | MerchantUser |
| POST | `/acquirer/remediation-plans/{id}/review` | Review a submitted plan (APPROVE or RETURN) | RiskOfficer |
| POST | `/acquirer/prevention-alerts` | Ingest a network prevention alert for a transaction | AcquirerOps |
| GET | `/acquirer/prevention-alerts` | List prevention alerts with filters | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| GET | `/acquirer/prevention-alerts/{id}` | Get one prevention alert | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/prevention-alerts/{id}/action` | Merchant actions an OPEN alert (REFUND or DISMISS) | MerchantUser |
| GET | `/acquirer/merchants/{id}/education-assignments` | List a merchant's education assignments | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/education-assignments/{id}/complete` | Mark an ASSIGNED education module complete | MerchantUser |
| GET | `/acquirer/analytics/win-rate` | Win-rate analytics over decided representments | AcquirerOps, RiskOfficer, FinanceOps, MerchantUser |
| POST | `/acquirer/ops/advance-month` | Monthly ops checkpoint: snapshots, thresholds, enrollments, fines | AcquirerOps |
| POST | `/acquirer/_clock/set_current_utc` | Set the test-driving logical clock and fire the expiry sweeps | AcquirerOps |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifier and HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_NETWORK_CASE` | 409 Conflict |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 Conflict |
| `ERR_REASON_CODE_RULE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_RULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TRANSACTION_NOT_CHARGEBACKABLE` | 409 Conflict |
| `ERR_TRANSACTION_HAS_OPEN_CHARGEBACK` | 409 Conflict |
| `ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION` | 409 Conflict |
| `ERR_MERCHANT_SUSPENDED` | 409 Conflict |
| `ERR_MERCHANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_CASE_STATE` | 409 Conflict |
| `ERR_ACCEPT_WINDOW_PASSED` | 409 Conflict |
| `ERR_REPRESENTMENT_DEADLINE_PASSED` | 409 Conflict |
| `ERR_EVIDENCE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_NOT_ATTACHABLE` | 409 Conflict |
| `ERR_EMPTY_EVIDENCE_PACKET` | 409 Conflict |
| `ERR_REPRESENTMENT_ALREADY_OPEN` | 409 Conflict |
| `ERR_CURE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_REPRESENTMENT_STATE` | 409 Conflict |
| `ERR_INVALID_FEE_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NO_RELEASABLE_FUNDS` | 409 Conflict |
| `ERR_PROGRAM_RESERVE_LOCK` | 409 Conflict |
| `ERR_ENROLLMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_ENROLLMENT_STATE` | 409 Conflict |
| `ERR_EXIT_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_INVALID_PLAN_STATE` | 409 Conflict |
| `ERR_ALERT_NOT_OPEN` | 409 Conflict |
| `ERR_TRANSACTION_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_OPEN` | 409 Conflict |

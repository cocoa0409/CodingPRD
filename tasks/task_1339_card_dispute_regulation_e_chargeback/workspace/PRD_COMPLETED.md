# Card Dispute & Regulation E Chargeback API — Product Requirements Document

## 1. Introduction

Card-issuing banks operate under Regulation E, which imposes strict, clock-driven obligations on how cardholder disputes are received, investigated, provisionally credited, and resolved. Miss the provisional credit window by a day and the bank is out of compliance; file a network chargeback a day late and the recovery right is gone; reverse a cardholder's provisional credit without proper notice and the bank has created a regulatory violation of its own. The system specified here is the issuer-side engine that enforces those obligations deterministically: dispute intake with provisional credit timing rules, an error-resolution investigation window whose length depends on the transaction type and the age of the account, chargeback reason code selection against network deadlines, merchant representment review and second presentment, escalation to pre-compliance or arbitration with their associated costs, fraud versus non-fraud classification with its consumer liability tiers, provisional credit reversal notification, and finally loss recognition and recovery accounting.

Three properties of the domain shape the design. First, every deadline is derived from a **logical clock** the operator controls, never from wall-clock time, so that compliance behavior is reproducible and testable. Second, money moves through the system in integer cents along a small number of well-defined paths — provisional credit grant, reversal, reinstatement, finalization true-up, network fee accrual, and loss ledger entries — and each path is auditable. Third, duties are segregated: the agent who intakes a dispute may not resolve it, chargeback work belongs to network specialists, and only finance operations may reverse a credit or post to the loss ledger.

This document is the complete product requirements specification for the API. Section 2 defines system-wide contracts; Section 3 walks the business workflows in lifecycle order; Sections 4 and 5 summarize the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` identifying the acting party and `X-User-Role` naming their operational capacity. The system recognizes exactly six roles: `Cardholder`, `IntakeAgent`, `DisputeInvestigator`, `ChargebackAnalyst`, `FinanceOfficer`, and `BankAdmin`. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_AUTH` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `CardAccount`; ownership checks on any resource trace back to that account — a cardholder may file a dispute only against a transaction whose account's `id` equals their `X-User-ID`, may withdraw only their own cases, and may read only their own account, transactions, and disputes. When `X-User-Role` is `IntakeAgent`, `DisputeInvestigator`, `ChargebackAnalyst`, `FinanceOfficer`, or `BankAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, an `IntakeAgent`'s `X-User-ID` is stamped onto the case as `intake_agent_id` at filing, and the resolving investigator's `X-User-ID` is compared against it for segregation of duties — but it is never treated as the `id` of an entity.

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

Requests that match no defined route — or a defined route with an unsupported method — are rejected in the same envelope as `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. List filters are exact-match equality filters, and a filter value that matches no resource simply yields an empty page — except the `type` filters on the notification and loss-recovery collections (§3.8), whose domains are fixed and where an unrecognized value is rejected with `ERR_INVALID_REQUEST`.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Regulatory Deadline Arithmetic

Every timestamp the system assigns and every deadline it enforces is read from a **logical clock**, never from the host's wall clock — the sole exception is the response envelope's `api_request_timestamp` (§2.2), which is transport-level metadata rendered from wall-clock UTC. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time. A `BankAdmin` may set the logical clock by supplying a `to_iso8601` instant — any parseable ISO 8601 instant is accepted, forward or backward, and an unparseable value is rejected with `ERR_INVALID_REQUEST`; the capability responds with the resulting `current_utc`. Intake timestamps, filing timestamps, notification send times, reversal cooling checks, and every regulatory deadline described below are computed against this clock. Every business timestamp the server stamps — `opened_at`, `posted_at`, `received_at`, `granted_at`, `filed_at`, `sent_at`, `reversed_at`, every deadline and window field, and the clock's `current_utc` — is rendered as ISO 8601 UTC at whole-second precision with a `Z` suffix; only the `created_at` and `updated_at` fields of §2.5 carry three fractional digits.

Two calendar conventions recur throughout the specification. **Business days** mean Monday through Friday only, with no holiday calendar; when a rule says a period of business days runs from an event, counting begins the day *after* the event. **End-of-day inclusive deadlines** mean the deadline instant is 23:59:59Z on the final calendar day of the period, and an action taken at or before that instant is timely. Where the two conventions combine — as with the provisional credit due date — the business-day count lands on a date and that date's end of day is the inclusive deadline.

### 2.5. Common Resource Properties

All primary resources — Card Accounts, Card Transactions, Dispute Cases, Provisional Credits, Chargebacks, and Representments — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource, including mutations caused by system cascades originating on another entity.

Two resource types are deliberately lighter. A **Notification** and a **LossRecovery** ledger entry carry only `id` and `created_at` from the standard set; both `updated_at` and `version` are absent from them, because letters and ledger entries are immutable once created.

### 2.6. Monetary Representation, Precision, and Rounding

All monetary quantities in the system — balances, claim amounts, credit amounts, holdbacks, liabilities, fees, and loss ledger amounts — are represented as integer cents. Liability and ledger arithmetic is exact integer math with no rounding. The single exception is network fee computation at chargeback escalation, where a stage fee is computed from a base amount plus a percentage of the chargeback amount: each stage fee is individually rounded half-up to whole cents first, and only then summed with the filing fee into the chargeback's total. The fractional components of different stages are never summed before rounding.

### 2.7. Optimistic Concurrency Control on Reclassification

Reclassification is a legitimate, repeatable action while a case sits in `CLASSIFIED` — an investigator may refine the fraud determination more than once. Because a second sequential request carrying an outdated view of the case would silently overwrite a colleague's updated classification, the reclassification action is protected by optimistic concurrency control. A reclassification request must carry `expected_dispute_version` — a positive integer under the schema tier — holding the `version` of the Dispute Case the client last observed. If that value does not match the case's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint in the API accepts or requires a version field.

### 2.8. Validation Priority and Nested Resource Retrieval

Requests are validated against a fixed priority ladder, and a failure at an earlier tier masks all later checks. Evaluated in order, the tiers are: first, presence of the authentication headers and a recognized role (`ERR_MISSING_AUTH`); second, whether the presented role is permitted on the endpoint at all (`ERR_FORBIDDEN`); third, request-body schema — required fields present, enum members valid, integer amounts strictly greater than zero (non-amount integer fields — the opening balance and the report-delay day counts — are non-negative instead, zero permitted), unknown fields rejected (`ERR_INVALID_REQUEST`); fourth, existence of every referenced resource (`ERR_NOT_FOUND`); fifth, cardholder ownership where the caller is a `Cardholder` (`ERR_FORBIDDEN`); sixth, entity state preconditions for the requested transition (`ERR_INVALID_STATE`, with the more specific `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where applicable); seventh, the optimistic concurrency check on reclassification (`ERR_STALE_VERSION`); eighth, segregation of duties on resolution (`ERR_SOD_VIOLATION`); ninth, temporal compliance gates — the provisional credit requirement, the investigation window, the network filing deadline, and the reversal-notice cooling period; tenth, business constraints — network window occupancy, reason-code compatibility, and evidence presence; and eleventh, fiscal bounds — the claim-versus-transaction-amount bound and the recovery-versus-outstanding-loss bound.

Existence checks follow the URL hierarchy strictly left to right: for a nested path, each path identifier is confirmed to exist in sequence, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve, before any deeper validation occurs. Body-referenced resource identifiers are validated in the same existence tier.

### 2.9. Fraud Restriction and Cross-Entity State Consistency

A Card Account is either `ACTIVE` or `RESTRICTED`. The restriction is not applied by any direct account-mutation call; it is a **system cascade**. Whenever a dispute classification or reclassification marks a case as fraud, the account behind the disputed transaction moves from `ACTIVE` to `RESTRICTED` — idempotently, so an already-restricted account is unaffected. While any non-terminal fraud case references the account, it stays `RESTRICTED`, and the concrete consequence is that seeding new posted transactions against it fails with `ERR_ACCOUNT_RESTRICTED`. The account returns to `ACTIVE` automatically at the moment no fraud Dispute Case for it remains in any of `RECEIVED`, `CLASSIFIED`, `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING` — whether that moment arrives through resolution, withdrawal, or a reclassification that clears the fraud flag.

State alignment propagates in the other direction as well. A dispute's lifecycle drags its underlying Card Transaction through `POSTED`, `DISPUTED`, `CHARGED_BACK`, `RE_PRESENTED`, and `SETTLED`; a chargeback's lifecycle drags the case and the transaction along with it; a credit's reversal or reinstatement flips the case between its resolved outcomes. The server performs these reconciliations automatically when criteria are met, without requiring an explicit client request on the affected resource. Each such cascade that mutates a resource refreshes its `updated_at` and increments its `version`, so a client holding a stale view of a cascaded entity is detectably out of date.

### 2.10. Segregation of Duties

The dispute pipeline separates intake from judgment. When a case was filed by an `IntakeAgent` — recorded as a non-null `intake_agent_id` — the `DisputeInvestigator` who resolves that case must present an `X-User-ID` different from the intake agent's. A resolution attempted by the same operator identity is rejected with `ERR_SOD_VIOLATION` (HTTP 403). When the cardholder filed the case directly, `intake_agent_id` is null and no segregation check applies. The check sits above the temporal gates in the validation ladder: a same-operator resolution is refused as `ERR_SOD_VIOLATION` even if a deadline problem also exists.

## 3. Business Logic & Workflows

### 3.1. Account Seeding and Transaction Posting

Before any dispute can exist, a `BankAdmin` opens card accounts and seeds their posted transactions. Opening an account requires the `cardholder_name` and accepts an optional `initial_balance_cents` that defaults to 0; the new account's `balance_cents` starts at that opening figure, its `status` starts at `ACTIVE`, and its `opened_at` is stamped with the logical clock time at creation. That `opened_at` value matters far beyond record-keeping: it anchors the new-account rule used throughout the regulation logic, under which an account is treated as new when the disputed transaction's `posted_at` falls no later than thirty days after the account's `opened_at` (the boundary is inclusive, and a `posted_at` earlier than `opened_at` also satisfies the rule).

Seeding a transaction requires the owning account's `card_account_id`, plus `merchant_name`, `amount_cents` (strictly greater than zero), `transaction_type` (one of `POS_PIN`, `POS_SIGNATURE`, `ATM_WITHDRAWAL`, `ECOMMERCE`, or `RECURRING`), `network` (`VISA` or `MASTERCARD`), and a client-supplied `posted_at` so historical transactions can be backdated (a `posted_at` that does not parse as an ISO 8601 timestamp is rejected with `ERR_INVALID_REQUEST`, and the stored value is normalized to UTC). A freshly seeded transaction is `POSTED`. Because posting against a fraud-restricted account is prohibited, this operation fails with `ERR_ACCOUNT_RESTRICTED` whenever the owning account is `RESTRICTED`.

Anyone of the six roles may read a single account back; the response exposes the ledger `balance_cents` and the derived `provisional_outstanding_cents`, which is the sum of `amount_cents` over that account's Provisional Credits currently in `GRANTED` or `REINSTATED`. An account's transactions can be listed through the account's transaction collection, subject to standard pagination.

### 3.2. Dispute Intake and the Provisional Credit Clock

A dispute enters the system when a `Cardholder` (for their own account only) or an `IntakeAgent` files one against a posted transaction, supplying the `card_transaction_id`, an `error_type` of `UNAUTHORIZED`, `INCORRECT_AMOUNT`, `DUPLICATE_CHARGE`, `SERVICE_NOT_RECEIVED`, or `CANCELLED_RECURRING`, the `claim_amount_cents` being claimed, and the `claimed_report_delay_days` — the cardholder's own statement of how many calendar days elapsed between the transaction posting and their report. The intake checks, in validation-ladder order, that the request body is well formed (so a claim amount of zero or less fails as `ERR_INVALID_REQUEST`), that the transaction exists, that a cardholder caller owns the account behind it, that the transaction is in a disputable state, and only then that the claim fits the transaction. A transaction may carry at most one open dispute: if any earlier case for it still sits in `RECEIVED`, `CLASSIFIED`, `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING`, intake is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE`; if the transaction is otherwise not `POSTED`, the refusal is `ERR_INVALID_STATE`. A claim exceeding the transaction's `amount_cents` is rejected with `ERR_CLAIM_EXCEEDS_TRANSACTION`.

A successful intake creates the Dispute Case in `RECEIVED` and flips the transaction from `POSTED` to `DISPUTED`. The case copies the `card_account_id` from the transaction, records `received_at` as the logical clock time — every Regulation E deadline anchors here — and stamps `intake_agent_id` with the caller's `X-User-ID` when an `IntakeAgent` filed, or null when a `Cardholder` did. Two computed fields appear immediately. The `provisional_credit_due_at` is ten business days after `received_at`, extended to twenty business days when the account is new under the thirty-day rule, landing at 23:59:59Z on that business day, inclusive. The `provisional_holdback_cents` is the cardholder-borne portion withheld from any provisional credit, computed from the *claimed* delay tier: for a claim treated as fraud, a reported delay of at most two days caps the cardholder's exposure at 5,000 cents, a delay of at most sixty days caps it at 50,000 cents, and a delay beyond sixty days leaves the cardholder exposed to the full claim; the holdback is then the smaller of that cap and the `claim_amount_cents`. Until an investigator classifies the case, the fraud question is provisionally answered by the `error_type`: `UNAUTHORIZED` is treated as fraud, everything else as non-fraud (holdback zero). The remaining computed fields start empty at intake: `is_fraud_claim`, `verified_report_delay_days`, `investigation_window_days`, `investigation_deadline_at`, and `final_liability_cents` are null, and `cardholder_keeps_cents` and `outstanding_loss_cents` are zero.

### 3.3. Fraud Classification, Liability Tiers, and the Investigation Window

Classification is the `DisputeInvestigator`'s first act and moves a case from `RECEIVED` to `CLASSIFIED`. The investigator supplies `is_fraud_claim` and a `verified_report_delay_days` — their own evidence-based determination of the report delay, which may diverge from the cardholder's claim. Classification fixes the fraud flag, recomputes the `provisional_holdback_cents` under that flag (still from the claimed delay, since the provisional tier is what funds any credit), stores the verified delay to drive the final liability tier at resolution, and computes the investigation window. The window — recorded as `investigation_window_days` — is ninety calendar days when the claim is fraud, when the transaction was a `POS_PIN` or `POS_SIGNATURE` purchase, or when the account is new under the thirty-day rule; it is forty-five calendar days otherwise. The `investigation_deadline_at` falls that many calendar days after `received_at`, at 23:59:59Z inclusive. Classification also increments the case's `version` by one. If the claim is fraud, the account cascade of §2.9 fires: the owning Card Account moves `ACTIVE` → `RESTRICTED`.

Reclassification keeps the case in `CLASSIFIED` — a deliberate self-loop for refining the determination. It takes the same `is_fraud_claim` and `verified_report_delay_days`, plus the OCC field `expected_dispute_version` described in §2.7; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful reclassification recomputes the fraud flag, the verified delay, the investigation window and its deadline, and the provisional holdback, and it increments the case's `version` by one. Flipping the fraud flag to true restricts the account; flipping it to false restores the account to `ACTIVE` provided no other open fraud case still references it.

### 3.4. Provisional Credit Grant and Investigation Resolution

Once a case is `CLASSIFIED`, an `IntakeAgent` may grant the provisional credit. A case carries at most one open credit: if a Provisional Credit in `GRANTED` or `REINSTATED` already exists for the case, the grant is rejected with `ERR_INVALID_STATE`. The granted `amount_cents` is the `claim_amount_cents` minus the `provisional_holdback_cents`, floored at zero, and the new credit carries `final_amount_cents` and `reversed_at` as null. The credit records `granted_at` from the logical clock and computes `granted_late` — true when the grant happens after the case's `provisional_credit_due_at`, a compliance fact retained on the record. The grant credits the account's `balance_cents` by the granted amount, raises `provisional_outstanding_cents` by the same amount, and generates a `PROVISIONAL_CREDIT_ADVICE` Notification to the cardholder.

Resolution is the `DisputeInvestigator`'s judgment call, submitted with an `outcome`, and it always increments the case's `version` by one. Two compliance gates guard it. First, the segregation-of-duties rule of §2.10: the resolver's `X-User-ID` must differ from the case's `intake_agent_id` when one is recorded, or the attempt fails with `ERR_SOD_VIOLATION`. Second, the provisional-credit compliance rule: once the logical clock has passed `provisional_credit_due_at`, a case may not be resolved if no credit ever reached `GRANTED`, `REINSTATED`, or `FINALIZED` — such an attempt is rejected with `ERR_PROVISIONAL_CREDIT_REQUIRED`.

When the outcome is `ERROR_CONFIRMED`, the bank concedes the cardholder's error claim. The final cardholder-borne liability, `final_liability_cents`, is taken from the liability tier engine using the *verified* delay: zero for a non-fraud claim; for fraud, the 5,000-cent cap at a verified delay of at most two days, the 50,000-cent cap at a verified delay of at most sixty days, and the full claim beyond sixty days, in each tier capped at the `claim_amount_cents`. The final credit owed to the cardholder, F, is the `claim_amount_cents` minus `final_liability_cents`, and the system enforces claim conservation: `cardholder_keeps_cents` plus `final_liability_cents` always equals `claim_amount_cents`. If a credit is open, it is trued up — the account `balance_cents` is adjusted by the difference between F and the credit's current `amount_cents`, the credit moves to `FINALIZED` with `final_amount_cents` set to F, and its former amount leaves `provisional_outstanding_cents`. If no credit was ever granted, the system creates a Provisional Credit directly in `FINALIZED` — with `amount_cents` and `final_amount_cents` both equal to F, `granted_at` stamped at resolution time, `granted_late` false, and `reversed_at` null — and credits the account's `balance_cents` by F. A `LOSS_RECOGNIZED` ledger entry of F is auto-created when F is greater than zero, `cardholder_keeps_cents` is set to F, a `RESOLUTION_LETTER` Notification is issued, the transaction settles, and the account restriction lifts if no other fraud case remains open. The case lands in `RESOLVED_CARDHOLDER_FAVOR`.

When the outcome is `NO_ERROR`, the investigation found the transaction valid. This path is only available while the logical clock is at or before `investigation_deadline_at` (inclusive at end of day); a late `NO_ERROR` is rejected with `ERR_INVESTIGATION_WINDOW_EXPIRED`. What happens next depends on whether money is out the door. If a Provisional Credit is open (`GRANTED` or `REINSTATED`), the case moves to `REVERSAL_PENDING` and a `REVERSAL_NOTICE` Notification is generated with `sent_at` stamped at the logical clock — the bank must now give the cardholder the statutory notice period before pulling the funds back. If no credit is open, the case resolves directly to `RESOLVED_MERCHANT_FAVOR` with a `RESOLUTION_LETTER`, and the transaction settles.

### 3.5. Chargeback Filing: Reason Codes, Network Deadlines, and Fees

A `ChargebackAnalyst` pursues the merchant through the card network by filing a chargeback against a `CLASSIFIED` case, supplying the `dispute_case_id`, a `reason_code`, and optionally an `amount_cents` that defaults to the case's `claim_amount_cents` when omitted — an explicitly supplied `amount_cents` need only be a positive integer and is not bounded by the claim or the transaction amount. The chargeback copies the `card_transaction_id` and the `network` from the underlying transaction, and records the derived `network_filing_deadline_at` and `response_window_end_at` on itself. Filing enforces three gates after the state check that the case is `CLASSIFIED`. The network filing deadline comes first: filing must occur at or before `network_filing_deadline_at`, which is the transaction's `posted_at` plus 120 calendar days for `VISA` or 90 calendar days for `MASTERCARD`, end-of-day inclusive; a late filing is rejected with `ERR_NETWORK_DEADLINE_PASSED`. Next, window occupancy: each chargeback occupies its transaction for the half-open interval from its `filed_at` up to but not including its `response_window_end_at`, the thirty-day merchant response window ending at 23:59:59Z — occupancy is purely interval-based and does not depend on the chargeback's status, so a `CANCELLED`, `WITHDRAWN`, or otherwise closed chargeback's window blocks exactly as an open one's does until the interval expires; if any other chargeback on the same transaction currently occupies its window, filing is rejected with `ERR_NETWORK_WINDOW_ACTIVE`. Finally, reason-code compatibility: fraud claims take `V10_4` or `V10_5` on `VISA` and `M4837` or `M4870` on `MASTERCARD`, while non-fraud claims take `V13_1` or `V13_3` on `VISA` and `M4853` or `M4855` on `MASTERCARD`; any other recognized-code combination is rejected with `ERR_REASON_CODE_MISMATCH`, while a `reason_code` outside the eight recognized codes fails earlier, at schema validation, with `ERR_INVALID_REQUEST`.

A successfully filed chargeback starts in `FILED` with `filed_at` stamped from the logical clock, `stage_entered` at `NONE`, `outcome` null while open, and a filing fee of 2,500 cents already accrued in `fees_total_cents`. Filing cascades outward: the case moves `CLASSIFIED` → `CHARGEBACK_FILED` and the transaction moves `DISPUTED` → `CHARGED_BACK`. Individual chargebacks can be read back with their fees and stage; chargebacks can be listed with `card_transaction_id` and `status` filters, or per case through the case's chargeback collection.

### 3.6. Representment Review, Second Presentment, and Escalation

The merchant answers a `FILED` chargeback through a representment, which the `ChargebackAnalyst` registers with a `merchant_ref` and an `evidence_documents` list. The list must contain at least one entry, each a `doc_type` paired with a `reference`; an empty array is rejected with `ERR_EVIDENCE_REQUIRED`. Registration creates the Representment in `PENDING_REVIEW`, linked to the contested chargeback through its `chargeback_id` and with `received_at` from the logical clock; it moves the chargeback `FILED` → `REPRESENTED`, the case `CHARGEBACK_FILED` → `REPRESENTMENT_REVIEW`, and the transaction `CHARGED_BACK` → `RE_PRESENTED`. The representments registered against a chargeback can be listed at any time.

Reviewing the representment is a binary `decision`. A `REJECT` decision — the issuer stands by its chargeback and issues a second presentment — moves the Representment to `REJECTED`, the chargeback `REPRESENTED` → `SECOND_PRESENTED`, the transaction `RE_PRESENTED` → `CHARGED_BACK`, and the case `REPRESENTMENT_REVIEW` → `CHARGEBACK_FILED`. An `ACCEPT` decision concedes: the Representment becomes `ACCEPTED`, the chargeback closes as `CLOSED_LOST` with `outcome` set to `LOST`, and the case forks on whether a credit is open. With an open credit the case moves to `REVERSAL_PENDING` and a `REVERSAL_NOTICE` goes out; with no open credit it moves straight to `RESOLVED_MERCHANT_FAVOR` with a `RESOLUTION_LETTER` and the transaction settles. Either way, an automatic `LOSS_RECOGNIZED` ledger entry records the chargeback's `fees_total_cents` plus any finalized credit principal the issuer bears — zero when no credit has been finalized.

From `SECOND_PRESENTED`, escalation is the terminal gamble: the analyst submits a `stage` and an `outcome`. Winning requires having chosen a recognized escalation stage, `PRE_COMPLIANCE` or `ARBITRATION`. Each entered stage accrues its own fee on top of the filing fee, computed per §2.6's pinned rounding: the pre-compliance stage fee is 10,000 cents plus 0.8 percent of the chargeback `amount_cents`, rounded half-up to whole cents; the arbitration stage fee is 25,000 cents plus 1.5 percent of the `amount_cents`, likewise rounded half-up on its own. The stage fee actually entered is then added into `fees_total_cents`, and `stage_entered` records which variant was chosen; arbitration is the more expensive path, so an identical `amount_cents` always yields a strictly larger total at arbitration than at pre-compliance. An escalation `outcome` of `WON` closes the chargeback `CLOSED_WON`: the final credit F (claim minus final liability) finalizes any open credit with `final_amount_cents` set to F and a balance true-up (creating the credit directly in `FINALIZED`, as in §3.4, when none is open), a `LOSS_RECOGNIZED` entry of F plus `fees_total_cents` is auto-created when that sum is positive, a `RECOVERY_RECEIVED` entry of the chargeback's `amount_cents` books the network recovery, and the case resolves `RESOLVED_CARDHOLDER_FAVOR` with the `RESOLUTION_LETTER`, a settled transaction, and any account restriction lifted. An `outcome` of `LOST` closes the chargeback `CLOSED_LOST` with `outcome` recorded as `LOST`: the stage fee stays accrued, the automatic loss entry is `fees_total_cents` plus any finalized principal, and the case forks to `REVERSAL_PENDING` or `RESOLVED_MERCHANT_FAVOR` exactly as in the accept path. Escalating with `outcome` `WITHDRAWN` closes the chargeback as `WITHDRAWN` — withdrawal at arbitration concedes the case, so the loss cascade is identical to `LOST`.

A chargeback still in `FILED` can instead be withdrawn outright. Withdrawal closes it as `CANCELLED` with `outcome` left null, returns the case `CHARGEBACK_FILED` → `CLASSIFIED`, and returns the transaction `CHARGED_BACK` → `DISPUTED`; the filing fee remains accrued on the `CANCELLED` record. The case is then eligible for a fresh filing — permitted once the cancelled chargeback's response window no longer occupies the timeline, and still subject to the network filing deadline.

### 3.7. Reversal, Reinstatement, and Cardholder Withdrawal

Pulling provisional funds back is a finance function with a statutory cooling period. A `FinanceOfficer` may reverse a Provisional Credit in `GRANTED` or `REINSTATED` only while its case sits in `REVERSAL_PENDING`, and only when a `REVERSAL_NOTICE` exists for the case whose `sent_at` is at least three business days in the past, counted by calendar date — the count covers Monday–Friday dates from the day after the notice's sent date through the current date inclusive and must reach three; reversing earlier is rejected with `ERR_REVERSAL_NOTICE_PENDING`. The reversal debits the account's `balance_cents` by the credit's `amount_cents`, reduces `provisional_outstanding_cents` by the same, stamps `reversed_at` from the clock, and moves the credit to `REVERSED`. Completion of the reversal cascades the case `REVERSAL_PENDING` → `RESOLVED_MERCHANT_FAVOR`, issues the `RESOLUTION_LETTER`, settles the transaction, and restores the account to `ACTIVE` when no other fraud case remains open.

An erroneous reversal can be corrected. When the case is `RESOLVED_MERCHANT_FAVOR` and the credit is `REVERSED`, a `FinanceOfficer` may reinstate it: the account's `balance_cents` and `provisional_outstanding_cents` each increase by the credit's `amount_cents`, the credit moves to `REINSTATED`, and the case flips `RESOLVED_MERCHANT_FAVOR` → `RESOLVED_CARDHOLDER_FAVOR` — because the issuer now bears the principal, an automatic `LOSS_RECOGNIZED` entry equal to the reinstated `amount_cents` is booked, and a fresh `RESOLUTION_LETTER` is issued. A reinstated credit remains subject to the same lifecycle as a granted one: it can be reversed again under the same case-state and notice-cooling rules, or finalized with the same true-up semantics if the re-opened investigation later confirms the error or the chargeback is won.

The cardholder retains the right to walk away. A `Cardholder` (own cases only — withdrawing someone else's case fails ownership with `ERR_FORBIDDEN`) or an `IntakeAgent` may withdraw a case from `RECEIVED` or `CLASSIFIED`, landing it in `WITHDRAWN` and incrementing the case's `version` by one. Withdrawal from `CLASSIFIED` while a credit is open auto-reverses that credit immediately: the account's `balance_cents` and `provisional_outstanding_cents` drop by the credit amount and the credit becomes `REVERSED` — a cardholder-initiated withdrawal waives the three-business-day notice, so no cooling period applies. In both withdrawal paths the transaction moves to `SETTLED`, and the account restriction lifts when no other fraud case remains.

### 3.8. Loss Recognition, Recovery, and the Case Ledger

Every case carries a loss ledger, and its `outstanding_loss_cents` is the running balance: the sum of all `LOSS_RECOGNIZED` entry amounts minus the sum of all `RECOVERY_RECEIVED` entry amounts. Ledger entries arrive from two sources, recorded on each entry's `source` field. `AUTO` entries are cascade-created by the transitions described above — fee-and-principal loss at chargeback closure or concession (fees accounted first, then principal, within the combined entry), principal loss at an error-confirmed resolution or a reinstatement, and the network recovery at a won chargeback. `MANUAL` entries are posted by a `FinanceOfficer` through the case's loss-recovery collection, supplying the entry `type`, an `amount_cents` strictly greater than zero, and an optional `memo` (null on the stored entry when omitted, as it always is on `AUTO` entries).

Manual entries observe two rules. A manual `RECOVERY_RECEIVED` may not exceed the case's current `outstanding_loss_cents` — an amount exactly equal to the outstanding balance is permitted, but anything larger is rejected with `ERR_LOSS_EXCEEDS_OUTSTANDING`. A manual `LOSS_RECOGNIZED` requires the case to already sit in a resolved status (`RESOLVED_CARDHOLDER_FAVOR` or `RESOLVED_MERCHANT_FAVOR`). Posting either entry recomputes `outstanding_loss_cents`; the recomputation is a derived-balance refresh and does not by itself increment the case's `version` or refresh its `updated_at`. The full ledger for a case can be listed with an optional `type` filter and standard pagination; a case's notification letters can likewise be listed with a `type` filter spanning `PROVISIONAL_CREDIT_ADVICE`, `REVERSAL_NOTICE`, and `RESOLUTION_LETTER`, where every letter's `sent_at` is its creation time on the logical clock and its `detail` carries a human-readable summary of the body. The case's Provisional Credits can be listed as well — at most one is open at a time under the one-open-credit rule, with closed history retained. Individual cases can be read back with all computed deadline and liability fields, and the case collection can be listed with `card_account_id`, `card_transaction_id`, and `status` filters — for a `Cardholder` caller the collection is implicitly scoped to their own account, and explicitly passing another account's id as `card_account_id` is rejected with `ERR_FORBIDDEN`.

## 4. Endpoint Definitions

Operations that create a new resource — opening an account, seeding a transaction, filing a dispute, granting a credit, filing a chargeback, registering a representment, posting a ledger entry — return `201 Created`. Operations that act on an existing resource without creating a new one — classification, reclassification, resolution, withdrawal, representment review, escalation, chargeback withdrawal, credit reversal or reinstatement, setting the clock — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/card-accounts` | Open a card account (opened_at = logical clock at creation) | BankAdmin |
| GET | `/card-accounts/{id}` | Read one card account with derived balances | BankAdmin, Cardholder, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| GET | `/card-accounts/{id}/transactions` | List transactions posted to an account | BankAdmin, Cardholder, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/card-transactions` | Seed a posted card transaction (posted_at supplied for backdating) | BankAdmin |
| POST | `/disputes` | Dispute intake; computes received_at, provisional credit deadline, and provisional holdback | Cardholder, IntakeAgent |
| GET | `/disputes/{id}` | Read one dispute case with computed deadline and liability fields | BankAdmin, Cardholder, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| GET | `/disputes` | List/filter dispute cases | BankAdmin, Cardholder, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/disputes/{id}/classify` | Classify fraud vs non-fraud; sets verified delay and investigation window; fraud restricts the account | DisputeInvestigator |
| POST | `/disputes/{id}/reclassify` | Re-classify under optimistic concurrency; CLASSIFIED self-loop with version check | DisputeInvestigator |
| POST | `/disputes/{id}/grant-provisional-credit` | Grant provisional credit = claim − provisional holdback; creates the credit advice letter | IntakeAgent |
| POST | `/disputes/{id}/resolve` | Resolve investigation: ERROR_CONFIRMED finalizes credit with true-up; NO_ERROR starts the reversal flow | DisputeInvestigator |
| POST | `/disputes/{id}/withdraw` | Cardholder withdrawal from RECEIVED/CLASSIFIED; auto-reverses open credit without the notice wait | Cardholder, IntakeAgent |
| POST | `/chargebacks` | File a network chargeback for a CLASSIFIED case; reason code and deadline enforced | ChargebackAnalyst |
| GET | `/chargebacks/{id}` | Read one chargeback including fees and stage | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| GET | `/chargebacks` | List/filter chargebacks by transaction or status | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| GET | `/disputes/{id}/chargebacks` | List chargebacks filed for a case | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/chargebacks/{id}/representments` | Register a merchant representment with evidence (chargeback must be FILED) | ChargebackAnalyst |
| GET | `/chargebacks/{id}/representments` | List representments registered against a chargeback | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/chargebacks/{id}/review-representment` | ACCEPT closes lost (issuer concedes); REJECT issues second presentment | ChargebackAnalyst |
| POST | `/chargebacks/{id}/escalate` | From SECOND_PRESENTED: choose PRE_COMPLIANCE or ARBITRATION with terminal outcome; accrues the stage fee | ChargebackAnalyst |
| POST | `/chargebacks/{id}/withdraw` | Cancel a FILED chargeback; returns the case to CLASSIFIED for possible refile | ChargebackAnalyst |
| POST | `/provisional-credits/{id}/reverse` | Reversal after the 3-business-day REVERSAL_NOTICE cooling; cascades the case to RESOLVED_MERCHANT_FAVOR | FinanceOfficer |
| POST | `/provisional-credits/{id}/reinstate` | Reinstate an erroneously reversed credit; case flips to RESOLVED_CARDHOLDER_FAVOR with a loss auto-entry | FinanceOfficer |
| GET | `/disputes/{id}/provisional-credits` | List provisional credits for a case (at most one open; history retained) | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| GET | `/disputes/{id}/notifications` | List notification letters generated for a case | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/disputes/{id}/loss-recoveries` | Manual loss recognition or recovery entry against a RESOLVED_* case | FinanceOfficer |
| GET | `/disputes/{id}/loss-recoveries` | List loss/recovery ledger entries for a case | BankAdmin, IntakeAgent, DisputeInvestigator, ChargebackAnalyst, FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z; never falls back to wall-clock time) | BankAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_DISPUTE` | 409 Conflict |
| `ERR_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PROVISIONAL_CREDIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVESTIGATION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NETWORK_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_REVERSAL_NOTICE_PENDING` | 422 Unprocessable Entity |
| `ERR_NETWORK_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_REASON_CODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_TRANSACTION` | 422 Unprocessable Entity |
| `ERR_LOSS_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |

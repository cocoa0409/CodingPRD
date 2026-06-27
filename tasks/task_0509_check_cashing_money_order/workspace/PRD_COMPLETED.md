# Check Cashing & Money Services API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Check Cashing & Money Services API, the transactional backbone of a retail financial-services storefront in the mold of a high-street check-cashing and money-transfer outlet. A single counter in such a store must, within seconds, decide whether a presented check is safe to cash, price the service against the customer's risk profile, screen the customer against sanctions and identity rules, hand out cash from a physical drawer, and issue money orders, wires, bill payments, and prepaid-card loads — all while staying inside per-customer daily limits and producing a drawer that balances at the end of the day.

The system exists to make these decisions defensible and auditable. Every dollar that leaves or enters the drawer is tied to a posted transaction; every risk-held check is resolved by a supervisor who is provably not the clerk who took it in; every returned check spawns a recovery obligation that is chased until it is collected or written off. The two organizing concerns are therefore **compliance** (knowing the customer, blocking the sanctioned, holding the suspicious) and **reconciliation** (the cash drawer must explain itself to the penny at close). The remainder of this document defines the global contracts that every endpoint obeys, the cross-cutting financial and safety principles, and the detailed business workflows that connect customers, drawers, transactions, instruments, and recovery.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. The API is mounted at the server root; all paths in this document are absolute from that root.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers identifying the operator: `X-User-ID`, an identifier for the acting individual, and `X-User-Role`, the operator's role. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED`. When a request is authenticated but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly two roles, spelled exactly as follows: `Teller` and `StoreManager`. A `Teller` is the front-line clerk who registers customers, posts ordinary transactions, and collects recovery payments. A `StoreManager` is the branch supervisor who runs compliance screens, manages fee schedules and cash drawers, releases or rejects risk-held checks, voids and returns transactions, writes off bad debt, and advances the logical clock.

Both roles use an opaque identity. When `X-User-Role` is `Teller`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow demands it — notably, the `X-User-ID` of the operator who creates a transaction is captured as that transaction's creating Teller for later segregation-of-duties checks — but it never compares it to any entity's `id`. Likewise, when `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server reads it to enforce that the manager resolving a risk-held check or voiding a transaction is not the same operator who created it, but it is never matched against an entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — an out-of-range value is silently clamped into that range (a `limit` below 1 becomes 1, above 100 becomes 100) rather than rejected. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0; a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`.

Unless an endpoint explicitly states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Versioning

Most resources in the system carry a standard set of server-managed fields. Each such resource has an `id` formatted as a UUID with no type prefix, a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when the resource was first created, an `updated_at` timestamp (same format) refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on every mutation. These entity `created_at` and `updated_at` timestamps are stamped from the server's logical clock (§3.8), not wall-clock time, so they reflect whatever instant the logical clock currently holds; this is distinct from the envelope's `api_request_timestamp` (§2.2), which is wall-clock. These common fields apply to `Customer`, `FeeSchedule`, `CashDrawer`, `Transaction`, `CheckItem`, `MoneyOrder`, `WireTransfer`, `BillPayment`, `PrepaidCardLoad`, and `ReturnedItem`.

The `ComplianceScreen` resource is the one exception. A compliance screen is an immutable audit record: once written it is never modified. It therefore carries only an `id` (UUID) and a `created_at` timestamp — it has neither an `updated_at` field nor a `version` field.

Whenever the server mutates a resource — whether in direct response to a client request or as a downstream cascade from another operation — that resource's `updated_at` is refreshed and its `version` is incremented. A single client request may thus bump the version of several resources at once: for example, posting a check-cash transaction mutates the transaction, the customer, and the cash drawer, and each of those independently advances its own `version` and `updated_at`.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several read endpoints expose a resource's children by walking a foreign key in reverse — for instance, listing the compliance screens or returned items belonging to a customer, or the check item, money order, wire transfer, bill payment, or prepaid-card load tied to a transaction. For any request whose path names more than one resource, the server validates path identifiers left to right and rejects on the first one that does not resolve to an existing resource. A request for the check items of a non-existent transaction, for example, fails because the transaction segment cannot be resolved, before any child lookup is attempted.

More generally, every resource referenced by a request — whether named in the path or supplied in the body, and including `Customer`, `CashDrawer`, `FeeSchedule`, `Transaction`, `CheckItem`, and `ReturnedItem` — must exist. A reference to a resource that does not exist is rejected with `ERR_NOT_FOUND`. Existence is checked after authentication and authorization but before any state or business rule is evaluated.

### 2.6. Monetary Amounts and Calculation Precision

All monetary amounts in the system are integer cents; there are no fractional cents and no floating-point money. Fees, balances, drawer totals, and recovery amounts are stored and returned as whole integers.

Where a fee calculation multiplies an amount by a basis-point rate, the result of each percentage component is divided by 10000 using integer floor division (the fractional part is discarded, never rounded up). A critical precision rule applies to tiered check-cash fees: when a fee has both a low-tier and a high-tier percentage component, **each component is floor-divided independently before the two are summed** — the system rounds each leg down to whole cents first, then adds. This per-leg flooring can differ by up to one cent from flooring a single combined sum, and the per-leg order is the contract. Drawer aggregation and recovery waterfalls are exact integer sums with no rounding.

### 2.7. Segregation of Duties

The store operates under a segregation-of-duties discipline: the operator who originates a transaction may not be the operator who later approves, reverses, or otherwise passes judgment on it. Concretely, when a `StoreManager` releases a risk-held check, rejects a risk-held check, or voids a posted transaction, the manager's `X-User-ID` must differ from the `X-User-ID` recorded as the creating Teller of the underlying transaction. If they are the same operator, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. This check guards exactly three operations: check release, check rejection, and transaction void.

### 2.8. Compliance Gating: KYC and Sanctions

No transaction may post for a customer who has not cleared compliance. Before any posting, the customer's `kyc_status` must be `VERIFIED`; if it is anything else, the posting is rejected with `ERR_KYC_NOT_VERIFIED`. This gate applies both when a transaction is first created and when a risk-held check is released (which posts the held transaction).

A sanctions match is treated as an absolute, separate block. Because `OFAC_BLOCKED` is itself a non-`VERIFIED` status, it is caught by the KYC gate above wherever that gate applies: the relative ordering in §2.11 places the KYC gate before the sanctions block, so on any posting attempt and on any release of a risk-held check, an `OFAC_BLOCKED` customer fails the KYC gate first and is rejected with `ERR_KYC_NOT_VERIFIED` — the standalone `ERR_OFAC_BLOCKED` is never produced by the posting or release paths. The standalone sanctions block is reached only on the one path that has no KYC gate: an attempt to run another compliance screen for a customer whose `kyc_status` is already `OFAC_BLOCKED` is rejected with `ERR_OFAC_BLOCKED`. A sanctioned customer is thus hard-blocked from any further activity, but the specific error returned is `ERR_KYC_NOT_VERIFIED` on posting and release and `ERR_OFAC_BLOCKED` on re-screening.

### 2.9. The Cash Drawer as Ledger

The cash drawer is the single source of truth for the physical cash position of a branch on a given day. A drawer's `expected_cash_cents` is derived, never set directly: it is its opening float adjusted by the cash impact of every posted transaction flowing through it (see §3.5 for the exact sign convention and §3.7 for reconciliation). Whenever a posting, void, or release cascade touches a drawer, its expected cash is recomputed from scratch and its `version` is bumped — which is precisely why closing a drawer is concurrency-controlled, as described next.

### 2.10. Optimistic Concurrency Control on Drawer Close

Closing a cash drawer is guarded by optimistic concurrency control on the drawer's `version`. The close request must carry `expected_drawer_version`, a non-optional field whose value is the `version` of the `CashDrawer` the closing manager last observed when counting cash. If that value does not match the drawer's current `version` at the moment the close is processed, the request is rejected with `ERR_STALE_DRAWER_VERSION` (HTTP 412). The hazard this prevents is concrete: between the manager reading the drawer to count cash and submitting the close, a transaction void or a returned-item cascade may recompute `expected_cash_cents` and advance the drawer's `version`; closing against the stale view would lock in an expected balance that no longer reflects reality. No other endpoint takes a version field; OCC applies only to drawer close.

### 2.11. Resolution Order of Validations

When several checks could fail a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first the authentication header check (`ERR_UNAUTHENTICATED`); then the role-permission check (`ERR_FORBIDDEN_ROLE`); then existence of all referenced resources, validated left to right (`ERR_NOT_FOUND`); then whether the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`); then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); then the KYC gate (`ERR_KYC_NOT_VERIFIED`); then the sanctions block (`ERR_OFAC_BLOCKED`); then fee-schedule validity (`ERR_FEE_SCHEDULE_INVALID`); then drawer-open status (`ERR_DRAWER_NOT_OPEN`); then embargoed wire destination (`ERR_EMBARGOED_DESTINATION`); then the per-transaction risk ceiling (`ERR_RISK_CEILING_EXCEEDED`); then the daily transaction-count limit (`ERR_VELOCITY_LIMIT_EXCEEDED`); then the daily cash-amount limit (`ERR_DAILY_LIMIT_EXCEEDED`); then recovery overpayment (`ERR_RECOVERY_OVERPAYMENT`); then remaining-open-items on reconcile (`ERR_OPEN_ITEMS_REMAIN`); then drawer single-occupancy conflict (`ERR_DRAWER_CONFLICT`). A malformed body, a missing required field, or an out-of-domain value (for example a `face_amount_cents` below 1 or an unrecognized enum) is rejected with `ERR_VALIDATION`. Each rule below names the operations it guards; a rule that does not apply to a given endpoint is skipped, but the relative ordering among the rules that do apply is always as listed here.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Customer and Clearing Compliance

A customer record is the KYC subject around which all activity revolves. Either a `Teller` or a `StoreManager` registers a customer by supplying the customer's legal `full_name`, the `id_type` of the government identification presented — one of `DRIVERS_LICENSE`, `STATE_ID`, `PASSPORT`, or `MILITARY_ID` — the `id_number` on that document, and the `date_of_birth` as an ISO date in `YYYY-MM-DD` form, which is recorded as supplied (validated only as a present non-empty string; its calendar value is not parsed and no minimum-age check is enforced). A freshly registered customer begins with `kyc_status` of `PENDING`, a `risk_tier` of `STANDARD`, a `risk_score` of 0, an `outstanding_recovery_cents` of 0, and zeroed velocity counters (`daily_cashed_amount_cents` and `daily_transaction_count` both 0, with `limit_window_opened_at` unset until the first posting).

Clearing compliance is a `StoreManager`-only act. The manager runs a screen against a customer by supplying that customer's `customer_id` together with two vendor signals: `ofac_list_hit`, indicating whether the sanctions vendor returned a match, and `kyc_documents_valid`, indicating whether the presented identity documents passed verification. The screen's `outcome` is computed deterministically and written back to the customer's `kyc_status`: if `ofac_list_hit` is true the outcome is `OFAC_BLOCKED`; otherwise, if `kyc_documents_valid` is false the outcome is `REJECTED`; otherwise the outcome is `VERIFIED`. The possible `kyc_status` values are therefore `PENDING`, `VERIFIED`, `OFAC_BLOCKED`, and `REJECTED`. Because a sanctioned customer is hard-blocked, an attempt to screen a customer who is already `OFAC_BLOCKED` is itself refused with `ERR_OFAC_BLOCKED`. The compliance screen is stored as a permanent record and can be listed back per customer.

### 3.2. Pricing: Fee Schedules and Service Fees

Check-cashing prices live in fee schedules, which a `StoreManager` creates and maintains. A schedule prices one `check_type` — one of `PAYROLL`, `GOVERNMENT`, `PERSONAL`, `MONEY_ORDER_CHECK`, or `INSURANCE` — and carries a flat `base_fee_cents` floor applied regardless of the percentage, a `percent_rate_bps` percentage in basis points (for instance 200 basis points means 2.00%), a `tier_breakpoint_cents` face amount at or above which a marginal rate kicks in, a `high_percent_rate_bps` marginal rate in basis points applied only to the portion of the face above the breakpoint, a `max_fee_cents` ceiling on the total fee, and an `active` flag (defaulting to true) governing whether the schedule may be selected for new transactions.

The **check-cash fee** is computed at posting time whenever a transaction's `txn_type` is `CHECK_CASH`, using the transaction's selected fee schedule. Begin with the flat `base_fee_cents`. Then compute the percentage portion against the check's face amount. If the face amount is at or below the `tier_breakpoint_cents`, the percentage portion is the face amount multiplied by `percent_rate_bps`, divided by 10000 with integer floor division. If the face amount is above the breakpoint, the percentage portion is the sum of two legs computed separately: a low leg equal to the breakpoint multiplied by `percent_rate_bps` divided by 10000 (floored), plus a high leg equal to the excess of the face over the breakpoint multiplied by `high_percent_rate_bps` divided by 10000 (floored). Each leg is floored to whole cents on its own before the two are added — this per-leg flooring is the binding precision rule. The raw fee is the base plus the percentage portion; the final `fee_cents` is the smaller of that raw fee and the `max_fee_cents` ceiling. The check-cash fee is charged on the full check face and is never reduced by a later return.

For every other product the fee comes from fixed system constants rather than a fee schedule, and is computed at posting against the transaction's `face_amount_cents`. For a `MONEY_ORDER`, the fee is the smaller of (99 cents plus the face multiplied by 50 basis points divided by 10000, floored) and a 500-cent cap. For a `WIRE`, the fee is 1500 cents plus the face multiplied by 100 basis points divided by 10000 (floored), with no cap. For a `BILL_PAY`, the fee is a flat 195 cents independent of the face amount. For a `PREPAID_LOAD`, the fee is the greater of 395 cents and the face multiplied by 30 basis points divided by 10000 (floored). As with check-cash, each percentage leg is floored before being combined.

### 3.3. Opening and Operating a Cash Drawer

Before any cash can move, a `StoreManager` opens a cash drawer for a branch and a business day by supplying the `store_code`, the `business_date` as an ISO `YYYY-MM-DD` date, and the `opening_float_cents` counted into the drawer at open. A new drawer starts in status `OPEN` with `expected_cash_cents` equal to its opening float, `counted_cash_cents` unset (null) until reconciliation begins, and `variance_cents` initialized to 0 (it takes its meaningful signed value only at close). The drawer's lifecycle states are `OPEN`, `RECONCILING`, `CLOSED`, and `OVER_SHORT`.

Only one drawer may be open at a time for a given branch-and-day. Specifically, at most one `CashDrawer` may be in status `OPEN` for a given combination of `store_code` and `business_date`. Attempting to open a second drawer for the same `store_code` and `business_date` while one is already `OPEN` is rejected with `ERR_DRAWER_CONFLICT`. The conflict is on the exact pair only — there is no buffer and no aggregate capacity; once the existing drawer is no longer `OPEN`, a new one may be opened for that same key.

A drawer accepts new postings and voids only while it is `OPEN`. Any attempt to post a transaction, void a transaction, or release a risk-held check against a drawer that is `RECONCILING`, `CLOSED`, or `OVER_SHORT` is rejected with `ERR_DRAWER_NOT_OPEN`. Transactions posted to a drawer can be listed back, optionally filtered by `lifecycle_state`.

### 3.4. Posting a Transaction

A transaction is the unit of business activity, and any `Teller` or `StoreManager` may create one. The creator supplies the acting `customer_id`, the `drawer_id` the cash flows through, the `txn_type` — one of `CHECK_CASH`, `MONEY_ORDER`, `WIRE`, `BILL_PAY`, or `PREPAID_LOAD` — and the `face_amount_cents`, which is the check face for a check-cash and the send or load amount otherwise and must be at least 1. The operator's `X-User-ID` is recorded as the transaction's creating Teller for later segregation-of-duties enforcement. A transaction carries two independent state dimensions: a `lifecycle_state` that is one of `DRAFT`, `POSTED`, or `VOIDED` (starting at `DRAFT`), and a `settlement_state` that is one of `UNSETTLED`, `SETTLED`, `RETURNED`, or `RECOVERED` (starting at `UNSETTLED` and meaningful only once posted). On creation the server computes `fee_cents` per §3.2 and the `net_disbursed_cents` per §3.5.

A check-cash posting requires a `fee_schedule_id` referencing an `active` schedule; for any other `txn_type` the `fee_schedule_id` must be null. A missing or inactive schedule on a check-cash, or a non-null schedule on any other type, is rejected with `ERR_FEE_SCHEDULE_INVALID`. The remaining product-specific fields are described in §3.6, but the gating checks every posting must clear are these, applied in the order set out in §2.11: the customer must be `VERIFIED` and not `OFAC_BLOCKED`; the drawer must be `OPEN`; a wire's destination must not be embargoed; the face amount must sit within the customer's risk-tier ceiling; and the posting must not breach the daily velocity or cash limits (§3.8).

For a check-cash transaction, the server always creates an accompanying check item (§3.5). For every non-check-cash transaction that clears its gates, the transaction immediately moves to `lifecycle_state` `POSTED` and `settlement_state` `SETTLED`, the corresponding product child instrument is created (§3.6), the drawer's `expected_cash_cents` is recomputed, and the customer's velocity counters are advanced.

### 3.5. The Check Item: Verification, Risk Holds, and the Drawer

Every `CHECK_CASH` transaction is backed one-to-one by a check item, which carries the verification and risk-hold dimension. At creation the server copies the parent transaction's face into the check item's `check_face_cents` and records the vendor's `maker_account_risk` signal on the maker's account — one of `LOW`, `MEDIUM`, or `HIGH` — which is a required field on the CHECK_CASH posting body (a missing or out-of-enum value is rejected with `ERR_VALIDATION`). The check item's `verification_state` begins at `VERIFYING` and resolves to one of `CLEARED`, `RISK_HELD`, or `REJECTED`; `REJECTED` is terminal. While a check is held, its `hold_reason` records why; otherwise `hold_reason` is null.

At posting, the system decides whether the check clears or is held. A check is placed on hold — moving `VERIFYING → RISK_HELD` — if any of three conditions is met: the face amount is at least 300000 cents (that is, $3,000 or more), or the maker's account risk is `HIGH`, or the customer's daily transaction count has already reached 8 within the current window. The `hold_reason` is set to the first matching condition evaluated in that exact order: `AMOUNT_THRESHOLD` first, then `MAKER_RISK`, then `VELOCITY`. When a check is held, no cash moves: the parent transaction stays in `lifecycle_state` `DRAFT`, the drawer is untouched, and the hold-derived risk increment is **not** written to the customer's confirmed `risk_score` — it is neither stored on the customer nor surfaced as a field on the check item, and is computed only later from the held check's `maker_account_risk` and `hold_reason` (§3.8) if and when the hold is resolved, contributing nothing in the meantime. If none of the three hold conditions is met, the check clears automatically: it moves `VERIFYING → CLEARED`, the parent transaction moves to `POSTED` with `settlement_state` `SETTLED`, the customer's `daily_cashed_amount_cents` is increased by the check's face, and the drawer's expected cash is recomputed.

The drawer's expected cash is derived by aggregation over all transactions on that drawer whose `lifecycle_state` is `POSTED` (drafts and voided transactions are excluded). The sign convention rests on the `net_disbursed_cents` computed per transaction at posting. For a check-cash, cash leaves the drawer to the customer, so the net disbursed is the face minus the fee. For a money order, wire, bill payment, or prepaid load, cash comes in from the customer, so the net disbursed is the negative of the face plus the fee. Expected cash equals the opening float, minus the total of (face minus fee) across all posted check-cash transactions, plus the total of (face plus fee) across all posted non-check-cash transactions. This sum is exact, with no rounding.

### 3.6. Issuing Money Orders, Wires, Bill Payments, and Prepaid Loads

When a non-check-cash transaction posts, the system issues the matching product child instrument, each linked back to its originating transaction by `transaction_id` in a one-to-one relationship. Each child is created in its own initial status and can be listed back from its transaction.

A `MONEY_ORDER` posting requires a `payee_name` and produces a money order whose `serial_number` is a unique server-minted printed serial (unique across all money orders), whose `amount_cents` is copied from the parent transaction's face at issuance, and whose `status` begins at `ISSUED` (and may become `VOIDED`). A `WIRE` posting requires the `destination_country` as an ISO 3166 alpha-2 code and the `beneficiary_name`; the resulting wire transfer's `status` begins at `SENT` (and may become `RECALLED`). A wire whose `destination_country` is one of the embargoed set `CU`, `IR`, `KP`, or `SY` is rejected at posting with `ERR_EMBARGOED_DESTINATION`. A `BILL_PAY` posting requires the `biller_code` of the registered biller and the customer's `account_reference` with that biller; the bill payment's `status` begins at `SUBMITTED` (and may become `VOIDED`). A `PREPAID_LOAD` posting requires the `card_last_four` of the card being loaded; the prepaid-card load records a `loaded_amount_cents` copied from the parent transaction's face and a `status` beginning at `LOADED` (and may become `REVERSED`).

### 3.7. Resolving Held Checks, Voiding, and Drawer Reconciliation

A held check is resolved only by a `StoreManager`, and only when the check item is in `RISK_HELD`. Both resolution paths enforce segregation of duties: the resolving manager's `X-User-ID` must differ from the creating Teller's, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. **Releasing** a held check moves the check item `RISK_HELD → CLEARED`; this additionally requires the customer to be `VERIFIED` and the drawer to be `OPEN`. The customer's status is enforced by the KYC gate (§2.8): any non-`VERIFIED` status — including `OFAC_BLOCKED` — fails this gate and is rejected with `ERR_KYC_NOT_VERIFIED`, so the standalone `ERR_OFAC_BLOCKED` is not produced on release. A non-open drawer is rejected with `ERR_DRAWER_NOT_OPEN`. On release, the parent transaction moves to `lifecycle_state` `POSTED` with `settlement_state` `SETTLED`, the customer's `daily_cashed_amount_cents` is increased by the check's face, the drawer's expected cash is recomputed, and the hold-derived risk delta is confirmed onto the customer's `risk_score` (§3.8). **Rejecting** a held check moves the check item `RISK_HELD → REJECTED`; the parent transaction moves to `lifecycle_state` `VOIDED` while its settlement stays `UNSETTLED`, no cash moves, the drawer is untouched, and the same hold-derived risk delta is confirmed onto the customer's `risk_score`.

A `StoreManager` may **void** a transaction that is in `lifecycle_state` `POSTED`, provided its `settlement_state` is not `RETURNED` or `RECOVERED` and the drawer is still `OPEN`; an attempt against any other lifecycle state is rejected with `ERR_INVALID_STATE`, and a non-open drawer with `ERR_DRAWER_NOT_OPEN`. Voiding moves the transaction to `lifecycle_state` `VOIDED`, sets the product child to its voided form (`VOIDED` for a money order or bill payment, `RECALLED` for a wire, `REVERSED` for a prepaid load), recomputes the drawer's expected cash by reversing the original net impact, and decrements the customer's `daily_transaction_count` by one and, for a check-cash, the customer's `daily_cashed_amount_cents` by the face as compensation for the original posting. This compensating decrement is applied unconditionally against the current counter values: it does not roll or consult the velocity window and is not floored, so a void can drive either counter below 0 if the window has since rolled.

Day-end reconciliation runs in two steps. First, a `StoreManager` begins reconciliation, moving the drawer `OPEN → RECONCILING`; this is permitted only when the drawer is `OPEN` and no transaction on the drawer remains in `lifecycle_state` `DRAFT` (that is, no risk-held check is still unresolved). A begin-reconcile against a drawer that is not `OPEN` is rejected with `ERR_INVALID_STATE` (this state check precedes the open-items check). If the drawer is `OPEN` but a draft remains, the request is rejected with `ERR_OPEN_ITEMS_REMAIN`. Beginning reconciliation freezes `expected_cash_cents` at its current value and accepts no further postings. Second, the manager closes the drawer by supplying the physically `counted_cash_cents` (which must be present and at least 0) together with `expected_drawer_version` for the OCC check (§2.10). Closing is permitted only from `RECONCILING`; a close against a drawer in any other state is rejected with `ERR_INVALID_STATE`, and this state check is evaluated before the OCC version comparison (so a stale version on a non-`RECONCILING` drawer still surfaces `ERR_INVALID_STATE`, not `ERR_STALE_DRAWER_VERSION`). The drawer's `variance_cents` is set to the counted cash minus the expected cash (signed). If the variance is exactly 0 the drawer moves `RECONCILING → CLOSED`; if the variance is non-zero it moves `RECONCILING → OVER_SHORT`. Either way the drawer's `version` is incremented by one. Both `CLOSED` and `OVER_SHORT` are terminal drawer states.

### 3.8. Risk Scoring, Per-Transaction Ceilings, and the Rolling Velocity Window

A customer's confirmed `risk_score` accumulates across the customer's lifetime and starts at 0, clamped to the range 0 through 1000. Several events add points. When a held check is resolved (released or rejected), the hold-derived delta is confirmed: 120 points if the held check's maker account risk was `HIGH`, plus 60 points if the hold reason was `AMOUNT_THRESHOLD`, plus 90 points if the hold reason was `VELOCITY`. When a posted, settled check-cash transaction is returned, 250 points are added. When a returned item is written off, 200 points are added. After any addition, the new score is the old score plus the delta, clamped so it never drops below 0 nor rises above 1000.

The `risk_tier` is derived from the confirmed score: it is `STANDARD` while the score is below 350, `ELEVATED` while the score is at least 350 and below 700, and `HIGH` once the score is at least 700. Note the provisional figure described in §3.5 is never written to `risk_score`; only the confirmed deltas listed here move it, and a tier change takes effect as soon as a confirmed delta crosses a boundary.

The tier gates how large a single transaction the customer may run. A posting's `face_amount_cents` must not exceed the customer's per-transaction ceiling: 500000 cents for `STANDARD`, 200000 cents for `ELEVATED`, and 50000 cents for `HIGH`. A face amount above the applicable ceiling is rejected with `ERR_RISK_CEILING_EXCEEDED`.

Beyond the per-transaction ceiling, every customer is subject to a rolling 24-hour limit window, evaluated against the server's logical clock on every posting attempt. The window is the half-open interval beginning at `limit_window_opened_at` and ending 24 hours later. When a posting is attempted, the system first checks the window: if `limit_window_opened_at` is unset, or if the current clock time is at or after `limit_window_opened_at` plus 24 hours, the window rolls — `limit_window_opened_at` is reset to the current time and both `daily_transaction_count` and `daily_cashed_amount_cents` are reset to 0. The boundary is half-open: a posting whose clock time falls exactly at the 24-hour mark rolls the window (it is treated as the start of a fresh window, not the tail of the prior one); a posting strictly inside the interval accumulates against the existing window.

After any rollover, the caps are enforced including the posting under evaluation. The projected transaction count is the current `daily_transaction_count` plus 1; if that projected count would exceed the daily transaction limit of 12, the posting is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED`. The projected cashed amount is the current `daily_cashed_amount_cents` plus the face amount for a check-cash posting (non-check-cash postings add nothing to the cashed amount); if that projected cashed amount would exceed the daily cash limit of 1000000 cents, a check-cash posting is rejected with `ERR_DAILY_LIMIT_EXCEEDED`. On a successful posting the counters take their projected values, with only check-cash face amounts contributing to `daily_cashed_amount_cents`. Separately, recall from §3.5 that a daily transaction count already at 8 or more at posting time forces a check-cash check into a velocity-reason hold rather than auto-clearing.

The logical clock that drives this window is settable for testing: a `StoreManager` may advance it by supplying a target instant as `to_iso8601`. The clock's startup default is `2026-05-01T00:00:00Z`, and the logical clock reads exactly that value before any set call — it never falls back to wall-clock time. A clock change does not eagerly recompute any window; window rollover is evaluated lazily on the next velocity check.

### 3.9. Returns and the Recovery Waterfall

When a previously cashed check comes back unpaid, a `StoreManager` returns it. A return is permitted only on a transaction whose `txn_type` is `CHECK_CASH` and which is currently in `lifecycle_state` `POSTED` with `settlement_state` `SETTLED`. The return supplies a `return_reason` — one of `NSF`, `ACCOUNT_CLOSED`, `STOP_PAYMENT`, or `FRAUD`. Returning the transaction moves its `settlement_state` `SETTLED → RETURNED` and creates a returned item in status `OUTSTANDING`, copying the originating transaction's `transaction_id` and `customer_id` onto it and assessing a flat `return_fee_cents` of 2500 cents. As a first cascade hop, the customer's `outstanding_recovery_cents` is increased by the sum of the check face plus the 2500-cent return fee. As a second cascade hop, 250 points are confirmed onto the customer's `risk_score`, which may in turn bump the `risk_tier` as described in §3.8.

A returned item carries a recovery lifecycle: its `status` is one of `OUTSTANDING`, `PARTIALLY_RECOVERED`, `RECOVERED`, or `WRITTEN_OFF`, with `RECOVERED` and `WRITTEN_OFF` terminal, and a `recovered_cents` accumulator starting at 0. The total owed is fixed at return time as the check face plus the return fee and is never re-derived. Recovery follows a waterfall: each payment fills the return-fee bucket first, then the check-face principal.

A `Teller` or `StoreManager` applies a recovery payment by supplying `amount_cents`. The amount must be greater than 0 and must not exceed the remaining balance, which is the total owed minus the amount already recovered; an amount of 0 or less, or any amount that would overpay the remaining balance, is rejected with `ERR_RECOVERY_OVERPAYMENT` (overpayment is refused outright, not silently capped). On a valid payment, the applied amount is added to `recovered_cents` and subtracted from the customer's `outstanding_recovery_cents`. If the payment brings `recovered_cents` to exactly the total owed, the returned item moves to `RECOVERED` (whether arriving from `OUTSTANDING` directly or from `PARTIALLY_RECOVERED`), and the linked transaction's `settlement_state` moves to `RECOVERED`. If the payment is for less than the remaining balance, the returned item moves to `PARTIALLY_RECOVERED` and may receive further partial payments, each repeating the same accumulation and customer-balance reduction.

Alternatively, a `StoreManager` may write off a returned item that is `OUTSTANDING` or `PARTIALLY_RECOVERED`. Writing off clears the remaining balance from the customer's `outstanding_recovery_cents` (the total owed minus what has been recovered so far) and moves the returned item to `WRITTEN_OFF`. A write-off confirms 200 points onto the customer's `risk_score`. Returned items can be fetched individually and listed, optionally filtered by `transaction_id`, `customer_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource (registering a customer, running a compliance screen, creating a fee schedule, opening a drawer, posting a transaction, or returning a transaction into a new returned item) return `201 Created`. Operations that modify an existing resource — including the action endpoints that drive state transitions such as releasing or rejecting a check, voiding, beginning reconciliation, closing a drawer, recovering, and writing off — return `200 OK`. The clock-setting capability also returns `200 OK`. The table below is a routing summary only; request bodies, response shapes, and side effects are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a KYC subject (kyc_status starts PENDING) | Teller, StoreManager |
| GET | `/customers/{id}` | Fetch a customer | Teller, StoreManager |
| GET | `/customers` | List customers (paginated; optionally filtered by `kyc_status`) | Teller, StoreManager |
| GET | `/customers/{id}/compliance-screens` | List a customer's compliance screens | Teller, StoreManager |
| GET | `/customers/{id}/returned-items` | List a customer's returned items | Teller, StoreManager |
| POST | `/compliance-screens` | Run an OFAC/KYC screen; writes outcome to the customer | StoreManager |
| POST | `/fee-schedules` | Create a check-cashing fee schedule | StoreManager |
| GET | `/fee-schedules/{id}` | Fetch a fee schedule | Teller, StoreManager |
| GET | `/fee-schedules` | List fee schedules (optionally filtered by `check_type` and/or `active`) | Teller, StoreManager |
| POST | `/cash-drawers` | Open a cash drawer for a store/business date | StoreManager |
| GET | `/cash-drawers/{id}` | Fetch a drawer | Teller, StoreManager |
| GET | `/cash-drawers/{id}/transactions` | List transactions on a drawer | Teller, StoreManager |
| POST | `/cash-drawers/{id}/begin-reconcile` | Move a drawer OPEN to RECONCILING | StoreManager |
| POST | `/cash-drawers/{id}/close` | Close a drawer with a physical count (OCC-guarded) | StoreManager |
| POST | `/transactions` | Create and post a transaction of any type | Teller, StoreManager |
| GET | `/transactions/{id}` | Fetch a transaction | Teller, StoreManager |
| GET | `/transactions` | List transactions (optionally filtered by `customer_id`, `drawer_id`, `fee_schedule_id`, and/or `txn_type`) | Teller, StoreManager |
| POST | `/transactions/{id}/void` | Void a posted transaction | StoreManager |
| POST | `/transactions/{id}/return` | Mark a posted, settled check-cash as returned | StoreManager |
| GET | `/check-items/{id}` | Fetch a check item | Teller, StoreManager |
| GET | `/transactions/{id}/check-items` | List the check item(s) for a transaction | Teller, StoreManager |
| POST | `/check-items/{id}/release` | Release a risk-held check (posts the transaction) | StoreManager |
| POST | `/check-items/{id}/reject` | Reject a risk-held check (voids the transaction) | StoreManager |
| GET | `/transactions/{id}/money-order` | List the money order for a transaction | Teller, StoreManager |
| GET | `/transactions/{id}/wire-transfer` | List the wire transfer for a transaction | Teller, StoreManager |
| GET | `/transactions/{id}/bill-payment` | List the bill payment for a transaction | Teller, StoreManager |
| GET | `/transactions/{id}/prepaid-card-load` | List the prepaid-card load for a transaction | Teller, StoreManager |
| GET | `/returned-items/{id}` | Fetch a returned item | Teller, StoreManager |
| GET | `/returned-items` | List returned items | Teller, StoreManager |
| POST | `/returned-items/{id}/recover` | Apply a recovery payment (waterfall) | Teller, StoreManager |
| POST | `/returned-items/{id}/write-off` | Write off an outstanding returned item | StoreManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_KYC_NOT_VERIFIED` | 403 |
| `ERR_OFAC_BLOCKED` | 403 |
| `ERR_FEE_SCHEDULE_INVALID` | 422 |
| `ERR_DRAWER_NOT_OPEN` | 409 |
| `ERR_EMBARGOED_DESTINATION` | 422 |
| `ERR_RISK_CEILING_EXCEEDED` | 422 |
| `ERR_VELOCITY_LIMIT_EXCEEDED` | 422 |
| `ERR_DAILY_LIMIT_EXCEEDED` | 422 |
| `ERR_RECOVERY_OVERPAYMENT` | 422 |
| `ERR_OPEN_ITEMS_REMAIN` | 409 |
| `ERR_DRAWER_CONFLICT` | 409 |
| `ERR_STALE_DRAWER_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |

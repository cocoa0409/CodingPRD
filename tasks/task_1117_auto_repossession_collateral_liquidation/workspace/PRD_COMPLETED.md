# Auto Repossession & Collateral Liquidation API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Auto Repossession & Collateral Liquidation API, the system of record for an auto lender's recovery unit. The platform governs the complete post-default lifecycle of a vehicle loan: the determination of default and the borrower's statutory right-to-cure period, the assignment and compliance supervision of repossession agents, the inventory and return of personal property found in a recovered vehicle, redemption and reinstatement quoting, auction consignment with reserve pricing, deficiency balance calculation and notification, and the handling of wrongful-repossession complaints through to restitution.

Two forces shape every design decision in this document. The first is regulatory exposure: statutory clocks (cure periods, redemption windows, deficiency-notice deadlines, property-retention windows) are hard boundaries, and the system must be able to prove, at any moment, exactly what was owed, what was said to the borrower, and when. The second is distrust of any single operator: the manager who opens a case may not certify its sale or adjudicate its complaint, every dollar that moves is written to an append-only ledger, and every superseding document is protected by optimistic concurrency control so that no client ever silently overwrites a notice or quote it has not observed. Recovery accounting is deliberately dual-tracked — provisional estimates guide decisions before the auction, while final settled figures govern what the borrower is actually billed afterwards — and vendor performance is scored continuously so that assignment decisions reflect an agent's recent conduct, not just its historical record.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly five roles: `RecoveryManager`, `RepoAgent`, `Auctioneer`, `ComplianceOfficer`, and `Borrower`. A request with missing headers, or a role value outside those five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A properly authenticated caller whose role is not listed among the endpoint's permitted roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `RepoAgent`, `X-User-ID` is the `id` of the acting `RepoAgent`; ownership checks on any resource that references a `RepoAgent` compare the resource's foreign-key field (for example, an assignment's `agent_id`) to `X-User-ID`. When `X-User-Role` is `Auctioneer`, `X-User-ID` is the `id` of the acting `AuctionHouse`; ownership checks compare a consignment's `auction_house_id` to `X-User-ID`. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`; ownership checks compare the `borrower_id` of the loan behind the target case to `X-User-ID`. When `X-User-Role` is `RecoveryManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (as `opened_by_user_id` on each `RecoveryCase` the manager opens) but never compares it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (as `resolved_by_user_id` on each resolved `Complaint`) but never compares it to any entity's `id`.

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

Two fallbacks complete the error surface: a request to an unknown path, or to a known path with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404); any unexpected server failure is reported as `ERR_INTERNAL` (HTTP 500) in the same envelope.

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; because the logical clock makes equal timestamps common, ties are broken by creation (insertion) sequence. Where an endpoint supports filters, the filters are applied before pagination, so `total_count` and `has_more` describe the filtered set. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — borrowers, loan accounts, recovery cases, cure notices, repo agents, repo assignments, personal property items, redemption quotes, auction houses, consignments, sale records, deficiency notices, and complaints — carries a standard set of system-managed fields. The `id` is a server-minted unique identifier formatted as a UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same style of timestamp refreshed on every modification. The `version` field is a system-managed integer that starts at 1 on creation and increments on every mutation of the resource — including mutations produced by side-effect cascades, such as a supersession that repoints a case's live document pointer — and it anchors the optimistic concurrency control described in §2.8. Case-scoped documents each carry a `recovery_case_id` back-reference taken from the URL path of the request that created them, and a `SaleRecord` similarly carries the `consignment_id` of the consignment it was reported against.

One resource is the deliberate exception. A `RecoveryLedgerEntry` is append-only: it carries `id` and `created_at` and nothing else from the standard set — `updated_at` and `version` are absent, and no endpoint updates or deletes a ledger entry.

### 2.5. The Logical Clock and Automatic Transitions

Every reference to "now" in this document means the system's logical clock, never the wall clock. Before any operator intervention the logical clock starts at exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A test-driving capability, restricted to `RecoveryManager` and `ComplianceOfficer` callers, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The supplied instant is applied verbatim: no monotonicity check rejects a `to_iso8601` earlier than the current logical time.

Advancing the clock atomically applies every automatic transition that has fallen due, in dependency order, within the same request. Cure notices whose deadline has passed move from `SENT` to `EXPIRED` first, and only then do their cases move from `CURE_PENDING` to `CURE_EXPIRED`. Still-`ISSUED` redemption quotes past the redemption deadline move to `EXPIRED` and their cases advance from `REDEMPTION_OPEN` to `CONSIGNMENT_PENDING` — but quote and case expiry fire only while the case is still `REDEMPTION_OPEN`; a case frozen in `COMPLAINT_REVIEW` and its quote are left untouched by the clock. Finally, assignments still sitting in `ASSIGNED` more than 48 hours after their creation move to `EXPIRED`, each triggering an agent score recompute and, where the recomputed rolling score warrants it, the suspension cascade described in §3.3.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are represented as integer cents; no floating-point money exists anywhere in the API. Wherever a computation produces a fractional cent, the value is rounded half up to the nearest whole cent. Two rounding orders are pinned and non-negotiable. Per-diem interest is always rounded to whole cents first and only then multiplied by the number of days — computing the interest for the whole period in a single shot and rounding once at the end produces a different, non-conformant number. And on a sale, each fee line (the auction commission, the transport fee) is rounded to cents individually before any subtraction takes place.

### 2.7. Validation Order and Error Precedence

Every mutating request passes through a fixed validation cascade, and the first failing check wins — later checks are never evaluated for a rejected request. The order is: (1) authentication headers are present and the role is one of the five declared roles (`ERR_UNAUTHENTICATED`); (2) the caller's role is permitted on the endpoint (`ERR_UNAUTHORIZED`); (3) the caller owns the target resource within the borrower, agent, or auctioneer scope that applies (`ERR_FORBIDDEN_OWNERSHIP`); (4) every identifier in the path resolves to an existing resource (`ERR_NOT_FOUND`, path identifiers validated left to right) and the request body is well-formed (`ERR_INVALID_REQUEST`) — required fields present, types correct, enum values valid, unknown fields rejected, monetary fields integral with payment, bid, and ledger amount fields required positive while stored balance, appraisal, and fee fields accept zero; a body field that references another entity by id (such as `loan_account_id`, `borrower_id`, `agent_id`, or `auction_house_id`) and fails to resolve is likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400), not `ERR_NOT_FOUND`; (5) the target resource's own state permits the transition (the family of `ERR_INVALID_CASE_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`, `ERR_INVALID_QUOTE_STATE`, `ERR_INVALID_ITEM_STATE`, `ERR_INVALID_CONSIGNMENT_STATE`, `ERR_INVALID_SALE_STATE`, `ERR_INVALID_DEFICIENCY_STATE`, and `ERR_INVALID_COMPLAINT_STATE` rejections); (6) business-safety rules — segregation of duties, agent-suspension, and agent-licensing checks (`ERR_SEGREGATION_OF_DUTIES`, `ERR_AGENT_SUSPENDED`, `ERR_AGENT_LICENSE_MISMATCH`); (7) temporal windows (`ERR_QUOTE_EXPIRED`, `ERR_DEFICIENCY_WINDOW_EXPIRED`, `ERR_PROPERTY_RETENTION_ACTIVE`); (8) business constraints (`ERR_DUPLICATE_OPEN_CASE`, `ERR_AGENT_CAPACITY_EXCEEDED`, `ERR_FIELD_WINDOW_OVERLAP`, `ERR_NO_ELIGIBLE_AGENT`, `ERR_AUCTION_WINDOW_OVERLAP`); (9) fiscal sufficiency (`ERR_PAYMENT_INSUFFICIENT`, `ERR_BID_BELOW_RESERVE`); and finally (10) the optimistic-concurrency version check (`ERR_STALE_VERSION`).

One tie-break rule applies throughout the state tier (step 5): the state of the resource named in the request path is evaluated before any cross-entity precondition. An accept attempted on a quote that is already `EXPIRED` therefore yields `ERR_INVALID_QUOTE_STATE` even when the owning case has itself moved on to `CONSIGNMENT_PENDING` — the quote's own staleness is reported, not the case's.

### 2.8. Optimistic Concurrency Control on Case Documents

Two operations create documents that supersede their predecessor on a case: issuing a right-to-cure notice, and issuing a redemption or reinstatement quote. Both require the request to carry `expected_recovery_case_version` as a non-optional input field, holding the `version` of the `RecoveryCase` as the client last observed it. If the case's current `version` does not match — because another write has advanced the case since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is created or superseded. Supersession is a legitimate product operation, so no state-field check would ever catch a second sequential create; the version check is the only guard protecting a client from superseding a notice or quote it never saw. Endpoints other than these two do not accept any version field.

### 2.9. Ownership Scopes and Segregation of Duties

Beyond role membership, three entity-backed ownership scopes restrict what a caller may touch. A `Borrower` acts only on cases whose loan's `borrower_id` equals the caller's `X-User-ID` — this governs cure payments, quote acceptance, complaint filing, item claim and unclaim, and deficiency dispute and payment. A `RepoAgent` acts only on assignments whose `agent_id` equals the caller's `X-User-ID`, and — for personal property returns and disposals — only on items of a case whose `SECURED` assignment belongs to that agent. An `Auctioneer` acts only on consignments whose `auction_house_id` equals the caller's `X-User-ID`. A caller who is authenticated and role-permitted but outside the owning scope is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

Segregation of duties cuts across the role model in one specific place. The `RecoveryManager` who opened a case — recorded as the case's `opened_by_user_id` — may not certify that case's sale and may not resolve that case's complaint, regardless of the caller's current role assignment. An attempt to do either is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. The Append-Only Recovery Ledger

Every recovery case accumulates an append-only ledger of `RecoveryLedgerEntry` rows, each carrying a `kind`, a positive `amount_cents`, and an optional `memo` that defaults to an empty string. The direction of an entry is implied by its kind, never by a sign on the amount. Manual posting by a `RecoveryManager` accepts only the cost and adjustment kinds — `COST_REPO_FEE`, `COST_STORAGE`, `COST_TRANSPORT`, `COST_KEY`, `COST_OTHER`, and `ADJUSTMENT` — each of which increases the borrower-owed costs of the case. The remaining kinds are written exclusively by system transitions: `PAYMENT` when borrower money arrives, `REVERSAL` when a prior entry is undone, and `REFUND` when a surplus is paid out. A `REVERSAL` entry carries `reverses_entry_id`, the `id` of the ledger entry it undoes.

The ledger feeds a single derived figure used throughout the document: the case's recovery-costs total. That total is the sum of the `amount_cents` of all entries in the six cost and adjustment kinds, minus the sum of the `amount_cents` of every `REVERSAL` whose `reverses_entry_id` references one of those cost or adjustment entries. Cure amounts, redemption quotes, reserve prices, and deficiency balances all draw on this one definition, so a cost posted (or reversed) anywhere in the case history is reflected consistently everywhere. The ledger also drives the loan's running payment total: every `PAYMENT` entry increments the loan's `paid_to_date_cents` by its amount, and every `REVERSAL` decrements it correspondingly.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Borrowers, Loan Accounts, and the Default Determination

A `RecoveryManager` begins by registering the borrower with a `full_name`, a `state_code` capturing the two-letter US state of the borrower's residence, and a contact `email`. The loan account follows: the manager supplies the `borrower_id` of the owning borrower, the collateral vehicle's `vin`, the `governing_state_code` naming the state whose statute governs the loan (this is the code that drives agent licensing checks later), the `principal_balance_cents` outstanding, the `apr_bps` annual percentage rate expressed in basis points (so 1200 represents twelve percent), and the scheduled `monthly_payment_cents`. Three arrears fields — `missed_installments`, `accrued_interest_cents`, and `late_fees_cents` — may be supplied at creation and each defaults to 0 when omitted; they capture the count of unpaid scheduled installments, the interest arrears (excluding any per-diem accrual after case opening), and the unpaid late fees, all as of case opening. A freshly created loan stands in `CURRENT` status with `paid_to_date_cents` at 0. The `principal_balance_cents` is never mutated afterwards; payments are tracked exclusively through `paid_to_date_cents`. From these inputs the system derives `total_outstanding_cents` — the principal balance plus the accrued interest plus the late fees, minus the payments to date — with per-diem interest deliberately excluded from that figure.

The default determination is itself an API act: a `RecoveryManager` opens a recovery case by supplying the `loan_account_id` and a free-text `default_reason`. At most one case per loan may be non-`CLOSED` at any time; opening a second while another is still live is rejected with `ERR_DUPLICATE_OPEN_CASE` (HTTP 409). A successful opening sets the loan to `IN_DEFAULT` (incrementing the loan's `version`) — the one-open-case rule is the only precondition, so on a re-opened loan this applies whatever status the loan previously held — stamps the case `OPENED`, and records the caller in `opened_by_user_id` — the value that later anchors the segregation-of-duties checks. The case register can be listed with optional `status` and `loan_account_id` filters alongside the standard `limit` and `offset` pagination parameters, and a `status` filter value outside the case status vocabulary is rejected with `ERR_INVALID_REQUEST` (HTTP 400); every case-scoped collection (notices, assignments, items, quotes, consignments, deficiency notices, complaints, ledger entries) can be listed through its own reverse-lookup endpoint.

### 3.2. The Right-to-Cure Period

With a case `OPENED`, the `RecoveryManager` issues a right-to-cure notice. The request body carries no amounts at all — only the OCC guard `expected_recovery_case_version` described in §2.8 — because the cure amount is always computed by the system. The case must stand in `OPENED` or `CURE_PENDING`; any other status is rejected with `ERR_INVALID_CASE_STATE`. The notice's `cure_amount_cents` is a snapshot, computed once at creation and never recomputed afterwards: it is the loan's missed installments multiplied by the monthly payment, plus the unpaid late fees, plus the case's recovery-costs total as defined in §2.10. The notice is created directly in `SENT` status with `sent_at` stamped from the logical clock, and the case's `cure_deadline` is set to the notice's `sent_at` plus fourteen days.

Issuing that first notice moves the case from `OPENED` to `CURE_PENDING`, repoints the case's `current_cure_notice_id` to the live notice, and increments the case's `version`. Issuing another notice while one is still live is the supersession path: the prior `SENT` notice transitions to `SUPERSEDED` with its `superseded_by_id` set to the new notice, the replacement is created in `SENT` carrying a freshly computed `cure_amount_cents`, the case's `cure_deadline` is recomputed as the new `sent_at` plus fourteen days, `current_cure_notice_id` is repointed, and the case `version` increments again.

The borrower answers a cure notice with a cure payment carrying an `amount_cents`, actable only on the borrower's own cases. Two guards apply in cascade order: the case must stand in `CURE_PENDING` (a state-tier rejection with `ERR_INVALID_CASE_STATE`), and only then is sufficiency judged — the payment must be at least the live notice's `cure_amount_cents`, else the request fails with `ERR_PAYMENT_INSUFFICIENT` (HTTP 422). Note that the moment the logical clock passes `cure_deadline`, the automatic transition of §2.5 fires: the live notice moves from `SENT` to `EXPIRED` and the case from `CURE_PENDING` to `CURE_EXPIRED`. A payment attempted after the deadline therefore always observes `CURE_EXPIRED` and fails the state guard rather than the clock. A full in-window payment writes a `PAYMENT` ledger entry for the paid `amount_cents`, increments the loan's `paid_to_date_cents` by the same amount (incrementing the loan's `version`), moves the current notice to `CURED`, moves the case to `CURED`, and restores the loan from `IN_DEFAULT` to `CURRENT`. The response is `201 Created` carrying the created `PAYMENT` ledger entry.

### 3.3. Repossession Agents and Field Assignments

Field work is performed by registered repossession vendors. A `RecoveryManager` registers each agent with a legal `name`, a `license_number`, the array of `licensed_state_codes` in which the agent may operate, and a `max_active_assignments` capacity cap. A new agent starts `ACTIVE` with both performance scores at 100. Suspension — whether manual or automatic — is terminal: a `SUSPENDED` agent has no reinstatement path.

Performance is scored on a fixed formula evaluated over an assignment window: start from 100, subtract 25 for every assignment that ended in `BREACHED_PEACE`, subtract 10 for every assignment that went `EXPIRED`, and add 2 for every assignment that reached `SECURED` quickly — within fourteen days of its creation, a fact recorded on the assignment as `secured_fast`. The result is clamped so it never falls below 0 or rises above 100. Two variants of this score are maintained on the agent and recomputed on every terminal assignment transition of that agent (and reflected on every read of the agent): `performance_score_lifetime` spans all of the agent's assignments regardless of age, while `performance_score_rolling` restricts the same weights to assignments created within the trailing ninety days of the logical clock. The rolling variant alone drives auto-suspension and auto-assignment ranking, so an agent whose violations are all older than ninety days reads 100 on the rolling score even while its lifetime score reads lower.

Assignment creation is a `RecoveryManager` act on a case standing in `CURE_EXPIRED` or `REPO_ACTIVE` — provided no assignment of that case is currently `ASSIGNED` or `ACCEPTED`; otherwise the create is rejected with `ERR_INVALID_CASE_STATE`. The payload carries the planned field-operation window as `field_window_start` and `field_window_end` (a half-open interval: the start is inclusive, the end exclusive) and an optional `agent_id`. When `agent_id` is given, four explicit-assignment checks fire: the agent must be `ACTIVE` (`ERR_AGENT_SUSPENDED`, HTTP 422); the case's loan `governing_state_code` must appear among the agent's `licensed_state_codes` (`ERR_AGENT_LICENSE_MISMATCH`, HTTP 422); the agent's count of `ASSIGNED` plus `ACCEPTED` assignments must be strictly below its `max_active_assignments` (`ERR_AGENT_CAPACITY_EXCEEDED`, HTTP 422); and the new half-open window must not overlap the window of any `ASSIGNED` or `ACCEPTED` assignment the agent already holds (`ERR_FIELD_WINDOW_OVERLAP`, HTTP 409). Two half-open windows overlap only when each starts strictly before the other ends — two windows that merely abut, one ending exactly when the other begins, do not overlap.

When `agent_id` is omitted, the server selects the agent and marks the assignment `auto_selected`. Eligibility for the pool requires all of: the agent is `ACTIVE`; the agent is licensed in the case loan's governing state; the agent's live `ASSIGNED`-or-`ACCEPTED` count is below its capacity cap; the new field window does not overlap (in the same half-open sense) any of the agent's live assignment windows; and the agent has never held an assignment on this very case that ended in `BREACHED_PEACE`. The eligible pool is ranked by `performance_score_rolling` descending, with ties broken by the agent's `created_at` in ascending order — the earliest-registered agent wins a tie, and agents registered at the same logical instant (equal `created_at`) are further ordered by registration sequence. The first agent of that ranking is selected; an empty pool rejects the create with `ERR_NO_ELIGIBLE_AGENT` (HTTP 422). Either way, a successful create moves the case into `REPO_ACTIVE` (from `CURE_EXPIRED`, or remaining in `REPO_ACTIVE` on re-assignment) and the new assignment starts in `ASSIGNED`. A create that leaves the case in `REPO_ACTIVE` does not modify the case row at all — its `version` does not increment on re-assignment.

The assigned agent accepts by its own action, moving the assignment from `ASSIGNED` to `ACCEPTED`. Acceptance requires the assignment to be in `ASSIGNED` (`ERR_INVALID_ASSIGNMENT_STATE`), the caller to be the assignment's agent (`ERR_FORBIDDEN_OWNERSHIP`), and — a business-safety check evaluated only after the state tier — the agent to still be `ACTIVE` (`ERR_AGENT_SUSPENDED`). An assignment left unacknowledged expires automatically: once the logical clock passes 48 hours beyond the assignment's creation while it still stands `ASSIGNED`, it moves to `EXPIRED`, the agent's scores are recomputed with one more expired count (a 10-point penalty), and if the recomputed rolling score falls below 40 the agent is auto-suspended and the suspension cascade fires.

A `ComplianceOfficer` records a breach-of-peace finding against an assignment in `ASSIGNED` or `ACCEPTED` (any other status is rejected with `ERR_INVALID_ASSIGNMENT_STATE`), moving it to `BREACHED_PEACE`. The breach triggers a three-link cascade, applied atomically: first, the agent's scores are recomputed with one more breach count (a 25-point penalty); second, if the recomputed `performance_score_rolling` has fallen below the suspension threshold of 40, the agent transitions to `SUSPENDED`; third, every other assignment of that agent still standing in `ASSIGNED` or `ACCEPTED` is moved to `CANCELLED`. The case itself remains in `REPO_ACTIVE` with no live assignment, so the manager is free to assign a different agent. A manual suspension — a `ComplianceOfficer` act on the agent — moves the agent from `ACTIVE` to `SUSPENDED` and fires that same third link, cancelling the agent's live `ASSIGNED` and `ACCEPTED` assignments. Suspending an already-`SUSPENDED` agent is an idempotent no-op: the request succeeds with `200 OK` and nothing changes.

As the field operation unfolds, the `RecoveryManager` posts the case's costs into the ledger — repossession fees, storage, transport, key cutting, other costs, and manual adjustments — each entry carrying its `kind`, a positive `amount_cents`, and an optional `memo`, appended immutably per §2.10. These entries are what the cure amount, the quotes, the reserve price, and the deficiency balance all draw upon.

### 3.4. Securing the Collateral and Inventorying Personal Property

The field phase concludes when the assigned agent reports the vehicle secured. Only the assignment's own agent may file this report (`ERR_FORBIDDEN_OWNERSHIP`), and only while the assignment stands `ACCEPTED` (`ERR_INVALID_ASSIGNMENT_STATE`). The case must additionally stand in `REPO_ACTIVE` — a cross-entity state precondition evaluated after the assignment-state guard per the §2.7 tie-break, rejected with `ERR_INVALID_CASE_STATE` otherwise. The report carries the vehicle's `odometer`, a `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`, the clean trade-in appraisal `trade_in_value_cents`, and the wholesale `auction_guide_low_cents`. On success the assignment moves to `SECURED` — with `secured_fast` set when the securing happened within fourteen days of assignment creation — and the case moves from `REPO_ACTIVE` to `COLLATERAL_SECURED`. All four appraisal fields are copied onto the case, the case's `collateral_secured_at` is stamped with the current logical time (this instant anchors both the property-retention window below and downstream storage windows), and both of the agent's performance score variants are recomputed.

Repossessed vehicles frequently contain the borrower's belongings. The agent holding the case's `SECURED` assignment inventories each item found in the vehicle — a `RepoAgent` caller who does not hold that assignment is rejected with `ERR_FORBIDDEN_OWNERSHIP` — with a `description` and an optional `estimated_value_cents` that defaults to 0; every item created increments the case's `property_item_count` by one, and that counter is never decremented — it is the anchor of the custody invariant that every item ever inventoried remains accounted for. Items are created in `INVENTORIED` status. The borrower who owns the case may claim an `INVENTORIED` item, moving it to `CLAIMED` and recording themselves in `claimed_by_borrower_id` (an item in any other status rejects with `ERR_INVALID_ITEM_STATE`; a borrower reaching for someone else's case is stopped by `ERR_FORBIDDEN_OWNERSHIP`). A claim can be withdrawn, moving the item from `CLAIMED` back to `INVENTORIED` and clearing `claimed_by_borrower_id` — but only by the borrower recorded on the claim. The agent holding the case's `SECURED` assignment marks a `CLAIMED` item handed back, moving it to `RETURNED`, and may dispose of an `INVENTORIED` item only once the retention window has elapsed: at least fifteen days must have passed since `collateral_secured_at`, else the disposal is rejected with `ERR_PROPERTY_RETENTION_ACTIVE` (HTTP 422) — a temporal check evaluated after the item-state guard. Successful disposal moves the item to `DISPOSED`; `RETURNED` and `DISPOSED` are the item's terminal states.

### 3.5. Redemption and Reinstatement

Once the collateral is secured, the borrower retains the right to recover the vehicle or cure the arrears, and the `RecoveryManager` communicates the price of that right through redemption quotes. Issuing a quote requires the case to stand in `COLLATERAL_SECURED` or `REDEMPTION_OPEN` (`ERR_INVALID_CASE_STATE` otherwise), and the request carries the `quote_type` — `REDEMPTION` for a full payoff, or `REINSTATEMENT` for arrears plus costs only — together with the OCC guard `expected_recovery_case_version` from §2.8. The very first quote on a case moves it from `COLLATERAL_SECURED` to `REDEMPTION_OPEN` and fixes the case's `redemption_deadline` at the quote's `issued_at` plus ten days; that deadline is set once and is never extended by any later quote.

The quoted amount is a snapshot, computed at issuance and never recomputed. Per-diem interest is derived from the loan in the pinned order of §2.6: the principal balance is multiplied by the APR in basis points, divided by ten thousand, divided by 365, and the result rounded half up to whole cents — that daily figure is then multiplied by the number of calendar days between the case's `created_at` date and the quote's `valid_until` date (both read as UTC dates, end minus start). A `REDEMPTION` quote prices the full payoff: the loan's `total_outstanding_cents`, plus the per-diem amount times those interest days, plus the case's recovery-costs total. A `REINSTATEMENT` quote prices arrears only: the missed installments times the monthly payment, plus the late fees, plus the recovery-costs total — with no principal acceleration and no per-diem interest at all, which is why a reinstatement quote's `per_diem_cents` snapshot is 0 while a redemption quote's carries the computed daily figure. Every quote is created in `ISSUED` status with `issued_at` stamped from the logical clock and `valid_until` set equal to the case's `redemption_deadline`; acceptance at any moment on or before `valid_until` is in-window. Issuing a replacement quote supersedes the live one: the prior `ISSUED` quote moves to `SUPERSEDED` with its `superseded_by_id` pointing at the newcomer, the new quote is created `ISSUED` with a freshly computed `quoted_amount_cents`, the case's `current_redemption_quote_id` is repointed, and the case `version` increments.

The borrower accepts a quote by paying it, supplying `payment_amount_cents`. Four preconditions apply, in the cascade order of §2.7: the quote itself must be `ISSUED` (`ERR_INVALID_QUOTE_STATE` — and by the state-tier tie-break this is judged before any cross-entity check, so an expired quote on a case that has since moved on reports the quote's state); the quote's case must stand in `REDEMPTION_OPEN` (`ERR_INVALID_CASE_STATE`), which means a case frozen in `COMPLAINT_REVIEW` blocks acceptance even while its quote remains `ISSUED`; the logical clock must be on or before the quote's `valid_until` (`ERR_QUOTE_EXPIRED`, HTTP 422 — a rejection reachable precisely in the complaint scenario, because a quote whose case sat frozen past the deadline was never auto-expired, and accepting it after a dismissal restores the case therefore fails this temporal check); and the payment must cover the `quoted_amount_cents` in full (`ERR_PAYMENT_INSUFFICIENT`). A successful acceptance moves the quote to `ACCEPTED`, writes a `PAYMENT` ledger entry, and adds the `payment_amount_cents` to the loan's `paid_to_date_cents`. The closing movement then depends on the quote type: accepting a `REDEMPTION` quote moves the case to `REDEEMED` and the loan to `REDEEMED_PAID`, while accepting a `REINSTATEMENT` quote moves the case to `REINSTATED` and restores the loan to `CURRENT`.

Should the redemption window lapse unused, the clock work of §2.5 takes over: while the case stands `REDEMPTION_OPEN`, a logical time beyond the `redemption_deadline` expires the `ISSUED` quote (`ISSUED` → `EXPIRED`) and moves the case to `CONSIGNMENT_PENDING`, clearing the path to auction.

### 3.6. Auction Consignment, Listing, and Sale Certification

Auction vendors are onboarded by a `RecoveryManager` with a `name`, a `fee_bps` commission expressed in basis points of the gross sale (so 500 represents five percent), and a flat `transport_fee_cents` charged per sold vehicle. Consigning a case's collateral to a house is a manager act carrying the `auction_house_id`; the case must stand in `CONSIGNMENT_PENDING`, and a case whose appraisal was never captured — no `condition_grade` on file — cannot be consigned at all (both rejected with `ERR_INVALID_CASE_STATE`). The consignment is created in `DRAFT` status with its reserve price computed immediately.

The reserve blends three signals, each figure rounded half up to whole cents independently before any comparison. The grade-adjusted appraisal is the case's `trade_in_value_cents` multiplied by the grade multiplier — eighty-five percent for `EXCELLENT`, seventy-five percent for `GOOD`, sixty percent for `FAIR`, forty-five percent for `POOR` — rounded half up. The floor value is one half of the payoff estimate, where the payoff estimate is the loan's `total_outstanding_cents` plus the case's recovery-costs total at consignment creation, rounded half up. The reserve price then stored in `reserve_price_cents` is the smaller of the grade-adjusted appraisal and the larger of the `auction_guide_low_cents` and the floor value. Each consignment also receives a `consignment_seq`, a per-case monotonically increasing creation sequence — 1 for the case's first consignment, 2 for the next, and so on — which serves as the deterministic "latest consignment" key used by the deficiency estimate of §3.7, since `created_at` values may tie under the logical clock but this sequence never does.

The auction house itself lists a consignment, supplying a `listing_start` and `listing_end` that form a closed interval — both endpoints inclusive. Listing requires the consignment in `DRAFT` (`ERR_INVALID_CONSIGNMENT_STATE`), the caller to own the consignment via `auction_house_id` (`ERR_FORBIDDEN_OWNERSHIP`), the case in `CONSIGNMENT_PENDING` (`ERR_INVALID_CASE_STATE`), and — because two sales cannot run concurrently at one venue — the new closed window must not touch or overlap any other `LISTED` consignment window at the same auction house (`ERR_AUCTION_WINDOW_OVERLAP`, HTTP 409; note the contrast with field windows: closed-interval adjacency counts as a conflict here). A successful listing moves the consignment from `DRAFT` to `LISTED` and the case from `CONSIGNMENT_PENDING` to `IN_AUCTION`. When a vehicle fails to sell, the house reports it: the consignment must be `LISTED`, and the report moves it to `UNSOLD` and the case back to `CONSIGNMENT_PENDING`. Relisting an `UNSOLD` consignment repeats the same ownership, case-state, and window-overlap checks, but the reserve softens: before the transition commits, the consignment's `reserve_price_cents` is recomputed as the prior reserve multiplied by 0.95 — a five-percent markdown — rounded half up, and stored; the `relist_count` increments by one, the consignment returns to `LISTED`, and the case re-enters `IN_AUCTION`.

A hammer price is reported by the auction house as `gross_sale_cents` against a `LISTED` consignment, and the bid must meet the reserve: a `gross_sale_cents` below the consignment's `reserve_price_cents` is rejected with `ERR_BID_BELOW_RESERVE` (HTTP 422), a fiscal check that fires only after the consignment's state guard has passed. A valid report creates the `SaleRecord` in `PENDING_CERTIFICATION` — the consignment itself stays `LISTED` until certification — with its fee lines computed at report time: the `auction_fee_cents` is the gross multiplied by the house's `fee_bps` and divided by ten thousand, rounded half up; the `transport_fee_cents` is a snapshot of the house's flat fee; and the `net_proceeds_cents` is the gross minus the auction fee minus the transport fee, each fee line rounded to cents individually before the subtraction per §2.6. At most one non-`VOID` sale record may exist per consignment: a `report-sale` or `report-unsold` against a consignment that already carries a non-`VOID` sale record is rejected with `ERR_INVALID_CONSIGNMENT_STATE` (HTTP 409), enforced together with the consignment's state guard.

Certification is the compliance gate. A `ComplianceOfficer` certifies a record standing in `PENDING_CERTIFICATION` (`ERR_INVALID_SALE_STATE` otherwise), on a case standing in `IN_AUCTION` (`ERR_INVALID_CASE_STATE`), and the certifier must not be the manager who opened the case — the segregation-of-duties rule of §2.9, rejected as `ERR_SEGREGATION_OF_DUTIES`. Certification moves the record to `CERTIFIED`, the consignment to `SOLD`, and the case from `IN_AUCTION` to `SALE_CONFIRMED`, stamping the case's `sold_at` with the current logical time — the instant that anchors the deficiency-notice window of §3.7.

### 3.7. Deficiency Notices and Post-Sale Settlement

After the sale — and even before it — the unit tracks what the borrower will still owe. A provisional estimate is readable by all five roles at any time after the case reaches `COLLATERAL_SECURED` — a read before any appraisal is on file (no `condition_grade` on the case) is rejected with `ERR_INVALID_CASE_STATE` (HTTP 409) — and it projects proceeds rather than measuring them: proceeds are estimated as ninety percent of the latest consignment's `reserve_price_cents`, rounded half up, where "latest" is decided by `consignment_seq`; if the case has no consignment yet, proceeds are instead ninety percent of the grade-adjusted appraisal (the same grade table as the reserve price), again rounded half up. The response carries `estimated_deficiency_cents`, `estimated_surplus_cents`, and a `basis` string naming the proceeds basis used — `consignment_reserve` when the case has a consignment, `grade_adjusted_appraisal` otherwise.

Both the provisional estimate and the final notice share one arithmetic skeleton; the variants differ only in the proceeds term and the as-of date. Interest days run from the case's `created_at` date to the as-of date — the logical clock's current date for the provisional estimate, the case's `sold_at` for the final figure. The payoff as of that date is the loan's `total_outstanding_cents` plus the pinned per-diem figure times those days, and the total owed is that payoff plus the case's recovery-costs total. Sale expenses are not added to the total owed: the proceeds figure is already net of the auction commission and transport fee, so the expenses are accounted for there. The deficiency is the excess of total owed over proceeds, floored at zero; the surplus is the excess of proceeds over total owed, floored at zero. When proceeds are applied against the debt in the audit display's waterfall order — costs first, then interest, then principal — the result is identical to that single subtraction; the waterfall ordering is presentational and never changes the arithmetic.

The final figures are fixed when a `RecoveryManager` creates the deficiency notice after the sale is certified. Creation requires exactly one `CERTIFIED` sale record on the case; if none exists or the record is not yet certified, creation fails with `ERR_INVALID_CASE_STATE`. No uniqueness constraint applies to the notices themselves — several `DRAFT` notices may coexist on one case. The notice's proceeds term is that record's actual `net_proceeds_cents` and its as-of date is the case's `sold_at`, so identical ledger data yields a different number than the provisional estimate whenever actual proceeds differ from the estimate. The computed `deficiency_amount_cents` and `surplus_cents` are snapshotted onto the notice — the deficiency is 0 whenever the surplus is positive, since surplus is money owed back to the borrower — and the notice starts in `DRAFT` with `paid_cents` at 0.

Sending is a separate, windowed act: the notice must be `DRAFT` (`ERR_INVALID_DEFICIENCY_STATE`), the case must stand in `SALE_CONFIRMED` (`ERR_INVALID_CASE_STATE`), and the logical clock must be on or before `sold_at` plus thirty days — the statutory deficiency-notice window — else the send is rejected with `ERR_DEFICIENCY_WINDOW_EXPIRED` (HTTP 422), a temporal check evaluated after the state tier. A successful send moves the notice to `SENT`, stamps its `sent_at`, and moves the case from `SALE_CONFIRMED` to `DEFICIENCY_NOTICED`.

From there the notice lives through a borrower-dialogue cycle. The borrower who owns the case may dispute a `SENT` notice, moving it to `DISPUTED`. The manager answers a `DISPUTED` notice with a revision carrying an `adjustment_cents` and a `reason`: the notice's `deficiency_amount_cents` becomes the greater of zero and the prior amount plus the adjustment, the notice returns to `SENT`, and its `version` increments — the `SENT` → `DISPUTED` → `SENT` cycle may repeat as negotiation continues. The borrower pays down the balance with payments of `amount_cents` against a notice in `SENT` or `DISPUTED`: each payment accumulates into the notice's `paid_cents`, writes a `PAYMENT` ledger entry, and increments the loan's `paid_to_date_cents` by the same amount; the notice moves to `PAID` only once `paid_cents` reaches at least the `deficiency_amount_cents`, and otherwise remains in its current status — partial payments change the numbers, not the state. A `ComplianceOfficer` may instead waive a notice in `SENT` or `DISPUTED`, moving it to `WAIVED`, and where a `surplus_cents` exists it is settled at that point by a `REFUND` ledger entry paying the surplus out. `PAID`, `WAIVED`, and `VOID` are the notice's terminal states.

### 3.8. Borrower Complaints and the Restitution Cascade

A borrower who believes the recovery was wrongful files a complaint against the case, supplying a `category` — one of `WRONGFUL_REPOSSESSION`, `BREACH_OF_PEACE`, `PROPERTY_LOSS`, `DEFICIENCY_DISPUTE`, or `NOTICE_DEFECT` — and a narrative `description`. Filing is limited to the borrower who owns the case, and the case must stand in one of the complaint-eligible states: `REPO_ACTIVE`, `COLLATERAL_SECURED`, `REDEMPTION_OPEN`, `CONSIGNMENT_PENDING`, `IN_AUCTION`, `SALE_CONFIRMED`, or `DEFICIENCY_NOTICED` (`ERR_INVALID_CASE_STATE` otherwise). The complaint is created directly in `UNDER_REVIEW` with the filer's identity recorded as its `borrower_id`. Filing freezes the case: the case's status at that instant is captured verbatim into `pre_complaint_state`, the case moves to `COMPLAINT_REVIEW`, and if any consignment of the case is currently `LISTED`, that consignment is withdrawn to `WITHDRAWN` in the same atomic act. While a case is frozen, the clock's expiry machinery leaves it and its quote untouched, per §2.5.

Resolution belongs to a `ComplianceOfficer`, who supplies an `outcome` of `UPHELD` or `DISMISSED`. The complaint must still be `UNDER_REVIEW` (`ERR_INVALID_COMPLAINT_STATE`), and the resolver must not be the manager who opened the case (`ERR_SEGREGATION_OF_DUTIES`); the resolver's identity is recorded in `resolved_by_user_id`. A `DISMISSED` outcome closes the complaint and restores the case verbatim to its `pre_complaint_state` — whatever complaint-eligible state it was frozen from. The restoration covers the case status only: a consignment withdrawn to `WITHDRAWN` at filing remains `WITHDRAWN` after a dismissal. An `UPHELD` outcome fires the four-link restitution cascade, applied atomically: first, the complaint itself moves to `UPHELD`; second, every deficiency notice of the case in `DRAFT`, `SENT`, or `DISPUTED` is voided, every sale record of the case in `PENDING_CERTIFICATION` or `CERTIFIED` is voided, and every consignment of the case in `DRAFT`, `LISTED`, or `UNSOLD` is withdrawn; third, for every `PAYMENT` ledger entry of the case, a `REVERSAL` entry is created with its `reverses_entry_id` pointing at the payment it undoes; fourth, the loan's `paid_to_date_cents` is decremented by the reversed amounts — the loan is restored as if the case's payments never happened — the loan moves back to `CURRENT`, and the case settles into `RESTITUTION`.

### 3.9. Case Closure and Terminal Outcomes

Closing a case is the final `RecoveryManager` act, and it is permitted from the settled states: `CURED`, `REDEEMED`, `REINSTATED`, and `RESTITUTION` close without further condition. A case in `DEFICIENCY_NOTICED` closes only when every deficiency notice of the case stands in `PAID`, `WAIVED`, or `VOID`; attempting to close with a notice still open is rejected with `ERR_INVALID_CASE_STATE`. Closing from `DEFICIENCY_NOTICED` carries one extra side effect: the loan moves from `IN_DEFAULT` to `CHARGED_OFF` — unless the loan already stands `REDEEMED_PAID` or `CURRENT`, in which case it is left as is. Closures from `REDEEMED` or `RESTITUTION` carry nothing further. `CLOSED` is the case's only terminal state; the loan's terminal states are `REDEEMED_PAID` and `CHARGED_OFF`. Once a case is `CLOSED`, the loan is again eligible under the one-open-case rule of §3.1 should a future default occur.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone entity or a new member of a case-scoped collection — return a `201 Created` status code. Operations that modify an existing resource, including state transitions and counterparty actions on an existing record, return a `200 OK` status code. Read endpoints return `200 OK`. The complete request and response semantics of each operation are defined by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/borrowers` | Register a borrower | RecoveryManager |
| GET | `/borrowers/{id}` | Get one borrower | All roles |
| GET | `/borrowers/{id}/loan-accounts` | List a borrower's loan accounts | All roles |
| GET | `/borrowers/{id}/complaints` | List complaints filed by a borrower | All roles |
| POST | `/loan-accounts` | Create a loan account (collateral vehicle financing) | RecoveryManager |
| GET | `/loan-accounts/{id}` | Get one loan account | All roles |
| GET | `/loan-accounts/{id}/recovery-cases` | List recovery cases of a loan | All roles |
| POST | `/recovery-cases` | Open a recovery case on a loan (the default determination) | RecoveryManager |
| GET | `/recovery-cases/{id}` | Get one recovery case | All roles |
| GET | `/recovery-cases` | List recovery cases with pagination and filtering | All roles |
| POST | `/recovery-cases/{id}/close` | Close a settled case | RecoveryManager |
| POST | `/recovery-cases/{id}/cure-notices` | Issue (and immediately send) a right-to-cure notice; supersedes any live `SENT` notice; OCC-guarded | RecoveryManager |
| GET | `/recovery-cases/{id}/cure-notices` | List cure notices of a case | All roles |
| POST | `/recovery-cases/{id}/cure-payments` | Borrower pays the cure amount | Borrower |
| POST | `/recovery-cases/{id}/ledger-entries` | Post a manual cost or adjustment ledger entry | RecoveryManager |
| GET | `/recovery-cases/{id}/ledger-entries` | List ledger entries of a case | All roles |
| POST | `/repo-agents` | Register a repossession agent vendor | RecoveryManager |
| GET | `/repo-agents/{id}` | Get one agent, including both score variants | All roles |
| POST | `/repo-agents/{id}/suspend` | Manually suspend an agent | ComplianceOfficer |
| GET | `/repo-agents/{id}/repo-assignments` | List assignments of an agent | All roles |
| POST | `/recovery-cases/{id}/repo-assignments` | Assign an agent, explicitly or via server auto-selection | RecoveryManager |
| GET | `/recovery-cases/{id}/repo-assignments` | List assignments of a case | All roles |
| POST | `/repo-assignments/{id}/accept` | Agent accepts an assignment | RepoAgent |
| POST | `/repo-assignments/{id}/report-secured` | Agent reports the vehicle secured, with condition and appraisal data | RepoAgent |
| POST | `/repo-assignments/{id}/report-breach` | Compliance records a breach-of-peace finding on an assignment | ComplianceOfficer |
| POST | `/recovery-cases/{id}/personal-property-items` | Inventory a personal property item found in the vehicle | RepoAgent |
| GET | `/recovery-cases/{id}/personal-property-items` | List property items of a case | All roles |
| POST | `/personal-property-items/{id}/claim` | Borrower claims an item | Borrower |
| POST | `/personal-property-items/{id}/unclaim` | Borrower withdraws a claim | Borrower |
| POST | `/personal-property-items/{id}/mark-returned` | Agent marks a claimed item returned | RepoAgent |
| POST | `/personal-property-items/{id}/dispose` | Agent disposes of an unclaimed item after the retention window | RepoAgent |
| POST | `/recovery-cases/{id}/redemption-quotes` | Issue a redemption or reinstatement quote; supersedes any live `ISSUED` quote; OCC-guarded | RecoveryManager |
| GET | `/recovery-cases/{id}/redemption-quotes` | List quotes of a case | All roles |
| POST | `/redemption-quotes/{id}/accept` | Borrower pays and accepts a quote | Borrower |
| POST | `/auction-houses` | Register an auction house vendor | RecoveryManager |
| GET | `/auction-houses/{id}` | Get one auction house | All roles |
| GET | `/auction-houses/{id}/consignments` | List consignments of an auction house | All roles |
| POST | `/recovery-cases/{id}/consignments` | Consign the collateral to an auction house; reserve price computed at creation | RecoveryManager |
| GET | `/recovery-cases/{id}/consignments` | List consignments of a case | All roles |
| GET | `/consignments/{id}` | Get one consignment | All roles |
| POST | `/consignments/{id}/list` | List a `DRAFT` consignment with a closed auction window | Auctioneer |
| POST | `/consignments/{id}/relist` | Relist an `UNSOLD` consignment with a markdown reserve | Auctioneer |
| POST | `/consignments/{id}/report-sale` | Report a hammer price at or above reserve; creates the sale record | Auctioneer |
| POST | `/consignments/{id}/report-unsold` | Report the vehicle did not sell | Auctioneer |
| GET | `/consignments/{id}/sale-records` | List sale records of a consignment (at most one non-`VOID`) | All roles |
| POST | `/sale-records/{id}/certify` | Compliance certifies the sale as commercially reasonable | ComplianceOfficer |
| GET | `/recovery-cases/{id}/deficiency-estimate` | Provisional deficiency estimate (projected proceeds from reserve) | All roles |
| POST | `/recovery-cases/{id}/deficiency-notices` | Create a deficiency notice with the final settled figures | RecoveryManager |
| GET | `/recovery-cases/{id}/deficiency-notices` | List deficiency notices of a case | All roles |
| POST | `/deficiency-notices/{id}/send` | Send the deficiency notice within the statutory 30-day window | RecoveryManager |
| POST | `/deficiency-notices/{id}/dispute` | Borrower disputes the deficiency amount | Borrower |
| POST | `/deficiency-notices/{id}/revise` | Manager revises a disputed notice, adjusting the amount | RecoveryManager |
| POST | `/deficiency-notices/{id}/waive` | Compliance waives the deficiency | ComplianceOfficer |
| POST | `/deficiency-notices/{id}/record-payment` | Borrower pays toward the deficiency | Borrower |
| POST | `/recovery-cases/{id}/complaints` | Borrower files a complaint; freezes the case into review | Borrower |
| GET | `/recovery-cases/{id}/complaints` | List complaints of a case | All roles |
| POST | `/complaints/{id}/resolve` | Compliance resolves a complaint; an upheld outcome triggers restitution | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock, applying every due automatic transition | RecoveryManager, ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is defined where its guarded workflow is described in §2 and §3; this catalogue is a reference of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_CASE_STATE` | 409 |
| `ERR_INVALID_ASSIGNMENT_STATE` | 409 |
| `ERR_INVALID_QUOTE_STATE` | 409 |
| `ERR_INVALID_ITEM_STATE` | 409 |
| `ERR_INVALID_CONSIGNMENT_STATE` | 409 |
| `ERR_INVALID_SALE_STATE` | 409 |
| `ERR_INVALID_DEFICIENCY_STATE` | 409 |
| `ERR_INVALID_COMPLAINT_STATE` | 409 |
| `ERR_DUPLICATE_OPEN_CASE` | 409 |
| `ERR_FIELD_WINDOW_OVERLAP` | 409 |
| `ERR_AUCTION_WINDOW_OVERLAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_DEFICIENCY_WINDOW_EXPIRED` | 422 |
| `ERR_PROPERTY_RETENTION_ACTIVE` | 422 |
| `ERR_AGENT_SUSPENDED` | 422 |
| `ERR_AGENT_LICENSE_MISMATCH` | 422 |
| `ERR_AGENT_CAPACITY_EXCEEDED` | 422 |
| `ERR_NO_ELIGIBLE_AGENT` | 422 |
| `ERR_PAYMENT_INSUFFICIENT` | 422 |
| `ERR_BID_BELOW_RESERVE` | 422 |
| `ERR_INTERNAL` | 500 |

# Campus Card & Meal Plan Management API — Product Requirements Document

## 1. Introduction

The campus card office sits at an awkward intersection of domains that rarely share a single system: physical credential issuance, meal plan administration, declining-balance money movement, building access control, and an off-campus merchant program with its own settlement cycle. Each of these domains currently runs on its own calendar and its own notion of who the customer is, and the seams show up as real operational pain — a stolen card reported to the card office does not freeze the student's dining dollars, a mid-term meal plan change is prorated by hand and frequently disputed, and end-of-term refunds stall because no one can tell which residual balances are encumbered by open transaction disputes.

This document specifies a unified Campus Card & Meal Plan Management API that closes those seams. The system governs the full lifecycle of a card holder's relationship with the university: registration and card issuance with photo verification, meal plan enrollment gated by housing status and holder type, weekly swipe accounting and dining-dollar balances, door access privileges granted by zone and schedule, declining-balance funding with term-end refund or forfeiture, lost and stolen card handling with fraud escalation, merchant onboarding with commission-bearing settlement, and a dispute workflow with provisional credit and segregation of duties. All monetary state is derived from an append-only ledger, and all temporal behavior — term boundaries, weekly swipe resets, plan change effective weeks, dispute filing windows — is evaluated against a single logical clock rather than wall-clock time, so that every workflow is deterministic and replayable.

The audience for this document is the engineering team building the service. Section 2 defines the system-wide contracts that apply uniformly to every endpoint; Section 3 walks the business workflows in narrative form and is the authoritative source for every rule, threshold, and state transition; Section 4 tabulates the HTTP surface; Section 5 catalogues the error codes. All business endpoints are mounted under the `/api` prefix, with a single administrative clock endpoint mounted outside it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role string the system does not declare, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). If the headers are well-formed but the named role is not in the calling endpoint's authorized role list, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The system recognizes exactly ten roles, spelled as follows: `PlatformAdmin`, `CardOfficeAdmin`, `CardHolder`, `DiningServicesManager`, `BursarOffice`, `FraudAnalyst`, `SecurityOfficer`, `MerchantUser`, `PointOfSale`, and `DoorController`.

Two of these roles are **entity-backed**, meaning `X-User-ID` is not merely an operator label but the `id` of a persisted resource, and ownership checks are enforced against it:

- When `X-User-Role` is `CardHolder`, `X-User-ID` is the `id` of the acting `CardHolder`; ownership checks on any resource that references a `CardHolder` (a card, an enrollment, an account, a dispute, a refund request) compare the resource's holder linkage field to `X-User-ID`. A holder calling an owner-scoped endpoint against another holder's resource — including list filters that name another holder's id — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `MerchantUser`, `X-User-ID` is the `id` of the acting `Merchant`; ownership checks on any resource that references a `Merchant` compare the resource's merchant linkage field to `X-User-ID`, and list filters naming another merchant's id are equally rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining eight roles are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity. For `PlatformAdmin`, `CardOfficeAdmin`, `DiningServicesManager`, `BursarOffice`, `FraudAnalyst`, `SecurityOfficer`, `PointOfSale`, and `DoorController`, the server may record the identifier where a workflow calls for it — for example as `reviewed_by` on a photo review, `decided_by` on a plan change decision, `granted_by` on an access grant, `last_adjusted_by` on an account, `granter_analyst_id` or `resolver_analyst_id` on a dispute, or `submitted_by`, `approved_by`, and `paid_by` on refund requests and settlements — but it never compares the value to any entity's `id` for ownership purposes. Segregation-of-duties checks, however, do compare these recorded operator identifiers against one another, as described in §3.7 and §3.9.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — card holders, campus cards, photo submissions, terms, meal plans, enrollments, plan change requests, declining-balance accounts, card transactions, disputes, refund requests, door zones, access grants, merchants, and merchant settlements — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, and that underpins optimistic concurrency control where declared.

Two resources are deliberate exceptions. A `LedgerEntry` and an `AccessEvent` are immutable event records: each carries only `id` and `created_at`, and neither `updated_at` nor `version` exists on them. They are written once and never modified.

### 2.5. The Logical Clock

The system does not consult wall-clock time for any business decision. All temporal evaluation — term boundaries, week indexes, dispute windows, card and grant expiry, proration day counts — reads a single server-maintained **logical clock**. At server startup, before any explicit set, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time.

A `PlatformAdmin` may advance the logical clock through an administrative capability that accepts a `to_iso8601` instant and responds with the new `current_utc`. Advancing the clock does not eagerly rewrite any resource; instead, cards and access grants whose expiry has passed are flipped to `EXPIRED` lazily, the next time a transaction, access attempt, or grant action touches them (see §3.2 and §3.8).

### 2.6. Monetary Representation and Rounding

All monetary values in the system are represented as integer cents — prices, allocations, charges, credits, balances, fees, commissions, and refund amounts alike. Wherever a calculation produces a fractional cent, the result is rounded **half up** to the nearest whole cent. Where a calculation produces several monetary components, each component is rounded exactly once, independently, in the evaluation order the relevant workflow pins (see §3.4 and §3.9); there is no second rounding pass over a sum of already-rounded components. Counts such as swipes, weeks, and fraud strikes are plain integers with no rounding.

### 2.7. The Ledger as the System of Record

Every declining-balance account's `balance_cents` is a **derived value**: it is never set directly by any client, and it is recomputed after every ledger posting as the signed sum of the account's `LedgerEntry` rows. Each entry carries an `entry_type`, an unsigned `amount_cents` strictly greater than zero, a human-readable `description`, and a per-account `entry_sequence` that increases monotonically starting at 1. The direction of an entry is pinned by its type: the credit types are `FUND`, `ALLOCATION_GRANT`, `PRORATION_CREDIT`, `PROVISIONAL_CREDIT`, `ADJUSTMENT_CREDIT`, and `PURCHASE_REVERSAL`; the debit types are `PURCHASE`, `FEE`, `PRORATION_DEBIT`, `ADJUSTMENT_DEBIT`, `PROVISIONAL_CLAWBACK`, `REFUND_PAYOUT`, and `FORFEIT`. Replaying the account's entries in ascending `created_at` order, with ties in `created_at` broken by ascending `entry_sequence`, the balance equals the sum of credit amounts minus the sum of debit amounts; each entry's `running_balance_cents` stores the balance immediately after that entry in that replay order.

Two invariants follow. First, at all times and for every account, `balance_cents` equals the signed ledger sum — a purchase of a given amount paired with its `PURCHASE_REVERSAL` of the same amount (posted directly, or made permanent through a provisional credit) leaves the balance identical to what it was before the purchase. Second, only `FEE`, `PRORATION_DEBIT`, and `ADJUSTMENT_DEBIT` entries may drive a balance negative; purchases may not, because a purchase that exceeds the available balance is rejected rather than posted (§3.5).

Entries that arise from card activity carry a `reference_transaction_id` — this is set on `PURCHASE`, `PURCHASE_REVERSAL`, `PROVISIONAL_CREDIT`, and `PROVISIONAL_CLAWBACK` entries and is null otherwise — and entries arising from dispute credit activity additionally carry a `reference_dispute_id`, set on `PROVISIONAL_CREDIT` and `PROVISIONAL_CLAWBACK` and null otherwise. The ledger can be listed with filters on `account_id`, `reference_transaction_id`, `reference_dispute_id`, and `entry_type`, and individual entries can be fetched by id, by `PlatformAdmin`, `CardOfficeAdmin`, `BursarOffice`, `FraudAnalyst`, and the owning `CardHolder`.

### 2.8. Idempotency of Value-Moving Requests

Two value-moving creations accept a client-supplied `idempotency_key`: posting a card transaction and posting an account funding. When an `idempotency_key` is seen for the first time, the request is processed normally. When the same key is presented again with an identical payload, the server replays the original 201 response without performing the operation a second time. When the same key is presented with a divergent payload, the request is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

### 2.9. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control on a parent resource's `version`; no other endpoint accepts a version field:

- Requesting a meal plan change against an enrollment requires the request body to carry `expected_enrollment_version`, the enrollment `version` the client last observed. If the enrollment's current `version` has advanced past that value — for example because a swipe purchase in the meantime bumped it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since the proration basis the client saw is stale and the request must be re-based on a fresh read.
- Posting a manual adjustment to a declining-balance account requires `expected_account_version` matching the account's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the adjustment decision was made against a stale `balance_cents`.
- Issuing a card replacement requires `expected_card_version` matching the card's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening photo review or lost/stolen report may have changed the fraud-relevant state the fee schedule depends on.

### 2.10. Validation Priority Order

When a request violates several rules at once, the error that surfaces is determined by a fixed priority order, evaluated from first to last:

1. **Authentication context** — `X-User-ID` and `X-User-Role` are present and the role is declared, else `ERR_MISSING_AUTH_CONTEXT` (401). Applies to all endpoints.
2. **Role permission** — the caller's role is in the endpoint's authorized list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to all endpoints.
3. **Ownership** — entity-backed callers (`CardHolder`, `MerchantUser`) act only on resources they own, including owner-naming list filters, else `ERR_NOT_RESOURCE_OWNER` (403). Applies to owner-scoped endpoints: card report-lost, report-stolen, and unfreeze; photo submission; plan change creation and withdrawal; account funding; refund request creation; dispute creation and withdrawal; merchant settlement creation and submission; and owner reads.
4. **Body well-formedness** — required fields present, types correct, enum values in range, `amount_cents` positive (exactly zero for a meal swipe), end after start, dates parseable, and `rejection_reason` or `denial_reason` present where the action requires one, else `ERR_VALIDATION` (400). Applies to all mutating endpoints.
5. **Path existence** — path identifiers resolve to existing resources, validated left to right, else `ERR_NOT_FOUND` (404).
6. **Body reference existence** — ids referenced in the body (such as `plan_id`, `term_id`, `zone_id`, `card_id`) exist, else `ERR_NOT_FOUND` (404).
7. **Idempotency** — a reused `idempotency_key` with a divergent payload, else `ERR_IDEMPOTENCY_CONFLICT` (409).
8. **State transition legality** — the target resource's state permits the requested transition, including terminal-state lockout, invalid-from rejection, and any state-machine precondition, else `ERR_INVALID_STATE_TRANSITION` (409).
9. **Optimistic concurrency** — the declared `expected_<parent>_version` matches the parent's current `version`, else `ERR_STALE_VERSION` (412), on the three OCC-guarded endpoints named in §2.9.
10. **Cross-entity referenced state** — the states of related resources permit the action: term open where required (`ERR_TERM_NOT_OPEN`), card active or frozen (`ERR_CARD_NOT_ACTIVE`, `ERR_CARD_FROZEN`), photo approved for non-provisional activation (`ERR_PHOTO_NOT_APPROVED`), plan published (`ERR_PLAN_NOT_PUBLISHED`), merchant active (`ERR_MERCHANT_NOT_ACTIVE`), enrollment active (`ERR_ENROLLMENT_NOT_ACTIVE`), account open (`ERR_ACCOUNT_FROZEN`), account close-pending for refunds (`ERR_ACCOUNT_NOT_CLOSABLE`), holder active (`ERR_HOLDER_NOT_ACTIVE`) — all HTTP 409.
11. **Fraud and segregation of duties** — suspended or fraud-flagged holders blocked from value-extending actions (`ERR_FRAUD_HOLD`, 409); the refund approver differing from the account's last adjuster (`ERR_SOD_ADJUSTER_CANNOT_APPROVE`, 403); refund and settlement payers differing from their approvers (`ERR_SOD_PAYER_IS_APPROVER`, 403); the settlement approver differing from the submitter (`ERR_SOD_APPROVER_IS_SUBMITTER`, 403); the dispute resolver differing from the provisional-credit granter (`ERR_SOD_RESOLVER_IS_GRANTER`, 403); provisional credit limited to non-swipe tenders (`ERR_CREDIT_NOT_APPLICABLE`, 422).
12. **Temporal windows** — plan changes requested or approved on or before the add/drop deadline (`ERR_PLAN_CHANGE_WINDOW_CLOSED`), disputes filed within the filing window (`ERR_DISPUTE_WINDOW_CLOSED`), term opened no earlier than its start (`ERR_TERM_NOT_YET_STARTED`), term closed no earlier than its end (`ERR_TERM_NOT_ENDED`), week advancement bounded by the term's length (`ERR_TERM_WEEKS_EXHAUSTED`), and change effective weeks inside the term (`ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID`) — all HTTP 422.
13. **Uniqueness and eligibility** — natural keys unique (`ERR_DUPLICATE_NATURAL_KEY`), one non-terminal card per holder (`ERR_ACTIVE_CARD_EXISTS`), one live enrollment per holder and term (`ERR_ENROLLMENT_OVERLAP`), housing and holder-type plan eligibility (`ERR_HOUSING_INELIGIBLE_FOR_PLAN`, `ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN`), no pending change request (`ERR_PENDING_CHANGE_EXISTS`), no pending refund request (`ERR_PENDING_REFUND_EXISTS`), no open dispute per transaction (`ERR_DISPUTE_ALREADY_OPEN`), account uniqueness per holder, type, and term (`ERR_ACCOUNT_UNIQUENESS`), grant interval overlap (`ERR_GRANT_OVERLAP`), settlement period overlap (`ERR_SETTLEMENT_PERIOD_OVERLAP`), settlement period inside the term (`ERR_PERIOD_OUTSIDE_TERM`), and transactions not locked in an approved or paid settlement (`ERR_TX_NOT_DISPUTABLE`).
14. **Funds and thresholds** — purchase amounts covered by the account balance (`ERR_INSUFFICIENT_FUNDS`, 402), swipe availability (`ERR_SWIPES_EXHAUSTED`, 422), the provisional daily cap (`ERR_PROVISIONAL_DAILY_CAP`, 422), and the minimum refund amount (`ERR_REFUND_BELOW_MINIMUM`, 422).

The practical consequence of this ordering is that, for example, a malformed body surfaces as `ERR_VALIDATION` before any state check runs, and an ownership violation surfaces before the body is examined at all.

### 2.11. Nested Resource Retrieval

For any endpoint whose path contains more than one resource identifier, the server validates path identifiers strictly left to right. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no further identifiers or business rules are examined. A request to act on a card under a non-existent card holder therefore fails on the holder id before the card id is ever considered.

### 2.12. Mutation Semantics

Every state-changing action on a resource — activation, freezing, review, lifecycle transitions, postings that touch derived fields — increments that resource's `version` by 1 and refreshes its `updated_at`. Where an action cascades into child or sibling resources (a suspension freezing accounts, a replacement revoking grants), each mutated resource observes its own version increment and timestamp refresh. The immutable event resources of §2.4 are the only exceptions, having neither field.

## 3. Business Logic & Workflows

### 3.1. Card Holder Registration, Card Issuance, and Photo Verification

Everything begins with the card holder. A `CardOfficeAdmin` registers a new holder by supplying the university-issued `university_id`, the holder's `full_name` and `email`, a `holder_type` of `STUDENT_RESIDENT`, `STUDENT_COMMUTER`, `FACULTY`, `STAFF`, or `AFFILIATE`, and a `housing_status` of `ON_CAMPUS`, `COMMUTER`, or `OFF_CAMPUS`. The `university_id` is a natural key: a duplicate submission is rejected with `ERR_DUPLICATE_NATURAL_KEY`. A new holder starts with `status` `ACTIVE`, a `fraud_strike_count` of 0, and `fraud_flag` false. The holder roster can be listed with filters on `holder_type`, `status`, `housing_status`, and `university_id`; a holder record can be read by administrative roles, and a `CardHolder` caller may read only their own record.

With a holder registered, a `CardOfficeAdmin` issues a campus card, providing an `expires_at` instant that must lie in the future at issuance. The server mints a unique 16-digit `card_number` and links the card to its holder via `holder_id` taken from the creation path. A holder may possess **at most one non-terminal card** at any time: issuing while the holder already holds a card that is not `REPLACED`, `EXPIRED`, or `DEACTIVATED` is rejected with `ERR_ACTIVE_CARD_EXISTS`. A fresh card starts with `lifecycle_status` `PENDING_PHOTO`, `photo_status` `NOT_SUBMITTED`, `is_provisional` true, `replacement_fee_cents` 0, `lost_or_stolen_report_count` 0, and a null `replaced_by_card_id`. Cards can be listed with filters on `holder_id`, `lifecycle_status`, and `replaced_by_card_id`.

The card's lifecycle dimension (`lifecycle_status`: `PENDING_PHOTO`, `ACTIVE`, `LOST_FROZEN`, `STOLEN_FROZEN`, `REPLACED`, `EXPIRED`, `DEACTIVATED`) and its photo dimension (`photo_status`: `NOT_SUBMITTED`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`) are **parallel and independent**; each has its own rules, and neither implies the other.

The holder — and only the holder, on their own card — submits a photo by supplying an opaque `image_ref`. Submission is accepted only while the card's `lifecycle_status` is `PENDING_PHOTO`, `ACTIVE`, or `LOST_FROZEN`; any other lifecycle state is rejected with `ERR_INVALID_STATE_TRANSITION`. Each submission creates a `PhotoSubmission` whose `review_status` starts at `PENDING_REVIEW`, moves the card's `photo_status` to `PENDING_REVIEW`, and bumps the card's `version`. Submissions are ordered by a `submission_sequence`, a 1-based ordinal assigned in `created_at` order among the card's submissions, and a card's submissions can be listed by a `CardOfficeAdmin` or the owning holder.

A `CardOfficeAdmin` then reviews the card's **latest** pending submission — the one with the highest `submission_sequence`; earlier submissions are not reviewable, and attempting to review a submission that is not pending review is rejected as an invalid state transition. The review carries a `decision` of `APPROVED` or `REJECTED`. Rejection requires a `rejection_reason`; omitting it is rejected with `ERR_VALIDATION`. The reviewer's `X-User-ID` is recorded as `reviewed_by`, and the outcome mirrors onto the card's `photo_status` (`PENDING_REVIEW` → `APPROVED` or `PENDING_REVIEW` → `REJECTED`), bumping the card's `version`. Approval additionally clears a provisional card's `is_provisional` to false. A rejected photo is not the end of the road: the holder may submit again, cycling `REJECTED` → `PENDING_REVIEW` without bound.

Activation moves a card `PENDING_PHOTO` → `ACTIVE` and is performed by a `CardOfficeAdmin`. Three preconditions guard it: the holder's `status` must be `ACTIVE` (otherwise `ERR_HOLDER_NOT_ACTIVE`); the card's `photo_status` must be `APPROVED`, unless the caller deliberately passes `allow_provisional` as true (otherwise `ERR_PHOTO_NOT_APPROVED`); and the logical clock must read earlier than the card's `expires_at` (otherwise `ERR_INVALID_STATE_TRANSITION`). A card activated on an approved photo carries `is_provisional` false; one activated through `allow_provisional` carries `is_provisional` true until a photo is later approved. Provisional cards are second-class citizens: their spending is subject to a daily cap (§3.5), and door readers deny them (§3.8).

### 3.2. Card Loss, Theft, Replacement, and Fraud Escalation

When a holder misplaces a card, the holder reports it lost. Reporting moves the card `ACTIVE` → `LOST_FROZEN`, increments the card's `lost_or_stolen_report_count` by 1, and suspends every `ACTIVE` access grant on the card with `suspended_reason` `CARD_FROZEN`. Only the owning holder may file the report; anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. A lost card that turns up can be unfrozen by its owner: unfreezing moves `LOST_FROZEN` → `ACTIVE`, provided the holder's `status` is `ACTIVE` (otherwise `ERR_HOLDER_NOT_ACTIVE`), and restores every grant suspended with `suspended_reason` `CARD_FROZEN` back to `ACTIVE`. Unfreezing is defined only for a lost-frozen card — attempting it on a `STOLEN_FROZEN` card or any terminal card is rejected with `ERR_CARD_NOT_RECOVERABLE`.

Theft is treated more harshly. The owner reports the card stolen, optionally supplying a `police_report_number`, which is recorded on the card as `stolen_police_report_number` when supplied. The report moves the card to `STOLEN_FROZEN` from either `ACTIVE` or `LOST_FROZEN`, increments `lost_or_stolen_report_count`, and suspends the card's `ACTIVE` grants with `suspended_reason` `CARD_FROZEN`, exactly as a lost report does. But a stolen report also fires a four-link cascade. First, the holder's `fraud_strike_count` increments by 1. Second, when the count reaches or exceeds the suspension threshold of **3 strikes** — the boundary is inclusive, so exactly the third strike suspends — the holder's `status` flips to `SUSPENDED` and `fraud_flag` is set true. Third, that suspension freezes every `OPEN` declining-balance account of the holder with `frozen_reason` `HOLDER_SUSPENDED` and deactivates the holder's remaining non-terminal cards, revoking each such card's grants. Fourth, independently of the strike count, the holder's `OPEN` accounts are frozen with `frozen_reason` `CARD_STOLEN` (an account already `FROZEN` stays as it is). A stolen card never unfreezes; account thaws are cascade-only, with reinstatement or fraud review restoring accounts frozen under `HOLDER_SUSPENDED` (see §3.7's fraud-review discussion below and the withdrawal cascade in this section).

The fraud strike ledger is shared with the dispute workflow: a dispute resolved in the merchant's favor on a transaction filed under `UNAUTHORIZED_USE` likewise adds one strike (§3.6), and the same inclusive threshold of 3 applies.

A `CardOfficeAdmin` or `FraudAnalyst` may also suspend a holder directly, moving the holder `ACTIVE` → `SUSPENDED` with the full suspension cascade: every `OPEN` account of the holder freezes with `frozen_reason` `HOLDER_SUSPENDED`, and every card of the holder in `ACTIVE`, `LOST_FROZEN`, or `STOLEN_FROZEN` is `DEACTIVATED`, each deactivation revoking that card's non-terminal grants. When the suspension was driven by the strike threshold rather than a manual action, `fraud_flag` is set true as part of the transition.

A suspended holder can be reinstated to `ACTIVE` by a `CardOfficeAdmin`, but only when `fraud_flag` is false — if the flag is set, reinstatement is rejected with `ERR_FRAUD_HOLD`, and a fraud review must run first. A fraud review, performed by a `FraudAnalyst` who may attach optional `notes`, resets `fraud_strike_count` to 0 and clears `fraud_flag`, and restores accounts frozen under `HOLDER_SUSPENDED` to `OPEN`; reinstatement proper performs the same account restoration when moving `SUSPENDED` → `ACTIVE`. A `WITHDRAWN` holder can likewise be reinstated to `ACTIVE`, with no preconditions and no side effects. `GRADUATED` is terminal and admits no reinstatement.

A `CardOfficeAdmin` processing a mid-term departure withdraws the holder (`ACTIVE` → `WITHDRAWN`), and graduation (`ACTIVE` → `GRADUATED`) applies the identical cascade. Both cascades do three things: every enrollment of the holder in `ASSIGNED` moves to `CANCELLED` with no credit, and every enrollment in `ACTIVE` moves to `CANCELLED` with a cancellation credit computed and posted as a `PRORATION_CREDIT` to the holder's term `DINING_DOLLARS` account, recomputing its `balance_cents` (the credit formula lives in §3.4); every account of the holder in `OPEN` or `FROZEN` moves to `CLOSE_PENDING`; and every plan change request in `SUBMITTED` or `APPROVED` on those enrollments is voided with `void_reason` `ENROLLMENT_CANCELLED`.

Replacement is how any card — `ACTIVE`, `LOST_FROZEN`, `STOLEN_FROZEN`, or even still `PENDING_PHOTO` — is retired in favor of a successor. A `CardOfficeAdmin` requests the replacement with a `reason` of `LOST`, `STOLEN`, or `DAMAGED`, an optional `police_report_number`, an optional `surrendered` flag, and the OCC field `expected_card_version` (§2.9). The old card becomes `REPLACED`, its `replaced_by_card_id` points at the new card, and every grant of the old card in `ACTIVE` or `SUSPENDED` is `REVOKED` (a card replaced from `PENDING_PHOTO` has no grants to revoke). The new card is minted for the same holder with `expires_at` inherited from the old card: if the old card's `photo_status` was `APPROVED`, the successor is created already `ACTIVE` with `is_provisional` false; otherwise it starts at `PENDING_PHOTO` with `photo_status` `NOT_SUBMITTED`.

The replacement fee follows a tiered schedule and is computed on the new card as its `replacement_fee_cents`. Let the **ordinal** be 1 plus the count of the holder's other cards already in `REPLACED`; the base tier fee is 2500 cents for the first replacement, 3500 cents for the second, and 5000 cents for the third and every subsequent one. The rules apply in strict order: (1) a `FACULTY` or `STAFF` holder's first replacement is free — fee 0 — though the ordinal is still consumed; (2) a `STOLEN` replacement with a police report — either recorded as the old card's `stolen_police_report_number` or supplied on the replacement payload — is free; (3) a `STOLEN` replacement without a police report costs double the tier fee (a surcharge multiplier of 2); (4) a `DAMAGED` replacement with `surrendered` true costs the tier fee less a 1500-cent surrender discount, floored at 0; (5) every other case — `LOST`, or `DAMAGED` without surrender — pays the tier fee. The fee posts as a `FEE` ledger entry to the holder's `CAMPUS_CASH` account, which is auto-created `OPEN` when none exists, and a `FEE` entry is one of the few entry types permitted to drive a balance negative. A first issuance, of course, charges nothing — `replacement_fee_cents` is 0 on any card that is not itself a replacement.

Finally, a `CardOfficeAdmin` or `FraudAnalyst` may permanently deactivate any non-terminal card (`PENDING_PHOTO`, `ACTIVE`, `LOST_FROZEN`, or `STOLEN_FROZEN` → `DEACTIVATED`); deactivation revokes the card's grants (`ACTIVE` or `SUSPENDED` → `REVOKED`), and a `PENDING_PHOTO` card has no grants to revoke. Separately, a card whose `expires_at` has passed expires lazily: the first transaction or access attempt that touches it with the clock at or after `expires_at` flips it `ACTIVE` → `EXPIRED`, the triggering transaction fails with `ERR_CARD_NOT_ACTIVE`, and the triggering access attempt is recorded `DENIED` with `deny_reason` `CARD_NOT_ACTIVE`.

### 3.3. Terms and the Meal Plan Catalogue

A `DiningServicesManager` defines the academic calendar's financial skeleton by creating a **term** with a unique `term_code` (duplicates rejected with `ERR_DUPLICATE_NATURAL_KEY`), a display `name`, a `start_date` and `end_date` in UTC with the start strictly before the end, an `add_drop_deadline` that must fall on or after `start_date` and on or before `end_date`, a `total_weeks` count of weekly swipe periods of at least 1, and a `proration_mode` of `WEEKLY` or `DAILY` that selects the proration variant used by every enrollment in the term. A term starts `SCHEDULED` with `current_week_index` 0 and progresses through `OPEN` and `CLOSED` to `SETTLED`; terms can be listed with a `status` filter.

The meal plan catalogue is likewise managed by the `DiningServicesManager`. Each plan carries a unique `plan_code`, a display `name`, a `weekly_swipe_allowance` of zero or more swipes per week (ignored when `is_unlimited_swipes` is true, which itself defaults to false), a `dining_dollar_allocation_cents` of zero or more granted at activation, a full-term `price_cents` strictly greater than zero, a `requires_on_campus_housing` flag defaulting to false, and a non-empty `eligible_holder_types` list drawn from the holder-type enum. Plans are created in `DRAFT`, move to `PUBLISHED` when published, and a published plan can be retired to `RETIRED` only while no enrollment in `ASSIGNED` or `ACTIVE` references it — otherwise the retire is rejected with `ERR_PLAN_IN_USE`. Plans can be listed with a `status` filter.

### 3.4. Enrollment, Activation Pricing, and Plan Changes

A `DiningServicesManager` assigns a meal plan to a holder by posting the target `plan_id` and `term_id`; the holder is taken from the creation path, and the body-referenced plan and term must exist. Eligibility is enforced at assignment: the holder must be `ACTIVE` (`ERR_HOLDER_NOT_ACTIVE`); the plan must be `PUBLISHED` (`ERR_PLAN_NOT_PUBLISHED`); a plan with `requires_on_campus_housing` true admits only holders whose `housing_status` is `ON_CAMPUS` (`ERR_HOUSING_INELIGIBLE_FOR_PLAN`); and the holder's `holder_type` must appear in the plan's `eligible_holder_types` (`ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN`). A holder may have at most one enrollment in `ASSIGNED` or `ACTIVE` per term; a second live enrollment in the same term is rejected with `ERR_ENROLLMENT_OVERLAP`.

The enrollment's initial status depends on the term: `ASSIGNED` while the term is `SCHEDULED`, or `ACTIVE` immediately when the term is already `OPEN`. Activation — whether immediate or in bulk at term open — prices the enrollment forward-looking from the activation moment, computes both the charge and the dining-dollar grant, and pins their evaluation order: the charge first, then the grant, each rounded half-up to whole cents exactly once, independently.

- Under the `WEEKLY` variant, the number of remaining weeks is the term's `total_weeks` minus the current `current_week_index` plus 1 — the current week always counts as fully remaining. The `charge_cents` is the plan's `price_cents` multiplied by the remaining weeks and divided by `total_weeks`, rounded half-up to whole cents; the grant is the plan's `dining_dollar_allocation_cents` multiplied by the remaining weeks and divided by `total_weeks`, rounded half-up the same way.
- Under the `DAILY` variant, the term's total days are the calendar days from `start_date` through `end_date` inclusive; the days consumed are the calendar days elapsed since `start_date`, never below zero; and the remaining days are the total minus the consumed. Charge and grant are the plan's `price_cents` and `dining_dollar_allocation_cents` respectively multiplied by the remaining days and divided by the total days, each rounded half-up to whole cents. A mid-week activation under `DAILY` therefore charges less than the same activation under `WEEKLY`.

Activation also snapshots the plan's `weekly_swipe_allowance` and `is_unlimited_swipes` onto the enrollment (later plan edits do not disturb live enrollments), records the term's `current_week_index` as `enrolled_week_index`, stamps `activated_at`, and posts the grant as an `ALLOCATION_GRANT` ledger entry to the holder's `DINING_DOLLARS` account for that term, auto-creating the account `OPEN` when none exists and recomputing its `balance_cents`. A grant of zero posts no entry at all — ledger entries always carry a strictly positive `amount_cents`. The `charge_cents` of an enrollment remains null until it is `ACTIVE`, and its `credit_cents` starts at 0.

Opening a term is a `DiningServicesManager` action gated on the logical clock reading at or after the term's `start_date` (otherwise `ERR_TERM_NOT_YET_STARTED`). Opening sets `current_week_index` to 1 and activates every `ASSIGNED` enrollment of the term exactly as above — charge computed, `ALLOCATION_GRANT` posted, dining account auto-created where absent.

Cancelling an enrollment (a `DiningServicesManager` action, or the withdraw/graduate cascade of §3.2, or term close in §3.7) behaves differently by state. Cancelling an `ASSIGNED` enrollment posts nothing, because nothing was charged; any pending change request on it is voided with `void_reason` `ENROLLMENT_CANCELLED` — a pairing that cannot occur from `ASSIGNED` in practice, pinned here for completeness. Cancelling an `ACTIVE` enrollment computes a cancellation credit: the consumed measure is, under `WEEKLY`, the term's `current_week_index` minus the enrollment's `enrolled_week_index`, never below zero (the current week is not charged), or under `DAILY`, the calendar days elapsed since `activated_at`; the earned amount is the plan's `price_cents` multiplied by the consumed measure and divided by `total_weeks` under `WEEKLY`, or multiplied by the consumed days capped at the term's total days and divided by that total under `DAILY`, each rounded half-up to whole cents. The credit is the enrollment's `charge_cents` minus the earned amount, floored at zero, and is recorded as `credit_cents` and posted as a `PRORATION_CREDIT` to the enrollment-linked `DINING_DOLLARS` account when it is positive, recomputing the account's `balance_cents`. Any change request in `SUBMITTED` or `APPROVED` on the enrollment is voided with `void_reason` `ENROLLMENT_CANCELLED`.

Holders themselves drive **plan changes**. The owning holder submits a change request against their enrollment, naming a `new_plan_id` and carrying `expected_enrollment_version` for the OCC check of §2.9. The enrollment must be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`), the term must be `OPEN` and the clock must read on or before the term's `add_drop_deadline` (`ERR_PLAN_CHANGE_WINDOW_CLOSED`), the new plan must differ from the enrollment's current plan (`ERR_VALIDATION`), the new plan must pass the same housing and holder-type eligibility rules as a fresh enrollment, and no other change request in `SUBMITTED` or `APPROVED` may exist on the enrollment (`ERR_PENDING_CHANGE_EXISTS`). Submitting a change request is itself a mutation of the enrollment and bumps its `version` — which is precisely what a second, stale client will trip over at the OCC check. The new request starts `SUBMITTED` with `requested_by` set to the holder's `X-User-ID`, and an enrollment's change requests can be listed, as can the global change-request feed with filters on `enrollment_id`, `new_plan_id`, and `status`.

A `DiningServicesManager` approves or denies. Denial requires a `denial_reason` (`ERR_VALIDATION` otherwise) and records `decided_by`. Approval checks the window again — the clock must still read on or before the `add_drop_deadline` (`ERR_PLAN_CHANGE_WINDOW_CLOSED`), the term must be `OPEN` (`ERR_TERM_NOT_OPEN`), and the term's `current_week_index` plus 1 must not exceed `total_weeks` (`ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID`) — then sets `effective_week_index` to `current_week_index` plus 1, computes and stores `charge_delta_cents` and `funding_delta_cents` (both null until the request is `APPROVED`), records `decided_by`, and defers all money movement to week advancement. The proration follows a mandatory five-step order that breaks the apparent circle between the credit from the old plan and the charge owed on the new plan. Let W be the `effective_week_index` and T the term's `total_weeks`:

1. The old plan's earned amount: under `WEEKLY`, the old plan's `price_cents` multiplied by W minus 1 and divided by T, rounded half-up; under `DAILY`, the old plan's `price_cents` multiplied by the calendar days elapsed since `start_date` and divided by the term's total days, rounded half-up.
2. The credit from the old plan: the old enrollment's `charge_cents` minus that earned amount — possibly zero, never negative here.
3. The new plan's due amount: under `WEEKLY`, the new plan's `price_cents` multiplied by T minus W plus 1 and divided by T, rounded half-up; under `DAILY`, the new plan's `price_cents` multiplied by the term's total days minus the elapsed days and divided by the total days, rounded half-up.
4. `charge_delta_cents` is the new due minus the credit from the old plan — a signed value.
5. `funding_delta_cents`: under `WEEKLY`, the new plan's `dining_dollar_allocation_cents` multiplied by T minus W plus 1 and divided by T, rounded half-up; under `DAILY`, that allocation multiplied by the remaining days and divided by the total days, rounded half-up.

The old plan's already-granted dining allocation is **not** clawed back. A holder may also withdraw their own `SUBMITTED` request (`SUBMITTED` → `WITHDRAWN`); anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`.

Nothing moves until the `DiningServicesManager` advances the term's week. Advancing requires `current_week_index` strictly below `total_weeks` (otherwise `ERR_TERM_WEEKS_EXHAUSTED`) and runs three pinned steps: first `current_week_index` increments by 1; second, every `ACTIVE` enrollment of the term has its `swipes_used_this_week` reset to 0; third, every change request in `APPROVED` whose `effective_week_index` equals the new week index executes, in ascending `created_at` order. Execution of each request re-checks its preconditions: the parent enrollment must still be `ACTIVE`, and when the stored `charge_delta_cents` is positive, the holder's `CAMPUS_CASH` `balance_cents` must cover it. On success, the old enrollment becomes `SUPERSEDED` with `credit_cents` set to its `charge_cents` minus the old plan's earned amount; a successor enrollment is created `ACTIVE` with `supersedes_enrollment_id` pointing at the old enrollment, the new plan, `enrolled_week_index` equal to the `effective_week_index`, `swipes_used_this_week` at 0 (post-reset), and `charge_cents` equal to the new due amount; a positive delta posts a `PRORATION_DEBIT` to the holder's `CAMPUS_CASH` (auto-created `OPEN` when absent), a negative delta posts a `PRORATION_CREDIT` of its magnitude, and a zero delta posts nothing; a positive `funding_delta_cents` posts an `ALLOCATION_GRANT` to the term `DINING_DOLLARS` account; and the request becomes `EXECUTED`. On a failed precondition the request becomes `VOID` instead — `void_reason` `ENROLLMENT_CANCELLED` when the enrollment is no longer active, `INSUFFICIENT_FUNDS` when the balance cannot cover a positive delta — the old enrollment remains in its prior state, and no ledger entries are posted.

Enrollments can be listed with filters on `holder_id`, `plan_id`, `term_id`, `supersedes_enrollment_id`, and `status`.

### 3.5. Spending Power: Accounts, Funding, Purchases, and Swipes

Every holder's spending power lives in **declining-balance accounts**, opened by `BursarOffice` or `CardOfficeAdmin` with an `account_type` of `DINING_DOLLARS` or `CAMPUS_CASH`. A `DINING_DOLLARS` account is bound to a term and requires a `term_id`; a `CAMPUS_CASH` account is termless and must carry a null `term_id` — violating either rule is `ERR_VALIDATION`. At most one non-terminal account may exist per holder, type, and term combination (`ERR_ACCOUNT_UNIQUENESS`). New accounts start `OPEN` with `balance_cents` 0 — a derived value that is never settable directly, only moved through ledger entries — and a null `last_adjusted_by`. Accounts can be listed with filters on `holder_id`, `account_type`, `term_id`, and `status`.

Funding posts to an `OPEN` account (a `FROZEN` or otherwise non-`OPEN` account is rejected with `ERR_ACCOUNT_FROZEN`) and may be performed by the owning `CardHolder` or by `BursarOffice`, with a positive `amount_cents` and a client `idempotency_key` per §2.8. Funding writes a `FUND` entry, recomputes the balance, and bumps the account's `version`. `BursarOffice` may also post manual adjustments with an `amount_cents`, a `direction` selecting an `ADJUSTMENT_CREDIT` or `ADJUSTMENT_DEBIT`, a `reason`, and the OCC field `expected_account_version` (§2.9); the posting records the acting user's `X-User-ID` as the account's `last_adjusted_by` — a value the refund workflow's segregation-of-duties rule later reads (§3.7).

Spending happens through **card transactions**, posted either by a `PointOfSale` terminal for on-campus dining (which must omit `merchant_id`) or by a `MerchantUser` for an off-campus purchase (who must pass a `merchant_id` equal to their own merchant id — anything else is `ERR_NOT_RESOURCE_OWNER`). The payload names the `card_id`, a `tender_type` of `MEAL_SWIPE`, `DINING_DOLLARS`, or `CAMPUS_CASH`, an `amount_cents` that must be exactly 0 for a swipe and strictly positive for either declining-balance tender (`ERR_VALIDATION` otherwise), an `idempotency_key` per §2.8, and an optional free-text `location_description`. The server derives the rest: for `DINING_DOLLARS` and `CAMPUS_CASH` it resolves the holder's account of that type for the current term (or the termless account for `CAMPUS_CASH`) and sets `account_id`, leaving `enrollment_id` null; for `MEAL_SWIPE` it resolves the holder's enrollment in the current term and sets `enrollment_id`, leaving `account_id` null.

A battery of guards precedes every posting. The card must be `ACTIVE`: a card in `LOST_FROZEN` or `STOLEN_FROZEN` is rejected with `ERR_CARD_FROZEN`, a card in any other non-active state with `ERR_CARD_NOT_ACTIVE`, and a card touched at or after its `expires_at` flips to `EXPIRED` first and fails with `ERR_CARD_NOT_ACTIVE`. The holder must be `ACTIVE` (`ERR_HOLDER_NOT_ACTIVE`), and a suspended or fraud-flagged holder attempting any value-extending action is rejected with `ERR_FRAUD_HOLD`. A merchant posting additionally requires the merchant to be `ACTIVE` (`ERR_MERCHANT_NOT_ACTIVE`). For a swipe, the resolved enrollment must be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`), and admission follows the weekly rule: unlimited plans always admit; otherwise the swipe is admitted only while `swipes_used_this_week` is strictly below the snapshotted `weekly_swipe_allowance` — a swipe attempted when the used count already equals the allowance is rejected with `ERR_SWIPES_EXHAUSTED`, and a plan with a zero allowance and no unlimited flag rejects every swipe. An admitted swipe increments `swipes_used_this_week` by 1 and bumps the enrollment's `version`. For a declining-balance purchase, the resolved account must be `OPEN` (`ERR_ACCOUNT_FROZEN`), and the amount must not exceed the account's `balance_cents` — a purchase exactly equal to the balance is admitted, anything larger is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402); an admitted purchase posts a `PURCHASE` entry carrying the transaction's `reference_transaction_id`, recomputes the balance, and bumps the account's `version`.

Provisional cards carry one more constraint: when `is_provisional` is true and the tender is `DINING_DOLLARS` or `CAMPUS_CASH`, the sum of `amount_cents` over the card's `PURCHASE` ledger entries — across both account types — whose `created_at` falls on the same UTC calendar date as the logical clock, plus the new amount, must not exceed the provisional daily cap of 2500 cents. A purchase that lands exactly on the cap is admitted; one that would push the day's total above it is rejected with `ERR_PROVISIONAL_DAILY_CAP` (HTTP 422). Meal swipes are exempt from the cap.

A transaction's initial `status` depends on who posted it: on-campus postings settle immediately and are born `SETTLED`, while merchant postings are born `POSTED` and settle only through the settlement approval of §3.9. A transaction's `settled_in_settlement_id` stays null until a settlement sweep links it, and its `pre_dispute_status` stays null until a dispute opens. Transactions can be listed with filters on `card_id`, `account_id`, `enrollment_id`, `merchant_id`, `settled_in_settlement_id`, and `status`; a `CardHolder` sees only their own transactions and a `MerchantUser` only their own merchant's.

### 3.6. Disputes and Provisional Credit

When a holder disputes a charge, the owning holder files a dispute against the transaction with a `reason_code` of `UNAUTHORIZED_USE`, `DUPLICATE_CHARGE`, `AMOUNT_MISMATCH`, or `SERVICE_NOT_RECEIVED`. Filing is allowed only within 30 days of the transaction's `created_at` (later filings are rejected with `ERR_DISPUTE_WINDOW_CLOSED`), only against a transaction that is not `REVERSED` and not locked into a settlement in `APPROVED` or `PAID` (`ERR_TX_NOT_DISPUTABLE`), and only while no non-terminal dispute already exists on the transaction (`ERR_DISPUTE_ALREADY_OPEN`). Filing moves the transaction to `UNDER_DISPUTE`, captures its prior state (`POSTED` or `SETTLED`) into `pre_dispute_status`, bumps the transaction's `version`, and records the filer as `filed_by_holder_id`. The dispute starts `OPENED`. Disputes can be listed with filters on `transaction_id`, `filed_by_holder_id`, and `status`.

A `FraudAnalyst` may grant **provisional credit** on an `OPENED` dispute — but only when the disputed transaction's tender is not `MEAL_SWIPE`; a swipe dispute is ineligible and is rejected with `ERR_CREDIT_NOT_APPLICABLE`. Granting posts a `PROVISIONAL_CREDIT` ledger entry for the full transaction amount to the transaction's account (carrying both `reference_transaction_id` and `reference_dispute_id`), sets `provisional_credit_cents` equal to the disputed amount, records `granter_analyst_id`, and moves the dispute to `PROVISIONAL_CREDIT_GRANTED`.

Resolution, also by a `FraudAnalyst`, takes an `outcome` of `FOR_CARDHOLDER` or `FOR_MERCHANT` and a `resolution_note`, and records `resolver_analyst_id`. One segregation-of-duties rule applies: when provisional credit was granted, the resolving analyst must differ from the `granter_analyst_id` (`ERR_SOD_RESOLVER_IS_GRANTER`). The outcomes diverge as follows:

- **For the cardholder** (`OPENED` or `PROVISIONAL_CREDIT_GRANTED` → `RESOLVED_FOR_CARDHOLDER`): the transaction becomes `REVERSED`. If the dispute never received provisional credit, a `PURCHASE_REVERSAL` entry is posted to the account and the balance recomputed; if provisional credit was already posted, that credit simply becomes permanent and no reversal entry is written — either way the ledger invariant of §2.7 holds, and the account ends as if the purchase had never happened.
- **For the merchant** (`OPENED` or `PROVISIONAL_CREDIT_GRANTED` → `RESOLVED_FOR_MERCHANT`): the transaction returns to its `pre_dispute_status`; if provisional credit existed, a `PROVISIONAL_CLAWBACK` entry removes it; and if the dispute's `reason_code` was `UNAUTHORIZED_USE`, the holder's `fraud_strike_count` increments by 1 — which may push the count to the threshold of 3 and fire the full suspension cascade of §3.2.

The filing holder may instead withdraw their own dispute (anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`), moving it to `WITHDRAWN`: the transaction returns to its `pre_dispute_status`, and any provisional credit is clawed back, exactly as in a merchant win.

Disputes interact with settlement through a carryover rule detailed in §3.9: a transaction under dispute at settlement-submit time is excluded from that sweep, and a dispute that later resolves for the merchant or is withdrawn makes the transaction eligible for the merchant's next sweep regardless of that settlement's period. A transaction resolved for the cardholder is `REVERSED` and never settles.

### 3.7. Term Closeout, Refunds, and Forfeiture

Closing a term is a `DiningServicesManager` action gated on the logical clock reading at or after the term's `end_date` (otherwise `ERR_TERM_NOT_ENDED`). Close fires a three-link cascade. First, every enrollment of the term in `ACTIVE` becomes `CLOSED` — unused swipes simply lapse with no compensation — and every enrollment still `ASSIGNED` becomes `CANCELLED`. Second, each enrollment closure sweeps the enrollment-linked `DINING_DOLLARS` account for the term from `OPEN` or `FROZEN` into `CLOSE_PENDING` (entering from `FROZEN` clears the `frozen_reason`). Third, each account entering `CLOSE_PENDING` at term close is immediately evaluated against the forfeiture threshold: when its `balance_cents` is below the minimum refund amount of 1000 cents, the account posts a `FORFEIT` entry for its full balance and continues straight to `FORFEITED`, zeroing it. Close also moves every plan change request in `SUBMITTED` or `APPROVED` on the term's enrollments to `EXPIRED`.

A holder whose dining account sits in `CLOSE_PENDING` may request a term-end refund; requesting against an account in any other state is rejected with `ERR_ACCOUNT_NOT_CLOSABLE`, and requesting while another request on the same account is `REQUESTED` or `APPROVED` is rejected with `ERR_PENDING_REFUND_EXISTS`. The request itself takes no amount — the server computes one. It first sums the unresolved provisional exposure: the total of `provisional_credit_cents` over the holder's disputes in `OPENED` or `PROVISIONAL_CREDIT_GRANTED` whose underlying transaction debited this account. Variant selection is then deterministic: `FULL_BALANCE`, which refunds the account's entire `balance_cents`, is selectable only when that unresolved sum is zero; whenever unresolved provisional credits exist, the request is computed under `AUTO_EXCLUDING_PROVISIONAL`, which refunds the balance minus the unresolved provisional sum, floored at zero. In both variants the computed `amount_cents` must be at least the minimum refund amount of 1000 cents, or the request is rejected with `ERR_REFUND_BELOW_MINIMUM`. The created request records the `account_id`, the `requested_by_holder_id`, the selected `refund_variant`, and the computed `amount_cents`, and starts `REQUESTED`. Refund requests can be listed with filters on `account_id`, `requested_by_holder_id`, and `status`.

`BursarOffice` adjudicates, under two segregation-of-duties rules. Approval requires the approver's `X-User-ID` to differ from the account's `last_adjusted_by` — the bursar user who last posted a manual adjustment to that account may not approve its refund (`ERR_SOD_ADJUSTER_CANNOT_APPROVE`) — and records `approved_by`. Denial requires a `denial_reason` (`ERR_VALIDATION` otherwise). Payment of an `APPROVED` request requires the payer to differ from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`), records `paid_by`, and posts a `REFUND_PAYOUT` entry of the request's `amount_cents`. When the payout zeroes the account's `balance_cents`, the account becomes `REFUNDED`; when a residual remains — the residue of provisional credits excluded from the refund — the account stays `CLOSE_PENDING`, and a later refund request may capture the residue once those disputes resolve.

The final act of a term is settlement, again by the `DiningServicesManager`. Settling requires that no refund request in `REQUESTED` or `APPROVED` exists on any account bound to the term (`ERR_REFUNDS_OUTSTANDING`) and that no merchant settlement for the term sits in `DRAFT`, `SUBMITTED`, or `APPROVED` (`ERR_SETTLEMENTS_OUTSTANDING`). Settling then forfeits what remains: every `CLOSE_PENDING` `DINING_DOLLARS` account of the term posts a `FORFEIT` entry for its full `balance_cents` and becomes `FORFEITED`, and the term becomes `SETTLED`, which is terminal.

### 3.8. Door Access: Zones, Grants, and the Access Decision

Physical access is administered by `SecurityOfficer`s. A **door zone** is created with a unique `zone_code` (`ERR_DUPLICATE_NATURAL_KEY` on collision), a `building`, a `security_level` of `STANDARD`, `ELEVATED`, or `RESTRICTED` — carrying ordinal values 1, 2, and 3 respectively for clearance comparison — and a non-empty `access_windows` list. Each window names a `day_of_week` from `MON` through `SUN`, a `start_minute` between 0 and 1439, and an `end_minute` between 1 and 1440 strictly greater than its start; matching against a window is half-open, admitting attempt minutes from `start_minute` up to but not including `end_minute`. Zones start `ACTIVE` and can be listed with filters on `security_level` and `status`. Decommissioning moves a zone to `DECOMMISSIONED` and revokes every grant on the zone in `ACTIVE` or `SUSPENDED`.

An **access grant** gives a specific card entry to a zone: the card comes from the creation path, and the payload names the `zone_id`, a `clearance` of `STANDARD`, `ELEVATED`, or `RESTRICTED`, a `valid_from` that is inclusive, and a `valid_until` that is exclusive and strictly after `valid_from`, so the grant's validity is the half-open interval from `valid_from` up to but not including `valid_until`. Creating a grant whose interval intersects an existing `ACTIVE` or `SUSPENDED` grant on the same card and zone is rejected with `ERR_GRANT_OVERLAP`; because the intervals are half-open, adjacency — one grant ending exactly where another begins — is permitted. Grants start `ACTIVE`, record the creating officer as `granted_by`, and can be listed with filters on `card_id`, `zone_id`, and `status`.

Officers manage grants through three actions. Suspending an `ACTIVE` grant marks it `SUSPENDED` with `suspended_reason` `MANUAL` (the same state reached by the card-freeze cascades of §3.2, which use `CARD_FROZEN`). Reinstating a `SUSPENDED` grant requires the card's `lifecycle_status` to be `ACTIVE` (`ERR_CARD_NOT_ACTIVE` otherwise) and the clock to read earlier than the grant's `valid_until` — a grant touched at or past its `valid_until` is first evaluated to `EXPIRED`; reinstatement clears the `suspended_reason`. Revoking moves an `ACTIVE` or `SUSPENDED` grant to `REVOKED`. Expiry is lazy from both `ACTIVE` and `SUSPENDED`: whenever an access attempt or grant action touches a grant whose `valid_until` has passed, it flips to `EXPIRED`.

A `DoorController` device records each door attempt with the `card_id` and `zone_id`. The decision is **computed data, not an API error**: the created `AccessEvent` carries the logical-clock `attempted_at`, a `decision` of `GRANTED` or `DENIED`, a `deny_reason` that is null when granted, and the `grant_id` of the selected grant when one exists. The evaluation order is pinned, and the first failing check determines the recorded outcome:

1. If the zone is not `ACTIVE`, the attempt is `DENIED` with `deny_reason` `ZONE_DECOMMISSIONED`.
2. If the card's `lifecycle_status` is not `ACTIVE`, the attempt is `DENIED` with `deny_reason` `CARD_NOT_ACTIVE` — a card touched at or after its `expires_at` flips to `EXPIRED` first and fails here.
3. If the card's `is_provisional` is true, the attempt is `DENIED` with `deny_reason` `CARD_PROVISIONAL`.
4. The candidate grants are this card's grants on this zone in `ACTIVE` status whose half-open validity contains the attempt instant — `valid_from` at or before `attempted_at`, and `attempted_at` before `valid_until` — ranked by `valid_from` descending with ties broken by `created_at` ascending; the top-ranked grant is the selected one. If the candidate set is empty, the attempt is `DENIED` with `deny_reason` `NO_ACTIVE_GRANT` and a null `grant_id`.
5. If the selected grant's `clearance` ordinal is below the zone's `security_level` ordinal, the attempt is `DENIED` with `deny_reason` `INSUFFICIENT_CLEARANCE`, with the `grant_id` recorded.
6. If the attempt instant matches no access window — same `day_of_week`, and the minute of day from `start_minute` up to but not including `end_minute` — the attempt is `DENIED` with `deny_reason` `OUTSIDE_SCHEDULE`, with the `grant_id` recorded.
7. Otherwise the attempt is `GRANTED`, with the `grant_id` recorded.

Access events can be listed with filters on `card_id`, `zone_id`, `grant_id`, and `decision`, and individual events fetched by id.

### 3.9. The Off-Campus Merchant Program and Settlement

`BursarOffice` onboards off-campus merchants with a unique `merchant_code` (`ERR_DUPLICATE_NATURAL_KEY` on collision), a `legal_name`, a `category` of `RESTAURANT`, `GROCERY`, `COFFEE`, `BOOKSTORE`, or `OTHER`, a `commission_bps` rate in basis points between 0 and 2000, an optional `commission_mode` of `PER_TRANSACTION` or `AGGREGATE` defaulting to `PER_TRANSACTION`, and a `contact_email`. Merchants start `PENDING_CONTRACT`, become `ACTIVE` on activation, can be suspended to `SUSPENDED` and reactivated, and can be terminated to `TERMINATED` — termination requires that no settlement of the merchant sits in `DRAFT`, `SUBMITTED`, or `APPROVED` (`ERR_SETTLEMENTS_OUTSTANDING`). A suspended merchant accepts no new transactions. Merchants can be listed with filters on `status` and `category`.

Settlement turns a merchant's posted transactions into a payable statement. A `MerchantUser` acting for their own merchant — or `BursarOffice` on the merchant's behalf — creates a settlement draft naming a `term_id`, a `period_start`, and a `period_end`. The period is a **closed-closed** interval: `period_end` must be on or after `period_start` (`ERR_VALIDATION` otherwise), both ends must lie within the term's `start_date`-to-`end_date` span (`ERR_PERIOD_OUTSIDE_TERM`), and the period must not share any day with an existing non-`REJECTED` settlement of the same merchant — because both intervals are closed, touching endpoints conflict and are rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP`. The merchant must be `ACTIVE` (`ERR_MERCHANT_NOT_ACTIVE`). Drafts carry null `gross_cents`, `commission_cents`, `net_cents`, and `transaction_count` until first submitted. Settlements can be listed with filters on `merchant_id`, `term_id`, `status`, and `carried_from_settlement_id`.

Submitting a settlement — from `DRAFT`, or resubmitting after `REJECTED` — runs the sweep. The sweep set is the merchant's card transactions whose `created_at` falls within the closed-closed period (compared at timestamp precision), whose `status` is `POSTED`, and whose `settled_in_settlement_id` is still null — plus any **carried** transactions, which join the sweep regardless of the period (see the carryover rule below). Transactions `UNDER_DISPUTE` at submit time are excluded. Submitting links every swept transaction by setting its `settled_in_settlement_id`, then computes the statement: `gross_cents` is the sum of the swept amounts; `transaction_count` is their number; `net_cents` is `gross_cents` minus `commission_cents`. The commission depends on the merchant's `commission_mode`, and the rounding order is variant-defining: under `PER_TRANSACTION`, each transaction's commission — its amount multiplied by `commission_bps` and divided by 10000 — is rounded half-up to whole cents **first**, and those rounded values are then summed; under `AGGREGATE`, the amounts are summed first and the commission is computed on the gross and rounded half-up exactly once. The two modes disagree whenever per-transaction fractions would sum across a half-cent boundary. The submitter's `X-User-ID` is recorded as `submitted_by`; when the sweep picks up carried transactions, `carried_from_settlement_id` is set to the id of the most recent prior non-`REJECTED` settlement of the same merchant whose dispute exclusions entered this sweep, and stays null when none did. Resubmission after rejection runs a fresh sweep that replaces the prior computed values, clears the `rejection_reason`, and updates `submitted_by`.

The carryover rule keeps disputed money from falling through the cracks. A transaction excluded from a sweep because it was `UNDER_DISPUTE` becomes sweep-eligible again when its dispute resolves for the merchant or is withdrawn — restored to its `pre_dispute_status` — and it then enters the merchant's **next** submitted settlement as a carried transaction, overriding the period filter, with `carried_from_settlement_id` recording the settlement that excluded it. A transaction resolved for the cardholder is `REVERSED` and never settles. The invariant this preserves: for every merchant, the sum of `gross_cents` over all non-`REJECTED` settlements plus the amounts of transactions still `POSTED` and never swept equals the sum of all the merchant's transactions not in `REVERSED` — a dispute exclusion followed by a later carryover leaves the combined gross unchanged.

`BursarOffice` then adjudicates the submitted settlement under segregation of duties. Approval requires the approver's `X-User-ID` to differ from the `submitted_by` (`ERR_SOD_APPROVER_IS_SUBMITTER`), records `approved_by`, and moves every linked transaction to `SETTLED`. Rejection requires a `rejection_reason` (`ERR_VALIDATION` otherwise) and unlinks every swept transaction — their `settled_in_settlement_id` returns to null — making them eligible for a future sweep. Payment of an `APPROVED` settlement requires the payer to differ from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`) and records `paid_by`, completing the cycle at `PAID`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`; this includes registration and issuance endpoints as well as actions whose primary effect is to mint a new resource (a replacement mints a new card, funding and adjustments mint ledger entries, disputes, photos, and access events are new records). Operations that modify an existing resource's state return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/api/card-holders` | Register a card holder | CardOfficeAdmin |
| GET | `/api/card-holders` | List card holders | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, FraudAnalyst, SecurityOfficer |
| GET | `/api/card-holders/{id}` | Get one card holder; CardHolder caller may read only own record | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, FraudAnalyst, SecurityOfficer, CardHolder |
| POST | `/api/card-holders/{id}/suspend` | Manually suspend a holder | CardOfficeAdmin, FraudAnalyst |
| POST | `/api/card-holders/{id}/reinstate` | Reinstate a SUSPENDED or WITHDRAWN holder to ACTIVE | CardOfficeAdmin |
| POST | `/api/card-holders/{id}/withdraw` | Withdraw a holder (mid-term departure) | CardOfficeAdmin |
| POST | `/api/card-holders/{id}/graduate` | Graduate a holder (terminal) | CardOfficeAdmin |
| POST | `/api/card-holders/{id}/fraud-review` | Clear fraud_flag and reset fraud_strike_count to 0 | FraudAnalyst |
| POST | `/api/card-holders/{id}/cards` | Issue a card; rejected when the holder already has a non-terminal card | CardOfficeAdmin |
| GET | `/api/cards` | List cards with filters | CardOfficeAdmin, FraudAnalyst, SecurityOfficer |
| GET | `/api/cards/{id}` | Get one card | CardOfficeAdmin, FraudAnalyst, SecurityOfficer, CardHolder |
| POST | `/api/cards/{id}/activate` | Activate a PENDING_PHOTO card; allow_provisional permits activation without approved photo | CardOfficeAdmin |
| POST | `/api/cards/{id}/report-lost` | Owner reports card lost; freezes card and its door grants | CardHolder |
| POST | `/api/cards/{id}/report-stolen` | Owner reports card stolen; adds fraud strike and freezes accounts | CardHolder |
| POST | `/api/cards/{id}/unfreeze` | Owner recovers a LOST_FROZEN card | CardHolder |
| POST | `/api/cards/{id}/replacement` | Replace a card; OCC-guarded; computes replacement fee and mints successor card | CardOfficeAdmin |
| POST | `/api/cards/{id}/deactivate` | Permanently deactivate a non-terminal card | CardOfficeAdmin, FraudAnalyst |
| POST | `/api/cards/{id}/photos` | Submit a photo for a card (owner) | CardHolder |
| GET | `/api/cards/{id}/photos` | List a card's photo submissions | CardOfficeAdmin, CardHolder |
| POST | `/api/photos/{id}/review` | Approve or reject the card's latest pending photo submission | CardOfficeAdmin |
| POST | `/api/terms` | Create a term | DiningServicesManager |
| GET | `/api/terms` | List terms | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, FraudAnalyst, CardHolder |
| GET | `/api/terms/{id}` | Get one term | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, FraudAnalyst, CardHolder |
| POST | `/api/terms/{id}/open` | Open a term; activates ASSIGNED enrollments with full pricing and funding | DiningServicesManager |
| POST | `/api/terms/{id}/advance-week` | Advance the term one week: resets swipes, executes due plan changes | DiningServicesManager |
| POST | `/api/terms/{id}/close` | Close a term at/after end_date | DiningServicesManager |
| POST | `/api/terms/{id}/settle` | Settle a closed term; forfeits residual CLOSE_PENDING dining balances | DiningServicesManager |
| POST | `/api/meal-plans` | Create a meal plan (DRAFT) | DiningServicesManager |
| GET | `/api/meal-plans` | List meal plans | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, CardHolder |
| GET | `/api/meal-plans/{id}` | Get one meal plan | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, BursarOffice, CardHolder |
| POST | `/api/meal-plans/{id}/publish` | Publish a DRAFT plan | DiningServicesManager |
| POST | `/api/meal-plans/{id}/retire` | Retire a PUBLISHED plan with no live enrollments | DiningServicesManager |
| POST | `/api/card-holders/{id}/enrollments` | Assign a meal plan; ACTIVE immediately when term OPEN (prorated), else ASSIGNED until open | DiningServicesManager |
| GET | `/api/enrollments` | List enrollments with filters | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, CardHolder |
| GET | `/api/enrollments/{id}` | Get one enrollment | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, CardHolder |
| POST | `/api/enrollments/{id}/cancel` | Cancel an ASSIGNED or ACTIVE enrollment; ACTIVE cancellation posts proration credit | DiningServicesManager |
| GET | `/api/enrollments/{id}/change-requests` | List change requests of an enrollment | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, CardHolder |
| POST | `/api/enrollments/{id}/change-requests` | Request a plan change (owner); OCC-guarded on enrollment version | CardHolder |
| GET | `/api/change-requests` | List change requests with filters | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, CardHolder |
| GET | `/api/change-requests/{id}` | Get one change request | PlatformAdmin, CardOfficeAdmin, DiningServicesManager, CardHolder |
| POST | `/api/change-requests/{id}/approve` | Approve a SUBMITTED change request; computes proration deltas; execution deferred to advance-week | DiningServicesManager |
| POST | `/api/change-requests/{id}/deny` | Deny a SUBMITTED change request | DiningServicesManager |
| POST | `/api/change-requests/{id}/withdraw` | Withdraw a SUBMITTED change request (owner) | CardHolder |
| POST | `/api/card-holders/{id}/accounts` | Open a declining-balance account; DINING_DOLLARS requires term_id, CAMPUS_CASH forbids it | BursarOffice, CardOfficeAdmin |
| GET | `/api/accounts` | List accounts with filters | PlatformAdmin, CardOfficeAdmin, BursarOffice, CardHolder |
| GET | `/api/accounts/{id}` | Get one account | PlatformAdmin, CardOfficeAdmin, BursarOffice, CardHolder |
| POST | `/api/accounts/{id}/funding` | Fund an OPEN account (idempotent by idempotency_key) | CardHolder, BursarOffice |
| POST | `/api/accounts/{id}/adjustments` | Manual credit/debit adjustment; OCC-guarded; records last_adjusted_by | BursarOffice |
| GET | `/api/ledger-entries` | List ledger entries with filters | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder |
| GET | `/api/ledger-entries/{id}` | Get one ledger entry | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder |
| POST | `/api/accounts/{id}/refund-requests` | Request term-end refund of a CLOSE_PENDING account (owner); amount computed by the server | CardHolder |
| GET | `/api/refund-requests` | List refund requests with filters | PlatformAdmin, CardOfficeAdmin, BursarOffice, CardHolder |
| GET | `/api/refund-requests/{id}` | Get one refund request | PlatformAdmin, CardOfficeAdmin, BursarOffice, CardHolder |
| POST | `/api/refund-requests/{id}/approve` | Approve a REQUESTED refund; approver must differ from the account's last manual adjuster | BursarOffice |
| POST | `/api/refund-requests/{id}/deny` | Deny a REQUESTED refund | BursarOffice |
| POST | `/api/refund-requests/{id}/pay` | Pay an APPROVED refund; payer must differ from approver; posts REFUND_PAYOUT | BursarOffice |
| POST | `/api/transactions` | Post a meal swipe or declining-balance purchase (idempotent); merchant and account/enrollment derived server-side | PointOfSale, MerchantUser |
| GET | `/api/transactions` | List transactions with filters; CardHolder sees only own, MerchantUser only own merchant's | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder, MerchantUser |
| GET | `/api/transactions/{id}` | Get one transaction | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder, MerchantUser |
| POST | `/api/transactions/{id}/disputes` | File a dispute on a disputable transaction (owner) | CardHolder |
| GET | `/api/disputes` | List disputes with filters | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder |
| GET | `/api/disputes/{id}` | Get one dispute | PlatformAdmin, CardOfficeAdmin, BursarOffice, FraudAnalyst, CardHolder |
| POST | `/api/disputes/{id}/grant-provisional-credit` | Grant provisional credit for an OPENED dispute (non-swipe only) | FraudAnalyst |
| POST | `/api/disputes/{id}/resolve` | Resolve a dispute; resolver must differ from granter when provisional credit was granted | FraudAnalyst |
| POST | `/api/disputes/{id}/withdraw` | Withdraw an open dispute (filing owner) | CardHolder |
| POST | `/api/door-zones` | Create a door zone with weekly access windows | SecurityOfficer |
| GET | `/api/door-zones` | List door zones | PlatformAdmin, CardOfficeAdmin, SecurityOfficer |
| GET | `/api/door-zones/{id}` | Get one door zone | PlatformAdmin, CardOfficeAdmin, SecurityOfficer |
| POST | `/api/door-zones/{id}/decommission` | Decommission a zone; revokes its live grants | SecurityOfficer |
| POST | `/api/cards/{id}/access-grants` | Grant door access for a card; rejects half-open overlap with an existing live grant on the same card and zone | SecurityOfficer |
| GET | `/api/access-grants` | List access grants with filters | PlatformAdmin, SecurityOfficer, CardHolder |
| GET | `/api/access-grants/{id}` | Get one access grant | PlatformAdmin, SecurityOfficer, CardHolder |
| POST | `/api/access-grants/{id}/suspend` | Manually suspend an ACTIVE grant | SecurityOfficer |
| POST | `/api/access-grants/{id}/reinstate` | Reinstate a SUSPENDED grant; requires card ACTIVE and validity remaining | SecurityOfficer |
| POST | `/api/access-grants/{id}/revoke` | Revoke a non-terminal grant | SecurityOfficer |
| POST | `/api/access-events` | Record a door access attempt; the decision is computed and returned as data (denials are not API errors) | DoorController |
| GET | `/api/access-events` | List access events with filters | PlatformAdmin, SecurityOfficer, CardOfficeAdmin |
| GET | `/api/access-events/{id}` | Get one access event | PlatformAdmin, SecurityOfficer, CardOfficeAdmin |
| POST | `/api/merchants` | Onboard an off-campus merchant (PENDING_CONTRACT) | BursarOffice |
| GET | `/api/merchants` | List merchants | PlatformAdmin, CardOfficeAdmin, BursarOffice |
| GET | `/api/merchants/{id}` | Get one merchant | PlatformAdmin, CardOfficeAdmin, BursarOffice, MerchantUser |
| POST | `/api/merchants/{id}/activate` | Activate a PENDING_CONTRACT or SUSPENDED merchant | BursarOffice |
| POST | `/api/merchants/{id}/suspend` | Suspend an ACTIVE merchant (blocks new transactions) | BursarOffice |
| POST | `/api/merchants/{id}/terminate` | Terminate a merchant with no open settlements | BursarOffice |
| POST | `/api/merchants/{id}/settlements` | Create a settlement period draft; rejects period overlap and periods outside the term | MerchantUser, BursarOffice |
| GET | `/api/settlements` | List settlements with filters | PlatformAdmin, CardOfficeAdmin, BursarOffice, MerchantUser |
| GET | `/api/settlements/{id}` | Get one settlement | PlatformAdmin, CardOfficeAdmin, BursarOffice, MerchantUser |
| POST | `/api/settlements/{id}/submit` | Submit (or resubmit after rejection) a settlement; runs the settlement sweep | MerchantUser, BursarOffice |
| POST | `/api/settlements/{id}/approve` | Approve a SUBMITTED settlement; approver must differ from submitter | BursarOffice |
| POST | `/api/settlements/{id}/reject` | Reject a SUBMITTED settlement; transactions are unlinked and re-eligible | BursarOffice |
| POST | `/api/settlements/{id}/pay` | Pay an APPROVED settlement; payer must differ from approver | BursarOffice |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_HOLDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_FROZEN` | 409 Conflict |
| `ERR_CARD_NOT_RECOVERABLE` | 409 Conflict |
| `ERR_PHOTO_NOT_APPROVED` | 409 Conflict |
| `ERR_ACTIVE_CARD_EXISTS` | 409 Conflict |
| `ERR_TERM_NOT_OPEN` | 409 Conflict |
| `ERR_TERM_NOT_YET_STARTED` | 422 Unprocessable Entity |
| `ERR_TERM_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_TERM_WEEKS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PLAN_IN_USE` | 409 Conflict |
| `ERR_MERCHANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_FROZEN` | 409 Conflict |
| `ERR_ACCOUNT_NOT_CLOSABLE` | 409 Conflict |
| `ERR_TX_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_FRAUD_HOLD` | 409 Conflict |
| `ERR_SOD_ADJUSTER_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_SOD_PAYER_IS_APPROVER` | 403 Forbidden |
| `ERR_SOD_APPROVER_IS_SUBMITTER` | 403 Forbidden |
| `ERR_SOD_RESOLVER_IS_GRANTER` | 403 Forbidden |
| `ERR_CREDIT_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_PLAN_CHANGE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID` | 422 Unprocessable Entity |
| `ERR_HOUSING_INELIGIBLE_FOR_PLAN` | 422 Unprocessable Entity |
| `ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_OVERLAP` | 409 Conflict |
| `ERR_PENDING_CHANGE_EXISTS` | 409 Conflict |
| `ERR_PENDING_REFUND_EXISTS` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_ACCOUNT_UNIQUENESS` | 409 Conflict |
| `ERR_GRANT_OVERLAP` | 409 Conflict |
| `ERR_SETTLEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_OUTSIDE_TERM` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_NATURAL_KEY` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_SWIPES_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_PROVISIONAL_DAILY_CAP` | 422 Unprocessable Entity |
| `ERR_REFUND_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_REFUNDS_OUTSTANDING` | 409 Conflict |
| `ERR_SETTLEMENTS_OUTSTANDING` | 409 Conflict |

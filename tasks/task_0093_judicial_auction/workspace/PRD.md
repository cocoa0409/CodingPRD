# Judicial Auction Platform API — Product Requirements Document

## 1. Introduction

The Judicial Auction Platform exists to give courts a single, auditable channel for liquidating distrained assets — real estate, vehicles, equity stakes, and movable property — under the supervision of court officers and with statutory protections for bidders, debtors, and counterparty registries. The system absorbs the procedural rigour of an in-court auction (notice periods, sealed rulings, escrowed deposits, registry coordination) and translates it into an online workflow that several parties operate in parallel: the court clerk who authors rulings, the platform operator who runs the live session, the authenticated real-name bidder who places bids and pays the balance, and the silent observer who watches without participating.

Two design tensions shape every requirement that follows. First, the platform must simultaneously act as an open marketplace (anyone may observe the bid feed) and as a privileged judicial workspace (only the court may issue or fail a confirmation ruling) — and the role separation between these two surfaces is non-negotiable. Second, every value the platform touches — bid amounts, deposit calculations, late-payment penalties — settles into an enforceable obligation, so every calculation is performed in integer cents with pinned rounding rules and every threshold is interpreted with explicit boundary semantics. The remainder of this document specifies the entities, lifecycles, calculations, and constraints that together implement this contract.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting principal and `X-User-Role` to specify their operational capacity. Requests that omit either header, or supply them empty, are rejected with `ERR_AUTH_MISSING`. Requests authenticated with a role not permitted for the requested operation are rejected with `ERR_AUTH_FORBIDDEN`.

The system recognises exactly four roles, spelled as written here: `CourtClerk`, `AuctionAdmin`, `Bidder`, and `Observer`.

When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `BidderAccount`; ownership checks on any resource that references a `BidderAccount` — including `Deposit`, `Bid`, and `Payment` rows — compare the resource's `bidder_account_id` (resolved through `Confirmation.winning_bid_id` for `Payment` ownership) to `X-User-ID`. A `Bidder` may only post a deposit, pay it, raise or settle a dispute on it, place a bid, settle a payment, or read a bidder-account or payment record when the targeted resource belongs to their own account; cross-account access is rejected with `ERR_AUTH_FORBIDDEN`.

When `X-User-Role` is `CourtClerk`, `AuctionAdmin`, or `Observer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on emitted audit events (as `AuditEvent.actor_id`) but does not compare it to any entity's `id`. `Observer` is a strictly read-only role that sees the masked public surface — lot listings, the auction record, and the masked bid feed — but cannot transition any state.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless explicitly noted otherwise, list endpoints return resources sorted by `created_at` in ascending order.

Paginated list responses always include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

The primary entities of the platform — `Lot`, `BidderAccount`, `Auction`, `Deposit`, `Confirmation`, `Payment`, and `TransferOrder` — all carry the following system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): the ISO 8601 UTC timestamp of resource creation, rendered with three fractional digits (for example `2025-05-24T10:30:00.123Z`).
- `updated_at` (string): the ISO 8601 UTC timestamp of the most recent mutation; refreshed by any operation that mutates the resource, including automatic transitions driven by clock advance or by cascades from related resources.
- `version` (integer): a system-managed counter that increments by one on every mutation. It is used for optimistic concurrency control as described in §2.6.

Two append-only entities — `Bid` and `AuditEvent` — are immutable after creation. They expose only the system-minted `id` and `created_at`; neither `updated_at` nor `version` exists on these rows. A `Bid`'s `validity` may move from `VALID` to `ROLLED_BACK` through the system-fault-rollback path, but that change is realised through writing a verdict, not through mutating an existing immutable record's `updated_at` clock.

### 2.5. Monetary Precision and Integer Cents

All monetary quantities on the platform — `assessment_value_cents`, `starting_price_cents`, `bid_increment_cents`, `bid_cap_cents`, `deposit_fixed_cents`, `deposit_amount_cents`, `amount_cents` (on `Bid` and `Deposit`), `balance_due_cents`, `penalty_accrued_cents`, `amount_paid_cents`, and `current_high_cents` — are stored as integer cents. Percentages are likewise expressed as integer basis points where `10000` equals one hundred percent (for example `deposit_percent_bps`). Where a calculation requires rounding, the result is rounded half up to integer cents; the order of operations is multiplication first to the highest-precision intermediate, then division by `10000`, then rounding half up. Cap comparisons evaluate the unrounded intermediate against the cap before the final rounding step.

### 2.6. Optimistic Concurrency Control

State-mutating operations that target a specific resource by its `id` (issuing or sealing a confirmation, settling or extending a payment, completing a transfer-order handover, and so on) may include the most recently observed `version` of that resource in the request body. If the supplied `version` does not match the server's current value, the operation is rejected with `ERR_VERSION_CONFLICT`. If the request body omits `version`, the server processes the mutation without the optimistic-concurrency check. Successful mutations increment `version` by one and update `updated_at`.

### 2.7. Hierarchical Consistency and Cascading Side Effects

State transitions on the platform are not isolated events — they trigger ordered cascades across related entities, and each cascade hop is itself atomic with the triggering call (the consistency model is immediate, not eventually consistent). When an `Auction` closes successfully, the `Lot.status` is bubbled to `AUCTIONED`, every `Deposit` whose `bidder_account_id` does not equal the `outcome_winner_account_id` and whose status is `PAID` is moved to `REFUNDED`, and the refund SLA clock starts on each refunded deposit (its `refund_due_at` is set to the current instant plus seventy-two hours). When a `TransferOrder` reaches `COMPLETED`, the parent `Lot.status` bubbles to `TRANSFERRED`. When a winner's `Payment` is forfeited, the matched `Deposit` cascades to `FORFEITED`, the `Lot.round_number` is incremented, and a new auction round is spawned — unless the second-bidder offer path has already been invoked to short-circuit the re-auction. Every entity touched by such a cascade has its `updated_at` refreshed and its `version` incremented; `Bid` and `AuditEvent` are append-only and are not affected by the `updated_at`/`version` mechanic.

### 2.8. Nested Resource Retrieval and Existence Checks

Endpoints with multiple identifiers in their path validate those identifiers in strict left-to-right order. The first identifier that does not resolve to an existing row causes the request to be rejected with `ERR_NOT_FOUND` before any deeper resource is consulted. Foreign-key identifiers passed in request bodies (for example a `lot_id` on auction-creation flows, an `auction_id` on a deposit posting, a `winning_bid_id` on a confirmation draft) are likewise verified to refer to existing rows, again with `ERR_NOT_FOUND` on miss.

### 2.9. Validation Priority Ordering

Several requests trigger more than one check. The platform evaluates validations in a fixed priority order so that error responses are deterministic and the most fundamental violation is always surfaced first: presence of the authentication headers (`ERR_AUTH_MISSING`) is checked before role authorisation (`ERR_AUTH_FORBIDDEN`); role authorisation is checked before path-parameter existence (`ERR_NOT_FOUND`), which is in turn checked before request-body foreign-key existence (also `ERR_NOT_FOUND`); existence checks complete before any state-machine precondition (`ERR_INVALID_STATE`) is consulted; and only after the state check do business-safety rules (such as bidder-account activeness, statutory notice, and winner disqualification), business-temporal rules (inspection-window placement, handover-agency spacing), business-constraint rules (bid increment ladder, bid cap, deposit-must-be-paid, empty-bid-set guard, second-bidder eligibility), business-fiscal rules (full-payment requirement, deposit-deadline freshness), and business-referential rules (real-estate tenancy clearance, re-auction round limit) fire. Within each category, the priorities encoded in this document are the source of truth.

Generic structural problems with a request body — a missing required field, a value with the wrong type, or an enum value outside the allowed set for that field — are reported as `ERR_VALIDATION` with HTTP 422.

### 2.10. Audit Trail and Event Sourcing

Every state-affecting operation emits an `AuditEvent` row that records `kind`, `actor_role`, `actor_id` (taken from the request's `X-User-ID`, or the literal string "system" for automatic transitions driven by the clock or by cascades), `subject_entity`, `subject_id`, and a structured `payload` capturing the relevant before/after values. The event kinds the platform emits are `BID_PLACED`, `BID_REJECTED`, `BID_ROLLED_BACK`, `SOFT_CLOSE_EXTENSION`, `AUCTION_CLOSED`, `DEPOSIT_PAID`, `DEPOSIT_REFUNDED`, `DEPOSIT_FORFEITED`, `CONFIRMATION_ISSUED`, `CONFIRMATION_SEALED`, `CONFIRMATION_FAILED`, `PAYMENT_RECEIVED`, `PAYMENT_OVERDUE`, `TRANSFER_NOTIFIED`, `TRANSFER_COMPLETED`, `COLLUSION_FLAGGED`, `REAUCTION_TRIGGERED`, and `SYSTEM_FAULT_ROLLBACK`. `AuditEvent` rows are append-only — they expose only `id` and `created_at` as system fields and never carry `updated_at` or `version`.

### 2.11. Identity Masking and the Public Bid Feed

The auction record and the bid feed are public surfaces: every caller, including `Observer`, can read them. To preserve bidder privacy on this surface, every `Bid` carries a server-computed `masked_handle` (for example `"Bidder #042"`) that is rendered to non-`CourtClerk` callers; the underlying `bidder_account_id` is omitted from any payload returned to `AuctionAdmin`, `Bidder`, or `Observer`. A `Bidder` reading the feed receives the unmasked `bidder_account_id` only on their own bids; for everyone else's bids they see the `masked_handle`. Only `CourtClerk` reads the un-masked view.

### 2.12. Concurrency Serialization on Hot Resources

Because several flows allow multiple actors to act on the same resource at the same instant, the platform serialises concurrent mutations as follows. Two bids that arrive with identical `amount_cents` on the same auction at the same server second serialise to first-writer-wins on `Auction.current_high_cents`, with the tie broken in favour of the lower `(client_seq_no, created_at)` pair; the loser sees `current_high_cents` already equal to its own amount and is rejected with `ERR_BID_NOT_ABOVE_HIGH`. Two bids that both target the `bid_cap_cents` exactly serialise the same way, except that the loser observes `current_high_cents` already at the cap and is rejected with `ERR_BID_AT_OR_ABOVE_CAP`. A `CourtClerk` who issues a confirmation while another terminal simultaneously fails it serialises on the `Confirmation.status` write — exactly one of the two writes lands on the `DRAFT → {ISSUED, FAILED}` edge, and the loser is rejected with `ERR_INVALID_STATE`. A `Bidder` who attempts to settle a balance at the same instant the clock advance is flipping the payment to `FORFEITED` is rejected with `ERR_PAYMENT_FORFEITED` if the forfeit write committed first. A `Bidder` who raises a refund-delay dispute at the same instant the system completes the refund is rejected with `ERR_DEPOSIT_ALREADY_REFUNDED` if the refund landed first. Two deposit-creation attempts by the same bidder on the same auction serialise on the uniqueness of `(auction_id, bidder_account_id)`; the second is rejected with `ERR_DEPOSIT_DUPLICATE`.

## 3. Business Logic & Workflows

### 3.1. Lot Intake and Statutory Notice

A judicial auction begins with a `CourtClerk` registering a `Lot` from court-order intake. The intake payload identifies the underlying court order by `court_order_no` (which must be non-empty and is unique across the system; collisions are rejected with `ERR_DUPLICATE`), declares the `asset_profile` as one of `REAL_ESTATE`, `VEHICLE`, `EQUITY`, or `MOVABLE_ASSET`, supplies the court-appointed assessor's valuation as `assessment_value_cents` (a positive integer of at least one cent), attaches the `assessment_report_uri` of the assessor's PDF, optionally enumerates known `encumbrances` (each entry an object containing a `kind` of `MORTGAGE`, `LIEN`, or `TENANCY` together with a free-text description; an omitted list defaults to empty), pins the planned `auction_scheduled_start_at`, and frames the asset inspection period with `inspection_window_start_at` and `inspection_window_end_at`. The inspection window must end strictly before the planned auction start; an `inspection_window_end_at` greater than or equal to `auction_scheduled_start_at` is rejected with `ERR_INSPECTION_OVERLAPS_AUCTION`. A successful registration creates the `Lot` row in `REGISTERED` status (its `status` field is computed and defaults to `DRAFT` at row level, but the registration transition writes `REGISTERED` atomically) and creates the first sibling `Auction` for `round_number` 1 with its `starting_price_cents` computed as described in §3.3.

Additional inspection windows may be appended later by either a `CourtClerk` or an `AuctionAdmin`, supplying a `start_at` and an `end_at`. Two inspection windows on the same lot may not overlap, and adjacency counts as overlap — that is, a new window whose `start_at` is exactly equal to an existing window's `end_at` is rejected (closed-interval semantics). Overlapping or touching attempts surface `ERR_INSPECTION_WINDOW_CONFLICT`.

The `CourtClerk` then publishes the auction announcement, transitioning the `Lot.status` from `REGISTERED` to `ANNOUNCED`. This transition stamps `announcement_published_at` to the current instant and pins the `deposit_amount_cents` on the sibling `Auction` as described in §3.4. The announcement is only valid if the gap between the planned `auction_scheduled_start_at` and the current instant is at least fifteen calendar days — the statutory notice period — and the sibling auction for the current `round_number` already exists in `SCHEDULED` status. An announcement attempted with less than fifteen calendar days of notice is rejected with `ERR_STATUTORY_NOTICE_INSUFFICIENT`. The announcement transition itself does not emit a dedicated audit event; downstream cascades (such as a subsequent auction closing) emit their own.

Before any auction has gone live or sold, a `CourtClerk` may withdraw the lot, transitioning `Lot.status` from `REGISTERED` to `WITHDRAWN` (an optional `reason` may accompany the withdrawal). A withdrawal is rejected if any associated `Auction` has already reached `LIVE` or `SOLD`. `WITHDRAWN` and `TRANSFERRED` are the terminal states of the lot machine; the post-sale `TRANSFERRED` arrival is described in §3.10.

### 3.2. Bidder Account Registration and Real-Name Authentication

An `AuctionAdmin` registers a `BidderAccount` from a real-name authentication payload containing the bidder's legal `real_name`, their government-issued `id_document_no` (non-empty; the platform enforces uniqueness on `id_document_no` for all rows whose `status` is `ACTIVE`, returning `ERR_DUPLICATE` on collision), and an optional `ip_fingerprint` recorded on first login. The account is created with `status` `ACTIVE` and an initial `collusion_risk_score` of zero. The system tracks `account_age_days` as the integer floor of days since `created_at`; this value is referenced by the anti-collusion calculation in §3.6.

The account remains `ACTIVE` until anti-collusion observation moves it through `SUSPENDED` to potentially `BLOCKED`. A `SUSPENDED` account can be returned to `ACTIVE` only by a `CourtClerk`, by submitting `investigation_resolved` set to true; once `BLOCKED`, the account is terminal.

### 3.3. Starting Price Computation Across Rounds

The starting price for the first auction of a lot is the court-appointed assessment value discounted by thirty percent. Precisely: when the auction's `round_number` is one, `starting_price_cents` is the result of multiplying `Lot.assessment_value_cents` by ten thousand minus three thousand (the basis-point representation of the first-auction discount), then dividing by ten thousand, then rounding half up to integer cents. Multiplication precedes division; no intermediate division is performed before the rounding step.

Re-auction rounds discount further. When `round_number` is greater than one, `starting_price_cents` is computed from the prior round's `starting_price_cents` — not from the original `assessment_value_cents` — by multiplying that prior value by ten thousand minus two thousand (the basis-point representation of the twenty-percent per-round re-auction discount), dividing by ten thousand, then rounding half up. Because each round consumes the prior round's starting price as its base, the discount compounds: a second round's starting price is the first round's starting price reduced by twenty percent, and a third round's starting price is the second round's starting price reduced by another twenty percent.

The `Lot.round_number` starts at one on registration and is incremented by one each time a re-auction is triggered. A re-auction may be triggered by a failed confirmation, an unsold auction, or a forfeited winner's payment when the second-bidder fallback is not available. Re-auctions are capped: when the current `round_number` is three, no further re-auction is permitted and the lot closes unsold; an attempt to trigger one is rejected with `ERR_REAUCTION_LIMIT_REACHED`. A successful re-auction creation emits `REAUCTION_TRIGGERED`.

### 3.4. Deposit Amount and Posting

When the auction announcement publishes, the platform pins the `deposit_amount_cents` on the auction using the mode the operator chose. If `deposit_mode` is `FIXED`, `deposit_amount_cents` is taken literally from `deposit_fixed_cents`, which must not exceed the auction's `starting_price_cents`. If `deposit_mode` is `PERCENT`, `deposit_amount_cents` is computed as the `starting_price_cents` multiplied by `deposit_percent_bps`, divided by ten thousand, and rounded half up to integer cents; `deposit_percent_bps` must lie between five hundred and three thousand basis points inclusive (that is, between five percent and thirty percent of the starting price). Percent-mode deposits scale automatically with each re-auction round because the underlying `starting_price_cents` is itself recomputed each round; fixed-mode deposits do not scale.

A bidder, or an `AuctionAdmin` acting on a bidder's behalf, posts a `Deposit` row by submitting the targeted `auction_id` and the `bidder_account_id`. The new row carries `amount_cents` snapshotted from the auction's current `deposit_amount_cents`, status `PENDING`, and no `paid_at`, `refunded_at`, `refund_due_at`, or `dispute_opened_at`. The same `(auction_id, bidder_account_id)` pair must be unique; a duplicate is rejected with `ERR_DEPOSIT_DUPLICATE`.

The bidder marks the deposit `PAID` once funds have arrived in the escrow account; this transition is only valid while the auction is `SCHEDULED` or `LIVE`, the bidder's account is `ACTIVE`, and the current instant is not after the auction's `deposit_deadline_at`. A payment attempt after the deadline is rejected with `ERR_DEPOSIT_DEADLINE_PASSED`. Successful payment stamps `paid_at` and emits `DEPOSIT_PAID`; an account not in `ACTIVE` status is rejected with `ERR_BIDDER_NOT_ACTIVE`.

### 3.5. Live Bidding, Increment Ladder, and Soft-Close Extension

Once the announcement is in place, an `AuctionAdmin` opens the auction, advancing it from `SCHEDULED` to `LIVE`. Opening is only permitted when the current instant has reached `scheduled_start_at`, the parent lot is `ANNOUNCED`, and the auction's `starting_price_cents` and `deposit_amount_cents` are both pinned. The transition also sets `effective_end_at` equal to `scheduled_end_at`; the effective end may later drift forward through soft-close extensions but never backward.

A `CourtClerk` may cancel a `SCHEDULED` auction so long as no bid has yet been placed (that is, `current_high_cents` is still null). Cancellation accepts a `reason` and moves `status` to `CANCELLED`. The cancellation cascades to every `Deposit` on this auction that has status `PAID`, moving each to `REFUNDED`.

While the auction is `LIVE`, a `Bidder` places a bid by submitting `auction_id`, `amount_cents`, and a monotonic per-bidder `client_seq_no`. A successful bid creates a new `Bid` row whose `validity` defaults to `VALID`, captures the server-side `created_at`, and computes a public-facing `masked_handle` that never reveals the underlying `bidder_account_id`. Several preconditions must hold for the bid to be accepted:

- The bidder's `BidderAccount.status` must be `ACTIVE`; otherwise the bid is rejected with `ERR_BIDDER_NOT_ACTIVE`.
- The bidder must already have a `Deposit` on this `auction_id` in `PAID` status; otherwise the bid is rejected with `ERR_DEPOSIT_NOT_PAID`.
- The submitted `amount_cents` must be at least the ladder minimum described below; a smaller amount is rejected with `ERR_BID_NOT_ABOVE_HIGH`.
- If the auction's `bid_cap_cents` is not null, `amount_cents` must not be strictly greater than the cap; equality with the cap is accepted, but any value above the cap is rejected with `ERR_BID_AT_OR_ABOVE_CAP`.

The bid-increment ladder determines the minimum acceptable next bid. Take as the ladder base `current_high_cents` if any valid bid exists on this auction, otherwise `starting_price_cents`. The applicable increment is then read from a four-tier ladder by inspecting the base:

- If the base is strictly less than fifty million cents (that is, less than five hundred thousand units), the increment is one hundred thousand cents (one thousand units).
- If the base is at least fifty million cents but strictly less than two hundred million cents (that is, less than two million units), the increment is five hundred thousand cents (five thousand units).
- If the base is at least two hundred million cents but strictly less than one billion cents (that is, less than ten million units), the increment is one million cents (ten thousand units).
- If the base is at least one billion cents, the increment is five million cents (fifty thousand units).

When at least one valid bid already exists, the minimum acceptable next bid is the current high plus the applicable increment, and the submitted `amount_cents` must be greater than or equal to that minimum (equality is accepted). When no valid bid exists yet, the very first bid may equal `starting_price_cents` exactly — the ladder increment does not apply to the opening bid. Constants in the ladder are exact integers and no rounding is performed. The computed minimum is published on the auction as `bid_increment_cents` and is recomputed after each accepted bid.

Soft-close extension applies on every accepted bid. If the remaining time until `effective_end_at` is strictly less than `soft_close_window_seconds`, the auction's `effective_end_at` is reset to the current instant plus `soft_close_extension_seconds`. The comparison is strict — a bid arriving exactly at the boundary (with the remaining time equal to `soft_close_window_seconds`) does not extend; a bid one second further inside the window does. Repeated qualifying bids compound: each one resets the end to the current instant plus the extension. Both `soft_close_window_seconds` and `soft_close_extension_seconds` default to three hundred (that is, five minutes) when not supplied, and each must be at least one second. A qualifying extension emits `SOFT_CLOSE_EXTENSION`; every accepted bid emits `BID_PLACED`.

When the auction's clock advances past `effective_end_at`, the system closes the session. If at least one `VALID` bid exists (`current_high_cents` is not null), the auction moves from `LIVE` to `SOLD`, `outcome_winner_account_id` is recorded as the `bidder_account_id` of the highest-bid winner, `highest_bid_id` and `second_highest_bid_id` are pinned, and the parent `Lot.status` bubbles to `AUCTIONED`. Every `Deposit` on this auction whose `bidder_account_id` is not the winning account and whose status is `PAID` cascades to `REFUNDED`, and on each such refunded deposit the `refund_due_at` is set to the current instant plus seventy-two hours; the cascade emits one `DEPOSIT_REFUNDED` per refunded row and one `AUCTION_CLOSED` event. If no valid bid exists, the auction instead moves from `LIVE` to `UNSOLD`, the parent `Lot.status` still bubbles to `AUCTIONED`, the platform schedules a re-auction subject to the round limit, and every `PAID` deposit on this auction also cascades to `REFUNDED`.

To allow tests and automation to drive these time-gated transitions deterministically, an admin-only capability advances the simulated server clock to a supplied `to` instant. Reaching that instant fires any pending automatic transitions: `LIVE → SOLD` or `LIVE → UNSOLD` when `effective_end_at` is in the past, and `PENDING → OVERDUE` on payments whose `due_at` has elapsed.

### 3.6. Anti-Collusion Observation

Every accepted bid triggers a recomputation of the bidding account's `collusion_risk_score` against the pool of `ACTIVE` co-bidders on the same auction. For each peer the platform computes four binary indicators:

- **Shared IP fingerprint** — set to one if the peer's `ip_fingerprint` equals the acting bidder's; zero otherwise.
- **Alternating pattern** — set to one if the last four `VALID` bids on this auction strictly alternate between the acting bidder and this peer (in either order); zero otherwise.
- **Identical increment** — set to one if the last three `VALID` bid deltas from the acting bidder and this peer are all exactly equal to the ladder's current increment; zero otherwise.
- **Young account** — set to one if the acting bidder's `account_age_days` is strictly less than thirty; zero otherwise.

Each indicator is multiplied by its weight — forty for shared IP, thirty for the alternating pattern, twenty for identical increments, ten for the young-account flag — and the four products are summed into a per-peer score. The account's `collusion_risk_score` is the maximum of those per-peer scores across all peers on the auction (or zero if there are no peers); the platform explicitly takes the maximum, not the sum, to avoid double-counting peers. The result is an integer in the closed range zero to one hundred and is stored as is — no rounding is applied.

Two thresholds gate state transitions on the bidder's account. When the recomputed `collusion_risk_score` lands in the closed range sixty through seventy-nine, the account moves from `ACTIVE` to `SUSPENDED`; the bidder cannot place new bids while suspended, but existing bids remain `VALID` and the auction's current high is not disturbed. When the score reaches eighty or higher, the account moves to `BLOCKED`; all of the blocked account's bids on `LIVE` auctions have their `validity` rewritten to `ROLLED_BACK`, and each affected auction's `current_high_cents` and `highest_bid_id` are recomputed from the remaining `VALID` bids — which may surface a new high or, if no valid bids remain, may leave the auction with a null current high. Both transitions emit `COLLUSION_FLAGGED`.

A `CourtClerk` may return a `SUSPENDED` account to `ACTIVE` after investigation; the body for that operation carries `investigation_resolved` set to true. A `BLOCKED` account is terminal — there is no clearance path.

### 3.7. System-Fault Rollback

When the platform experiences a technical incident on a live session, an `AuctionAdmin` may invoke an operator capability that marks the most recent `N` bids on a given auction as `ROLLED_BACK`. The request body supplies `last_n_bids` and a free-text `fault_reason`. The targeted bids' `validity` is rewritten from `VALID` to `ROLLED_BACK`, and the auction's `current_high_cents` and `highest_bid_id` are recomputed from the remaining `VALID` bids — exactly as in the BLOCKED-account cascade described in §3.6. Crucially, soft-close extension is **not** re-applied for rolled-back triggers; the `effective_end_at` retains whatever extensions earlier valid bids produced and does not contract. The capability emits `SYSTEM_FAULT_ROLLBACK`. A rejected bid (one that failed the increment ladder, bid cap, or another precondition) emits `BID_REJECTED` rather than being silently dropped; a bid whose `validity` flips to `ROLLED_BACK` later emits `BID_ROLLED_BACK`.

### 3.8. Confirmation Ruling, Failure, and Sealing

After an auction reaches `SOLD`, a `CourtClerk` drafts a `Confirmation` by submitting the `auction_id`, the `ruling_document_uri` of the court's ruling document, and an optional `use_second_bidder` flag. The `winning_bid_id` on the draft is resolved automatically from the auction: when `use_second_bidder` is omitted or false, it equals `Auction.highest_bid_id`; when `use_second_bidder` is true, it equals `Auction.second_highest_bid_id`. The empty-set guard rejects a draft against an auction whose `current_high_cents` is null with `ERR_NO_VALID_BIDS`. The second-bidder offer path is only available when `Auction.second_highest_bid_id` is not null and that bidder's account is `ACTIVE`; otherwise the request is rejected with `ERR_NO_ELIGIBLE_SECOND_BIDDER`. Uniqueness of `auction_id` is enforced for any confirmation whose `status` is not `FAILED`, so a fresh `DRAFT` cannot be created against an auction that already has an `ISSUED` or `SEALED` confirmation; collisions surface `ERR_DUPLICATE`.

The `CourtClerk` then issues the ruling, transitioning the confirmation from `DRAFT` to `ISSUED`. Issuance is only valid when the parent auction is `SOLD`, the draft's `winning_bid_id` still equals `Auction.highest_bid_id` (or, on a second-bidder draft, `Auction.second_highest_bid_id`), the winner's `BidderAccount.status` is `ACTIVE`, and the `ruling_document_uri` is non-empty. A winning bidder who is `BLOCKED` or whose `collusion_risk_score` is at or above eighty at issuance time is rejected with `ERR_WINNER_DISQUALIFIED`. The transition stamps `issued_at` to the current instant, creates a `Payment` row as described in §3.9, and emits `CONFIRMATION_ISSUED`.

Alternatively, when collusion is confirmed, the winner is disqualified, or the court overrides the result, the `CourtClerk` transitions the confirmation from `DRAFT` to `FAILED` by supplying a `failure_reason` of `COLLUSION_FOUND`, `BIDDER_DISQUALIFIED`, or `COURT_OVERRIDE`. The transition triggers a re-auction by incrementing `Lot.round_number` and creating a new auction row (subject to the round-three cap, in which case `ERR_REAUCTION_LIMIT_REACHED` fires). When the `failure_reason` is `COLLUSION_FOUND` or `BIDDER_DISQUALIFIED`, the winning bidder's deposit is additionally forfeited; `COURT_OVERRIDE` does not forfeit the deposit. The transition emits `CONFIRMATION_FAILED`.

After payment is fully received and a transfer order is in place, the `CourtClerk` seals the confirmation by moving it from `ISSUED` to `SEALED`. Sealing requires the matched `Payment.status` to be `PAID` and a `TransferOrder` whose `status` is not `BLOCKED`. The transition stamps `sealed_at` and emits `CONFIRMATION_SEALED`. `SEALED` and `FAILED` are the terminal states of the confirmation machine. `Confirmation.failure_reason` is null on any confirmation whose `status` is not `FAILED`.

### 3.9. Balance Payment, Penalty Accrual, and Forfeiture

Issuing a confirmation creates a `Payment` row tied to the `confirmation_id` (uniqueness is enforced on `confirmation_id`). The `balance_due_cents` is pinned at issuance to the winning bid amount minus the matched deposit's `amount_cents`: precisely, it equals `Auction.current_high_cents` minus the `amount_cents` of the single `Deposit` row whose `auction_id` matches the confirmation's auction, whose `bidder_account_id` equals `Auction.outcome_winner_account_id`, and whose status is `PAID`. The result cannot be negative — the deposit calculation and the bid increment ladder together guarantee the winning bid is at least the starting price and therefore at least the deposit. The edge case where the bid equals the deposit yields a `balance_due_cents` of zero; in that case the payment is automatically marked `PAID` at creation. The row carries `amount_paid_cents` initialised to zero, `penalty_accrued_cents` initialised to zero, `status` `PENDING`, a `due_at` equal to the issuance instant plus the auction's `payment_deadline_days` (which must be at least one day and is captured at auction setup time), and a null `receipt_no`.

When the clock advances past `due_at`, the payment automatically moves from `PENDING` to `OVERDUE` and emits `PAYMENT_OVERDUE`. While the payment is `OVERDUE`, late-payment penalty accrues on every state-affecting read. The number of days overdue is the ceiling of the elapsed seconds since `due_at` divided by eighty-six thousand four hundred. The uncapped penalty equals `balance_due_cents` multiplied by fifty (the daily penalty in basis points, that is half a percent per calendar day) multiplied by the number of days overdue, with the full-precision intermediate then divided by ten thousand. A hard cap equals `balance_due_cents` multiplied by one thousand (the maximum penalty in basis points, that is ten percent of the balance), again divided by ten thousand. The stored `penalty_accrued_cents` is the lesser of the uncapped value and the cap, then rounded half up to integer cents; the cap comparison uses the unrounded intermediates. Equivalently, penalty grows linearly at half a percent of the balance per calendar day for the first twenty days, then plateaus at ten percent of the balance for every day thereafter — at twenty days of overdue the linear value equals the cap, and from day twenty-one onward the cap dominates. While the payment is `PENDING` or `PAID`, `penalty_accrued_cents` is recomputed as zero.

A `Bidder` settles the obligation by submitting `amount_cents` against the payment. The settlement is only valid when the payment's current `status` is `PENDING` or `OVERDUE`, and the submitted amount, added to the current `amount_paid_cents`, is at least the sum of `balance_due_cents` and `penalty_accrued_cents`. A settlement that does not clear the full obligation in a single call is rejected with `ERR_PARTIAL_PAYMENT_REJECTED` — the platform does not accept partial payments. A successful settlement adds the submitted amount to `amount_paid_cents`, flips `status` to `PAID`, mints a `receipt_no`, and emits `PAYMENT_RECEIVED`.

A `CourtClerk` may grant grace by extending an `OVERDUE` payment back to `PENDING`. The request body carries `extension_days`, which must be at least one and at most fourteen days. The transition sets `due_at` to the current instant plus the supplied number of days, returns `status` to `PENDING`, and pauses penalty accrual while retaining the already-accrued `penalty_accrued_cents`. This `PENDING → OVERDUE → PENDING` cycle is the cyclic shape of the payment machine.

If the payment remains `OVERDUE` for more than seven calendar days past `due_at`, the `CourtClerk` may forfeit it. The transition moves the payment to `FORFEITED`; the winner's `Deposit` cascades from `PAID` to `FORFEITED` (emitting `DEPOSIT_FORFEITED`); `Lot.round_number` is incremented and a new auction round is created (subject to the round-three cap), unless the second-bidder offer flow has been invoked beforehand to short-circuit the re-auction. A settlement attempted on a `FORFEITED` payment is rejected with `ERR_PAYMENT_FORFEITED`.

### 3.10. Deposit Refund, Dispute, and Resolution

A non-winning bidder's deposit refund SLA starts at auction close: the `refund_due_at` is set to the close instant plus seventy-two hours, and the system's periodic refund sweep is responsible for finalising any `PAID` deposits on auctions in `SOLD`, `UNSOLD`, or `CANCELLED` that have not yet been moved to `REFUNDED`. A test-driving sweep capability invokes that sweep on demand.

If the refund has not landed by `refund_due_at`, the bidder may raise a dispute, transitioning the deposit from `PAID` to `DISPUTED` with an optional `dispute_note`. The transition is only valid when the current instant is strictly past `refund_due_at` and the deposit is still `PAID`; a deposit that the refund sweep has already moved to `REFUNDED` cannot be disputed and surfaces `ERR_DEPOSIT_ALREADY_REFUNDED`. The transition stamps `dispute_opened_at`.

A `CourtClerk` resolves the dispute by transitioning the deposit from `DISPUTED` to `REFUNDED`, optionally attaching a `resolution_note`. The transition stamps `refunded_at`. The deposit's terminal states are `REFUNDED` and `FORFEITED`.

### 3.11. Transfer Order and Counterpart Coordination

Once the winner's payment is `PAID`, an `AuctionAdmin` initiates a `TransferOrder` against the `confirmation_id`. The request carries the `handover_scheduled_at` instant, the `transfer_instrument_uri` of the prepared transfer document, and optionally `tenancy_cleared`. The `counterpart_agency` is derived from the parent `Lot.asset_profile` on creation: `REAL_ESTATE` maps to `REAL_ESTATE_REGISTRY`, `VEHICLE` to `VEHICLE_AUTHORITY`, `EQUITY` to `EQUITY_REGISTRY`, and `MOVABLE_ASSET` to `COURT_BAILIFF`. Uniqueness on `confirmation_id` ensures one transfer order per confirmation. Two transfer orders on the same `counterpart_agency` whose `handover_scheduled_at` values fall on the same calendar day must be at least four hours apart (the agency-handover buffer); two handovers exactly four hours apart are allowed (half-open interval semantics — touching at the buffer boundary is permitted). Closer spacing is rejected with `ERR_HANDOVER_AGENCY_BUSY`.

The order's `status` begins at `INITIATED`. An `AuctionAdmin` notifies the counterpart registry, transitioning to `AGENCY_NOTIFIED`; this requires the parent `Confirmation.status` to be `ISSUED` or `SEALED`, the matched `Payment.status` to be `PAID`, and `transfer_instrument_uri` to be non-empty. The transition emits `TRANSFER_NOTIFIED` annotated with `counterpart_agency`.

The `AuctionAdmin` then marks the physical handover done, moving the order from `AGENCY_NOTIFIED` to `HANDOVER_DONE`. This transition requires the current instant to be at or after `handover_scheduled_at`. For real-estate lots, it additionally requires `tenancy_cleared` to be true; a `REAL_ESTATE` order whose tenancy is not cleared is rejected with `ERR_TENANCY_NOT_CLEARED`. The `tenancy_cleared` flag may be set at order creation or refreshed by passing it on the handover call.

Alternatively, when the counterpart agency rejects the transfer or a tenancy issue blocks progress, the `AuctionAdmin` blocks the order by supplying a non-empty `blocked_reason`. The transition moves `AGENCY_NOTIFIED` to `BLOCKED`, which is terminal.

Finally, the `CourtClerk` confirms completion, moving the order from `HANDOVER_DONE` to `COMPLETED`. The transition bubbles the parent `Lot.status` to `TRANSFERRED` and emits `TRANSFER_COMPLETED`. `COMPLETED` and `BLOCKED` are the terminal states of the transfer-order machine, and `TRANSFERRED` is the terminal post-sale state of the lot.

### 3.12. Audit Querying, External Event Ingestion, and Read Filters

A `CourtClerk` may query the audit trail through a list endpoint that accepts `subject_entity`, `subject_id`, `kind`, `since`, and `until` filters together with the standard `limit` and `offset` paging parameters. Auction-bid listings accept a `validity` filter to scope by `VALID`, `REJECTED`, or `ROLLED_BACK`; a bidder reading the feed sees only their own bid in un-masked form, while every other entry is rendered via its `masked_handle`. The lot listing accepts a `status` filter to scope by `DRAFT`, `REGISTERED`, `ANNOUNCED`, `AUCTIONED`, `WITHDRAWN`, or `TRANSFERRED`.

To support tests that simulate counterpart-agency callbacks, payment-gateway notifications, or court-system events, the platform exposes an automation-only event-ingestion capability that accepts a `source`, a `kind`, and a structured `payload` and routes the call to the matching internal handler. A successful ingestion is accepted with HTTP 202.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — registering a lot, posting a deposit, placing a bid, drafting a confirmation, initiating a transfer order, or registering a bidder account — return HTTP 201. Operations that modify an existing resource, including the various lifecycle transitions and read endpoints, return HTTP 200. The external-event ingestion capability returns HTTP 202. All endpoints are mounted under the platform's API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/lots` | Register a new lot from court-order intake. | CourtClerk |
| GET    | `/lots` | List lots with pagination. | CourtClerk, AuctionAdmin, Bidder, Observer |
| GET    | `/lots/{lot_id}` | Fetch a lot. | CourtClerk, AuctionAdmin, Bidder, Observer |
| POST   | `/lots/{lot_id}/announce` | Publish auction announcement; starts statutory notice clock. | CourtClerk |
| POST   | `/lots/{lot_id}/inspection-windows` | Add an additional inspection window. | CourtClerk, AuctionAdmin |
| POST   | `/lots/{lot_id}/withdraw` | Withdraw the lot before any LIVE auction. | CourtClerk |
| POST   | `/bidder-accounts` | Register a bidder with real-name authentication. | AuctionAdmin |
| GET    | `/bidder-accounts/{account_id}` | Fetch a bidder account. | AuctionAdmin, CourtClerk, Bidder |
| POST   | `/bidder-accounts/{account_id}/clear` | Clear a SUSPENDED account after investigation. | CourtClerk |
| GET    | `/auctions/{auction_id}` | Fetch an auction; bidder identities masked unless caller is CourtClerk. | CourtClerk, AuctionAdmin, Bidder, Observer |
| POST   | `/auctions/{auction_id}/open` | Open the auction for live bidding. | AuctionAdmin |
| POST   | `/auctions/{auction_id}/cancel` | Cancel a SCHEDULED auction with no bids. | CourtClerk |
| GET    | `/auctions/{auction_id}/bids` | List bids on an auction; masks bidder identity for non-CourtClerk callers. | CourtClerk, AuctionAdmin, Bidder, Observer |
| POST   | `/auctions/{auction_id}/system-rollback` | Operator-invoked system-fault rollback. | AuctionAdmin |
| POST   | `/deposits` | Post a deposit (PENDING) for a bidder on an auction. | Bidder, AuctionAdmin |
| POST   | `/deposits/{deposit_id}/pay` | Mark deposit PAID. | Bidder |
| POST   | `/deposits/{deposit_id}/raise-dispute` | Raise refund-delay dispute after refund_due_at elapsed. | Bidder |
| POST   | `/deposits/{deposit_id}/resolve-dispute` | Resolve dispute and complete refund. | CourtClerk |
| POST   | `/bids` | Place a bid. | Bidder |
| POST   | `/confirmations` | Create a DRAFT confirmation for a SOLD auction. | CourtClerk |
| POST   | `/confirmations/{confirmation_id}/issue` | Issue the court confirmation ruling. | CourtClerk |
| POST   | `/confirmations/{confirmation_id}/fail` | Fail the confirmation; triggers re-auction. | CourtClerk |
| POST   | `/confirmations/{confirmation_id}/seal` | Seal the confirmation into the court file. | CourtClerk |
| GET    | `/payments/{payment_id}` | Fetch payment; penalty_accrued_cents recomputed on read. | CourtClerk, AuctionAdmin, Bidder |
| POST   | `/payments/{payment_id}/settle` | Settle balance + accrued penalty in full. | Bidder |
| POST   | `/payments/{payment_id}/extend` | Court grants grace extension on an OVERDUE payment. | CourtClerk |
| POST   | `/payments/{payment_id}/forfeit` | Forfeit an OVERDUE payment past the grace window. | CourtClerk |
| POST   | `/transfer-orders` | Initiate a transfer order against a paid Confirmation. | AuctionAdmin |
| POST   | `/transfer-orders/{transfer_order_id}/notify-agency` | Notify counterpart registry of pending transfer. | AuctionAdmin |
| POST   | `/transfer-orders/{transfer_order_id}/complete-handover` | Mark physical handover done. | AuctionAdmin |
| POST   | `/transfer-orders/{transfer_order_id}/confirm-completion` | Court confirms transfer is complete. | CourtClerk |
| POST   | `/transfer-orders/{transfer_order_id}/block` | Block transfer with reason. | AuctionAdmin |
| GET    | `/audit-events` | Query audit events. | CourtClerk |
| POST   | `/_clock/advance` | Advance simulated server clock (test/automation only). | AuctionAdmin, CourtClerk |
| POST   | `/_sweep/refunds` | Run the periodic refund sweep (test/automation only). | AuctionAdmin |
| POST   | `/_events/emit` | External-event ingestion (test/automation only). | AuctionAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_BIDDER_NOT_ACTIVE` | 403 |
| `ERR_STATUTORY_NOTICE_INSUFFICIENT` | 422 |
| `ERR_WINNER_DISQUALIFIED` | 422 |
| `ERR_INSPECTION_OVERLAPS_AUCTION` | 422 |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 |
| `ERR_HANDOVER_AGENCY_BUSY` | 409 |
| `ERR_BID_NOT_ABOVE_HIGH` | 422 |
| `ERR_BID_AT_OR_ABOVE_CAP` | 422 |
| `ERR_DEPOSIT_NOT_PAID` | 422 |
| `ERR_PARTIAL_PAYMENT_REJECTED` | 422 |
| `ERR_DEPOSIT_DEADLINE_PASSED` | 422 |
| `ERR_TENANCY_NOT_CLEARED` | 422 |
| `ERR_REAUCTION_LIMIT_REACHED` | 409 |
| `ERR_NO_VALID_BIDS` | 422 |
| `ERR_NO_ELIGIBLE_SECOND_BIDDER` | 422 |
| `ERR_PAYMENT_FORFEITED` | 409 |
| `ERR_DEPOSIT_ALREADY_REFUNDED` | 409 |
| `ERR_DEPOSIT_DUPLICATE` | 409 |

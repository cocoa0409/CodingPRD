# Gift Card & Stored-Value Program API — Product Requirements Document

## 1. Introduction

Retailers that run a gift-card and stored-value program juggle three problems at once: they must move value reliably across a network of point-of-sale terminals, they must hold that value as a liability on the books until a customer spends it, and they must obey a patchwork of state escheatment and dormancy laws that decide whether unspent value eventually becomes revenue or money owed back to a state treasury. This API is the system of record for all three concerns. It issues digital and physical cards, activates and reloads them, redeems them across split-tender purchases, applies reload-bonus promotions, assesses dormancy and breakage, refunds value back to a card, replaces compromised cards, and prices B2B bulk orders for corporate buyers.

Every monetary quantity in the system is an integer count of minor currency units — cents — and the platform is built as an append-only event ledger: balances are never stored as a mutable number but are always derived by summing posted ledger entries. This design lets the system answer, at any instant, both "what has actually settled on this card" and "what is still spendable once outstanding authorizations are accounted for," and it lets the program office reconcile its total outstanding liability, its recognized breakage revenue, and its escheat obligations directly from the same entry stream. The sections that follow define the request/response contract, the cross-cutting fiscal and concurrency principles, and the detailed business workflows that operators, cardholders, fraud analysts, and corporate buyers rely on.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted beneath the `/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing the role header, or carrying a role string that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or when an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes five roles, spelled exactly as follows: `ProgramAdmin`, `StoreAssociate`, `Customer`, `FraudAnalyst`, and `B2BBuyer`.

A `ProgramAdmin` configures programs, jurisdiction rules, and campaigns; runs dormancy assessment; activates bulk orders; and adjudicates refunds. A `StoreAssociate` is the point-of-sale operator who issues, activates, and reloads cards, places and releases authorization holds, and drafts, settles, and voids redemptions. A `FraudAnalyst` owns the risk dimension — flagging, freezing, and clearing cards — and adjudicates replacement requests, and may settle a redemption that draws on a flagged card. A `Customer` is a cardholder acting on their own cards, redemptions, refunds, and replacement requests. A `B2BBuyer` is a corporate buyer who places and manages bulk gift-card orders.

These five roles split into two identity models. When `X-User-Role` is `ProgramAdmin`, `StoreAssociate`, or `FraudAnalyst`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`, and these operators are not subject to per-resource ownership checks. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that reference to `X-User-ID` — a `Customer` may act only on a `GiftCard` whose `owner_customer_id` is their own id, on a `Redemption` whose `customer_id` is their own id, and on refund and replacement requests anchored to their own cards. When `X-User-Role` is `B2BBuyer`, `X-User-ID` is likewise the `id` of the acting `Customer` record (a corporate customer); ownership checks on a `BulkOrder` compare its `buyer_customer_id` to `X-User-ID`. A failed ownership check yields `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Append-Only Ledger

Most resources in this system carry a standard set of system-managed fields. Every such resource has an `id`, a server-minted UUID with no type prefix. It also has a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when it was first created, an `updated_at` timestamp recording the most recent modification, and a `version`, an integer that begins at 1 and increments by one on every mutation of the resource. Two entity types are deliberately leaner: a `LedgerEntry` and a `RedemptionLeg` are immutable audit records, so each carries only an `id` and a `created_at` — neither has an `updated_at` and neither has a `version`. Every other entity (Program, StateRule, PromoCampaign, Customer, GiftCard, AuthorizationHold, Redemption, BulkOrder, ReplacementRequest, RefundRequest, DormancyWaiver) carries the full `id`/`created_at`/`updated_at`/`version` set.

The financial heart of the system is the append-only ledger. A `LedgerEntry` records `card_id` (the card it posts to), a `program_id` copied from that card for program-level aggregation, an `entry_type`, a signed `amount_cents`, a `status`, a `source_ref_id`, and a `reverses_entry_id`. The `entry_type` is one of `LOAD`, `RELOAD`, `BONUS`, `REDEEM`, `REFUND`, `TRANSFER_IN`, `TRANSFER_OUT`, `DORMANCY_FEE`, `BREAKAGE`, `ESCHEAT`, or `REVERSAL`. Credits carry a positive `amount_cents` (`LOAD`, `RELOAD`, `BONUS`, `REFUND`, `TRANSFER_IN`, and any `REVERSAL` that cancels a debit); debits carry a negative `amount_cents` (`REDEEM`, `DORMANCY_FEE`, `BREAKAGE`, `ESCHEAT`, `TRANSFER_OUT`). An entry's `status` is `POSTED` when first written and becomes `REVERSED` once a reversing entry cancels it; the reversing entry itself has `entry_type` of `REVERSAL` and sets its `reverses_entry_id` to the `id` of the entry it cancels. The `source_ref_id` records the originating Redemption, RefundRequest, ReplacementRequest, or BulkOrder id for audit purposes only and is not used for reverse traversal.

### 2.5. Balance Derivation — Settled, Pending, and Available

A card's money position is never stored directly; it is recomputed from the ledger on every read of the `GiftCard` and after every entry post, entry reversal, or authorization-hold change. Three derived figures express it. The `settled_balance_cents` is the sum of `amount_cents` over every `LedgerEntry` on the card whose `status` is `POSTED`; entries whose `status` is `REVERSED` are excluded from this sum. The `pending_hold_cents` is the sum of `amount_cents` over every `AuthorizationHold` on the card whose `status` is `ACTIVE`. The `available_balance_cents` is the `settled_balance_cents` minus the `pending_hold_cents`.

These two views serve different purposes and are used in different places, so it matters which one a rule invokes. The **settled** view (posted entries only, holds ignored entirely) is the figure consulted by dormancy assessment, breakage and escheat, and the balance-cap ceiling. The **authorized** view — `available_balance_cents`, which subtracts active holds from settled — is the forward-looking "spendable" figure consulted when a redemption tests whether the chosen cards can cover a sale, and it is the figure surfaced to a cardholder as their spendable balance. Whenever a hold is outstanding the two views diverge by exactly the held amount; with no active holds they coincide. A card also exposes `last_activity_at`, the `created_at` of the most recent `POSTED` `LedgerEntry` on the card, or the card's activation time when no later entry exists. Balances and these aggregates are all integer cents with no rounding, because every amount is already stored in minor units.

### 2.6. Program-Level Liability Aggregation

A `Program` continuously reflects three computed roll-ups derived from its cards and their ledger entries. The `outstanding_liability_cents` is the sum of `settled_balance_cents` across every `GiftCard` in the program whose `lifecycle_status` is either `ACTIVE` or `EXHAUSTED` — that is, the value the retailer still owes its cardholders. The `breakage_recognized_cents` is the total magnitude of all `POSTED` `BREAKAGE` entries in the program (the sum of the negated `amount_cents` of those debits), representing revenue recognized when residual value is forfeited. The `escheat_liability_cents` is the total magnitude of all `POSTED` `ESCHEAT` entries in the program, representing value owed to state treasuries. When a program is first created, these three figures all start at 0. Each is re-derived whenever an underlying ledger event changes it.

### 2.7. Monetary Precision and Rounding

Because all amounts are integer minor units, balance arithmetic, allocation, and transfers are exact and involve no rounding. Rounding enters only where a fractional multiplier is applied to an amount: the reload bonus, the escheat fraction, and the per-card B2B price. In each of those three cases the result is rounded to a whole number of cents using the round-half-up convention (a value ending in exactly one-half cent rounds up to the next cent). Configuration fractions themselves — `b2b_discount_pct`, `bonus_pct`, `escheat_rate` — are stored at their input precision and are not rounded.

### 2.8. Card State: Two Independent Dimensions

A `GiftCard` carries two orthogonal status fields that evolve independently. The `lifecycle_status` tracks issuance through depletion and is one of `INACTIVE`, `ACTIVE`, `VOIDED`, `EXPIRED`, or `EXHAUSTED`; `VOIDED` and `EXPIRED` are terminal. The `risk_status` tracks fraud handling and is one of `CLEAR`, `FLAGGED`, or `FROZEN_RISK`, beginning at `CLEAR`. Because risk is a separate dimension, there is deliberately no "frozen" lifecycle state — a frozen card retains whatever lifecycle status it held. The two dimensions interact only through the gates described in §3: a `FROZEN_RISK` card cannot be redeemed, reloaded, or have a new hold placed on it, and a `FLAGGED` card may be redeemed only along the fraud-review path.

### 2.9. Cascading Side Effects and Reconciliation

Many operations mutate more than one resource. When a card's balance changes, the program's liability roll-ups in §2.6 are re-derived in the same operation. When a redemption debit drives a card's `settled_balance_cents` to exactly zero, the card's `lifecycle_status` auto-transitions from `ACTIVE` to `EXHAUSTED` without any separate client request; conversely a later credit can revive an `EXHAUSTED` card to `ACTIVE`. When a card is frozen, all of its active holds are released as a cascade. When a replacement is approved, value moves off the old card and onto a freshly minted card, and the old card is voided. Each resource that the server mutates as part of such a cascade has its own `updated_at` refreshed and its own `version` incremented; the ledger entries that record the value movement are appended as new immutable records. Throughout, the system applies changes immediately and consistently — a read taken after an operation reflects every cascade that operation triggered.

### 2.10. Nested Reference Validation Order

Although the API surface is flat — every resource lives at `/v1/<collection>/{id}` and children are reached by filtered list queries rather than deep URL nesting — requests still reference other entities both through path identifiers and through foreign-key fields in their bodies. Path identifiers are validated first, left to right: any `id` named in the path that does not resolve to an existing resource yields `ERR_NOT_FOUND` before the body is examined. Once the path resolves, body references are checked: every foreign-key field in the body — including `owner_customer_id`, `card_id`, `redemption_id`, `old_card_id`, `buyer_customer_id`, and every member of `card_id_order` — must reference an existing entity in the same program, otherwise the request is rejected with `ERR_REFERENCE_NOT_FOUND`.

### 2.11. Validation Order of Precedence

When several checks could apply to one request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation, or an owner mismatch, yields `ERR_FORBIDDEN`. Third, path existence is checked left to right, yielding `ERR_NOT_FOUND`. Fourth, the body is checked for well-formedness — required fields present, correct types, and valid enum members — yielding `ERR_VALIDATION`. Fifth, body foreign keys are checked for same-program existence, yielding `ERR_REFERENCE_NOT_FOUND`. Sixth, domain-shape constraints are checked (described per workflow in §3), yielding `ERR_INVALID_REDEMPTION`. Seventh, optimistic-concurrency version checks are applied, yielding `ERR_STALE_VERSION`. Eighth, the target resource's state is checked against the transition, yielding `ERR_INVALID_STATE`. Ninth and tenth, the risk gates apply (`ERR_CARD_RISK_FROZEN`, then `ERR_CARD_RISK_REVIEW`). The remaining business checks — already-replaced, jurisdiction and window gates, fiscal floor/cap, and sufficient balance — follow, each described alongside the workflow it guards. The guiding rule: cheaper, more fundamental checks (identity, existence, shape) precede deeper state and fiscal checks, so that a request failing several conditions surfaces the earliest one.

### 2.12. Optimistic Concurrency Control

Two specific operations guard against acting on a stale view of a parent resource. Each requires the client to submit the `version` it last observed for that parent, and rejects the operation if the parent's current `version` has moved on.

When a redemption is settled, the request must carry `expected_redemption_version`, which must equal the target `Redemption`'s current `version`. A draft redemption can be amended (its `card_id_order` or `requested_amount_cents` revised), and each amendment increments the redemption's `version`. If an amendment has advanced the redemption's version since the client last read it, the client's settle request carries a stale `expected_redemption_version`, and the settle is rejected with `ERR_STALE_VERSION` (HTTP 412) before any debit posts — preventing the operator from settling against an allocation plan that has since been superseded.

When a replacement request is approved, the request must carry `expected_old_card_version`, which must equal the old `GiftCard`'s current `version`. If another writer has reloaded or partially redeemed the old card since the analyst last read it, the card's `version` has advanced, the submitted `expected_old_card_version` is stale, and the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) — so that no value is transferred against a balance that has since changed. No other endpoint takes a version field; operations not named here proceed without an OCC check.

## 3. Business Logic & Workflows

### 3.1. Program Configuration, Jurisdictions, and Promotions

A `ProgramAdmin` stands up the platform by creating a `Program`, supplying its `name` and optionally overriding a set of program-wide defaults: the `default_currency` (an ISO currency code, defaulting to USD, with all amounts expressed in that currency's minor units); the `reload_min_cents` floor that every load and reload must meet (default 500 cents, i.e. five dollars); the `reload_max_balance_cents` ceiling that a card's settled balance may never exceed after any credit (default 100000 cents, i.e. one thousand dollars); the `hold_ttl_seconds` lifetime of an authorization hold (default 900 seconds, i.e. fifteen minutes); and the `b2b_discount_pct` per-card discount applied to bulk-order pricing (default 0.035, i.e. three and one-half percent). At creation the program's `outstanding_liability_cents`, `breakage_recognized_cents`, and `escheat_liability_cents` are all initialized to zero.

The legal treatment of unspent value varies by jurisdiction, so the admin defines a `StateRule` for each state the program operates in. A rule names its `program_id` and a two-letter `state_code`, and the pair of `program_id` and `state_code` must be unique — attempting to define a second rule for the same state in the same program is a domain-shape violation rejected with `ERR_INVALID_REDEMPTION`. Each rule sets `expiration_allowed` (whether stored value may expire in this jurisdiction at all), `dormancy_fee_allowed` (whether a periodic dormancy fee may be charged), and a `breakage_policy` of either `RECOGNIZE` or `ESCHEAT`. Under `RECOGNIZE`, residual value of an expiring card is booked as breakage revenue; under `ESCHEAT`, a fraction of it — the `escheat_rate`, defaulting to 0.60 — is booked as a liability owed to the state. The rule also carries `dormancy_threshold_months`, the whole number of months of inactivity at or beyond which a card becomes dormant (default 12).

To drive reload incentives, the admin creates a `PromoCampaign` against a `program_id`, with a `name`, a `bonus_pct` (the bonus fraction credited on qualifying reloads — for example 0.10 for a ten-percent bonus), and a half-open active window defined by `window_start` (inclusive) and `window_end` (exclusive). The campaign's `status` is one of `SCHEDULED`, `ACTIVE`, or `ENDED`, beginning at `SCHEDULED`. A new campaign window may not overlap any existing campaign in the same program; an overlapping window is rejected with `ERR_CAMPAIGN_OVERLAP`. A campaign's status is recomputed against the clock either by an explicit admin-driven status-synchronization capability or by the system on a clock advance: while the current instant is at or after `window_start` and before `window_end`, the campaign becomes `ACTIVE` (`SCHEDULED → ACTIVE`); once the current instant reaches `window_end`, it becomes `ENDED` (`ACTIVE → ENDED`, or directly `SCHEDULED → ENDED` if the window elapsed before it was ever synced into the active state).

### 3.2. Customers and Card Issuance

Anyone joining the program is registered as a `Customer`, recorded with a unique `email`, a `full_name`, a `residence_state_code` (the two-letter state that serves as the default jurisdiction for that customer's cards), and an `is_corporate` flag that defaults to false. Only a corporate customer — one whose `is_corporate` is true — may place B2B bulk orders; an attempt to confirm a bulk order for a non-corporate buyer is rejected with `ERR_NOT_CORPORATE_BUYER`. A customer may register themselves, or a `ProgramAdmin` may register them.

A card is brought into being when a `StoreAssociate` or `ProgramAdmin` issues a `GiftCard`. Issuance records the `program_id`, the `form_factor` (either `DIGITAL` or `PHYSICAL`), the `state_code` governing the card (which selects the applicable `StateRule`), and optionally an `owner_customer_id` — ownership may be left unassigned at issuance and attached later. A freshly issued card has `lifecycle_status` of `INACTIVE` and `risk_status` of `CLEAR`, with no value on it yet. Cards can be listed and filtered by `program_id`, by `owner_customer_id`, by `lifecycle_status`, or by `replaced_by_card_id`.

### 3.3. Activation, Reload, and Promotional Bonuses

A `StoreAssociate` activates an `INACTIVE` card by supplying an `initial_load_cents` amount; this drives the card from `INACTIVE` to `ACTIVE`. The card must currently be `INACTIVE` — activating a card in any other lifecycle state is rejected with `ERR_INVALID_STATE`. The initial load must be at least the program's `reload_min_cents`, otherwise the request is rejected with `ERR_RELOAD_BELOW_MIN`; and it must not push the settled balance above `reload_max_balance_cents`, otherwise the request is rejected with `ERR_BALANCE_CAP_EXCEEDED`. On success the system appends a `LOAD` credit whose amount equals the initial load, recomputes `settled_balance_cents`, sets `last_activity_at` to that entry's timestamp, and re-derives the program's `outstanding_liability_cents`.

Adding value to a card already in service is a reload, available to a `StoreAssociate` or to the owning `Customer`. A reload supplies an `amount_cents` and applies to a card that is `ACTIVE` (which stays `ACTIVE`) or `EXHAUSTED` (which revives to `ACTIVE`). The card's `risk_status` must not be `FROZEN_RISK`, otherwise the reload is rejected with `ERR_CARD_RISK_FROZEN`. The amount must meet the `reload_min_cents` floor (else `ERR_RELOAD_BELOW_MIN`), and the resulting `settled_balance_cents` must not exceed `reload_max_balance_cents` (else `ERR_BALANCE_CAP_EXCEEDED`). On success a `RELOAD` credit for the supplied amount is posted. If a `PromoCampaign` in the same program is `ACTIVE` at the instant of the reload, the system additionally posts a `BONUS` credit equal to the reload amount multiplied by that campaign's `bonus_pct`, rounded half up to whole cents. The card's `last_activity_at` advances and the program's liability roll-up is re-derived. Reviving an `EXHAUSTED` card via reload makes it `ACTIVE` again.

### 3.4. Authorization Holds

To reserve value before a sale is finalized — the gift-card analogue of a pre-authorization — a `StoreAssociate` places an `AuthorizationHold` on a card, supplying the `card_id` and a positive `amount_cents` (a non-positive amount is a domain-shape violation rejected with `ERR_INVALID_REDEMPTION`). A new hold may not be placed on a card whose `risk_status` is `FROZEN_RISK` (`ERR_CARD_RISK_FROZEN`). A hold begins with `status` of `ACTIVE` and computes its `expires_at` as its own creation time plus the program's `hold_ttl_seconds`; at or after that instant the hold is considered expired. While a hold is `ACTIVE` it raises the card's `pending_hold_cents` and therefore lowers `available_balance_cents`, but it does not touch `settled_balance_cents`.

A hold can resolve four ways, leaving it in one of the terminal states `CAPTURED`, `RELEASED`, or `EXPIRED`. A `StoreAssociate` may release an `ACTIVE` hold whose expiry has not yet passed: the hold moves `ACTIVE → RELEASED`, its `pending_hold_cents` contribution is removed so `available_balance_cents` rises back by the held amount, and `settled_balance_cents` is unchanged. If the release is attempted at or after the hold's `expires_at`, the hold finalizes instead as `EXPIRED` (`ACTIVE → EXPIRED`), again restoring available balance by the held amount with no settled-balance impact. Releasing a hold that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The fourth path is capture, which is system-driven during redemption settlement: when a settlement consumes the value backing a hold, the hold moves `ACTIVE → CAPTURED`, the held amount converts into a `REDEEM` debit, `pending_hold_cents` falls by the amount and `settled_balance_cents` falls by the same amount, so the net available balance is unchanged across the capture. A hold can be captured only while it is `ACTIVE` and only before its `expires_at`; an expired hold cannot be captured.

### 3.5. Split-Tender Redemption

A purchase can be paid from several cards at once. A `StoreAssociate` or `Customer` drafts a `Redemption` over a `program_id`, a positive `requested_amount_cents` (the total the sale must cover), an ordered `card_id_order` listing the cards to draw from, and an optional `customer_id` (the redeeming cardholder, which may be absent for a clerk-initiated point-of-sale sale). A draft has `status` of `DRAFT` and carries no ledger impact yet. While still `DRAFT`, the redemption can be amended by a `StoreAssociate` or `Customer` to revise its `requested_amount_cents` or its `card_id_order`; each amendment increments the redemption's `version` and is permitted only while the status is `DRAFT` (otherwise `ERR_INVALID_STATE`). At draft and amend time, a positive amount and a non-empty `card_id_order` are required, failing which the request is rejected with `ERR_INVALID_REDEMPTION`. The redemption also exposes an `allocated_amount_cents`, the sum of its legs' amounts, which equals `requested_amount_cents` on a successful settlement.

Settlement is the consequential step, performed by a `StoreAssociate`, the owning `Customer`, or a `FraudAnalyst`, moving the redemption `DRAFT → SETTLED`. Settlement first applies the optimistic-concurrency check on `expected_redemption_version` described in §2.12. It then requires that `requested_amount_cents` is positive and `card_id_order` is non-empty (`ERR_INVALID_REDEMPTION`); that every card in `card_id_order` has `lifecycle_status` of `ACTIVE` (`ERR_INVALID_STATE`); that no card in the order is `FROZEN_RISK` (`ERR_CARD_RISK_FROZEN`); that any card whose `risk_status` is `FLAGGED` is being settled by a `FraudAnalyst` actor — a flagged card settled by anyone else is rejected with `ERR_CARD_RISK_REVIEW`; and that the sum of `available_balance_cents` across the listed cards is at least `requested_amount_cents` (`ERR_INSUFFICIENT_BALANCE`).

The allocation itself is a strict waterfall over `card_id_order` in exactly the given order — the client-pinned order *is* the allocation order. The system tracks a running remaining amount, initialized to `requested_amount_cents`. For each card in order it takes the smaller of the remaining amount and that card's available balance (treating any negative available balance as zero); if that take is greater than zero it creates one `RedemptionLeg` recording the `redemption_id`, the `card_id`, and the `leg_amount_cents` drawn, and subtracts the take from the remaining amount. Cards that would draw zero produce no leg. Allocation stops as soon as the remaining amount reaches zero. If, after walking every card, the remaining amount is still above zero, the settlement is rejected with `ERR_INSUFFICIENT_BALANCE` and no leg and no debit are persisted. Because allocation follows the pinned order, the same set of cards in a different `card_id_order` yields different per-card `leg_amount_cents` and drives a different set of cards to `EXHAUSTED`.

On a successful settlement the system posts one `REDEEM` debit per leg, recording the posted entry's id as the leg's `ledger_entry_id`; each drawn card's `settled_balance_cents` falls accordingly, and any card whose settled balance reaches zero auto-transitions `ACTIVE → EXHAUSTED` as a cascade. The redemption's `allocated_amount_cents` is set equal to `requested_amount_cents`, the program's `outstanding_liability_cents` is re-derived, and the redemption's `version` increments. A `DRAFT` redemption may instead be voided by a `StoreAssociate` (`DRAFT → VOIDED`); because no debits were posted while it was a draft, voiding has no ledger impact. A redemption's legs can be listed and filtered by `redemption_id`, by `card_id`, or by `ledger_entry_id`.

### 3.6. Refund-to-Card and Redemption Reversal

A refund returns value to a card. A `Customer`, `StoreAssociate`, or `ProgramAdmin` opens a `RefundRequest` naming the `card_id` to credit, a positive `requested_refund_cents`, and optionally a `redemption_id` identifying a prior settled redemption being refunded. A request begins `PENDING`; a non-positive `requested_refund_cents` is rejected with `ERR_INVALID_REDEMPTION`. A refund flows through the states `PENDING`, `NEEDS_REVISION`, `APPLIED`, and `DENIED`, with `APPLIED` and `DENIED` terminal.

A `ProgramAdmin` adjudicates a `PENDING` refund along three branches. They may send it back for revision (`PENDING → NEEDS_REVISION`) with no side effects; from `NEEDS_REVISION` the owning `Customer` resubmits a revised positive `requested_refund_cents`, which updates the stored amount and loops the request back to `PENDING` (a non-positive resubmitted amount is rejected with `ERR_INVALID_REDEMPTION`, and resubmission is allowed only from `NEEDS_REVISION`, else `ERR_INVALID_STATE`). They may deny it outright (`PENDING → DENIED`) with no side effects. Or they may approve it (`PENDING → APPLIED`). Approval requires that the target card's `lifecycle_status` is `ACTIVE` or `EXHAUSTED` (`ERR_INVALID_STATE`); that the resulting `settled_balance_cents` after the credit would not exceed `reload_max_balance_cents` (`ERR_BALANCE_CAP_EXCEEDED`); and, when a `redemption_id` is set, that `requested_refund_cents` does not exceed that referenced redemption's `allocated_amount_cents` (`ERR_REFUND_EXCEEDS_REDEMPTION`).

On approval the system posts a `REFUND` credit equal to `requested_refund_cents` on the card; if the card was `EXHAUSTED` it revives to `ACTIVE` as a cascade. There is a further cascade tied to full-amount redemption refunds: if a `redemption_id` is set and the approved `requested_refund_cents` exactly equals that redemption's `allocated_amount_cents`, the referenced redemption is driven `SETTLED → VOIDED`. That reversal walks every `RedemptionLeg` of the redemption, posting for each a `REVERSAL` credit that cancels the leg's original `REDEEM` debit — the reversal's `reverses_entry_id` points at the original entry, and that original debit's `status` becomes `REVERSED`. Each affected card's `settled_balance_cents` is restored by its leg's `leg_amount_cents`, any card that was `EXHAUSTED` revives to `ACTIVE`, and the program's `outstanding_liability_cents` is re-derived.

### 3.7. Fraud Handling and Card Replacement

The risk dimension is the `FraudAnalyst`'s domain and cycles independently of the card's lifecycle. Flagging a card moves its `risk_status` `CLEAR → FLAGGED` and is permitted only when the card's `lifecycle_status` is `ACTIVE` or `EXHAUSTED` (`ERR_INVALID_STATE`); once flagged, redemption drawing on that card is restricted to the `FraudAnalyst` review path, and any other actor attempting it gets `ERR_CARD_RISK_REVIEW`. Freezing moves a `FLAGGED` card `FLAGGED → FROZEN_RISK` (the card must currently be `FLAGGED`, else `ERR_INVALID_STATE`); as a cascade, every `AuthorizationHold` on the card whose `status` is `ACTIVE` is released to `RELEASED` and `pending_hold_cents` recomputes to zero, and while frozen the card blocks redemption, reload, and new holds with `ERR_CARD_RISK_FROZEN`. Clearing risk returns a card to `CLEAR`: a `FROZEN_RISK` card clears `FROZEN_RISK → CLEAR` (completing the full cycle and unblocking redeem, reload, and holds), and a `FLAGGED` card clears `FLAGGED → CLEAR`; in either case the card must be in the corresponding source state, else `ERR_INVALID_STATE`.

When a card is lost, damaged, or compromised, a replacement transfers its value to a fresh card. A `FraudAnalyst` or the owning `Customer` opens a `ReplacementRequest` naming the `old_card_id` and a `reason` of `FRAUD`, `LOST`, or `DAMAGED`. Opening is refused if the old card already has its `replaced_by_card_id` set — meaning an approved replacement already exists — with `ERR_CARD_ALREADY_REPLACED`. The request begins `OPEN`, with `APPROVED` and `REJECTED` as its terminal branches. A `FraudAnalyst` may reject an `OPEN` request (`OPEN → REJECTED`, no card mutation, must be `OPEN` else `ERR_INVALID_STATE`), or approve it (`OPEN → APPROVED`).

Approval first applies the `expected_old_card_version` optimistic-concurrency check from §2.12, then requires that the old card's `lifecycle_status` is `ACTIVE` or `EXHAUSTED` and not already `VOIDED` or `EXPIRED` (`ERR_INVALID_STATE`) — since an already-replaced card is `VOIDED`, this also blocks a second approval. On approval the system runs the balance transfer: it mints a new `GiftCard` (driven `INACTIVE → ACTIVE`) cloning the old card's `state_code` and owner, records the new card's id in `new_card_id`, and snapshots the old card's `settled_balance_cents` at approval as `transferred_amount_cents`. It posts a `TRANSFER_OUT` debit on the old card equal to the negative of that snapshot (zeroing the old card) and a `TRANSFER_IN` credit of the same magnitude on the new card, so that the old card's post-transfer settled balance plus the new card's post-transfer settled balance equals the old card's pre-transfer balance — value is conserved across the pair, and the program's `outstanding_liability_cents` therefore does not change because the value merely moves between two cards in the same program. The old card transitions `ACTIVE → VOIDED`, its `replaced_by_card_id` is set to the new card's id, and the old card's `version` increments.

### 3.8. Dormancy, Breakage, and Escheat

Unspent value cannot sit forever. A `ProgramAdmin` runs a dormancy assessment against a card, evaluated relative to the server's current clock. The assessment first measures inactivity as the number of whole months elapsed between the card's `last_activity_at` and the current instant (the floor of the elapsed whole months). A card is dormant when that count is at or beyond the applicable `StateRule`'s `dormancy_threshold_months` — the boundary is inclusive, so reaching exactly the threshold counts as dormant.

If the jurisdiction permits a dormancy fee (`dormancy_fee_allowed` is true), the card is dormant, and no `ACTIVE` `DormancyWaiver` covers the current instant, the system charges a dormancy fee: a `DORMANCY_FEE` debit equal to the smaller of a fixed fee of 200 cents (two dollars) and the card's `settled_balance_cents` — so the fee can never drive the balance below zero. If a dormancy assessment is requested but the card has not reached the threshold, or an `ACTIVE` waiver covers the current instant, the request is rejected with `ERR_DORMANCY_NOT_DUE`.

Expiration is governed separately. If the jurisdiction does not permit expiration (`expiration_allowed` is false), an attempt to expire the card is rejected with `ERR_EXPIRATION_NOT_ALLOWED`. Where expiration is allowed and the card is dormant with no covering waiver, the card transitions to `EXPIRED` and the residual value is resolved per the jurisdiction's `breakage_policy`. The two policies produce two different numbers from the same expiring card. Under `RECOGNIZE`, the full residual `settled_balance_cents` is booked as breakage revenue: a `BREAKAGE` debit equal to the negative of the residual is posted, and the program's `breakage_recognized_cents` rises by that magnitude. Under `ESCHEAT`, only a fraction is owed to the state: the escheated amount is the residual `settled_balance_cents` multiplied by the rule's `escheat_rate`, rounded half up to whole cents; an `ESCHEAT` debit equal to the negative of that amount is posted, the program's `escheat_liability_cents` rises by that magnitude, and the remaining residual is forfeited rather than booked as revenue. An `ACTIVE` card with value transitions `ACTIVE → EXPIRED` upon expiry; an `EXHAUSTED` card (already at zero balance) that has reached the threshold transitions `EXHAUSTED → EXPIRED` with no debit posted since there is nothing left to resolve.

To suppress dormancy during a known period of inactivity, a `ProgramAdmin` or `FraudAnalyst` creates a `DormancyWaiver` on a `card_id` spanning a closed interval from `window_start` (inclusive) to `window_end` (inclusive), beginning with `status` of `ACTIVE` and revocable to `REVOKED`. A new waiver may not overlap an existing `ACTIVE` waiver on the same card; an overlapping waiver is rejected with `ERR_WAIVER_OVERLAP`. Waivers can be listed and filtered by `card_id` and by `status`.

### 3.9. B2B Bulk Orders

A corporate buyer purchases cards in bulk. A `B2BBuyer` or `ProgramAdmin` quotes a `BulkOrder` naming the `program_id`, the `buyer_customer_id`, a `card_count` of at least one, a positive `face_value_cents` to load onto each minted card, and the `state_code` stamped on every minted card. A `card_count` below one or a non-positive `face_value_cents` is a domain-shape violation rejected with `ERR_INVALID_REDEMPTION`. A quote begins with `status` of `QUOTED`; the lifecycle runs through `CONFIRMED` and `ACTIVATED`, with `CANCELLED` as the other terminal outcome.

Confirmation is performed by the `B2BBuyer` and moves the order `QUOTED → CONFIRMED`. It requires that the buyer's `is_corporate` is true (`ERR_NOT_CORPORATE_BUYER`) and that the order is currently `QUOTED` (`ERR_INVALID_STATE`). Confirmation pins the order's `net_invoice_cents` using the bulk pricing rule: first compute one card's discounted price as `face_value_cents` multiplied by the quantity one minus the program's `b2b_discount_pct`, rounded half up to whole cents; then multiply that per-card price by `card_count`. The rounding is applied per card *before* the multiplication — rounding each card's price first and only then multiplying — which can differ from rounding a summed total by as much as one cent per card less one.

Activation is reserved for a `ProgramAdmin` and moves a `CONFIRMED` order `CONFIRMED → ACTIVATED` (the order must be `CONFIRMED`, else `ERR_INVALID_STATE`). Activation mints `card_count` gift cards as a cascade, each driven `INACTIVE → ACTIVE` with a `LOAD` credit of `face_value_cents`, each stamped with the order's `state_code` and an `owner_customer_id` equal to the order's `buyer_customer_id`; the program's `outstanding_liability_cents` is then re-derived to reflect all the newly loaded value. A `B2BBuyer` may cancel an order that is still `QUOTED` or `CONFIRMED` (`→ CANCELLED`, no side effects); cancelling from any other state is rejected with `ERR_INVALID_STATE`.

### 3.10. The Test-Driving Clock

Because dormancy thresholds, hold expiry, and campaign windows all depend on the passage of time, the system exposes an administrative test-driving capability that sets the server's notion of the current UTC instant to a supplied `to_iso8601` value. Advancing the clock affects every time-dependent rule — dormancy month counts, hold `expires_at` comparisons, and campaign window evaluation — and may cause campaign statuses to be recomputed on advance. This capability is restricted to a `ProgramAdmin`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that read a resource or that modify, transition, or act upon an existing resource (including the action endpoints that drive state machines) return a `200 OK` status code. All paths are mounted under the `/v1` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/programs` | Create a stored-value program | ProgramAdmin |
| GET | `/v1/programs/{program_id}` | Read a program with computed liability fields | ProgramAdmin, StoreAssociate, FraudAnalyst, B2BBuyer, Customer |
| POST | `/v1/state-rules` | Define a jurisdiction's expiration/breakage/dormancy rule | ProgramAdmin |
| GET | `/v1/state-rules/{state_rule_id}` | Read a state rule | ProgramAdmin, StoreAssociate, FraudAnalyst |
| GET | `/v1/state-rules` | List state rules (filter by program_id, state_code) | ProgramAdmin, StoreAssociate, FraudAnalyst |
| POST | `/v1/campaigns` | Create a reload-bonus campaign | ProgramAdmin |
| GET | `/v1/campaigns/{campaign_id}` | Read a campaign | ProgramAdmin, StoreAssociate |
| GET | `/v1/campaigns` | List campaigns (filter by program_id) | ProgramAdmin, StoreAssociate |
| POST | `/v1/campaigns/{campaign_id}/sync-status` | Recompute campaign status against the current clock | ProgramAdmin |
| POST | `/v1/customers` | Register a customer (cardholder or corporate buyer) | ProgramAdmin, Customer |
| GET | `/v1/customers/{customer_id}` | Read a customer | ProgramAdmin, Customer, FraudAnalyst, B2BBuyer |
| POST | `/v1/cards` | Issue a card (digital/physical), INACTIVE until activated | StoreAssociate, ProgramAdmin |
| GET | `/v1/cards/{card_id}` | Read a card with computed balance fields | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| GET | `/v1/cards` | List cards (filter by program_id, owner_customer_id, lifecycle_status, replaced_by_card_id) | StoreAssociate, ProgramAdmin, FraudAnalyst |
| POST | `/v1/cards/{card_id}/activate` | Activate an INACTIVE card with an initial load | StoreAssociate |
| POST | `/v1/cards/{card_id}/reload` | Reload value onto an ACTIVE/EXHAUSTED card | StoreAssociate, Customer |
| POST | `/v1/cards/{card_id}/assess-dormancy` | Run dormancy/breakage/escheat assessment against the clock | ProgramAdmin |
| POST | `/v1/cards/{card_id}/flag` | Flag a card for fraud review | FraudAnalyst |
| POST | `/v1/cards/{card_id}/freeze` | Freeze a card's value, releasing ACTIVE holds | FraudAnalyst |
| POST | `/v1/cards/{card_id}/clear-risk` | Clear a card's risk hold | FraudAnalyst |
| GET | `/v1/ledger-entries/{ledger_entry_id}` | Read a single ledger entry | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| GET | `/v1/ledger-entries` | List ledger entries (filter by card_id, program_id, entry_type, reverses_entry_id) | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| POST | `/v1/holds` | Place an authorization hold on a card | StoreAssociate |
| GET | `/v1/holds/{hold_id}` | Read a hold | StoreAssociate, ProgramAdmin, FraudAnalyst |
| GET | `/v1/holds` | List holds (filter by card_id, status) | StoreAssociate, ProgramAdmin, FraudAnalyst |
| POST | `/v1/holds/{hold_id}/release` | Release an ACTIVE hold (or finalize an expired one) | StoreAssociate |
| POST | `/v1/redemptions` | Draft a split-tender redemption over an ordered set of cards | StoreAssociate, Customer |
| GET | `/v1/redemptions/{redemption_id}` | Read a redemption | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| GET | `/v1/redemptions` | List redemptions (filter by program_id, customer_id) | StoreAssociate, ProgramAdmin, FraudAnalyst |
| PATCH | `/v1/redemptions/{redemption_id}` | Amend a DRAFT redemption's card order or amount | StoreAssociate, Customer |
| POST | `/v1/redemptions/{redemption_id}/settle` | Settle a DRAFT redemption: allocate waterfall, post REDEEM debits | StoreAssociate, Customer, FraudAnalyst |
| POST | `/v1/redemptions/{redemption_id}/void` | Void a DRAFT redemption | StoreAssociate |
| GET | `/v1/redemption-legs/{leg_id}` | Read a single redemption leg | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| GET | `/v1/redemption-legs` | List redemption legs (filter by redemption_id, card_id, ledger_entry_id) | StoreAssociate, ProgramAdmin, FraudAnalyst, Customer |
| POST | `/v1/bulk-orders` | Quote a B2B bulk order | B2BBuyer, ProgramAdmin |
| GET | `/v1/bulk-orders/{bulk_order_id}` | Read a bulk order with net_invoice_cents | B2BBuyer, ProgramAdmin |
| GET | `/v1/bulk-orders` | List bulk orders (filter by program_id, buyer_customer_id) | B2BBuyer, ProgramAdmin |
| POST | `/v1/bulk-orders/{bulk_order_id}/confirm` | Confirm a quoted order; pins net_invoice_cents | B2BBuyer |
| POST | `/v1/bulk-orders/{bulk_order_id}/activate` | Activate a confirmed order: mint and load all cards | ProgramAdmin |
| POST | `/v1/bulk-orders/{bulk_order_id}/cancel` | Cancel a quoted/confirmed order | B2BBuyer |
| POST | `/v1/replacements` | Open a replacement request for a compromised card | FraudAnalyst, Customer |
| GET | `/v1/replacements/{replacement_id}` | Read a replacement request | FraudAnalyst, ProgramAdmin, Customer |
| GET | `/v1/replacements` | List replacement requests (filter by old_card_id, new_card_id) | FraudAnalyst, ProgramAdmin |
| POST | `/v1/replacements/{replacement_id}/approve` | Approve a replacement: mint new card, transfer balance, void old card | FraudAnalyst |
| POST | `/v1/replacements/{replacement_id}/reject` | Reject a replacement request | FraudAnalyst |
| POST | `/v1/refunds` | Open a refund-to-card request | Customer, StoreAssociate, ProgramAdmin |
| GET | `/v1/refunds/{refund_id}` | Read a refund request | Customer, StoreAssociate, ProgramAdmin |
| GET | `/v1/refunds` | List refund requests (filter by card_id, redemption_id) | Customer, StoreAssociate, ProgramAdmin |
| POST | `/v1/refunds/{refund_id}/approve` | Approve a refund: credit the card (may reverse a redemption) | ProgramAdmin |
| POST | `/v1/refunds/{refund_id}/request-revision` | Ask the customer to revise a refund request | ProgramAdmin |
| POST | `/v1/refunds/{refund_id}/resubmit` | Customer resubmits a revised refund amount | Customer |
| POST | `/v1/refunds/{refund_id}/deny` | Deny a refund request | ProgramAdmin |
| POST | `/v1/dormancy-waivers` | Create a dormancy-suppression window on a card | ProgramAdmin, FraudAnalyst |
| GET | `/v1/dormancy-waivers/{waiver_id}` | Read a dormancy waiver | ProgramAdmin, FraudAnalyst, StoreAssociate |
| GET | `/v1/dormancy-waivers` | List dormancy waivers (filter by card_id, status) | ProgramAdmin, FraudAnalyst, StoreAssociate |
| POST | `/v1/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REDEMPTION` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CARD_RISK_FROZEN` | 409 Conflict |
| `ERR_CARD_RISK_REVIEW` | 409 Conflict |
| `ERR_CARD_ALREADY_REPLACED` | 409 Conflict |
| `ERR_EXPIRATION_NOT_ALLOWED` | 409 Conflict |
| `ERR_DORMANCY_NOT_DUE` | 409 Conflict |
| `ERR_WAIVER_OVERLAP` | 409 Conflict |
| `ERR_CAMPAIGN_OVERLAP` | 409 Conflict |
| `ERR_RELOAD_BELOW_MIN` | 409 Conflict |
| `ERR_BALANCE_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_REDEMPTION` | 409 Conflict |
| `ERR_NOT_CORPORATE_BUYER` | 409 Conflict |

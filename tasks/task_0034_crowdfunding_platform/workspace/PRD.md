# Crowdfunding Platform API — Product Requirements Document

## 1. Introduction

The Crowdfunding Platform API powers a marketplace where creators ("initiators") raise funds from the public ("backers") in exchange for tiered rewards, while a platform operator brokers the entire lifecycle — from initial project review, through live fundraising and order placement, into post-deadline charge waves, fulfillment, refunds, and periodic payouts to the initiator's bank account. The platform is opinionated: it enforces a multi-stage editorial review with segregation-of-duties, holds backer funds in third-party escrow with payment-authorization-only at backing time, and reconciles the entire ledger through deterministic settlement batches that compute commission, payment-channel fees, refund reversals, and tax withholding in a pinned evaluation order.

Operationally, the system must remain consistent under three sources of pressure: time (deadlines that flip a project's status the instant they pass), concurrency (two backers chasing the last unit of inventory, an initiator cancelling while the system is auto-succeeding the same project), and cascades (a single project cancellation that voids dozens of authorized orders and synthesizes their refund requests). These pressures are addressed by a parallel state model — every order carries one state for payment and a separate state for fulfillment, evolving independently — and by an event-driven test harness that lets external payment, banking, and logistics signals be injected deterministically.

Audit-grade traceability is non-negotiable: every fund movement records an entry in an escrow ledger, every status change appends to an immutable audit log, and every settlement payout is reproducible from the orders, refunds, and constants in scope at the time of finalization.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the acting principal's identifier) and `X-User-Role` (one of the six role names defined below). When either header is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). When the headers are present but the role is not authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The complete set of role names — written exactly as they must appear in the `X-User-Role` header — is:

- `Initiator` — creates and runs projects; receives settlement payouts.
- `Backer` — places orders and receives rewards or refunds.
- `ContentReviewer` — decides on the content of submitted projects.
- `LegalReviewer` — decides on the legal review stage that follows content approval.
- `FinancialReviewer` — decides on the financial review stage that follows legal approval.
- `PlatformAdmin` — operates the platform: KYC verification, refund approval and execution, settlement, audit, and event/clock test drivers.

Three of these roles are entity-backed and three are opaque. When `X-User-Role` is `Initiator`, `X-User-ID` is the `id` of the acting `Initiator`; ownership checks on any resource that references an `Initiator` (for example, a project's `initiator_id`) compare that resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Backer`, `X-User-ID` is the `id` of the acting `Backer`; ownership checks on orders and refund requests compare the resource's `backer_id` (directly on orders, or via the linked order for a refund request) to `X-User-ID`. When `X-User-Role` is `ContentReviewer`, `LegalReviewer`, `FinancialReviewer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, but it does record it on review and audit trails — for example, as `actor_id` on an `AuditLogEntry`, and it is the value the segregation-of-duties check inspects across the three reviewer stages of a project.

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

List endpoints accept two optional query parameters: `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; values outside this range are rejected. The default `offset` is 0. Lists are returned in `created_at` ascending order so that pagination cursors are stable across requests. The pagination block in `meta` carries four values for every list response: `limit` (the value applied to this request), `offset` (the value applied to this request), `total_count` (the count of records that would be returned across all pages with the current filter set), and `has_more` (true when more records exist beyond the current page).

### 2.4. Common Resource Properties

Most resources carry a uniform property set. Their `id` is a server-minted UUID without any type prefix. Their `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. Their `version` is a non-negative integer assigned when the resource is first written and incremented by exactly one on every server-side mutation. The entities `ProgressUpdate`, `AuditLogEntry`, and `EscrowLedgerEntry` are append-only and lighter: they carry only `id` and `created_at`; both `updated_at` and `version` are absent for those three.

### 2.5. Optimistic Concurrency Control

Every mutating endpoint that accepts a request body permits a `version` field. When the request body omits `version`, the server skips the concurrency check and proceeds with the mutation. When the request body includes `version`, the server compares it against the current persisted version of the target resource; on mismatch, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). On a successful mutation, the resource's `version` increments by one and its `updated_at` is refreshed to the server's current time.

### 2.6. Nested Resource Path Resolution

Several endpoints address resources nested under a project — rewards, add-on items, progress updates, settlement batches, and the escrow ledger. Path parameters resolve strictly left-to-right: the leftmost identifier (typically `project_id`) is checked first; if it does not name an existing project, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) without examining the next identifier. Only after the parent resolves does the server validate the child identifier (for example `reward_id`, `batch_id`, or the trailing `id` of a reward/refund/order/settlement-batch). A child whose parent reference does not match the URL parent is treated as a referential-integrity error and rejected with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422); this applies to reward CRUD and to order creation or modification where the selected reward, or any add-on referenced through `add_on_item_id` in `add_ons`, must belong to the order's `project_id`.

### 2.7. Status Codes and Status Code Discipline

Endpoints that create a brand-new resource (project creation, reward creation, add-on-item creation, order placement, progress-update publishing, refund-request creation, draft settlement-batch creation, and the registration of an `Initiator` or `Backer`) return HTTP 201 on success. All other successful mutations and reads return HTTP 200. The 4xx codes used by error responses are listed alongside their `error_id` values in §5; trigger conditions for each error are written into the relevant business-logic narrative in §3 rather than collected here.

### 2.8. Validation Ordering

When an endpoint must run several checks, they execute in a fixed precedence so that the same input always surfaces the same error. The order is: header presence (`ERR_AUTH_REQUIRED`), then role authorization (`ERR_FORBIDDEN`), then path-parameter existence (`ERR_NOT_FOUND`), then state-machine compatibility — first project state, then order state, both expressed as `ERR_INVALID_STATE`. Beyond the state checks, business rules apply in their declared scaffold priority: segregation-of-duties on review stages (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), the KYC gate at submit (`ERR_KYC_REQUIRED`), the order-modification window (`ERR_MODIFICATION_WINDOW_CLOSED`), the deadline-too-soon gate at submit (`ERR_DEADLINE_TOO_SOON`), cross-project referential integrity (`ERR_CROSS_PROJECT_REFERENCE`), the shipping-address requirement (`ERR_SHIPPING_ADDRESS_REQUIRED`), the reward inventory check (`ERR_REWARD_INVENTORY_EXHAUSTED`), the add-on inventory check (`ERR_ADDON_INVENTORY_EXHAUSTED`), the at-least-one-reward gate (`ERR_NO_REWARDS_DEFINED`), the refund-amount-vs-remainder check (`ERR_REFUND_EXCEEDS_REMAINDER`), the silence-window check at settlement finalize (`ERR_UPDATE_FREQUENCY_BREACH`), the open-refund check at settlement finalize (`ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT`), the positive-amount check (`ERR_INVALID_AMOUNT`), and finally the OCC version check (`ERR_VERSION_CONFLICT`). When several checks would all fire, the earlier check wins; the implementation must not let a later business rule mask an earlier one.

### 2.9. Monetary Precision and Rounding

All monetary fields are stored as integer cents — there are no fractional cents anywhere in the system. Whenever a calculation produces a non-integer intermediate (for example, multiplying `order_total_cents` by a basis-point rate), the result is rounded half-up to the nearest cent at the step the scaffold designates. Tier-based and per-order calculations always round per order first and only then sum into batch totals; the alternative ordering — summing gross amounts and rounding once at the end — is forbidden because it produces a different cents result when many small orders accumulate.

### 2.10. Cascades, Auditing, and the Escrow Ledger

Operations that change the status of a project or order frequently trigger secondary effects on related entities. Every such cascade increments the `version` and refreshes `updated_at` of every entity it touches, and every status change of a project, order, refund request, or settlement batch appends an `AuditLogEntry` whose `subject_type` is one of `PROJECT`, `ORDER`, `REFUND_REQUEST`, `SETTLEMENT_BATCH`, or `ESCROW_LEDGER`, whose `subject_id` is the affected resource's `id`, and whose `event_type` is one of `STATUS_CHANGE`, `FUND_FLOW`, `REFUND_EXECUTED`, `SETTLEMENT_PAID`, `REVIEW_DECISION`, or `EXTERNAL_EVENT_RECEIVED`. The entry's `payload` carries the from-state, to-state, amounts, and any external system reference; `actor_role` and `actor_id` carry the role and identifier of whoever initiated the operation, with both fields set to the literal string `SYSTEM` when an automatic transition fired without a human caller. Fund movements additionally append an `EscrowLedgerEntry` whose `entry_type` is one of `AUTH_HOLD`, `CHARGE_CAPTURE`, `CHARGE_VOID`, `REFUND_OUT`, `COMMISSION_HOLD`, `COMMISSION_REVERSAL`, `CHANNEL_FEE`, or `SETTLEMENT_PAYOUT`; the `amount_cents` is a signed integer where positive values move money into escrow and negative values move money out, and `external_ref` carries the upstream payment- or banking-system reference where one exists. Settlement-payout entries leave `order_id` null; all other entry types pin both `project_id` and `order_id`.

### 2.11. Concurrency and Serialization Guarantees

Several scenarios admit two clients racing on the same resource. Each scenario has a pinned winner and a pinned loser-error. When two backers simultaneously place orders for the last unit of a limited-inventory reward, only `inventory_limit` orders may succeed in total; the loser receives `ERR_REWARD_INVENTORY_EXHAUSTED` (HTTP 409) — first-writer-wins on the reward's `inventory_claimed` increment under row lock. When two backers simultaneously add the same add-on item where only one unit remains, the aggregate `inventory_claimed` for that add-on must never exceed `inventory_limit`; the loser receives `ERR_ADDON_INVENTORY_EXHAUSTED` (HTTP 409). When an initiator submits the same draft project for review twice in rapid succession (the classic double-click), at most one transition into `CONTENT_REVIEW` may occur; the second request is rejected with `ERR_INVALID_STATE` (HTTP 409). When an initiator cancels a project at the same moment the system is auto-transitioning it to `SUCCEEDED` past its deadline, exactly one transition wins: cancellation takes precedence only if the project is still in `LIVE` when the write is applied; otherwise the loser receives `ERR_INVALID_STATE` (HTTP 409). When two `PlatformAdmin` actors try to approve and reject the same refund request simultaneously, exactly one decision wins and the loser receives `ERR_INVALID_STATE` (HTTP 409). When a backer attempts to modify an order while the platform's auto-cancellation cascade voids it, the modification loses if the order has already moved to `VOIDED` and the backer receives `ERR_INVALID_STATE` (HTTP 409). All five `ERR_INVALID_STATE` cases serialize on the relevant entity's status (and, where the OCC `version` is supplied, on `version`).

## 3. Business Logic & Workflows

### 3.1. Onboarding Initiators and Backers

A creator joins the platform by registering as an initiator with at least their `legal_name`. They may also supply `tax_id` (which materially affects later tax withholding), `bank_account_id` (a reference to a settlement bank account at the third-party escrow), and `qualification_doc_uri` pointing to uploaded qualification documents that will be reviewed during KYC. Newly created initiators are persisted with `kyc_status` set to `PENDING`. KYC verification is a `PlatformAdmin` operation that supplies a `decision` and flips `kyc_status` to either `VERIFIED` or `REJECTED`; the decision is recorded as an `AuditLogEntry` and is the gate that downstream submission depends on. Backers register with their `display_name`, `email` (which is unique across all backers), and an optional `default_shipping_address`.

### 3.2. Drafting a Project, Defining Rewards, and Adding Add-Ons

An initiator drafts a project by supplying `title` (4 to 120 characters), a `category` chosen from `TECH`, `ART`, or `COMMUNITY` (which will later drive the commission rate), a long-form `description_md` in Markdown, between 1 and 10 image or video URIs in `media_uris`, the mandatory `risk_disclosure` clause text, a `funding_model` of either `ALL_OR_NOTHING` or `KEEP_IT_ALL`, a `funding_target_cents` strictly greater than zero, and a `deadline` expressed as a UTC timestamp. The new project is persisted in `DRAFT` status with `provisional_raised_cents` and `final_raised_cents` both zero, with `last_update_published_at` and `rejection_reason` null, and with the `initiator_id` pinned to the calling initiator's `X-User-ID`. While the project remains in `DRAFT`, the initiator may continue to edit it — adjusting `title`, `description_md`, `media_uris`, `risk_disclosure`, `funding_model`, `funding_target_cents`, or `deadline` — under optimistic concurrency.

Reward tiers and add-on items can be created and edited only while the project is in `DRAFT`. Each reward carries a `tier_label` that must be unique within the project (a duplicate is rejected with `ERR_DUPLICATE_TIER_LABEL`), a strictly-positive `pledge_amount_cents`, a `reward_type` of either `PHYSICAL` or `DIGITAL`, an optional `inventory_limit` (null means unlimited), and an optional `estimated_delivery` that is meaningful only for physical rewards. The reward's `inventory_claimed` is a system-maintained counter that starts at zero. Add-on items carry a `name`, a strictly-positive `price_cents`, an optional `requires_shipping` flag (default false), and an optional `inventory_limit`; their `inventory_claimed` aggregates unit counts across all non-terminal or charged orders. All three positive-amount checks — on `funding_target_cents`, `pledge_amount_cents`, and `price_cents` — surface as `ERR_INVALID_AMOUNT` if the supplied value is not strictly greater than zero.

### 3.3. Submitting for Review and the Three-Stage Editorial Pipeline

When the initiator is ready, they submit the draft for review. Submission advances `status` from `DRAFT` to `CONTENT_REVIEW` and is gated by five preconditions checked together: the calling initiator's `kyc_status` must be `VERIFIED` (otherwise `ERR_KYC_REQUIRED`); `title`, `description_md`, and `risk_disclosure` must all be present and non-empty; `media_uris` must contain at least one URI; `funding_target_cents` must be greater than zero and `deadline` must be more than 24 hours after the current time (otherwise `ERR_DEADLINE_TOO_SOON`); and the project must already have at least one reward defined (otherwise `ERR_NO_REWARDS_DEFINED`). The deadline check applies both at project creation and at submit. A successful submit appends an `AuditLogEntry` with `event_type` `STATUS_CHANGE`. A second concurrent submit on the same draft is rejected with `ERR_INVALID_STATE`, since only one transition out of `DRAFT` may win.

Reviewers act in a strict sequence and supply a `decision` plus an optional `message`. The content reviewer acts first while the project is in `CONTENT_REVIEW`. An `APPROVE` decision moves the project to `LEGAL_REVIEW`. A `REQUEST_CHANGES` decision moves the project back to `DRAFT`, sets `rejection_reason` to the supplied message so the initiator can revise and resubmit, and writes an audit entry — this is the revision loop. A `REJECT` decision moves the project to the terminal `REJECTED` status with `rejection_reason` set. The legal reviewer acts only while the project is in `LEGAL_REVIEW`; their three decisions mirror the content reviewer's: `APPROVE` advances to `FINANCIAL_REVIEW`, `REQUEST_CHANGES` returns to `DRAFT` with `rejection_reason` set, and `REJECT` makes `REJECTED` terminal. The financial reviewer, acting only while the project is in `FINANCIAL_REVIEW`, follows the same three-decision pattern: `APPROVE` advances to `LIVE`, `REQUEST_CHANGES` returns to `DRAFT` with `rejection_reason` set, and `REJECT` makes `REJECTED` terminal. Every reviewer decision appends an `AuditLogEntry` with `event_type` `REVIEW_DECISION`.

A hard segregation-of-duties rule sits across the three reviewer stages: a single `X-User-ID` may not approve more than one of the content, legal, and financial decisions on the same project. The legal-review approve transition therefore requires that the calling reviewer's `X-User-ID` differ from the content reviewer who approved this project; the financial-review approve transition requires that the calling reviewer's `X-User-ID` differ from both prior approvers. A repeat approval by a previously-recorded reviewer is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

### 3.4. Going Live, Backing, and the Order Modification Window

Once the financial reviewer approves, the project enters `LIVE` and accepts orders. A backer places an order by supplying the `project_id`, the chosen `reward_id`, an optional `add_ons` array of `{add_on_item_id, quantity}` entries (each `quantity` strictly greater than zero), an optional `shipping_address`, and a `payment_method_token` from the payment system that is pinned at backing time. Order creation is rejected with `ERR_INVALID_STATE` if the project is not in `LIVE`. The reward and any referenced add-on item must belong to the same project as the order; a mismatch is rejected with `ERR_CROSS_PROJECT_REFERENCE`. A `shipping_address` is mandatory whenever the selected reward's `reward_type` is `PHYSICAL` or any referenced add-on has `requires_shipping` true; absence is rejected with `ERR_SHIPPING_ADDRESS_REQUIRED`. Inventory is claimed atomically: if the reward has a non-null `inventory_limit` and accepting this order would push `inventory_claimed` past it, the order is rejected with `ERR_REWARD_INVENTORY_EXHAUSTED`; the same logic applies to each add-on with `ERR_ADDON_INVENTORY_EXHAUSTED` when the requested quantity would push that add-on's `inventory_claimed` past its `inventory_limit`. On successful creation the reward's `inventory_claimed` is incremented by one, each referenced add-on's `inventory_claimed` is incremented by its `quantity`, and the order is persisted with `payment_status` `AUTHORIZED` and `fulfillment_status` `NOT_STARTED`. The order's `pledge_amount_cents` is snapshot from the reward's `pledge_amount_cents` at this moment; `add_ons_total_cents` is computed as the sum over the order's add-ons of `price_cents` multiplied by `quantity`; and `order_total_cents` is the sum of the snapshot pledge amount and the add-ons total. An `EscrowLedgerEntry` of type `AUTH_HOLD` is inserted on the project's ledger. The project's `provisional_raised_cents` is then recomputed.

The `provisional_raised_cents` figure is the live progress meter while the project is `LIVE`. It equals the sum of `order_total_cents` over every order on the project whose `payment_status` is `AUTHORIZED`. Voided, charged, refunded, partially refunded, charge-pending, charge-failed, and refund-pending orders are all excluded from this provisional sum.

Each order also pins an `order_modification_locked_at` timestamp at creation, computed as the earlier of two moments: the project's `deadline`, and the order's `created_at` plus 72 hours. Up to that moment the backer may modify their order: change `reward_id`, change `add_ons`, change `shipping_address`, or change `payment_method_token`. Modification requires that the project still be in `LIVE`; if the new `reward_id` differs from the current selection and the new reward has an `inventory_limit`, the new reward's `inventory_claimed` must remain strictly less than its `inventory_limit` (otherwise `ERR_REWARD_INVENTORY_EXHAUSTED`). On a successful modification, the old reward's `inventory_claimed` decreases by one and the new reward's increases by one when the reward changes; add-on inventory deltas are applied symmetrically; `pledge_amount_cents`, `add_ons_total_cents`, and `order_total_cents` are all recomputed; the project's `provisional_raised_cents` is recomputed; and the order's `version` increments. An attempt to modify or cancel an order at or after the locked-at moment is rejected with `ERR_MODIFICATION_WINDOW_CLOSED`. The same window also bounds backer-initiated order cancellation: while still inside the window and with the project in `LIVE`, the backer may cancel, which moves the order's `payment_status` from `AUTHORIZED` to `VOIDED`, inserts a `CHARGE_VOID` `EscrowLedgerEntry` with no cash movement, decrements the reward's `inventory_claimed` by one, reverses the add-on inventory deltas, and recomputes the project's `provisional_raised_cents`. A `PlatformAdmin` may also cancel an order as an administrative override, subject to the same effects.

### 3.5. Deadline Resolution: SUCCEEDED versus FAILED

Deadlines are evaluated through an admin-only test-driving capability that advances the logical clock to a supplied `to` instant; in production the same logic fires on the wall clock. When the clock crosses a project's `deadline` while the project is in `LIVE`, exactly one of two transitions occurs.

If the project's `funding_model` is `KEEP_IT_ALL`, or if it is `ALL_OR_NOTHING` and `provisional_raised_cents` is at least `funding_target_cents`, the project transitions from `LIVE` to `SUCCEEDED`. The success transition opens the charge wave: for every order whose `payment_status` is `AUTHORIZED` on this project, a charge is enqueued and the order's `payment_status` is set to `CHARGE_PENDING`. After the charge wave settles, `final_raised_cents` is recomputed: it equals the sum of `order_total_cents` over orders whose `payment_status` is now `CHARGED` or `PARTIALLY_REFUNDED`. The arithmetic shape is the same as the provisional sum but the input set is fundamentally different — for example, the same project may end with a `provisional_raised_cents` of 50,000 but a `final_raised_cents` of 47,500 because a few backers' cards declined three times. An `AuditLogEntry` records the `STATUS_CHANGE`.

If instead the project's `funding_model` is `ALL_OR_NOTHING` and `provisional_raised_cents` is strictly less than `funding_target_cents`, the project transitions from `LIVE` to `FAILED`. The failure transition voids the entire authorized order pool: every order with `payment_status` `AUTHORIZED` on this project has its authorization voided and its `payment_status` set to `VOIDED`. As a second cascade hop, the system synthesizes for each voided order a `RefundRequest` with `reason` `PROJECT_FAILED`, `triggered_by` `PLATFORM_AUTO`, `status` `APPROVED`, and `approved_amount_cents` zero — voids do not move money, but the refund record is preserved in `EXECUTED` form for audit. An `AuditLogEntry` records the status change.

The initiator may also voluntarily cancel a `LIVE` project before its deadline by supplying an optional `reason`. Cancellation moves the project to terminal `CANCELLED` and triggers a two-hop cascade: every `AUTHORIZED` order is voided, and for every `CHARGED` order the system synthesizes a `RefundRequest` with `reason` `PROJECT_CANCELLED`, `triggered_by` `PLATFORM_AUTO`, `status` `APPROVED`, and `approved_amount_cents` set to that order's current `refundable_remainder_cents`. When such an auto-approved refund is executed, the refund-commission-reversal calculation runs against the open settlement batch covering the period.

### 3.6. The Charge Wave, Retries, and Final Failure

The charge wave is driven by simulated payment events from the payment system. Each time the system receives a payment event carrying the affected `order_id`, an optional `external_ref`, and a `result` field, it consults the order's current state. From `CHARGE_PENDING`, a `result` of `SUCCESS` transitions the order to `CHARGED`: the `EscrowLedgerEntry` of type `CHARGE_CAPTURE` is finalized, additional `COMMISSION_HOLD` and `CHANNEL_FEE` entries are inserted with their per-order amounts pinned by the commission calculation, the project's `final_raised_cents` is incremented, the order's `refundable_remainder_cents` is set to its `order_total_cents` (the entire order is refundable until any shipment), and an `AuditLogEntry` of type `FUND_FLOW` is appended. From `CHARGE_PENDING`, a `result` of `FAILURE` transitions the order to `CHARGE_FAILED` only when `charge_attempts` is at least 3; otherwise (when `charge_attempts` is less than 3) the order reverts to `AUTHORIZED` to be retried, cycling `AUTHORIZED → CHARGE_PENDING → AUTHORIZED` until `charge_attempts` reaches 3. The `charge_attempts` counter is incremented by one each time the order leaves `AUTHORIZED` for `CHARGE_PENDING`. When the order finally reaches `CHARGE_FAILED`, the system synthesizes a `RefundRequest` with `reason` `PLATFORM_MANDATORY`, `triggered_by` `PLATFORM_AUTO`, `status` `APPROVED`, and `approved_amount_cents` zero — the authorization is implicitly released by the issuer after seven days, so no actual refund flow is needed; the refund record exists only for audit and downstream IM notification, and an `AuditLogEntry` is appended.

### 3.7. Fulfillment, Partial Shipments, and the Refund Remainder

An order's `fulfillment_status` is a parallel state dimension independent of `payment_status`; it begins at `NOT_STARTED` and may move to `PARTIALLY_SHIPPED`, then `FULLY_SHIPPED`, or directly to `NOT_APPLICABLE` for digital-only orders. Fulfillment events arrive through a logistics test driver that registers shipment lines for an order: the platform tags the supplied `lines`, recomputes the order's `refundable_remainder_cents`, and updates `fulfillment_status` accordingly.

The refundable remainder is the cap that gates partial refunds. Before any shipment, `refundable_remainder_cents` equals the order's `order_total_cents`. Once shipments arrive, the system aggregates the value of shipped lines for the order and resets `refundable_remainder_cents` to the maximum of zero and the order's `order_total_cents` minus the total shipped value. When approving any refund request, the requested amount is checked against this remainder.

### 3.8. Refund Requests: Submission, Decision, and Execution

A refund request is created by a `Backer` against their own order or by a `PlatformAdmin` on behalf of the platform. The creator supplies the linked `order_id`, the `reason` (one of `PROJECT_FAILED`, `PROJECT_CANCELLED`, `DISPUTE`, or `PLATFORM_MANDATORY`), and the `requested_amount_cents`. The new request is persisted with `status` `PENDING_REVIEW`, `approved_amount_cents` null, `rejection_reason` null, and `triggered_by` set to `BACKER`, `INITIATOR`, or `PLATFORM_AUTO` per the originator. If the requested amount exceeds the linked order's current `refundable_remainder_cents` either at create time or at approve time, the request is rejected with `ERR_REFUND_EXCEEDS_REMAINDER`.

Approval is a `PlatformAdmin` operation. Approval requires that the request is currently `PENDING_REVIEW`, that `requested_amount_cents` is no greater than the linked order's `refundable_remainder_cents` (the order is found via `order_id`), and that the linked order's `payment_status` is one of `CHARGED` or `PARTIALLY_REFUNDED`. On approval, `approved_amount_cents` is set equal to `requested_amount_cents`, the request moves to `APPROVED`, and an `AuditLogEntry` is appended. Rejection is also a `PlatformAdmin` operation and requires that the request is `PENDING_REVIEW` and that `rejection_reason` is provided; the request moves to terminal `REJECTED` with the supplied reason recorded, and an `AuditLogEntry` is appended.

Execution drives the depth-three cascade that links refunds, orders, and settlement. An approved refund is executed by the platform admin or by the system as part of an automatic flow. On execution, the refund moves to terminal `EXECUTED`. The linked order then transitions per its own state machine: from `CHARGED`, when `approved_amount_cents` equals the order's `refundable_remainder_cents` and that remainder still equals the full `order_total_cents` (no shipments yet), the order moves to `REFUNDED` and `refundable_remainder_cents` is set to zero; otherwise — when `approved_amount_cents` is strictly less than the order's `order_total_cents` — the order moves to `PARTIALLY_REFUNDED` and `refundable_remainder_cents` is decreased by `approved_amount_cents`; if the order has unfulfilled items, the `fulfillment_status` may shift independently as new fulfillment events arrive. Two `EscrowLedgerEntry` records are written: a `REFUND_OUT` for the cash that leaves escrow, and a `COMMISSION_REVERSAL` whose magnitude is determined by the refund-commission-reversal calculation. Then, as the third cascade hop, the open settlement batch covering this period has its `refund_reversal_cents` recomputed. Two audit entries are appended, one of `event_type` `FUND_FLOW` and one of `REFUND_EXECUTED`. Should the banking event arrive with a failure result while the request is `APPROVED`, the request transitions to terminal `FAILED` and an audit entry records that manual intervention is required.

### 3.9. Progress Updates and the Silence Window

The initiator publishes progress updates to keep backers informed. Each update carries a `title`, a Markdown `body_md`, a `visibility` of either `PUBLIC` or `BACKERS_ONLY`, an optional `milestone_label` (such as "Prototype Done"), and an optional boolean `is_delay_notice` that announces a fulfillment delay. Publishing an update sets the project's `last_update_published_at` to the current time and appends an `AuditLogEntry`. When a list of progress updates is requested, entries with `visibility` `BACKERS_ONLY` are filtered out unless the requester is a backer of this project (the requester's `X-User-ID` matches the `backer_id` of an order placed against this project) or holds a privileged role.

Silence is policed by the update-frequency rule. The system computes the integer number of days between the current time and `last_update_published_at`. While the project is in `LIVE` and the silence has exceeded a 30-day threshold, the deviation is recorded as a warning and does not block any operation. After the project has transitioned to `SUCCEEDED`, the same threshold becomes a hard gate at settlement finalize: a settlement batch may not be finalized while the silence exceeds 30 days, in which case the request is rejected with `ERR_UPDATE_FREQUENCY_BREACH`. The 30-day boundary is exclusive of equality — a silence of exactly 30 days is compliant; a silence strictly greater than 30 days is non-compliant.

### 3.10. Commission, Channel Fees, Refund Reversals, and Per-Order Pinning

When an order moves to `CHARGED`, the platform pins its commission and channel-fee values and writes them onto the order so that subsequent refund reversals stay reproducible. The commission rate is selected by the project's `category`: `TECH` charges 500 basis points (5.00%), `ART` charges 700 basis points (7.00%), and `COMMUNITY` charges 300 basis points (3.00%). The per-order commission is computed as the order's `order_total_cents` multiplied by the category rate divided by 10,000, rounded half-up to the nearest cent. The per-order payment-channel fee uses a single 290 basis-point (2.90%) rate but is floored: take `order_total_cents` multiplied by 290 divided by 10,000, drop any fractional cents (floor), and then enforce a minimum of 30 cents — the channel fee is the larger of 30 cents and the floored result, with that maximum then rounded half-up to the nearest cent. Both pinning steps insert a `COMMISSION_HOLD` and a `CHANNEL_FEE` `EscrowLedgerEntry` against the project's ledger.

A refund reversal mirrors the commission proportionally. When a refund executes against an order, the system retrieves the commission that was pinned on that order at charge time, multiplies it by `approved_amount_cents`, divides by the order's `order_total_cents`, and rounds half-up to the nearest cent — that figure is the `commission_cents` reversed. When the refund is for the entire order, the reversal equals the full original commission. When the refund is partial (after partial shipments), the reversal is strictly proportional. The payment-channel fee, by contrast, is never reversed: the platform absorbs no part of it, so for the refunded fraction the initiator effectively absorbs the channel fee. The settlement adjustment for a single refund is therefore the negative of the difference between `approved_amount_cents` and the cents that were reversed from commission.

### 3.11. Settlement Batches: Periodic Payouts to the Initiator

Settlement is the periodic payout flow that returns net proceeds to the initiator. A `PlatformAdmin` creates a draft settlement batch on a project by supplying an inclusive `period_start` and an exclusive `period_end`. The batch is persisted with `status` `DRAFT`, with `gross_charged_cents` populated from the `order_total_cents` of orders whose charge event timestamp falls in the half-open interval defined by those bounds, and with `commission_cents`, `channel_fee_cents`, `refund_reversal_cents`, `tax_withheld_cents`, and `net_payout_cents` pre-computed. Finalization is a separate `PlatformAdmin` step that locks all amounts and readies the payout. Finalization is gated by three preconditions: the project must be in `SUCCEEDED`; no `RefundRequest` for orders in the batch's period may be currently `PENDING_REVIEW` or `APPROVED` (otherwise `ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT`); and the project's update-frequency compliance must be `COMPLIANT` per §3.9 (otherwise `ERR_UPDATE_FREQUENCY_BREACH`).

When finalize succeeds, the batch transitions from `DRAFT` to `FINALIZED` and all five computed amounts are pinned in a fixed evaluation order. First, `commission_cents` is the sum across the batch's charged orders of each order's pinned commission (per-order rounding then sum). Second, `channel_fee_cents` is the sum across the same orders of each order's pinned channel fee. Third, `refund_reversal_cents` aggregates the commission reversals for refunds executed in the same period. Fourth, the taxable base is computed as `gross_charged_cents` minus `commission_cents` minus `channel_fee_cents` minus `refund_reversal_cents`. Fifth, `tax_withheld_cents` is computed by the withholding rule from §3.12 against that taxable base. Finally, `net_payout_cents` equals the taxable base minus `tax_withheld_cents`. The pinned ordering breaks the apparent circularity between commission and tax: tax depends on the net-of-commission base, but commission is never recomputed from the net.

A finalized batch becomes `PAID` when the simulated banking event reports `SUCCESS` against the `batch_id`, at which point a `SETTLEMENT_PAYOUT` `EscrowLedgerEntry` is inserted and an `AuditLogEntry` of `event_type` `SETTLEMENT_PAID` is appended. A `FAILURE` result transitions the batch to terminal `FAILED` and records that manual retry is required.

### 3.12. Tax Withholding

Tax withholding is computed once at finalize against the taxable base described in §3.11. When the initiator's `tax_id` is missing or the empty string, the system applies backup withholding at 2,400 basis points (24%) of the taxable base regardless of size, rounded half-up to the nearest cent. When the initiator's `tax_id` is present, the rule is threshold-driven: if the taxable base in cents is strictly greater than 60,000 (which corresponds to USD 600.00, a reporting threshold where the boundary is exclusive — exactly USD 600.00 does not trigger the rate), `tax_withheld_cents` is computed at 1,000 basis points (10%) of the taxable base, rounded half-up to the nearest cent; otherwise, when the taxable base in cents is less than or equal to 60,000, `tax_withheld_cents` is zero.

### 3.13. Audit Log Access and the Escrow Ledger View

The platform exposes the audit trail and the escrow ledger as read-only listings. The audit log is filterable by `subject_type`, `subject_id`, and `event_type`, paginated through `limit` and `offset`, and is restricted to `PlatformAdmin` callers. The per-project escrow ledger is restricted to the owning initiator and platform admins; entries are returned in the standard pagination order and include all fund movements affecting the project — authorization holds, capture, voids, refunds out, commission holds and reversals, channel fees, and the eventual settlement payout.

## 4. Endpoint Definitions

Endpoints follow standard REST conventions over JSON. Endpoints that mint a brand-new resource return HTTP 201; reads, modifications, and action endpoints (review decisions, cancellations, approvals, executions, finalizations, and the test drivers) return HTTP 200. Failure modes use 4xx codes per the standard error envelope; the trigger conditions for each `error_id` are in §2 and §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /initiators | Register an initiator (KYC pending). | Initiator, PlatformAdmin |
| POST | /initiators/{id}/verify-kyc | Mark initiator KYC verified or rejected. | PlatformAdmin |
| POST | /backers | Register a backer. | Backer, PlatformAdmin |
| POST | /projects | Create draft project. | Initiator |
| GET | /projects/{id} | Read project (with computed counters). | Initiator, Backer, ContentReviewer, LegalReviewer, FinancialReviewer, PlatformAdmin |
| GET | /projects | List projects (filter by status, category). | Initiator, Backer, ContentReviewer, LegalReviewer, FinancialReviewer, PlatformAdmin |
| PATCH | /projects/{id} | Edit project while in DRAFT. | Initiator |
| POST | /projects/{id}/submit | Submit DRAFT project to CONTENT_REVIEW. | Initiator |
| POST | /projects/{id}/review-content | Content reviewer decision. | ContentReviewer |
| POST | /projects/{id}/review-legal | Legal reviewer decision. | LegalReviewer |
| POST | /projects/{id}/review-financial | Financial reviewer decision. | FinancialReviewer |
| POST | /projects/{id}/cancel | Initiator cancels LIVE project before deadline. | Initiator |
| POST | /projects/{project_id}/rewards | Create reward tier (DRAFT only). | Initiator |
| GET | /projects/{project_id}/rewards | List rewards for project. | Initiator, Backer, ContentReviewer, LegalReviewer, FinancialReviewer, PlatformAdmin |
| PATCH | /projects/{project_id}/rewards/{id} | Update reward (DRAFT only). | Initiator |
| POST | /projects/{project_id}/add-on-items | Create add-on item (DRAFT only). | Initiator |
| GET | /projects/{project_id}/add-on-items | List add-on items. | Initiator, Backer, PlatformAdmin |
| POST | /orders | Place order on a LIVE project. | Backer |
| GET | /orders/{id} | Get an order. | Backer, Initiator, PlatformAdmin |
| PATCH | /orders/{id} | Modify order within window. | Backer |
| POST | /orders/{id}/cancel | Cancel order (own backer within window or admin override). | Backer, PlatformAdmin |
| POST | /projects/{project_id}/progress-updates | Publish project progress update (milestone or delay notice). | Initiator |
| GET | /projects/{project_id}/progress-updates | List progress updates (BACKERS_ONLY filtered for non-backers). | Backer, Initiator, PlatformAdmin |
| POST | /refund-requests | Create a refund request for an order. | Backer, PlatformAdmin |
| GET | /refund-requests/{id} | Read refund request. | Backer, Initiator, PlatformAdmin |
| POST | /refund-requests/{id}/approve | Approve a pending refund request. | PlatformAdmin |
| POST | /refund-requests/{id}/reject | Reject a pending refund request. | PlatformAdmin |
| POST | /refund-requests/{id}/execute | Execute an approved refund. | PlatformAdmin |
| POST | /projects/{project_id}/settlement-batches | Create a draft settlement batch over a period. | PlatformAdmin |
| POST | /projects/{project_id}/settlement-batches/{batch_id}/finalize | Finalize a draft settlement batch. | PlatformAdmin |
| GET | /projects/{project_id}/settlement-batches/{batch_id} | Read settlement batch. | Initiator, PlatformAdmin |
| GET | /audit-log | Filtered audit log. | PlatformAdmin |
| GET | /projects/{project_id}/escrow-ledger | Read escrow ledger entries for a project. | Initiator, PlatformAdmin |
| POST | /_clock/advance | Advance virtual clock to a supplied instant; triggers time-gated transitions. | PlatformAdmin |
| POST | /_events/payment | Simulate payment system event (charge success/failure). | PlatformAdmin |
| POST | /_events/banking | Simulate banking event for refund or settlement. | PlatformAdmin |
| POST | /_events/logistics | Register a shipment event (full or partial) for an order. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_KYC_REQUIRED | 422 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_DEADLINE_TOO_SOON | 422 |
| ERR_NO_REWARDS_DEFINED | 422 |
| ERR_MODIFICATION_WINDOW_CLOSED | 422 |
| ERR_REWARD_INVENTORY_EXHAUSTED | 409 |
| ERR_ADDON_INVENTORY_EXHAUSTED | 409 |
| ERR_SHIPPING_ADDRESS_REQUIRED | 422 |
| ERR_CROSS_PROJECT_REFERENCE | 422 |
| ERR_REFUND_EXCEEDS_REMAINDER | 422 |
| ERR_UPDATE_FREQUENCY_BREACH | 422 |
| ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT | 422 |
| ERR_INVALID_AMOUNT | 422 |
| ERR_DUPLICATE_TIER_LABEL | 422 |

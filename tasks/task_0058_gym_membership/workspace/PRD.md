# Gym Membership API — Product Requirements Document

## 1. Introduction

This document specifies the back-office and member-facing API for a gym's membership platform. The system unifies several overlapping concerns: per-visit, monthly, and annual cards with shared family entitlements and freeze handling; trainer-side personal-training (PT) slots, single-session and package bookings, and tier-driven commissions; group-class scheduling with capacity, waitlist, and instructor substitution; and a stored-value wallet with bonus credits, refund handling, and ledger-projected balances. Around these business surfaces sit time-driven side effects — expiring cards, freeze settlements, no-show transitions, payout-cycle closes, and renewal-reminder fan-outs — that need a deterministic logical-clock entry point so the test harness can advance time without wall-clock dependency.

The driving operational pressures are reconciliation correctness and time-sensitive cascades. Card values must remain consistent across freeze extensions, partial transfers, and proportional refunds; commission must accrue and reverse in lockstep with the bookings and packages that earned it; wallet balances are reconstructed from an append-only ledger where bonus credits are consumed FIFO ahead of principal funds. The contract is therefore intentionally explicit about evaluation order, rounding, and the precise error returned by the losing side of every race, because those decisions decide whether a refund preview, a transfer fee, or a payout-close reconciles to the cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry an `X-User-ID` header and an `X-User-Role` header. When either is absent or the role name is unknown, the request is rejected with `ERR_AUTH_REQUIRED`. When the role is known but is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN`.

The system recognises five roles, named exactly:

- `PlatformAdmin` — the highest-privilege operator, with override authority across cards, commissions, trainers, payouts, and audit reads. `X-User-ID` for a `PlatformAdmin` is an opaque operator identifier not tied to any persisted entity. The server may record it on audit entries (for example on `AuditLogEntry.actor_id`) but does not compare it to any entity's `id`.
- `StaffOps` — the front-desk operator who can act on behalf of members across card lifecycle, bookings, wallet recharges, group class admin, and slot publication. `X-User-ID` for a `StaffOps` caller is likewise an opaque operator identifier with no persisted entity behind it; the server records it on audit entries via `AuditLogEntry.actor_id` but never compares it to any `id`.
- `Member` — the end user. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field (for example `Card.holder_member_id`, `PTBooking.member_id`, `GroupBooking.member_id`, `FreezeEpisode`'s parent card's `holder_member_id`) to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- `Trainer` — when `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer`; ownership checks on any resource that references a `Trainer` compare its trainer foreign key (for example `TrainerSlot.trainer_id`, `PTBooking.trainer_id`, `PTPackage.trainer_id`, `GroupClass.instructor_trainer_id`) to `X-User-ID`.
- `system` — used only by operator-tooling endpoints (clock advance, sweep run, external-event emit). `X-User-ID` for `system` is an opaque internal identifier not tied to any persisted entity.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside this band are rejected with `ERR_VALIDATION`. `offset` defaults to 0 and has a minimum of 0. Results are sorted by `created_at` ascending; pagination is stable because all entities carry `created_at`. The `meta` block on list responses surfaces `limit`, `offset`, `total_count`, and `has_more` — the last of which is true exactly when more rows exist beyond the returned window.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix. Resources whose entity has the common-fields shape additionally carry `created_at`, `updated_at`, and `version`. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set once at row birth and never moves, while `updated_at` is refreshed on every mutation. The `version` field is an integer that starts at 1 on creation and increments by exactly one on each mutation. The entities `Member`, `CardType`, `Card`, `Trainer`, `TrainerSlot`, `PTBooking`, `PTPackage`, `GroupClass`, `GroupBooking`, and `FreezeEpisode` all carry this full common-field shape.

The append-only ledger and archival entities — `WalletTransaction`, `TransferRecord`, `CommissionRecord`, `PayoutCycle`, `RenewalReminder`, and `AuditLogEntry` — carry only `id` and `created_at`. They have no `updated_at` and no `version`, because once written they are not mutated.

### 2.5. Optimistic Concurrency Control

Every `PATCH` endpoint accepts an optional `version` field in the body. When `version` is supplied, the server compares it to the current entity version: if they match, the mutation proceeds and `version` is bumped; if they differ, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the OCC check is skipped and the write proceeds against whatever the current row holds. Two concurrent `PATCH`es that submit the same prior `version` will serialise such that exactly one wins on the increment; the loser receives `ERR_VERSION_CONFLICT`.

### 2.6. Path-Parameter Resolution

URL paths that nest path parameters are resolved left-to-right: the leftmost id must resolve to an existing parent entity before any rightward id is checked. If any path-parameter id along the chain does not resolve, the response is `ERR_NOT_FOUND` with HTTP 404. Foreign-key body fields — including `card_type_id`, `holder_member_id`, `member_id`, `trainer_id`, `slot_id`, `package_id`, `class_id`, `card_id`, and `to_member_id` — are likewise checked for existence, and unresolved references return `ERR_NOT_FOUND`.

### 2.7. Money, Time, and Rounding

All monetary amounts are stored and exchanged as integer cents. Computations that produce non-integer intermediate values are rounded to the nearest cent using half-up rounding (a value exactly halfway between two integers rounds up to the larger). When a calculation pipeline has multiple steps, rounding is applied at the step the formula in §3 nominates — typically a single final rounding rather than rounding per intermediate sub-amount. The one exception, surfaced explicitly in the refund preview, is the chronological-remaining variant which rounds per day before summing; this variant is for preview only and never drives the actual refund.

Tiered percentages used by recharge bonuses, transfer fees, renewal discounts, and trainer commissions are stored in **basis points**, where 10,000 basis points equal 100%. When multiplying an amount in cents by a basis-point rate, the system divides by 10,000 at the step the formula declares; rounding is half-up except for the recharge-bonus tier multiplication, which truncates toward zero (see §3.4).

Durations are expressed in days for membership-lifetime measurements (validity, freeze, refund-eligibility, transfer-grace, renewal-window) and in minutes for the no-show grace and class buffer. Both the `TrainerSlot` interval and the `GroupClass` interval are half-open: `[starts_at, ends_at)`. End-of-day timestamps used for expiry semantics are anchored at 23:59:59.999Z UTC.

### 2.8. Wallet Ledger Principles

The wallet is an append-only ledger of `WalletTransaction` rows. A member's `wallet_balance_cents` is projected by summing every `WalletTransaction.amount_cents` for that member; the sign on `amount_cents` distinguishes credits (`RECHARGE`, `BONUS_GRANT`, `REFUND`) from debits (`DEBIT`, `BONUS_EXPIRE`). A seventh `kind`, `ADJUSTMENT`, is reserved for operator-initiated balance corrections recorded directly against the ledger; the sign on `amount_cents` carries the direction of the correction. The two sub-balances — `principal_balance_cents` and `bonus_balance_cents` — are projected by filtering on the `bucket` field, which is either `PRINCIPAL` or `BONUS`, and the `Member.bonus_balance_cents` and `Member.bonus_expires_at` fields surface the bonus sub-ledger to readers. Reads always project from the latest append; concurrent appends serialise via append order, and the rare reconciler conflict in that path surfaces as `ERR_WALLET_LEDGER_CONFLICT`. The `kind`, `service_type`, `ref_entity`, and `expires_at` columns on each row form the polymorphic provenance trail that audit and refund logic walk.

### 2.9. Hierarchical State Consistency

Many transitions ripple across more than one entity. Approving a freeze on a card transitions both the `FreezeEpisode` from `REQUESTED` to `APPROVED` and the `Card` from `ACTIVE` to `FROZEN`; settling the freeze cascades the opposite way and recomputes the card's `effective_expiry_date`. Completing a PT session in package mode advances `PTPackage.sessions_consumed` and may flip the package to `EXHAUSTED`. Cancelling a confirmed group booking promotes the head of the waitlist. In every such cascade the dependent entity's `updated_at` is refreshed and its `version` is incremented by one; downstream readers using OCC against the stale prior `version` are rejected with `ERR_VERSION_CONFLICT`. The audit log is the cross-cutting witness: `CARD_ADJUST`, `COMMISSION_ADJUST`, `CARD_REFUND`, `FREEZE_OVERRIDE`, and `COMMISSION_REVERSAL` are the recognised `action` codes, written by side-effect machinery rather than by direct API calls.

### 2.10. Time-Gated Transitions and the Logical Clock

Several transitions are driven not by an explicit endpoint but by time crossing a threshold: a freeze settling at `ends_at`, a card expiring at `effective_expiry_date`, a PT booking flipping to `NO_SHOW` 15 minutes after `scheduled_starts_at`, a group booking flipping to `NO_SHOW` at `ends_at`, a group class auto-completing at `ends_at`, and the renewal sweep producing T30, T7, and T0 reminders. The clock-advance capability is the deterministic test entry point that nudges the logical clock to a supplied instant and fires every time-gated transition whose threshold lies between the old and new clock values. A parallel sweep capability runs the renewal-reminder fan-out independently for tests that want to exercise reminder behaviour without moving the clock further.

## 3. Business Logic & Workflows

### 3.1. Configuring Card Types and Members

A `PlatformAdmin` operator establishes the catalogue of card configurations before any card can be issued. Each `CardType` has a business key `code` that is unique, between 2 and 32 characters long, and uppercase snake-case; a `category` of `PER_VISIT`, `MONTHLY`, or `ANNUAL`; a `price_cents` that must be at least zero; a `validity_days` between 1 and 3650 inclusive; a `visit_quota` that is at least zero (with the value 0 meaning unlimited visits, the typical setting for `MONTHLY` and `ANNUAL`); a `family_shareable` flag; a `max_freeze_days` cumulative freeze cap that is at least zero; a `transfer_fee_pct_bp` between 0 and 10,000 basis points; a `renewal_discount_pct_bp` between 0 and 10,000 basis points; and a `refund_eligibility_days` at least zero. The `validity_days` field is ignored when `category` is `PER_VISIT` and `visit_quota` is greater than zero — such cards expire when their visits are exhausted or when `validity_days` elapses, whichever happens first. Every `CardType` carries a configuration-lifecycle `status` that begins at `ACTIVE` and can be moved to `RETIRED` by patch; a `RETIRED` card type rejects new card issuance with `ERR_CARD_TYPE_RETIRED`, but already-issued cards continue to operate against the pricing that was pinned at their issuance.

Member registration captures `full_name` (1 to 120 characters), `phone` (unique E.164 digits only), `email` (unique), optional `family_group_id` (members sharing the same value can use family-shared cards), optional `notification_channels` (a subset of `SMS`, `EMAIL`, `IM`, and `PUSH`, defaulting to `["SMS", "EMAIL"]`), and optional `auto_renew_authorized` (defaulting to false). The wallet-balance fields `wallet_balance_cents`, `bonus_balance_cents`, and `bonus_expires_at` are server-computed from the ledger and start at zero, zero, and null respectively.

### 3.2. The Card Lifecycle

Issuing a card produces a `Card` whose `card_type_id` and `holder_member_id` are taken from the request body and whose `issuance_price_cents` is copied from `CardType.price_cents` at the issuance moment. Issuance also debits the wallet of the holder for `CardType.price_cents` (recorded as a `WalletTransaction` with `kind=DEBIT`, `bucket=PRINCIPAL`, `service_type=CARD_ISSUANCE`, `ref_entity` pointing at the new card). The card is born in `PENDING` status with `activation_date`, `original_expiry_date`, `effective_expiry_date` all null, `visits_consumed` at zero, `visits_remaining` set to the card type's `visit_quota` when that quota is positive and to null when it is zero (unlimited), `cumulative_freeze_days` at zero, and `parent_card_id` null for an original issuance.

Activating a `PENDING` card requires the card to currently be `PENDING` and the referenced card type to still be `ACTIVE`; on success the card transitions `PENDING → ACTIVE`, `activation_date` is set to the current instant, `original_expiry_date` is set to `activation_date` plus `validity_days` (anchored at end-of-day UTC), `effective_expiry_date` is set equal to `original_expiry_date` (no freeze yet), and an access-control grant event is emitted carrying the card id, the holder member id, and the effective expiry. The transition is invoked through the activate capability available to `StaffOps` and `PlatformAdmin`.

A card naturally expires when the clock crosses its `effective_expiry_date`, or — for `PER_VISIT` cards whose `visit_quota` is greater than zero — when its `visits_remaining` reaches zero. The system transitions the card `ACTIVE → EXPIRED`, emits a permanent access-control revoke, and either triggers auto-renewal or dispatches a final reminder. Auto-renewal fires only when the member's `auto_renew_authorized` is true and a `RenewalReminder` with `tier` `T0` has been dispatched: in that case the system creates a child `Card` in `PENDING` status with its `parent_card_id` set to the expiring card, debits the member's wallet for the renewal price (computed per §3.7), and activates the child card immediately (the same `PENDING → ACTIVE` cascade described above). When auto-renewal does not fire, a `RenewalReminder` is recorded with `tier=T0` and `status=LAPSED`.

Two non-time-driven terminal transitions exist for an `ACTIVE` card. Refund (described in §3.6) moves the card `ACTIVE → REFUNDED`. Transfer (described in §3.6) moves the card `ACTIVE → TRANSFERRED` and creates a child card at the destination. `REFUNDED`, `TRANSFERRED`, and `EXPIRED` are terminal states.

The status enumeration for `Card` is therefore `PENDING`, `ACTIVE`, `FROZEN`, `EXPIRED`, `REFUNDED`, and `TRANSFERRED`. The state pair `ACTIVE → FROZEN` is driven by the freeze workflow in §3.5; `FROZEN → ACTIVE` is driven either by clock-cross at the freeze episode's end or by an early unfreeze.

### 3.3. Stored-Value Recharges and Bonus Credits

Members top up their wallet through the recharge capability available to `Member`, `StaffOps`, and `PlatformAdmin`. The request body carries a single `amount_cents` field. The value must be strictly greater than zero and no more than 1,000,000 cents; otherwise the request is rejected with `ERR_RECHARGE_AMOUNT_INVALID`.

Each successful recharge appends a `RECHARGE` row to the ledger with `bucket=PRINCIPAL` and `amount_cents` set to the requested amount, and may additionally append a `BONUS_GRANT` row. The bonus tier is computed from the requested amount alone: amounts of at least 100,000 cents earn a 20% bonus, amounts of at least 50,000 cents earn a 10% bonus, amounts of at least 20,000 cents earn a 5% bonus, and amounts below 20,000 cents earn no bonus. The bonus amount in cents equals the requested amount multiplied by the tier's basis-point rate divided by 10,000, with the result truncated toward zero — recharge bonuses do not round up. When the bonus is greater than zero, a `BONUS_GRANT` row is appended with `bucket=BONUS`, the truncated bonus value as `amount_cents`, and `expires_at` set to 365 days after the current instant anchored at end-of-day UTC. The earliest unexpired `BONUS_GRANT.expires_at` over all outstanding grants is what the member-read surface exposes as `bonus_expires_at`; when the bonus balance is zero this field is null. A successful recharge also emits a payment-sync `RECHARGED` event.

### 3.4. Wallet Debits, Quotes, and Bonus Consumption

Every debit driven by issuance, PT booking in single-session mode, group-class entry, transfer fee, or no-show penalty walks the ledger in a fixed order. The debit amount is satisfied first from outstanding `BONUS_GRANT` rows in FIFO order — bonuses with the earliest `expires_at` go first, with ties broken by the earliest `created_at`. For each grant consumed, a `DEBIT` row with `bucket=BONUS`, an `amount_cents` that is the negative of the bonus portion taken, and a `ref_entity` pointing at the grant is appended; the running need is reduced by the amount consumed and consumption stops as soon as the need reaches zero. Any unmet remainder is then satisfied from principal: if `principal_balance_cents` is less than the remainder, the entire debit aborts with `ERR_INSUFFICIENT_BALANCE` and no rows are appended; otherwise a single `DEBIT` row with `bucket=PRINCIPAL`, an `amount_cents` that is the negative of the remainder, and a `ref_entity` pointing at the originating booking, package, card, or transfer is appended.

Refunds and class-cancel refunds always credit `PRINCIPAL` regardless of which bucket originally paid — bonus credits are never returned to the bonus bucket. This one-way flow keeps bonus value tied to the recharge episode that produced it.

The wallet-quote read-only capability lets a member or operator see what a hypothetical debit would consume without mutating the ledger. Its query parameters are `amount_cents` and an optional `service_type`. The quote surface walks the same FIFO consumption order against the current ledger projection and reports which grants would be drawn down and how much principal would be needed, but appends nothing.

The ledger-listing capability for `WalletTransaction` rows accepts pagination parameters as well as optional `kind` and `bucket` filters that match `WalletTransaction.kind` and `WalletTransaction.bucket` exactly. Rows are returned in `created_at` ascending order, consistent with §2.3.

### 3.5. Freeze Episodes and the Freeze Budget

Freezing a card is a member-initiated or staff-initiated action that takes a `reason` of either `ILLNESS` or `BUSINESS_TRIP` and a `requested_days` that is at least 1. The card must currently be `ACTIVE`; otherwise the request is rejected with `ERR_INVALID_STATE`. The remaining freeze budget — `CardType.max_freeze_days` minus `Card.cumulative_freeze_days` — must be strictly greater than zero; when it is exactly zero, the system creates a `FreezeEpisode` in `REQUESTED` status and immediately moves it to `REJECTED`, returning `ERR_FREEZE_BUDGET_EXHAUSTED`. The card must additionally have no concurrent freeze already in `APPROVED` status (rejected with `ERR_FREEZE_IN_PROGRESS`), and it must have no `PTBooking` in `CONFIRMED` status whose `scheduled_starts_at` falls inside the proposed freeze window — that cross-entity guard is rejected with `ERR_FREEZE_CONFLICTS_WITH_BOOKING`.

When all preconditions hold, the `FreezeEpisode` is created with `card_id` set, `reason` and `requested_days` from the body, `starts_at` set to the current instant, `actual_days` set to the smaller of `requested_days` and the remaining freeze budget, and `ends_at` set to `starts_at` plus `actual_days` anchored at end-of-day UTC. The episode immediately transitions `REQUESTED → APPROVED`. The owning card cascades from `ACTIVE` to `FROZEN`, its `cumulative_freeze_days` rises by the episode's `actual_days`, and an access-control revoke event is emitted carrying the card id and the episode's `ends_at`.

Two paths end a freeze. When the clock crosses `ends_at`, the system settles the episode (`APPROVED → SETTLED`) and brings the card back from `FROZEN` to `ACTIVE`, recomputing `effective_expiry_date` (see below) and emitting an access-control grant with the new effective expiry. When a member or operator invokes the early-unfreeze capability before `ends_at` — supplying the target episode as `freeze_episode_id` in the body — the episode transitions `APPROVED → CANCELED`: its `actual_days` is reduced to the ceiling of the elapsed time in days (the in-flight days are charged, but the unused tail is returned), its `ends_at` is moved to the current instant, the card transitions back to `ACTIVE`, `cumulative_freeze_days` is recomputed, and `effective_expiry_date` is recomputed.

The `effective_expiry_date` of a card is its `original_expiry_date` plus the sum of `FreezeEpisode.actual_days` across episodes whose `status` is in `SETTLED`, `APPROVED`, or `CANCELED`. `APPROVED` episodes contribute their current `actual_days` so an in-progress freeze pushes the effective expiry out immediately; `CANCELED` episodes contribute the truncated `actual_days` captured at cancellation time (early unfreezing shortens the extension but never makes it negative). The effective expiry is truncated to end-of-day UTC.

The status enumeration for `FreezeEpisode` is `REQUESTED`, `APPROVED`, `SETTLED`, `REJECTED`, and `CANCELED`. The cancel capability is exposed on the freeze-episode resource itself (not on the card) and is the same action the unfreeze capability on the card invokes internally.

### 3.6. Refunds and Transfers

A card can be refunded only while it is in `ACTIVE` status (rejected with `ERR_INVALID_STATE` otherwise). The card's remaining validity in days — `effective_expiry_date` minus the current instant — must be at least `CardType.refund_eligibility_days`; otherwise the response is `ERR_REFUND_NOT_ELIGIBLE`. The card must additionally have no `FreezeEpisode` in `SETTLED` status: any card that was ever frozen and settled is non-refundable, with rejection code `ERR_REFUND_FROZEN_CARD_BLOCKED`. Note that this is a distinct check from the eligibility-days check above; the fiscal-window check runs first, then the ever-frozen check.

On refund, the system computes the remaining value via the forward-looking formula. For a `PER_VISIT` card the unit value is `Card.issuance_price_cents` divided by `CardType.visit_quota`, and the remaining value is that unit value multiplied by `Card.visits_remaining`, with the product rounded half-up to the nearest cent at the final step. For a `MONTHLY` or `ANNUAL` card the remaining days are the maximum of zero and `effective_expiry_date` minus the current instant in days; the remaining value is `Card.issuance_price_cents` multiplied by remaining days divided by `CardType.validity_days`, rounded half-up at the final step. This is a sum-then-round policy: the multiplication and division are computed in full precision before a single rounding step, never one rounding per day.

The remaining value is credited to the holder's wallet as a `WalletTransaction` with `kind=REFUND`, `bucket=PRINCIPAL`, and `ref_entity` pointing at the card. The card transitions `ACTIVE → REFUNDED`, an access-control permanent revoke is emitted, any unconsumed package commissions tied to the holder are reversed (no-op when none exist), and an `AuditLogEntry` with `action=CARD_REFUND` is written, capturing the calling role in `actor_role`, the caller's `X-User-ID` in `actor_id`, the card reference in `target_entity`, and a structured before/after diff in `payload`.

The refund-preview capability surfaces both the forward-looking remaining value (which the actual refund will use) and a parallel chronological variant. The chronological variant applies only when the card category is `MONTHLY` or `ANNUAL` and walks day-by-day from the current instant to `effective_expiry_date`, accumulating `Card.issuance_price_cents` divided by `CardType.validity_days` per day, rounding each per-day amount half-up to the nearest cent before summing. For non-evenly-divisible issuance prices this yields a different result from the forward-looking sum-then-round; surfacing both lets members see the worst-case rounding outcome.

A card can be transferred only while it is `ACTIVE`, has `visits_consumed` equal to zero (any card that has been entered against is non-transferable), has no `FreezeEpisode` in either `APPROVED` or `SETTLED` status, and has a destination Member that satisfies the relationship rule: either the destination member shares the source holder's `family_group_id`, or the card type's `family_shareable` is true, or the card was issued within the last 7 days. Failing the visit-or-freeze precondition returns `ERR_TRANSFER_NOT_ELIGIBLE`; failing the relationship rule returns `ERR_TRANSFER_INELIGIBLE_RECIPIENT`. The request body carries the destination as `to_member_id`.

When the transfer proceeds, the system first computes `remaining_value_cents` using the forward-looking formula above. It then computes `transfer_fee_cents` by multiplying that remaining value by `CardType.transfer_fee_pct_bp` and dividing by 10,000, rounding half-up at this step, and finally taking the maximum of that result and 2,000 cents — that floor is the minimum transfer fee. The wallet is debited for the transfer fee as a `WalletTransaction` with `kind=DEBIT`, `bucket=PRINCIPAL`, `service_type=TRANSFER_FEE`, and `ref_entity` pointing at the card. The source card transitions `ACTIVE → TRANSFERRED`. A new `Card` in `ACTIVE` status is created for the destination member, inheriting `activation_date` and `original_expiry_date` from the source and setting `parent_card_id` to the source card's id. A `TransferRecord` is appended capturing `source_card_id`, the new card id as `destination_card_id`, the previous holder as `from_member_id`, the new holder as `to_member_id`, the computed `remaining_value_cents`, and the computed `transfer_fee_cents`. Two access-control sync events are emitted: a revoke on the old card and a grant on the new card.

### 3.7. Renewal Quotes, Reminders, and Lapse

The renewal-quote capability returns the renewal price a holder would pay right now. The system measures the number of whole days between the current instant and `effective_expiry_date`. When that value is greater than 30, no discount applies and the quote equals `CardType.price_cents`. When it is at least 7 and no more than 30, the discount in basis points equals `CardType.renewal_discount_pct_bp`. When it is at least 0 and no more than 6, the discount is `CardType.renewal_discount_pct_bp` plus 500 basis points — an extra five percentage points inside the final week. When the card has already lapsed (days-to-expiry is negative), the discount is zero. The renewal price is `CardType.price_cents` multiplied by (10,000 minus the discount in basis points) divided by 10,000, rounded half-up at the final step. The auto-renewal cascade described in §3.2 uses exactly this same formula to compute the wallet debit it applies on behalf of the member.

The sweep capability scans all `ACTIVE` cards and, for each card, computes the days between the current instant and its `effective_expiry_date`. When that value is exactly 30 days a tier-`T30` `RenewalReminder` is produced and fanned out over the intersection of the member's `notification_channels` with `{SMS, EMAIL}`. When it is exactly 7 days a tier-`T7` reminder is produced and fanned out over the intersection of `notification_channels` with `{SMS, EMAIL, IM}`. When it is less than or equal to zero a tier-`T0` reminder is produced and fanned out over the intersection of `notification_channels` with `{SMS, EMAIL, IM, PUSH}`; in this last case, if the member has `auto_renew_authorized=true` the reminder's `status` is `AUTO_RENEW_TRIGGERED`, otherwise if the days are strictly negative the `status` is `LAPSED`, and otherwise (exactly zero) the `status` is `SENT`. The channel intersection actually fanned out is persisted on the reminder as `channels_dispatched`. No reminder is dispatched for any other day value. The send-reminder capability on a card lets an operator force a specific `tier` independently of the sweep — the body carries the `tier` value.

### 3.8. Personal Training Slots, Bookings, and Packages

Trainers are created and updated only by `PlatformAdmin`. A `Trainer` record carries `full_name`, a non-empty `specialties` array of specialty codes such as `STRENGTH`, `YOGA`, or `REHAB`, a per-session commission rate in basis points (`session_commission_pct_bp`, between 0 and 10,000), a package-sales commission rate in basis points (`package_commission_pct_bp`, between 0 and 10,000), a performance `tier` recomputed at payout-close (`BRONZE`, `SILVER`, or `GOLD`, with `BRONZE` as the default), and an active/inactive `status` (`ACTIVE` or `INACTIVE`). Inactive trainers cannot be booked or sold against, with rejection code `ERR_TRAINER_INACTIVE`.

Slots are published against a specific trainer with `starts_at`, `ends_at`, and `specialty_code`. The `specialty_code` must be in the trainer's `specialties` array, otherwise the slot cannot be the subject of a booking and the related booking attempt would fail with `ERR_SPECIALTY_MISMATCH`. The interval `[starts_at, ends_at)` is half-open; publishing a slot that overlaps any other slot of the same trainer whose `status` is `OPEN` or `RESERVED` is rejected with `ERR_SLOT_OVERLAP`. Slots that touch endpoint-to-endpoint (one slot's `ends_at` equals the next slot's `starts_at`) are explicitly allowed because the half-open semantics make them non-overlapping. The slot status enumeration is `OPEN`, `RESERVED`, `COMPLETED`, `CANCELED`, and `NO_SHOW`. Slot listing accepts `trainer_id`, `specialty_code`, `status`, `starts_after`, and `starts_before` as filter query parameters.

Booking a single PT session requires the slot to be currently `OPEN` (rejected `ERR_SLOT_ALREADY_RESERVED` otherwise) and the trainer to be `ACTIVE`. The body carries `member_id`, `slot_id`, `billing_mode`, and optional `package_id`. The `billing_mode` is either `SINGLE` (wallet-debited) or `PACKAGE` (consumed against an active package). When `billing_mode` is `SINGLE`, the wallet is debited for the session price as a `WalletTransaction` with `kind=DEBIT`, `bucket=PRINCIPAL`, `service_type=PT_SESSION`, and `ref_entity` pointing at the booking — subject to the bonus-first FIFO consumption described in §3.4. When `billing_mode` is `PACKAGE`, `package_id` must point at an active `PTPackage` for the same member and trainer; no wallet debit fires, but the booking is considered package-debited and will draw down the package's session count on completion. On successful booking creation, the `TrainerSlot` flips `OPEN → RESERVED` atomically with the booking row, the `PTBooking` is created in `CONFIRMED` status, `scheduled_starts_at` is mirrored from the slot's `starts_at` so cancellation windows can be measured without a join, and `session_price_cents` is pinned. The status enumeration for `PTBooking` is `CONFIRMED`, `COMPLETED`, `CANCELED`, and `NO_SHOW`.

Cancelling a `CONFIRMED` booking before its `scheduled_starts_at` returns the slot to `OPEN`. When the cancellation lands at least 24 hours before `scheduled_starts_at` and the `billing_mode` is `SINGLE`, the session price is refunded to the wallet as a `WalletTransaction` with `kind=REFUND` and `bucket=PRINCIPAL`. When `billing_mode` is `SINGLE` and the cancellation lands strictly less than 24 hours before `scheduled_starts_at`, no refund is issued — that is the late-cancel penalty. When `billing_mode` is `PACKAGE`, cancellation of a confirmed package-booked session frees the slot without affecting the package totals because package consumption only fires on completion. Attempting to cancel at or after `scheduled_starts_at` is rejected with `ERR_CANCEL_WINDOW_EXPIRED`.

Marking a booking complete requires `now()` to be at or after `scheduled_starts_at` and the booking to be in `CONFIRMED` status. The slot flips to `COMPLETED`. When `billing_mode` is `PACKAGE`, `PTPackage.sessions_consumed` is incremented; if it now equals `PTPackage.total_sessions`, the package flips `ACTIVE → EXHAUSTED`. A `CommissionRecord` of `kind=SESSION` is appended whose `amount_cents` is `session_price_cents` multiplied by the trainer's effective rate divided by 10,000, rounded half-up. The effective rate is `Trainer.session_commission_pct_bp` plus a tier modifier: 0 basis points when the trainer is `BRONZE`, 500 when `SILVER` (a five-percentage-point uplift), and 1000 when `GOLD` (a ten-percentage-point uplift). The tier modifier is applied at session-complete time, not deferred to payout close. The `ref_entity` on the commission row points at the booking.

The no-show transition fires either explicitly via the no-show capability (operators only) or automatically when the clock crosses `scheduled_starts_at` plus 15 minutes without a complete having been recorded. The booking flips `CONFIRMED → NO_SHOW`, the slot flips to `NO_SHOW`, the wallet is debited the no-show penalty constant (a fixed cents amount; recorded as a `WalletTransaction` with `kind=DEBIT`, `bucket=PRINCIPAL`, `service_type=PT_SESSION`), and when `billing_mode` is `PACKAGE` the package's `sessions_consumed` is still incremented because the session slot is forfeited. No commission accrues on a no-show; only `COMPLETED` accrues session commission.

A `PTPackage` is sold against a single trainer and tied to one purchasing member. The body carries `member_id`, `trainer_id`, `total_sessions` (at least 1), and `gross_price_cents` (at least 0). On successful creation, the wallet is debited for `gross_price_cents` (subject to bonus-first FIFO consumption) and a `CommissionRecord` of `kind=PACKAGE_SALE` is appended whose `amount_cents` equals `gross_price_cents` multiplied by `Trainer.package_commission_pct_bp` divided by 10,000, rounded half-up. The package's `sessions_consumed` and `sessions_refunded` both start at zero and the `status` begins at `ACTIVE` (terminal states are `EXHAUSTED` and `REFUNDED`).

The session price pinned on a package-billed booking comes from a pinned per-session evaluation. The base unit price is the floor of `gross_price_cents` divided by `total_sessions`; the remainder is `gross_price_cents` minus the base unit multiplied by `total_sessions`. Each completed session of the package is priced at the base unit, except for the final completed session (the `total_sessions`-th completion), which is priced at the base unit plus the remainder. This puts every cent of remainder onto the last completed session deterministically.

Refunding a package requires the package to currently be `ACTIVE` and to have `sessions_consumed` strictly less than `total_sessions`. On refund the wallet receives a credit equal to (`total_sessions` minus `sessions_consumed`) multiplied by the package unit price (per the pinned evaluation above), as a `WalletTransaction` with `kind=REFUND` and `bucket=PRINCIPAL`. The package-sale commission is reversed proportionally: the system locates the original `PACKAGE_SALE` `CommissionRecord` for the package, computes the unconsumed-sessions count, and appends a `CommissionRecord` of `kind=REVERSAL` whose `amount_cents` equals the negative of the original commission multiplied by unconsumed sessions divided by `total_sessions`, rounded half-up. Each currently-`CONFIRMED` `PTBooking` whose `package_id` matches this package is cancelled (its slot returned to `OPEN`). The package transitions `ACTIVE → REFUNDED`, and an `AuditLogEntry` with `action=COMMISSION_REVERSAL` is written.

The card-refund cascade described in §3.6 includes a "reverse any unconsumed package commissions tied to this card's holder" step. This is a no-op when no such packages exist; when they do exist, the same proportional reversal logic fires against each affected package.

### 3.9. Group Classes, Capacity, and Waitlist

Group classes are scheduled by `StaffOps` or `PlatformAdmin`. The body carries `class_code`, `instructor_trainer_id`, `starts_at`, `ends_at`, `capacity` (at least 1), an optional `recurrence_series_id` (null for one-off classes), and an optional `deduction_cents` (default zero) that is the per-attendance wallet deduction for members paying via wallet. The class interval `[starts_at, ends_at)` is half-open. Unlike trainer slots, group classes require a 30-minute buffer between any two classes for the same `instructor_trainer_id` whose `status` is `SCHEDULED`; specifically, for any two such classes a and b ordered in time, b's `starts_at` minus a's `ends_at` must be at least 30 minutes. Adjacent-endpoint classes are therefore rejected at this step, with `ERR_CLASS_OVERLAP`. The class is born with `status=SCHEDULED`, `confirmed_count=0`, `waitlist_count=0`, and `substitute_trainer_id` null. Both `confirmed_count` and `waitlist_count` are server-computed: `confirmed_count` is the count of `CONFIRMED` `GroupBooking` rows for the class, and `waitlist_count` is the count of `WAITLISTED` rows for the class.

A group class can be edited via patch to raise `capacity` or to record a substitute trainer (the body carries `version`, optional `capacity`, and optional `substitute_trainer_id`). When `capacity` is raised, the system promotes waitlist heads (see below) until either the confirmed count equals the new capacity or the waitlist is empty.

Booking a class submits `class_id`, `member_id`, an optional `card_id` (when the member wants to pay by a card visit rather than the wallet deduction), and an optional `accept_waitlist` flag. When `accept_waitlist` is false and the class is at capacity, the booking is rejected with `ERR_CAPACITY_REACHED`. When `accept_waitlist` is true or omitted and the class is at capacity, the booking is created in `WAITLISTED` status; otherwise it is created in `CONFIRMED` status. The status enumeration is `CONFIRMED`, `WAITLISTED`, `CANCELED`, `ATTENDED`, and `NO_SHOW`.

When a `CONFIRMED` booking is created, the system either debits the wallet for `GroupClass.deduction_cents` (when no `card_id` is supplied and the deduction is greater than zero, as a `WalletTransaction` with `kind=DEBIT`, `bucket=PRINCIPAL`, and `service_type=GROUP_CLASS`) or consumes a visit on the supplied card. When the `card_id` belongs to a different member than the acting member, the family-share rule applies: the holder and the acting member must share a non-null `family_group_id`, otherwise `ERR_FAMILY_SHARE_NOT_AUTHORIZED`. Cards whose `visits_remaining` is zero cannot be supplied as payment and produce `ERR_CARD_VISITS_EXHAUSTED`. When a booking is created in `WAITLISTED` status, the row carries a 1-based `waitlist_position` (next behind the existing waitlist) and a `waitlisted_at` timestamp; no wallet debit or card visit fires until the booking is later promoted to `CONFIRMED`.

Cancelling a `CONFIRMED` booking requires the cancellation to land at least 2 hours before `starts_at`; otherwise it is rejected with `ERR_CANCEL_WINDOW_EXPIRED`. On successful cancellation, `confirmed_count` decreases by one and the head of the waitlist (the row with the lowest `waitlist_position`) is promoted: that row transitions `WAITLISTED → CONFIRMED`, its `waitlist_position` is set to null, every later waitlist row has its `waitlist_position` decremented by one, and an IM `PROMOTED` notification is emitted. The promotion-time wallet debit or card-visit consumption fires at that moment, identically to a fresh `CONFIRMED` booking. Cancelling a `WAITLISTED` booking does not change capacity but decrements the `waitlist_position` of every later waitlisted row.

Capacity-increase promotion follows the same rule: whenever `confirmed_count` falls below `capacity` (because of an increase or a cancellation), the lowest-position waitlisted row is promoted, the same wallet-or-visit consumption fires, and an IM `PROMOTED` notification is emitted.

Checking in at the class door transitions `CONFIRMED → ATTENDED` and, when a `card_id` was attached to the booking, increments that card's `visits_consumed` by one. The check-in requires `now()` to be at or after `class.starts_at`. When the clock crosses the class's `ends_at` while a booking is still `CONFIRMED`, the booking auto-transitions to `NO_SHOW` (no wallet effect — the deduction was already taken at confirmation). When the clock crosses the class's `ends_at` while the class is still `SCHEDULED`, the class auto-transitions `SCHEDULED → COMPLETED`.

Cancelling a class (operator-initiated, while `status=SCHEDULED` and `now()` is strictly before `ends_at`) transitions the class `SCHEDULED → CANCELED`, refunds each `CONFIRMED` booking (wallet credit of `GroupClass.deduction_cents` with `kind=REFUND` and `bucket=PRINCIPAL`, or card-visit return when a card was used), cancels every `WAITLISTED` booking, and emits an IM `CLASS_CANCELED` notification to each affected member.

### 3.10. Access Events and the Family Share Rule

Access events represent turnstile entries. The body carries `card_id` and `member_id`. The card must have `visits_remaining` strictly greater than zero (otherwise `ERR_CARD_VISITS_EXHAUSTED`). When the acting `member_id` differs from `Card.holder_member_id`, the family-share rule applies: the holder and the acting member must share a non-null `family_group_id`, otherwise `ERR_FAMILY_SHARE_NOT_AUTHORIZED`. On success, the card's `visits_consumed` is incremented by one; when this causes `visits_remaining` to reach zero on a `PER_VISIT` card with positive `visit_quota`, the card transitions `ACTIVE → EXPIRED` with the same access-revoke and renewal-reminder/auto-renew side effects as a clock-driven expiry.

### 3.11. Trainer Commissions, Tiers, and Payout Cycles

Trainer earnings accumulate as `CommissionRecord` rows whose `kind` is `SESSION` (from PT-session completion), `PACKAGE_SALE` (from package activation), `REVERSAL` (from package refund or card refund), or `TIER_BONUS` (added at payout close). Each row carries `trainer_id`, the signed `amount_cents`, a polymorphic `ref_entity`, and an initially-null `payout_cycle_id` that is set when the row is included in a closed cycle.

Opening a payout cycle takes `cycle_start` and `cycle_end` (both ISO 8601 UTC) and produces a `PayoutCycle` with `status=OPEN`. Closing the cycle requires the current instant to be at or after `cycle_end` (otherwise `ERR_PAYOUT_CYCLE_OPEN`) and the cycle to currently be `OPEN`. On close, the system performs three steps for each trainer.

First, it aggregates the trainer's `CommissionRecord` rows whose `kind` is one of `SESSION`, `PACKAGE_SALE`, or `REVERSAL`, whose `created_at` lies in the half-open interval `[cycle_start, cycle_end)`, and whose `payout_cycle_id` is null. Second, it counts the trainer's completed PT bookings — `PTBooking` rows with `status=COMPLETED` and `scheduled_starts_at` in `[cycle_start, cycle_end)` — to recompute `Trainer.tier`: at least 80 completed sessions promotes to `GOLD`, at least 40 promotes to `SILVER`, otherwise `BRONZE`. Third, the system appends a `CommissionRecord` of `kind=TIER_BONUS` whose `amount_cents` equals the sum of the trainer's `SESSION`-kind commission rows in the cycle window (matched on `trainer_id`, `kind=SESSION`, and `created_at` in `[cycle_start, cycle_end)`), multiplied by the tier-bonus basis-point rate, divided by 10,000, rounded half-up. The tier-bonus rate is zero for `BRONZE`, 1000 basis points (a ten-percent uplift on session commissions) for `SILVER`, and 2000 basis points (a twenty-percent uplift on session commissions) for `GOLD`. The new row carries `payout_cycle_id` set to this cycle and `ref_entity` pointing at the cycle. Finally, every aggregated row from step one has its `payout_cycle_id` stamped to this cycle, and the cycle's `closed_at` is set to the current instant and its `status` flipped to `CLOSED`.

Listing a trainer's commissions accepts pagination plus optional `payout_cycle_id` and `kind` filters that match the `CommissionRecord` fields exactly.

### 3.12. Concurrency, Races, and Audit

Several races have deterministic loser codes. Two members simultaneously booking the last open slot of a `TrainerSlot` will serialise on the slot's status flip: exactly one becomes `CONFIRMED` and the slot transitions `OPEN → RESERVED` atomically with that booking row; the other receives `ERR_SLOT_ALREADY_RESERVED`. Two members simultaneously grabbing the last confirmed seat of a `GroupClass` (when `confirmed_count` equals `capacity - 1`) will serialise on the `confirmed_count` increment: exactly one becomes `CONFIRMED`, and the other falls through to the waitlist path with `waitlist_position=1`; the only case where the loser sees `ERR_CAPACITY_REACHED` rather than entering the waitlist is when the loser supplied `accept_waitlist=false`. Two simultaneous refund attempts on the same card serialise on the card's status flip: exactly one wins and moves the card `ACTIVE → REFUNDED`; the loser receives `ERR_INVALID_STATE` because the card is no longer `ACTIVE`. Two simultaneous patches against the same entity carrying the same prior `version` serialise on the OCC check (see §2.5): exactly one wins; the loser receives `ERR_VERSION_CONFLICT`. Concurrent wallet operations (a debit and a recharge against the same member) always succeed as appended rows in deterministic order; the rare reconciler conflict in that path returns `ERR_WALLET_LEDGER_CONFLICT`.

Validation rules run in a fixed priority order so that the error returned matches the failure the caller most needs to know about. Authentication header presence and role-recognition checks run first (rejected with `ERR_AUTH_REQUIRED`), then RBAC permission checks (rejected with `ERR_FORBIDDEN`), then path-parameter existence (rejected with `ERR_NOT_FOUND`), then body foreign-key existence (rejected with `ERR_NOT_FOUND`). After those generic gates, ownership comes next for `Member` callers: a `Member` invoking a card, booking, or freeze action must own the resource via the relevant holder/member foreign key, otherwise `ERR_FORBIDDEN`. State-machine `from`-state checks come next, with `ERR_INVALID_STATE` for the generic mismatch and `ERR_CARD_TYPE_RETIRED` reserved for an issuance against a `RETIRED` card type. Business-safety checks (trainer inactive at booking or package sale → `ERR_TRAINER_INACTIVE`; specialty mismatch on PT booking → `ERR_SPECIALTY_MISMATCH`) and slot/class availability checks (`ERR_SLOT_ALREADY_RESERVED`, `ERR_SLOT_OVERLAP`, `ERR_CLASS_OVERLAP`, `ERR_CAPACITY_REACHED`) follow. Cancellation-window checks produce `ERR_CANCEL_WINDOW_EXPIRED`. The refund-eligibility days check fires before the ever-frozen check, so a card that is both inside the fiscal window and ever-frozen surfaces `ERR_REFUND_NOT_ELIGIBLE` first and `ERR_REFUND_FROZEN_CARD_BLOCKED` only when remaining days are sufficient. Similarly, the transfer-eligibility check (`ERR_TRANSFER_NOT_ELIGIBLE` — visits or ever-frozen) fires before the recipient-eligibility check (`ERR_TRANSFER_INELIGIBLE_RECIPIENT` — family/family-shareable/7-day grace). Freeze-budget exhaustion (`ERR_FREEZE_BUDGET_EXHAUSTED`) comes before freeze-in-progress (`ERR_FREEZE_IN_PROGRESS`) which comes before booking-conflict (`ERR_FREEZE_CONFLICTS_WITH_BOOKING`). Fiscal checks — wallet balance for any debit-bearing endpoint (`ERR_INSUFFICIENT_BALANCE`), card visits for any visit-debiting endpoint (`ERR_CARD_VISITS_EXHAUSTED`), and family-share authorisation on the access-events and shared-card group-booking surfaces (`ERR_FAMILY_SHARE_NOT_AUTHORIZED`) — round out the business-rule layer. Recharge-amount validity (`ERR_RECHARGE_AMOUNT_INVALID`), payout-cycle close window (`ERR_PAYOUT_CYCLE_OPEN`), and the OCC `version` check (`ERR_VERSION_CONFLICT`) come last. Any field-level validation failure not otherwise classified (type, range, enum) returns `ERR_VALIDATION`.

Every override-style action — operator-initiated card adjustment, commission adjustment, card refund, freeze override, and commission reversal — writes an `AuditLogEntry` with the corresponding `action` value, capturing `actor_role`, `actor_id`, a polymorphic `target_entity`, a structured `payload` describing the before/after diff, and `created_at`. The audit-log list capability accepts optional `action` and `actor_id` filter query parameters as well as pagination.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that mutate or read an existing resource return HTTP 200. Authorisation is enforced exactly as listed below; any role not listed is rejected with `ERR_FORBIDDEN`. The request and response bodies for each endpoint are reconstructed from the workflow narrative in §3 — this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/card-types` | Create a card type configuration. | `PlatformAdmin` |
| GET | `/card-types` | List card types (filter by `category`, `status`). | `PlatformAdmin`, `StaffOps`, `Member`, `Trainer` |
| PATCH | `/card-types/{id}` | Retire a card type or edit pricing for future issuance. | `PlatformAdmin` |
| POST | `/members` | Register a member. | `PlatformAdmin`, `StaffOps` |
| GET | `/members/{id}` | Get member with computed wallet balances. | `PlatformAdmin`, `StaffOps`, `Member` |
| PATCH | `/members/{id}` | Update notification channels, auto-renew, or family group. | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/members/{id}/wallet/recharge` | Recharge stored value with tiered bonus. | `Member`, `StaffOps`, `PlatformAdmin` |
| GET | `/members/{id}/wallet/quote` | Forward-looking quote of bonus-first consumption. | `Member`, `StaffOps` |
| GET | `/members/{id}/wallet/transactions` | List wallet ledger entries (filter by `kind`, `bucket`). | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/cards` | Issue a card in `PENDING` status. | `PlatformAdmin`, `StaffOps` |
| GET | `/cards/{id}` | Get a card with computed expiry and remaining visits. | `PlatformAdmin`, `StaffOps`, `Member` |
| GET | `/cards` | List cards (filter by `holder_member_id`, `status`). | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/cards/{id}/activate` | Activate a `PENDING` card. | `PlatformAdmin`, `StaffOps` |
| POST | `/cards/{id}/freeze` | Request and auto-approve a freeze episode. | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/cards/{id}/unfreeze` | End an in-progress freeze early. | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/cards/{id}/refund` | Refund a card; cascades commission reversal. | `PlatformAdmin`, `StaffOps` |
| GET | `/cards/{id}/refund-preview` | Show forward-looking and chronological remaining-value variants. | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/cards/{id}/transfer` | Transfer a card to a different member; debits the transfer fee. | `PlatformAdmin`, `StaffOps` |
| GET | `/cards/{id}/renewal-quote` | Quote renewal price with applicable discount tier. | `PlatformAdmin`, `StaffOps`, `Member` |
| POST | `/cards/{id}/send-reminder` | Manually dispatch a renewal reminder. | `PlatformAdmin`, `StaffOps` |
| POST | `/trainers` | Create a trainer profile. | `PlatformAdmin` |
| GET | `/trainers/{id}` | Get a trainer. | `PlatformAdmin`, `StaffOps`, `Member`, `Trainer` |
| PATCH | `/trainers/{id}` | Update specialties, status, or commission rates. | `PlatformAdmin` |
| POST | `/trainer-slots` | Publish a trainer slot. | `PlatformAdmin`, `StaffOps`, `Trainer` |
| GET | `/trainer-slots` | List slots (filter by `trainer_id`, `specialty_code`, `status`, `starts_after`, `starts_before`). | `PlatformAdmin`, `StaffOps`, `Member`, `Trainer` |
| POST | `/pt-bookings` | Book a single PT session or a package session. | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/pt-bookings/{id}/cancel` | Cancel a confirmed PT booking. | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/pt-bookings/{id}/complete` | Mark a PT booking completed; accrues commission. | `Trainer`, `StaffOps`, `PlatformAdmin` |
| POST | `/pt-bookings/{id}/no-show` | Mark a PT booking no-show manually. | `StaffOps`, `PlatformAdmin` |
| POST | `/pt-packages` | Sell a PT package; commission accrues. | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/pt-packages/{id}/refund` | Refund unused package balance; reverses commission proportionally. | `StaffOps`, `PlatformAdmin` |
| POST | `/group-classes` | Schedule a group class (one-off or recurring). | `PlatformAdmin`, `StaffOps` |
| PATCH | `/group-classes/{id}` | Adjust `capacity` or record substitute trainer. | `PlatformAdmin`, `StaffOps` |
| POST | `/group-classes/{id}/cancel` | Cancel a class; refunds attendees, notifies IM. | `PlatformAdmin`, `StaffOps` |
| POST | `/group-bookings` | Book a group class (auto-waitlist when at capacity). | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/group-bookings/{id}/cancel` | Cancel a group booking; promotes waitlist head. | `Member`, `StaffOps`, `PlatformAdmin` |
| POST | `/group-bookings/{id}/check-in` | Check in at class start. | `StaffOps`, `PlatformAdmin` |
| POST | `/access-events` | Record a turnstile entry; debits a visit on the card. | `StaffOps`, `PlatformAdmin` |
| POST | `/payouts` | Open a payout cycle. | `PlatformAdmin` |
| POST | `/payouts/{id}/close` | Close a payout cycle; recompute trainer tier; append tier bonus. | `PlatformAdmin` |
| GET | `/trainers/{id}/commissions` | List a trainer's commission records (filter by `payout_cycle_id`, `kind`). | `PlatformAdmin`, `Trainer` |
| POST | `/_clock/advance` | Advance the logical clock to a supplied `to` instant; triggers time-gated transitions. | `system` |
| POST | `/_sweep/run` | Run the renewal-reminder sweep over all `ACTIVE` cards. | `system` |
| POST | `/_events/emit` | Inject an external `event_type` with `payload`. | `system` |
| GET | `/audit-log` | List audit log entries (filter by `action`, `actor_id`). | `PlatformAdmin` |

## 5. Error Code Catalogue

The trigger conditions for each error code are described in the relevant narrative in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_CARD_TYPE_RETIRED` | 409 |
| `ERR_TRAINER_INACTIVE` | 409 |
| `ERR_SPECIALTY_MISMATCH` | 422 |
| `ERR_SLOT_ALREADY_RESERVED` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_CLASS_OVERLAP` | 409 |
| `ERR_CAPACITY_REACHED` | 409 |
| `ERR_CANCEL_WINDOW_EXPIRED` | 409 |
| `ERR_REFUND_NOT_ELIGIBLE` | 422 |
| `ERR_REFUND_FROZEN_CARD_BLOCKED` | 422 |
| `ERR_TRANSFER_NOT_ELIGIBLE` | 422 |
| `ERR_TRANSFER_INELIGIBLE_RECIPIENT` | 422 |
| `ERR_FREEZE_BUDGET_EXHAUSTED` | 422 |
| `ERR_FREEZE_IN_PROGRESS` | 409 |
| `ERR_FREEZE_CONFLICTS_WITH_BOOKING` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 422 |
| `ERR_CARD_VISITS_EXHAUSTED` | 422 |
| `ERR_FAMILY_SHARE_NOT_AUTHORIZED` | 403 |
| `ERR_RECHARGE_AMOUNT_INVALID` | 422 |
| `ERR_PAYOUT_CYCLE_OPEN` | 409 |
| `ERR_WALLET_LEDGER_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |

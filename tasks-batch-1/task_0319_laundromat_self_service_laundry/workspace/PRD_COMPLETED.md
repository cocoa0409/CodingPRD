# Laundromat & Self-Service Laundry API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Laundromat & Self-Service Laundry platform, a back-office and customer-facing API that runs an attended self-service laundry. The system tracks a floor of washers and dryers in real time, prices and captures machine sessions (vends) paid by coin, card, or prepaid app wallet, and runs a wash-dry-fold drop-off service priced by weight. Around that core it layers a loyalty and wallet-reload program, a machine-fault refund workflow, attendant cash-drawer shifts, and a lost-and-found register.

The central tension the platform manages is money moving through many channels at once: coins landing in an attendant's drawer, prepaid wallet balances rising on reload and falling on spend, loyalty points accruing and reversing, and refunds flowing back to whichever destination is appropriate. Pricing itself is two-faced — every machine session carries a forward-looking quote computed against the store's active price book and the time-of-day surge clock, alongside the amount actually charged once free-wash credits and tender rules are applied. Because attendants reconcile their drawers at the end of each shift and managers adjudicate disputed charges after the fact, the system must keep an auditable, immediately-consistent record of every cent and every point.

The reader should treat this document as the complete contract. It describes the entities, their lifecycles, the precise arithmetic of every price and bonus, the order in which validations fire, and the role each operator plays. Nothing about the system's behavior is specified elsewhere.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as `Manager`, `Attendant`, and `Member`. A request missing either header, or carrying an `X-User-Role` value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles relate to persisted identity differently, and that difference drives ownership checks. When `X-User-Role` is `Member`, the role is entity-backed: `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's `member_id` to `X-User-ID` — a member may reload, redeem, pay, and cancel only against their own records. When `X-User-Role` is `Attendant`, `X-User-ID` is an opaque operator handle not tied to any persisted entity; the server records it where a workflow calls for it (for example as `attendant_id` on a `Shift`, `intake_attendant_id` on a `WdfOrder`, or `logged_by_id` on a `LostFoundItem`) but never compares it to any entity's `id`. Shift ownership is enforced by comparing `X-User-ID` to the shift's `attendant_id`, both being opaque strings. When `X-User-Role` is `Manager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

A member acting on a resource that is not their own — reloading another member's wallet, redeeming or paying against another member's account or order — is rejected with `ERR_FORBIDDEN`, as is an attendant attempting to reconcile or close a shift whose `attendant_id` does not equal their `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION` (HTTP 422).

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

### 2.4. Common Resource Properties and Identity

Almost every resource in the system carries four system-managed fields. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on each mutation; it is the basis for optimistic concurrency control described in §2.8.

One entity is the exception. The loyalty ledger entry is an append-only audit record: each `LoyaltyLedgerEntry` carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified.

### 2.5. Time, the Capture Clock, and Cycle Completion

The system runs against a server-held logical capture clock expressed in UTC. All time-sensitive computations — whether a vend falls inside the surge window, when a running cycle ends, and how long a lost item has been held — read this clock rather than wall-clock time. A `Manager`-only test-driving capability sets the clock to an absolute instant supplied as `to_iso8601`. Advancing the clock is also a cycle driver: any machine that is `RUNNING` whose `cycle_ends_at` is at or before the new clock value is completed automatically — the machine moves to `DONE`, its occupying vend's `cycle_status` moves from `RUNNING` to `COMPLETED`, and the machine's `lifetime_vend_count` increments by one.

### 2.6. Monetary Values, Points, and Precision

All monetary amounts in the system are integer counts of cents — there are no fractional cents and no floating-point money. Bonus rates, surge multipliers, and loyalty thresholds are likewise integers. Where a calculation multiplies by a basis-points rate, the basis-points denominator is 10000, so a multiplier of 10000 means exactly one times the base. Two rounding conventions appear and they are not interchangeable: the surge multiplication on a vend quote and the rush surcharge on a wash-dry-fold order are rounded half up to the nearest whole cent, whereas loyalty-point counts and reload bonuses are floored (truncated toward zero) to a whole number. Each calculation in §3 states which convention it uses; apply the stated one exactly.

Wallet balances, loyalty points, free-wash credits, and lifetime spend are never negative. Where a reversal would drive a balance below zero, it is floored at zero.

### 2.7. Hierarchical Consistency and Cascading Effects

A single operation in this system frequently mutates several peer entities at once, and every such cascade must complete as part of the triggering request. Capturing a vend, for instance, simultaneously advances a machine's operational state, debits a wallet, writes a loyalty ledger entry, and may stamp a shift. Approving a refund reverses a charge across a vend, a wallet, a member's loyalty balance, a member's lifetime spend, and possibly a shift drawer. Each entity touched by a cascade has its own `updated_at` refreshed and, where it carries a `version`, its `version` incremented. The precise membership of each cascade is specified alongside the workflow that triggers it in §3; the governing rule here is that none of these secondary effects is optional — when the triggering condition holds, every listed effect occurs.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to present the version it last observed of the resource it is about to mutate, so that a writer working from a stale view is rejected rather than silently overwriting a change it never saw.

Capturing a vend against a machine requires the request to carry `expected_machine_version`, holding the client's last observed `version` of the target `Machine`. If that value does not match the machine's current `version` — because another writer has captured a vend, changed the machine's status, or otherwise advanced it since the client last read it — the capture is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before vending.

Approving a refund claim requires the request to carry `expected_claim_version`, holding the client's last observed `version` of the target `RefundClaim`. If that value does not match the claim's current `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a manager from re-approving a claim that another adjudication has already moved. No other endpoint takes a version field, and endpoints that do not appear here perform no version check.

### 2.9. Nested Resource Retrieval and Existence Ordering

Several paths name more than one resource — a machine and the vends beneath it, a member and that member's reloads or loyalty ledger. When a path or body references resources by id, the system validates their existence left to right, in the order they appear, and rejects the first missing one with `ERR_NOT_FOUND` (HTTP 404). This applies uniformly: any referenced machine, member, plan, vend, shift, order, claim, or item that does not exist halts the request at that point before any business rule is evaluated.

### 2.10. Validation Order

When several checks could apply to one request, they fire in a fixed priority order, and the first failure determines the error returned. Authentication comes first: the headers must be present and the role known, or `ERR_UNAUTHENTICATED` is returned. Authorization is second: the role must be permitted to call the endpoint, or `ERR_FORBIDDEN`. Existence is third: every referenced resource must exist, or `ERR_NOT_FOUND`. Request well-formedness is fourth: required fields present, enum values in range, and integers within their declared bounds, or `ERR_INVALID_REQUEST` (HTTP 422). Ownership is fifth: an entity-backed member acting on a self-owned resource must own it, and an attendant acting on a shift must own it, or `ERR_FORBIDDEN`. State validity is sixth: the target resource must be in a state that admits the requested transition, or `ERR_INVALID_STATE` (HTTP 409). Optimistic-concurrency is seventh: where a version field is required it must match, or `ERR_STALE_VERSION` (HTTP 412). Only after all of these do the domain-specific business rules in the remainder of this document apply, in the priority each one states.

## 3. Business Logic & Workflows

### 3.1. The Price Book: Pricing Plans and Activation

Everything the store charges flows from a single source of truth, the **Pricing Plan**, which a `Manager` authors and the system holds at most one of in the `ACTIVE` state at any moment. A manager creates a plan in `DRAFT` by supplying a human `label` and the full schedule of rates. The washer base price is `wash_base_cents` and must be greater than zero. Dryer pricing is sold in time-blocks: `dry_base_cents_per_block` (greater than zero) is the price of one block, and `dry_block_minutes` is how many minutes of dryer run one block buys, defaulting to 8 and required to be greater than zero.

Surge pricing is governed by four fields. The `surge_multiplier_bps` is a basis-points multiplier applied during the surge window, defaulting to 10000 (one times) and never below 10000. The window itself runs from `surge_start_hour_utc` (an hour 0 through 23, inclusive, default 16) up to but not including `surge_end_hour_utc` (an hour 0 through 23, default 20); the window is the half-open interval from the start hour up to the end hour. Wash-dry-fold pricing uses `wdf_rate_cents_per_lb` (the per-pound rate, greater than zero) with a charge floor of `wdf_minimum_cents` (default 1500 cents, i.e. fifteen dollars, and never below zero).

The reload bonus schedule has two tiers. The tier-1 threshold `reload_bonus_tier1_min_cents` (default 2000 cents, i.e. twenty dollars, never below zero) is the reload amount at or above which the tier-1 rate `reload_bonus_tier1_bps` (default 500 basis points, i.e. five percent, never below zero) applies. The tier-2 threshold `reload_bonus_tier2_min_cents` (default 5000 cents, i.e. fifty dollars) must be at least the tier-1 threshold, and the tier-2 rate `reload_bonus_tier2_bps` (default 1000 basis points, i.e. ten percent) must be at least the tier-1 rate. Loyalty accrual is set by `loyalty_cents_per_point` — the cents of net app-wallet vend spend that earn one point, default 100 cents, greater than zero — and redemption by `loyalty_redeem_threshold_points`, the points needed for one free-wash credit, default 50, greater than zero. The plan's `status` is one of `DRAFT`, `ACTIVE`, or `RETIRED`, starting at `DRAFT`.

Activation is the pivotal transition. A manager activating a plan moves it from `DRAFT` to `ACTIVE`, but only if the plan is currently `DRAFT`, its `surge_end_hour_utc` is strictly greater than its `surge_start_hour_utc`, and its `reload_bonus_tier2_min_cents` is at least its `reload_bonus_tier1_min_cents`; a plan failing the state precondition is rejected with `ERR_INVALID_STATE`. Activation carries a cascade: any other plan currently in `ACTIVE` is moved to `RETIRED` at the same moment, since only one plan may be active, and from then on every vend, reload, and wash-dry-fold price reads from the newly activated plan. A manager may also retire an `ACTIVE` plan directly, moving it `ACTIVE → RETIRED`; this requires the plan to be `ACTIVE`. Retired plans are no longer consulted for new pricing, but historical transactions keep the amounts captured against them. Whenever a vend, reload, or wash-dry-fold intake needs to price something and no plan is `ACTIVE`, that request is rejected with `ERR_NO_ACTIVE_PLAN` (HTTP 409).

### 3.2. Machines: Real-Time Status and the Operational Cycle

A `Manager` registers each **Machine** with a floor `label`, a `machine_type` of either `WASHER` or `DRYER`, a drum `capacity_lb` in pounds (greater than zero), and, for washers, a nominal `cycle_minutes` length (default 30, greater than zero; dryers derive their run length from purchased blocks instead). A new machine starts `IDLE` with `lifetime_vend_count` and `fault_count` both at zero. Its operational `status` is one of `IDLE`, `RUNNING`, `DONE`, `FAULT`, or `OUT_OF_SERVICE`, and it tracks the vend currently occupying it in `current_vend_id` (a reference to the live vend, null when the machine is idle) and the moment its running cycle finishes in `cycle_ends_at` (null unless running).

The machine moves through a repeating cycle. A captured vend takes an `IDLE` machine to `RUNNING`. When the cycle completes — either because the capture clock has reached `cycle_ends_at` during a clock advance, or because an attendant explicitly marks the running machine's cycle complete — the machine moves `RUNNING → DONE`, the occupying vend's `cycle_status` moves from `RUNNING` to `COMPLETED`, and `lifetime_vend_count` increments by one. An attendant marking completion requires the machine to be `RUNNING`; clock-driven completion additionally requires that the current capture clock be at or after the machine's `cycle_ends_at`. Clearing a `DONE` machine returns it `DONE → IDLE`, setting `current_vend_id` and `cycle_ends_at` back to null; either a member or an attendant may clear it, and the machine must be `DONE`.

Faults branch off the cycle. An attendant may declare a fault on a machine that is `RUNNING` or `DONE`, moving it to `FAULT`; this increments `fault_count` by one, and if the occupying vend was still `RUNNING` its `cycle_status` moves to `ABORTED`. The `current_vend_id` is deliberately retained on the faulted machine so a refund claim can be linked to it. Clearing a `FAULT` machine also returns it `FAULT → IDLE` and nulls `current_vend_id` and `cycle_ends_at`, but only an attendant may do so, the machine must be `FAULT`, and no refund claim filed against the retained `current_vend_id` may still be in `SUBMITTED` status — a clear attempted while such a claim is open is rejected with `ERR_INVALID_STATE`. Separately, a manager may take an `IDLE` machine `OUT_OF_SERVICE` and later return it `OUT_OF_SERVICE → IDLE`; each requires the machine to be in the respective starting state.

### 3.3. Capturing a Vend: Pricing, Tender, and the Two Variants

Capturing a vend is the busiest operation in the system, and it produces two distinct money figures. A member or an attendant captures a vend against a machine by supplying the `payment_method` (`COIN`, `CARD`, or `APP_WALLET`) and `expected_machine_version`, optionally a `member_id`, `dry_blocks`, `used_free_credit`, and `card_token`. The capture is allowed only against an `IDLE` machine; if the machine is `RUNNING`, `DONE`, `FAULT`, or `OUT_OF_SERVICE` the vend is rejected with `ERR_MACHINE_UNAVAILABLE` (HTTP 409). The new vend is created with `payment_status` of `CAPTURED` and `cycle_status` of `RUNNING`, takes the machine from `IDLE` to `RUNNING`, sets the machine's `current_vend_id` to the new vend, sets `cycle_ends_at` to the capture clock plus the purchased minutes, and increments the machine's `version` by one. A washer's purchased minutes are its `cycle_minutes`; a dryer's are its `dry_blocks` multiplied by the active plan's `dry_block_minutes`. The vend records its own `cycle_ends_at` to match.

The **quote** is the forward-looking figure, computed first and stored as `quoted_amount_cents`. The base depends on machine type: for a `WASHER` the base is the active plan's `wash_base_cents` and `dry_blocks` is ignored (treated as zero); for a `DRYER` the base is the plan's `dry_base_cents_per_block` multiplied by the requested `dry_blocks`. A dryer vend must request at least one block — a `DRYER` capture with `dry_blocks` less than 1 is rejected with `ERR_DRY_BLOCKS_REQUIRED` (HTTP 422). The capture clock's hour is then tested against the surge window: the vend is in surge when that hour is at or after `surge_start_hour_utc` and strictly before `surge_end_hour_utc`, and the boolean `surge_applied` records the outcome. When in surge, the quote is the base multiplied by `surge_multiplier_bps`, divided by 10000, and rounded half up to a whole cent; outside surge the multiplier is effectively 10000, so the quote equals the base.

The **charged amount** is the chronological figure, computed after the quote in a pinned order and stored as `charged_amount_cents`. It starts equal to the quote. Then the free-wash credit is considered: if `used_free_credit` is set and the tender is `APP_WALLET` and the machine is a `WASHER` and the member holds at least one `free_wash_credits`, the charged amount is forced to zero and one free-wash credit is consumed. Free credit only ever zeroes a washer vend paid by app wallet; it never applies to a dryer or to coin or card tenders. If the free-credit conditions are not met, the charged amount stays equal to the quote. Loyalty accrual is then computed, but only for `APP_WALLET` vends and only on the net amount actually charged: `loyalty_points_earned` is the charged amount divided by the active plan's `loyalty_cents_per_point`, floored to a whole number. Coin and card vends, and any vend whose charged amount came out to zero via free credit, earn zero points.

Tender-specific settlement follows. For an `APP_WALLET` vend a `member_id` must be supplied so the acting member's wallet can be settled — an `APP_WALLET` capture with no `member_id` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The named member's wallet must then be active and funded: the member must be `ACTIVE` (a `SUSPENDED` or `CLOSED` member is rejected with `ERR_MEMBER_NOT_ACTIVE`, HTTP 409) and `wallet_cents` must be at least the charged amount (otherwise `ERR_INSUFFICIENT_WALLET`, HTTP 409). On success `wallet_cents` is debited by the charged amount, `lifetime_spend_cents` rises by the charged amount, and the loyalty points earned are credited to `loyalty_points` with a matching `ACCRUAL` entry written to the member's loyalty ledger. If `used_free_credit` was requested but the conditions for it do not hold — the member has no `free_wash_credits`, or the tender is not `APP_WALLET`, or the machine is not a `WASHER` — the vend is rejected with `ERR_NO_FREE_CREDIT` (HTTP 409). For a `COIN` vend captured by an attendant who has an `OPEN` shift, the vend's `shift_id` is stamped with that shift (the `OPEN` shift whose `attendant_id` equals the attendant's `X-User-ID`) and that shift's `coin_collected_cents` is recomputed; coin and card vends do not touch wallet, loyalty, or lifetime spend. A member-captured vend and any non-coin vend leave `shift_id` null.

### 3.4. The Member Wallet: Reloads, Bonuses, and Loyalty

A **Member** is registered with a `full_name`, a `phone`, and a `card_token` used to authenticate vends and reloads; a manager or attendant may register one. A member starts `ACTIVE` with `wallet_cents`, `loyalty_points`, `free_wash_credits`, and `lifetime_spend_cents` all at zero, and a `status` of `ACTIVE`, `SUSPENDED`, or `CLOSED`. The `phone` must be unique among members that are not `CLOSED`; registering a member whose phone collides with an existing non-closed member is rejected with `ERR_DUPLICATE_PHONE` (HTTP 409). A manager may update a member's `status`, `full_name`, or `phone`, transitioning the member among `ACTIVE`, `SUSPENDED`, and `CLOSED`.

Reloading tops up the wallet with a tiered bonus. A member (on their own wallet) or an attendant initiates a **Reload** by supplying the `tender` (`CASH`, `CARD`, or `APP`) and the `principal_cents` paid in (greater than zero); the member must be `ACTIVE` or the reload is rejected with `ERR_MEMBER_NOT_ACTIVE`. The bonus selects a single tier — tiers do not stack, and the highest tier whose minimum the principal satisfies wins. If `principal_cents` is at least the active plan's `reload_bonus_tier2_min_cents`, the bonus rate is `reload_bonus_tier2_bps`; otherwise if it is at least `reload_bonus_tier1_min_cents`, the rate is `reload_bonus_tier1_bps`; otherwise the rate is zero. The `bonus_cents` is the principal multiplied by the chosen rate, divided by 10000, floored to a whole cent. The `credited_cents` is `principal_cents` plus `bonus_cents`, and that full credited amount is added to the member's `wallet_cents`. A reload posts immediately and finally with `status` of `POSTED` — there is no void. When the tender is `CASH` and the reload is taken by an attendant holding an `OPEN` shift (the shift whose `attendant_id` equals the attendant's `X-User-ID`), the reload's `shift_id` is stamped with that shift and the shift's `cash_reload_cents` is recomputed; non-cash tenders and member-initiated reloads leave `shift_id` null.

Loyalty points accumulate from app-wallet spend (as described in the vend workflow) and are spent through redemption. A member (on their own account) or an attendant redeems points for a free-wash credit; redemption reads the threshold from the active plan, so it requires a plan to be `ACTIVE` (else `ERR_NO_ACTIVE_PLAN`, HTTP 409) and requires the member to be `ACTIVE` (a `SUSPENDED` or `CLOSED` member is rejected with `ERR_MEMBER_NOT_ACTIVE`, HTTP 409); it also requires the member's `loyalty_points` to be at least the active plan's `loyalty_redeem_threshold_points`, otherwise the redemption is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 409). On redemption the member's `loyalty_points` is reduced by the redemption threshold, `free_wash_credits` increases by one, and a `REDEMPTION` entry is written to the member's loyalty ledger with a negative `points_delta`. Every movement of points — accrual on a vend, reversal on a refund, or redemption — is recorded as an immutable `LoyaltyLedgerEntry` carrying the `member_id`, the originating `vend_id` (null for redemptions), an `entry_type` of `ACCRUAL`, `REVERSAL`, or `REDEMPTION`, the signed `points_delta`, and the `balance_after` reflecting the member's `loyalty_points` once the delta is applied.

### 3.5. Wash-Dry-Fold: Weighted Intake to Pickup

The wash-dry-fold service is a staffed drop-off pipeline. An `Attendant` takes in a **WDF Order** by supplying the `intake_attendant_id` (their own operator handle), the net `weight_lb` in whole pounds (greater than zero), optionally a `member_id` (null for a walk-in who pays at pickup), and optionally a `rush` flag. The order starts in `DROPPED`, and if an `OPEN` shift is active at intake its `shift_id` is stamped on the order. Pricing is computed at intake and stored as `quoted_total_cents`, in this pinned order: first the raw charge is `weight_lb` multiplied by the active plan's `wdf_rate_cents_per_lb`; then the minimum floor is applied by taking the greater of that raw charge and the plan's `wdf_minimum_cents`; then, if and only if `rush` is set, a rush surcharge is added equal to the floored subtotal multiplied by 2500 basis points (twenty-five percent), divided by 10000, rounded half up to a whole cent. Because the floor is applied before rush, a light load that hits the minimum still pays its rush surcharge on the minimum, not on the smaller raw figure. With no rush, the total is simply the floored subtotal.

The order then advances through the floor. An attendant starts washing a `DROPPED` order, moving it `DROPPED → WASHING`, then marks a `WASHING` order ready, moving it `WASHING → READY`. Settlement happens at pickup: a member or an attendant pays a `READY` order, supplying the `pay_method` (`APP_WALLET`, `CARD`, or `CASH`), which moves it `READY → PAID` and sets `paid_amount_cents` (equal to `quoted_total_cents`). When the pay method is `APP_WALLET`, the order must name a member (an `APP_WALLET` payment on a walk-in order that names no member is rejected with `ERR_INVALID_STATE`, HTTP 409), that member must be `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`), and the member's `wallet_cents` must be at least `paid_amount_cents` (else `ERR_INSUFFICIENT_WALLET`); on success the wallet is debited by `paid_amount_cents`. A cash payment at pickup affects no drawer field — wash-dry-fold cash is recorded as paid but is not coin-collected. At any point before payment — while the order is `DROPPED`, `WASHING`, or `READY`, but never once `PAID` — a member or attendant may cancel it, moving it to `CANCELLED` with no charge collected. Both `PAID` and `CANCELLED` are terminal.

### 3.6. Attendant Shifts and Drawer Reconciliation

Cash handled on the floor is tracked through an attendant's **Shift**. An attendant opens a shift by supplying their own `attendant_id` and the `opening_float_cents` counted into the drawer (never negative); the shift starts `OPEN` and becomes the active shift for that attendant's coin vends and cash reloads. An attendant may hold only one open shift at a time — opening a second while one is already `OPEN` for the same attendant is rejected with `ERR_SHIFT_ALREADY_OPEN` (HTTP 409). Throughout the shift the system maintains three running aggregates: `coin_collected_cents` is the sum of `charged_amount_cents` over the shift's `COIN` vends that remain `CAPTURED`; `cash_reload_cents` is the sum of `principal_cents` over the shift's `CASH` reloads that are `POSTED`; and `cash_refund_paid_cents` is the sum of `approved_cents` over approved cash-destination refunds whose underlying vend belongs to this shift.

When the attendant is ready to close out, they begin reconciliation — permitted only by the shift's owner (the attendant whose `X-User-ID` equals the shift's `attendant_id`) on an `OPEN` shift — which moves it `OPEN → RECONCILING`, stops it being the active shift for new coin vends and cash reloads, and freezes the `expected_drawer_cents`. That expected figure is the `opening_float_cents` plus `coin_collected_cents` plus `cash_reload_cents` minus `cash_refund_paid_cents`. Note the deliberate asymmetry in how refunds touch the drawer: a coin vend that is later refunded is not removed from `coin_collected_cents`, because the cash genuinely sat in the drawer; instead the cash refund payout is subtracted separately through `cash_refund_paid_cents`. Closing the shift requires it to be `RECONCILING` and the attendant to submit the physically `counted_drawer_cents`; this moves it `RECONCILING → CLOSED` and computes the signed `variance_cents` as the counted figure minus the expected figure, which may be non-zero when the drawer does not balance.

### 3.7. Faults, Refunds, and Loyalty Reversal

When a charge is disputed, a member or an attendant files a **Refund Claim** against a vend by supplying the `vend_id`, the `reported_by_id` of whoever is filing (a member's id, or an attendant operator handle), the `reason` (`MACHINE_FAULT`, `NO_CYCLE`, or `DOUBLE_CHARGE`), and optionally the `refund_destination` (`WALLET`, `CASH`, or `ORIGINAL_TENDER`, defaulting to `WALLET`). The claim is created in `SUBMITTED`, and its `requested_cents` is derived from the referenced vend: if the vend's `charged_amount_cents` is zero — a free-credit vend where nothing was actually charged — the requested amount is zero, since there is nothing to refund; otherwise the requested amount equals the vend's `charged_amount_cents`. Filing itself performs no check on the vend's `payment_status`: a claim may be filed and is created in `SUBMITTED` even against a vend whose `payment_status` is already `REFUNDED`. The `ERR_ALREADY_REFUNDED` (HTTP 409) guard is enforced not at filing but at adjudication — such a claim is created successfully and is rejected only when its approval is attempted against the already-refunded vend (see approval below).

A `Manager` adjudicates each claim, and the two branches diverge sharply. Denying a `SUBMITTED` claim moves it `SUBMITTED → DENIED`, leaves `approved_cents` at zero, and changes nothing about the vend. Approving a `SUBMITTED` claim moves it `SUBMITTED → APPROVED` and carries the system's largest cascade. Approval requires the claim to be `SUBMITTED`, the referenced vend's `payment_status` to still be `CAPTURED` and not already `REFUNDED` (else `ERR_ALREADY_REFUNDED`), and the request to carry an `expected_claim_version` matching the claim's current `version` (else `ERR_STALE_VERSION`). On approval the `approved_cents` is set to the `requested_cents`, the claim's `version` increments by one, and the vend's `payment_status` moves `CAPTURED → REFUNDED`. The cascade then settles the money and the points: if the vend was paid by `APP_WALLET` and the refund destination is `WALLET`, the member's `wallet_cents` is credited the approved amount; a `REVERSAL` loyalty ledger entry of negative the vend's `loyalty_points_earned` is written and the member's `loyalty_points` is reduced by that many points, floored at zero; the member's `lifetime_spend_cents` is reduced by the vend's `charged_amount_cents`, floored at zero; and if the refund destination is `CASH` and the referenced vend's `shift_id` points to an `OPEN` shift, that shift's `cash_refund_paid_cents` increases by the approved amount. On approval `approved_cents` equals `requested_cents` exactly — refunds are full, never partial. Recall from §3.2 that a faulted machine retains its `current_vend_id` precisely so a claim can be linked to it, and cannot be cleared back to `IDLE` while a claim against that vend is still `SUBMITTED`.

### 3.8. Lost and Found

Found property is logged and resolved through the **Lost & Found** register. An attendant logs a found item by supplying their `logged_by_id`, a free-text `description`, and optionally the `machine_id` where it was found (null if found on the floor); the item starts `LOGGED` and its `found_at` is set to the current capture clock. An attendant may mark a `LOGGED` item claimed by supplying the `claimed_by_id` of the member claiming it, which moves it `LOGGED → CLAIMED` and records that member. Alternatively an attendant may dispose of a `LOGGED` item, moving it `LOGGED → DISPOSED`, but only once it has been held long enough: disposal is permitted only when the difference between the current capture clock and the item's `found_at` is at least the disposal-hold window of 24 hours, and an attempt before that window elapses is rejected with `ERR_DISPOSAL_HOLD_ACTIVE` (HTTP 409). Both `CLAIMED` and `DISPOSED` are terminal.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including state transitions and reconciliation — return `200 OK`. All list and get operations return `200 OK`. List endpoints accept the `limit` and `offset` query parameters described in §2.3 in addition to any filters noted in the description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pricing-plans` | Create a DRAFT pricing plan | Manager |
| GET | `/pricing-plans` | List pricing plans (filter by `status`) | Manager, Attendant |
| GET | `/pricing-plans/{plan_id}` | Get a pricing plan | Manager, Attendant |
| POST | `/pricing-plans/{plan_id}/activate` | Activate a DRAFT plan; retire the prior ACTIVE plan | Manager |
| POST | `/pricing-plans/{plan_id}/retire` | Retire an ACTIVE plan | Manager |
| POST | `/machines` | Register a machine | Manager |
| GET | `/machines` | List machines (filter by `status`, `machine_type`, `current_vend_id`) | Manager, Attendant, Member |
| GET | `/machines/{machine_id}` | Get a machine (real-time status) | Manager, Attendant, Member |
| GET | `/machines/{machine_id}/vends` | List vend transactions for a machine | Manager, Attendant, Member |
| POST | `/machines/{machine_id}/vends` | Capture a vend on an IDLE machine | Member, Attendant |
| POST | `/machines/{machine_id}/complete-cycle` | Mark a RUNNING machine's cycle complete | Attendant |
| POST | `/machines/{machine_id}/clear` | Clear a DONE or FAULT machine back to IDLE | Member, Attendant |
| POST | `/machines/{machine_id}/declare-fault` | Declare a machine faulted | Attendant |
| POST | `/machines/{machine_id}/take-offline` | Take an IDLE machine OUT_OF_SERVICE | Manager |
| POST | `/machines/{machine_id}/return-to-service` | Return an OUT_OF_SERVICE machine to IDLE | Manager |
| GET | `/vends` | List/filter vends (by `machine_id`, `member_id`, `shift_id`, `payment_status`, `cycle_status`) | Manager, Attendant, Member |
| GET | `/vends/{vend_id}` | Get a single vend transaction | Manager, Attendant, Member |
| POST | `/members` | Register a member | Manager, Attendant |
| GET | `/members` | List members (filter by `status`, `phone`) | Manager, Attendant |
| GET | `/members/{member_id}` | Get a member (wallet/points balances) | Manager, Attendant, Member |
| PATCH | `/members/{member_id}` | Update member status / name / phone | Manager |
| POST | `/members/{member_id}/reloads` | Reload a member wallet with tiered bonus | Member, Attendant |
| GET | `/members/{member_id}/reloads` | List a member's reloads | Manager, Attendant, Member |
| GET | `/members/{member_id}/vends` | List a member's vends | Manager, Attendant, Member |
| GET | `/members/{member_id}/loyalty-ledger` | List a member's loyalty ledger | Manager, Attendant, Member |
| POST | `/members/{member_id}/redeem` | Redeem loyalty points for a free-wash credit | Member, Attendant |
| GET | `/reloads` | List/filter reloads (by `member_id`, `shift_id`, `tender`, `status`) | Manager, Attendant, Member |
| GET | `/reloads/{reload_id}` | Get a single reload transaction | Manager, Attendant, Member |
| GET | `/loyalty-ledger` | List/filter loyalty ledger (by `member_id`, `vend_id`, `entry_type`) | Manager, Attendant, Member |
| GET | `/loyalty-ledger/{entry_id}` | Get a single loyalty ledger entry | Manager, Attendant, Member |
| POST | `/shifts` | Open an attendant shift (cash drawer) | Attendant |
| GET | `/shifts` | List shifts (filter by `status`, `attendant_id`) | Manager, Attendant |
| GET | `/shifts/{shift_id}` | Get a shift (drawer totals) | Manager, Attendant |
| POST | `/shifts/{shift_id}/begin-reconcile` | Move an OPEN shift to RECONCILING; freeze expected drawer | Attendant |
| POST | `/shifts/{shift_id}/close` | Close a RECONCILING shift with counted drawer; compute variance | Attendant |
| POST | `/wdf-orders` | Intake a wash-dry-fold drop-off priced by weight | Attendant |
| GET | `/wdf-orders` | List WDF orders (filter by `status`, `member_id`, `intake_attendant_id`, `shift_id`) | Manager, Attendant, Member |
| GET | `/wdf-orders/{order_id}` | Get a WDF order | Manager, Attendant, Member |
| POST | `/wdf-orders/{order_id}/start` | Begin washing a dropped order | Attendant |
| POST | `/wdf-orders/{order_id}/ready` | Mark a washing order ready for pickup | Attendant |
| POST | `/wdf-orders/{order_id}/pay` | Settle a READY order at pickup | Member, Attendant |
| POST | `/wdf-orders/{order_id}/cancel` | Cancel a non-paid order | Member, Attendant |
| POST | `/refund-claims` | File a refund claim against a vend | Member, Attendant |
| GET | `/refund-claims` | List refund claims (filter by `status`, `vend_id`, `reported_by_id`) | Manager, Attendant, Member |
| GET | `/refund-claims/{claim_id}` | Get a refund claim | Manager, Attendant, Member |
| POST | `/refund-claims/{claim_id}/approve` | Approve a refund claim (cascade refund) | Manager |
| POST | `/refund-claims/{claim_id}/deny` | Deny a refund claim | Manager |
| POST | `/lost-found` | Log a found item | Attendant |
| GET | `/lost-found` | List lost-and-found items (filter by `status`, `machine_id`, `logged_by_id`, `claimed_by_id`) | Manager, Attendant, Member |
| GET | `/lost-found/{item_id}` | Get a lost-and-found item | Manager, Attendant, Member |
| POST | `/lost-found/{item_id}/claim` | Mark an item claimed by a member | Attendant |
| POST | `/lost-found/{item_id}/dispose` | Dispose an item after the hold window | Attendant |
| POST | `/_clock/advance` | Test-driving: set the capture clock; complete due cycles | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NO_ACTIVE_PLAN` | 409 Conflict |
| `ERR_MACHINE_UNAVAILABLE` | 409 Conflict |
| `ERR_DRY_BLOCKS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_FREE_CREDIT` | 409 Conflict |
| `ERR_INSUFFICIENT_WALLET` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 409 Conflict |
| `ERR_ALREADY_REFUNDED` | 409 Conflict |
| `ERR_DISPOSAL_HOLD_ACTIVE` | 409 Conflict |
| `ERR_SHIFT_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_PHONE` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |

# Cattle Feedlot Closeout API — Product Requirements Document

## 1. Introduction

A Texas Panhandle feedyard operates on thin margins and hard deadlines: cattle arrive by the truckload, are placed in pens, fed a step-up ration program, doctored when they get sick, hedged against the futures market, and finally sold to a packer on a carcass grid. Between arrival and settlement the yard accumulates feed, yardage, health, and death-loss costs against every lot, and the owner of the cattle — a custom-feeding customer — expects a final invoice that reconciles every one of those charges to the penny.

This document specifies the Cattle Feedlot Closeout API, the system of record for that entire cycle. It governs pen assignment and commingling rules, ration formulation and the daily feed call driven by bunk scores, health treatments with label withdrawal periods, cost-of-gain accounting with both provisional and final variants, carcass-grid close-out with two pinned pricing formulas, per-lot hedging and risk transfer, mortality insurance claims with segregation of duties, and owner billing through final settlement.

Two design commitments shape everything that follows. First, money is pinned chronologically: a death loss is priced only from costs accrued before the loss date, and an invoice totals its lines in a fixed evaluation order, so later events never silently reprice earlier ones. Second, every aggregate on a lot — head counts, cost accumulators, provisional cost of gain — is reconciled immediately as events occur, so a reader of the API always sees the yard's current truth rather than a nightly batch approximation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/feedlot` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes seven operational roles: `FeedyardManager` (yard manager: owners, pens, lot reception, marketing, shipping, pen moves, and the logical clock), `FeedManager` (nutritionist and feed-truck dispatcher: rations, ration windows, daily feed calls), `CattleHealthTech` (cattle health crew: treatments, death losses, mortality claim filing), `RiskManager` (risk desk: hedges and close-outs), `ClaimsAdjuster` (decides and appeal-reviews mortality claims, and may pay claims they did not decide), `ClaimsTreasurer` (pays approved claims), and `BillingClerk` (front-office billing: applies invoice payments and voids open invoices). The endpoint catalogue in §4 also uses `Any` as a shorthand meaning every authenticated role may perform the operation; `Any` is not itself an assignable role. An attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For every role named above — `FeedyardManager`, `FeedManager`, `CattleHealthTech`, `RiskManager`, `ClaimsAdjuster`, `ClaimsTreasurer`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `decided_by_user_id` on an `InsuranceClaim` when a decision is written) but does not compare it to any entity's `id`. The single exception to this hands-off treatment is the segregation-of-duties check on claim payment described in §3.5, which compares the payer's `X-User-ID` against a previously recorded `decided_by_user_id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The one exception is the per-pen feed-call listing, which sorts by `call_date` ascending.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — owners, pens, lots, rations, pen assignments, ration assignments, health events, death losses, insurance claims, hedge positions, close-outs, and invoices — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T12:00:00.000Z`) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including modifications the server makes automatically as reconciliation side effects.

The feed call is the single exception to this convention. A `FeedCall` is an immutable event record and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, because a posted feed call is never modified.

### 2.5. The Logical Clock

The yard runs on a logical clock, not the wall clock. At server startup the current logical instant is exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time. A `FeedyardManager` may advance the logical clock through a test-driving capability that sets the current instant to a supplied `to_iso8601` value; the capability responds with the resulting `current_utc`.

Advancing the clock is a reconciliation event with four consequences. Every health event whose `withdrawal_end_date` is on or before the new date transitions from `WITHDRAWAL_ACTIVE` to `CLEARED`. Every ration assignment whose `end_date` has been reached transitions from `ACTIVE` to `CLOSED`. Every hedge position whose contract month has begun — that is, whose `contract_month`'s first day is on or before the new date — transitions from `OPEN` to `EXPIRED`. And every non-terminal lot has its `provisional_cog_cents_per_cwt` recomputed. Several validation rules pin date-valued inputs against this logical clock: `ship_date`, `loss_date`, `treatment_date`, and `offset_date` may not lie in the future relative to it, and a violation is an `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Money, Weights, and Rounding Discipline

All monetary amounts are integer cents unless a field's description says otherwise, and all rounding in the system is **round half up**. Per-head feed quantities are rounded half up to one decimal place (tenths of a pound); feed totals, cost shares, death-loss components, hedge results, and invoice lines are rounded half up to whole cents; cost-of-gain values and carcass-grid values are rounded half up to two decimal places (hundredths of a cent per hundredweight, and hundredths of a cent respectively). Calendar dates use the `YYYY-MM-DD` format, and date windows throughout the system are half-open: a window written as start-inclusive, end-exclusive contains its start date and does not contain its end date. Futures contract months use the `YYYY-MM` format.

### 2.7. Optimistic Concurrency on the Lot

Two creation endpoints participate in optimistic concurrency control against the lot they target, and both name the same field. A request that enters a new hedge position for a lot, and a request that opens a new close-out for a lot, must each carry `expected_lot_version` in the request body, holding the lot `version` the client last observed. If the lot's current `version` has advanced since that observation — because a death loss, a health event, a feed allocation, a hedge offset, or any other mutation bumped it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Hedge sizing depends on `head_count_current`, and opening a close-out legitimately supersedes a prior confirmed close-out, so in both cases acting on a stale view of the lot is unsafe. Endpoints not named here do not take a version field; no other request body carries an expected-version input.

### 2.8. Validation Order and Nested Resource Retrieval

Every request is screened by a fixed validation cascade, evaluated in the following priority order; the first failing check produces the response and later checks are not consulted.

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization.** The role named by `X-User-Role` must be listed among the endpoint's authorized roles (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Request shape.** Required fields must be present, enum members valid, integer and number ranges respected (head counts greater than zero, quantities greater than zero, dates well-formed `YYYY-MM-DD`), and date-valued inputs not future-dated where a rule pins them to the logical clock (`ERR_INVALID_REQUEST`).
4. **Resource existence.** Resource identifiers in the path are validated left to right, and foreign-key identifiers in the body must also exist; the first missing resource yields its specific 404 error — `ERR_OWNER_NOT_FOUND`, `ERR_PEN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_INSURANCE_CLAIM_NOT_FOUND`, `ERR_HEDGE_NOT_FOUND`, `ERR_CLOSE_OUT_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`. Because identifiers resolve left to right, a request for a child collection under a non-existent parent fails on the parent before the child is ever considered.
5. **Optimistic concurrency.** Where §2.7 applies, `expected_lot_version` must equal the lot's current `version` (`ERR_STALE_VERSION`).
6. **Segregation of duties.** On claim payment, the payer's `X-User-ID` must differ from the claim's `decided_by_user_id` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`).
7. **State guards.** Target and guarding entities must be in the states the operation requires (the family of 409 state errors, from `ERR_OWNER_SUSPENDED` through `ERR_INVOICE_NOT_OPEN`, detailed throughout §3).
8. **Withdrawal safety.** Shipping requires every health event's withdrawal to have cleared by the ship date (`ERR_WITHDRAWAL_NOT_CLEARED`).
9. **Referential business rules.** Commingling compatibility, ration step-up progression, and claim-free death-loss voids (`ERR_COMMINGLE_RULE_VIOLATION`, `ERR_STEP_UP_VIOLATION`, `ERR_VOID_BLOCKED_BY_CLAIMS`).
10. **Temporal interval rules.** Pen capacity over overlapping days, disjoint ration windows, date ordering, and feed-call date monotonicity (`ERR_PEN_CAPACITY_EXCEEDED`, `ERR_RATION_WINDOW_OVERLAP`, `ERR_INVALID_DATE_RANGE`, `ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS`).
11. **Aggregate and uniqueness constraints.** Over-assignment, duplicate codes and lot numbers, one claim per loss, insured-only claims, carcass counts, and the appeal limit (`ERR_OVER_ASSIGNMENT`, `ERR_DUPLICATE_PEN_CODE`, `ERR_DUPLICATE_LOT_NUMBER`, `ERR_CLAIM_ALREADY_EXISTS`, `ERR_DEATH_LOSS_NOT_INSURED`, `ERR_CARCASS_COUNT_MISMATCH`, `ERR_APPEAL_LIMIT_REACHED`).
12. **Money limits.** Hedge coverage, claim-against-loss ceilings, and overpayment (`ERR_HEDGE_OVER_COVERED`, `ERR_CLAIM_EXCEEDS_LOSS_VALUE`, `ERR_OVERPAYMENT`).

### 2.9. Automatic Reconciliation and Hierarchical Consistency

The server keeps derived state truthful without waiting for client requests. A pen's `current_occupancy_head` is always the sum of `head_count` over that pen's `ACTIVE` pen assignments, and the pen flips between `EMPTY` and `OCCUPIED` automatically as that sum rises above or falls to zero — whether the cause is an assignment created, an assignment ended, a lot shipped, a death-loss allocation, or a death-loss void compensation. A lot's `head_count_current`, `total_deaths`, and cost accumulators are likewise maintained as events post. Every such automatic adjustment is a mutation of the affected resource: its `updated_at` refreshes and its `version` increments, exactly as if a client had written it. Status updates to an owner or a pen are explicit client actions; a status-update request that names the status the resource already holds, or that attempts a transition the state machine does not define, is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Owners, Pens, and Receiving Cattle

Everything begins with the custom-feeding customer. A `FeedyardManager` registers an owner by supplying an `owner_name` and a `billing_email`; the new owner starts in `ACTIVE` status with an `outstanding_balance_cents` of zero. That balance is a computed figure — the sum of unpaid invoice remainders minus any direct credits — and the system guarantees it never falls below zero. An owner may later be suspended and reactivated by a status-update request carrying the desired `status` of `SUSPENDED` or `ACTIVE`; each successful toggle increments the owner's `version` by one. Suspension has teeth: while an owner is `SUSPENDED`, receiving a new lot for that owner is rejected with `ERR_OWNER_SUSPENDED` (HTTP 409). Owners can be listed and fetched individually, and each owner's lots and billed invoices are readable as nested collections, sorted by creation time ascending.

The yard itself is organized into pens. Creating a pen takes a `pen_code` — a yard-unique code such as "B-12", with duplicates rejected as `ERR_DUPLICATE_PEN_CODE` (HTTP 409) — and a `capacity_head` greater than zero. A new pen is `EMPTY` with `current_occupancy_head` zero. A `FeedyardManager` can move an `EMPTY` pen into `MAINTENANCE` and back to `EMPTY`; attempting to start maintenance on an `OCCUPIED` pen is rejected with `ERR_PEN_OCCUPIED` (HTTP 409), and any status update that names the pen's current status is an `ERR_INVALID_STATE_TRANSITION`. The transitions between `EMPTY` and `OCCUPIED` themselves are never client-driven — they follow occupancy per §2.9.

Receiving cattle creates a **lot**, the central aggregate of the system. A `FeedyardManager` receives a lot by naming its `owner_id`, a yard-unique `lot_number` (duplicates rejected with `ERR_DUPLICATE_LOT_NUMBER`), the `sex_class` (`STEER` or `HEIFER`), `head_count_in` greater than zero, `in_weight_total_lbs` greater than zero (the total pay weight received), `purchase_cost_cents` of zero or more (the total in-cost of the cattle), the `arrival_date`, and optionally `commingle_allowed`, which defaults to `false` when omitted. The lot is born `OPEN`: `head_count_current` is initialized to `head_count_in`, `head_shipped` and `total_deaths` start at zero, every cost accumulator — `total_feed_cost_cents`, `total_health_cost_cents`, `total_death_loss_cents`, `total_hedge_pnl_cents`, and `insurance_credit_pending_cents` — starts at zero, `withdrawal_clear_date` is null until the lot has health events, `out_weight_total_lbs` stays null until the lot ships, and `provisional_cog_cents_per_cwt` is null until the first clock day has passed and a projected gain exists. A single lot can be fetched with all of these computed accumulators visible.

### 3.2. Pen Placement and the Commingling Rules

Placing cattle into a pen creates a **pen assignment**. A `FeedyardManager` supplies the `pen_id`, the `lot_id`, a `head_count` greater than zero, and a `start_date` — the first occupied calendar day, inclusive. The start date may not precede the lot's `arrival_date`; a violation is an `ERR_INVALID_DATE_RANGE` (HTTP 400).

Several guards converge on this one action, applied in the §2.8 cascade order. The lot must be `OPEN` (`ERR_LOT_NOT_OPEN`). The pen must not be in `MAINTENANCE` (`ERR_PEN_IN_MAINTENANCE`). If the pen already holds other lots, the commingling rule demands three compatibilities at once: the new lot's `sex_class` must match that of the lots already present, `commingle_allowed` must be `true` on both the incoming lot and every lot sharing the pen, and all lots sharing the pen must be on an identical active ration; any breach is an `ERR_COMMINGLE_RULE_VIOLATION` (HTTP 409). Capacity is enforced day by day: the summed head over overlapping compatible assignments must not exceed the pen's `capacity_head` on any day of the overlap, or the request fails with `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 409). Finally, the lot's own books must balance: the lot's total actively-assigned head plus the new `head_count` may not exceed `head_count_current`, or the request fails with `ERR_OVER_ASSIGNMENT` (HTTP 409).

A created assignment is `ACTIVE`; the pen's `current_occupancy_head` rises by the assigned head, an empty pen flips to `OCCUPIED`, and the pen's `version` increments. The assignment's `end_date` is null while it is `ACTIVE` — and note that an assignment whose head count is reduced all the way to zero by death-loss allocation remains `ACTIVE` until it is explicitly ended or the lot ships.

Cattle move out when a `FeedyardManager` ends an assignment by supplying an `end_date`, the last-day-exclusive end of occupation. The end date must be on or after the `start_date` — a zero-day occupation, where the two dates are equal, is allowed — and anything earlier is an `ERR_INVALID_DATE_RANGE`. Ending an assignment that is no longer `ACTIVE` is rejected with `ERR_ASSIGNMENT_ALREADY_ENDED` (HTTP 409). On success the assignment transitions from `ACTIVE` to `ENDED`, its `version` increments, the pen's occupancy is recomputed, and a pen that falls to zero head flips `OCCUPIED → EMPTY`. A pen's assignments and a lot's assignments are both readable as collections sorted by creation time ascending.

### 3.3. Rations, Step-Up Windows, and the Daily Feed Call

The feed program belongs to the `FeedManager`. A **ration** is formulated with a `ration_name` (for example, "Starter-1"), a `step_level` of at least 1, and a `cost_per_ton_cents` greater than zero — the as-fed cost per ton.

A lot is put on feed through a **ration assignment** naming the `lot_id`, the `ration_id`, and an explicit half-open window with a `start_date` (inclusive) and an `end_date` (exclusive); the end must be strictly after the start, or the request fails with `ERR_INVALID_DATE_RANGE`. The lot must be `OPEN` (`ERR_LOT_NOT_OPEN`). Two rules keep the program honest. The step-up rule requires the lot's first ration assignment to be at `step_level` 1, and every subsequent assignment to be exactly one step above the lot's latest assignment's step level; jumping or repeating a step is an `ERR_STEP_UP_VIOLATION` (HTTP 409). The window rule requires a lot's ration windows to be pairwise disjoint, with zero-gap adjacency — one window's `end_date` equal to the next window's `start_date` — explicitly allowed; an overlap is an `ERR_RATION_WINDOW_OVERLAP` (HTTP 409). A ration assignment is `ACTIVE` once created and transitions `ACTIVE → CLOSED` with a version increment either when the lot ships (its `end_date` is overwritten to the ship date) or when the logical clock reaches its `end_date`.

Feeding itself is recorded as a daily **feed call** against a pen, posted by the `FeedManager` with the `pen_id` and a `call_date`. The pen must currently be `OCCUPIED` — a call against a pen with no active assignments is rejected with `ERR_PEN_NOT_OCCUPIED` (HTTP 409) — and the `call_date` must be strictly after the pen's latest existing feed call date, or the request fails with `ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS` (HTTP 409). The two remaining inputs alternate depending on the pen's history. If the pen has no prior feed call, `base_qty_lbs_per_head` is required and becomes the starting per-head quantity, and `bunk_score` must not be supplied. If the pen has at least one prior feed call, `bunk_score` — the previous-day bunk reading, one of 0, 1, 2, or 3 — is required and `base_qty_lbs_per_head` is forbidden. Supplying the wrong member of the pair for the pen's situation is an `ERR_INVALID_REQUEST`.

The quantity engine then runs. The pen's latest prior call is located by ordering its feed calls by `call_date` descending with a `created_at` descending tie-break, and its per-head quantity becomes the base. The bunk score adjusts that base by a fixed delta: a score of 0 adds three quarters of a pound per head, a score of 1 adds a quarter pound, a score of 2 leaves the quantity unchanged, and a score of 3 subtracts three quarters of a pound. The adjusted figure is clamped to a floor of 8.0 pounds and a ceiling of 30.0 pounds per head, and the result is rounded half up to the nearest tenth of a pound to become the call's `qty_lbs_per_head`. The call's `ration_id` is not an input; it is derived as the common active ration of the lots in the pen — commingled lots are required to share one ration, which is what makes the derivation unambiguous. The call's `total_qty_lbs` is the per-head quantity multiplied by the pen's `current_occupancy_head`, rounded half up to a whole pound, and its `total_cost_cents` is that total divided by two thousand (converting pounds to tons) and multiplied by the ration's `cost_per_ton_cents`, rounded half up to a whole cent.

Cost then flows to the lots by waterfall allocation. The call's `total_cost_cents` is distributed across the pen's `ACTIVE` pen assignments in proportion to each assignment's `head_count`, processing assignments in `created_at` ascending order. Every assignment except the last in that order receives a share of the total proportional to its head, rounded half up to whole cents; the last-created assignment receives the residual — the total minus the sum of the prior rounded shares. Rounding each share independently and summing is forbidden, because it can drift from the true total; the pinned order is round every non-final share first, then assign the residual. Each assignment's share is added to its lot's `total_feed_cost_cents`, and each affected lot's `version` increments. Because a feed call is immutable once posted (§2.4), these allocations are never recomputed in place. A pen's feed calls are readable sorted by `call_date` ascending, and a ration's feed calls and ration assignments are readable sorted by creation time ascending.

### 3.4. Treatments, Withdrawal, and Death Loss

The `CattleHealthTech` crew records a **health event** against a lot with the `lot_id`, a `treatment_date` that must fall within the lot's arrival date and the current logical date inclusive (a future or pre-arrival date is an `ERR_INVALID_REQUEST`), the `drug_product` name, a `withdrawal_days` label period of zero or more days, a `head_treated` count between one and the lot's `head_count_current`, and a `treatment_cost_cents` charge of zero or more that passes through to the lot. The lot must be `OPEN` (`ERR_LOT_NOT_OPEN`). The event's `withdrawal_end_date` is computed as the `treatment_date` plus `withdrawal_days` calendar days — cattle may ship on or after that date — and the event begins `WITHDRAWAL_ACTIVE`, transitioning to `CLEARED` with a version increment once the logical clock reaches the end date. Posting the event adds `treatment_cost_cents` to the lot's `total_health_cost_cents`, recomputes the lot's `withdrawal_clear_date` as the latest `withdrawal_end_date` across all of the lot's health events (null when the lot has none), recomputes the lot's provisional cost of gain, and increments the lot's `version`.

Death is recorded as a **death loss** with the `lot_id`, a `loss_date` within the same arrival-to-present bounds as treatments, a `head_count` between one and the lot's `head_count_current`, a free-text `cause` such as "RESPIRATORY", and an `insured` flag marking whether mortality insurance covers the loss. The lot must be `OPEN`. The loss is valued at its own moment and never repriced: the in-cost per head is the lot's `purchase_cost_cents` divided by `head_count_in`, rounded half up to a whole cent; the accrued basis is the lot's `total_feed_cost_cents` plus yardage accrued over the window from the arrival date up to but not including the `loss_date` (per the yardage computation of §3.7) plus the lot's `total_health_cost_cents`; the accrued per-head figure is that basis divided by the lot's `head_count_current` measured before this loss is applied, rounded half up to a whole cent; and the `loss_value_cents` is the lost `head_count` multiplied by the sum of the in-cost per head and the accrued per head. Because only costs accrued before the loss date enter the basis, costs posted later never reprice an earlier loss — this chronological pinning is deliberate.

Recording the loss cascades. The dead head are allocated to the lot's `ACTIVE` pen assignments oldest-created first — a waterfall over `created_at` ascending — and the loss's `allocations` field records each step as an entry naming the `assignment_id` and the `head_count` absorbed from it. Each allocated assignment's `head_count` is reduced accordingly; each affected pen's `current_occupancy_head` is recomputed, and a pen that falls to zero flips `OCCUPIED → EMPTY`. On the lot, `head_count_current` decreases by the lost count, `total_deaths` increases by it, `total_death_loss_cents` increases by `loss_value_cents`, the provisional cost of gain is recomputed, and the lot's `version` increments. The loss itself is `RECORDED`.

A recorded loss can be voided by a `CattleHealthTech` as a compensating action, but only while it is `RECORDED` — voiding a `VOIDED` loss, or filing a claim against one, is an `ERR_INVALID_STATE_TRANSITION` — and only while no insurance claim references it (`ERR_VOID_BLOCKED_BY_CLAIMS`, HTTP 409). Voiding restores every `allocations` entry's head to its pen assignment, recomputes each affected pen's occupancy (a pen that regains head flips `EMPTY → OCCUPIED`), adds the head back to the lot's `head_count_current`, subtracts them from `total_deaths`, subtracts `loss_value_cents` from `total_death_loss_cents`, recomputes the provisional cost of gain, and increments both the death loss's and the lot's `version`. A `VOIDED` loss is excluded from yardage computations and from `total_deaths` thereafter. Individual death losses are fetchable, and a lot's death losses and health events are readable as collections sorted by creation time ascending.

### 3.5. Mortality Claims and Segregation of Duties

When a loss is insured, the `CattleHealthTech` files an **insurance claim** naming the `death_loss_id` and a `claimed_amount_cents` greater than zero. Three guards apply: the loss's `insured` flag must be true (`ERR_DEATH_LOSS_NOT_INSURED`, HTTP 409), at most one claim may exist per death loss (`ERR_CLAIM_ALREADY_EXISTS`, HTTP 409), and the claimed amount may not exceed the loss's `loss_value_cents` (`ERR_CLAIM_EXCEEDS_LOSS_VALUE`, HTTP 422). The claim opens `UNDER_REVIEW` with an `appeal_count` of zero and a null `approved_amount_cents`.

A `ClaimsAdjuster` decides an `UNDER_REVIEW` claim — deciding from any other state is an `ERR_CLAIM_INVALID_STATE` (HTTP 409) — by submitting a `decision` of `APPROVE` or `DENY`. On approval an optional `approved_amount_cents` may be supplied between 1 and the `claimed_amount_cents` inclusive (outside that range is an `ERR_INVALID_REQUEST`); when omitted it defaults to the full `claimed_amount_cents`. Either decision stamps `decided_by_user_id` with the deciding operator's `X-User-ID` and increments the claim's `version`.

A denied claim is not necessarily finished. A `ClaimsAdjuster` may appeal a `DENIED` claim — appealing from any other state is an `ERR_CLAIM_INVALID_STATE` — provided `appeal_count` is still below one; a claim may be appealed at most once, and a second appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409). A successful appeal increments `appeal_count` and returns the claim to `UNDER_REVIEW` for a fresh decision cycle.

Payment is where duties segregate. Paying is open to both `ClaimsTreasurer` and `ClaimsAdjuster`, but the paying operator's `X-User-ID` must differ from the claim's `decided_by_user_id`; a payer who decided the claim is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The claim must be `APPROVED` (`ERR_CLAIM_INVALID_STATE` otherwise), and `PAID` is terminal. The recovery routes by timing: if the lot has an `OPEN` invoice at pay time, the owner's `outstanding_balance_cents` is reduced directly by the approved amount, or by the full balance if the approved amount exceeds it; otherwise the approved amount is added to the lot's `insurance_credit_pending_cents`, to be consumed when the next invoice is generated (§3.7). A death loss's claims are readable as a collection sorted by creation time ascending.

### 3.6. Marketing, Shipping, and the Hedge Book

When a buyer is found, a `FeedyardManager` markets the lot. Marketing requires the lot to be `OPEN` (`ERR_LOT_NOT_OPEN`) and to have at least one head on feed — a lot whose `head_count_current` is zero is rejected with `ERR_LOT_HAS_NO_HEAD` (HTTP 409). Success moves the lot `OPEN → MARKETED` and increments its `version`. If the sale falls through, the same role can fail the sale, returning the lot `MARKETED → OPEN` with another version increment; hedges, assignments, and every cost accumulator are untouched by the round trip, so the cycle back to feeding is clean. Shipping and failing a sale both require the lot to be `MARKETED`; attempting either from another state is an `ERR_LOT_NOT_MARKETED` (HTTP 409).

Shipping sends the cattle to the packer. A `FeedyardManager` supplies the `ship_date` and the `out_weight_total_lbs` — the pay weight at ship time. The ship date must fall on or after the lot's `arrival_date` and on or before the current logical date (outside that window is an `ERR_INVALID_REQUEST`), and the withdrawal gate must pass: every health event of the lot must have a `withdrawal_end_date` on or before the `ship_date`. The hold is half-open — shipping exactly on the clear date is allowed — and a violation is an `ERR_WITHDRAWAL_NOT_CLEARED` (HTTP 409). A successful ship moves the lot `MARKETED → SHIPPED`, sets `head_shipped` to the lot's `head_count_current` at that moment, stores the `out_weight_total_lbs`, ends every `ACTIVE` pen assignment of the lot with `end_date` set to the ship date (recomputing pen occupancies, so pens may flip to `EMPTY`), closes every `ACTIVE` ration assignment with its `end_date` overwritten to the ship date, recomputes the provisional cost of gain, and increments the lot's `version`.

While cattle are on feed, the `RiskManager` runs the hedge book. Entering a **hedge position** names the `lot_id`, a `contract_month` in `YYYY-MM` form, an optional `side` of `SHORT` or `LONG` that defaults to `SHORT` (the normal feedlot hedge), a `quantity_contracts` of at least one, and an `entry_price_cents_per_cwt` greater than zero. The lot must be `OPEN` (`ERR_LOT_NOT_OPEN`), and the creation is OCC-guarded per §2.7: the body must carry `expected_lot_version` matching the lot's current `version`, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412). Sizing is capped by a coverage rule. The lot's marketable hundredweight is computed by multiplying the lot's `head_count_current` by its `in_weight_total_lbs`, multiplying by three, and dividing by the product of `head_count_in` and two hundred — equivalently, the current head times the average in-weight per head times a factor of one and a half, expressed in hundredweight — rounded half up to a whole hundredweight. Each live-cattle contract covers 400 hundredweight, so the candidate position plus every `OPEN` position on the lot must not exceed that marketable figure; exceeding it is an `ERR_HEDGE_OVER_COVERED` (HTTP 422), while landing exactly on the cap is allowed. A new position is `OPEN`, its `exit_price_cents_per_cwt` and `realized_pnl_cents` are null while open, and entering it increments the lot's `version`.

A `RiskManager` offsets an `OPEN` position — offsetting from any other state is an `ERR_HEDGE_NOT_OPEN` (HTTP 409) — by supplying the `exit_price_cents_per_cwt` and an `offset_date` that may not lie in the future relative to the logical clock (`ERR_INVALID_REQUEST`). Realized P&L follows the side: for a `SHORT` position it is the entry price minus the exit price, multiplied by the 400-hundredweight contract size and the number of contracts; for a `LONG` position the price difference is reversed. The result is stored as `realized_pnl_cents` (which may be negative), added into the lot's `total_hedge_pnl_cents`, and the lot's `version` increments as the position moves `OPEN → OFFSET`. Positions left open are settled by the clock: when the logical date reaches the first day of the `contract_month`, the position moves `OPEN → EXPIRED`, settling at its entry price with `realized_pnl_cents` of zero and leaving the lot's P&L unchanged. A lot's hedge positions are readable as a collection sorted by creation time ascending.

### 3.7. Close-Out, Grid Pricing, and Final Settlement

The close-out converts a shipped lot into money. A `RiskManager` opens a **close-out** by naming the `lot_id`, a `pricing_basis` of `PER_CARCASS` or `LOT_AVERAGE` — the grid formula variant is pinned at creation and cannot change — and a `grid_base_price_cents_per_cwt` greater than zero. The lot must be `SHIPPED` or `CLOSED_OUT` (`ERR_LOT_NOT_CLOSABLE`, HTTP 409), and creation is OCC-guarded per §2.7 via `expected_lot_version`, with stale writers rejected as `ERR_STALE_VERSION`. The close-out is born `DRAFT` with a null `carcass_records`, and opening it increments the lot's `version`.

Confirmation is the heaviest transaction in the system. A `RiskManager` confirms a `DRAFT` close-out — any other state is an `ERR_CLOSE_OUT_NOT_DRAFT` (HTTP 409) — by supplying `carcass_records`, an array with one entry per shipped head; each entry carries a `hot_carcass_weight_lbs`, a `quality_grade` of `PRIME`, `CHOICE`, `SELECT`, or `STANDARD`, and a `yield_grade` of 1, 2, 3, 4, or 5. The record count must equal the lot's `head_shipped` exactly (`ERR_CARCASS_COUNT_MISMATCH`, HTTP 409), the lot must still be `SHIPPED` or `CLOSED_OUT` (`ERR_LOT_NOT_CLOSABLE`), and every hedge position of the lot must be `OFFSET` or `EXPIRED` — confirming while any hedge is `OPEN` is an `ERR_ACTIVE_HEDGES_EXIST` (HTTP 409).

Grid proceeds depend on the pinned `pricing_basis`. Each carcass earns a quality premium and a yield adjustment, both in cents per hundredweight: `PRIME` adds 1200, `CHOICE` adds 0, `SELECT` subtracts 1800, and `STANDARD` subtracts 3500; yield grade 1 adds 400, grade 2 adds 200, grade 3 adds 0, grade 4 subtracts 2000, and grade 5 subtracts 3500. Under `PER_CARCASS`, each record's value is its `hot_carcass_weight_lbs` divided by one hundred and multiplied by the base price plus that record's two adjustments, with each per-record line rounded half up to two decimal places first, and `total_grid_value_cents` is the sum of those rounded lines. Under `LOT_AVERAGE`, a weight-averaged quality adjustment is computed as the sum of each record's quality premium multiplied by its carcass weight, divided by the total carcass weight and rounded half up to two decimal places; the yield adjustment is averaged the same way; the average price is the base plus the two averaged adjustments; and `total_grid_value_cents` is the total carcass weight divided by one hundred and multiplied by that average price, rounded half up to two decimal places as a single final rounding.

The cost side draws on the lot's full cost pool at confirm time. The invoice's feed line `feed_cents` is the lot's `total_feed_cost_cents` at that moment; the yardage line is built from `yardage_head_days`, computed by walking each of the lot's pen assignments in `start_date` ascending order (creation-time tie-break), splitting each assignment's span at its `start_date`, at the `loss_date` of every non-void death loss allocated to it, and at its `end_date` or the window's end if still open — each day-segment contributing its head count (after applying death allocations with a loss date on or before the segment start, since a death reduces the count for dates from its loss date onward, not for earlier dates) multiplied by the segment's length in days. For the final variant the window runs from `arrival_date` up to but not including the ship date; `yardage_cents` is the resulting head-days multiplied by the yardage rate of 45 cents per head-day. The health line `health_cents` is `total_health_cost_cents` at confirm, and the death-loss line `death_loss_cents` is `total_death_loss_cents` — each loss already pinned at its own loss date, never repriced from invoice totals. The invoice's `insurance_credit_cents` is the smaller of the lot's `insurance_credit_pending_cents` and the sum of the four charge lines, and that credit is then subtracted from the pending balance; `total_cents` is the feed, yardage, health, and death-loss lines summed, minus the insurance credit. This pinned evaluation order — feed, then yardage, then health, then death loss, then the credit — is what breaks the apparent circularity among the lines. Only claims that reached `PAID` before confirm are netted into the invoice; claims paid afterwards credit the owner's balance directly per §3.5.

The close-out also computes its own summary figures: `total_cost_cents` is the lot's full cost pool — `purchase_cost_cents` plus feed, final-variant yardage, health, and death-loss costs; `final_cog_cents_per_cwt` divides that pool by the lot's gained hundredweight, where the gained weight is the `out_weight_total_lbs` minus the in-weight attributable to shipped head (`in_weight_total_lbs` multiplied by `head_shipped` and divided by `head_count_in`, so dead-head in-weight is excluded), the whole difference divided by one hundred, and the division is rounded half up to two decimal places; `hedge_pnl_cents` snapshots the lot's `total_hedge_pnl_cents`; and `net_result_cents` is the grid value plus the hedge P&L minus the total cost.

Confirmation then cascades in four links. First, any prior `CONFIRMED` close-out for the same lot becomes `SUPERSEDED`, and its still-`OPEN` invoice becomes `VOID` with the owner's balance compensated by that invoice's unpaid remainder. Second, the lot transitions `SHIPPED → CLOSED_OUT`. Third, a new `OPEN` invoice is generated with the lines above, its `lot_id` and `owner_id` copied from the lot, and an `amount_paid_cents` of zero, consuming the lot's pending insurance credit. Fourth, the owner's `outstanding_balance_cents` increases by the new invoice's `total_cents`. The confirm increments both the close-out's and the lot's `version`.

A lot's provisional cost of gain, visible as `provisional_cog_cents_per_cwt`, is the forward-looking counterpart of the final figure. It is recomputed on every cost- or head-affecting mutation — feed allocations, health events, death losses and their voids, shipping — and on every clock advance for non-terminal lots. Its cost pool is the purchase cost plus feed, provisional yardage over the window from arrival up to but not including the current logical date, health, and death-loss costs; its projected gain is the lot's `head_count_current` multiplied by the whole days on feed (the current logical date minus the arrival date, in whole days) and by an assumed average daily gain of 3.4 pounds per head per day; the pool divided by that gain, expressed in hundredweight and rounded half up to two decimal places, is the provisional value, and the value is null whenever the projected gain is zero or negative.

Settlement completes the cycle. A `BillingClerk` applies payments to an `OPEN` invoice — anything else is an `ERR_INVOICE_NOT_OPEN` (HTTP 409) — by supplying an `amount_cents` greater than zero (`ERR_INVALID_REQUEST` otherwise) and a `payment_date`. Each payment adds to `amount_paid_cents` and reduces the owner's `outstanding_balance_cents` by the same amount. Cumulative payments may never exceed the invoice's `total_cents` — an excess is an `ERR_OVERPAYMENT` (HTTP 422) — but exact equality is allowed and pays the invoice: the invoice transitions `OPEN → PAID`, and the billed lot bubbles up from `CLOSED_OUT` to `SETTLED`, its terminal state. A `BillingClerk` may instead void an `OPEN` invoice, optionally recording a `reason` that is stored as `void_reason`; a `PAID` invoice can never be voided. Voiding compensates the owner by the invoice's unpaid remainder — `total_cents` minus `amount_paid_cents` — and the lot remains `CLOSED_OUT`; it does not revert. Invoices are readable per lot and per owner, and a lot's close-outs are likewise listable, all sorted by creation time ascending.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, post events against it, or drive state transitions return a `200 OK`. All request and response bodies conform to the envelope of §2.2, and list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/feedlot/owners` | Create a cattle owner (custom-feeding customer) | FeedyardManager |
| GET | `/feedlot/owners` | List owners | Any |
| GET | `/feedlot/owners/{ownerId}` | Get one owner | Any |
| PATCH | `/feedlot/owners/{ownerId}` | Suspend or reactivate an owner | FeedyardManager |
| GET | `/feedlot/owners/{id}/lots` | List lots owned by an owner | Any |
| GET | `/feedlot/owners/{id}/invoices` | List invoices billed to an owner | Any |
| POST | `/feedlot/pens` | Create a pen | FeedyardManager |
| GET | `/feedlot/pens` | List pens | Any |
| GET | `/feedlot/pens/{penId}` | Get one pen | Any |
| PATCH | `/feedlot/pens/{penId}` | Enter or exit maintenance | FeedyardManager |
| GET | `/feedlot/pens/{id}/assignments` | List pen assignments for a pen | Any |
| GET | `/feedlot/pens/{id}/feed-calls` | List feed calls for a pen | Any |
| POST | `/feedlot/lots` | Receive a lot of cattle | FeedyardManager |
| GET | `/feedlot/lots/{lotId}` | Get one lot with all computed accumulators | Any |
| POST | `/feedlot/lots/{lotId}/market` | Mark a lot as sold/marketed | FeedyardManager |
| POST | `/feedlot/lots/{lotId}/fail-sale` | Sale fell through; return lot to feeding | FeedyardManager |
| POST | `/feedlot/lots/{lotId}/ship` | Ship a marketed lot to the packer | FeedyardManager |
| GET | `/feedlot/lots/{id}/assignments` | List pen assignments for a lot | Any |
| GET | `/feedlot/lots/{id}/ration-assignments` | List ration assignments for a lot | Any |
| GET | `/feedlot/lots/{id}/health-events` | List health events for a lot | Any |
| GET | `/feedlot/lots/{id}/death-losses` | List death losses for a lot | Any |
| GET | `/feedlot/lots/{id}/hedges` | List hedge positions for a lot | Any |
| GET | `/feedlot/lots/{id}/close-outs` | List close-outs for a lot | Any |
| GET | `/feedlot/lots/{id}/invoices` | List invoices for a lot | Any |
| POST | `/feedlot/rations` | Formulate a ration | FeedManager |
| GET | `/feedlot/rations` | List rations | Any |
| GET | `/feedlot/rations/{rationId}` | Get one ration | Any |
| GET | `/feedlot/rations/{id}/ration-assignments` | List ration assignments using a ration | Any |
| GET | `/feedlot/rations/{id}/feed-calls` | List feed calls that used a ration | Any |
| POST | `/feedlot/assignments` | Place head of a lot into a pen | FeedyardManager |
| POST | `/feedlot/assignments/{assignmentId}/end` | End an active pen assignment | FeedyardManager |
| POST | `/feedlot/ration-assignments` | Put a lot on a ration for a half-open window | FeedManager |
| POST | `/feedlot/feed-calls` | Post a daily feed call for a pen | FeedManager |
| POST | `/feedlot/health-events` | Record a treatment with withdrawal period | CattleHealthTech |
| POST | `/feedlot/death-losses` | Record dead cattle against a lot | CattleHealthTech |
| GET | `/feedlot/death-losses/{deathLossId}` | Get one death loss | Any |
| POST | `/feedlot/death-losses/{deathLossId}/void` | Void a recorded death loss (compensating) | CattleHealthTech |
| GET | `/feedlot/death-losses/{id}/insurance-claims` | List insurance claims against a death loss | Any |
| POST | `/feedlot/insurance-claims` | File a mortality claim against an insured loss | CattleHealthTech |
| POST | `/feedlot/insurance-claims/{claimId}/decide` | Adjuster decision: approve or deny | ClaimsAdjuster |
| POST | `/feedlot/insurance-claims/{claimId}/appeal` | Appeal a denied claim (at most once) | ClaimsAdjuster |
| POST | `/feedlot/insurance-claims/{claimId}/pay` | Pay an approved claim | ClaimsTreasurer, ClaimsAdjuster |
| POST | `/feedlot/hedges` | Enter a futures hedge for a lot | RiskManager |
| POST | `/feedlot/hedges/{hedgeId}/offset` | Offset an open hedge and realize P&L | RiskManager |
| POST | `/feedlot/close-outs` | Open a close-out for a shipped lot | RiskManager |
| POST | `/feedlot/close-outs/{closeOutId}/confirm` | Confirm with carcass data; generate the invoice | RiskManager |
| POST | `/feedlot/invoices/{invoiceId}/payments` | Apply a payment to an open invoice | BillingClerk |
| POST | `/feedlot/invoices/{invoiceId}/void` | Void an open invoice (compensating) | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO-8601) | FeedyardManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PEN_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_RATION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DEATH_LOSS_NOT_FOUND` | 404 Not Found |
| `ERR_INSURANCE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_HEDGE_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSE_OUT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_OWNER_SUSPENDED` | 409 Conflict |
| `ERR_PEN_IN_MAINTENANCE` | 409 Conflict |
| `ERR_PEN_OCCUPIED` | 409 Conflict |
| `ERR_PEN_NOT_OCCUPIED` | 409 Conflict |
| `ERR_LOT_NOT_OPEN` | 409 Conflict |
| `ERR_LOT_NOT_MARKETED` | 409 Conflict |
| `ERR_LOT_HAS_NO_HEAD` | 409 Conflict |
| `ERR_LOT_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CLOSE_OUT_NOT_DRAFT` | 409 Conflict |
| `ERR_ACTIVE_HEDGES_EXIST` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_HEDGE_NOT_OPEN` | 409 Conflict |
| `ERR_ASSIGNMENT_ALREADY_ENDED` | 409 Conflict |
| `ERR_INVOICE_NOT_OPEN` | 409 Conflict |
| `ERR_WITHDRAWAL_NOT_CLEARED` | 409 Conflict |
| `ERR_COMMINGLE_RULE_VIOLATION` | 409 Conflict |
| `ERR_STEP_UP_VIOLATION` | 409 Conflict |
| `ERR_VOID_BLOCKED_BY_CLAIMS` | 409 Conflict |
| `ERR_PEN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS` | 409 Conflict |
| `ERR_OVER_ASSIGNMENT` | 409 Conflict |
| `ERR_DUPLICATE_PEN_CODE` | 409 Conflict |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 Conflict |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DEATH_LOSS_NOT_INSURED` | 409 Conflict |
| `ERR_CARCASS_COUNT_MISMATCH` | 409 Conflict |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_HEDGE_OVER_COVERED` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_LOSS_VALUE` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |

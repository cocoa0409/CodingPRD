# Donor & Fundraising CRM API — Product Requirements Document

## 1. Introduction

Nonprofit development teams live and die by the integrity of their gift ledger. A single acknowledged gift is rarely a self-contained event: it advances a donor's lifetime giving, re-tiers that donor into a new giving band, credits the campaign and the appeal that solicited it, distributes soft credit across the donor's household, pays down an outstanding pledge installment, and may later anchor an employer matching claim. When that same gift is refunded, every one of those postings must unwind to the value it held before the gift was ever acknowledged. This API exists to make those cascades exact, auditable, and reproducible.

The platform serves three operational constituencies. Gift entry and refunds, pledge management, and matching-gift administration belong to the **GiftAdmin**; campaigns, appeals, households, employers, and donor segmentation belong to the **CampaignManager**; and acknowledgements, tax receipts, planned giving, and the donor lifecycle (lapse, reactivation, archival) belong to **DonorRelations**. The system is built around a ledger-reconciliation discipline: every derived total — pledge balances, campaign raised figures, donor giving aggregates, household soft-credit sums — is recomputed atomically inside the request that triggers it, never deferred to a batch job. Because money and tax receipts are at stake, the specification below fixes precise contracts for amounts (always integer cents), state transitions, and concurrency, and it leaves no cascade implicit.

This document specifies the complete external contract: the global conventions every endpoint obeys (Section 2), the business workflows and their reconciliation rules (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as `GiftAdmin`, `CampaignManager`, and `DonorRelations`. When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All three roles are operator roles whose identity is opaque. When `X-User-Role` is `GiftAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id` for ownership purposes. The same holds when `X-User-Role` is `CampaignManager` and when `X-User-Role` is `DonorRelations`: in every case `X-User-ID` is an opaque operator identifier, never matched against a stored entity. There is therefore no resource-ownership check anchored to `X-User-ID` anywhere in this system — authorization is purely role-based, governed by the matrix in Section 4 and the per-operation notes in Section 3.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside the inclusive range of 1 through 100, or whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Audit Trail

Most resources in this system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field, also an ISO 8601 UTC timestamp, is refreshed on every mutation. Both `created_at` and `updated_at` are stamped from the server's logical clock (Section 2.9) — the same clock value that governs the system's time comparisons — rather than from wall-clock time; when the logical clock has never been set, they fall back to wall-clock time. (This is distinct from the response envelope's `api_request_timestamp` of Section 2.2, which always records the real wall-clock instant the server answered the request.) Stamping these resource timestamps from the logical clock is what lets the time-gated flows that derive their anchors from them — a pledge's installment `due_on` offsets from its `created_at` (Section 3.5), and a donor's `last_gift_at` taken as a gift's `created_at` (Section 3.4) — be evaluated deterministically against that same clock. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the anchor for the optimistic concurrency checks described in Section 2.10.

One entity type is deliberately leaner. A soft-credit row is an immutable artifact of a gift acknowledgement; such rows carry only `id` and `created_at`. They have neither `updated_at` nor `version`. When the originating gift is refunded, a soft-credit row is not deleted or re-versioned — instead its `reversed` flag is flipped, and the household total is recomputed to exclude reversed rows.

### 2.5. Monetary Values, Precision, and Cent-Conservation

Every monetary quantity in this system is an integer number of cents. There are no fractional cents and no floating-point money. Where a calculation divides an amount across several rows — a pledge's installment schedule, or a household's even soft-credit split — the division is performed in integer cents and the remainder is distributed one cent at a time, so that the sum of the parts equals the original whole exactly, with no rounding loss. Each calculation in Section 3 states precisely which rows receive the leftover cents and in what order.

Ratios are the one exception to the integer rule: an employer's `match_ratio` is a decimal multiplier. When a ratio is applied to a gift amount, the product is taken first and then reduced to a whole number of cents by discarding any fractional cent (flooring toward zero) before any cap is applied. The exact order — ratio first, then caps — is specified in Section 3's matching-gift narrative and must be preserved.

### 2.6. Foreign-Key Reference Integrity and Validation Ordering

All entities in this system are peers; relationships are expressed as foreign-key fields carried in request bodies, not as nested URL paths. Whenever a request names a resource by a path identifier or references another entity by a foreign key in its body, the referenced entity must already exist. Existence is validated left to right: path identifiers are checked first, then body foreign keys in their declaration order. The first identifier that does not resolve to an existing entity causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404), before any business rule is evaluated.

Validation across the whole API obeys a strict precedence so that a single request never reports a downstream failure while an upstream one is still latent. Authentication is checked first: a missing header yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a forbidden role yields `ERR_UNAUTHORIZED`. Existence is checked third, yielding `ERR_NOT_FOUND`. For the action endpoints that drive a state machine — acknowledge, receipt, refund, cancel, approve, deny, pay, confirm, realize, lapse, flag-lapsed, reactivate, flag-active, archive, and evaluate-delinquency — the target resource's current state is checked fourth: an operation requested against a resource not in a valid state for the requested transition yields `ERR_INVALID_STATE` (HTTP 409). Only after these four gates does the system evaluate the domain-specific business rules described below, and finally the body's own field-type and range checks, which yield `ERR_INVALID_REQUEST` (HTTP 400). The relative ordering of the remaining business rules is stated within the workflow that hosts them.

### 2.7. Atomic Reconciliation and Cascading Side Effects

The system is reconciliation-immediate: when an operation changes a fact that feeds a derived total, every dependent total is recomputed inside the same request, atomically. A gift acknowledgement, for example, does not merely flip the gift's `status`; in the same transaction it pins the gift's deductible amount, recomputes the donor's lifetime credit and re-tiers the donor, refreshes the donor's last-gift timestamp, recomputes the campaign's two raised figures, recomputes the appeal's attributed count when an appeal is named, mints soft-credit rows and recomputes the household total when the donor belongs to a household, and allocates the gift against the donor's pledge when one is named. A refund is the exact compensating action: every total the acknowledgement touched returns to the value it held beforehand.

When the server transitions a resource as a side effect — a pledge moving to `FULFILLED` because a gift drove its balance to zero, or a matching claim being denied because its gift was refunded — that secondary mutation independently refreshes the affected resource's `updated_at` and increments its `version`, exactly as a client-initiated mutation would. Server-driven transitions require no separate client request against the affected resource.

### 2.8. Campaign Window and Open-Gating

A campaign carries a window defined by `starts_on` (inclusive) and `ends_on` (inclusive), where `ends_on` must be strictly later than `starts_on`. The window is descriptive metadata; the operative gate on new financial activity is the campaign's `status`. Gifts, pledges, and planned-gift realizations may only attach to a campaign whose `status` is `OPEN`. Attempting to attach any of these to a campaign that is `DRAFT` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409). Closing a campaign does not retroactively touch gifts already recorded against it; it only blocks new attribution going forward.

### 2.9. The Logical Clock

Several flows are time-gated — pledge installment due dates and the donor lapse window in particular. So that these flows are testable deterministically, the server maintains a single logical UTC clock. An administrative capability sets that clock to a supplied instant, after which all time comparisons in the system — overdue-installment detection, lapse-window evaluation — use the clock's value rather than wall-clock time. The clock value is also what stamps the resource `created_at` / `updated_at` / `acknowledged_at` timestamps recorded during a request (Section 2.4), so that the anchors those comparisons read against — installment `due_on` and donor `last_gift_at` — lie on the same timeline as the clock they are compared to; only the response envelope's `api_request_timestamp` (Section 2.2) is exempt and continues to record wall-clock time. Until the clock is first set, both stamping and comparisons fall back to wall-clock time.

### 2.10. Optimistic Concurrency Control

Two mutating operations are guarded by optimistic concurrency control, each requiring the client to echo back the version it last observed on the parent resource.

Cancelling a pledge requires the body to carry `expected_pledge_version` as a non-optional field, holding the client's last observed `version` of that pledge. A gift acknowledgement allocated to a pledge legitimately advances the pledge's `version` (through the paid/balance recomputation and the installment cascade). If a cancel request still carries a `version` from before that advance, it is operating on a stale view of a now-partially-paid pledge; the request is rejected with `ERR_STALE_VERSION` (HTTP 412) so the operator re-reads the pledge before cancelling. A match between `expected_pledge_version` and the pledge's current `version` is required for the cancel to proceed.

Refunding a gift requires the body to carry `expected_gift_version` as a non-optional field, holding the client's last observed `version` of that gift. Moving a gift from `RECORDED` to `ACKNOWLEDGED` to `RECEIPTED` advances its `version` at each step; a refund request carrying the version the client saw at `RECORDED` time is acting on a stale view of a gift whose deductible amount and downstream postings have since changed. If `expected_gift_version` does not match the gift's current `version`, the refund is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint outside these two takes a version field, and neither version check is optional on its endpoint.

## 3. Business Logic & Workflows

### 3.1. Organizing the Campaign: Campaigns and Appeals

A `CampaignManager` opens the fundraising year by creating a campaign with a `name`, a fundraising `goal_cents` (a whole number of cents, at least 1), and a window bounded by `starts_on` and `ends_on`. The window's end must be strictly after its start. A new campaign begins in `DRAFT`, with both of its raised figures — `raised_hard_cents` and `raised_with_match_cents` — initialized to zero. A campaign accepts no financial activity until the manager advances it from `DRAFT` to `OPEN`; that transition is permitted only from `DRAFT`. When the campaign is finished, the manager advances it from `OPEN` to `CLOSED`, permitted only from `OPEN`, after which `CLOSED` is terminal. A campaign's `status` therefore walks `DRAFT → OPEN → CLOSED`, and only the `OPEN` middle state admits gifts, pledges, and realizations.

Beneath a campaign sit one or more appeals, each authored by a `CampaignManager`. An appeal records the `campaign_id` of the campaign it belongs to, a solicitation `channel` (one of `EMAIL`, `DIRECT_MAIL`, `EVENT`, `PHONE`, or `WEB`), and a tracking `code` of 1 to 40 characters. The `code` must be unique within its campaign, compared case-insensitively; a collision is rejected with `ERR_DUPLICATE_APPEAL_CODE` (HTTP 409). A planner may also record an `expected_response_rate`, a fraction strictly greater than 0 and at most 1, expressing the share of solicited donors expected to give; it defaults to 0.05 when omitted. Each appeal maintains a computed `attributed_gift_count`, the number of gifts naming this appeal that have reached `ACKNOWLEDGED` or `RECEIPTED`; it is refreshed whenever such a gift is acknowledged or refunded.

### 3.2. Donors, Households, and Soft-Credit Distribution

Donors are created by either a `CampaignManager` or a `GiftAdmin`. A donor carries a `full_name` (1 to 120 characters) and an `email` that must be unique across all donors when compared case-insensitively; a duplicate email is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A donor may optionally name the `household_id` of the household they belong to and the `employer_id` of their matching-gift employer, both nullable for unaffiliated donors. A donor may also set `lapse_threshold_days`, the number of days of inactivity that must pass before the donor becomes eligible to be flagged lapsed; it must be an integer from 30 to 3650 and defaults to 365.

Each donor carries two parallel status dimensions on the same record. The lifecycle dimension, `lifecycle_status`, begins at `PROSPECT` and is one of `PROSPECT`, `ACTIVE`, `LAPSED`, `REACTIVATED`, or `ARCHIVED`; it is driven by the lifecycle workflow in Section 3.7. The giving dimension, `giving_status`, begins at `NONE` and is one of `NONE`, `ENTRY`, `MID`, or `MAJOR`; it is derived purely from the donor's lifetime hard credit and is recomputed on every acknowledgement and refund. The donor also exposes `lifetime_hard_credit_cents` and `last_gift_at`, both computed (described in Section 3.4).

Households are the unit of soft credit. A `CampaignManager` creates a household with a display `name` (1 to 120 characters) and a `soft_credit_policy`, one of `FULL_TO_ALL`, `SPLIT_EVEN`, or `PRIMARY_ONLY`, defaulting to `FULL_TO_ALL`. A household tracks a computed `member_count` (the number of donors whose `household_id` equals this household's `id`) and a computed `total_soft_credit_cents`, both starting at zero. The household's `primary_donor_id` is nullable at creation and is set later by patching the household; when set it must reference a donor whose `household_id` already equals this household's `id`, otherwise the patch is rejected with `ERR_PRIMARY_NOT_MEMBER` (HTTP 422). Patching a household may update its `name`, `soft_credit_policy`, or `primary_donor_id`.

Soft credit is distributed as a side effect of acknowledging a gift whose donor belongs to a household, and it is the household's `soft_credit_policy` that decides who receives it. Consider the set of household members — every donor whose `household_id` equals the giving donor's `household_id`, which includes the giving donor — and the subset of *other* members, all of them except the giving donor. The giving donor receives hard credit only and never a soft-credit row for themselves. Under the `FULL_TO_ALL` policy, each other member is credited the full gift amount; a soft-credit row is created for every other member with `soft_credit_cents` equal to the gift's `amount_cents`, so the household total grows by the gift amount multiplied by one less than the member count. Under the `SPLIT_EVEN` policy, the full gift amount is partitioned across the other members as evenly as possible: order the other members by `created_at` ascending, give each the integer quotient of the gift amount divided by the number of other members, then hand the leftover cents — the gift amount minus that quotient times the number of other members — out one cent each to the earliest members in that `created_at` ascending order until the leftover is exhausted; here the household total grows by exactly the gift amount, since cents are conserved across beneficiaries. Under the `PRIMARY_ONLY` policy, only the household's `primary_donor_id` receives a soft-credit row equal to the full gift amount — and only when the primary donor is set and is not the giving donor; if the giving donor is themselves the primary, no soft-credit rows are created at all. After the rows are minted, the household's `total_soft_credit_cents` is recomputed as the sum of `soft_credit_cents` over all that household's soft-credit rows whose `reversed` flag is false. Each soft-credit row records the originating `gift_id`, the `household_id` over which credit is distributed, the `beneficiary_donor_id` receiving it, the `soft_credit_cents` amount, and the `reversed` flag, which is false at creation.

### 3.3. Recording and Acknowledging a Gift

Recording a gift is a `GiftAdmin` action. The gift names a `donor_id` (the donor of record and hard-credit recipient, who must exist and must not be archived), a `campaign_id` for attribution (the campaign must be `OPEN`), and an `amount_cents` of at least 1. Optionally it names an `appeal_id` for finer attribution, a `pledge_id` if it pays down a pledge, a `payment_method` (one of `CARD`, `CHECK`, `ACH`, `CASH`, or `STOCK`, defaulting to `CARD`), and a `benefit_value_cents` recording the fair-market value of any goods or services the donor received in exchange, which defaults to 0 and must be an integer no greater than the gift's `amount_cents`. A `benefit_value_cents` exceeding `amount_cents` is rejected with `ERR_BENEFIT_EXCEEDS_GIFT` (HTTP 422). When an `appeal_id` is supplied, its `campaign_id` must equal the gift's `campaign_id`, else the gift is rejected with `ERR_APPEAL_CAMPAIGN_MISMATCH` (HTTP 422). When a `pledge_id` is supplied, the pledge's `donor_id` must equal the gift's `donor_id` *and* the pledge's `campaign_id` must equal the gift's `campaign_id`; a violation of either is rejected with `ERR_PLEDGE_ATTRIBUTION_MISMATCH` (HTTP 422). Among the gift-creation business rules, appeal-campaign agreement is evaluated before pledge attribution, which is evaluated before the open-campaign gate, which is evaluated before the benefit-versus-amount check. A freshly recorded gift starts in `RECORDED` with no ledger postings yet; postings happen only at acknowledgement.

Acknowledgement, performed by `DonorRelations`, is the moment hard credit becomes real, and it requires the gift to be in `RECORDED` and its donor's `lifecycle_status` to be anything other than `ARCHIVED`. The transition `RECORDED → ACKNOWLEDGED` fans out a single atomic cascade: it creates an acknowledgement record of kind `ACKNOWLEDGEMENT` (carrying the gift's `gift_id` and the `donor_id` copied from the gift); it sets the gift's `acknowledged_at` to the current clock; it pins the gift's `deductible_amount_cents`; it recomputes the donor's `lifetime_hard_credit_cents`, then re-derives the donor's `giving_status`, then refreshes the donor's `last_gift_at`; it recomputes the campaign's `raised_hard_cents` and `raised_with_match_cents`; if an `appeal_id` is present it recomputes that appeal's `attributed_gift_count`; if the donor has a `household_id` it mints soft-credit rows per the household policy and recomputes the household's `total_soft_credit_cents`; and if a `pledge_id` is present it recomputes the pledge's `paid_cents` and `balance_cents`, allocates the gift to the earliest due installment, and may drive the pledge to `FULFILLED` (all detailed in Sections 3.2, 3.4, and 3.5). Acknowledgement alone does not change a donor's `lifecycle_status`; a lapsed donor's return to activity is handled only by the reactivation workflow of Section 3.7.

A gift's `deductible_amount_cents` is the tax-deductible portion, computed at acknowledgement and pinned thereafter. It is the gift's `amount_cents` reduced by its `benefit_value_cents`, floored at zero — that is, the larger of zero and the difference between the two. A gift bought entirely as a quid-pro-quo benefit thus pins a zero deductible.

### 3.4. Donor Lifetime Credit and Giving Tier

A donor's `lifetime_hard_credit_cents` is the sum of `amount_cents` over that donor's gifts whose `status` is either `ACKNOWLEDGED` or `RECEIPTED`. Gifts still in `RECORDED` and gifts that have been refunded contribute nothing. The figure is recomputed at every acknowledgement (which adds the newly acknowledged gift) and at every refund (which subtracts the refunded gift). The donor's `last_gift_at` is, in parallel, the `created_at` of the most recent such gift — the most recent gift in `ACKNOWLEDGED` or `RECEIPTED` ordered by `created_at` — or null when the donor has no such gift; this field drives lapse detection.

The giving tier follows directly from lifetime credit and is re-derived in the same step. Let the donor's recomputed `lifetime_hard_credit_cents` be the deciding figure. When it equals zero, `giving_status` is `NONE`. When it is greater than zero but strictly below 50,000 cents (that is, under five hundred dollars), `giving_status` is `ENTRY`. When it is at least 50,000 cents but strictly below 1,000,000 cents (from five hundred dollars up to, but not reaching, ten thousand dollars), `giving_status` is `MID`. When it reaches or exceeds 1,000,000 cents (ten thousand dollars or more), `giving_status` is `MAJOR`. The boundaries are strict in the stated direction: a lifetime of exactly 50,000 cents is `MID`, and a lifetime of exactly 1,000,000 cents is `MAJOR`.

### 3.5. Pledges, Installment Schedules, and the Delinquency Cycle

A `GiftAdmin` creates a pledge naming the `donor_id` of the pledging donor (who must exist and must not be archived), the `campaign_id` of the campaign it supports (which must be `OPEN` at pledge creation, else `ERR_CAMPAIGN_NOT_OPEN`), a `total_amount_cents` of at least 1, an `installment_count` (an integer from 1 to 60), and a `frequency` cadence of `ONE_TIME`, `MONTHLY`, `QUARTERLY`, or `ANNUAL`. When the cadence is `ONE_TIME`, the `installment_count` must be exactly 1; any other count with a `ONE_TIME` frequency is rejected with `ERR_INSTALLMENT_FREQUENCY_MISMATCH` (HTTP 422). The pledge may also carry a `schedule_basis`, either `FRONT_LOADED` or `BACK_LOADED`, defaulting to `FRONT_LOADED`. A new pledge starts `ACTIVE` with `balance_cents` equal to its `total_amount_cents`, and as a creation cascade it mints exactly `installment_count` installment rows; installments are never created directly.

Each minted installment carries a 1-based `sequence_no`, a computed `amount_cents`, a computed `due_on`, a `status` starting at `DUE`, and a `paid_by_gift_id` that is null while the installment is due. The per-installment amounts partition the pledge total exactly. Take the integer quotient of `total_amount_cents` divided by `installment_count` as the base amount, and let the remainder be the total minus that base times the count — a value of at least zero and less than the count. Under `FRONT_LOADED`, the earliest installments absorb the leftover: each of the first *remainder* installments (those whose `sequence_no` is at most the remainder) carries one cent above the base, and the rest carry the base. Under `BACK_LOADED`, the latest installments absorb the leftover: each of the last *remainder* installments (those whose `sequence_no` exceeds the count minus the remainder) carries one cent above the base, and the rest carry the base. Either way the installment amounts sum to `total_amount_cents` exactly; the only difference is whether installment 1 or installment *n* is the one that may run a cent higher. Each installment's `due_on` is offset from the pledge's `created_at` by its position: a `ONE_TIME` pledge has its single installment due at `created_at`; a `MONTHLY` pledge sets installment *k* due at `created_at` plus *(k − 1)* months; a `QUARTERLY` pledge sets it due at `created_at` plus *(k − 1)* times three months; and an `ANNUAL` pledge sets it due at `created_at` plus *(k − 1)* years.

A pledge maintains three computed figures, recomputed on every gift acknowledgement and refund that touches it. Its `paid_cents` is the sum of `amount_cents` over gifts naming this `pledge_id` whose `status` is `ACKNOWLEDGED` or `RECEIPTED`. Its `balance_cents` is `total_amount_cents` minus `paid_cents`, floored at zero. Its `installments_due_count` is the number of this pledge's installments whose `due_on` is at or before the current clock and whose `status` is still `DUE`; this count drives delinquency.

Allocation happens inside gift acknowledgement. When an acknowledged gift names a `pledge_id`, the system recomputes the pledge's `paid_cents` and `balance_cents`, then allocates the gift to the single earliest due installment of that pledge — earliest by `due_on` ascending, breaking ties by `sequence_no` ascending — moving that installment from `DUE` to `PAID` and stamping its `paid_by_gift_id` with the allocating gift's id. If that allocation drives the pledge's `balance_cents` to zero, the pledge advances to `FULFILLED` and any installments still `DUE` are marked `WAIVED`. A pledge may reach `FULFILLED` from either `ACTIVE` or `DELINQUENT` by this route.

Delinquency is the cyclic heart of the pledge machine. A `GiftAdmin` (or the system, cascading from a clock advance) re-evaluates a pledge: this recomputes its `installments_due_count`, and if the pledge is `ACTIVE` and at least one installment is overdue (its `installments_due_count` is 1 or more), the pledge moves `ACTIVE → DELINQUENT`. The return leg is system-driven: when a gift acknowledgement allocates payment such that, afterward, no installment with a `due_on` at or before the current clock remains `DUE`, a `DELINQUENT` pledge moves back to `ACTIVE`. A `DELINQUENT` pledge can also be driven straight to `FULFILLED` if an allocation drives its balance to zero. And the cycle can run in reverse: if a refund reverses an allocation and lifts a `FULFILLED` pledge's `balance_cents` back above zero, the pledge reverts `FULFILLED → ACTIVE` and its `installments_due_count` is recomputed.

Cancelling a pledge is a `GiftAdmin` action permitted only while the pledge is `ACTIVE` or `DELINQUENT`, and it is guarded by the optimistic concurrency check of Section 2.10 on `expected_pledge_version`. A successful cancel moves the pledge to `CANCELLED`, marks all still-`DUE` installments `WAIVED`, and increments the pledge's `version` by one. `CANCELLED` and `FULFILLED` are the pledge's terminal states.

Installments themselves move on a small machine. An installment goes `DUE → PAID` when a gift acknowledgement allocates payment to it (it must be `DUE` and the allocating gift's `pledge_id` must equal the installment's `pledge_id`), recording the allocating gift in `paid_by_gift_id`. It returns `PAID → DUE` when the allocating gift is refunded — matched by the installment whose `paid_by_gift_id` equals the refunded gift's id — clearing `paid_by_gift_id`. And a still-`DUE` installment goes `DUE → WAIVED` when its pledge becomes `FULFILLED` or `CANCELLED`. `PAID` and `WAIVED` are terminal for an installment.

### 3.6. Matching Gifts: Employers and Claims

Employers underwrite matching gifts. A `CampaignManager` registers an employer with a `name` (1 to 120 characters, unique case-insensitively across employers), a `match_ratio` multiplier (greater than 0 and at most 3.0, defaulting to 1.0), a `min_gift_cents` floor (an integer of at least 0, defaulting to 2500) below which a gift is ineligible for matching, a `max_match_cents` per-gift cap on the matched amount (an integer of at least 1, defaulting to 1,000,000), and an `annual_match_cap_cents` ceiling on the total matched per donor per employer within a calendar year (an integer of at least 1, defaulting to 5,000,000).

A matching claim is opened by a `GiftAdmin` against a single acknowledged gift, supplied as `gift_id`. The gift must already be `ACKNOWLEDGED` or `RECEIPTED`, and its donor must have an `employer_id` set; if the donor lacks an employer, or if the gift's `amount_cents` is below that employer's `min_gift_cents`, the claim is rejected with `ERR_GIFT_INELIGIBLE_FOR_MATCH` (HTTP 422). On a successful open, the claim copies the donor's `employer_id`, pins its `requested_amount_cents`, and starts in `SUBMITTED`. The requested amount is computed by applying the employer's `match_ratio` to the gift's `amount_cents` and discarding any fractional cent (flooring to whole cents), then taking the smaller of that floored product and the employer's `max_match_cents`. This is the per-gift cap stage; the donor-employer annual cap is not applied here.

A submitted claim forks. A `GiftAdmin` may approve it (`SUBMITTED → APPROVED`, allowed only while the claim's gift is `ACKNOWLEDGED` or `RECEIPTED`) or deny it (`SUBMITTED → DENIED`). An approved claim may then be paid (`APPROVED → PAID`, again only while the gift is `ACKNOWLEDGED` or `RECEIPTED`) or denied (`APPROVED → DENIED`). Denial carries no ledger side effect. Paying is the divergent branch: it pins the claim's `matched_amount_cents` and adds it to the gift's campaign's `raised_with_match_cents`, whereas denial touches no totals. The claim's `matched_amount_cents` is zero until the claim is paid.

At pay time the annual cap binds. Compute the calendar year of the gift's `created_at`. Sum the `matched_amount_cents` of every other claim that is already `PAID`, belongs to the same employer, was raised against a gift in that same calendar year, and shares the same donor — this is the amount of the annual cap already consumed. The remaining cap is the larger of zero and the employer's `annual_match_cap_cents` minus that consumed amount. The claim's final `matched_amount_cents` is the smaller of its `requested_amount_cents` and that remaining cap. Two outcomes follow from this: when the annual cap is not yet approached and the remaining cap is at least the requested amount, the matched amount equals the requested amount (which itself was the floored product capped by the per-gift maximum); but when earlier paid claims have consumed enough of the cap that the remaining is below the requested amount, the matched amount equals the remaining cap, so the same gift and ratio yield a smaller match than they otherwise would. Only `PAID` claims consume the annual cap; `SUBMITTED`, `APPROVED`, and `DENIED` claims do not. A claim's `status` is one of `SUBMITTED`, `APPROVED`, `PAID`, or `DENIED`, with `PAID` and `DENIED` terminal.

### 3.7. The Donor Lifecycle: Lapse, Reactivation, and Archival

A donor's `lifecycle_status` evolves on its own machine, independent of the giving tier. A `PROSPECT` donor becomes `ACTIVE` automatically the first time a gift for that donor is acknowledged (the same step that first sets `last_gift_at`). `DonorRelations` flags an `ACTIVE` donor lapsed: the transition `ACTIVE → LAPSED` is permitted only when the elapsed time from the donor's `last_gift_at` to the current clock is at least the donor's `lapse_threshold_days` days; a request that does not meet that window is rejected with `ERR_LAPSE_WINDOW_NOT_MET` (HTTP 409).

Reactivation requires evidence of renewed giving. `DonorRelations` moves a `LAPSED` donor to `REACTIVATED` only when a qualifying reactivation gift exists — a gift for that donor in `ACKNOWLEDGED` or `RECEIPTED` whose `created_at` falls after the `last_gift_at` recorded at the moment of lapse; without such a gift the request is rejected with `ERR_NO_REACTIVATION_GIFT` (HTTP 409). A successful reactivation sets the donor's `lifecycle_status` to `REACTIVATED`. From there `DonorRelations` promotes the donor `REACTIVATED → ACTIVE`.

Archival closes a donor out. `DonorRelations` may archive a donor whose `lifecycle_status` is `PROSPECT` or `LAPSED`, provided the donor has no pledge in `ACTIVE` or `DELINQUENT` status; an attempt to archive a donor with such a live pledge is rejected with `ERR_DONOR_HAS_ACTIVE_PLEDGE` (HTTP 409). A successful archival moves the donor to `ARCHIVED`, which is terminal. Because an archived donor cannot be the donor of record on a new gift or pledge, archival also closes off future hard-credit activity for that donor.

### 3.8. Planned Giving

`DonorRelations` records a planned-giving intent for a donor, naming the `donor_id` (the donor must exist), the `vehicle` instrument (one of `BEQUEST`, `CHARITABLE_TRUST`, `LIFE_INSURANCE`, or `IRA_ROLLOVER`), and an `expected_amount_cents` estimate of at least 1. A planned gift starts in `INTENT`. `DonorRelations` confirms it `INTENT → CONFIRMED`. A confirmed planned gift may be realized: `DonorRelations` supplies the `campaign_id` of the realizing campaign (which must be `OPEN`) and a `realized_amount_cents`, and the system creates a gift for the planned gift's donor against that campaign for the realized amount with `payment_method` of `STOCK`, starting in `RECORDED`, and records that new gift's id in the planned gift's `realized_gift_id` while moving the planned gift to `REALIZED`. The realized gift then flows through its own `RECORDED → ACKNOWLEDGED` lifecycle separately. Alternatively, a planned gift in either `INTENT` or `CONFIRMED` may be marked `LAPSED` by `DonorRelations`. A planned gift's `status` is one of `INTENT`, `CONFIRMED`, `REALIZED`, or `LAPSED`, with `REALIZED` and `LAPSED` terminal; its `realized_gift_id` is null until it is realized.

### 3.9. Acknowledgements, Tax Receipts, and Refunds

Every acknowledgement record carries the `gift_id` it concerns, the `donor_id` copied from that gift, a `template_code` letter/email template identifier (1 to 40 characters, defaulting to `STANDARD`), a `kind`, and a `receipt_number`. The `kind` is `ACKNOWLEDGEMENT` when the row is created by the acknowledge action and `RECEIPT` when created by the receipt action. The `receipt_number` is null for an `ACKNOWLEDGEMENT` row.

Issuing a tax receipt is a `DonorRelations` action that moves a gift `ACKNOWLEDGED → RECEIPTED` and creates a second acknowledgement record of kind `RECEIPT`. It is permitted only while the gift is `ACKNOWLEDGED` and only when the gift's `deductible_amount_cents` is at least 1; a zero-deductible gift cannot be tax-receipted and the attempt is rejected with `ERR_ZERO_DEDUCTIBLE` (HTTP 422). Receipting changes no ledger total — hard credit was already counted at acknowledgement. Only `RECEIPT`-kind rows consume receipt numbers. The number assigned is one greater than the count of all prior `RECEIPT` acknowledgements, formatted as the prefix `RCPT-` followed by that running count zero-padded to a width of six digits — so the first receipt is `RCPT-000001`, the second `RCPT-000002`, and so on. `ACKNOWLEDGEMENT`-kind rows never consume a number.

Refunds are the compensating action and are reserved to `GiftAdmin`, guarded by the `expected_gift_version` optimistic-concurrency check of Section 2.10. A refund is permitted when the gift is `ACKNOWLEDGED` or `RECEIPTED` and is blocked when any matching claim against that gift is already `PAID` — a paid match must be reversed by the employer first — in which case the refund is rejected with `ERR_MATCH_PAID_BLOCKS_REFUND` (HTTP 409). A permitted refund moves the gift to `REFUNDED` (terminal) and runs the full compensating cascade: it recomputes the donor's `lifetime_hard_credit_cents` (subtracting this gift), then re-derives the donor's `giving_status`, then refreshes `last_gift_at`; it recomputes the campaign's `raised_hard_cents` and `raised_with_match_cents`; if an `appeal_id` is present it recomputes that appeal's `attributed_gift_count`; if the donor has a `household_id` it sets `reversed` to true on this gift's soft-credit rows and recomputes the household's `total_soft_credit_cents` so that conserved household credit returns to its pre-acknowledgement value; if a `pledge_id` is present it recomputes the pledge's `paid_cents` and `balance_cents`, returns the installment whose `paid_by_gift_id` equals this gift to `DUE` and clears that `paid_by_gift_id`, and reverts a `FULFILLED` pledge to `ACTIVE` when the reversal lifts its balance above zero; and if any matching claim against this gift is in `SUBMITTED` or `APPROVED`, that claim is cascaded to `DENIED`.

### 3.10. Segmentation

A `CampaignManager` defines a donor segment with a `name` (1 to 80 characters) and a membership predicate. The predicate has three parts: `min_lifetime_cents`, an inclusive lower bound on a donor's `lifetime_hard_credit_cents` (an integer of at least 0, defaulting to 0); `giving_status_in`, an array drawn from `NONE`, `ENTRY`, `MID`, and `MAJOR` listing the giving tiers that qualify; and `lifecycle_status_in`, an array drawn from `PROSPECT`, `ACTIVE`, `LAPSED`, `REACTIVATED`, and `ARCHIVED` listing the lifecycle states that qualify. Each array defaults to empty, and an empty array imposes no restriction on that dimension. A donor is a member when its `lifetime_hard_credit_cents` is at least `min_lifetime_cents`, its `giving_status` is among `giving_status_in` (or that array is empty), and its `lifecycle_status` is among `lifecycle_status_in` (or that array is empty). The segment exposes a computed `member_count`, which is the number of donors satisfying the predicate evaluated against the current donor population at read time — it is recomputed when the segment is fetched and when its members are listed, never frozen as a stored snapshot.

### 3.11. The Logical Clock as a Test-Driving Capability

Any of the three roles may invoke the administrative clock capability, supplying a `to_iso8601` target instant. Setting the clock takes effect immediately for all subsequent time comparisons — installment due-date evaluation during delinquency checks and the lapse-window evaluation during lapse flagging both read this clock value rather than wall-clock time. This capability returns no resource body.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that fetch a resource, list a collection, or modify an existing resource (including the state-machine action endpoints and the clock-setting capability) return a `200 OK` status code. All endpoints require the `X-User-ID` and `X-User-Role` headers described in Section 2.1; the "Authorized Role(s)" column lists the roles permitted to invoke each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/households` | Create a household | CampaignManager |
| GET    | `/households/{id}` | Fetch a household with computed soft-credit total and member count | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/households` | List households; filter by `primary_donor_id` | CampaignManager, GiftAdmin, DonorRelations |
| PATCH  | `/households/{id}` | Update household name, soft-credit policy, or primary donor | CampaignManager |
| GET    | `/households/{id}/soft-credits` | List soft-credit rows for this household | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/donors` | Create a donor | CampaignManager, GiftAdmin |
| GET    | `/donors/{id}` | Fetch a donor with computed lifetime credit, giving tier, and lapse fields | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/donors` | List donors; filter by `household_id`, `employer_id`, `lifecycle_status`, `giving_status` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/donors/{id}/flag-lapsed` | Flag an ACTIVE donor LAPSED once the inactivity window is met | DonorRelations |
| POST   | `/donors/{id}/reactivate` | Move a LAPSED donor to REACTIVATED given a qualifying post-lapse gift | DonorRelations |
| POST   | `/donors/{id}/flag-active` | Promote a REACTIVATED donor back to ACTIVE | DonorRelations |
| POST   | `/donors/{id}/archive` | Archive a PROSPECT or LAPSED donor with no active pledge | DonorRelations |
| POST   | `/employers` | Create a matching-gift employer | CampaignManager |
| GET    | `/employers/{id}` | Fetch an employer | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/campaigns` | Create a campaign (starts DRAFT) | CampaignManager |
| GET    | `/campaigns/{id}` | Fetch a campaign with both raised variants | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/campaigns/{id}/open` | Open a DRAFT campaign for gifts and pledges | CampaignManager |
| POST   | `/campaigns/{id}/close` | Close an OPEN campaign | CampaignManager |
| POST   | `/appeals` | Create an appeal under a campaign | CampaignManager |
| GET    | `/appeals/{id}` | Fetch a single appeal | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/appeals` | List appeals; filter by `campaign_id` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/pledges` | Create a pledge; cascades the installment schedule | GiftAdmin |
| GET    | `/pledges/{id}` | Fetch a pledge with paid/balance and overdue counts | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/pledges` | List pledges; filter by `donor_id` or `campaign_id` | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/pledges/{id}/installments` | List the installments of a pledge | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/pledge-installments/{id}` | Fetch a single pledge installment | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/pledge-installments` | List pledge installments; filter by `pledge_id` or `paid_by_gift_id` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/pledges/{id}/evaluate-delinquency` | Re-evaluate a pledge against the current clock | GiftAdmin |
| POST   | `/pledges/{id}/cancel` | Cancel a pledge (OCC-guarded on pledge version) | GiftAdmin |
| POST   | `/gifts` | Record a gift (starts RECORDED) | GiftAdmin |
| GET    | `/gifts/{id}` | Fetch a gift with computed deductible amount and status | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/gifts` | List gifts; filter by `donor_id`, `campaign_id`, `appeal_id`, `pledge_id`, `status` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/gifts/{id}/acknowledge` | Acknowledge a RECORDED gift; fans out the full ledger cascade | DonorRelations |
| POST   | `/gifts/{id}/receipt` | Issue a tax receipt for an ACKNOWLEDGED gift with positive deductible | DonorRelations |
| POST   | `/gifts/{id}/refund` | Refund an ACKNOWLEDGED/RECEIPTED gift (OCC-guarded on gift version) | GiftAdmin |
| GET    | `/gifts/{id}/acknowledgements` | List acknowledgement rows for a gift | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/gifts/{id}/soft-credits` | List soft-credit rows generated by a gift | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/soft-credits/{id}` | Fetch a single soft-credit row | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/soft-credits` | List soft-credit rows; filter by `beneficiary_donor_id`, `household_id`, or `gift_id` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/match-claims` | Open a matching-gift claim against an acknowledged gift | GiftAdmin |
| GET    | `/match-claims/{id}` | Fetch a match claim | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/match-claims` | List match claims; filter by `gift_id`, `employer_id`, or `status` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/match-claims/{id}/approve` | Approve a SUBMITTED claim | GiftAdmin |
| POST   | `/match-claims/{id}/deny` | Deny a SUBMITTED or APPROVED claim | GiftAdmin |
| POST   | `/match-claims/{id}/pay` | Pay an APPROVED claim; pins matched amount under the annual cap | GiftAdmin |
| POST   | `/planned-gifts` | Record a planned-giving intent | DonorRelations |
| GET    | `/planned-gifts/{id}` | Fetch a planned gift | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/planned-gifts` | List planned gifts; filter by `donor_id`, `realized_gift_id`, `status` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/planned-gifts/{id}/confirm` | Confirm an INTENT planned gift | DonorRelations |
| POST   | `/planned-gifts/{id}/realize` | Realize a CONFIRMED planned gift, minting a Gift into an OPEN campaign | DonorRelations |
| POST   | `/planned-gifts/{id}/lapse` | Mark an INTENT or CONFIRMED planned gift LAPSED | DonorRelations |
| GET    | `/acknowledgements/{id}` | Fetch a single acknowledgement/receipt | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/acknowledgements` | List acknowledgements; filter by `donor_id`, `kind` | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/segments` | Create a donor segment definition | CampaignManager |
| GET    | `/segments/{id}` | Fetch a segment definition | CampaignManager, GiftAdmin, DonorRelations |
| GET    | `/segments/{id}/members` | Evaluate the segment predicate and return matching donors | CampaignManager, GiftAdmin, DonorRelations |
| POST   | `/_clock/set_current_utc` | Set the server's logical UTC clock (test-driving) | GiftAdmin, CampaignManager, DonorRelations |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_APPEAL_CAMPAIGN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PLEDGE_ATTRIBUTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_APPEAL_CODE` | 409 Conflict |
| `ERR_BENEFIT_EXCEEDS_GIFT` | 422 Unprocessable Entity |
| `ERR_MATCH_PAID_BLOCKS_REFUND` | 409 Conflict |
| `ERR_GIFT_INELIGIBLE_FOR_MATCH` | 422 Unprocessable Entity |
| `ERR_ZERO_DEDUCTIBLE` | 422 Unprocessable Entity |
| `ERR_LAPSE_WINDOW_NOT_MET` | 409 Conflict |
| `ERR_DONOR_HAS_ACTIVE_PLEDGE` | 409 Conflict |
| `ERR_NO_REACTIVATION_GIFT` | 409 Conflict |
| `ERR_PRIMARY_NOT_MEMBER` | 422 Unprocessable Entity |
| `ERR_INSTALLMENT_FREQUENCY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |

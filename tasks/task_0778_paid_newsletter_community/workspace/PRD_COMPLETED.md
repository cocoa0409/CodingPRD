# Paid-Newsletter & Membership Community API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Paid-Newsletter & Membership Community API, a Substack- and Circle-style platform on which independent creators publish gated writing, run paid membership tiers, host community events, and collect recurring revenue. The platform sits at the intersection of two hard problems: orchestrating the full subscription lifecycle — free-to-paid conversion, trials, renewals, dunning, cancellation, and win-back — and running a correct billing engine on top of it, complete with tiered pricing, proration, a platform-fee split, and creator payouts.

The system serves four kinds of authenticated actors plus anonymous visitors. Creators own a publication and everything beneath it; members hold subscriptions and participate in the community; moderators police discussion; and platform operators run billing settlement, deliverability, and the logical clock that drives all time-based behavior. Because money and email reputation are both at stake, the API is deliberately strict: every monetary movement is conserved across a publication ledger, every seat in an event is conserved across its registrations, and every mutation that another writer could race against is guarded by optimistic concurrency control.

The requirements below define the shared contract first — authentication, response envelope, pagination, precision, concurrency, and consistency — and then walk the business workflows: publication and tier setup, member onboarding, the subscription lifecycle and its billing, publishing and newsletter delivery, content gating and moderation, event registration, and finally revenue analytics and payouts.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and boilerplate that apply across the entire API. Paths are absolute — the API has no common URL prefix — and each resource is addressed at its own top-level collection.

### 2.1. Users, Roles, and Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled precisely as `Creator`, `Member`, `Moderator`, `PlatformAdmin`, and `Anonymous`. A request whose `X-User-Role` is missing or not one of these five, or whose `X-User-ID` is absent for any role other than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED`. When a recognized, authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`. When a caller is permitted the operation in general but targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The five roles bind to identity differently, and this binding is what ties `X-User-ID` to ownership:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's `member_id` to `X-User-ID`: a member may act only on their own `Subscription`, their own `EventRegistration`, and their own `Comment`.
- When `X-User-Role` is `Creator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `creator_user_id` on the `Publication` the creator creates, and ownership checks on a publication and all of its child resources compare that publication's `creator_user_id` to `X-User-ID`.
- When `X-User-Role` is `Moderator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is used for permission checks but not compared to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; platform administrators operate billing, settlement, suspension, and simulation endpoints without per-resource ownership.
- When `X-User-Role` is `Anonymous`, `X-User-ID` need not be supplied; anonymous visitors may perform public reads, self-signup, and email verification only.

A `Creator` may act on behalf of their members for subscription operations (subscribe, change tier, cancel, reactivate) and may moderate comments; a `Moderator` shares only comment moderation. These shared arrangements are reflected in the per-endpoint authorization column of §4.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server's logical clock (§2.10) rather than wall-clock time.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; a value outside this range is clamped into it (a `limit` below 1 becomes 1 and above 100 becomes 100) rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative offset is clamped to 0. A `limit` or `offset` query value that cannot be parsed as an integer is silently ignored and its default is used.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system — `Publication`, `Tier`, `Member`, `Subscription`, `Invoice`, `Post`, `Event`, `EventRegistration`, `Comment`, and `Payout` — carries the same system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix, used for identity only.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value and increments by one on every mutation of the resource. This field backs optimistic concurrency control (§2.8).

All ten resource types in this domain carry the full set — none is create-only — so `updated_at` and `version` are always present. Note that the logical time recorded in these timestamps is drawn from the server's logical clock (§2.10), not wall-clock time.

### 2.5. Request Validation Order

When more than one rule could reject a request, the checks are evaluated in a fixed priority order, and the first failing check determines the returned error. This ordering is normative because a later, more specific error must never mask an earlier, more fundamental one:

1. **Authentication** — `X-User-Role` is present and one of the five known roles, and `X-User-ID` is present for every non-`Anonymous` role; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role permission** — the role is permitted for this endpoint; otherwise `ERR_FORBIDDEN` (403).
3. **Ownership** — a member acts only on their own subscription, registration, or comment, and a creator only on their own publication and its children; otherwise `ERR_NOT_RESOURCE_OWNER` (403).
4. **Existence** — every resource identifier in the path is resolved left-to-right (see §2.10); the first unresolved identifier yields its specific not-found error (404).
5. **Body validation** — the request body is present with all required fields, valid types and enum values, and honored numeric ranges; otherwise `ERR_VALIDATION` (422).
6. **Uniqueness** — member email is unique per publication and tier rank is unique per publication; otherwise `ERR_EMAIL_TAKEN` or `ERR_TIER_RANK_TAKEN` (409).
7. **State** — the target resource is in a state that permits the operation, and payout creation and subscription (re)activation additionally require the owning publication to be `ACTIVE`; otherwise `ERR_INVALID_STATE`, `ERR_ALREADY_REGISTERED`, or `ERR_PUBLICATION_SUSPENDED` (409).
8. **Referential business rules** — a member is `VERIFIED` before subscribing and the chosen tier belongs to the member's publication; otherwise `ERR_MEMBER_NOT_VERIFIED` or `ERR_TIER_PUBLICATION_MISMATCH` (409).
9. **Gating** — content, community, and delivery gating (see §3.6 and §3.7); yields `ERR_SUBSCRIPTION_REQUIRED`, `ERR_TIER_TOO_LOW` (403), or `ERR_DELIVERABILITY_SUSPENDED` (409).
10. **Temporal windows** — registration windows, win-back windows, renewal timing, event non-overlap, and send-window non-overlap (see the relevant workflows); yields the corresponding 409 error.
11. **Capacity** — a full event with waitlisting disabled rejects with `ERR_EVENT_FULL` (409).
12. **Fiscal** — a payout may not exceed available balance, else `ERR_INSUFFICIENT_BALANCE` (402).
13. **Concurrency** — the supplied expected parent version matches the parent's current `version`; otherwise the stale-version error (412).

### 2.6. Monetary Precision and the Platform-Fee Split

All monetary amounts are stored and returned as integer cents. Any computed monetary amount is rounded half up to a whole cent — that is, a fractional cent of exactly one half rounds away from zero to the next whole cent.

When an invoice is paid, the platform takes its cut and the remainder is credited to the creator. The **platform fee** for an invoice equals the invoice's `amount_due_cents` multiplied by the owning publication's `platform_fee_bps`, divided by ten thousand, rounded half up to whole cents; the result is stored as `platform_fee_cents`. The **creator net** is then the invoice's `amount_due_cents` minus that `platform_fee_cents`, stored as `creator_net_cents`. The `platform_fee_bps` value is a basis-points figure supplied at publication creation — for example, 1000 basis points is a ten percent fee — and it must lie between 0 and 3000 inclusive.

The rounding order is pinned and consequential: the fee is rounded **per invoice** and the resulting creator net is added to the publication's running totals one invoice at a time. The system must never sum several invoices' amounts and then take a single fee over the sum. Concretely, two invoices of 1005 cents each at 1000 basis points credit 1808 cents of creator net (each invoice yields a fee of 101 cents rounded half up from 100.5, leaving 904 cents, summed to 1808), which differs from the 1809 cents a sum-then-fee computation would produce.

### 2.7. The Publication Money-Conservation Ledger

Each publication maintains four money counters that together form a strict ledger: `lifetime_net_cents` (cumulative creator net ever credited, less any refunded net), `payout_balance_cents` (net currently available to withdraw), `pending_payout_cents` (net held by payouts that have been requested but not yet settled), and `lifetime_paid_out_cents` (cumulative net actually paid out). At all times the sum of `payout_balance_cents`, `pending_payout_cents`, and `lifetime_paid_out_cents` equals `lifetime_net_cents`.

The counters move only through the following events, and every movement preserves that invariant. When an invoice is paid, both `lifetime_net_cents` and `payout_balance_cents` increase by the invoice's `creator_net_cents`. When an invoice is refunded, both `lifetime_net_cents` and `payout_balance_cents` decrease by that same net. When a payout is requested, `payout_balance_cents` decreases and `pending_payout_cents` increases by the requested amount. When a payout settles as paid, `pending_payout_cents` decreases and `lifetime_paid_out_cents` increases by the amount. When a payout settles as failed, `pending_payout_cents` decreases and `payout_balance_cents` increases by the amount, releasing the held funds back to available balance.

### 2.8. Optimistic Concurrency Control

Two mutations draw against a parent whose state another writer may have advanced, and both are guarded by an expected-version field that the client must supply from its last read.

Requesting a payout draws down a publication's `payout_balance_cents`, so a payout request must carry `expected_publication_version`. If this value does not match the target publication's current `version` — because another payout or a refund has already moved the balance since the client last read the publication — the request is rejected with `ERR_STALE_PUBLICATION_VERSION` (HTTP 412), preventing the creator from drawing against a balance it has not observed. A successful payout request increments the publication's `version` by one.

Changing a subscription's tier prorates against the tier the client believes is currently in effect, so a change-tier request must carry `expected_subscription_version`. If this value does not match the subscription's current `version` — because a prior change-tier has already superseded that base tier since the client last read the subscription — the request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). A successful change-tier increments the subscription's `version` by one.

No other endpoint accepts an expected-version field; only these two mutations perform the concurrency check. The expected-version field is optional on the request body: when it is supplied the check is enforced as above, and when it is omitted (or null) the concurrency check is skipped and the mutation proceeds unconditionally.

### 2.9. Hierarchical Consistency and Recompute Semantics

Several operations mutate more than one resource. Whenever a mutation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented — this applies to the derived counters as well as to input fields. A publication's computed fields (`active_member_count`, `mrr_cents`, `recognized_revenue_cents`, `bounce_rate`, and the ledger counters) are recomputed by the server whenever an underlying event occurs, without requiring a client call against the publication itself; the analytics read described in §3.9 additionally forces a recompute of these fields on demand.

Cascades are described in full in the workflows they belong to, but two are load-bearing and stated here as well. Cancelling a subscription cascades into that member's future event registrations, and cancelling or freeing a seat on an event cascades into promoting the earliest waitlisted registration on that event. In each case the parent event's seat counters are adjusted and its `version` and `updated_at` move accordingly.

### 2.10. Nested Resource Retrieval and the Logical Clock

When an endpoint path contains more than one resource identifier, the system validates them left-to-right and rejects on the first that does not resolve. A comment under a non-existent post, for instance, yields `ERR_POST_NOT_FOUND` before the comment is ever considered. The not-found errors are resource-specific: `ERR_PUBLICATION_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, and `ERR_PAYOUT_NOT_FOUND`.

All time-dependent behavior reads a server-held logical clock rather than wall-clock time. The clock's startup default is exactly `2026-03-01T00:00:00Z`; before any call sets it, the clock reads exactly this default and never falls back to wall-clock time. A platform administrator may set the clock to a supplied instant via the required `to_iso8601` field (any valid ISO 8601 instant, including one earlier than the current clock); this is the mechanism by which trials expire, renewals become due, dunning deadlines pass, and win-back windows close during testing. The set-clock call returns a `data` object of the form `{ "current_utc": <the new instant> }` rather than a persisted resource.

### 2.11. Email Deliverability Posture

Independently of its operational `status`, each publication carries a `deliverability_status` reflecting email health, one of `HEALTHY`, `THROTTLED`, or `SUSPENDED`, starting at `HEALTHY`. The publication tracks `sent_count` (cumulative newsletter recipient-sends) and `bounce_count` (cumulative hard bounces), and its `bounce_rate` is `bounce_count` divided by the greater of one and `sent_count`.

After each recorded hard bounce, the posture is recomputed from the bounce rate against two inclusive breakpoints: the posture is `SUSPENDED` when the bounce rate is at least 0.50; it is `THROTTLED` when the rate is at least 0.20 but below 0.50; and it is `HEALTHY` otherwise. The 0.50 boundary is inclusive — a rate of exactly one half lands in `SUSPENDED`, not `THROTTLED`. A `THROTTLED` posture still allows newsletter sends; a `SUSPENDED` posture blocks them (§3.6). A creator or platform administrator can reset the posture, which zeroes `bounce_count`, `sent_count`, and `bounce_rate` and returns `deliverability_status` to `HEALTHY`.

## 3. Business Logic & Workflows

### 3.1. Establishing a Publication and its Tiers

A `Creator` bootstraps the platform by creating a **publication**, supplying its `name` and optionally its `platform_fee_bps`; when the fee is omitted it defaults to 1000 basis points. The server records the creating operator's identifier as `creator_user_id`, sets `status` to `ACTIVE` and `deliverability_status` to `HEALTHY`, and initializes every computed counter — `sent_count`, `bounce_count`, `lifetime_net_cents`, `payout_balance_cents`, `pending_payout_cents`, `lifetime_paid_out_cents`, `active_member_count`, `mrr_cents`, and `recognized_revenue_cents` — to zero. A platform administrator may later move a publication from `ACTIVE` to `SUSPENDED`; a suspend attempt against a publication that is not currently `ACTIVE` is rejected with `ERR_INVALID_STATE`. While suspended, the publication blocks new payout requests and blocks subscriptions from transitioning into an active spell, surfacing `ERR_PUBLICATION_SUSPENDED`.

Within a publication, a creator defines one or more **tiers**. A tier carries a `name`, a `tier_rank`, a `monthly_price_cents`, and an optional `trial_days` that defaults to zero. The `tier_rank` is a non-negative integer that must be unique within the publication — a rank of zero denotes the free tier and higher ranks grant more access — and a duplicate rank is rejected with `ERR_TIER_RANK_TAKEN`. The `monthly_price_cents` must be non-negative and is zero for a free tier, `trial_days` must be non-negative, and the computed `is_free` flag is true exactly when `tier_rank` is zero (equivalently, when the monthly price is zero). Each tier records its owning publication via `publication_id`. Tiers of a publication may be listed by anyone.

### 3.2. Member Onboarding and Verification

A visitor becomes a **member** of a publication either through self-signup or by being added by the creator; the caller supplies `email` and `display_name`. The email must be unique within the publication, and a collision is rejected with `ERR_EMAIL_TAKEN`. On creation the member's `status` is `PENDING`, a one-time `verification_token` is issued (a UUID, carried as a field on the member resource and returned in member responses), `email_bounced` is false, and the member records its `publication_id`. The member's `id` doubles as the `Member` role's `X-User-ID`.

To activate their account, the member (or an anonymous holder of the token) submits the `verification_token`; a match sets `status` to `VERIFIED` (the operation is not guarded on the member's current status), while a token that does not match the member's issued `verification_token` is rejected with `ERR_VALIDATION`. Verification matters because only a `VERIFIED` member may subscribe: attempting to subscribe while still `PENDING` (or after a bounce has driven the member to `BOUNCED`) is rejected with `ERR_MEMBER_NOT_VERIFIED`. A member's records are readable by the member themselves, the creator, and platform administrators.

### 3.3. The Subscription Lifecycle: Trial, Activation, and Renewal

A verified member **subscribes** by naming a `tier_id`; the subscription records the acting `member_id` and its chosen `tier_id`, and mirrors the tier's rank into `current_tier_rank` for gating purposes. The chosen tier must belong to the same publication as the member, or the request is rejected with `ERR_TIER_PUBLICATION_MISMATCH`.

Creation branches on the tier. A free tier (rank zero) advances the new subscription straight from `TRIALING` to `ACTIVE` at creation with no invoice, provided the publication is `ACTIVE`; it sets `current_period_start` to the current clock and `current_period_end` to thirty days later. A paid tier instead creates an `INITIAL` invoice due at the trial's end and leaves the subscription in `TRIALING`. The trial end is the creation instant plus the tier's `trial_days`; when `trial_days` is zero the invoice is due immediately at creation. The subscription's `trial_end` records this instant (null when there is no trial), and stays `TRIALING` until that `INITIAL` invoice is paid.

Payment is driven by a platform administrator simulating a gateway webhook against a named `invoice_id` with an `outcome` of `SUCCEEDED`, `FAILED`, or `REFUNDED`. A `SUCCEEDED` outcome is accepted only when the invoice is currently `OPEN` or `FAILED` (the latter enabling a dunning retry); a `FAILED` outcome only when the invoice is `OPEN`; and a `REFUNDED` outcome only when the invoice is `PAID`. An outcome applied to an invoice in any other payment status is rejected with `ERR_INVALID_STATE`. On any `SUCCEEDED` outcome the invoice is marked `PAID`, its `paid_at` stamped, and the platform-fee split is computed and credited to the owning publication (§2.6, §2.7), regardless of the invoice `reason`; a subscription status transition additionally occurs only for the activating cases described below. A `REFUNDED` outcome marks the invoice `REFUNDED` and reverses the previously credited `creator_net_cents` out of `lifetime_net_cents` and `payout_balance_cents` without changing any subscription's status. A `SUCCEEDED` outcome on the `INITIAL` invoice — permitted only while the publication is `ACTIVE` — advances the subscription from `TRIALING` to `ACTIVE`, sets `current_period_start` to the clock and `current_period_end` thirty days later, marks the invoice `PAID`, records its `paid_at`, computes the platform-fee split, and credits the publication's balance and lifetime net by the invoice's creator net. A `FAILED` outcome on the `INITIAL` invoice instead drives the subscription from `TRIALING` to the terminal `EXPIRED` state and marks the invoice `FAILED`. Both outcomes trigger a recompute of the publication's `active_member_count` and `mrr_cents`; a successful payment additionally refreshes `recognized_revenue_cents`.

An active subscription is **renewed** by a platform administrator or the creator, but only once the clock has reached or passed `current_period_end`; a premature attempt is rejected with `ERR_PERIOD_NOT_ENDED`. Renewal creates a `RENEWAL` invoice with a proration factor of one and no discount, due at the current clock and `OPEN`, then advances the period so that `current_period_start` becomes the old `current_period_end` and `current_period_end` moves thirty days further out. When a `RENEWAL` invoice's payment is later simulated as `FAILED`, the subscription moves from `ACTIVE` to `PAST_DUE`, the invoice is marked `FAILED`, and a `dunning_deadline` is set seven days after the failure. Retrying that same failed renewal with a `SUCCEEDED` outcome — again only while the publication is `ACTIVE` — brings the subscription back from `PAST_DUE` to `ACTIVE`, clears the `dunning_deadline`, marks the invoice `PAID`, credits the creator net to the publication, and recomputes `active_member_count`, `mrr_cents`, and `recognized_revenue_cents`.

### 3.4. Billing, Proration, and Tier Changes

Every invoice records the subscription it bills via `subscription_id`, its `reason` (one of `INITIAL`, `RENEWAL`, `PRORATION_UPGRADE`, or `WIN_BACK`), a `gross_cents` basis, a `discount_cents`, a `proration_factor`, the computed `amount_due_cents`, the `platform_fee_cents` and `creator_net_cents` filled in at payment, a `payment_status` (`OPEN`, `PAID`, `FAILED`, or `REFUNDED`), a `due_at`, and a `paid_at`.

The **amount due** for an ordinary invoice is computed from the subscription's current tier. The base price is the tier's `monthly_price_cents`. The discount is the win-back discount (see §3.5) when the invoice reason is `WIN_BACK`, and zero otherwise. The net after discount is the base price minus the discount, floored at zero so it can never go negative. The `amount_due_cents` is then that net multiplied by the invoice's `proration_factor`, rounded half up to whole cents. For `INITIAL`, `RENEWAL`, and `WIN_BACK` invoices the `proration_factor` is one.

A **tier change** is where proration enters. A member or creator changes tier by supplying a `new_tier_id` together with `expected_subscription_version`, and the subscription must be `ACTIVE`. The new tier must belong to the member's publication. The price delta is the new tier's `monthly_price_cents` minus the old tier's `monthly_price_cents`. The system computes a **provisional** proration that bills the remainder of the current period as if the member keeps the new tier through `current_period_end`: the remaining forward days are the whole days from the change instant to `current_period_end` (the day-difference rounded up to a whole day), the provisional factor is those remaining days divided by thirty, and the provisional charge is the price delta multiplied by that factor, rounded half up to whole cents. A `PRORATION_UPGRADE` invoice carrying this charge is created only when the price delta is positive (a genuine upgrade); its `gross_cents` is the price delta and its `amount_due_cents` is the provisional charge. The change then sets the subscription's `tier_id` to the new tier, recomputes `current_tier_rank`, and increments the subscription's `version` by one.

The same proration has a **final** form used at period close or at cancellation, and it can diverge from the provisional one. The final charge uses the actual active days — the whole days the new tier was genuinely in effect before `current_period_end` or before `canceled_at`, whichever bounds the spell — and equals the price delta multiplied by those actual active days divided by thirty, rounded half up to whole cents. Because the provisional form assumes the member keeps the new tier to period end, the final form is lower whenever the member cancels before `current_period_end`. This final form is descriptive only and is never separately billed: the system issues no final-proration invoice at period close or at cancellation — a renewal at period close creates a `RENEWAL` invoice at the full tier price (§3.3) and a cancellation (§3.5) creates no invoice — so the sole proration invoice the system ever generates is the provisional `PRORATION_UPGRADE` created at the instant of the tier change.

### 3.5. Dunning, Cancellation, and Win-Back

A subscription is **cancelled** by the member or creator from either `ACTIVE` or `PAST_DUE`, moving it to `CANCELED` and setting `canceled_at` to the clock; an optional `reason` may accompany the request (it is not persisted on the subscription). When the reason is the literal string `DUNNING`, cancellation is permitted only from `PAST_DUE` and only once the clock has reached or passed the `dunning_deadline`; a `DUNNING` cancellation attempted while the subscription is not `PAST_DUE`, or before the `dunning_deadline` has been reached, is rejected with `ERR_INVALID_STATE`. Cancellation carries a cascade: every one of that member's event registrations that is still `REGISTERED` for an event whose `starts_at` is in the future is moved to `CANCELED`; each such cancellation decrements that event's `registered_count` and increments its `available_slots`; and each freed seat promotes the earliest-created still-`WAITLISTED` registration on that same event to `REGISTERED`. Cancellation then recomputes the publication's `active_member_count` and `mrr_cents`.

Because `CANCELED` is not terminal, a cancelled subscription can be won back. **Reactivation** is performed by the member or creator only while the subscription is `CANCELED`, only when the publication is `ACTIVE`, and only within the win-back window — that is, when the clock is at or before thirty days after `canceled_at`. A reactivation attempt after that window has closed is rejected with `ERR_WINBACK_WINDOW_EXPIRED`. A successful reactivation moves the subscription from `CANCELED` back to `ACTIVE`, increments `reactivation_count` by one, sets `is_win_back` to true, clears `canceled_at`, sets `current_period_start` to the clock and `current_period_end` thirty days later, and creates a `WIN_BACK` invoice with a discount. The **win-back discount** is the current tier's `monthly_price_cents` multiplied by twenty percent, rounded half up to whole cents; it populates the invoice's `discount_cents` and, through the amount-due computation of §3.4, reduces what the returning member pays. Reactivation also recomputes `active_member_count` and `mrr_cents`.

### 3.6. Publishing and Sending Newsletters

A creator authors a **post** by supplying a `title`, a `body`, an optional `content_type` that defaults to `POST` (the alternative being `NEWSLETTER`), and an optional `min_tier_rank` that defaults to zero and sets the minimum subscriber rank required to read or comment. A new post records its `publication_id`, starts in `DRAFT`, and exposes computed counters `recipient_count` and `approved_comment_count` initialized to zero. Publishing a post advances it from `DRAFT` to `PUBLISHED`, and a retired post may rest in the `ARCHIVED` status; posts may be listed by anyone.

Sending a newsletter advances a post to `SENT`, stamps a throttle window, and emails the eligible audience; the send carries no source-state precondition, so a post may be sent directly from `DRAFT` without first being `PUBLISHED`, and its `content_type` need not be `NEWSLETTER`. The send-throttle window runs from `send_window_start` to `send_window_end`, the latter being sixty minutes after the former. A send is rejected with `ERR_SEND_WINDOW_CONFLICT` when its window would overlap that of a prior send within the sixty-minute throttle window, and is rejected with `ERR_DELIVERABILITY_SUSPENDED` when the publication's `deliverability_status` is `SUSPENDED`. The **recipient set** comprises every member of the publication whose `status` is `VERIFIED` and whose `email_bounced` is false and who holds at least one subscription in `ACTIVE` or `TRIALING` status whose `current_tier_rank` is at least the post's `min_tier_rank`; the count of that set becomes the post's `recipient_count`, and the publication's `sent_count` increases by that recipient count.

Deliverability posture is fed by bounces. A platform administrator records a hard bounce against a `member_id`, which sets that member's `email_bounced` to true, moves the member's `status` to `BOUNCED`, increments the publication's `bounce_count` by one, and recomputes `bounce_rate` and the deliverability posture against the breakpoints of §2.11. A `HEALTHY` publication whose rate reaches the 0.20 breakpoint becomes `THROTTLED` (sends still allowed); a publication whose rate reaches 0.50 becomes `SUSPENDED` (sends blocked). A creator or platform administrator restores the posture to `HEALTHY` and zeroes the counters through a deliverability reset.

### 3.7. Content Gating and Community Moderation

Reading a post's gated `body` and commenting on it are both gated on the acting member's subscription. To read gated content or to comment, the member must hold an `ACTIVE` subscription whose `current_tier_rank` is at least the post's `min_tier_rank`. A member with no qualifying subscription is refused with `ERR_SUBSCRIPTION_REQUIRED`, and a member whose subscription rank falls below the post's minimum is refused with `ERR_TIER_TOO_LOW`.

A member posts a **comment** by supplying its `body`; the comment records its `post_id`, the authoring `member_id`, starts in `PENDING`, and carries a `moderation_reason` that is null until it is moderated. Comments then move through a moderator-driven fork. A `Moderator` or `Creator` moderates a comment by supplying a `decision`. From `PENDING`, an `APPROVE` decision moves the comment to `APPROVED`, a `REJECT` decision moves it to the terminal `REJECTED` and sets a `moderation_reason`, and a `HOLD` decision moves it to `HELD` and sets a `moderation_reason`. From `HELD`, an `APPROVE` decision moves it to `APPROVED` and a `REJECT` decision moves it to `REJECTED` with a reason. From `APPROVED`, a `HIDE` decision moves the comment to the terminal `HIDDEN`. Whenever a decision sets `moderation_reason`, its value is the literal name of the applied decision — `REJECT` for a rejection and `HOLD` for a hold — and the request carries no separate reason field; the `APPROVE` and `HIDE` decisions leave `moderation_reason` unchanged. Any moderation attempt from a state that does not permit the requested decision is rejected with `ERR_INVALID_STATE`. Each transition into `APPROVED` increments the owning post's `approved_comment_count`, and hiding an approved comment decrements it, so the post's `approved_comment_count` always reflects the number of comments currently in `APPROVED`.

### 3.8. Events, Registration, and Seat Management

A creator schedules an **event** with a `title`, `starts_at`, `ends_at`, `registration_closes_at`, and `capacity`, plus an optional `min_tier_rank` (default zero) and an optional `allow_waitlist` (default true). The `ends_at` must be strictly after `starts_at` and the `capacity` must be at least one, or the request is rejected with `ERR_VALIDATION`. The event records its `publication_id` and exposes computed counters `registered_count`, `waitlist_count`, and `available_slots`, where `available_slots` is the `capacity` minus `registered_count` and never falls below zero.

A `Member` registers themselves for an event; the registration records the `event_id`, the acting `member_id`, a `registered_at`, and a `status`. Registration is gated exactly like content — an `ACTIVE` subscription of sufficient rank is required, subject to `ERR_SUBSCRIPTION_REQUIRED` and `ERR_TIER_TOO_LOW` — and is refused with `ERR_REGISTRATION_CLOSED` once the clock has passed `registration_closes_at`. A member may not double-register: an existing `REGISTERED` or `WAITLISTED` registration for the same event yields `ERR_ALREADY_REGISTERED`. A member already holding a `REGISTERED` spot on another event whose interval from `starts_at` to `ends_at` overlaps this event's interval is refused with `ERR_SCHEDULE_CONFLICT`. When these checks pass, the registration is created `REGISTERED` if a seat is available; otherwise it is created `WAITLISTED` when waitlisting is allowed, or rejected with `ERR_EVENT_FULL` when `allow_waitlist` is false.

Seats are conserved on every transition: for each event, the sum of `registered_count` and `available_slots` always equals `capacity`, `registered_count` equals the count of registrations in `REGISTERED`, and `waitlist_count` equals the count in `WAITLISTED`. When a `REGISTERED` registration is cancelled — by the member directly, or by the subscription-cancel cascade of §3.5 — the event's `registered_count` drops by one and `available_slots` rises by one, and the freed seat immediately promotes the earliest-created `WAITLISTED` registration on that event to `REGISTERED`. Promotion moves that registration from `WAITLISTED` to `REGISTERED`, raising `registered_count` and lowering both `waitlist_count` and `available_slots` by one. A member may also cancel their own `WAITLISTED` registration, which simply lowers `waitlist_count` by one with no promotion.

### 3.9. Revenue Analytics and Creator Payouts

A publication surfaces two distinct revenue figures, and the difference between them is deliberate. The **forward-looking monthly recurring revenue**, `mrr_cents`, is the sum of `monthly_price_cents` across every subscription of the publication whose status is `ACTIVE` or `TRIALING`; a trialing subscription contributes its full tier price even though nothing has been collected yet. The **recognized revenue**, `recognized_revenue_cents`, is instead the sum of `creator_net_cents` across every invoice of the publication whose `payment_status` is `PAID` and whose `paid_at` is at or before the current clock; a trialing subscription that has collected nothing contributes zero. The analytics read recomputes `mrr_cents`, `recognized_revenue_cents`, `active_member_count`, and `bounce_rate` on demand, where `active_member_count` is the number of members holding a subscription in `ACTIVE` or `TRIALING`.

A creator withdraws earnings by requesting a **payout** for an `amount_cents`, which must be positive and must not exceed the publication's `payout_balance_cents`; an over-draw is rejected with `ERR_INSUFFICIENT_BALANCE`. The request also carries `expected_publication_version` for the concurrency check of §2.8, and it is refused with `ERR_PUBLICATION_SUSPENDED` when the publication is not `ACTIVE`. A successful request creates a payout in `REQUESTED`, moves the requested amount out of `payout_balance_cents` and into `pending_payout_cents`, and increments the publication's `version`. A platform administrator later settles the payout by supplying an `outcome`. Settling as paid moves the payout from `REQUESTED` to the terminal `PAID`, decreases `pending_payout_cents` and increases `lifetime_paid_out_cents` by the payout's `amount_cents`, and stamps `settled_at`. Settling as failed moves the payout from `REQUESTED` to the terminal `FAILED`, and as a compensation releases the hold — decreasing `pending_payout_cents` and increasing `payout_balance_cents` by the amount — restoring the money invariant, and stamps `settled_at`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, including state transitions and simulations, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/publications` | Create a publication | Creator |
| GET | `/publications/{id}` | Get a publication | Anonymous, Member, Creator, Moderator, PlatformAdmin |
| POST | `/publications/{id}/suspend` | Suspend a publication | PlatformAdmin |
| POST | `/publications/{id}/deliverability-reset` | Reset bounce counters and deliverability posture | Creator, PlatformAdmin |
| GET | `/publications/{id}/analytics` | Computed analytics snapshot | Creator, PlatformAdmin |
| POST | `/publications/{id}/tiers` | Create a subscription tier | Creator |
| GET | `/publications/{id}/tiers` | List tiers of a publication | Anonymous, Member, Creator, PlatformAdmin |
| POST | `/publications/{id}/members` | Register a member | Anonymous, Creator |
| GET | `/publications/{id}/members` | List members | Creator, PlatformAdmin |
| GET | `/members/{memberId}` | Get a member | Member, Creator, PlatformAdmin |
| POST | `/members/{memberId}/verify` | Verify member email with token | Anonymous, Member |
| POST | `/members/{memberId}/subscriptions` | Create a subscription to a tier | Member, Creator |
| GET | `/subscriptions/{subscriptionId}` | Get a subscription | Member, Creator, PlatformAdmin |
| GET | `/subscriptions` | List/filter subscriptions (optional `member_id` and `tier_id` query filters) | Member, Creator, PlatformAdmin |
| POST | `/subscriptions/{subscriptionId}/change-tier` | Change tier with proration | Member, Creator |
| POST | `/subscriptions/{subscriptionId}/cancel` | Cancel a subscription | Member, Creator |
| POST | `/subscriptions/{subscriptionId}/reactivate` | Win-back reactivation | Member, Creator |
| POST | `/subscriptions/{subscriptionId}/renew` | Advance period and issue a renewal invoice | PlatformAdmin, Creator |
| GET | `/invoices/{invoiceId}` | Get an invoice | Member, Creator, PlatformAdmin |
| GET | `/invoices` | List/filter invoices (optional `subscription_id` query filter) | Member, Creator, PlatformAdmin |
| POST | `/_payments/simulate` | Simulate a payment-gateway outcome on an invoice | PlatformAdmin |
| POST | `/publications/{id}/posts` | Create a post or newsletter draft | Creator |
| GET | `/publications/{id}/posts` | List posts | Anonymous, Member, Creator, PlatformAdmin |
| GET | `/posts/{postId}/content` | Read gated content body | Member, Creator |
| POST | `/posts/{postId}/publish` | Publish a post | Creator |
| POST | `/posts/{postId}/send` | Send a newsletter to eligible members | Creator |
| POST | `/publications/{id}/events` | Create an event | Creator |
| GET | `/publications/{id}/events` | List events | Anonymous, Member, Creator, PlatformAdmin |
| POST | `/events/{eventId}/registrations` | Register the acting member for an event | Member |
| GET | `/registrations/{registrationId}` | Get a registration | Member, Creator, PlatformAdmin |
| GET | `/registrations` | List/filter registrations (optional `event_id` and `member_id` query filters) | Member, Creator, PlatformAdmin |
| POST | `/registrations/{registrationId}/cancel` | Cancel a registration | Member |
| POST | `/posts/{postId}/comments` | Post a comment | Member |
| GET | `/comments/{commentId}` | Get a comment | Anonymous, Member, Creator, Moderator, PlatformAdmin |
| GET | `/comments` | List/filter comments (optional `post_id` and `member_id` query filters) | Anonymous, Member, Creator, Moderator, PlatformAdmin |
| POST | `/comments/{commentId}/moderate` | Moderate a comment | Moderator, Creator |
| POST | `/publications/{id}/payouts` | Request a payout | Creator |
| GET | `/publications/{id}/payouts` | List payouts | Creator, PlatformAdmin |
| POST | `/payouts/{payoutId}/settle` | Settle a payout | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/_email/bounce` | Record a hard email bounce for a member | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_PUBLICATION_NOT_FOUND` | 404 |
| `ERR_TIER_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_POST_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_EMAIL_TAKEN` | 409 |
| `ERR_TIER_RANK_TAKEN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_REGISTERED` | 409 |
| `ERR_PUBLICATION_SUSPENDED` | 409 |
| `ERR_MEMBER_NOT_VERIFIED` | 409 |
| `ERR_TIER_PUBLICATION_MISMATCH` | 409 |
| `ERR_SUBSCRIPTION_REQUIRED` | 403 |
| `ERR_TIER_TOO_LOW` | 403 |
| `ERR_DELIVERABILITY_SUSPENDED` | 409 |
| `ERR_REGISTRATION_CLOSED` | 409 |
| `ERR_WINBACK_WINDOW_EXPIRED` | 409 |
| `ERR_PERIOD_NOT_ENDED` | 409 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_SEND_WINDOW_CONFLICT` | 409 |
| `ERR_EVENT_FULL` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_STALE_PUBLICATION_VERSION` | 412 |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 |

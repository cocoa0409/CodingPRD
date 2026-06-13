# Reward Crowdfunding API — Product Requirements Document

## 1. Introduction

Reward crowdfunding turns an idea into a pre-sale: a creator publishes a campaign with a funding goal and a deadline, supporters back it by pledging money in exchange for tangible rewards, and money only changes hands when the campaign closes. This API is the settlement backbone behind such a platform. It must hold an honest, moment-to-moment picture of how much a campaign has raised while it is running, decide at the deadline which pledges actually pay, and then either fulfil the rewards or return every backer's money — all without ever double-counting a limited reward or charging a card that the campaign never earned.

The domain is deceptively rich. A single campaign carries reward tiers (some of them limited in quantity, some of them time-windowed "early-bird" tiers), stretch goals that unlock as momentum builds, optional add-on products that backers bolt onto their pledge, and a stream of pledges whose payment fate is only resolved at the deadline. Two funding philosophies coexist: **all-or-nothing**, where nobody pays unless the goal is reached, and **flexible**, where the creator keeps whatever was raised. The platform must model both, settle each pledge through a simulated payment processor in a deterministic order, and cascade the result through reward inventory, backer reliability statistics, shipping surveys, and refunds.

This document specifies the complete contract: the shape of every response, the lifecycle of every entity, the precise arithmetic of every derived amount, and the order in which validations fire. Three roles operate the system — a platform operator who runs registration and settlement, creators who own campaigns, and backers who own pledges. The sections that follow define their permissions, the global response and concurrency rules, and then the business workflows in detail.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is absent, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401) before any other processing. If both headers are present but the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `PlatformAdmin`, `Creator`, and `Backer`.

A `PlatformAdmin` operates registration, settlement, payment-authorization queueing, and the server clock. This role is **opaque**: when `X-User-Role` is `PlatformAdmin`, the `X-User-ID` is an operator identifier that is not tied to any persisted business entity. The server may accept and act on it, but it does not compare it against any entity's `id` for ownership purposes.

A `Creator` is **entity-backed by the `Creator` entity**: when `X-User-Role` is `Creator`, the `X-User-ID` is the `id` of the acting `Creator`. Ownership checks on any resource that traces back to a creator compare against this value — for a campaign, the resource's `creator_id` must equal `X-User-ID`; for a tier, stretch goal, add-on product, or shipment action, the owning campaign's `creator_id` must equal `X-User-ID`.

A `Backer` is **entity-backed by the `Backer` entity**: when `X-User-Role` is `Backer`, the `X-User-ID` is the `id` of the acting `Backer`. Ownership checks on a pledge compare the pledge's `backer_id` against `X-User-ID`.

When an entity-backed user is authenticated and authorized for the operation type but is not the owner of the specific target resource, the request is rejected with `ERR_NOT_OWNER` (HTTP 403). This applies to creator-owned actions (launching, cancelling, creating tiers/stretch-goals/add-on-products, marking shipped) and backer-owned actions (cancelling a pledge, completing a survey).

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

All collection (list) endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and must be at least 0. A request whose `limit` falls outside the inclusive range from 1 to 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

List endpoints return their results sorted by `created_at` in ascending order, with ties broken by server insertion order (never by `id`). The pagination fields reported back in the `meta` object are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all matching records before the limit/offset window is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is an opaque UUID with no type prefix; clients never supply it. Every resource also carries a `created_at` timestamp, recorded as an ISO 8601 UTC instant with three fractional digits, fixed at creation and never changed.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` is refreshed on every mutation, including mutations that arrive as cascaded side effects of operations on other resources. The `version` starts at 1 when the resource is created and increments by one on every mutation, again including cascaded side effects. The entities that carry the full set — `id`, `created_at`, `updated_at`, and `version` — are `Creator`, `Backer`, `Campaign`, `RewardTier`, `StretchGoal`, `AddOn`, `Pledge`, and `FulfillmentSurvey`.

Three entities are append-only event records and therefore carry only `id` and `created_at`, with **no** `updated_at` and **no** `version`: the pledge add-on line (`PledgeAddOn`), the payment authorization record (`PaymentAuthorization`), and the refund record (`Refund`). For these three, do not expect an `updated_at` field or a `version` field in the response.

### 2.5. Monetary Precision and Rounding

All monetary amounts are expressed and stored as integer cents; there are no fractional cents anywhere in storage. Where a calculation introduces a fraction — the platform fee and the backer reliability score being the only two — the result is rounded **half-up**. The platform fee is rounded half-up to whole cents, and the reliability score is rounded half-up to one decimal place. The exact ordering of rounding-then-summing for the platform fee is specified in §3 and must be followed precisely, because it produces results that differ observably from summing-then-rounding.

### 2.6. Nested Resource Resolution

Many endpoints address a resource through a path that names a parent before a child — for example a pledge reached beneath its campaign, or a survey action reached beneath its pledge. Path-referenced resources are validated left-to-right: the leftmost identifier is checked first, and if any identifier in the path names a resource that does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before deeper identifiers or the request body are examined. The path variables used to address single resources are `creator_id`, `backer_id`, `campaign_id`, `tier_id`, `stretch_goal_id`, `addon_id`, `pledge_id`, `pledge_addon_id`, `authorization_id`, `refund_id`, and `survey_id`; each is resolved this way against its owning collection.

### 2.7. Optimistic Concurrency on Pledge Creation

Creating a pledge against a campaign is the one write that participates in optimistic concurrency control. The create request must carry a field named `expected_campaign_version` whose value is the `version` of the target campaign as the client last observed it; this field is required, not optional, and an absent or non-integer `expected_campaign_version` is rejected as a body well-formedness failure with `ERR_INVALID_REQUEST` (HTTP 422), distinct from the stale-version comparison below. The server compares `expected_campaign_version` against the campaign's current `version`. If they do not match — because another pledge create, a stretch-goal unlock, or an inventory recompute has advanced the campaign's `version` since the client last read it — the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). The rejection protects the client from committing a pledge against a stale view of remaining tier inventory and projected raise. No other endpoint accepts or requires a version field.

### 2.8. Cascading Consistency and Derived Fields

This system maintains a number of fields whose values are derived from other records and must always be reconciled in the same request that changes their inputs — never lazily. A campaign's projected and settled raise, a tier's and an add-on's claimed quantity, a stretch goal's unlocked flag, and a backer's lifetime contributions and reliability score are all derived fields. When an operation changes an input to a derived field, the owning record is updated in the same request, and that update — like any mutation — refreshes the record's `updated_at` and increments its `version`. A single backer-facing action can therefore ripple outward: creating a pledge recomputes the tier's claimed quantity, may flip the tier's inventory state, recomputes the campaign's projected raise, may unlock a stretch goal, and increments the campaign's `version`. The detailed cascades, including the multi-level ones that fire at close, are specified per workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Registration, Currency, and the Campaign Skeleton

Before any campaign exists, the platform operator registers the participants. Registering a creator supplies a `display_name` and a `payout_currency`, the latter being an ISO-4217 currency code such as USD; every campaign that creator owns will settle in this currency. Registering a backer supplies an `email` and a `display_name`. A freshly registered backer begins with no contribution history: `lifetime_authorized_cents` and `lifetime_captured_cents` are zero, `declined_auth_count` is zero, and `reliability_score` starts at its base value of 100.0 (the meaning of that starting value is explained in §3.7).

A creator builds a campaign as a skeleton in `DRAFT`. Creating a campaign supplies the owning `creator_id`, a `title`, a `funding_goal_cents`, a `funding_model`, and a `deadline_utc`. The `funding_goal_cents` must be greater than zero. The body is checked for well-formedness first (required fields present, `funding_goal_cents` a positive integer, `funding_model` a valid enum, `deadline_utc` a parseable ISO 8601 timestamp), failing with `ERR_INVALID_REQUEST` (HTTP 422); then the named `creator_id` must resolve to a real creator, failing with `ERR_NOT_FOUND` (HTTP 404) if it does not; then the supplied `creator_id` must equal the acting creator's `X-User-ID`, failing with `ERR_NOT_OWNER` (HTTP 403) otherwise. The `funding_model` is one of exactly two values, `ALL_OR_NOTHING` or `FLEXIBLE`. The `deadline_utc` is the instant at which the campaign closes, an ISO 8601 UTC timestamp. At creation, the campaign's `currency` is copied from the owning creator's `payout_currency` and thereafter governs every tier, add-on, and pledge beneath it; its `status` is `DRAFT`; its `committed_amount_cents`, `settled_amount_cents`, and `goal_met` are not yet meaningful (settled raise and goal-met remain null until closing begins); its `launched_at` is null; and its `version` is 1.

While the campaign is still in `DRAFT`, the creator populates it. Reward tiers and stretch goals may be created only while the campaign is in `DRAFT`. Add-on products may be created while the campaign is in `DRAFT` or `LIVE`. Each of these creations is owner-scoped: only the creator who owns the campaign may add to it.

### 3.2. Reward Tiers, Early-Bird Windows, and Inventory

A reward tier is the unit a backer pledges against. Creating a tier supplies a `title`, a `price_cents` (the minimum pledge price for the tier, which must be greater than zero), an optional `limit_quantity`, a `weight_grams` (the per-unit shipping weight, which must be at least zero), and the early-bird fields described below. The `limit_quantity`, when supplied, must be greater than zero and caps how many units may be claimed; when omitted or null, the tier is unlimited. A new tier starts with `status` of `AVAILABLE` and `claimed_quantity` of 0.

A tier's `claimed_quantity` is the count of pledges that currently hold a unit of it — specifically, pledges on this tier whose `status` is `ACTIVE` and whose `payment_status` is neither `AUTH_DECLINED` nor `REFUNDED`. It is recomputed whenever a pledge is created on the tier, whenever a pledge is cancelled, and whenever a pledge releases its claim at close because its authorization was declined. A tier becomes `SOLD_OUT` exactly when its `limit_quantity` is not null and, after a claiming pledge, its `claimed_quantity` is equal to its `limit_quantity` — the boundary is "equal to or greater than the limit", not "strictly greater". While `SOLD_OUT`, the tier blocks new pledges. The reverse transition is just as live: when a pledge cancels or a declined authorization releases a unit and the tier's `claimed_quantity` falls below `limit_quantity` again, a `SOLD_OUT` tier returns to `AVAILABLE` and accepts pledges once more. This `AVAILABLE` ↔ `SOLD_OUT` cycling continues for as long as the campaign is `LIVE`.

Some tiers are time-windowed early-bird tiers. The `is_early_bird` flag defaults to false; when true, the tier carries an `available_from` and an `available_until` that bound a half-open availability window `[available_from, available_until)` — the start instant is included and the end instant is excluded. When `is_early_bird` is false, both window fields are null. The `available_until` must be strictly after `available_from`. Early-bird tiers on the same campaign must be separated by a buffer gap: a new early-bird window must be separated from every existing early-bird tier's window on that campaign by at least one hour (3600 seconds). Concretely, the new window and an existing window are too close — and the new tier is rejected with `ERR_TIER_WINDOW_OVERLAP` (HTTP 409) — whenever the new window's start is earlier than the existing window's end plus one hour **and** the existing window's start is earlier than the new window's end plus one hour. Mere adjacency is not enough separation: two early-bird windows that merely touch end-to-start, with a gap of zero, are still rejected; only a genuine gap of at least one hour between them is accepted.

### 3.3. Stretch Goals and the Unlock Threshold

A stretch goal is a milestone above the funding goal that "unlocks" as the campaign gathers momentum. Creating a stretch goal supplies a `title` and a `threshold_cents`, the committed amount at or above which the goal unlocks. The `threshold_cents` must be strictly greater than the campaign's `funding_goal_cents`. A new stretch goal begins locked, with its `unlocked` flag false.

Whether a stretch goal is unlocked is a live, two-directional function of the campaign's raise. While the campaign is `LIVE`, the basis for comparison is the campaign's projected raise, `committed_amount_cents`; once the campaign has closed, the basis is the settled raise, `settled_amount_cents`. The goal's `unlocked` flag is true exactly when that basis is at or above the goal's `threshold_cents` — the boundary is "at or above the threshold", evaluated with greater-than-or-equal, not strictly greater. Because the basis can both rise and fall while a campaign is `LIVE`, the flag tracks it in both directions: when a new pledge pushes the projected raise to or past the threshold, the goal moves from `LOCKED` to `UNLOCKED`; when a pledge cancellation drops the projected raise back below the threshold, the goal moves from `UNLOCKED` back to `LOCKED`.

### 3.4. Add-On Products and Their Inventory

An add-on product is something a backer can attach to a pledge on top of the chosen tier. Creating an add-on product supplies a `title`, a `price_cents` (per-unit price, which must be greater than zero), an optional `limit_quantity`, and a `weight_grams` (per-unit shipping weight, at least zero). The `limit_quantity`, when supplied, must be greater than zero and caps the total units claimable across all pledges; when null, the add-on is unlimited. A new add-on product starts with `claimed_quantity` of 0.

An add-on's `claimed_quantity` is the total quantity claimed across the campaign: the sum of the `quantity` on every add-on line that references this add-on and sits on a non-released pledge — that is, a pledge whose `status` is `ACTIVE` and whose `payment_status` is neither `AUTH_DECLINED` nor `REFUNDED`. It is recomputed when a line is attached, when a pledge is cancelled, and when inventory is released at close. Unlike a tier, an add-on has no public inventory state field; its availability is enforced at attach time (see §3.5).

### 3.5. Pledging: Composing a Backer's Commitment

Once a campaign is `LIVE`, backers pledge. Creating a pledge is owned by the backer and supplies a `backer_id`, a `tier_id`, a `pledge_amount_cents`, a `destination_zone`, and the `expected_campaign_version` described in §2.7. The `destination_zone` is one of exactly two values, `DOMESTIC` or `INTL`. A new pledge begins with `status` of `ACTIVE`, `payment_status` of `PENDING_AUTH`, and `fulfillment_status` of `NOT_STARTED`.

Several conditions guard pledge creation, and they are evaluated in a fixed precedence so that the most fundamental failures surface first. Authentication is checked first: missing headers yield `ERR_MISSING_AUTH`, and a role not permitted to pledge yields `ERR_ROLE_FORBIDDEN`. Next, existence of the path-named campaign is checked, yielding `ERR_NOT_FOUND` if it is absent. Then the body's foreign keys are resolved — the `tier_id` must name a tier belonging to this campaign and the `backer_id` must name a real backer — failing with `ERR_FK_INVALID` (HTTP 422) otherwise. Then the body is checked for well-formedness — required fields present, enums valid, integers positive where required — failing with `ERR_INVALID_REQUEST` (HTTP 422). Then ownership is checked: the acting `Backer` (`X-User-ID`) must equal the body's `backer_id`, failing with `ERR_NOT_OWNER` (HTTP 403) otherwise. After that the campaign must be in a state that permits the transition, failing with `ERR_INVALID_STATE` (HTTP 409) if not. Then the temporal gate: pledging is allowed only while the campaign is `LIVE` and the clock is still before `deadline_utc`; a pledge against a campaign that is not live, or whose deadline has passed, is rejected with `ERR_CAMPAIGN_NOT_LIVE` (HTTP 409). (There is no campaign-state condition for pledge creation that is distinct from this temporal gate, so the not-`LIVE` case is reported as `ERR_CAMPAIGN_NOT_LIVE` rather than `ERR_INVALID_STATE`.) Then the pledge amount is checked: `pledge_amount_cents` must be at least the tier's `price_cents`, failing with `ERR_PLEDGE_BELOW_TIER_MIN` (HTTP 422) when it is below. Then tier inventory is checked: the tier must be `AVAILABLE` and, when its `limit_quantity` is not null, its `claimed_quantity` must still be below the limit, failing with `ERR_TIER_SOLD_OUT` (HTTP 409). And finally the optimistic-concurrency check on `expected_campaign_version` fires, failing with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). In short, the ordering is authentication, then role, then path existence, then foreign-key resolution, then body well-formedness, then state, then the live-window temporal gate, then the tier-minimum amount check, then tier inventory, then the stale-version check.

When a pledge is accepted, the platform computes its money. The pledge's items subtotal, `items_subtotal_cents`, is the backer's chosen `pledge_amount_cents` plus the sum of every attached add-on line's total; at creation, with no add-on lines yet attached, the items subtotal equals the pledge amount. The pledge's `shipping_cents` is computed from weight and destination as described in §3.6, and the pledge's `committed_amount_cents` — the amount that will be authorized at close — is the items subtotal plus the shipping. Creating the pledge then recomputes the tier's `claimed_quantity` (possibly flipping it to `SOLD_OUT`), recomputes the campaign's projected raise `committed_amount_cents` (possibly unlocking a stretch goal), and increments the campaign's `version` by one.

A backer may attach add-on lines to their own pledge while the campaign is `LIVE`. Attaching a line supplies an `addon_id` and a `quantity` (units of the add-on, which must be greater than zero). The attach guards fire in a fixed precedence: first the path-named pledge must exist (`ERR_NOT_FOUND` if absent); then the `addon_id` must resolve to a real add-on, failing with `ERR_FK_INVALID` (HTTP 422) otherwise (a missing or non-string `addon_id` also surfaces as `ERR_FK_INVALID`); then the body must be well-formed, with `quantity` a positive integer, failing `ERR_INVALID_REQUEST` (HTTP 422); then the acting backer must own the pledge, failing `ERR_NOT_OWNER` (HTTP 403); then the pledge itself must still be `ACTIVE`, failing `ERR_INVALID_STATE` (HTTP 409) if it is not; then the owning campaign must be `LIVE` and the clock still before `deadline_utc`, failing `ERR_CAMPAIGN_NOT_LIVE` (HTTP 409) when the campaign is not `LIVE` or its deadline has passed; then the same-campaign check below; and finally add-on inventory. The add-on must belong to the same campaign as the pledge; an add-on from another campaign is rejected with `ERR_CURRENCY_MISMATCH` (HTTP 422), since cross-campaign means cross-currency. Add-on inventory is enforced here: the attach is rejected with `ERR_ADDON_SOLD_OUT` (HTTP 409) when the add-on's `limit_quantity` is not null and its current `claimed_quantity` plus the requested `quantity` would exceed the limit — the boundary is that claimed-plus-requested must not go above the limit; landing exactly on the limit is allowed. A successful attach records the line's `line_total_cents` as the requested `quantity` multiplied by the add-on's `price_cents` at attach time, then recomputes the pledge's `items_subtotal_cents`, `shipping_cents`, and `committed_amount_cents`, and recomputes the add-on's `claimed_quantity` and the campaign's projected `committed_amount_cents`.

A backer may cancel their own pledge while the campaign is `LIVE`. Cancelling is allowed only when the pledge is still `ACTIVE` and the owning campaign's `status` is `LIVE`; a cancel against a pledge that is no longer `ACTIVE`, or against a campaign that is no longer `LIVE` (for example a campaign that has already closed to `SUCCESSFUL`, `FAILED`, or `CANCELED`), is rejected with `ERR_INVALID_STATE` (HTTP 409). (The `ERR_CAMPAIGN_NOT_LIVE` code is reserved for pledge creation and add-on attachment; it is not used by pledge cancellation.) Cancellation sets the pledge's `status` to `CANCELED`, releases its tier claim and every add-on claim it held (recomputing the tier's and add-ons' `claimed_quantity`, and returning a `SOLD_OUT` tier to `AVAILABLE` if it now sits below its limit), recomputes the campaign's projected `committed_amount_cents` (which may re-lock a stretch goal), and increments the campaign's `version`.

### 3.6. Computing Shipping and the Committed Amount

The shipping component of a pledge is driven by the combined weight of the chosen tier and all attached add-on lines, together with the destination zone. The total shipping weight in grams is the tier's `weight_grams` plus, for each attached add-on line, that line's `quantity` multiplied by its add-on's `weight_grams`. That gram total is converted to billable kilograms by dividing by 1000 and rounding **up** to the next whole kilogram (a partial kilogram always rounds up to the next whole kilogram).

The shipping charge then depends on the `destination_zone`. For a `DOMESTIC` destination, the shipping is a base of 500 cents plus 150 cents for every billable kilogram. For an `INTL` destination, the shipping is a base of 1500 cents plus 400 cents for every billable kilogram. Whichever zone applies, the resulting shipping charge is then capped: if it exceeds 5000 cents, it is reduced to 5000 cents. This capped figure is the pledge's `shipping_cents`.

The pledge's `committed_amount_cents` is then the `items_subtotal_cents` plus the `shipping_cents`, all in integer cents. Because every input — the pledge amount, the add-on line totals, the weights, and the zone — feeds this single figure, the committed amount is recomputed from scratch every time a line is attached or the pledge is first created.

### 3.7. Backer Reliability and Lifetime Contributions

Each backer carries denormalized statistics that the platform refreshes as their pledges reach payment decisions. Two of them track money. The `lifetime_authorized_cents` is the optimistic figure: the sum of `committed_amount_cents` across all of this backer's pledges whose `payment_status` is either `AUTHORIZED` or `CAPTURED`. The `lifetime_captured_cents` is the realized figure: the sum of `committed_amount_cents` across only those of this backer's pledges whose `payment_status` is `CAPTURED`. The two differ precisely by the pledges that have been authorized but not yet captured.

The backer also carries a `declined_auth_count`, the number of this backer's pledges whose `payment_status` is `AUTH_DECLINED`, and a `reliability_score` in the range from 0 to 100. The reliability score is a weighted measure of how often this backer's pledges actually clear authorization. Consider only the backer's pledges that have reached an authorization decision — those whose `payment_status` is `AUTHORIZED`, `CAPTURED`, or `AUTH_DECLINED`; call this count the total. If the total is zero — the backer has no decided pledges, only ones still `PENDING_AUTH` (or ones refunded due to a failed campaign, which do not penalize the backer) — the `reliability_score` is the base value of 100.0. Otherwise, let the count of "good" pledges be those whose `payment_status` is `AUTHORIZED` or `CAPTURED`; the score is the good count divided by the total count, multiplied by 100, and rounded half-up to one decimal place.

This produces a deliberately two-faced figure across a pledge's life. A backer whose only pledge is still `PENDING_AUTH` shows a provisional `reliability_score` of 100.0, because nothing has been decided. If that single pledge is then declined at close, the same backer's score becomes 0.0 — a good count of zero over a total of one. The provisional reading and the final reading therefore diverge on the very same pledge as soon as an authorization decision lands. These statistics — `lifetime_authorized_cents`, `lifetime_captured_cents`, `declined_auth_count`, and `reliability_score` — are recomputed as cascaded side effects every time one of this backer's pledges changes payment status, whether to `AUTHORIZED`, `AUTH_DECLINED`, `CAPTURED`, or `REFUNDED`.

### 3.8. Queuing Authorizations and Reaching the Deadline

A pledge does not charge anything when it is made; it merely commits a `committed_amount_cents` that will be authorized at the campaign's close. To make settlement deterministic and testable, the platform operator queues, for each pledge, a simulated processor outcome ahead of close. Recording an authorization supplies an `outcome` that is one of exactly two values, `SUCCEEDED` or `DECLINED`, and returns the created authorization record (HTTP 201). The stored authorization snapshots the pledge's `committed_amount_cents` into its own `amount_cents` at the moment it is recorded, and it is consumed when the campaign closes. If more than one authorization has been queued for the same pledge, the one consumed at close is the most recently created — by ascending `(created_at, insertion order)`, the last queued wins.

The platform also runs a logical clock that drives time-based behavior. An admin capability sets the server's current UTC clock to a supplied `now_utc` without closing anything. A separate admin capability advances the clock to a supplied `now_utc` and, as it does, automatically closes any `LIVE` campaign whose `deadline_utc` is at or before the new clock value, running that campaign through its full settlement cascade; when several campaigns are due at once they are settled in ascending `(created_at, insertion order)`. Both clock capabilities require a parseable ISO 8601 `now_utc` (rejected with `ERR_INVALID_REQUEST` otherwise) and return an empty data object on success (HTTP 200). A platform operator may also force a specific campaign to close immediately; the target campaign must currently be `LIVE`, and a force-close of a campaign that is in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — this status check is applied before the closable-time gate. Force-closing is then permitted only once the clock has reached or passed the campaign's `deadline_utc`, and an attempt before that point is rejected with `ERR_NOT_CLOSABLE` (HTTP 409). The state machine itself requires the same gate: the move from `LIVE` to `CLOSING` requires that the current clock is at or after `deadline_utc`.

### 3.9. Settlement: From CLOSING to SUCCESSFUL or FAILED

When a campaign reaches its deadline it moves from `LIVE` to `CLOSING`, and the settlement engine resolves every pledge. The engine replays the campaign's pledges that are still `ACTIVE` and `PENDING_AUTH` in chronological order — ascending by `created_at`, with ties broken by `created_at` and never by `id`. For each such pledge it consumes the queued authorization: if the outcome was `SUCCEEDED`, the pledge's `payment_status` advances from `PENDING_AUTH` to `AUTHORIZED` and its `committed_amount_cents` is added to the running settled total; if the outcome was `DECLINED`, the pledge's `payment_status` advances from `PENDING_AUTH` to `AUTH_DECLINED`. A pledge for which no authorization was ever queued is treated exactly as a `DECLINED` outcome: it advances to `AUTH_DECLINED` and is excluded from the settled total. A pledge moving to `AUTHORIZED` recomputes its backer's `lifetime_authorized_cents` and `reliability_score`. A pledge moving to `AUTH_DECLINED` releases the tier inventory and add-on inventory it held — recomputing the tier's `claimed_quantity`, returning a `SOLD_OUT` tier to `AVAILABLE` if it now sits below its limit, and recomputing each affected add-on's `claimed_quantity` — and recomputes its backer's `declined_auth_count` and `reliability_score`.

The campaign's `settled_amount_cents` is the sum of `committed_amount_cents` over the pledges that are now `AUTHORIZED` (together with any pledges that were already `AUTHORIZED` or `CAPTURED` before close). This is the realized raise, and it differs from the projected raise the campaign showed while `LIVE` precisely by the total `committed_amount_cents` of every pledge whose authorization was declined: the projected `committed_amount_cents` while `LIVE` counts every `ACTIVE` pledge whose `payment_status` is `PENDING_AUTH`, `AUTHORIZED`, or `CAPTURED`, whereas the settled figure counts only those that ended up `AUTHORIZED` or `CAPTURED`. Once `settled_amount_cents` is known, the campaign's `goal_met` is set true exactly when the settled amount is at or above the `funding_goal_cents`, and false otherwise.

From `CLOSING`, the campaign forks. It becomes `SUCCESSFUL` when the funding model is `FLEXIBLE`, or when the model is `ALL_OR_NOTHING` and `goal_met` is true. On success, every `AUTHORIZED` pledge has its `payment_status` advance from `AUTHORIZED` to `CAPTURED`; each captured pledge has its `fulfillment_status` advance from `NOT_STARTED` to `SURVEY_SENT` with a new `FulfillmentSurvey` row created (its `completed` flag false); each captured pledge's backer has `lifetime_captured_cents` and `reliability_score` recomputed; and every tier on the campaign is retired, its `status` moving to `RETIRED`.

The campaign becomes `FAILED` instead when the model is `ALL_OR_NOTHING` and `goal_met` is false. On failure, every `AUTHORIZED` pledge has its `payment_status` advance from `AUTHORIZED` to `REFUNDED`, and for each such pledge a `Refund` row is created whose `reason` is `FAILED_CAMPAIGN` and whose `amount_cents` equals the pledge's `committed_amount_cents` at that moment (a refund's `reason` is one of `FAILED_CAMPAIGN` or `BACKER_CANCEL`). Each refunded pledge then releases its tier and add-on inventory, recomputing the affected `claimed_quantity` values. As on success, every tier on the campaign is retired to `RETIRED`. This is a three-level cascade: finalizing as failed refunds the pledge, which in turn releases tier and add-on inventory.

Across both forks the campaign's `version` is incremented for each transition it makes, and any record touched by the cascade — pledges, tiers, add-ons, surveys, backers — has its own `updated_at` refreshed and its own `version` incremented as it is mutated.

### 3.10. Cancelling a Campaign

A creator may cancel their own campaign while it is in `DRAFT` or `LIVE`. Cancellation moves the campaign's `status` to `CANCELED`. Every `ACTIVE` pledge whose `payment_status` is `PENDING_AUTH` or `AUTHORIZED` is unwound: a pledge that had already reached `AUTHORIZED` has its `payment_status` moved to `REFUNDED` and a `Refund` row created with reason `FAILED_CAMPAIGN`; a pledge still `PENDING_AUTH` is simply voided. In all these cases the pledge's `status` becomes `CANCELED`. The cancellation then releases all tier and add-on inventory and retires every tier to `RETIRED`, and it increments the campaign's `version`.

### 3.11. Fulfillment: Surveys and Shipping

Fulfillment runs on its own axis, independent of payment, and only begins after a pledge has been captured by a successful campaign. When the campaign succeeds, each captured pledge's `fulfillment_status` moves from `NOT_STARTED` to `SURVEY_SENT` and the platform creates the pledge's `FulfillmentSurvey` with its `completed` flag false.

The owning backer then completes the survey, advancing the pledge's `fulfillment_status` from `SURVEY_SENT` to `SURVEY_COMPLETE`. Completing the survey supplies a `shipping_address`, which is written onto the survey, and sets the survey's `completed` flag to true. This is permitted only when the pledge's `payment_status` is `CAPTURED` and the pledge's `FulfillmentSurvey` exists with `completed` still false; an attempt to submit before the pledge is captured, or to submit a survey that is already complete, is rejected with `ERR_SURVEY_NOT_READY` (HTTP 409). Only the backer who owns the pledge may complete its survey. The guards fire in the order: pledge existence (`ERR_NOT_FOUND`), then `shipping_address` well-formedness as a non-empty string (`ERR_INVALID_REQUEST`), then pledge ownership (`ERR_NOT_OWNER`), then the captured/incomplete-survey readiness checks (`ERR_SURVEY_NOT_READY`). The successful response (HTTP 200) returns the updated pledge object, not the survey.

Finally, the campaign's creator marks the reward shipped, advancing the pledge's `fulfillment_status` from `SURVEY_COMPLETE` to `SHIPPED`, which is terminal on the fulfillment axis. Shipping is permitted only when the pledge's `fulfillment_status` is `SURVEY_COMPLETE`; an attempt to ship a pledge in any other fulfillment status is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the creator who owns the campaign may mark it shipped (a non-owning creator is rejected with `ERR_NOT_OWNER`, checked before the fulfillment-status gate). The successful response (HTTP 200) returns the updated pledge object.

### 3.12. The Launch Gate and Same-Creator Window Exclusivity

Launching takes a campaign from `DRAFT` to `LIVE`, and it is the moment several invariants are enforced. Only the owning creator may launch. The campaign must have at least one reward tier whose `status` is `AVAILABLE`; a launch with no available tier is rejected with `ERR_NO_TIERS` (HTTP 409). The campaign's `deadline_utc` must be strictly after the current clock; a deadline at or before "now" is rejected with `ERR_DEADLINE_IN_PAST` (HTTP 422).

A creator may not run two campaigns whose live windows overlap. A campaign's prospective live window runs from the current clock up to its `deadline_utc`, treated as half-open `[current_clock, deadline_utc)`. The launch is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP` (HTTP 409) if the same creator already has another campaign whose `status` is `LIVE` and whose window overlaps — that is, when the current clock is strictly before that other campaign's `deadline_utc` and that other campaign's `launched_at` is strictly before this campaign's `deadline_utc`. Because the interval is half-open, two windows that merely touch at an endpoint do not overlap: a campaign whose launch instant coincides exactly with another's deadline is allowed. (Note the contrast with early-bird tier windows in §3.2, which instead demand a positive buffer gap and therefore reject mere adjacency.) On a successful launch, the campaign's `launched_at` is set to the current clock, its `committed_amount_cents` is initialized to 0, and its `version` is incremented.

## 4. Endpoint Definitions

Creating a brand-new resource returns HTTP 201. State transitions and other modifications of an existing resource return HTTP 200, as do reads. Error responses carry the status code listed in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/creators` | Register a creator | PlatformAdmin |
| GET | `/creators/{creator_id}` | Read a creator | PlatformAdmin, Creator, Backer |
| POST | `/backers` | Register a backer | PlatformAdmin |
| GET | `/backers/{backer_id}` | Read a backer, including reliability and lifetime contributions | PlatformAdmin, Creator, Backer |
| POST | `/campaigns` | Create a campaign in DRAFT | Creator |
| GET | `/campaigns` | List campaigns, filterable by `creator_id` | PlatformAdmin, Creator, Backer |
| GET | `/campaigns/{campaign_id}` | Read a campaign | PlatformAdmin, Creator, Backer |
| POST | `/campaigns/{campaign_id}/launch` | Launch a campaign from DRAFT to LIVE | Creator |
| POST | `/campaigns/{campaign_id}/close` | Force-close a LIVE campaign at/after its deadline and settle it | PlatformAdmin |
| POST | `/campaigns/{campaign_id}/cancel` | Cancel a DRAFT or LIVE campaign | Creator |
| GET | `/campaigns/{campaign_id}/settlement` | Read settled amount, platform fee, creator payout, and captured pledge count | PlatformAdmin, Creator |
| POST | `/campaigns/{campaign_id}/tiers` | Create a reward tier while the campaign is DRAFT | Creator |
| GET | `/tiers` | List reward tiers, filterable by `campaign_id` | PlatformAdmin, Creator, Backer |
| GET | `/tiers/{tier_id}` | Read a reward tier | PlatformAdmin, Creator, Backer |
| POST | `/campaigns/{campaign_id}/stretch-goals` | Create a stretch goal while the campaign is DRAFT | Creator |
| GET | `/stretch-goals` | List stretch goals, filterable by `campaign_id` | PlatformAdmin, Creator, Backer |
| GET | `/stretch-goals/{stretch_goal_id}` | Read a stretch goal | PlatformAdmin, Creator, Backer |
| POST | `/campaigns/{campaign_id}/add-on-products` | Create an add-on product while the campaign is DRAFT or LIVE | Creator |
| GET | `/add-on-products` | List add-on products, filterable by `campaign_id` | PlatformAdmin, Creator, Backer |
| GET | `/add-on-products/{addon_id}` | Read an add-on product | PlatformAdmin, Creator, Backer |
| POST | `/campaigns/{campaign_id}/pledges` | Create a pledge against a LIVE campaign | Backer |
| GET | `/pledges` | List pledges, filterable by `campaign_id`, `backer_id`, `tier_id` | PlatformAdmin, Creator, Backer |
| GET | `/pledges/{pledge_id}` | Read a pledge | PlatformAdmin, Creator, Backer |
| POST | `/pledges/{pledge_id}/add-ons` | Attach an add-on line to a pledge while the campaign is LIVE | Backer |
| POST | `/pledges/{pledge_id}/cancel` | Cancel one's own pledge while the campaign is LIVE | Backer |
| POST | `/pledges/{pledge_id}/survey` | Complete the fulfillment survey for one's own pledge | Backer |
| POST | `/pledges/{pledge_id}/ship` | Mark a surveyed pledge shipped | Creator |
| GET | `/pledge-add-ons` | List pledge add-on lines, filterable by `pledge_id`, `addon_id` | PlatformAdmin, Creator, Backer |
| GET | `/pledge-add-ons/{pledge_addon_id}` | Read a single pledge add-on line | PlatformAdmin, Creator, Backer |
| POST | `/pledges/{pledge_id}/authorization` | Queue a simulated processor outcome to apply at close | PlatformAdmin |
| GET | `/authorizations` | List payment authorizations, filterable by `pledge_id` | PlatformAdmin, Creator, Backer |
| GET | `/authorizations/{authorization_id}` | Read a single payment authorization | PlatformAdmin, Creator, Backer |
| GET | `/refunds` | List refunds, filterable by `pledge_id` | PlatformAdmin, Creator, Backer |
| GET | `/refunds/{refund_id}` | Read a single refund | PlatformAdmin, Creator, Backer |
| GET | `/surveys` | List fulfillment surveys, filterable by `pledge_id` | PlatformAdmin, Creator, Backer |
| GET | `/surveys/{survey_id}` | Read a single fulfillment survey | PlatformAdmin, Creator, Backer |
| POST | `/_clock/set` | Set the server's current UTC clock | PlatformAdmin |
| POST | `/_clock/advance` | Advance the clock and auto-close any due LIVE campaign | PlatformAdmin |

The settlement read returns the campaign's `settled_amount_cents`, the `platform_fee_cents`, the `creator_payout_cents`, and the `captured_pledge_count`. The platform fee is computed only over pledges whose `payment_status` is `CAPTURED` (that is, on a `SUCCESSFUL` campaign): for each captured pledge, its fee is the pledge's `committed_amount_cents` multiplied by the fee rate of 0.05 (five percent), rounded half-up to whole cents per pledge; the `platform_fee_cents` is then the sum of those per-pledge rounded fees. This per-pledge-rounding-then-summing order is mandatory and produces results that can differ from summing first and rounding once. The `creator_payout_cents` is the campaign's `settled_amount_cents` minus the `platform_fee_cents`. The settlement read is available for any campaign regardless of status: `settled_amount_cents` is reported exactly as stored on the campaign (so it is `null` until closing has populated it), `captured_pledge_count` and `platform_fee_cents` are 0 whenever there are no `CAPTURED` pledges, and the `creator_payout_cents` treats a still-`null` `settled_amount_cents` as 0 for the purpose of the subtraction.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH | 401 |
| ERR_ROLE_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_FK_INVALID | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_NO_TIERS | 409 |
| ERR_DEADLINE_IN_PAST | 422 |
| ERR_CAMPAIGN_NOT_LIVE | 409 |
| ERR_PLEDGE_BELOW_TIER_MIN | 422 |
| ERR_CURRENCY_MISMATCH | 422 |
| ERR_TIER_SOLD_OUT | 409 |
| ERR_ADDON_SOLD_OUT | 409 |
| ERR_STALE_CAMPAIGN_VERSION | 412 |
| ERR_NOT_CLOSABLE | 409 |
| ERR_SURVEY_NOT_READY | 409 |
| ERR_CAMPAIGN_WINDOW_OVERLAP | 409 |
| ERR_TIER_WINDOW_OVERLAP | 409 |
| ERR_VALIDATION_PAGINATION | 422 |

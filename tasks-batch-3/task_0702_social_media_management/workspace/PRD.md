# Social-Media Management API — Product Requirements Document

## 1. Introduction

Modern social-media agencies juggle dozens of brand accounts, each with its own roster of platform channels, a content calendar that must survive several rounds of internal review before anything is published, an advertising budget that has to be reserved and metered to the cent, and a steady stream of inbound comments and direct messages that someone has to triage. This document specifies the Social-Media Management API: a single back-office service that ties all of those concerns together for the account teams who run them.

The platform models the full operational arc of an engagement. An account team onboards a client and connects that client's channels; content creators draft posts that move through an approval pipeline with revision loops; approved posts are scheduled into per-channel timeline windows and then published across multiple platforms at once; a finance function reserves ad-boost budget against a monthly ceiling, records daily spend under a pacing cap, and settles unspent reservations back to the client; community agents work DM and comment threads to resolution; and the agency negotiates influencer collaborations, clears the rights on user-generated assets, and produces analytics snapshots at the close of each billing cycle. Because budget movement, post quotas, and channel limits are all derived from a retainer package whose terms are copied onto the client at activation, the API places strong emphasis on keeping these derived figures reconciled at every step.

The sections that follow define the system-wide contracts first — authentication, the response envelope, pagination, and the cross-cutting principles that govern consistency, budgeting precision, and concurrency — and then walk through the business workflows in detail. Endpoint and error-code summary tables close the document; the conditions that trigger each error live in the narrative, not in those tables.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly six roles, whose names must be spelled exactly as follows: `AccountManager`, `ContentCreator`, `Approver`, `CommunityAgent`, `FinanceController`, and `PlatformAdmin`. When a request is well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

All six roles use an **opaque** identity model: in every case `X-User-ID` is an opaque operator identifier that is not tied to the `id` of any persisted entity, and the server never compares it to an entity's `id` for ownership purposes. The server may, however, record an operator identifier where a workflow calls for it. When an `AccountManager` is the acting role, `X-User-ID` is an opaque operator id, and the same applies to `ContentCreator`, `Approver`, `FinanceController`, and `PlatformAdmin`. When a `CommunityAgent` is the acting role, `X-User-ID` is likewise opaque, but the server does persist it: claiming a conversation records the acting agent's `X-User-ID` onto the conversation's `assigned_agent_id`, and an outbound engagement message records its `author_agent_id` from the request rather than from any entity lookup. Two further opaque-operator fields are supplied by the client on creation rather than derived from the header: a client account names the owning operator in `account_manager_id`, and a content item names its drafting operator in `author_id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0.

Unless an endpoint explicitly states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Beyond `limit` and `offset`, most list endpoints accept additional filter query parameters drawn from the resource's own fields — for example a `status` filter narrows a listing to rows in a particular lifecycle `status`, and other entity-specific filters (such as `platform`, `entry_type`, or a parent foreign key) are available where the endpoint table indicates them.

### 2.4. Common Resource Properties

Most resources in this system are "full" resources carrying a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, used for identity only.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.7.

The following entities are full resources and carry all four fields: the client account, the retainer package, the channel, the content item, the content target, the schedule slot, the boost campaign, the conversation, the influencer collaboration, and the UGC asset.

Three entities are **lightweight** records that carry only `id` and `created_at`; they have neither `updated_at` nor `version`, because they are write-once audit or reporting rows. These are the engagement message, the analytics snapshot, and the ledger entry. When any of these is created it receives an `id` and a `created_at` but no `updated_at` and no `version`.

### 2.5. Hierarchical Consistency and Nested Retrieval

Resources reference one another by foreign key, and many operations cascade across more than one entity. Whenever an operation mutates an entity, that entity's `updated_at` is refreshed and its `version` is incremented; when an operation cascades into a second entity, the second entity is mutated in the same way. The specific cascades — releasing schedule slots when a channel disconnects, reverting scheduled content to approved, recomputing a client's budget fields after every boost movement, resolving a client's conversations on churn — are described in the workflow sections of §3, and each affected entity is independently bumped.

For any request whose path names a resource, the server validates the path identifier and rejects a request that names a non-existent resource. Where a path or create body names more than one resource, identifiers are validated left to right, and the first identifier that does not resolve produces that resource's not-found error before any later identifier is examined: `ERR_CLIENT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_CONTENT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_BOOST_NOT_FOUND`, `ERR_CONVERSATION_NOT_FOUND`, `ERR_COLLAB_NOT_FOUND`, or `ERR_ASSET_NOT_FOUND`, each returned with HTTP 404. A child whose foreign-key parent does not match a referenced path identifier is treated as not found. This same set of not-found errors applies when a foreign key in a create body — for example the `client_id` on a channel, the `content_item_id` and `channel_id` on a content target, or the `collab_id` on a UGC asset — fails to reference an existing parent of the correct type.

### 2.6. Budget Precision and Monetary Conservation

All monetary amounts in the system are integer cents and are computed exactly, with no rounding drift; there is never a fractional cent. Where a calculation divides — the engagement-rate basis points, the retainer churn proration, the per-deliverable collaboration bonus — the document specifies the exact rounding direction (round half up, ceiling, or floor) at the point of use; absent such an instruction, integer cents are exact.

A client's ad-boost budget obeys a conservation invariant that is recomputed from the underlying boost campaigns on every reservation, spend record, completion, cancellation, and on client activation. The client's `boost_reserved_cents` is the sum of `reserved_budget_cents` across that client's boost campaigns whose status is either `RESERVED` or `RUNNING`. The client's `boost_spent_cents` is the sum of `spent_budget_cents` across that client's boost campaigns whose status is either `RUNNING` or `COMPLETED`. The client's `boost_available_cents` is the boost budget limit minus reserved minus spent — that is, `boost_budget_limit_cents` less `boost_reserved_cents` less `boost_spent_cents` — and is never allowed to go below zero; if the subtraction would be negative it is held at zero. While the budget remains non-negative, the limit equals the sum of the reserved, spent, and available figures; the validations in §3 forbid any reservation that would over-allocate the ceiling, so the floor-at-zero clamp is only a safety net.

### 2.7. Optimistic Concurrency Control on Boost Reservation

Reserving budget for a boost campaign is the one operation in this system guarded by optimistic concurrency control, because two reservations against the same client both debit the shared `boost_available_cents`. The reserve request must carry an `expected_client_version` field whose value is the `version` of the owning client the caller last observed. The server compares `expected_client_version` to the owning client's current `version`. If they differ — meaning another writer has advanced the client's `version` since the caller last read it, and the caller's view of the available budget is therefore stale — the reservation is rejected with `ERR_STALE_CLIENT_VERSION` and HTTP 412. This prevents a caller from committing a reservation on top of a budget figure it never actually observed. The `expected_client_version` field is required on the reserve operation; no other endpoint in the system takes a version field, and the reserve operation is the only one that increments a client's `version`.

### 2.8. Billing Cycles and Quotas

Each client carries a deterministic billing-cycle counter, `current_cycle_index`, that starts at 0 and is advanced only by the cycle-close operation, which increments it by one. Closing a cycle resets the published-post tally for the new cycle: a client's `posts_published_this_cycle` is, by definition, the count of that client's content items whose status is `PUBLISHED` and whose `published_cycle_index` equals the client's current `current_cycle_index`, so immediately after a cycle close that count is recomputed to zero for the new cycle. A client's `monthly_post_quota` caps how many posts may be published in a single cycle and is copied from the active retainer package at activation. A client also exposes `open_conversation_count`, the count of conversations on that client's channels whose status is `OPEN`.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding, Retainer Packages, and Lifecycle

A new client account is created by an `AccountManager` or a `PlatformAdmin`, who supply the brand's `name` and the `account_manager_id` of the operator who will own the account. The account is born in `ONBOARDING` status with a `current_cycle_index` of 0 and every budget figure — `retainer_fee_cents`, `boost_budget_limit_cents`, `boost_reserved_cents`, `boost_spent_cents`, `boost_available_cents`, and `monthly_post_quota` — sitting at zero. The client's lifecycle moves through `ONBOARDING`, `ACTIVE`, `SUSPENDED`, and the terminal `CHURNED` status.

Before a client can go live it needs a commercial agreement. An `AccountManager` creates a retainer package for a client by referencing the `client_id` and choosing a `tier` of `STARTER`, `GROWTH`, or `SCALE`. The package records the `monthly_retainer_fee_cents` (which must be greater than zero), the `monthly_boost_budget_cents` (which must be zero or greater), the `monthly_post_quota` (which must be at least one), and the `included_channels` count (the maximum number of channels that may reach the live state under this package, at least one). A package is born in `DRAFT` status and moves through `ACTIVE` to the terminal `SUPERSEDED`. Activating a draft package promotes it to `ACTIVE`; if the same client already had another `ACTIVE` package, that prior package is automatically driven to `SUPERSEDED` by the same call. Re-activating a package that is already `ACTIVE` is not a valid transition and is rejected with `ERR_PACKAGE_ALREADY_ACTIVE`; activation is defined only out of `DRAFT`, so a package already in `SUPERSEDED` yields `ERR_INVALID_STATE` instead.

Activating the client itself, performed by an `AccountManager`, advances it from `ONBOARDING` to `ACTIVE`, but only when the client has exactly one retainer package in `ACTIVE` status and at least one of its channels has reached the live state; if neither precondition holds the transition is an invalid one. On activation the system copies the active package's terms onto the client — the package's `monthly_retainer_fee_cents` becomes the client's `retainer_fee_cents`, its `monthly_boost_budget_cents` becomes the client's `boost_budget_limit_cents`, and its `monthly_post_quota` becomes the client's `monthly_post_quota` — recomputes the client's available boost budget as the limit less reserved less spent, and writes a ledger entry of type `RETAINER_CHARGE` whose `amount_cents` is the positive retainer fee just copied and whose `cycle_index` is the client's current `current_cycle_index`.

A client in `ACTIVE` can be moved to `SUSPENDED` by either an `AccountManager` or a `PlatformAdmin`; while suspended, the client may not accept new content submissions, schedule-slot reservations, or boost reservations. The same two roles can reinstate a `SUSPENDED` client back to `ACTIVE`. Churning a client is reserved to a `PlatformAdmin` and is allowed from `ONBOARDING`, `ACTIVE`, or `SUSPENDED`, but only when none of the client's boost campaigns is in `RESERVED` or `RUNNING` status; otherwise the churn is an invalid transition. When a client churns, every one of its channels that is not already `DISCONNECTED` is driven to `DISCONNECTED`, and every conversation on those channels that is `OPEN`, `ASSIGNED`, or `ESCALATED` is driven to `RESOLVED`. A `PlatformAdmin` or `AccountManager` may close the current billing cycle, which advances `current_cycle_index` by one and leaves the new cycle's published-post tally at zero.

### 3.2. Channel Onboarding and the Publishing Timeline

An `AccountManager` onboards a channel by naming the owning `client_id`, the `platform` (one of `FACEBOOK`, `INSTAGRAM`, `X`, `LINKEDIN`, or `TIKTOK`), and the channel `handle`. The handle must be unique within the combination of `client_id` and `platform`; a collision is rejected with `ERR_DUPLICATE_HANDLE`. The onboarding payload may optionally set `min_publish_gap_minutes`, the minimum number of minutes that must separate two schedule slots on this channel, which is zero or greater and defaults to 30. A channel begins in `PENDING` and proceeds through `CONNECTED` and `LIVE` to the terminal `DISCONNECTED` status.

Connecting a channel advances it from `PENDING` to `CONNECTED`, and is permitted only while the owning client is in `ONBOARDING` or `ACTIVE`. Taking a channel live advances it from `CONNECTED` to `LIVE`, but only when the number of the client's channels already in the live state is strictly fewer than the `included_channels` allowance on the client's active retainer package; reaching that allowance and attempting one more go-live is rejected with `ERR_CHANNEL_LIMIT_EXCEEDED`. A go-live whose owning client is not in a permitted state surfaces as `ERR_CHANNEL_NOT_LIVE` where the cross-entity state guard does not hold. Disconnecting a channel — performed by an `AccountManager` or triggered by the system during client churn — drives it to `DISCONNECTED` from any of `PENDING`, `CONNECTED`, or `LIVE`. Disconnection has two cascades: every schedule slot of that channel still in `RESERVED` is released to `RELEASED`, and each such released slot's content item, if it was `SCHEDULED`, is reverted to `APPROVED` with its `scheduled_slot_id` cleared.

A schedule slot occupies a window on one channel's timeline. It records the `channel_id` whose timeline it sits on, the `content_item_id` reserved into it, the `slot_start_utc` (the inclusive start of the publishing window, an ISO 8601 UTC instant), and a `duration_minutes` window length that is at least one minute and defaults to 15. The occupied window is the half-open interval running from `slot_start_utc` up to but not including `slot_start_utc` plus `duration_minutes`. A slot's lifecycle runs `RESERVED`, then either `FIRED` (when its content publishes) or `RELEASED` (when the content is unscheduled or the channel disconnects). Slots are created indirectly through the scheduling workflow described in §3.3 rather than by a direct create call; they may be listed and fetched directly. When a new slot would be placed on a channel, it must not overlap the half-open window of any slot on the same channel that is currently `RESERVED` or `FIRED`, and it must additionally be separated from the nearest such slot by at least the channel's `min_publish_gap_minutes`; a violation of either the overlap rule or the gap rule is rejected with `ERR_SLOT_OVERLAP`.

### 3.3. Content Drafting, Review, Scheduling, and Publishing

Content begins life as a draft authored by a `ContentCreator` or an `AccountManager`, who supply the `client_id`, the drafting operator's `author_id`, an internal `title`, and the post `body`. A content item is created in `DRAFT` with a `revision_round` of 0, a null `published_cycle_index`, and a null `scheduled_slot_id`; its lifecycle spans `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED`, `APPROVED`, `SCHEDULED`, `PUBLISHED`, and the terminal `ARCHIVED`. Before a draft can enter review it must be aimed at one or more channels: a `ContentCreator` or `AccountManager` attaches the item to a channel by creating a content target that references the `content_item_id` and the destination `channel_id`, born with a `publish_state` of `PENDING` that later moves to `PUBLISHED`, `FAILED`, or `SKIPPED` during the publish fan-out. Because a target spans a content item and a channel, the channel's `client_id` must equal the content item's `client_id`; a mismatch is rejected with `ERR_CROSS_CLIENT_REFERENCE`. The same cross-client check guards scheduling and boost reservation, where the referenced content item and channel must belong to the same client.

A `ContentCreator` submits a draft for review, moving it from `DRAFT` to `IN_REVIEW`, but only when the owning client is `ACTIVE` — a submission against a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE` — and only when the item has at least one content target. From `IN_REVIEW` an `Approver` may either request changes, sending the item to `CHANGES_REQUESTED` and optionally recording a `note`, or approve it, sending it to `APPROVED`. When a `ContentCreator` resubmits an item from `CHANGES_REQUESTED` it returns to `IN_REVIEW` and its `revision_round` increments by one. These transitions form the revision loop: an item may cycle `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW` any number of times, each resubmission bumping the revision counter.

Scheduling an approved item is an `AccountManager` action that advances it from `APPROVED` to `SCHEDULED`. The scheduler names the destination `channel_id`, a `slot_start_utc`, and an optional `duration_minutes`; the system reserves a new schedule slot on that channel — which must be a `LIVE` channel hosting one of the item's content targets, and the slot must clear the overlap-and-gap rule of §3.2 — and records the new slot's id on the item's `scheduled_slot_id`. Unscheduling reverses this: an `AccountManager` moves the item from `SCHEDULED` back to `APPROVED`, releasing the reserved slot (it leaves `RESERVED` for `RELEASED`) and clearing `scheduled_slot_id`.

Publishing is an `AccountManager` action that advances a `SCHEDULED` item to `PUBLISHED`. It is permitted only when the owning client's `posts_published_this_cycle` is strictly fewer than its `monthly_post_quota` and the reserved slot is still `RESERVED`; once the published count has reached the quota a further publish is rejected with `ERR_POST_QUOTA_EXCEEDED`. Publishing captures `published_cycle_index` as the client's current `current_cycle_index`, fires the reserved slot (moving it from `RESERVED` to `FIRED`), fans out across the item's content targets so that every target whose channel is `LIVE` moves to a `publish_state` of `PUBLISHED` while every target on a non-live channel moves to `SKIPPED`, and then refreshes the client's `posts_published_this_cycle` by recounting the published items in the current cycle. A content item may be archived from `DRAFT`, `CHANGES_REQUESTED`, or `APPROVED` by a `ContentCreator` or `AccountManager`, but never directly from `SCHEDULED` — an item must be unscheduled first, and an archive attempt on an item that is still scheduled is rejected as an invalid state transition.

### 3.4. Ad-Boost Budgeting, Reservation, and Spend Pacing

Ad-boost campaigns are owned by the finance function. A `FinanceController` or `AccountManager` drafts a campaign by naming the budget-owning `client_id`, the boosted `content_item_id`, the `requested_budget_cents` (the daily cap multiplied by the duration the buyer asks for, greater than zero), the `daily_cap_cents` (the maximum spend per active day, greater than zero), and the `duration_days` planned run length (at least one). A campaign is created in `DRAFT` with `reserved_budget_cents`, `spent_budget_cents`, `days_elapsed`, and `current_day_spent_cents` all at zero, and runs through `RESERVED`, `RUNNING`, and the terminal `COMPLETED` or `CANCELLED`.

Reserving budget — a `FinanceController` action advancing the campaign from `DRAFT` to `RESERVED` — is the budget-gating step and is hedged by several preconditions. The owning client must be `ACTIVE`; the boosted content item must be either `SCHEDULED` or `PUBLISHED`; the client's `boost_available_cents` must be at least the `requested_budget_cents`, and a request that would exceed available budget is rejected with `ERR_BOOST_BUDGET_EXCEEDED` and HTTP 402; and the request's `expected_client_version` must match the client's current `version` per the optimistic-concurrency rule of §2.7, failing which the reservation is rejected with `ERR_STALE_CLIENT_VERSION` and HTTP 412. When a reservation succeeds, the campaign's `reserved_budget_cents` is set equal to the `requested_budget_cents`, the client's `boost_reserved_cents` and `boost_available_cents` are recomputed, a ledger entry of type `BOOST_RESERVE` is appended with a positive `amount_cents` equal to the reserved amount along with the `boost_campaign_id` and the current `cycle_index`, and the client's `version` is incremented by one. Launching a reserved campaign advances it from `RESERVED` to `RUNNING`, permitted only when the boosted content item is `PUBLISHED`; a launch against unpublished content is rejected with `ERR_CONTENT_NOT_PUBLISHED`.

Recording spend keeps a `RUNNING` campaign in `RUNNING` and is where the daily pacing cap is enforced. Each record-spend names an `amount_cents` and an optional `spend_day_index`, a calendar-day bucket index that defaults to the current day when omitted. The daily cap is an aggregate per-day window, not a per-call ceiling: the bucket total for a given day is the sum of the amounts of all prior record-spends carrying the same `spend_day_index` plus this call's `amount_cents`, and if that bucket total exceeds `daily_cap_cents` the call is rejected with `ERR_DAILY_CAP_EXCEEDED`. The `spend_day_index` must be greater than or equal to the highest `spend_day_index` recorded so far — that is, monotonic non-decreasing — and a new, previously unseen index opens a fresh bucket. Independently of the daily window, the campaign's reservation ceiling must hold: the existing `spent_budget_cents` plus this call's `amount_cents` must not exceed `reserved_budget_cents`, and a breach is rejected with `ERR_BOOST_OVERSPEND` and HTTP 402. On a successful record-spend the campaign's `spent_budget_cents` increases by the `amount_cents`; if the `spend_day_index` is a previously unseen value the `days_elapsed` count increments by one; `current_day_spent_cents` is recomputed as the bucket total for the highest `spend_day_index` seen so far; the client's `boost_spent_cents` is recomputed; and a ledger entry of type `BOOST_SPEND` is appended with a positive `amount_cents` together with the `boost_campaign_id` and the current `cycle_index`.

Completing a `RUNNING` campaign moves it to `COMPLETED` and settles the reservation: the unspent remainder is the `reserved_budget_cents` minus the `spent_budget_cents`, and when that remainder is greater than zero a ledger entry of type `BOOST_RELEASE` is appended whose `amount_cents` is the negative of that unspent remainder (a release returns budget, so the signed amount is negative), carrying the `boost_campaign_id` and `cycle_index`; the campaign's `reserved_budget_cents` is then set to zero and the client's `boost_reserved_cents`, `boost_spent_cents`, and `boost_available_cents` are recomputed. Cancelling a campaign from `DRAFT` or `RESERVED` drives it to `CANCELLED`: the released amount is the `reserved_budget_cents` when cancelling from `RESERVED` (and zero when cancelling from `DRAFT`), and when that released amount is greater than zero a `BOOST_RELEASE` ledger entry with a negative `amount_cents` of that magnitude is appended with the `boost_campaign_id` and `cycle_index`; the `reserved_budget_cents` is then zeroed and the client's `boost_reserved_cents` and `boost_available_cents` are recomputed.

A boost campaign's settlement cost is read in two distinct ways that can diverge for identical inputs. While a campaign is `RESERVED` or `RUNNING`, its cost for budget-gating purposes is the full reservation — the whole locked `reserved_budget_cents` — because the committed cost the moment a campaign reserves is the entire reservation. At completion, settlement bills only what was actually recorded, clamped by both ceilings: the billable cost is the smallest of three figures — the recorded `spent_budget_cents`, the pacing ceiling given by `daily_cap_cents` multiplied by `days_elapsed`, and the reservation ceiling `reserved_budget_cents` — and whichever of the three is smallest is the one that binds. For pacing diagnostics that are computed on demand and not persisted, the expected spend to date is `daily_cap_cents` multiplied by `days_elapsed`; a campaign is over-pacing when its `spent_budget_cents` is strictly greater than that expected figure and exactly at pace when the two are equal.

### 3.5. Community Management: Conversations and Messages

Community work centers on conversations. A `CommunityAgent` or `AccountManager` opens a thread by naming the `channel_id` it belongs to, the `kind` (`DM` or `COMMENT`), and the `external_author_handle` of the person who started it. A conversation is born `OPEN`, with a null `assigned_agent_id` and a `message_count` of 0, and its triage lifecycle spans `OPEN`, `ASSIGNED`, `RESOLVED`, and `ESCALATED`. A `CommunityAgent` claims an `OPEN` conversation, advancing it to `ASSIGNED` and recording the acting agent's `X-User-ID` onto `assigned_agent_id`, but only when the conversation's channel is `LIVE`; a claim against a non-live channel is rejected with `ERR_CHANNEL_NOT_LIVE`. A conversation may be escalated to `ESCALATED` from either `OPEN` or `ASSIGNED`, optionally carrying a `reason`. An `ESCALATED` conversation can be re-assigned by a `CommunityAgent`, which returns it to `ASSIGNED` and again records the acting agent's identity onto `assigned_agent_id`. From either `ASSIGNED` or `ESCALATED` a conversation is resolved to `RESOLVED` — by a `CommunityAgent` or by the system during client churn.

Messages are appended to a conversation by a `CommunityAgent`. A message names its parent `conversation_id`, a `direction` of `INBOUND` or `OUTBOUND`, and the message `body`; an outbound message also carries an `author_agent_id` identifying the agent who wrote it, while inbound messages leave that field null. Appending a message recomputes the parent conversation's `message_count` as the number of messages under that conversation. Engagement messages are lightweight write-once records and carry only their `id` and `created_at`.

### 3.6. Influencer Collaborations and UGC Rights

The agency negotiates influencer partnerships through collaborations managed by an `AccountManager`. A collaboration is proposed by naming the sponsoring `client_id`, the partner's `influencer_handle`, the proposed flat `offer_fee_cents` (greater than zero), and the `deliverable_count` of UGC pieces expected (at least one). It is created in `PROPOSED` with a `negotiation_round` of 0 and an `approved_asset_count` of 0; its lifecycle runs `PROPOSED`, `COUNTERED`, `ACCEPTED`, `DELIVERED`, and the terminal `CLOSED` or `CANCELLED`. From `PROPOSED` or `COUNTERED`, an `AccountManager` may issue a counter-offer, which keeps or moves the collaboration to `COUNTERED`, sets `offer_fee_cents` to the supplied `counter_fee_cents` (which must be greater than zero), and increments `negotiation_round` by one. From `PROPOSED` or `COUNTERED` the collaboration may instead be accepted, advancing it to `ACCEPTED`.

A submitted asset is the unit of delivery. An `AccountManager` submits a UGC asset under a collaboration by naming the parent `collab_id` and the `asset_url`; the asset is born `SUBMITTED` and moves to the terminal `RIGHTS_CLEARED` or `REJECTED`. Clearing rights advances an asset from `SUBMITTED` to `RIGHTS_CLEARED`, permitted only while the parent collaboration is `ACCEPTED` or `DELIVERED`, and recomputes the parent collaboration's `approved_asset_count` as the number of its assets in `RIGHTS_CLEARED`. Rejecting an asset moves it from `SUBMITTED` to `REJECTED`, either explicitly by an `AccountManager` or automatically by the system when its collaboration is cancelled. Marking a collaboration delivered advances it from `ACCEPTED` to `DELIVERED`, but only when its `approved_asset_count` is at least its `deliverable_count` — that is, enough assets have cleared rights; a shortfall is rejected with `ERR_DELIVERABLES_NOT_MET`. A `DELIVERED` collaboration is closed to the terminal `CLOSED`. Cancelling a collaboration from `PROPOSED`, `COUNTERED`, or `ACCEPTED` drives it to `CANCELLED` and, as a cascade, drives every one of that collaboration's assets still in `SUBMITTED` to `REJECTED`.

The collaboration's settlement quote is read on demand and applies a per-deliverable bonus on top of the accepted fee. The base is the final accepted `offer_fee_cents`. Each deliverable's nominal value is the base divided by `deliverable_count`, rounded down to a whole number of cents (floor). The bonus is tiered by how many assets have cleared rights, evaluated in deliverable order: the first two cleared deliverables earn no bonus; cleared deliverables three through five each earn a bonus of five percent of the per-deliverable value, taken as the floor of the per-deliverable value multiplied by 0.05; and cleared deliverables six and beyond each earn a bonus of ten percent of the per-deliverable value, taken as the floor of the per-deliverable value multiplied by 0.10. Concretely, the number of deliverables earning the five-percent rate is the smaller of the approved-asset count and 5, minus 2, but never below zero; the number earning the ten-percent rate is the approved-asset count minus 5, but never below zero. The bonus is the floored five-percent per-unit value multiplied by the count of five-percent units, plus the floored ten-percent per-unit value multiplied by the count of ten-percent units; each per-unit bonus is floored before being multiplied by its unit count, and the two products are then summed — rounding is per line item and then summed, never summed and then rounded. The settlement amount is the base plus that bonus, in exact integer cents.

### 3.7. Analytics, Churn Settlement, and the Ledger

At the close of a cycle an `AccountManager` or `PlatformAdmin` creates an analytics snapshot for a client, supplying the externally measured `total_impressions` (zero or greater) and `total_engagements` (zero or greater). The snapshot captures the client's `cycle_index` at snapshot time, the `posts_published` (the count of that client's content items whose status is `PUBLISHED` and whose `published_cycle_index` equals the captured cycle index), and the `boost_spent_cents` (the sum of `spent_budget_cents` over that client's boost campaigns in `RUNNING` or `COMPLETED` at snapshot time). The headline figure is the `engagement_rate_bps`, an engagement rate in basis points. When `total_impressions` is zero the engagement rate is defined as zero rather than a division by zero; otherwise it is the total engagements multiplied by ten thousand and then divided by the total impressions, rounded half up to a whole number of basis points. The multiply-before-divide order is deliberate, so that the multiplication by ten thousand happens before the division to avoid truncation. An analytics snapshot is a lightweight write-once record carrying only its `id` and `created_at`.

When a client is about to churn, a churn-quote can be read by an `AccountManager`, `PlatformAdmin`, or `FinanceController`; it returns two retainer figures that can diverge on the same fee. The forward-looking figure, `forward_full_cents`, treats the whole cycle's retainer as owed once the cycle has opened regardless of when churn happens, and so equals the client's `retainer_fee_cents` independent of usage. The chronological figure, `chronological_prorated_cents`, scales the retainer by posts actually published this cycle against quota: it is the `retainer_fee_cents` multiplied by `posts_published_this_cycle`, divided by `monthly_post_quota`, rounded up to the next whole cent (ceiling); the `monthly_post_quota` is guaranteed to be at least one, and when `posts_published_this_cycle` is zero the prorated figure is zero. The endpoint returns both figures; settlement uses the chronological-prorated one.

The ledger is the system's append-only record of budget movement. Each ledger entry names the `client_id` whose budget it moves, an `entry_type` of `RETAINER_CHARGE`, `BOOST_RESERVE`, `BOOST_RELEASE`, or `BOOST_SPEND`, a signed `amount_cents` (positive amounts consume budget and negative amounts return it), an optional `boost_campaign_id` naming the source campaign for boost entries and left null for a `RETAINER_CHARGE`, and the `cycle_index` that was current when the entry was written. Ledger entries are written by the workflows above — retainer charge on client activation, reserve and release and spend across the boost lifecycle — and are lightweight write-once records carrying only their `id` and `created_at`. They may be listed and fetched but never mutated.

### 3.8. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the most fundamental failure is the one reported. Authentication comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_USER_CONTEXT` before anything else. Role authorization comes next: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Existence is then checked, first for every resource identifier in the path (left to right, yielding the appropriate not-found error) and then for foreign keys named in a create body. Cross-client referential integrity — the same-client requirement on content targets, schedule slots, and boost reservations — is checked next, yielding `ERR_CROSS_CLIENT_REFERENCE`. Only then is the basic state-machine check applied: if the requested transition is not defined from the target's current state the request yields `ERR_INVALID_STATE`. Cross-entity state preconditions follow — content submit requiring an `ACTIVE` client (`ERR_CLIENT_NOT_ACTIVE`), boost launch requiring `PUBLISHED` content (`ERR_CONTENT_NOT_PUBLISHED`), and conversation-assign and channel state requirements (`ERR_CHANNEL_NOT_LIVE`). After these come the business-specific constraints in their own order: duplicate channel handle (`ERR_DUPLICATE_HANDLE`), package already active (`ERR_PACKAGE_ALREADY_ACTIVE`), channel limit (`ERR_CHANNEL_LIMIT_EXCEEDED`), slot overlap or gap (`ERR_SLOT_OVERLAP`), daily cap (`ERR_DAILY_CAP_EXCEEDED`), post quota (`ERR_POST_QUOTA_EXCEEDED`), the boost-reserve stale-version check (`ERR_STALE_CLIENT_VERSION`), the boost budget ceiling (`ERR_BOOST_BUDGET_EXCEEDED`), the overspend ceiling (`ERR_BOOST_OVERSPEND`), and the deliverables-met requirement (`ERR_DELIVERABLES_NOT_MET`). Finally, generic body validation — required fields present and correctly typed, enum values within their declared sets, amounts positive where required, and counts at least one — is reported as `ERR_INVALID_REQUEST` with HTTP 400 on any write endpoint.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and every action that mutates derived fields — return a `200 OK` status code. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a client account (ONBOARDING) | AccountManager, PlatformAdmin |
| GET | `/clients` | List clients | AccountManager, PlatformAdmin, FinanceController |
| GET | `/clients/{clientId}` | Get a client | AccountManager, PlatformAdmin, FinanceController |
| POST | `/clients/{clientId}/activate` | Activate client (ONBOARDING→ACTIVE) | AccountManager |
| POST | `/clients/{clientId}/suspend` | Suspend client | AccountManager, PlatformAdmin |
| POST | `/clients/{clientId}/reinstate` | Reinstate suspended client | AccountManager, PlatformAdmin |
| POST | `/clients/{clientId}/churn` | Churn client (terminal) | PlatformAdmin |
| POST | `/clients/{clientId}/cycles/close` | Close current billing cycle, advance cycle clock | PlatformAdmin, AccountManager |
| GET | `/clients/{clientId}/churn-quote` | Read retainer churn proration (both variants) | AccountManager, PlatformAdmin, FinanceController |
| POST | `/retainer-packages` | Create a draft retainer package | AccountManager |
| GET | `/retainer-packages` | List retainer packages | AccountManager, PlatformAdmin, FinanceController |
| GET | `/retainer-packages/{packageId}` | Get a retainer package | AccountManager, PlatformAdmin, FinanceController |
| POST | `/retainer-packages/{packageId}/activate` | Activate package (DRAFT→ACTIVE), supersede prior | AccountManager |
| POST | `/channels` | Onboard a channel (PENDING) | AccountManager |
| GET | `/channels` | List channels | AccountManager, PlatformAdmin, FinanceController, CommunityAgent |
| GET | `/channels/{channelId}` | Get a channel | AccountManager, PlatformAdmin, FinanceController, CommunityAgent |
| POST | `/channels/{channelId}/connect` | Connect channel (PENDING→CONNECTED) | AccountManager |
| POST | `/channels/{channelId}/go-live` | Go live (CONNECTED→LIVE) | AccountManager |
| POST | `/channels/{channelId}/disconnect` | Disconnect channel (→DISCONNECTED) | AccountManager |
| POST | `/content-items` | Create a draft content item | ContentCreator, AccountManager |
| GET | `/content-items` | List content items | ContentCreator, AccountManager, Approver, PlatformAdmin |
| GET | `/content-items/{contentItemId}` | Get a content item | ContentCreator, AccountManager, Approver, PlatformAdmin |
| POST | `/content-items/{contentItemId}/submit` | Submit for review (DRAFT→IN_REVIEW) | ContentCreator |
| POST | `/content-items/{contentItemId}/request-changes` | Request changes (IN_REVIEW→CHANGES_REQUESTED) | Approver |
| POST | `/content-items/{contentItemId}/resubmit` | Resubmit after changes (CHANGES_REQUESTED→IN_REVIEW) | ContentCreator |
| POST | `/content-items/{contentItemId}/approve` | Approve (IN_REVIEW→APPROVED) | Approver |
| POST | `/content-items/{contentItemId}/schedule` | Schedule approved item (APPROVED→SCHEDULED) | AccountManager |
| POST | `/content-items/{contentItemId}/unschedule` | Unschedule (SCHEDULED→APPROVED) | AccountManager |
| POST | `/content-items/{contentItemId}/publish` | Publish (SCHEDULED→PUBLISHED) | AccountManager |
| POST | `/content-items/{contentItemId}/archive` | Archive (→ARCHIVED) | ContentCreator, AccountManager |
| POST | `/content-targets` | Attach a content item to a channel | ContentCreator, AccountManager |
| GET | `/content-targets` | List content targets | ContentCreator, AccountManager, Approver, PlatformAdmin |
| GET | `/content-targets/{targetId}` | Get a content target | ContentCreator, AccountManager, Approver, PlatformAdmin |
| GET | `/schedule-slots` | List schedule slots | AccountManager, PlatformAdmin, FinanceController |
| GET | `/schedule-slots/{slotId}` | Get a schedule slot | AccountManager, PlatformAdmin, FinanceController |
| POST | `/boost-campaigns` | Create a draft boost campaign | FinanceController, AccountManager |
| GET | `/boost-campaigns` | List boost campaigns | FinanceController, AccountManager, PlatformAdmin |
| GET | `/boost-campaigns/{boostId}` | Get a boost campaign | FinanceController, AccountManager, PlatformAdmin |
| POST | `/boost-campaigns/{boostId}/reserve` | Reserve budget (DRAFT→RESERVED) with OCC on client | FinanceController |
| POST | `/boost-campaigns/{boostId}/launch` | Launch (RESERVED→RUNNING) | FinanceController |
| POST | `/boost-campaigns/{boostId}/record-spend` | Record spend into a per-day bucket (RUNNING→RUNNING) | FinanceController |
| POST | `/boost-campaigns/{boostId}/complete` | Complete (RUNNING→COMPLETED), release unspent | FinanceController |
| POST | `/boost-campaigns/{boostId}/cancel` | Cancel (DRAFT\|RESERVED→CANCELLED), release reservation | FinanceController |
| GET | `/ledger-entries` | List ledger entries | FinanceController, AccountManager, PlatformAdmin |
| GET | `/ledger-entries/{entryId}` | Get a ledger entry | FinanceController, AccountManager, PlatformAdmin |
| POST | `/conversations` | Open a community conversation thread | CommunityAgent, AccountManager |
| GET | `/conversations` | List conversations | CommunityAgent, AccountManager, PlatformAdmin |
| GET | `/conversations/{conversationId}` | Get a conversation | CommunityAgent, AccountManager, PlatformAdmin |
| POST | `/conversations/{conversationId}/assign` | Assign/claim conversation (OPEN\|ESCALATED→ASSIGNED) | CommunityAgent |
| POST | `/conversations/{conversationId}/escalate` | Escalate (OPEN\|ASSIGNED→ESCALATED) | CommunityAgent |
| POST | `/conversations/{conversationId}/resolve` | Resolve (ASSIGNED\|ESCALATED→RESOLVED) | CommunityAgent |
| POST | `/messages` | Append a message to a conversation | CommunityAgent |
| GET | `/messages` | List messages | CommunityAgent, AccountManager, PlatformAdmin |
| GET | `/messages/{messageId}` | Get a message | CommunityAgent, AccountManager, PlatformAdmin |
| POST | `/influencer-collabs` | Propose an influencer collaboration (PROPOSED) | AccountManager |
| GET | `/influencer-collabs` | List collabs | AccountManager, PlatformAdmin, FinanceController |
| GET | `/influencer-collabs/{collabId}` | Get a collab | AccountManager, PlatformAdmin, FinanceController |
| POST | `/influencer-collabs/{collabId}/counter` | Counter-offer (PROPOSED\|COUNTERED→COUNTERED) | AccountManager |
| POST | `/influencer-collabs/{collabId}/accept` | Accept (PROPOSED\|COUNTERED→ACCEPTED) | AccountManager |
| POST | `/influencer-collabs/{collabId}/mark-delivered` | Mark delivered (ACCEPTED→DELIVERED) | AccountManager |
| POST | `/influencer-collabs/{collabId}/close` | Close (DELIVERED→CLOSED) | AccountManager |
| POST | `/influencer-collabs/{collabId}/cancel` | Cancel collab (→CANCELLED) | AccountManager |
| GET | `/influencer-collabs/{collabId}/settlement-quote` | Read tiered settlement amount | AccountManager, PlatformAdmin, FinanceController |
| POST | `/ugc-assets` | Submit a UGC asset under a collab (SUBMITTED) | AccountManager |
| GET | `/ugc-assets` | List UGC assets | AccountManager, PlatformAdmin |
| GET | `/ugc-assets/{assetId}` | Get a UGC asset | AccountManager, PlatformAdmin |
| POST | `/ugc-assets/{assetId}/clear-rights` | Clear rights (SUBMITTED→RIGHTS_CLEARED) | AccountManager |
| POST | `/ugc-assets/{assetId}/reject` | Reject asset (SUBMITTED→REJECTED) | AccountManager |
| POST | `/clients/{clientId}/analytics-snapshots` | Create an analytics snapshot for the current cycle | AccountManager, PlatformAdmin |
| GET | `/analytics-snapshots` | List analytics snapshots | AccountManager, PlatformAdmin, FinanceController |
| GET | `/analytics-snapshots/{snapshotId}` | Get an analytics snapshot | AccountManager, PlatformAdmin, FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_CHANNEL_NOT_FOUND` | 404 Not Found |
| `ERR_CONTENT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOST_NOT_FOUND` | 404 Not Found |
| `ERR_CONVERSATION_NOT_FOUND` | 404 Not Found |
| `ERR_COLLAB_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_CLIENT_REFERENCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CLIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_CHANNEL_NOT_LIVE` | 409 Conflict |
| `ERR_DUPLICATE_HANDLE` | 409 Conflict |
| `ERR_PACKAGE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CHANNEL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_POST_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_DELIVERABLES_NOT_MET` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_DAILY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_STALE_CLIENT_VERSION` | 412 Precondition Failed |
| `ERR_BOOST_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_BOOST_OVERSPEND` | 402 Payment Required |

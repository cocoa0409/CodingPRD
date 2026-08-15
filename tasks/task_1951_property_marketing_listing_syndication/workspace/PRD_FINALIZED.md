# Property Marketing & Listing Syndication API — Product Requirements Document

## 1. Introduction

A brokerage's marketing department lives or dies by how quickly and cleanly its listings reach the public portals. Agents enter listing data, photographers deliver media, coordinators push feeds outward, and compliance staff police every word of public marketing copy — all against a backdrop of fair-housing regulation, portal service-level agreements, and the constant churn of price changes, offers, withdrawals, and relists. When any one of these threads is mishandled, the brokerage faces stale portal data, regulatory exposure, or a listing that quietly disappears from the market.

This document specifies the Property Marketing & Listing Syndication API, the system of record for that entire workflow. It governs listing intake and data completeness, photo, video, and floor-plan curation, a fair-housing compliance review gate, syndication of listing feeds to external portal accounts with delay monitoring and retry, aggregation of showing feedback into marketing scores, a complete price and remarks history, and the rules for withdrawing, expiring, and relisting a property. The API is built around an explicit logical clock so that expiry sweeps, retry backoff, cooldown windows, and feedback aging are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level formats, and cross-cutting policies that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

The system recognizes exactly five roles:

- `ListingAgent` — a licensed agent who owns listings and acts only on their own.
- `MarketingCoordinator` — brokerage marketing staff who operate on any listing without an ownership restriction.
- `ComplianceOfficer` — the fair-housing reviewer; decides compliance reviews and otherwise reads.
- `MarketingDirector` — marketing leadership; administers agents, portal accounts, blackout windows, the logical clock, and the operations sweep.
- `PortalWebhook` — the external portal callback identity; it can only acknowledge or fail feed events and read job state.

Role identity is bound to resources as follows. When `X-User-Role` is `ListingAgent`, `X-User-ID` is the `id` of the acting Agent record; ownership checks on any resource that references an Agent compare the resource's `agent_id` field to `X-User-ID`, and a listing-scoped mutation attempted by a `ListingAgent` on a listing whose `agent_id` does not equal their `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNERSHIP`. When `X-User-Role` is `MarketingCoordinator`, `ComplianceOfficer`, `MarketingDirector`, or `PortalWebhook`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by `created_at` in ascending order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and the Operations Sweep

All time-dependent behavior in the system — expiry, retry scheduling, cooldowns, blackout buffering, feedback aging, and breach measurement — reads from a single server-side logical clock, never from wall-clock time. On server startup the logical clock is exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own.

A `MarketingDirector` may advance the clock through an administrative capability that accepts a target instant in the `to_iso8601` field and responds with the resulting `current_utc`. Timestamps such as `created_at`, `decided_at`, `dispatched_at`, and `terminal_entered_at` are always stamped from this clock.

A second administrative capability, the operations sweep, performs three kinds of work in one run: it expires every listing whose agreement has run out, it dispatches every syndication job that is due, and it recomputes derived syndication postures. The sweep responds with three collections: `expired_listing_ids` (the listings it transitioned), `dispatched_job_ids` (the jobs it sent to portals), and `deferred_job_ids` (the due jobs it held back because a blackout window or a suspended portal blocked dispatch). The detailed dispatch and expiry mechanics live in §3.4 and §3.6.

### 2.5. Common Resource Properties and Mutation Semantics

Primary resources — Agent, Listing, MediaAsset, ComplianceReview, PortalAccount, FeedSubscription, SyndicationJob, ShowingWindow, ShowingFeedback, and RelistRequest — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource.

Two resource types are deliberately lighter. A BlackoutWindow and a ListingEvent are append-only records: each carries only `id` and `created_at`; both `updated_at` and `version` are absent from them.

When a mutation cascades — a listing whose withdrawal pauses its subscriptions, for example — the parent listing's `updated_at` is refreshed and its `version` is incremented exactly once for the triggering transition, regardless of how many related records the cascade touches. Derived read-time values (§2.6) are recomputed, not stored, and their recomputation never refreshes `updated_at` and never increments `version`.

### 2.6. Derived Read-Time State: Posture, Scores, and Breach Counters

A Listing carries, alongside its stored fields, a set of values that are computed at read time and on every summary read: `syndication_posture`, `feedback_score_raw`, `feedback_score_weighted`, `audited_breach_count`, and `provisional_breach_count`. None of these is ever persisted, and recomputing them never increments the listing's `version`. The posture is additionally recomputed after every job, subscription, or lifecycle mutation so that the next read reflects it immediately.

The `syndication_posture` is a marketing-health dimension layered on top of the lifecycle, and it takes one of five exact values: `NOT_SYNDICATED`, `SYNDICATING`, `SYNDICATED`, `DEGRADED`, or `SUSPENDED`. Recomputation evaluates the following rules in order, and the first rule that matches wins:

1. If the listing's `lifecycle_status` is `COMPLIANCE_HOLD`, `WITHDRAWN`, `EXPIRED`, or `SOLD`, the posture is `SUSPENDED`. This lifecycle override wins over every other rule.
2. Otherwise, if the listing's `audited_breach_count` is greater than zero, or any syndication job of the listing has reached `DEAD_LETTER`, the posture is `DEGRADED`. This condition is sticky: the audited breach count never decreases, so once a listing degrades it remains `DEGRADED` even after later jobs acknowledge cleanly.
3. Otherwise, if at least one job of the listing is live — in `QUEUED`, `RETRY_QUEUED`, or `DISPATCHED` — the posture is `SYNDICATING`.
4. Otherwise, if at least one feed subscription of the listing is `SUBSCRIBED`, the posture is `SYNDICATED`.
5. Otherwise — no subscribed subscriptions and no live jobs — the posture is `NOT_SYNDICATED`.

The two feedback scores and the two breach counters have their own formulas, given in §3.8 and §3.6 respectively. A freshly created listing starts in lifecycle `DRAFT` with posture `NOT_SYNDICATED`, both scores null, and both breach counters at zero.

### 2.7. Money, Precision, and Rounding

All prices and fees are represented as integer cents — `list_price_cents`, `terminal_price_cents`, `fee_cents`, `payload_display_price_cents`, and their relatives are whole numbers of cents, never fractional.

Rounding follows a single convention everywhere: round half up. Each computed quantity declares exactly where rounding happens, and intermediate steps are never rounded early. Feedback scores are rounded half up to three decimal places. Percentages such as `price_reduction_pct` are rounded half up to two decimal places. The relist fee is rounded half up to a whole cent exactly once, at the very end of its formula. Portal display prices are rounded half up exactly once as well, at the division by the portal's rounding increment, as detailed in §3.5.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both guard the Listing:

- Updating a listing's editable fields requires the request to carry `expected_listing_version`, holding the listing `version` the client last observed.
- Posting a price change likewise requires `expected_listing_version` in the request body, since the price-history head may have moved since the client last read the listing.

In both cases, if `expected_listing_version` does not match the listing's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): another writer has advanced the listing since the client last read it, and the client's input is based on stale data. No other endpoint accepts a version field.

### 2.9. Validation Order and Nested Resource Resolution

When several checks could reject the same request, the system evaluates them in a fixed global order so the surfaced error is deterministic:

1. Authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED`.
2. Role authorization — the role is permitted on this endpoint, else `ERR_UNAUTHORIZED_ROLE`.
3. Ownership — a `ListingAgent` must own the listing they are mutating, else `ERR_FORBIDDEN_OWNERSHIP`.
4. Existence — every identifier resolves, else `ERR_NOT_FOUND`.
5. Field validity — required fields present, types correct, enum membership, and ranges, else `ERR_INVALID_REQUEST`.
6. Lifecycle and entity state — the current state permits the operation, else `ERR_INVALID_STATE`; where an operation specifically requires an `ACTIVE` listing, the rejection is `ERR_LISTING_NOT_ACTIVE` instead.
7. Posture suspension — marketing mutations are forbidden while the listing's posture is `SUSPENDED`, else `ERR_POSTURE_SUSPENDED`.
8. Stale-version guard — `expected_listing_version` must match, else `ERR_STALE_VERSION`.
9. Endpoint-specific business rules — evaluated last, in the relative order stated for each workflow in §3.

Existence checking on nested paths is strictly left to right: the system resolves each identifier in the path in the order it appears and rejects with `ERR_NOT_FOUND` at the first one that does not resolve, without examining later identifiers. The same rule applies to foreign-key references in a request body, such as `agent_id` or `portal_account_id`.

The posture guard at step 7 applies to exactly this set of operations: updating a listing, posting a price change, creating a media asset, marking an asset ready, designating a primary photo, archiving an asset, and creating a showing window. It does not guard review submission, compliance decisions, subscription management, callbacks, feedback, or relisting.

### 2.10. Fair-Housing Language Policy

Public marketing remarks are screened against a fixed list of prohibited phrases. The scan is a case-insensitive substring match over the remarks text, and the prohibited phrases are exactly: "no children", "adults only", "not suitable for families", "christian neighborhood", "no wheelchairs", and "english speakers only".

The scan runs at four moments: when a listing is created with `marketing_remarks` present, when a listing update changes `marketing_remarks`, when a listing is submitted for review, and when a listing is relisted — where it screens `new_marketing_remarks` when that field is supplied and the stored `marketing_remarks` otherwise. Any match rejects the request with `ERR_FAIR_HOUSING_VIOLATION`. Because the scan sits ahead of the endpoint-specific business checks in the global validation order, a relist whose remarks violate the policy fails with `ERR_FAIR_HOUSING_VIOLATION` even if the relist would also have failed the cooldown check.

## 3. Business Logic & Workflows

### 3.1. Agents and Listing Intake

Before any listing exists, a `MarketingDirector` registers the agents of the brokerage. Creating an agent requires a `full_name`, a `license_number`, and a contact `email`. The `license_number` must be unique across all agents; a duplicate is rejected with `ERR_DUPLICATE_LICENSE`.

A listing is brought into the system by a `ListingAgent` or a `MarketingCoordinator`. When a `ListingAgent` creates the listing, the `agent_id` in the payload must be their own identifier, per the ownership rule; a coordinator may create a listing for any agent. The intake payload carries the property's address — `address_line1`, `city`, the two-letter `state_code`, and `postal_code` — together with the `property_type`, which must be one of `SINGLE_FAMILY`, `CONDO`, `TOWNHOUSE`, `MULTI_FAMILY`, or `LAND`, the asking price `list_price_cents`, and the listing agreement's expiry instant `listing_expires_on`. Five further fields are optional at intake: `bedrooms`, `bathrooms`, `square_feet`, `marketing_remarks`, and `mls_number`. When `marketing_remarks` is supplied at creation, it is immediately screened under the fair-housing policy of §2.10. A new listing begins with `lifecycle_status` `DRAFT`, posture `NOT_SYNDICATED`, and `relist_count` zero.

While a listing is being prepared, its editable profile can be updated: `bedrooms`, `bathrooms`, `square_feet`, `marketing_remarks`, `mls_number`, and `listing_expires_on` may all change. The price is never patchable through this route — it moves only through the price-change workflow of §3.7 or a relist. Every update is OCC-guarded per §2.8, increments the listing's `version` by one, and refreshes `updated_at`. When an update changes `marketing_remarks`, the system appends a `REMARKS_UPDATE` entry to the listing's event history capturing `old_remarks` and `new_remarks`; if the listing is `ACTIVE` at that moment, it also queues a `REMARKS_UPDATE` syndication job for every `SUBSCRIBED` feed subscription, superseding any still-`QUEUED` remarks job of the same subscription. The whole update is forbidden while the posture is `SUSPENDED`.

Listings can be browsed with optional `agent_id` and `lifecycle_status` filters, and a single listing read returns the stored record with its derived posture, scores, and breach counters computed fresh.

### 3.2. Media Assets and Primary Photo Curation

Marketing media — photographs, video walkthroughs, and floor plans — are attached to a listing as media assets. Uploading an asset takes its `kind` (one of `PHOTO`, `VIDEO`, or `FLOOR_PLAN`), the stored `file_url`, the `file_bytes` size which must be greater than zero, and optionally the pixel dimensions `width_px` and `height_px`. A new asset starts in `UPLOADED` status with `is_primary` false. Uploads are marketing mutations and are rejected with `ERR_POSTURE_SUSPENDED` while the listing's posture is `SUSPENDED`.

Marking an asset ready moves it from `UPLOADED` to `READY` and is the gate that makes media publishable. Several checks guard it, in the global validation order of §2.9: field-level validity first, so a `PHOTO` asset missing its `width_px` or `height_px` fails with `ERR_INVALID_REQUEST` before any state evaluation; then the state gate, so the listing's `lifecycle_status` must be `DRAFT`, `COMPLIANCE_HOLD`, or `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise; then the posture gate, rejecting with `ERR_POSTURE_SUSPENDED` while the posture is `SUSPENDED`; and finally the minimum-resolution rule — a `PHOTO` must be at least 1024 pixels wide and at least 768 pixels tall, failing with `ERR_MEDIA_TOO_SMALL` when either dimension falls short. When a `PHOTO` becomes ready and no other `READY` photo of the listing currently holds `is_primary` true, the system sets `is_primary` true on the newly ready asset — an automatic primary assignment. If the listing is `ACTIVE` and any of its feed subscriptions is `SUBSCRIBED`, a `MEDIA_UPDATE` job is queued for each such subscription, superseding any still-`QUEUED` media job of that subscription.

Exactly one `READY` photo per listing may be primary at a time. An operator may designate a different primary photo explicitly; the designation enforces three checks in order — the asset's `kind` must be `PHOTO`, else `ERR_PRIMARY_REQUIRES_PHOTO`; its `status` must be `READY`, else `ERR_MEDIA_NOT_READY`; and it must not already be the primary, else `ERR_ALREADY_PRIMARY`. The swap is atomic: the previous primary's `is_primary` flips to false as the new one flips to true, and `MEDIA_UPDATE` jobs are queued exactly as in the mark-ready flow.

Archiving retires an asset from `READY` to `ARCHIVED`, or from `REJECTED` to `ARCHIVED`. Archiving is subject to the posture guard and fails with `ERR_POSTURE_SUSPENDED` while the posture is `SUSPENDED`. When the archived asset was the primary photo, primary status is reassigned to the remaining `READY` photo of the listing with the earliest `created_at`; if no `READY` photo remains, the listing simply has no primary until another photo becomes ready. Media jobs are queued on archive just as they are on mark-ready. The `REJECTED` status itself is reserved for system-side content moderation and cannot be reached through any public endpoint. A listing's media collection can be listed with optional `kind` and `status` filters.

### 3.3. Compliance Review and the Compliance Hold

Before a draft listing may go live, it must pass fair-housing review. Submitting a listing for review moves it to `PENDING_REVIEW`. The state gate admits a listing whose lifecycle is `DRAFT` or `PENDING_REVIEW`; a submission from any other lifecycle state is rejected with `ERR_INVALID_STATE` at step 6 of the global validation order of §2.9, ahead of the four business checks below. Admitting `PENDING_REVIEW` is what makes the fourth check reachable, since a still-`PENDING` review can only ever coexist with a listing in `PENDING_REVIEW`. The four business checks are evaluated in this order. First, the fair-housing scan of §2.10 runs against the current `marketing_remarks`, rejecting with `ERR_FAIR_HOUSING_VIOLATION`. Second, the listing must be complete — `bedrooms`, `bathrooms`, `square_feet`, `marketing_remarks`, and `mls_number` all non-null — else `ERR_LISTING_INCOMPLETE`. Third, the listing must have at least one media asset of `kind` `PHOTO` in `READY` status, else `ERR_NO_READY_PHOTO`. Fourth, there must be no other compliance review still `PENDING` for this listing, else `ERR_REVIEW_ALREADY_PENDING`. A successful submission creates a ComplianceReview in `PENDING` status whose `remarks_snapshot` captures the listing's `marketing_remarks` exactly as they were at submit time, appends a `STATUS_CHANGE` event whose `from_lifecycle` records the listing's lifecycle state at submission and whose `to_lifecycle` is `PENDING_REVIEW` — so a re-submission while the listing is already `PENDING_REVIEW`, which succeeds when its latest review has been decided `APPROVED` but the listing has not yet been activated, records `PENDING_REVIEW` to `PENDING_REVIEW` — and increments the listing's `version`.

A `ComplianceOfficer` decides each pending review by supplying an `outcome` of `APPROVED` or `REJECTED`, optionally with `notes` and, for rejections, the `flagged_terms` the reviewer found. The review must still be `PENDING`; deciding an already-decided review is rejected with `ERR_REVIEW_DECIDED`. Either decision stamps `decided_at` from the logical clock and stores the supplied `notes`; a rejection additionally stores `flagged_terms` on the review.

Rejection is a cascading event. The listing moves from `PENDING_REVIEW` to `COMPLIANCE_HOLD`, appending a `STATUS_CHANGE` event and incrementing `version`. The posture recomputes to `SUSPENDED` under the lifecycle override. Every feed subscription in `SUBSCRIBED` is paused to `PAUSED`, and each paused subscription's live jobs — those `QUEUED`, `RETRY_QUEUED`, or `DISPATCHED` — move to `CANCELLED`.

From `COMPLIANCE_HOLD`, the agent or coordinator revises the listing back to `DRAFT` to fix the flagged remarks. Revising appends the usual `STATUS_CHANGE` event, increments `version`, and lifts the lifecycle override so the posture recomputes — typically back to `NOT_SYNDICATED`, since a held listing normally has no live subscriptions. The listing's full review history remains listable at any time.

### 3.4. Activation, Contract Negotiation, and Leaving the Market

Activation turns an approved listing loose on the market, moving it from `PENDING_REVIEW` to `ACTIVE`. Two conditions must hold, checked in the global validation order: the state gate fires first — if the current instant is no longer strictly before `listing_expires_on`, activation fails with `ERR_INVALID_STATE` — and then the compliance gate, which requires the listing's most recently created compliance review to be `APPROVED`, failing with `ERR_COMPLIANCE_NOT_APPROVED` otherwise.

Once `ACTIVE`, a listing under offer moves to `UNDER_CONTRACT` when the agent or coordinator marks it under contract; if the deal falls through, reactivation returns it from `UNDER_CONTRACT` to `ACTIVE`. Both transitions append a `STATUS_CHANGE` event, increment `version`, and queue a `STATUS_UPDATE` syndication job for every feed subscription in `SUBSCRIBED`.

Closing the sale moves the listing from `UNDER_CONTRACT` to `SOLD`, the terminal lifecycle state, with a full shutdown cascade: every `SUBSCRIBED` subscription moves to `PAUSED`; each paused subscription's live jobs move to `CANCELLED` and exactly one `TERMINAL_SYNC` job is queued per paused subscription, so portals receive a final farewell sync; every `SCHEDULED` showing window of the listing moves to `CANCELLED`; the posture recomputes to `SUSPENDED`; and the listing's `version` increments with the customary `STATUS_CHANGE` event.

A listing can also leave the market without a sale. Withdrawal moves an `ACTIVE` listing to `WITHDRAWN`; expiry — performed by the operations sweep whenever the current instant reaches or passes a listing's `listing_expires_on` while it is still `ACTIVE` — moves it to `EXPIRED`. Both paths stamp `terminal_entered_at` with the current instant and freeze `terminal_price_cents` at the listing's then-current `list_price_cents`, and both run the same cascade as a closing: subscriptions paused to `PAUSED`, live jobs moved to `CANCELLED` with one `TERMINAL_SYNC` queued per paused subscription, scheduled showing windows moved to `CANCELLED`, posture recomputed to `SUSPENDED`, the `STATUS_CHANGE` event appended, and `version` incremented. These two anchors — `terminal_entered_at` and `terminal_price_cents` — drive the relisting rules of §3.9.

### 3.5. Portal Accounts, Blackout Windows, and Feed Subscriptions

External portals are represented as portal accounts, administered by a `MarketingDirector`. Creating a portal account takes a `portal_name` and accepts three tuning fields: `sla_seconds`, the propagation service-level agreement which defaults to 3600 seconds — one hour — when omitted; `discount_pct`, the portal-specific price discount fraction which defaults to 0; and `rounding_increment_cents`, the display price increment which defaults to 100000 cents and must be one of 10000, 50000, 100000, or 1000000 cents. A new portal account starts `ACTIVE`. A director may suspend a portal, moving it to `SUSPENDED`, which blocks both new subscriptions and job dispatch to that portal — due jobs of a suspended portal simply stay queued — and may later resume it back to `ACTIVE`.

Each portal account may declare blackout windows: closed intervals from `starts_at` through `ends_at`, where `ends_at` must be strictly later than `starts_at`, with an optional operator `reason`. A blackout window is an append-only record carrying only `id` and `created_at`. Dispatch respects a buffered form of the window — fifteen minutes are added before the start and after the end, both edges inclusive — so a job whose dispatch instant falls anywhere in that buffered interval is deferred rather than sent.

Subscribing a listing to a portal creates a feed subscription. A `MarketingCoordinator` or `MarketingDirector` supplies the `portal_account_id`; the target portal must be `ACTIVE`, failing with `ERR_PORTAL_NOT_ACTIVE` otherwise, and there must be no other subscription for the same listing and portal already in `SUBSCRIBED` or `PAUSED` — the portal-active check is evaluated before this duplicate check, so a suspended portal surfaces `ERR_PORTAL_NOT_ACTIVE` even when a subscription already exists, while a live duplicate on an active portal fails with `ERR_SUBSCRIPTION_EXISTS`. A new subscription starts `SUBSCRIBED`, and the system immediately queues a `FULL_SYNC` syndication job for it, snapshotting the portal display price into the job's `payload_display_price_cents` at creation.

The portal display price is computed per subscription as follows. Start from the exact, unrounded product of the listing's `list_price_cents` and one minus the portal's `discount_pct`. Divide that exact figure by the portal's `rounding_increment_cents`, round the quotient half up to a whole number, and multiply back by `rounding_increment_cents`; the result is the display price in cents. The pinned order matters — the discount is applied to the unrounded price and the single rounding happens at the increment division; rounding to the increment first and discounting afterwards would produce different cents and is not the contract. The listing's `headline_display_price_cents` is the minimum display price across its `SUBSCRIBED` subscriptions, and null when there are none.

Subscriptions can be paused and resumed by a coordinator or director. Pausing moves `SUBSCRIBED` to `PAUSED` and moves the subscription's live jobs — those `QUEUED`, `RETRY_QUEUED`, or `DISPATCHED` — to `CANCELLED`. Resuming moves `PAUSED` back to `SUBSCRIBED` and demands, first, that the listing's `lifecycle_status` is `ACTIVE`, failing with `ERR_LISTING_NOT_ACTIVE`, and, second, that the portal is `ACTIVE`, failing with `ERR_PORTAL_NOT_ACTIVE`; a successful resume queues a fresh `FULL_SYNC` job with the display price recomputed at that moment. A paused subscription reaches its terminal `COMPLETED` status only one way: when its `TERMINAL_SYNC` job is acknowledged on a listing that has left the market. Both a listing's subscriptions and a portal's subscriptions are listable, and a single subscription read returns its current status.

### 3.6. Syndication Jobs: Dispatch, Portal Callbacks, and Breach Accounting

Every unit of work sent to a portal is a syndication job. Each job belongs to one feed subscription through its `feed_subscription_id`, denormalizes the `listing_id` for feed-event queries, and carries a `job_type` of `FULL_SYNC`, `PRICE_UPDATE`, `REMARKS_UPDATE`, `STATUS_UPDATE`, `MEDIA_UPDATE`, or `TERMINAL_SYNC`. A job is born `QUEUED` with `attempt_count` zero and a `scheduled_at` marking the earliest instant it may be dispatched; `dispatched_at`, `completed_at`, `propagation_delay_seconds`, and `failure_code` stay null until the corresponding events occur. Creating a newer job of the same `job_type` for the same subscription supersedes any still-`QUEUED` job of that type, moving it to `SUPERSEDED` and stamping its `completed_at`.

The operations sweep dispatches due work. A `QUEUED` or `RETRY_QUEUED` job is eligible when its `scheduled_at` is at or before the current instant, its portal is `ACTIVE`, and the current instant does not fall inside any buffered blackout window of the portal; eligible jobs are sent in batch order of `scheduled_at` ascending, breaking ties by `created_at` ascending. Dispatch stamps `dispatched_at` and increments `attempt_count` by one. Due jobs blocked by a suspended portal or a blackout are reported as deferred in the sweep's response.

Portals report back through two callback operations restricted to the `PortalWebhook` role. Both require the job to be in `DISPATCHED`; a callback against a job in any other status is rejected with `ERR_JOB_NOT_DISPATCHED`. An acknowledgement moves the job to `ACKED`, stamps `completed_at`, and computes `propagation_delay_seconds` as the exact number of seconds between `dispatched_at` and the acknowledgement instant. Acknowledging a `TERMINAL_SYNC` job whose subscription is `PAUSED` on a listing that has left the market completes that subscription, moving it to `COMPLETED`. A failure callback carries the portal-reported `error_code`, which is stored as the job's `failure_code`, and the job enters `FAILED`; what happens next depends on the attempt count. When the job has made fewer than three attempts, it moves from `FAILED` to `RETRY_QUEUED` with a new `scheduled_at` set sixty seconds times two raised to the power of the job's current `attempt_count` after the failure — one minute after the first failure, two after the second. When the failure is the job's third, the job moves instead from `FAILED` to the terminal `DEAD_LETTER` status with `completed_at` stamped, the listing's audited breach count increases by one, and the posture recomputes — to `DEGRADED`, per the precedence of §2.6. Either callback recomputes the listing's posture.

Breach accounting distinguishes two counters on the listing. The `audited_breach_count` counts terminal evidence only: jobs that acknowledged with a `propagation_delay_seconds` strictly greater than their portal's `sla_seconds`, plus jobs that died in `DEAD_LETTER`. The `provisional_breach_count` adds a forward-looking term: it equals the audited count plus the number of in-flight `DISPATCHED` jobs already older than the SLA — jobs for which the seconds between `dispatched_at` and now strictly exceed `sla_seconds`. The comparison is strict in both counters: a delay exactly equal to `sla_seconds` is not a breach. The two counters diverge while jobs are in flight, because an over-age dispatched job counts toward the provisional figure immediately but reaches the audited figure only when it acknowledges late or dies. Both counters recompute on every job acknowledgement, every dead-letter event, every sweep, and every read of the listing or its marketing summary. Jobs of a listing can be listed with optional `job_type` and `status` filters, and jobs of a single subscription are listable as well.

A listing's marketing summary aggregates the computed picture in one read: it reports the `listing_id`, the current `lifecycle_status`, the derived `syndication_posture`, the two feedback scores `feedback_score_raw` and `feedback_score_weighted`, the two breach counters `audited_breach_count` and `provisional_breach_count`, the `headline_display_price_cents`, and the `relist_count`.

### 3.7. Price Changes and the Listing Event History

Price movements on a live listing go through a dedicated price-change workflow, available while the listing is `ACTIVE` or `UNDER_CONTRACT` — any other lifecycle fails the state gate with `ERR_INVALID_STATE` — and forbidden while the posture is `SUSPENDED`. The request carries the `new_price_cents`, the OCC guard `expected_listing_version` per §2.8, and an optional free-text `change_reason`. The business checks run in a fixed order after the state, posture, and stale-version gates: first, the new price must differ from the current `list_price_cents`, else `ERR_PRICE_UNCHANGED`; second, the movement must be material — either the absolute difference between the new and current price is at least 50000 cents, or the absolute percentage change, computed against the current price and rounded half up to two decimal places, is at least 1.0 percent — and a change failing both tests is rejected with `ERR_PRICE_CHANGE_TOO_SMALL`. A change meeting either threshold exactly passes.

An accepted price change updates `list_price_cents`, appends a `PRICE_CHANGE` event capturing `old_price_cents` and `new_price_cents`, increments the listing's `version`, supersedes any still-`QUEUED` `PRICE_UPDATE` job of each `SUBSCRIBED` subscription and queues a fresh `PRICE_UPDATE` job per such subscription — each snapshotting the new portal display price — and recomputes the posture. The created history entry is what the workflow returns.

The listing event history is an append-only, per-listing log ordered by `seq`, a monotonic sequence starting at 1 for each listing; entries are selected and ordered by the highest `seq` last. Every entry carries an `event_type` of `PRICE_CHANGE`, `REMARKS_UPDATE`, or `STATUS_CHANGE`, and exactly the pair of payload fields matching its type — `old_price_cents` and `new_price_cents` for a price change, `old_remarks` and `new_remarks` for a remarks update, `from_lifecycle` and `to_lifecycle` for a status change — with the other four fields null. Every lifecycle transition in this document appends a `STATUS_CHANGE` entry and increments the listing's `version` by one, so the history doubles as an audit trail of the listing's public life. The history can be listed with an optional `event_type` filter.

### 3.8. Showing Windows and Feedback Aggregation

While a listing is on the market, agents schedule showing windows for buyer visits. Creating a window takes a `starts_at` and an `ends_at` strictly later than it. Windows occupy a half-open interval — a visitor at exactly `starts_at` is inside the window, one at exactly `ends_at` is not — and a new window must not intersect any other `SCHEDULED` window of the same listing; two windows that merely touch, where one window's `ends_at` equals the other's `starts_at`, do not overlap and are both allowed. An intersecting request is rejected with `ERR_WINDOW_OVERLAP`. Window creation is a marketing mutation and is rejected with `ERR_POSTURE_SUSPENDED` while the posture is `SUSPENDED`. Whenever a listing leaves the market — entering `COMPLIANCE_HOLD`, `WITHDRAWN`, `EXPIRED`, or `SOLD` — every `SCHEDULED` window of that listing is moved to `CANCELLED` by cascade.

After a window ends, attendees' impressions are collected as showing feedback: a `rating` from 1 to 5 inclusive and an optional free-text `comment`. Submitting feedback is allowed only once the current instant has reached the window's `ends_at` — earlier submissions fail with `ERR_WINDOW_NOT_ENDED` — and a window accepts at most one feedback record, a second attempt failing with `ERR_FEEDBACK_ALREADY_EXISTS`; the window-ended check is evaluated before the duplicate check. The feedback record links back through its `showing_window_id` and denormalizes the `listing_id` from the window, and it starts in `INCLUDED` status. A window's feedback — zero or one record — is directly readable, and all feedback of a listing can be listed with an optional `status` filter.

Two scores summarize a listing's included feedback, and both are recomputed on feedback creation, on exclusion, and on every read of the listing or its summary. The input set is exactly the listing's feedback records in `INCLUDED` status; `EXCLUDED` records are ignored entirely. When the set is empty, both scores are null. Otherwise, `feedback_score_raw` is the simple mean of the included ratings, rounded half up to three decimal places, ignoring age entirely. The `feedback_score_weighted` score applies an age decay: each feedback's age in days is the exact number of seconds between its `created_at` and now, divided by 86400; its weight is two raised to the power of negative that age divided by a half-life of fourteen days; and the score is the sum of each rating multiplied by its weight, divided by the sum of the weights, rounded half up to three decimal places. Because older feedback contributes less, the weighted score differs from the raw score whenever the included records differ in age.

A `MarketingCoordinator` may moderate a feedback record out of the aggregate by excluding it, moving it from `INCLUDED` to `EXCLUDED`; excluding a record that is not currently `INCLUDED` is rejected with `ERR_INVALID_STATE`. Exclusion recomputes both scores over the remaining included feedback.

### 3.9. Relisting a Withdrawn or Expired Listing

A listing that left the market as `WITHDRAWN` or `EXPIRED` can be brought back through a relist, which returns it to `DRAFT`. Two preconditions guard the relist, and the safety check runs first: the fair-housing scan screens `new_marketing_remarks` when one is supplied in the request, or the stored `marketing_remarks` otherwise, failing with `ERR_FAIR_HOUSING_VIOLATION`; then the cooldown — at least thirty full days must have elapsed since `terminal_entered_at`, with a relist attempted exactly thirty days after terminal entry permitted, and an earlier attempt rejected with `ERR_RELIST_COOLDOWN_ACTIVE`. The request may also carry a `new_list_price_cents` to reprice the listing as it returns.

A successful relist creates a RelistRequest record and applies a bundle of effects. The record captures `relist_count_before` — the listing's `relist_count` before this relist — the computed `price_reduction_pct`, the `new_list_price_cents` actually applied (the payload value when supplied, otherwise the current price), and the computed `fee_cents`. The listing's `relist_count` increments by one; when a `new_list_price_cents` was supplied, `list_price_cents` updates to it and a `PRICE_CHANGE` event is appended; the customary `STATUS_CHANGE` event records the return to `DRAFT`; `version` increments; and the posture recomputes to `NOT_SYNDICATED`.

The relist fee is quoted and charged by one formula, with its evaluation order pinned: tier multiplier first, then volume multiplier, then discount, with a single rounding at the very end. The base fee is 20000 cents. The tier multiplier is 1.0 when `relist_count_before` is zero, 1.5 when it is one, and 2.0 when it is two or more. The volume multiplier is 2.0 when the owning agent currently has more than ten listings in `ACTIVE` status — counting listings whose `agent_id` matches the relisted listing's agent — and 1.0 otherwise. The discount fraction is 0.25 when the `price_reduction_pct` is at least 5.0 and 0.0 otherwise, where `price_reduction_pct` is one hundred times the difference between `terminal_price_cents` and the effective price, divided by `terminal_price_cents`, rounded half up to two decimal places, and the effective price is the supplied `new_list_price_cents` when present or the current `list_price_cents` otherwise. The fee is the base fee multiplied by the tier multiplier, multiplied by the volume multiplier, multiplied by one minus the discount fraction, the whole product rounded half up to a whole cent exactly once.

A relist quote capability reports the same computation without performing it: given an optional prospective `new_list_price_cents`, it answers at the current clock whether the listing is `eligible` to relist, the `fee_cents` that would be charged, the `cooldown_until` instant at which the cooldown lifts, the `relist_count_before`, and the `price_reduction_pct` that price would imply. The full history of a listing's relist requests remains listable.

## 4. Endpoint Definitions

Operations that create a new resource — an agent, a listing, a media asset, a portal account, a blackout window, a feed subscription, a showing window, a feedback record — or that produce a new distinct record as their result — a compliance review, a relist request, a price-change event — return `201 Created`. Operations that modify an existing resource in place or read data return `200 OK`. Request and response bodies for every operation are defined by the workflows of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agents` | Create an agent | MarketingDirector |
| GET | `/agents` | List agents | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/listings` | Create a listing in `DRAFT` | ListingAgent, MarketingCoordinator |
| GET | `/listings` | List listings with filters | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/listings/{id}` | Get one listing with derived fields | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| PATCH | `/listings/{id}` | Update editable listing fields; OCC-guarded | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/submit-review` | Submit for compliance review | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/activate` | Activate an approved listing | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/revise` | Return a held listing to draft | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/mark-under-contract` | Mark an active listing under contract | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/reactivate` | Reactivate a fallen-through listing | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/close-sold` | Close the listing as sold | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/withdraw` | Withdraw an active listing | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/relist` | Relist a withdrawn or expired listing | ListingAgent, MarketingCoordinator |
| GET | `/listings/{id}/relist-quote` | Computed relist quote at the current clock | ListingAgent, MarketingCoordinator, MarketingDirector |
| GET | `/listings/{id}/relist-requests` | Relist history of a listing | ListingAgent, MarketingCoordinator, MarketingDirector |
| GET | `/listings/{id}/summary` | Computed marketing summary | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/listings/{id}/events` | Price, remarks, and status history | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/listings/{id}/media-assets` | Upload a media asset | ListingAgent, MarketingCoordinator |
| GET | `/listings/{id}/media-assets` | List media of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/media-assets/{id}/mark-ready` | Mark an uploaded asset ready | ListingAgent, MarketingCoordinator |
| POST | `/media-assets/{id}/set-primary` | Designate the primary photo | ListingAgent, MarketingCoordinator |
| POST | `/media-assets/{id}/archive` | Archive a ready or rejected asset | ListingAgent, MarketingCoordinator |
| GET | `/listings/{id}/compliance-reviews` | List reviews of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/compliance-reviews/{id}/decision` | Approve or reject a pending review | ComplianceOfficer |
| POST | `/portal-accounts` | Create a portal account | MarketingDirector |
| GET | `/portal-accounts` | List portal accounts | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/portal-accounts/{id}` | Get one portal account | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/portal-accounts/{id}/suspend` | Suspend a portal account | MarketingDirector |
| POST | `/portal-accounts/{id}/resume` | Resume a suspended portal account | MarketingDirector |
| POST | `/portal-accounts/{id}/blackout-windows` | Declare a dispatch blackout window | MarketingDirector |
| GET | `/portal-accounts/{id}/blackout-windows` | List blackout windows of a portal | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/portal-accounts/{id}/feed-subscriptions` | List subscriptions of a portal | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/listings/{id}/feed-subscriptions` | Subscribe a listing to a portal | MarketingCoordinator, MarketingDirector |
| GET | `/listings/{id}/feed-subscriptions` | List subscriptions of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/feed-subscriptions/{id}` | Get one feed subscription | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/feed-subscriptions/{id}/pause` | Pause a subscription | MarketingCoordinator, MarketingDirector |
| POST | `/feed-subscriptions/{id}/resume` | Resume a paused subscription | MarketingCoordinator, MarketingDirector |
| GET | `/feed-subscriptions/{id}/jobs` | List jobs of a subscription | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector, PortalWebhook |
| GET | `/listings/{id}/feed-events` | List syndication jobs of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector, PortalWebhook |
| POST | `/feed-events/{id}/ack` | Portal acknowledgement callback | PortalWebhook |
| POST | `/feed-events/{id}/fail` | Portal failure callback | PortalWebhook |
| POST | `/listings/{id}/price-changes` | Change the list price; OCC-guarded | ListingAgent, MarketingCoordinator |
| POST | `/listings/{id}/showing-windows` | Create a showing window | ListingAgent, MarketingCoordinator |
| GET | `/listings/{id}/showing-windows` | List showing windows of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/showing-windows/{id}` | Get one showing window | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/showing-windows/{id}/feedback` | Submit feedback for an ended window | ListingAgent, MarketingCoordinator |
| GET | `/showing-windows/{id}/feedback` | Read the feedback of a window | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| GET | `/listings/{id}/feedbacks` | List all feedback of a listing | ListingAgent, MarketingCoordinator, ComplianceOfficer, MarketingDirector |
| POST | `/feedbacks/{id}/exclude` | Exclude a feedback record from the aggregate | MarketingCoordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock | MarketingDirector |
| POST | `/_sweeps/run` | Run the expiry and dispatch sweep | MarketingDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_POSTURE_SUSPENDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FAIR_HOUSING_VIOLATION` | 422 |
| `ERR_DUPLICATE_LICENSE` | 409 |
| `ERR_LISTING_INCOMPLETE` | 422 |
| `ERR_NO_READY_PHOTO` | 422 |
| `ERR_REVIEW_ALREADY_PENDING` | 409 |
| `ERR_COMPLIANCE_NOT_APPROVED` | 409 |
| `ERR_PRICE_UNCHANGED` | 422 |
| `ERR_PRICE_CHANGE_TOO_SMALL` | 422 |
| `ERR_RELIST_COOLDOWN_ACTIVE` | 422 |
| `ERR_PORTAL_NOT_ACTIVE` | 409 |
| `ERR_SUBSCRIPTION_EXISTS` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_WINDOW_NOT_ENDED` | 422 |
| `ERR_FEEDBACK_ALREADY_EXISTS` | 409 |
| `ERR_PRIMARY_REQUIRES_PHOTO` | 422 |
| `ERR_MEDIA_NOT_READY` | 409 |
| `ERR_ALREADY_PRIMARY` | 409 |
| `ERR_MEDIA_TOO_SMALL` | 422 |
| `ERR_REVIEW_DECIDED` | 409 |
| `ERR_JOB_NOT_DISPATCHED` | 409 |

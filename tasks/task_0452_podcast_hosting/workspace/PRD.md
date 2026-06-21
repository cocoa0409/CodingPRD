# Podcast Hosting & Monetization API — Product Requirements Document

## 1. Introduction

This document specifies the Podcast Hosting & Monetization platform — a back-end service that lets independent publishers and networks host audio shows, transcode and publish episodes, distribute them to directories such as Apple and Spotify, and earn revenue through dynamic ad insertion and listener paywalls. The platform sits at the intersection of three distinct constituencies whose interests rarely align cleanly: publishers who own content and want it heard, advertisers who want measurable impressions against a finite budget, and listeners who consume episodes and, in some cases, pay for private access.

The hard problems this system solves are all about reconciliation under contention. Advertising inventory is finite — an episode offers only so many ad slots — and a campaign's budget is likewise finite, reserved when a placement is booked and only truly spent once delivery is measured. The platform therefore maintains two parallel ledgers: an inventory ledger over ad slots and fill rate, and a money ledger over reserved, spent, and available campaign budget. Both must stay internally consistent on every mutation, even when a show is suspended out from under a live campaign or a transcode job fails three times. A second axis of complexity is time: episodes are scheduled against a logical clock, subscriptions lapse and are cancelled on period boundaries, and download analytics follow IAB counting conventions that decide which raw downloads are real impressions and which are noise.

The remainder of this document defines the global contract every endpoint honours (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). Section 3 is deliberately organised around how the business actually operates rather than around the data model, so a given resource's complete behaviour is assembled from several places.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`. The system recognises exactly four roles: `Publisher`, `Advertiser`, `Listener`, and `PlatformAdmin`.

Three of these roles are entity-backed, meaning `X-User-ID` is the identity of a persisted actor and is used for ownership checks. When `X-User-Role` is `Publisher`, `X-User-ID` is the `id` of the acting Publisher; ownership checks on any resource that ultimately references a Publisher (a Show via its `publisher_id`, and transitively the show's Episodes, MediaAssets, Feeds, Distributions, and PayoutStatements) compare that chain back to `X-User-ID`. When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the acting Advertiser; ownership checks on an AdCampaign compare its `advertiser_id` to `X-User-ID`, and ownership of an AdPlacement is derived through the placement's funding campaign. When `X-User-Role` is `Listener`, `X-User-ID` is the `id` of the acting Listener; ownership checks on a Subscription compare its `listener_id` to `X-User-ID`. In all three cases, an authenticated caller of the correct role who acts on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

The fourth role, `PlatformAdmin`, is opaque: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`, and the PlatformAdmin is never subject to ownership checks. The PlatformAdmin performs platform operations: advancing the logical clock, registering publishers and advertisers, suspending shows, driving transcoding, reconciling ad delivery, marking subscriptions past due, reviewing directory submissions, and managing payouts.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Almost every resource in the platform carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent mutation, and the `version` field is an integer that starts at its initial value and is incremented by one on every mutation of the resource. Whenever a derived field is recomputed as part of a mutation — a campaign's budget ledger fields, an episode's fill metrics, a show's episode count — that recomputation is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

One resource is an exception. A DownloadEvent is an append-only IAB analytics record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after ingestion.

### 2.5. Nested Reference Resolution and Validation Ordering

Resources are organised as a flat collection of peers linked by foreign keys rather than as deeply nested URL paths, but most mutations still reference other resources by id — either in the path or in the request body. The system resolves every such reference left to right and front to back: path identifiers first, then foreign-key identifiers carried in the body. If any referenced id does not resolve to an existing resource, the request is rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

Validation across an endpoint follows a fixed precedence so that the same failure always surfaces the same error. Authentication is checked first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Role permission is checked next, yielding `ERR_FORBIDDEN` when the role may not perform the operation at all. Resource ownership is checked third for owner-scoped mutations, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of all path and foreign-key references is checked fourth, yielding `ERR_NOT_FOUND`. Only after these four gates does the system evaluate state legality, which yields `ERR_INVALID_STATE` when the requested transition is not defined from the resource's current state — and for placement creation, when the funding campaign is not `ACTIVE`. Business-specific rules (targeting, slots, budget, scheduling, overlap, and so on) are evaluated after the state gate, in the priority order described where each rule is introduced. Body well-formedness — required fields present, correct types, valid enum members — is the lowest-priority check and surfaces as `ERR_INVALID_REQUEST`.

### 2.6. Hierarchical Consistency and Cascades

State changes do not stop at the resource that was acted upon. Several transitions cascade through the dependency graph, and every entity touched by a cascade has its own `updated_at` refreshed and `version` incremented as part of the same request, synchronously. The platform never defers reconciliation to a background process: derived fields are correct the instant the mutating request returns.

The deepest cascade is show suspension, which propagates three levels. Suspending a show first transitions each of that show's episodes that is currently `PUBLISHED` to `UNPUBLISHED`. For each such episode, every ad placement on it in the `PROPOSED` or `INSERTED` status is then transitioned to `CANCELLED`. Each of those cancellations releases the placement's reserved cost back to its funding campaign, so the campaign's `reserved_budget_cents` and `available_budget_cents` are recomputed, and each affected episode's `filled_slots`, `available_slots`, and `fill_rate` are recomputed. The same chain applies in miniature when an episode is unpublished on its own: its `PROPOSED` and `INSERTED` placements are cancelled, their reserves released, and the episode's fill metrics recomputed. Archiving a show disables all of that show's feeds. These cascades are detailed in the relevant workflow narratives in Section 3.

### 2.7. Monetary Precision, Fill Precision, and Rounding

All money on the platform is expressed in integer cents; there are no fractional cents anywhere in storage or in responses. Whenever a monetary calculation produces a non-integer intermediate value — most notably the cost-per-mille arithmetic for ad placements — the system applies the round-half-up convention to the single raw product to land on an integer number of cents. An episode's `fill_rate` is the one derived value that is not money: it is a ratio carried to four decimal places, also rounded half up.

Budget ledger fields are pure aggregations of already-rounded integers and so introduce no further rounding. Where a calculation sums several already-rounded per-placement amounts, the rounding happens per placement first and the integer results are summed — the platform never sums raw values and rounds once at the end. Each calculation's exact ordering is pinned in Section 3 where the calculation is described.

### 2.8. Optimistic Concurrency Control for Placement Booking

Booking an ad placement reserves money against a budget pool shared by every placement of the same campaign, so the platform guards placement creation with optimistic concurrency control. A request to create an AdPlacement must carry `expected_campaign_version`, the value of the funding campaign's `version` that the client last observed. This field is mandatory on placement creation. If `expected_campaign_version` does not equal the campaign's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_CAMPAIGN_VERSION` and HTTP status 412. The rejection means another writer has already booked a placement against this campaign — legitimately reserving budget and advancing the campaign's `version` — since the client last read it; the client's view of `available_budget_cents` is therefore stale, and refusing the create prevents it from over-reserving against the shared pool. No other endpoint takes a version field; optimistic concurrency control applies only to placement creation.

### 2.9. The Logical Clock

Time on the platform is a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to the host's wall clock. A PlatformAdmin advances the clock by supplying a target instant in the field `to_iso8601`; the clock is set to that value. Advancing the clock is not a passive operation — it fires every transition that has become due. Each `SCHEDULED` episode whose `scheduled_publish_at` is at or before the new clock value automatically publishes, provided its show is `ACTIVE` and its media is `READY`. Each `ACTIVE` subscription whose billing period has ended without renewal moves to `PAST_DUE`, and each `PAST_DUE` subscription that has remained so past the end of its grace window moves to `CANCELLED`. The exact thresholds for these time-driven transitions are given with the subscription and episode workflows in Section 3.

## 3. Business Logic & Workflows

### 3.1. Onboarding Actors and Shows

The platform is operated by a PlatformAdmin who registers the commercial actors. Registering a publisher captures the network's `name`, the `payout_email` that appears on payout statements, and an optional `revenue_share_pct` — the publisher's share of net ad revenue, a fraction between 0.0 and 1.0 inclusive, with the platform keeping the remainder. When `revenue_share_pct` is omitted it defaults to 0.70. Registering an advertiser captures the brand's `name` and a `billing_email`. A listener is registered with a unique login `email` and a `display_name`; listeners may register themselves, and the PlatformAdmin may also register them.

A Publisher creates a **Show**, which starts life in `DRAFT`. Creation supplies the `publisher_id` that owns the show, a `title`, and a `category` drawn from the IAB content taxonomy — one of `TECH`, `NEWS`, `COMEDY`, `BUSINESS`, `EDUCATION`, or `TRUE_CRIME`. Creation may also set `monetization_enabled`, the flag that governs whether ad placements may ever be inserted on this show's episodes; it defaults to false. A show exposes a computed `episode_count` that reflects the number of its episodes whose `publish_status` is anything other than `DELETED`; on a freshly created show this count is zero. Every show also carries a lifecycle `status` that gates what may be done to its children: `DRAFT`, `ACTIVE`, `SUSPENDED`, or `ARCHIVED`.

The owning Publisher activates a show, moving it `DRAFT → ACTIVE`; this is the only transition a Publisher may drive on the status axis besides archival, and the PlatformAdmin may also activate a show, including reinstating a suspended one. A PlatformAdmin alone suspends an `ACTIVE` show, moving it `ACTIVE → SUSPENDED` and triggering the three-level cascade described below. Reinstatement runs `SUSPENDED → ACTIVE` and is performed by the PlatformAdmin; it deliberately does not auto-republish the episodes that suspension unpublished, nor does it restore the placements that suspension cancelled. The owning Publisher archives a show from either `DRAFT` or `ACTIVE`, reaching the terminal `ARCHIVED` state; archival is rejected with `ERR_INVALID_STATE` if attempted from `SUSPENDED`. Archiving a show that is `ACTIVE` is refused with `ERR_SHOW_HAS_PUBLISHED_EPISODES` when any episode of that show is still `PUBLISHED`; the publisher must unpublish those episodes first. From `DRAFT` no such episode check applies. In both archival paths, every feed belonging to the show transitions to `DISABLED`.

When a show is suspended, the cascade unfolds in order. First, each episode of the show whose `publish_status` is `PUBLISHED` is moved to `UNPUBLISHED`. Second, on each of those episodes, every ad placement in `PROPOSED` or `INSERTED` is moved to `CANCELLED`. Third, each cancelled placement releases its `estimated_cost_cents` back to the funding campaign, whose `reserved_budget_cents` and `available_budget_cents` are recomputed, and each affected episode's `filled_slots`, `available_slots`, and `fill_rate` are recomputed. Suspension itself does not delete or archive anything; it only changes states and reconciles the two ledgers.

### 3.2. Episodes, Media, and the Two Independent Axes

An **Episode** belongs to a show via `show_id` and is created by the owning Publisher with a `title`, a `total_ad_slots` count (the fixed number of ad slots offered across all positions, which must be zero or greater), and an `offered_positions` array — the subset of `PRE_ROLL`, `MID_ROLL`, and `POST_ROLL` that this episode will accept. A new episode starts with `publish_status` of `DRAFT` and `media_status` of `NONE`. These two status fields are genuinely independent axes: the publish axis tracks distribution while the media axis tracks transcoding, and they advance on their own triggers.

The episode also exposes several computed fields. Its `duration_ms` is the total audio duration in milliseconds, copied from the episode's `READY` media asset; it is 0 until media is ready. Its `filled_slots` is the count of ad placements on the episode that are currently `INSERTED` or `DELIVERED`. Its `available_slots` is `total_ad_slots` minus `filled_slots`. Its `fill_rate` is the ratio of filled slots to total slots, carried to four decimal places, and is defined to be 0.0 whenever `total_ad_slots` is zero so that an empty episode never divides by zero. Concretely, fill rate is computed by counting the placements on the episode whose status is `INSERTED` or `DELIVERED` to get filled slots, subtracting that from total slots to get available slots, and — when total slots is greater than zero — dividing filled slots by total slots and rounding half up to four decimals; when total slots is zero the rate is fixed at 0.0. These fill metrics are recomputed on every placement status change that touches `PROPOSED`, `INSERTED`, or `DELIVERED`, and they are present whenever an episode is read.

The publish axis works as follows. The owning Publisher schedules a `DRAFT` episode, moving it `DRAFT → SCHEDULED`, by supplying `scheduled_publish_at`; this instant must be strictly after the current logical clock, and a value at or before the clock is rejected with `ERR_SCHEDULE_IN_PAST`. Publishing moves an episode to `PUBLISHED` from `DRAFT`, from `SCHEDULED`, or from `UNPUBLISHED`. Publishing requires that the episode's show is `ACTIVE` and that the episode's `media_status` is `READY`; either condition unmet rejects the publish with `ERR_INVALID_STATE`. A `SCHEDULED` episode also publishes automatically when the logical clock reaches its `scheduled_publish_at`, subject to the same show-active and media-ready conditions. Each publish recomputes the show's `episode_count`. Unpublishing moves a `PUBLISHED` episode to `UNPUBLISHED`, either by the owning Publisher or by the system as part of a show suspension; in both cases every `PROPOSED` or `INSERTED` placement on the episode is cancelled (releasing each placement's reserve back to its campaign) and the episode's fill metrics are recomputed. Deleting an episode is permitted only from `DRAFT`, moving it to the terminal `DELETED` state and recomputing the show's `episode_count`.

The media axis is driven entirely by the episode's **MediaAsset** and never by direct client action on the episode. A Publisher uploads media for an episode, creating a MediaAsset with its `episode_id`, the original `source_filename`, and the declared raw `source_duration_ms` in milliseconds (which must be greater than zero). A new asset has `status` `UPLOADED`, `transcode_attempts` of 0, and `output_duration_ms` of 0; its creation moves the episode's `media_status` from `NONE` to `PENDING`. A PlatformAdmin starts transcoding, moving the asset `UPLOADED → TRANSCODING`; this increments `transcode_attempts` by one and moves the episode's `media_status` to `PROCESSING`. The transcoder callback delivers the result: with a `SUCCESS` outcome the asset goes `TRANSCODING → READY`, sets `output_duration_ms` to the provided `output_duration_ms`, sets the episode's `media_status` to `READY`, and copies `output_duration_ms` into the episode's `duration_ms`. With a `FAILURE` outcome the asset goes `TRANSCODING → FAILED`; the episode's `media_status` becomes `FAILED` only when `transcode_attempts` has reached the maximum of three attempts, otherwise the episode's `media_status` stays `PROCESSING` awaiting a retry. A `FAILED` asset can be retried back into `TRANSCODING` by starting transcoding again, but only while `transcode_attempts` is below three; a successful retry increments `transcode_attempts` and returns the episode to `PROCESSING`. The asset reaches its terminal state at `READY`; failure becomes a terminal media outcome only at the third attempt. The transcoder result is supplied via the `outcome` field, with `output_duration_ms` accompanying a success.

### 3.3. Feeds, Distribution, and Subscriptions

A **Feed** renders a show's catalogue. A Publisher creates a feed against a `show_id` and chooses its `visibility`, either `PUBLIC` or `PRIVATE`. A feed starts `ENABLED` and carries a computed `token_required` flag that is true exactly when `visibility` is `PRIVATE`. A Publisher disables a feed (`ENABLED → DISABLED`) and re-enables it (`DISABLED → ENABLED`); re-enabling is refused with `ERR_INVALID_STATE` when the show is `ARCHIVED`. As noted with show archival, archiving a show disables all of its feeds as a side effect.

**Distribution** pushes a show to an external directory. A Publisher submits a distribution with the `show_id` and a `channel` of either `APPLE` or `SPOTIFY`; it begins `PENDING`. A PlatformAdmin reviews the submission: approval moves it `PENDING → LIVE` and mints an `external_ref` (the directory-assigned reference), but only when the show is `ACTIVE` and the show has a feed whose `visibility` is `PUBLIC` and whose `status` is `ENABLED`; otherwise approval is rejected with `ERR_INVALID_STATE`. Rejection moves the submission `PENDING → REJECTED`. From either `LIVE` or `REJECTED` the distribution can be removed to the terminal `REMOVED` state, an action available to either the owning Publisher or the PlatformAdmin.

A **Subscription** is a listener's paywall relationship to a private show. A Listener creates a subscription with their `listener_id`, the `show_id` they want, a monthly `price_cents` (zero or greater), and an inclusive billing window described by `period_start` and `period_end`. It begins `PENDING`. Activating a subscription moves it `PENDING → ACTIVE` and mints an `access_token` that the listener later presents to download private episodes. Activation by the owning Listener is gated by two business rules in addition to the state and ownership checks: the target show must have a feed whose `visibility` is `PRIVATE` and whose `status` is `ENABLED`, otherwise the activation is rejected with `ERR_NO_PRIVATE_FEED`; and the subscription's closed period `[period_start, period_end]` must not overlap any other subscription for the same `listener_id` and `show_id` that is currently `ACTIVE` or `PAST_DUE`, otherwise the activation is rejected with `ERR_SUBSCRIPTION_PERIOD_OVERLAP`. An `ACTIVE` subscription moves to `PAST_DUE` either when the PlatformAdmin marks it past due or when the logical clock advances past its `period_end` without a renewal. A `PAST_DUE` subscription can be reactivated by the owning Listener, moving `PAST_DUE → ACTIVE` with a renewed period supplied via `period_start` and `period_end`. The owning Listener cancels an `ACTIVE` or `PAST_DUE` subscription, moving it to the terminal `CANCELLED` state and clearing its `access_token`; the system also auto-cancels a `PAST_DUE` subscription once the logical clock passes its `period_end` plus a grace window of seven days. Whenever the clock advances, every due `period_end` lapse and every due grace-window cancellation fires together.

### 3.4. Campaigns and the Budget Ledger

An **AdCampaign** is an advertiser's funded buy. An Advertiser creates a campaign with its `advertiser_id`, a `name`, a total `budget_cents` (greater than zero and immutable after creation), a `bid_cpm_cents` (the advertiser's bid cost per one thousand impressions, in cents, greater than zero), a `targeting_category` drawn from the same taxonomy as shows (`TECH`, `NEWS`, `COMEDY`, `BUSINESS`, `EDUCATION`, or `TRUE_CRIME`), an optional `premium_targeting` flag that defaults to false, and a flight window bounded by `flight_start` and `flight_end` (both inclusive). The campaign begins `DRAFT` and exposes three computed ledger fields. Its `reserved_budget_cents` is the sum of `estimated_cost_cents` over the campaign's placements that are currently `PROPOSED` or `INSERTED`. Its `spent_budget_cents` is the sum of `final_cost_cents` over the campaign's placements that are `DELIVERED`. Its `available_budget_cents` is `budget_cents` minus `reserved_budget_cents` minus `spent_budget_cents`. The platform holds the invariant that `budget_cents` always equals the sum of available, reserved, and spent. On a brand-new campaign, reserved and spent are zero and available equals the full budget. These three fields are recomputed synchronously on every placement insert, reconcile, cancel, or reject.

The campaign lifecycle has five states: `DRAFT`, `ACTIVE`, `PAUSED`, `EXHAUSTED`, and the terminal `COMPLETED`. The owning Advertiser activates a campaign from `DRAFT`, moving it `DRAFT → ACTIVE`, provided its `budget_cents` is greater than zero. The owning Advertiser pauses an `ACTIVE` campaign (`ACTIVE → PAUSED`); pausing rejects every placement of the campaign that is still `PROPOSED` (moving each `PROPOSED → REJECTED` and releasing its reserve, with `reserved_budget_cents` recomputed) while leaving `INSERTED` placements intact. The system also pauses a campaign automatically when budget is exhausted during a placement insert, described in the next subsection. The owning Advertiser reactivates a `PAUSED` campaign (`PAUSED → ACTIVE`) provided `available_budget_cents` is greater than zero and the campaign was not previously `EXHAUSTED`. A campaign that has reached `EXHAUSTED` cannot be reactivated; it can only move forward to completion. The owning Advertiser completes a campaign from either `ACTIVE` or `EXHAUSTED`, reaching `COMPLETED`, but only when the campaign has no placements left in `PROPOSED` or `INSERTED`; an attempt with open placements is rejected with `ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS`.

### 3.5. Booking a Placement: Reservation and Pricing

Booking is where the inventory ledger and the money ledger meet. An Advertiser books an **AdPlacement** by creating it against a `campaign_id` and an `episode_id`, naming the `position` (one of `PRE_ROLL`, `MID_ROLL`, or `POST_ROLL`), the `ad_duration_ms` (the length of the creative, greater than zero), the `forecast_impressions` used to price the booking (greater than zero), and, for a `MID_ROLL`, the `offset_ms` start offset within the episode timeline (zero or greater; `PRE_ROLL` and `POST_ROLL` use 0). The create request must also carry `expected_campaign_version` for the optimistic-concurrency check described in Section 2.8. A newly created placement is `PROPOSED`.

Creation is the moment cost is computed, reserved, and frozen — insertion never re-prices. The platform first checks, in priority order, that the requested `position` is a member of the episode's `offered_positions`, rejecting with `ERR_POSITION_NOT_OFFERED` if not. The funding campaign must be `ACTIVE`; a campaign in any other state rejects the create with `ERR_INVALID_STATE`. The provisional cost is then computed as follows. The base is the campaign's `bid_cpm_cents` multiplied by `forecast_impressions` and divided by one thousand. A premium multiplier of 1.25 applies when the campaign's `premium_targeting` is true, and is 1.0 otherwise. A fill-tier multiplier is selected from the episode's current `fill_rate` band, evaluated before this placement is counted: a fill rate of 0.80 or greater selects the high band of 1.20, a fill rate of at least 0.50 but below 0.80 selects the mid band of 1.10, and any lower fill rate selects the low band of 1.00. That chosen multiplier is stored on the placement as `fill_tier_multiplier` and frozen there. The raw cost is the base multiplied by the premium and by the tier multiplier; `estimated_cost_cents` is the larger of the placement floor of 100 cents and that raw cost rounded half up to whole cents. The resulting `estimated_cost_cents` must not exceed the campaign's `available_budget_cents` at create time; if it would, the create is rejected with `ERR_BUDGET_WOULD_EXCEED`. When the create succeeds, the reserve is held immediately: the campaign's `reserved_budget_cents` increases by `estimated_cost_cents`, `available_budget_cents` is recomputed, and the campaign's `version` is incremented by one — which is precisely what makes a later create with a stale `expected_campaign_version` fail.

A placement also exposes `delivered_impressions`, which counts the download events attributed to it and starts at 0, and `final_cost_cents`, which is 0 until delivery is reconciled. Its lifecycle states are `PROPOSED`, `INSERTED`, `DELIVERED`, `CANCELLED`, and `REJECTED`, with the last three terminal.

### 3.6. Inserting and Cancelling Placements

The owning Advertiser inserts a `PROPOSED` placement (`PROPOSED → INSERTED`), the dynamic-ad-insertion step that actually attaches the ad to the episode. Insertion enforces a battery of cross-entity gates evaluated in priority order. The episode's show category must equal the campaign's `targeting_category`, otherwise the insert is rejected with `ERR_TARGETING_MISMATCH`. The episode's show must have `monetization_enabled` set to true, otherwise the insert is rejected with `ERR_MONETIZATION_DISABLED`. For a `MID_ROLL` placement, the interval beginning at `offset_ms` and running for `ad_duration_ms`, extended by a one-second buffer on each side, must not overlap any existing `INSERTED` or `DELIVERED` `MID_ROLL` placement on the same episode; an overlap is rejected with `ERR_MIDROLL_OVERLAP`. The episode must have an available slot — `available_slots` greater than zero — otherwise the insert is rejected with `ERR_NO_AVAILABLE_SLOT`. Insertion also requires the campaign to be `ACTIVE`, the episode to be `PUBLISHED`, and the episode's media to be `READY`; any of these unmet rejects the insert with `ERR_INVALID_STATE`.

Insertion does not re-price: `estimated_cost_cents` and `fill_tier_multiplier` remain frozen from creation, and the reserve is already held. What insertion does change is fill: the placement now counts as filled, so the episode's `filled_slots`, `available_slots`, and `fill_rate` are recomputed. There is one further consequence. If, at the moment an insert confirms, the campaign's `available_budget_cents` is exactly zero, the campaign automatically transitions `ACTIVE → EXHAUSTED`. Exhaustion cascades like a pause: every remaining `PROPOSED` placement of that campaign is moved `PROPOSED → REJECTED`, each releasing its reserve and prompting a recompute of the campaign's `reserved_budget_cents` and `available_budget_cents` and the affected episodes' fill metrics; `INSERTED` placements are left untouched.

A placement can be cancelled by the owning Advertiser from `PROPOSED` or from `INSERTED`, and is also cancelled by the system during the show-suspend and episode-unpublish cascades. Cancellation moves the placement to the terminal `CANCELLED` state, releases the reserve (the campaign's `reserved_budget_cents` decreases by `estimated_cost_cents` and `available_budget_cents` is recomputed), and recomputes the episode's `filled_slots`, `available_slots`, and `fill_rate`. System rejection of a `PROPOSED` placement during a campaign pause or exhaustion cascade behaves the same way on the ledger and fill metrics, but lands the placement in `REJECTED` rather than `CANCELLED`.

### 3.7. Delivery Analytics and Reconciliation

Download analytics follow IAB counting conventions. Anyone with the Listener or PlatformAdmin role ingests a **DownloadEvent** for an episode, supplying the `episode_id`, an optional `placement_id` to credit a specific ad impression, a `client_ip_hash` for IAB unique-download deduplication, the `user_agent` of the listener's client, the `bytes_served` count (zero or greater), the `event_at` logical-clock instant of the download, and, when the episode lives behind a paywall, an `access_token`. On ingestion the system sets the computed `counted` flag to true exactly when `bytes_served` is at least the IAB minimum of 1,048,576 bytes (one mebibyte); the comparison is inclusive at that threshold. Only a counted event that also carries a non-null `placement_id` increments that placement's `delivered_impressions` by one. There is a paywall gate: when the downloaded episode belongs to a show whose only feed is `PRIVATE`, the request must present a valid `access_token` from a subscription that is `ACTIVE` for the listener; absent that, the ingestion is rejected with `ERR_NO_PRIVATE_ACCESS`.

A PlatformAdmin reconciles an `INSERTED` placement once its `delivered_impressions` reflects the counted download events attributed to it, moving the placement `INSERTED → DELIVERED`. Reconciliation computes the final billed cost and moves money from reserve to spent. The final cost uses the same shape as the estimate but is driven by actual delivery and is capped so the advertiser never pays more than was reserved. The base is the campaign's `bid_cpm_cents` multiplied by `delivered_impressions` and divided by one thousand. The premium multiplier is again 1.25 when `premium_targeting` is true and 1.0 otherwise. The tier multiplier is not re-banded — it reuses the `fill_tier_multiplier` frozen on the placement at insertion. The raw cost is base times premium times that frozen tier multiplier; an uncapped value is taken as the larger of the 100-cent floor and that raw cost rounded half up to whole cents; and `final_cost_cents` is the smaller of that uncapped value and the placement's `estimated_cost_cents`. Because impressions can fall short of forecast, this means a delivery shortfall lowers the bill, while overdelivery never raises it above the reserve. On reconciliation the campaign's `reserved_budget_cents` decreases by `estimated_cost_cents`, its `spent_budget_cents` increases by `final_cost_cents`, and `available_budget_cents` is recomputed; the episode's `fill_rate` is unchanged because a `DELIVERED` placement still counts as filled.

### 3.8. Payouts, Revenue Share, and Settlement

A **PayoutStatement** pays a publisher for delivered advertising. A PlatformAdmin creates a draft statement for a `publisher_id` over a half-open window described by `period_start` (inclusive) and `period_end` (exclusive); the window selects placements by their `created_at`. The statement begins `DRAFT` and computes its figures at creation. Gross revenue is the sum of `final_cost_cents` over the selected placements — those that are `DELIVERED`, that sit on episodes of shows owned by the named publisher, and whose `created_at` falls within `[period_start, period_end)`, processed in ascending `created_at` order for determinism. Because each placement's `final_cost_cents` is already an integer rounded at reconcile time, the gross is a straight sum of those per-placement integers and is exposed as `gross_revenue_cents`.

Net and platform fee derive from gross in a pinned order to avoid circularity: gross is computed first, then net, then the fee as the residual. The publisher's net payout `net_payable_cents` is the gross multiplied by the publisher's `revenue_share_pct`, rounded half up once after the product. The `platform_fee_cents` is gross minus net, computed as a residual so that net and fee always sum exactly to gross. The statement also computes a settled variant, `settled_revenue_cents`, which restricts the selection to only those selected placements whose funding campaign has reached `COMPLETED`: it sums their `final_cost_cents` and multiplies that settled gross by the publisher's `revenue_share_pct`, rounding half up once. The accrued figure (`net_payable_cents`) counts every `DELIVERED` placement in the window regardless of campaign status, so it diverges from the settled figure exactly when the window contains a `DELIVERED` placement on a campaign that is still `ACTIVE`, `PAUSED`, or `EXHAUSTED`. The platform holds the invariant that gross equals net plus platform fee.

A PlatformAdmin finalizes a `DRAFT` statement (`DRAFT → FINALIZED`), freezing the snapshot of gross, platform fee, net, and settled figures. A finalized statement is paid (`FINALIZED → PAID`) only when `net_payable_cents` is greater than zero; an attempt to pay a statement whose net is zero is rejected with `ERR_NOTHING_TO_PAY`. A statement can be voided to the terminal `VOID` state from `DRAFT`, or from `FINALIZED` provided it has not already been paid. The statement's terminal states are `PAID` and `VOID`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and the logical-clock control — return a `200 OK` status code. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; fire due episode publishes and subscription transitions | PlatformAdmin |
| POST | `/publishers` | Register a publisher | PlatformAdmin |
| POST | `/advertisers` | Register an advertiser | PlatformAdmin |
| POST | `/listeners` | Register a listener | PlatformAdmin, Listener |
| POST | `/shows` | Create a show (DRAFT) | Publisher |
| GET | `/shows` | List shows; filter by publisher_id, status | PlatformAdmin, Publisher, Listener |
| GET | `/shows/{id}` | Get a show with computed episode_count | PlatformAdmin, Publisher, Listener |
| POST | `/shows/{id}/activate` | DRAFT/SUSPENDED → ACTIVE | Publisher, PlatformAdmin |
| POST | `/shows/{id}/suspend` | ACTIVE → SUSPENDED; three-level cascade | PlatformAdmin |
| POST | `/shows/{id}/archive` | DRAFT/ACTIVE → ARCHIVED; disables feeds | Publisher |
| POST | `/episodes` | Create an episode (publish DRAFT, media NONE) | Publisher |
| GET | `/episodes` | List episodes; filter by show_id, publish_status | PlatformAdmin, Publisher, Listener |
| GET | `/episodes/{id}` | Get an episode with computed fill metrics | PlatformAdmin, Publisher, Listener, Advertiser |
| POST | `/episodes/{id}/schedule` | DRAFT → SCHEDULED | Publisher |
| POST | `/episodes/{id}/publish` | DRAFT/SCHEDULED/UNPUBLISHED → PUBLISHED | Publisher |
| POST | `/episodes/{id}/unpublish` | PUBLISHED → UNPUBLISHED; cancels placements | Publisher |
| DELETE | `/episodes/{id}` | DRAFT → DELETED | Publisher |
| POST | `/media-assets` | Upload media; episode media_status → PENDING | Publisher |
| GET | `/media-assets` | List media assets; filter by episode_id | PlatformAdmin, Publisher |
| GET | `/media-assets/{id}` | Get a media asset | PlatformAdmin, Publisher |
| POST | `/media-assets/{id}/transcode-start` | UPLOADED/FAILED → TRANSCODING | PlatformAdmin |
| POST | `/media-assets/{id}/transcode-result` | TRANSCODING → READY or FAILED | PlatformAdmin |
| POST | `/feeds` | Create a feed for a show (ENABLED) | Publisher |
| GET | `/feeds` | List feeds; filter by show_id, visibility | PlatformAdmin, Publisher, Listener |
| GET | `/feeds/{id}` | Get a feed | PlatformAdmin, Publisher, Listener |
| POST | `/feeds/{id}/disable` | ENABLED → DISABLED | Publisher |
| POST | `/feeds/{id}/enable` | DISABLED → ENABLED (show not ARCHIVED) | Publisher |
| POST | `/subscriptions` | Create a subscription (PENDING) | Listener |
| GET | `/subscriptions` | List subscriptions; filter by listener_id, show_id, status | PlatformAdmin, Listener, Publisher |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, Listener |
| POST | `/subscriptions/{id}/activate` | PENDING/PAST_DUE → ACTIVE; mints access_token | Listener |
| POST | `/subscriptions/{id}/mark-past-due` | ACTIVE → PAST_DUE | PlatformAdmin |
| POST | `/subscriptions/{id}/cancel` | ACTIVE/PAST_DUE → CANCELLED; clears access_token | Listener |
| POST | `/distributions` | Submit a show to a directory (PENDING) | Publisher |
| GET | `/distributions` | List distributions; filter by show_id, channel | PlatformAdmin, Publisher |
| GET | `/distributions/{id}` | Get a distribution | PlatformAdmin, Publisher |
| POST | `/distributions/{id}/approve` | PENDING → LIVE; mints external_ref | PlatformAdmin |
| POST | `/distributions/{id}/reject` | PENDING → REJECTED | PlatformAdmin |
| POST | `/distributions/{id}/remove` | LIVE/REJECTED → REMOVED | Publisher, PlatformAdmin |
| POST | `/ad-campaigns` | Create a campaign (DRAFT) | Advertiser |
| GET | `/ad-campaigns` | List campaigns; filter by advertiser_id, status | PlatformAdmin, Advertiser |
| GET | `/ad-campaigns/{id}` | Get a campaign with computed budget ledger | PlatformAdmin, Advertiser |
| POST | `/ad-campaigns/{id}/activate` | DRAFT/PAUSED → ACTIVE | Advertiser |
| POST | `/ad-campaigns/{id}/pause` | ACTIVE → PAUSED; rejects PROPOSED placements | Advertiser |
| POST | `/ad-campaigns/{id}/complete` | ACTIVE/EXHAUSTED → COMPLETED | Advertiser |
| POST | `/ad-placements` | Create a placement (PROPOSED); reserves cost; OCC-guarded | Advertiser |
| GET | `/ad-placements` | List placements; filter by campaign_id, episode_id, status | PlatformAdmin, Advertiser, Publisher |
| GET | `/ad-placements/{id}` | Get a placement with computed cost fields | PlatformAdmin, Advertiser, Publisher |
| POST | `/ad-placements/{id}/insert` | PROPOSED → INSERTED; may auto-EXHAUST campaign | Advertiser |
| POST | `/ad-placements/{id}/reconcile` | INSERTED → DELIVERED; computes final_cost_cents | PlatformAdmin |
| POST | `/ad-placements/{id}/cancel` | PROPOSED/INSERTED → CANCELLED; releases reserve | Advertiser |
| POST | `/download-events` | Ingest an IAB download event | PlatformAdmin, Listener |
| GET | `/download-events` | List download events; filter by episode_id, placement_id, counted | PlatformAdmin, Publisher |
| GET | `/download-events/{id}` | Get a download event | PlatformAdmin, Publisher |
| POST | `/payout-statements` | Create a DRAFT payout statement; computes figures | PlatformAdmin |
| GET | `/payout-statements` | List payout statements; filter by publisher_id, status | PlatformAdmin, Publisher |
| GET | `/payout-statements/{id}` | Get a payout statement | PlatformAdmin, Publisher |
| POST | `/payout-statements/{id}/finalize` | DRAFT → FINALIZED; freezes snapshot | PlatformAdmin |
| POST | `/payout-statements/{id}/pay` | FINALIZED → PAID (net_payable_cents > 0) | PlatformAdmin |
| POST | `/payout-statements/{id}/void` | DRAFT/FINALIZED → VOID | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_POSITION_NOT_OFFERED` | 422 Unprocessable Entity |
| `ERR_TARGETING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MONETIZATION_DISABLED` | 409 Conflict |
| `ERR_NO_PRIVATE_ACCESS` | 403 Forbidden |
| `ERR_NO_PRIVATE_FEED` | 409 Conflict |
| `ERR_MIDROLL_OVERLAP` | 409 Conflict |
| `ERR_SUBSCRIPTION_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_NO_AVAILABLE_SLOT` | 409 Conflict |
| `ERR_BUDGET_WOULD_EXCEED` | 409 Conflict |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 Precondition Failed |
| `ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS` | 409 Conflict |
| `ERR_SHOW_HAS_PUBLISHED_EPISODES` | 409 Conflict |
| `ERR_NOTHING_TO_PAY` | 409 Conflict |

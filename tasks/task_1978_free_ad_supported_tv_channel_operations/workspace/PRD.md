# Fast Channel Ops API — Product Requirements Document

## 1. Introduction

A free ad-supported streaming television (FAST) channel lives or dies by three disciplines at once: programming that tiles a broadcast day to the second, advertising that monetizes every break without breaching budgets or competitive-separation rules, and rights management that never lets a frame air outside its licensed window. This document specifies the API behind those disciplines — a system that schedules looping playlists for linear-style channels, marks ad breaks inside them, fills those breaks through server-side insertion, and settles the resulting revenue with distributor platforms.

The API serves the network operator who runs the channel lineup, the programming team that builds each day's loop, the licensing team that ingests content and negotiates rights windows, the ad-operations team that traffics campaigns and creatives, an independent ad-quality reviewer, the finance team that reports revenue to distribution partners, and the distribution partners themselves, who stream the channel and report viewership. Because so many of these actors touch the same money and the same airtime, the system leans on three cross-cutting commitments: a single logical clock that every timestamp and date comparison reads, optimistic concurrency on the few writes that overwrite another writer's observations, and segregation of duties wherever one person's work must be approved or settled by someone else.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints described in this document are mounted under the `/v1` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_CONTEXT_HEADER`. A caller whose role is not in an endpoint's authorized set is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes eight roles, each with exact spelling as follows:

- `PlatformAdmin` — the network operator superuser: channel lifecycle, distributor platforms, distribution agreements, ops-run checkpoints, the logical clock, and snapshot computation.
- `ChannelProgrammer` — the programming operator: playlist loops, entries, ad-break marking, publishing, and marking breaks as aired.
- `ContentLicensing` — the rights and content operator: content assets and rights grants.
- `AdOps` — the ad trafficking operator: campaigns, creative trafficking, house ads, decision runs, reconciliation, and manual voids.
- `AdQualityReviewer` — the independent ad-quality reviewer, who must never review a creative they trafficked themselves.
- `FinanceAnalyst` — the revenue analyst who creates and recomputes revenue reports in their provisional form.
- `FinanceController` — the revenue controller who finalizes, refinalizes, and settles reports, and who must never settle a report they generated.
- `DistributorPartner` — an external distributor platform user.

For seven of these roles — `PlatformAdmin`, `ChannelProgrammer`, `ContentLicensing`, `AdOps`, `AdQualityReviewer`, `FinanceAnalyst`, and `FinanceController` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a creative trafficked by an `AdOps` user, as `reviewed_by_user_id` when an `AdQualityReviewer` completes a review, as `generated_by_user_id` on a report created by a `FinanceAnalyst`, or as `finalized_by_user_id` when a `FinanceController` finalizes), but it never compares it to any entity's `id`. The segregation-of-duties checks in §3.5 and §3.8 are the only places these identifiers are compared — against each other, not against resource ids.

When `X-User-Role` is `DistributorPartner`, `X-User-ID` is the `id` of the acting `DistributorPlatform`; ownership checks on any resource that references a `DistributorPlatform` compare the resource's foreign-key field to `X-User-ID`. A partner touching another platform's resource — reading or disputing a report whose `platform_id` differs from the caller's id, or submitting a viewership event for a different platform — is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Server-Stamped Time

Every timestamp the server stamps — `created_at`, `updated_at`, `validated_at`, `published_at`, `computed_at`, and every date comparison this document describes as "the current logical date" — reads a single logical clock, never the wall clock. Before any operator sets it, the logical clock starts at exactly 2026-08-01T00:00:00Z. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the clock never moves backward, and an attempt to set an earlier instant is rejected with `ERR_INVALID_REQUEST`. Grant windows, flight dates, broadcast dates, report periods, and staleness thresholds all evaluate against this clock.

### 2.5. Common Resource Properties

All primary resources in the system share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix. Ids are identity only — they are never used in any ranking, tie-break, allocation, or selection anywhere in this document.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification to the resource, and that anchors the optimistic concurrency checks of §2.8.

One deliberate exception exists: a viewership event is an append-only record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it — events are never modified after ingestion.

### 2.6. Channels Carry Two Independent State Dimensions

A channel's state is two-dimensional. The lifecycle dimension, `channel_status`, walks `DRAFT` → `LIVE` (optionally through `SUSPENDED` and back) → `OFFLINE` → `ARCHIVED`, and is driven only by explicit operator actions. The gating dimension, `channel_posture`, takes the values `ACTIVE`, `GUARDED`, and `FROZEN`, and is never set directly by a client — it is derived, recomputed whenever a rights grant is revoked, whenever a grant expires at an ops-run, whenever a loop is published, and whenever an ops-run checkpoint executes. Mutations on one dimension never rewrite the other; a channel can be `LIVE` and `FROZEN` at once, and taking a channel offline does not change its posture.

The derived posture follows three rules, evaluated in this order. The posture is `FROZEN` when there exists a published loop of the channel containing an entry whose air window lacks a covering active rights grant. Otherwise it is `GUARDED` when the channel is `LIVE` and has never published a loop (its `last_published_on` is null), or when the current logical date is strictly later than `last_published_on` plus the channel's `refresh_cadence_days` — on the exact date `last_published_on` plus the cadence the channel is not stale, because the comparison is strict. Otherwise the posture is `ACTIVE`. A frozen channel refuses loop validation, locking, and publishing, as well as ad-break decision runs, each rejected with `ERR_CHANNEL_POSTURE_FROZEN`; a resume action on a suspended channel is likewise blocked while the posture is `FROZEN`. Once a channel is `OFFLINE`, its posture is held as-is until archive, and no loop operations are permitted while it is offline.

### 2.7. Monetary Precision, Basis Points, and Rate Scale

All monetary values are integer cents; the system never carries fractional cents between steps. Every division that produces a money value rounds half-up to a whole cent. Revenue-share rates are expressed in basis points, where 10,000 basis points equal 100 percent. Fill rates are scale-4 fixed-point numbers rounded half-up — a three-quarter-filled day reads 0.7500. Two rounding orders are pinned and deliberately different: revenue attribution rounds per (decision, platform) pair first and then sums the rounded integers, while the revenue-share statement rounds once at statement level. §3.8 gives both in full.

### 2.8. Optimistic Concurrency Control

Three write operations overwrite work derived from what the caller last observed, and each therefore requires the caller to present the version it observed:

- Publishing a loop requires `expected_channel_version` carrying the client's last observed `version` of the channel. If the channel's current `version` differs — for example because another writer has since published a loop for that date, which bumps the channel's version — the publish is rejected with `ERR_STALE_CHANNEL_VERSION` (HTTP 412), preventing the client from unknowingly superseding a loop it never saw.
- Executing a decision run on an ad break requires `expected_break_version` matching the break's current `version`. A mismatch is rejected with `ERR_STALE_BREAK_VERSION` (HTTP 412), preventing a stale writer from silently discarding placements created after its read, since a decision run voids and replaces the break's provisional decisions.
- Recomputing a revenue report requires `expected_report_version` matching the report's current `version`. A mismatch is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412), preventing a stale writer from discarding figures produced after its read.

No other endpoint takes a version field; for all other mutations the server processes the write without an OCC check.

### 2.9. Nested Resource Retrieval and Reference Validation

For any endpoint whose path contains resource identifiers, the system validates the existence of each identifier in strict left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, without examining later identifiers. References supplied in a request body — a `content_id` on an entry, a `campaign_id` on a creative, a `channel_id` on a loop, and so on — are validated as referential integrity targets; a body reference that points at a non-existent resource is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

### 2.10. Validation Priority Order

When several checks could reject the same request, the server evaluates them in a fixed order and reports the first failure it encounters; the order below is the contract, not an implementation detail.

1. Header context: `X-User-ID` and `X-User-Role` must be present and the role must be one of the declared roles, else `ERR_MISSING_CONTEXT_HEADER`. A malformed request with missing headers therefore reports the header failure, not the body failure.
2. Request body shape: required fields present, enum values valid, and numeric ranges respected (for example `max_plays` must be positive, `runtime_seconds` must be positive, and revenue-share basis points outside 0..6000 are reported as `ERR_REV_SHARE_OUT_OF_RANGE`), else `ERR_INVALID_REQUEST`. Creative duration is deliberately not shape-checked here; it is an approve-time ad-quality rule (tier 10).
3. Role authorization: the caller's role must appear in the endpoint's authorized set, else `ERR_FORBIDDEN_ROLE`.
4. Existence: path identifiers validated left-to-right, else `ERR_NOT_FOUND`; body foreign-key targets, else `ERR_REFERENCE_NOT_FOUND`.
5. Ownership scope: a `DistributorPartner` may only read or dispute reports, and create viewership events, for their own platform, else `ERR_FORBIDDEN_OWNERSHIP`.
6. Segregation of duties: a creative reviewer must differ from the creative's creator, and a report finalizer, refinalizer, or settler must differ from the report's generator, else `ERR_SEGREGATION_OF_DUTIES`.
7. State-transition legality: the trigger must be valid from the resource's current state, including terminal-state lockdown, else `ERR_INVALID_STATE_TRANSITION`; the channel-specific guards live at this tier too — publishing against a channel that is not `LIVE` fails with `ERR_CHANNEL_NOT_LIVE`, and loop validate, lock, or publish, or a decision run, attempted while the channel's posture is `FROZEN` fails with `ERR_CHANNEL_POSTURE_FROZEN`.
8. Optimistic concurrency: the three version checks of §2.8, each carrying its own stale-version error and HTTP 412.
9. Referential usability: the referenced entity must be usable for this operation — entry content must be `AVAILABLE` (`ERR_CONTENT_NOT_AVAILABLE`), a creative's `iab_category` must equal its campaign's (`ERR_CATEGORY_MISMATCH`), and report creation must resolve a covering agreement with a locked rate snapshot (`ERR_NO_COVERING_AGREEMENT`).
10. Rights and ad-quality safety: every entry air window must be covered with enough remaining plays (`ERR_RIGHTS_WINDOW_VIOLATION`, `ERR_PLAYS_EXHAUSTED`), and a creative's duration must satisfy the ad-quality rule at approve time (`ERR_AD_QUALITY_RULE`).
11. Temporal windows and dates: grant window end after start (`ERR_INVALID_WINDOW`), grant half-open overlap per (content, channel) among pending or active grants (`ERR_GRANT_WINDOW_OVERLAP`), agreement closed-interval overlap per (channel, platform) among non-terminal agreements (`ERR_AGREEMENT_WINDOW_OVERLAP`), broadcast dates not in the past at loop create or publish (`ERR_BROADCAST_DATE_IN_PAST`), campaign flight end not before flight start (`ERR_INVALID_FLIGHT`), and report period fully elapsed (`ERR_REPORT_PERIOD_NOT_ELAPSED`).
12. Uniqueness and capacity: one active loop per (channel, broadcast date) (`ERR_DUPLICATE_LOOP_DATE`), exact tiling at validate (`ERR_LOOP_NOT_TILED`), entry or break additions that would overflow the loop duration (`ERR_LOOP_OVERFLOW`), break duration a multiple of 30 within 30 to 240 (`ERR_BREAK_DURATION_INVALID`), total break seconds within the ad-capacity fraction (`ERR_AD_CAPACITY_EXCEEDED`), one report per (channel, platform, period) (`ERR_DUPLICATE_REPORT`), and the dispute-round ceiling (`ERR_DISPUTE_ROUND_LIMIT`).
13. Fiscal budget integrity: an adjusted total budget must not fall below the amount already spent (`ERR_BUDGET_BELOW_SPENT`), and a paused campaign may only resume with headroom under its total budget (`ERR_BUDGET_EXHAUSTED`).

The practical consequence: a publish attempted against a non-`LIVE` channel surfaces `ERR_CHANNEL_NOT_LIVE` before any version comparison runs; a stale channel version surfaces `ERR_STALE_CHANNEL_VERSION` before rights coverage is evaluated; and a missing covering agreement surfaces `ERR_NO_COVERING_AGREEMENT` before a not-yet-elapsed period or a duplicate report is ever considered.

## 3. Business Logic & Workflows

### 3.1. Standing Up and Operating a Channel

A `PlatformAdmin` brings a channel into existence by supplying its `name`, its primary `genre` label, and the IANA `timezone` that fixes the channel's programming-day boundaries. Four tuning knobs are optional at creation. `loop_duration_seconds` fixes the exact length every playlist loop of this channel must tile to, in seconds; it defaults to 86400 — one full day — and must be positive. `refresh_cadence_days`, defaulting to 7 and likewise positive, sets the maximum number of days the channel may go without a loop publish before it is considered stale. `ad_separation_window_seconds`, defaulting to 600, defines the competitive-separation window: two breaks whose gap is at or below this many seconds are treated as adjacent for IAB-category exclusion. `avg_slot_impressions`, defaulting to 1000, is the expected impressions per 30-second slot and becomes the basis for the committed cost of every direct-fill decision on this channel. A new channel starts in `DRAFT` status with posture `ACTIVE`, an `ops_run_index` of 0, and `last_published_on` null until its first publish.

Going live — `DRAFT` → `LIVE` — is permitted only once the channel has at least one playlist loop in `LOCKED` or `PUBLISHED` status whose `broadcast_date` is on or after the current logical date. From `LIVE`, an administrator may suspend the channel (`LIVE` → `SUSPENDED`) and later resume it (`SUSPENDED` → `LIVE`), though resuming is blocked while the channel's posture is `FROZEN`. Either a live or suspended channel may be taken offline (`LIVE` or `SUSPENDED` → `OFFLINE`), at which point its posture is held until archive and no loop operations are permitted. Finally, an offline channel may be archived (`OFFLINE` → `ARCHIVED`, terminal) only when no playlist loop of the channel sits in `PUBLISHED` status with a `broadcast_date` on or after the current logical date. Every one of these lifecycle mutations increments the channel's `version` by one and refreshes its `updated_at`; any attempt to drive a transition from a state where it is not defined is rejected with `ERR_INVALID_STATE_TRANSITION`.

Channels may be listed with optional filters on `channel_status` and `channel_posture`, and a single channel may be fetched by its `channel_id`.

Once per operating rhythm, a `PlatformAdmin` triggers an ops-run checkpoint on a channel. The checkpoint increments the channel's `ops_run_index` by one, expires every rights grant whose `window_end_utc` is at or before the current logical time — whether the grant is still `PENDING` or already `ACTIVE`, both move to `EXPIRED` with the content re-evaluation cascade of §3.2 — and recomputes the channel's posture against both the staleness rule and the frozen rule of §2.6. The checkpoint revives nothing else: no campaign, creative, loop, or agreement changes state as part of an ops-run beyond these effects.

### 3.2. Content Ingestion and Rights Windows

A `ContentLicensing` operator ingests a content asset with its `title`, a `content_type` of `MOVIE`, `EPISODE`, or `SHORT`, the exact `runtime_seconds` (which must be positive), a `rating` of `G`, `PG`, `PG13`, `R`, or `TVMA`, and a `genre` label. An asset begins life `INGESTING`; marking it available moves it to `AVAILABLE`, a transition that requires a positive `runtime_seconds`. Assets may be listed filtered by `content_status` or `genre`, and fetched individually by `content_id`.

Rights to air an asset on a channel are expressed as rights grants. Creating a grant takes the `channel_id` and `content_id` it links, a half-open window given by `window_start_utc` (inclusive) and `window_end_utc` (exclusive), and `max_plays`, the maximum number of playlist entries this grant may cover, which must be positive. The end of the window must fall strictly after its start, else `ERR_INVALID_WINDOW`. Among grants in `PENDING` or `ACTIVE` status for the same (content, channel) pair, windows may not overlap under half-open semantics — adjacency, where one grant's end equals another's start, is allowed — and a violating creation is rejected with `ERR_GRANT_WINDOW_OVERLAP`. A new grant starts `PENDING` with `plays_used` at 0. Grants may be listed filtered by `channel_id`, `content_id`, or `grant_status`, and fetched by `grant_id`.

Activating a grant (`PENDING` → `ACTIVE`) requires that the window contain the current logical time — equality with `window_start_utc` counts, while the end remains exclusive — that the content be `AVAILABLE` (otherwise `ERR_CONTENT_NOT_AVAILABLE`), and that the channel not be `ARCHIVED`. Revoking a grant (`PENDING` or `ACTIVE` → `REVOKED`) triggers two evaluations: every channel with a published loop containing an entry whose air window this grant covered is evaluated for the frozen rule of §2.6, and the content is re-evaluated as follows.

Content re-evaluation is the system's way of pulling the rug cleanly. Whenever a grant leaves the usable set — expired at an ops-run, exhausted at publish, or revoked — and no other grant for that content remains in `PENDING` or `ACTIVE`, an `AVAILABLE` asset transitions to `WINDOW_EXPIRED`. That transition, like an explicit pull (`AVAILABLE` → `PULLED`), fires the loop-revert cascade: every playlist loop in `VALIDATED` or `LOCKED` status that contains an entry of this content reverts to `DRAFT`, with the decision-voiding consequences described in §3.4. A pulled asset may be reinstated (`PULLED` → `AVAILABLE`) only when at least one grant for the content exists in `PENDING` or `ACTIVE` status, and may be archived (`PULLED` → `ARCHIVED`, terminal) only when no such grant remains.

### 3.3. Building the Playlist Loop

A `ChannelProgrammer` opens a playlist loop by naming its `channel_id` and `broadcast_date`, the logical air date in YYYY-MM-DD form. Only one loop per (channel, broadcast date) may exist in `DRAFT`, `VALIDATED`, or `LOCKED` status at a time; a second attempt is rejected with `ERR_DUPLICATE_LOOP_DATE`. A `broadcast_date` earlier than the current logical date is rejected with `ERR_BROADCAST_DATE_IN_PAST` — and because temporal checks (tier 11) run before uniqueness checks (tier 12), a past-dated duplicate reports the date failure first. A new loop starts in `DRAFT` with `used_seconds` at 0, `validated_at` and `published_at` null, and `supersedes_loop_id` null. Loops may be listed filtered by `channel_id`, `loop_status`, `broadcast_date`, or `supersedes_loop_id`, and fetched by `loop_id`.

While the loop is in `DRAFT`, the programmer appends content entries, each a payload containing the `content_id` of the scheduled asset. The content must be `AVAILABLE`, else `ERR_CONTENT_NOT_AVAILABLE`. The server assigns each entry a zero-based `sequence_index` in append order and derives its position through the offset walk below; each entry carries its `loop_id`, its `start_offset_seconds`, and its `end_offset_seconds` (the start plus the content's runtime). Entries may be listed filtered by `loop_id` or `content_id`, fetched by `entry_id`, and removed — again only while the loop is in `DRAFT` — after which the offsets are recomputed. Removing an entry compacts the remaining entries' `sequence_index` values to close the gap and clamps every break's `after_entry_index` into the range from zero to the remaining entry count.

Ad breaks are marked on a `DRAFT` loop by supplying a `duration_seconds`, which must be a multiple of 30 and lie between 30 and 240 inclusive — anything else is rejected with `ERR_BREAK_DURATION_INVALID`. A break is positioned after the current last entry at the moment it is marked: its `after_entry_index` records how many entries precede it in the walk, and its `sequence_index` records creation order among the loop's breaks, which is what orders breaks that share an `after_entry_index`. Each break exposes its computed `slots` — its duration divided by 30 — along with `start_offset_seconds` from the walk and the fill accounting of §3.6: `direct_seconds`, `house_seconds`, and `slate_seconds`. Breaks may be listed filtered by `loop_id` or `break_status`, fetched by `break_id`, and removed while the loop is in `DRAFT`.

Two capacity guards fire at placement time, before validation ever runs. Adding an entry or marking a break that would push the loop's `used_seconds` beyond the channel's `loop_duration_seconds` is rejected with `ERR_LOOP_OVERFLOW`. And marking a break that would push the loop's total break seconds beyond the ad-capacity fraction — one quarter of the loop duration — is rejected with `ERR_AD_CAPACITY_EXCEEDED`.

Whenever entries or breaks are added or removed while the loop is in `DRAFT`, the server recomputes the layout with a deterministic offset walk. The walk visits entries in ascending `sequence_index`, carrying a running offset that starts at zero. Immediately before the entry at position k, it places every break whose `after_entry_index` equals k, in ascending break `sequence_index`: each such break takes `start_offset_seconds` equal to the running offset, which then advances by the break's `duration_seconds`. The entry at position k then takes `start_offset_seconds` equal to the running offset, which advances by the content's `runtime_seconds`; the entry's `end_offset_seconds` is its start plus that runtime. After the last entry, the walk places the breaks whose `after_entry_index` equals the total entry count. The loop's `used_seconds` is the final value of the running offset. No identifier participates in this ordering — only sequence positions and creation order.

### 3.4. From Draft to Air: Validating, Locking, and Publishing the Loop

Validation (`DRAFT` → `VALIDATED`) is where a loop proves it is airworthy. The channel's posture must not be `FROZEN` (else `ERR_CHANNEL_POSTURE_FROZEN`) and the channel must not be `OFFLINE` or `ARCHIVED`. Four content rules then hold. First, exact tiling: `used_seconds` must equal the channel's `loop_duration_seconds` exactly — one second under or over fails with `ERR_LOOP_NOT_TILED`. Second, ad capacity: the summed duration of the loop's breaks must not exceed one quarter of the loop duration, computed as 25 percent of `loop_duration_seconds` rounded down to a whole second; a loop whose breaks total exactly that quarter passes, and anything more is `ERR_AD_CAPACITY_EXCEEDED`. Third, every entry's content must be `AVAILABLE`, else `ERR_CONTENT_NOT_AVAILABLE`. Fourth, rights coverage: every entry's air window must be covered by a grant in `PENDING` or `ACTIVE` status for that (content, channel) pair, and each covering grant must have enough remaining plays to cover all entries of that content in this loop. An entry with no covering window is rejected with `ERR_RIGHTS_WINDOW_VIOLATION`; a grant whose plays would be overdrawn is rejected with `ERR_PLAYS_EXHAUSTED`. A successful validation stamps `validated_at` with the logical now.

An entry's air window is the closed interval from the loop's `broadcast_date` plus the entry's `start_offset_seconds` to the `broadcast_date` plus its `end_offset_seconds`. The covering grant is the unique grant for that (content, channel) whose half-open window contains the entire air window — an air window ending exactly at `window_end_utc` is permitted — and the overlap rule of §3.2 guarantees at most one active covering grant exists.

Rework is cheap before the lock. Reverting a validated loop (`VALIDATED` → `DRAFT`) voids every provisional fill decision on the loop's breaks — with no spend impact, since provisional decisions were never charged — and flips each break in `DECIDED` status that has no remaining provisional or committed decisions back to `MARKED`. The same loop-revert cascade fires from outside when content is pulled or window-expired, and there it reaches `LOCKED` loops as well: every `VALIDATED` or `LOCKED` loop containing an entry of the affected content reverts to `DRAFT`; provisional decisions on its breaks are voided without spend impact; committed decisions voided by the revert refund their `committed_cost_cents` to the campaign's `spent_cents`, which may revive an `EXHAUSTED` campaign per §3.5; and each emptied `DECIDED` break falls back to `MARKED` with its fill seconds recomputed to zero.

Locking (`VALIDATED` → `LOCKED`) is the moment money moves. The posture must again not be `FROZEN`, and every ad break of the loop must be in `DECIDED` status. On lock, every provisional fill decision on the loop's breaks becomes `COMMITTED`, processed in order by break `sequence_index` and then `slot_index`. For each committed direct decision, the campaign's `spent_cents` increases by the decision's `committed_cost_cents`; should `spent_cents` reach or exceed the campaign's `total_budget_cents`, the campaign flips to `EXHAUSTED` and its exhaustion cascade fires — the campaign's remaining provisional decisions are voided and every affected break recomputes, falling back to `MARKED` if emptied. Unlocking (`LOCKED` → `VALIDATED`) runs the compensation: every committed decision returns to `PROVISIONAL` and each campaign's `spent_cents` is reduced by the corresponding `committed_cost_cents`; if a campaign in `EXHAUSTED` thereby drops below its `total_budget_cents` and its `flight_end_date` is on or after the current logical date, it returns to `ACTIVE`.

Publishing (`LOCKED` → `PUBLISHED`) puts the loop on air. The channel must be `LIVE` — anything else is `ERR_CHANNEL_NOT_LIVE` — and its posture must not be `FROZEN`. The request must carry `expected_channel_version` matching the channel's current `version`, as detailed in §2.8. The `broadcast_date` must not be earlier than the current logical date (`ERR_BROADCAST_DATE_IN_PAST`). And the rights bar rises one notch: every entry's air window must now be covered by an `ACTIVE` grant — pending no longer suffices — and per covering grant, the grant's `plays_used` plus the number of entries it covers in this loop must not exceed `max_plays`, with equality permitted; shortfalls surface as `ERR_RIGHTS_WINDOW_VIOLATION` or `ERR_PLAYS_EXHAUSTED` respectively.

A successful publish ripples outward. Any other loop of this channel with the same `broadcast_date` still in `PUBLISHED` status becomes `SUPERSEDED`, and this loop's `supersedes_loop_id` is set to that displaced loop. For each content, the covering grant's `plays_used` increases by the number of entries of that content, and a grant whose `plays_used` reaches `max_plays` flips to `EXHAUSTED`, firing the content re-evaluation of §3.2 — which may drive the asset to `WINDOW_EXPIRED` with its own loop-revert cascade. The channel's `last_published_on` becomes the current logical date, the channel's `version` increments by one, and the posture recomputes — a publish is exactly what clears `GUARDED`, and superseding the offending loop is one of the two ways a `FROZEN` channel returns to `ACTIVE` (the other being an ops-run recompute that finds no violation and no staleness; in both cases the frozen rule must no longer hold and the channel must not be stale). The loop's `published_at` stamps the logical now.

Once its `broadcast_date` has passed, a loop in `PUBLISHED` or `SUPERSEDED` status may be archived, reaching terminal `ARCHIVED`.

### 3.5. Trafficking Demand: Campaigns, Creatives, and House Ads

An `AdOps` operator creates a campaign with the `advertiser_name`, the `iab_category` used for competitive separation, a `total_budget_cents` lifetime budget (positive), a `daily_budget_cents` cap on committed cost per broadcast date (positive and no greater than the total budget), the `cpm_cents` rate (positive cents per thousand impressions), and the flight window `flight_start_date` through `flight_end_date` — the end may not precede the start, else `ERR_INVALID_FLIGHT`. An optional `priority` defaults to 0 and acts as a ranking tier in which higher wins. A campaign starts in `DRAFT` with `spent_cents` at 0; `spent_cents` accrues committed cost, is adjusted at reconcile, and never goes negative. Campaigns may be listed filtered by `campaign_status` or `iab_category`, and fetched by `campaign_id`.

Activating a campaign (`DRAFT` → `ACTIVE`) requires at least one creative of the campaign in `APPROVED` status and a `flight_end_date` on or after the current logical date. Pausing (`ACTIVE` → `PAUSED`) voids all of the campaign's provisional decisions, and every affected break recomputes — a `DECIDED` break left with no provisional or committed decisions falls back to `MARKED`. Resuming (`PAUSED` → `ACTIVE`) requires `spent_cents` strictly below `total_budget_cents` — otherwise `ERR_BUDGET_EXHAUSTED` — and a flight that has not ended. Completing (`ACTIVE`, `PAUSED`, or `EXHAUSTED` → `COMPLETED`, terminal) fires the same provisional-voiding cascade as pausing. The system itself moves a campaign to `EXHAUSTED` the moment `spent_cents` reaches or exceeds `total_budget_cents` after a commit or a reconcile adjustment, firing that same cascade; and it moves an `EXHAUSTED` campaign back to `ACTIVE` when `spent_cents` drops below the total — after a void refund or a downward reconcile adjustment — provided the flight end is still today or later. A budget adjustment carrying `new_total_budget_cents` is rejected when the new total would fall below `spent_cents` (`ERR_BUDGET_BELOW_SPENT`); when an `EXHAUSTED` campaign's total is raised above its spend and its flight remains valid, the adjustment returns it to `ACTIVE`.

Creatives are trafficked by `AdOps` with the `campaign_id` they serve, a `brand`, an `iab_category`, and a `duration_seconds`. Trafficking records the caller's identity in `created_by_user_id` and starts the creative in `PENDING_REVIEW`. Review belongs to `AdQualityReviewer`, and three approve-time checks hold, evaluated in the priority order of §2.10 — segregation first (tier 6), then category match (tier 9), then ad quality (tier 10). The reviewer's identity must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the same segregation governs rejection. The creative's `iab_category` must equal its campaign's `iab_category`, else `ERR_CATEGORY_MISMATCH`. And the ad-quality rule requires `duration_seconds` to be exactly 30 or exactly 60, else `ERR_AD_QUALITY_RULE` — this check deliberately runs at approve time, not at trafficking time, so a non-conforming duration can be ingested but never approved. Approval sets `reviewed_by_user_id`; rejection records the request's `reason` into `rejection_reason` and likewise stamps `reviewed_by_user_id`. A rejected creative may be resubmitted, returning to `PENDING_REVIEW` with `rejection_reason` cleared. Retiring an `APPROVED` creative (terminal `RETIRED`) voids every provisional decision using it and recomputes the affected breaks — `COMMITTED` and `RECONCILED` decisions are untouched, since that inventory is already bought. Creatives may be listed filtered by `campaign_id` or `creative_status`, and fetched by `creative_id`.

House ads are the network's own promos, the filler of last resort. Creating one takes a `name`, a `priority_weight` (higher fills first), and a `daily_impression_cap` (positive; the maximum house placements per broadcast date). An optional `channel_id` restricts eligibility to one channel; when null, the house ad is eligible network-wide. Its `duration_seconds` defaults to 30 and must be exactly 30 — one slot, always. A house ad starts `ACTIVE` and moves between `ACTIVE` and `PAUSED`, or to terminal `RETIRED`, by status change requests carrying a `target_status`. House ads may be listed filtered by `channel_id` or `house_ad_status`, and fetched by `house_ad_id`.

### 3.6. The Decision Run: Server-Side Ad Insertion

When a loop has been validated and its breaks marked, an `AdOps` operator executes a decision run against a single break. The parent loop must be in `VALIDATED` or `LOCKED` status and the channel's posture must not be `FROZEN` (`ERR_CHANNEL_POSTURE_FROZEN`); the request must carry `expected_break_version` matching the break's current `version`, per §2.8. On a `MARKED` break the run moves it to `DECIDED`; on an already-`DECIDED` break the run first voids the break's existing provisional decisions as compensation and then executes the selector fresh. Either way the selector creates its direct and house placements as rows in `PROVISIONAL` status, the break's `version` increments by one, and the break's `direct_seconds`, `house_seconds`, and `slate_seconds` recompute. Slate slots are implicit: no decision row is ever created for them.

The selector works in a single greedy pass over the break's free slots in ascending `slot_index`, where the break's `slots` count is its `duration_seconds` divided by 30. At each position it first attempts a direct placement against the broadcast date D — the parent loop's `broadcast_date`. A creative is eligible when: its `creative_status` is `APPROVED`; its campaign's `campaign_status` is `ACTIVE`; D falls within the campaign's flight window from `flight_start_date` through `flight_end_date` inclusive; the creative's slot span — its `duration_seconds` divided by 30 — fits within the contiguous free slots at that position; and two fiscal checks pass, namely the campaign's `spent_cents` plus the candidate's committed cost must not exceed `total_budget_cents`, and the campaign's daily spend on D — the sum of `committed_cost_cents` over that campaign's provisional or committed decisions on loops whose `broadcast_date` is D, including reservations already made earlier in this run — plus the candidate's committed cost must not exceed `daily_budget_cents`.

Competitive separation then excludes a creative whose `iab_category` already appears among the direct decisions placed earlier in this run, or among the provisional or committed direct decisions of any adjacent break of the same loop. Adjacency is measured on the walk: for two breaks where the earlier break ends at e1 — its start offset plus its duration — and the later starts at s2, the gap is s2 minus e1; the breaks are adjacent when the gap is at or below the channel's `ad_separation_window_seconds`, and a gap exactly equal to the window counts as adjacent. The same category may likewise never appear twice within a single break.

Among eligible creatives, ranking is by the campaign's `cpm_cents` descending, then the campaign's `priority` descending, then the creative's `created_at` ascending, then the campaign's `created_at` ascending. Ids never participate in this ranking.

Slots with no direct fit fall to the house waterfall: the house ad must be `ACTIVE`; its `channel_id` must be null or equal to the loop's channel; and its placements on D so far must be strictly below its `daily_impression_cap`. House candidates rank by `priority_weight` descending and then `created_at` ascending, and each house placement occupies exactly one slot. Any slot still unfilled after both passes is slate.

Every decision row records its `break_id`, the `slot_index` of the first 30-second slot it occupies, and its `slots_spanned`. Its `fill_type` is `DIRECT` or `HOUSE`: a direct row carries `creative_id` and `campaign_id`, a house row carries `house_ad_id`, and each leaves the other side's references unset. A direct row's `expected_impressions` is the channel's `avg_slot_impressions` multiplied by `slots_spanned`; a house row's is 0. A direct row's `committed_cost_cents` is the campaign's `cpm_cents` multiplied by `expected_impressions` and divided by 1000, rounded half-up to whole cents; a house row's is 0. Both `actual_impressions` and `reconciled_cost_cents` remain null until reconciliation, and every row begins with `decision_status` `PROVISIONAL`. The break's `direct_seconds` total the seconds under its provisional, committed, or reconciled direct decisions; `house_seconds` total the seconds under its non-voided house decisions; and `slate_seconds` is whatever of `duration_seconds` remains.

A decision may also be voided directly by `AdOps` from either `PROVISIONAL` or `COMMITTED`. Voiding a committed decision refunds its `committed_cost_cents` from the campaign's `spent_cents`, which may return an `EXHAUSTED` campaign to `ACTIVE` when its flight remains valid; voiding a provisional one has no spend impact. In both cases the parent break recomputes, and when no provisional or committed decisions remain the break falls from `DECIDED` back to `MARKED` with its fill seconds recomputed to zero. That same `DECIDED` → `MARKED` collapse is the system's response whenever a break's decisions are all voided by an outside cause — campaign pause, completion, or exhaustion, creative retirement, loop revert, or manual void. Decisions may be listed filtered by `break_id`, `campaign_id`, `creative_id`, `house_ad_id`, `decision_status`, or `fill_type`, and fetched by `decision_id`.

### 3.7. Air, Reconciliation, and Viewership Measurement

Once the parent loop is `PUBLISHED`, a `ChannelProgrammer` marks a decided break as aired (`DECIDED` → `AIRED`), incrementing the break's `version`. After air, an `AdOps` reconcile moves the break to terminal `RECONCILED`. Each committed direct decision becomes `RECONCILED`: its `actual_impressions` is the sum of `quantity` over the `AD_IMPRESSION` viewership events carrying its `decision_id`, and its `reconciled_cost_cents` is the campaign's `cpm_cents` multiplied by `actual_impressions` and divided by 1000, rounded half-up. The campaign's `spent_cents` is then adjusted by the delta between reconciled and committed cost — which may be negative — and an `EXHAUSTED` campaign that drops below its total budget with its `flight_end_date` on or after the current logical date returns to `ACTIVE`. House decisions reconcile with `reconciled_cost_cents` of 0. Reconciling increments the break's `version`.

Viewership events are the raw measurement feed, ingested as an append-only stream by `DistributorPartner` callers or by `PlatformAdmin`. Every event names its `channel_id`, an `event_type` of `SESSION_START`, `SESSION_END`, `CONTENT_WATCH`, `AD_IMPRESSION`, or `AD_COMPLETE`, the opaque `viewer_session_id`, and the `occurred_at_utc` timestamp. Companion references are required by type: `break_id` for `AD_IMPRESSION` and `AD_COMPLETE`; `decision_id` additionally for `AD_IMPRESSION`; and `content_id` together with `watch_seconds` for `CONTENT_WATCH`. A `quantity` field, defaulting to 1 and required positive, applies to `AD_IMPRESSION` only — every impression count in this system is a sum of `quantity`, never a row count. A `DistributorPartner` caller's `platform_id` must equal the caller's own platform id; when omitted it is stamped from the caller's identity, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`. A `PlatformAdmin` caller must pass `platform_id` explicitly. Events may be listed — by internal roles only: `PlatformAdmin`, `ChannelProgrammer`, `AdOps`, `FinanceAnalyst`, and `FinanceController` — filtered by `channel_id`, `platform_id`, `break_id`, `decision_id`, `content_id`, or `event_type`, and fetched by `event_id`.

Measurement condenses into the channel-day snapshot, computed on demand by `PlatformAdmin` or `ChannelProgrammer` supplying a `snapshot_date`. One snapshot exists per (channel, date): recomputation upserts the same record, increments its `version`, and restamps `computed_at`. Every computed field reads the half-open day window from the snapshot date's 00:00:00Z up to, but not including, the next day's 00:00:00Z. `watch_seconds` sums the `watch_seconds` of `CONTENT_WATCH` events in the window. `peak_concurrent_viewers` replays the channel-day's `SESSION_START` events as +1 and `SESSION_END` events as −1, ordered by `occurred_at_utc` ascending with ties broken by `created_at` ascending; the running count never drops below zero, and the peak is the maximum the running count reaches. `ad_impressions` sums `quantity` over the window's `AD_IMPRESSION` events, and `direct_sold_impressions` does the same restricted to events whose decision's `fill_type` is `DIRECT`.

The supply side reads the date's `PUBLISHED` loop. `capacity_seconds` sums the break durations on that loop, and is 0 when no loop was published for the date. `direct_seconds` sums `slots_spanned` times 30 over that loop's direct decisions in `COMMITTED` or `RECONCILED` status; `house_seconds` is the same sum over house decisions. From these, `direct_fill_rate` is `direct_seconds` divided by `capacity_seconds`, and `effective_fill_rate` is the sum of `direct_seconds` and `house_seconds` divided by `capacity_seconds` — each a scale-4 fixed-point value rounded half-up, each exactly 0.0000 when `capacity_seconds` is 0. The direct rate, the fill quality seen by ad sales, excludes house filler and never exceeds the effective rate; the effective rate, the viewer-experience fill, equals 1.0000 minus the slate share. `direct_revenue_cents` sums, over the direct decisions on the date's loop, `reconciled_cost_cents` when the decision is `RECONCILED` and `committed_cost_cents` otherwise. `ecpm_cents` is `direct_revenue_cents` multiplied by 1000 and divided by `direct_sold_impressions`, rounded half-up — and is exactly 0, not null and not an error, when there are no direct-sold impressions.

The snapshot's `performance_score` condenses three of these signals into a 0-to-100 figure: the `direct_fill_rate` multiplied by 80 and rounded half-up to a whole number, plus a 20-point bonus when the day's `watch_seconds` reach at least 60,000, plus a further 20-point bonus when `ecpm_cents` reaches at least 2,000, with the total capped at 100 and each bonus contributing nothing below its threshold. Snapshots may be listed filtered by `channel_id` or `snapshot_date`, and fetched by `snapshot_id`.

### 3.8. Distribution Agreements and Revenue Settlement

A `PlatformAdmin` onboards a distributor platform with its `name` and a `reporting_tier` of `STANDARD` or `PREMIUM`; the platform starts in `ONBOARDING`. Status changes carrying a `target_status` move it from `ONBOARDING` to `ACTIVE`, between `ACTIVE` and `SUSPENDED` in either direction, and from any non-terminal state to terminal `OFFBOARDED` — which terminates every distribution agreement of that platform still in `NEGOTIATION`, `ACTIVE`, or `SUSPENDED`. Platforms may be listed filtered by `platform_status` and fetched by `platform_id`.

A distribution agreement binds one channel to one platform. Creating one takes `channel_id`, `platform_id`, the tiered revenue-share rates `rev_share_bps_below` and `rev_share_bps_above` (each between 0 and 6000 basis points inclusive, else `ERR_REV_SHARE_OUT_OF_RANGE`), the `tier_threshold_cents` split point (zero or more), an optional `minimum_guarantee_cents` floor per report (defaulting to 0, zero or more), and a closed effective window from `effective_start_date` through `effective_end_date`, both inclusive, with the end not before the start. For the same (channel, platform) pair, agreements in `NEGOTIATION`, `ACTIVE`, or `SUSPENDED` may not overlap under closed-interval semantics — and unlike rights grants, adjacency counts as overlap here — else `ERR_AGREEMENT_WINDOW_OVERLAP`. An agreement starts in `NEGOTIATION`, and its rate fields are editable only while it remains there. Agreements may be listed filtered by `channel_id`, `platform_id`, or `agreement_status`, and fetched by `agreement_id`.

First activation (`NEGOTIATION` → `ACTIVE`) requires the platform to be `ACTIVE` and the channel not `ARCHIVED`, and it pins the economics: `locked_rev_share_bps_below`, `locked_rev_share_bps_above`, `locked_tier_threshold_cents`, and `locked_minimum_guarantee_cents` are copied from the agreement's current values — until that moment all four are null. An agreement may move between `ACTIVE` and `SUSPENDED`; re-activation requires the platform to be `ACTIVE` and deliberately does not refresh the pinned snapshot, so the original locked rates persist. Termination from any non-terminal state, whether direct or through platform offboarding, lands in terminal `TERMINATED`.

Revenue reporting begins when a `FinanceAnalyst` creates a report with `channel_id`, `platform_id`, and the `period_month` in YYYY-MM form. Creation resolves the covering agreement: an agreement in `ACTIVE`, `SUSPENDED`, or `TERMINATED` status whose terms cover that (channel, platform, period) and which carries a locked rate snapshot — when none exists the creation fails with `ERR_NO_COVERING_AGREEMENT`. The period must be fully elapsed, meaning the current logical date is strictly after the last day of `period_month`, else `ERR_REPORT_PERIOD_NOT_ELAPSED`; the same check runs again at provisional generation and at finalize. Only one report may exist per (channel, platform, period), else `ERR_DUPLICATE_REPORT`. A created report stamps its `agreement_id` from the resolution and records the analyst in `generated_by_user_id`; it starts in `DRAFT` with `dispute_round` at 0, `calculation_variant` null, and `gross_revenue_cents`, `platform_share_cents`, and `net_revenue_cents` all null until first generation. Reports may be listed filtered by `channel_id`, `platform_id`, `agreement_id`, `report_status`, or `period_month`, and fetched by `report_id`; a `DistributorPartner` sees only their own platform's reports.

Generating the provisional figures (`DRAFT` → `PROVISIONAL`) computes the provisional variant and sets `calculation_variant` to `PROVISIONAL`. Recomputing — allowed while the report is `DRAFT` or `PROVISIONAL`, landing in `PROVISIONAL` — recomputes those figures, requires `expected_report_version` matching the report's current `version` per §2.8, and increments the report's `version`. Finalizing (`PROVISIONAL` → `FINALIZED`) belongs to a `FinanceController` who must not be the analyst recorded in `generated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; it computes the final variant from reconciled decisions only, against the agreement's locked rate snapshot, sets `calculation_variant` to `FINAL`, and stamps `finalized_by_user_id`. A `DistributorPartner` may then dispute a finalized report — only for their own platform, else `ERR_FORBIDDEN_OWNERSHIP` — carrying a `dispute_reason`, provided `dispute_round` is below the ceiling of 3; disputing at the ceiling is rejected with `ERR_DISPUTE_ROUND_LIMIT`. Refinalizing (`DISPUTED` → `FINALIZED`) again requires a `FinanceController` other than the generator, recomputes the final variant, and increments `dispute_round`. Settling (`FINALIZED` → `SETTLED`, terminal) carries the same segregation requirement.

Both variants share one attribution engine. For each (decision, platform) pair, the attributed revenue is the decision's campaign's `cpm_cents` multiplied by the impressions that decision earned on that platform — the sum of `quantity` over `AD_IMPRESSION` events carrying both that `decision_id` and that `platform_id` — divided by 1000, rounded half-up to whole cents. The rounding order is pinned: each per-pair amount is rounded first, and only then are the rounded integers summed into the platform's gross; summing first and rounding once is the rejected alternative and yields different cents. A report's included decisions are those on breaks of loops whose `broadcast_date` falls inside the `period_month`, filtered by variant: the provisional variant includes decisions in `COMMITTED` or `RECONCILED` status, while the final variant includes `RECONCILED` only — so the final gross is the smaller figure whenever unreconciled decisions carry impressions.

The statement itself evaluates in a pinned order that removes the circularity between the tier test and the share amount. First, gross is the attribution total for the report's platform. Second, tier selection reads gross alone: the below-tier portion is the smaller of gross and the locked threshold `locked_tier_threshold_cents`, and the above-tier portion is the excess of gross over that threshold — zero when gross does not exceed it. Third, the raw share is the below-tier portion multiplied by `locked_rev_share_bps_below` plus the above-tier portion multiplied by `locked_rev_share_bps_above`, in basis points. Fourth, `platform_share_cents` is the raw share divided by 10,000 and rounded half-up to whole cents, then raised to `locked_minimum_guarantee_cents` when that floor is higher. Fifth, `net_revenue_cents` is `gross_revenue_cents` minus `platform_share_cents`. The share rounds exactly once, at statement level — deliberately different from the per-pair rounding of the attribution engine.

## 4. Endpoint Definitions

Operations that create a new resource — a channel, a content asset, a grant, a loop, an entry, a break, a decision run's fill decisions, a campaign, a creative, a house ad, a platform, an agreement, a report, a viewership event, or a snapshot computation — return `201 Created`. Operations that modify an existing resource, including every state transition, return `200 OK`. Removals of entries and breaks return `204 No Content` with no data. The table below is a routing summary only; request payloads, derived fields, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/channels` | Create a channel (starts `DRAFT`, posture `ACTIVE`) | PlatformAdmin |
| GET | `/v1/channels` | List channels | Any |
| GET | `/v1/channels/{channel_id}` | Get one channel | Any |
| POST | `/v1/channels/{channel_id}/go-live` | Move a channel from `DRAFT` to `LIVE` | PlatformAdmin |
| POST | `/v1/channels/{channel_id}/suspend` | Move a channel from `LIVE` to `SUSPENDED` | PlatformAdmin |
| POST | `/v1/channels/{channel_id}/resume` | Move a channel from `SUSPENDED` back to `LIVE` | PlatformAdmin |
| POST | `/v1/channels/{channel_id}/take-offline` | Take a `LIVE` or `SUSPENDED` channel `OFFLINE` | PlatformAdmin |
| POST | `/v1/channels/{channel_id}/archive` | Archive an `OFFLINE` channel (terminal) | PlatformAdmin |
| POST | `/v1/channels/{channel_id}/run-ops` | Run the ops checkpoint: grant expiry and posture recompute | PlatformAdmin |
| POST | `/v1/content-assets` | Ingest a content asset (starts `INGESTING`) | ContentLicensing |
| GET | `/v1/content-assets` | List content assets | Any |
| GET | `/v1/content-assets/{content_id}` | Get one content asset | Any |
| POST | `/v1/content-assets/{content_id}/mark-available` | Move an asset from `INGESTING` to `AVAILABLE` | ContentLicensing |
| POST | `/v1/content-assets/{content_id}/pull` | Pull an `AVAILABLE` asset; loop-revert cascade | ContentLicensing |
| POST | `/v1/content-assets/{content_id}/reinstate` | Reinstate a `PULLED` asset to `AVAILABLE` | ContentLicensing |
| POST | `/v1/content-assets/{content_id}/archive` | Archive a `PULLED` asset (terminal) | ContentLicensing |
| POST | `/v1/rights-grants` | Create a rights grant (starts `PENDING`) | ContentLicensing |
| GET | `/v1/rights-grants` | List rights grants | Any |
| GET | `/v1/rights-grants/{grant_id}` | Get one rights grant | Any |
| POST | `/v1/rights-grants/{grant_id}/activate` | Activate a `PENDING` grant | ContentLicensing |
| POST | `/v1/rights-grants/{grant_id}/revoke` | Revoke a `PENDING` or `ACTIVE` grant | ContentLicensing |
| POST | `/v1/playlist-loops` | Create a playlist loop (starts `DRAFT`) | ChannelProgrammer |
| GET | `/v1/playlist-loops` | List playlist loops | Any |
| GET | `/v1/playlist-loops/{loop_id}` | Get one playlist loop | Any |
| POST | `/v1/playlist-loops/{loop_id}/entries` | Append a content entry to a `DRAFT` loop | ChannelProgrammer |
| GET | `/v1/playlist-entries` | List playlist entries | Any |
| GET | `/v1/playlist-entries/{entry_id}` | Get one playlist entry | Any |
| DELETE | `/v1/playlist-entries/{entry_id}` | Remove an entry from a `DRAFT` loop | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/ad-breaks` | Mark an ad break on a `DRAFT` loop | ChannelProgrammer |
| GET | `/v1/ad-breaks` | List ad breaks | Any |
| GET | `/v1/ad-breaks/{break_id}` | Get one ad break | Any |
| DELETE | `/v1/ad-breaks/{break_id}` | Remove a break from a `DRAFT` loop | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/validate` | Validate a `DRAFT` loop (tiling, capacity, rights) | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/revert-to-draft` | Revert a `VALIDATED` loop to `DRAFT` | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/lock` | Lock a `VALIDATED` loop; commits decisions and accrues spend | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/unlock` | Unlock a `LOCKED` loop; compensates decisions and refunds spend | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/publish` | Publish a `LOCKED` loop; supersedes, consumes plays, OCC on channel | ChannelProgrammer |
| POST | `/v1/playlist-loops/{loop_id}/archive` | Archive a past-dated `PUBLISHED` or `SUPERSEDED` loop | ChannelProgrammer |
| POST | `/v1/ad-breaks/{break_id}/decision-runs` | Execute the ad-insertion selector on a break; OCC on break | AdOps |
| POST | `/v1/ad-breaks/{break_id}/mark-aired` | Mark a `DECIDED` break as `AIRED` | ChannelProgrammer |
| POST | `/v1/ad-breaks/{break_id}/reconcile` | Reconcile an `AIRED` break against impression events | AdOps |
| GET | `/v1/fill-decisions` | List fill decisions | Any |
| GET | `/v1/fill-decisions/{decision_id}` | Get one fill decision | Any |
| POST | `/v1/fill-decisions/{decision_id}/void` | Void a `PROVISIONAL` or `COMMITTED` decision | AdOps |
| POST | `/v1/ad-campaigns` | Create an ad campaign (starts `DRAFT`) | AdOps |
| GET | `/v1/ad-campaigns` | List ad campaigns | Any |
| GET | `/v1/ad-campaigns/{campaign_id}` | Get one ad campaign | Any |
| POST | `/v1/ad-campaigns/{campaign_id}/activate` | Activate a `DRAFT` campaign | AdOps |
| POST | `/v1/ad-campaigns/{campaign_id}/pause` | Pause an `ACTIVE` campaign; voids its provisional decisions | AdOps |
| POST | `/v1/ad-campaigns/{campaign_id}/resume` | Resume a `PAUSED` campaign with budget headroom | AdOps |
| POST | `/v1/ad-campaigns/{campaign_id}/complete` | Complete a campaign (terminal) | AdOps |
| POST | `/v1/ad-campaigns/{campaign_id}/adjust-budget` | Raise or lower the campaign's total budget | AdOps |
| POST | `/v1/ad-creatives` | Traffic a creative (starts `PENDING_REVIEW`) | AdOps |
| GET | `/v1/ad-creatives` | List creatives | Any |
| GET | `/v1/ad-creatives/{creative_id}` | Get one creative | Any |
| POST | `/v1/ad-creatives/{creative_id}/approve` | Approve a `PENDING_REVIEW` creative | AdQualityReviewer |
| POST | `/v1/ad-creatives/{creative_id}/reject` | Reject a `PENDING_REVIEW` creative | AdQualityReviewer |
| POST | `/v1/ad-creatives/{creative_id}/resubmit` | Resubmit a `REJECTED` creative for review | AdOps |
| POST | `/v1/ad-creatives/{creative_id}/retire` | Retire an `APPROVED` creative (terminal) | AdOps |
| POST | `/v1/house-ads` | Create a house ad (starts `ACTIVE`) | AdOps |
| GET | `/v1/house-ads` | List house ads | Any |
| GET | `/v1/house-ads/{house_ad_id}` | Get one house ad | Any |
| PATCH | `/v1/house-ads/{house_ad_id}` | Change a house ad's status | AdOps |
| POST | `/v1/distributor-platforms` | Create a distributor platform (starts `ONBOARDING`) | PlatformAdmin |
| GET | `/v1/distributor-platforms` | List distributor platforms | Any |
| GET | `/v1/distributor-platforms/{platform_id}` | Get one distributor platform | Any |
| PATCH | `/v1/distributor-platforms/{platform_id}` | Change a platform's status; offboarding terminates agreements | PlatformAdmin |
| POST | `/v1/distribution-agreements` | Create a distribution agreement (starts `NEGOTIATION`) | PlatformAdmin |
| GET | `/v1/distribution-agreements` | List distribution agreements | Any |
| GET | `/v1/distribution-agreements/{agreement_id}` | Get one distribution agreement | Any |
| PATCH | `/v1/distribution-agreements/{agreement_id}` | Change an agreement's status; first activation pins locked rates | PlatformAdmin |
| POST | `/v1/revenue-reports` | Create a revenue report (starts `DRAFT`); resolves covering agreement | FinanceAnalyst |
| GET | `/v1/revenue-reports` | List revenue reports; partners see only their own platform's | PlatformAdmin, FinanceAnalyst, FinanceController, DistributorPartner |
| GET | `/v1/revenue-reports/{report_id}` | Get one revenue report; partners limited to their own platform | PlatformAdmin, FinanceAnalyst, FinanceController, DistributorPartner |
| POST | `/v1/revenue-reports/{report_id}/generate-provisional` | Compute the provisional variant | FinanceAnalyst |
| POST | `/v1/revenue-reports/{report_id}/recompute` | Recompute provisional figures; OCC on report | FinanceAnalyst |
| POST | `/v1/revenue-reports/{report_id}/finalize` | Finalize a `PROVISIONAL` report; computes the final variant | FinanceController |
| POST | `/v1/revenue-reports/{report_id}/dispute` | Dispute a `FINALIZED` report (own platform only) | DistributorPartner |
| POST | `/v1/revenue-reports/{report_id}/refinalize` | Refinalize a `DISPUTED` report; increments the dispute round | FinanceController |
| POST | `/v1/revenue-reports/{report_id}/settle` | Settle a `FINALIZED` report (terminal) | FinanceController |
| POST | `/v1/viewership-events` | Ingest a viewership or ad event (append-only) | DistributorPartner, PlatformAdmin |
| GET | `/v1/viewership-events` | List viewership events (internal roles only) | PlatformAdmin, ChannelProgrammer, AdOps, FinanceAnalyst, FinanceController |
| GET | `/v1/viewership-events/{event_id}` | Get one viewership event | PlatformAdmin, ChannelProgrammer, AdOps, FinanceAnalyst, FinanceController |
| POST | `/v1/channels/{channel_id}/snapshot-computations` | Compute (upsert) the channel-day snapshot for a date | PlatformAdmin, ChannelProgrammer |
| GET | `/v1/channel-day-snapshots` | List channel-day snapshots | Any |
| GET | `/v1/channel-day-snapshots/{snapshot_id}` | Get one channel-day snapshot | Any |
| POST | `/v1/_clock/set-current-utc` | Advance the logical clock (never backward) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CHANNEL_NOT_LIVE` | 409 Conflict |
| `ERR_CHANNEL_POSTURE_FROZEN` | 409 Conflict |
| `ERR_STALE_CHANNEL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BREAK_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REPORT_VERSION` | 412 Precondition Failed |
| `ERR_CONTENT_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_CATEGORY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_COVERING_AGREEMENT` | 422 Unprocessable Entity |
| `ERR_RIGHTS_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PLAYS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_AD_QUALITY_RULE` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_GRANT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BROADCAST_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INVALID_FLIGHT` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LOOP_DATE` | 409 Conflict |
| `ERR_LOOP_NOT_TILED` | 422 Unprocessable Entity |
| `ERR_LOOP_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_BREAK_DURATION_INVALID` | 422 Unprocessable Entity |
| `ERR_AD_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_REV_SHARE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DISPUTE_ROUND_LIMIT` | 422 Unprocessable Entity |
| `ERR_BUDGET_BELOW_SPENT` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXHAUSTED` | 422 Unprocessable Entity |

# Podcast Ad Sales & Dynamic Insertion API — Product Requirements Document

## 1. Introduction

A podcast ad network lives and dies by two promises that pull in opposite directions. To advertisers and their agencies it promises guaranteed, measured delivery: a booked number of qualified impressions, served against named shows and episodes, billed on a standard measurement basis, and made good when reality falls short. To show producers it promises editorial control: no gambling spot read over a health show whose host banned the category, no advertiser whose creative was never approved, no episode stuffed with more ads than its format allows. Reconciling those promises requires a single system of record for inventory forecasting, campaign flights, dynamic insertion decisions, download measurement, and settlement.

This document specifies the Podcast Ad Sales & Dynamic Insertion API, mounted under the `/adnet` prefix. The platform models shows and their episodes as a finite, forecastable pool of impressions; campaigns as contracted flights bought by advertisers directly or through agencies on a commission basis; line items as the reservation of that pool against a specific show or episode; and ad copy as a reviewed, version-controlled creative asset. Downloads arrive from player pings through an ingestion identity, are qualified provisionally at ingest and finally when an episode's measurement window closes, and drive both per-campaign delivery accounting and position-aware CPM billing. Shortfalls against booked impressions produce make-good offers that the buyer can accept — extending the flight — or decline for a cash credit, after which invoices are issued, disputed, and paid until the campaign reconciles.

Because the business runs on deadlines — publish schedules, measurement windows, attribution windows — the API is driven by a logical clock rather than wall-clock time, and every time-gated rule in this document is evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts: how callers authenticate, what every response looks like, how lists paginate, how time works, how money is rounded, and the order in which the server validates any request.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which they act. The declared roles are `AdOps`, `Advertiser`, `Agency`, `ShowProducer`, `Finance`, and `Ingestion`. A request missing either header, or presenting an `X-User-Role` value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role, and ownership scoping depends on them:

- When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the acting `Advertiser` entity. An advertiser may act only on its own campaigns, ad copies, and make-good decisions: any operation whose target resolves to a campaign compares the campaign's `advertiser_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Agency`, `X-User-ID` is the `id` of the acting `Agency` entity. An agency acts on behalf of the advertisers it represents: the advertiser referenced by the request must have `agency_id` equal to `X-User-ID`. If the referenced advertiser is direct or represented by a different agency, the request is rejected with `ERR_AGENCY_MISMATCH` (HTTP 403).
- When `X-User-Role` is `ShowProducer`, `X-User-ID` is the `id` of the acting producer's `Show` entity. A show producer reviews host-read scripts only for its own show: the copy's `show_id` must equal `X-User-ID`, otherwise `ERR_FORBIDDEN`.
- When `X-User-Role` is `AdOps`, `Finance`, or `Ingestion`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `AdOps` runs inventory, campaigns, line items, measurement, and the logical clock; `Finance` owns the invoice lifecycle; `Ingestion` is the measurement and attribution pipeline identity used by player pings and pixel or promo webhooks.

All six roles may read resources through the API's GET endpoints, subject to the per-endpoint role lists in §4; writes are restricted as described throughout §3.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the system — publish eligibility, measurement-window closure, flight containment, forecast horizons, slot occupancy, attribution windows — is evaluated against a single server-side **logical clock**, never against wall-clock time. At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. An `AdOps` operator may set the clock to any ISO-8601 UTC instant by supplying `to_iso8601`, moving it forward or backward; the clock never falls back to wall-clock time on its own. The response echoes the new time as `current_utc`. Setting the clock is a system-wide event: every show's inventory forecast and every episode's in-flight slot occupancy are recomputed against the new time, since both depend on where "now" sits.

### 2.5. Common Resource Properties

Primary resources — Show, Episode, Agency, Advertiser, Campaign, LineItem, AdCopy, Invoice, and MakeGood — share a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is the same format and refreshes on every modification. `version` is an integer starting at its initial value on creation and incrementing by one on every mutation of the resource, including mutations caused by cascaded recomputes originating elsewhere (for example, when a campaign's delivery counters are recomputed as a side effect of measurement finalization, the campaign's `version` advances and its `updated_at` refreshes).

Three ingest-side resources are deliberately lighter: Download, Impression, and AttributionEvent carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them; they are append-only records and are never patched.

### 2.6. Money, Impressions, and Rounding Discipline

All monetary amounts in the system are integer **cents** — `cpm_cents` on a campaign, `gross_cents`, `make_good_credit_cents`, `agency_commission_cents`, `net_cents`, and the per-line `line_cents` on an invoice are all whole numbers of cents. Wherever a calculation produces a fractional cent, the result is rounded **half-up** to the nearest integer cent. Agency commission rates are expressed in basis points: a `commission_bps` of 1500 means 15 percent. Position multipliers are expressed in per-mille of the base CPM: `PRE_ROLL` bills at 800 per mille (0.8×), `MID_ROLL` at 1000 per mille (1.0×), and `POST_ROLL` at 600 per mille (0.6×).

Impression forecasts are integer impressions produced by truncation: the inventory forecast multiplies a show's trailing average by its eligible episode count and a sell-through cap, then applies a floor to reach a whole number. Delivery counters, download counts, shortfalls, and slot counts are plain integer counts. Qualification and attribution flags are booleans with no rounding involved.

### 2.7. Optimistic Concurrency Control

Two write operations in the API are guarded by optimistic concurrency control, and only these two take a version field:

- Editing a campaign's flight or booking terms requires `expected_campaign_version` in the request body, carrying the client's last observed `version` of that campaign. If the stored `version` no longer matches — because any mutation, including cascaded `delivered_impressions` recomputes, has advanced it since the client last read the campaign — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting flight dates, `booked_impressions`, or `cpm_cents` it has not observed.
- Editing a show's baseline or brand-safety blocks requires `expected_show_version`, carrying the client's last observed `version` of that show. A mismatch with the stored version — which advances on every mutation, including cascaded reservation and forecast recomputes — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.8. Request Validation Pipeline

Every request is validated against an ordered pipeline; the first failing check wins and short-circuits all later checks. The order is fixed and significant:

1. **Authentication** — presence of `X-User-ID` and `X-User-Role` with a declared role, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role must be listed for the endpoint, else `ERR_FORBIDDEN`.
3. **Ownership and scope** — entity-backed scoping (an advertiser acting on another advertiser's resources, a producer reviewing another show's script) fails with `ERR_FORBIDDEN`.
4. **Agency representation** — when an `Agency` acts, the referenced advertiser's `agency_id` must equal the acting agency's id, else `ERR_AGENCY_MISMATCH`. This is evaluated immediately after general ownership and before existence checks.
5. **Existence** — path identifiers are validated left-to-right, and body foreign keys (`show_id`, `episode_id`, `campaign_id`, `advertiser_id`, `agency_id`, `ad_copy_id`, `invoice_id`) must reference existing resources, else `ERR_NOT_FOUND`.
6. **Optimistic concurrency** — the `expected_*_version` checks of §2.7, else `ERR_STALE_VERSION`.
7. **State legality** — the resource's current state must permit the requested operation under its state machine (for example `ERR_CAMPAIGN_NOT_ACTIVATABLE`, `ERR_LINE_ITEM_STATE`, `ERR_COPY_STATE`, `ERR_INVOICE_STATE`, `ERR_MAKE_GOOD_STATE`, `ERR_CAMPAIGN_NOT_EDITABLE`, `ERR_CAMPAIGN_NOT_ENDED`, `ERR_CAMPAIGN_NOT_ACTIVE`, `ERR_EPISODE_NOT_PUBLISHED`).
8. **Brand safety** — suspended-show and blocked-category screening (`ERR_SHOW_SUSPENDED`, `ERR_BRAND_SAFETY_CONFLICT`).
9. **Cross-reference integrity** — target scoping, host-read show binding, copy-to-campaign attachment, format matching, and promo-code presence (`ERR_TARGET_SCOPE_INVALID`, `ERR_HOST_READ_REQUIRES_SHOW`, `ERR_COPY_CAMPAIGN_MISMATCH`, `ERR_INVALID_REQUEST`).
10. **Temporal rules** — flight windows, publish dues, measurement closure, and measurement completeness (`ERR_FLIGHT_WINDOW_INVALID`, `ERR_EPISODE_NOT_DUE`, `ERR_MEASUREMENT_WINDOW_OPEN`, `ERR_MEASUREMENT_PENDING`).
11. **Structural business rules** — approved-copy requirements, category exclusivity, slot capacity, advertiser standing (`ERR_NO_APPROVED_COPY`, `ERR_COPY_NOT_APPROVED`, `ERR_CATEGORY_EXCLUSIVE_CONFLICT`, `ERR_SLOT_CAPACITY_EXCEEDED`, `ERR_ADVERTISER_SUSPENDED`).
12. **Inventory sufficiency** — run-of-show reservation feasibility (`ERR_INSUFFICIENT_INVENTORY`).
13. **Make-good settlement blocking** — invoice issuance while a make-good is outstanding (`ERR_MAKE_GOOD_OUTSTANDING`).
14. **Field shape** — malformed or missing required fields, enum values outside the declared sets, out-of-range integers, and duplicate-invoice attempts all surface as `ERR_INVALID_REQUEST`. This is the catch-all and runs only when no earlier category fired.

The practical consequence: a request that is both stale and brand-unsafe reports `ERR_STALE_VERSION`; one that targets a missing show with a malformed enum reports `ERR_NOT_FOUND`.

### 2.9. Provisional versus Final Measurement

The system maintains two parallel measurement lenses, and confusing them is a category error the API is designed to prevent. The **provisional** lens applies at download ingest: it excludes only bot-classified traffic, counts unknown agents and same-day repeat listens, and drives live counters such as an episode's `provisional_download_count` and report-only provisional delivery figures. The **final** lens applies exactly once, when an episode's measurement is finalized: it keeps only human-classified downloads inside the measurement window and deduplicates to one download per listener per UTC calendar day. Per-download `qualified_final` and per-impression `billable_final` stay null until that moment. Billing, shortfall computation, and make-good fulfillment are always evaluated on the final lens; the provisional lens exists for in-flight reporting and never persists a delivery figure onto a campaign.

## 3. Business Logic & Workflows

### 3.1. Building the Sellable Inventory: Shows and Episodes

An `AdOps` operator onboards a show by supplying its `title`, its editorial `content_category` — one of `TECHNOLOGY`, `BUSINESS`, `COMEDY`, `NEWS`, `HEALTH`, or `SPORTS` — and `avg_downloads_30d`, the trailing 30-day average of qualified downloads per episode, which must be zero or greater and serves as the forecast baseline. The producer's brand-safety voice is captured in `blocked_advertiser_categories`, an array of advertiser categories banned from the show that defaults to an empty list when omitted. A new show's `brand_safety_tier` starts at `CLEAR`, and with no episodes yet its `forecast_impressions` computes to zero and `reserved_impressions` to zero; `available_impressions` is always the forecast minus the reserved figure. Shows can be listed with optional `content_category` and `brand_safety_tier` filters, and an operator may later revise `avg_downloads_30d` or `blocked_advertiser_categories` through the OCC-guarded edit described in §2.7 — every such edit recomputes the forecast.

The **inventory forecast** answers "how many impressions can this show sell over the next 30 days?" Eligible episodes are those of the show whose `status` is `SCHEDULED` or `PUBLISHED` and whose `publish_at` falls inside the inclusive window from the current logical-clock instant to thirty days after it. The forecast equals the floor of `avg_downloads_30d` multiplied by the count of eligible episodes multiplied by the tier's sell-through cap: 0.95 while `CLEAR`, 0.70 while `FLAGGED`, and 0.00 while `SUSPENDED`. `reserved_impressions` is the sum of `reserved_impressions` over the show's `ACTIVE` run-of-show line items, and `available_impressions` is the difference — which may legitimately dip negative when the rolling horizon drops episodes that still hold active reservations; in that case the activation gate described in §3.4 simply fails. The forecast is recomputed whenever its inputs could move: episode creation, episode publish, measurement finalization, a show baseline edit, a tier transition, and every logical-clock adjustment.

A show's brand-safety posture is itself a small state machine driven by `AdOps` through tier transitions carrying a `to_tier`. From `CLEAR` a show may move to `FLAGGED` or directly to `SUSPENDED`; from `FLAGGED` it may return to `CLEAR` or escalate to `SUSPENDED`; from `SUSPENDED` it may be reinstated only to `FLAGGED`, never directly back to `CLEAR`. Every tier change recomputes the forecast with the new cap. Suspending a show — whether from `CLEAR` or `FLAGGED` — fires a full cascade: every `ACTIVE` line item targeting the show or any of its episodes moves to `PAUSED`, each pause releasing its reservation so the show's `reserved_impressions` and `available_impressions` are recomputed, and each campaign left without any remaining `ACTIVE` line item by this cascade bubbles up to `PAUSED` itself. Reinstatement, whether to `CLEAR` or to `FLAGGED`, never resumes paused line items or campaigns; an operator must reactivate them deliberately, and each reactivation re-runs the full activation gate.

Episodes are created under a show with a `title`, a scheduled `publish_at` instant, and two optional knobs: `measurement_window_days`, the number of days after publish during which downloads count toward final measurement (defaulting to 30, allowed from 1 to 90), and `slot_capacity`, the maximum number of distinct `ACTIVE` line items that may serve into one download of the episode (defaulting to 2, allowed from 1 to 5). A new episode is `SCHEDULED`, and its creation recomputes the owning show's forecast. Episode lists accept `show_id` and `status` filters.

An `AdOps` operator drives episode transitions by supplying an `action` naming the verb. Publishing is gated on the logical clock: an episode may move `SCHEDULED → PUBLISHED` only once the current clock time is at or after `publish_at`; earlier attempts are rejected with `ERR_EPISODE_NOT_DUE`. Publication recomputes the show's forecast. Later, measurement is finalized — `PUBLISHED → MEASURED`, the episode's terminal state — only when the clock has moved strictly past `publish_at` plus `measurement_window_days`; attempting finalization at or before that instant fails with `ERR_MEASUREMENT_WINDOW_OPEN`. Finalization is the moment the final measurement lens is applied, as detailed in §3.5: it sets `qualified_final` on every download of the episode, stores the count of qualifying downloads in `measured_download_count`, cascades `billable_final` onto every impression those downloads carried, recomputes `delivered_impressions` on every campaign that served into the episode, and recomputes the show's forecast since `MEASURED` episodes leave the eligible set.

### 3.2. Buyers, Agencies, and Campaign Flights

Agencies are registered by `AdOps` with a `name` and a `commission_bps` between 0 and 5000 — the agency's commission in basis points of post-credit gross, so 1500 encodes a 15 percent commission. Advertisers are registered with a `name`, a `category` drawn from `AUTOMOTIVE`, `CPG_FOOD`, `FINTECH`, `GAMBLING`, `ALCOHOL`, `HEALTH_PHARMA`, or `TECHNOLOGY` (this category drives both category exclusivity and brand-safety blocking), and an optional `agency_id` left null for direct advertisers. Advertiser lists accept `agency_id`, `category`, and `status` filters. A new advertiser's `status` is `ACTIVE`.

An `AdOps` operator may suspend an advertiser, moving it `ACTIVE → SUSPENDED`. Suspension cascades: every campaign of the advertiser in `ACTIVE` moves to `PAUSED`, every `ACTIVE` line item of each such campaign moves to `PAUSED` with its show-pool reservation released, and each affected show's `reserved_impressions` and `available_impressions` are recomputed. Reinstatement moves the advertiser `SUSPENDED → ACTIVE` but resumes nothing — paused campaigns and line items stay paused until individually reactivated.

A **campaign** is a contracted flight. Creating one — open to `AdOps`, to an `Advertiser` for itself, or to an `Agency` for a represented advertiser — takes the buying `advertiser_id`, a campaign `name`, the flight bounds `flight_start` (inclusive) and `flight_end` (exclusive) forming a half-open interval, the contracted `booked_impressions` (strictly greater than zero), the rate `cpm_cents` in cents per thousand qualified impressions (strictly greater than zero), and a `billing_model` of `ACTUAL_DELIVERY` or `BOOKED_GROSS`, which selects the invoicing variant and is immutable after creation. The advertiser must be `ACTIVE`, both at creation and at activation, or the request fails with `ERR_ADVERTISER_SUSPENDED`. `flight_end` must be strictly after `flight_start`; a non-positive window is rejected with `ERR_FLIGHT_WINDOW_INVALID` (HTTP 422). New campaigns are `DRAFT` with `delivered_impressions` at zero. Campaign lists accept `advertiser_id` and `status` filters.

Flight dates and booking terms may be edited while the campaign is `DRAFT` or `PAUSED` — never from `ACTIVE`, `ENDED`, `RECONCILED`, or `CANCELLED`, where the attempt fails with `ERR_CAMPAIGN_NOT_EDITABLE`. Such edits carry `flight_start`, `flight_end`, `booked_impressions`, or `cpm_cents`, and are OCC-guarded per §2.7; the same flight-window rule is re-enforced on every edit.

The campaign lifecycle proceeds as follows, with each transition requested by `AdOps` supplying an `action` naming the verb. Activation moves a campaign `DRAFT → ACTIVE` or resumes it `PAUSED → ACTIVE`; either requires the advertiser to be `ACTIVE` and at least one of the campaign's ad copies to be `APPROVED`, failing with `ERR_ADVERTISER_SUSPENDED` or `ERR_NO_APPROVED_COPY` respectively, and activation attempted from any other state fails with `ERR_CAMPAIGN_NOT_ACTIVATABLE`. An `ACTIVE` campaign may be paused manually by `AdOps` or by the system cascades above; notably, a manual pause does **not** pause the campaign's `ACTIVE` line items — they simply stop serving because the insertion selector requires the campaign to be `ACTIVE`. Ending a campaign, allowed from `ACTIVE` or `PAUSED`, moves every line item in `ACTIVE` or `PAUSED` to `ENDED` with reservations and episode slots released, recomputes `delivered_impressions`, evaluates make-good fulfillment if one of the campaign's make-goods is `ACCEPTED` (§3.7), and then performs the reconcile check: if the campaign's invoice is `PAID` and no make-good of the campaign is in `OFFERED` or `ACCEPTED`, the campaign does not rest in `ENDED` but advances directly to `RECONCILED`. A `DRAFT` campaign may instead be cancelled, moving `DRAFT → CANCELLED`, terminal. `ENDED → RECONCILED` may also fire later, the moment an invoice is marked paid while the campaign is `ENDED` and no make-good is in `OFFERED` or `ACCEPTED`. And one transition runs the lifecycle backward: when a make-good is accepted, the campaign moves `ENDED → ACTIVE` with its `flight_end` extended (§3.7). `CANCELLED` and `RECONCILED` are terminal.

A campaign's `delivered_impressions` is always the count of its impressions whose `billable_final` is true; an impression is only ever created when its download's `occurred_at` lies inside the campaign's half-open flight, so the delivered count never includes out-of-flight serves. A live **campaign report**, readable in any campaign status by all roles, returns the campaign's `campaign_id`, `status`, `booked_impressions`, final `delivered_impressions`, a report-only `provisional_delivered_impressions` (the count of its impressions with `billable_provisional` true — this over-counts relative to final since it skips dedupe and includes unknown agents), `shortfall_impressions` computed as `booked_impressions` minus `delivered_impressions` floored at zero, `attributed_promo_code_count` and `attributed_pixel_count` split from the campaign's attributed events, a `gross_cents_estimate`, and an `effective_cpm_cents`. The estimate follows the invoicing shape of §3.7: for `ACTUAL_DELIVERY` campaigns it applies per-line position multipliers over `billable_final` impressions with per-line rounding then a sum; for `BOOKED_GROSS` campaigns it is the booked charge regardless of delivery. `effective_cpm_cents` is zero when `delivered_impressions` is zero, and otherwise the half-up-rounded value of the gross estimate times one thousand divided by `delivered_impressions`.

### 3.3. Creative Review: Ad Copy from Draft to Approval

Ad copy is authored by the buyer side — an `Advertiser` for its own campaigns or an `Agency` for represented advertisers — by supplying the owning `campaign_id`, a `kind` of `HOST_READ_SCRIPT` or `PRODUCED_AUDIO`, and the `script_text` body (a verbatim host script or a produced-spot copy brief). A host-read script must name the `show_id` of the show whose host will read it; omitting it for that kind fails with `ERR_HOST_READ_REQUIRES_SHOW`. New copy starts in `DRAFT` with `revision` set to 1, and `script_text` remains editable while the copy is `DRAFT` or `CHANGES_REQUESTED`. Copy lists accept `campaign_id`, `show_id`, and `status` filters.

Submission moves copy `DRAFT → SUBMITTED`; resubmission out of `CHANGES_REQUESTED` moves it back to `SUBMITTED` and increments `revision` by exactly one. Submission from any other state fails with `ERR_COPY_STATE`. Review splits by creative kind: `HOST_READ_SCRIPT` is reviewed by the `ShowProducer` of the copy's show, while `PRODUCED_AUDIO` is reviewed by `AdOps`. Approval moves `SUBMITTED → APPROVED`. Requesting changes moves `SUBMITTED → CHANGES_REQUESTED`, and may also be applied to an already-`APPROVED` copy — a **revocation** that moves `APPROVED → CHANGES_REQUESTED` and immediately pauses every `ACTIVE` line item referencing that copy, releasing their reservations and episode slots. Review actions may carry an optional `note` for the author. Withdrawal is an owner-only privilege: the owning advertiser or its agency may withdraw a `DRAFT` copy, moving it to terminal `WITHDRAWN`; neither `AdOps` nor the `ShowProducer` may withdraw, and reviews or withdrawals attempted from states the machine forbids fail with `ERR_COPY_STATE`.

### 3.4. Selling the Inventory: Line Items, Safety Gates, and Exclusivity

A **line item** is where money meets inventory. `AdOps` creates one with the owning `campaign_id`; a target that is exactly one of `show_id` (run-of-show) or `episode_id` (episode-specific) — supplying both or neither fails with `ERR_TARGET_SCOPE_INVALID`; an `ad_format` of `HOST_READ` or `PRODUCED_SPOT`; a `position` of `PRE_ROLL`, `MID_ROLL`, or `POST_ROLL`, which feeds the billing position multiplier; a positive `reserved_impressions` quantity; an integer `priority` used as the serve-time ranking key; and the `ad_copy_id` of the creative to serve. The referenced copy must belong to the same campaign — a copy attached to another campaign fails with `ERR_COPY_CAMPAIGN_MISMATCH` (HTTP 409, since the copy exists but is misattached) — and the `ad_format` must match the copy's `kind` (`HOST_READ` pairs with `HOST_READ_SCRIPT`, `PRODUCED_SPOT` with `PRODUCED_AUDIO`), else `ERR_INVALID_REQUEST`. The owning campaign must be in `DRAFT`, `ACTIVE`, or `PAUSED` at creation; against an `ENDED`, `RECONCILED`, or `CANCELLED` campaign the create fails with `ERR_CAMPAIGN_NOT_EDITABLE`. Line-item lists accept `campaign_id`, `show_id`, `episode_id`, `ad_copy_id`, and `status` filters. New line items are `DRAFT` and hold no reservation.

Activation — `DRAFT → ACTIVE`, and identically resumption `PAUSED → ACTIVE` — runs the full sales-integrity gate, in the pipeline order of §2.8:

1. The owning campaign must be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`.
2. The target show's `brand_safety_tier` must not be `SUSPENDED`, else `ERR_SHOW_SUSPENDED`. (This screen also applies at line-item creation.)
3. The campaign advertiser's `category` must not appear in the target show's `blocked_advertiser_categories`, else `ERR_BRAND_SAFETY_CONFLICT`. (Also screened at creation.)
4. The referenced ad copy must be `APPROVED`, else `ERR_COPY_NOT_APPROVED`.
5. **Category exclusivity**: no other `ACTIVE` line item belonging to a *different* advertiser of the *same* category may target the same show with a flight overlapping the candidate's flight, else `ERR_CATEGORY_EXCLUSIVE_CONFLICT`. Two half-open flight intervals overlap when the first flight's start is strictly before the second flight's end, and the second flight's start is strictly before the first flight's end.
6. **Episode slot capacity** (episode-targeted items): the count of other `ACTIVE` episode-targeted line items on that episode whose campaign flights overlap the candidate's flight must be less than the episode's `slot_capacity`, else `ERR_SLOT_CAPACITY_EXCEEDED`.
7. **Inventory sufficiency** (run-of-show items): the item's `reserved_impressions` must not exceed the show's `available_impressions` — equality is allowed — else `ERR_INSUFFICIENT_INVENTORY`.

A successful activation debits the pool it sells against: a run-of-show item adds its `reserved_impressions` to the show's `reserved_impressions` and recomputes `available_impressions`; an episode-targeted item triggers recomputation of the episode's `slots_in_use`, defined as the count of `ACTIVE` episode-targeted line items whose campaign flight contains the current logical-clock instant (`slots_free`, the capacity minus that count, is what remains sellable).

Pausing an `ACTIVE` line item — manually by `AdOps`, or by the system when its show is suspended, its advertiser is suspended, or its ad copy is revoked — releases what it holds: a run-of-show item subtracts its `reserved_impressions` back out of the show's `reserved_impressions` and recomputes `available_impressions`, and an episode-targeted item's `slots_in_use` is recomputed. A manual pause never auto-pauses the owning campaign; the campaign bubble-pause fires only on the system cascades (show or advertiser suspension) when a cascade leaves the campaign with no remaining `ACTIVE` line item. Ending a line item — from `ACTIVE` or `PAUSED`, manually or because the campaign ended — moves it to terminal `ENDED` and releases the reservation or slot exactly as a pause does. Any transition the machine forbids, such as activating an `ENDED` item, fails with `ERR_LINE_ITEM_STATE`.

### 3.5. Dynamic Insertion and Download Measurement

Player pings arrive through the `Ingestion` identity as batched download events. Each batch names the `episode_id`, a `listener_key_prefix`, a `count` of downloads between 1 and 1000, the client-reported `occurred_at` instant (late arrival is permitted), and a `user_agent_class` of `HUMAN`, `BOT`, or `UNKNOWN`. The episode must be `PUBLISHED`; ingesting against a `SCHEDULED` or `MEASURED` episode fails with `ERR_EPISODE_NOT_PUBLISHED`. Each batch creates `count` Download records whose `listener_key` values are minted as the prefix, a hyphen, and the record's zero-based index within the batch — the first is the prefix followed by `-0`, the last the prefix followed by the index one less than `count`. Every download's `qualified_provisional` is set at ingest: true whenever `user_agent_class` is anything other than `BOT`. The episode's `provisional_download_count` is the running count of its provisionally qualified downloads.

Each ingested download fires the **dynamic insertion selector**. Eligible line items are those in `ACTIVE` status whose owning campaign is also `ACTIVE`, whose campaign flight contains the download's `occurred_at` within the half-open interval from `flight_start` up to but not including `flight_end`, and whose target matches — either the line item's `episode_id` is this episode, or its `show_id` is this episode's show. Eligible items are ranked by `priority` descending, ties broken by `created_at` ascending, and the top `slot_capacity` of them each receive an Impression on that download. An impression records the `download_id` that carried it, the `line_item_id` selected, the `campaign_id` denormalized from the line item at serve time, the `position` copied from the line item, and `served_at` set to the parent download's `occurred_at`. Its `billable_provisional` mirrors the download's `qualified_provisional` at serve time; `billable_final` remains null until the episode is measured. Impressions can be listed with `campaign_id`, `line_item_id`, or `download_id` filters, and an episode's downloads via the episode-scoped download list.

Final qualification lands once per episode at measurement finalization. The candidate set is the episode's downloads whose `user_agent_class` is `HUMAN` and whose `occurred_at` falls inside the measurement window from `publish_at` to `publish_at` plus `measurement_window_days`, with both bounds inclusive. Candidates are grouped by listener — the `listener_key` — and UTC calendar day of `occurred_at`; within each group only the download with the earliest `occurred_at` qualifies, so each listener contributes at most one qualified download per UTC day. `qualified_final` is set true for group winners and false for every other download of the episode; the cascade then writes `billable_final` onto each affected impression and recomputes campaign delivery as described in §3.1.

### 3.6. Attribution: Promo Codes and Pixels

Conversion signals arrive through the `Ingestion` identity as attribution events naming the `campaign_id`, a `kind` of `PROMO_CODE` or `PIXEL`, the client-reported `occurred_at` instant, and a `promo_code` that is required exactly when the kind is `PROMO_CODE` and must be absent otherwise — a presence mismatch fails with `ERR_INVALID_REQUEST`. At ingest the server computes the event's `attributed` flag: the event is attributed when its `occurred_at` falls on or after the campaign's `flight_start` and on or before the campaign's **current** `flight_end` plus thirty days — both bounds inclusive, and evaluated against whatever `flight_end` the campaign holds at ingest time, which matters when a make-good acceptance has extended the flight. Campaign-scoped attribution lists accept a `kind` filter, and the campaign report of §3.2 splits the attributed counts by kind.

### 3.7. Billing, Make-Goods, and Reconciliation

When a campaign has ended, `Finance` creates its invoice by naming the `campaign_id`. Creation requires the campaign to be `ENDED` — against any other status the request fails with `ERR_CAMPAIGN_NOT_ENDED` — and requires every episode that produced impressions for the campaign to be `MEASURED`, else `ERR_MEASUREMENT_PENDING`. Exactly one invoice may exist per campaign; a second attempt fails with `ERR_INVALID_REQUEST`. The invoice snapshots the campaign's `billing_model` at creation and freezes all amounts at that moment; nothing later recomputes them except the make-good decline credit described below.

Billing walks the campaign's line items. For each line item that produced at least one impression with `billable_final` true, the line's `billable_impressions` is that count, and its `line_cents` is computed by multiplying the line's billable impressions by the campaign's `cpm_cents` and by the position's per-mille multiplier (800 for `PRE_ROLL`, 1000 for `MID_ROLL`, 600 for `POST_ROLL`), dividing by one million, and rounding half-up to integer cents. Rounding order is pinned: each line is rounded first, then the lines are summed. The invoice's `lines` array freezes this per-line breakdown — `line_item_id`, `position`, `billable_impressions`, and `line_cents` — at creation. `delivered_impressions_billed` is the sum of the per-line billable counts. `shortfall_impressions` is `booked_impressions` minus `delivered_impressions_billed`, floored at zero. The gross depends on the billing variant: under `ACTUAL_DELIVERY`, `gross_cents` is the sum of the per-line amounts; under `BOOKED_GROSS`, `gross_cents` is the half-up-rounded value of `booked_impressions` times `cpm_cents` divided by one thousand, billed in full regardless of delivery or position.

Commission and credit follow a pinned evaluation order, each step using only earlier steps: first the delivered and shortfall figures, then `gross_cents`, then `make_good_credit_cents` — the half-up-rounded value of `shortfall_impressions` times `cpm_cents` divided by one thousand when a make-good of the campaign has been `DECLINED`, and zero otherwise — then `agency_commission_cents`, the half-up-rounded value of `gross_cents` minus `make_good_credit_cents`, multiplied by the agency's `commission_bps` and divided by ten thousand, applied only when the advertiser has an `agency_id` (direct advertisers pay zero commission), and finally `net_cents` as `gross_cents` minus `agency_commission_cents` minus `make_good_credit_cents`. The invariant `net_cents` plus `agency_commission_cents` plus `make_good_credit_cents` equals `gross_cents` always holds.

If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status, recording the `campaign_id`, the `invoice_id` that documented the shortfall, and `granted_impressions` equal to the invoice's `shortfall_impressions`. While any make-good of the campaign is `OFFERED`, issuing the invoice is blocked with `ERR_MAKE_GOOD_OUTSTANDING`. Invoice lists accept `campaign_id` and `status` filters; make-good lists accept `campaign_id`, `invoice_id`, and `status` filters.

The buyer side — the owning `Advertiser`, its representing `Agency`, or `AdOps` — answers the offer. **Acceptance** requires `extension_days` between 1 and 30 (missing or out of range fails with `ERR_INVALID_REQUEST`) and reopens the campaign: the campaign moves `ENDED → ACTIVE`, its `flight_end` is extended by `extension_days`, and the make-good snapshots `baseline_delivered_impressions` as the campaign's `delivered_impressions` at the moment of acceptance. Fulfillment is then judged when the campaign next ends: the bonus delivered is the campaign's `delivered_impressions` minus `baseline_delivered_impressions`, and if that bonus is greater than or equal to `granted_impressions` — an exact tie fulfills — the make-good moves `ACCEPTED → FULFILLED`, otherwise `ACCEPTED → EXPIRED`. **Declining** the offer grants cash instead: the still-`DRAFT` invoice recomputes with `make_good_credit_cents` set to the shortfall charge above, and `agency_commission_cents` and `net_cents` recomputed in the pinned order. Answering a make-good that is no longer `OFFERED` fails with `ERR_MAKE_GOOD_STATE`. `DECLINED`, `FULFILLED`, and `EXPIRED` are terminal.

The invoice lifecycle itself runs `DRAFT → ISSUED → PAID`, with a dispute branch `ISSUED → DISPUTED`, and re-issuance `DISPUTED → ISSUED` permitted — re-issuing does not recompute any amounts, since the figures frozen at creation (plus a decline credit) are final. Any transition outside this machine fails with `ERR_INVOICE_STATE`. Marking an invoice `PAID` performs the reconcile check of §3.2: if the campaign is `ENDED` and no make-good of the campaign is in `OFFERED` or `ACCEPTED`, the campaign advances to terminal `RECONCILED`, closing the loop from flight to settlement.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or perform a state transition return `200 OK`. All endpoints enforce the validation pipeline of §2.8 and the role lists below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; recomputes all forecasts and slot occupancy | AdOps |
| POST | `/adnet/shows` | Create a show | AdOps |
| GET | `/adnet/shows/{id}` | Get a show | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/shows` | List shows with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| PATCH | `/adnet/shows/{id}` | Edit show baseline / brand-safety blocks; OCC-guarded | AdOps |
| POST | `/adnet/shows/{id}/transition` | Move `brand_safety_tier` per the Show machine | AdOps |
| POST | `/adnet/episodes` | Create an episode | AdOps |
| GET | `/adnet/episodes/{id}` | Get an episode | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/episodes` | List episodes with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| POST | `/adnet/episodes/{id}/transition` | Publish or finalize measurement per the Episode machine | AdOps |
| GET | `/adnet/episodes/{id}/downloads` | List downloads of an episode | AdOps, Finance |
| POST | `/adnet/agencies` | Create an agency | AdOps |
| GET | `/adnet/agencies/{id}` | Get an agency | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| POST | `/adnet/advertisers` | Create an advertiser | AdOps |
| GET | `/adnet/advertisers/{id}` | Get an advertiser | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/advertisers` | List advertisers with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| POST | `/adnet/advertisers/{id}/transition` | Suspend or reinstate per the Advertiser machine | AdOps |
| POST | `/adnet/campaigns` | Create a campaign flight | AdOps, Advertiser, Agency |
| GET | `/adnet/campaigns/{id}` | Get a campaign | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/campaigns` | List campaigns with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| PATCH | `/adnet/campaigns/{id}` | Edit flight/booking while DRAFT or PAUSED; OCC-guarded | AdOps, Advertiser, Agency |
| POST | `/adnet/campaigns/{id}/transition` | Activate, pause, end, or cancel per the Campaign machine | AdOps |
| GET | `/adnet/campaigns/{id}/report` | Computed campaign delivery and attribution report | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/campaigns/{id}/attribution-events` | List attribution events of a campaign | AdOps, Advertiser, Agency, Finance |
| POST | `/adnet/line-items` | Create a line item (run-of-show or episode-targeted) | AdOps |
| GET | `/adnet/line-items/{id}` | Get a line item | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/line-items` | List line items with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| POST | `/adnet/line-items/{id}/transition` | Activate, pause, or end per the LineItem machine | AdOps |
| POST | `/adnet/ad-copies` | Create ad copy | Advertiser, Agency |
| GET | `/adnet/ad-copies/{id}` | Get ad copy | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| GET | `/adnet/ad-copies` | List ad copies with optional filters and pagination | AdOps, Advertiser, Agency, ShowProducer, Finance, Ingestion |
| POST | `/adnet/ad-copies/{id}/submit` | Submit copy for review; resubmission bumps `revision` | Advertiser, Agency |
| POST | `/adnet/ad-copies/{id}/review` | Approve, request changes (reviewer), or withdraw (owner) | AdOps, ShowProducer, Advertiser, Agency |
| POST | `/adnet/downloads` | Batch ingest of download pings; runs the insertion selector | Ingestion |
| GET | `/adnet/impressions/{id}` | Get an impression | AdOps, Finance |
| GET | `/adnet/impressions` | List impressions with optional filters and pagination | AdOps, Finance |
| POST | `/adnet/attribution-events` | Ingest a promo-code redemption or pixel hit | Ingestion |
| POST | `/adnet/invoices` | Create the single invoice for an ENDED campaign | Finance |
| GET | `/adnet/invoices/{id}` | Get an invoice | AdOps, Advertiser, Agency, Finance |
| GET | `/adnet/invoices` | List invoices with optional filters and pagination | AdOps, Advertiser, Agency, Finance |
| POST | `/adnet/invoices/{id}/transition` | Issue, dispute, or mark paid per the Invoice machine | Finance |
| GET | `/adnet/make-goods/{id}` | Get a make-good | AdOps, Advertiser, Agency, Finance |
| GET | `/adnet/make-goods` | List make-goods with optional filters and pagination | AdOps, Advertiser, Agency, Finance |
| POST | `/adnet/make-goods/{id}/transition` | Accept (extends the flight) or decline (grants cash credit) | Advertiser, Agency, AdOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_AGENCY_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EPISODE_NOT_PUBLISHED` | 409 |
| `ERR_EPISODE_NOT_DUE` | 409 |
| `ERR_MEASUREMENT_WINDOW_OPEN` | 409 |
| `ERR_MEASUREMENT_PENDING` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVATABLE` | 409 |
| `ERR_CAMPAIGN_NOT_EDITABLE` | 409 |
| `ERR_CAMPAIGN_NOT_ENDED` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_LINE_ITEM_STATE` | 409 |
| `ERR_COPY_STATE` | 409 |
| `ERR_NO_APPROVED_COPY` | 409 |
| `ERR_COPY_NOT_APPROVED` | 409 |
| `ERR_COPY_CAMPAIGN_MISMATCH` | 409 |
| `ERR_HOST_READ_REQUIRES_SHOW` | 400 |
| `ERR_TARGET_SCOPE_INVALID` | 400 |
| `ERR_BRAND_SAFETY_CONFLICT` | 409 |
| `ERR_SHOW_SUSPENDED` | 409 |
| `ERR_ADVERTISER_SUSPENDED` | 409 |
| `ERR_FLIGHT_WINDOW_INVALID` | 422 |
| `ERR_CATEGORY_EXCLUSIVE_CONFLICT` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_MAKE_GOOD_OUTSTANDING` | 409 |
| `ERR_MAKE_GOOD_STATE` | 409 |

# Self-Publishing & Print-on-Demand API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a self-publishing and print-on-demand (POD) platform of the kind that authors and small imprints use to bring a book from a raw manuscript to a distributed, revenue-generating product. The platform accepts uploaded manuscript and cover files, validates them against manufacturing constraints, attaches metadata and ISBNs, prices each edition per sales channel and territory, gates distribution behind a review step, and finally reconciles unit sales and returns into periodic royalty statements that culminate in a payout.

The system exists to make the economics of publishing deterministic. A print book's per-unit manufacturing cost, an ebook's royalty after delivery fees, the discount a wholesale channel takes at expanded reach, and the slice of every sale withheld against future returns are all computed by fixed rules rather than negotiated case by case. Because money is at stake, the platform treats every monetary figure as an integer count of minor currency units (cents), snapshots prices at the moment a sale posts, and keeps a running returns-reserve balance that is conserved exactly as sales and returns flow through it.

Three parties collaborate around a title. A **Publisher** owns the creative content and its commercial configuration — titles, formats, uploaded assets, proofs, prices, and distribution requests. A **Reviewer** acts as the distribution gate, approving or rejecting a publisher's request to list a format on a channel. A **PlatformAdmin** operates the shared machinery: the ISBN pool, asset validation, channel configuration, sales ingestion, statement issuance, payout, and the platform's logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This authentication check has the highest precedence of any validation and runs before anything else.

There are exactly three roles, spelled precisely as follows: `Publisher`, `Reviewer`, and `PlatformAdmin`. When a request is authenticated but the acting role is not permitted to perform the requested operation — or when a `Publisher` attempts to act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `Publisher`, `X-User-ID` is the `id` of the acting `Publisher` entity. Ownership checks compare the target resource's owning publisher to `X-User-ID`: for a `Title`, the resource's `publisher_id` must equal `X-User-ID`; for any resource that hangs off a title (a `Format`, and transitively its `Asset`, `Proof`, `ChannelPrice`, or `DistributionRequest`), the owning title's `publisher_id` must equal `X-User-ID`. A publisher may only read and mutate its own graph.

When `X-User-Role` is `Reviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Reviewer` gates distribution and does not own content. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `PlatformAdmin` operates shared platform machinery and may read across every entity.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a request asking for more than 100 items is clamped to 100. The `offset` parameter defaults to 0 and represents the number of leading items skipped. List results are ordered by `created_at` ascending — that is, oldest first — unless a specific endpoint narrative states otherwise. Each list response reports `limit`, `offset`, `total_count` (the number of rows matching the query before pagination), and `has_more` (true when unreturned rows remain beyond the current window) inside the `meta` object.

### 2.4. Common Resource Properties

Every resource in this system carries a server-minted `id` that is a UUID string with no type prefix. Every resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, fixed at the moment the row is inserted. Because all entities in this system are full first-class resources, each additionally carries an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on each mutation of that row. These four properties — `id`, `created_at`, `updated_at`, `version` — are managed by the server; clients never supply them on create.

Clients must never provide `id`, `created_at`, `updated_at`, or `version` in a request body; those are ignored if present. The `version` field is the anchor for optimistic concurrency (see §2.7) and its increments are called out explicitly wherever a workflow mutates a resource.

### 2.5. Monetary Precision and Rounding

All monetary amounts are integer counts of cents (minor currency units); the system never stores fractional cents. Wherever a computation produces a fractional intermediate — a per-page rate multiplied by a page count, a royalty rate multiplied by a list price, a reserve percentage multiplied by a gross amount — the result is rounded to the nearest whole cent using **round half up** (a value exactly halfway between two integers rounds to the larger integer). Spine widths are the one non-monetary computed quantity: they are expressed in millimetres and rounded to two decimal places, also using round half up.

The **order** in which rounding is applied matters and is fixed per calculation. As a rule, each calculation applies a single final rounding, except where a narrative below explicitly pins a different order (for example, the returns reserve is rounded per sales line at ingest, and a statement then sums those already-rounded per-line values rather than re-rounding a combined figure).

### 2.6. Cascading State Changes, Versioning, and Immediate Consistency

The platform is an immediately-consistent system: when an operation triggers downstream state changes across several entities, all of those changes are applied within the same request, before the response is returned. Several workflows in §3 cascade — publishing a format can lock its ISBN, activate approved distribution requests, and flip a title to live; withdrawing the last live distribution request can unlist a format and, in turn, its title. Whenever such a cascade mutates a resource, that resource's `updated_at` is refreshed and, where the narrative calls it out, its `version` is incremented. In particular, every state transition of a `Format` increments `Format.version` by 1.

### 2.7. Optimistic Concurrency on Format Pricing

Creating a `ChannelPrice` is guarded by optimistic concurrency keyed on the parent format's `version`. The price-create request must include `expected_format_version`, a non-optional field carrying the client's last observed `version` of the target `Format`. Before the price is created, the server compares `expected_format_version` to the format's current `version`. If they do not match — meaning another writer has advanced the format's version since the client last read it, for instance by creating a newer default price that superseded the client's expected base — the create is rejected with `ERR_STALE_FORMAT_VERSION` (HTTP 412), so the client cannot stack a supersede on an out-of-date base it never observed. No other endpoint in this system accepts or requires a version field.

### 2.8. Nested Path Resolution

Several endpoints address a resource through a parent path segment — for example, creating a format under a title, or an asset under a format. Path identifiers and body foreign keys are resolved left to right: the leftmost identifier is checked first, and the first one that fails to resolve to an existing row determines the error. Each entity type has its own not-found error — `ERR_PUBLISHER_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_FORMAT_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_ISBN_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_PRICE_NOT_FOUND`, and `ERR_SALESLINE_NOT_FOUND` (returned when a sales-line read cannot resolve its id) — each returned with HTTP 404.

### 2.9. The Logical Clock and Temporal Windows

Time in this system is driven by a server-held logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it never falls back to real time; before any client sets it, every temporal comparison uses that default. A `PlatformAdmin` may advance the clock to a supplied instant by providing `to_iso8601`. Temporal comparisons that depend on "now" — most importantly, whether a statement's reporting period has ended — read this logical clock.

Two kinds of temporal windows govern the domain. A **price effective window** on a `ChannelPrice` runs from `effective_from` (inclusive) to `effective_to` (exclusive); an `effective_to` of null means an open-ended default price with no upper bound. A **statement period** on a `RoyaltyStatement` runs from `period_start` to `period_end`, both bounds inclusive. The distinction in bound inclusivity is deliberate and is enforced by the overlap rules described in §3.

### 2.10. The Returns-Reserve Ledger

Because printed books can be returned by retailers well after they sell, the platform withholds a channel-defined fraction of every sale's royalty as a **returns reserve** and releases it on a delay. Each publisher carries a running `reserve_held_cents` balance that is the sum of the per-line reserve amounts across every `SalesLine` belonging to that publisher (reached through the sold format and its title). A `SALE` line contributes a positive reserve; a `RETURN` line contributes the exact negative, so that a sale which is later fully returned — same royalty per unit, same units, same channel — leaves the publisher's `reserve_held_cents` unchanged. This balance is reconciled on every sales-line ingest. Each publisher also carries `lifetime_paid_cents`, the cumulative sum of `net_payable_cents` over that publisher's statements that have reached the `PAID` status.

## 3. Business Logic & Workflows

The sections below trace a book from account setup through publication, distribution, sales, and payout. Rules that belong to a given moment in that lifecycle are described where they arise; the endpoint table in §4 and the error table in §5 are only indexes back into these narratives.

### 3.1. Accounts, ISBN Pool, and Channel Configuration

A `PlatformAdmin` opens a `Publisher` account by supplying a `name` and an `email`, and optionally a `payout_method`, which is one of `BANK` or `PAYPAL` and defaults to `BANK` when omitted. A freshly created publisher has `status` of `ACTIVE` — the only status a publisher ever holds — a `reserve_held_cents` of 0, and a `lifetime_paid_cents` of 0. Reading a publisher returns these balances alongside its identifying fields.

Each publisher owns a pool of ISBNs. A `PlatformAdmin` adds an ISBN to a specific publisher's pool by supplying the 13-digit string as `isbn_13`; the new `Isbn` is created with `status` `FREE` and its `assigned_format_id` null, and its `publisher_id` is the pool owner. An ISBN moves `FREE → ASSIGNED` when attached to a format, and `ASSIGNED → LOCKED` when that format publishes. ISBNs can be read individually or listed, filtered by their owning `publisher_id` or by the `assigned_format_id` they currently point at.

Sales channels are configured by a `PlatformAdmin`. A `Channel` has a display `name`, a `channel_type` of `RETAIL`, `LIBRARY`, or `DIRECT`, and a `supports_formats` array listing which of `PRINT`, `EBOOK`, and `AUDIO` it distributes. Its commercial parameters are the print wholesale discounts `distribution_discount_standard` and `distribution_discount_expanded`; the ebook royalty rates `ebook_high_rate` and `ebook_low_rate` together with the inclusive price-band bounds `ebook_rate_low_threshold_cents` and `ebook_rate_high_threshold_cents`; the `delivery_fee_per_mb_cents` charged per megabyte inside the ebook high-rate band (defaulting to 0); the `returns_reserve_pct` withheld from each sale; and the inclusive list-price acceptance range `min_list_price_cents` to `max_list_price_cents`. A channel can be read back by id.

### 3.2. Titles and Formats

A `Publisher` creates a `Title` by supplying its own `publisher_id` (which must equal `X-User-ID`), the `title`, the `language` as a BCP-47 code, and a `bisac_category` subject code; a `subtitle` is optional and defaults to null. A new title starts in `status` `DRAFT` and later moves to `LIVE` or `UNLISTED` as its formats are distributed or withdrawn (see §3.5 and §3.7). Titles may be read individually or listed, optionally filtered by `publisher_id`.

Under a title, a publisher creates a `Format`, choosing a `format_type` of `PRINT`, `EBOOK`, or `AUDIO`. The parent title is identified by `title_id`, taken from the path. Print formats additionally describe their physical build: a `trim_size` of `5x8`, `6x9`, `7x10`, or `8.5x11`; an `interior_color` of `BW`, `STANDARD_COLOR`, or `PREMIUM_COLOR`; and a `page_count`. Digital formats instead declare a `file_size_mb`, the delivery file size that drives ebook delivery fees. All of `trim_size`, `interior_color`, `page_count`, and `file_size_mb` default to null and apply only to the format types that use them. A format begins in `status` `DRAFT` and holds `isbn_id` and `print_cost_cents` as null until they are set.

For a `PRINT` format, the platform computes the per-unit manufacturing cost `print_cost_cents` at creation, and recomputes it whenever the `page_count`, `interior_color`, or `trim_size` change. The cost is built from a fixed charge of 85 cents, plus a per-page interior charge, plus a per-page surcharge for large trims. The per-page interior rate is selected by `interior_color`: 1.2 cents per page for `BW`, 7.0 cents per page for `STANDARD_COLOR`, and 10.0 cents per page for `PREMIUM_COLOR`. The trim surcharge applies only when `trim_size` is in the large-trim band — that is, `7x10` or `8.5x11` — and adds 0.5 cents for each page; for the standard-trim sizes `5x8` and `6x9` the surcharge is zero. Concretely, the cost is 85 cents, plus the page count multiplied by the color's per-page rate, plus the page count multiplied by the large-trim surcharge (which is 0.5 when the trim is large and 0 otherwise), with the total sum rounded half up to a whole number of cents. For `EBOOK` and `AUDIO` formats, `print_cost_cents` stays null. Formats can be read individually or listed, optionally filtered by `title_id`.

### 3.3. File Uploads and Asset Validation

A `Publisher` uploads files against a format as `Asset` records; the parent format is identified by `format_id` from the path. Each asset declares an `asset_type` of `INTERIOR` (the manuscript) or `COVER`, an opaque storage handle `file_ref`, and a `file_format` drawn from `PDF`, `EPUB`, `DOCX`, `AAX`, `JPG`, or `TIFF`. An interior upload also carries a `declared_page_count`. A cover upload carries the `paper_type` the book is printed on — `WHITE`, `CREAM`, or `COLOR` — and the `declared_spine_mm`, the spine width baked into the artwork. The optional fields `declared_page_count`, `paper_type`, and `declared_spine_mm` default to null and apply to the asset type that uses them. A new asset begins in `status` `PENDING` with `rejection_reason` null.

At the moment a cover is uploaded, the platform computes the required spine width `spine_width_mm` from the parent format's `page_count` and the cover's `paper_type`, and stores it on the asset. The required spine is the page count multiplied by the paper caliper, rounded half up to two decimal places. The caliper depends on `paper_type`: 0.0572 mm per page for `WHITE`, 0.0635 mm per page for `CREAM`, and 0.0572 mm per page for `COLOR`. Interior uploads do not compute a spine width.

A `PlatformAdmin` validates a pending asset, moving it from `PENDING` toward the terminal `VALIDATED` or `REJECTED`. Validation may only run while the asset is `PENDING`; attempting it in any other state yields `ERR_ASSET_INVALID_STATE` (HTTP 409). For an `INTERIOR` asset, validation passes when the `file_format` is one of `PDF`, `EPUB`, or `DOCX` and the `declared_page_count` is at least the minimum of 24 pages; if the declared page count is below 24, the asset instead transitions `PENDING → REJECTED` with `rejection_reason` set to `ERR_PAGE_COUNT_TOO_LOW`. The page-count check is applied first; an interior whose `declared_page_count` is at least 24 but whose `file_format` is not one of `PDF`, `EPUB`, or `DOCX` is likewise rejected `PENDING → REJECTED` with `rejection_reason` set to `ERR_PAGE_COUNT_TOO_LOW`. For a `COVER` asset, validation first recomputes `spine_width_mm` from the current `page_count` and `paper_type`, then passes when the `file_format` is one of `JPG`, `TIFF`, or `PDF` and the absolute difference between `declared_spine_mm` and the computed `spine_width_mm` is at most the tolerance of 0.5 mm; if that difference exceeds 0.5 mm — or the cover's `file_format` is not one of `JPG`, `TIFF`, or `PDF`, or either the declared or the computed spine is absent — the asset transitions `PENDING → REJECTED` with `rejection_reason` set to `ERR_SPINE_MISMATCH`. Both `ERR_PAGE_COUNT_TOO_LOW` and `ERR_SPINE_MISMATCH` are surfaced as the asset's `rejection_reason` on a 200 validate response that records the rejection — they are not returned as HTTP error bodies. Assets can be read individually or listed, optionally filtered by `format_id`.

### 3.4. ISBN Assignment, Content Lock, and the Proof Revision Cycle

Before a format can publish it needs an ISBN and a locked, proof-approved interior. A `Publisher` assigns an ISBN by naming the `isbn_id` to attach; the target `Isbn` must be `FREE` and must belong to the same publisher that owns the format, otherwise the assignment is rejected with `ERR_ISBN_NOT_AVAILABLE` (HTTP 409). A successful assignment transitions the ISBN `FREE → ASSIGNED`, sets its `assigned_format_id` to the format, sets the format's denormalized `isbn_id`, and increments `Format.version` by 1. A publisher may reverse this as a compensation, releasing the assigned ISBN back to `ASSIGNED → FREE`, clearing both `assigned_format_id` and the format's `isbn_id`, and again incrementing `Format.version` by 1; if the format has no assigned ISBN to release, the request is refused with `ERR_ISBN_NOT_ASSIGNED` (HTTP 409).

Locking content advances a format `DRAFT → CONTENT_LOCKED`. The lock may only run while the format is `DRAFT`; otherwise it is rejected with `ERR_FORMAT_INVALID_STATE` (HTTP 409). Locking additionally requires that the format have a `VALIDATED` `INTERIOR` asset — if none exists, the lock is refused with `ERR_MANUSCRIPT_NOT_VALIDATED` (HTTP 409). When the format is `PRINT`, locking further requires a `VALIDATED` `COVER` asset; a print format lacking a validated cover is refused with `ERR_COVER_NOT_APPROVED` (HTTP 409). A successful lock increments `Format.version` by 1.

Proofing runs against a locked (or draft) format. The server does not gate proof ordering on the format's status, however — a `Publisher` may order a proof regardless of the format's current state. A `Publisher` orders a proof copy, creating a `Proof` in `status` `ORDERED`; the `round_number` is assigned by the server, starting at 1 and incrementing by one for each new proof ordered on that format. The publisher then either approves the proof, moving it `ORDERED → APPROVED` and marking the format proof-approved so it may later publish, or requests a revision, moving it `ORDERED → REVISION_REQUESTED` and capturing the optional `revision_notes`. A proof action is only valid while the proof is `ORDERED`; otherwise it is rejected with `ERR_PROOF_INVALID_STATE` (HTTP 409). Requesting a revision has a cascading effect that closes the revision loop: if the parent format is currently `CONTENT_LOCKED`, the revision request transitions it back `CONTENT_LOCKED → DRAFT`, unlocking the content so the interior or cover can be re-uploaded, and increments `Format.version` by 1. Proofs can be read individually or listed, optionally filtered by `format_id`.

### 3.5. Channel Pricing and Royalty Snapshots

Pricing attaches a `ChannelPrice` to a format for a specific channel and territory. A `Publisher` supplies the target `channel_id`, a `territory` of `US`, `UK`, `EU`, or `ROW`, the consumer `list_price_cents`, and the window's `effective_from`; the `currency` is an ISO-4217 code defaulting to `USD`, the `effective_to` defaults to null for an open-ended default price, and `expanded_reach` defaults to false. The format being priced is identified from the path, and the create also carries the concurrency guard `expected_format_version` described in §2.7. A new price is created with `status` `ACTIVE`.

Several checks guard a price create, and when more than one could fire they are evaluated in a fixed precedence order that holds system-wide: first authentication (`ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_FORBIDDEN`), then existence of every path id and body foreign key resolved left to right (the relevant `ERR_*_NOT_FOUND`), then the target resource's required state (the relevant `ERR_*_INVALID_STATE`), then temporal-window validity, then referential business rules, then other business constraints, then fiscal bounds, then the optimistic-concurrency version check, and finally generic request-shape validation. In this ordering a lower-precedence failure is only reported once every higher-precedence check has passed. For a price create specifically this means: the effective window is checked (an `effective_to` that is not null must be strictly greater than `effective_from`, else `ERR_INVALID_EFFECTIVE_WINDOW`, HTTP 422); then the channel must actually distribute this `format_type`, i.e. the format's type must appear in the channel's `supports_formats`, else `ERR_CHANNEL_FORMAT_UNSUPPORTED` (HTTP 422); then the new window must not overlap an existing `ACTIVE` price for the same format, channel, and territory — windows are half-open, so two windows that merely touch at an endpoint do not overlap, but any true overlap yields `ERR_PRICE_WINDOW_OVERLAP` (HTTP 409); then the `list_price_cents` must fall within the channel's inclusive `min_list_price_cents` to `max_list_price_cents` range, else `ERR_PRICE_OUT_OF_BOUNDS` (HTTP 422); then the `expected_format_version` must match, else `ERR_STALE_FORMAT_VERSION` (HTTP 412); and any malformed body — a missing required field, a bad enum member, or a non-positive price — yields `ERR_INVALID_REQUEST` (HTTP 422).

When a new open-ended price (one whose `effective_to` is null) is created for a given format, channel, and territory, it supersedes the prior open-ended `ACTIVE` default for that same key: the previous price transitions `ACTIVE → SUPERSEDED` and has its `effective_to` closed to the new price's `effective_from`. Creating any price increments `Format.version` by 1, which is exactly why a stale `expected_format_version` signals that another writer has already superseded the base the client meant to build on. Prices can be read individually or listed, optionally filtered by `format_id` and/or `channel_id`.

At creation the platform snapshots the per-unit royalty into `royalty_per_unit_cents`, and the formula depends on the format type: a `PRINT` format uses the print formula below, while both `EBOOK` and `AUDIO` formats use the ebook formula below (an `AUDIO` format is priced with the same royalty rules as an `EBOOK`). The evaluation always resolves the format's `format_type` and its already-computed `print_cost_cents` first, then selects the variant, and applies a single final rounding half up to whole cents (the one exception being the ebook delivery fee, which is pre-rounded before entering the subtraction). For a `PRINT` format, the applicable wholesale discount is the channel's `distribution_discount_expanded` when `expanded_reach` is true and its `distribution_discount_standard` otherwise; the royalty per unit is the list price multiplied by one minus that discount, minus the format's `print_cost_cents`, the whole expression rounded half up. For an `EBOOK` format, the platform first decides whether the list price sits inside the channel's high-rate band, which runs from `ebook_rate_low_threshold_cents` to `ebook_rate_high_threshold_cents` inclusive of both ends: when `list_price_cents` is greater than or equal to the low threshold and less than or equal to the high threshold, the rate is `ebook_high_rate` and a delivery fee equal to the format's `file_size_mb` multiplied by the channel's `delivery_fee_per_mb_cents`, rounded half up, is charged; when the list price falls outside that band, the rate is `ebook_low_rate` and no delivery fee is charged. The ebook royalty per unit is then the list price multiplied by the selected rate, minus the delivery fee, rounded half up.

### 3.6. Distribution Requests

Getting a format onto a channel begins with a `Publisher` filing a `DistributionRequest`. The publisher names the target `channel_id` and the `territory`, and may set `expanded_reach` to request the channel's broader retailer network (it defaults to false). The format is taken from the path, and the request is created in `status` `REQUESTED`. Two gates apply at creation: the channel must distribute the format's `format_type` (its type must be in the channel's `supports_formats`, else `ERR_CHANNEL_FORMAT_UNSUPPORTED`, HTTP 422), and there must already exist an `ACTIVE`, in-bounds `ChannelPrice` for that format, channel, and territory — without one the request is refused with `ERR_NO_VALID_PRICE` (HTTP 409).

A `Reviewer` is the gate on a filed request, and the two outcomes are deliberately asymmetric. On **approval**, the request transitions `REQUESTED → APPROVED`; then, if the target format is already `PUBLISHED`, it immediately advances `APPROVED → LIVE` in the same operation, and any such advance to `LIVE` drives the parent title `DRAFT → LIVE` if the title is not already `LIVE`. If the format is not yet `PUBLISHED`, the request simply waits in `APPROVED` until the format publishes, at which point publication itself completes the advance to `LIVE` (see §3.7). On **rejection**, the request transitions `REQUESTED → REJECTED` and captures the reviewer's `reason`; this branch is divergent — the format's and the title's states are left completely untouched, and a rejected request can never reach `LIVE`. Both approve and reject require the request to be `REQUESTED`; acting on a request in any other state yields `ERR_DISTRIBUTION_INVALID_STATE` (HTTP 409). The advance to `LIVE` additionally requires the format to be `PUBLISHED`; a request that cannot reach `LIVE` because its format is not published is blocked with `ERR_FORMAT_NOT_PUBLISHED` (HTTP 409).

A `Publisher` may later **withdraw** a live listing, transitioning it `LIVE → WITHDRAWN`; withdrawal is only valid from `LIVE`, otherwise `ERR_DISTRIBUTION_INVALID_STATE`. Withdrawal triggers a downstream cascade: once the request is withdrawn, if no remaining `LIVE` distribution request exists for the format, the format transitions `PUBLISHED → UNLISTED`; and once a format goes unlisted, if every format under the parent title is now `UNLISTED`, the title transitions `LIVE → UNLISTED`. Distribution requests can be read individually — this read is available to `Publisher`, `PlatformAdmin`, and `Reviewer` — or listed, optionally filtered by `format_id` and/or `channel_id`.

### 3.7. Publishing and the Publication Cascade

Publishing is the pivotal act that turns a locked, proofed, ISBN-bearing edition into a live product. A `Publisher` publishes a format, transitioning it `CONTENT_LOCKED → PUBLISHED`. The format must be `CONTENT_LOCKED` — otherwise `ERR_FORMAT_INVALID_STATE` (HTTP 409) — and must have a proof that reached `APPROVED`; a format without an approved proof is not in a publishable condition and the publish is refused with `ERR_FORMAT_INVALID_STATE`. The format must also carry an assigned ISBN: if `isbn_id` is null, publication is refused with `ERR_ISBN_NOT_ASSIGNED` (HTTP 409).

A successful publish fans out a cascade in a fixed causal order. First the format itself moves `CONTENT_LOCKED → PUBLISHED`. That publication then locks the edition's identifier: the assigned `Isbn` (the one whose `assigned_format_id` points at this format) transitions `ASSIGNED → LOCKED`. It also activates the format's approved listings: every `DistributionRequest` for this format that is sitting in `APPROVED` transitions `APPROVED → LIVE`. Each of those requests reaching `LIVE` in turn drives the parent `Title` `DRAFT → LIVE` if the title is not already `LIVE`. Finally, publication increments `Format.version` by 1. Formats, titles, and ISBNs all reflect these state changes immediately in reads once the publish request returns.

### 3.8. Sales Ingestion and Reserve Reconciliation

A `PlatformAdmin` ingests each unit of activity as a `SalesLine`, supplying the sold `format_id`, the selling `channel_id`, the `territory`, a positive `units` count, a `line_type` of `SALE` or `RETURN`, and the `sale_date` on which it posted. Units must be positive; a non-positive `units` value is rejected with `ERR_INVALID_REQUEST` (HTTP 422). A new sales line is created in `status` `PENDING`, awaiting a statement.

To value the line, the platform selects the applicable price: among the `ACTIVE` `ChannelPrice` rows for that format, channel, and territory, it takes the one whose effective window contains the `sale_date` — that is, whose `effective_from` is at or before the sale date and whose `effective_to` is either null or strictly after the sale date. Should more than one somehow qualify, the tie is broken by taking the latest `effective_from` first and, failing that, the earliest `created_at`. If no price qualifies, the ingest is refused with `ERR_NO_VALID_PRICE` (HTTP 409). The selected price's `royalty_per_unit_cents` is snapshotted onto the sales line's own `royalty_per_unit_cents`.

From that snapshot the platform derives two amounts. The magnitude is the royalty per unit multiplied by the `units`. For a `SALE`, the `gross_royalty_cents` is that magnitude and the `reserve_held_cents` is the magnitude multiplied by the channel's `returns_reserve_pct`, rounded half up to whole cents. For a `RETURN`, both figures are negated: the `gross_royalty_cents` is the negative of the magnitude, and the `reserve_held_cents` is the negative of that same rounded reserve amount. The reserve is rounded on the positive magnitude before the sign is applied, so a return exactly reverses the reserve its matching sale contributed. Immediately after the line is stored, the owning publisher's `reserve_held_cents` is reconciled to the sum of `reserve_held_cents` across every sales line that belongs to that publisher through the sold format and its title — the conserved returns-reserve balance of §2.10. Sales lines can be read individually or listed, optionally filtered by `format_id` and/or `channel_id`.

### 3.9. Royalty Statements, Reserve Release, and Payout

A `PlatformAdmin` opens a `RoyaltyStatement` for a publisher by supplying the reporting `period_start` and `period_end`, with the payee's `publisher_id` taken from the path. Both bounds are inclusive. A new statement's period must not overlap any existing period for that publisher; because periods are closed-inclusive, two periods that merely touch at a shared endpoint are treated as overlapping and the create is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409). A fresh statement starts in `status` `ACCRUING`.

While a statement is `ACCRUING`, the platform maintains a forward-looking estimate in `provisional_net_cents`: the sum of `gross_royalty_cents` over the `PENDING` sales lines that would fall in the period, minus the corresponding sum of `reserve_held_cents`, ignoring any reserve maturing from a prior period. This value is recomputed live on every read of an `ACCRUING` statement. This provisional figure is an estimate only and does not lock any money.

Issuing a statement moves it `ACCRUING → ISSUED` and settles the numbers. Issuance requires the statement to be `ACCRUING` — otherwise `ERR_STATEMENT_INVALID_STATE` (HTTP 409); it requires the period to have ended, meaning `period_end` is at or before the logical clock's current instant, otherwise `ERR_PERIOD_NOT_ENDED` (HTTP 409); and it requires at least one `PENDING` sales line to fall within the period, otherwise `ERR_NO_SALES_IN_PERIOD` (HTTP 409). On issue, the platform sweeps every `PENDING` sales line of that publisher whose `sale_date` lies within the inclusive `period_start` to `period_end` window, moving each `PENDING → STATEMENTED`. The statement's `gross_royalty_cents` is the sum of the swept lines' `gross_royalty_cents`. Its `reserve_held_cents` is the sum of the swept lines' per-line `reserve_held_cents`; crucially, each line's reserve was already rounded when the line was ingested, and the statement sums those already-rounded per-line values rather than re-rounding a combined figure.

Issuance also matures the prior period's reserve. The statement's `reserve_released_cents` is the `reserve_held_cents` of this publisher's immediately-prior issued statement — the statement that has already been issued (its `status` is `ISSUED` or `PAID`) whose `period_start` is the greatest value strictly less than this statement's `period_start`; if no such prior statement exists, the released amount is 0. Reserve therefore matures after exactly one period. The final `net_payable_cents` locked at issue is the statement's `gross_royalty_cents`, minus its `reserve_held_cents`, plus its `reserve_released_cents`. At issue the statement's `provisional_net_cents` is also fixed to its `gross_royalty_cents` minus its `reserve_held_cents` (it does not include the released reserve) and stays at that value once the statement leaves `ACCRUING`.

Paying a statement moves it `ISSUED → PAID`; payment requires the statement to be `ISSUED`, otherwise `ERR_STATEMENT_INVALID_STATE` (HTTP 409). On payment, the owning publisher's `lifetime_paid_cents` is increased by the statement's `net_payable_cents`. Statements can be read individually or listed, optionally filtered by `publisher_id`.

An admin-only test-driving capability sets the server's logical clock to a supplied `to_iso8601` instant, which governs the period-ended check at issue time and any other comparison against the current instant.

## 4. Endpoint Definitions

The table below indexes every operation. Creating a new resource returns HTTP 201; state transitions and other modifications of an existing resource return HTTP 200; reads return 200. Request bodies, response payloads, and side effects are intentionally not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/publishers` | Create a publisher account | `PlatformAdmin` |
| GET | `/publishers/{id}` | Read a publisher (with reserve balance) | `Publisher`, `PlatformAdmin` |
| POST | `/publishers/{id}/isbns` | Add an ISBN to the publisher's pool | `PlatformAdmin` |
| POST | `/publishers/{id}/royalty-statements` | Open an accruing statement for a period | `PlatformAdmin` |
| POST | `/titles` | Create a title | `Publisher` |
| GET | `/titles/{id}` | Read a title | `Publisher`, `PlatformAdmin` |
| GET | `/titles` | List titles, filterable by publisher | `Publisher`, `PlatformAdmin` |
| POST | `/titles/{id}/formats` | Create a format under a title | `Publisher` |
| GET | `/formats/{id}` | Read a format | `Publisher`, `PlatformAdmin` |
| GET | `/formats` | List formats, filterable by title | `Publisher`, `PlatformAdmin` |
| POST | `/formats/{id}/lock` | Lock content (DRAFT to CONTENT_LOCKED) | `Publisher` |
| POST | `/formats/{id}/publish` | Publish (CONTENT_LOCKED to PUBLISHED, cascade) | `Publisher` |
| POST | `/formats/{id}/assign-isbn` | Assign a free pool ISBN to the format | `Publisher` |
| POST | `/formats/{id}/release-isbn` | Release the assigned ISBN back to free | `Publisher` |
| POST | `/formats/{id}/prices` | Create a channel price (OCC on format version) | `Publisher` |
| POST | `/formats/{id}/proofs` | Order a proof copy | `Publisher` |
| POST | `/formats/{id}/distribution-requests` | Request distribution to a channel/territory | `Publisher` |
| POST | `/formats/{id}/assets` | Upload an interior or cover asset | `Publisher` |
| POST | `/assets/{id}/validate` | Validate an asset (to VALIDATED or REJECTED) | `PlatformAdmin` |
| GET | `/assets/{id}` | Read an asset | `Publisher`, `PlatformAdmin` |
| GET | `/assets` | List assets, filterable by format | `Publisher`, `PlatformAdmin` |
| GET | `/isbns/{id}` | Read an ISBN | `Publisher`, `PlatformAdmin` |
| GET | `/isbns` | List ISBNs, filterable by publisher or assigned format | `Publisher`, `PlatformAdmin` |
| POST | `/channels` | Create a sales channel | `PlatformAdmin` |
| GET | `/channels/{id}` | Read a channel config | `Publisher`, `PlatformAdmin` |
| GET | `/prices/{id}` | Read a channel price | `Publisher`, `PlatformAdmin` |
| GET | `/prices` | List prices, filterable by format and/or channel | `Publisher`, `PlatformAdmin` |
| POST | `/proofs/{id}/approve` | Approve a proof (ORDERED to APPROVED) | `Publisher` |
| POST | `/proofs/{id}/request-revision` | Request revision (ORDERED to REVISION_REQUESTED) | `Publisher` |
| GET | `/proofs/{id}` | Read a proof | `Publisher`, `PlatformAdmin` |
| GET | `/proofs` | List proofs, filterable by format | `Publisher`, `PlatformAdmin` |
| POST | `/distribution-requests/{id}/approve` | Approve a request (to APPROVED, then LIVE if published) | `Reviewer` |
| POST | `/distribution-requests/{id}/reject` | Reject a request (to REJECTED) | `Reviewer` |
| POST | `/distribution-requests/{id}/withdraw` | Withdraw a live request (to WITHDRAWN, cascade) | `Publisher` |
| GET | `/distribution-requests/{id}` | Read a distribution request | `Publisher`, `PlatformAdmin`, `Reviewer` |
| GET | `/distribution-requests` | List distribution requests, filterable by format and/or channel | `Publisher`, `PlatformAdmin`, `Reviewer` |
| POST | `/sales-lines` | Ingest a sale/return line | `PlatformAdmin` |
| GET | `/sales-lines/{id}` | Read a sales line | `Publisher`, `PlatformAdmin` |
| GET | `/sales-lines` | List sales lines, filterable by format and/or channel | `Publisher`, `PlatformAdmin` |
| POST | `/royalty-statements/{id}/issue` | Issue a statement (ACCRUING to ISSUED, sweeps lines) | `PlatformAdmin` |
| POST | `/royalty-statements/{id}/pay` | Pay a statement (ISSUED to PAID) | `PlatformAdmin` |
| GET | `/royalty-statements/{id}` | Read a royalty statement | `Publisher`, `PlatformAdmin` |
| GET | `/royalty-statements` | List statements, filterable by publisher | `Publisher`, `PlatformAdmin` |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `PlatformAdmin` |

## 5. Error Code Catalogue

The conditions that trigger each error are described in the §2 and §3 narratives; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PUBLISHER_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_FORMAT_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_ISBN_NOT_FOUND` | 404 |
| `ERR_CHANNEL_NOT_FOUND` | 404 |
| `ERR_PROOF_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_PRICE_NOT_FOUND` | 404 |
| `ERR_SALESLINE_NOT_FOUND` | 404 |
| `ERR_ASSET_INVALID_STATE` | 409 |
| `ERR_FORMAT_INVALID_STATE` | 409 |
| `ERR_PROOF_INVALID_STATE` | 409 |
| `ERR_DISTRIBUTION_INVALID_STATE` | 409 |
| `ERR_STATEMENT_INVALID_STATE` | 409 |
| `ERR_MANUSCRIPT_NOT_VALIDATED` | 409 |
| `ERR_COVER_NOT_APPROVED` | 409 |
| `ERR_ISBN_NOT_ASSIGNED` | 409 |
| `ERR_ISBN_NOT_AVAILABLE` | 409 |
| `ERR_FORMAT_NOT_PUBLISHED` | 409 |
| `ERR_NO_SALES_IN_PERIOD` | 409 |
| `ERR_PERIOD_NOT_ENDED` | 409 |
| `ERR_INVALID_EFFECTIVE_WINDOW` | 422 |
| `ERR_PRICE_WINDOW_OVERLAP` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
| `ERR_CHANNEL_FORMAT_UNSUPPORTED` | 422 |
| `ERR_PAGE_COUNT_TOO_LOW` | 422 |
| `ERR_SPINE_MISMATCH` | 422 |
| `ERR_PRICE_OUT_OF_BOUNDS` | 422 |
| `ERR_NO_VALID_PRICE` | 409 |
| `ERR_STALE_FORMAT_VERSION` | 412 |

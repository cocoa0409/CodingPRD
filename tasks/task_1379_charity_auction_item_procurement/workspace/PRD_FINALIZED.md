# Charity Auction Procurement API — Product Requirements Document

## 1. Introduction

A nonprofit gala committee raises a meaningful share of its annual budget through the auction held at its flagship event, yet the operational trail behind that auction — who was asked for what, which items were valued at how much and by whom, what the catalog promised, who won, who paid, what was delivered, and what happened to the items nobody bought — is usually scattered across spreadsheets and inboxes. The Charity Auction Procurement API consolidates that entire trail into one system of record, covering the solicitation pipeline and donor tracking, independent valuation review with fair-market-value disclosure tiering, item bundling and minimum-bid setting, catalog publication and bidder registration, winning-bid checkout and payment processing, certificate fulfillment for experience items, unsold-item disposition, and written donor acknowledgment.

Two concerns shape the design throughout. First, fiscal defensibility: every winning bid is split into a revenue portion and a charitable contribution portion under a pinned set of rounding rules, donor-facing acknowledgments carry the fair market value as of issuance, and the event closes only through a gated reconciliation. Second, committee governance: valuation decisions are segregated from valuation submissions, unsold items cannot leave the building without the donor's explicit response, and several high-stakes writes are protected by optimistic concurrency so that no operator ever acts on a stale view of an event, item, or bundle.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `GalaAdmin`, `ProcurementOfficer`, `ValuationApprover`, `CatalogManager`, `FinanceOfficer`, `Bidder`, and `Donor`. A request with missing or invalid headers, or one naming a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Two of the seven roles are entity-backed. When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Bidder`; ownership checks on any resource that references a bidder — a bid, an invoice, or a certificate — compare the resource's `bidder_id` to `X-User-ID`. When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`; ownership checks on a disposition compare the disposition's `donor_id` to `X-User-ID`. A breach of either rule is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). Ownership is enforced on exactly three operations: `POST /invoices/{id}/payments`, `POST /certificates/{id}/redeem`, and `POST /dispositions/{id}/donor-response`.

The remaining five roles — `GalaAdmin`, `ProcurementOfficer`, `ValuationApprover`, `CatalogManager`, and `FinanceOfficer` — carry opaque operator identifiers not tied to any persisted entity. The server may record such an identifier (for example, as `submitted_by_user_id` or `decided_by_user_id` on a valuation) but never compares it to any entity's `id` for ownership purposes.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource served by this API — gala events, donors, bidders, solicitations, items, valuations, bundles, bids, invoices, payments, certificates, blackout windows, dispositions, and donor acknowledgments alike — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Mutations performed by cascades count as modifications: when a state transition on one resource rewrites a field on another — a recomputed `bundle_fmv_cents`, an advanced `payment_status`, a voided certificate — the affected resource's `updated_at` refreshes and its `version` increments. This convention provides a consistent audit trail and a reliable optimistic-concurrency handle for every entity in the system.

### 2.5. The Logical Clock

The server maintains a logical clock rather than reading the wall clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any administrative call it continues to read that default and never falls back to wall-clock time. Every timestamp the system stamps onto a resource — `last_sent_at` on a solicitation, `published_at` on a bundle, `placed_at` on a bid, `issued_at` on a certificate or an acknowledgment, `redeemed_at` on a redemption — is taken from this logical clock.

A `GalaAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Setting the clock also runs the certificate expiry sweep: every certificate still `ISSUED` whose `expires_at` is strictly earlier than the new current instant transitions to `EXPIRED`, with the downstream effects described in §3.8. A certificate whose `expires_at` equals the new current instant survives the sweep, because redemption remains legal at exactly that instant.

### 2.6. Monetary Values and Precision

All monetary values within the system — valuations, minimum bids, bid amounts, invoice portions, payments, and the event summary — are represented as integer cents. No floating-point arithmetic is ever applied to money. Where a calculation produces a fractional cent, it is rounded half-up to a whole cent at exactly the step the relevant rule specifies, and not at any other step; several rules in §3 pin their rounding placement because a different placement yields different cents. Datetime arithmetic for certificate validity uses second precision.

### 2.7. Optimistic Concurrency Control

Four write operations are protected by optimistic concurrency control. Each requires the client to supply, in the request body, a version field carrying the client last-observed `version` of the parent resource the operation targets. If the supplied value does not match the resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) — the client's view is stale and the write must not proceed on top of changes the client has not observed.

- `PATCH /gala-events/{id}` requires `expected_gala_event_version`, matched against the gala event's current `version`. An update to gala settings made against an event whose version has advanced since the client last read it is rejected, even when the update would otherwise be valid.
- `POST /items/{id}/valuations` requires `expected_item_version`, matched against the item's current `version`. Submission supersedes any still-`SUBMITTED` valuation on the item, so a client working from an out-of-date item view could silently supersede a valuation it never saw; the stale-version rejection prevents that.
- `PATCH /bundles/{id}/min-bid` requires `expected_bundle_version`, matched against the bundle's current `version` — for example, the computed minimum may have changed when the bundle was re-published after a detach.
- `POST /bundles/{id}/bids` requires `expected_bundle_version`, matched against the bundle's current `version`, because the amount decision was made against the client's observed `current_high_bid_cents`, which a newer accepted bid would have advanced.

Endpoints not listed above do not take a version field. Note that several of these operations also increment the target resource's `version` as part of a successful write — a settings update bumps the gala event's `version`, a valuation submission bumps the item's `version`, and a minimum-bid override or an accepted bid bumps the bundle's `version` — so a stale client is detected on its very next write.

### 2.8. Validation Order of Evaluation

Every request is evaluated against a single ordered cascade of checks; a failure at any step short-circuits the rest, so the error a client receives identifies the earliest failing category. The order is fixed:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — the role is permitted for this endpoint; otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Ownership** — for the three ownership-enforced operations named in §2.1, the entity-backed actor owns the target resource; otherwise `ERR_OWNERSHIP_VIOLATION` (HTTP 403).
4. **Existence** — path identifiers and body foreign-key references all exist, validated left to right; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **Request shape** — required fields are present, types and enum values are valid, and datetime ordering is valid (`bidding_opens_at` earlier than `bidding_closes_at` on event creation or update, blackout `starts_at` earlier than `ends_at`, redemption `scheduled_start` earlier than `scheduled_end`); otherwise `ERR_INVALID_REQUEST` (HTTP 400).
6. **Optimistic concurrency** — the supplied `expected_<parent>_version` equals the parent's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
7. **Generic state-machine legality** — the target entity's state machine permits the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
8. **Event phase** — the event's current phase permits the operation (solicitation sends and item receipts need `SOLICITING` or `CATALOGING`; bids need `BIDDING_OPEN`; gala settings updates need `DRAFT`, `SOLICITING`, or `CATALOGING`); otherwise `ERR_EVENT_PHASE_FORBIDDEN` (HTTP 409).
9. **Catalog freeze** — structural catalog edits (bundle creation, attach, detach, publish, minimum-bid override) are allowed only while the event is in `CATALOGING`; otherwise `ERR_CATALOG_FROZEN` (HTTP 409). The minimum-bid override additionally requires the bundle itself to be `PUBLISHED`, and a non-`PUBLISHED` bundle is rejected under step 7 with `ERR_INVALID_STATE`.
10. **Domain state preconditions** — the specific state each action demands: solicitation `PLEDGED` for item receipt (`ERR_SOLICITATION_NOT_PLEDGED`), valuation `SUBMITTED` for a decision (`ERR_VALUATION_ALREADY_DECIDED`), invoice `UNPAID` or `PARTIALLY_PAID` for a payment (`ERR_INVOICE_NOT_PAYABLE`), invoice `PAID` with no `REDEEMED` certificate for a refund (`ERR_REFUND_FORBIDDEN`), invoice `UNPAID` for a write-off (`ERR_WRITEOFF_FORBIDDEN`), certificate `ISSUED` for a redemption (`ERR_CERTIFICATE_NOT_REDEEMABLE`), disposition in the correct step for decide or donor-response (`ERR_DISPOSITION_FORBIDDEN`); all HTTP 409.
11. **Segregation of duties** — the valuation approver or rejecter differs from the submitter; otherwise `ERR_SOD_VIOLATION` (HTTP 403).
12. **Acknowledgment threshold** — issuance requires the acknowledgment's `fmv_cents` to be at least the event's `ack_threshold_cents`; otherwise `ERR_ACK_THRESHOLD_NOT_MET` (HTTP 422).
13. **Solicitation cooldown** — the donor is outside the cooldown window for the event; otherwise `ERR_SOLICITATION_COOLDOWN` (HTTP 409).
14. **Redemption window containment** — the scheduled experience window sits inside the certificate's validity and grace bounds; otherwise `ERR_REDEMPTION_WINDOW_INVALID` (HTTP 422).
15. **Blackout intersection** — the scheduled window does not intersect any member experience item's blackout window; otherwise `ERR_BLACKOUT_CONFLICT` (HTTP 409).
16. **Cross-entity referential rules** — the item is `VALUED` and unbundled and belongs to the bundle's event for an attach (`ERR_ITEM_NOT_VALUED`, `ERR_ITEM_ALREADY_BUNDLED`), the bidder is registered to the bundle's event (`ERR_BIDDER_EVENT_MISMATCH`), at least one published bundle exists before bidding opens (`ERR_NO_PUBLISHED_BUNDLES`), a rollover target is valid (`ERR_ROLLOVER_TARGET_INVALID`), and the reconcile gates hold (`ERR_RECONCILE_BLOCKED`); all HTTP 409.
17. **Paddle uniqueness** — the requested `paddle_no` is unused within the gala event; otherwise `ERR_PADDLE_TAKEN` (HTTP 409).
18. **Bidder eligibility** — the bidder is `REGISTERED` (`ERR_BIDDER_SUSPENDED`, HTTP 403) and has a payment method on file (`ERR_PAYMENT_METHOD_REQUIRED`, HTTP 422).
19. **Bid amount** — the offered amount reaches the minimum acceptable next bid; otherwise `ERR_BID_BELOW_MINIMUM` (HTTP 422).
20. **Minimum-bid floor** — an override value reaches the event's absolute floor; otherwise `ERR_MIN_BID_BELOW_FLOOR` (HTTP 422).
21. **Payment balance** — a payment amount lies within the invoice's outstanding balance; otherwise `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422).

### 2.9. Nested Resource Retrieval and Existence Checking

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example a detach carrying both a bundle `id` and an `item_id` — the system validates the existence of each identifier in sequential, left-to-right order and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource. Foreign keys supplied in request bodies, such as `donor_id`, `gala_event_id`, `solicitation_id`, or `target_gala_event_id`, are existence-checked in the same pass, before any state or business rule is evaluated.

### 2.10. Hierarchical Consistency: Cascades and Bubble-Ups

The system maintains consistency across entity boundaries automatically, without requiring an explicit client request on each affected resource. Two directions of propagation exist. Cascades flow downward: advancing an event past the close of bidding rewrites bundles, bids, items, invoices, certificates, and dispositions in one transaction; refunding or writing off an invoice unwinds its payments, certificate, winning bid, bundle, and member items and re-opens disposition for every member item. Bubble-ups flow upward: when an invoice's fulfillment completes or expires, its `SOLD` bundle advances to `SETTLED`, and when every member item's latest disposition has been executed, an `UNSOLD` bundle advances to `DISPOSITIONED`. Each hop of a cascade or bubble-up is a mutation of the affected resource, refreshing its `updated_at` and incrementing its `version` as stated in §2.4.

## 3. Business Logic & Workflows

### 3.1. Gala Event Configuration and Lifecycle Advancement

A `GalaAdmin` opens the season by creating a gala event with its `name` and `gala_date` (an ISO 8601 calendar date), the informational bidding window `bidding_opens_at` and `bidding_closes_at` (the opening instant must be earlier than the closing instant, or the request fails shape validation with `ERR_INVALID_REQUEST`), and the full policy configuration: `min_bid_pct_bps` expressing the default minimum bid as basis points of bundle fair market value (3000 means 30 percent), `min_bid_increment_cents` as the grid increment used to round minimum bids up, `min_bid_floor_cents` as the absolute floor any minimum bid must reach, `bid_increment_tiers` as an ordered array of objects each carrying `up_to_cents` and `increment_cents` (the last tier's `up_to_cents` is null, marking the open-ended top tier), `ack_threshold_cents` as the minimum item fair market value that requires a written donor acknowledgment, `solicitation_cooldown_days` as the number of days after a donor's most recent sent solicitation before that donor may be solicited again for the same event, `cert_validity_months` as the number of calendar months from certificate issuance to expiry, and `cert_grace_days` as the number of days beyond expiry within which a redemption's scheduled end may fall. A new event starts in `DRAFT` status.

While the event remains in `DRAFT`, `SOLICITING`, or `CATALOGING`, a `GalaAdmin` may update its settings, carrying any subset of `min_bid_pct_bps`, `min_bid_increment_cents`, `min_bid_floor_cents`, `bid_increment_tiers`, `ack_threshold_cents`, `solicitation_cooldown_days`, `cert_validity_months`, `cert_grace_days`, `bidding_opens_at`, and `bidding_closes_at`, alongside the mandatory `expected_gala_event_version`. Once the event has moved past `CATALOGING` the settings are locked, and an update attempt is rejected with `ERR_EVENT_PHASE_FORBIDDEN`. A successful update increments the event's `version` by one.

Lifecycle advancement is likewise a `GalaAdmin` prerogative and walks a single linear chain: `DRAFT` → `SOLICITING` → `CATALOGING` → `BIDDING_OPEN` → `BIDDING_CLOSED` → `SETTLEMENT`. Two steps carry consequences. Moving from `CATALOGING` to `BIDDING_OPEN` requires at least one bundle of the event to be `PUBLISHED`; with none, the advance is rejected with `ERR_NO_PUBLISHED_BUNDLES`. Moving from `BIDDING_OPEN` to `BIDDING_CLOSED` fires the close cascade described in §3.6. Each successful advance increments the event's `version` by one. The final step out of `SETTLEMENT` is not an advance but a reconciliation performed by a `FinanceOfficer`, moving the event to `RECONCILED` — the terminal state — only when the gates of §3.9 hold; a blocked reconciliation is rejected with `ERR_RECONCILE_BLOCKED`.

### 3.2. Donors and the Solicitation Pipeline

Before anything can be asked for, the committee needs donors. A `ProcurementOfficer` creates each donor with a `full_name`, a contact `email`, a `donor_type` of either `INDIVIDUAL` or `BUSINESS`, and an optional `tax_id`.

A solicitation records one ask of one donor for one event, created by a `ProcurementOfficer` with the `donor_id`, the `gala_event_id`, an `ask_description` of what was requested, and an `ask_estimate_cents` capturing the committee's estimate of the ask's value. A new solicitation starts in `DRAFT`. The committee's courtesy rule is enforced at creation and again at every send: for a given donor and event, if any *other* solicitation has a `last_sent_at` such that the current instant falls at or after that `last_sent_at` and strictly before that `last_sent_at` plus the event's `solicitation_cooldown_days` — a half-open window — the create or send is rejected with `ERR_SOLICITATION_COOLDOWN`. A solicitation may always re-send itself: its own `last_sent_at` never blocks its own re-send.

Sending, performed by a `ProcurementOfficer`, moves a solicitation from `DRAFT`, `REVISED`, or `STALLED` to `SENT` and stamps `last_sent_at` with the logical clock's current instant; until the first send, `last_sent_at` is null. The send is phase-gated: the solicitation's event must be in `SOLICITING` or `CATALOGING`, otherwise the attempt is rejected with `ERR_EVENT_PHASE_FORBIDDEN`.

When the ask needs reshaping after it has gone out, revision by a `ProcurementOfficer` pulls a `SENT` solicitation back to `REVISED`, replacing `ask_description` and `ask_estimate_cents` with the payload values. The loop from `SENT` to `REVISED` and back to `SENT` is a genuine cycle — each re-send refreshes `last_sent_at` and thereby re-arms the donor cooldown.

The donor's answer is recorded by a `ProcurementOfficer` through the record-response action, whose `outcome` takes one of four values. Against a `SENT` solicitation, `PLEDGED` moves it to `PLEDGED`, `DECLINED` moves it to `DECLINED`, and `STALLED` moves it to `STALLED`. Against any not-yet-terminal solicitation — `DRAFT`, `SENT`, `REVISED`, or `STALLED` — an `outcome` of `WITHDRAWN` moves it to `WITHDRAWN`. The terminal states are `DECLINED`, `WITHDRAWN`, and `FULFILLED`, the last reached only through item receipt as described next. For pipeline review, the solicitations of a donor and the solicitations of an event can each be listed.

### 3.3. Item Intake, Valuation Review, and Disclosure Tiering

When a pledged item physically arrives, a `ProcurementOfficer` records the receipt with a payload naming the `solicitation_id` plus the item's `title`, `description`, and `kind` — either `PHYSICAL` or `EXPERIENCE`. Receipt requires the solicitation's event to be in `SOLICITING` or `CATALOGING` (`ERR_EVENT_PHASE_FORBIDDEN` otherwise) and the solicitation itself to be `PLEDGED` (`ERR_SOLICITATION_NOT_PLEDGED` otherwise). The item is created in `RECEIVED` status with its `donor_id` and `gala_event_id` copied from the solicitation, its `bundle_id` null, and both `current_fmv_cents` and `disclosure_tier` null until the first approved valuation; in the same transaction the solicitation moves from `PLEDGED` to `FULFILLED`. Items can be listed with filters on `solicitation_id`, `donor_id`, `gala_event_id`, `bundle_id`, and `status`, with pagination.

Valuation begins when a `ProcurementOfficer` submits a valuation for an item, supplying `fmv_cents` (which must be at least one cent), an `fmv_source` of `DONOR_DECLARED`, `APPRAISAL`, or `COMPARABLE_SALE`, and the OCC field `expected_item_version`. Submission is destructive to pending competition: any valuation of the same item still `SUBMITTED` immediately transitions to `SUPERSEDED`, and the item's `version` increments by one. The submitting officer's `X-User-ID` is recorded as `submitted_by_user_id`; `decided_by_user_id` stays null until a decision. The valuations of an item can be listed in creation order.

Decisions belong to the `ValuationApprover`, and segregation of duties is absolute: the approving or rejecting user's `X-User-ID` must differ from the valuation's `submitted_by_user_id`, or the decision is rejected with `ERR_SOD_VIOLATION`. Only a `SUBMITTED` valuation can be decided; one already `APPROVED`, `REJECTED`, or `SUPERSEDED` rejects the attempt with `ERR_VALUATION_ALREADY_DECIDED`. The deciding user's identifier is stamped into `decided_by_user_id`. Rejection simply moves the valuation to `REJECTED` with no further effect.

Approval is where value enters the system. On the first approval for an item still `RECEIVED`, the item moves to `VALUED`, its `current_fmv_cents` is set to the approved valuation's `fmv_cents`, and its `disclosure_tier` is computed: `LOW` when the value is below 100000 cents, `MEDIUM` when it is at least 100000 and at most 500000 cents, and `HIGH` when it exceeds 500000 cents — so 99999 cents is `LOW`, exactly 100000 is `MEDIUM`, exactly 500000 is still `MEDIUM`, and 500001 is `HIGH`. The same approval also creates a donor acknowledgment for the item in `PENDING` status, of kind `DONATION_RECEIPT`, snapshotting the current `fmv_cents` and `disclosure_tier`.

Re-valuation keeps an item's bookkeeping honest without disturbing its logistics. When a later valuation is approved for an item in `VALUED`, `BUNDLED`, `CATALOGED`, `SOLD`, or `UNSOLD`, the item's status does not change — a bundled item stays `BUNDLED` — but its `current_fmv_cents` and `disclosure_tier` are updated from the new approval. Three side effects follow. If the item's donor acknowledgment is still `PENDING`, its `fmv_cents` and `disclosure_tier` are refreshed to the new approval, because acknowledgments track value as of issuance. If the acknowledgment was already `ISSUED`, it is voided and a fresh `PENDING` acknowledgment is created carrying the new value. And if the item sits inside a bundle still in `DRAFT`, that bundle's `bundle_fmv_cents` is recomputed; a `PUBLISHED` bundle's frozen `bundle_fmv_cents` and `min_bid_cents` do not change. Once an item has been terminally dispositioned — returned or discarded — re-valuation is blocked and the approval attempt fails the generic state check with `ERR_INVALID_STATE`.

### 3.4. Catalog Assembly: Bundles, Minimum Bids, and Blackout Windows

Catalog construction is the `CatalogManager`'s domain. Creating a bundle requires the event's `gala_event_id` and a catalog display `title`; the bundle starts in `DRAFT` with `bundle_fmv_cents` at zero, `min_bid_cents` null, `min_bid_overridden` false, `current_high_bid_cents` null, and `published_at` null. The bundles of an event can be listed.

Attaching an item to a bundle takes a payload containing the `item_id` and passes five gates: the bundle is `DRAFT`; the event is still `CATALOGING` (once the event has reached `BIDDING_OPEN` or beyond, the attempt is rejected with `ERR_CATALOG_FROZEN`); the item is `VALUED`, meaning it carries an approved valuation (`ERR_ITEM_NOT_VALUED` otherwise); the item's `bundle_id` is null (`ERR_ITEM_ALREADY_BUNDLED` otherwise); and the item belongs to the same event as the bundle. A successful attach moves the item from `VALUED` to `BUNDLED`, points its `bundle_id` at the bundle, recomputes the bundle's `bundle_fmv_cents` as the sum of its members' `current_fmv_cents`, and increments the bundle's `version`. Detaching — naming the bundle's `id` and the `item_id` in the path — is allowed under the same bundle-`DRAFT` and event-`CATALOGING` gates, returns the item from `BUNDLED` to `VALUED`, nulls its `bundle_id`, recomputes `bundle_fmv_cents`, and increments the bundle's `version`.

Publishing is the point of no return for pricing. A `CatalogManager` may publish a bundle only while the event is in `CATALOGING` (`ERR_CATALOG_FROZEN` otherwise) and only when the bundle has at least one member item (`ERR_BUNDLE_EMPTY` otherwise). Publication freezes `bundle_fmv_cents`, computes and stores the locked `min_bid_cents`, stamps `published_at` with the logical clock's instant, moves the bundle from `DRAFT` to `PUBLISHED`, moves every member item from `BUNDLED` to `CATALOGED`, and increments the bundle's `version`.

The minimum bid itself is produced in three pinned steps. First, the bundle's fair market value in cents is multiplied by the event's `min_bid_pct_bps` and divided by ten thousand, and the result is rounded half-up to whole cents — the basis-point rounding happens first. Second, if that rounded figure falls below the event's `min_bid_floor_cents`, it is raised to the floor — the floor applies only after the rounding. Third, the floored figure is rounded up to the next whole multiple of the event's `min_bid_increment_cents`. The evaluation order — basis-point rounding, then floor, then ceiling to the grid — is fixed; any other order yields different cents and is wrong. Two variants of this value exist. While the bundle is in `DRAFT`, reading it shows the preview variant, computed on the fly from the current member fair market values, so it shifts as valuations are approved or items attach and detach; the preview appears in every representation of a `DRAFT` bundle — the single-bundle read, the event's bundle list, and the attach and detach responses alike — with the sole exception of the create response, which returns the newly created bundle exactly as stored, with `min_bid_cents` null. At publish, the locked variant is computed once from the frozen `bundle_fmv_cents` and stored on `min_bid_cents`; valuation changes after publish never move the locked value, so preview and locked figures diverge whenever a valuation lands between the last preview and the publish.

Committee judgment can still override arithmetic. A `CatalogManager` may patch a bundle's minimum bid, but only while the bundle is `PUBLISHED` (any other bundle status fails the generic state check with `ERR_INVALID_STATE`) and the event remains in `CATALOGING` (`ERR_CATALOG_FROZEN` otherwise). The override value `min_bid_cents` must reach at least the event's `min_bid_floor_cents` (`ERR_MIN_BID_BELOW_FLOOR` otherwise), and the request must carry `expected_bundle_version` per §2.7. A successful override sets `min_bid_overridden` to true and increments the bundle's `version`.

Experience items need availability guardrails before the catalog opens. Against an item whose `kind` is `EXPERIENCE`, a `CatalogManager` registers blackout windows, each with a `starts_at`, an `ends_at` that must be strictly later than `starts_at` (`ERR_INVALID_REQUEST` otherwise), and an optional `label`. A blackout window is a half-open interval covering its `starts_at` and running up to but not including its `ends_at`. Blackout windows attach only to experience items; the attempt against a `PHYSICAL` item is rejected as an invalid request. The blackout windows of an item can be listed.

### 3.5. Bidder Registration and the Bidding Exchange

A `GalaAdmin` registers each bidder to exactly one event, supplying the `gala_event_id`, the bidder's `full_name`, `email`, a numeric `paddle_no`, and the boolean `payment_method_on_file`. Paddle numbers are unique within their event: a registration reusing a `paddle_no` already taken under the same `gala_event_id` is rejected with `ERR_PADDLE_TAKEN`. New bidders start `REGISTERED`; a `GalaAdmin` may later suspend a bidder by setting `status` to `SUSPENDED` and reinstate by setting it back to `REGISTERED`. The bidders of an event can be listed.

Placing a bid is the one moment of pure market pressure in the system, and it is gated accordingly. The acting user must carry the `Bidder` role, and the bid's `bidder_id` is taken from that user's `X-User-ID`; the payload carries the offered `amount_cents` and the OCC field `expected_bundle_version`, and the server stamps `placed_at` from the logical clock. The bundle's event must be in `BIDDING_OPEN` (`ERR_EVENT_PHASE_FORBIDDEN` otherwise). The bidder must be registered to the same event as the bundle (`ERR_BIDDER_EVENT_MISMATCH`), must be `REGISTERED` rather than `SUSPENDED` (`ERR_BIDDER_SUSPENDED`), and must have `payment_method_on_file` set (`ERR_PAYMENT_METHOD_REQUIRED`). Finally the amount must reach the minimum acceptable next bid, or the bid is rejected with `ERR_BID_BELOW_MINIMUM`.

That minimum is computed as follows. When no `ACTIVE` bid exists on the bundle, the minimum acceptable next bid is the bundle's `min_bid_cents`. Once a high bid exists, the system walks the event's `bid_increment_tiers` in order and selects the first tier whose `up_to_cents` is null — the open-ended top tier — or whose `up_to_cents` is strictly greater than the current high bid; the minimum acceptable next bid is then the current high bid plus the selected tier's `increment_cents`. Tier selection is strict at the boundary: a current high bid exactly equal to a tier's `up_to_cents` falls into the following tier. Consider an event whose tiers place a 5000-cent increment above a 100000-cent boundary — with the current high bid at exactly 100000 cents, the 100000-boundary tier does not apply, the 5000-cent increment governs, and the minimum acceptable bid is 105000 cents. Acceptance is inclusive: an `amount_cents` equal to the computed minimum is accepted.

Each accepted bid outbids its predecessor. The bundle's previous `ACTIVE` bid, if any, transitions to `OUTBID`, the new bid enters `ACTIVE`, and the bundle's `current_high_bid_cents` is updated to the new amount, with the bundle's `version` incrementing. Because every accepted bid strictly exceeds the previous high, at most one `ACTIVE` bid exists per bundle at any moment — and that single `ACTIVE` bid is the one the close cascade of §3.6 crowns as `WINNER`. Bids can be listed per bundle and per bidder.

### 3.6. Closing the Auction: Invoices and the Revenue–Contribution Split

When a `GalaAdmin` advances the event from `BIDDING_OPEN` to `BIDDING_CLOSED`, the close cascade settles every published bundle of the event in a deterministic order — `published_at` ascending, ties broken by `created_at` ascending.

For each `PUBLISHED` bundle holding at least one `ACTIVE` bid, the bundle transitions to `SOLD`. The single remaining `ACTIVE` bid — all earlier bids are already `OUTBID`, because each accepted bid strictly exceeded the previous high — transitions to `WINNER`. An invoice is then created for that winning bid, carrying the event's `gala_event_id` from the bundle, the `bundle_id`, the winning `bidder_id`, the `winning_bid_cents` pinned at the bid amount, and the `pinned_bundle_fmv_cents` copied from the bundle's frozen `bundle_fmv_cents`; the new invoice starts with `payment_status` `UNPAID` and `fulfillment_status` `PENDING`. If the sold bundle contains at least one member item whose `kind` is `EXPERIENCE`, a certificate is created for that invoice in `PENDING_ISSUE` status, bearing a unique human-facing `certificate_code` shaped as `CERT-` followed by eight hexadecimal characters; an invoice carries at most one certificate. For each `PUBLISHED` bundle with no `ACTIVE` bid at all, the bundle transitions instead to `UNSOLD`, every member item moves from `CATALOGED` to `UNSOLD`, and one disposition is created per member item in `PROPOSED` status with its `decision` null.

Every invoice records the auction's central accounting split in two variants. The aggregate variant is authoritative — it drives revenue recognition, invoice display, and payment accounting. Under it, `revenue_portion_cents` is the smaller of `winning_bid_cents` and `pinned_bundle_fmv_cents`, and `contribution_portion_cents` is the excess of `winning_bid_cents` over `pinned_bundle_fmv_cents`, floored at zero. The quid-pro-quo boundary is exact: a winning bid precisely equal to the pinned fair market value yields a contribution of zero, because a contribution exists only when the winning bid is strictly greater than the pinned value. The prorata variant, stored as `contribution_prorata_cents`, is a donor-facing disclosure estimate computed per member item: for each member item with an approved valuation at close, the item's allocation is the winning bid multiplied by that item's approved fair market value and divided by the pinned bundle fair market value, rounded half-up to whole cents per line; each line's contribution is the excess of its allocation over its own fair market value, floored at zero; and the prorata contribution is the sum of those per-line contributions. Per-line rounding is deliberately not reconciled back to the bid, so the sum of the allocations may differ from `winning_bid_cents` by a cent. The two variants diverge only through rounding placement: a bundle whose three member items carry approved values of 33333, 33333, and 33334 cents, sold at a winning bid of 150000 cents, reports an aggregate contribution of 50000 cents but a prorata estimate of 50001 cents.

### 3.7. Payments, Refunds, and Write-Offs

Checkout begins when the invoice's winning bidder creates a payment attempt, supplying `amount_cents` and a `method` of `CARD` or `CHECK`; the payment is stored against the invoice's `invoice_id` and starts in `INITIATED`. Only the bidder who owns the invoice may pay it (`ERR_OWNERSHIP_VIOLATION` otherwise), the invoice's `payment_status` must be `UNPAID` or `PARTIALLY_PAID` (`ERR_INVOICE_NOT_PAYABLE` otherwise), and the amount must be at least one cent and at most the outstanding balance (`ERR_PAYMENT_EXCEEDS_BALANCE` otherwise) — partial payments are expressly allowed. The payments of an invoice can be listed, and invoices can be listed with filters on `gala_event_id`, `bidder_id`, `bundle_id`, and `payment_status`.

The outstanding balance obeys a conserved ledger. An invoice's `amount_paid_cents` is the sum of the `amount_cents` of its `SUCCEEDED` payments minus the sum of the `amount_cents` of its `REFUNDED` payments; `INITIATED` and `FAILED` payments are excluded. The outstanding balance is `winning_bid_cents` minus `amount_paid_cents`, and a succeeded payment followed by its refund restores `amount_paid_cents` to its pre-payment value.

Settlement itself is driven by a `GalaAdmin`-only simulation capability that takes a `payment_id` and an `outcome` and moves an `INITIATED` payment to `SUCCEEDED` or `FAILED`. A failure mutates nothing on the invoice, and a fresh payment may be created afterward. A success recomputes the invoice's `amount_paid_cents` and may advance its `payment_status`: a payment covering less than the outstanding balance moves an `UNPAID` invoice to `PARTIALLY_PAID`, while one covering the full outstanding balance moves an `UNPAID` or `PARTIALLY_PAID` invoice to `PAID` and fires the paid cascade — `fulfillment_status` moves from `PENDING` to `READY`, and the invoice's certificate, if any, moves from `PENDING_ISSUE` to `ISSUED` with its validity window populated as §3.8 describes.

Two compensation paths exist for money that must move backward, both reserved to the `FinanceOfficer`. Refunding requires the invoice's `payment_status` to be `PAID` and any attached certificate to be in a status other than `REDEEMED` — redeemed experiences cannot be refunded — with both failures rejected as `ERR_REFUND_FORBIDDEN`. The refund cascade then moves every `SUCCEEDED` payment of the invoice to `REFUNDED` (so `amount_paid_cents` recomputes to zero), moves `fulfillment_status` to `VOIDED`, moves a certificate in `PENDING_ISSUE` or `ISSUED` to `VOIDED`, moves the `WINNER` bid to `VOID`, moves the bundle from `SOLD` back to `UNSOLD`, moves every member item from `SOLD` to `UNSOLD`, and creates one disposition in `PROPOSED` status per member item. Writing off is the harsher path for money that will never arrive: it requires `payment_status` `UNPAID` (a `PARTIALLY_PAID` or `PAID` invoice is rejected with `ERR_WRITEOFF_FORBIDDEN`), and it runs the same unwind — `fulfillment_status` to `VOIDED`, a `PENDING_ISSUE` certificate to `VOIDED`, the `WINNER` bid to `VOID`, the bundle from `SOLD` to `UNSOLD`, member items from `SOLD` to `UNSOLD`, and one `PROPOSED` disposition per member item. Both paths are deliberate re-openings: a refunded or written-off sale returns the bundle and its items to the disposition pipeline.

### 3.8. Certificates, Redemption, and Fulfillment

A certificate springs to life the moment its invoice reaches `PAID`: `issued_at` and `valid_from` are both set to the logical clock's current instant, `expires_at` is set to `issued_at` plus the event's `cert_validity_months` calendar months — preserving the day-of-month and the time-of-day — and `grace_end_at` is set to `expires_at` plus the event's `cert_grace_days` days. Until redemption, `redeemed_at`, `scheduled_start`, and `scheduled_end` remain null. The certificates of an invoice can be listed — the list holds zero or one element — and a certificate can be read directly.

Redemption belongs to the winning bidder, and only that bidder: the acting user's `X-User-ID` must match the invoice's `bidder_id`, or the attempt is rejected with `ERR_OWNERSHIP_VIOLATION`. The certificate must be `ISSUED`; any other status — including a certificate the expiry sweep has already moved to `EXPIRED` — is rejected with `ERR_CERTIFICATE_NOT_REDEEMABLE`. Redemption remains legal while the current instant is at or before `expires_at`; the bound is closed, so a redemption at exactly `expires_at` succeeds. The redeeming payload commits the experience window through `scheduled_start` and `scheduled_end`, and the window must sit inside containment bounds: `valid_from` at or before `scheduled_start`, `scheduled_start` strictly earlier than `scheduled_end`, and `scheduled_end` at or before `grace_end_at` — a `scheduled_end` exactly equal to `grace_end_at` is allowed. Any breach of containment is rejected with `ERR_REDEMPTION_WINDOW_INVALID`. Finally, the scheduled window must not intersect any blackout window of any `EXPERIENCE` member item of the bundle; intersection is tested on half-open intervals, so a window that merely touches a blackout's edge — adjacency — is allowed, while a true overlap is rejected with `ERR_BLACKOUT_CONFLICT`. A successful redemption stamps `redeemed_at` with the logical clock's instant, stores the scheduled window, moves the certificate from `ISSUED` to `REDEEMED`, moves the invoice's `fulfillment_status` from `READY` to `FULFILLED`, and bubbles the bundle from `SOLD` to `SETTLED`.

Time itself closes the window for certificates never redeemed. When the logical clock is set to an instant strictly later than an `ISSUED` certificate's `expires_at`, the expiry sweep moves that certificate to `EXPIRED`, moves the invoice's `fulfillment_status` from `READY` to `EXPIRED`, and likewise bubbles the bundle from `SOLD` to `SETTLED`.

Physical bundles take a simpler road. A `GalaAdmin` marks a physical-only invoice fulfilled, moving `fulfillment_status` from `READY` to `FULFILLED`; fulfillment requires `payment_status` `PAID`, and any attempt against a different payment state is rejected with `ERR_INVALID_STATE`. Here too the bundle bubbles from `SOLD` to `SETTLED`. Fulfillment is terminal in one of three states — `FULFILLED`, `EXPIRED`, or `VOIDED` — and a refund or write-off from `PENDING` or `READY` lands it in `VOIDED`.

### 3.9. Unsold Item Disposition, Donor Acknowledgments, and Event Reconciliation

Every item that fails to sell — whether at the close of bidding or through a refund or write-off — enters the disposition pipeline with a `PROPOSED` disposition recording the `item_id`, the `gala_event_id` of the event of origin (which never changes, even across a rollover), and the `donor_id` of the donor who must respond; `decision` starts null. A `GalaAdmin` then decides, setting `decision` to `RETURN_TO_DONOR`, `ROLLOVER`, or `DISCARD`; a `ROLLOVER` decision additionally requires a `target_gala_event_id` that exists, differs from the source event, and is in `DRAFT`, `SOLICITING`, or `CATALOGING` — a missing, identical, or wrong-phase target is rejected with `ERR_ROLLOVER_TARGET_INVALID`. Deciding against a disposition not in `PROPOSED` — or recording a donor response against one not in `DONOR_NOTIFIED` — is rejected with `ERR_DISPOSITION_FORBIDDEN`. A successful decision moves the disposition from `PROPOSED` to `DONOR_NOTIFIED`.

The donor's word is final. The acting `Donor`'s `X-User-ID` must equal the disposition's `donor_id` (`ERR_OWNERSHIP_VIOLATION` otherwise). Responding with `accept` true moves the disposition to `EXECUTED` and executes the decided path on the item. Under `RETURN_TO_DONOR`, the item moves from `UNSOLD` to `RETURNED_TO_DONOR`, and its donor acknowledgment — whether `PENDING` or `ISSUED` — is voided, because returned items receive no gift acknowledgment. Under `ROLLOVER`, the item's `gala_event_id` is rewritten to the target event, its `bundle_id` is nulled, and its status re-enters `VALUED` under the target event, ready to be bundled anew; the original acknowledgment is voided and a new `PENDING` acknowledgment is created under the target event carrying the item's current fair market value. Under `DISCARD`, the item moves from `UNSOLD` to `DISCARDED` and its acknowledgment is left unchanged, remaining issuable, since the gift was completed even though the item was not. Responding with `accept` false instead returns the disposition from `DONOR_NOTIFIED` to `PROPOSED`, clearing `decision` and `target_gala_event_id` back to null so the committee may reconsider. Dispositions can be listed with filters on `gala_event_id`, `item_id`, `donor_id`, `target_gala_event_id`, and `status`. When every member item's latest disposition has reached `EXECUTED`, the unsold bundle bubbles up from `UNSOLD` to `DISPOSITIONED`.

Donor acknowledgments run on their own clock of value. While an acknowledgment is `PENDING`, its `fmv_cents` and `disclosure_tier` track the item's latest `APPROVED` valuation — the as-of-issue rule — refreshing with each re-valuation. A `FinanceOfficer` issues the acknowledgment only when its `fmv_cents` reaches at least the event's `ack_threshold_cents`; the comparison is inclusive, so a value exactly equal to the threshold issues cleanly, and anything below it is rejected with `ERR_ACK_THRESHOLD_NOT_MET`. Issuance freezes `fmv_cents` and `disclosure_tier`, stamps `issued_at` with the logical clock's instant, and moves the acknowledgment from `PENDING` to `ISSUED`. This as-of-issue semantics contrasts with the invoice's pinned-at-sale semantics: `pinned_bundle_fmv_cents` is frozen at bundle publish and copied to the invoice at close, immune to later re-valuation, so when a re-valuation lands after the sale the acknowledgment reflects the new value — say 45000 cents — while the invoice still reports the pinned 40000 cents. A `FinanceOfficer` may also void an acknowledgment in `PENDING` or `ISSUED`, moving it to `VOIDED`, for example after a corrected valuation. Acknowledgments can be listed with filters on `donor_id`, `gala_event_id`, `item_id`, and `status`.

Reconciliation is the event's final gate, performed by a `FinanceOfficer` to move the event from `SETTLEMENT` to `RECONCILED`. It is blocked with `ERR_RECONCILE_BLOCKED` unless all three of the following hold: every invoice of the event has `payment_status` in `PAID`, `REFUNDED`, or `WRITTEN_OFF`; every invoice whose `payment_status` is `PAID` has `fulfillment_status` in `FULFILLED` or `EXPIRED`; and every disposition of the event has reached `EXECUTED`.

For oversight before and after that gate, a financial summary is available to `GalaAdmin` and `FinanceOfficer`. It reports `gross_winning_bids_cents`, the sum of `winning_bid_cents` over all invoices of the event; `collected_cents`, the sum of `amount_paid_cents` over those invoices; `outstanding_cents`, the sum of each invoice's `winning_bid_cents` minus its `amount_paid_cents`, taken only over invoices with `payment_status` `UNPAID` or `PARTIALLY_PAID`; `written_off_cents`, the sum of `winning_bid_cents` over invoices with `payment_status` `WRITTEN_OFF`; `refunded_cents`, the same sum over invoices with `payment_status` `REFUNDED`; `recognized_revenue_cents`, the sum of `revenue_portion_cents` over invoices with `payment_status` `PAID` only; `recognized_contribution_cents`, the sum of `contribution_portion_cents` over `PAID` invoices only; `prorata_contribution_cents`, the sum of `contribution_prorata_cents` over `PAID` invoices only; `unsold_item_count`, the count of the event's items in `UNSOLD` status; and `open_disposition_count`, the count of the event's dispositions in `PROPOSED` or `DONOR_NOTIFIED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource (an event, donor, bidder, solicitation, item, valuation, blackout window, bundle, bid, or payment) return a `201 Created` status code. Operations that modify an existing resource in place — advances, updates, publishes, decisions, simulations, redemptions, and the like — return a `200 OK` status code. The table below is a navigational summary only; request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/gala-events` | Create a gala event with its full policy configuration | GalaAdmin |
| GET | `/gala-events/{id}` | Read a gala event | All roles |
| PATCH | `/gala-events/{id}` | Update gala settings while the event is in DRAFT, SOLICITING, or CATALOGING; OCC-protected | GalaAdmin |
| POST | `/gala-events/{id}/advance` | Advance the event lifecycle; the BIDDING_OPEN to BIDDING_CLOSED step runs the close cascade | GalaAdmin |
| POST | `/gala-events/{id}/reconcile` | Move SETTLEMENT to RECONCILED when all aggregate gates hold | FinanceOfficer |
| GET | `/gala-events/{id}/summary` | Computed financial summary of the event | GalaAdmin, FinanceOfficer |
| POST | `/donors` | Create a donor | ProcurementOfficer |
| GET | `/donors/{id}` | Read a donor | All roles |
| POST | `/bidders` | Register a bidder to an event; paddle number unique per event | GalaAdmin |
| GET | `/bidders/{id}` | Read a bidder | All roles |
| POST | `/bidders/{id}/status` | Suspend or reinstate a bidder | GalaAdmin |
| GET | `/gala-events/{id}/bidders` | List the bidders of an event | All roles |
| POST | `/solicitations` | Create a solicitation in DRAFT; donor cooldown applies | ProcurementOfficer |
| GET | `/solicitations/{id}` | Read a solicitation | All roles |
| GET | `/donors/{id}/solicitations` | List the solicitations of a donor | All roles |
| GET | `/gala-events/{id}/solicitations` | List the solicitations of an event | All roles |
| POST | `/solicitations/{id}/send` | Send or re-send a solicitation; refreshes the last-sent stamp; cooldown-gated | ProcurementOfficer |
| POST | `/solicitations/{id}/revise` | Pull a SENT solicitation back to REVISED with new ask fields | ProcurementOfficer |
| POST | `/solicitations/{id}/record-response` | Record the donor outcome: PLEDGED, DECLINED, STALLED, or WITHDRAWN | ProcurementOfficer |
| POST | `/items` | Receive a pledged item; the solicitation moves to FULFILLED | ProcurementOfficer |
| GET | `/items/{id}` | Read an item | All roles |
| GET | `/items` | List items with foreign-key filters and pagination | All roles |
| POST | `/items/{id}/valuations` | Submit a valuation; supersedes any SUBMITTED valuation; OCC-protected | ProcurementOfficer |
| GET | `/items/{id}/valuations` | List the valuations of an item in creation order | All roles |
| POST | `/valuations/{id}/approve` | Approve a SUBMITTED valuation; approver must differ from the submitter | ValuationApprover |
| POST | `/valuations/{id}/reject` | Reject a SUBMITTED valuation; rejecter must differ from the submitter | ValuationApprover |
| POST | `/items/{id}/blackout-windows` | Add a half-open blackout window to an EXPERIENCE item | CatalogManager |
| GET | `/items/{id}/blackout-windows` | List the blackout windows of an item | All roles |
| POST | `/bundles` | Create an empty bundle in DRAFT | CatalogManager |
| GET | `/bundles/{id}` | Read a bundle: fair market value, minimum bid, current high bid | All roles |
| GET | `/gala-events/{id}/bundles` | List the bundles of an event | All roles |
| POST | `/bundles/{id}/items` | Attach a VALUED item to a DRAFT bundle | CatalogManager |
| DELETE | `/bundles/{id}/items/{item_id}` | Detach an item from a DRAFT bundle | CatalogManager |
| POST | `/bundles/{id}/publish` | Publish a bundle: freeze FMV, lock the minimum bid, move items to CATALOGED | CatalogManager |
| PATCH | `/bundles/{id}/min-bid` | Override the minimum bid of a PUBLISHED bundle; OCC-protected | CatalogManager |
| POST | `/bundles/{id}/bids` | Place a bid as the authenticated bidder; OCC-protected; outbids the previous ACTIVE bid | Bidder |
| GET | `/bundles/{id}/bids` | List the bids of a bundle | All roles |
| GET | `/bidders/{id}/bids` | List the bids of a bidder | All roles |
| GET | `/invoices/{id}` | Read an invoice: split portions and parallel statuses | All roles |
| GET | `/invoices` | List invoices with foreign-key filters | All roles |
| POST | `/invoices/{id}/payments` | Create a payment attempt as the invoice's bidder; partial payments allowed | Bidder |
| GET | `/invoices/{id}/payments` | List the payments of an invoice | All roles |
| POST | `/_payments/simulate` | Test-driving: settle an INITIATED payment as SUCCEEDED or FAILED | GalaAdmin |
| POST | `/invoices/{id}/refund` | Refund a PAID invoice; full compensation cascade | FinanceOfficer |
| POST | `/invoices/{id}/write-off` | Write off an UNPAID invoice; re-opens the bundle for disposition | FinanceOfficer |
| POST | `/invoices/{id}/fulfill` | Mark a physical bundle's invoice fulfilled | GalaAdmin |
| GET | `/invoices/{id}/certificates` | List the certificates of an invoice (zero or one element) | All roles |
| GET | `/certificates/{id}` | Read a certificate | All roles |
| POST | `/certificates/{id}/redeem` | Redeem an ISSUED certificate, committing the experience window | Bidder |
| GET | `/dispositions/{id}` | Read a disposition | All roles |
| GET | `/dispositions` | List dispositions with foreign-key filters | All roles |
| POST | `/dispositions/{id}/decide` | Committee decision: RETURN_TO_DONOR, ROLLOVER, or DISCARD | GalaAdmin |
| POST | `/dispositions/{id}/donor-response` | Donor accepts (executes) or declines (returns to PROPOSED) | Donor |
| GET | `/acknowledgments/{id}` | Read a donor acknowledgment | All roles |
| GET | `/acknowledgments` | List donor acknowledgments with foreign-key filters | All roles |
| POST | `/acknowledgments/{id}/issue` | Issue a PENDING acknowledgment whose FMV meets the event threshold | FinanceOfficer |
| POST | `/acknowledgments/{id}/void` | Void a PENDING or ISSUED acknowledgment | FinanceOfficer |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical clock; runs the certificate expiry sweep | GalaAdmin |

## 5. Error Code Catalogue

The table below catalogues every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EVENT_PHASE_FORBIDDEN` | 409 Conflict |
| `ERR_CATALOG_FROZEN` | 409 Conflict |
| `ERR_SOLICITATION_COOLDOWN` | 409 Conflict |
| `ERR_SOLICITATION_NOT_PLEDGED` | 409 Conflict |
| `ERR_ITEM_NOT_VALUED` | 409 Conflict |
| `ERR_ITEM_ALREADY_BUNDLED` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_VALUATION_ALREADY_DECIDED` | 409 Conflict |
| `ERR_BUNDLE_EMPTY` | 422 Unprocessable Entity |
| `ERR_MIN_BID_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_BID_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_BIDDER_EVENT_MISMATCH` | 403 Forbidden |
| `ERR_BIDDER_SUSPENDED` | 403 Forbidden |
| `ERR_PAYMENT_METHOD_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_REFUND_FORBIDDEN` | 409 Conflict |
| `ERR_WRITEOFF_FORBIDDEN` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_REDEMPTION_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_BLACKOUT_CONFLICT` | 409 Conflict |
| `ERR_DISPOSITION_FORBIDDEN` | 409 Conflict |
| `ERR_ROLLOVER_TARGET_INVALID` | 409 Conflict |
| `ERR_ACK_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_RECONCILE_BLOCKED` | 409 Conflict |
| `ERR_NO_PUBLISHED_BUNDLES` | 409 Conflict |
| `ERR_PADDLE_TAKEN` | 409 Conflict |

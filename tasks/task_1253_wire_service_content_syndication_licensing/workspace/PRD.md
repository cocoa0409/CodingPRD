# Wire Service Syndication API — Product Requirements Document

## 1. Introduction

A wire service lives and dies by two contracts at once: the editorial contract with its readers, which demands fast, accurate, rights-clean copy, and the commercial contract with its subscriber newsrooms, which demands predictable pricing tied to audience size and enforceable limits on how often and how widely content may be republished. This document specifies the API for a wire service and content syndication licensing platform in the Associated Press mould. The platform manages the full commercial lifecycle — content package and subscriber tier definition, distribution feed configuration, entitlement enforcement at the moment of republication, usage reporting and audit of subscriber republication, embargo enforcement and legal takedown, a member contribution model with credit rules, circulation-based pricing, rights carve-outs for photos and video, and renewal and termination notice handling.

The system serves two populations with sharply different powers. Internal staff — platform administrators, sales operations, editors, legal counsel, auditors, and billing clerks — configure the catalogue, move accounts and content through their lifecycles, and settle invoices. External subscriber representatives, by contrast, may only record republication events against their own organisation's subscriptions and read their own data. Because money, rights, and timing rules intersect at nearly every operation, the platform treats the logical clock, optimistic concurrency tokens, and a fixed validation precedence order as first-class parts of the contract rather than implementation details. All resources are mounted under the `/wire` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the principal acts. A request missing either header, or carrying a role string the platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform declares exactly seven roles, spelled exactly as follows:

- `PlatformAdmin` — the wire service operator; configures packages, tiers, and feeds, and is the only role permitted to drive the logical clock.
- `SalesOps` — manages subscribers, subscriptions, and entitlements: registration, suspension, reinstatement, termination, activation, cancellation, renewal, granting and revocation.
- `Editor` — editorial staff; creates, publishes, embargoes, lifts embargoes on, withdraws, and republishes articles, and attaches photo and video assets.
- `Legal` — legal counsel; issues article takedowns and reads articles, assets, and publications.
- `Auditor` — reviews republication audit; flags publications and dismisses flagged publications.
- `Billing` — generates, issues, marks paid, and voids invoices.
- `SubscriberRep` — an external subscriber representative; records republication events and reads the subscriber's own subscriptions, entitlements, publications, invoices, and articles.

For six of the seven roles — `PlatformAdmin`, `SalesOps`, `Editor`, `Legal`, `Auditor`, and `Billing` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for an actor stamp, but it never compares it against any entity's `id`. When `X-User-Role` is `SubscriberRep`, by contrast, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource that references a `Subscriber` compare the resource's foreign-key field to `X-User-ID`. A `SubscriberRep` attempting to touch a resource owned by a different subscriber is rejected with `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403).

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope. Unless a workflow says otherwise, list results are sorted by `created_at` ascending. Many list endpoints additionally accept resource-specific filter parameters (for example `status`, `is_member`, `feed_id`, `subscriber_id`, `subscription_id`, `article_id`, `package_id`, `tier_id`, `kind`, or `embargo_status`); the workflows in §3 name the filters each collection supports.

### 2.4. The Logical Clock

All time-sensitive behaviour in the platform — embargoes, termination notice periods, renewal deadlines, monthly quota buckets, invoice months — is evaluated against a single logical clock, not wall-clock time. The logical clock is exposed through a `ClockCheckpoint` resource whose sole meaningful field is `current_utc`. When the server starts, before any clock operation has been invoked, the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Advancing the clock is not inert: if the new `current_utc` has reached or passed the `renewal_due_at` of any `ACTIVE` subscription, that subscription is swept to `EXPIRED` as a side effect of the clock advance.

### 2.5. Common Resource Properties

Every persisted resource carries an `id`, a server-minted UUID with no type prefix. Resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and a `version`, an integer that increments by exactly one on every mutation of that resource. The one exception is the `ClockCheckpoint`: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision and Rounding

All money in the platform is integer cents. Every fee, multiplier application, discount, credit, overage charge, and invoice total is stored and returned as an integer number of cents. Wherever a multiplication or division would produce a fractional cent — applying a tier's `circulation_multiplier_basis_points` to a package's base fee, or applying a `member_discount_pct` to a gross amount — the result is rounded half up to the nearest integer cent at that step, and subsequent steps operate on the rounded figure. No calculation performs a second rounding pass after summation.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on a parent entity's `version`; no other endpoint accepts a version field.

Activating a subscription requires the request to carry `expected_subscriber_version`, holding the `version` of the owning subscriber as the client last observed it. If the subscriber's current `version` has advanced since that observation — because another writer modified the subscriber, for example its `member_credit_balance_cents` or `declared_audience`, between the client's read and the activation — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from resolving a tier and price against subscriber inputs it has not observed. A successful activation itself advances the owning subscriber's `version` by one.

Republishing a withdrawn article requires the request to carry `expected_article_version`, holding the `version` of the article as the client last observed it. If the article's current `version` has advanced since that observation — because another writer recorded an embargo extension or metadata change in the interim — the republish is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful republish advances the article's `version` by one.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces only the first failure. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the seven declared roles; failure yields `ERR_UNAUTHENTICATED` (HTTP 401). This check applies to every endpoint.
2. **Authorization** — the declared role is permitted to invoke the endpoint; failure yields `ERR_UNAUTHORIZED` (HTTP 403). This check applies to every endpoint.
3. **Existence** — every path identifier and every request-body foreign key resolves to an existing entity; failure yields `ERR_NOT_FOUND` (HTTP 404). This check applies to every endpoint.
4. **State-machine from-state** — the target resource is in the exact from-state the transition requires (for example, an article must be `DRAFT` before publishing, a subscription must be `DRAFT` before activation); failure yields `ERR_INVALID_STATE` (HTTP 409). This check applies to all transition endpoints.
5. **Temporal rules** — embargo, notice, and renewal timing rules (an `embargo_until` still in the future at republication time, a termination attempted before the 30-day notice period has elapsed, a renewal notice sent too late, an embargo extension that does not move the embargo later); failure yields `ERR_TEMPORAL_VIOLATION` (HTTP 422). This check applies to the republication, termination, renewal-notice, and embargo-extension operations.
6. **Rights safety** — the article is not `TAKEN_DOWN` and every attached asset's `rights_scope` is compatible with the subscribing package's `media_rights`; failure yields `ERR_RIGHTS_VIOLATION` (HTTP 422). This check applies to the recording of a republication.
7. **Cross-account ownership** — when the caller's role is `SubscriberRep`, the subscriber that owns the referenced subscription must match `X-User-ID`; failure yields `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403). This check applies to subscriber-scoped endpoints.
8. **Tier uniqueness** — more than one `ACTIVE` tier matching the subscriber's `declared_audience` is a configuration defect; failure yields `ERR_AMBIGUOUS_TIER` (HTTP 422). This check applies to subscription activation and ranks ahead of the no-match check.
9. **Tier existence** — no `ACTIVE` tier matching the subscriber's `declared_audience` yields `ERR_NO_MATCHING_TIER` (HTTP 422). This check applies to subscription activation.
10. **Entitlement presence** — recording a republication requires a `LIVE` entitlement pairing the subscription with the article's feed; failure yields `ERR_NO_ENTITLEMENT` (HTTP 422).
11. **Minimum commitment** — a cancellation attempted before the subscription's `months_used_current_period` has reached 3 yields `ERR_MIN_COMMITMENT_NOT_MET` (HTTP 422).
12. **Invoice fiscal consistency** — issuing an invoice must produce a `total_due_cents` of zero or more and a `member_credit_applied_cents` no greater than the subscriber's `member_credit_balance_cents`; failure yields `ERR_FISCAL_INCONSISTENCY` (HTTP 422).

Independent of the ordered list above, any request that is missing a required field or carries a malformed value — an unknown enum literal, an out-of-range number — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. Cascading State Propagation and Hierarchical Consistency

The platform's aggregates form a shallow hierarchy — subscribers own subscriptions, subscriptions own entitlements, articles own assets — and several transitions deliberately propagate down that hierarchy. Suspending a subscriber flips every `ACTIVE` or `DRAFT` subscription of that subscriber to `SUSPENDED`. Terminating a subscriber flips every non-terminal subscription to `CANCELLED` and every outstanding `DRAFT` invoice to `VOIDED`. Suspending, cancelling, or expiring a subscription flips all of its entitlements to `REVOKED`. Withdrawing an article flips its `RECORDED` publication rows to `AUDIT_FLAGGED`. Taking down an article flips all of its assets to `TAKEN_DOWN`, all of its publication rows to `AUDIT_FLAGGED`, and debits the contributing member's credit. Every such mutation — whether direct or cascaded — refreshes the affected resource's `updated_at`, and every mutation of a resource increments that resource's `version` by one.

Reinstatement is deliberately asymmetric with suspension: reinstating a subscriber does not reinstate its subscriptions, and reinstating a subscription does not restore its previously revoked entitlements. Recovery from suspension is always an explicit, manual act, described in §3.

### 2.10. Nested Resource Retrieval

Several resources are addressable only beneath their parent — subscriptions beneath a subscriber, entitlements and invoices beneath a subscription, assets beneath an article. Path parameters are validated left to right: each segment's identifier must resolve to an existing entity, and each child must actually belong to the parent named to its left. An unresolvable identifier, or a child that belongs to a different parent than the path claims, is rejected with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Catalogue Configuration: Packages, Tiers, and Feeds

Before any subscriber can be sold anything, a `PlatformAdmin` builds the commercial catalogue. A content package is created with a unique wire service `code` such as NATIONAL_NEWS_PLUS, a human-readable `display_name`, a `media_rights` class, and a `base_monthly_fee_cents` — the list price per calendar month before any circulation multiplier is applied. The `media_rights` class is one of `TEXT_ONLY`, `TEXT_AND_PHOTO`, or `TEXT_PHOTO_VIDEO`, and it bounds which asset classes a subscription to that package may republish: `TEXT_ONLY` licenses text alone, `TEXT_AND_PHOTO` adds photographs, and `TEXT_PHOTO_VIDEO` adds video. A package is born `ACTIVE`; retiring it flips its `status` to `RETIRED`, and a retired package may no longer be referenced by new subscriptions — activation against a retired package is refused. The package collection can be listed with an optional `status` filter, alongside the standard `limit` and `offset` parameters.

Subscriber tiers translate audience size into price. Each tier carries a unique `code` (the house conventions are METRO, REGIONAL, COMMUNITY, and DIGITAL), an inclusive lower bound `min_audience`, an exclusive upper bound `max_audience` that may be null to mean unbounded above, a `circulation_multiplier_basis_points` where 10000 represents a 1.0x multiplier on the base fee, a `monthly_republish_quota` capping included republications per calendar month, an `overage_per_article_cents` charged per republication beyond that quota, and an optional `member_discount_pct` — a percentage between 0 and 90, defaulting to 0 — granted when the subscriber is an active contributing member. A tier's audience window includes its `min_audience` boundary and excludes its `max_audience` boundary. Tiers are likewise born `ACTIVE` and can be retired to `RETIRED`; only `ACTIVE` tiers participate in tier resolution, and the tier collection supports the same optional `status` filter.

Feeds are the editorial distribution channels. A feed is created with a unique `code` such as WIRE-NATIONAL or WIRE-SPORTS, a `topic` drawn from `NATIONAL`, `WORLD`, `BUSINESS`, `SPORTS`, or `FEATURES`, and an `embargo_window_minutes` — the standard embargo applied to articles routed to the feed when no explicit later embargo has been set. A feed's `status` is either `LIVE` or `SUSPENDED`, and an article can only be published into a feed that is `LIVE` at publish time. The feed collection also accepts the optional `status` filter on listing.

### 3.2. Subscriber Onboarding and Account Lifecycle

A `SalesOps` operator registers each subscriber with its `legal_name` (the publication's legal entity name), a `billing_email`, a `declared_audience` — the self-declared average circulation that will later drive tier resolution — and an optional `is_member` flag, defaulting to false, marking the subscriber as a contributing wire-service member. A subscriber is born `ACTIVE`, and its `member_credit_balance_cents` — the running balance of credit earned from accepted member contributions — accumulates from zero. The subscriber collection can be listed with optional `status` and `is_member` filters.

Account discipline follows a three-state lifecycle over `ACTIVE`, `SUSPENDED`, and `TERMINATED`. Suspending a subscriber moves it from `ACTIVE` to `SUSPENDED` and cascades downward: every `ACTIVE` or `DRAFT` subscription belonging to that subscriber flips to `SUSPENDED`. Reinstating moves the subscriber from `SUSPENDED` back to `ACTIVE` but, by design, does not auto-reinstate any subscription — each subscription must be reinstated individually.

Termination is a two-step, notice-governed process. First, giving termination notice stamps the subscriber's `termination_notice_at` with the current logical clock and sets `termination_effective_at` to exactly 30 days after that notice instant. The actual termination — whether the subscriber stands `ACTIVE` or `SUSPENDED` at the time — is only lawful once the logical clock has reached or passed `termination_notice_at` plus 30 days; an attempt made earlier is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422). When termination lands, the cascade is total: every subscription in any non-terminal state flips to `CANCELLED`, and every outstanding `DRAFT` invoice flips to `VOIDED`. `TERMINATED` is terminal.

### 3.3. Subscription Lifecycle: Activation, Pricing, Suspension, Renewal

A `SalesOps` operator opens a subscription by creating a draft beneath a subscriber, supplying the `package_id` of the content package being sold and a `start_at` instant in UTC. The draft is born in `DRAFT` status with `months_used_current_period` and `republish_count_current_month` both at zero. The subscription collection — both the subscriber-scoped listing and the global filtered listing — accepts optional filters on `status`, and the global listing additionally accepts `subscriber_id`, `package_id`, and `tier_id`.

Activation is the pivotal commercial event, and it is guarded four ways. The subscription must be `DRAFT` and its owning subscriber must be `ACTIVE` — a wrong from-state on either is `ERR_INVALID_STATE` (HTTP 409). The package referenced by `package_id` must still be `ACTIVE`. Tier resolution must succeed unambiguously: the candidates are the `ACTIVE` subscriber tiers whose `min_audience` is no greater than the subscriber's `declared_audience` and whose `max_audience` is either null or strictly greater than `declared_audience`; zero candidates is `ERR_NO_MATCHING_TIER` (HTTP 422), more than one is `ERR_AMBIGUOUS_TIER` (HTTP 422), and exactly one becomes the subscription's `tier_id`. Finally, the request must carry `expected_subscriber_version` matching the subscriber's current `version`, as specified in §2.7 — a mismatch is `ERR_STALE_VERSION` (HTTP 412).

With the tier resolved, the monthly price is computed in integer cents. The gross amount is the package's `base_monthly_fee_cents` multiplied by the tier's `circulation_multiplier_basis_points` and divided by 10000, rounded half up to the nearest cent. If the subscriber `is_member` and the tier's `member_discount_pct` is greater than zero, the discount is the gross amount multiplied by `member_discount_pct` and divided by 100, again rounded half up to the nearest cent; otherwise the discount is zero. The subscription's `monthly_price_cents` is the gross amount minus the discount. Activation also sets `renewal_due_at` to exactly 12 months after `start_at`, stamps `current_month_bucket` with the year-and-month of `start_at` in YYYY-MM form, moves the subscription to `ACTIVE`, and — as the OCC side effect — increments the owning subscriber's `version` by one.

Suspension and reinstatement mirror the subscriber-level discipline. Suspending moves a subscription from `ACTIVE` to `SUSPENDED` — the owning subscriber must be `ACTIVE` — and flips all of the subscription's entitlements to `REVOKED`, stamping each `revoked_at`. Reinstating moves it from `SUSPENDED` back to `ACTIVE` — again the subscriber must be `ACTIVE` — but entitlements previously revoked remain `REVOKED`; access is restored only by granting new entitlements explicitly.

Cancellation enforces a minimum commitment. Whether the subscription is cancelled from `ACTIVE` (permitted while the owning subscriber is `ACTIVE` or `SUSPENDED`) or from `SUSPENDED`, the subscription's `months_used_current_period` — the count of months consumed since `start_at` or the last renewal — must have reached at least 3; otherwise the cancellation is rejected with `ERR_MIN_COMMITMENT_NOT_MET` (HTTP 422). Cancelling from `ACTIVE` flips all of the subscription's entitlements to `REVOKED`; cancelling from `SUSPENDED` performs no further cascade, because the entitlements were already revoked when the subscription was suspended. `CANCELLED` is terminal, as is `EXPIRED`: if the logical clock reaches `renewal_due_at` with no renewal action taken, the subscription is swept from `ACTIVE` to `EXPIRED` and all of its entitlements flip to `REVOKED`. That sweep may be set in motion by a clock advance.

Renewal keeps a good subscriber whole. Renewing a subscription extends its `renewal_due_at` by a further 12 months and resets `months_used_current_period` to zero for the new period. Separately, sending a renewal notice stamps `renewal_notice_sent_at` with the current logical clock; the notice must be dispatched no later than 60 days before `renewal_due_at`, and a notice attempted inside that 60-day window is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422).

### 3.4. Entitlements and Feed Access

An entitlement is the unit of access: it pairs one subscription with one feed. A `SalesOps` operator grants an entitlement beneath a subscription by supplying the target `feed_id`; the entitlement is born `LIVE` with `granted_at` stamped from the current logical clock. Revocation — either an explicit revocation by `SalesOps` or a cascade from a subscription suspension, cancellation, or expiry — moves a `LIVE` entitlement to `REVOKED` and stamps `revoked_at` from the current clock; while live, `revoked_at` is null. `REVOKED` is terminal: there is no path back to `LIVE`, only a fresh grant.

Entitlements are checked at the moment of republication. Recording a republication requires a `LIVE` entitlement for the pairing of the subscription and the feed the article was routed to; without one, the republication is rejected with `ERR_NO_ENTITLEMENT` (HTTP 422). The entitlement collections — the subscription-scoped listing and the global filtered listing — accept an optional `status` filter, and the global listing additionally accepts `subscription_id` and `feed_id` filters.

### 3.5. Editorial Pipeline: Articles, Embargoes, Takedowns, and Member Credits

An `Editor` creates an article as a draft, routing it to a feed by `feed_id` and supplying a `headline`, the `body_word_count` of its body text, a unique `slug`, and — when the copy originated from a member newsroom rather than from staff — the `contributing_member_subscriber_id` of that member. The article is born `DRAFT`. The article collection accepts optional filters on `feed_id`, `status`, `embargo_status`, and `contributing_member_subscriber_id`.

Publishing moves the article from `DRAFT` to `PUBLISHED`. The feed it was routed to must be `LIVE` at that moment. On publish, `published_at` is stamped from the current logical clock, `embargo_until` is computed as `published_at` plus the feed's `embargo_window_minutes`, and `embargo_status` becomes `EMBARGOED` when that computed `embargo_until` lies later than `published_at`, or `CLEAR` when it does not. Publishing is also the moment the member contribution model pays out: when `contributing_member_subscriber_id` is set and that subscriber's `is_member` is true, the article's `member_credit_cents` is computed and credited to the contributing subscriber's `member_credit_balance_cents`. The credit has a word-count base plus a per-asset bonus, each component an integer-cent figure summed without any post-summation rounding. The base is 2000 cents for a body under 400 words, 5000 cents for a body of at least 400 but under 900 words, 9000 cents for a body of at least 900 but under 1500 words, and 14000 cents for a body of 1500 words or more. The bonus adds 1500 cents for every attached asset whose `kind` is `PHOTO` and 4000 cents for every attached asset whose `kind` is `VIDEO`, counting all of the article's assets regardless of their status at publish time.

While `PUBLISHED`, an `Editor` may manage the embargo two ways. Extending the embargo supplies a `new_embargo_until` that must be strictly later than the article's current `embargo_until` — an instant that fails that comparison is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422) — and sets `embargo_until` to the new instant with `embargo_status` forced to `EMBARGOED`. Lifting the embargo early is permitted only while `embargo_status` is `EMBARGOED` and moves it to `EMBARGO_LIFTED`, signalling that subscribers may republish immediately.

Withdrawal and republication handle corrections. Withdrawing moves a `PUBLISHED` article to `WITHDRAWN` and cascades: every publication row referencing the article that still stands `RECORDED` flips to `AUDIT_FLAGGED`, and each subscriber whose publication was flagged receives an audit review marker. Republishing moves a `WITHDRAWN` article back to `PUBLISHED`, provided no outstanding takedown request stands against it; the request must carry `expected_article_version` matching the article's current `version` per §2.7, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). A successful republish refreshes `published_at` from the current logical clock, recomputes `embargo_until` from the feed's window, resets `embargo_status` to `EMBARGOED` or `CLEAR` by the same comparison used at publish, and increments the article's `version` by one.

Takedown is the legal kill switch. A `Legal` operator may take down an article standing `PUBLISHED` or `WITHDRAWN`, moving it to `TAKEN_DOWN`, which is terminal. The cascade is threefold: every asset of the article flips to `TAKEN_DOWN`; every publication row referencing the article flips to `AUDIT_FLAGGED`; and if the article had a `contributing_member_subscriber_id`, that member's `member_credit_balance_cents` is decremented by the article's `member_credit_cents`, with the balance floored at zero so it never goes negative.

Assets are attached to an article by an `Editor` with a `kind` of `PHOTO` or `VIDEO`, a `rights_scope` carve-out class, and a `file_ref` storage reference. An asset is born `ACTIVE` and leaves that state only through the takedown cascade. The asset collections — the article-scoped listing and the global filtered listing — accept optional `kind` and `status` filters, and the global listing additionally accepts an `article_id` filter.

### 3.6. Republication, Quotas, Rights Enforcement, and Audit

The republication event is where licensing is enforced. A `SubscriberRep` records a republication by supplying the `subscription_id` being used and the `article_id` being republished; the server stamps `republished_at` from the current logical clock. Because the caller is a `SubscriberRep`, the cross-account rule of §2.8 applies first among the business checks: the subscriber that owns the referenced subscription must be the subscriber identified by `X-User-ID`, otherwise the request is rejected with `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403).

Three business gates then guard the event. There must be a `LIVE` entitlement pairing the subscription with the feed the article was routed to, otherwise `ERR_NO_ENTITLEMENT` (HTTP 422). The article's `embargo_until` must not lie in the future — republication of still-embargoed copy is a temporal violation, rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422). And rights must be clean: the article must not be `TAKEN_DOWN`, and every attached asset's `rights_scope` must be compatible with the subscribing package's `media_rights`. The carve-out classes are `WIRE`, `EDITORIAL_ONLY`, and `MEMBER_ONLY`; assets marked `EDITORIAL_ONLY` or `MEMBER_ONLY` are excluded from syndication, and the package's `media_rights` class bounds which asset kinds may ride along at all — a `TEXT_ONLY` package licenses no photo or video republication, `TEXT_AND_PHOTO` admits photographs but not video, and `TEXT_PHOTO_VIDEO` admits both. A failure on either limb is rejected with `ERR_RIGHTS_VIOLATION` (HTTP 422).

Quota bookkeeping happens at the same moment, against the resolved tier's `monthly_republish_quota`. The subscription's `current_month_bucket` holds the YYYY-MM month its `republish_count_current_month` belongs to. If that bucket differs from the year-and-month of the current logical clock, the counter is first reset to zero and the bucket is moved to the current month; the counter is then incremented by one. The republication is `within_quota` when the incremented count is no greater than the tier's `monthly_republish_quota`; in that case `billed_amount_cents` is zero. Otherwise `within_quota` is false and `billed_amount_cents` is the tier's `overage_per_article_cents`. The publication is born `RECORDED`, carrying the resolved `subscriber_id` and `subscription_id` alongside the supplied `article_id`.

Audit closes the loop. An `Auditor` may flag a `RECORDED` publication, moving it to `AUDIT_FLAGGED` — the same state the withdraw and takedown cascades produce — and may later dismiss an `AUDIT_FLAGGED` publication, moving it to `DISMISSED`. Dismissal carries a refund: if the publication's `billed_amount_cents` is greater than zero, that amount is credited back to the subscriber's `member_credit_balance_cents`. The publication collection accepts optional filters on `subscriber_id`, `subscription_id`, `article_id`, and `status`.

### 3.7. Billing: Invoices, Overage Aggregation, and Member Credit Application

Invoices are cut per subscription per month. A `Billing` operator generates a draft invoice beneath a subscription by supplying the `billing_month` in YYYY-MM form. Generation snapshots three computed figures onto the `DRAFT` invoice. `base_fee_cents` is the subscription's `monthly_price_cents`, snapshotted as it stands at generation time. `overage_cents` is the sum of `billed_amount_cents` across every publication of this subscription whose `republished_at` falls inside the billing month — the month boundary is inclusive at the first instant of the named month and exclusive at the first instant of the following month — and whose `status` is `RECORDED` or `AUDIT_FLAGGED`; `DISMISSED` rows are excluded from the sum. `provisional_total_due_cents` is the provisional pricing variant: the gross monthly figure is recomputed from the package's `base_monthly_fee_cents` multiplied by the tier's `circulation_multiplier_basis_points` and divided by 10000, rounded half up to the nearest cent, deliberately ignoring both the tier's `member_discount_pct` and the subscriber's credit balance, then added to the accrued overage. The provisional figure therefore differs from the final one whenever the subscriber is a member whose tier grants a `member_discount_pct` above zero. The invoice collections accept an optional `status` filter, and the global invoice listing additionally accepts `subscriber_id` and `subscription_id` filters.

Issuing the invoice settles the member credit waterfall. Issuance requires the invoice to be `DRAFT` and the subscription it references to be in any state other than `DRAFT` — a `DRAFT` subscription cannot anchor an issued invoice, and the attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). The gross due is `base_fee_cents` plus `overage_cents`. The credit applied is the lesser of the subscriber's `member_credit_balance_cents` at issue time and that gross due; it is recorded as `member_credit_applied_cents`, and the subscriber's `member_credit_balance_cents` is decremented by the same amount. `total_due_cents` is the gross due minus the applied credit, and it can never fall below zero. The fiscal guard of §2.8 backs these invariants: any issuance whose arithmetic would produce a negative `total_due_cents`, or apply more credit than the subscriber's balance holds, is rejected with `ERR_FISCAL_INCONSISTENCY` (HTTP 422).

Settlement and reversal are simple from there. Paying moves an `ISSUED` invoice to `PAID`. Voiding moves a `DRAFT` invoice to `VOIDED` — the same destination the subscriber-termination cascade forces on every outstanding `DRAFT` invoice. Both `PAID` and `VOIDED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under the `/wire` prefix. Creating a new resource returns HTTP 201; every other successful operation — reads, state transitions, modifications — returns HTTP 200. Request and response payloads for each endpoint are reconstructed from the workflows in §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /wire/_clock/set_current_utc | Advance the logical clock to a supplied instant; may trigger the subscription expiry sweep | PlatformAdmin |
| POST | /wire/packages | Create a content package | PlatformAdmin |
| GET | /wire/packages | List packages | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/packages/{id} | Get a package by id | PlatformAdmin, SalesOps, Auditor, Billing |
| POST | /wire/packages/{id}/retire | Retire a package so no new subscriptions may reference it | PlatformAdmin |
| POST | /wire/tiers | Create a subscriber tier | PlatformAdmin |
| GET | /wire/tiers | List tiers | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/tiers/{id} | Get a tier by id | PlatformAdmin, SalesOps, Auditor, Billing |
| POST | /wire/tiers/{id}/retire | Retire a tier | PlatformAdmin |
| POST | /wire/feeds | Create a distribution feed | PlatformAdmin |
| GET | /wire/feeds | List feeds | PlatformAdmin, SalesOps, Editor, Auditor |
| GET | /wire/feeds/{id} | Get a feed by id | PlatformAdmin, SalesOps, Editor, Auditor |
| POST | /wire/subscribers | Register a subscriber | SalesOps |
| GET | /wire/subscribers | List subscribers | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/subscribers/{id} | Get a subscriber by id | PlatformAdmin, SalesOps, Auditor, Billing |
| POST | /wire/subscribers/{id}/suspend | Suspend a subscriber, cascading to its subscriptions | SalesOps |
| POST | /wire/subscribers/{id}/reinstate | Reinstate a suspended subscriber | SalesOps |
| POST | /wire/subscribers/{id}/give-termination-notice | Record the 30-day termination notice | SalesOps |
| POST | /wire/subscribers/{id}/terminate | Terminate a subscriber after the notice period | SalesOps |
| POST | /wire/subscribers/{id}/subscriptions | Create a draft subscription for a subscriber | SalesOps |
| GET | /wire/subscribers/{id}/subscriptions | List a subscriber's subscriptions | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/subscriptions | List subscriptions, filtered | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/subscriptions/{id} | Get a subscription by id | PlatformAdmin, SalesOps, Auditor, Billing, SubscriberRep |
| POST | /wire/subscriptions/{id}/activate | Activate a subscription; resolves tier and price; OCC via expected_subscriber_version | SalesOps |
| POST | /wire/subscriptions/{id}/suspend | Suspend a subscription, cascading entitlements to REVOKED | SalesOps |
| POST | /wire/subscriptions/{id}/reinstate | Reinstate a subscription without restoring entitlements | SalesOps |
| POST | /wire/subscriptions/{id}/cancel | Cancel a subscription after the 3-month minimum | SalesOps |
| POST | /wire/subscriptions/{id}/renew | Renew a subscription for another 12 months | SalesOps |
| POST | /wire/subscriptions/{id}/send-renewal-notice | Send the renewal notice, at least 60 days before renewal is due | SalesOps |
| POST | /wire/subscriptions/{id}/entitlements | Grant an entitlement to a feed for a subscription | SalesOps |
| GET | /wire/subscriptions/{id}/entitlements | List a subscription's entitlements | PlatformAdmin, SalesOps, Auditor, Billing, SubscriberRep |
| GET | /wire/entitlements | List entitlements, filtered | PlatformAdmin, SalesOps, Auditor, Billing |
| GET | /wire/entitlements/{id} | Get an entitlement by id | PlatformAdmin, SalesOps, Auditor, Billing, SubscriberRep |
| POST | /wire/entitlements/{id}/revoke | Revoke an entitlement | SalesOps |
| POST | /wire/articles | Create a draft article | Editor |
| GET | /wire/articles | List articles | PlatformAdmin, Editor, Auditor, Legal |
| GET | /wire/articles/{id} | Get an article by id | PlatformAdmin, Editor, Auditor, Legal, SubscriberRep |
| POST | /wire/articles/{id}/publish | Publish an article; stamps published_at and computes embargo_until | Editor |
| POST | /wire/articles/{id}/embargo | Extend an article's embargo | Editor |
| POST | /wire/articles/{id}/lift-embargo | Lift an article's embargo early | Editor |
| POST | /wire/articles/{id}/withdraw | Withdraw an article; its publications flip to AUDIT_FLAGGED | Editor |
| POST | /wire/articles/{id}/republish | Republish a withdrawn article; OCC via expected_article_version | Editor |
| POST | /wire/articles/{id}/takedown | Legal takedown; cascades to assets and publications and debits member credit | Legal |
| POST | /wire/articles/{id}/assets | Attach a photo or video asset to an article | Editor |
| GET | /wire/articles/{id}/assets | List an article's assets | PlatformAdmin, Editor, Auditor, Legal |
| GET | /wire/assets | List assets, filtered | PlatformAdmin, Editor, Auditor, Legal |
| POST | /wire/publications | Record a subscriber republication; enforces entitlement, embargo, and rights | SubscriberRep |
| GET | /wire/publications | List publications, filtered | PlatformAdmin, Auditor, Billing, SubscriberRep |
| GET | /wire/publications/{id} | Get a publication by id | PlatformAdmin, Auditor, Billing, SubscriberRep |
| POST | /wire/publications/{id}/flag | Flag a publication for audit | Auditor |
| POST | /wire/publications/{id}/dismiss | Dismiss an audit flag, refunding any billed amount to member credit | Auditor |
| POST | /wire/subscriptions/{id}/invoices | Generate a draft invoice for a billing month | Billing |
| GET | /wire/subscriptions/{id}/invoices | List a subscription's invoices | PlatformAdmin, Billing, Auditor, SubscriberRep |
| GET | /wire/invoices | List invoices, filtered | PlatformAdmin, Billing, Auditor |
| GET | /wire/invoices/{id} | Get an invoice by id | PlatformAdmin, Billing, Auditor, SubscriberRep |
| POST | /wire/invoices/{id}/issue | Issue an invoice, applying member credit | Billing |
| POST | /wire/invoices/{id}/pay | Mark an invoice paid | Billing |
| POST | /wire/invoices/{id}/void | Void a draft invoice | Billing |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TEMPORAL_VIOLATION | 422 |
| ERR_RIGHTS_VIOLATION | 422 |
| ERR_FORBIDDEN_CROSS_ACCOUNT | 403 |
| ERR_AMBIGUOUS_TIER | 422 |
| ERR_NO_MATCHING_TIER | 422 |
| ERR_NO_ENTITLEMENT | 422 |
| ERR_MIN_COMMITMENT_NOT_MET | 422 |
| ERR_FISCAL_INCONSISTENCY | 422 |
| ERR_VALIDATION | 400 |

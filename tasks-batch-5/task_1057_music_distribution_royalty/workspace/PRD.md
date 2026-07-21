# Music Distribution & Royalty API — Product Requirements Document

## 1. Introduction

Independent artists no longer sign away their masters to get onto Spotify, Apple Music or YouTube. Instead they pay a flat yearly subscription to a distributor, upload a record, and expect the distributor to push it to every store on time, collect the money the stores report months later, split that money with the people who actually played on the record, and hand everyone a tax form in January. The gap between that expectation and reality is where distributors lose their customers: a missing ISRC silently kills a delivery, a co-writer never signs off on their share, a statement is closed twice with different numbers, or a payout lands in the wrong collaborator's account and cannot be clawed back.

This document specifies the backend service that closes that gap. It is a ledger-first system: every cent that a store reports is recorded as an immutable line, aggregated into a statement, commissioned according to the artist's plan and the store's own take, allocated down through a locked split sheet to individual payees, taxed according to each payee's residence and paperwork, and finally paid or reversed — with the running totals on each payee reconciling exactly at every observable instant. Wrapped around that ledger is a distribution workflow: an editorial review pipeline that gates what may go out, a per-store delivery pipeline with retry and takedown, and a subscription layer that decides how many records an artist may have in flight at once.

Two properties dominate the design. First, **the platform never reads wall-clock time** — every deadline, grace window, lead-time and expiry rule reads a server-held logical clock that tests and operators reposition explicitly. Second, **money is never approximated**: all monetary amounts are whole cents, all rates are basis points, and every rounding step in the pipeline has a pinned order of evaluation so that two implementations reading this document arrive at the same cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity and Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which they act. Both headers must be present, and `X-User-Role` must name one of the six recognised roles, otherwise the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is fan pre-save registration, which accepts the role `Fan` with any `X-User-ID` value whatsoever. Once the caller is recognised, the platform checks that their role appears in the set of roles authorised for the endpoint they addressed; if it does not, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `PlatformAdmin`, `Artist`, `Collaborator`, `DistributionOps`, `FinanceOps` and `Fan`.

- A `PlatformAdmin` operates platform configuration — subscription plans, stores, artist accounts, subscription billing state, and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.
- An `Artist` owns the releases, tracks, collaborators and split sheets registered under a single artist account. When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist` record; ownership checks on any resource that hangs off an artist compare that resource's owning artist reference to `X-User-ID`. A release is owned through its `artist_id`; a track through its release; a split sheet through its track's release; a collaborator through its `artist_id`.
- A `Collaborator` is a payee who accepts or rejects split shares and reads their own payouts and tax forms. When `X-User-Role` is `Collaborator`, `X-User-ID` is the `id` of the acting `Collaborator` record; ownership checks compare a share's or payout's `collaborator_id` to `X-User-ID`.
- A `DistributionOps` operator reviews release metadata and drives store delivery and takedown. When `X-User-Role` is `DistributionOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it in no field of its own, but it is never compared to an entity `id`.
- A `FinanceOps` operator runs the royalty ledger — statement creation, ingestion, reconciliation, closing, payouts and 1099s. When `X-User-Role` is `FinanceOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example as `reconciled_by_user_id` and `closed_by_user_id` on a statement, and as `approved_by_user_id` and `paid_by_user_id` on a payout) but does not compare it to any entity's `id`.
- A `Fan` is a public actor whose only capability is registering a pre-save against a release. When `X-User-Role` is `Fan`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is never compared to an entity `id`.

When an entity-backed role — `Artist` or `Collaborator` — addresses a resource that belongs to somebody else, the request is refused with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). This applies to every endpoint whose authorised role set includes `Artist` or `Collaborator`, including read endpoints: an artist's list queries are scoped to their own account, and a collaborator's share, payout and tax-form queries are scoped to their own payee record.

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

### 2.3. Pagination and Collection Ordering

Every collection endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` controls the starting position: it defaults to 0 and may be no smaller than 0. A value outside these bounds is a request-shape failure and is rejected with `ERR_VALIDATION`.

Collections are returned in ascending `created_at` order — oldest first — unless a subsection below states otherwise for a particular resource. The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` giving the number of records matching the filters before the page window is applied, and `has_more`, which is true exactly when records matching the filters remain beyond the current page.

Filters supplied alongside pagination narrow the matched set before counting. Most collections accept a `status` filter; beyond that, subscriptions may be narrowed by `artist_id` or `plan_id`, releases by `artist_id` and by either state dimension (`status` or `delivery_status`), tracks by `release_id`, collaborators by `artist_id`, split sheets by `track_id`, split shares by `split_sheet_id` or `collaborator_id`, deliveries by `release_id` or `store_id`, royalty statements by `artist_id`, royalty lines by `royalty_statement_id`, `track_id`, `store_id` or `source`, payouts by `collaborator_id` or `royalty_statement_id`, and tax forms by `collaborator_id` or `tax_year`.

### 2.4. Resource Identity, Timestamps and Versioning

Every stored resource carries a server-minted `id`, which is a UUID string with no type prefix and is never supplied by the client. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded when the row is first persisted.

Most resources additionally carry `updated_at`, refreshed on every mutation of that row, and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on each mutation. The one exception is the royalty line. Royalty lines are append-only ledger entries: once ingested they are never edited, so a royalty line carries only `id` and `created_at` — it has no `updated_at` and no `version` field at all.

Version increments are not confined to the row the caller addressed. Whenever a workflow step mutates a second resource as a side effect — a subscription's slot counter changing because a release was submitted, a track flipping to active because its release went live, a store delivery being marked for takedown because the artist requested one — that second resource's `updated_at` is refreshed and its `version` advances by 1 in the same way. Section 3 names each such cascade at the point where it happens; the general rule is that a resource whose stored state changed has a new `version`, and a resource whose state did not change does not.

### 2.5. The Logical Clock

The platform never reads wall-clock time for business decisions. It holds a single server-wide logical clock whose startup value is exactly `2026-07-01T00:00:00Z`; before any operator repositions it, the server must read that instant and must not substitute real time. A `PlatformAdmin` repositions the clock by supplying the target instant as `to_iso8601`; the response reports the resulting `current_utc`. Repositioning the clock mutates no entity — it neither advances any state machine nor recomputes any total.

Every deadline in this specification reads that clock: the seven-day minimum lead before a release date, the thirty-day subscription grace window, the store delivery lead requirement, the pre-save window, the ninety-day payout reversal window, and every `..._at` stamp the workflows write. Where a rule says "the current instant", it means the current value of the logical clock.

### 2.6. Money, Rates and Rounding Discipline

All monetary amounts in this system are integers denominated in cents; there are no fractional-cent fields and no floating-point money. All rates — plan commission, store surcharge, loyalty discount, split share, tax withholding, and content bonus — are expressed in **basis points**, where one basis point is one ten-thousandth, so 10000 basis points is the whole amount and 2500 basis points is a quarter of it.

Wherever a rate is applied to an amount, the result is rounded to whole cents using **round half up**: a computed value whose fractional part is exactly one half rounds away from zero, to the next larger whole cent. This applies to commission computation, to the content-identification bonus, and to tax withholding.

Two places in this specification deliberately do **not** round half up, and the difference is material. The gross-weighted store surcharge is rounded half up to whole **basis points** before it participates in the effective commission rate — it is not carried as a fraction into the later multiplication. And the two-level allocation of a statement's net across tracks and then across payees takes the **floor** at each level and then distributes the leftover cents by largest remainder; rounding each share independently and summing is explicitly not the rule and produces a different distribution. Section 3 gives both procedures in full.

### 2.7. Optimistic Concurrency on Parent Records

Two write operations are guarded against stale client state by an optimistic-concurrency check on their parent record. In both cases the caller must supply, as a required (never optional) field of the request body, the `version` value they last observed on that parent. If it does not equal the parent's current `version`, the write is refused with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

Creating a split sheet requires `expected_track_version`, carrying the client's last observed `version` of the target track. A newly locked sheet legitimately supersedes an earlier locked sheet for the same track, so no state precondition blocks a second create — the client's stale view of the track is the only signal the platform has that the client is about to overwrite work it never saw.

Appending a batch of royalty lines to a statement requires `expected_statement_version`, carrying the client's last observed `version` of the target statement. Ingestion is append-only and a replayed feed file would otherwise be accepted silently, so the stale version is the only way to detect a duplicated or superseded batch.

No other endpoint accepts or requires an expected-version field. Endpoints not named above must not be given one and must not reject on version grounds.

### 2.8. Validation Precedence

When a single request could fail several checks at once, exactly one error is returned, and which one is fixed by a global precedence order. Implementations must evaluate in this order and return the first failure encountered:

1. Authentication — headers present and role recognised: `ERR_UNAUTHENTICATED`.
2. Role authorisation — the acting role is authorised for this endpoint: `ERR_UNAUTHORIZED`.
3. Ownership — an entity-backed role owns the addressed resource: `ERR_FORBIDDEN_OWNERSHIP`.
4. Request shape — the body parses, all required input fields are present, enum members are legal, numbers fall in their declared ranges, and identifier formats match (a `upc` is exactly 12 digits, an `isrc` is exactly 12 alphanumeric characters, a `country_code` is exactly 2 uppercase letters): `ERR_VALIDATION`. This applies to every write endpoint.
5. Path existence — every resource named in the URL exists, checked left to right: `ERR_RESOURCE_NOT_FOUND`. This applies to every endpoint with path parameters.
6. Body reference existence — every foreign key supplied in the body resolves to an existing row: `ERR_RESOURCE_NOT_FOUND`. This applies to every write endpoint that carries one.
7. State legality — the target resource is in a state from which the requested transition is declared: `ERR_INVALID_STATE`.
8. Stale version — the supplied expected-version field equals the parent's current `version`: `ERR_STALE_VERSION`.
9. Segregation of duties: `ERR_SEGREGATION_OF_DUTIES`.
10. Store explicit-flag compliance: `ERR_METADATA_NONCOMPLIANT`.
11. Store ISRC requirement: `ERR_ISRC_MISSING`.
12. Every track of the release holds a locked split sheet: `ERR_SPLIT_SHEET_NOT_LOCKED`.
13. The sheet has at least one share: `ERR_SPLIT_SHEET_EMPTY`.
14. The sheet's shares total exactly the whole amount: `ERR_SPLIT_TOTAL_INVALID`.
15. Every share of the sheet has been accepted: `ERR_SPLIT_NOT_ACCEPTED`.
16. Identifier uniqueness: `ERR_DUPLICATE_IDENTIFIER`.
17. Release-date minimum lead: `ERR_RELEASE_DATE_TOO_SOON`.
18. Delivery lead time: `ERR_DELIVERY_LEAD_TIME_VIOLATION`.
19. Store window saturation: `ERR_STORE_WINDOW_SATURATED`.
20. Statement period overlap: `ERR_STATEMENT_PERIOD_OVERLAP`.
21. Ingested line inside the statement period: `ERR_LINE_OUTSIDE_PERIOD`.
22. Pre-save window open: `ERR_PRE_SAVE_WINDOW_CLOSED`.
23. Payout reversal window: `ERR_REVERSAL_WINDOW_EXPIRED`.
24. Subscription active or inside grace: `ERR_SUBSCRIPTION_INACTIVE`.
25. Release slots remaining: `ERR_RELEASE_SLOTS_EXHAUSTED`.
26. Content-identification entitlement: `ERR_CONTENT_ID_NOT_ENTITLED`.
27. Payee tax form verified: `ERR_TAX_FORM_NOT_VERIFIED`.
28. Payout at or above the payment threshold: `ERR_PAYOUT_BELOW_THRESHOLD`.
29. Reportable total at or above the 1099 threshold: `ERR_1099_THRESHOLD_NOT_MET`.
30. Release date reached: `ERR_RELEASE_DATE_NOT_REACHED`.

The exact trigger condition behind each of these codes is stated in the workflow narrative of Section 3 that it guards, and the scope of each — the precise set of operations it applies to — is stated there as well.

### 2.9. Two Independent State Dimensions on a Release

A release carries two enumerated state fields that evolve independently on the same record. The editorial dimension is `status`, taking one of `DRAFT`, `SUBMITTED`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `LIVE` or `TAKEN_DOWN`, and beginning at `DRAFT` on creation. The distribution dimension is `delivery_status`, taking one of `NONE`, `QUEUED`, `PARTIAL`, `DELIVERED`, `TAKEDOWN_PENDING` or `TAKEN_DOWN`, and beginning at `NONE` on creation. A release may sit in `APPROVED` while its distribution dimension moves `NONE → QUEUED → PARTIAL → DELIVERED`, and only the arrival at `DELIVERED` can push the editorial dimension forward. Both dimensions are filterable independently on the release collection.

The two dimensions are coupled at exactly two points, and both couplings are described in full in Section 3: the moment the distribution dimension reaches `DELIVERED` may drive the editorial dimension `APPROVED → LIVE`, and the moment it reaches `TAKEN_DOWN` drives the editorial dimension `LIVE → TAKEN_DOWN`.

### 2.10. Segregation of Duties in the Ledger

Two steps of the money pipeline may not be performed by the operator who performed the preceding step. Closing a statement requires that the acting `X-User-ID` differ from the `reconciled_by_user_id` recorded when the statement was reconciled. Paying a payout requires, whenever the payout carries a non-null `approved_by_user_id`, that the acting `X-User-ID` differ from it; a payout that was auto-approved by the close cascade has no recorded approver and therefore imposes no such restriction. A violation of either rule is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). These two operations are the only ones subject to the rule.

### 2.11. Nested Paths and Left-to-Right Resolution

Several operations address a child resource through its parent — adding a track to a release, adding a share to a split sheet, queueing a delivery for a release, registering a pre-save. In every such case the path segments are resolved from left to right: the outermost identifier is looked up first, and if it does not resolve the request fails immediately with `ERR_RESOURCE_NOT_FOUND` without any inner identifier being consulted. The same applies to identifiers supplied in a request body: a body reference to a non-existent plan, artist, store, track, collaborator or statement is a not-found failure, not a validation failure.

## 3. Business Logic & Workflows

### 3.1. The Platform Catalogue: Plans, Stores and Artist Accounts

Before any music moves, a `PlatformAdmin` populates the catalogue the rest of the system reads. A **subscription plan** is defined by a `code` — an uppercase identifier of between 2 and 32 characters that must be unique across all plans — together with a human-readable `name`, the yearly price `annual_fee_cents` (zero or greater), and `included_release_slots`, the number of releases a subscriber on this plan may hold in flight at once, which must be at least 1. The plan also fixes the platform's take through `commission_bps`, a rate in basis points somewhere between 0 and 10000 inclusive, and declares through `allows_content_id` whether subscribers on this plan may request YouTube Content-ID monetisation on a track; when that flag is omitted at creation it defaults to false. A plan's `status` is either `ACTIVE` or `RETIRED` and defaults to `ACTIVE` when omitted.

A **store** is a delivery destination — think `SPOTIFY`, `APPLE`, `YOUTUBE`. Like a plan it is keyed by a `code` that must be unique across all stores, and carries a display `name`. Its `delivery_lead_days` states, in whole days, how far ahead of a release date a delivery to this store must be scheduled; it may be zero but not negative. Three booleans describe what the store demands of the metadata it receives: `supports_pre_save` records whether the store participates in pre-save campaigns (default false), `requires_isrc` records whether it refuses a delivery when any track of the release still has no recording code (default true), and `requires_explicit_flag` records whether it refuses a delivery when any track has left its explicit-content declaration undeclared (default true). The store's own cut is `surcharge_bps`, a commission surcharge in basis points between 0 and 2000 inclusive that defaults to 0 and later enters the weighted surcharge of a statement's commission. Finally, `max_concurrent_deliveries` — at least 1, defaulting to 2 — caps how many delivery windows may be in flight against this store at any single instant. A store's `status` is either `ACTIVE` or `PAUSED` and defaults to `ACTIVE`; a delivery may only be dispatched to a store that is `ACTIVE`.

Registering an **artist account** requires a `display_name`, a `legal_name` used on payout paperwork, a `country_code` given as exactly two uppercase letters denoting the country of tax residence, and an `email` that must be unique across all artists. A freshly registered artist begins with `status` `ACTIVE` — the enumeration is `ACTIVE`, `SUSPENDED` or `CLOSED` — and with both of its running totals initialised to zero: `lifetime_gross_cents`, which accumulates the gross of every statement of this artist that has reached `CLOSED` and which later determines the artist's loyalty discount, and `live_track_count`, which counts the tracks in `ACTIVE` status across all of this artist's releases. A `PlatformAdmin` may subsequently amend `display_name`, `legal_name`, `country_code` or `status`; any such amendment advances the artist's `version` by 1. The two running totals are never client-supplied — they are maintained by the workflows described later.

Attempting to reuse a plan `code`, a store `code` or an artist `email` is refused with `ERR_DUPLICATE_IDENTIFIER`.

### 3.2. Subscriptions, Grace and the Release-Slot Economy

An artist's ability to publish is metered by a subscription. A `PlatformAdmin` creates one by naming the subscriber through `artist_id` and the purchased plan through `plan_id`, optionally setting `auto_renew` (which defaults to true). The subscription is born in `PENDING` with `releases_used` at 0, `activated_at` null and `past_due_since` null. Its lifecycle states are `PENDING`, `ACTIVE`, `PAST_DUE`, `EXPIRED` and `CANCELLED`, of which the last two are terminal.

Activation carries the payment evidence as `payment_reference`. A `PENDING` subscription may be activated only while the owning artist's own `status` is `ACTIVE`; the transition `PENDING → ACTIVE` stamps `activated_at` with the current instant, sets `past_due_since` to null, recomputes `releases_used` from scratch, and advances the subscription's `version` by 1. When billing fails, a `PlatformAdmin` lapses the subscription: `ACTIVE → PAST_DUE` stamps `past_due_since` with the current instant and advances `version`. From `PAST_DUE` the same activation operation restores the subscription — `PAST_DUE → ACTIVE` again stamps `activated_at`, again clears `past_due_since`, and again advances `version`, so a subscription may cycle between `ACTIVE` and `PAST_DUE` indefinitely.

Two terminations share one operation. A `PAST_DUE` subscription may be expired, taking it to `EXPIRED`. An `ACTIVE` subscription may be ended too, but only when its `auto_renew` is false, in which case it moves to `CANCELLED`; an `ACTIVE` subscription that still renews automatically cannot be ended this way and the attempt is refused with `ERR_INVALID_STATE`. Both terminations advance `version` by 1 and make no other change. Any of these four billing operations attempted against a subscription in the wrong state is refused with `ERR_INVALID_STATE`.

`releases_used` is a derived count, never an input, and it is defined identically everywhere it is recomputed: it is the number of releases belonging to this subscription's artist whose editorial `status` is one of `SUBMITTED`, `IN_REVIEW`, `APPROVED` or `LIVE`. Releases sitting in `DRAFT`, `REJECTED` or `TAKEN_DOWN` are excluded and do not consume a slot. The count is recomputed when a release is submitted (which raises it by one), when a release is withdrawn (which lowers it by one), when a release is rejected by editorial (which likewise lowers it by one), when a live release is taken down, and on every subscription activation. Because submit and withdraw are exact compensating pairs, the counter returns to its prior value whenever an artist reverses a submission.

Two fiscal gates read the subscription at the moment an artist submits a release. The first is entitlement: the artist's subscription must be `ACTIVE`, or else `PAST_DUE` with the current instant strictly earlier than thirty days after `past_due_since` — the grace window during which submissions remain permitted. A subscription that is `PENDING`, `EXPIRED`, `CANCELLED`, or `PAST_DUE` beyond that thirty-day window, fails this gate with `ERR_SUBSCRIPTION_INACTIVE` (HTTP 402). The second gate is capacity: `releases_used` must be strictly less than the plan's `included_release_slots`. An artist who already has as many releases in flight as the plan permits is refused with `ERR_RELEASE_SLOTS_EXHAUSTED` (HTTP 402). Entitlement is evaluated before capacity, so an artist whose subscription has expired and whose slots are also full sees the entitlement failure.

### 3.3. Building the Record: Release Metadata, Tracks and Pre-Save Campaigns

An artist assembles a record privately before anyone else sees it. Creating a release names the owning account through `artist_id` and supplies a `title` of between 1 and 200 characters, the scheduled `release_date` as an ISO 8601 UTC instant, a `primary_genre` label and a `label_name`. A barcode may be supplied immediately as `upc` or left null and added later; when present it must be exactly 12 digits and must not already be in use by another release, on pain of `ERR_DUPLICATE_IDENTIFIER`. Pre-save behaviour may also be declared up front through `pre_save_enabled` (false when omitted) and `pre_save_opens_at`, which is null whenever pre-saves are disabled. The new release starts with editorial `status` `DRAFT` and distribution `delivery_status` `NONE`, `pre_save_count` at 0, and `rejection_reason_code`, `submitted_at` and `taken_down_at` all null.

While the release remains in `DRAFT`, its owning artist may amend `title`, `upc`, `release_date`, `primary_genre`, `label_name`, `pre_save_enabled` and `pre_save_opens_at`; each amendment advances the release's `version` by 1. Once the release has left `DRAFT`, metadata amendment is refused with `ERR_INVALID_STATE`, and the same refusal applies to adding further tracks.

Tracks are added to a `DRAFT` release one at a time. Each track carries a `title`, a `duration_seconds` runtime of at least one whole second, and a `track_number`, a 1-based ordinal that must be at least 1 and must be unique within its release — a repeated ordinal is refused with `ERR_DUPLICATE_IDENTIFIER`. Three further attributes are optional at creation. `isrc` is the recording code; it may be null, but when supplied it must be exactly 12 alphanumeric characters and must not collide with any other track's code, again `ERR_DUPLICATE_IDENTIFIER`. `explicit` is a three-valued content declaration: true, false, or null meaning the artist has not yet declared. `content_id_enabled` requests YouTube Content-ID monetisation and defaults to false. A newly added track has `status` `PENDING` — the enumeration is `PENDING`, `ACTIVE`, `INACTIVE` — and a null `locked_split_sheet_id`, which is a computed pointer to whichever of the track's split sheets is currently locked rather than a field the client ever writes. The track belongs to the release through `release_id`.

Content-ID is a paid entitlement. Whenever `content_id_enabled` is being set to true — whether while adding a track or while later amending one — the platform checks the `allows_content_id` flag of the plan behind the artist's subscription, and refuses the request with `ERR_CONTENT_ID_NOT_ENTITLED` (HTTP 403) when that plan does not permit it. Both track creation and track amendment enforce this rule; no other operation does. Amendment additionally allows `title`, `isrc`, `explicit` and `duration_seconds` to be revised, and advances the track's `version` by 1.

Pre-saves are the one thing a member of the public may do. A `Fan` registers one by supplying a `fan_reference` identifying themselves; the platform raises the release's `pre_save_count` by 1 and advances the release's `version` by 1. Registration is only accepted while the pre-save window is genuinely open, which means all three of the following hold: `pre_save_enabled` is true on the release, `pre_save_opens_at` is at or before the current instant, and the current instant is strictly earlier than `release_date`. A registration that arrives before the campaign opens, after the record has come out, or against a release that never enabled pre-saves at all is refused with `ERR_PRE_SAVE_WINDOW_CLOSED` (HTTP 422). Whether a given store advertises pre-saves through its `supports_pre_save` flag is catalogue information for downstream delivery planning and does not itself gate fan registration.

### 3.4. Payees, Split Sheets and the Path to a Locked Split

Nobody gets paid until the artist has said, in writing and with counter-signature, who is owed what. That record is the **split sheet**, and its payees are **collaborators**.

An artist registers a collaborator under their own account by supplying `artist_id`, the payee's `name`, their `email` — which must be unique among that artist's payees, otherwise `ERR_DUPLICATE_IDENTIFIER` — and their `country_code` as exactly two uppercase letters, since residence drives tax. Two further attributes may be set at registration and revised afterwards: `tax_form_status`, which is one of `MISSING`, `SUBMITTED`, `VERIFIED` or `EXPIRED` and defaults to `MISSING`, and `payout_method`, which is either `PAYPAL` or `BANK_TRANSFER` and defaults to `PAYPAL`. A collaborator's own `status` is `ACTIVE` or `ARCHIVED` and starts at `ACTIVE`. Their three running money totals — `pending_payout_cents`, `lifetime_paid_cents` and `reversed_payout_cents` — all begin at zero and are maintained exclusively by the payout workflow. Either the owning artist or a `FinanceOps` operator may later revise `tax_form_status`, `payout_method`, `country_code` or `status`; such a revision advances the collaborator's `version` by 1.

Whenever a collaborator is registered or revised, the platform recomputes their `withholding_bps` — the rate at which tax will be withheld from their payouts — by walking four cases in a strictly pinned order. First, if the payee's `tax_form_status` is either `MISSING` or `EXPIRED`, backup withholding applies at 2400 basis points, and this case overrides everything below it, including the domestic zero rate and any treaty relief, regardless of country. Otherwise, if their `country_code` is `US`, the rate is 0 basis points. Otherwise, if their `country_code` is one of the five treaty jurisdictions — `GB`, `DE`, `NL`, `AU` or `JP` — **and** their `tax_form_status` is exactly `VERIFIED`, reduced treaty withholding applies at 1000 basis points. In every remaining case the statutory foreign rate of 3000 basis points applies. The consequence worth stressing is that a payee in a treaty country whose paperwork has only reached `SUBMITTED` is withheld at 3000 basis points, not 1000: identical country and identical gross yield a materially different net purely because verification has not landed. The rate stored on the collaborator is a live figure that tracks their paperwork; the rate that actually taxes a given payout is pinned separately, at the moment their statement is closed.

A split sheet divides one recording's revenue. Creating one names the recording through `track_id`, states the `effective_from` instant from which the sheet governs allocation, and — because the create is guarded against stale client state — must carry `expected_track_version` matching the track's current `version`, failing which the create is refused with `ERR_STALE_VERSION` (HTTP 412). A successful create yields a sheet in `DRAFT`, with `total_share_bps` and `accepted_share_count` at 0 and `locked_at` null, and advances the parent track's `version` by 1. Sheet states are `DRAFT`, `PENDING_ACCEPTANCE`, `LOCKED` and `SUPERSEDED`, the last being terminal.

Shares are added to a `DRAFT` sheet by naming the payee through `collaborator_id` and the entitlement through `share_bps`, a value between 1 and 10000 inclusive. The same payee may not appear twice on one sheet — a duplicate pairing of sheet and collaborator is refused with `ERR_DUPLICATE_IDENTIFIER`. Each addition recomputes the sheet's `total_share_bps` as the sum of `share_bps` across the sheet's shares and advances the sheet's `version` by 1. A newly added share has `accepted` false and `accepted_at` null, and belongs to its sheet through `split_sheet_id`.

Circulating the sheet for signature moves it `DRAFT → PENDING_ACCEPTANCE` and advances its `version` by 1. Two conditions guard that step: the sheet must hold at least one share, otherwise `ERR_SPLIT_SHEET_EMPTY` (HTTP 422), and `total_share_bps` must equal exactly 10000 — the whole of the recording, no more and no less — otherwise `ERR_SPLIT_TOTAL_INVALID` (HTTP 422). Both of these same two conditions are re-checked at lock time as well, in the same order and with the same codes; they guard those two operations and no others.

Each named payee then responds. Acceptance sets that share's `accepted` to true, stamps `accepted_at` with the current instant, recomputes the sheet's `accepted_share_count` as the number of its shares with `accepted` true, and advances the share's `version` by 1. Rejection is far more destructive and is deliberately so: a single payee rejecting, with a `reason_code` recorded for the artist's benefit, returns the whole sheet from `PENDING_ACCEPTANCE` back to `DRAFT`, clears `accepted` to false and `accepted_at` to null on **every** share of that sheet — not merely the rejecting one — resets `accepted_share_count` to 0, advances the sheet's `version` by 1, and advances the rejecting share's `version` by 1. The artist must then renegotiate and re-circulate, so a sheet may cycle `DRAFT → PENDING_ACCEPTANCE → DRAFT` any number of times. A rejection is only meaningful while the sheet is in `PENDING_ACCEPTANCE` and the rejecting share has not itself already been accepted.

Locking is the artist's final step and requires unanimity: the sheet must be in `PENDING_ACCEPTANCE`, its `accepted_share_count` must equal the total number of its shares, and that count must be at least 1. A lock attempted while any share is still unaccepted is refused with `ERR_SPLIT_NOT_ACCEPTED` (HTTP 409). A successful lock moves the sheet `PENDING_ACCEPTANCE → LOCKED`, stamps `locked_at` with the current instant, writes the sheet's identifier into the parent track's `locked_split_sheet_id`, and — this is the cascade that makes re-splitting possible — moves any other sheet of the same track that was in `LOCKED` to `SUPERSEDED`, advancing that superseded sheet's `version` by 1 as well as the newly locked sheet's own `version`. A track therefore has at most one locked sheet at any instant, and that sheet is the one every later allocation reads.

### 3.5. Editorial Review: From DRAFT to APPROVED, and the Road to LIVE

Submission is the artist's own act and the moment the fiscal gates bite. A release may be submitted only from `DRAFT`, and only when it holds at least one track; a submission of an empty release, or of a release that is not in `DRAFT`, is refused with `ERR_INVALID_STATE`. Beyond that, three further conditions apply, evaluated after the state check in the global precedence order: the scheduled `release_date` must be at least seven whole days after the current instant, otherwise `ERR_RELEASE_DATE_TOO_SOON` (HTTP 422); the artist's subscription must be active or inside its thirty-day grace window, otherwise `ERR_SUBSCRIPTION_INACTIVE`; and a release slot must remain, otherwise `ERR_RELEASE_SLOTS_EXHAUSTED`. A successful submission moves the release `DRAFT → SUBMITTED`, stamps `submitted_at` with the current instant, raises the subscription's `releases_used` by recomputing it, and advances the release's `version` by 1.

Withdrawal is the compensating action and serves two distinct starting points. From `SUBMITTED` it returns the release to `DRAFT`, clears `submitted_at` back to null, recomputes `releases_used` — which falls by one, exactly undoing the submission — and advances `version` by 1. From `REJECTED` the same operation also returns the release to `DRAFT`, but there it clears `rejection_reason_code` back to null instead; `releases_used` is unaffected on this path because the rejection already released the slot. Withdrawal from any other state is refused with `ERR_INVALID_STATE`.

A `DistributionOps` reviewer picks the release up. Taking it into review moves it `SUBMITTED → IN_REVIEW` and advances `version` by 1, changing nothing else. From `IN_REVIEW` the reviewer either approves or rejects. Approval moves the release `IN_REVIEW → APPROVED` and advances `version` by 1, but is permitted only when the release's `upc` is non-null — a barcode-less record cannot be approved, and the attempt is refused with `ERR_INVALID_STATE`. Rejection moves the release `IN_REVIEW → REJECTED`, records the supplied `reason_code` into `rejection_reason_code`, recomputes `releases_used` so that the slot is given back to the artist, and advances `version` by 1. A rejected release is not dead: withdrawing it returns it to `DRAFT` for repair, so the full editorial cycle `DRAFT → SUBMITTED → IN_REVIEW → REJECTED → DRAFT` may be traversed as often as necessary.

Going live is where the two state dimensions of a release finally touch. The editorial transition `APPROVED → LIVE` demands three things at once: the release's editorial `status` is `APPROVED`, its distribution `delivery_status` is `DELIVERED`, and the current instant has reached — is at or after — its `release_date`. It has two entry points that behave identically. A `DistributionOps` operator may drive it explicitly, which is what happens when the last store acknowledgement landed early and the clock only later reaches the release date; if the clock has not yet reached `release_date` that explicit attempt is refused with `ERR_RELEASE_DATE_NOT_REACHED` (HTTP 422), and if the release is not `APPROVED` or its distribution dimension is not yet `DELIVERED` it is refused with `ERR_INVALID_STATE`. Alternatively the platform performs it automatically, without any operator asking, at the instant a store acknowledgement pushes `delivery_status` to `DELIVERED` while the clock has already passed `release_date`. Whichever entry point fires, the effects are the same: every track of the release still sitting in `PENDING` is moved to `ACTIVE`, the owning artist's `live_track_count` is recomputed as the number of tracks in `ACTIVE` across all of that artist's releases, and the release's `version` advances by 1.

### 3.6. Store Delivery: Queueing, Dispatch, Rejection Retry and Takedown

Once a release is approved, a `DistributionOps` operator queues one delivery per destination store. Queueing names the destination through `store_id` and the planned dispatch instant through `scheduled_send_at`. It is permitted only while the release's editorial `status` is either `APPROVED` or `LIVE` — a release still in review cannot be delivered, and the attempt fails with `ERR_INVALID_STATE`.

Five further gates guard queueing, and they are evaluated in the order given here, so a release that trips more than one reports the earliest. First, if the destination store's `requires_explicit_flag` is true, every track of the release must carry a non-null `explicit` declaration; a single undeclared track fails the whole delivery with `ERR_METADATA_NONCOMPLIANT` (HTTP 422). Second, if the store's `requires_isrc` is true, every track must carry a non-null `isrc`, otherwise `ERR_ISRC_MISSING` (HTTP 422). Third, every track of the release must hold a split sheet in `LOCKED`, otherwise `ERR_SPLIT_SHEET_NOT_LOCKED` (HTTP 409) — this is the invariant that later guarantees every earning track has somewhere to send its money. Fourth, the schedule must respect the store's lead time: `scheduled_send_at` advanced by the store's `delivery_lead_days` whole days must fall at or before the release's `release_date`, with exact equality accepted; a schedule that would arrive too late is refused with `ERR_DELIVERY_LEAD_TIME_VIOLATION` (HTTP 422). Fifth is store capacity, described next.

A store can only absorb so much traffic at once. Each delivery occupies a **buffer-expanded window** on its store: the window opens 15 minutes before the delivery's `scheduled_send_at` and closes 75 minutes after it — that is, the 60-minute processing window plus the same 15-minute buffer on the trailing side. The window is closed at its opening instant and open at its closing instant, so two windows that merely touch endpoint-to-endpoint do **not** intersect. Before a new delivery row is created, the platform counts the existing deliveries on that same store whose `status` is either `QUEUED` or `SENT` and whose buffer-expanded window has a non-empty intersection with the new one; deliveries that have already been accepted, rejected, marked for takedown or taken down no longer occupy the store and are not counted. If that count is greater than or equal to the store's `max_concurrent_deliveries`, the request is refused with `ERR_STORE_WINDOW_SATURATED` (HTTP 409).

A successful queueing creates the delivery in `QUEUED` with `attempt_count` at 0 and `last_error_code`, `sent_at` and `taken_down_at` all null, moves the release's `delivery_status` from `NONE` to `QUEUED` when it was still `NONE`, and advances the release's `version` by 1. The delivery belongs to its release through `release_id`. Delivery states are `QUEUED`, `SENT`, `ACCEPTED`, `REJECTED`, `TAKEDOWN_REQUESTED` and `TAKEN_DOWN`, of which the last is terminal.

Dispatching a `QUEUED` delivery is only possible while the destination store's own `status` is `ACTIVE`; dispatch to a `PAUSED` store is refused with `ERR_INVALID_STATE`. Dispatch moves the delivery `QUEUED → SENT`, raises `attempt_count` by 1, stamps `sent_at` with the current instant, and advances the delivery's `version` by 1.

The store's answer arrives as an acknowledgement carrying an `outcome` of either `ACCEPTED` or `REJECTED`, plus an optional `error_code` when the store is complaining. An acknowledgement is only meaningful against a delivery in `SENT`. A rejecting acknowledgement moves the delivery `SENT → REJECTED`, copies the supplied `error_code` into `last_error_code`, and advances `version` by 1. A rejected delivery may be requeued for another attempt, moving it `REJECTED → QUEUED` and advancing `version` by 1, but only while `attempt_count` remains below 3 — the third dispatch is the last one the platform will make, and a further retry attempt is refused with `ERR_INVALID_STATE`. The cycle `QUEUED → SENT → REJECTED → QUEUED` is therefore bounded.

An accepting acknowledgement moves the delivery `SENT → ACCEPTED`, clears `last_error_code` back to null, advances the delivery's `version` by 1, and then recomputes the release's distribution dimension. If at least one delivery of the release is now `ACCEPTED` while at least one sibling delivery remains in `QUEUED`, `SENT` or `REJECTED`, the release moves `QUEUED → PARTIAL`. If instead every delivery of the release is now `ACCEPTED`, the release moves to `DELIVERED` — from `PARTIAL` when siblings were previously outstanding, or directly from `QUEUED` when the release had exactly one delivery all along. Each of these distribution moves advances the release's `version` by 1. Reaching `DELIVERED` is also the moment that may drive the editorial dimension `APPROVED → LIVE`, with the effects described in the preceding subsection, provided the clock has reached `release_date`.

Withdrawing a record from sale is a two-phase cascade that reaches across three levels. Either the owning artist or a `DistributionOps` operator initiates it, and it is permitted only while the release's `delivery_status` is `DELIVERED`; otherwise `ERR_INVALID_STATE`. The first hop moves the release's distribution dimension `DELIVERED → TAKEDOWN_PENDING` and moves every delivery of that release currently in `ACCEPTED` to `TAKEDOWN_REQUESTED`, advancing each such delivery's `version` by 1 as well as the release's own.

Each store then confirms individually. Confirming a takedown moves that delivery `TAKEDOWN_REQUESTED → TAKEN_DOWN`, stamps its `taken_down_at` with the current instant, and advances its `version` by 1. The second hop fires on whichever confirmation leaves no delivery of the release in `QUEUED`, `SENT`, `ACCEPTED` or `TAKEDOWN_REQUESTED` — in other words, when every delivery of the release now sits in either `TAKEN_DOWN` or `REJECTED`. At that point the release's `delivery_status` becomes `TAKEN_DOWN` and, as the third hop, its editorial `status` moves `LIVE → TAKEN_DOWN` with `taken_down_at` stamped on the release itself. The third hop drags a fourth behind it: every track of the release still in `ACTIVE` is moved to `INACTIVE` and has its `content_id_enabled` forced back to false, and because those tracks have left the active set, the owning artist's `live_track_count` is recomputed and the artist's subscription `releases_used` is recomputed too — a taken-down release no longer occupies a slot. The release's `version` advances by 1 for the whole cascade.

### 3.7. The Royalty Ledger: Opening a Statement, Ingesting Lines and Reconciling

Money arrives from the stores in arrears, in batches, per reporting period. A `FinanceOps` operator opens a **royalty statement** for one artist by naming `artist_id` and bounding the reporting period with `period_start` and `period_end`. The interval is half-open: `period_start` is inclusive, `period_end` is exclusive. No two statements of the same artist may overlap — a new statement is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409) whenever any existing statement of that artist, in any status whatsoever including already-closed ones, has a `period_start` strictly earlier than the new `period_end` while the new `period_start` is strictly earlier than that existing statement's `period_end`. Because the intervals are half-open, exact adjacency is fine: a statement beginning precisely where another ends does not overlap it.

A newly opened statement is in `OPEN` with every derived figure at zero — `line_count`, `gross_cents`, `content_id_gross_cents`, `commission_cents`, `content_id_bonus_cents`, `provisional_net_cents` and `net_cents` — and with `reconciled_by_user_id` and `closed_by_user_id` both null. Statement states are `OPEN`, `INGESTING`, `RECONCILED` and `CLOSED`, the last being terminal.

Ingestion appends a batch of reported revenue. The request carries `expected_statement_version`, which must equal the statement's current `version` or the batch is rejected with `ERR_STALE_VERSION` (HTTP 412), together with `lines`, an array of reported royalty lines. Each element names the earning recording through `track_id` and the reporting store through `store_id`, and states `units` — the reported streams or downloads, zero or greater — `gross_cents`, the reported gross revenue in cents, likewise zero or greater, a `source` classifying the revenue as `STREAMING`, `DOWNLOAD` or `CONTENT_ID`, and `reported_at`, the instant the store says the revenue was earned. Every line's `reported_at` must fall inside the statement's half-open period — at or after `period_start` and strictly before `period_end` — and a batch containing even one line outside that window is rejected in full with `ERR_LINE_OUTSIDE_PERIOD` (HTTP 422). Each accepted line is persisted with `royalty_statement_id` pointing at the statement it was ingested into.

Ingestion is permitted from `OPEN`, which it moves to `INGESTING`, and from `INGESTING`, which it leaves in `INGESTING` — a statement may absorb as many successive batches as the feed requires. Every successful batch appends one line per submitted element, recomputes the three aggregates, and advances the statement's `version` by 1. The aggregates are defined over every line whose `royalty_statement_id` matches the statement, with no status filter of any kind because lines are append-only: `line_count` is the number of such lines, `gross_cents` is the sum of their `gross_cents`, and `content_id_gross_cents` is the sum of `gross_cents` restricted to lines whose `source` is `CONTENT_ID`. The complement — total gross minus Content-ID gross — is the non-Content-ID gross, and it matters at close. Ingestion against a statement already `RECONCILED` or `CLOSED` is refused with `ERR_INVALID_STATE`.

Reconciliation produces the provisional numbers the artist sees first. It may be performed from `INGESTING`, and also from `OPEN` for a statement that never received a single line, in which case `commission_cents` and `provisional_net_cents` are both simply 0. In either case the acting operator's `X-User-ID` is recorded into `reconciled_by_user_id`, the statement moves to `RECONCILED`, and its `version` advances by 1.

The commission itself is computed in five steps, and both the provisional pass here and the final pass at close share the first three of them.

**Step one — loyalty discount.** Read the artist's `lifetime_gross_cents`, which reflects only statements that have already reached `CLOSED` and therefore excludes the statement being worked on. If that figure is at least 500000 cents, the loyalty discount is 250 basis points; otherwise if it is at least 100000 cents, the discount is 100 basis points; otherwise there is no discount and the figure is 0 basis points.

**Step two — gross-weighted store surcharge.** If the statement's `gross_cents` is 0, the weighted surcharge is 0 basis points. Otherwise, for every line of the statement, multiply that line's `gross_cents` by the `surcharge_bps` of the store that reported it; sum those products across all lines; divide the sum by the statement's `gross_cents`; and round the quotient half up to a whole number of basis points. That rounding happens **here**, before the surcharge is used for anything else — the fractional value is never carried forward.

**Step three — effective rate.** Take the `commission_bps` of the plan behind the artist's subscription, subtract the loyalty discount from step one, and add the weighted surcharge from step two. Clamp the outcome to the range 0 to 10000 inclusive: anything below 0 becomes 0, anything above 10000 becomes 10000. The plan in question is the plan of the artist's subscription; when the artist has more than one subscription row, the relevant one is the most recently created subscription of that artist whose `status` is one of `ACTIVE`, `PAST_DUE`, `EXPIRED` or `CANCELLED`.

**Step four — the variant-dependent basis.** In the **provisional** variant used at reconciliation, the whole of the statement's `gross_cents` is commissioned at the effective rate: multiply `gross_cents` by the effective rate, divide by 10000, and round half up to whole cents. That raw figure includes Content-ID revenue at the plan rate. (The **final** variant used at close computes this step differently; Section 3.8 gives it.)

**Step five — floor and cap.** Compute the cap as the statement's `gross_cents` multiplied by 2000 basis points and divided by 10000, rounded half up to whole cents — the platform never takes more than a fifth of an artist's gross. If the statement's `gross_cents` is 0, the commission is 0 and no floor applies. Otherwise the commission is the raw figure from step four, first limited downward to the cap by taking the smaller of the two, and then lifted to the floor of 50 cents by taking the larger of that result and 50. The minimum-commission floor therefore wins over the cap whenever both would bite.

Reconciliation stores that provisional commission in `commission_cents`, computes `provisional_net_cents` as the statement's `gross_cents` minus that commission, copies the same value into `net_cents`, and leaves `content_id_bonus_cents` at 0 — the Content-ID bonus does not exist until the statement closes. Reconciling a statement that is not in `OPEN` or `INGESTING` is refused with `ERR_INVALID_STATE`.

### 3.8. Closing a Statement: Final Numbers and the Payout Cascade

Closing is the single heaviest operation in the platform. It may be performed only on a statement in `RECONCILED` — any other state is refused with `ERR_INVALID_STATE` — and only by a `FinanceOps` operator whose `X-User-ID` differs from the `reconciled_by_user_id` already recorded on that statement, on pain of `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The operator who closes is recorded in `closed_by_user_id`, and the statement's `version` advances by 1.

**Final commission.** Steps one through three of the commission computation are re-run exactly as at reconciliation — the loyalty tier from the artist's `lifetime_gross_cents`, the gross-weighted store surcharge rounded half up to whole basis points, and the effective rate clamped to the range 0 to 10000. Step four, however, splits the basis in two. The non-Content-ID gross — the statement's `gross_cents` less its `content_id_gross_cents` — is multiplied by the effective rate, divided by 10000 and rounded half up to whole cents. Separately, the statement's `content_id_gross_cents` is multiplied by 3000 basis points, divided by 10000 and rounded half up to whole cents; Content-ID revenue is commissioned at that flat 3000-basis-point rate rather than at the artist's plan rate. The two rounded amounts are then added together to give the raw final figure. Step five is unchanged: the same 2000-basis-point cap on `gross_cents` limits it from above, the same 50-cent floor lifts it from below, and a statement with zero gross has zero commission. Because of the split basis, identical line data yields a different commission at close than it did at reconciliation whenever the statement has any Content-ID revenue at all and the effective rate is not itself exactly 3000 basis points — and that divergence is deliberate, visible and reportable.

**Content-ID bonus.** Close is also the only moment the Content-ID bonus is computed. Its tier is selected from the statement's `content_id_gross_cents` **before** any bonus exists: if that figure is at least 200000 cents the bonus rate is 500 basis points, otherwise if it is at least 50000 cents the bonus rate is 200 basis points, otherwise it is 0. The bonus is then that Content-ID gross multiplied by the selected rate, divided by 10000 and rounded half up to whole cents, and it is stored in `content_id_bonus_cents`. The bonus is never fed back into its own tier selection, even though it is subsequently added to the statement total.

**Final net.** With those two figures in hand, `net_cents` becomes the statement's `gross_cents`, less the final commission, plus the Content-ID bonus. The value of `provisional_net_cents` recorded at reconciliation is deliberately left untouched, so that the divergence between the provisional and final views remains reportable after the fact.

**Allocating the net.** The final net is then distributed down to individual payees through a two-level waterfall whose rounding order is pinned. Rounding each share independently and summing the results is explicitly **not** the rule and produces a different distribution of cents.

At the first level the net is split across recordings. The participating recordings are exactly those tracks that have at least one royalty line in this statement. If the statement's `gross_cents` is 0, every track receives 0. Otherwise, for each participating track, compute its exact rational entitlement as the statement's `net_cents` multiplied by that track's own total gross across this statement's lines and divided by the statement's `gross_cents`; take the floor of that rational value as the track's provisional allocation; sum those floors and subtract the sum from the statement's `net_cents` to obtain the leftover cents. Then order the participating tracks by the fractional part of their exact entitlement, largest first, breaking ties by the track's `created_at` earliest first, and hand one additional cent to each of the first tracks in that order until the leftover is exhausted.

At the second level each recording's allocation is split across its payees. The governing sheet for a track is the one split sheet of that track whose status is `LOCKED`, reachable through the track's `locked_split_sheet_id`; such a sheet always exists for a participating track, because no delivery could ever have been queued for the release otherwise. For each share on that sheet, compute the exact rational entitlement as the track's allocated cents multiplied by that share's `share_bps` and divided by 10000; take the floor as the share's provisional cents; sum those floors and subtract from the track's allocation to obtain that track's leftover cents. Order the shares by the fractional part of their exact entitlement, largest first, breaking ties first by `share_bps` largest first and then by the share's `created_at` earliest first, and hand one additional cent to each of the first shares in that order until that track's leftover is exhausted.

Finally the per-share cents are folded by payee: one payout is created for each collaborator holding at least one share in the locked sheets of the statement's participating tracks, and its `gross_cents` is the sum of every share amount awarded to that collaborator across every track. The invariant this procedure guarantees is exact: the sum of `gross_cents` across all payouts created by a close equals the statement's `net_cents` to the cent, with nothing lost and nothing invented.

**Taxing each payout.** Each new payout records `collaborator_id` for its payee and `royalty_statement_id` for the statement it settles. Its `withholding_bps` is pinned at this moment by re-evaluating the four-case withholding ladder for that collaborator — backup at 2400 basis points when the paperwork is `MISSING` or `EXPIRED`, zero for a `US` payee, 1000 basis points for a `VERIFIED` payee resident in `GB`, `DE`, `NL`, `AU` or `JP`, and 3000 basis points otherwise — and stored on the payout, so that later paperwork changes cannot retroactively alter a settled payout. Its `withholding_cents` is the payout's `gross_cents` multiplied by that pinned rate, divided by 10000 and rounded half up to whole cents, and its `net_cents` is `gross_cents` less `withholding_cents`. Each created payout starts in `PENDING` with `auto_approved` false, `approved_by_user_id`, `paid_by_user_id`, `paid_at` and `reversal_reason_code` all null, and each raises its collaborator's `pending_payout_cents` by that payout's `net_cents`.

**Auto-approval.** As the last hop of the cascade, every payout the close just created whose `net_cents` is at least 2000 cents moves straight from `PENDING` to `APPROVED` with `auto_approved` set true, `approved_by_user_id` deliberately left null, and its `version` advanced by 1. Payouts below that threshold remain in `PENDING` awaiting a human. Because an auto-approved payout records no approver, no segregation-of-duties restriction later constrains who may pay it.

**Artist history.** Closing also raises the artist's `lifetime_gross_cents` by the statement's `gross_cents`, which is why the loyalty tier of the *next* statement can differ from this one's, and why the artist's history figure never includes the statement currently being priced.

### 3.9. Settling Up: Payout Approval, Payment, Reversal, Reporting and Year-End Forms

A payout's lifecycle runs `PENDING → APPROVED → PAID → REVERSED`, with `REVERSED` terminal. Manual approval is available to any `FinanceOps` operator for a payout still in `PENDING`; it records the acting `X-User-ID` into `approved_by_user_id`, sets `auto_approved` to false, and advances the payout's `version` by 1. This is the deliberate counterpart of the auto-approval performed by the close cascade: an auto-approved payout carries `auto_approved` true and no recorded approver, whereas a manually approved one carries `auto_approved` false and names its approver. Approving anything not in `PENDING` is refused with `ERR_INVALID_STATE`.

Payment is the most heavily guarded step in the ledger. The payout must be in `APPROVED`, otherwise `ERR_INVALID_STATE`. When the payout carries a non-null `approved_by_user_id`, the paying operator's `X-User-ID` must differ from it, otherwise `ERR_SEGREGATION_OF_DUTIES`; an auto-approved payout has no recorded approver and so imposes no such constraint. The payee's `tax_form_status` must be exactly `VERIFIED` at the moment of payment — `MISSING`, `SUBMITTED` and `EXPIRED` all fail with `ERR_TAX_FORM_NOT_VERIFIED` (HTTP 422). And the payout's `net_cents` must be at least 2000 cents; anything smaller is refused with `ERR_PAYOUT_BELOW_THRESHOLD` (HTTP 422), since the platform does not move sub-threshold sums. A successful payment moves the payout `APPROVED → PAID`, stamps `paid_at` with the current instant, records the acting `X-User-ID` into `paid_by_user_id`, lowers the payee's `pending_payout_cents` by the payout's `net_cents` while raising their `lifetime_paid_cents` by the same amount, and advances the payout's `version` by 1.

Mistakes happen, and reversal is the compensating action. A `PAID` payout may be reversed, with a `reason_code` recorded into `reversal_reason_code`, provided the current instant is strictly earlier than ninety days after the payout's `paid_at`; a reversal attempted ninety days or more after payment is refused with `ERR_REVERSAL_WINDOW_EXPIRED` (HTTP 422), and reversing anything not in `PAID` is refused with `ERR_INVALID_STATE`. Reversal moves the payout `PAID → REVERSED`, lowers the payee's `lifetime_paid_cents` by the payout's `net_cents`, raises their `reversed_payout_cents` by the same amount, and advances `version` by 1.

Those three running totals on a collaborator are not free-floating counters — they are defined as aggregates over that payee's payouts and must agree with them at every observable instant. `pending_payout_cents` is the sum of `net_cents` across the payee's payouts in `PENDING` or `APPROVED`; `lifetime_paid_cents` is the sum across those in `PAID`; `reversed_payout_cents` is the sum across those in `REVERSED`. Payment moves an amount from the first bucket to the second and reversal moves the same amount from the second to the third, so the sum of all three buckets is identical before payment, after payment and after reversal — the payee's settled total never drifts. A second identity holds alongside it: `pending_payout_cents` plus `lifetime_paid_cents` always equals the sum of `net_cents` across the payee's payouts in `PENDING`, `APPROVED` or `PAID`.

For anyone who wants the whole picture of a statement in one read, a computed roll-up is available to finance operators, the owning artist and platform administrators. It reports `statement_id`, the statement's `gross_cents` and `content_id_gross_cents`, its `commission_cents` and `content_id_bonus_cents`, both `provisional_net_cents` and `net_cents`, a `variant_delta_cents` giving the divergence between the final net and the provisional net — the final `net_cents` less `provisional_net_cents` — and two payout roll-ups: `payout_count`, the number of payouts attached to the statement, and `payout_gross_total_cents`, the sum of their `gross_cents`. The roll-up mutates nothing.

Year-end reporting closes the loop. A `FinanceOps` operator drafts a 1099 by naming the payee through `collaborator_id` and the calendar year through `tax_year`, a value between 2020 and 2100 inclusive. Only one live form may exist per payee and year: a second draft for a pairing that already has a form in `DRAFT` or `ISSUED` is refused with `ERR_DUPLICATE_IDENTIFIER`, though a `VOIDED` form does not block a replacement. The form is created in `DRAFT` with `issued_at` null and `total_paid_cents` computed immediately as the sum of `net_cents` across that collaborator's payouts whose status is `PAID` and whose `paid_at` falls within the calendar year named by `tax_year`, read in UTC. Reversed payouts are excluded from that sum, so a reversal landing before issue genuinely lowers the reported total.

Issuing recomputes `total_paid_cents` afresh before deciding, moves the form `DRAFT → ISSUED`, stamps `issued_at` with the current instant, and advances its `version` by 1 — but only when that recomputed total is at least 60000 cents; a form below the reporting threshold is refused with `ERR_1099_THRESHOLD_NOT_MET` (HTTP 422), and issuing a form not in `DRAFT` is refused with `ERR_INVALID_STATE`. An issued form may later be voided with a `reason_code`, moving it `ISSUED → VOIDED` and advancing its `version` by 1; `VOIDED` is terminal, and voiding anything not in `ISSUED` is refused with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that bring a brand-new resource into existence answer with HTTP 201; every other successful operation — reads, metadata amendments, state transitions and computed reports — answers with HTTP 200. The table below is a routing summary only: request payloads, response contents and side effects are specified in the Section 3 narratives, and the error each operation can raise is governed by the precedence order of Section 2.8.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Sets the server's logical clock. | PlatformAdmin |
| POST | `/api/subscription-plans` | Creates a subscription plan. | PlatformAdmin |
| GET | `/api/subscription-plans/{id}` | Reads one subscription plan. | PlatformAdmin, Artist, FinanceOps, DistributionOps |
| GET | `/api/subscription-plans` | Lists subscription plans. | PlatformAdmin, Artist, FinanceOps, DistributionOps |
| POST | `/api/stores` | Creates a store (delivery destination). | PlatformAdmin |
| GET | `/api/stores/{id}` | Reads one store. | PlatformAdmin, DistributionOps, FinanceOps, Artist |
| GET | `/api/stores` | Lists stores. | PlatformAdmin, DistributionOps, FinanceOps, Artist |
| POST | `/api/artists` | Registers an artist account. | PlatformAdmin |
| GET | `/api/artists/{id}` | Reads one artist. | PlatformAdmin, Artist, FinanceOps, DistributionOps |
| GET | `/api/artists` | Lists artists. | PlatformAdmin, FinanceOps, DistributionOps |
| PATCH | `/api/artists/{id}` | Updates mutable artist attributes. | PlatformAdmin |
| POST | `/api/subscriptions` | Creates a PENDING subscription for an artist on a plan. | PlatformAdmin |
| GET | `/api/subscriptions/{id}` | Reads one subscription. | PlatformAdmin, Artist, FinanceOps |
| GET | `/api/subscriptions` | Lists subscriptions, filterable by owning artist or plan. | PlatformAdmin, Artist, FinanceOps |
| POST | `/api/subscriptions/{id}/activate` | Activates a PENDING subscription or restores a PAST_DUE one. | PlatformAdmin |
| POST | `/api/subscriptions/{id}/lapse` | Marks an ACTIVE subscription PAST_DUE and starts the 30-day grace window. | PlatformAdmin |
| POST | `/api/subscriptions/{id}/expire` | Expires a PAST_DUE subscription, or cancels an ACTIVE subscription whose auto_renew is false. | PlatformAdmin |
| POST | `/api/releases` | Creates a DRAFT release. | Artist |
| GET | `/api/releases/{id}` | Reads one release. | Artist, DistributionOps, FinanceOps, PlatformAdmin |
| GET | `/api/releases` | Lists releases, filterable by owning artist and by either state dimension. | Artist, DistributionOps, FinanceOps, PlatformAdmin |
| PATCH | `/api/releases/{id}` | Updates mutable release metadata while the release is in DRAFT. | Artist |
| POST | `/api/releases/{id}/submit` | Submits a DRAFT release for editorial review. | Artist |
| POST | `/api/releases/{id}/withdraw` | Withdraws a SUBMITTED or REJECTED release back to DRAFT; compensating action of submit. | Artist |
| POST | `/api/releases/{id}/review` | Moves a SUBMITTED release into IN_REVIEW. | DistributionOps |
| POST | `/api/releases/{id}/approve` | Approves an IN_REVIEW release for distribution. | DistributionOps |
| POST | `/api/releases/{id}/reject` | Rejects an IN_REVIEW release. | DistributionOps |
| POST | `/api/releases/{id}/takedown` | Requests takedown of a DELIVERED release from every store. | Artist, DistributionOps |
| POST | `/api/releases/{id}/go-live` | Publishes an APPROVED, fully DELIVERED release once the logical clock has reached its release_date. | DistributionOps |
| POST | `/api/releases/{id}/pre-saves` | Registers a fan pre-save for a release. | Fan |
| POST | `/api/releases/{id}/tracks` | Adds a track to a DRAFT release. | Artist |
| GET | `/api/tracks/{id}` | Reads one track. | Artist, DistributionOps, FinanceOps, PlatformAdmin |
| GET | `/api/tracks` | Lists tracks, filterable by owning release. | Artist, DistributionOps, FinanceOps, PlatformAdmin |
| PATCH | `/api/tracks/{id}` | Updates mutable track metadata. | Artist |
| POST | `/api/collaborators` | Registers a payee under an artist account. | Artist |
| GET | `/api/collaborators/{id}` | Reads one collaborator. | Artist, Collaborator, FinanceOps, PlatformAdmin |
| GET | `/api/collaborators` | Lists collaborators, filterable by owning artist. | Artist, FinanceOps, PlatformAdmin |
| PATCH | `/api/collaborators/{id}` | Updates a payee's tax documentation state or payout rail. | Artist, FinanceOps |
| POST | `/api/split-sheets` | Creates a DRAFT split sheet for a track. | Artist |
| GET | `/api/split-sheets/{id}` | Reads one split sheet. | Artist, Collaborator, FinanceOps, PlatformAdmin |
| GET | `/api/split-sheets` | Lists split sheets, filterable by owning track. | Artist, Collaborator, FinanceOps, PlatformAdmin |
| POST | `/api/split-sheets/{id}/shares` | Adds a collaborator share to a DRAFT split sheet. | Artist |
| GET | `/api/split-shares/{id}` | Reads one split share. | Artist, Collaborator, FinanceOps, PlatformAdmin |
| GET | `/api/split-shares` | Lists split shares, filterable by sheet or by payee. | Artist, Collaborator, FinanceOps, PlatformAdmin |
| POST | `/api/split-sheets/{id}/send` | Sends a complete DRAFT sheet to its collaborators for acceptance. | Artist |
| POST | `/api/split-shares/{id}/accept` | A collaborator accepts their share. | Collaborator |
| POST | `/api/split-shares/{id}/reject` | A collaborator rejects their share, returning the whole sheet to DRAFT and clearing every acceptance. | Collaborator |
| POST | `/api/split-sheets/{id}/lock` | Locks a fully accepted sheet, superseding any previously LOCKED sheet of the same track. | Artist |
| POST | `/api/releases/{id}/deliveries` | Queues a delivery of an APPROVED release to a store. | DistributionOps |
| GET | `/api/deliveries/{id}` | Reads one delivery. | DistributionOps, Artist, PlatformAdmin |
| GET | `/api/deliveries` | Lists deliveries, filterable by release or store. | DistributionOps, Artist, PlatformAdmin |
| POST | `/api/deliveries/{id}/send` | Dispatches a QUEUED delivery to the store. | DistributionOps |
| POST | `/api/deliveries/{id}/ack` | Records the store's acknowledgement of a SENT delivery. | DistributionOps |
| POST | `/api/deliveries/{id}/retry` | Requeues a REJECTED delivery for another attempt. | DistributionOps |
| POST | `/api/deliveries/{id}/confirm-takedown` | Confirms the store has removed the release. | DistributionOps |
| POST | `/api/royalty-statements` | Opens a royalty statement for an artist over a half-open reporting period. | FinanceOps |
| GET | `/api/royalty-statements/{id}` | Reads one royalty statement. | FinanceOps, Artist, PlatformAdmin |
| GET | `/api/royalty-statements` | Lists royalty statements, filterable by artist. | FinanceOps, Artist, PlatformAdmin |
| POST | `/api/royalty-statements/{id}/ingest` | Appends a batch of reported royalty lines. | FinanceOps |
| GET | `/api/royalty-lines/{id}` | Reads one ingested royalty line. | FinanceOps, Artist, PlatformAdmin |
| GET | `/api/royalty-lines` | Lists royalty lines, filterable by statement, track or store. | FinanceOps, Artist, PlatformAdmin |
| POST | `/api/royalty-statements/{id}/reconcile` | Computes the PROVISIONAL commission and net for the statement. | FinanceOps |
| POST | `/api/royalty-statements/{id}/close` | Closes the statement: recomputes commission and net with the FINAL variant and materialises collaborator payouts. | FinanceOps |
| GET | `/api/royalty-statements/{id}/summary` | Computed report: gross, commission, bonus, provisional vs final net and their divergence, plus payout roll-up. | FinanceOps, Artist, PlatformAdmin |
| GET | `/api/payouts/{id}` | Reads one payout. | FinanceOps, Collaborator, Artist, PlatformAdmin |
| GET | `/api/payouts` | Lists payouts, filterable by payee or statement. | FinanceOps, Collaborator, Artist, PlatformAdmin |
| POST | `/api/payouts/{id}/approve` | Manually approves a PENDING payout and records the approving operator. | FinanceOps |
| POST | `/api/payouts/{id}/pay` | Pays an APPROVED payout; segregated from the approving operator. | FinanceOps |
| POST | `/api/payouts/{id}/reverse` | Reverses a PAID payout inside the 90-day reversal window; compensating action of pay. | FinanceOps |
| POST | `/api/tax-forms` | Drafts a 1099 for a collaborator and a tax year. | FinanceOps |
| GET | `/api/tax-forms/{id}` | Reads one 1099 form. | FinanceOps, Collaborator, PlatformAdmin |
| GET | `/api/tax-forms` | Lists 1099 forms, filterable by payee. | FinanceOps, Collaborator, PlatformAdmin |
| POST | `/api/tax-forms/{id}/issue` | Issues a DRAFT 1099 once the reportable total reaches the 60000-cent threshold. | FinanceOps |
| POST | `/api/tax-forms/{id}/void` | Voids an ISSUED 1099. | FinanceOps |

## 5. Error Code Catalogue

Each error is returned in the standard error envelope of Section 2.2, carrying the identifier below as `error_id`. The conditions that raise each one are stated in the Section 2 and Section 3 narratives that govern the operation concerned.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_METADATA_NONCOMPLIANT` | 422 |
| `ERR_ISRC_MISSING` | 422 |
| `ERR_SPLIT_SHEET_NOT_LOCKED` | 409 |
| `ERR_SPLIT_SHEET_EMPTY` | 422 |
| `ERR_SPLIT_TOTAL_INVALID` | 422 |
| `ERR_SPLIT_NOT_ACCEPTED` | 409 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_RELEASE_DATE_TOO_SOON` | 422 |
| `ERR_DELIVERY_LEAD_TIME_VIOLATION` | 422 |
| `ERR_STORE_WINDOW_SATURATED` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
| `ERR_LINE_OUTSIDE_PERIOD` | 422 |
| `ERR_PRE_SAVE_WINDOW_CLOSED` | 422 |
| `ERR_REVERSAL_WINDOW_EXPIRED` | 422 |
| `ERR_SUBSCRIPTION_INACTIVE` | 402 |
| `ERR_RELEASE_SLOTS_EXHAUSTED` | 402 |
| `ERR_CONTENT_ID_NOT_ENTITLED` | 403 |
| `ERR_TAX_FORM_NOT_VERIFIED` | 422 |
| `ERR_PAYOUT_BELOW_THRESHOLD` | 422 |
| `ERR_1099_THRESHOLD_NOT_MET` | 422 |
| `ERR_RELEASE_DATE_NOT_REACHED` | 422 |

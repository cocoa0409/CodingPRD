# Programmatic Exchange Bid Management API — Product Requirements Document

## 1. Introduction

Programmatic advertising runs on a marketplace of milliseconds: publishers package inventory, demand-side platforms bid against that inventory, and the exchange in the middle must clear each auction, enforce brand safety, throttle request volume, and account for every micro of money that moves. This document specifies the Programmatic Exchange & Bid Management API, the control plane for such an exchange. It covers inventory packaging and deal configuration on the supply side, floor pricing and auction dynamics at the clearing layer, bid throttling and capacity limits on the demand side, and the full financial tail of the business — supply-path fee transparency, DSP-versus-SSP discrepancy reconciliation, seasonal pricing strategy, and publisher payout under both sequential-liability and guaranteed payment terms.

Two design pressures shape everything that follows. First, the marketplace is adversarial: creatives must be screened against blocklists, demand partners must be capped per second and per day, and click-fraud corrections must be reversible without corrupting settled money. Second, the money is dual-view by construction — what a DSP is billed and what a publisher earns are computed differently and are never expected to reconcile to the same number, so the system treats discrepancy measurement and make-good adjustment as first-class workflows rather than exception handling. All of this operates against a deterministic logical clock so that auctions, seasonal windows, throttles, and settlement periods behave identically on every run.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract and the cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the capacity in which they act. The system recognizes exactly four roles: `ExchangeAdmin`, `PublisherManager`, `DemandSide`, and `FinanceOfficer`. A request with either header missing or malformed is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint — or whose entity-backed ownership check fails — is rejected with `ERR_UNAUTHORIZED`.

The roles anchor to resources differently. When `X-User-Role` is `PublisherManager`, `X-User-ID` is the `id` of the acting `Publisher`; ownership checks on any resource that references a publisher — packages, deals, seasonal windows, supply-chain nodes, publisher-scoped or deal-scoped blocklist entries — compare the resource's publisher foreign key against `X-User-ID`, and a `PublisherManager` may only mutate resources whose owning publisher id equals their own. When `X-User-Role` is `ExchangeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, in the segregation-of-duties comparison at batch approval time) but does not compare it to any entity's `id`. When `X-User-Role` is `DemandSide`, `X-User-ID` is likewise an opaque operator identifier for the bidding agent; auctions are cross-publisher by design, so a `DemandSide` caller is never blocked by publisher ownership. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier as well, though it is persisted on payout batches as `created_by_user_id` so the approval step can enforce segregation of duties.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All temporal behavior in the exchange is driven by a server-side logical clock, never by wall-clock time. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z. An `ExchangeAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every timestamp the system records — billing confirmations, voids, report resolutions — is taken from this logical clock. Date-typed fields use the YYYY-MM-DD format; datetime-typed fields are ISO 8601 UTC.

Setting the clock fires three sweeps. When the new time enters a later UTC second, every demand partner's `current_second_auction_count` resets to zero, and any partner sitting in `THROTTLED` is automatically reactivated to `ACTIVE` provided the new time is in a later UTC second than the one in which it was throttled and its `spend_today_micros`, recomputed for the new UTC date, is below its `daily_cap_micros`. When the new time crosses into a different UTC date, every inventory package's `current_seasonal_multiplier_bps` and `effective_floor_cpm_micros` are recomputed against the new date, and every demand partner's `spend_today_micros` is recomputed for the new date. Independently of both, every deal still `ACTIVE` whose `end_at` is at or before the new time transitions to `EXPIRED`. The same expiry evaluation also happens lazily whenever an individual deal is touched — on reads, on auction candidacy, on resume attempts — so a deal whose flight has ended never remains actionable.

### 2.5. Money, Rates, and Rounding

All monetary amounts are integer **micros**: one US dollar equals 1,000,000 micros, and no fractional micro ever exists anywhere in the system. All rates are integer **basis points**, where 10,000 basis points equal 100 percent; a neutral multiplier is therefore 10,000 basis points, and a 10 percent fee is 1,000 basis points. Whenever a calculation divides and must land on an integer micro amount, the result is rounded half-up to the nearest integer micro. Where several rounded components feed a sum, each component is rounded individually first and the rounded values are then summed — summing unrounded intermediates and rounding once at the end is not permitted anywhere. The one non-integer quantity in the system is the reconciliation discrepancy percentage, which is rounded half-up to three decimal places.

### 2.6. Common Resource Properties

Most resources share a standard set of system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp of creation, carried with three fractional digits. `updated_at` follows the same format and refreshes on every mutation of the resource. `version` is an integer that starts at creation and increments by one on every mutation — including mutations the server performs itself, such as recomputing a package's derived floor fields, cascading a pause onto a deal, or recomputing a publisher's accrual balances. Two ledger-style resources are deliberately thinner: a supply-chain node and an auction record each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because neither is ever modified after creation.

### 2.7. Optimistic Concurrency Control on Commercial Edits

Three write operations guard against stale views with optimistic concurrency control, and each names its expectation field after the entity it edits. Editing a deal's commercial terms requires the request to carry `expected_deal_version` equal to the deal's current `version`. Editing an inventory package requires `expected_package_version` equal to the package's current `version`. Retuning a demand partner's capacity requires `expected_demand_partner_version` equal to the partner's current `version`. In all three cases the field is non-optional: if another writer has advanced the entity's version since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before overwriting changes it has not observed. No other endpoint accepts a version field.

### 2.8. The Validation Pipeline and Its Evaluation Order

Every request passes through a fixed validation pipeline, and the request fails at the first check that does not pass — later checks never mask earlier ones. The order is:

1. Authentication: both identity headers present and well-formed, else `ERR_UNAUTHENTICATED`.
2. Authorization: the caller's role is permitted for this endpoint, else `ERR_UNAUTHORIZED`.
3. Body well-formedness: every required field present, JSON types correct, numeric amounts positive where required (floors and daily caps above zero, `max_qps` at least 1, `fee_bps` within 0 to 9,000, `multiplier_bps` within 1 to 100,000, the bids array non-empty with each bid carrying a positive `bid_cpm_micros`, a positive `impression_count`, and a non-empty `creative_domain`), and enum members valid, else `ERR_INVALID_REQUEST`.
4. Field formats: dates in YYYY-MM-DD, datetimes in ISO 8601 UTC, `category_tags` a non-empty array of strings, `write_off_reason` non-empty where required, else `ERR_VALIDATION`.
5. Existence: every path identifier and every body foreign key resolves, validated left to right — a deal before its report, a batch before its line — else `ERR_NOT_FOUND`.
6. State and ownership: the target entity is in a state that permits the operation. Where a transition-specific state code exists it is used — `ERR_BATCH_NOT_SUBMITTABLE`, `ERR_BATCH_NOT_PENDING_APPROVAL`, `ERR_BATCH_NOT_APPROVED`, `ERR_BATCH_NOT_SETTLED`, `ERR_LINE_NOT_PENDING`, `ERR_LINE_NOT_HELD`, `ERR_REPORT_ALREADY_TERMINAL`, `ERR_ENTRY_ALREADY_LIFTED`, `ERR_PARTNER_NOT_RESUMABLE`, `ERR_ALREADY_CONFIRMED`, `ERR_ALREADY_VOIDED`, `ERR_PACKAGE_NOT_ACTIVE`, `ERR_PARTNER_NOT_ACTIVE`, `ERR_PUBLISHER_SUSPENDED` — and any other state-precondition failure surfaces as `ERR_INVALID_STATE`. Ownership for entity-backed roles is enforced at this same stage: a `PublisherManager` mutating a resource owned by a different publisher is rejected with `ERR_UNAUTHORIZED`.
7. Deal editability: commercial edits to a deal are allowed only while it is in `DRAFT` or `RENEGOTIATING`, and its `auction_type` and `deal_type` are immutable once first approved, else `ERR_DEAL_NOT_EDITABLE`.
8. Blocklist scope consistency: a new entry's `value` must be non-empty, a `PUBLISHER`-scoped entry must carry `publisher_id` and no `deal_id`, a `DEAL`-scoped entry must carry `deal_id` and no `publisher_id`, and an `EXCHANGE`-scoped entry must carry neither, else `ERR_BLOCKLIST_SCOPE_MISMATCH`.
9. Interval sanity: a seasonal window's `start_date` on or before its `end_date`, a deal's `start_at` strictly before its `end_at`, and a report's or batch's `period_start` strictly before its `period_end`, else `ERR_INVALID_TIME_RANGE`.
10. Seasonal window overlap: no two windows on the same package may overlap as closed intervals, else `ERR_SEASONAL_WINDOW_OVERLAP`.
11. Payout period overlap at submission, else `ERR_PAYOUT_PERIOD_OVERLAP`.
12. Supply-chain tail integrity when appending a node, else `ERR_SUPPLY_CHAIN_NOT_TAIL`.
13. Supply-chain depth and per-hop fee capacity, else `ERR_SUPPLY_CHAIN_TOO_DEEP`.
14. Programmatic-guaranteed commitment terms, else `ERR_PG_COMMITMENT_MISMATCH`.
15. Segregation of duties at batch approval, else `ERR_SEGREGATION_OF_DUTIES`.
16. Settlement protection when voiding an auction record, else `ERR_VOID_AFTER_SETTLEMENT`.
17. Write-off eligibility of a payout line, else `ERR_LINE_NOT_WRITABLE_OFF`.
18. Reconciliation resolution input consistency, else `ERR_RECONCILIATION_INPUT_MISMATCH`.

Because the pipeline short-circuits, a request that is both unauthenticated and malformed always reports `ERR_UNAUTHENTICATED`; a malformed body on a non-existent resource reports `ERR_INVALID_REQUEST` rather than `ERR_NOT_FOUND`; and a state failure always surfaces before any business-temporal or business-fiscal rule on the same endpoint.

### 2.9. Identifier Resolution on Nested Paths

Resource URLs in this API are flat, but several paths still chain identifiers — a line beneath its batch, a statement beneath its publisher, records beneath a deal. Existence is validated strictly left to right along the path: a request naming a non-existent batch and a non-existent line is rejected with `ERR_NOT_FOUND` for the batch, without the line ever being examined. The same left-to-right discipline applies to foreign keys in request bodies at pipeline stage five.

### 2.10. Conservation Invariants and Cascade Discipline

Two conservation laws hold at every instant. On the supply side, for each publisher: `lifetime_net_micros` plus the sum of open make-good adjustments always equals `paid_out_micros` plus `written_off_micros` plus `accrued_open_micros`; nothing may be created or destroyed silently, only moved between those buckets. On the demand side, for each partner: `lifetime_spend_micros` always equals the sum of `gross_micros` over that partner's non-voided auction records — creating a record adds its gross, voiding it subtracts the same gross, and a create-then-void pair leaves lifetime spend unchanged; `spend_today_micros` obeys the same law restricted to records created on the current UTC date.

Structural cascades follow a single direction and always stop where the scaffold of ownership stops. Suspending a publisher pauses its active packages and, one hop further, pauses every active deal on those packages; each cascaded mutation refreshes `updated_at` and increments the affected resource's `version`. Resuming walks the same chain only partway: the publisher and its packages come back, but paused deals stay paused until each is individually resumed. Derived-field recomputation is likewise a mutation: when a publisher's accrual balances or a package's effective floor change as a side effect of another operation, the owning resource's `version` and `updated_at` move with them.

## 3. Business Logic & Workflows

### 3.1. Onboarding and Governing Publishers and Demand Partners

An `ExchangeAdmin` registers a publisher by supplying its display `name` and primary `domain`, optionally choosing `payment_terms` — `SEQUENTIAL_LIABILITY`, meaning the publisher is paid only as DSPs confirm their billing, or `GUARANTEED`, meaning the publisher is paid on the exchange's gross recording regardless of DSP confirmation. When omitted, `payment_terms` defaults to `SEQUENTIAL_LIABILITY`. A new publisher starts `ACTIVE` with all derived balances — `lifetime_net_micros`, `accrued_open_micros`, `paid_out_micros`, `written_off_micros` — at zero, and with `active_package_count` at zero. The publisher roster can be listed with an optional `status` filter, and fetching a single publisher also lazily applies the deal-expiry sweep to that publisher's deals before responding.

Suspension is the exchange's emergency brake on supply. When an `ExchangeAdmin` suspends an `ACTIVE` publisher, its `status` becomes `SUSPENDED`; accrual continues for auctions already recorded, but new package creation is blocked. The suspension then cascades: every package of that publisher currently `ACTIVE` moves to `PAUSED` with its `version` incremented, and every deal on those packages currently `ACTIVE` moves to `PAUSED` with its own `version` incremented. Resuming a `SUSPENDED` publisher returns it to `ACTIVE` and flips each of its `PAUSED` packages back to `ACTIVE`, recomputing their floors against the current date — but, deliberately, deals are not resumed by the cascade; each deal remains `PAUSED` until its owning manager resumes it individually.

Demand partners are registered by an `ExchangeAdmin` with a display `name`, a `seat_id` that must be unique across all demand partners — a duplicate is rejected with `ERR_DUPLICATE_SEAT` — and two capacity knobs: `max_qps`, the maximum number of auctions the partner may participate in per UTC second across all of its deals, and `daily_cap_micros`, the maximum gross spend it may accrue per UTC day. Both must be at least 1. A new partner starts `ACTIVE` with `spend_today_micros`, `current_second_auction_count`, and `lifetime_spend_micros` all at zero; the roster is listable with an optional `status` filter. Capacity can be retuned later through an optimistic-concurrency-guarded edit that may change `name`, `max_qps`, or `daily_cap_micros` and increments the partner's `version`.

A partner's standing is managed through three states. Suspending moves an `ACTIVE` or `THROTTLED` partner to `SUSPENDED`, which excludes it from deal candidacy and from being named on any newly created deal. Reactivation returns a `THROTTLED` or `SUSPENDED` partner to `ACTIVE`; coming back from `THROTTLED` resets its `current_second_auction_count` to zero, while coming back from `SUSPENDED` recomputes `spend_today_micros` for the current UTC date. Asking to reactivate a partner that is already `ACTIVE` is rejected with `ERR_PARTNER_NOT_RESUMABLE`. The third standing, `THROTTLED`, is never set directly by an operator — it is the system's own sanction, described with the auction pipeline in §3.5.

### 3.2. Packaging Inventory, Seasonal Pricing, and Supply-Path Declaration

A `PublisherManager` creates an inventory package for their own publisher — the package's `publisher_id` is taken from the caller's `X-User-ID`, never from the request body — by supplying a `name`, a dominant `ad_format` of `DISPLAY`, `VIDEO`, `NATIVE`, or `AUDIO`, a non-empty array of `category_tags` used later by brand-safety category rules, and a `base_floor_cpm_micros` above zero. If the caller's publisher is `SUSPENDED`, creation is rejected with `ERR_PUBLISHER_SUSPENDED`. Packages start `ACTIVE`, and the package's `active_deal_count` tracks how many of its deals are live; packages can be listed filtered by `publisher_id` or `status`.

Every package carries two derived pricing fields. `current_seasonal_multiplier_bps` is the `multiplier_bps` of whichever seasonal pricing window covers the logical clock's current UTC date, or the neutral 10,000 basis points when no window covers it. `effective_floor_cpm_micros` is the package's `base_floor_cpm_micros` multiplied by `current_seasonal_multiplier_bps` and divided by 10,000, rounded half-up to integer micros. This effective floor is recomputed whenever the package is created or edited, whenever a seasonal window is created or deleted, whenever the clock crosses a UTC date boundary, and on every read of the package.

A seasonal pricing window is created on a package the caller owns, with a `package_id`, a descriptive `name` such as a holiday label, an inclusive `start_date`, an inclusive `end_date` that must fall on or after the start, and a `multiplier_bps` between 1 and 100,000 — that is, from one-hundredth of the base floor up to ten times it. Two windows on the same package may not overlap as closed intervals: a new window is rejected with `ERR_SEASONAL_WINDOW_OVERLAP` when its `start_date` falls on or before an existing window's `end_date` while that existing window's `start_date` falls on or before the new window's `end_date`; strict adjacency, where one window begins the day after the other ends, is allowed. Each window exposes `is_currently_applied`, true exactly when the logical clock's current UTC date falls within its inclusive bounds. Creating or deleting a window that covers the current date immediately recomputes the package's multiplier and effective floor, incrementing the package's `version` when the multiplier actually changes; windows are listable by `package_id`, and deletion is restricted to the owning manager.

The supply path is declared as an append-only chain of hops. Appending a node to a package the caller owns records the `seller_domain` of the seller or reseller at that hop and the `fee_bps` that hop takes — between 0 and 9,000 basis points of the amount entering the hop. The first hop omits `parent_node_id` and receives `hop_index` zero. Every subsequent append must name the chain's current tail in `parent_node_id`: a node of the same package whose `is_tail` is still true. Naming anything else — a mid-chain node, a node of another package, a node that is already a parent — is rejected with `ERR_SUPPLY_CHAIN_NOT_TAIL`, and the append atomically flips the parent's `is_tail` to false while the new node takes `hop_index` one greater than its parent's. The chain is capped at ten hops; an append that would exceed that depth, or a `fee_bps` above the 9,000-basis-point ceiling, is rejected with `ERR_SUPPLY_CHAIN_TOO_DEEP`. Chains are never edited or deleted — there is no update or removal capability for nodes — so the declared path is a permanent, auditable record; nodes can be listed filtered by `package_id` or `parent_node_id`.

### 3.3. The Deal Lifecycle: Drafting, Review, Renegotiation, and Expiry

A deal binds one package to one buying seat. A `PublisherManager` creates a deal on a package they own by supplying the `package_id`, the `demand_partner_id` of the single buying seat, a `deal_type` of `PMP_STANDARD`, `PMP_EXCLUSIVE`, `PREFERRED`, or `PROGRAMMATIC_GUARANTEED`, an `auction_type` of `FIRST_PRICE` or `SECOND_PRICE`, a deal-level `floor_cpm_micros` above zero, and a flight window from `start_at` inclusive to `end_at` exclusive, where the end must be strictly after the start. The deal's `publisher_id` is derived from the package at creation, and its `is_exclusive` flag is computed — true for `PMP_EXCLUSIVE` and `PROGRAMMATIC_GUARANTEED` deals, false otherwise. Deals can be listed filtered by `package_id`, `publisher_id`, `demand_partner_id`, or `status`, and both the listing and the single-deal read apply the lazy expiry sweep before responding.

Programmatic-guaranteed deals carry a delivery obligation. `committed_impressions` is required and must be greater than zero exactly when `deal_type` is `PROGRAMMATIC_GUARANTEED`, and is forbidden on every other deal type; violating either direction is rejected with `ERR_PG_COMMITMENT_MISMATCH`. As guaranteed impressions deliver, `delivered_impressions` accumulates and `remaining_committed_impressions` tracks the difference between the commitment and what has delivered; both are null-free machinery only on guaranteed deals — `remaining_committed_impressions` is null on every other deal type.

While a deal is in `DRAFT` or `RENEGOTIATING`, its owning manager may edit its commercial terms — `floor_cpm_micros`, `start_at`, `end_at`, `committed_impressions` — through the version-guarded edit described in §2.7, which increments the deal's `version`. The edit re-checks the guaranteed-commitment rule, and additionally forbids lowering `committed_impressions` below the impressions already delivered, again with `ERR_PG_COMMITMENT_MISMATCH`. Once a deal has been approved at least once, `auction_type` and `deal_type` are immutable; an edit attempting to change them, or any edit outside `DRAFT` and `RENEGOTIATING`, is rejected with `ERR_DEAL_NOT_EDITABLE`.

Review follows a strict gate. Submission by the owning manager moves a deal from `DRAFT` — or, in the renegotiation loop, from `RENEGOTIATING` — to `PENDING_REVIEW`, and is permitted only while the package, the publisher, and the demand partner are all `ACTIVE`; a suspended publisher surfaces `ERR_PUBLISHER_SUSPENDED`, a non-active package `ERR_PACKAGE_NOT_ACTIVE`, and a non-active partner `ERR_PARTNER_NOT_ACTIVE`. An `ExchangeAdmin` then approves or rejects. Approval moves the deal to `ACTIVE` under the same three-way liveness check and, critically, pins `approved_floor_cpm_micros` to the greater of the package's `effective_floor_cpm_micros` at that moment and the deal's own `floor_cpm_micros`; this pinned floor governs auctions thereafter, even if the package's live floor later moves. Blocklists never gate approval — category entries gate deal eligibility at auction selection time and advertiser-domain entries gate bids at clearing time. Rejection returns the deal to `DRAFT`.

Live deals can be paused and renegotiated. Pausing — by the owning manager, by an `ExchangeAdmin`, or by the suspension cascade — moves an `ACTIVE` deal to `PAUSED` and excludes it from auction eligibility. Resuming is the owning manager's action and requires the package, publisher, and partner all `ACTIVE`, plus the logical clock inside the flight window; a resume attempted when the clock is outside the window from `start_at` to `end_at` is rejected with `ERR_DEAL_WINDOW_CLOSED`, and the deal must instead be expired. A successful resume re-pins `approved_floor_cpm_micros` to the greater of the package's current effective floor and the deal's floor. Renegotiation sends an `ACTIVE` deal back to `RENEGOTIATING`, increments `renegotiation_count` by one, and clears `approved_floor_cpm_micros` to null until the next approval; the cycle `RENEGOTIATING` → `PENDING_REVIEW` → `ACTIVE` then replays the same gates. Finally, when the logical clock reaches `end_at`, an `ACTIVE` deal transitions to `EXPIRED` — lazily on any touch of the deal and eagerly on clock sweeps. `EXPIRED` is terminal: the deal's commercial terms become immutable and it never leaves that state.

### 3.4. Brand Safety and Blocklist Enforcement

Brand safety is enforced through blocklist entries, each pairing a `rule_type` — `ADVERTISER_DOMAIN` to block a specific creative domain, or `CATEGORY` to block any package carrying a matching category tag — with the `value` to match. Scope decides where the rule bites. An `EXCHANGE`-scoped entry applies marketplace-wide and carries neither a `publisher_id` nor a `deal_id`. A `PUBLISHER`-scoped entry carries exactly a `publisher_id` and applies to everything that publisher serves. A `DEAL`-scoped entry carries exactly a `deal_id` and applies only to that deal. Mixing these reference fields wrong is rejected with `ERR_BLOCKLIST_SCOPE_MISMATCH`. An `ExchangeAdmin` may create entries of any scope; a `PublisherManager` may create `PUBLISHER`-scoped entries only against their own publisher and `DEAL`-scoped entries only against their own deals. Entries can be listed filtered by `scope`, `publisher_id`, `deal_id`, or `status`.

Enforcement is split deliberately across the auction pipeline. `CATEGORY` entries gate deal eligibility during selection: a deal is ineligible while any `ACTIVE` category entry's `value` appears among its package's `category_tags` at a matching scope. `ADVERTISER_DOMAIN` entries gate bids at clearing time: any bid whose `creative_domain` is blocked for the deal simply does not compete. Lifting is the one-way deactivation of an entry — an `ExchangeAdmin` moves it from `ACTIVE` to `LIFTED`, after which it no longer gates anything and historical auction records stand unchanged. A lifted entry can never return to `ACTIVE`; attempting to lift it again is rejected with `ERR_ENTRY_ALREADY_LIFTED`, and reinstating the rule means creating a fresh entry.

### 3.5. Executing Auctions: Throttles, Selection, and Clearing

The auction is the exchange's hot path, driven by a `DemandSide` caller. The request names a `publisher_id` — the supply side of this impression opportunity — and carries a `bids` array, which must be non-empty, each bid carrying a positive `bid_cpm_micros`, a positive `impression_count`, and a non-empty `creative_domain`. The response reports an `outcome` of fill or no-fill, the `auction_record` when the auction fills, and a `throttled_deal_count` reporting how many candidate deals were excluded from this request purely by the per-second capacity gate. A no-fill creates nothing, consumes nothing, and is never an error: no record, no counter movement, no throttle.

Before any deal competes, capacity gates run per demand partner. For each partner with live deals on the requested publisher, that partner's candidate deals are walked in a deterministic order — lowest `approved_floor_cpm_micros` first, then earliest `start_at`, then earliest `created_at` — and the k-th candidate in that order participates only if the partner's `current_second_auction_count` plus k is at most its `max_qps`. A position exactly equal to `max_qps` is allowed; one beyond it is throttled. The budget gate is evaluated once per request per partner: if the partner's `spend_today_micros` has already reached its `daily_cap_micros` — exactly at the cap blocks, one micro below it does not — none of that partner's candidates participate, and the partner transitions from `ACTIVE` to `THROTTLED` for budget reasons. If any candidate is excluded purely by the per-second gate, the partner transitions to `THROTTLED` for capacity reasons after the auction completes; the current auction still runs with the admitted candidates.

Deal selection then ranks every eligible deal of the requested publisher. A deal is eligible only when all of the following hold: the deal is `ACTIVE`; the logical clock is at or after its `start_at` and before its `end_at`; its package, publisher, and demand partner are all `ACTIVE`; the deal's `publisher_id` matches the request's `publisher_id`; a `PROGRAMMATIC_GUARANTEED` deal still has `remaining_committed_impressions` greater than zero; and no `ACTIVE` `CATEGORY` blocklist entry at exchange, publisher, or deal scope names a value found in the package's `category_tags`. Eligible deals are ranked exclusive-first — `is_exclusive` deals ahead of non-exclusive ones — then by higher `approved_floor_cpm_micros`, then by earlier `start_at`, then by earlier `created_at`. The winner is the first deal in that ranking whose clearing evaluation over the request's bids produces a winner; if no deal fills, the outcome is a no-fill.

Clearing a deal against the bids runs in five steps. First, brand safety drops every bid whose `creative_domain` is blocked for this deal by any `ACTIVE` `ADVERTISER_DOMAIN` entry at exchange, publisher, or deal scope; dropped bids produce no errors and simply do not compete. Second, eligibility keeps only bids whose `bid_cpm_micros` is at least the deal's pinned `approved_floor_cpm_micros` — the pinned floor, not the package's live effective floor, governs here. Third, the winner is the highest eligible bid; ties break toward fewer `impression_count` first, and any remaining tie breaks toward the bid appearing earliest in the request array. If no bid is eligible, the deal does not fill. Fourth, the clearing price depends on the deal's `auction_type`: a `FIRST_PRICE` deal clears at exactly the winning bid, recorded as `winning_bid_cpm_micros` and `clearing_cpm_micros` alike; a `SECOND_PRICE` deal clears at the greater of the pinned floor and the second-highest eligible bid plus 1,000 micros — a tenth-of-a-cent step above the runner-up — and when the winner is the only eligible bid, the clearing price is simply the pinned floor. Fifth, the money: `gross_micros` is the `clearing_cpm_micros` multiplied by the winning bid's `impressions` and divided by 1,000, rounded half-up to integer micros.

A filled auction writes an `AuctionRecord` that snapshots the deal's `deal_id`, `publisher_id`, `demand_partner_id`, and `auction_type`, carries the winning bid's `winning_bid_cpm_micros`, `impressions`, and `creative_domain` alongside the computed `clearing_cpm_micros`, and then prices three fee layers in a pinned order. The exchange fee comes first and is marginal across three slabs of the record's `gross_micros`: the first 5,000,000 micros — five dollars — are charged at 1,500 basis points, any portion above that up to 20,000,000 micros is charged at 1,000 basis points, and any portion above 20,000,000 micros is charged at 500 basis points, with each slab individually rounded half-up and the rounded slabs summed into `exchange_fee_micros`. The supply-path fee then walks the deal's package chain head-first by ascending `hop_index`, applied to what remains after the exchange fee: each hop's fee is the current remainder multiplied by that hop's `fee_bps` and divided by 10,000, rounded half-up, and the remainder shrinks by that fee before the next hop; the per-hop fees sum into `supply_fee_micros`, an empty chain charges nothing, and `publisher_net_micros` is what is left — `gross_micros` minus `exchange_fee_micros` minus `supply_fee_micros`, exactly the final remainder. The DSP's bill is computed last and independently: `dsp_fee_micros` is `gross_micros` at a 1,000-basis-point markup rounded half-up, and `dsp_billed_micros` is the gross plus that fee. The buy-side billed view and the sell-side net view are never expected to equal each other; reconciliation, described in §3.7, compares impressions and billed-versus-gross, never billed-versus-net. A fresh record's `dsp_confirmed_at` is null, `voided` is false, and `voided_at` is null.

A fill also moves the marketplace's counters. The partner's `current_second_auction_count` increments by one, and its `spend_today_micros` and `lifetime_spend_micros` each grow by the record's `gross_micros`. The deal's `delivered_impressions` grows by the record's `impressions`, recomputing `remaining_committed_impressions` on guaranteed deals. The publisher's `lifetime_net_micros` and `accrued_open_micros` recompute to absorb the new net revenue.

### 3.6. Billing Confirmation, Voids, and Fraud Correction

After a fill, the DSP side confirms its bill. Confirmation by a `DemandSide` caller stamps `dsp_confirmed_at` with the current logical time; confirming a record that is already confirmed is rejected with `ERR_ALREADY_CONFIRMED`. Confirmation is intentionally weightless on the ledger: it changes nothing about `lifetime_net_micros` or `spend_today_micros` — it only moves amounts between the unconfirmed and confirmed buckets that drive payout eligibility in §3.8. Auction records can be listed filtered by `deal_id`, `publisher_id`, `demand_partner_id`, or `voided`.

Voiding is the fraud-correction path, reserved to `ExchangeAdmin`. A void stamps `voided` true and `voided_at` with the logical time; voiding an already-voided record is rejected with `ERR_ALREADY_VOIDED`. The one hard wall is settled money: if the record's creation UTC date falls inside the period of a `SETTLED` payout batch, the void is rejected with `ERR_VOID_AFTER_SETTLEMENT`, because that money has already flowed. A record covered by a batch that has not yet settled, or by no batch at all, may be voided freely, and the void reverses everything the fill created: the partner's `lifetime_spend_micros` shrinks by the record's `gross_micros`, its `spend_today_micros` shrinks when the record was created on the current UTC date, the deal's `delivered_impressions` shrinks with the guaranteed remainder recomputed, and the publisher's `lifetime_net_micros` and `accrued_open_micros` recompute downward.

### 3.7. Discrepancy Reporting and Reconciliation

DSPs and the exchange count the same traffic differently, so reconciliation is a standing workflow rather than an exception. An `ExchangeAdmin` or `FinanceOfficer` generates a reconciliation report by naming a `deal_id` and a comparison window from `period_start` inclusive to `period_end` exclusive, where the end must be strictly after the start. The report aggregates two deliberately different populations of the deal's non-voided auction records. The SSP set collects records whose `created_at` UTC date falls inside the window: their impressions sum into `ssp_impressions` and their gross into `ssp_spend_micros`. The DSP set collects records whose `dsp_confirmed_at` UTC date falls inside the window — confirmed records only: their impressions sum into `dsp_impressions` and their billed amounts into `dsp_billed_micros`. Because the two sets are sliced on different clocks, identical traffic can yield a nonzero discrepancy purely from confirmation timing; surfacing exactly that is the report's purpose.

The headline figure, `discrepancy_pct`, is the absolute difference between `ssp_impressions` and `dsp_impressions`, multiplied by 100, divided by `ssp_impressions` — or by 1 when `ssp_impressions` is zero — and rounded half-up to three decimal places. When the discrepancy is strictly greater than 2.000 percent, the report is `auto_flagged` and is born directly in `DISPUTED`; otherwise it opens in `OPEN`. From `OPEN`, an `ExchangeAdmin` or `FinanceOfficer` acknowledges it to `ACKNOWLEDGED`; from `ACKNOWLEDGED` it can be escalated to `DISPUTED`, converging with the auto-flagged path. Reports can be listed filtered by `deal_id` or `status`.

Resolution closes the loop from any of `OPEN`, `ACKNOWLEDGED`, or `DISPUTED`. The resolver supplies a `resolution_type`: `ACCEPT_SSP` trusts the exchange's counts, `ACCEPT_DSP` trusts the buyer's, and `MAKE_GOOD` grants the publisher a credit. A make-good requires `adjustment_micros` greater than zero; the two accept resolutions forbid it outright — mixing these up is rejected with `ERR_RECONCILIATION_INPUT_MISMATCH`. Resolution stamps `resolved_at` with the logical time and moves the report to the terminal `RESOLVED`; any attempt to acknowledge, dispute, or resolve a resolved report is rejected with `ERR_REPORT_ALREADY_TERMINAL`. A make-good's `adjustment_micros` is immediately added to the publisher's `accrued_open_micros` and flows forward into the next payout line that covers that publisher and an overlapping period, as §3.8 details.

### 3.8. Publisher Payouts: Batches, Lines, and Settlement

Payouts run on a period cadence. A `FinanceOfficer` opens a payout batch by supplying `period_start` and `period_end`, the window from the start date inclusive to the end date exclusive, with the end strictly after the start. The batch is born in `DRAFT`, remembers its creator in `created_by_user_id`, and starts with `line_count`, `total_gross_micros`, and `total_payable_micros` all at zero. Batches can be listed filtered by `status`.

Submitting the batch is what materializes the money. The batch must be in `DRAFT`, else `ERR_BATCH_NOT_SUBMITTABLE`. Submission first checks period exclusivity: no other batch whose period overlaps this one as a half-open interval — one's `period_start` falling before the other's `period_end` while the other's `period_start` falls before the one's `period_end` — may exist outside `DRAFT`, and a conflict is rejected with `ERR_PAYOUT_PERIOD_OVERLAP`; batches sharing an exact boundary date do not conflict, and rejected batches never block anyone because they return to `DRAFT` with their lines deleted. Submission then generates one payout line per publisher that has at least one non-voided auction record created inside the window; every generated line records the `batch_id` of its parent batch and the `publisher_id` it pays. Each line aggregates that publisher's in-window records: `gross_micros` sums their `publisher_net_micros`; `confirmed_micros` is the portion of that gross coming from records whose `dsp_confirmed_at` is set; `unconfirmed_micros` is the remainder; and `adjustment_micros` sums the `adjustment_micros` of the publisher's `RESOLVED` make-good reports whose own windows overlap the batch window, applied in report creation order with ties broken by earlier report period start. The payable amount then depends on the publisher's `payment_terms`: under `SEQUENTIAL_LIABILITY`, `payable_micros` is `confirmed_micros` plus `adjustment_micros` — the exchange pays only what DSPs have confirmed, plus any make-goods; under `GUARANTEED`, `payable_micros` is `gross_micros` plus `adjustment_micros` — the exchange stands behind the full recorded amount. Every line starts `PENDING`, and lines for `GUARANTEED` publishers promote immediately to `ELIGIBLE` at generation. The batch's aggregates recompute from the lines: `line_count` counts them, `total_gross_micros` sums their gross, and `total_payable_micros` sums the payable of lines in `PENDING`, `HELD`, or `ELIGIBLE`.

Approval enforces segregation of duties. An `ExchangeAdmin` approves a batch in `PENDING_APPROVAL` — any other state draws `ERR_BATCH_NOT_PENDING_APPROVAL` — but the approver's `X-User-ID` must differ from the batch's `created_by_user_id`; the person who built the batch may not approve it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Rejection returns the batch to `DRAFT`, deletes every generated line, and resets all three aggregates to zero, forming a revision loop with submission.

Release is the point of no return, executed by a `FinanceOfficer` on an `APPROVED` batch — anything earlier draws `ERR_BATCH_NOT_APPROVED`. Release runs in two steps. First, every line still `PENDING` has its payable basis re-evaluated at that moment: sequential-liability lines whose DSP confirmations have since arrived, lifting `payable_micros` above zero, promote to `ELIGIBLE`; a sequential line with nothing confirmed stays `PENDING`. Second, every `ELIGIBLE` line is paid: it transitions to `PAID`, snapshots `payable_micros` into `paid_micros`, adds that amount to the publisher's `paid_out_micros`, and recomputes the publisher's `accrued_open_micros`. Lines still `PENDING` or `HELD` pass through untouched. The batch itself moves to `RELEASED` and then immediately to the terminal `SETTLED`; even a batch that generated zero lines settles. A batch's lines are listable beneath it, filterable by `status`, and a publisher-level statement lists every line for one publisher across all batches, likewise filterable by `status`.

Finance retains two levers over individual lines while a batch is pending or approved, and one after settlement. Holding moves a `PENDING` line to `HELD` — allowed only while the parent batch is in `PENDING_APPROVAL` or `APPROVED`, and rejected with `ERR_LINE_NOT_PENDING` on any other line state — which excludes the line from the release sweep and recomputes the batch's payable total. Releasing the hold returns a `HELD` line to circulation, rejected with `ERR_LINE_NOT_HELD` on anything not held: a guaranteed publisher's line, or any line whose `payable_micros` is above zero, goes back to `ELIGIBLE`, while a sequential-liability line with nothing payable falls back to `PENDING` instead. After the batch has settled, the unpaid remainder is closed out by write-off: the batch must be `SETTLED` — otherwise `ERR_BATCH_NOT_SETTLED` — the line must be `PENDING` or `HELD` — anything else draws `ERR_LINE_NOT_WRITABLE_OFF` — and a non-empty `write_off_reason` is mandatory. The write-off snapshots the line's `payable_micros` into `written_off_amount_micros` — zero when nothing was payable — moves the line to `WRITTEN_OFF`, adds the amount to the publisher's `written_off_micros`, and recomputes `accrued_open_micros`, keeping the conservation invariant of §2.10 intact across the reversal.

Transparency closes the loop back to supply. A per-package fee report answers with the package's declared `chain` ordered by ascending `hop_index`, its `non_voided_record_count` across all of its deals, and the summed `total_gross_micros`, `total_exchange_fee_micros`, `total_supply_fee_micros`, and `total_publisher_net_micros` over those records — letting a publisher verify exactly what each hop and the exchange kept. A per-deal records listing gives the reverse reachability from a deal to its auction history.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition posts, billing confirmations, voids, and the auction execution — return `200 OK`; the auction endpoint returns 200 whether or not the auction fills. Deleting a seasonal window returns `204 No Content` with an empty body. Reads return `200 OK`. "Any" in the role column means any authenticated role, reflecting the shared read access granted to all four roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires time-based sweeps | ExchangeAdmin |
| POST | `/publishers` | Register a publisher | ExchangeAdmin |
| GET | `/publishers` | List publishers | Any |
| GET | `/publishers/{publisherId}` | Get a publisher (lazy deal-expiry sweep applies) | Any |
| POST | `/publishers/{publisherId}/suspend` | Suspend a publisher; cascades to packages then deals | ExchangeAdmin |
| POST | `/publishers/{publisherId}/resume` | Resume a publisher and its packages (deals stay paused) | ExchangeAdmin |
| GET | `/publishers/{id}/payout-lines` | Publisher statement: all payout lines across batches | Any |
| POST | `/packages` | Create an inventory package for the caller's publisher | PublisherManager |
| GET | `/packages` | List packages | Any |
| GET | `/packages/{packageId}` | Get a package (floor recomputed on read) | Any |
| PUT | `/packages/{packageId}` | Edit a package (OCC on package version) | PublisherManager |
| POST | `/packages/{packageId}/pause` | Pause a package; cascades to its active deals | PublisherManager |
| POST | `/packages/{packageId}/resume` | Resume a package | PublisherManager |
| GET | `/packages/{packageId}/fee-report` | Supply-path and fee transparency report for a package | Any |
| POST | `/seasonal-windows` | Create a seasonal pricing window on an owned package | PublisherManager |
| GET | `/seasonal-windows` | List seasonal windows | Any |
| GET | `/seasonal-windows/{windowId}` | Get a seasonal window | Any |
| DELETE | `/seasonal-windows/{windowId}` | Delete a seasonal window (owner only) | PublisherManager |
| POST | `/demand-partners` | Register a demand partner (DSP seat) | ExchangeAdmin |
| GET | `/demand-partners` | List demand partners | Any |
| GET | `/demand-partners/{demandPartnerId}` | Get a demand partner | Any |
| PUT | `/demand-partners/{demandPartnerId}` | Retune partner capacity (OCC on partner version) | ExchangeAdmin |
| POST | `/demand-partners/{demandPartnerId}/suspend` | Suspend a partner | ExchangeAdmin |
| POST | `/demand-partners/{demandPartnerId}/reactivate` | Reactivate a throttled or suspended partner | ExchangeAdmin |
| POST | `/deals` | Create a deal on an owned package | PublisherManager |
| GET | `/deals` | List deals (lazy expiry sweep applies) | Any |
| GET | `/deals/{dealId}` | Get a deal (lazy expiry sweep applies) | Any |
| PUT | `/deals/{dealId}` | Edit deal commercial terms while DRAFT or RENEGOTIATING (OCC) | PublisherManager |
| POST | `/deals/{dealId}/submit` | Submit a deal for review from DRAFT or RENEGOTIATING | PublisherManager |
| POST | `/deals/{dealId}/approve` | Approve a deal; pins the approved floor | ExchangeAdmin |
| POST | `/deals/{dealId}/reject` | Reject a deal back to DRAFT | ExchangeAdmin |
| POST | `/deals/{dealId}/renegotiate` | Send an active deal into renegotiation | PublisherManager |
| POST | `/deals/{dealId}/pause` | Pause an active deal | PublisherManager, ExchangeAdmin |
| POST | `/deals/{dealId}/resume` | Resume a paused deal; re-pins the approved floor | PublisherManager |
| GET | `/deals/{id}/records` | List auction records of a deal | Any |
| POST | `/supply-chain-nodes` | Append a hop to a package's supply chain (append-only) | PublisherManager |
| GET | `/supply-chain-nodes` | List supply chain nodes | Any |
| GET | `/supply-chain-nodes/{nodeId}` | Get a supply chain node | Any |
| POST | `/blocklist-entries` | Create a brand-safety blocklist entry | ExchangeAdmin, PublisherManager |
| GET | `/blocklist-entries` | List blocklist entries | Any |
| GET | `/blocklist-entries/{entryId}` | Get a blocklist entry | Any |
| POST | `/blocklist-entries/{entryId}/lift` | Lift (deactivate) a blocklist entry | ExchangeAdmin |
| POST | `/auctions/execute` | Run one auction for a publisher's supply against a bids array | DemandSide |
| GET | `/auction-records` | List auction records | Any |
| GET | `/auction-records/{recordId}` | Get an auction record | Any |
| POST | `/auction-records/{recordId}/confirm-billing` | DSP confirms billing for a record | DemandSide |
| POST | `/auction-records/{recordId}/void` | Void an auction record (fraud correction) | ExchangeAdmin |
| POST | `/reconciliation-reports` | Generate a DSP-vs-SSP discrepancy report for a deal | ExchangeAdmin, FinanceOfficer |
| GET | `/reconciliation-reports` | List reconciliation reports | Any |
| GET | `/reconciliation-reports/{reportId}` | Get a reconciliation report | Any |
| POST | `/reconciliation-reports/{reportId}/acknowledge` | Acknowledge an OPEN report | ExchangeAdmin, FinanceOfficer |
| POST | `/reconciliation-reports/{reportId}/dispute` | Move an ACKNOWLEDGED report into DISPUTED | ExchangeAdmin, FinanceOfficer |
| POST | `/reconciliation-reports/{reportId}/resolve` | Resolve a report from any non-terminal state | ExchangeAdmin, FinanceOfficer |
| POST | `/payout-batches` | Create a payout batch shell for a period | FinanceOfficer |
| GET | `/payout-batches` | List payout batches | Any |
| GET | `/payout-batches/{batchId}` | Get a payout batch | Any |
| POST | `/payout-batches/{batchId}/submit` | Submit a batch: generates lines, checks period overlap | FinanceOfficer |
| POST | `/payout-batches/{batchId}/approve` | Approve a batch (approver must differ from creator) | ExchangeAdmin |
| POST | `/payout-batches/{batchId}/reject` | Reject a batch back to DRAFT; deletes generated lines | ExchangeAdmin |
| POST | `/payout-batches/{batchId}/release` | Release a batch: pays eligible lines, then settles | FinanceOfficer |
| GET | `/payout-batches/{id}/lines` | List a batch's payout lines | Any |
| POST | `/payout-batches/{batchId}/lines/{lineId}/hold` | Hold a PENDING line | FinanceOfficer |
| POST | `/payout-batches/{batchId}/lines/{lineId}/release-hold` | Release a held line back to ELIGIBLE or PENDING | FinanceOfficer |
| POST | `/payout-batches/{batchId}/lines/{lineId}/write-off` | Write off an unpaid line of a SETTLED batch | FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_BLOCKLIST_SCOPE_MISMATCH` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_PG_COMMITMENT_MISMATCH` | 422 |
| `ERR_RECONCILIATION_INPUT_MISMATCH` | 422 |
| `ERR_SUPPLY_CHAIN_TOO_DEEP` | 422 |
| `ERR_DUPLICATE_SEAT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PUBLISHER_SUSPENDED` | 409 |
| `ERR_PACKAGE_NOT_ACTIVE` | 409 |
| `ERR_PARTNER_NOT_ACTIVE` | 409 |
| `ERR_DEAL_NOT_EDITABLE` | 409 |
| `ERR_DEAL_WINDOW_CLOSED` | 409 |
| `ERR_ALREADY_CONFIRMED` | 409 |
| `ERR_ALREADY_VOIDED` | 409 |
| `ERR_VOID_AFTER_SETTLEMENT` | 409 |
| `ERR_REPORT_ALREADY_TERMINAL` | 409 |
| `ERR_BATCH_NOT_SUBMITTABLE` | 409 |
| `ERR_BATCH_NOT_PENDING_APPROVAL` | 409 |
| `ERR_BATCH_NOT_APPROVED` | 409 |
| `ERR_BATCH_NOT_SETTLED` | 409 |
| `ERR_LINE_NOT_PENDING` | 409 |
| `ERR_LINE_NOT_HELD` | 409 |
| `ERR_LINE_NOT_WRITABLE_OFF` | 409 |
| `ERR_ENTRY_ALREADY_LIFTED` | 409 |
| `ERR_PARTNER_NOT_RESUMABLE` | 409 |
| `ERR_SEASONAL_WINDOW_OVERLAP` | 409 |
| `ERR_PAYOUT_PERIOD_OVERLAP` | 409 |
| `ERR_SUPPLY_CHAIN_NOT_TAIL` | 409 |
| `ERR_STALE_VERSION` | 412 |
